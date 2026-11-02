"""Cards the human puts on the table for an effect that needs to SEE them, read back by the bot (Ivan, 31/10 and after).

The engine never holds the human's hand or deck, so an effect that depends on cards only they hold asks a `cards`
request with `table_discard` and a `pile_mode`; the chat tells the human what to do on the table, they press Done and the
bot DETECTS the result, checks it against the request and answers with the cards it found. A table that shows something
else changes nothing: the chat says what is wrong and the panel keeps waiting. The button handling is `session_pile`'s
(a single Done); this module owns the wording and the verdict of each mode:

  rage    Unbridled rage: defense or versatile cards given up, laid on the discard pile (+2 each); zero is fine.
  blind   BLIND BOOST (Doctor Strange): the top cards of their deck, laid on the discard pile, up to N; zero is fine.
  reveal  No, Really, I'm a Doctor: the card from their hand shown on the discard pile, exactly one; the bot then puts it on top
          of their deck (`session_translators.stack_top`).
  play    The Mists of Munnopor: the card their deck revealed and they play, face up at their combat spot instead of the
          one that was discarded; none is fine (no playable card in the deck). Sleight Of Hand (`sleight` in the request): the
          card they take back to their hand and play instead, same spot; none keeps Sleight Of Hand where it is."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .i18n import plural, t
from .session_choices import panel_text, request_card

MODES = ("rage", "blind", "reveal", "play")


def is_rage(req: ChoiceRequest) -> bool:
    return req is not None and req.kind == "cards" and bool(req.extra.get("table_discard"))


def mode(req: ChoiceRequest) -> str:
    return req.extra.get("pile_mode", "rage")


def _card_name(session, req: ChoiceRequest) -> str:
    card = request_card(session.game, req)
    return card.title if card is not None else t("pile.this_card")


def instruction(session, req: ChoiceRequest) -> str:
    m, card = mode(req), _card_name(session, req)
    if m == "blind":
        return t("blind.instruction", card=card, n=req.max)
    if m == "reveal":
        return t("reveal.instruction", card=card)
    if m == "play" and req.extra.get("sleight"):
        attacker = session.game.fighters.get(req.extra.get("attacker"))
        return t("sleight.instruction", card=card, attacker=attacker.name if attacker is not None else "")
    if m == "play":
        return t("mists.instruction", card=card, attacker=req.extra.get("attacker", ""))
    return t("rage.instruction", card=card, per=req.extra.get("per_card", 2))


def status(session, req: ChoiceRequest) -> str:
    if mode(req) == "play" and req.extra.get("sleight"):
        return panel_text(t("sleight.status"))
    return panel_text(t({"blind": "blind.status", "reveal": "reveal.status", "play": "mists.status"}.get(mode(req), "rage.status")))


def _aside(session, req: ChoiceRequest) -> set[int]:
    """Cards on the pile that are not an answer: what the engine already counts there, what the bot has in flight and the
    scheme being resolved (it lies face up on the pile until its effect ends)."""
    g, st = session.game, session.game.players[session.human]
    aside = {c.card_id for c in (*st.discard, *st.tucked, *st.removed)} | session.fx_in_flight
    aside.add(g.fx.ongoing_card_id(session.human))
    if req.card_owner in (None, session.human):
        aside.add(req.card_id)
    return aside


def verdict(session, req: ChoiceRequest) -> tuple[list[int] | None, str | None]:
    """(CardIDs, None) when the table shows a valid answer, else (None, what is wrong). The engine's discard pile is the
    baseline (nothing of this request has been applied yet)."""
    if mode(req) == "play":
        return _verdict_play(session, req)
    g = session.game
    st = g.players[session.human]
    by_id = {c.card_id: c for c in st.full_set}
    rows = session._rd_human_discard_raw()
    if rows is None and st.discard:                  # no reply is not an empty pile: nothing may be read as given up
        return None, t("pile.unreadable")
    arrived = sorted(({r["id"] for r in rows or [] if isinstance(r, dict)} & set(by_id)) - _aside(session, req))
    m = mode(req)
    if m == "rage":
        wrong = [by_id[i] for i in arrived if i not in req.options]
        if wrong:
            items = ", ".join(t("rage.wrong_item", title=c.title, kind=t(f"rage.type.{c.type}")) for c in wrong)
            return None, t("rage.wrong", items=items, card=_card_name(session, req))
    elif len(arrived) > req.max:
        return None, t("blind.too_many" if m == "blind" else "reveal.too_many", n=len(arrived), max=req.max,
                       titles=", ".join(by_id[i].title for i in arrived), card=_card_name(session, req))
    elif len(arrived) < req.min:
        return None, t("reveal.none", card=_card_name(session, req))
    return arrived, None


def _combat_spot(session) -> list[dict]:
    rows = session._rd_combat_spot()
    return [r for r in rows if isinstance(r, dict)]


def _verdict_play(session, req: ChoiceRequest) -> tuple[list[int] | None, str | None]:
    """The Mists of Munnopor played by the human's attacker: the new card sits at their combat spot, not the discarded one."""
    st = session.game.players[session.human]
    by_id = {c.card_id: c for c in st.full_set}
    old = req.extra.get("old")
    at_spot = {r["id"] for r in _combat_spot(session) if r.get("id") in by_id}
    new = sorted(at_spot - {old})
    if not new:
        if req.extra.get("sleight") and old not in at_spot:      # taken back with nothing in its place: neither card is in play
            return None, t("sleight.missing", card=by_id[old].title)
        return [], None                      # Mists: no playable card in the whole deck, the attack has no card. Sleight: they keep it
    if len(new) > 1:
        return None, t("mists.too_many", titles=", ".join(by_id[i].title for i in new))
    card, attacker = by_id[new[0]], session.game.fighters.get(req.extra.get("attacker"))
    if new[0] not in req.options:
        if req.extra.get("sleight") and card.title == by_id[old].title:
            return None, t("sleight.same", title=card.title, card=card.title)
        why = t("mists.not_playable", title=card.title, kind=t(f"rage.type.{card.type}"),
                fighter=attacker.name if attacker is not None else "")
        return None, why
    return new, None


def counted(session, req: ChoiceRequest, ids: list[int]) -> str:
    """The chat line once the cards are accepted."""
    card, m = _card_name(session, req), mode(req)
    by_id = {c.card_id: c for c in session.game.players[session.human].full_set}
    if m == "blind":
        if not ids:
            return t("blind.none", card=card)
        return t("blind.counted", card=card, titles=", ".join(by_id[i].title for i in ids),
                 bonus=f"+{sum(by_id[i].boost for i in ids)}")
    if m == "reveal":
        return t("reveal.counted", card=card, title=by_id[ids[0]].title, boost=by_id[ids[0]].boost)
    if m == "play" and req.extra.get("sleight"):
        return t("sleight.kept", card=card) if not ids else t("sleight.counted", card=card, title=by_id[ids[0]].title)
    if m == "play":
        return t("mists.none", card=card) if not ids else t("mists.counted", card=card, title=by_id[ids[0]].title)
    if not ids:
        return t("rage.none", card=card)
    return t("rage.counted", card=card, titles=", ".join(by_id[i].title for i in ids), n=plural(len(ids), "noun.card"),
             bonus=f"+{len(ids) * int(req.extra.get('per_card', 2))}")
