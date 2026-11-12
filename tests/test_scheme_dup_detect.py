"""F-SCHEME-DUP-DETECT (live 12/11, Liz Sherman): Wildfire discarded a Searing Clarity from the bottom of the deck; it is
burning, so it went back to the hand, and the human then played a Searing Clarity as their scheme. The engine had not
yet confirmed that the card left the pile (a removal needs two buttons), so the Scheme baseline still held its CardID
and the card laid back on the pile was "nothing new": no extra action, no shuffle."""
from __future__ import annotations

import json

from sparring.ai_medusa import MedusaAI
from sparring.session import Session
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, said
from test_e2_human_cards import LIZ_VS_HELLBOY, ONGOING_SPOTS, labels, rig, with_rig  # noqa: F401  (rig is the fixture)


def wildfire_discarded(session, table, game, *titles):
    """`titles` lie on the human's pile, on the table and in the engine (the Wildfire discard was read at End action)."""
    st = game.players[1]
    ids = card_ids(game, 1, *titles)
    for i in ids:
        card = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.deck, st.hand):
            if card in zone:
                zone.remove(card)
        st.discard.append(card)
    table.human_discard = list(ids)
    table.human_count = len(st.hand)
    session.snap = None
    return ids


@with_rig(*LIZ_VS_HELLBOY)
def test_the_burning_scheme_wildfire_returned_to_the_hand_is_recognised_when_played(rig):
    session, table, game, fake, cfg = rig
    incinerate, _, clarity = wildfire_discarded(session, table, game, "Incinerate", "Fireball", "Searing Clarity")
    table.human_discard.remove(clarity)                          # burning: it returns to the hand
    table.human_count += 1
    game.actions_left = 2
    click(session, table, Event.SCHEME)
    table.human_discard.append(clarity)                          # and it is the scheme they play
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert not said(msgs, "resuelve el plan a mano") and not said(msgs, "No he visto"), msgs
    assert said(msgs, "Searing Clarity: saca de tu descarte una carta, ponla en tu mazo y barajalo y pulsa Hecho"), msgs
    assert labels(session) == ["Hecho"]
    table.human_discard.remove(incinerate)                       # the shuffle proceeds
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "Anoto Incinerate en tu mazo") and said(msgs, "Aplico Searing Clarity"), msgs
    assert game.actions_left == 2 and session.effect_run is None    # 2 - 1 (the scheme) + 1 (gained)
    assert clarity in {c.card_id for c in game.players[1].discard}


@with_rig(*LIZ_VS_HELLBOY)
def test_a_second_copy_played_over_one_already_on_the_pile_is_recognised(rig):
    """A guard, not coverage of the fix: each copy has its own CardID, so this already worked."""
    session, table, game, fake, cfg = rig
    first, second = card_ids(game, 1, "Searing Clarity", "Searing Clarity")
    wildfire_discarded(session, table, game, "Incinerate", "Searing Clarity")
    game.actions_left = 2
    click(session, table, Event.SCHEME)
    table.human_discard.append(second)
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Aplico Searing Clarity") and game.actions_left == 2, msgs
    assert {first, second} <= {c.card_id for c in game.players[1].discard}


@with_rig(*LIZ_VS_HELLBOY)
def test_a_scheme_that_stays_on_the_pile_is_never_read_as_played(rig):
    session, table, game, fake, cfg = rig
    wildfire_discarded(session, table, game, "Incinerate", "Searing Clarity")
    game.actions_left = 2
    click(session, table, Event.SCHEME)
    msgs = click(session, table, Event.END_ACTION)                # nothing was laid down
    assert not said(msgs, "saca de tu descarte una carta") and session.effect_run is None, msgs
    assert game.actions_left == 1


@with_rig(*LIZ_VS_HELLBOY)
def test_a_stray_read_that_misses_a_scheme_at_the_scheme_button_plays_nothing(rig):
    """One read losing a card is not the card leaving the pile: the hand did not grow, nothing was laid."""
    session, table, game, fake, cfg = rig
    incinerate, clarity = wildfire_discarded(session, table, game, "Incinerate", "Searing Clarity")
    game.actions_left = 2
    table.human_discard.remove(clarity)                          # the read misses it; the hand count is the same
    click(session, table, Event.SCHEME)
    assert session.scheme_returned is None
    table.human_discard.append(clarity)
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "No he visto ninguna carta de plan nueva") and not said(msgs, "Searing Clarity"), msgs
    assert game.actions_left == 1 and session.effect_run is None
    assert incinerate in {c.card_id for c in game.players[1].discard}


@with_rig(*LIZ_VS_HELLBOY)
def test_a_returned_scheme_back_on_the_pile_with_the_hand_as_it_was_plays_nothing(rig):
    """It went to the hand, but the read at End action shows the hand no smaller: it was not laid from the hand."""
    session, table, game, fake, cfg = rig
    _, clarity = wildfire_discarded(session, table, game, "Incinerate", "Searing Clarity")
    table.human_discard.remove(clarity)
    table.human_count += 1
    game.actions_left = 2
    click(session, table, Event.SCHEME)
    assert session.scheme_returned == {"cards": [clarity], "hand": table.human_count}
    table.human_discard.append(clarity)                          # on the pile again, the hand count unchanged
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "No he visto ninguna carta de plan nueva") and session.effect_run is None, msgs


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_scheme_on_the_ongoing_spot_is_the_one_played_not_also_the_returned_card(rig):
    session, table, game, fake, cfg = rig
    _, clarity = wildfire_discarded(session, table, game, "Incinerate", "Searing Clarity")
    fof = card_ids(game, 1, "Fight Or Flight")[0]
    table.card_to_discard_fails = True
    table.human_discard.remove(clarity)
    table.human_count += 1
    game.actions_left = 2
    click(session, table, Event.SCHEME)
    assert session.scheme_returned is not None
    table.human_ongoing.append(fof)                              # the scheme played, on the ONGOING zone
    table.human_discard.append(clarity)                          # and the burning card dropped back on the pile
    table.human_count -= 2
    msgs = click(session, table, Event.END_ACTION)
    assert game.fx.ongoing_card_id(1) == fof and said(msgs, "Fight Or Flight queda en juego"), msgs
    assert not said(msgs, "Searing Clarity") and session.effect_run is None, msgs
    assert game.actions_left == 1


@with_rig(*LIZ_VS_HELLBOY)
def test_the_returned_card_survives_a_save_and_the_resumed_session_recognises_it(rig):
    session, table, game, fake, cfg = rig
    _, _, clarity = wildfire_discarded(session, table, game, "Incinerate", "Fireball", "Searing Clarity")
    table.human_discard.remove(clarity)
    table.human_count += 1
    game.actions_left = 2
    click(session, table, Event.SCHEME)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["scheme_returned"] == {"cards": [clarity], "hand": table.human_count}
    other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    assert other.scheme_returned == session.scheme_returned and other.scheme_baseline == session.scheme_baseline
    table.session = other
    other.resume()
    table.human_discard.append(clarity)
    table.human_count -= 1
    msgs = click(other, table, Event.END_ACTION)
    assert said(msgs, "Searing Clarity: saca de tu descarte una carta"), msgs
    assert "scheme_returned" not in other.to_dict()
