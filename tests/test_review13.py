"""Revision 13: crecimiento del mazo no explicado, reparto de la ultima carta y aviso tras respuesta tardia."""
import pytest
from conftest import *  # noqa: F401,F403
from test_session import rig  # noqa: F401
from test_batch import brig, click  # noqa: F401
from test_review5_fixes import flaky_after_execution
from test_review12 import with_human_deck
from sparring.tts.ui import Event
from sparring.tts import lua


def _two_destinies(game):
    return [c.card_id for c in game.players[1].full_set if c.destiny][:2]


def test_deck_growth_explained_by_a_hand_card_does_not_lower_destiny(brig):  # noqa: F811
    session, table, game, fake = brig
    a, b = _two_destinies(game)
    table.human_discard, table.human_deck_qty = [a, b], 10
    click(session, table, Event.END_ACTION)
    table.human_count -= 1                          # Vistazo al infierno: una carta de la MANO va al mazo (+1)
    table.human_discard, table.human_deck_qty = [a], 11   # y b no se lee en esta lectura
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2
    table.human_discard = [a, b]
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2, "el contador no rebota"


def test_deck_growth_matching_the_missing_card_still_removes_it_at_once(brig):  # noqa: F811
    session, table, game, fake = brig
    a, b = _two_destinies(game)
    table.human_discard, table.human_deck_qty = [a, b], 10
    click(session, table, Event.END_ACTION)
    table.human_discard, table.human_deck_qty = [a], 11
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 1


def test_draw_and_discard_in_the_same_step_keeps_the_count(brig):  # noqa: F811
    session, table, game, fake = brig
    a, b = _two_destinies(game)
    other = next(c.card_id for c in game.players[1].full_set if not c.destiny)
    table.human_discard, table.human_deck_qty = [a, b], 10
    click(session, table, Event.END_ACTION)
    table.human_discard, table.human_deck_qty = [a, b, other], 9
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2


def test_a_double_maneuver_click_deals_once(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.MANEUVER)
    assert table.human_deals == [1]


def test_a_late_deal_reply_does_not_order_a_second_card_by_hand(rig, monkeypatch):  # noqa: F811
    session, table, game = rig
    if session.cfg.batch:
        pytest.skip("solo sin lote")
    with_human_deck(session)
    flaky_after_execution(session, monkeypatch, "deal_cards")
    out = session.handle(Event.MANEUVER)
    assert table.human_deals == [1]
    assert not any("Roba tu carta a mano" in m for m in out)
    assert any("mira tu mano" in m and "si no tienes la carta nueva" in m for m in out)


lupa = pytest.importorskip("lupa")
from test_review9 import HUMAN_ID, rt, run  # noqa: E402,F401


def _no_hand(rt):
    rt.execute("Player = setmetatable({}, {__index = function() return {getHandTransform = function() "
               "return {position = {x=0,y=0,z=0}, rotation = {y = 0}} end, getHandObjects = function() return {} end} end})")


def _deal(rt):
    return run(rt, lua.deal_cards("HDECK", 1, "White", spot=(-4.6, 13.67), id_range=lua.HUMAN_CARD_IDS,
                                  identity=HUMAN_ID))


def test_the_last_card_fallback_never_takes_a_faceup_discard_card(rt):  # noqa: F811
    lo = lua.HUMAN_CARD_IDS[0]
    rt.execute(f"""
mkobj({{guid = 'disc1', type = 'Card', cid = {lo} + 5, owner = 'hellboy', is_face_down = false, pos = {{x = -4.6 + 1.8, y = 1, z = 13.67}}}})
mkobj({{guid = 'last', type = 'Card', cid = {lo} + 7, owner = 'hellboy', is_face_down = true, pos = {{x = -4.6, y = 1, z = 13.67}}}})
""")
    _no_hand(rt)
    assert _deal(rt) == {"dealt": 1}
    assert not rt.eval("getObjectFromGUID('disc1').moved_count")
    assert rt.eval("getObjectFromGUID('last').moved_count") == 1


def test_the_last_card_fallback_ignores_a_lone_faceup_card(rt):  # noqa: F811
    lo = lua.HUMAN_CARD_IDS[0]
    rt.execute(f"mkobj({{guid = 'disc1', type = 'Card', cid = {lo} + 5, owner = 'hellboy', is_face_down = false, "
               "pos = {x = -4.6, y = 1, z = 13.67}})")
    _no_hand(rt)
    assert _deal(rt) == {"dealt": 0}
    assert not rt.eval("getObjectFromGUID('disc1').moved_count")


def test_the_last_card_fallback_picks_the_nearest_facedown_card(rt):  # noqa: F811
    lo = lua.HUMAN_CARD_IDS[0]
    rt.execute(f"""
mkobj({{guid = 'far', type = 'Card', cid = {lo} + 5, owner = 'hellboy', is_face_down = true, pos = {{x = -4.6 + 1.5, y = 1, z = 13.67}}}})
mkobj({{guid = 'near', type = 'Card', cid = {lo} + 7, owner = 'hellboy', is_face_down = true, pos = {{x = -4.6 + 0.2, y = 1, z = 13.67}}}})
""")
    _no_hand(rt)
    assert _deal(rt) == {"dealt": 1}
    assert not rt.eval("getObjectFromGUID('far').moved_count")
    assert rt.eval("getObjectFromGUID('near').moved_count") == 1
