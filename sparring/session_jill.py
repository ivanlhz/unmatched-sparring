"""The top cards of a deck looked at through Jill Trent's cards (Hypnoray Blaster, Battle of Wits, Insightful Deduction) and Golden Bat's
Sight Beyond Sight, at the table.

Two intents come from `effects/plugins_jill.py` and `effects/ops_info.py`:

  * `reveal_top` {player, viewer, cards}: the top cards of `player`'s deck were revealed to `viewer`. Revealed cards are public,
    so the chat names them (the human is entitled to see the bot's, and the bot only reads the human's through the table
    reader at the moment a card says so). Nothing moves.
  * `deck_order` {player, seen, top, bottom, owner}: `owner` looked at the cards `seen` (top first) of `player`'s deck, put the
    card `bottom` (None: none) at the bottom and the cards `top` on top, in that order (top first). The bot's deck order is the
    engine's, rebuilt from the table at every hand read, so the human's choice is pinned (`session_peek.engine_order`). The
    human's real deck is reordered by the bot itself, blind (Ivan, 2026-11-08): `lua.deck_reorder` takes the cards by what was
    read, puts them back face down in the bot's order and the chat says only how many cards were reordered, never which or
    in what order."""
from __future__ import annotations

from .i18n import t, tn
from .session_translators import BOT, DOMAIN, ERRORS, HUMAN, register, result_of
from .tts import lua
from .tts.lua import ChatKind


def _names(session, owner: int, ids) -> str:
    cards = session.game.cards_by_id(owner)
    return ", ".join(cards[i].title if i in cards else str(i) for i in ids)


def _reveal_mode(session, intent: dict) -> str | None:
    return BOT


@register("reveal_top", mode=_reveal_mode, human=lambda session, intent, ctx: [])
def _reveal(session, intent: dict, ctx) -> list:
    """Says which cards were revealed and whose deck they are on."""
    holder = intent["player"]
    key = "jill.reveal.bot_deck" if holder == session.bot else "jill.reveal.human_deck"
    session.say(t(key, cards=_names(session, holder, intent["cards"])), ChatKind.SCHEME)
    return []


def _order_mode(session, intent: dict) -> str | None:
    return BOT if intent["player"] == session.bot or session.cfg.human_deck_guid else HUMAN


def _cannot_reorder(session, intent: dict, ctx) -> list:
    """No physical human deck configured: nothing can be moved, and the cards are not named to anybody."""
    session.say(t("order.blind_failed", cause=ctx.cause), ChatKind.WARNING)
    return []


@register("deck_order", mode=_order_mode, human=_cannot_reorder)
def _deck_order(session, intent: dict, ctx) -> list:
    if intent["player"] != session.bot:
        return _reorder_human_deck(session, intent, ctx)
    return _pin_bot_deck(session, intent)


def _pin_bot_deck(session, intent: dict) -> list:
    """The human's Insightful Deduction on the bot's deck: the engine's order is kept (the cards left on top first, the one buried
    last); the table's own order of that deck is not the engine's and never was."""
    pins = session.peek_pins
    moved = set(intent["top"]) | {intent["bottom"]}
    for where in pins.values():
        where[:] = [i for i in where if i not in moved]
    pins["top"][:0] = list(intent["top"])
    pins["bottom"].append(intent["bottom"])
    session.say(t("jill.order.bot", bottom=_names(session, session.bot, [intent["bottom"]])), ChatKind.SCHEME)
    return []


def _reorder_human_deck(session, intent: dict, ctx) -> list:
    """The bot's Sight Beyond Sight or Insightful Deduction on the human's real deck: the bot puts the cards it read back in its
    order (the buried one at the bottom) without turning or showing any, and once the table confirms it says only how many it
    reordered. If the table refuses or its top is no longer what was read, nothing moved: the bot forgets the order it was going to
    know."""
    from .session import SessionError
    cfg, seen, bottom = session.cfg, intent["seen"], [] if intent["bottom"] is None else [intent["bottom"]]
    try:
        op = session._w(lua.deck_reorder(cfg.human_deck_guid, seen, intent["top"], bottom, cfg.human_card_ids,
                                         identity=session._identity("human"), **session._deck_kw("human")), DOMAIN)
    except ERRORS + (SessionError, ValueError, TypeError):
        session.game.players[session.bot].known.clear_top()
        return _cannot_reorder(session, intent, ctx)

    def check() -> None:
        res = result_of(op)
        if (res.get("reordered") is True and res.get("order") == intent["top"] and res.get("quantity") == res.get("was")
                and (not bottom or res.get("last") == bottom[-1])):
            session.say(tn("order.blind_bottom" if bottom else "order.blind", len(seen), cause=ctx.cause), ChatKind.SCHEME)
            return
        session.game.players[session.bot].known.clear_top()
        session.say(t("order.blind_failed", cause=ctx.cause), ChatKind.WARNING)
    return [check]
