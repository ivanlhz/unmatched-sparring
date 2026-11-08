"""The human puts the top cards of the BOT's deck back in an order they choose, by their own hand (Ivan, 2026-11-08).

Golden Bat's Sight Beyond Sight ("look at the top 3 cards of your opponent's deck, put them back in any order") and the human's
Insightful Deduction (Jill Trent: the cards that are left after one goes to the bottom) end in an `order` request over the bot's
deck. Buttons named after the bot's cards were useless live (the human does not know them, and two copies of a title cannot be told
apart), so the order is done on the table:

  1. The bot takes its engine's top N cards off its deck by CardID and deck image (`lua.deck_card_to_spot`: the table's own order is
     not the engine's) and lays them FACE UP in a row at `order_spot`, on the table and never in the human's hand (the bot reads that
     hand and would miscount it). The chat says what to do and where the stack ends; the panel shows only Done.
  2. The human looks at them, picks them up and puts them face down on the bot's deck. TTS stacks a card dropped on a deck ON TOP of
     it, so the first card they put ends under the others and the LAST one ends on top.
  3. On Done the bot reads the top N cards of its deck (`lua.peek_deck_top`, image identity plus CardID, never a bare CardID) and
     compares them with the N it laid. If they are exactly those, that order (top first) answers the request, so the engine, the
     pinned engine order of the bot's deck (`Session.peek_pins`) and what the AI knows match the table. If not, the chat says what is
     wrong and the request keeps waiting; the bot moves nothing.

The row in view is `Session.order_row` {key, ids}: it is saved with the game (the run that asks is a parked run too), so a resume says
again what to do and never lays the cards twice. When the cards cannot be laid, the request falls back to the panel buttons."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .i18n import t
from .session_choices import CHOICE_IDS, card_titles, options_text, panel_text, prompt_text, request_card, card_text_hint
from .session_translators import DOMAIN, ERRORS, result_of
from .tts import lua
from .tts.lua import ChatKind

MAX_CARDS = 6          # a row longer than this is not laid (Sight Beyond Sight looks at 3)


def is_bot_deck_order(session, req) -> bool:
    """The request asks the human for the order of cards on top of the bot's deck."""
    return (req is not None and req.kind == "order" and req.player == session.human and req.extra.get("of") == session.bot
            and req.extra.get("position") == "top")


def wants(session, req) -> bool:
    """The pause is laid out on the table instead of the panel buttons."""
    return session.cfg.order_by_hand and is_bot_deck_order(session, req) and 2 <= len(req.options) <= MAX_CARDS


def manual_request(session) -> ChoiceRequest | None:
    """The pending request of the human while its cards lie on the table (the row of the request in view)."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    row = session.order_row
    return req if req is not None and row is not None and row["key"] == req.key else None


def spots(cfg, n: int) -> list[tuple[float, float, float]]:
    (x, y, z), (dx, dz) = cfg.order_spot, cfg.order_step
    return [(x + (i - (n - 1) / 2) * dx, y, z + (i - (n - 1) / 2) * dz) for i in range(n)]


def instruction(session, req: ChoiceRequest) -> str:
    card = request_card(session.game, req)
    return t("order.instruction", card=card.title if card is not None else t("pile.this_card"), n=len(req.options))


def reprompt(session, req: ChoiceRequest) -> str:
    return t("common.still_pending", text=instruction(session, req))


def status(session, req: ChoiceRequest) -> str:
    return panel_text(t("order.status"))


def view(session, req: ChoiceRequest) -> tuple[dict, dict]:
    """The choice slots while the cards are on the table: a single Done button."""
    states = {ident: (False, False) for ident in CHOICE_IDS}
    states[CHOICE_IDS[0]] = (True, True)
    return states, {CHOICE_IDS[0]: panel_text(t("btn.done"), 40)}


# ---------------------------------------------------------------- laying the cards

def open_row(session, req: ChoiceRequest) -> bool:
    """Lays the cards of `req` face up in the row, pings it and says what to do. False when nothing could be queued (the caller then
    shows the panel buttons). A row already laid for this request is only announced again: the cards are never dealt twice."""
    from .session import SessionError             # the session imports this module: resolved at call time
    cfg, ids = session.cfg, list(req.options)
    row = session.order_row
    if row is not None and row["key"] == req.key:
        session.say(instruction(session, req), ChatKind.YOUR_TURN)
        return True
    at = spots(cfg, len(ids))
    bottom = req.extra.get("bottom")
    try:
        bury = None if bottom is None else _bury(session, bottom, (at[-1][0] + cfg.order_step[0], at[-1][1], at[-1][2] + cfg.order_step[1]))
        ops = [session._w(lua.deck_card_to_spot(i, cfg.bot_deck_guid, where, session._look_rot(), cfg.bot_card_ids,
                                                identity=session._identity(), **session._deck_kw()), DOMAIN)
               for i, where in zip(ids, at)]
        session._w(lua.ping_points([cfg.bot_seat, cfg.human_seat], [at[len(at) // 2]]), "misc")
    except ERRORS + (SessionError, ValueError, TypeError):
        return False
    session.order_row = {"key": req.key, "ids": ids}
    session._post.append(lambda: _laid(session, req, ops, bury))
    session.say(instruction(session, req), ChatKind.YOUR_TURN)
    return True


def _bury(session, card_id: int, parking: tuple) -> list:
    """The card the owner sent to the bottom (Insightful Deduction) goes to the bottom of the bot's real deck BEFORE the rest is laid:
    taken out by CardID and deck image, then put under the deck by CardID (a loose card of the bot's, `ours` only)."""
    cfg, kw = session.cfg, session._deck_kw()
    take = lua.deck_card_to_spot(card_id, cfg.bot_deck_guid, parking, session._look_rot(), cfg.bot_card_ids,
                                 identity=session._identity(), **kw)
    put = lua.card_to_deck_bottom(card_id, cfg.bot_deck_guid, cfg.bot_card_ids, identity=session._identity(), **kw)
    return [session._w(take, DOMAIN), session._w(put, DOMAIN)]


def _laid(session, req: ChoiceRequest, ops: list, bury: list | None = None) -> None:
    """After the write: a buried card that did not reach the bottom is said (the table and the engine would disagree in silence);
    if the table did not give every card, the request goes back to the panel buttons."""
    if bury is not None and not result_of(bury[1]).get("placed"):
        session.say(t("order.bottom_failed", card=card_titles(session.game, [req.extra["bottom"]], session.bot)), ChatKind.WARNING)
    row = session.order_row
    if row is None or row["key"] != req.key:
        return
    left_out = [i for i, op in zip(row["ids"], ops) if not result_of(op).get("taken")]
    if not left_out:
        return
    session.order_row = None
    key = "order.lay_failed" if len(left_out) == len(ops) else "order.lay_partial"
    session.say(t(key), ChatKind.WARNING)
    session.say(t("sess.choice_hint", prompt=prompt_text(session.game, req), options=options_text(session.game, req),
                  hint=card_text_hint(session.game, req)), ChatKind.YOUR_TURN)


# ---------------------------------------------------------------- Done

def read_top(session, n: int) -> list[int] | None:
    """The CardIDs of the top `n` cards of the bot's real deck, top first, as far as they are the bot's own (image identity and
    CardID); None when the deck cannot be found or the table does not answer."""
    from .session import SessionError
    cfg = session.cfg
    try:
        res = session.client.call_lua(lua.peek_deck_top(cfg.bot_deck_guid, cfg.bot_card_ids, identity=session._identity(),
                                                        **session._deck_kw(), count=n))
    except ERRORS + (SessionError, ValueError, TypeError):
        return None
    ids = res.get("ids") if isinstance(res, dict) and res.get("deck") is not False else None
    if isinstance(ids, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return ids
    return [] if isinstance(res, dict) and res.get("deck") is not False else None


def verdict(session, req: ChoiceRequest) -> tuple[list[int] | None, str | None]:
    """(the order, top first, None) when the top of the bot's deck is exactly the cards that were laid, else (None, what is wrong)."""
    laid = list(session.order_row["ids"])
    top = read_top(session, len(laid))
    if top is None:
        return None, t("order.unreadable")
    if len(top) == len(laid) and set(top) == set(laid):
        return top, None
    missing = [i for i in laid if i not in top]
    extra = [i for i in top if i not in laid]
    detail = (t("order.missing", titles=card_titles(session.game, missing, session.bot)) if missing else "") \
        + (t("order.extra", n=len(extra)) if extra else "")
    return None, t("order.mismatch", n=len(laid), detail=detail)


def press(session, paused, index) -> None:
    """A click on the choice buttons while the cards lie on the table: 1 is Done."""
    req = manual_request(session)
    if isinstance(index, float) and index.is_integer():
        index = int(index)
    if index != 1:
        session.say(t("choice.no_such_button"), ChatKind.WARNING)
        return
    ids, why = verdict(session, req)
    if ids is None:
        session.say(why, ChatKind.WARNING)
        return
    session._answer_choice(paused, ids)
    if manual_request(session) is None:           # answered (a refusal rolls the save back and the row stays)
        session.order_row = None
        session.say(t("order.counted"), ChatKind.YOUR_TURN)


def pin(session, req, value: list) -> None:
    """The order the human chose for the bot's deck is the engine's order: the bot's deck is rebuilt from the table at every hand read,
    so the cards are pinned on top (same pins as `session_peek.pin`). Runs before the answer reaches the engine."""
    if not is_bot_deck_order(session, req):
        return
    pins = session.peek_pins
    for where in pins.values():
        where[:] = [i for i in where if i not in value]
    pins["top"][:0] = list(value)


def remind(session) -> str | None:
    """`--resume` with the cards still on the table: the line to say again (the cards are not laid again)."""
    req = manual_request(session)
    return None if req is None else reprompt(session, req)


# ---------------------------------------------------------------- saving

def to_dict(session) -> dict:
    row = session.order_row
    return {} if row is None else {"order_row": {"key": row["key"], "ids": list(row["ids"])}}


def load(saved: dict) -> dict | None:
    """The row of a save; anything that is not valid is dropped (the request then shows the panel buttons)."""
    raw = saved.get("order_row")
    if (isinstance(raw, dict) and isinstance(raw.get("key"), str) and isinstance(raw.get("ids"), list)
            and all(isinstance(i, int) and not isinstance(i, bool) for i in raw["ids"])):
        return {"key": raw["key"], "ids": list(raw["ids"])}
    return None
