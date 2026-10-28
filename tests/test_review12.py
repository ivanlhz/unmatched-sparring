"""Revision 12: Cancelar tras una colocacion con respuesta tardia; Maniobra reparte la carta del humano."""
import os

import pytest

from sparring.tts.ui import Event
from conftest import place
from test_session import NICK, card, human_plays, ids, rig  # noqa: F401
from test_review5_fixes import flaky_after_execution

BATCH = bool(os.environ.get("SPARRING_BATCH"))


@pytest.mark.skipif(BATCH, reason="la respuesta tardia de una escritura suelta solo existe sin lote")
def test_late_place_then_cancel_resolves_placing_and_returns_the_card(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    flaky_after_execution(session, monkeypatch, "play_card_face_down")
    place(game, hellboy=1, medusa=0)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    table.human_hand = ids(game, 1, "Service Pistol")
    session.handle(Event.ATTACKER, {"attacker": "att_hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Service Pistol")
    session.handle(Event.REVEAL)
    assert session.placing is not None and table.bot_play == [dash.card_id]
    out = session.handle(Event.CANCEL)
    assert any("Ataque cancelado" in m for m in out)
    assert session.placing is None and session.pending is None
    assert table.bot_play == [] and dash.card_id in table.bot_hand
    session.handle(Event.MANEUVER)
    assert session.pending is None


# ---------- destinos que vuelven al mazo ----------
from test_batch import brig, click  # noqa: E402,F401


def _two_destinies(game):
    return [c.card_id for c in game.players[1].full_set if c.destiny][:2]


def test_a_destiny_moved_from_the_discard_to_the_deck_lowers_the_count_within_two_buttons(brig):  # noqa: F811
    session, table, game, fake = brig
    a, b = _two_destinies(game)
    table.human_discard, table.human_deck_qty = [a, b], 10
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2
    table.human_discard = [a]                                  # b vuelve al mazo (sin que la mesa lo cuente aun)
    assert not any("Destinos" in m and "antes" in m for m in click(session, table, Event.END_ACTION))
    assert game.destiny_count(1) == 2, "una sola lectura no lo baja"
    msgs = click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 1 and "Destinos de Hellboy: 1 (antes 2)." in msgs


def test_a_destiny_that_grows_the_deck_lowers_the_count_on_the_first_snapshot(brig):  # noqa: F811
    session, table, game, fake = brig
    a, b = _two_destinies(game)
    table.human_discard, table.human_deck_qty = [a, b], 10
    click(session, table, Event.END_ACTION)
    deck = len(game.players[1].deck)
    table.human_discard, table.human_deck_qty = [a], 11
    msgs = click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 1 and "Destinos de Hellboy: 1 (antes 2)." in msgs
    assert len(game.players[1].deck) == deck + 1, "la carta cuenta en el mazo del motor"


def test_a_single_snapshot_glitch_without_deck_growth_does_not_lower_the_count(brig):  # noqa: F811
    session, table, game, fake = brig
    a, b = _two_destinies(game)
    table.human_discard, table.human_deck_qty = [a, b], 10
    click(session, table, Event.END_ACTION)
    table.human_discard = [a]
    click(session, table, Event.END_ACTION)
    table.human_discard = [a, b]                               # la lectura siguiente la vuelve a ver
    click(session, table, Event.END_ACTION)
    table.human_discard = [a, b]
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2


# ---------- Maniobra reparte la carta del humano ----------
import dataclasses  # noqa: E402

from sparring.session import SessionError  # noqa: E402
from sparring.state import EXHAUST_DAMAGE  # noqa: E402
from sparring.tts import lua  # noqa: E402

DEALT_MSG = ("Maniobra: te he dado 1 carta. Mueve tus miniaturas (puedes potenciar descartando una carta) y pulsa "
             "Fin de accion")


def with_human_deck(session):
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid="HDECK", human_deck_spot=(-4.6, 13.67))


def test_a_normal_maneuver_deals_exactly_one_card_and_keeps_the_engine_view(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    session.sync_human()
    hand0, deck0 = table.human_count, len(game.players[1].deck)
    msgs = click(session, table, Event.MANEUVER)
    assert DEALT_MSG in msgs and not any("robas 1" in m for m in msgs)
    assert table.human_deals == [1] and table.human_count == hand0 + 1
    st = game.players[1]
    assert len(st.hand) == hand0 + 1 and len(st.deck) == deck0 - 1
    assert len(st.deck) + len(st.hand) + len(st.discard) == len(st.full_set)
    session.snap = None
    click(session, table, Event.END_ACTION)
    assert len(game.players[1].hand) == hand0 + 1, "la mano que lee la mesa y la del motor coinciden"
    assert "no ha llegado" not in " ".join(session.messages)


def test_an_empty_deck_exhausts_every_human_fighter_and_deals_nothing(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    game.players[1].deck.clear()
    hp0 = {f.fid: f.hp for f in game.own(1)}
    msgs = click(session, table, Event.MANEUVER)
    assert table.human_deals == []
    assert any("Mazo vacio" in m for m in msgs) and not any("te he dado" in m for m in msgs)
    for fid, hp in hp0.items():
        assert game.fighters[fid].hp == max(hp - EXHAUST_DAMAGE, 0) or not game.fighters[fid].alive
    assert table.dial_writes, "los diales se escriben igual que con cualquier dano"


def test_a_failed_deal_says_to_draw_by_hand_and_never_deals_twice(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    table.human_deal_fails = True
    hand0, deck0 = len(game.players[1].hand), len(game.players[1].deck)
    msgs = click(session, table, Event.MANEUVER)
    assert any("Roba tu carta a mano" in m for m in msgs)
    assert len(game.players[1].hand) == hand0 and len(game.players[1].deck) == deck0, "el motor no cuenta la carta"
    click(session, table, Event.MANEUVER)                  # reintento con la accion abierta: se ignora
    click(session, table, Event.END_ACTION)
    assert table.human_deals == [1]


def test_a_deal_that_reports_one_but_never_reaches_the_hand_is_flagged_on_the_next_snapshot(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    table.do_deal_cards = lambda s: {"dealt": 1}           # TTS dice que la dio y la mano no sube
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    assert any("Roba tu carta a mano" in m for m in msgs)
    assert len(game.players[1].hand) == table.human_count


def test_a_deal_that_arrives_after_the_human_discarded_one_is_not_flagged(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    click(session, table, Event.MANEUVER)
    table.human_count -= 1                                 # potencia: descarta una carta de la mano
    table.human_discard = [next(c.card_id for c in game.players[1].full_set if not c.destiny)]
    msgs = click(session, table, Event.END_ACTION)
    assert not any("Roba tu carta a mano" in m for m in msgs)


def test_an_unreadable_human_identity_deals_nothing_and_asks_for_the_card_by_hand(brig, monkeypatch):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)

    def identity(side="bot"):
        raise SessionError("sin identidad")
    monkeypatch.setattr(session, "_identity", identity)
    hand0 = len(game.players[1].hand)
    msgs = click(session, table, Event.MANEUVER)
    assert table.human_deals == [] and any("Roba tu carta a mano" in m for m in msgs)
    assert len(game.players[1].hand) == hand0


def test_the_deal_adds_no_message_to_the_maneuver_button(brig):  # noqa: F811
    session, table, game, fake = brig
    n = fake.lua_messages
    click(session, table, Event.MANEUVER)
    plain = fake.lua_messages - n
    session.moving = False
    game.actions_left = 2
    with_human_deck(session)
    n = fake.lua_messages
    click(session, table, Event.MANEUVER)
    assert table.human_deals == [1] and fake.lua_messages - n == plain == 1


def test_the_deal_script_reads_no_hand_and_uses_the_human_range_and_seat(brig):  # noqa: F811
    session, table, game, fake = brig
    with_human_deck(session)
    click(session, table, Event.MANEUVER)
    script = next(s for s in table.scripts if s.startswith("-- sparring:deal_cards"))
    assert '"Red"' in script and str(lua.HUMAN_CARD_IDS[0]) in script and "getHandObjects" not in script


lupa = pytest.importorskip("lupa")
from test_review9 import HUMAN_ID, rt, run  # noqa: E402,F401


def test_a_foreign_card_with_a_human_card_id_is_not_dealt(rt):  # noqa: F811
    lo = lua.HUMAN_CARD_IDS[0]
    rt.execute(f"""
local h = {{}}
for i = 0, 29 do table.insert(h, {{cid = {lo} + i, guid = 'h' .. i, owner = 'alice'}}) end
mkobj({{guid = 'HDECK', type = 'Deck', cards = h, pos = {{x = -4.6, y = 1, z = 13.67}}}})
""")
    rt.execute("getObjectFromGUID('HDECK').deal = function() DEALT = true end")
    res = run(rt, lua.deal_cards("HDECK", 1, "White", spot=(-4.6, 13.67), id_range=lua.HUMAN_CARD_IDS,
                                 identity=HUMAN_ID))
    assert res == {"dealt": 0} and rt.globals().DEALT is None


@pytest.mark.parametrize("build", [
    lambda: lua.deal_cards("HDECK", 1, "White", spot=(0, 0), id_range=lua.HUMAN_CARD_IDS),
    lambda: lua.deal_cards("HDECK", 1, "White", spot=(0, 0), id_range=lua.HUMAN_CARD_IDS, identity=()),
    lambda: lua.deal_cards("HDECK", 1, "Nobody", spot=(0, 0), id_range=lua.HUMAN_CARD_IDS, identity=HUMAN_ID),
    lambda: lua.deal_cards("HDECK", 1, "White", spot=(0, 0), id_range=(1,), identity=HUMAN_ID),
])
def test_deal_cards_for_the_human_rejects_bad_arguments(build):
    with pytest.raises((ValueError, TypeError)):
        build()
