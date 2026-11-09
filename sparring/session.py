"""Live session: translates the human's buttons (panel events) into `Game` calls and projects
the bot's decisions onto the TTS table. All I/O goes through `TTSClient.call_lua` (request and response).

Principios
  * The table rules. The bot's hand is read from its seat; its deck is the multiset of 30 cards minus what has
    been seen (order unknown); drawing and discarding are physical operations confirmed by reading the table. If the
    table and the engine permanently disagree (the human moved a bot card, a piece will not move...), after
    `adopt_after` consecutive failures, or with Cancel, the engine adopts what the table shows.
  * Of the human only what is in their discard pile and the size of their hand is known; nothing is invented. What
    the engine cannot know (damage or healing from effects) comes in through the HP and Remove buttons.
  * Pieces are identified by GUID, never by name.
  * Reveal validates before touching anything: an illegal card leaves the combat pending.
  * The state is saved after every button (`state_path`) and can be resumed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import persist
from .ai_medusa import GAZE, MedusaAI, play_signature
from .cards import Card, can_be_boost
from .controller import Controller
from .combat_flow import CombatFlow, PendingChoice, Phase, legacy_chooser
from .effects import events, narrate, ongoing
from .effects import table as fx_table
from .effects.choose import ControllerChooser
from .effects.run import EffectRun
from .game_log import GameLog
from . import session_boost as boost_session
from . import session_bot_effects as bot_effects
from . import session_blind as blind
from . import session_choices as choices
from . import session_effects as human_effects
from . import session_gadget as gadget_token
from . import session_hidden as hidden
from . import session_moves as moves
from . import session_pieces as piece_id
from . import session_peek as peek
from . import session_order as order_cards
from . import session_jill as jill_decks      # noqa: F401  (registers the translators of Jill Trent's deck reveals)
from . import session_pile as pile
from . import session_reveal as reveal
from . import session_source as source_dial
from . import session_sleight as sleight
from . import session_translators as translators
from .session_choices import panel_text
from .spaces import describe, zone_text
from .combat import FEINT, GLANCE_DAMAGE, can_boost, deck_boost, is_medusa_card, scheme_gain_actions
from .effects.model import EffectError, load_effects
from .effects.modifiers import boost_limit, grants_boost, has_boost_effect
from .state import ANUNG, DETECTIVE, EXHAUST_DAMAGE, Fighter, Game, RuleError
from .table_prep import DISCARD_ZONE_KEYS, ZoneSpawn
from .tts import lua, ui
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind
from .tts.client import TTSClient, TTSLuaError
from . import i18n
from .i18n import plural, t, tn
from .tts.ui import Event


NUMBER_TAGS = {2: "scheme.number.two", 3: "scheme.number.three"}      # how many effects a scheme makes you pick, in the chat


class SessionError(Exception):
    """The table is not as the engine expected (a card that is not there, a discard pile that does not match...)."""


TABLE_ERRORS = (SessionError, TTSLuaError, OSError)      # TimeoutError es un OSError
RESTART_WINDOW = 3.0   # seconds to confirm Restart game with a second press
COMPOSITE_OVERHEAD = 12_000   # what the snapshot and the frame of a composite take up, besides its operations
TRANSIT_READS = 4   # discard reads to wait for a card the human just played before giving it up as lost
DEAL_FLIGHT = 3.0   # seconds after the bot deals cards to the human during which a card read in their discard zone may be one still flying to the hand


class Msg(str):
    """Bot message: a `str` that also carries its category, to colour it in the chat without bothering whoever treats it as text."""
    kind: ChatKind
    shown: bool

    def __new__(cls, text: str, kind: ChatKind = ChatKind.NEUTRAL, shown: bool = False) -> "Msg":
        obj = super().__new__(cls, text)
        obj.kind = ChatKind(kind)
        obj.shown = shown          # already on the table's chat (a scene sent it in its own script): not broadcast again
        return obj


# category of each bot action in `_action_text`; the attack does not go through there (`_bot_continue` says it)
ACTION_KIND = {"maneuver": ChatKind.MOVE, "glance": ChatKind.SCHEME, "frenzy": ChatKind.SCHEME, "scheme": ChatKind.SCHEME}


CODED_ABILITY_HERO = "medusa"     # the hero whose start-of-turn ability the engine runs (`Game.use_ability(..., "medusa_gaze")`)
HOLD_MARGIN = 2.0           # seconds on top of a composite's hold for the reply to arrive
DEFAULT_ONGOING_HOLD = 1.5    # seconds of the bot's ping on a human ONGOING scheme that left play, before it moves it (tests use 0)
DEFAULT_WILDFIRE_HOLD = 3.0   # seconds the bot leaves its Wildfire card face up on the discard before applying it (tests use 0)
DEFAULT_ACTION_ANNOUNCE_HOLD = 2.0    # seconds between the chat line that says what the bot is about to do and the table writes (tests use 0)
DEFAULT_BOT_PAUSE = 1.0     # seconds between bot actions in the real game (tests use 0)


@dataclass
class SessionConfig:
    bot_seat: str
    human_seat: str
    nicknames: dict[str, str]                    # fid -> name for the messages (pieces go by GUID)
    bot_card_spot: tuple[float, float, float]    # where the bot leaves its face-down card (world)
    human_card_spot: tuple[float, float]         # (x, z) where the human leaves theirs
    bot_discard_spot: tuple[float, float, float]  # origin of the bot's discard grid (first slot)
    bot_discard_zone: str                        # GUID of the scripting ZONE over the bot's discard pile
    bot_deck_guid: str                           # GUID of the bot's physical deck
    human_discard_zone: str                      # GUID of the scripting ZONE over the human's discard pile
    bot_deck_spot: tuple[float, float]           # (x, z) of the deck: the last card is left loose and is only found this way
    pieces: dict[str, str | list[str]]           # fid -> miniature GUID, or several if it changes state
    reveal_radius: float = 2.0
    rot_y: float = 0.0
    settle_tries: int = 6          # table reads before a card move is given up as failed
    settle_wait: float = 0.4       # seconds between reads (0 in tests)
    dials: dict[str, str] = field(default_factory=dict)   # fid -> GUID of the life dial (optional: only warns)
    off_board_dist: float = 4.0    # a piece farther than this from its nearest space is not on the board
    adopt_after: int = 3           # consecutive table failures after which what the table shows is adopted
    bot_discard_step: tuple[float, float] = (-3.6, 2.2)   # (column dx, row dz) between discard slots
    bot_discard_rows: int = 15     # slots per column before moving to the next
    bot_discard_rot_y: float = 90.0
    deck_clear: float = 3.0        # slots closer than this to the draw deck are skipped
    human_deck_guid: str | None = None            # the human's draw deck (may be inside their zone)
    human_deck_spot: tuple[float, float] | None = None
    bot_deck_zone: str | None = None              # optional Scripting zone over each deck: the deck is searched ONLY inside it
    human_deck_zone: str | None = None
    deck_radius: float = lua.DECK_RADIUS          # without a zone: nearest face-down deck/card this close to the deck spot
    bot_deck_hint: str | None = None              # GUID the start-up read found for each deck (TTS re-forms decks with a new one)
    human_deck_hint: str | None = None
    deck_exclude_radius: float = 1.5              # whatever is this close to a deck is not discard
    start_spaces: dict[str, int] = field(default_factory=dict)   # hero fid -> its real starting space
    bot_discard_bounds: tuple[float, float, float, float, float] | None = None   # (cx, cz, size x, z, rotY) of the zone
    setup: bool = False            # set the game up (hand, mulligan, place pieces) before playing
    mulligan_bot: bool = True      # the bot may change its opening hand once if it is bad (house rule)
    mulligan_human: bool = True    # the human has the Mulligan button during setup (house rule)
    destiny_dial: str | None = None   # GUID of the destiny dial (count of Hellboy's destinies in his discard)
    source_dial: str | None = None    # GUID of the Source dial (count of Ciri's Source cards in her discard: session_source)
    dead_spot: tuple[float, float, float] | None = None   # where the bot sets aside the miniatures of ITS fallen
    discard_layer: float = 0.15    # height added per full turn of the discard grid
    batch: bool = False            # fast mode: reads from the snapshot and writes in a single script per step
    human_dead_spot: tuple[float, float, float] | None = None   # where the bot sets aside the human's FALLEN miniatures
    label_font: float = lua.LABEL_FONT   # size of the floor labels' text
    bot_pause: float = 0.0         # seconds of pause after each bot action (0 = none; `play` uses 1.0)
    wildfire_hold: float = 0.0     # seconds the Wildfire card stays face up on the bot's discard before its effect (0 = no scene; `play` uses 3.0)
    action_announce_hold: float = 0.0   # seconds between announcing a bot action in the chat and writing it on the table (0 = say it after, as before; `play` uses 2.0)
    ongoing_hold: float = 0.0      # seconds the bot's ping on a human ONGOING scheme that left play lasts before it moves it (0 = no pause; `play` uses 1.5)
    live_ui: bool = False          # status line, buttons by state and on-screen announcements in the same script
    bot_card_ids: tuple[int, int] = lua.BOT_CARD_IDS         # CardID range of the bot's deck (of its hero: data/tts)
    human_card_ids: tuple[int, int] = lua.HUMAN_CARD_IDS     # and of the human's deck
    bot_card_shift: int = 0        # how far TTS moved each deck's CardIDs from the data's (it renumbers a repeated DeckID); already in the ranges
    human_card_shift: int = 0
    deck_identity: dict[str, tuple] = field(default_factory=dict)   # "bot"/"human" -> (FaceURL, BackURL) pairs from data/tts
    bot_label: str = "MEDUSA"      # name of each side on the floor labels (its hero's)
    human_label: str = "HELLBOY"
    look_spot: tuple[float, float, float] = (-23.0, 2.5, 0.0)   # center of the row of the bot's hand in view (estimate: calibrate live)
    look_step: tuple[float, float] = (0.0, 2.6)                 # (dx, dz) between cards of the row
    bot_row_spot: tuple[float, float, float] = (11.5, 2.5, -29.0)   # center of the row of the bot's hand the human's cards look at (next to its combat and ONGOING zones)
    bot_row_step: tuple[float, float] = (0.0, 2.6)              # (dx, dz) between cards of that row
    order_by_hand: bool = True                                   # the human orders the bot's top cards on the table (session_order); False: panel buttons
    order_spot: tuple[float, float, float] = (-10.5, 2.5, 22.5)   # center of the row where the bot lays its top cards for the human to order (estimate: calibrate live)
    order_step: tuple[float, float] = (0.0, 3.4)                 # (dx, dz) between cards of that row
    look_rot_y: float | None = None                              # turn of the row's cards (default: the bot discard's)
    token_spot: tuple[float, float, float] | None = None         # where the bot lays its active ability tokens (Abe); default: beside its deck
    bot_ongoing_spot: tuple[float, float, float] | None = None   # ONGOING zone below each combat zone (E2, Ivan): the bot lays its
    human_ongoing_spot: tuple[float, float] | None = None        # ONGOING scheme there; the human leaves theirs (recognized there)
    bot_tuck_spot: tuple[float, float, float] | None = None      # where the bot tucks its inventions (Donatello); outside its discard zone
    bot_removed_spot: tuple[float, float, float] | None = None   # where the bot sets aside the cards it removes from the game
    card_zoom: bool = False                                      # big copy of the cards the human must read (`play` turns it on)
    card_zoom_seconds: float = 6.0                               # how long the copy stays
    card_zoom_scale: float = 4.0                                 # size factor of the copy
    card_zoom_spot: tuple[float, float, float] = (0.0, 12.0, 0.0)   # where it floats: above the board centre, outside every zone
    card_zoom_rot: tuple[float, float, float] | None = None      # (x, y, z) degrees; default flat, readable from the human's seat
    reveal_display: bool = True                                  # revealed cards are laid large on the table until the human dismisses them (Ivan, 2026-11-08)
    reveal_spot: tuple[float, float, float] = (0.0, 14.0, 0.0)   # centre of the row: above the zoom copy, over the board centre (estimate: calibrate live)
    reveal_scale: float = 2.5                                    # size factor of each copy (the zoom's 4 is too wide for a row of three)
    reveal_step: float = 6.2                                     # distance between neighbouring copies along z
    zone_spawns: dict[str, ZoneSpawn] = field(default_factory=dict)   # discard zone key -> transform to create / straighten it with
    remove_plan: tuple[tuple[str, str], ...] = ()   # (GUID, expected object name) of the loose objects destroyed at a fresh start
    remove_limits: tuple[float, float] = (26.0, 36.0)   # |x|, |z| of the central table rectangle they must lie in


def zoom_spec(cfg: "SessionConfig") -> lua.ZoomSpec | None:
    """The big copy of a card the bot shows the human (None when `card_zoom` is off)."""
    if not cfg.card_zoom:
        return None
    rot = cfg.card_zoom_rot
    if rot is None:
        rot = (0.0, cfg.look_rot_y if cfg.look_rot_y is not None else cfg.bot_discard_rot_y, 0.0)
    return lua.ZoomSpec(cfg.card_zoom_spot, rot, cfg.card_zoom_scale, cfg.card_zoom_seconds)


FALLEN_STEP = 1.5


def fallen_slot(spot: tuple[float, float, float], mine: bool, slot: int) -> tuple[float, float, float]:
    """Where the `slot`-th fallen piece of a side lies: the row grows from the dead spot toward the centre of the table
    (the dead spots sit at the edge of "Clean table"'s area, so growing outward would leave pieces it cannot reach)."""
    return (spot[0] + (-FALLEN_STEP if mine else FALLEN_STEP) * slot, spot[1], spot[2])


def human_dead_spot(cfg: "SessionConfig") -> tuple[float, float, float] | None:
    """The human's fallen zone: the configured one or, by default, the bot's mirrored to the other side of the table
    (off the board, next to their seat)."""
    if cfg.human_dead_spot is not None:
        return cfg.human_dead_spot
    if cfg.dead_spot is not None:
        return (-cfg.dead_spot[0], cfg.dead_spot[1], cfg.dead_spot[2])
    return None


def piece_guids(value) -> list[str]:
    """GUID of a miniature: one, or several if it changes state (each state is another object with another GUID)."""
    guids = [value] if isinstance(value, str) else value
    if not isinstance(guids, (list, tuple)) or not guids or not all(isinstance(g, str) for g in guids):
        raise ValueError(t("cfg.piece_guid", value=value))
    return list(guids)


def deck_where(zone: str | None, spot, radius: float) -> str:
    """Where a deck is looked for, for the messages: the zone, or the spot and radius."""
    if zone:
        return t("deck.where.zone", zone=zone)
    return t("deck.where.spot", x=f"{float(spot[0]):g}", z=f"{float(spot[1]):g}", r=f"{radius:g}") if spot else t("deck.where.guid")


# configuration keys that identify the table and the game (fine settings do not count)
INTUITION = "intuition"                 # Abe Sapien's ability counter (two tokens)
TOKEN_NICKNAMES = {"intuition": "Intuition Token"}   # tokens that rest in several places or are split off a stack: found by nickname
INTUITION_TOKEN = TOKEN_NICKNAMES["intuition"]      # nickname of those tokens on the table (data/tts/abe-sapien.json, stack 5a17e9)

IDENTITY_KEYS = ("destiny_dial", "bot_seat", "human_seat", "bot_deck_guid", "bot_discard_zone", "human_discard_zone",
                 "human_deck_guid", "start_spaces", "dials")


class HumanProxy(Controller):
    """The human decides on the table: when the engine forces them to discard, the bot announces it and waits."""

    human = True

    def __init__(self, owe):
        self.owe = owe

    def take_turn(self, game: Game) -> None:
        pass

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        self.owe(n, reason)
        return []


class _Op:
    """A write to the table. In fast mode it waits in the queue until something needs its result (or the table)."""
    __slots__ = ("session", "script", "domain", "value", "error", "done", "seen")

    def __init__(self, session: "Session", script: str, domain: str):
        self.session, self.script, self.domain = session, script, domain
        self.value, self.error, self.done, self.seen = None, None, False, False

    @property
    def result(self):
        if not self.done:
            self.session._flush()
        self.seen = True
        if self.error is not None:
            raise self.error
        return self.value


class _Timed:
    """Counts the messages to TTS and the time of a button or a bot action (`--timing`)."""

    def __init__(self, session: "Session", label: str):
        self.session, self.label = session, label

    def __enter__(self):
        if self.session._depth == 0:
            self.session._epoch += 1
        self.session._depth += 1
        self.calls0 = getattr(self.session.client, "calls", 0)
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.session._depth -= 1
        calls = getattr(self.session.client, "calls", 0) - self.calls0
        took = time.monotonic() - self.t0
        self.session.cost_log.append((self.label, calls, took))
        if self.session.timing is not None:
            self.session.timing(t("console.timing", line=t("timing.line", label=self.label, calls=calls, ms=took * 1000)))
        return False


# with the bot's hand in view only what resolves it is attended to (or does not touch it: HP, remove, value)
CHOICE_EVENTS = (Event.CHOICE, Event.CANCEL, Event.LOOK_PING, Event.HP, Event.REMOVE, Event.VALUE, Event.RESTART,
                Event.NEW_GAME)
ABILITY_EVENTS = (Event.END_ACTION, Event.HP, Event.REMOVE, Event.RESTART, Event.NEW_GAME)   # while your start-of-turn ability waits
GATE_EVENTS = (Event.END_ACTION, Event.HP, Event.REMOVE, Event.RESTART, Event.NEW_GAME)    # while the combat waits for a step of your hand
LOOK_EVENTS = (Event.LOOK_PING, Event.CHOICE, Event.CANCEL, Event.END_ACTION, Event.HP, Event.REMOVE, Event.VALUE,
               Event.RESTART, Event.NEW_GAME)
CARD_TYPE_TAGS = {"attack": "look.type.attack", "defense": "look.type.defense", "versatile": "look.type.versatile", "scheme": "look.type.scheme"}

SNAP_KEYS = ("bot_hand", "human_count", "bot_discard", "human_discard", "face_bot", "face_human", "pieces", "dials")
_COMBAT_KEYS = ("flip", "human_guid", "bot_seen", "alive_before", "before", "boost")   # Pending.combat (see _resolve_combat)


def _bot_snapshot(saved: dict) -> dict[str, tuple[int | None, bool]]:
    """`Pending.combat["before"]` as `_snapshot_bot` returns it (JSON turned its tuples into lists)."""
    return {fid: (v[0], v[1]) for fid, v in saved.items()}


@dataclass
class Pending:
    kind: str                    # human_attacks | bot_attacks
    attacker: Fighter
    target: Fighter
    bot_card: Card | None        # the bot's defense (human_attacks) or the bot's attack (bot_attacks)
    bot_card_guid: str | None = None
    cancel_failures: int = 0
    defended: bool = True        # False: the human attacks and the bot has not yet decided or placed its defense (done at Reveal)
    wait: PendingChoice | None = None   # cards already revealed, unresolved: waits for the human's BOOST (extra: guid, baseline, hand, stuck)
    flow: CombatFlow | None = None      # the combat itself, stopped at a decision of the human's card effect (E1)
    combat: dict | None = None          # what finishing that combat still needs (flip, human_guid, bot_seen, alive_before, before, boost)
    prediction: dict | None = None      # Perfect Shot: {"value": int | None} once the attacker decided (None value: face down)
    predict: dict | None = None         # Perfect Shot: the human's prediction request, while the panel asks it (E3)
    declared: dict | None = None        # the `attacked` event of the human's attack was raised before the bot's defense (E3):
                                        # {"counters": the bot's ability counters before it}, so the token projection sees the spend

    @property
    def boost_wait(self) -> dict | None:
        """Flat save form of `wait` (read-only: mutate `wait` itself, e.g. `wait.extra["stuck"] = True`)."""
        return None if self.wait is None else self.wait.to_dict()


class Session:
    def __init__(self, game: Game, client: TTSClient, ai: MedusaAI, cfg: SessionConfig, bot: int = 0):
        self.game, self.client, self.ai, self.cfg = game, client, ai, cfg
        self.bot, self.human = bot, 1 - bot
        game.controllers[self.bot] = ai
        game.controllers[self.human] = HumanProxy(self._owe_discard)
        self.pending: Pending | None = None
        self.pending_discard: dict | None = None
        self.free_effect: EffectRun | None = None   # an effect outside any combat, stopped at a decision of the human
        self.choice_ui = choices.ChoiceUI()      # page and picks of the choice being answered (not saved)
        self.look_granted = False                # a card lets the human look at the bot's hand (the button shows only then)
        self._look_epoch: int | None = None      # button (`_epoch`) that granted the look: that button never revokes it
        self._blocks_told: set[str] = set()      # restrictions already explained in the chat while they last
        self.look_fails = 0                      # row closings the table did not do (the second Cancel forces the exit)
        self.look: dict | None = None            # the bot's hand in view: {"ids", "guids", "spots"} of the table's row
        self.pending_value = 0
        self.token_copies: dict[str, list[str]] = {}   # ability token -> GUIDs of the active copies on the table (D3)
        self.fx_unprojected: dict | None = None       # bot_effects snapshot taken before the turn change, projected at the bot's first write
        self.fx_in_flight: set[int] = set()           # CardIDs a bot effect is moving off its pile or hand in this step
        self.hand_discarded: set[int] = set()         # CardIDs the bot moved from the human's hand to their pile in this step (Crown Of Flame): nothing left to ask
        self.hand_deck: set[int] = set()              # CardIDs the human put from their discard into their deck by hand (session_pile): not moved again
        self.hand_moved: dict[str, int] = {}          # fid -> space the human put a miniature on by hand (session_moves): not projected again
        self.boost_note: dict | None = None                   # what the bot's Maneuver boost card drew and gained (`_note_boost`)
        self.fx_looked = False                        # a look_hand re-identified the human's virtual hand in this step
        self.reveal_bot_hand = False                  # a card of the human looked at the bot's hand in this step (E3)
        self.peek: dict | None = None                 # the bot's top card face up in the row, while the human decides (The future of Ninjutsu)
        self.order_row: dict | None = None            # the bot's top cards face up on the table, while the human orders them by hand (session_order)
        self.peek_pins: dict[str, list[int]] = {"top": [], "bottom": []}     # cards the human left on top / put at the bottom of the bot's deck: its engine order
        self._attach_choosers()
        self.chosen_attacker: str | None = None
        self.moving = False
        self.bot_discarded: set[int] = set()
        self.messages: list[Msg] = []
        self.game_log = GameLog()                # no file until play() points it next to the state file
        self._destiny_tried = False
        self.dials_written: dict[str, int] = {}  # dial GUID -> last value the engine wrote and verified
        self.dirty = False                       # the engine moved the bot and the table does not reflect it yet
        self.unprojected: dict | None = None     # previous positions of pieces not yet projected
        self.bot_stage: str | None = None        # "start": bot turn begun in the engine, I/O pending
        self.first_turn_pending = False          # the new game's first start-of-turn triggers have not fired yet
        self.start_line: str | None = None      # what the bot Hellboy start-of-turn trigger (ANUNG or DETECTIVE) did, said before the first write
        self.wildfire_scene: dict | None = None  # what the bot's Wildfire did at the turn change, shown at its first write
        self.said_returns: set[int] = set()      # cards whose return to the bot's hand the Wildfire scene already announced
        self.limit_waived = False
        self.flush_failures = 0                  # consecutive table failures (SessionError) while settling the debt
        self.state_path: Path | None = None      # if set, saved after every start/resume/handle
        self.game_id = uuid.uuid4().hex          # identifies this game in the save
        self.setup: dict | None = None                      # state machine of the setup (persisted)
        self.first_mode: str | None = None                  # "random" | "human" | "bot": how who goes first was chosen
        self.dial_debt = False                              # a dial could not be written during the bot's turn
        self.over_shown = False                            # the game-over dialog went out
        self.zoom_ids: set[int] = set()                    # bot cards the next discard write shows as a big copy
        self.reveal_shown = False                          # big copies of revealed cards lie on the table: "Stop revealing" shows (session_reveal)
        self.scheme_baseline: list[int] | None = None      # human's discard when pressing Scheme: waits for their card
        self.maneuver_baseline: list[int] | None = None    # their discard at Maneuver: a BOOST 0 card put there is warned
        self.maneuver_boosted: int | None = None           # the card this Maneuver was boosted with (once; its effects already ran)
        self._deal_at = -1e9                                # when cards were last dealt to the human (they may still be flying to their hand)
        self.ability_wait: str | None = None               # the human's start-of-turn ability to do on the table before anything else (E2)
        self._attack_announced: tuple | None = None     # the bot attack already said before its card went down (a retry stays quiet)
        self.declared_carry: dict | None = None            # a cancelled attack already declared (UNCANNY INTUITION spent): the same attack again does not re-spend
        self.destiny_seen: tuple[int, str] | None = None   # (destinies, form) already written and verified on the dial
        self.source_seen: int | None = None                # Source already written and verified on Ciri's dial
        self._transit: dict[int, int] = {}                 # CardID played by the human -> reads it has gone without reaching the discard
        self.combat_guids: dict[int, str] = {}             # CardID of the human's card at the combat spot -> its GUID (Relentless moves it)
        self._intuition_said: int | None = None            # the human Abe's active tokens already told in chat
        self._gadget_shown: int | None = None              # the gadget Jill Trent's token was last put at (None: not placed yet this game)
        self._gadget_missing_said = False                  # the missing token was already told in chat
        self._gadget_failed_said = False                   # the failed write of the token was already told in chat
        self._destiny_said: tuple[int, str] | None = None  # what was already announced (not repeated while retrying)
        self.placing: dict | None = None         # bot card put on the table whose reply never arrived
        self.dials_attempted: dict[str, int] = {}  # GUID -> last value tried to write (verified or not)
        self._warned: set[tuple[str, str]] = set()
        self._deck_qty = -1                                 # cards in the human's draw deck at the last read
        self._deal_check: tuple[int, int, int] | None = None  # (hand, cards, discard) of the human when dealing them cards
        self.human_dealt = 0                                # human draws (`Game.drawn`) already dealt or taken as done (saved)
        self._epoch = 0                                     # number of the button attended (to confirm discard removals)
        self._wild_credit: tuple[int, int, int] = (-1, -1, 0)  # Wildfire: (turn, button, extra cards in your hand unexplained)
        self._gone: dict[int, int] = {}                     # CardID missing from the table's discard -> button on which it was seen
        self._depth = 0                                     # >0 while a button, the start or a resume is being attended
        self._restart_at: float | None = None               # instant of the first tap on Restart game
        self._new_game_at: float | None = None              # instant of the first tap on New game
        self.back_to_gate = False                           # set by a confirmed New game: the run loop ends and play() returns to the gate
        self.can_regate = True                              # False when the pre-game gate is off: New game has nowhere to go back to
        self.cost_log: list[tuple[str, int, float]] = []   # (what, messages to TTS, seconds) per button and per action
        self.snap: dict | None = None                       # current table snapshot (fast mode)
        self._trusted = False                               # the snapshot comes from the click: no need to re-read to confirm
        self._queue: list[_Op] = []                         # writes pending for the composite script
        self._expect_hand: tuple[str, int] | None = None
        self._dials_pending: set[str] = set()               # dials with a write still to be checked
        self._post: list[Callable[[], bool]] = []           # checks that wait for the button's closing
        self._snap_spec: lua.SnapSpec | None = None
        self.configured_pieces = {fid: piece_guids(v) for fid, v in cfg.pieces.items()}   # as the data gives them (identity of the table)
        self._deck_origin: dict[str, str] = {}              # "bot_deck_guid"/"human_deck_guid" -> the configured GUID, for each one adopted
        self._saved_decks: dict[str, str] = {}               # side -> live deck GUID read from session.json (first candidate on resume)
        self._zone_origin: dict[str, str] = {}              # "bot_discard_zone"/"human_discard_zone" -> the configured GUID, for each one created or replaced
        self._saved_zones: dict[str, str] = {}              # zone key -> live GUID read from session.json (first candidate on resume)
        self.prep_removed = 0                                   # loose objects the last table preparation destroyed
        self._startup_notes: list[tuple[str, ChatKind]] = []   # what the table preparation did: said by the start / resume
        self._dial_origin: dict[str, str] = {}              # fid -> the dial GUID the data gave it, for each one resolved by name
        self.resolved_dials: dict[str, str] = {}            # fid -> life dial GUID found by name when two dials shared one (saved)
        self._dial_unresolved: set[str] = set()             # fids whose dial cannot be told from another's: not written, not verified
        self._dial_notes_said: set[str] = set()
        self._dials_resolved = False                        # the shared dials were looked at since start / resume / adopt
        self.resolved_pieces: dict[str, list[str]] = {}     # fid -> GUIDs found by name when the configured one held another piece (saved)
        self._piece_notes: list[str] = []                   # what the resolution has to tell the player
        self._piece_gave_up: set[str] = set()               # fids whose piece was looked for by name once, in vain
        self._resolving = False
        self._piece_full_check = False                      # the next table read also looks for a piece missing at its GUID
        self._write_seq = 0                                 # last table write sent (the composite seals it)
        self._deck_ident: dict[str, tuple] = {}             # "bot"/"human" -> (FaceURL, BackURL) pairs of its deck
        self._saved_ident: dict[str, tuple] = {}            # the same, read from session.json (if the table does not answer)
        self.new_game: Callable[[], Game] | None = None     # factory of the new game on restart
        self.clock: Callable[[], float] = time.monotonic    # clock of the double press of Restart game
        self.timing: Callable[[str], None] | None = None    # --timing: one line per button and per bot action
        self.broadcast = cfg.live_ui
        for fid, space in cfg.start_spaces.items():
            if fid in game.fighters:
                game.start_spaces[game.fighters[fid].owner] = space

    # ---------- input ----------
    def _check_config(self) -> None:
        if (not isinstance(self.cfg.bot_deck_spot, (tuple, list)) or len(self.cfg.bot_deck_spot) != 2):
            raise SessionError(t("cfg.deck_spot_required"))
        if not 0 < self.cfg.deck_radius < self.cfg.deck_clear:        # a discard slot is deck_clear away: it must stay out of reach
            raise SessionError(t("cfg.deck_radius", radius=self.cfg.deck_radius, clear=self.cfg.deck_clear))
        missing = sorted(set(self.game.fighters) - set(self.cfg.pieces))
        if missing:
            raise SessionError(t("cfg.missing_pieces", ids=", ".join(missing)))
        bad = sorted(s for s in self.cfg.start_spaces.values() if s not in self.game.board.spaces)
        if bad:
            raise SessionError(t("cfg.bad_start_spaces", spaces=bad))
        if not self._grid_slots():
            raise SessionError(t("cfg.no_grid_slots"))

    def start(self) -> list[str]:
        with self._timed(t("timing.start")):
            return self._start()

    def _start(self) -> list[str]:
        """Starts the game. A table or connection failure does not kill it: it leaves the debt and retries with
        End action (if the bot starts, `bot_stage` is left half-done and resumable)."""
        self.snap = None
        self.messages = []
        self._say_startup_notes()
        self._destiny_tried = False
        self._begin_game()
        return self._done()

    def _preload_identities(self) -> None:
        if "bot" in self._deck_ident:
            return
        try:
            self.load_identities()
        except TABLE_ERRORS as e:
            self._table_failure(e)               # retried on first use: without identity no card is written
        for side, pairs in self._saved_ident.items():
            self._deck_ident.setdefault(side, pairs)

    def _begin_game(self) -> None:
        self.first_turn_pending = True            # built with `begin_turn(emit=False)`: see `_start_first_turn`
        self._intuition_said = None               # a restart keeps the old game's count otherwise
        self._gadget_shown = None
        self.game_log.new_game((self.game.hero_def(self.bot).name, self.game.hero_def(self.human).name))
        self.game_log.observe(self.game, self._name)
        self._check_config()
        self._check_pieces()
        self._preload_identities()
        self._announce_first()
        self._announce_bot_hero()
        if self.cfg.setup:
            self.setup = {"stage": "hand", "mull_done": False, "mull_decision": None, "mull_step": "start",
                          "human_mull": False}
            self._assign_start_spaces()
            self._persist()
            self._setup_advance()
            return
        if self.game.turn == self.bot:
            self.bot_stage = "start"
        self._open(announce_turn=True)
        self._track_intuition(announce=True)
        gadget_token.track(self)

    def _start_first_turn(self) -> None:
        """The first turn's start-of-turn triggers. The game was built with `begin_turn(emit=False)`: before the table
        was set (no pieces placed, no hands dealt) a Wildfire or an ANUNG UN RAMA would run in the engine only and
        never reach the table. They run here, once, when the game really begins; the bot's leave the same debt and
        Wildfire scene as any later turn (`start_bot_turn`). A table error before it does not lose it: the flag is
        saved and the bot's turn or the human's start fire it on the retry."""
        g = self.game
        if not self.first_turn_pending:
            return
        self.first_turn_pending = False
        if g.turn_no != 1:                        # a later turn change already fired its own triggers: never twice
            return
        if g.turn != self.bot:
            g.start_first_turn()
            return
        before, fx_before = self._snapshot_bot(), bot_effects.snapshot(self)
        probe = self._wildfire_probe()
        g.start_first_turn()
        self._turn_change_debt(before, fx_before)
        self.wildfire_scene = self._wildfire_outcome(probe)

    def _announce_first(self) -> None:
        if self.first_mode is None:
            return
        who = self._name(self.game.hero(self.game.turn))
        self.say(t("sess.first.random", who=who) if self.first_mode == "random"
                 else t("sess.first.forced", who=who, mode=self.first_mode))

    def _bot_ability_coded(self) -> bool:
        """Only Medusa's start-of-turn ability is DRIVEN by the engine (`Game.use_ability`, effects/driven.py: the bot
        picks a gaze target). Every other interpreted hero's ability runs as triggers inside the effects interpreter."""
        return self.game.hero_def(self.bot).slug == CODED_ABILITY_HERO

    def _announce_bot_hero(self) -> None:
        """A bot hero the effects interpreter does not run: its ability text is said and it is played by value and boost,
        breaking nothing. A hero the interpreter runs has its ability and cards coded, whatever `_bot_ability_coded` says."""
        hero = self.game.hero_def(self.bot)
        if not self._bot_ability_coded() and not self.game.fx.interprets(self.bot) and hero.ability:
            self.say(t("sess.hero_uncoded", name=hero.name, ability=hero.ability), ChatKind.ABILITY)

    def resume(self) -> list[str]:
        with self._timed(t("timing.resume")):
            return self._resume()

    def _resume(self) -> list[str]:
        """Resumes a game loaded from a save: the table rules (it is re-read) and it picks up where it left off."""
        self.snap = None
        self.messages = []
        reveal.clear(self, orphans=True)          # copies a run that died left on the table: none is shown to a resumed game
        self._say_startup_notes()
        self._destiny_tried = False
        self._check_config()
        self._check_pieces()
        self._preload_identities()
        self.game_log.resumed()
        self.game_log.observe(self.game, self._name)
        self.say(t("sess.resumed"))
        self._intuition_said = None
        self._gadget_shown = None
        if self.setup is not None:
            self.say(t("sess.resume.setup", stage=self.setup["stage"]))
            self._setup_advance()
            self._write_dials(post=True)
            return self._done()
        self._open(announce_turn=False)
        self._track_intuition(announce=True)
        gadget_token.track(self)
        self._write_dials(post=True)              # the table already shows the engine's life, not the one from before the cut
        if self.game.winner is not None:
            self.say(t("sess.resume.game_over", winner=self.game.winner))
        elif self.look is not None:
            self._w(lua.set_look_row(self._look_entries()), "misc")     # the panel variable does not survive a reload
            self.say(hidden.resume_prompt(self), ChatKind.YOUR_TURN)
        elif hidden.manual_request(self) is not None:
            hidden.manual_start(self, hidden.manual_request(self))
        elif moves.manual_request(self) is not None:
            self.choice_ui = choices.ChoiceUI()
            self.say(moves.reprompt(self, moves.manual_request(self)), ChatKind.YOUR_TURN)
        elif pile.manual_request(self) is not None:
            self.choice_ui = choices.ChoiceUI()
            self.say(pile.reprompt(self, pile.manual_request(self)), ChatKind.YOUR_TURN)
        elif order_cards.manual_request(self) is not None:
            self.choice_ui = choices.ChoiceUI()
            self.say(order_cards.remind(self), ChatKind.YOUR_TURN)
        elif self.effect_run is not None:
            self.choice_ui = choices.ChoiceUI()
            self.say(t("sess.resume.effect", prompt=choices.prompt_text(self.game, self.effect_run.awaiting)), ChatKind.YOUR_TURN)
            peek.remind(self)
        elif self._table_gate(self.pending):
            self.say(t("sess.resume.table_gate"), ChatKind.YOUR_TURN)
        elif self.pending is not None and self.pending.wait is not None:
            self.say(self._boost_prompt(self.pending), ChatKind.YOUR_TURN)
        elif self.pending is not None:
            self.say(t("sess.resume.combat"), ChatKind.YOUR_TURN)
        elif self.pending_discard is not None:
            self.say(t("sess.resume.discard"), ChatKind.YOUR_TURN)
        elif self.ability_wait is not None:
            self.say(t("sess.resume.ability", wait=self.ability_wait), ChatKind.YOUR_TURN)
        elif self.game.turn == self.human:
            self.say(t("sess.resume.turn", n=self.game.actions_left), ChatKind.YOUR_TURN)
            if self.moving:                       # their own action is still open: End action closes it
                self.say(t("sess.resume.after"), ChatKind.YOUR_TURN)
        elif self.moving:                         # the human's step after the bot's combat: End action closes it, then the bot goes on
            self.say(t("sess.resume.after"), ChatKind.YOUR_TURN)
        return self._done()

    def _open(self, announce_turn: bool) -> None:
        try:
            self._name_pieces()
            if announce_turn:
                self._setup_new_game()
            self.read_bot_hand()
            if announce_turn and self.dirty:
                self._flush_table()                  # deal of the opening hands
            self.sync_positions()
            self.sync_human()
            if announce_turn:
                self._start_first_turn()          # on the pieces just read, not on the engine's default spaces
            if self.game.turn == self.bot and self.pending is None and self.game.winner is None and not self.moving:
                self._bot_continue()
            elif announce_turn and self.game.turn == self.human:
                self._announce_human_start()
        except TABLE_ERRORS as e:
            self._table_failure(e)
            if self.game.turn == self.bot:
                self.say(t("sess.bot_retry_hint"), ChatKind.YOUR_TURN)

    def _setup_new_game(self) -> None:
        """Only when starting a new game: real starting spaces and opening hands."""
        if not self.cfg.start_spaces:
            for player in (self.bot, self.human):                 # unconfigured: they are where each hero starts
                info = self._table_pieces().get(self.game.hero(player).fid) or {}
                if self._on_board(info):
                    self.game.start_spaces[player] = info["space"]
        if not self._table_hand_ids():
            self.game.drawn[self.bot] = self.game.start_hand(self.bot)
            self.dirty = True
            self.say(t("sess.bot_deals", n=self.game.start_hand(self.bot)))
        self._deal_human_start()

    def _deal_human_start(self) -> None:
        """The human's opening hand: when their seat is empty the bot deals it from their deck (the human then decides
        the mulligan); without a human deck or on a failed deal they are told to draw what is missing themselves."""
        if self._rd_human_count(1) != 0:
            return
        n = self.game.start_hand(self.human)
        missing, _, _ = self._deal_human_hand(n, mulligan=False)
        if missing == 0:
            self.say(t("sess.deal_yours", n=n), ChatKind.YOUR_TURN)
        else:
            self.say(t("sess.draw_yours", n=missing), ChatKind.YOUR_TURN)

    def _deal_human_hand(self, n: int, mulligan: bool) -> tuple[int, bool, bool]:
        """Deals `n` cards from the human's deck to their seat; with `mulligan` first returns their hand to the deck and
        shuffles it. Returns `(missing, redo, unshuffled)`: `missing` is how many cards the human still has to draw by hand (0 when
        the hand is complete), `redo` is True when a mulligan did not happen (their hand was not returned, so they do
        it by hand) and `unshuffled` when the hand went back but the deck could not be shuffled. When
        the deal fails, the seat is read again, because the script may have run with its reply lost: only what is
        really missing is asked for. The engine's virtual hand is settled by the next read of the table."""
        c = self.cfg
        if not c.human_deck_guid:
            return n, mulligan, False
        returned = False
        try:
            kw, ident = self._deck_kw("human"), self._identity("human")
            if mulligan:
                back = self._w(lua.return_hand_to_deck(c.human_seat, c.human_deck_guid, c.human_card_ids, identity=ident,
                                                       **kw), "cards").result or {}
                if not back.get("deck"):
                    return self._human_missing(n), True, False
                returned = True
                if not self._settle(lambda: self._rd_human_count(1) == 0):
                    missing = self._human_missing(n)
                    return missing, missing < n, False       # a hand that never emptied: nothing was returned
                total = len(self.game.players[self.human].full_set)

                def shuffled() -> bool:
                    r = self._w(lua.shuffle_deck(c.human_deck_guid, id_range=c.human_card_ids, identity=ident, **kw),
                                "cards").result or {}
                    return bool(r.get("shuffled")) and r.get("quantity") == total
                if not self._settle(shuffled):
                    return self._human_missing(n), False, True
            dealt = (self._w(lua.deal_cards(c.human_deck_guid, n, c.human_seat, id_range=c.human_card_ids,
                                            identity=ident, **kw), "cards").result or {}).get("dealt")
        except TABLE_ERRORS:
            return self._human_missing(n), mulligan and not returned, False
        self.snap = None
        return (0, False, False) if dealt == n else (self._human_missing(n), False, False)

    def _human_missing(self, n: int) -> int:
        """Cards the human's seat lacks to have `n`, read again from the table (all of them if it cannot be read)."""
        self.snap = None
        try:
            return max(0, n - self._rd_human_count(0))
        except TABLE_ERRORS:
            return n

    # ---------- game setup: persisted state machine ----------
    # Stages (self.setup["stage"]): those the bot runs alone, and those waiting for the human (Ready button).
    #   hand -> mulligan -> [bot starts]    place_bot -> wait_human            -> begin
    #                       [human starts] wait_human_first -> place_bot -> begin
    # Who places first follows the turn: if the bot starts it places Medusa and the Harpies (with only its hand and the
    # known starting spaces) and then asks the human to place; if the human starts, the bot WAITS, reads
    # where Hellboy and Lobster were put and then places the Harpies taking those spaces into account.
    SETUP_AUTO = ("hand", "mulligan", "place_bot", "begin")

    def _assign_start_spaces(self) -> None:
        """Rulebook: the first player takes starting space 1 and the other 2 (unless explicitly configured).
        The engine's pieces are repositioned in their starting zone until they are really placed."""
        g = self.game
        if not self.cfg.start_spaces:
            first = g.turn
            g.start_spaces = {first: g.board.starts["1"], 1 - first: g.board.starts["2"]}
        taken: set[int] = set()
        for player in (self.bot, self.human):
            start = g.start_spaces[player]
            for f in sorted(g.own(player), key=lambda f: (not f.hero, f.fid)):    # only those on the board
                f.pos = g.board.nearest_free(start, taken, zone_of=start)
                taken.add(f.pos)

    def _setup_advance(self) -> None:
        """Advances the bot's stages up to one that waits for the human. Resumable: each stage is idempotent and is
        saved on finishing; a table failure leaves the stage where it was and Ready retries it."""
        try:
            while self.setup is not None and self.setup["stage"] in self.SETUP_AUTO:
                stage = self.setup["stage"]
                if stage == "hand":
                    self._setup_hand()
                    self.setup["stage"] = "mulligan"
                elif stage == "mulligan":
                    self._setup_mulligan()
                    self._require_bot_hand_matches()
                    self.setup["stage"] = "place_bot" if self.game.turn == self.bot else "wait_human_first"
                    if self.setup["stage"] == "wait_human_first":
                        self._setup_place_hero()
                        names, many = self._sidekick_names(), len(self._sidekicks()) > 1
                        tag = ("setup.first.several" if many else "setup.first.single") if names else "setup.first.alone"
                        self.say(t(tag, names=names, n=self.game.start_hand(self.human),
                                   zone=zone_text(self.game, self.game.start_spaces[self.human])),
                                 ChatKind.YOUR_TURN)
                elif stage == "place_bot":
                    self._require_bot_hand_matches()
                    self._setup_place()
                    if self.game.turn == self.bot:
                        self._setup_place_hero()
                        self.setup["stage"] = "wait_human"
                        names = self._sidekick_names()
                        n = self.game.start_hand(self.human)
                        self.say(t("setup.then.names", names=names, n=n, zone=zone_text(self.game, self.game.start_spaces[self.human]))
                                 if names else t("setup.then.alone", n=n), ChatKind.YOUR_TURN)
                    else:
                        self.setup["stage"] = "begin"
                elif stage == "begin":
                    self._setup_begin()
                    return
                self._persist()
        except TABLE_ERRORS as e:
            self._table_failure(e)
            self.say(t("setup.retry"), ChatKind.WARNING)

    def _setup_hand(self) -> None:
        self._name_pieces()
        if not self._table_hand_ids():
            self.game.drawn[self.bot] = self.game.start_hand(self.bot)
            self.dirty = True
            self.say(t("sess.bot_deals", n=self.game.start_hand(self.bot)))
        self.read_bot_hand()
        if self.dirty:
            self._flush_table()
        self._deal_human_start()

    def _setup_mulligan(self) -> None:
        """Once only: if the hand is bad, the 5 cards go back to the deck, it is shuffled and 5 new ones dealt.
        It is announced without saying which cards they were.

        Resumable: the decision is saved (`mull_decision`) before touching the table, because after returning the hand
        there is no hand left to evaluate, and each physical sub-step (`mull_step`) is saved on finishing. `mull_done`
        is only set when the table's hand matches the engine's again."""
        s, g = self.setup, self.game
        if s["mull_done"]:
            return
        who = self._name(g.hero(self.bot))
        if s.get("mull_decision") and not self.cfg.mulligan_bot:
            self._abandon_mulligan()
        if s.get("mull_decision") is None:
            self.read_bot_hand()
            s["mull_decision"] = bool(self.cfg.mulligan_bot and self.ai.should_mulligan(g, g.players[self.bot].hand))
            self._persist()
        if s["mull_decision"]:
            self._physical_mulligan()
            self.say(t("setup.mulligan_bot", who=who))
        else:
            self.say(t("setup.keep_bot", who=who))
        s["mull_done"] = True

    def _abandon_mulligan(self) -> None:
        """Resumed with mulligan_bot=false after a half-done physical mulligan: it is given up. The table rules; if
        the hand is empty 5 cards are dealt, and setup requires table and engine to match."""
        s, g = self.setup, self.game
        s["mull_decision"], s["mull_step"] = False, "start"
        self.read_bot_hand()
        if not self._table_hand_ids():
            g.drawn[self.bot] = self.game.start_hand(self.bot)
            self.read_bot_hand()
            self.dirty = True
        if self.dirty:
            self._flush_table()
        self._require_bot_hand_matches()
        self._persist()

    def _physical_mulligan(self) -> None:
        """return (returned) -> shuffle (shuffled) -> deal (dealt). Each step is noted when done; a cut or a
        failure leaves the step where it was and Ready retries it without repeating the previous ones."""
        c, g, s = self.cfg, self.game, self.setup
        step = s.setdefault("mull_step", "start")
        if step == "start":
            res = self._w(lua.return_hand_to_deck(c.bot_seat, c.bot_deck_guid, c.bot_card_ids, identity=self._identity(),
                                                       **self._deck_kw()), "cards").result or {}
            if not res.get("deck"):
                raise SessionError(t("err.mull_no_deck", where=self.deck_where()))
            if not self._settle(lambda: not self._table_hand_ids()):
                raise SessionError(t("err.mull_not_returned"))
            step = s["mull_step"] = "returned"
            self._persist()
        if step == "returned":
            total = len(g.players[self.bot].full_set)

            def shuffled() -> bool:
                r = self._w(lua.shuffle_deck(c.bot_deck_guid, id_range=c.bot_card_ids, identity=self._identity(),
                                                   **self._deck_kw()), "cards").result or {}
                return bool(r.get("shuffled")) and r.get("quantity") == total
            if not self._settle(shuffled):
                raise SessionError(t("err.shuffle", total=total))
            st = g.players[self.bot]
            st.hand, st.deck = [], [x for x in st.full_set if x not in st.discard]
            g.rng.shuffle(st.deck)
            g.drawn[self.bot] = 0
            g.draw(self.bot, self.game.start_hand(self.bot), log=False)
            self.dirty = True
            step = s["mull_step"] = "shuffled"
            self._persist()
        if step == "shuffled":
            self._flush_table()
            self._require_bot_hand_matches()
            s["mull_step"] = "dealt"

    def _require_bot_hand_matches(self) -> None:
        """Setup does not advance while the table's hand is not the engine's."""
        table = sorted(self._table_hand_ids())
        engine = sorted(c.card_id for c in self.game.players[self.bot].hand)
        if table != engine:
            raise SessionError(t("err.hand_mismatch", table=len(table), engine=len(engine)))

    def _setup_place(self) -> None:
        """Medusa and the Harpies are placed on the table with move_piece and verified by reading the table."""
        g = self.game
        self.sync_positions()                     # where Hellboy and Lobster really are (if already placed)
        plan = self.ai.choose_setup(g, g.players[self.bot].hand)
        pieces = self._table_pieces() if self.cfg.batch else None
        staged = []
        for fid, space in plan.items():
            g.fighters[fid].pos = space
            staged.append((fid, space, self._move_stage(fid, space, pieces)))
            if not self.cfg.batch and not staged[-1][2]():
                raise SessionError(t("err.move_piece", name=self._name(g.fighters[fid]), space=space))
        if self.cfg.batch:
            for fid, space, moved in staged:
                if not moved():
                    raise SessionError(t("err.move_piece", name=self._name(g.fighters[fid]), space=space))

        def placed() -> bool:
            pieces = self._table_pieces()
            return all((pieces.get(fid) or {}).get("found") and pieces[fid].get("space") == sp
                       for fid, sp in plan.items())
        if not self._settle(placed):
            raise SessionError(t("err.bot_pieces"))
        self.say(t("setup.bot_places", places="; ".join(t("setup.bot_place_item", name=self._name(g.fighters[fid]), zone=zone_text(g, sp))
                                                       for fid, sp in plan.items())))

    def _setup_place_hero(self) -> None:
        """The human's hero leaves from their starting space (fixed by the rulebook): the bot places it, verifies it
        on the table and announces it. The human only places their sidekick. Idempotent (`hero_placed` is persisted)."""
        s, g = self.setup, self.game
        if s.get("hero_placed"):
            return
        hero = g.hero(self.human)
        space = g.start_spaces[self.human]
        hero.pos = space
        if not self._move_piece(hero.fid, space):
            raise SessionError(t("err.move_piece", name=self._name(hero), space=space))

        def placed() -> bool:
            info = self._table_pieces().get(hero.fid) or {}
            return bool(info.get("found")) and info.get("space") == space
        if not self._settle(placed):
            raise SessionError(t("err.hero_not_at_start", name=self._name(hero)))
        s["hero_placed"] = True
        self.say(t("setup.bot_places_hero", name=self._name(hero), zone=zone_text(self.game, space)))

    def _setup_begin(self) -> None:
        g = self.game
        self.setup = None
        self.sync_human()
        self.say(t("setup.done"))
        self._intuition_said = None               # the setup's silent first look must not hide the starting count
        self._track_intuition(announce=True)
        gadget_token.track(self)
        self._start_first_turn()
        if g.turn == self.bot:
            self.bot_stage = "start"
            self._persist()
            self._bot_continue()
        else:
            self._persist()
            self._announce_human_start()

    def _ready(self, _: dict) -> None:
        """Ready button: the human finished placing (and drawing). It is checked on the table before going on."""
        s = self.setup
        if s is None:
            self.say(t("setup.none"), ChatKind.WARNING)
            return
        if s["stage"] in ("wait_human_first", "wait_human"):
            try:
                self._setup_place_hero()                 # if an earlier failure left it unplaced
            except TABLE_ERRORS as e:
                self._table_failure(e)
                return
            if not self._human_setup_ok():
                return
            s["stage"] = "place_bot" if s["stage"] == "wait_human_first" else "begin"
        self._setup_advance()

    def _human_mulligan(self, _: dict) -> None:
        """The human's Mulligan button: only during setup, once and before Ready. The bot returns their hand to their
        deck, shuffles and deals the new starting hand; without a human deck (or if the table fails) it tells them to
        do it by hand."""
        s = self.setup
        if s is None:
            self.say(t("setup.mull.only_setup"), ChatKind.WARNING)
        elif not self.cfg.mulligan_human:
            self.say(t("setup.mull.disabled"), ChatKind.WARNING)
        elif s["stage"] not in ("wait_human_first", "wait_human"):
            self.say(t("setup.mull.wait_bot"), ChatKind.WARNING)
        elif s.get("human_mull"):
            self.say(t("setup.mull.done", n=self.game.start_hand(self.human)), ChatKind.WARNING)
        else:
            n = self.game.start_hand(self.human)
            missing, redo, unshuffled = self._deal_human_hand(n, mulligan=True)
            s["human_mull"] = True
            side = bool(self._sidekicks())
            if missing == 0 and not redo:
                tag = "setup.mull.dealt.sidekick" if side else "setup.mull.dealt.plain"
            elif redo:
                tag = "setup.mull.go.sidekick" if side else "setup.mull.go.plain"
            else:
                tag = "setup.mull.unshuffled" if unshuffled else "setup.mull.partial"
            self.say(t(tag, n=n, missing=missing, names=self._sidekick_names()), ChatKind.YOUR_TURN)

    def _human_setup_ok(self) -> bool:
        g = self.game
        self.sync_positions()
        start = g.start_spaces[self.human]
        for fid, f in g.fighters.items():
            if f.owner != self.human:
                continue
            info = self._table_pieces().get(fid) or {}
            if not self._on_board(info) or not g.board.share_zone(start, info["space"]):
                self.say(t("setup.missing_piece", name=self._name(f), zone=zone_text(self.game, start)), ChatKind.WARNING)
                return False
        count = self._rd_human_count(0)
        if count == 0:
            self.say(t("setup.draw_first", n=self.game.start_hand(self.human)), ChatKind.WARNING)
            return False
        if count != self.game.start_hand(self.human):
            tag = "setup.mull_count" if (self.setup or {}).get("human_mull") else "setup.hand_count"
            self.say(t(tag, n=self.game.start_hand(self.human), count=count), ChatKind.WARNING)
            return False
        return True

    def _name_pieces(self) -> None:
        """Gives each miniature the name of its configuration key (Harpy 1/2/3...) to tell them apart with the
        mouse. By GUID; a failure does not matter to the game."""
        owners: dict[str, int] = {}
        for fid in self.cfg.pieces:
            for g in self._guids(fid):
                owners[g] = owners.get(g, 0) + 1
        # a GUID two fighters share is never renamed: it would rename one hero's miniature with the other's name
        # (session_pieces tells them apart by exactly that name)
        names = {g: self.cfg.nicknames[fid] for fid in self.cfg.pieces if fid in self.cfg.nicknames
                 for g in self._guids(fid) if owners[g] == 1}
        if not names:
            return
        try:
            self._w(lua.name_pieces(names), "misc")
        except (ValueError, *TABLE_ERRORS) as e:
            self.say(t("sess.name_pieces_warn", err=e), ChatKind.WARNING)

    def _say_triggers(self) -> None:
        for kind, line in self.game.fx.said:      # your triggers (Wildfire's return, your Pact at the end of a turn)
            self.say(t("sess.trigger.card" if kind == "card" else "sess.trigger.ability", line=line), ChatKind.ABILITY)
        self.game.fx.said.clear()

    def _done(self) -> list[str]:
        self._say_triggers()
        self._track_intuition()
        gadget_token.track(self)
        hidden.after_step(self)                   # a look of the human at the bot's hand: the row rides this script
        self._tell_blocks()
        self._commit()
        self._persist()
        self.snap = None                          # the table changes between buttons: the next one brings its own
        self.fx_in_flight = set()
        self.hand_deck = set()
        self.hand_discarded = set()
        self.game_log.observe(self.game, self._name)
        return self.messages

    def _table_failure(self, e: Exception) -> None:
        if isinstance(e, SessionError):
            self.say(t("sess.table_error", err=e), ChatKind.WARNING)
        elif isinstance(e, (TTSLuaError, TimeoutError)):
            self.say(t("sess.tts_odd", err=e), ChatKind.WARNING)
        else:
            self.say(t("sess.tts_down", err=e), ChatKind.WARNING)

    def handle(self, event: Event, payload: dict | None = None) -> list[str]:
        payload = dict(payload or {})
        self._take_snapshot(payload.pop("snapshot", None))
        self.messages = []
        self._destiny_tried = False
        with self._timed(t("timing.button", name=event.value)):
            return self._handle(event, payload)

    def _handle(self, event: Event, payload: dict) -> list[str]:
        if event is Event.STOP_REVEAL:            # dismissing the copies touches no game state: valid in every state
            reveal.stop(self)
            return self._done()
        table = {Event.MANEUVER: self._maneuver, Event.ATTACKER: self._choose_attacker, Event.ATTACK: self._attack,
                 Event.SCHEME: self._scheme, Event.REVEAL: self._reveal, Event.END_ACTION: self._end_action,
                 Event.VALUE: self._value, Event.CANCEL: self._cancel, Event.HP: self._hp,
                 Event.REMOVE: self._remove, Event.UNDO_GAME_OVER: self._undo_game_over, Event.READY: self._ready,
                 Event.MULLIGAN: self._human_mulligan, Event.RESTART: self._restart, Event.NEW_GAME: self._new_game,
                 Event.BOOST: self._boost, Event.NO_BOOST: self._no_boost, Event.MANEUVER_BOOST: self._maneuver_boost,
                 Event.LOOK: self._look_hand, Event.LOOK_PING: self._look_ping, Event.CHOICE: self._choice}
        if self.setup is not None and event not in (Event.READY, Event.HP, Event.REMOVE, Event.CANCEL, Event.VALUE,
                                                    Event.MULLIGAN, Event.RESTART, Event.NEW_GAME):
            self.say(t("sess.setting_up"), ChatKind.WARNING)
            return self._done()
        if self.look is not None and event not in LOOK_EVENTS:
            self.say(hidden.resume_prompt(self), ChatKind.WARNING)
            return self._done()
        if self._paused() is not None and event not in CHOICE_EVENTS:
            self.say(t("sess.effect_pending"), ChatKind.WARNING)
            return self._done()
        if self._table_gate(self.pending) and event not in GATE_EVENTS:
            self.say(t("sess.table_first"), ChatKind.WARNING)
            return self._done()
        if self.ability_wait is not None and event not in ABILITY_EVENTS:
            self.say(t("sess.ability_first", wait=self.ability_wait), ChatKind.WARNING)
            return self._done()
        if event is not Event.RESTART:
            self._restart_at = None               # any other button disarms the confirmation
        if event is not Event.NEW_GAME:
            self._new_game_at = None
        try:
            table[event](payload)
        except RuleError as e:
            self.say(t("sess.illegal", err=e), ChatKind.WARNING)
        except TABLE_ERRORS as e:
            self._table_failure(e)
        return self._done()

    def say(self, msg: str, kind: ChatKind = ChatKind.NEUTRAL, shown: bool = False) -> None:
        self.messages.append(Msg(msg, kind, shown))
        self.game_log.observe(self.game, self._name)      # the engine events up to this line, before the line itself
        self.game_log.chat(msg)

    def zoom(self) -> lua.ZoomSpec | None:
        return zoom_spec(self.cfg)

    def _game_over_dialog(self) -> None:
        """The verdict in the middle of the human's screen, once per game over (the chat line stays as it was)."""
        g = self.game
        if g.winner is None or self.over_shown or not self.cfg.live_ui:
            return
        self.over_shown = True
        loser = self._name(g.hero(1 - g.winner))
        text = t("game.over_dialog_win" if g.winner == self.human else "game.over_dialog_lose", loser=loser)
        try:
            self._w(lua.info_dialog(self.cfg.human_seat, " ".join(lua.ascii_text(text, lua.MAX_DIALOG_CHARS))), "misc")
        except (ValueError, TypeError) as e:
            self.say(t("sess.panel_prep_fail", err=e), ChatKind.WARNING)

    def _hold(self, seconds: float) -> None:
        """The one pause of the bot's table scenes: what is already queued goes out and stays on show `seconds`. In a
        batch the wait is inside the TTS script (`lua.hold`: no extra message, no snapshot of a half-done table),
        otherwise it is a sleep after the writes."""
        if seconds <= 0:
            return
        if self.cfg.batch:
            self._w(lua.hold(seconds), "misc")
        self._flush()
        if not self.cfg.batch:
            time.sleep(seconds)

    def _announce_before(self, first: int) -> None:
        """Ivan, 30/10: the bot says what it is about to do, waits `action_announce_hold` seconds and only then writes
        it. The lines said since `messages[first]` reach the table now (marked `shown`, so the closing broadcast does
        not repeat them) and the pause follows; the caller's table writes come after. 0 = nothing here: the line goes
        out with the button's closing announcement, after the writes, as it always did."""
        if self.cfg.action_announce_hold <= 0:
            return
        for m in self.messages[first:]:
            for chunk in lua.ascii_text(m):
                self._w(lua.broadcast(chunk, m.kind), "misc")
            m.shown = True
        self._hold(self.cfg.action_announce_hold)

    # ---------- the human's effect choices (E1; the button logic lives in session_choices) ----------
    # One pause at a time reaches the panel. In priority order: the pending combat stopped inside a card effect
    # (`Pending.flow`, a C2 PanelChooser pause), an effect outside combat (`free_effect`: schemes, E2) and the
    # ability triggers a chooser parked (`game.fx.parked`, C3), oldest first.
    def _choosers(self) -> dict:
        return {self.bot: ControllerChooser(), self.human: human_effects.human_chooser(self)}

    def _attach_choosers(self) -> None:
        """Trigger decisions: the bot's controller answers its own; the human's stop the run (parked) for the panel.
        The `look_hand` op reads the human's real hand through `hand_reader` (D3), nothing else ever does."""
        self.game.fx.choosers = self._choosers()
        if self.game.fx.intents is None:
            self.game.fx.intents = []             # the ops report what they do to the table: the translators take it
        self.game.hand_reader = self._read_human_hand
        self.game.deck_reader = (lambda player, n=None: peek.read_top(self, player, n)) if self.cfg.human_deck_guid else None
        self.game.hazard_hook = lambda: self._announce_hazards(write_dials=True)

    def _read_human_hand(self, player: int) -> list[Card]:
        hidden.note_look(self, player)
        return bot_effects.read_human_hand(self, player)

    def _project_effects(self, before: dict | None, played: frozenset = frozenset(),
                         cause: str | None = None) -> Callable[[], None]:
        """Queues what a step changed on the table beyond the bot's own pieces and discards (`session_bot_effects`);
        a table failure is said once, the table wins at the next read. `cause`: whose effect the chat blames."""
        try:
            fin = bot_effects.project(self, before, played, cause)
        except TABLE_ERRORS as e:
            self.say(t("sess.warn_project", err=e), ChatKind.WARNING)
            return lambda: None

        def run() -> None:
            try:
                fin()
            except TABLE_ERRORS as e:
                self.say(t("sess.warn_check", err=e), ChatKind.WARNING)
        return run

    def _human_played(self, p: Pending) -> frozenset:
        """The human's cards this combat took out of their hand by their own hand (the played card, the boost)."""
        played = {c.card_id for owner, c in p.flow.played if owner == self.human}
        combat = p.combat or {}
        boosts = combat.get("boosts") or ([combat["boost"]] if combat.get("boost") is not None else [])
        return frozenset(played | set(boosts))

    def _paused(self) -> tuple[str, object, EffectRun] | None:
        """(kind, holder, run) of the decision the panel shows: ("flow", CombatFlow, run), ("effect", run, run) or
        ("parked", run, run). None when nothing waits for the human."""
        p = self.pending
        if p is not None and p.flow is not None and p.flow.awaiting_run is not None:
            return "flow", p.flow, p.flow.awaiting_run
        if (wait := hidden.prediction_wait(p)) is not None:      # Perfect Shot: the human predicts at Reveal
            return "predict", p, wait
        if self.free_effect is not None and self.free_effect.awaiting is not None:
            return "effect", self.free_effect, self.free_effect
        for run in self.game.fx.parked:
            if run.awaiting is not None:
                return "parked", run, run
        return None

    @property
    def effect_run(self) -> EffectRun | None:
        """The card effect stopped at a decision of the human (its `awaiting` is the request shown)."""
        paused = self._paused()
        return None if paused is None else paused[2]

    def play_effect(self, run: EffectRun) -> list[str]:
        """Public entry point (E2 calls it for the human's cards outside combat): runs `run` and, if it asks the
        human something, leaves it waiting with the choice on the panel buttons."""
        self.messages = []
        with self._timed(t("timing.effect")):
            if self._guarded(lambda: self._begin_effect(run)) and run.done:
                self._effect_finished()
            return self._done()

    def _begin_effect(self, run: EffectRun) -> None:
        if self._paused() is not None:
            raise RuleError(t("err.effect_pending"))
        self.free_effect = run
        self._continue_effect(run)

    def _continue_effect(self, run: EffectRun) -> None:
        """Runs `run` to its end or to the next decision of the human, which the panel then shows."""
        if run.run(self.game, self._choosers()) is not None:
            self._show_choice(run.awaiting)

    def _show_choice(self, req) -> None:
        self.choice_ui.sync(req)
        if peek.wants(self, req):
            peek.open_row(self, req)          # the bot's top card face up in the row, pinged
        if order_cards.wants(self, req) and order_cards.open_row(self, req):
            return                                # the bot's top cards lie face up on the table: the human orders them by hand
        if (req.kind == "cards" and req.player == self.human and req.extra.get("zone") == "hand"
                and req.extra.get("of") == self.bot and req.extra.get("purpose") == "discard"):
            return                                # look-and-discard: `hidden.manual_start` explains it, no option list
        if moves.manual_request(self) is not None:
            moves.start(self, req)                # a fighter the human moves by hand: no space buttons
            return
        if pile.manual_request(self) is not None:
            pile.start(self, req)                 # cards the human moves from their discard to their deck: no options
            return
        self.say(t("sess.choice_hint", prompt=choices.prompt_text(self.game, req), options=choices.options_text(self.game, req),
                   hint=choices.card_text_hint(self.game, req)), ChatKind.YOUR_TURN)

    def _effect_finished(self) -> None:
        self.choice_ui = choices.ChoiceUI()
        self.say(t("sess.effect_done"), ChatKind.NEUTRAL)
        self._write_dials(post=True)              # heals and damage of the effect: the table dials catch up

    def _guarded(self, step: Callable[[], None]) -> bool:
        """Runs an engine step that may stop halfway inside an effect. If it fails, the game and the session go back
        to the saved-game snapshot taken before it: nothing half-applied stays. True when the step went through."""
        saved = self.to_dict()
        try:
            step()
        except RuleError as e:
            self._restore(saved)
            self.say(t("sess.illegal", err=e), ChatKind.WARNING)
            return False
        except Exception:
            self._restore(saved)
            raise
        return True

    def _restore(self, saved: dict) -> None:
        self.load_dict(saved)
        self.choice_ui = choices.ChoiceUI()
        self.reveal_bot_hand = False              # the look belonged to the step that was undone

    def _choice(self, payload: dict) -> None:
        paused = self._paused()
        if paused is None:
            self.say(t("sess.no_choice"), ChatKind.WARNING)
            return
        kind, holder, run = paused
        if hidden.manual_request(self) is not None:      # look-and-discard: the human acts on the table, this is Done
            hidden.manual_done(self, paused)
            return
        if moves.manual_request(self) is not None:        # a fighter to move by hand: 1 is Done, 2 is Don't move
            moves.press(self, paused, payload.get("i"))
            return
        if pile.manual_request(self) is not None:         # cards from your discard to your deck: 1 is Done
            pile.press(self, paused, payload.get("i"))
            return
        if order_cards.manual_request(self) is not None:   # the bot's top cards on the table, stacked by you: 1 is Done
            order_cards.press(self, paused, payload.get("i"))
            return
        verdict, value = choices.press(self.game, run.awaiting, self.choice_ui, payload.get("i"))
        if verdict == "error":
            self.say(value, ChatKind.WARNING)
            return
        if verdict != "answer":
            return
        try:
            run.awaiting.validate(value)
        except ValueError as e:
            self.say(t("sess.bad_answer", err=e), ChatKind.WARNING)
            return
        self._answer_choice(paused, value)

    def _answer_choice(self, paused: tuple, value: list) -> None:
        """Delivers a validated answer (a button, or a ping on the bot's hand row) to the decision that waits."""
        kind, holder, run = paused
        if kind == "predict":
            hidden.answer_prediction(self, holder, value)
            return
        if blind.is_count(getattr(run, "awaiting", None)):      # BLIND BOOST: the bot moves the declared cards before the engine goes on
            blind.declared(self, run, value)
        if kind == "flow":
            ok = self._guarded(lambda: self._answer_flow(holder, value))
            hidden.close_row(self, value, ok)     # a pick among the bot's hand cards: the row follows the engine
            if ok:
                self._combat_step_done(self.pending)
            return
        asked = run.awaiting
        ok = self._guarded(lambda: self._answer_run(run, value))
        hidden.close_row(self, value, ok)
        peek.answered(self, asked, value, ok)     # the card of the row goes back on top or to the bottom of the bot's deck
        if ok and run.done:
            if kind == "effect":
                self.free_effect = None
            else:
                self.game.fx.parked.remove(run)
            self._effect_finished()
            self._effect_done(run)

    def _effect_done(self, run: EffectRun) -> None:
        """A run that stopped at a decision of the human is now done. A scheme (parked by `ongoing.resolve_scheme`)
        ends where a scheme ends: the bot's reaches its discard pile, the human's step closes (`session_effects`);
        then the bot's turn goes on if it was its turn (its action was spent when the card was played)."""
        if events.say_parked(self.game, run):     # a trigger of yours that hurt someone once you answered (the Pact)
            self._say_triggers()
            self._write_dials()
        if self.game.winner is not None:              # the answer ended the game (DARK PACT at 1 hit point): nothing left to move or deal
            for f in self.game.own(self.human, alive_only=False):
                if not f.alive and f.hero:
                    self._announce_fall(f)
            self.game.fx.intents and self.game.fx.intents.clear()
            self.say(t("game.over", winner=self.game.winner))
            self._game_over_dialog()
            return
        cause = human_effects.ABILITY_NAME.get(run.label, run.label.replace("_", " ").upper())
        checks = self._pact_to_bottom(cause)
        if not run.flags.get("scheme"):               # a parked ability (OCCULT DETECTIVE): a scheme's draws go with its step
            self._deal_owed_draws(cause)
        if checks:
            self._try_flush_stage()()
            for check in checks:
                check()
        if run.ctx.moment == "after_combat" and self.game.winner is None:
            self.say(t("combat.after"), ChatKind.YOUR_TURN)       # the combat's own closing line, held back while DARK PACT asked
        scheme = run.flags.get("scheme")
        if scheme:
            player = scheme["player"]
            card = next(c for c in self.game.players[player].full_set if c.card_id == scheme["card_id"])
            ongoing.finish_scheme(self.game, player, card)
            if player == self.bot:
                self._mark_dirty()                # the card reaches the discard pile
            else:
                human_effects.finish(self, run)
                if self.moving and self.game.turn == self.human:
                    self.say(t("sess.press_end"), ChatKind.YOUR_TURN)
        elif human_effects.STEP in run.flags:         # the BOOSTED WITH of a Maneuver boost the human answered
            human_effects.finish(self, run)
            if self.moving and self.game.turn == self.human and self.game.winner is None:
                self.say(t("maneuver.boost_then_end"), ChatKind.YOUR_TURN)
        if self.game.turn == self.bot and self.pending is None and self.game.winner is None:
            self._bot_continue()

    def _pact_to_bottom(self, cause: str) -> list[Callable[[], None]]:
        """DARK PACT paid by the human: the card they played is still at their combat spot, and the engine sent it to the
        bottom of their deck. The bot moves it there by GUID before the draw the pact owes is dealt (the reported
        intent is taken out of the queue: nothing else translates it)."""
        intents = self.game.fx.intents
        if not intents:
            return []
        mine = [i for i in intents if i["op"] == "return_to_deck" and i["player"] == self.human and i["zone"] == "discard"
                and i.get("position") == "bottom"]
        for i in mine:
            intents.remove(i)
        ids = [c for i in mine for c in i["cards"]]
        return translators.combat_card_to_bottom(self, ids, translators.Ctx(cause)) if ids else []

    def _answer_flow(self, flow: CombatFlow, value: list) -> None:
        run = flow.awaiting_run
        order_cards.pin(self, None if run is None else run.awaiting, value)     # undone with the save if the answer is refused
        flow.resume(value)
        self._drive_flow(flow)

    def _answer_run(self, run: EffectRun, value: list) -> None:
        if "said_before" in run.flags:            # the run changes nothing until now: its line must not include what other triggers did meanwhile
            run.flags["said_before"] = narrate.snapshot(self.game)
        peek.pin(self, run.awaiting, value)       # the order the human chose for the bot's deck, before any reread of its table
        order_cards.pin(self, run.awaiting, value)
        run.resume(value)
        self._continue_effect(run)

    def _drive_flow(self, flow: CombatFlow) -> None:
        """Advances the pending combat until it ends or stops at a decision of the human's card effect (shown on the
        panel). The bot's effect decisions and every boost are answered on the spot: the human's boost is the card
        the table already read (`Pending.combat["boost"]`), the rest as the synchronous `resolve_combat` does."""
        p = self.pending
        mine = {c.card_id: c for c in self.game.players[self.human].full_set}
        ids = p.combat.get("boosts") or ([p.combat["boost"]] if p.combat["boost"] is not None else [])
        boost = [mine[i] for i in ids] if len(ids) > 1 else (mine[ids[0]] if ids else None)    # a card with several boosts takes a list
        flow.choosers = hidden.flow_choosers(self, p)      # the Perfect Shot prediction decided at play time
        choose = legacy_chooser(self.game, flow, boost, self.human)
        while (wait := flow.run()) is not None:
            if wait.choice.kind == "table" or (wait.choice.kind == "effect" and wait.choice.player == self.human):
                return                            # `_combat_step_done` shows the choice, after what the combat already did
            flow.resume(choose(wait.choice))

    def panel_labels(self) -> dict[str, str]:
        """Texts of the visible choice buttons (empty without a pending choice)."""
        run = self.effect_run
        req = None if run is None else run.awaiting
        if hidden.manual_request(self) is not None:
            return hidden.manual_view(self)[1]
        if moves.manual_request(self) is not None:
            return moves.view(self, req)[1]
        if pile.manual_request(self) is not None:
            return pile.view(self, req)[1]
        if order_cards.manual_request(self) is not None:
            return order_cards.view(self, req)[1]
        return choices.panel_choice_view(self.game, req, self.choice_ui)[1]

    # ---------- the look at the bot's hand: only when a card allows it ----------
    def grant_look(self) -> None:
        """A card of the human lets them look at the bot's hand: the button shows until the look is taken, the next
        action of the human starts or the bot's turn goes on (`revoke_look`)."""
        self.look_granted = True
        self._look_epoch = self._epoch

    def revoke_look(self) -> None:
        self.look_granted = False

    def _revoke_look_after_button(self) -> None:
        """The look window closes, unless this very button is the one that opened it."""
        if self._look_epoch != self._epoch:
            self.revoke_look()

    def _grant_look_for(self, card: Card | None) -> None:
        """Legacy route (the human's hero outside the interpreter): a card that looks grants the button. An
        interpreted hero looks inside the card's run and the bot shows its hand then (`session_hidden`)."""
        if self.game.fx.interprets(self.human):
            return
        if card is not None and choices.grants_look(self.game, self.human, card):
            self.grant_look()
            self.say(t("look.granted", title=card.title), ChatKind.YOUR_TURN)

    # ---------- restrictions on the human ----------
    def _blocked_buttons(self) -> dict[str, str]:
        out = {}
        for r in choices.active_restrictions(self):
            for ident in r.buttons(self):
                out[ident] = r.reason
        return out

    def _tell_blocks(self) -> None:
        """Explains in the chat, once while it lasts, each restriction that now limits the human."""
        active = {r.name: r for r in choices.active_restrictions(self)}
        for name, r in active.items():
            if name not in self._blocks_told:
                self.say(r.reason, ChatKind.WARNING)
        self._blocks_told = set(active)

    def _check_may_attack(self) -> None:
        for r in choices.active_restrictions(self):
            if r.name == "attack":
                raise RuleError(r.reason)

    def _warn(self, fid: str, kind: str, msg: str) -> None:
        """Warns only once per piece and reason until the problem goes away."""
        if (fid, kind) not in self._warned:
            self._warned.add((fid, kind))
            self.say(msg, ChatKind.WARNING)


    # ---------- restarting the game ----------
    def _restart(self, _: dict) -> None:
        """Double press (3 s): the first arms, the second restarts."""
        if not self.restart_armed():
            self._restart_at = self.clock()
            self.say(t("restart.arm"), ChatKind.WARNING)
            return
        self._restart_at = None
        if self.look is not None:
            self._look_best_effort_cancel()
        reveal.clear(self)
        fresh = self._fresh_game()
        self._reset_table(fresh)
        self._adopt_fresh(fresh)
        if self.state_path is not None:
            try:
                self.state_path.unlink(missing_ok=True)
            except OSError as e:
                self.say(t("restart.delete_fail", path=self.state_path, err=e), ChatKind.WARNING)
        self.say(t("restart.done"))
        self._begin_game()
        self._darken_intuition_tokens()

    def _new_game(self, _: dict) -> None:
        """Double press (same window as Restart): discards the saved game and asks `play` to return to the pre-game
        gate, where the player puts another map and other heroes. Nothing on the table is touched here."""
        if not self.can_regate:
            return
        if not self.new_game_armed():
            self._new_game_at = self.clock()
            self.say(t("newgame.arm"), ChatKind.WARNING)
            return
        self._new_game_at = None
        if self.look is not None:
            self._look_best_effort_cancel()
        reveal.clear(self)
        if self.state_path is not None:
            try:
                self.state_path.unlink(missing_ok=True)
            except OSError as e:
                self.say(t("restart.delete_fail", path=self.state_path, err=e), ChatKind.WARNING)
        self.say(t("newgame.done"))
        self.back_to_gate = True

    def _fresh_game(self) -> Game:
        if self.new_game is not None:
            return self.new_game()
        game = Game.new(self.game.board, secrets.randbelow(2 ** 31), controllers={}, bot_player=self.bot,
                        heroes=(self.game.hero_def(self.bot).slug, self.game.hero_def(self.human).slug),
                        card_shifts=(self.cfg.bot_card_shift, self.cfg.human_card_shift))
        if self.first_mode in ("human", "bot"):
            game.turn = self.human if self.first_mode == "human" else self.bot
        game.begin_turn(emit=False)          # its triggers fire when the table is set (`_start_first_turn`)
        return game

    def _reset_table(self, fresh: Game) -> None:
        """The table back to its initial state in ONE message: all the cards of both sides to their decks (shuffled),
        the dials at full life and the destinies at 0, and all miniatures off the board. It is checked on the
        resulting table; if anything fails the engine is not touched and it can be repeated."""
        c = self.cfg
        bot_spot, human_spot = c.dead_spot, human_dead_spot(c)
        if bot_spot is None or human_spot is None:
            raise SessionError(t("err.no_dead_spot"))
        scope = self._scope()
        sizes = {"bot": len(fresh.players[self.bot].full_set), "human": len(fresh.players[self.human].full_set)}
        self._flush()
        self._check_reset_plan(scope, sizes)
        decks = {"bot": self._w(lua.reset_deck(c.bot_deck_guid, id_range=c.bot_card_ids, identity=self._identity(),
                                               scope=scope, **self._deck_kw()), "cards")}
        if c.human_deck_guid:
            decks["human"] = self._w(lua.reset_deck(c.human_deck_guid, id_range=c.human_card_ids, identity=self._identity("human"),
                                                    scope=scope, **self._deck_kw("human")), "cards")
        else:
            self.say(t("restart.no_human_deck"), ChatKind.WARNING)
        pieces = self._table_pieces()
        for owner, spot, mine in ((self.bot, bot_spot, True), (self.human, human_spot, False)):
            for slot, f in enumerate(sorted(fresh.own(owner, alive_only=False), key=lambda f: f.fid)):
                info = pieces.get(f.fid) or {}
                guid = info["guid"] if info.get("found") else self._guids(f.fid)[0]
                self._w(lua.place_piece(guid, *fallen_slot(spot, mine, slot)), "pieces")
        want = {guid: fresh.fighters[fid].max_hp for fid, guid in self._live_dials().items()}
        want = {g: int(v) for g, v in want.items()}
        if c.destiny_dial:
            want[c.destiny_dial] = 0
        if c.source_dial:
            want[c.source_dial] = 0
        if want:
            self._w(lua.set_health_dials(want), "dials")
        self._flush()
        for side, op in decks.items():
            res = op.result or {}
            if not res.get("deck") or res.get("quantity") != sizes[side]:
                raise SessionError(t("err.deck_incomplete", side=t("sess.side.bot" if side == "bot" else "sess.side.human"), button=self._reset_button(), got=res.get("quantity"), want=sizes[side]))
        own = {x.card_id for x in fresh.players[self.bot].full_set}

        def clean() -> bool:
            on_board = [fid for fid, info in self._table_pieces().items() if self._on_board(info)]
            dials = self._rd_dials(sorted(want)) if want else {}
            return (not self._table_hand_ids() and not ({r["id"] for r in self._rd_bot_discard()} & own)
                    and not on_board and ("human" not in decks or self._rd_human_count(0) == 0)
                    and all((dials.get(g) or {}).get("value") == v for g, v in want.items()))
        if not self._settle(clean):
            raise SessionError(t("err.reset_dirty", button=self._reset_button()))

    def _reset_button(self) -> str:
        """The panel button that repeats the reset, (its label in the current language), for the error texts."""
        return t("panel.restart")

    def _check_reset_plan(self, scope: lua.Scope, sizes: dict[str, int]) -> None:
        """Before moving anything: each side must be able to gather ALL its cards into its deck. If one cannot, the
        restart is rejected as a whole (one side is never left returned and the other not)."""
        c = self.cfg
        sides = [("bot", c.bot_deck_guid, c.bot_deck_spot, c.bot_card_ids, c.bot_deck_zone)]
        if c.human_deck_guid:
            sides.append(("human", c.human_deck_guid, c.human_deck_spot, c.human_card_ids, c.human_deck_zone))
        plans = self.client.call_lua(lua.reset_plan(
            [(guid, spot, rng, self._identity(side), zone) for side, guid, spot, rng, zone in sides], c.deck_radius,
            scope=scope))
        if not isinstance(plans, list) or len(plans) != len(sides):
            raise TTSLuaError(t("err.reset_plan", got=repr(str(plans)[:80])))
        for (side, *_), plan in zip(sides, plans):
            plan = plan if isinstance(plan, dict) else {}
            total, gatherable = plan.get("total"), plan.get("deck") or (plan.get("loose") or 0) >= 1
            if total != sizes[side] or not gatherable:
                raise SessionError(t("err.reset_gather", button=self._reset_button(), n=sizes[side], side=t("sess.side.bot" if side == "bot" else "sess.side.human"),
                                     found=total if isinstance(total, int) else 0))

    def _adopt_fresh(self, fresh: Game) -> None:
        """The session moves to the new game, keeping the client, the configuration and the run settings."""
        keep = ("client", "ai", "cfg", "bot", "human", "timing", "state_path", "first_mode", "new_game", "clock",
                "cost_log", "broadcast", "snap", "_trusted", "_queue", "_post", "_expect_hand", "_snap_spec", "_depth",
                "_epoch", "messages", "_write_seq", "_deck_ident", "game_log", "_deck_origin")
        saved = {k: self.__dict__[k] for k in keep}
        blank = Session(fresh, self.client, self.ai, self.cfg, self.bot)
        self.__dict__.clear()
        self.__dict__.update(blank.__dict__)
        self.__dict__.update(saved)
        self.game.controllers[self.human] = HumanProxy(self._owe_discard)
        self._attach_choosers()                   # the hand reader is a bound method: it has to be this session's
        getattr(self.ai, "reset", lambda: None)()          # an AI with memory forgets the previous game

    # ---------- saving ----------
    def to_dict(self) -> dict:
        saved = self._to_dict(self.pending)
        if self.free_effect is not None:
            saved["effect"] = self.free_effect.to_dict()
        if self.look_granted:
            saved["look_granted"] = True
        if self.token_copies:
            saved["token_copies"] = {k: list(v) for k, v in self.token_copies.items()}
        if self.combat_guids:
            saved["combat_guids"] = {str(k): v for k, v in self.combat_guids.items()}
        if self.fx_unprojected is not None:
            saved["fx_unprojected"] = self.fx_unprojected
        return saved

    def _to_dict(self, p: Pending | None) -> dict:
        return {
            "game": persist.game_to_dict(self.game),
            "heroes": [self.game.hero_def(self.bot).slug, self.game.hero_def(self.human).slug],
            "card_shifts": [self.cfg.bot_card_shift, self.cfg.human_card_shift],
            "language": i18n.language(),
            "pending": None if p is None else {
                "kind": p.kind, "attacker": p.attacker.fid, "target": p.target.fid,
                "bot_card": p.bot_card.card_id if p.bot_card else None, "bot_card_guid": p.bot_card_guid,
                "cancel_failures": p.cancel_failures, "defended": p.defended, "boost_wait": None if p.wait is None else p.wait.to_dict(),
                **({"flow": p.flow.to_dict(), "combat": p.combat} if p.flow is not None else {}),
                **({"prediction": p.prediction} if p.prediction is not None else {}),
                **({"predict": p.predict} if p.predict is not None else {}),
                **({"declared": p.declared} if p.declared is not None else {})},
            "pending_discard": self.pending_discard, "pending_value": self.pending_value, "look": self.look,
            "chosen_attacker": self.chosen_attacker, "moving": self.moving,
            "bot_discarded": sorted(self.bot_discarded), "dirty": self.dirty,
            "unprojected": None if self.unprojected is None else {k: list(v) for k, v in self.unprojected.items()},
            "bot_stage": self.bot_stage, "first_turn_pending": self.first_turn_pending, "limit_waived": self.limit_waived, "flush_failures": self.flush_failures,
            "placing": self.placing, "fingerprint": self.fingerprint(),
            "destiny_seen": None if self.destiny_seen is None else list(self.destiny_seen),
            "scheme_baseline": self.scheme_baseline, "dial_debt": self.dial_debt, "setup": self.setup,
            **({"maneuver_baseline": self.maneuver_baseline} if self.maneuver_baseline is not None else {}),
            **({"maneuver_boosted": self.maneuver_boosted} if self.maneuver_boosted is not None else {}),
            **({"ability_wait": self.ability_wait} if self.ability_wait is not None else {}),
            **({"human_dealt": self.human_dealt} if self.human_dealt != self.game.drawn[self.human] else {}),
            **({"declared_carry": self.declared_carry} if self.declared_carry is not None else {}),
            "dials_written": self.dials_written, "dials_attempted": self.dials_attempted,
            "start_spaces": {str(k): v for k, v in self.game.start_spaces.items()},
            "deck_ident": {side: [list(pair) for pair in pairs]
                           for side, pairs in {**self._saved_ident, **self._deck_ident}.items()},
            **({"resolved_pieces": self.resolved_pieces} if self.resolved_pieces else {}),
            **peek.to_dict(self),
            **order_cards.to_dict(self),
            **({"resolved_dials": self.resolved_dials} if self.resolved_dials else {}),
            **({"deck_live": {**self._saved_decks, **self._live_decks()}} if {**self._saved_decks, **self._live_decks()} else {}),
            **({"zones_live": self._live_zones()} if self._live_zones() else {}),
        }

    @property
    def configured_dials(self) -> dict[str, str]:
        """The life dial GUIDs as the data gives them, not as resolved by name (the identity of the table)."""
        return {fid: self._dial_origin.get(fid, g) for fid, g in self.cfg.dials.items()}

    def fingerprint(self) -> dict:
        """Fingerprint of the save: which table (GUIDs and identity settings) and which game it belongs to."""
        return {"game_id": self.game_id, "config_hash": self._config_hash(), "guids": self.guids_in_use(configured=True)}

    def _config_hash(self, **override) -> str:
        c = self.cfg
        identity = {k: getattr(c, k) for k in IDENTITY_KEYS}
        identity.update(self.configured_decks)          # the decks as configured, not the GUID the table gave them
        identity.update(self.configured_zones)          # and the discard zones: one created at start-up has a new GUID every time
        identity["dials"] = self.configured_dials
        identity.update(override)
        identity["pieces"] = {fid: v for fid, v in sorted(self.configured_pieces.items())}
        identity["board"] = self.game.board.key
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()

    def _check_fingerprint(self, saved) -> None:
        if not isinstance(saved, dict) or not isinstance(saved.get("game_id"), str):
            raise persist.StateError(t("save.no_fingerprint"))
        mine = self.fingerprint()
        # a save from before the destiny dial followed a bot-side Hellboy (bf91f02) has no dial in its identity:
        # same table, the dial is simply written on the next read
        legacy = self.cfg.destiny_dial is not None and saved.get("config_hash") == self._config_hash(destiny_dial=None)
        if saved.get("config_hash") != mine["config_hash"] and not legacy:
            differ = sorted(set(saved.get("guids") or []) ^ set(mine["guids"]))
            detail = t("save.detail.guids", guids=", ".join(differ)) if differ else t("save.detail.layout")
            raise persist.StateError(t("save.other_config", detail=detail))

    def load_dict(self, d: dict) -> None:
        self._check_fingerprint(d.get("fingerprint"))
        try:
            persist.apply_game(self.game, d["game"])
            self._attach_choosers()
            by_id = {c.card_id: c for c in self.game.players[self.bot].full_set}
            p = d["pending"]
            self.pending = None if p is None else Pending(
                p["kind"], self.game.fighters[p["attacker"]], self.game.fighters[p["target"]],
                by_id[p["bot_card"]] if p["bot_card"] is not None else None, p["bot_card_guid"], p["cancel_failures"],
                bool(p.get("defended", True)),
                self._load_boost_wait(p.get("boost_wait"), self.human, {c.card_id: c for c in self.game.players[self.human].full_set}),
                *self._load_flow(p), p.get("prediction"), p.get("predict"),
                p["declared"] if isinstance(p.get("declared"), dict) else None)
            self.free_effect = None if d.get("effect") is None else EffectRun.from_dict(d["effect"])
            self.look_granted = d.get("look_granted") is True
            self.token_copies = {str(k): [str(g) for g in v] for k, v in (d.get("token_copies") or {}).items()}
            self.combat_guids = {int(k): str(v) for k, v in (d.get("combat_guids") or {}).items()}
            self.fx_unprojected = d.get("fx_unprojected")
            self.pending_discard, self.pending_value = d["pending_discard"], d["pending_value"]
            self.look = self._load_look(d.get("look"))
            self.peek, self.peek_pins = peek.load(d)
            self.order_row = order_cards.load(d)
            self.chosen_attacker, self.moving = d["chosen_attacker"], d["moving"]
            self.bot_discarded, self.dirty = set(d["bot_discarded"]), d["dirty"]
            un = d["unprojected"]
            self.unprojected = None if un is None else {k: (v[0], v[1]) for k, v in un.items()}
            self.bot_stage, self.limit_waived = d["bot_stage"], d["limit_waived"]
            self.first_turn_pending = bool(d.get("first_turn_pending", False))
            self.flush_failures = d["flush_failures"]
            self.placing = d.get("placing")
            self.scheme_baseline = d.get("scheme_baseline")
            self.maneuver_baseline = d.get("maneuver_baseline")
            self.maneuver_boosted = d.get("maneuver_boosted")
            self.ability_wait = d.get("ability_wait")
            self.human_dealt = int(d.get("human_dealt", self.game.drawn[self.human]))     # absent: everything counted was dealt
            self.declared_carry = d.get("declared_carry") if isinstance(d.get("declared_carry"), dict) else None
            self.dial_debt = bool(d.get("dial_debt", False))
            self.dials_written = {str(k): int(v) for k, v in (d.get("dials_written") or {}).items()}
            self.dials_attempted = {str(k): int(v) for k, v in (d.get("dials_attempted") or {}).items()}
            self.setup = d.get("setup")
            if d.get("start_spaces"):
                self.game.start_spaces = {int(k): int(v) for k, v in d["start_spaces"].items()}
            seen = d.get("destiny_seen")
            self.destiny_seen = None if seen is None else (int(seen[0]), str(seen[1]))
            self.game_id = d["fingerprint"]["game_id"]
            self._saved_ident = self._load_saved_identities(d.get("deck_ident"))
            piece_id.restore(self, d.get("resolved_pieces"))
            piece_id.restore_dials(self, d.get("resolved_dials"))
            self._saved_decks = {side: g for side, g in (d.get("deck_live") or {}).items()
                                 if side in ("bot", "human") and isinstance(g, str) and lua._GUID.fullmatch(g)}
            self._saved_zones = self.read_saved_zones(d.get("zones_live"))
        except (KeyError, TypeError, IndexError, ValueError) as e:
            raise persist.StateError(t("save.invalid", error=repr(e))) from None

    def _load_flow(self, p: dict) -> tuple[CombatFlow | None, dict | None]:
        """The combat stopped inside a card effect and what finishing it needs; saves from before E1 have neither."""
        if p.get("flow") is None:
            return None, None
        combat = p["combat"]
        if not isinstance(combat, dict) or not all(k in combat for k in _COMBAT_KEYS):
            raise KeyError("combat")
        return CombatFlow.from_dict(self.game, p["flow"]), combat

    @staticmethod
    def _load_look(raw) -> dict | None:
        if raw is None:
            return None
        ok = (isinstance(raw, dict) and all(isinstance(raw.get(k), list) for k in ("ids", "guids", "spots"))
              and 1 <= len(raw["ids"]) <= lua.MAX_LOOK_CARDS
              and len(raw["ids"]) == len(raw["guids"]) == len(raw["spots"])
              and all(isinstance(i, int) and not isinstance(i, bool) for i in raw["ids"])
              and all(isinstance(g, str) and lua._GUID.fullmatch(g) for g in raw["guids"])
              and all(isinstance(sp, list) and len(sp) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                                     and math.isfinite(v) for v in sp)
                      for sp in raw["spots"]))
        if not ok:
            raise KeyError("look")
        look = {"ids": list(raw["ids"]), "guids": list(raw["guids"]), "spots": [list(sp) for sp in raw["spots"]]}
        if raw.get("mode") in (hidden.MODE_PICK, hidden.MODE_REVEAL):     # E3: the row a card of the human opened
            look["mode"] = raw["mode"]
            if isinstance(raw.get("purpose"), str):
                look["purpose"] = raw["purpose"]
            hp = raw.get("hp")
            if isinstance(hp, dict) and all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                                            and math.isfinite(v) for k, v in hp.items()):
                look["hp"] = dict(hp)       # the pick's price is announced from it
        return look

    @staticmethod
    def _load_boost_wait(raw, human: int, human_cards: dict | None = None) -> PendingChoice | None:
        """Translator for the saved `boost_wait`: a dict without "kind" is the old flat format (the human's boost)."""
        if raw is None:
            return None
        hand = raw.get("hand") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or not isinstance(raw.get("card"), int) \
                or not isinstance(raw.get("baseline"), list) or not all(isinstance(i, int) for i in raw["baseline"]) \
                or not (raw.get("guid") is None or isinstance(raw["guid"], str)) \
                or not (hand is None or (isinstance(hand, int) and not isinstance(hand, bool))):
            raise KeyError("boost_wait")
        flat = {"kind": raw.get("kind", "boost"), "player": raw.get("player", human), "card": raw["card"],
                "guid": raw.get("guid"), "baseline": list(raw["baseline"]), "hand": hand,
                "stuck": raw.get("stuck") is True}

        def deck_of(card_id: int) -> bool:        # Flame Lash: recomputed from the card, so a save without the key also works
            card = (human_cards or {}).get(card_id)
            return card is not None and deck_boost(card)
        try:
            return PendingChoice.from_dict({**flat, "deck": raw.get("deck")}, default_player=human, deck_of=deck_of)
        except KeyError:
            raise KeyError("boost_wait") from None

    @staticmethod
    def _load_saved_identities(raw) -> dict[str, tuple]:
        """Saved identities are validated like those read from the table; what is useless is dropped without breaking
        the save (the identity is read again from the table)."""
        out = {}
        for side in ("bot", "human"):
            rows = raw.get(side) if isinstance(raw, dict) else None
            rows = rows if isinstance(rows, list) else []
            pairs = Session._parse_pairs([{"face": r[0], "back": r[1]} for r in rows
                                          if isinstance(r, (list, tuple)) and len(r) == 2])
            if pairs:
                out[side] = pairs
        return out

    def _persist(self) -> None:
        if self.state_path is None or self.back_to_gate:      # a discarded game must not leave its save behind
            return
        try:
            persist.save_atomic(self.state_path, self.to_dict())
        except OSError as e:
            self.say(t("sess.save_fail", path=self.state_path, err=e), ChatKind.WARNING)

    def guids_in_use(self, configured: bool = False) -> list[str]:
        """All the configuration's GUIDs that must still exist after reloading the game (`configured`: the pieces' GUIDs
        as the data gives them, not as resolved by name)."""
        c = self.cfg
        pcs = self.configured_pieces if configured else {fid: piece_guids(v) for fid, v in c.pieces.items()}
        zones = self.configured_zones if configured else {k: getattr(c, k) for k in DISCARD_ZONE_KEYS}
        guids = [lua.board_guid(self.game.board), self.configured_decks["bot_deck_guid"] if configured else c.bot_deck_guid,
                 zones["bot_discard_zone"], zones["human_discard_zone"],
                 *(g for v in pcs.values() for g in v), *(self.configured_dials if configured else c.dials).values(),
                 *([c.destiny_dial] if c.destiny_dial else []), *([c.source_dial] if c.source_dial else []), *self._deck_zones()]
        return sorted(set(guids))

    def _deck_zones(self) -> list[str]:
        return [z for z in (self.cfg.bot_deck_zone, self.cfg.human_deck_zone) if z]

    def guid_groups(self) -> list[list[str]]:
        """GUIDs that must exist, in groups: one of each group is enough (a miniature with states is a single object
        at a time; the rest of the GUIDs are its own)."""
        c = self.cfg
        singles = [lua.board_guid(self.game.board), c.bot_deck_guid, c.bot_discard_zone, c.human_discard_zone,
                   *c.dials.values(), *([c.destiny_dial] if c.destiny_dial else []), *([c.source_dial] if c.source_dial else []),
                   *self._deck_zones()]
        return [[g] for g in sorted(set(singles))] + [piece_guids(v) for _, v in sorted(c.pieces.items())]

    def _require_human_turn(self) -> bool:
        if self.game.winner is not None:
            self.say(t("game.ended"), ChatKind.WARNING)
            return False
        if self.game.turn != self.human or self.pending is not None or self.pending_discard is not None:
            self.say(t("sess.not_possible"), ChatKind.WARNING)
            return False
        if self.moving:
            self.say(t("sess.action_open"), ChatKind.WARNING)
            return False
        return True

    def _begin_action(self) -> None:
        """Before each human action the table is re-read (it includes what they did when starting the turn)."""
        self._revoke_look_after_button()
        self._try_flush_table()
        self.sync_positions()
        self.sync_human()

    def _try_flush_table(self) -> None:
        """Settles the bot's table debt without blocking the human: if it keeps failing only a warning is given."""
        self._try_flush_stage()()

    def _try_flush_stage(self) -> Callable[[], None]:
        try:
            fin = self._flush_table_stage()
        except TABLE_ERRORS as e:
            self.say(t("sess.warn_table_behind", err=e), ChatKind.WARNING)
            return lambda: None

        def run() -> None:
            try:
                fin()
            except TABLE_ERRORS as e:
                self.say(t("sess.warn_table_behind", err=e), ChatKind.WARNING)
        return run

    # ---------- the human's buttons ----------
    def _maneuver(self, _: dict) -> None:
        if not self._require_human_turn():
            return
        self._begin_action()
        self.game.use_action()
        if self.game.fx.can_draw(self.human):         # a Maneuver whose draw is prevented does not count (an empty deck does)
            self.game.fx.count_maneuver()
        hp0, alive0 = {fid: f.hp for fid, f in self.game.fighters.items()}, self._alive_map()
        self.moving = True
        st = self.game.players[self.human]
        self.maneuver_baseline = [c.card_id for c in st.discard]
        self.maneuver_boosted = None
        if not self.game.fx.can_draw(self.human):
            self.say(t("maneuver.no_draw", reason=choices.NO_DRAW_REASON), ChatKind.YOUR_TURN)
            return
        if not self.cfg.human_deck_guid:
            self._draw_human_by_button(1)
            self._announce_exhaustion(hp0, alive0)
            self.say(t("maneuver.drew"), ChatKind.YOUR_TURN)
            self.game.fx.emit("after_maneuver", self.human)
            return
        if not st.deck:                           # empty deck: exhaustion through the same path as the bot's
            self._draw_human_by_button(1)
            self._announce_exhaustion(hp0, alive0)
            self.say(t("maneuver.empty"), ChatKind.YOUR_TURN)
            return
        self._deal_maneuver_card(st)
        self.game.fx.emit("after_maneuver", self.human)       # INVENTIVE asks on the panel (a trigger of the hero)

    def _deal_maneuver_card(self, st) -> None:
        """Deals the Maneuver card from the human's deck to their hand, in the same composite as the button. It only
        counts cards: it never reads which ones the human has. A failed deal is not repeated (the human draws the card
        by hand and the engine adjusts to the hand count on the next read)."""
        c = self.cfg
        before, discarded = len(st.hand), len(st.discard)
        try:
            script = lua.deal_cards(c.human_deck_guid, 1, c.human_seat, id_range=c.human_card_ids,
                                    identity=self._identity("human"), **self._deck_kw("human"))
        except TABLE_ERRORS as e:
            self.say(t("deal.maneuver_fail", err=e), ChatKind.WARNING)
            return
        try:
            op = self._w(script, "cards")
        except TABLE_ERRORS as e:             # the reply may arrive late with the card already dealt
            self.say(t("deal.confirm_fail", err=e), ChatKind.WARNING)
            return
        drawn = self._draw_human_by_button(1)
        self.say(t("maneuver.dealt"), ChatKind.YOUR_TURN)

        def check() -> bool:
            try:
                dealt = (op.result or {}).get("dealt")
            except TABLE_ERRORS:
                self.say(t("deal.confirm_fail_short"), ChatKind.WARNING)
                self._deal_check = None
                return False
            if dealt != 1:
                for card in drawn:
                    if card in st.hand:
                        st.hand.remove(card)
                        st.deck.insert(0, card)
                        self.game.drawn[self.human] = max(0, self.game.drawn[self.human] - 1)
                        self.human_dealt = max(0, self.human_dealt - 1)
                self.say(t("deal.card_fail"), ChatKind.WARNING)
                self._deal_check = None
                return False
            self._deal_check = (before, 1, discarded)
            return True
        self._post.append(check)

    def _draw_human_by_button(self, n: int) -> list[Card]:
        """The engine draws for the human in a step that deals (or announces) the cards itself: they are not owed."""
        drawn = self.game.draw(self.human, n)
        self.human_dealt += len(drawn)
        return drawn

    def _deal_owed_draws(self, cause: str | None = None) -> None:
        """Every draw the engine counted for the human from an effect (their cards, their hero, a rival's) is dealt
        from their physical deck to their hand, like the Maneuver's: counted only, their hand is never read. Called
        where an effect's step is projected and at the close of every button (`_commit`); `human_dealt` is saved, so
        a resume never deals twice. A deal that fails is said once and the human draws by hand (the engine already
        counts the cards: the next reading of their hand settles it)."""
        drawn = self.game.drawn[self.human]
        self.human_dealt = min(self.human_dealt, drawn)
        n = drawn - self.human_dealt
        if n <= 0:
            return
        d = self.pending_discard
        if d is not None and d.get("hand"):
            # the effect discards from the human's hand first and draws after (Fleeting Moments, Crown Of Flame):
            # the cards are dealt when the discard is settled, so the discard is of the hand they hold now
            if cause and not d.get("draw_cause"):
                d["draw_cause"] = cause
            if not d.get("draws_told"):
                d["draws_told"] = True
                self.say(t("deal.after_discard", cards=plural(n, "noun.card")), ChatKind.YOUR_TURN)
            return
        self.human_dealt = drawn
        translators.translate(self, {"op": "draw", "player": self.human, "n": n, "cause": cause},
                              translators.Ctx(cause or ""))

    def _undealt_draws(self) -> int:
        """Draws the engine counted that wait for the human's discard to be settled (`_deal_owed_draws`)."""
        d = self.pending_discard
        return max(0, self.game.drawn[self.human] - self.human_dealt) if d is not None and d.get("hand") else 0

    def _deal_human_cards(self, n: int, cause: str | None) -> None:
        """The bot variant of the `draw` translator: `n` cards from the human's physical deck to their hand."""
        c, st = self.cfg, self.game.players[self.human]
        why = f" ({cause})" if cause else ""
        cards = plural(n, "noun.card")
        before, discarded = len(st.hand) - n, len(st.discard)
        try:
            script = lua.deal_cards(c.human_deck_guid, n, c.human_seat, id_range=c.human_card_ids,
                                    identity=self._identity("human"), **self._deck_kw("human"))
            op = self._w(script, "cards")
        except TABLE_ERRORS as e:
            # Nothing was written, so the engine's count is the only record: it stays (the next reading of the hand
            # settles it when he draws by hand) and the cards are not owed again (`human_dealt` already caught up).
            self.say(t("deal.fail", cards=cards, why=why, err=e), ChatKind.WARNING)
            return
        self.say(t("deal.given_discard" if self.pending_discard else "deal.given", cards=cards, why=why), ChatKind.SCHEME)

        def check() -> bool:
            try:
                dealt = (op.result or {}).get("dealt")
            except TABLE_ERRORS as err:
                self.say(t("deal.confirm_fail_n", cards=cards, why=why, err=err), ChatKind.WARNING)
                self._deal_check = None
                return False
            if dealt != n:
                # TTS did write, and dealt fewer cards than the engine counted: the missing ones go back to the engine
                # (hand -> deck, `drawn` and `human_dealt` down) so it matches what the table really holds.
                short = n - (dealt if isinstance(dealt, int) else 0)
                self._undraw_human(short)
                self.say(t("deal.short", short=short, cards=cards, why=why), ChatKind.WARNING)
                self._deal_check = None
                return False
            self._deal_check = (before, n, discarded)
            return True
        self._post.append(check)

    def _undraw_human(self, k: int) -> None:
        """The table could not deal `k` cards the engine counted: they go back to the top of the virtual deck (the
        cards the bot was not told about first) and are no longer owed."""
        st, known = self.game.players[self.human], self.game.players[self.bot].known
        told = set(known.seen) | set(known.possible)
        for _ in range(min(k, len(st.hand))):
            card = next((c for c in reversed(st.hand) if c.card_id not in told), st.hand[-1])
            st.hand.remove(card)
            st.deck.insert(0, card)
        self.game.drawn[self.human] = max(0, self.game.drawn[self.human] - k)
        self.human_dealt = max(0, self.human_dealt - k)

    def _verify_maneuver_deal(self, real: int, discard_now: int) -> None:
        """On the next snapshot the human's hand must have gone up by what was dealt (discounting what they have
        played or discarded since); if not, a warning is given once and it is not dealt again."""
        chk, self._deal_check = self._deal_check, None
        if chk is None:
            return
        before, n, discarded = chk
        if real >= before + n:
            return
        played = max(0, discard_now - discarded) + len(self._rd_face("human"))
        if real + played < before + n:
            if n == 1:
                self.say(t("deal.missing_one"), ChatKind.WARNING)
            else:
                self.say(t("deal.missing_n", n=n), ChatKind.WARNING)

    def _maneuver_boost(self, _: dict) -> None:
        """The "Boost" button of a human Maneuver: the boost card they put in their discard pile is recognised NOW, its
        BOOSTED WITH runs (choices on the panel) and only then do they move or place the pieces and press End action."""
        g = self.game
        if (g.winner is not None or g.turn != self.human or self.pending is not None or not self.moving
                or self.maneuver_baseline is None):
            self.say(t("maneuver.boost_none"), ChatKind.WARNING)
            return
        self.sync_human()
        _, saw_new = self._read_maneuver_boost()
        if not saw_new:
            self.say(t("maneuver.boost_none" if self.maneuver_boosted is not None else "maneuver.boost_no_card"), ChatKind.WARNING)

    def _read_maneuver_boost(self) -> tuple[bool, bool]:
        """Looks for the boost card among the cards that reached the human's discard pile since the Maneuver began.
        Returns (a boost was made now, there were new cards). A card without BOOST value (Liz's burning cards) boosts
        nothing (docs/heroes/liz-sherman.md): said once, the table is not corrected. One boost per Maneuver."""
        base = self.maneuver_baseline
        if base is None:
            return False, False
        new = [c for c in self.game.players[self.human].discard if c.card_id not in base]
        if not new:
            return False, False
        for c in new:
            if not can_be_boost(c):
                self.say(t("maneuver.no_boost_value", title=c.title), ChatKind.WARNING)
        spent = [c for c in new if can_be_boost(c)]
        if self.maneuver_boosted is not None:           # already boosted: another card is not a second boost
            boosted = next(c for c in self.game.players[self.human].full_set if c.card_id == self.maneuver_boosted)
            for c in spent:
                self.say(t("maneuver.boost_again", boosted=boosted.title, title=c.title), ChatKind.WARNING)
        elif len(spent) > 1:
            self.say(t("maneuver.boost_many", n=len(spent), titles=", ".join(c.title for c in spent)), ChatKind.WARNING)
            return False, True
        elif spent:
            self._apply_maneuver_boost(spent[0])
            self.maneuver_baseline = [*base, *(c.card_id for c in new)]
            return True, True
        self.maneuver_baseline = [*base, *(c.card_id for c in new)]
        return False, True

    def _apply_maneuver_boost(self, card: Card) -> None:
        """Announces the boost (and ESCAPE ARTIST when the hero has it), runs BOOSTED WITH, and leaves the action open."""
        g = self.game
        self.maneuver_boosted = card.card_id
        runs_effects = has_boost_effect(card) and g.fx.interprets(self.human)
        fx_first = t("maneuver.fx_first") if runs_effects else ""
        if g.fx.hero_rule(self.human, "maneuver_boost_places_hero"):
            self.say(t("maneuver.boosted_places", title=card.title, value=card.boost, hero=self._name(g.hero(self.human)),
                       fx=fx_first), ChatKind.YOUR_TURN)
        else:
            self.say(t("maneuver.boosted", title=card.title, value=card.boost, fx=fx_first), ChatKind.YOUR_TURN)
        if runs_effects:
            human_effects.maneuver_boost(self, card)      # BOOSTED WITH: its ops run now, like a scheme's
        if self._paused() is None and self.game.winner is None:
            self.say(t("maneuver.boost_then_end"), ChatKind.YOUR_TURN)

    def _announce_exhaustion(self, hp0: dict[str, float], alive0: dict[str, bool]) -> None:
        """Drawing with an empty deck hurts everyone: it is announced and written like any other damage."""
        g = self.game
        hurt = [f for fid, f in g.fighters.items() if f.hp != hp0[fid]]
        if not hurt:
            return
        self.say(t("exhaust.line", hp=self._hp_changes(hp0)), ChatKind.COMBAT)
        for f in hurt:
            if alive0[f.fid] and not f.alive:
                self._announce_fall(f)
        if g.winner is not None:
            self.say(t("game.over_fix", winner=g.winner))
            self._game_over_dialog()
        self._write_dials(post=True)
        self._drop_pending_if_gone()

    def _scheme(self, _: dict) -> None:
        if not self._require_human_turn():
            return
        self._begin_action()
        self.game.use_action()
        self.moving = True
        self.scheme_baseline = [c.card_id for c in self.game.players[self.human].discard]
        if self._resolve_human_scheme(wait=not self.cfg.batch):
            if self._paused() is None:
                self.say(t("sess.press_end"), ChatKind.YOUR_TURN)
        else:
            self.say(t("scheme.prompt"), ChatKind.YOUR_TURN)

    def _resolve_human_scheme(self, wait: bool) -> bool:
        """Waits (bounded) for the human's scheme card to appear face up in their discard pile, identifies it by
        the table's CardID and applies what needs no choice from the human. True if it found the card."""
        base = set(self.scheme_baseline or [])
        found: list[Card] = []

        def seen() -> bool:
            self.sync_human()
            found[:] = human_effects.recognize_scheme(self, base)
            return bool(found)
        if not (self._settle(seen) if wait else seen()):
            return False
        self.scheme_baseline = None
        discarding = [c for c in found if self._scheme_traits(c).get("discards_hand")]
        if discarding:                            # a card that discards the hand: the rest that appears is not a played scheme
            found[:] = discarding[:1]
        for c in found:
            self._apply_human_scheme(c)
            self._grant_look_for(c)
        self._write_dials(post=True)
        return True

    def _apply_human_scheme(self, c: Card) -> None:
        g = self.game
        if g.fx.interprets(self.human):               # E2: the interpreter, in table mode
            human_effects.play_scheme(self, c)
        elif (traits := self._scheme_traits(c)).get("discards_hand"):
            g.draw(self.human, traits["draw"])
            self.say(t("scheme.detect_discard", title=c.title, gain=self._gain_actions(scheme_gain_actions(c))), ChatKind.SCHEME)
        elif traits.get("bonus"):
            old = g.add_combat_bonus(self.human, traits["bonus"], c.title)
            if old is not None:
                self.say(t("scheme.replaces", title=c.title, old=old), ChatKind.SCHEME)
            total = g.combat_bonus_total(self.human)
            g.draw(self.human, traits["draw"])
            self.say(t("scheme.detect_bonus", title=c.title, bonus=traits["bonus"], total=total), ChatKind.SCHEME)
        elif traits.get("choose"):
            heal, choose = traits["heal"], traits["choose"]
            times = t({1: "scheme.times.one", 2: "scheme.times.two"}.get(heal, "scheme.times.other"), n=heal)
            count = t(NUMBER_TAGS[choose]) if choose in NUMBER_TAGS else choose
            self.say(t("scheme.detect_choose", title=c.title, count=count, hero=g.hero(self.human).name, heal=heal, times=times),
                     ChatKind.SCHEME)
        elif scheme_gain_actions(c):
            self.say(t("scheme.detect_gain", title=c.title, gain=self._gain_actions(scheme_gain_actions(c)), text=c.text), ChatKind.SCHEME)
        else:
            self.say(t("scheme.detect_plain", title=c.title, text=c.text), ChatKind.SCHEME)

    def _scheme_traits(self, card: Card) -> dict:
        """What the data of a human's scheme says about it (`ongoing.scheme_traits`), for the heroes the interpreter
        does not run: the legacy path reads it from the card's DSL, never from its title."""
        return ongoing.scheme_traits(self.game.players[self.human].hero.slug, card.title)

    def _gain_actions(self, n: int) -> str:
        """Grants the actions a scheme gives (the engine refuses them under Cold Iron And Holy Water) and says so."""
        g = self.game
        if not g.fx.can_gain_actions(self.human):
            return t("gain.blocked", n=n, left=g.actions_left)
        g.grant_actions(n)
        return tn("gain.ok", n, left=g.actions_left)

    def _value(self, payload: dict) -> None:
        raw = payload.get("value")
        if raw is None:
            raw = 0
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or abs(raw) > 100:
            self.say(t("value.invalid"), ChatKind.WARNING)
            return
        if self.pending is None:
            self.say(t("value.no_combat"), ChatKind.WARNING)
            return
        if self.pending.wait is not None:
            self.say(t("value.boost_read"), ChatKind.WARNING)
            return
        self.pending_value = int(raw)
        self.say(t("value.registered", value=self.pending_value))

    def _choose_attacker(self, payload: dict) -> None:
        if not self._require_human_turn():
            return
        self._check_may_attack()
        fid = str(payload.get("attacker", "")).removeprefix("att_")
        f = self.game.fighters.get(fid)
        if f is not None and f.owner == self.human and not f.alive:
            self.say(t("attack.dead", name=self._name(f)), ChatKind.WARNING)
            return
        if f is None or f.owner != self.human:
            self.say(t("attack.bad_attacker", value=repr(payload.get("attacker"))), ChatKind.WARNING)
            return
        self._try_flush_table()
        self.sync_positions()                     # what was moved outside an action (Wildfire at turn start) already counts
        self.chosen_attacker = fid
        self.say(t("attack.chosen", fid=fid), ChatKind.YOUR_TURN)

    def _attack(self, payload: dict) -> None:
        if not self._require_human_turn():
            return
        self._check_may_attack()
        if self.chosen_attacker is None:
            who = " / ".join(t("panel.attacker", name=self._name(f)) for f in self.game.own(self.human))
            self.say(t("attack.pick_first", who=who), ChatKind.WARNING)
            return
        target = self.game.fighters.get(str(payload.get("target", "")))
        if target is None or target.owner != self.bot or not target.alive:
            self.say(t("attack.bad_target", value=repr(payload.get("target"))), ChatKind.WARNING)
            return
        self._begin_action()
        if self.pending is not None:              # a play with a late reply: the card is already on the table
            if not self.pending.defended:
                self.say(t("attack.open"), ChatKind.WARNING)
            else:
                self.say(t("combat.bot_card_on_table"), ChatKind.WARNING)
            return
        attacker = self.game.fighters[self.chosen_attacker]
        if not self.game.can_attack(attacker, target):
            self.chosen_attacker = None
            raise RuleError(t("err.out_of_reach", attacker=attacker.fid, target=target.fid))
        self.pending = Pending("human_attacks", attacker, target, None, None, defended=False)
        self.chosen_attacker = None
        self.say(t("attack.declared", attacker=attacker.fid, target=target.fid), ChatKind.YOUR_TURN)
        carry, self.declared_carry = self.declared_carry, None
        if carry is not None and (carry["attacker"], carry["target"]) == (attacker.fid, target.fid):
            self.pending.declared = carry["declared"]     # the same attack again: declared already, nothing fires twice
            self.say(t("attack.intuition_carry"), ChatKind.ATTACK)
            return
        hidden.intuition_notice(self, target)

    def _bot_defends(self, p: Pending, attack_card: Card | None = None) -> None:
        """The bot decides and places its defense AFTER the human has committed, in the engine's order: first the
        `attacked` event (UNCANNY INTUITION spends the token and draws; the drawn card is dealt right away, so it
        can be the defense), then the defense. The decision uses only what the AI already knew (engine state and the
        bot's hand): never the CardID of the human's face-down card, except for the attack a rule plays face up
        (UNCANNY INTUITION, Perfect Shot), which is all it sees."""
        revealed = hidden.declare_attack(self, p, attack_card)
        self.read_bot_hand()
        if revealed is not None:
            card = self.ai.choose_defense(self.game, p.attacker, p.target, attack_card=revealed)
        else:
            card = self.ai.choose_defense(self.game, p.attacker, p.target)
        guid = self._place_bot_card(card, "human_attacks", p.attacker, p.target)
        p.bot_card, p.bot_card_guid, p.defended = card, guid, True

    def _cancel(self, _: dict) -> None:
        """Emergency exit from any pending human state.

        Unresolved human attack: returns the bot's card to its hand (after two failed attempts it is
        abandoned and the human is asked to place it by hand). Pending discard: annulled (the table resyncs by itself).
        Dirty bot table (unsettled debt): what the table shows is adopted. A bot attack is not
        cancelled: it is revealed, with no card if the human has no defense. A placed card whose reply arrived late
        (`placing`) is resolved first: if it landed it becomes the pending attack and is returned like any other."""
        if (paused := self._paused()) is not None:     # a card asks: "Cancel" is the answer that does nothing
            human_effects.decline(self, paused)       # (a forced pick, the bot's hand row included, is refused)
            return
        if self.look is not None:
            self._look_close()
            return
        if self.placing is not None:
            self._recover_placing()
        if self._drop_pending_if_gone():
            return
        p = self.pending
        if p is not None and p.wait is not None:
            if p.wait.extra["stuck"]:
                self._cancel_stuck_boost(p)
                return
            self.say(t("cancel.flipped"), ChatKind.WARNING)
            return
        if p is not None and p.kind != "human_attacks":
            self.say(t("cancel.bot_attack"), ChatKind.WARNING)
            return
        if p is not None:
            self._return_bot_card(p)
            self.pending, self.pending_value, self.chosen_attacker = None, 0, None
            self.say(t("cancel.done"))
            if p.declared is not None:            # Ivan (29/10): the token spent and the card drawn stand
                self.declared_carry = {"attacker": p.attacker.fid, "target": p.target.fid, "declared": p.declared}
                self.say(t("cancel.intuition_again", attacker=self._name(p.attacker), target=self._name(p.target)), ChatKind.ATTACK)
            return
        if self.pending_discard is not None:
            self.limit_waived = self.pending_discard["kind"] == "limit"
            self.pending_discard = None
            self.say(t("cancel.discard"))
            return
        if self.dirty or self.unprojected is not None or self.flush_failures:
            self.adopt_table()
            return
        if self.chosen_attacker is not None or self.pending_value:
            self.pending_value, self.chosen_attacker = 0, None
            self.say(t("cancel.selection"))
            return
        self.say(t("cancel.nothing"), ChatKind.WARNING)

    def _return_bot_card(self, p: Pending) -> None:
        if not p.bot_card_guid:
            return
        try:
            res = self._w(lua.return_card_to_hand(p.bot_card_guid, self.cfg.bot_seat), "cards").result or {}
            want = p.bot_card.card_id
            if not res.get("returned"):
                raise SessionError(t("err.return_card"))
            if not self._settle(lambda: want in self._table_hand_ids()):
                raise SessionError(t("err.card_not_back"))
        except TABLE_ERRORS:
            p.cancel_failures += 1
            if p.cancel_failures < 2:
                raise
            self.say(t("cancel.put_back", title=p.bot_card.title), ChatKind.WARNING)
        self.read_bot_hand()

    def _reveal(self, _: dict) -> None:
        p = self.pending
        if p is None:
            self.say(t("combat.none"), ChatKind.WARNING)
            return
        if self._drop_pending_if_gone():
            return
        if p.wait is not None:              # with the cards already turned there is nothing face down to look for
            self.say(self._boost_prompt(p), ChatKind.YOUR_TURN)
            return
        if self.placing is not None:              # defense placed whose reply arrived late: it is not placed twice
            self._recover_placing()
            p = self.pending
        g = self.game
        seen = self._rd_face("human")
        mine = {c.card_id: c for c in g.players[self.human].full_set}
        theirs = [r for r in seen if r["id"] in mine]  # by CardID ownership, never by order
        if len(theirs) > 1:
            self.say(t("reveal.many", n=len(theirs)), ChatKind.WARNING)
            return
        face_up = False
        if not theirs:                            # a defense/attack left FACE UP before the Reveal is read as it lies
            theirs = [r for r in self._rd_combat_spot() if isinstance(r, dict) and r.get("id") in mine and r.get("guid")]
            if len(theirs) > 1:
                self.say(t("reveal.many", n=len(theirs)), ChatKind.WARNING)
                return
            face_up = bool(theirs)
        human_card = mine[theirs[0]["id"]] if theirs else None
        try:
            if p.kind == "human_attacks":
                if human_card is None:
                    raise RuleError(t("err.no_card_down"))
                g.check_attack_card(p.attacker, human_card)
                g.check_attack_target(p.attacker, p.target, human_card)
                if not p.defended and hidden.ask_prediction(self, p, human_card):
                    return                        # Perfect Shot: the human predicts before the bot defends
                if not p.defended:
                    self._bot_defends(p, human_card)
                if p.bot_card:
                    g.check_defense_card(p.target, p.bot_card)
            else:
                g.check_attack_card(p.attacker, p.bot_card)
                if human_card:
                    g.check_defense_card(p.target, human_card)
        except RuleError as e:
            self.say(t("reveal.illegal", err=e), ChatKind.WARNING)
            return
        human_guid = theirs[0]["guid"] if theirs else None
        if face_up:
            self.say(t("reveal.face_up", card=human_card.title), ChatKind.COMBAT)
        granted = p.bot_card is not None and grants_boost(p.bot_card)
        if human_card is not None and (can_boost(human_card) or granted):      # your attack (Second Shot), your defense (Out Of Time), a boost the bot's card allows
            if p.bot_card is not None and is_medusa_card(p.bot_card) and p.bot_card.title == FEINT:
                self.say(t("reveal.feint", bot=p.bot_card.title, card=human_card.title), ChatKind.COMBAT)
            elif boost_session.offered(self, p, human_card):
                self._await_boost(p, human_card, human_guid)
                return
            else:                                 # the rival's IMMEDIATELY cancels the card's effect, the boost with it
                self.say(t("reveal.boost_cancelled", card=human_card.title, bot=p.bot_card.title), ChatKind.COMBAT)
        self._resolve_combat(p, human_card, human_guid, flip=True, boost=None)

    def _await_boost(self, p: Pending, card: Card, guid: str | None) -> None:
        """Both cards are turned and the combat is left half-done: the BOOST is played AFTER revealing. Exit:
        Continue (reads the new card from the discard) or No boost; Cancel no longer works with the cards turned."""
        own = {c.card_id for c in self.game.players[self.human].full_set}
        baseline = sorted({r["id"] for r in self._rd_human_discard()} & own)
        cards = [(p.bot_card_guid, "bot"), (guid, "human")]
        self._flip_all(cards)
        self._flip_queued(cards)
        p.wait = PendingChoice("boost", self.human, card.card_id, deck_boost(card),
                               {"guid": guid, "baseline": baseline, "hand": self._rd_human_count(-1), "stuck": False})
        if p.wait.deck:
            self.say(t("boost.revealed_deck", title=card.title), ChatKind.YOUR_TURN)
        elif boost_limit(card) > 1:
            self.say(t("boost.revealed_many", title=card.title, n=boost_limit(card)), ChatKind.YOUR_TURN)
        else:
            self.say(t("boost.revealed", title=card.title), ChatKind.YOUR_TURN)

    def _boost(self, _: dict) -> None:
        self._finish_boost(True)

    def _no_boost(self, _: dict) -> None:
        self._finish_boost(False)

    def _boost_prompt(self, p: Pending) -> str:
        if p.wait.extra["stuck"]:
            return t("boost.stuck")
        return t("boost.prompt_deck" if p.wait.deck else "boost.prompt")

    def _finish_boost(self, use: bool) -> None:
        p = self.pending
        if p is None or p.wait is None:
            self.say(t("boost.none"), ChatKind.WARNING)
            return
        if self._drop_pending_if_gone():
            return
        mine = {c.card_id: c for c in self.game.players[self.human].full_set}
        card, boost = mine[p.wait.card_id], None
        if use:
            seen = {r["id"] for r in self._rd_human_discard() if r["id"] in mine}
            new = sorted(seen - set(p.wait.extra["baseline"]) - {card.card_id})
            limit = max(boost_limit(card), 1)       # a card that says "boost this card twice" takes up to that many
            if not new:
                self.say(t("boost.no_new"), ChatKind.WARNING)
                return
            if len(new) > limit:
                self.say(t("boost.many_new" if limit == 1 else "boost.many_new_max", n=len(new), max=limit,
                           titles=", ".join(mine[i].title for i in new)), ChatKind.WARNING)
                return
            before, now = p.wait.extra["hand"], self._rd_human_count(-1)
            if p.wait.deck:          # Flame Lash: comes from the bottom of the deck, the hand does not change
                before = -1
            if isinstance(before, int) and before >= 0 and now >= 0 and now != before - len(new):
                self.say(t("boost.from_hand", before=before, now=now, expected=max(before - len(new), 0)), ChatKind.WARNING)
                return
            spent = [mine[i] for i in new]
            if not p.wait.deck and (bad := next((c for c in spent if not can_be_boost(c)), None)) is not None:
                self.say(t("boost.no_value", title=bad.title), ChatKind.WARNING)
                return
            boost = spent if len(spent) > 1 else spent[0]
        self.sync_positions()                     # the table rules: something may have moved while waiting
        self._resolve_combat(p, card, p.wait.extra["guid"], flip=False, boost=boost)
        p = self.pending                          # a refused combat restores the snapshot: a rebuilt Pending
        if p is not None and p.wait is not None:
            p.wait.extra["stuck"] = True          # the engine rejected it: Cancel becomes the exit

    def _cancel_stuck_boost(self, p: Pending) -> None:
        """Exit from a combat stuck after revealing: both cards go back face down, the bot's to its hand and the
        action is not spent. You pick up your own card."""
        self._unflip([(p.bot_card_guid, "bot"), (p.wait.extra["guid"], "human")])
        self._return_bot_card(p)
        self.pending, self.pending_value, self.chosen_attacker = None, 0, None
        self.say(t("cancel.stuck"))

    def _resolve_combat(self, p: Pending, human_card: Card | None, human_guid: str | None, flip: bool,
                        boost: Card | list | None) -> None:
        """Runs the combat. A card effect may stop it at a decision of the human: the combat stays in `p.flow`
        (saved) with the choice on the panel, and `_after_combat` closes it when the flow ends. If the engine refuses
        it, everything returns to the snapshot taken before (the action is not spent, the cards go back)."""
        g = self.game
        flip_cards = [(p.bot_card_guid, "bot"), (human_guid, "human")]
        flipped = self._flip_all(flip_cards) if flip else []
        self.combat_guids = {human_card.card_id: human_guid} if human_card is not None and human_guid else {}
        value = self.pending_value
        saved = self.to_dict()
        boosts = [] if boost is None else list(boost) if isinstance(boost, list) else [boost]
        p.combat = {"flip": flip, "human_guid": human_guid, "bot_seen": len(g.players[self.bot].discard),
                    "alive_before": self._alive_map(), "before": self._snapshot_bot(),
                    "boost": None if not boosts else boosts[0].card_id}
        if len(boosts) > 1:
            p.combat["boosts"] = [b.card_id for b in boosts]
        try:
            if human_card is not None:
                self.make_known(human_card)
                self._transit[human_card.card_id] = 0
            if boosts and deck_boost(human_card) and g.fx.interprets(self.human):
                human_effects.stage_bottom_card(self, boosts[0])      # Flame Lash's own DURING op discards it
            else:
                for b in boosts:
                    self.make_known(b, keep=(human_card, *boosts))
            p.combat["fx"] = bot_effects.snapshot(self)   # after the human's cards are known: the diff is the effects'
            if p.declared is not None:           # the `attacked` event already spent a token: project from before it
                p.combat["fx"]["counters"] = dict(p.declared["counters"])
            if p.kind == "human_attacks":        # `attacked` was raised when the bot chose its defense (`_bot_defends`)
                p.flow = g.begin_attack(p.attacker, p.target, human_card, p.bot_card, values=(value, 0),
                                        attacked=p.declared is None)
            else:
                p.flow = g.begin_attack(p.attacker, p.target, p.bot_card, human_card, values=(0, value),
                                        attacked=p.declared is None)
            p.wait = None                         # the boost (if any) is now an answer inside the flow
            self._drive_flow(p.flow)
        except RuleError as e:
            self._undo_combat(saved, human_card, flipped)
            if self.pending.wait is not None:
                self.say(t("combat.cant_resolve", err=e), ChatKind.WARNING)
            else:
                self.say(t("reveal.illegal_fix", err=e), ChatKind.WARNING)
            return
        except Exception:
            self._undo_combat(saved, human_card, flipped)
            raise
        self._combat_step_done(p)

    def _combat_step_done(self, p: Pending) -> None:
        """After driving the flow: close the combat, or project what the bot already did (moves, a boost to the
        discard) so that a save taken at the pause matches the table a resume reads."""
        if p.flow.done:
            self._after_combat(p, p.flow.result)
            return
        if self.cfg.batch and p.combat["flip"] and not p.combat.get("flipped"):
            # the combat stops at a choice of the human: both cards are turned now, in this same message (Ivan, 30/10),
            # not at the end of the combat, so he sees what is being resolved
            self._flip_queued([(p.bot_card_guid, "bot"), (p.combat["human_guid"], "human")])
            p.combat["flipped"] = True
        fin_swap = sleight.bot_swap(self, p)         # Sleight Of Hand: after the reveal, before the result is told
        self._mark_dirty(_bot_snapshot(p.combat["before"]))
        fin_dials = self._tell_damage_dealt(p)
        if self._table_gate(p):
            self._tell_human_effects(p)
        cause = t("cause.combat_effects") if human_effects.human_ran(p.flow) else None
        fin_fx = self._project_effects(p.combat.get("fx"), self._human_played(p), cause)
        self._try_flush_table()
        fin_dials()
        fin_swap()
        fin_fx()
        p.combat["before"], p.combat["fx"] = self._snapshot_bot(), bot_effects.snapshot(self)
        if (wait := p.flow.pending) is not None and wait.kind == "effect" and wait.player == self.human:
            self._show_choice(p.flow.awaiting_run.awaiting)
        elif self._table_gate(p):
            self.moving = True
            nxt = p.flow.sides[p.flow.side_idx].card.title
            self.say(t("combat.table_gate", next=nxt), ChatKind.YOUR_TURN)

    @staticmethod
    def _table_gate(p: Pending | None) -> bool:
        """The combat waits at an AFTER gate: the human's step on their hand comes before the next effect."""
        return p is not None and p.flow is not None and p.flow.pending is not None and p.flow.pending.kind == "table"

    def _tell_human_effects(self, p: Pending) -> None:
        """"Your card: ..." of the effects the human's card has already resolved (`p.combat["told"]["human_fx"]` counts
        what was said, so the end of the combat and a resume say only the rest)."""
        told = p.combat["told"]
        for e in p.flow.result.human_effects[told.get("human_fx", 0):]:
            self.say(t("sess.trigger.card", line=e), ChatKind.YOUR_TURN)
        told["human_fx"] = len(p.flow.result.human_effects)

    def _release_table_gate(self) -> None:
        """End action at an AFTER gate: the table is read (the engine's hand follows what the human did), then the
        next effect runs on that hand."""
        p = self.pending
        self._flush_table()
        self.sync_positions()
        self.sync_human()
        self.moving = False
        if self._guarded(lambda: (p.flow.resume(None), self._drive_flow(p.flow))):
            self._combat_step_done(p)

    def _tell_damage_dealt(self, p: Pending) -> Callable[[], bool]:
        """Ivan, 31/10 (Rekindle): the damage is dealt at the reveal and the combat then waits at a choice of the human
        in AFTER; the result must not wait with it. The first time the flow stops in AFTER, the summary, the bot's card
        lines and the health dials come out now (`p.combat["told"]` remembers what, so the end of the combat and a
        resume from a save say only the rest). A stop before AFTER (DURING) holds the damage back: nothing is told.
        Returns the function that verifies the dials."""
        c, g = p.combat, self.game
        if p.flow.phase is not Phase.AFTER or "told" in c:
            return lambda: True
        res, bot = p.flow.result, g.players[self.bot]
        first = len(self.messages)
        self.say(self._combat_text(p, res), ChatKind.COMBAT)
        pending = [(card, why) for card, why in ((res.atk_card, t("cause.attack")), (res.def_card, t("cause.defense")))
                   if card is not None and card in bot.full_set and card not in bot.discard]    # leave at the end of the flow
        reasons = {card.card_id: why for card, why in pending}
        for i in self._bot_boost_ids(p):
            reasons[i] = t("cause.combat_boost")
        listed = [self._discard_list(c["bot_seen"], reasons, t("cause.effect"))] + [t("combat.discard_item", title=card.title, why=why) for card, why in pending]
        if line := ", ".join(x for x in listed if x):
            self.say(t("combat.bot_discards", list=line))
        for e in res.applied:
            self.say(t("combat.applied", text=e), ChatKind.WARNING)
        for e in res.bot_notes:
            self.say(e, ChatKind.WARNING)
        for fid, was in c["alive_before"].items():
            f = g.fighters[fid]
            if was and not f.alive and f.owner == self.human:
                self._announce_fall(f)
            c["alive_before"][fid] = f.alive
        c["told"] = {"ids": [card.card_id for card in bot.discard[c["bot_seen"]:]] + [card.card_id for card, _ in pending],
                     "applied": len(res.applied), "notes": len(res.bot_notes)}
        if p.kind == "bot_attacks" or self._bot_answer_moves(c, reasons):
            self._announce_before(first)
        return self._write_dials(defer=True)

    def _bot_answer_moves(self, c: dict, reasons: dict[int, str]) -> bool:
        """The bot answered the human's attack with something that writes its own side of the table beyond the cards
        it played: a card it discarded for an effect (Incinerate's price, a cost) or a piece an effect moved. Its
        defense, the damage it takes and the human's own pieces need no pause."""
        g = self.game
        if any(card.card_id not in reasons for card in g.players[self.bot].discard[c["bot_seen"]:]):
            return True
        return any(was and g.fighters[fid].alive and g.fighters[fid].pos != pos
                   for fid, (pos, was) in _bot_snapshot(c["before"]).items())

    def _undo_combat(self, saved: dict, human_card: Card | None, flipped: list) -> None:
        self._restore(saved)
        self.combat_guids = {}
        if human_card is not None:
            self._transit.pop(human_card.card_id, None)
        self._unflip(flipped)

    def _after_combat(self, p: Pending, res) -> None:
        """The combat is over: the table shows it (flips, discards, dials) and the human resolves what is theirs."""
        g = self.game
        c = p.combat
        flip_cards = [(p.bot_card_guid, "bot"), (c["human_guid"], "human")]
        discarded_now = p.bot_card is not None and p.bot_card in g.players[self.bot].discard
        if discarded_now and c["flip"] and self.cfg.batch and not c.get("flipped"):
            self.zoom_ids.add(p.bot_card.card_id)         # not flipped on the table: the discard shows it instead
        if c["flip"] and not c.get("flipped"):
            self._flip_queued([(None if discarded_now and side == "bot" else guid, side) for guid, side in flip_cards])
        fin_swap = sleight.bot_swap(self, p)         # Sleight Of Hand: after the reveal, before the result is told
        self.pending, self.pending_value, self.chosen_attacker = None, 0, None
        said_first = len(self.messages)
        if self.pending_discard is not None:      # before any I/O: a table failure cannot leave it without a basis
            self.pending_discard["baseline"] = len(g.players[self.human].discard)
        self._mark_dirty(_bot_snapshot(c["before"]))
        told = c.get("told")                      # the result already went out when the flow stopped at a choice in AFTER
        if told is None:
            self.say(self._combat_text(p, res), ChatKind.COMBAT)
        reasons = {}
        for card, why in ((res.atk_card, t("cause.attack")), (res.def_card, t("cause.defense"))):
            if card is not None and card in g.players[self.bot].full_set:
                reasons[card.card_id] = why
        for i in self._bot_boost_ids(p):
            reasons[i] = t("cause.combat_boost")
        listed = self._discard_list(c["bot_seen"], reasons, t("cause.effect"), told=set(told["ids"]) if told else ())
        if listed:
            self.say(t("combat.bot_discards", list=listed))
        for e in res.applied[told["applied"] if told else 0:]:
            self.say(t("combat.applied", text=e), ChatKind.WARNING)
        for e in res.bot_notes[told["notes"] if told else 0:]:
            self.say(e, ChatKind.WARNING)
        for e in res.human_effects[(told or {}).get("human_fx", 0):]:   # your card: what the engine applied and what you do on the table
            self.say(t("sess.trigger.card", line=e), ChatKind.YOUR_TURN)
        for fid, was in c["alive_before"].items():
            f = g.fighters[fid]
            if was and not f.alive and f.owner == self.human:    # the bot's are removed by _project
                self._announce_fall(f)
        self._grant_look_for(res.atk_card if p.kind == "human_attacks" else res.def_card)
        self._track_destiny()
        if told is None and (p.kind == "bot_attacks" or self._bot_answer_moves(c, reasons)):
            self._announce_before(said_first)       # its attack resolved (or its answer to yours moved cards or pieces): said and held before the table moves
        cause = t("cause.combat_effects") if human_effects.human_ran(p.flow) else None
        fin_fx = self._project_effects(c.get("fx"), self._human_played(p), cause)
        fin_dials = self._write_dials(defer=True)
        fin_table = self._try_flush_stage()
        fin_dials()
        fin_table()
        fin_swap()
        fin_fx()
        if g.winner is not None:
            self.say(t("game.over", winner=g.winner))
            self._game_over_dialog()
            return
        self.moving = True
        if (paused := self._paused()) is not None and paused[0] == "parked" and paused[2].ctx.moment == "after_combat":
            self._show_choice(paused[2].awaiting)         # DARK PACT: asked right after the combat; `_effect_done` says the rest
            return
        self.say(t("combat.after"), ChatKind.YOUR_TURN)

    def _bot_boost_ids(self, p: Pending) -> set[int]:
        """The cards the bot spent as a boost in this combat, whichever side it was on (an attack's or a defense's)."""
        flow = p.flow
        ids = {i for side, spent in flow.boosted.items() for i in spent if (flow.att if side == "atk" else flow.tgt).owner == self.bot}
        card = flow.result.boost_card            # the interpreter's own boosts are all in `flow.boosted`; a legacy path's is here
        return ids | ({card.card_id} if card is not None and card in self.game.players[self.bot].full_set else set())

    def _combat_text(self, p: Pending, res) -> str:
        """Breakdown of where each total comes from: card played, bonuses and boost card, with their titles."""
        fighters = self.game.fighters                  # who fought: Smoke And Mirrors may have put the other one in
        attacker, target = self._name(fighters[res.attacker]), self._name(fighters[res.target])
        atk = t("combat.atk", who=attacker, parts=res.atk_parts[0]) + "".join(
            t("combat.join_and" if i == 0 else "combat.join_comma", part=part) for i, part in enumerate(res.atk_parts[1:]))
        if res.def_card is None:
            dfn = t("combat.no_def", who=target)
        else:
            dfn = t("combat.def", who=target, parts=res.def_parts[0]) + "".join(t("combat.join_comma", part=part) for part in res.def_parts[1:])
        return t("combat.line", atk=atk, atk_value=res.atk_value, dfn=dfn, def_value=res.def_value, damage=res.damage)

    def _intuition_range(self):
        """The counter range of the HUMAN's Intuition tokens (Abe Sapien), else None. The bot's Abe has real copies on
        the table (`translators._counter_bot`); the human's tokens are theirs to flip."""
        try:
            return load_effects(self.game.hero_def(self.human).slug).counters.get(INTUITION)
        except EffectError:
            return None

    def _track_intuition(self, announce: bool = False) -> None:
        """Tells in chat how many of the human Abe's Intuition tokens are active when the engine changes that count,
        and has the bot turn the physical tokens (`_turn_intuition_tokens`). `announce`: also say the current count
        (game start, resume)."""
        rng = self._intuition_range()
        if rng is None:
            return
        g, human = self.game, self.human
        now, prev = g.fx.counter_value(human, INTUITION, rng.start), self._intuition_said
        self._intuition_said = now
        name = self._name(g.hero(human))
        if prev is None or prev == now:
            if prev is None and announce:
                self.say(t("intuition.state", name=name, n=now, max=rng.max, dark=plural(rng.max - now, "noun.token")),
                         ChatKind.ABILITY)
            return
        self._turn_intuition_tokens(prev, now, name, rng.max)

    def _turn_intuition_tokens(self, prev: int, now: int, name: str, top: int) -> None:
        """The bot turns the human's physical Intuition tokens to match the engine (active face when one is activated,
        inactive when one is spent) and pings them. The table is read in the same script: a count that differs from
        `prev` is warned (the engine stays the authority) and tokens that cannot be found or turned are asked of the
        human by chat."""
        n = abs(now - prev)

        def ask(why: str, left: int = n, on: bool = now > prev) -> None:
            manual = "intuition.on_manual" if on else "intuition.off_manual"
            self.say(t(manual, name=name, tokens=plural(left, "noun.token"), n=now, max=top, why=why), ChatKind.ABILITY)

        try:
            table = load_hero_table(self.game.hero_def(self.human).slug)
            source, faces = table.tokens[INTUITION], table.token_faces[INTUITION]["faces"]
            script = lua.set_intuition_tokens(INTUITION_TOKEN, source, float(faces["active"]), float(faces["inactive"]), now,
                                              [self.cfg.human_seat, self.cfg.bot_seat])
        except (HeroTableError, KeyError, TypeError, ValueError):
            ask(t("intuition.why.nodata"))
            return
        op = self._w(script, translators.DOMAIN)

        def check() -> None:
            try:
                res = op.result or {}
            except translators.ERRORS:
                ask(t("intuition.why.write_failed"))
                return
            if not res.get("total"):
                ask(t("intuition.why.missing"))
                return
            before, after = res.get("active"), res.get("after")
            if before != prev:
                self.say(t("intuition.mismatch", name=name, table=before, engine=prev), ChatKind.WARNING)
            done = int(res.get("flipped") or 0)
            if after is not None and after != now:
                ask(t("intuition.why.partial"), abs(now - after), on=after < now)
            if done:
                # the direction is the table's own: with a table that disagrees, the engine's count can lie on the other side
                on = before < now if before is not None else now > prev
                self.say(t("intuition.turned_on" if on else "intuition.turned_off", name=name,
                           tokens=plural(done, "noun.token"), n=now, max=top), ChatKind.ABILITY)
            elif after == now:                    # the table already showed the engine's count: nothing to turn
                self.say(t("intuition.state", name=name, n=now, max=top, dark=plural(top - now, "noun.token")), ChatKind.ABILITY)
        self._post.append(check)

    def _darken_intuition_tokens(self) -> None:
        """After a restart: the human Abe's tokens left active by the last game go back to the dark side (the new game
        starts with none active)."""
        rng = self._intuition_range()
        if rng is None:
            return
        try:
            table = load_hero_table(self.game.hero_def(self.human).slug)
            source, faces = table.tokens[INTUITION], table.token_faces[INTUITION]["faces"]
            script = lua.set_intuition_tokens(INTUITION_TOKEN, source, float(faces["active"]), float(faces["inactive"]), rng.start,
                                              [self.cfg.human_seat, self.cfg.bot_seat])
        except (HeroTableError, KeyError, TypeError, ValueError):
            return
        op = self._w(script, translators.DOMAIN)

        def check() -> None:
            try:
                done = int((op.result or {}).get("flipped") or 0)
            except translators.ERRORS:
                return
            if done:
                self.say(t("intuition.reset", name=self._name(self.game.hero(self.human)), tokens=plural(done, "noun.token")),
                         ChatKind.ABILITY)
        self._post.append(check)

    def _track_destiny(self) -> bool:
        """Counts Hellboy's destinies in his discard pile (the engine equates them to the table's discard in sync_human),
        announces when they change and when the form changes. True if the dial does not yet reflect the count:
        `destiny_seen` only advances after a verified write (`_write_dials`), so a failure is retried on the next read."""
        g, owner = self.game, self._destiny_owner()
        if owner is None:
            return source_dial.stale(self)        # only the hero with a destiny counter (Hellboy) carries them; Ciri's Source dial rides along
        now = (g.destiny_count(owner), g.form(owner))
        said = self._destiny_said if self._destiny_said is not None else self.destiny_seen
        prev, self._destiny_said = said, now
        if not self.cfg.destiny_dial:
            self.destiny_seen = now               # without a dial there is nothing to verify
        if prev != now and owner == self.human:   # the bot's discards and its form change are announced where they happen
            self._announce_destiny(prev, now)
        return now != self.destiny_seen or source_dial.stale(self)

    def _destiny_owner(self) -> int | None:
        """The side whose hero keeps the destiny count (Hellboy, bot or human): the one dial counts for him."""
        g = self.game
        return next((p for p in (self.human, self.bot) if "destiny" in g.hero_def(p).counters), None)

    def _announce_destiny(self, prev: tuple[int, str] | None, now: tuple[int, str]) -> None:
        if prev is not None and prev[0] != now[0]:
            self.say(t("destiny.down", n=now[0], prev=prev[0]) if now[0] < prev[0] else t("destiny.up", n=now[0]), ChatKind.ABILITY)
        if prev is not None and prev[1] != now[1]:
            if now[1] == ANUNG:
                self.say(t("destiny.anung", n=now[0]), ChatKind.ABILITY)
            else:
                self.say(t("destiny.detective", n=now[0]), ChatKind.ABILITY)

    def _write_dials(self, only_destiny: bool = False, defer: bool = False, post: bool = False):
        """Writes the dials (see `_put_dials`). Every failure, wherever it comes from, leaves the `dial_debt` debt: the
        bot's turn turns it into a pause (`_pause_for_dials`) and `_bot_continue` settles it. A verified write of the
        life dials cancels it. With `defer` it returns the function that verifies (in fast mode the check shares a
        message with the other pending writes); with `post` the check waits for the button's closing (`_commit`) and
        shares its message: only for whoever does not need the result."""
        verify = self._put_dials(only_destiny)

        def done() -> bool:
            ok = verify()
            if not ok:
                self.dial_debt = True
            elif not only_destiny:
                self.dial_debt = False
            return ok
        if post and self.cfg.batch:
            self._post.append(done)
            return True
        if not defer:
            return done()
        if self.cfg.batch:
            return done
        ok = done()
        return lambda: ok

    def _put_dials(self, only_destiny: bool) -> Callable[[], bool]:
        """The engine rules: the life dials are set to the engine's life and the table is re-read to check it.
        Writes (or queues) and returns the function that checks: True if they were verified (or there was nothing).

        A dial the human touched by hand (it shows neither the last thing the engine wrote nor what is now due) is NOT
        overwritten: a warning is given and nothing is written; the human reconciles it with +1 / -1 (the engine counts) or by putting it back.
        It is the safe option: neither their correction is lost nor can a dial change the engine's state."""
        if not self.cfg.destiny_dial and not self.cfg.source_dial and (only_destiny or not self.cfg.dials):
            return lambda: True
        g = self.game
        dials = {} if only_destiny else self._live_dials()
        want = {guid: (max(0, math.ceil(g.fighters[fid].hp)) if g.fighters[fid].alive else 0)
                for fid, guid in dials.items()}
        label = {guid: self._name(g.fighters[fid]) for fid, guid in dials.items()}
        if self.cfg.destiny_dial:
            owner = self._destiny_owner()
            want[self.cfg.destiny_dial] = 0 if owner is None else g.destiny_count(owner)
            label[self.cfg.destiny_dial] = t("cause.destiny_dial")
        if self.cfg.source_dial:
            want.update(source_dial.want(self))
            label[self.cfg.source_dial] = source_dial.label()
        try:
            now = self._rd_dials(sorted(want))
            touched = [gd for gd, v in want.items() if self._hand_edited(gd, v, now)]
            if touched:
                self.say(t("dials.touched",
                           items="; ".join(t("dials.item", label=label[gd], mark=now[gd]["value"], want=want[gd]) for gd in touched),
                           advice=" ".join(t("dials.advice", label=label[gd], want=want[gd]) for gd in touched)), ChatKind.WARNING)
                for gd in touched:                # only that dial is respected: the others are written and checked
                    del want[gd]
            if want:
                self.dials_attempted.update(want)
                self._w(lua.set_health_dials(want), "dials")
                if self.cfg.batch:
                    self._dials_pending |= set(want)
        except TABLE_ERRORS as e:
            self.say(t("dials.update_fail", err=e), ChatKind.WARNING)
            return lambda: False

        def verify() -> bool:
            self._dials_pending -= set(want)
            if not want:
                return not touched
            seen: dict = {}

            def matches() -> bool:
                res = self._rd_dials(sorted(want))
                seen.update(res if isinstance(res, dict) else {})
                return all(isinstance((seen.get(gd) or {}).get("value"), (int, float))
                           and seen[gd]["value"] == v for gd, v in want.items())
            try:
                if not self._settle(matches):
                    bad = [t("dials.should", label=label[gd], want=want[gd]) for gd in want
                           if (seen.get(gd) or {}).get("value") != want[gd]]
                    self.say(t("dials.check_fail", bad="; ".join(bad)), ChatKind.WARNING)
                    return False
            except TABLE_ERRORS as e:
                self.say(t("dials.update_fail", err=e), ChatKind.WARNING)
                return False
            self.dials_written.update(want)
            owner = self._destiny_owner()
            if self.cfg.destiny_dial in want and owner is not None:
                self.destiny_seen = (want[self.cfg.destiny_dial], g.form(owner))
            source_dial.written(self, want)
            return not touched
        return verify

    def _hand_edited(self, guid: str, want: int, now) -> bool:
        """The dial shows something that is neither the last thing the engine wrote nor what is due to be written now."""
        value = (now.get(guid) or {}).get("value") if isinstance(now, dict) else None
        last = self.dials_written.get(guid)
        tried = self.dials_attempted.get(guid)
        return isinstance(value, (int, float)) and last is not None and value not in (last, want, tried)

    def _pause_for_dials(self) -> None:
        """A dial could not be written in the middle of the bot's turn: it stops here (the state is already saved) and
        asks the human to set it; End action resumes the turn. It never goes on silently."""
        self.dial_debt = True
        self._persist()
        self.say(t("dials.paused"), ChatKind.WARNING)

    def _hp_changes(self, before: dict[str, float], skip: str | tuple | list | None = None) -> str:
        """HP changes since `before`: 'Lobster Johnson from 6 to 3'. (ASCII: messages also go out by broadcast.)"""
        g = self.game
        skipped = (skip,) if isinstance(skip, str) else (skip or ())
        parts = [t("hp.part", name=self._name(f), before=before[fid], after=max(f.hp, 0)) for fid, f in g.fighters.items()
                 if fid not in skipped and fid in before and f.hp != before[fid]]
        return ", ".join(parts)

    def _hp_text(self, before: dict[str, float], skip: str | tuple | list | None = None) -> str:
        """The HP line of a step ('PV: Lobster Johnson de 6 a 3'), empty when nothing changed."""
        changes = self._hp_changes(before, skip)
        return t("hp.line", parts=changes) if changes else ""

    def _flip_script(self, guid: str, side: str, face_up: bool = True) -> str:
        ids = self.cfg.bot_card_ids if side == "bot" else self.cfg.human_card_ids
        zoom = self.zoom() if side == "bot" and face_up else None
        return lua.flip_card(guid, self.cfg.rot_y, face_up, ids, identity=self._identity(side), zoom=zoom)

    def _flip_all(self, cards: list[tuple[str | None, str]]) -> list[tuple[str, str]]:
        """Turns the cards (guid, side); if one fails the ones already turned are hidden again before the error spreads.
        In fast mode they are not turned here: `_flip_queued` queues them when the engine has already accepted the combat."""
        flipped: list[tuple[str, str]] = []
        if self.cfg.batch:
            return flipped
        try:
            for guid, side in cards:
                if guid:
                    self._w(self._flip_script(guid, side), "flip")
                    flipped.append((guid, side))
        except Exception:
            self._unflip(flipped)
            raise
        return flipped

    def _flip_queued(self, cards: list[tuple[str | None, str]]) -> None:
        if self.cfg.batch:
            for guid, side in cards:
                if guid:
                    self._w(self._flip_script(guid, side), "flip")

    def _unflip(self, cards: list[tuple[str | None, str]]) -> None:
        for guid, side in cards:
            if not guid:
                continue
            try:
                self._w(self._flip_script(guid, side, face_up=False), "flip").result
            except TABLE_ERRORS:
                self.say(t("unflip.fail"), ChatKind.WARNING)

    def _end_action(self, _: dict) -> None:
        if self.look is not None:                 # E3's reveal row has nothing to discard: everything goes back
            self._look_close(face_down=self.look.get("mode") != hidden.MODE_REVEAL)
            return
        if self._table_gate(self.pending):
            self._release_table_gate()
            return
        if self.pending is not None and not self._drop_pending_if_gone():
            self.say(t("end.finish_boost" if self.pending.wait is not None else "end.reveal_first"), ChatKind.WARNING)
            return
        if self.game.winner is not None:
            self.say(t("game.ended"), ChatKind.WARNING)
            return
        self._flush_table()                       # if the last attempt failed, it is retried before anything else
        if self.pending is not None:              # the card played with a late reply showed up on the table
            self.say(t("combat.bot_card_on_table"), ChatKind.WARNING)
            return
        self.sync_human()                         # first: the boost card in the pile tells sync_positions the hero was placed
        self.sync_positions()
        if self.scheme_baseline is not None and not self._resolve_human_scheme(wait=False):
            self.say(t("end.no_scheme"), ChatKind.WARNING)
        self.scheme_baseline = None
        if self._paused() is not None:            # the plan asks you something: the turn cannot end (nor its actions be counted) before the answer
            return
        if self.maneuver_baseline is not None:
            if self._read_maneuver_boost()[0]:
                return                                # old habit (boost card in the pile, End action): effects now, the action ends at the next End action
            self.maneuver_baseline, self.maneuver_boosted = None, None
        if self.ability_wait is not None:         # the table was read: your start-of-turn ability is done
            self.ability_wait = None
            self.say(t("end.ability_done"), ChatKind.ABILITY)
        self._check_dials()
        self.moving = False
        if self.pending_discard is not None and not self._discard_done():
            return
        owed_cause = (self.pending_discard or {}).get("draw_cause")
        self.pending_discard = None
        self._deal_owed_draws(owed_cause)         # the draws that came after the discard are dealt now
        if self.game.turn == self.bot:
            self._bot_continue()
        else:
            self._after_human_action()

    # ---------- HP and casualties from effects (the engine does not see them) ----------
    def _fighter_arg(self, payload: dict) -> Fighter | None:
        f = self.game.fighters.get(str(payload.get("fighter", "")))
        if f is None:
            self.say(t("fighter.bad", value=repr(payload.get("fighter"))), ChatKind.WARNING)
        return f

    def _name(self, f: Fighter) -> str:
        return self.cfg.nicknames.get(f.fid, f.fid)

    def _sidekicks(self) -> list[Fighter]:
        """The human's fighters that they place, not the bot (all but their hero)."""
        return [f for f in self.game.own(self.human, alive_only=False) if not f.hero]

    def _sidekick_names(self) -> str:
        names = [self._name(f) for f in self._sidekicks()]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + t("common.and") + names[-1] if names else ""

    def _after_hp_change(self, f: Fighter) -> None:
        g = self.game
        if not f.alive:
            self._announce_fall(f)
        if g.winner is not None:
            self.say(t("game.over_fix", winner=g.winner))
            self._game_over_dialog()
        self._write_dials(post=True)
        self._drop_pending_if_gone()

    def _drop_pending_if_gone(self) -> bool:
        """A pending combat whose attacker or target is no longer in play (Remove, HP, a casualty the bot did not see)
        cannot be resolved and no legal card fixes it: it is cancelled, the bot's card returns to its hand and the
        action is not spent. If the table fails when returning it, the combat goes on and any button retries."""
        p = self.pending
        if p is None or p.flow is not None or (p.attacker.alive and p.target.alive):
            return False
        gone = p.attacker if not p.attacker.alive else p.target
        self._return_bot_card(p)
        self.pending, self.pending_value, self.chosen_attacker = None, 0, None
        self.say(t("combat.gone", name=self._name(gone)), ChatKind.WARNING)
        return True

    def _hp(self, payload: dict) -> None:
        """Manual HP adjustment (damage or healing from card effects: Horseshoes, Posthumous Power, Pancakes!...)."""
        f = self._fighter_arg(payload)
        delta = payload.get("delta")
        if f is None:
            return
        if isinstance(delta, bool) or delta not in (1, -1):
            self.say(t("hp.bad_delta", delta=repr(delta)), ChatKind.WARNING)
            return
        g = self.game
        if delta < 0:
            if not f.alive:
                self.say(t("hp.out", name=self._name(f)), ChatKind.WARNING)
                return
            g.damage(f, 1, "manual")
        elif f.alive:
            g.heal(f, 1)
        elif not self._revive(f):
            return
        self.say(t("hp.now", name=self._name(f), hp=f.hp), ChatKind.COMBAT)
        self._after_hp_change(f)

    def _remove(self, payload: dict) -> None:
        """Removes a fighter killed by an effect (without going through the +1/-1)."""
        f = self._fighter_arg(payload)
        if f is None:
            return
        if not f.alive:
            self.say(t("hp.out", name=self._name(f)), ChatKind.WARNING)
            return
        self.game.damage(f, f.hp, "manual")
        self._after_hp_change(f)

    def _revive(self, f: Fighter, force: bool = False) -> bool:
        """Restores a fighter given for dead (an HP or casualty mistake) on the space where its miniature is."""
        info = self._table_pieces().get(f.fid) or {}
        buried = (f.owner == self.bot and f.died_at is not None and self.cfg.dead_spot is not None
                  and not self._on_board(info))      # the bot set it aside: it returns to the space where it fell
        if buried:
            taken = {o.pos for o in self.game.fighters.values() if o.alive and o is not f}
            pos = f.died_at if f.died_at not in taken else self.game.board.nearest_free(f.died_at, taken, f.died_at)
        elif self._on_board(info):
            pos = info["space"]
        elif force:
            pos = self.game.start_spaces[f.owner]
            self.say(t("revive.place", name=self._name(f), where=describe(self.game, pos, (f.fid,), self._name)), ChatKind.YOUR_TURN)
        else:
            self.say(t("revive.cannot", name=self._name(f)), ChatKind.WARNING)
            return False
        f.alive, f.hp, f.pos = True, 1, pos
        if f.hero and self.game.winner == 1 - f.owner:
            self.game.winner = None
            self.over_shown = False
        if buried:
            self._place_revived(f, self._name(f))
        return True

    def _undo_game_over(self, _: dict) -> None:
        g = self.game
        if g.winner is None:
            self.say(t("undo.none"), ChatKind.WARNING)
            return
        g.winner = None
        self.over_shown = False
        for f in g.fighters.values():
            if f.hero and not f.alive:
                self._revive(f, force=True)
        self.say(t("undo.done"))
        self._write_dials(post=True)
        self._drop_pending_if_gone()

    def _check_dials(self) -> None:
        """If life dials are configured, warns of discrepancies with the engine (changes nothing)."""
        if not self.cfg.dials:
            return
        try:
            guids = sorted(set(self.cfg.dials.values()) - self._dials_pending)   # those being written are verified by their write
            if self.cfg.batch and self.snap is not None:
                res = {g: (self.snap["dials"].get(g) or {"found": False}) for g in guids}   # without forcing the queue
            else:
                res = self._rd_dials(guids)
        except (TTSLuaError, OSError):
            return
        if not isinstance(res, dict):
            return
        for fid, guid in self._live_dials().items():
            if guid in self._dials_pending:
                continue
            f, info = self.game.fighters[fid], res.get(guid) or {}
            value = info.get("value")
            if f.alive and isinstance(value, (int, float)) and value != f.hp:
                self.say(t("dials.warn", name=self._name(f), value=value, hp=f.hp), ChatKind.WARNING)

    # ---------- the human's discards ----------
    def _owe_discard(self, n: int, reason: str) -> None:
        translators.translate(self, {"op": "discard", "player": self.human, "zone": "hand", "n": n, "reason": reason,
                                     "all": self.game.fx.whole_hand}, translators.Ctx())

    def _discard_human_hand(self, n: int, reason: str) -> int:
        """Crown Of Flame (Ivan, 30/10): the bot moves the human's whole hand to their discard pile, face up, and the
        engine follows with the cards the table reports (they become public). Returns how many cards are still left
        for the human to discard by hand: 0 when the table did it, else what it could not move (it is said, and the
        manual flow asks for them, so the game never stalls)."""
        c = self.cfg
        expected = n
        moved: list[int] = []
        count, failure = 0, None
        try:
            expected = self._rd_human_count(n)
        except TABLE_ERRORS as e:
            failure = str(e)
        if failure is None and expected > 0:
            try:
                res =self._w(lua.hand_to_discard(c.human_seat, c.human_discard_zone, c.human_card_ids,
                                                  identity=self._identity("human")), "cards").result
                res = res if isinstance(res, dict) else {}
                moved = [i for i in res.get("moved") or [] if isinstance(i, int)]
                count = res.get("count") if res.get("zone") is True and isinstance(res.get("count"), int) else 0
                if count != expected:
                    failure = t("discard.moved_n", count=count, expected=expected)
            except TABLE_ERRORS as e:
                failure = str(e)
        self._land_in_discard(set(moved))
        for i in moved:
            self._transit[i] = 0
        self.hand_discarded.update(moved)
        if moved:
            self._track_destiny()                # the discarded hand may hold destinies (and a change of form)
        if failure is not None:
            self.say(t("discard.hand_fail", failure=failure), ChatKind.WARNING)
            return max(0, n - count)
        self._trim_virtual_hand(0)
        if count:
            self.say(tn("discard.hand_done", count, reason=reason), ChatKind.SCHEME)
        return 0

    def _land_in_discard(self, ids: set[int]) -> None:
        """Cards the table shows in the human's discard pile: out of the engine's hand (or deck, its hand is virtual)
        and onto its pile; the bot stops counting on the ones it had seen in the hand."""
        st = self.game.players[self.human]
        by_id = {c.card_id: c for c in st.full_set}
        for i in sorted(ids & by_id.keys()):
            c = by_id[i]
            if c in st.discard:
                continue
            if c in st.hand:
                st.hand.remove(c)
            elif c in st.deck:
                st.deck.remove(c)
            st.discard.append(c)
            self.game.card_left_hand(self.human, c)     # if the bot had seen it in your hand, it stops counting on it

    def _human_wildfire(self) -> bool:
        """Liz (Wildfire): every burning card the human discards from their hand returns to it, so a forced discard
        may change neither their discard pile nor their hand on the table."""
        return any(p.get("effect") == "liz_wildfire_return_to_hand" for p in self.game.hero_def(self.human).passives)

    def _wildfire_hint(self) -> str:
        return t("wildfire.hint") if self._human_wildfire() else ""

    def _discard_done(self) -> bool:
        d, st = self.pending_discard, self.game.players[self.human]
        if d["kind"] == "limit":
            done = len(st.hand) <= self.game.hand_cap(self.human)
        else:
            if d["baseline"] is None:
                d["baseline"] = len(st.discard)
            # cards a bot effect discarded by name (D3) count once they are on the table pile
            named = d.get("cards") or []
            on_pile = {r["id"] for r in self._rd_human_discard()} if named else set()
            missing = [i for i in named if i not in on_pile]
            done = not missing and len(st.discard) - len(missing) >= d["baseline"] + d["n"]
            if missing:
                by_id = {c.card_id: c for c in st.full_set}
                self.say(t("discard.not_seen", titles=", ".join(by_id[i].title for i in missing if i in by_id)), ChatKind.WARNING)
                return False
        # Ivan's ruling (28/10): a burning card discarded for the end-of-turn hand limit stays in the discard (the one
        # exception to Wildfire), so the "it returned to my hand" leniency only applies to other forced discards
        wildfire = self._human_wildfire() and d["kind"] != "limit"
        if not done and wildfire and d.get("wildfire_asked"):
            # second time: the burning cards came back to the hand without passing through the table discard; believed
            self.say(t("wildfire.assumed"))
            return True
        if not done and wildfire:
            d["wildfire_asked"] = True
            self.say(t("wildfire.ask"), ChatKind.WARNING)
            return False
        if not done:
            self.say(t("discard.missing", n=d["n"]), ChatKind.WARNING)
        return done

    # ---------- turns ----------
    def _after_human_action(self) -> None:
        g = self.game
        if g.winner is not None or g.turn != self.human:
            return
        if g.actions_left > 0:
            self.say(t("turn.left", n=g.actions_left), ChatKind.YOUR_TURN)
            return
        if self.look_granted and self._look_epoch == self._epoch:    # granted by this very button: the look comes first
            self.say(t("turn.look_first"), ChatKind.YOUR_TURN)
            return
        hand = g.players[self.human].hand
        excess = len(hand) - self.game.hand_cap(self.human)
        if excess > 0 and self.limit_waived:      # the human annulled the discard: the engine does not demand it again
            self._trim_virtual_hand(self.game.hand_cap(self.human))
        elif excess > 0:
            self.pending_discard = {"n": excess, "baseline": None, "kind": "limit"}
            self.say(t("discard.limit", n=excess, limit=self.game.hand_cap(self.human)), ChatKind.YOUR_TURN)
            return
        self.limit_waived = False
        self.chosen_attacker = None
        before, fx_before = self._snapshot_bot(), bot_effects.snapshot(self)
        hp0 = {fid: f.hp for fid, f in g.fighters.items()}
        self._attack_announced = None             # a new turn: an identical attack is announced again
        g.end_turn()
        probe = self._wildfire_probe()
        g.begin_turn()                            # the turn change is atomic; what follows is only I/O
        self._turn_change_debt(before, fx_before)
        self.wildfire_scene = self._wildfire_outcome(probe)
        self.bot_stage = "start"
        self._persist()                           # checkpoint: the bot's turn starts here, only once
        self.say(t("turn.bot"))
        self._say_triggers()                      # your Pact at the end of your turn, before the bot starts
        if any(f.hp != hp0[fid] for fid, f in g.fighters.items()):
            self._write_dials()
        self._bot_continue()

    def start_bot_turn(self) -> None:
        before, fx_before = self._snapshot_bot(), bot_effects.snapshot(self)
        probe = self._wildfire_probe()
        self.game.begin_turn()
        self._turn_change_debt(before, fx_before)
        self.wildfire_scene = self._wildfire_outcome(probe)
        self.bot_stage = "start"
        self._persist()
        self._bot_continue()

    def _wildfire_probe(self) -> dict | None:
        """Called just before the bot's turn starts in the engine: Liz's WILDFIRE discards the bottom card of the deck
        and the result (damage or a move) is decided there. What it will be taken from, to show it on the table."""
        g, cfg = self.game, self.cfg
        hero = g.hero_def(self.bot)
        if cfg.wildfire_hold <= 0 or not any(t.get("id") == "wildfire_start" for t in hero.triggers):
            return None
        st = g.players[self.bot]
        if not st.deck:
            return None
        liz = g.hero(self.bot)
        return {"card": st.deck[-1].card_id, "pos": liz.pos, "hp": {f.fid: f.hp for f in g.fighters.values()}}

    def _wildfire_outcome(self, probe: dict | None) -> dict | None:
        """What the engine did for that Wildfire: the card (burning ones went back to the hand), the damage it dealt
        and where Liz moved."""
        if probe is None:
            return None
        g = self.game
        st = g.players[self.bot]
        card = next(c for c in st.full_set if c.card_id == probe["card"])
        liz = g.hero(self.bot)
        hits = [(f, probe["hp"][f.fid] - f.hp) for f in g.own(self.human, alive_only=False)
                if probe["hp"][f.fid] - f.hp > 0]
        return {"card": card, "burning": card in st.hand, "hits": hits,
                "from": probe["pos"], "to": liz.pos if liz.alive else probe["pos"]}

    def _wildfire_reveal(self, scene: dict) -> None:
        """Wildfire, step by step on the table (Ivan, 30/10): the bottom card goes face up onto the bot's discard and
        stays on show `wildfire_hold` seconds (the wait is inside the same TTS script: no extra message and no
        snapshot of a half-done table); the rest (the card back to the hand, the damage and its dial, Liz's move) is
        written by the usual projection right after, each step announced as it lands."""
        self.said_returns.clear()
        g, cfg = self.game, self.cfg
        st = g.players[self.bot]
        card, burning = scene["card"], scene["burning"]
        liz = self._name(g.hero(self.bot))
        slot = self._discard_slot(len(st.discard) if burning else [c.card_id for c in st.discard].index(card.card_id))
        first = t("wildfire.discard_burning" if burning else "wildfire.discard", liz=liz, title=card.title)
        self.say(first, ChatKind.ABILITY, shown=True)
        try:
            moved = self._w(lua.discard_cards([card.card_id], [slot], cfg.bot_discard_rot_y, identity=self._identity(),
                                              scope=self._scope(), id_range=cfg.bot_card_ids,
                                              zoom=self.zoom(), zoom_id=card.card_id), "cards")
            for chunk in lua.ascii_text(first):
                self._w(lua.broadcast(chunk, ChatKind.ABILITY), "misc")
            self._hold(cfg.wildfire_hold)
            if card.card_id not in ((moved.result or {}).get("moved") or []):
                self.say(t("wildfire.not_found", title=card.title), ChatKind.WARNING)
        except TABLE_ERRORS as e:
            self.say(t("wildfire.show_fail", err=e), ChatKind.WARNING)
        if burning and self.fx_unprojected is not None:     # for the projection it is now a discard going back to the hand
            zones = self.fx_unprojected["bot"]
            zones["deck"] = [i for i in zones["deck"] if i != card.card_id]
            zones["discard"] = zones["discard"] + [card.card_id]
            self.said_returns.add(card.card_id)
        for text, kind in self._wildfire_lines(scene, liz):
            self.say(text, kind, shown=True)
            if cfg.batch:
                for chunk in lua.ascii_text(text):
                    self._w(lua.broadcast(chunk, kind), "misc")

    def _wildfire_lines(self, scene: dict, liz: str) -> list[tuple[str, ChatKind]]:
        if scene["burning"]:
            lines = [(t("wildfire.burning", liz=liz), ChatKind.ABILITY)]
            lines += [(t("wildfire.hit", liz=liz, amount=amount, name=self._name(f)), ChatKind.COMBAT)
                      for f, amount in scene["hits"]]
            return lines
        steps = self.game.board.distance(scene["from"], scene["to"])
        if steps:
            return [(tn("wildfire.moves", steps, liz=liz), ChatKind.MOVE)]
        return [(t("wildfire.stays", liz=liz), ChatKind.MOVE)]

    def _turn_change_debt(self, before: dict, fx_before: dict) -> None:
        """The bot's start-of-turn triggers (Wildfire's discard and move, Hellboy's ANUNG discard and move, a draw)
        leave the same table debt as any of its actions, settled by `_bot_continue`'s first write; a turn change
        that moved nothing leaves none."""
        self.fx_unprojected = fx_before
        g = self.game
        self.start_line = (self._anung_start_text(before, fx_before["bot"]["discard"])
                            or self._detective_start_text(fx_before["drawn"])
                            or self._throw_start_text(fx_before["bot"]["discard"]))
        self.game_log.observe(g, self._name)      # the turn start and its triggers, not folded into the bot's actions
        if (before != self._snapshot_bot() or fx_before["bot"] != bot_effects.zones(g.players[self.bot])
                or g.drawn[self.bot]):
            self._mark_dirty(before)

    def _anung_start_text(self, before: dict, discard_before: list[int]) -> str | None:
        """What the bot's ANUNG UN RAMA start-of-turn trigger just did in the engine (discard 1, move Hellboy up to that
        card's BOOST), for the chat; None when it did not run (other form, other hero, empty hand)."""
        g = self.game
        if g.form(self.bot) != ANUNG or not any(t.get("id") == "anung_discard_move" for t in g.hero_def(self.bot).triggers):
            return None
        fuel = [c for c in g.players[self.bot].discard if c.card_id not in discard_before]
        if not fuel:
            return None
        hero = g.hero(self.bot)
        card = fuel[-1]
        if hero.alive and hero.pos != before[hero.fid][0]:
            return t("anung.start", title=card.title, boost=card.boost, name=self._name(hero),
                     where=describe(g, hero.pos, (hero.fid,), self._name))
        return t("anung.start_still", title=card.title, boost=card.boost, name=self._name(hero))

    def _throw_start_text(self, discard_before: list[int]) -> str | None:
        """What the bot's She-Hulk JUST THROW SOMETHING start-of-turn trigger just did in the engine (discard a card, deal its BOOST to a
        fighter in her zone), for the chat; None when it did not run (another hero, nothing thrown). The dial of the fighter it hit
        follows the engine like any other effect damage."""
        g = self.game
        if g.hero_def(self.bot).slug != "she-hulk":
            return None
        thrown = [c for c in g.players[self.bot].discard if c.card_id not in discard_before]
        if not thrown:
            return None
        return t("shehulk.throw", title=thrown[-1].title, boost=thrown[-1].boost, name=self._name(g.hero(self.bot)))

    def _detective_start_text(self, drawn_before: int) -> str | None:
        """What the bot's OCCULT DETECTIVE start-of-turn trigger just did in the engine (draw 2 when Hellboy starts the
        turn in the rival's starting zone), for the chat; None when it did not draw. The bot's choice to draw is the
        optional's default (accept), so a decline simply leaves no line."""
        g = self.game
        drew = g.drawn[self.bot] - drawn_before
        if drew <= 0 or g.form(self.bot) != DETECTIVE or not any(t.get("id") == "detective_draw" for t in g.hero_def(self.bot).triggers):
            return None
        if g.hero(self.bot).pos != g.start_spaces.get(self.human):
            return None                           # the trigger's own condition: a draw from anything else is not it
        return t("detective.start", n=drew)

    def _mark_dirty(self, before: dict | None = None) -> None:
        """The engine has already switched to the bot; until the table reflects it a debt remains that any button retries."""
        self.dirty = True
        if before is not None and self.unprojected is None:
            self.unprojected = before

    def _flush_table(self) -> None:
        """Projects and reconciles what the engine decided for the bot. Idempotent: if it fails, the debt remains.

        After `adopt_after` consecutive discrepancies between table and engine (SessionError) the table wins: it is adopted."""
        self._flush_table_stage()()

    def _flush_table_stage(self) -> Callable[[], None]:
        """Prepares (queues) the table flush and returns the function that checks it. This way, in fast mode, the
        dials and the cards share the same message; without `batch` everything happens now and the function does nothing."""
        checks: list[Callable[[], None]] = []
        try:
            self._recover_placing()
            if self.unprojected is not None:
                check = self._project_stage(self.unprojected)
                if self.cfg.batch:
                    checks += [check, self._forget_unprojected]
                else:
                    self.unprojected = None
            if self.dirty:
                checks.append(self._reconcile_stage())
                checks.append(self._forget_dirty)
        except SessionError:
            self._flush_failed()
            return lambda: None
        done = False

        def fin() -> None:
            nonlocal done
            if done:
                return
            done = True
            try:
                for c in checks:
                    c()
            except SessionError:
                self._flush_failed()
                return
            self.flush_failures = 0
        if self.cfg.batch:
            return fin
        fin()
        return lambda: None

    def _forget_unprojected(self) -> None:
        self.unprojected = None

    def _forget_dirty(self) -> None:
        self.dirty = False

    def _flush_failed(self) -> None:
        self.flush_failures += 1
        if self.flush_failures < self.cfg.adopt_after:
            raise
        self.adopt_table()

    def _card_on_spot(self, card_id: int) -> str | None:
        """GUID of the face-down card with that CardID at the bot's card spot, or None if the table does not show it."""
        for r in self._rd_face("bot"):
            if r["id"] == card_id:
                return r["guid"]
        return None

    def _discard_list(self, seen: int, reasons: dict[int, str], default: str, skip: Card | None = None,
                      told: set | tuple = ()) -> str:
        """'Snipe as attack, Dash as combat boost': the cards the bot has sent to the discard pile since there
        was `seen` in the pile, in the order they end up on the grid, each with its reason. `told`: ids already said."""
        return ", ".join(t("combat.discard_item", title=c.title, why=reasons.get(c.card_id, default))
                         for c in self.game.players[self.bot].discard[seen:] if c is not skip and c.card_id not in told)

    def _played_text(self, seen: int, reasons: dict[int, str], default: str, skip: Card | None = None) -> str:
        listed = self._discard_list(seen, reasons, default, skip)
        return t("bot.played_discards", list=listed) if listed else ""

    def _say_bot_action(self, act, seen: int, before: dict, hp0: dict[str, float], sig_before: tuple | None, actions0: int,
                        exhausting: bool, paused: bool, fx_before: dict | None = None) -> None:
        if exhausting:
            self.say(t("bot.exhaust", damage=EXHAUST_DAMAGE), ChatKind.COMBAT)
        if paused:        # the scheme asks you something: the panel shows it, the turn waits
            self.say(t("bot.plays", title=act.card.title) + self._played_text(seen, {}, t("cause.effect"), skip=act.card) + ".",
                     ChatKind.SCHEME)
        else:
            self.say(self._action_text(act, seen, before, hp0, sig_before, actions0, fx_before), ACTION_KIND.get(act.kind, ChatKind.MOVE))

    def _scheme_idle(self, act, sig_before: tuple | None) -> bool:
        """The scheme changed nothing but its own action (`play_signature`): cards of both players, pieces, ONGOINGs,
        statuses, modifiers, counters and draws."""
        return sig_before is not None and sig_before == play_signature(self.game, self.bot, act.card)

    def _action_text(self, act, seen: int, before: dict, hp0: dict[str, float], sig_before: tuple | None = None,
                     actions0: int | None = None, fx_before: dict | None = None) -> str:
        """What the bot did, with the name of the card played, the damage it did and where it moved each piece."""
        g = self.game
        moved = [t("bot.moved_item", name=self._name(g.fighters[fid]), where=describe(g, g.fighters[fid].pos, (fid,), self._name))
                 for fid, (pos, was_alive) in before.items()
                 if was_alive and g.fighters[fid].alive and g.fighters[fid].pos != pos]
        if act.kind in ("glance", "frenzy", "scheme"):
            title = act.card.title
            text = t("bot.plays", title=title) + self._played_text(seen, {}, t("cause.effect"), skip=act.card)
            healed = ()
            if act.kind == "scheme" and not moved and self._scheme_idle(act, sig_before) and not self._hp_text(hp0):
                gained = g.actions_left - (actions0 - 1)
                text += t("bot.no_effect") + (t("bot.only_action") if gained == 1 else "")
            elif act.kind == "scheme":
                healed = tuple(f.fid for f in g.own(self.bot) if f.hp > hp0[f.fid])
                done = [t("bot.heals", name=self._name(g.fighters[fid]), gained=g.fighters[fid].hp - hp0[fid], before=hp0[fid],
                          after=g.fighters[fid].hp) for fid in healed]
                done += bot_effects.scheme_cards(self, fx_before)
                text += ": " + t("common.and").join(done) if done else ""
            if act.kind == "glance":
                target = g.fighters[act.target]
                dealt = hp0[target.fid] - target.hp
                text += (t("bot.glance_dealt", dealt=dealt, name=self._name(target), before=hp0[target.fid], after=max(target.hp, 0))
                         if dealt else t("bot.glance_none", name=self._name(target)))
        else:
            boost = {act.boost.card_id: t("cause.maneuver_boost")} if act.boost is not None else {}
            text = t("bot.maneuvers") + self._played_text(seen, boost, t("cause.effect"))
        others = self._hp_text(hp0, skip=act.target if act.kind == "glance" else healed if act.kind == "scheme" else None)
        if act.kind == "maneuver" and not moved:
            text += t("bot.draws_idle")
        if act.kind == "maneuver" and act.boost is not None and has_boost_effect(act.boost) and self.boost_note is not None:
            text += self._boosted_with_text(act)
        return (text + (t("bot.moves", moved="; ".join(moved)) if moved else "") + (f". {others}" if others else "") + ".")

    def _note_boost(self, act, fx_before: dict, actions0: int) -> None:
        """Right after the engine ran the bot's Maneuver (before the table is written and the draws are dealt, which use
        the counters up): what the BOOSTED WITH of its boost card did to its own cards and actions."""
        g, self.boost_note = self.game, None
        if act.kind != "maneuver" or act.boost is None or not has_boost_effect(act.boost):
            return
        self.boost_note = {"drawn": g.drawn[self.bot] - fx_before["drawn"] - 1,          # the Maneuver's own draw is not the card's
                           "gained": g.actions_left - (actions0 - 1)}

    def _boosted_with_text(self, act) -> str:
        """' (draws 1 and gains 1 action)' after the Maneuver line: the card's trace on cards and actions; the hit points and
        the pieces it moved are told by the lines that follow. Empty when it left none."""
        note, parts = self.boost_note, []
        if note["drawn"] > 0:
            parts.append(t("bot.scheme_draws", n=note["drawn"]))
        if note["gained"] > 0:
            parts.append(tn("narr.gain_actions", note["gained"], verb=t("narr.v.gain.bot")))
        return t("bot.boosted_with", title=act.boost.title, what=t("common.and").join(parts)) if parts else ""

    def _recover_placing(self) -> None:
        """A card the bot put face down whose reply never arrived (timeout after running): if it is at its
        card spot it counts as played and the combat is resumed; if it does not show up, it never left the hand."""
        it = self.placing
        if it is None:
            return
        found: dict = {}

        def on_spot() -> bool:
            found["guid"] = self._card_on_spot(it["card"])
            return found["guid"] is not None
        landed = self._settle(on_spot)
        self.placing = None
        if landed:
            card = next(c for c in self.game.players[self.bot].full_set if c.card_id == it["card"])
            fighters = self.game.fighters
            self.pending = Pending(it["kind"], fighters[it["attacker"]], fighters[it["target"]], card, found["guid"])
            self.read_bot_hand()
            self.say(t("bot.card_down", title=card.title), ChatKind.WARNING)

    def _log_decision(self, act) -> None:
        """Replay aid: the bot's hand, its hero's space and the chosen action, written only to the local game log.
        The hand is secret, so this never goes through `say` (chat, broadcast, human-visible messages)."""
        try:
            self._write_decision(act)
        except Exception as exc:  # a replay aid must never break the bot turn
            print(f"decision log skipped: {exc!r}")

    def _write_decision(self, act) -> None:
        g = self.game
        hand = ", ".join(c.title for c in g.players[self.bot].hand)
        parts = [act.kind]
        if act.fid:
            parts.append(act.fid)
        if act.target:
            parts.append(f"-> {act.target}")
        if act.card is not None:
            parts.append(f"card={act.card.title}")
        if act.moves:
            parts.append(f"moves={act.moves}")
        if act.spot is not None:
            parts.append(f"spot={act.spot}")
        self.game_log.line(f"BOT DECISION: hand=[{hand}] hero@{g.hero(self.bot).pos} action: {' '.join(parts)}")

    def _bot_continue(self) -> None:
        """Resumable bot turn: each I/O step that fails leaves the state ready to repeat End action.

        Checkpoints (saved to disk): at the start of the turn, after Medusa's ability and after each action,
        so that a cut or a resumed Ctrl+C repeats nothing already done."""
        g = self.game
        if self.first_turn_pending and g.turn == self.bot and self.bot_stage == "start":
            self._start_first_turn()              # a table error at game start skipped it
        self._revoke_look_after_button()
        if self.start_line is not None:          # said, held, and only then the start-of-turn discard, move or draw reach the table
            said_first, line, self.start_line = len(self.messages), self.start_line, None
            self.say(line, ChatKind.ABILITY)
            self._announce_before(said_first)
        scene, self.wildfire_scene = self.wildfire_scene, None
        if scene is not None and self.bot_stage != "start":
            scene = None
        if scene is not None:
            self._wildfire_reveal(scene)
        fin_fx, self.fx_unprojected = self._project_effects(self.fx_unprojected), None
        gadget_token.track(self)                  # the token moves in the same flush as the gadget announcement
        if scene is None:
            self._flush_table()
            fin_fx()
        else:       # one message for the card back in the hand, the damage and its dial, and Liz's move
            try:
                fin_dials = self._write_dials(defer=True) if scene["hits"] else None
                fin_table = self._flush_table_stage()
                self._flush()
                fin_table()
                fin_fx()
                if fin_dials is not None:
                    fin_dials()
            finally:                  # a failed flush must not leave a flag that silences a later real "recovers" line
                self.said_returns.clear()
        if self.pending is not None:
            self.say(t("combat.bot_card_on_table"), ChatKind.WARNING)
            return
        if self.dial_debt:                        # resumed after a pause over a dial that could not be written
            self.dial_debt = False
            if not self._write_dials():
                self.say(t("dials.still_off"), ChatKind.WARNING)
        if self._paused() is not None:            # a start-of-turn trigger asked you something (FATEFUL BARGAINS)
            self.fx_unprojected = bot_effects.snapshot(self)
            self._persist()
            self._show_choice(self.effect_run.awaiting)
            return
        if self.bot_stage == "start":
            self.sync_positions()
            self.sync_human()
            self.read_bot_hand()
            target = self.ai.pick_ability_target(g) if self._bot_ability_coded() else None
            self.bot_stage = None
            if target:
                hp0, alive0 = target.hp, self._alive_map()
                g.use_ability(self.bot, GAZE, target)
                gaze = t("medusa.gaze", name=self._name(target), before=hp0, after=max(target.hp, 0))
                if self.cfg.action_announce_hold > 0:      # said, held, and only then the dial moves
                    said_first = len(self.messages)
                    self.say(gaze, ChatKind.ABILITY)
                    self._announce_before(said_first)
                dials_ok = self._write_dials()        # first the dial and its verification, then the announcement
                if self.cfg.action_announce_hold <= 0:
                    self.say(gaze, ChatKind.ABILITY)
                self._announce_human_falls(alive0)
                self._persist()
                if not dials_ok:
                    self._pause_for_dials()
                    return
                self._bot_breath()
            self._persist()
        while g.actions_left > 0 and g.winner is None:
            with self._timed(t("timing.bot_action")):
                self.read_bot_hand()
                act = self.ai.plan(g)
                self._log_decision(act)
                if act.kind == "attack":
                    attacker, target = g.fighters[act.fid], g.fighters[act.target]
                    announced = self.cfg.action_announce_hold > 0
                    attack = (attacker.fid, target.fid, act.card.card_id if act.card else None)
                    if announced and self._attack_announced != attack:    # said, the card goes down a pause later
                        said_first = len(self.messages)
                        self.say(t("bot.attacks", attacker=attacker.fid, target=target.fid), ChatKind.ATTACK)
                        self._announce_before(said_first)
                        self._attack_announced = attack       # a failed placement retried by End action does not say it again
                    guid = self._place_bot_card(act.card, "bot_attacks", attacker, target)
                    self._attack_announced = None
                    self.pending = Pending("bot_attacks", attacker, target, act.card, guid)
                    hidden.bot_attack_placed(self, self.pending)     # Perfect Shot / UNCANNY INTUITION: face up
                    self._persist()
                    self.say(t("attack.defend_now") if announced else t("attack.bot_defend", attacker=attacker.fid, target=target.fid),
                             ChatKind.ATTACK)
                    return
                before = self._snapshot_bot()
                seen = len(g.players[self.bot].discard)
                hp0 = {fid: f.hp for fid, f in g.fighters.items()}
                alive0 = self._alive_map()
                exhausting = act.kind == "maneuver" and not g.players[self.bot].deck
                fx_before = bot_effects.snapshot(self)
                actions0 = g.actions_left
                sig_before = play_signature(g, self.bot, act.card) if act.kind == "scheme" else None
                if act.kind in ("scheme", "glance", "frenzy"):
                    self.zoom_ids.add(act.card.card_id)       # the human reads it when it leaves the hand for the discard
                self.ai.execute(g, act)
                self._note_boost(act, fx_before, actions0)
                self._mark_dirty(before)
                self._persist()
                paused = self._paused() is not None
                said = False
                if act.kind == "scheme" or self.cfg.action_announce_hold > 0:   # the play comes first, then what the table does for it
                    said = True
                    said_first = len(self.messages)
                    self._say_bot_action(act, seen, before, hp0, sig_before, actions0, exhausting, paused, fx_before)
                    self._announce_before(said_first)
                fin_fx = self._project_effects(fx_before)
                fin_table = self._flush_table_stage()
                dials_ok = self._write_dials(defer=True)()    # a single message for cards, pieces, effects and dials
                fin_table()
                fin_fx()
                if paused:
                    if not said:
                        self._say_bot_action(act, seen, before, hp0, sig_before, actions0, exhausting, paused, fx_before)
                    self.fx_unprojected = bot_effects.snapshot(self)
                    self._persist()
                    self._show_choice(self.effect_run.awaiting)
                    return
                self._persist()
                if not said:                      # the dials are written and checked before the announcement
                    self._say_bot_action(act, seen, before, hp0, sig_before, actions0, exhausting, paused, fx_before)
                self._announce_human_falls(alive0)
                if not dials_ok:
                    self._pause_for_dials()
                    return
            if g.winner is None:
                self._bot_breath()                # between actions and also before the "Your turn"
        if g.winner is not None:
            self.say(t("game.over", winner=g.winner))
            self._game_over_dialog()
            return
        seen = len(g.players[self.bot].discard)
        fx_before = bot_effects.snapshot(self)
        in_play = g.fx.ongoing_card_id(self.human)
        hp0 = {fid: f.hp for fid, f in g.fighters.items()}
        self._attack_announced = None
        g.end_turn()                              # may discard for hand limit: that is also a table debt
        hurt_at_end = any(f.hp != hp0[fid] for fid, f in g.fighters.items())      # Pact Of Peace hurts who attacked
        expired = g.begin_turn()
        if len(g.players[self.bot].discard) > seen:
            self.say(t("combat.bot_discards", list=self._discard_list(seen, {}, t("cause.hand_limit"))))
        self._mark_dirty()
        self._persist()
        for n, label in (expired if in_play is None else []):      # a DSL card in play is said by `left_play`
            self.say(t("scheme.expired", label=label, n=n), ChatKind.SCHEME)
        self._say_triggers()                      # your Pact at the end of the bot's turn, before "Your turn"
        self._announce_human_start()
        try:
            fin_fx = self._project_effects(fx_before, cause=t("cause.expired"))   # the bot's form, your ONGOING that expired
            self._flush_table()
            fin_fx()
            if self._track_destiny() or hurt_at_end:      # a hand-limit discard may hold a destiny card
                self._write_dials()
        except TABLE_ERRORS as e:
            self.say(t("turn.late", err=e), ChatKind.WARNING)

    def _bot_breath(self) -> None:
        """Pause after a bot action so the table is seen moving step by step and not all at once. It is a Python
        sleep, not a message: a `Wait.time` inside the composite would not separate distinct actions (each is its own
        message) and an extra message would cost ~0.5 s, more than the pause itself. It sits outside the action's
        `_timed` measurement so `--timing` keeps reporting what the messages cost."""
        if self.cfg.bot_pause > 0:
            time.sleep(self.cfg.bot_pause)

    def _announce_human_start(self) -> None:
        """Your turn. A start-of-turn ability the engine leaves to the table (Hellboy's draw / ANUNG discard and
        move, Wildfire's bottom card) is said and waited for: only End action (and the hit-point buttons) work
        until you have done it (Ivan, 29/10)."""
        g = self.game
        if self.first_turn_pending and g.turn == self.human:
            self._start_first_turn()              # a table error at game start skipped it
        self._warned.discard((g.hero(self.human).fid, "draw"))
        form = g.form(self.human)
        self.say(t("turn.yours") if g.hero_def(self.human).forms is None else t("turn.yours_form", form=form), ChatKind.YOUR_TURN)
        self.ability_wait = human_effects.start_of_turn_ability(self)
        if self.ability_wait is not None:
            self.say(t("turn.ability_wait", wait=self.ability_wait), ChatKind.YOUR_TURN)
        paused = self._paused()
        if paused is not None and paused[0] == "parked":
            self.say(human_effects.ABILITY_TEXT.get(paused[2].label, paused[2].label), ChatKind.YOUR_TURN)
            self._show_choice(paused[2].awaiting)

    # ---------- table I/O: snapshot, write queue and composite script ----------
    # Each message to TTS costs a fixed ~0.5 s, so fast mode (`cfg.batch`) minimizes messages:
    #   * the panel click brings the table snapshot (`snap`); reads come from it, without asking;
    #   * writes are queued (`_w`) and go out together in ONE composite script that returns the resulting table
    #     (which becomes the new snapshot). A read only forces the flush if the queue touches what it reads;
    #   * if a read disagrees, `_settle` drops the snapshot and re-reads (a single message brings everything).
    # Without `batch` each read and each write is a message, as before.
    def _timed(self, label: str):
        return _Timed(self, label)

    def _deck_kw(self, side: str = "bot") -> dict:
        """Where the side's deck is looked for when its GUID is gone: `spot`, `zone` and `radius` for the lua builders."""
        c = self.cfg
        spot, zone = (c.bot_deck_spot, c.bot_deck_zone) if side == "bot" else (c.human_deck_spot, c.human_deck_zone)
        return {"spot": tuple(spot) if spot else None, "zone": zone, "radius": c.deck_radius}

    def deck_where(self, side: str = "bot") -> str:
        kw = self._deck_kw(side)
        return deck_where(kw["zone"], kw["spot"], kw["radius"])

    def _live_decks(self) -> dict[str, str]:
        """Sides whose deck GUID is no longer the configured one (TTS gave the re-formed deck another)."""
        return {side: getattr(self.cfg, f"{side}_deck_guid") for side in ("bot", "human")
                if f"{side}_deck_guid" in self._deck_origin}

    @property
    def configured_decks(self) -> dict[str, str | None]:
        """The deck GUIDs as the data gives them, not as adopted from the table (the identity of the table)."""
        return {key: self._deck_origin.get(key, getattr(self.cfg, key)) for key in ("bot_deck_guid", "human_deck_guid")}

    def _adopt_deck(self, side: str, guid: str) -> None:
        """The deck the table shows is the one the session uses from now on; the identity of the table keeps the
        configured GUID (`_deck_origin`) so a resume still recognizes the save."""
        c, key = self.cfg, f"{side}_deck_guid"
        if getattr(c, key) == guid:
            return
        self._deck_origin.setdefault(key, getattr(c, key))
        setattr(c, key, guid)
        self._snap_spec = None                              # the snapshot skips the deck by GUID

    def _live_zones(self) -> dict[str, str]:
        """Discard zones whose GUID is no longer the configured one (the bot created them, TTS gave them another)."""
        return {key: getattr(self.cfg, key) for key in DISCARD_ZONE_KEYS if key in self._zone_origin}

    @property
    def configured_zones(self) -> dict[str, str]:
        """The discard zone GUIDs as the configuration gives them, not as created at start-up (the identity of the table)."""
        return {key: self._zone_origin.get(key, getattr(self.cfg, key)) for key in DISCARD_ZONE_KEYS}

    @staticmethod
    def read_saved_zones(raw) -> dict[str, str]:
        """The `zones_live` of a session file, keeping only well-formed entries."""
        if not isinstance(raw, dict):
            return {}
        return {key: g for key, g in raw.items()
                if key in DISCARD_ZONE_KEYS and isinstance(g, str) and lua._GUID.fullmatch(g)}

    def _adopt_zone(self, key: str, guid: str) -> None:
        """The zone the table shows is the one the session uses from now on; the identity of the table keeps the
        configured GUID (`_zone_origin`), as with the decks, so a resume still recognizes the save."""
        if getattr(self.cfg, key) == guid:
            return
        self._zone_origin.setdefault(key, getattr(self.cfg, key))
        setattr(self.cfg, key, guid)
        self._snap_spec = None                              # the snapshot reads the zones by GUID

    def prepare_table(self, resume: bool, saved_zones: dict[str, str] | None = None) -> None:
        """Makes the table usable before anything reads it: a discard zone the save lacks is created (a straight one) and
        one it has is straightened; on a fresh start, the objects of `remove_plan` that are on the table are destroyed (only
        those GUIDs; never on `resume`: the game is already laid out). One message to TTS, only if there is
        something to do. The GUID of a created zone is used from now on and saved in the session file (`zones_live`).
        What it did is said by the start / resume (`_startup_notes`). `saved_zones` = the `zones_live` of an earlier session
        file, for a fresh start (on resume they come from the loaded file). On resume a changed zone GUID is saved at once;
        a fresh start saves with the game's first step (a game not begun must not look resumable), and the position match
        of the script adopts the zones an interrupted start left behind."""
        c = self.cfg
        if saved_zones:
            self._saved_zones = self.read_saved_zones(saved_zones)
        protected = {*self.guids_in_use(), *self.guids_in_use(configured=True), *self._saved_zones.values()}
        remove = [] if resume else [(g, name) for g, name in c.remove_plan if g not in protected]
        if not c.zone_spawns and not remove:
            return
        before = dict(self._saved_zones)
        zones = []
        for key, spawn in c.zone_spawns.items():
            saved, configured = self._saved_zones.get(key), getattr(c, key)
            candidates = [g for g in ((saved, configured) if resume else (configured, saved)) if g]
            zones.append((key, list(dict.fromkeys(candidates)), spawn.position, spawn.scale, spawn.rot_y))
        res = self.client.call_lua(lua.prepare_table(zones, remove, c.remove_limits))
        if not isinstance(res, dict):
            raise SessionError(t("err.prepare_reply", got=repr(str(res)[:80])))
        found = res.get("zones") if isinstance(res.get("zones"), dict) else {}
        for key, spawn in c.zone_spawns.items():
            entry = found.get(key) if isinstance(found.get(key), dict) else {}
            role = t("ro.role.bot" if key.startswith("bot") else "ro.role.human")
            guid, status = entry.get("guid"), entry.get("status")
            if status == "no_guid" or not (isinstance(guid, str) and lua._GUID.fullmatch(guid)):
                raise SessionError(t("prep.zone_no_guid", role=role))
            self._adopt_zone(key, guid)
            if status == "created":
                self._startup_notes.append((t("prep.zone_created", role=role, guid=guid), ChatKind.WARNING))
            elif status == "straightened":
                self._startup_notes.append((t("prep.zone_straightened", role=role, guid=guid, rot=spawn.rot_y),
                                            ChatKind.WARNING))
        for row in res.get("removed") if isinstance(res.get("removed"), list) else []:
            if isinstance(row, dict) and isinstance(row.get("guid"), str):
                self.prep_removed += 1
                self._startup_notes.append((t("prep.removed", what=row.get("name") or "", guid=row["guid"]), ChatKind.WARNING))
        for row in res.get("skipped") if isinstance(res.get("skipped"), list) else []:
            if isinstance(row, dict) and isinstance(row.get("guid"), str):
                self._startup_notes.append((t("prep.skipped", guid=row["guid"], what=row.get("name") or "",
                                              why=t("prep.why." + str(row.get("why")))
                                              if row.get("why") in ("type", "place", "zone") else ""), ChatKind.WARNING))
        if resume and self._live_zones() != before:
            self._persist()                   # the loaded game is complete: only the zones changed

    def _say_startup_notes(self) -> None:
        for text, kind in self._startup_notes:
            self.say(text, kind)
        self._startup_notes = []

    def load_identities(self) -> None:
        """At the start: the identity of each deck (FaceURL/BackURL of its cards' CustomDeck), read from the object
        itself. The CardID does not identify a deck (other card games share DeckID), so no card write touches
        anything that does not have these images. The deck is found by GUID (the configured or adopted one first, then the saved live one,
        then the one the start-up read detected; only a face-down deck counts), else in its Scripting zone or around its spot, and the GUID it
        has now is adopted."""
        c = self.cfg
        hints = {"bot": c.bot_deck_hint, "human": c.human_deck_hint}

        def candidates(side: str, current: str) -> list[str]:
            """GUIDs to try, the first one that is a face-down deck winning: the current one (configured, or adopted
            earlier), then the saved live one (resume), then the one detection found near the spot or in the zone."""
            out = [current]
            for g in (self._saved_decks.get(side), hints[side]):
                if g and g not in out:
                    out.append(g)
            return out
        decks = [("bot", (candidates("bot", c.bot_deck_guid), tuple(c.bot_deck_spot), c.bot_card_ids, c.bot_deck_zone))]
        if c.human_deck_guid:
            decks.append(("human", (candidates("human", c.human_deck_guid),
                                    tuple(c.human_deck_spot) if c.human_deck_spot else None,
                                    c.human_card_ids, c.human_deck_zone)))
        res = self.client.call_lua(lua.deck_identities([d for _, d in decks], c.deck_radius))
        if not isinstance(res, list) or len(res) != len(decks) or not all(isinstance(e, dict) for e in res):
            raise TTSLuaError(t("err.identity_reply", got=repr(str(res)[:80])))
        for (side, _), entry in zip(decks, res):
            pairs = self._parse_pairs(entry.get("pairs"))
            if entry.get("found") and pairs:
                self._deck_ident[side] = pairs
                guid = entry.get("guid")
                if isinstance(guid, str) and lua._GUID.fullmatch(guid):
                    self._adopt_deck(side, guid)

    @staticmethod
    def _parse_pairs(rows) -> tuple:
        if not isinstance(rows, list):
            return ()
        return tuple((r["face"], r["back"]) for r in rows
                     if isinstance(r, dict) and all(isinstance(r.get(k), str) and lua._URL.fullmatch(r[k])
                                                    for k in ("face", "back")))[:lua.MAX_IDENTITIES]

    def _identity_from_hand(self, side: str) -> None:
        """Last resort: the images of the cards in the side's hand (only those of its CardID range)."""
        seat, rng = ((self.cfg.bot_seat, self.cfg.bot_card_ids) if side == "bot"
                     else (self.cfg.human_seat, self.cfg.human_card_ids))
        res = self.client.call_lua(lua.hand_identities(seat, rng))
        pairs = self._parse_pairs(res.get("pairs") if isinstance(res, dict) else None)
        if pairs:
            self._deck_ident[side] = pairs

    def _identity(self, side: str = "bot") -> tuple:
        """Images of the side's cards: from the table; else from the session save; else from the hero data
        (data/tts, e.g. with the deck still in its bag); else from its hand."""
        failure: Exception | None = None
        if side not in self._deck_ident:
            try:
                self.load_identities()
            except TABLE_ERRORS as e:
                failure = e
        if side not in self._deck_ident and side in self._saved_ident:
            self._deck_ident[side] = self._saved_ident[side]
        if side not in self._deck_ident and self.cfg.deck_identity.get(side):
            self._deck_ident[side] = tuple(self.cfg.deck_identity[side])[:lua.MAX_IDENTITIES]
        if side not in self._deck_ident:
            try:
                self._identity_from_hand(side)
            except TABLE_ERRORS as e:
                failure = failure or e
        if side not in self._deck_ident:
            if failure is not None:
                raise failure
            raise SessionError(t("err.identity", side=t("sess.side.bot" if side == "bot" else "sess.side.human")))
        return self._deck_ident[side]

    def _scope(self) -> lua.Scope:
        c = self.cfg
        spots = [(c.bot_card_spot[0], c.bot_card_spot[2]), tuple(c.human_card_spot), tuple(c.bot_deck_spot)]
        if c.human_deck_spot:
            spots.append(tuple(c.human_deck_spot))
        if c.bot_ongoing_spot:                    # the bot's ONGOING scheme is discarded from there when it leaves play
            spots.append((c.bot_ongoing_spot[0], c.bot_ongoing_spot[2]))
        return lua.Scope((c.bot_seat, c.human_seat), (c.bot_discard_zone, c.human_discard_zone), tuple(spots),
                         max(2.0, c.reveal_radius))

    def snapshot_spec(self) -> lua.SnapSpec:
        if self._snap_spec is None:
            c = self.cfg
            pieces = sorted({g for v in c.pieces.values() for g in piece_guids(v)})
            dials = sorted({*c.dials.values(), *([c.destiny_dial] if c.destiny_dial else [])})
            self._snap_spec = lua.SnapSpec(
                self.game.board, c.bot_seat, c.human_seat, c.bot_discard_zone, (c.bot_deck_guid,),
                (tuple(c.bot_deck_spot),), c.human_discard_zone,
                (c.human_deck_guid,) if c.human_deck_guid else (),
                (tuple(c.human_deck_spot),) if c.human_deck_spot else (), c.deck_exclude_radius,
                (c.bot_card_spot[0], c.bot_card_spot[2]), tuple(c.human_card_spot), c.reveal_radius,
                tuple(pieces), tuple(dials), human_deck=c.human_deck_guid,
                bot_ongoing_spot=(c.bot_ongoing_spot[0], c.bot_ongoing_spot[2]) if c.bot_ongoing_spot else None,
                human_ongoing_spot=tuple(c.human_ongoing_spot) if c.human_ongoing_spot else None,
                bot_skip_zones=self._skip_zones("bot"), human_skip_zones=self._skip_zones("human"))
        return self._snap_spec

    @staticmethod
    def _valid_snap(snap: dict, spaces=None) -> bool:
        """Types and ranges of what the click brings (a TTS script sends it, but an external message could also
        forge it): any odd value drops the whole snapshot and one is requested from the table."""
        def num(v, lo, hi) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi

        def cards(rows) -> bool:
            return len(rows) <= 300 and all(isinstance(r, dict) and num(r.get("id"), 0, 10 ** 6)
                                            and float(r["id"]).is_integer() and isinstance(r.get("guid"), str)
                                            and len(r["guid"]) <= 40 for r in rows)
        if not all(cards(snap[k]) for k in ("bot_hand", "bot_discard", "human_discard", "face_bot", "face_human",
                                              "ongoing_bot", "ongoing_human")):
            return False
        if not num(snap["human_count"], 0, 300) or not num(snap.get("human_deck_qty", -1), -1, 300):
            return False
        if "seq" in snap and not (isinstance(snap["seq"], int) and not isinstance(snap["seq"], bool)
                                  and 0 <= snap["seq"] < 10 ** 12):
            return False
        for g, info in snap["pieces"].items():
            if not isinstance(g, str) or not isinstance(info, dict) or not isinstance(info.get("found"), bool):
                return False
            if info["found"] and not (num(info.get("space"), 0, 10 ** 4) and num(info.get("dist"), 0, 10 ** 7)
                                      and (spaces is None or info["space"] in spaces)):
                return False
        for g, info in snap["dials"].items():
            if not isinstance(g, str) or not isinstance(info, dict) or not isinstance(info.get("found"), bool):
                return False
            if info["found"] and any(info.get(k) is not None and not num(info[k], -10 ** 4, 10 ** 4)
                                     for k in ("value", "max")):
                return False
        return True

    @staticmethod
    def _parse_snap(raw, spaces=None) -> dict | None:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return None
        if not isinstance(raw, dict) or not all(k in raw for k in SNAP_KEYS):
            return None
        snap = dict(raw)
        for k in ("pieces", "dials"):             # an empty Lua object arrives as an empty list
            if not isinstance(snap[k], dict):
                snap[k] = {}
        for k in ("bot_hand", "bot_discard", "human_discard", "face_bot", "face_human", "ongoing_bot", "ongoing_human"):
            if not isinstance(snap.get(k), list):
                snap[k] = []
        return snap if Session._valid_snap(snap, spaces) else None

    def _snap_stale(self, snap: dict) -> bool:
        """A snapshot older than the last table write (or without a seal) does not reflect the table: re-absorbing it
        would undo what the engine already moved."""
        seq = snap.get("seq")
        return not isinstance(seq, int) or seq < self._write_seq

    def _take_snapshot(self, raw) -> None:
        """The snapshot the click brings (taken by the panel itself, with no round trip)."""
        self.snap, self._trusted = None, False
        if self.cfg.batch and raw is not None:
            snap = self._parse_snap(raw, set(self.game.board.spaces))
            if snap is not None and not self._snap_stale(snap):
                self.snap, self._trusted = snap, True

    def _view(self, domain: str) -> dict:
        """The current snapshot. If there are queued writes touching `domain` they go out first (and their result
        renews it); without a snapshot one is requested (a single message brings the whole table)."""
        if any(o.domain == domain for o in self._queue):
            self._flush()
        if self._depth == 0:
            self.snap = None                      # the snapshot is only valid while a button is attended
        if self.snap is not None and self._snap_stale(self.snap):
            self.snap = None                      # older than the last write: never adopted
        if self.snap is None:
            snap = self._parse_snap(self.client.call_lua(lua.snapshot(self.snapshot_spec())),
                                    set(self.game.board.spaces))
            if snap is None:
                raise SessionError(t("err.snapshot"))
            snap["seq"] = self._write_seq         # just read: it reflects everything written so far
            if self._depth == 0:
                return snap
            self.snap, self._trusted = snap, False
        return self.snap

    def _stamp_deal(self, scripts: list[str]) -> None:
        """A script that deals cards to the human's seat just ran: until `DEAL_FLIGHT` passes, a card read in their
        discard zone may be one still flying from the deck to the hand (`sync_human`)."""
        seat = f'"{self.cfg.human_seat}"'
        if any(x.startswith("-- sparring:deal_cards") and seat in x for x in scripts):
            self._deal_at = time.monotonic()

    def _w(self, script: str, domain: str) -> _Op:
        """Writes to the table: immediate without `batch`, queued with it (goes out on the next `_flush`)."""
        op = _Op(self, script, domain)
        if self.cfg.batch:
            self._queue.append(op)
        else:
            op.value, op.done = self.client.call_lua(script), True
            self._stamp_deal([script])
        return op

    def _flush(self) -> None:
        """Sends the queue as ONE composite script and adopts the resulting table as the snapshot."""
        while self._queue:
            take, size = 0, 0
            for o in self._queue[:lua.MAX_OPS - 4]:          # also cut by size in bytes
                size += len(o.script.encode("utf-8"))
                if take and size > lua.MAX_COMPOSITE_BYTES - COMPOSITE_OVERHEAD:
                    break
                take += 1
            ops, self._queue = self._queue[:take], self._queue[take:]
            expect, self._expect_hand = self._expect_hand, None
            wants_state = any(o.domain != "misc" for o in ops)
            if wants_state:
                self._write_seq += 1
            try:
                script = lua.composite([o.script for o in ops], self.snapshot_spec() if wants_state else None, expect,
                                       seq=self._write_seq)
                held = sum(float(m.group(1)) for o in ops for m in [re.search(r"math\.max\(holdFor or 0, ([\d.]+)\)", o.script)]
                           if o.script.startswith("-- sparring:hold\n") and m)
                if held:         # TTS replies only after the hold: the default wait would give up before it
                    res = self.client.call_lua(script, timeout=getattr(self.client, "timeout", 5.0) + held + HOLD_MARGIN)
                else:
                    res = self.client.call_lua(script)
            except Exception as e:                        # noqa: BLE001 - propagated to whoever asked for the result
                self.snap = None
                for o in ops:
                    o.error, o.done = e, True
                raise
            self._stamp_deal([o.script for o in ops])
            results = res.get("ops") if isinstance(res, dict) else None
            results = results if isinstance(results, list) and len(results) == len(ops) else [None] * len(ops)
            for o, r in zip(ops, results):
                o.done = True
                if isinstance(r, dict) and "__err" in r:
                    o.error = TTSLuaError(r["__err"])
                    continue
                o.value = r
            if wants_state:
                self.snap = self._parse_snap(res.get("state") if isinstance(res, dict) else None,
                                             set(self.game.board.spaces))
                if self.snap is not None:
                    self.snap["seq"] = self._write_seq
                self._trusted = True
                if self._depth == 0:
                    self.snap = None
            for o in ops:
                if o.error is not None and not o.seen:
                    tag = o.script.split("\n", 1)[0].removeprefix("-- sparring:")
                    self.say(t("sess.tts_failed", script=tag, err=o.error), ChatKind.WARNING)

    def _commit(self) -> None:
        """Closing of each button: what is left in the queue, the status line, the panel buttons and the announcements,
        all in the same message."""
        self._deal_owed_draws()
        posts, self._post = self._post, []
        said = len(self.messages)
        if self.cfg.live_ui:
            status, states = self.panel_view()
            shown = (status, states)
            try:
                self._w(lua.set_panel(status, states, release_busy=not self.cfg.batch, labels=self.panel_labels()), "misc")
                if self.broadcast:
                    for m in self.messages:
                        for chunk in [] if getattr(m, "shown", False) else lua.ascii_text(m):
                            self._w(lua.broadcast(chunk, m.kind), "misc")
            except (ValueError, TypeError) as e:
                self.say(t("sess.panel_prep_fail", err=e), ChatKind.WARNING)
        if self._queue:
            try:
                self._flush()
            except TABLE_ERRORS as e:
                self.say(t("sess.table_update_fail", err=e), ChatKind.WARNING)
        for check in posts:
            check()
        if posts and self.cfg.live_ui and self.panel_view() != shown:
            self._refresh_panel()                     # the closings changed the state: line and buttons up to date
        if len(self.messages) > said and posts:       # a check failed: a warning is also shown on screen
            if self.broadcast:
                for m in self.messages[said:]:
                    for chunk in [] if getattr(m, "shown", False) else lua.ascii_text(m):
                        self._w(lua.broadcast(chunk, m.kind), "misc")
            try:
                self._flush()
            except TABLE_ERRORS:
                pass

    def _refresh_panel(self) -> None:
        status, states = self.panel_view()
        try:
            self._w(lua.set_panel(status, states, release_busy=not self.cfg.batch, labels=self.panel_labels()), "misc")
            self._flush()
        except (ValueError, TypeError) + TABLE_ERRORS as e:
            self.say(t("sess.panel_update_fail", err=e), ChatKind.WARNING)

    def _rd_bot_hand(self) -> list[dict]:
        if self.cfg.batch:
            return self._view("cards")["bot_hand"]
        return self.client.call_lua(lua.read_hand(self.cfg.bot_seat)) or []

    def _skip_zones(self, side: str) -> tuple[str, ...]:
        zone = self.cfg.bot_deck_zone if side == "bot" else self.cfg.human_deck_zone
        return (zone,) if zone else ()

    def _rd_bot_discard(self) -> list[dict]:
        c = self.cfg
        if c.batch:
            return self._view("cards")["bot_discard"]
        return self.client.call_lua(lua.read_discard(c.bot_discard_zone, [c.bot_deck_guid], [c.bot_deck_spot],
                                                     c.deck_exclude_radius, self._skip_zones("bot"))) or []

    def _rd_human_discard(self) -> list[dict]:
        return self._rd_human_discard_raw() or []

    def _rd_human_discard_raw(self) -> list[dict] | None:
        """The human's pile as the table answered it: None when there was no reply (an empty pile answers [])."""
        c = self.cfg
        if c.batch:
            return self._view("cards")["human_discard"]
        skip = [c.human_deck_guid] if c.human_deck_guid else []
        spots = [c.human_deck_spot] if c.human_deck_spot else []
        return self.client.call_lua(lua.read_discard(c.human_discard_zone, skip, spots, c.deck_exclude_radius,
                                                     self._skip_zones("human")))

    def _rd_human_count(self, default: int) -> int:
        if self.cfg.batch:
            count = self._view("cards")["human_count"]
            return count if isinstance(count, int) else default
        return (self.client.call_lua(lua.count_hand(self.cfg.human_seat)) or {}).get("count", default)

    def _rd_face(self, side: str) -> list[dict]:
        """Face-down cards at the bot's (`bot`) or the human's (`human`) combat spot."""
        c = self.cfg
        if c.batch:
            return self._view("cards")["face_" + side]
        if side == "bot":
            return self.client.call_lua(lua.read_face_down_cards(c.bot_card_spot[0], c.bot_card_spot[2],
                                                                 c.reveal_radius)) or []
        return self.client.call_lua(lua.read_face_down_cards(*c.human_card_spot, c.reveal_radius)) or []

    def _rd_combat_spot(self) -> list[dict]:
        # Rows are bare CardIDs, but the caller only keeps ids that exist in the HUMAN's own deck and the spot is the human's
        # (the bot's combat spot is far away), so a card of the same id from another deck cannot be mistaken for theirs; the
        # move by GUID (`card_to_discard`) re-checks the deck image in Lua (`ours`).
        """The FACE-UP cards at the human's combat spot: [{id, guid}] (The Mists of Munnopor: the card they played in place
        of the discarded one). Face-down cards are never read here (`_rd_face` does that at the Reveal)."""
        c = self.cfg
        return self.client.call_lua(lua.read_cards_at(c.human_card_spot[0], c.human_card_spot[1], c.reveal_radius)) or []

    def _rd_ongoing(self, side: str) -> list[dict]:
        """The cards on the ONGOING spot of `bot` / `human` (E2); empty when the spot is not configured."""
        c = self.cfg
        spot = c.bot_ongoing_spot if side == "bot" else c.human_ongoing_spot
        if spot is None:
            return []
        if c.batch:
            return self._view("cards")["ongoing_" + side]
        x, z = (spot[0], spot[2]) if side == "bot" else spot
        return self.client.call_lua(lua.read_cards_at(x, z, c.reveal_radius)) or []

    def _rd_dials(self, guids: list[str]) -> dict:
        if self.cfg.batch:
            dials = self._view("dials")["dials"]
            return {g: dials.get(g) or {"found": False} for g in guids}
        return self.client.call_lua(lua.read_health_dials(guids)) or {}

    # ---------- status line and panel buttons ----------
    def _panel_ids(self) -> list[str]:
        return ui.element_ids([f.fid for f in self.game.own(self.bot, alive_only=False)],
                              tuple(f.fid for f in self.game.own(self.human, alive_only=False)))

    def panel_view(self) -> tuple[str, dict[str, tuple[bool, bool]]]:
        """(text of the status line, {id: (can be pressed, is visible)}) according to the session state."""
        g = self.game
        states = {i: (True, True) for i in self._panel_ids()}
        in_setup = self.setup is not None
        paused = self._paused()
        choosing = paused is not None
        free = (not in_setup and g.winner is None and g.turn == self.human and self.pending is None
                and self.pending_discard is None and not self.moving and self.look is None and not choosing)

        def alive(fid: str) -> bool:
            return g.fighters[fid].alive

        for i in ("btn_maneuver", "btn_scheme"):
            states[i] = (free, True)
        chosen = g.fighters.get(self.chosen_attacker) if self.chosen_attacker else None
        for fid, f in g.fighters.items():
            if f.owner == self.human:
                states[f"att_{fid}"] = (free and f.alive, True)
            else:
                try:
                    reach = bool(free and chosen is not None and f.alive and g.can_attack(chosen, f))
                except RuleError:
                    reach = False
                states[fid] = (reach, True)
            states[f"hpm_{fid}"] = (f.alive, True)
            states[f"rm_{fid}"] = (f.alive, True)
        cancellable = (self.look is not None or self.pending is not None or self.pending_discard is not None
                       or self.chosen_attacker is not None or bool(self.pending_value) or self.dirty or self.unprojected is not None
                       or bool(self.flush_failures))
        boosting = self.pending is not None and self.pending.wait is not None
        stuck = boosting and bool(self.pending.wait.extra["stuck"])
        gate = self._table_gate(self.pending)
        states["btn_reveal"] = (self.pending is not None and not boosting and not gate, not boosting)
        states["btn_cancel"] = (cancellable and (not boosting or stuck), not boosting or stuck)
        states["btn_boost"] = (boosting, boosting)
        states["btn_noboost"] = (boosting, boosting)
        can_boost_maneuver = (not in_setup and g.winner is None and g.turn == self.human and self.pending is None
                              and self.moving and self.maneuver_baseline is not None and self.maneuver_boosted is None
                              and not choosing and self.look is None)
        states["btn_mboost"] = (can_boost_maneuver, can_boost_maneuver)
        states["btn_end"] = (not in_setup and g.winner is None
                             and (self.pending is None or self.look is not None or gate), True)
        states["btn_look"] = (self._look_blocked() is None and not choosing, self.look_granted)
        if choosing:
            for i in ("btn_reveal", "btn_cancel", "btn_end", "btn_boost", "btn_noboost", "btn_mboost"):
                states[i] = (False, states[i][1])
        if gate:
            states["btn_cancel"] = (False, states["btn_cancel"][1])
        req = paused[2].awaiting if choosing else None
        manual = hidden.manual_request(self) is not None
        by_hand = moves.manual_request(self)
        by_pile = pile.manual_request(self)
        by_order = order_cards.manual_request(self)
        states.update((hidden.manual_view(self) if manual else moves.view(self, by_hand) if by_hand is not None
                       else pile.view(self, by_pile) if by_pile is not None
                       else order_cards.view(self, by_order) if by_order is not None
                       else choices.panel_choice_view(g, req, self.choice_ui))[0])
        for ident in self._blocked_buttons():
            states[ident] = (False, False)
        if self.ability_wait is not None:         # your start-of-turn ability first: only End action (and the hit points)
            for ident in states:
                if ident != "btn_end" and not ident.startswith(("hpm_", "rm_")):
                    states[ident] = (False, False)
            states["btn_end"] = (True, True)
        states["btn_undo"] = (g.winner is not None, g.winner is not None)
        waiting = in_setup and self.setup["stage"] in ("wait_human_first", "wait_human")
        states["btn_ready"] = (in_setup, in_setup)
        states["btn_mulligan"] = (bool(waiting and self.cfg.mulligan_human and not self.setup.get("human_mull")),
                                  in_setup)
        states["btn_restart"] = (True, not in_setup)
        states["btn_newgame"] = (True, self.can_regate)
        states["btn_unreveal"] = (True, self.reveal_shown)          # hidden, never greyed out, when nothing is revealed
        return self._status_text(), {k: v for k, v in states.items() if k in set(self._panel_ids())}

    def new_game_armed(self) -> bool:
        return self._new_game_at is not None and self.clock() - self._new_game_at <= RESTART_WINDOW

    def restart_armed(self) -> bool:
        return self._restart_at is not None and self.clock() - self._restart_at <= RESTART_WINDOW

    def _status_text(self) -> str:
        g = self.game
        if self.restart_armed():
            return panel_text(t("st.restart_armed"))
        if self.new_game_armed():
            return panel_text(t("st.new_game_armed"))
        if self.setup is not None:
            if self.setup["stage"] in ("wait_human_first", "wait_human"):
                return panel_text(t("st.setup_wait"))
            return panel_text(t("st.setup_bot"))
        if g.winner is not None:
            return panel_text(t("st.game_over", name=self._name(g.hero(g.winner))))
        if self.look is not None:
            return hidden.look_status(self)
        if hidden.manual_request(self) is not None:
            return hidden.manual_status(self)
        if moves.manual_request(self) is not None:
            return panel_text(moves.status(self, moves.manual_request(self)), 80, t("btn.done"))
        if pile.manual_request(self) is not None:
            return panel_text(pile.status(self, pile.manual_request(self)), 80, t("btn.done"))
        if order_cards.manual_request(self) is not None:
            return order_cards.status(self, order_cards.manual_request(self))
        if self.effect_run is not None:
            return panel_text(choices.prompt_text(g, self.effect_run.awaiting), 80, t("st.choose"))
        if g.turn != self.human:
            paused = self.dial_debt or self.bot_stage is not None or self.dirty or self.flush_failures
            return panel_text(t("st.bot_turn_paused" if paused else "st.bot_turn"))
        head = tn("st.head", g.actions_left)
        if self.ability_wait is not None:
            return panel_text(t("st.ability", head=head))
        if self.pending is not None and self.pending.wait is not None:
            title = next((c.title for c in g.players[self.human].full_set
                          if c.card_id == self.pending.wait.card_id), "Boost")
            return panel_text(t("st.boost_stuck" if self.pending.wait.extra["stuck"] else "st.boost_wait", title=title))
        if self._table_gate(self.pending):
            wait = t("st.wait.table")
        elif self.pending is not None:
            wait = t("st.wait.defense" if self.pending.kind == "bot_attacks" else "st.wait.reveal")
        elif self.pending_discard is not None:
            wait = t("st.wait.discard")
        elif self.moving:
            wait = t("st.wait.end")
        elif self.chosen_attacker is not None:
            wait = t("st.wait.target")
        else:
            wait = t("st.wait.action")
        return panel_text(t("st.waiting", head=head, wait=wait))

    # ---------- looking at the bot's hand (Confront Any Demon or God and similar) ----------
    def _look_blocked(self) -> str | None:
        """Why the bot's hand cannot be looked at now (None if it can)."""
        g = self.game
        if not self.look_granted:
            return t("look.not_granted")
        if self.setup is not None:
            return t("sess.setting_up")
        if g.winner is not None:
            return t("look.game_over")
        if self.look is not None:
            return t("look.already")
        if g.turn != self.human and self.pending is None and not self.moving:
            return t("look.when")
        if self.dirty or self.unprojected is not None or self.flush_failures or self.placing is not None:
            return t("look.unreflected")
        held = self.pending.bot_card if self.pending is not None else None
        if not [c for c in self.game.players[self.bot].hand if c is not held]:
            return t("look.empty")
        return None

    def _look_spots(self, n: int, card_row: bool = False) -> list[tuple[float, float, float]]:
        """Row spots: Look at bot's hand's (`look_spot`), or with `card_row` the one a card of the human opens (`bot_row_spot`)."""
        cfg = self.cfg
        (x, y, z), (dx, dz) = (cfg.bot_row_spot, cfg.bot_row_step) if card_row else (cfg.look_spot, cfg.look_step)
        return [(x + (i - (n - 1) / 2) * dx, y, z + (i - (n - 1) / 2) * dz) for i in range(n)]

    def _look_rot(self) -> float:
        return self.cfg.bot_discard_rot_y if self.cfg.look_rot_y is None else self.cfg.look_rot_y

    def _look_entries(self) -> list[tuple[str, float, float]]:
        return [(g, sp[0], sp[1]) for g, sp in zip(self.look["guids"], self.look["spots"])]

    def restore_look_row(self) -> None:
        """After recreating the panel (TTS reloaded the game) the row in view is noted on it again, if there is one."""
        if self.look is not None:
            self.client.call_lua(lua.set_look_row(self._look_entries()))

    def _card_line(self, n: int, c: Card) -> str:
        stats = ", ".join(p for p in (t(CARD_TYPE_TAGS[c.type]) if c.type in CARD_TYPE_TAGS else c.type,
                                      t("look.value", n=c.value) if c.value is not None else "", t("look.boost", n=c.boost)) if p)
        return f"{n}) {c.title}, {stats}: {c.text or t('look.no_effect')}"

    def _look_hand(self, _: dict) -> None:
        """Lays the cards of the bot's hand face up in a row in front of the human and reads them in the chat. Spends no
        action. The bot learns nothing of the human's hand: what is revealed is its own."""
        why = self._look_blocked()
        if why:
            self.say(why, ChatKind.WARNING)
            return
        self.read_bot_hand()
        st = self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        rows = [r for r in self._rd_bot_hand() if r["id"] in by_id][:lua.MAX_LOOK_CARDS]
        if not rows:
            self.say(t("look.no_cards"), ChatKind.WARNING)
            return
        self.look_fails = 0                       # a new row starts without failures
        spots = self._look_spots(len(rows))
        if self.cfg.batch:
            self._expect_hand = (self.cfg.bot_seat, 0)
        op = self._w(lua.show_hand_row([r["id"] for r in rows], spots, self._look_rot(), self.cfg.bot_seat,
                                       identity=self._identity(), id_range=self.cfg.bot_card_ids), "cards")
        # the GUIDs come from reading the hand: there is no need to wait for the reply (a single message with the notice)
        self.look = {"ids": [r["id"] for r in rows], "guids": [r["guid"] for r in rows],
                     "spots": [[sp[0], sp[2]] for sp in spots]}
        self.revoke_look()                        # the look the card allowed is being taken
        self._post.append(lambda: self._look_shown(op))
        self.say(t("look.shown", n=len(rows)), ChatKind.YOUR_TURN)
        for n, r in enumerate(rows, 1):
            self.say(self._card_line(n, by_id[r["id"]]), ChatKind.SCHEME)

    def _look_shown(self, op: _Op) -> bool:
        """Check at the button's closing: the table took the cards out of the hand. If it only took some, the row keeps
        those; if it failed altogether, the look is undone (a TTS error leaves the row for Cancel to pick up)."""
        look = self.look
        if look is None:
            return True
        try:
            shown = {e["id"] for e in ((op.result or {}).get("shown") or []) if isinstance(e, dict)}
        except TABLE_ERRORS as e:
            self.say(t("look.tts_unconfirmed", err=e), ChatKind.WARNING)
            return False
        keep = [i for i, cid in enumerate(look["ids"]) if cid in shown]
        if not keep:
            self.look = None
            self.read_bot_hand()
            self.say(hidden.row_failed_text(look), ChatKind.WARNING)
            return False
        if len(keep) < len(look["ids"]):
            self.look = {**look, **{k: [look[k][i] for i in keep] for k in ("ids", "guids", "spots")}}
            self.say(t("look.partial", n=len(keep), total=len(look["ids"])), ChatKind.WARNING)
        return True

    def _look_ping(self, payload: dict) -> None:
        guid = payload.get("guid")
        if self.look is None:
            self.say(t("look.none_shown"), ChatKind.WARNING)
            return
        if guid not in self.look["guids"]:
            self.say(t("look.bad_ping"), ChatKind.WARNING)
            return
        if hidden.ping(self, guid):               # E3: the card's own choice, or a reveal that picks nothing
            return
        self._look_close(discard=guid)

    def _look_close(self, discard: str | None = None, face_down: bool = False) -> None:
        """Closes the row with a single script: the chosen card (by ping, or the only one face down) goes to the bot's
        discard and the rest return to its hand; with no choice it is Cancel and everything returns. With ping or Cancel
        the engine counts the discard now (the card is known by its GUID) and the table confirms it at the button's
        closing (`_look_closed`); with the card face down we must wait for the table to say which one it was."""
        look, st = self.look, self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        n = len(look["ids"])
        if discard is None and not face_down and self.look_fails:
            self._look_force_exit(t("look.why_second_cancel"))
            return
        if self.cfg.batch:
            self._expect_hand = (self.cfg.bot_seat, n - 1 if (discard or face_down) else n)
        try:
            op = self._w(lua.resolve_hand_row(
                look["guids"], self.cfg.bot_seat, identity=self._identity(), id_range=self.cfg.bot_card_ids,
                discard=discard, face_down=face_down, spot=self._discard_slot(len(st.discard)),
                rot_y=self.cfg.bot_discard_rot_y), "cards")
        except TABLE_ERRORS:
            if discard is None and not face_down:
                self.look_fails += 1              # without a batch the failure arrives now: only failed Cancels count
            raise
        if face_down:
            chosen = (op.result or {}).get("discarded")
            if chosen in (None, False):
                self.say(t("look.face_down", n=(op.result or {}).get("down", 0)), ChatKind.WARNING)
                return
            card = by_id.get(chosen)
        else:
            card = by_id[look["ids"][look["guids"].index(discard)]] if discard else None
        self.look = None
        if card is not None:
            if card in st.hand:
                self.game.discard_card(self.bot, card)
            else:
                if card in st.deck:
                    st.deck.remove(card)
                st.discard.append(card)
                self.game.card_left_hand(self.bot, card)
        self._post.append(lambda: self._look_closed(op, card, look))
        self.say(t("look.discarded", title=card.title) if card is not None else t("look.returned"),
                 ChatKind.SCHEME if card is not None else ChatKind.NEUTRAL)

    def restore_row_hands(self, guids: list[str]) -> None:
        """Best effort: the shown cards get `use_hands` back so the human can put them in the hand zone by hand."""
        if not guids:
            return
        try:
            self._w(lua.restore_use_hands(list(guids)), "cards")
        except TABLE_ERRORS:
            pass

    def _look_force_exit(self, why: str) -> None:
        """Exit from the look when the table will not let it close: the table rules. The engine drops the row, re-reads the hand and
        leaves the table debt for the next End action; the bot's cards that are not in its hand are picked up by hand."""
        row = self.look["guids"] if self.look else []
        self.look, self.look_fails = None, 0
        self.restore_row_hands(row)
        self.read_bot_hand()
        self._mark_dirty()
        self.say(t("look.forced", why=why), ChatKind.WARNING)

    def _look_best_effort_cancel(self) -> None:
        """Before restarting: tries to return the row to the hand so the restart gathers the cards; if it fails, it goes on."""
        look = self.look
        self.look, self.look_fails = None, 0
        try:
            self._w(lua.resolve_hand_row(look["guids"], self.cfg.bot_seat, identity=self._identity(),
                                         id_range=self.cfg.bot_card_ids), "cards").result
        except TABLE_ERRORS:
            pass

    def _look_closed(self, op: _Op, card: Card | None, look: dict) -> bool:
        """Check at the button's closing: the table did what the engine already counted. If not (the card was not there, TTS failed),
        the engine undoes the discard and the row is in view again to repeat the ping or Cancel."""
        st = self.game.players[self.bot]
        try:
            res = op.result or {}
            done = res.get("discarded") == card.card_id if card is not None else bool(res.get("found"))
            fail, errored = (None if done else t("look.fail_missing")), False
        except TABLE_ERRORS as e:
            fail, errored = t("look.fail_error", err=e), True
        if fail is not None:
            if card is not None and card in st.discard:
                st.discard.remove(card)
                st.hand.append(card)
            if not errored and not (op.result or {}).get("found"):
                self._look_force_exit(t("look.why_stacked"))      # stacked, erased...
                return
            if card is None:
                self.look_fails += 1              # only a failed Cancel brings the forced exit closer
            self.look = look
            self.say(t("look.table_failed", fail=fail), ChatKind.WARNING)
            return False
        self.look_fails = 0
        if card is not None:
            want = len(look["ids"]) - 1
            if self._settle(lambda: card.card_id in self._table_discard() and len(self._table_hand_ids()) >= want):
                self.bot_discarded.add(card.card_id)
            else:
                self._mark_dirty()                # the engine already discarded it: the next sync finishes moving it
                self.say(t("look.not_in_discard", title=card.title), ChatKind.WARNING)
        self.read_bot_hand()
        return True

    # ---------- the bot's table ----------
    def _bot_cards_in_play(self) -> list[Card]:
        """The bot's cards in no zone of the engine: the ones a combat stopped at the panel holds until the flow
        discards them, its ONGOING scheme and a scheme stopped at a decision of the human (parked). They may still
        sit in the table hand: never counted as hand cards, never dealt again."""
        p, st = self.pending, self.game.players[self.bot]
        cards = [c for owner, c in p.flow.played if owner == self.bot] if p is not None and p.flow is not None else []
        ids = {self.game.fx.ongoing_card_id(self.bot), *(c.card_id for c in st.tucked), *(c.card_id for c in st.removed)}
        ids |= {r.flags["scheme"]["card_id"] for r in self.game.fx.parked
                if r.flags.get("scheme", {}).get("player") == self.bot}
        return cards + [c for c in st.full_set if c.card_id in ids]

    def read_bot_hand(self) -> None:
        """The hand comes from the table. Draws the engine already counted but the deck has not yet dealt (`drawn`) are
        kept in the engine's hand and out of its deck: a failed deal never re-inflates the deck."""
        res = self._rd_bot_hand()
        st = self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        try:
            cards = [by_id[r["id"]] for r in res]
        except KeyError as e:
            raise SessionError(t("err.unknown_card", err=e)) from None
        in_play = self._bot_cards_in_play()
        cards = [c for c in cards if c not in in_play]   # a scheme stopped at the panel still sits in the table hand
        p = self.pending
        held = p.bot_card if p is not None and p.flow is None else None
        if held is not None and held not in cards and held not in st.discard:
            cards.append(held)                    # the card played face down is still its own until resolved
        for card_id in (self.look["ids"] if self.look is not None else ()):
            c = by_id.get(card_id)                # the hand in view is in the table's row, not in its hand
            if c is not None and c not in cards and c not in st.discard:
                cards.append(c)
        unseen = peek.engine_order(self, [c for c in st.full_set if c not in cards and c not in st.discard and c not in in_play])
        owed = min(self.game.drawn[self.bot], len(unseen))
        st.hand = cards + unseen[:owed]
        st.deck = unseen[owed:]

    def _place_bot_card(self, card: Card | None, kind: str, attacker: Fighter, target: Fighter) -> str | None:
        """Leaves the card face down. If the reply does not arrive (timeout) it is not known whether TTS moved it: `placing`
        remembers it and the next `_flush_table` looks at the table (`_recover_placing`)."""
        if card is None:
            return None
        x, y, z = self.cfg.bot_card_spot
        self.placing = {"kind": kind, "attacker": attacker.fid, "target": target.fid, "card": card.card_id}
        try:
            if self.cfg.batch:
                self._expect_hand = (self.cfg.bot_seat, len(self._table_hand_ids()) - 1)
            ping = ((piece_guids(self.cfg.pieces[attacker.fid]), piece_guids(self.cfg.pieces[target.fid]),
                     [self.cfg.bot_seat, self.cfg.human_seat])
                    if kind == "bot_attacks" else None)
            res = self._w(lua.play_card_face_down(card.card_id, self.cfg.bot_seat, x, y, z, self.cfg.rot_y,
                                                  self.cfg.bot_card_ids, identity=self._identity(), ping=ping),
                          "cards").result
        except OSError:
            raise
        except Exception:
            self.placing = None
            raise
        self.placing = None
        guid = (res or {}).get("played")
        if not guid:
            self.read_bot_hand()
            raise SessionError(t("err.card_not_in_hand", title=card.title))
        # it does not trust the returned value: the card must really be at its spot and out of the hand
        if not self._settle(lambda: self._card_on_spot(card.card_id) is not None):
            self.placing = None
            self.read_bot_hand()
            raise SessionError(t("err.card_not_out", title=card.title))
        return self._card_on_spot(card.card_id) or guid

    def _settle(self, ok) -> bool:
        """Bounded polling: the TTS table is slow to reflect smooth card moves. It only waits (and re-reads the
        table) if the read disagrees; the first one comes from the snapshot."""
        tries = max(1, self.cfg.settle_tries)
        for i in range(tries):
            if ok():
                return True
            if i < tries - 1:
                if self.cfg.batch:
                    self.snap = None                  # the next read goes to the table
                if self.cfg.settle_wait > 0:
                    time.sleep(self.cfg.settle_wait)
        return False

    def _table_hand_ids(self) -> list[int]:
        return [r["id"] for r in self._rd_bot_hand()]

    def _table_discard(self) -> set[int]:
        """CardIDs of the bot's cards in its discard pile (the draw deck and anything foreign in the zone are ignored)."""
        own = {card.card_id for card in self.game.players[self.bot].full_set}
        return {r["id"] for r in self._rd_bot_discard()} & own

    def _in_discard_zone(self, x: float, z: float) -> bool:
        """The center (x, z) falls inside the discard zone, with its rotation (with no configured bounds, it does)."""
        bounds = self.cfg.bot_discard_bounds
        if bounds is None:
            return True
        cx, cz, sx, sz, rot = bounds
        t = math.radians(rot)
        dx, dz = x - cx, z - cz
        lx, lz = dx * math.cos(t) - dz * math.sin(t), dx * math.sin(t) + dz * math.cos(t)
        return abs(lx) <= sx / 2 and abs(lz) <= sz / 2

    def _grid_slots(self) -> list[tuple[float, float, float]]:
        """Valid slots of the discard grid, in order of play: columns toward dx, rows toward dz, without those that
        fall on the draw deck or outside the zone."""
        c = self.cfg
        (x0, y0, z0), (dx, dz), (kx, kz) = c.bot_discard_spot, c.bot_discard_step, c.bot_deck_spot
        rows = max(1, c.bot_discard_rows)
        cols = 8 if c.bot_discard_bounds is not None else 4
        out = []
        for i in range(cols * rows):
            col, row = divmod(i, rows)
            x, z = x0 + col * dx, z0 + row * dz
            if (x - kx) ** 2 + (z - kz) ** 2 > c.deck_clear ** 2 and self._in_discard_zone(x, z):
                out.append((x, y0, z))
        return out

    def _discard_slot(self, k: int) -> tuple[float, float, float]:
        """The k-th slot (in order of play) of the grid. It fills the grid, returns to the first slot and stacks on top
        (each lap a little higher): the cards merge into a Deck, which `read_discard` already knows how to read."""
        slots = self._grid_slots()
        lap, i = divmod(k, len(slots))
        x, y, z = slots[i]
        return (x, y + lap * self.cfg.discard_layer, z)

    def _adopt_extra_discards(self, on_pile: set[int]) -> None:
        """Bot cards that are in its discard on the table without the engine having discarded them (the human
        moved them: e.g. Confront Any Demon or God): they leave the engine's hand or deck and go to the discard."""
        st = self.game.players[self.bot]
        held = self.pending.bot_card.card_id if self.pending and self.pending.bot_card else None
        for c in st.full_set:
            if c.card_id in on_pile and c not in st.discard and c.card_id != held and c.card_id not in self.fx_in_flight \
                    and c not in st.tucked and c not in st.removed:
                for zone in (st.hand, st.deck):
                    if c in zone:
                        zone.remove(c)
                st.discard.append(c)
                self.bot_discarded.add(c.card_id)
                self.say(t("adopt.discard", title=c.title), ChatKind.WARNING)

    def adopt_table(self) -> None:
        """The table wins: the engine's hand, discard and positions become what is seen. Closes any debt."""
        st = self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        on_pile = self._table_discard() - {c.card_id for c in (*st.tucked, *st.removed)}
        st.discard[:] = [c for c in st.discard if c.card_id in on_pile] \
            + [by_id[i] for i in sorted(on_pile) if by_id[i] not in st.discard]
        self.bot_discarded = set(on_pile)
        self.game.drawn[self.bot] = 0
        self.dirty, self.unprojected, self.flush_failures = False, None, 0
        self.read_bot_hand()
        self._check_pieces()
        self.sync_positions()
        self.say(t("adopt.table"), ChatKind.WARNING)

    def _adopt_strays(self, missing: int) -> int:
        """Bot cards the table shows loose and face down (at its card spot or at the deck's) without
        being in its hand or its discard: they are returned to the hand and count as dealt."""
        by_id = {c.card_id: c for c in self.game.players[self.bot].full_set}
        known = set(self._table_hand_ids()) | self._table_discard()
        if self.pending and self.pending.bot_card:
            known.add(self.pending.bot_card.card_id)
        dx, dz = self.cfg.bot_deck_spot
        rows = [*self._rd_face("bot"),
                *(self.client.call_lua(lua.read_face_down_cards(dx, dz, self.cfg.reveal_radius)) or [])]
        moved = 0
        for r in rows:
            if moved >= missing:
                break
            if r["id"] in by_id and r["id"] not in known:
                known.add(r["id"])
                res = self._w(lua.return_card_to_hand(r["guid"], self.cfg.bot_seat), "cards").result or {}
                if res.get("returned"):
                    moved += 1
                    self.say(t("adopt.stray", title=by_id[r["id"]].title), ChatKind.WARNING)
        return moved

    def _reconcile_bot(self) -> None:
        """Makes physical what the engine decided for the bot (discards and draws) and re-reads the hand (see `_reconcile_stage`)."""
        self._reconcile_stage()()

    def _reconcile_stage(self) -> Callable[[], None]:
        """Queues what the engine decided for the bot (discards and draws) and returns the function that checks it.

        Idempotent: what the table already has (in the discard, even as a Deck) counts as moved, and only what is
        missing is resent. `bot_discarded` grows after seeing it in the discard and `drawn` only goes down by what the
        deck says it dealt, so any failure can be retried without duplicating anything. All the
        reads are done before writing: the discard and the draw go out in the same message."""
        g, st = self.game, self.game.players[self.bot]
        held = {self.pending.bot_card.card_id} if self.pending and self.pending.bot_card else set()
        held |= {c.card_id for c in self._bot_cards_in_play()}
        on_pile = self._table_discard()
        self._adopt_extra_discards(on_pile)
        new = [c.card_id for c in st.discard if c.card_id not in self.bot_discarded]
        hand_now = self._table_hand_ids() if g.drawn[self.bot] else []
        discard_op, todo = None, []
        if new:
            self.bot_discarded.update(i for i in new if i in on_pile)
            todo = [i for i in new if i not in on_pile]
            if todo:
                order = [c.card_id for c in st.discard]
                spots = [self._discard_slot(order.index(i)) for i in todo]
                shown = next((i for i in todo if i in self.zoom_ids), None)
                discard_op = self._w(lua.discard_cards(todo, spots, self.cfg.bot_discard_rot_y, identity=self._identity(),
                                                  scope=self._scope(), id_range=self.cfg.bot_card_ids,
                                                  zoom=self.zoom(), zoom_id=shown), "cards")
        self.zoom_ids.clear()

        def check_discard() -> None:
            if discard_op is None:
                return
            missing = set(todo) - set((discard_op.result or {}).get("moved") or [])
            if missing:
                raise SessionError(t("err.discard_missing", ids=sorted(missing)))
        if not self.cfg.batch:
            check_discard()
        n = g.drawn[self.bot]
        if n:
            # a deal whose reply arrived late is already in the table's hand: it is credited, not repeated.
            # Cards the engine already discarded (even if still flying to the pile) do not count as hand.
            gone = {c.card_id for c in st.discard} | held | self.fx_in_flight   # a bot effect is taking those out of the hand
            present = len({i for i in hand_now if i not in gone})
            n = max(0, min(n, len([c for c in st.hand if c.card_id not in held]) - present))
            g.drawn[self.bot] = n
        deal_op = None
        if n:
            deal_op = self._w(lua.deal_cards(self.cfg.bot_deck_guid, n, self.cfg.bot_seat,
                                             id_range=self.cfg.bot_card_ids, identity=self._identity(),
                                             **self._deck_kw()), "cards")
        # the card played face down counts in the engine's hand but is not in the table's hand
        want_discard = {c.card_id for c in st.discard}
        want_hand = len([c for c in st.hand if c.card_id not in held])
        if discard_op is not None or deal_op is not None:
            self._expect_hand = (self.cfg.bot_seat, want_hand)

        def fin() -> None:
            short = 0
            if deal_op is not None:
                res = deal_op.result or {}
                dealt = res.get("dealt") or 0
                short = n - min(n, dealt)
                if short:
                    short -= self._adopt_strays(short)
                g.drawn[self.bot] = short
            if self.cfg.batch:
                check_discard()
            if short:
                raise SessionError(t("err.deck_dealt", dealt=n - short, n=n, where=self.deck_where()))
            if any(o.domain == "fx" for o in self._queue):
                self._flush()                     # a bot effect that moves its cards (Pyrotechnics) is no `cards` write:
                                                  # no read sends it, and the check would see the table without it
            if not self._settle(lambda: len([i for i in self._table_hand_ids() if i not in held]) == want_hand
                                and self._table_discard() == want_discard):
                raise SessionError(t("err.table_mismatch"))
            self.bot_discarded.update(new)
            self.read_bot_hand()
        if not self.cfg.batch:
            fin()
            return lambda: None
        return fin

    def _alive_map(self) -> dict[str, bool]:
        return {fid: f.alive for fid, f in self.game.fighters.items()}

    def _announce_human_falls(self, alive_before: dict[str, bool]) -> None:
        """Human casualties caused by the bot (ability, A Momentary Glance...). The bot's own are projected by `_project`."""
        for fid, was in alive_before.items():
            f = self.game.fighters[fid]
            if was and not f.alive and f.owner == self.human:
                self._announce_fall(f)

    def _snapshot_bot(self) -> dict[str, tuple[int | None, bool]]:
        return {f.fid: (f.pos, f.alive) for f in self.game.own(self.bot, alive_only=False)}

    def _project(self, before: dict[str, tuple[int | None, bool]]) -> None:
        """Projects onto the table every bot piece movement made by the engine (including resurrections)."""
        self._project_stage(before)()

    def _project_stage(self, before: dict[str, tuple[int | None, bool]]) -> Callable[[], None]:
        """Queues the movements and returns the function that checks them (without `batch` it is checked now, piece by
        piece, as always)."""
        defer = self.cfg.batch
        pieces = self._table_pieces() if defer else None
        checks: list[Callable[[], None]] = []
        for fid, (pos, was_alive) in before.items():
            f, name = self.game.fighters[fid], self._name(self.game.fighters[fid])
            if f.alive and self.hand_moved.get(fid) == f.pos:
                check = None                      # the human already put this miniature there by hand
            elif not was_alive and f.alive:
                check = self._place_revived(f, name, defer, pieces)
            elif not f.alive:
                check = self._bury(fid, name, defer, pieces) if was_alive else None
            elif f.pos != pos:
                check = self._move_checked(fid, name, f.pos, pieces)
            else:
                check = None
            if check is not None:
                if defer:
                    checks.append(check)
                else:
                    check()

        self.hand_moved.clear()

        def fin() -> None:
            for c in checks:
                c()
        return fin

    def _move_checked(self, fid: str, name: str, space: int, pieces) -> Callable[[], None]:
        moved = self._move_stage(fid, space, pieces)
        if not self.cfg.batch:
            def check() -> None:
                if not moved():
                    raise SessionError(t("err.move_guid", name=name, guids="/".join(self._guids(fid)), space=space))
            return check

        def check() -> None:
            if not moved():
                raise SessionError(t("err.move_guid", name=name, guids="/".join(self._guids(fid)), space=space))
        return check

    def _announce_fall(self, f: Fighter) -> None:
        """Every casualty, wherever it comes from (combat, ability, bot effect, Remove, HP to 0), is announced the same way:
        '<name> falls' and what happens to the miniature. The bot's is set aside by `_bury`; the human's they remove themselves."""
        name = self._name(f)
        self._bury(f.fid, name)
        if f.owner == self.human:
            return
        if self.unprojected is not None and f.fid in self.unprojected:
            self.unprojected[f.fid] = (self.unprojected[f.fid][0], False)    # already set aside: `_project` does not repeat it

    def _bury(self, fid: str, name: str, defer: bool = False, pieces=None) -> Callable[[], None] | None:
        """A fallen piece (the bot's or the human's) sets itself aside in its fallen zone (`dead_spot` or `human_dead_spot`,
        one per piece) and the table is re-read to check it is no longer on the board; without a zone, or if TTS does
        not move it, the human is told to remove it. With `defer` it queues and returns the check."""
        owner = self.game.fighters[fid].owner
        mine = owner == self.bot
        spot = self.cfg.dead_spot if mine else human_dead_spot(self.cfg)
        done = t("bury.done_mine" if mine else "bury.done_human", name=name)
        failed = t("bury.failed_mine" if mine else "bury.failed_human", name=name)
        if spot is not None:
            slot = sorted(f.fid for f in self.game.own(owner, alive_only=False)).index(fid)
            at = fallen_slot(spot, mine, slot)
            if defer:
                info = (pieces if pieces is not None else self._table_pieces()).get(fid) or {}
                guids = [info["guid"]] if info.get("found") else self._guids(fid)
                op = self._w(lua.place_piece(guids[0], *at), "pieces")

                def check() -> None:
                    try:
                        res = op.result or {}
                    except TABLE_ERRORS:
                        res = {}
                    if res.get("moved") and self._off_board(fid):
                        self.say(done)
                    else:
                        self.say(failed, ChatKind.WARNING)
                return check
            for guid in self._guids(fid):
                try:
                    res = self._w(lua.place_piece(guid, *at), "pieces").result or {}
                except TABLE_ERRORS:
                    break
                if res.get("moved") and self._off_board(fid):
                    self.say(done)
                    return None
        self.say(failed, ChatKind.WARNING)
        return None

    def _off_board(self, fid: str) -> bool:
        """Table re-read: the miniature exists and is no longer on the board."""
        def away() -> bool:
            try:
                info = self._table_pieces().get(fid) or {}
            except TABLE_ERRORS:
                return False
            return bool(info.get("found")) and not self._on_board(info)
        return self._settle(away)

    def _place_revived(self, f: Fighter, name: str, defer: bool = False, pieces=None) -> Callable[[], None] | None:
        """Winged Frenzy: the Harpy returns; its miniature is moved to the space and checked on the table."""
        moved = self._move_stage(f.fid, f.pos, pieces)

        def there() -> bool:
            info = self._table_pieces().get(f.fid) or {}
            return bool(info.get("found")) and info.get("space") == f.pos

        def check() -> None:
            if moved() and self._settle(there):
                self.say(t("revive.back", name=name, where=describe(self.game, f.pos, (f.fid,), self._name)))
            else:
                self.say(t("revive.place_manual", name=name, where=describe(self.game, f.pos, (f.fid,), self._name)), ChatKind.YOUR_TURN)
        if defer:
            return check
        check()
        return None

    # ---------- the human's table ----------
    def _guids(self, fid: str) -> list[str]:
        return piece_guids(self.cfg.pieces[fid])

    def _table_pieces(self) -> dict[str, dict]:
        """fid -> {found, space, dist, type, name, guid} read by GUID (a single call). If the miniature has
        several GUIDs (one per state), the one that exists on the table counts."""
        guids = sorted({g for fid in self.cfg.pieces for g in self._guids(fid)})
        if self.cfg.batch:
            found = self._view("pieces")["pieces"]
            if not set(guids) <= set(found):          # the panel's snapshot predates a GUID resolved by name
                self.snap = None
                found = self._view("pieces")["pieces"]
        else:
            found = self.client.call_lua(lua.piece_spaces_by_guid(self.game.board, guids))
        found = found if isinstance(found, dict) else {}
        if not self._resolving:
            # A GUID that holds another hero's piece is always looked into; a GUID with nothing at it only on the first read
            # after start / resume / adopt (and not while the game is being set up: the pieces are still in their bags).
            full, self._piece_full_check = self._piece_full_check and self.setup is None, False
            wanted = {fid for fid, owner in piece_id.problems(self, found).items()
                      if fid not in self._piece_gave_up and (owner is not None or full)}
            if wanted:                                # look for the right piece by name
                before = {fid: self.cfg.pieces[fid] for fid in wanted}
                self.resolve_pieces(found)
                self._tell_piece_notes()
                if any(self.cfg.pieces[fid] != before[fid] for fid in wanted):
                    return self._table_pieces()
        out = {}
        for fid in self.cfg.pieces:
            hit = next(((g, found[g]) for g in self._guids(fid)
                        if isinstance(found.get(g), dict) and found[g].get("found")), None)
            out[fid] = {**hit[1], "guid": hit[0]} if hit else {"found": False}
        return out

    def resolve_pieces(self, found: dict | None = None) -> bool:
        """Checks every piece by name and re-points those whose GUID holds another piece (session_pieces). The lines for
        the player wait in `_piece_notes` until `_tell_piece_notes`."""
        self._resolving = True
        try:
            changed, notes = piece_id.resolve(self, found)
        finally:
            self._resolving = False
        self._piece_notes += notes
        return changed

    def _live_dials(self) -> dict[str, str]:
        """fid -> life dial GUID the engine may write and read: two dials with one GUID are told apart by name first (once per
        start / resume / adopt while it works, again at the next write while it does not); one that cannot be is left out and said."""
        if not self._dials_resolved and self.setup is None and piece_id.shared_dials(self):
            notes = piece_id.resolve_dials(self)
            if not self._dial_unresolved:
                self._dials_resolved = True
            for line in notes:
                if line not in self._dial_notes_said:          # an unresolved dial is retried at every write: said once
                    self._dial_notes_said.add(line)
                    self.say(line, ChatKind.WARNING)
        return {fid: g for fid, g in self.cfg.dials.items() if fid not in self._dial_unresolved}

    def _tell_piece_notes(self) -> None:
        notes, self._piece_notes = self._piece_notes, []
        for line in notes:
            self.say(line, ChatKind.WARNING)

    def _check_pieces(self) -> None:
        """At start, resume and adopt: GUIDs two heroes share in the data are said and the next table read verifies every
        piece by name (it is the read the step makes anyway: no extra message)."""
        self._piece_gave_up, self._piece_full_check = set(), True
        self._dials_resolved = False
        for line in piece_id.shared_guids(self):
            self.say(line, ChatKind.WARNING)
        self._tell_piece_notes()

    def _move_stage(self, fid: str, space: int, pieces: dict[str, dict] | None = None) -> Callable[[], bool]:
        """Queues the miniature's move (with the GUID the table shows; otherwise the first) and returns the
        function that says whether it moved, trying the other GUIDs if the first failed."""
        guids = self._guids(fid)
        order = guids
        if self.cfg.batch:
            info = (pieces if pieces is not None else self._table_pieces()).get(fid) or {}
            order = [info["guid"]] if info.get("found") else guids
        first = self._w(lua.move_piece(self.game.board, order[0], space), "pieces")

        def moved() -> bool:
            if (first.result or {}).get("moved"):
                return True
            return any((self._w(lua.move_piece(self.game.board, g, space), "pieces").result or {}).get("moved")
                       for g in order[1:])
        return moved

    def _move_piece(self, fid: str, space: int) -> bool:
        """Moves the miniature to a space trying its GUIDs in order until one exists."""
        return self._move_stage(fid, space)()

    def _on_board(self, info: dict) -> bool:
        return bool(info.get("found")) and info.get("dist", 0) <= self.cfg.off_board_dist

    def _announce_hazards(self, write_dials: bool = False) -> None:
        """Tells the chat about the hazard-edge damage the engine has charged since the last call (a move of the bot, a
        piece the human moved by hand): who, which edge, the new health. A fall is announced like any other; with
        `write_dials` the life dials are written (the human's move has no action of the bot to carry them)."""
        g = self.game
        hits, g.hazard_hits = g.hazard_hits, []
        for fid, (a, b), dmg, before in hits:
            f = g.fighters[fid]
            self.say(t("hazard.hit", name=self._name(f), a=a, b=b, dmg=dmg, before=before, after=max(before - dmg, 0)),
                     ChatKind.COMBAT)
            if not f.alive:
                self._announce_fall(f)
        if hits and write_dials:
            self._write_dials()
        if hits and g.winner is not None:
            self.say(t("game.over_fix", winner=g.winner))
            self._game_over_dialog()

    def _hand_move_pays(self, f: Fighter) -> bool:
        """Whether a change of position read from the table is a real move by the human (hazard edges hurt) and not a
        placement: the setup places pieces, effects put them down by hand (`game.placing`), and ESCAPE ARTIST places the
        hero instead of moving it (a boosted maneuver cannot be told from a plain one on the table: never charged)."""
        g = self.game
        if f.owner != self.human or not g.board.hazards or self.setup is not None or f.fid in g.placing:
            return False
        return not (f.hero and g.fx.hero_rule(f.owner, "maneuver_boost_places_hero"))

    def _escape_artist_placing(self, f: Fighter) -> bool:
        """The human's hero (ESCAPE ARTIST) is being PLACED by a boosted Maneuver: the boost is already read, or a boost card sits in
        their pile since the Maneuver began and has not been read yet (End action syncs positions before it reads the boost)."""
        g = self.game
        if not (f.hero and f.owner == self.human and self.maneuver_baseline is not None
                and g.fx.hero_rule(f.owner, "maneuver_boost_places_hero")):
            return False
        return self.maneuver_boosted is not None or any(
            can_be_boost(c) for c in g.players[self.human].discard if c.card_id not in self.maneuver_baseline)

    def _departed_by_hand(self, fighter: Fighter, origin: int, *, moved: bool = True) -> None:
        """The human moved `fighter` by hand: `left_zone` (the bot's ATTACK OF OPPORTUNITY) may hurt it. A placement or swap
        by hand (`moved=False`) is no departure."""
        with self._announcing_departure():
            self.game.departed(fighter, origin, moved=moved)

    @contextmanager
    def _announcing_departure(self):
        """Says what the departure ability dealt inside the block and writes the life dials (the human's move has no action
        of the bot to carry them). Hazard damage dealt by a walk in the block is announced by the hazard hook: the hp
        snapshot is retaken after each hook call so it is not said twice."""
        g = self.game
        before = {fid: (o.hp, o.alive) for fid, o in g.fighters.items()}
        hook = g.hazard_hook

        def after_hazards() -> None:
            if hook is not None:
                hook()
            before.update({fid: (o.hp, o.alive) for fid, o in g.fighters.items()})

        g.hazard_hook = after_hazards
        try:
            yield
        finally:
            g.hazard_hook = hook
        hurt = [(fid, hp, g.fighters[fid]) for fid, (hp, _) in before.items() if g.fighters[fid].hp < hp]
        for fid, hp, o in hurt:
            self.say(t("departure.hit", name=self._name(o), before=hp, after=max(o.hp, 0)), ChatKind.COMBAT)
            if not o.alive:
                self._announce_fall(o)
        if hurt:
            self._write_dials()
            if g.winner is not None:
                self.say(t("game.over_fix", winner=g.winner))
                self._game_over_dialog()

    def sync_positions(self) -> None:
        for fid, info in self._table_pieces().items():
            f = self.game.fighters[fid]
            if not f.alive:
                continue
            quiet = self.setup is not None        # during setup no pieces are placed yet: nothing to warn about
            name, guid = self._name(f), "/".join(self._guids(fid))
            if quiet and not self._on_board(info):
                continue
            if not info.get("found"):
                self._warn(fid, "missing", t("warn.missing", name=name, guid=guid))
            elif not self._on_board(info):
                self._warn(fid, "off", t("warn.off", name=name, dist=info["dist"], zone=zone_text(self.game, info["space"])))
            elif info["space"] != f.pos and not self.game.fx.can_move(f):
                self._warn(fid, "pinned", t("warn.pinned", name=name, where=describe(self.game, f.pos, (fid,), self._name)))
            else:
                if info["space"] != f.pos and f.pos is not None and self._hand_move_pays(f):
                    # the human moved this piece by hand: only the two ends are known, so the least-hazard shortest way is charged
                    with self._announcing_departure():
                        self.game.walk(f, info["space"], None)
                else:
                    moved_from = f.pos if info["space"] != f.pos and f.owner == self.human and not quiet else None
                    placed = fid in self.game.placing or self._escape_artist_placing(f)
                    if info["space"] != f.pos:
                        self.game.placing.discard(fid)
                    f.pos = info["space"]
                    if moved_from is not None:
                        self._departed_by_hand(f, moved_from, moved=not placed)
                for kind in ("missing", "off", "pinned"):
                    self._warned.discard((fid, kind))

    def sync_human(self) -> None:
        """Engine discard == table discard (additions and removals); hand size by count."""
        st = self.game.players[self.human]
        own = {x.card_id for x in st.full_set}
        def read() -> set[int]:                   # only the human's cards: foreign things in the zone neither count nor delay
            # a card that an effect of this step is taking out of your discard toward your deck (Searing Clarity, the
            # bot moves it) is not read again as discarded even if the snapshot lags
            aside = {x.card_id for x in (*st.tucked, *st.removed)}     # tucked or removed: still on their pile until they move them
            return ({r["id"] for r in self._rd_human_discard()} & own) - self.fx_in_flight - aside
        ids = read()
        self._swap_owed_copies(ids)
        known = {x.card_id for x in st.discard}
        # a change only counts if two reads see it (card in transit, edge); the click's snapshot is already the
        # second: the human cannot be dragging a card while pressing a button
        # A card the bot just dealt may still be flying from the deck to the hand over the discard zone: the snapshot of
        # the write that dealt it is not trusted (the live 7/11 case: Flourish's drawn card was read as discarded).
        in_flight = time.monotonic() - self._deal_at < DEAL_FLIGHT
        if ids != known and not (self.cfg.batch and self._trusted and not in_flight):
            if self.cfg.settle_wait > 0:
                time.sleep(self.cfg.settle_wait * (2.5 if in_flight else 1))
            if self.cfg.batch:
                self.snap = None
            again = read()
            ids = (ids & again) | (known & (ids | again))
        for i in list(self._transit):             # card just played: it is kept in the discard until it shows up
            if i in ids or self._transit[i] >= TRANSIT_READS:
                del self._transit[i]
            else:
                self._transit[i] += 1
                ids = ids | ({i} & known)
        for i in (self.pending_discard or {}).get("cards") or []:   # a bot effect discarded it: the human still has to move it
            ids = ids | ({i} & known)
        deck_qty = (self.snap or {}).get("human_deck_qty", -1) if self.cfg.batch else -1
        fresh = [c for c in st.discard if c.card_id not in ids and c.card_id not in self._gone]
        real = self._rd_human_count(len(st.hand))
        # If the draw deck grew by as many cards as just went missing, the deck tests where they went: the removal counts
        # at once, without waiting for the second button. Growth that explains one card less in the hand (Glimpse of hell:
        # hand -> deck) does not count, or a failed stray read would lower the counter.
        hand_drop = max(0, len(st.hand) - real)
        grew = (isinstance(deck_qty, int) and deck_qty >= 0 and self._deck_qty >= 0 and bool(fresh)
                and deck_qty - self._deck_qty - hand_drop >= len(fresh))
        drew = isinstance(deck_qty, int) and deck_qty >= 0 and self._deck_qty >= 0 and deck_qty < self._deck_qty
        # Wildfire: a burning card leaving the discard only returns to the hand if your table hand grew without
        # explanation (you picked it up) and the deck does not explain it (Rekindle, Searing Clarity: they shuffle it into the deck)
        wildfire, back = self._human_wildfire(), []
        # The credit expires at the button after the one that generated it and is only spent by a burning card that began to be
        # missing in that same read or later: the burning card from the bottom of the deck that returns to your hand at turn start
        # cannot send to the hand another one that Rekindle shuffles into the deck later.
        turn, at, credit = self._wild_credit
        credit = credit if turn == self.game.turn_no and self._epoch - at <= 1 else 0
        if real > len(st.hand):
            at, credit = self._epoch, credit + real - len(st.hand)
        for c in list(st.discard):
            if c.card_id in ids:
                self._gone.pop(c.card_id, None)
                continue
            # A missing card only leaves the discard if it is also missing at ANOTHER button (a stray read that
            # loses it cannot lower the destiny counter), or if the draw deck grew precisely because of it.
            if self._gone.setdefault(c.card_id, self._epoch) == self._epoch and not (grew and c in fresh):
                continue
            missing_since = self._gone.pop(c.card_id)
            st.discard.remove(c)
            st.deck.append(c)
            if (wildfire and "burning" in c.tags and not (grew and c in fresh) and len(back) < credit
                    and missing_since >= at):
                back.append(c)                          # returns to the hand, and into view
        self._wild_credit = (self.game.turn_no, at, credit - len(back)) if wildfire else (-1, -1, 0)
        for c in back:
            self.make_known(c, keep=tuple(back))
            self.game.players[self.bot].known.add(c, self.game.turn_no)
        if isinstance(deck_qty, int) and deck_qty >= 0:
            self._deck_qty = deck_qty
        in_play = self.game.fx.ongoing_card_id(self.human)     # your ONGOING scheme sits on the pile while in play
        self._land_in_discard(ids - {in_play})
        self._verify_maneuver_deal(real, len(ids))
        held = real + self._undealt_draws()       # the cards owed after a pending discard are not on the table yet
        self._trim_virtual_hand(held)
        hero = self.game.hero(self.human)
        if real > len(st.hand) and not self.game.fx.can_draw(self.human):      # a physical draw under Cold Iron
            self._warn(hero.fid, "draw", t("warn.draw", reason=choices.NO_DRAW_REASON))
        elif self.game.fx.can_draw(self.human):
            self._warned.discard((hero.fid, "draw"))
        # a card the bot knows is on top of your deck (Every Possible Angle) is not in your hand unless the deck shrank
        top = set() if drew else set(self.game.players[self.bot].known.top_of_deck)
        while len(st.hand) < held:
            spare = next((c for c in st.deck if c.card_id not in top), None)
            if spare is None:
                break
            st.deck.remove(spare)
            st.hand.append(spare)
        if self._track_destiny() and not self._destiny_tried:
            self._destiny_tried = True                # one attempt per button: a broken dial does not slow every read
            self._write_dials(only_destiny=True, post=True)   # HP is only written after a real change

    def _swap_owed_copies(self, ids: set[int]) -> None:
        """A bot look named a card to discard (Set the Stage, Confront Any Demon or God); the engine already put THAT
        copy on the pile. Copies of one title are interchangeable: if another copy of the title is on the table pile
        and the named one is not, the engine swaps them (the named one goes back to the hand it was seen in) and the
        debt is paid by the copy that arrived, instead of counting the arrival as one more discard."""
        d = self.pending_discard
        if not d or not d.get("cards"):
            return
        st = self.game.players[self.human]
        by_id = {c.card_id: c for c in st.full_set}
        owed = list(d["cards"])
        for n, i in enumerate(owed):
            card = by_id.get(i)
            if i in ids or card is None or card not in st.discard:
                continue
            copy = next((c for c in st.full_set if c.title == card.title and c.card_id in ids and c not in st.discard
                         and c.card_id not in owed), None)
            if copy is None:
                continue
            st.discard.remove(card)
            st.hand.append(card)
            self.game.players[self.bot].known.add(card, self.game.turn_no)
            owed[n] = copy.card_id
        d["cards"] = owed

    def _trim_virtual_hand(self, target: int) -> None:
        """The virtual human hand loses cards because the real one has fewer (shuffled or put away face down): which
        real cards left is unknown. The model drops the cards the bot was not told about first; only when that is
        not enough does a seen card have to go, and then what the bot saw degrades to "possible" instead of staying
        certain."""
        st = self.game.players[self.human]
        known = self.game.players[self.bot].known
        told = set(known.seen) | set(known.possible)
        dropped = len(st.hand) - target
        if dropped > sum(1 for c in st.hand if c.card_id not in told):
            known.degrade(dropped, target)
            told = set(known.seen) | set(known.possible)
        while len(st.hand) > target:
            spare = next((c for c in reversed(st.hand) if c.card_id not in told), st.hand[-1])
            st.hand.remove(spare)
            st.deck.append(spare)

    def make_known(self, card: Card, keep: tuple = (), game=None) -> None:
        """The human's hand is virtual: when a card is seen it takes the place of one of the virtual hand. `game`: a
        clone (the dry run of `session_boost`), not the live one."""
        fx_table.make_known(game or self.game, self.human, card, keep)
