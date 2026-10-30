"""TTS translators: what an op does to the real table, one function per op type and per who moves the objects.

An op that touches what is on the table leaves an intent (`effects.table.intent`: {"op", ...}); the session hands each
one, with the cause the chat blames, to `translate`. The registry `TRANSLATORS` is keyed by op type and holds two
variants:

  * `bot`   the bot moves the objects itself (a Lua write through `Session._w`, said in the chat) and returns the
            checks to run once the step's composite went out; when the table refuses, the check falls back to the
            human variant, so a failed write never leaves the game stuck;
  * `human` the human acts by hand: the variant says what to move and owes it to the existing flows that wait for it
            and validate it (`Session.pending_discard` settled at "Fin de accion", the table sync, the draws the
            human takes themselves).

`mode` picks the variant for an intent, or None when the op has no business with the table (the bot's own cards and
miniatures keep their projection in `session_bot_effects`). The before/after diff of `session_bot_effects.project`
stays as the final consistency check: it detects what changed, and whatever the ops did not report (an intent-less
change) is translated through this same registry. Phase 1: `draw`, `discard`, `move`. Ops without a translator keep
the diff path untouched (docs/effects-dsl.md, section 21)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .spaces import describe
from .tts import effects_bridge, lua
from .tts.client import TTSLuaError
from .tts.lua import ChatKind

DOMAIN = "fx"                  # queue domain of the writes of a projection: no read of the session forces them out early
ERRORS = (TTSLuaError, OSError)
BOT, HUMAN = "bot", "human"

Check = Callable[[], None]
Variant = Callable[["object", dict, "Ctx"], list[Check]]


@dataclass(frozen=True)
class Ctx:
    """What a translation needs besides the intent: whose effect the chat blames and the engine snapshot taken before
    the step (`session_bot_effects.snapshot`), None where no diff is involved."""
    cause: str = ""
    before: dict | None = None


@dataclass(frozen=True)
class Translator:
    mode: Callable[[object, dict], str | None]
    bot: Variant
    human: Variant


TRANSLATORS: dict[str, Translator] = {}


def register(op: str, *, mode: Callable[[object, dict], str | None], human: Variant) -> Callable[[Variant], Variant]:
    """Registers the decorated function as the bot variant of `op`; `human` is the by-hand variant."""
    def wrap(bot: Variant) -> Variant:
        TRANSLATORS[op] = Translator(mode, bot, human)
        return bot
    return wrap


def translate(session, intent: dict, ctx: Ctx) -> list[Check] | None:
    """The checks of the variant that handles `intent`, or None when no translator takes it (the op has none, or the
    intent is not about the table): the caller keeps its diff path."""
    translator = TRANSLATORS.get(intent["op"])
    if translator is None:
        return None
    mode = translator.mode(session, intent)
    if mode is None:
        return None
    return (translator.bot if mode == BOT else translator.human)(session, intent, ctx)


# ---------------------------------------------------------------- shared helpers

def result_of(op) -> dict:
    try:
        return op.result or {}
    except ERRORS:
        return {}


def join_titles(titles) -> str:
    titles = list(titles)
    return titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " y " + titles[-1]


def plural(n: int, word: str = "carta") -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


# ---------------------------------------------------------------- draw (the human's draws)

def _draw_mode(session, intent: dict) -> str | None:
    if intent["player"] != session.human:
        return None                               # the bot's draws are its own hidden zones (`_bot_cards`)
    return BOT if session.cfg.human_deck_guid else HUMAN


def _draw_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    why = f" ({intent['cause']})" if intent.get("cause") else ""
    session.say(f"Robas {plural(intent['n'])}{why}: hazlo en la mesa.", ChatKind.YOUR_TURN)
    return []


@register("draw", mode=_draw_mode, human=_draw_human)
def _draw_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """The cards owed to the human are dealt from their physical deck to their hand (`Session._deal_human_cards`)."""
    session._deal_human_cards(intent["n"], intent.get("cause"))
    return []


# ---------------------------------------------------------------- discard

def _discard_mode(session, intent: dict) -> str | None:
    if intent["player"] != session.human:
        return None                               # the bot's discards are reconciled with its pile
    if intent["zone"] == "in_play":
        return BOT if session.cfg.human_ongoing_spot is not None else HUMAN
    from .session import CROWN                    # the session imports this module: resolved at call time
    return BOT if intent.get("reason") == CROWN else HUMAN


def _discard_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    st = session.game.players[session.human]
    zone = intent["zone"]
    if zone == "in_play":
        return _left_play_by_hand(session, intent, ctx)
    d = session.pending_discard or {"n": 0, "baseline": intent.get("baseline", len(st.discard)), "kind": "cards"}
    if zone == "hand" and "cards" in intent:      # named cards: the human puts them on the pile, the sync waits for them
        by_id = {c.card_id: c for c in st.full_set}
        d["cards"] = list(d.get("cards") or []) + intent["cards"]
        session.pending_discard = d
        session.say(f"Pon {join_titles(by_id[i].title for i in intent['cards'])} de tu mano en tu descarte "
                    f"({ctx.cause}) y pulsa Fin de accion.", ChatKind.YOUR_TURN)
    elif intent["n"] > 0:                         # a count: the human chooses which ones
        d["n"] += intent["n"]
        session.pending_discard = d
        session.say(f"Descarta {intent['n']} carta(s) ({intent['reason']}) y pulsa Fin de accion."
                    f"{session._wildfire_hint()}", ChatKind.YOUR_TURN)
    return []


@register("discard", mode=_discard_mode, human=_discard_human)
def _discard_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    if intent["zone"] == "in_play":
        return _left_play_by_bot(session, intent, ctx)
    # Crown Of Flame (Ivan, 30/10): the bot moves the human's whole hand; what the table could not move is asked by hand
    st = session.game.players[session.human]
    left = session._discard_human_hand(intent["n"], intent["reason"])
    baseline = len(st.discard) + (0 if any(c.title == intent["reason"] for c in st.discard) else 1)   # the plan lands after
    return _discard_human(session, {**intent, "n": left, "baseline": baseline}, ctx)


def _title_of(session, card_id: int) -> str:
    return next(c.title for c in session.game.players[session.human].full_set if c.card_id == card_id)


def _left_play_by_hand(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Your ONGOING left play. With an ONGOING spot it is owed to your discard pile (the sync protects it until it
    is there); without one it already sits on the pile."""
    card_id, title = intent["card"], _title_of(session, intent["card"])
    if session.cfg.human_ongoing_spot is None:
        session.say(f"{title} deja de estar en juego ({ctx.cause}): queda en tu descarte.", ChatKind.SCHEME)
        return []
    st = session.game.players[session.human]
    d = session.pending_discard or {"n": 0, "baseline": len(st.discard), "kind": "cards"}
    if card_id in (d.get("cards") or []):
        return []
    d["cards"] = list(d.get("cards") or []) + [card_id]
    session.pending_discard = d
    session.say(f"{title} deja de estar en juego ({ctx.cause}): pasala de tu zona ONGOING a tu descarte y pulsa Fin de "
                "accion.", ChatKind.YOUR_TURN)
    return []


def _left_play_by_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Your ONGOING scheme left play (Pact Of Freedom when Baba Yaga takes 2+ combat damage...): the bot pings it on
    your ONGOING zone, says why it leaves, waits `ongoing_hold` seconds and moves it to your discard pile itself. Any
    failure (the zone cannot be read, the card is not there exactly once, no identity, the table refuses) falls back
    to asking you to move it (`_left_play_by_hand`)."""
    from .session import TABLE_ERRORS             # the session imports this module: resolved at call time
    cfg, card_id = session.cfg, intent["card"]
    title = _title_of(session, card_id)
    try:
        here = [r for r in session._rd_ongoing("human")
                if isinstance(r, dict) and r.get("id") == card_id and isinstance(r.get("guid"), str)]
        if len(here) != 1:
            raise TTSLuaError(f"{title} no esta una sola vez en tu zona ONGOING ({len(here)})")
        identity = session._identity("human")
        move = lua.card_to_discard(here[0]["guid"], cfg.human_discard_zone, cfg.human_card_ids, identity=identity)
        _show_and_wait(session, here[0]["guid"],
                       f"{title} deja de estar en juego ({ctx.cause}): mira el ping, la llevo yo a tu descarte.")
        op = session._w(move, "cards")
    except TABLE_ERRORS:
        return _left_play_by_hand(session, intent, ctx)
    session._transit[card_id] = 0                 # the sync keeps it on the engine's pile until the table shows it there

    def check() -> None:
        res = result_of(op)
        if res.get("zone") is not True or res.get("moved") != [card_id]:
            _left_play_by_hand(session, intent, ctx)
    return [check]


def _show_and_wait(session, guid: str, text: str) -> None:
    """Pings the card, says why in the chat and on screen, and lets the ping be seen: in a batch the wait is inside
    the TTS script that carries the ping (`lua.hold`), otherwise it is a sleep."""
    cfg = session.cfg
    session._w(lua.ping_objects([cfg.bot_seat, cfg.human_seat], [[guid]]), "misc")
    session.say(text, ChatKind.SCHEME, shown=True)
    for chunk in lua.ascii_text(text):
        session._w(lua.broadcast(chunk, ChatKind.SCHEME), "misc")
    if cfg.ongoing_hold <= 0:
        return
    if cfg.batch:
        session._w(lua.hold(cfg.ongoing_hold), "misc")
    session._flush()
    if not cfg.batch:
        time.sleep(cfg.ongoing_hold)


# ---------------------------------------------------------------- move (the human's miniatures the bot's effects move)

def _move_mode(session, intent: dict) -> str | None:
    return BOT if intent["owner"] == session.human else None     # the human moves their own by hand (session_moves)


def _moved_piece(session, intent: dict, ctx: Ctx):
    """The human's fighter if it really ended elsewhere than it started (a fall is announced by the combat / hp
    code), else None."""
    pos0, alive0 = ctx.before["human_pieces"][intent["fid"]]
    f = session.game.fighters[intent["fid"]]
    if not f.alive or f.pos is None or (alive0 and f.pos == pos0):
        return None
    return f


def _move_say(session, intent: dict, ctx: Ctx, moved: bool) -> None:
    g = session.game
    f = g.fighters[intent["fid"]]
    name, space = session._name(f), describe(g, f.pos, (f.fid,), session._name)
    what = "se mueve" if ctx.before["human_pieces"][f.fid][1] else "vuelve al tablero"
    if moved:
        session.say(f"{name} {what} a {space}: lo he movido yo (efecto del bot).", ChatKind.MOVE)
    else:
        session.say(f"{name} {what} a {space} por un efecto del bot: no he podido mover su "
                    "miniatura, muevela tu.", ChatKind.YOUR_TURN)


def _move_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    if _moved_piece(session, intent, ctx) is not None:
        _move_say(session, intent, ctx, moved=False)
    return []


@register("move", mode=_move_mode, human=_move_human)
def _move_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Ivan's rule "the bot moves what its card says": `move_piece` by GUID (the one the table shows for a miniature
    with states), said once the table confirms; when it does not, the human is told to move it."""
    f = _moved_piece(session, intent, ctx)
    if f is None:
        return []
    guids = session._guids(f.fid)
    guid = guids[0]
    if len(guids) > 1:                            # a miniature with states: the GUID the table shows now
        info = session._table_pieces().get(f.fid) or {}
        guid = info["guid"] if info.get("found") else guid
    op = session._w(effects_bridge.move_human_piece(session.game.board, guid, f.pos), DOMAIN)

    def check() -> None:
        _move_say(session, intent, ctx, moved=bool(result_of(op).get("moved")))
    return [check]
