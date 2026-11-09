"""EffectState: everything the DSL adds to a Game, kept in `game.fx`.

Hooks (`adjust_damage`, `can_draw`, `can_gain_actions`, `emit`...) are called by `Game` at fixed points. In C1 they
are no-ops; later phases fill them in without touching state.py again. They run on every clone used by ISMCTS,
so they must stay cheap."""
from __future__ import annotations

import weakref
from typing import Iterable

# Heroes whose cards and ability the interpreter resolves by default, whoever plays them (C5: Medusa; D1 the Hellboy
# box for the bot, E2 for the human too, in table mode: effects/table.py). `Game` derives `fx.dsl_heroes` from the
# heroes in play and persist omits the set when it is this default, so old saves load unchanged.
INTERPRETED_HEROES = frozenset({"medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "houdini", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "yennefer-triss", "triss-yennefer"})


def interpreted(slugs: Iterable[str]) -> set[str]:
    """The heroes among `slugs` the interpreter resolves."""
    return {s for s in slugs if s in INTERPRETED_HEROES}


def default_dsl_heroes(game) -> set[str]:
    return interpreted(p.hero.slug for p in game.players)


class EffectState:
    __slots__ = ("statuses", "ongoing", "counters", "modifiers", "dsl_heroes", "turn_start_pos", "attacked", "taken",
                 "maneuvers", "acting", "parked", "choosers", "said", "intents", "whole_hand", "played", "lost", "won", "_game_ref")

    def __init__(self) -> None:
        self.statuses: list[dict] = []                   # active status effects (name, target, until, amount)
        self.ongoing: list[dict | None] = [None, None]   # the one active ONGOING card per player
        self.counters: list[dict[str, int]] = [{}, {}]   # ability counters per player
        self.modifiers: list[dict] = []                  # active rule modifiers (max hand size, damage bonus...)
        self.dsl_heroes: set[str] = set()                # hero slugs whose cards the interpreter resolves
        self.turn_start_pos: dict[str, int] = {}         # fid -> space at the start of the turn (moved_this_turn)
        self.attacked: list[str] = []                    # fids that attacked this turn (one entry per attack; last = current)
        self.taken = 0                                   # actions the current player has spent this turn
        self.maneuvers = 0                               # Maneuver actions the current player has taken this turn (Golden Bat's THE FIRST SUPERHERO)
        self.played: list[int] = [0, 0]                  # cards each player has played on their own turn (attack, scheme)
        self.lost = [0, 0]                               # combats each player lost this turn (Raphael's ANGER ISSUES, Payback time!)
        self.won = [0, 0]                                # combats each player won this turn (Bullseye: "if you already won a combat this turn")
        self.acting: int | None = None                   # player whose effect op is running right now (transient)
        self.parked: list = []                           # EffectRuns of triggers a chooser paused, in firing order (saved)
        self.choosers = None                             # who answers trigger decisions; None = the bots' controllers
        self.said: list[tuple[str, str]] = []            # (kind, line) narrated for the table player's triggers (E2, transient)
        self.intents: list[dict] | None = None           # what table ops did (`table.intent`); None = nobody listens (clones), transient
        self.whole_hand = False                          # the discard being forced takes the player's whole hand (transient)
        self._game_ref = None

    def attach(self, game) -> None:
        """Tells the hooks which Game they belong to. Game calls it for every EffectState it takes (new, clone, load)."""
        self._game_ref = weakref.ref(game)

    def interprets(self, player: int) -> bool:
        """`player`'s hero runs on the effects interpreter (its cards and triggers resolve in the engine)."""
        return bool(self.dsl_heroes) and self.game().players[player].hero.slug in self.dsl_heroes

    # hooks: the bodies live in effects/modifiers.py and effects/ongoing.py; the guards keep the flag-off path free
    def _has_modifiers(self) -> bool:
        """Statuses, loose modifiers or an ONGOING card in play (whose modifiers modifiers.py reads from the card)."""
        return bool(self.statuses or self.modifiers or any(s is not None and s["card_id"] is not None
                                                           for s in self.ongoing))

    def adjust_damage(self, fighter, n, source):
        if not self._has_modifiers():
            return n
        from .modifiers import adjust_damage
        return adjust_damage(self, fighter, n, source)

    def can_draw(self, player: int) -> bool:
        if not self._has_modifiers():
            return True
        from .modifiers import can_draw
        return can_draw(self, player)

    def can_gain_actions(self, player: int) -> bool:
        if not self._has_modifiers():
            return True
        from .modifiers import can_gain_actions
        return can_gain_actions(self, player)

    def hand_limit(self, player: int, default: int) -> int:
        """Largest hand `player` may keep at the end of the turn (Pact Of Secrecy lowers it to 3)."""
        if not self.dsl_heroes:
            return default
        from . import ongoing
        return ongoing.hand_limit(self.game(), player, default)

    def may_attack(self, player: int) -> bool:
        """False while an ONGOING forbids attacking as the first action of the turn (Pact Of Freedom)."""
        if not self.dsl_heroes or not any(self.ongoing):
            return True
        from . import ongoing
        return ongoing.may_attack(self.game(), player)

    def count_action(self) -> None:
        if self.dsl_heroes:
            from .events import tracked
            if "taken" in tracked(frozenset(self.dsl_heroes)):
                self.taken += 1

    def count_maneuver(self) -> None:
        """The current player took a Maneuver action (Game.maneuver, the session's Maneuver button). Only recorded for games whose
        data reads it (`events.TRACKS`)."""
        if self.dsl_heroes:
            from .events import tracked
            if "maneuvers" in tracked(frozenset(self.dsl_heroes)):
                self.maneuvers += 1

    def maneuvered(self, player: int) -> bool:
        """`player` has already taken a Maneuver action in the turn that is running (their own turn only)."""
        return bool(self.maneuvers) and self.game().turn == player

    def count_played(self, player: int) -> None:
        """`player` plays a card (an attack or a scheme) on their own turn: what Cowabunga!! counts. Defenses on the
        rival's turn are not counted. Only recorded for games whose data reads it (`events.TRACKS`)."""
        if self.dsl_heroes and player == self.game().turn:
            from .events import tracked
            if "played" in tracked(frozenset(self.dsl_heroes)):
                self.played[player] += 1

    def on_damage(self, fighter, n, source: str, by) -> None:
        """`fighter` has just lost `n` hp (alive or not yet resolved) from `source` ("effect", "combat",
        "exhaustion", "set_hp"); `by` is the fighter that dealt it, when known."""
        if self.dsl_heroes:
            from . import events
            events.damage_dealt(self.game(), fighter, n, source, by)

    def can_force_discard(self, player: int, source_player: int) -> bool:
        """False vetoes a discard that `source_player` forces on `player` (Counterhex Shield)."""
        if not self._has_modifiers():
            return True
        from .modifiers import can_force_discard
        return can_force_discard(self, player, source_player)

    def hero_rule(self, player: int, rule: str) -> bool:
        """The hero of `player` has the passive rule `rule` (ESCAPE ARTIST: `maneuver_boost_places_hero`)."""
        if not self.dsl_heroes:
            return False
        from .modifiers import hero_rule
        return hero_rule(self.game(), player, rule)

    def combat_damage_reduction(self, fighter) -> int:
        """Combat damage the hero's ability takes off a blow that lands on `fighter` (Luke Cage: 2); 0 for any other fighter."""
        if not self.dsl_heroes or not fighter.hero:
            return 0
        from .modifiers import hero_rule_amount
        return hero_rule_amount(self.game(), fighter.owner, "combat_damage_reduction")

    def boost_bonus(self, player: int) -> int:
        """What `player`'s ONGOING adds to each BOOST value they spend (Advisor to the king: +1)."""
        if not self.dsl_heroes or not any(self.card_slots()):
            return 0
        from .ongoing import boost_bonus
        return boost_bonus(self.game(), player)

    def departure_damage(self, fighter, dest: int) -> int:
        """Damage the rival hero's ability would deal `fighter` for going to `dest` (leaving a zone); the bot prices its moves with it."""
        if not self.dsl_heroes:
            return 0
        from .events import departure_damage
        return departure_damage(self.game(), fighter, dest)

    def boost_effects(self, player: int, card) -> None:
        """`card` was spent as a BOOST outside a combat (a Maneuver): its `boost` moment runs now as an effect of `player`."""
        if self.dsl_heroes:
            from .events import run_boost
            run_boost(self.game(), player, card)

    def can_move(self, fighter) -> bool:
        """False when a status keeps `fighter` where it is (Burning Barrier, Counterhex Shield vs. enemy effects)."""
        if not self._has_modifiers():
            return True
        from .modifiers import can_move
        return can_move(self, fighter)

    def emit(self, name: str, *args) -> None:
        """Statuses of the `status` op expire first, then the event reaches triggers and ONGOING `until`s."""
        if self.statuses and name in ("start_of_turn", "end_of_turn", "after_maneuver", "after_attack"):
            from .modifiers import expire_on_event
            expire_on_event(self, name, *args)
        if self.dsl_heroes:
            from . import events
            events.dispatch(self.game(), name, args)

    def game(self):
        game = None if self._game_ref is None else self._game_ref()
        if game is None:
            raise RuntimeError("EffectState is not attached to a Game (Game.fx must be set through Game.attach_fx)")
        return game

    # ongoing slot
    def ongoing_card_id(self, player: int) -> int | None:
        slot = self.ongoing[player]
        return None if slot is None else slot["card_id"]

    def card_slots(self) -> list[dict | None]:
        """The ongoing slots that hold a real card; the pre-DSL bonus slots are saved apart (`combat_bonus`)."""
        return [s if s is not None and s["card_id"] is not None else None for s in self.ongoing]

    def set_ongoing(self, player: int, card_id: int) -> int | None:
        """Puts a scheme in play. Ivan's ruling (28/10): one per player, the new one replaces the old.
        Returns the replaced card id (or None)."""
        old = self.ongoing_card_id(player)
        self.ongoing[player] = {"card_id": card_id}
        return old

    def take_ongoing(self, player: int) -> int | None:
        old = self.ongoing_card_id(player)
        self.ongoing[player] = None
        return old

    # counters
    def counter_value(self, player: int, name: str, default: int = 0) -> int:
        return self.counters[player].get(name, default)

    def set_counter(self, player: int, name: str, value: int) -> None:
        self.counters[player][name] = value

    # clone / persist
    def is_empty(self) -> bool:
        return not (self.statuses or any(self.ongoing) or any(self.counters) or self.modifiers or self.dsl_heroes
                    or self.turn_start_pos or self.attacked or self.taken or self.maneuvers or any(self.played) or any(self.lost) or any(self.won))

    def copy(self) -> "EffectState":
        """The state a clone (search, simulation) starts from. `choosers` and `parked` stay with the live game: a
        clone decides with its own controllers (the bots' policy), never with the panel of the human."""
        c = EffectState()
        if self.is_empty():
            return c
        c.statuses = [dict(s) for s in self.statuses]
        c.ongoing = [None if s is None else dict(s) for s in self.ongoing]
        c.counters = [dict(x) for x in self.counters]
        c.modifiers = [dict(m) for m in self.modifiers]
        c.dsl_heroes = set(self.dsl_heroes)
        c.turn_start_pos = dict(self.turn_start_pos)
        c.attacked = list(self.attacked)
        c.taken = self.taken
        c.maneuvers = self.maneuvers
        c.played = list(self.played)
        c.lost = list(self.lost)
        c.won = list(self.won)
        return c

    def to_dict(self) -> dict:
        """Only the non-empty parts, so a game without effects saves byte-identical to before."""
        out: dict = {}
        if self.statuses:
            out["statuses"] = [dict(s) for s in self.statuses]
        slots = self.card_slots()
        if any(slots):
            out["ongoing"] = [None if s is None else dict(s) for s in slots]
        if any(self.counters):
            out["counters"] = [dict(x) for x in self.counters]
        if self.modifiers:
            out["modifiers"] = [dict(m) for m in self.modifiers]
        if self.dsl_heroes:
            out["dsl_heroes"] = sorted(self.dsl_heroes)
        if self.turn_start_pos:
            out["turn_start_pos"] = dict(self.turn_start_pos)
        if self.attacked:
            out["attacked"] = list(self.attacked)
        if self.taken:
            out["taken"] = self.taken
        if self.maneuvers:
            out["maneuvers"] = self.maneuvers
        if any(self.played):
            out["played"] = list(self.played)
        if any(self.lost):
            out["lost"] = list(self.lost)
        if any(self.won):
            out["won"] = list(self.won)
        if self.parked:
            out["parked"] = [run.to_dict() for run in self.parked]
        return out

    @classmethod
    def from_dict(cls, raw: dict | None) -> "EffectState":
        fx = cls()
        raw = raw or {}
        fx.statuses = [dict(s) for s in raw.get("statuses", [])]
        fx.ongoing = [None if s is None else {"card_id": int(s["card_id"])} for s in raw.get("ongoing", [None, None])]
        fx.counters = [{str(k): int(v) for k, v in side.items()} for side in raw.get("counters", [{}, {}])]
        fx.modifiers = [dict(m) for m in raw.get("modifiers", [])]
        fx.dsl_heroes = set(raw.get("dsl_heroes", []))
        fx.turn_start_pos = {str(k): int(v) for k, v in raw.get("turn_start_pos", {}).items()}
        fx.attacked = list(raw.get("attacked", []))
        fx.taken = int(raw.get("taken", 0))
        fx.maneuvers = int(raw.get("maneuvers", 0))
        fx.played = [int(n) for n in raw.get("played", [0, 0])]
        fx.lost = [int(n) for n in raw.get("lost", [0, 0])]
        fx.won = [int(n) for n in raw.get("won", [0, 0])]
        if raw.get("parked"):
            from .run import EffectRun                  # run.py imports the combat flow, which imports the engine
            fx.parked = [EffectRun.from_dict(r) for r in raw["parked"]]
        return fx
