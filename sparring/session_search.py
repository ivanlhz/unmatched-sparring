"""The bot's deck search by what a card is (Ciri's Searching strike: "search your deck for a Source card, reveal it, and add it to your hand").

`search_deck` normally counts what the bot takes as cards dealt from the top of its real deck (the engine does not know the table's order,
`session_translators._search_bot`). Here the engine PICKED a card by what it is, so that very card must leave the real deck: the intent
carries `cards` (CardIDs, `exact`), the bot takes each one out by CardID and deck image straight into its hand (`lua_search.deck_card_to_hand`)
and says which card it found, because the card is revealed to the human."""
from __future__ import annotations

from .i18n import t
from .session_translators import DOMAIN, ERRORS, Ctx, result_of
from .tts import lua_search
from .tts.lua import ChatKind


def take(session, intent: dict, ctx: Ctx) -> list:
    """Queues the takes and says the revealed cards; the checks warn when the table did not give a card (the engine's hand then keeps it
    and the next read of the table corrects the difference)."""
    from .session import SessionError
    cfg, by_id = session.cfg, session.game.cards_by_id(session.bot)
    titles = ", ".join(by_id[i].title for i in intent["cards"] if i in by_id)
    session.say(t("search.revealed", cards=titles), ChatKind.SCHEME)
    ops = []
    for card_id in intent["cards"]:
        try:
            ops.append((card_id, session._w(lua_search.deck_card_to_hand(
                card_id, cfg.bot_deck_guid, cfg.bot_seat, cfg.bot_card_ids, identity=session._identity(),
                **session._deck_kw()), DOMAIN)))
        except ERRORS + (SessionError, ValueError, TypeError):
            session.say(t("search.not_taken", card=by_id[card_id].title), ChatKind.WARNING)

    def check() -> None:
        for card_id, op in ops:
            if not result_of(op).get("taken"):
                session.say(t("search.not_taken", card=by_id[card_id].title), ChatKind.WARNING)
    return [check]
