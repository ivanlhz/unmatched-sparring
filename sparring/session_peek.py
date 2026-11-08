"""The top card of a deck looked at through a card (The future of Ninjutsu: "look at the top card of any deck"), at the table.

The human looks at the bot's deck. The bot's deck order is the engine's, so the card to show is the engine's top card:
the bot takes THAT card out of its physical deck by CardID and deck image (`lua.deck_card_to_spot`, not the physical top
card: the table's order is not the engine's), lays it face up in the row of `bot_row_spot`, pings it and says it in the
chat. The game waits at the panel (`future` = "peek" request). The human's answer, leave on top or put at the bottom, is
the continue button: the bot puts the card back on top or at the bottom of its deck (`card_to_deck_top` / `_bottom`), so
the table agrees with the engine's order. The shown card is saved (`Session.peek`) so `--resume` can say it again.

The bot looks at the human's deck. Their engine deck is virtual, so the real top card is read from the table
(`read_top`, installed as `Game.deck_reader`). What the bot decided reaches the table through the `future_look` intent:
put at the bottom, the bot moves the card itself (`lua.deck_top_to_bottom`) and says only that it looked and what it
did; the card is not public, so it is never named. A card left on top is only announced."""
from __future__ import annotations

import math

from .i18n import t
from .session_translators import DOMAIN, ERRORS, BOT, HUMAN, register, result_of
from .tts import lua
from .tts.lua import ChatKind

LEAVE, BOTTOM = 0, 1


# ---------------------------------------------------------------- the human looks at the bot's deck

def wants(session, req) -> bool:
    """The pause shows the bot's top card to the human."""
    return (req.kind == "effect" and req.player == session.human and req.extra.get("future") == "peek"
            and req.extra.get("deck_of") == session.bot)


def open_row(session, req) -> None:
    """Lays the bot's engine top card face up in the row, pings it and says it. A table that does not give the card
    leaves the choice to the panel: the chat names the card anyway, the human is entitled to see it."""
    from .session import SessionError             # the session imports this module: resolved at call time
    cfg = session.cfg
    card = session.game.card_of(req.extra["top"], session.bot)
    at = session._look_spots(1, card_row=True)[0]
    session.peek = {"card": card.card_id, "at": [at[0], at[2]], "guid": None, "taken": False}
    try:
        op = session._w(lua.deck_card_to_spot(card.card_id, cfg.bot_deck_guid, at, session._look_rot(), cfg.bot_card_ids,
                                              identity=session._identity(), **session._deck_kw()), DOMAIN)
        session._w(lua.ping_points([cfg.bot_seat, cfg.human_seat], [at]), "misc")
    except ERRORS + (SessionError, ValueError, TypeError):
        session.say(t("peek.not_taken", card=card.title), ChatKind.WARNING)
        return
    session._post.append(lambda: _opened(session, op, card))
    session.say(t("peek.look", card=card.title), ChatKind.YOUR_TURN)


def _opened(session, op, card) -> None:
    res = result_of(op)
    if res.get("taken") and isinstance(res.get("guid"), str) and session.peek is not None:
        session.peek.update(taken=True, guid=res["guid"])
        if res.get("single") and _triple(res.get("home")) and _triple(res.get("rot")):
            session.peek.update(home=list(res["home"]), rot=list(res["rot"]))      # the last card: it goes back where the deck lay
        return
    session.say(t("peek.not_taken", card=card.title), ChatKind.WARNING)


def answered(session, asked, value: list, ok: bool) -> None:
    """The answer of a pause was delivered (`asked` is the request it answered): the card goes back where the human said."""
    if not ok or session.peek is None or asked is None or asked.extra.get("future") != "peek":
        return
    peek, session.peek = session.peek, None
    bottom = value[0] == BOTTOM
    where = t("peek.where_bottom" if bottom else "peek.where_top")
    card = session.game.card_of(peek["card"], session.bot)
    if not peek["taken"]:
        return
    from .session import SessionError
    cfg = session.cfg
    build = lua.card_to_deck_bottom if bottom else lua.card_to_deck_top
    try:
        if peek.get("home"):      # one card was the whole deck: face down at its place, which is the deck again (top = bottom)
            op = session._w(lua.card_home(peek["guid"], peek["home"], peek["rot"], cfg.bot_card_ids,
                                          identity=session._identity()), DOMAIN)
        else:
            op = session._w(build(peek["guid"], cfg.bot_deck_guid, cfg.bot_card_ids, identity=session._identity(),
                                  **session._deck_kw()), DOMAIN)
    except ERRORS + (SessionError, ValueError, TypeError):
        session.say(t("peek.back_failed", card=card.title, where=where), ChatKind.WARNING)
        return
    session.say(t("peek.back_bottom" if bottom else "peek.back_top", card=card.title), ChatKind.SCHEME)
    session._post.append(lambda: None if result_of(op).get("placed")
                         else session.say(t("peek.back_failed", card=card.title, where=where), ChatKind.WARNING))


def remind(session) -> None:
    """`--resume` with the card still in the row: say again why the game waits."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if session.peek is not None and req is not None and wants(session, req):
        card = session.game.card_of(session.peek["card"], session.bot)
        session.say(t("peek.resume", card=card.title), ChatKind.YOUR_TURN)


def to_dict(session) -> dict:
    """What the save keeps of this feature (nothing, for a game that never used it)."""
    pins = {k: list(v) for k, v in session.peek_pins.items() if v}
    return {**({"peek": session.peek} if session.peek is not None else {}), **({"peek_pins": pins} if pins else {})}


def load(saved: dict) -> tuple[dict | None, dict[str, list[int]]]:
    """(the row in view, the pinned order) of a save; anything that is not valid is dropped."""
    raw = saved.get("peek")
    row = None
    if isinstance(raw, dict) and _is_int(raw.get("card")) and isinstance(raw.get("at"), list) and len(raw["at"]) == 2             and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in raw["at"]):
        guid = raw.get("guid")
        taken = raw.get("taken") is True and isinstance(guid, str) and bool(lua._GUID.fullmatch(guid))
        row = {"card": raw["card"], "at": list(raw["at"]), "guid": guid if taken else None, "taken": taken}
        if taken and _triple(raw.get("home")) and _triple(raw.get("rot")):
            row.update(home=list(raw["home"]), rot=list(raw["rot"]))
    pins = saved.get("peek_pins") if isinstance(saved.get("peek_pins"), dict) else {}
    return row, {k: [i for i in pins.get(k, []) if _is_int(i)] if isinstance(pins.get(k), list) else [] for k in ("top", "bottom")}


def _triple(v) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                       and math.isfinite(x) for x in v)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def pin(session, req, value: list) -> None:
    """The human's answer fixes the order of the bot's deck: left on top, the card is the engine's top card; at the bottom,
    its last. The bot's deck is rebuilt from the table at every hand read (`engine_order` keeps what was decided), and the
    answer may reread it, so this runs before the answer reaches the engine; a refused answer is undone with the save."""
    if req is None or req.extra.get("future") != "peek" or req.extra.get("deck_of") != session.bot:
        return
    card, pins = req.extra["top"], session.peek_pins
    for where in pins.values():
        if card in where:
            where.remove(card)
    if value[0] == BOTTOM:
        pins["bottom"].append(card)
    else:
        pins["top"].insert(0, card)


def engine_order(session, unseen: list) -> list:
    """The bot's cards that are in no hand and no pile, in the engine's deck order: the cards left on top first, the
    cards put at the bottom last (oldest first), the rest as they came. A pinned card that left the deck is forgotten."""
    pins = session.peek_pins
    if not pins["top"] and not pins["bottom"]:
        return unseen
    by_id = {c.card_id: c for c in unseen}
    for where in pins.values():
        where[:] = [i for i in where if i in by_id]
    pinned = {i for where in pins.values() for i in where}
    return ([by_id[i] for i in pins["top"]] + [c for c in unseen if c.card_id not in pinned]
            + [by_id[i] for i in pins["bottom"]])


# ---------------------------------------------------------------- the bot looks at the human's deck

def read_top(session, player: int, n: int | None = None) -> "int | list[int] | None":
    """`Game.deck_reader`: the CardID on top of the human's real deck, or None (said) when the table does not give it. With `n`
    (Jill Trent's Insightful Deduction) the CardIDs of the top `n` cards, top first, or None when they cannot all be read."""
    from .session import SessionError
    cfg = session.cfg
    try:
        res = session.client.call_lua(lua.peek_deck_top(cfg.human_deck_guid, cfg.human_card_ids,
                                                         identity=session._identity("human"), **session._deck_kw("human"),
                                                         **({"count": n} if n and n > 1 else {})))
    except ERRORS + (SessionError, ValueError, TypeError):
        res = None
    if n and n > 1:
        ids = res.get("ids") if isinstance(res, dict) else None
        if isinstance(ids, list) and len(ids) == min(n, res.get("quantity") or 0) and all(_is_int(i) for i in ids):
            return ids
    elif isinstance(res, dict) and res.get("found") and _is_int(res.get("id")):
        return res["id"] if not n else [res["id"]]
    session.say(t("peek.read_failed"), ChatKind.WARNING)
    return None


def _look_mode(session, intent: dict) -> str | None:
    if intent["player"] == session.bot:
        return None                               # the human looked at the bot's deck: the row did it
    return BOT if intent["position"] == "top" or session.cfg.human_deck_guid else HUMAN


def _look_human(session, intent: dict, ctx) -> list:
    session.say(t("peek.bot_bottom_failed", cause=ctx.cause), ChatKind.YOUR_TURN)
    return []


@register("future_look", mode=_look_mode, human=_look_human)
def _look_bot(session, intent: dict, ctx) -> list:
    """The bot looked at the top card of the human's deck: it says so and, if the card goes to the bottom, moves it."""
    from .session import SessionError
    cfg = session.cfg
    if intent["position"] == "top":
        session.say(t("peek.bot_top", cause=ctx.cause), ChatKind.SCHEME)
        return []
    try:
        op = session._w(lua.deck_top_to_bottom(cfg.human_deck_guid, intent["card"], cfg.human_card_ids,
                                               identity=session._identity("human"), **session._deck_kw("human")), DOMAIN)
    except ERRORS + (SessionError, ValueError, TypeError):
        return _look_human(session, intent, ctx)
    session.say(t("peek.bot_bottom", cause=ctx.cause), ChatKind.SCHEME)
    return [lambda: None if result_of(op).get("moved") else _look_human(session, intent, ctx)]
