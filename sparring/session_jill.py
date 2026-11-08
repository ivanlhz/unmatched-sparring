"""The top cards of a deck looked at through Jill Trent's cards (Hypnoray Blaster, Battle of Wits, Insightful Deduction), at the table.

Two intents come from `effects/plugins_jill.py`:

  * `reveal_top` {player, viewer, cards}: the top cards of `player`'s deck were revealed to `viewer`. Revealed cards are public,
    so the chat names them (the human is entitled to see the bot's, and the bot only reads the human's through the table
    reader at the moment a card says so). Nothing moves.
  * `deck_order` {player, top, bottom, owner}: `owner` put the card `bottom` at the bottom of `player`'s deck and the cards `top`
    on top, in that order (top first). The bot's deck order is the engine's, rebuilt from the table at every hand read, so the
    human's choice is pinned (`session_peek.engine_order`); the human's real deck is theirs, so the bot tells them what to do
    and they do it by hand."""
from __future__ import annotations

from .i18n import t
from .session_translators import BOT, HUMAN, register
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
    return BOT if intent["player"] == session.bot else HUMAN


def _arrange_by_hand(session, intent: dict, ctx) -> list:
    """The bot's Insightful Deduction on the human's deck: the human puts the card at the bottom and the others on top."""
    holder = intent["player"]
    if intent["bottom"] is None:             # only the top cards were reordered (Golden Bat's Sight Beyond Sight)
        session.say(t("order.human_top", cause=ctx.cause, top=_names(session, holder, intent["top"])), ChatKind.YOUR_TURN)
        return []
    session.say(t("jill.order.human", cause=ctx.cause, bottom=_names(session, holder, [intent["bottom"]]),
                  top=_names(session, holder, intent["top"]) or t("jill.order.none")), ChatKind.YOUR_TURN)
    return []


@register("deck_order", mode=_order_mode, human=_arrange_by_hand)
def _pin_bot_deck(session, intent: dict, ctx) -> list:
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
