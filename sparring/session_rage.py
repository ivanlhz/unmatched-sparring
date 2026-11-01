"""Unbridled rage played by the human: "DURING COMBAT: discard any number of defense or versatile cards, +2 each".

The engine never holds the human's hand, so the cards given up are found on the table: the chat tells the human to put
them in their discard pile and press Done, and the bot DETECTS the cards that arrived there since the combat began
(the pile is public and the cards are read by CardID, `session._rd_human_discard_raw`), checks each one is a defense or
versatile card of the human and answers the card's request with them. A pile that holds something else changes nothing:
the chat names each wrong card, why, and asks to take it back to the hand; the panel keeps waiting. Zero cards is a legal
answer (Done with nothing new). The button handling is `session_pile`'s (a single Done); this module owns the wording and
the verdict. The engine then discards the same cards from its virtual hand and adds `per_card` to the value for each."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .i18n import plural, t
from .session_choices import panel_text, request_card


def is_rage(req: ChoiceRequest) -> bool:
    return req is not None and req.kind == "cards" and bool(req.extra.get("table_discard"))


def _card_name(session, req: ChoiceRequest) -> str:
    card = request_card(session.game, req)
    return card.title if card is not None else t("pile.this_card")


def instruction(session, req: ChoiceRequest) -> str:
    return t("rage.instruction", card=_card_name(session, req), per=req.extra.get("per_card", 2))


def status(session, req: ChoiceRequest) -> str:
    return panel_text(t("rage.status"))


def verdict(session, req: ChoiceRequest) -> tuple[list[int] | None, str | None]:
    """(CardIDs, None) when the pile shows only valid cards, else (None, what is wrong). Reads the pile only: the
    engine's discard pile is the baseline (nothing of this request has been applied yet)."""
    g = session.game
    st = g.players[session.human]
    by_id = {c.card_id: c for c in st.full_set}
    rows = session._rd_human_discard_raw()
    if rows is None and st.discard:                  # no reply is not an empty pile: nothing may be read as given up
        return None, t("pile.unreadable")
    aside = {c.card_id for c in (*st.discard, *st.tucked, *st.removed)} | session.fx_in_flight
    aside.add(g.fx.ongoing_card_id(session.human))
    arrived = sorted(({r["id"] for r in rows or [] if isinstance(r, dict)} & set(by_id)) - aside)
    wrong = [by_id[i] for i in arrived if i not in req.options]
    if wrong:
        items = ", ".join(t("rage.wrong_item", title=c.title, kind=t(f"rage.type.{c.type}")) for c in wrong)
        return None, t("rage.wrong", items=items, card=_card_name(session, req))
    return arrived, None


def counted(session, req: ChoiceRequest, ids: list[int]) -> str:
    """The chat line once the cards are accepted."""
    card = _card_name(session, req)
    if not ids:
        return t("rage.none", card=card)
    by_id = {c.card_id: c for c in session.game.players[session.human].full_set}
    return t("rage.counted", card=card, titles=", ".join(by_id[i].title for i in ids), n=plural(len(ids), "noun.card"),
             bonus=f"+{len(ids) * int(req.extra.get('per_card', 2))}")
