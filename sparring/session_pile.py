"""Cards the human moves from their own discard pile into their own deck, by their own hand (Ivan, 31/10).

Searing Clarity, Rekindle and the human's half of Pact Of Time pick cards out of the human's public discard pile
and shuffle them into the human's deck. The panel does not list options for it: the chat says what to take, the
human moves the cards on the table and presses Done, and the bot DETECTS which cards left the pile (the deck is
hidden, so "left the discard pile" is the whole evidence), validates them against the request (only the eligible
cards, within its limits) and answers the request with them. A wrong table changes nothing: the chat says what is
wrong and the panel keeps waiting. The bot never moves these cards: `Session.hand_deck` tells the projection of the
step (`session_translators.return_to_deck`) that the table already shows them in the deck."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from . import session_rage as rage
from .i18n import t
from .session_choices import panel_text, request_card
from .tts.lua import ChatKind

WHERE = {"shuffle": "pile.where.shuffle", "bottom": "pile.where.bottom", "top": "pile.where.top"}     # position -> i18n key


def manual_request(session) -> ChoiceRequest | None:
    """The pending decision of the human when it picks cards out of their own discard pile to put them in the deck."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if req is not None and req.player == session.human and rage.is_rage(req):
        return req                                   # Unbridled rage: cards INTO the discard pile, the same Done button
    if (req is None or req.kind != "cards" or req.player != session.human or req.extra.get("zone") != "discard"
            or req.extra.get("of") != session.human or req.extra.get("purpose") != "return"):
        return None
    return req


def _titles(session, ids) -> str:
    from .session_choices import card_titles
    return card_titles(session.game, sorted(ids), session.human)


def _card_name(session, req: ChoiceRequest) -> str:
    card = request_card(session.game, req)
    return card.title if card is not None else ""


def _how_many(req: ChoiceRequest) -> str:
    if req.max == 1:
        return t("pile.how.up_to_one" if req.min == 0 else "pile.how.single")
    return t("pile.how.up_to_n" if req.min < req.max else "pile.how.n", n=req.max)


def instruction(session, req: ChoiceRequest) -> str:
    if rage.is_rage(req):
        return rage.instruction(session, req)
    st = session.game.players[session.human]
    no_scheme = any(c.card_id not in req.options and c.is_scheme for c in st.discard)
    kind = t("pile.kind.single" if req.max == 1 else "pile.kind.multi") if no_scheme else ""
    where = t(WHERE.get(req.extra.get("position"), WHERE["shuffle"]))
    return t("pile.instruction" if req.max == 1 else "pile.instruction_many", card=_card_name(session, req),
             how=_how_many(req), kind=kind, where=where)


def start(session, req: ChoiceRequest) -> None:
    session.say(instruction(session, req), ChatKind.YOUR_TURN)


def reprompt(session, req: ChoiceRequest) -> str:
    return t("common.still_pending", text=instruction(session, req))


def status(session, req: ChoiceRequest) -> str:
    if rage.is_rage(req):
        return rage.status(session, req)
    return panel_text(t("pile.status"))


def view(session, req: ChoiceRequest) -> tuple[dict, dict]:
    """The choice slots while the human acts on the table: a single Done button."""
    from .session_choices import CHOICE_IDS
    states = {ident: (False, False) for ident in CHOICE_IDS}
    states[CHOICE_IDS[0]] = (True, True)
    return states, {CHOICE_IDS[0]: panel_text(t("btn.done"), 40)}


def verdict(session, req: ChoiceRequest) -> tuple[list[int] | None, str | None]:
    """(CardIDs, None) when the table shows a valid move, else (None, what is wrong). Reads the pile only: the
    engine's discard pile is the baseline (nothing of this request has been applied yet)."""
    g = session.game
    st = g.players[session.human]
    own = {c.card_id for c in st.full_set}
    rows = session._rd_human_discard_raw()
    if rows is None and st.discard:                  # no reply is not an empty pile: nothing may be read as moved
        return None, t("pile.unreadable")
    on_table = {r["id"] for r in rows or [] if isinstance(r, dict)} & own
    left = sorted({c.card_id for c in st.discard} - on_table - {g.fx.ongoing_card_id(session.human)})
    wrong = [i for i in left if i not in req.options]
    if wrong:
        return None, t("pile.wrong", titles=_titles(session, wrong), card=_card_name(session, req) or t("pile.this_card"))
    if len(left) > req.max:
        return None, t("pile.too_many", n=len(left), titles=_titles(session, left), max=req.max)
    if len(left) < req.min:
        if not left:
            return None, t("pile.none")
        return None, t("pile.too_few", n=len(left), min=req.min)
    return left, None


def _settle_play(session, req: ChoiceRequest, ids: list[int]) -> None:
    """The Mists of Munnopor, the human's attack card: the card that was discarded still lies at their combat spot unless
    they moved it; the bot moves it to their discard pile by GUID (the engine already discarded it) and remembers the GUID of
    the card they played instead (a later effect, DARK PACT, may move it)."""
    from .session import SessionError             # the session imports this module: resolved at call time
    from .session_translators import DOMAIN, ERRORS, result_of
    from .tts import lua
    old = req.extra.get("old")
    sleight = bool(req.extra.get("sleight"))
    rows = {r["id"]: r.get("guid") for r in session._rd_combat_spot() if isinstance(r, dict) and r.get("guid")}
    if sleight and not ids:                       # they kept Sleight Of Hand: it is still the card of the combat
        return
    session.combat_guids.pop(old, None)
    if ids and rows.get(ids[0]):
        session.combat_guids[ids[0]] = rows[ids[0]]
    if old not in rows:
        return
    by_id = {c.card_id: c for c in session.game.players[session.human].full_set}
    cfg = session.cfg
    try:
        if sleight:                               # Sleight Of Hand goes back to their hand, not to the discard pile
            moved = result_of(session._w(lua.return_card_to_hand(rows[old], cfg.human_seat), DOMAIN)).get("returned")
            if moved and session.pending is not None and session.pending.combat is not None:
                session.pending.combat["hand_in_flight"] = True      # the hand count is not to be trusted yet (`_await_swap_boost`)
        else:
            op = session._w(lua.card_to_discard(rows[old], cfg.human_discard_zone, cfg.human_card_ids,
                                                identity=session._identity("human")), DOMAIN)
            moved = result_of(op).get("moved")
    except ERRORS + (SessionError,):              # a table or identity failure: the human does it
        moved = None
    if not moved:
        session.say(t("sleight.move_old" if sleight else "mists.move_old", title=by_id[old].title), ChatKind.WARNING)


def press(session, paused, index) -> None:
    """A click on the choice buttons while the human moves the cards by hand: 1 is Done."""
    req = manual_request(session)
    if isinstance(index, float) and index.is_integer():
        index = int(index)
    if index != 1:
        session.say(t("choice.no_such_button"), ChatKind.WARNING)
        return
    by_rage = rage.is_rage(req)
    ids, why = rage.verdict(session, req) if by_rage else verdict(session, req)
    if ids is None:
        session.say(why, ChatKind.WARNING)
        return
    if by_rage:                                   # the engine discards them from the virtual hand: nothing to undo here
        session.say(rage.counted(session, req, ids), ChatKind.YOUR_TURN)
        if rage.mode(req) == "play":
            _settle_play(session, req, ids)
        session._answer_choice(paused, ids)
        return
    session.hand_deck.update(ids)
    session._answer_choice(paused, ids)
    again = manual_request(session)
    if again is not None and again.key == req.key:      # refused (rolled back): still waiting, nothing moved
        session.hand_deck.difference_update(ids)
