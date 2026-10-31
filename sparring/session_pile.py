"""Cards the human moves from their own discard pile into their own deck, by their own hand (Ivan, 31/10).

Searing Clarity, Rekindle and the human's half of Pact Of Time pick cards out of the human's public discard pile
and shuffle them into the human's deck. The panel does not list options for it: the chat says what to take, the
human moves the cards on the table and presses Hecho, and the bot DETECTS which cards left the pile (the deck is
hidden, so "left the discard pile" is the whole evidence), validates them against the request (only the eligible
cards, within its limits) and answers the request with them. A wrong table changes nothing: the chat says what is
wrong and the panel keeps waiting. The bot never moves these cards: `Session.hand_deck` tells the projection of the
step (`session_bot_effects._human_disc_to_deck`) that the table already shows them in the deck."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .tts.lua import ChatKind

HECHO = "Hecho"
WHERE = {"shuffle": "en tu mazo y barajalo", "bottom": "en el fondo de tu mazo", "top": "encima de tu mazo"}


def manual_request(session) -> ChoiceRequest | None:
    """The pending decision of the human when it picks cards out of their own discard pile to put them in the deck."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if (req is None or req.kind != "cards" or req.player != session.human or req.extra.get("zone") != "discard"
            or req.extra.get("of") != session.human or req.extra.get("purpose") != "return"):
        return None
    return req


def _titles(session, ids) -> str:
    from .session_choices import card_titles
    return card_titles(session.game, sorted(ids))


def _card_name(session, req: ChoiceRequest) -> str:
    card = next((c for p in session.game.players for c in p.full_set if c.card_id == req.card_id), None)
    return card.title if card is not None else ""


def _how_many(req: ChoiceRequest) -> str:
    if req.max == 1:
        return "hasta una carta" if req.min == 0 else "una carta"
    return f"{'hasta ' if req.min < req.max else ''}{req.max} cartas"


def instruction(session, req: ChoiceRequest) -> str:
    st = session.game.players[session.human]
    no_scheme = any(c.card_id not in req.options and c.is_scheme for c in st.discard)
    kind = (" que no sea un plan" if req.max == 1 else " (que no sean planes)") if no_scheme else ""
    where = WHERE.get(req.extra.get("position"), WHERE["shuffle"])
    plural = "s" if req.max != 1 else ""
    return (f"{_card_name(session, req)}: saca de tu descarte {_how_many(req)}{kind}, ponla{plural} {where} y pulsa "
            "Hecho. Yo detecto cual has movido.")


def start(session, req: ChoiceRequest) -> None:
    session.say(instruction(session, req), ChatKind.YOUR_TURN)


def reprompt(session, req: ChoiceRequest) -> str:
    return "Sigue pendiente: " + instruction(session, req)


def status(session, req: ChoiceRequest) -> str:
    return "Mueve la carta de tu descarte a tu mazo y pulsa Hecho"


def view(session, req: ChoiceRequest) -> tuple[dict, dict]:
    """The choice slots while the human acts on the table: a single Hecho button."""
    from .session_choices import CHOICE_IDS
    states = {ident: (False, False) for ident in CHOICE_IDS}
    states[CHOICE_IDS[0]] = (True, True)
    return states, {CHOICE_IDS[0]: HECHO}


def verdict(session, req: ChoiceRequest) -> tuple[list[int] | None, str | None]:
    """(CardIDs, None) when the table shows a valid move, else (None, what is wrong). Reads the pile only: the
    engine's discard pile is the baseline (nothing of this request has been applied yet)."""
    g = session.game
    st = g.players[session.human]
    own = {c.card_id for c in st.full_set}
    on_table = {r["id"] for r in session._rd_human_discard() if isinstance(r, dict)} & own
    left = sorted({c.card_id for c in st.discard} - on_table - {g.fx.ongoing_card_id(session.human)})
    wrong = [i for i in left if i not in req.options]
    if wrong:
        return None, (f"{_titles(session, wrong)} no se puede elegir con {_card_name(session, req) or 'esta carta'}: "
                      "devuelvela a tu descarte y pulsa Hecho.")
    if len(left) > req.max:
        return None, (f"Has sacado {len(left)} cartas del descarte ({_titles(session, left)}) y solo puedes "
                      f"{req.max}. Devuelve las que sobran y pulsa Hecho.")
    if len(left) < req.min:
        if not left:
            return None, "No veo que hayas sacado ninguna carta de tu descarte: sacala, ponla en tu mazo y pulsa Hecho."
        return None, f"Solo veo {len(left)} carta(s) fuera del descarte y tienes que mover {req.min}."
    return left, None


def press(session, paused, index) -> None:
    """A click on the choice buttons while the human moves the cards by hand: 1 is Hecho."""
    req = manual_request(session)
    if isinstance(index, float) and index.is_integer():
        index = int(index)
    if index != 1:
        session.say("Ese boton no corresponde a ninguna opcion.", ChatKind.WARNING)
        return
    ids, why = verdict(session, req)
    if ids is None:
        session.say(why, ChatKind.WARNING)
        return
    session.hand_deck.update(ids)
    session._answer_choice(paused, ids)
    again = manual_request(session)
    if again is not None and again.key == req.key:      # refused (rolled back): still waiting, nothing moved
        session.hand_deck.difference_update(ids)
