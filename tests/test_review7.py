"""Probes de la revision 7 (reviewer)."""
import dataclasses
import json

import pytest

from conftest import place
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_session import NICK, card, ids, rig  # noqa: F401
from test_review5_fixes import (setup_rig, idle_bot, HIND, GOODH, bot_attack_on, dial_rig, destiny_rig, fresh,
                                destiny_ids)


# A. un dial cambiado a mano NO bloquea el turno del bot para siempre
def test_a_hand_edited_dial_never_freezes_the_bot_turn(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    assert session._write_dials()
    table.dials["dL"]["value"] = 2
    place(game, medusa=0, hellboy=30, lobster=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    game.turn, game.actions_left, session.bot_stage = 0, 2, "start"
    session.messages = []
    session._bot_continue()
    print("first", session.messages)
    presses = 0
    while game.turn == 0 and presses < 10:
        presses += 1
        out = session.handle(Event.END_ACTION)
        print(presses, out)
    assert game.turn == 1, "BUG: el turno del bot no termina con un dial tocado a mano"
    print("presses", presses, "debt", session.dial_debt)
    assert presses <= 3


# B. falso positivo: escritura aplicada pero la verificacion no la vio
def test_b_unverified_but_applied_write_is_flagged_as_hand_edit(rig):
    session, table, game = rig
    dial_rig(session, table)
    assert session._write_dials() and session.dials_written["dL"] == 6
    real_read = table.do_read_health_dials
    stale = {"n": 0}

    def lagging(s):
        out = real_read(s)
        if stale["n"] > 0:
            stale["n"] -= 1
            out = {g: (dict(v, value=6) if g == "dL" else v) for g, v in out.items()}
        return out
    table.do_read_health_dials = lagging
    stale["n"] = 1 + session.cfg.settle_tries
    out = session.handle(Event.HP, {"fighter": "lobster", "delta": -1})
    print("1", out, table.dials["dL"])
    assert table.dials["dL"]["value"] == 5
    out = session.handle(Event.HP, {"fighter": "lobster", "delta": -1})
    print("2", out, table.dials["dL"])
    flagged = any("cambiado a mano" in m for m in out)
    assert not flagged, "LOW: una escritura aplicada pero no verificada se toma por cambio a mano"


# C. mulligan: corte del proceso tras CADA llamada a la mesa, y resume
def _crash_run(rig, monkeypatch, tmp_path, k, titles, first):
    session, table, game = rig
    setup_rig(session, table, game, first=first, titles=titles)
    idle_bot(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    real = session.client.call_lua
    calls = {"n": 0}

    def crashing(script, *a, **kw):
        res = real(script, *a, **kw)
        calls["n"] += 1
        if calls["n"] == k:
            raise KeyboardInterrupt
        return res
    monkeypatch.setattr(session.client, "call_lua", crashing)
    crashed = False
    try:
        session.start()
    except KeyboardInterrupt:
        crashed = True
    monkeypatch.setattr(session.client, "call_lua", real)
    return session, table, game, crashed


@pytest.mark.parametrize("titles", [HIND, GOODH], ids=["mull", "keep"])
@pytest.mark.parametrize("k", range(1, 40))
def test_c_mulligan_survives_a_crash_after_any_table_call(rig, monkeypatch, tmp_path, k, titles):
    session, table, game, crashed = _crash_run(rig, monkeypatch, tmp_path, k, titles, first=0)
    if not crashed:
        pytest.skip("no hay tantas llamadas")
    if not session.state_path.exists():
        pytest.skip("murio antes del primer guardado")
    saved = json.loads(session.state_path.read_text())
    s2 = fresh(session)
    s2.state_path = session.state_path
    monkeypatch.setattr(s2.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(s2.ai, "pick_ability_target", lambda g: None)
    s2.load_dict(saved)
    out = s2.resume()
    for _ in range(3):
        if s2.setup and s2.setup["stage"] in ("wait_human", "wait_human_first"):
            break
        out += s2.handle(Event.READY)
    print(k, saved["setup"], out)
    assert s2.setup is not None and s2.setup["stage"] == "wait_human", out
    eng = sorted(c.card_id for c in s2.game.players[0].hand)
    assert sorted(table.bot_hand) == eng and len(eng) == 5
    assert len(table.bot_deck) == 25
    assert sorted(table.bot_hand + table.bot_deck) == sorted(c.card_id for c in s2.game.players[0].full_set)
    assert sorted(c.card_id for c in s2.game.players[0].deck) == sorted(table.bot_deck)
    assert table.shuffles <= 2   # un return repetido con la mano vacia es inocuo


# D. empieza el humano, hace mulligan y pulsa Listo
def test_d_human_first_mulligan_then_ready(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=1)
    idle_bot(session, monkeypatch)
    session.start()
    assert session.setup["stage"] == "wait_human_first"
    session.handle(Event.MULLIGAN)
    table.positions["Hellboy"], table.positions["Lobster Johnson"] = 3, 1
    table.human_count = 5
    out = session.handle(Event.READY)
    print(out)
    assert session.setup is None and game.turn == 1


# E. agotamiento del humano en su Maniobra
def test_e_human_exhaustion_on_maneuver_announces_fall(rig):
    session, table, game = rig
    dial_rig(session, table)
    st = game.players[1]
    table.human_count = 0
    table.human_discard = [c.card_id for c in st.full_set]
    st.deck.clear()
    st.hand.clear()
    st.discard[:] = list(st.full_set)
    game.fighters["lobster"].hp = 2
    out = session.handle(Event.MANEUVER)
    print(out, game.fighters["lobster"].alive, table.dials)
    assert not game.fighters["lobster"].alive
    assert any("cae" in m and "Lobster" in m for m in out), "LOW: baja por agotamiento del humano sin anunciar"


# F. resume con mulligan_bot cambiado a false tras un mulligan atascado
def test_f_disabling_mulligan_after_a_stuck_physical_mulligan(rig, monkeypatch, tmp_path):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND)
    idle_bot(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    table.do_return_hand_to_deck = lambda s: {"returned": 0, "deck": False}
    session.start()
    saved = json.loads(session.state_path.read_text())
    cfg = dataclasses.replace(session.cfg, mulligan_bot=False)
    s2 = fresh(session, cfg)
    idle_bot(s2, monkeypatch)
    s2.load_dict(saved)
    out = s2.resume()
    print(out)
    assert s2.setup["stage"] == "wait_human", "LOW: con mulligan_bot=false y resume sigue intentando el mulligan"


# G. -1 por error a una pieza del bot: ahora se entierra; deshacer la devuelve a su casilla?
def test_g_undo_of_a_mistaken_medusa_death_restores_her_space(rig):
    session, table, game = rig
    destiny_rig(session, table)
    med = game.fighters["medusa"]
    pos0 = med.pos
    med.hp = 1
    out = session.handle(Event.HP, {"fighter": "medusa", "delta": -1})
    print("kill", out, table.placed)
    out = session.handle(Event.UNDO_GAME_OVER)
    print("undo", out, med.pos, med.alive, table.positions.get("Medusa"), table.piece_dist.get("Medusa"))
    assert med.alive and med.pos == pos0, f"Medusa vuelve a {med.pos}, estaba en {pos0}"


def test_g2_plus_one_on_a_mistaken_harpy_death(rig):
    session, table, game = rig
    destiny_rig(session, table)
    h = game.fighters["harpy1"]
    pos0 = h.pos
    out = session.handle(Event.HP, {"fighter": "harpy1", "delta": -1})
    print("kill", out)
    out = session.handle(Event.HP, {"fighter": "harpy1", "delta": 1})
    print("revive", out, h.alive, h.pos)
    assert h.alive and h.pos == pos0, "Harpia no vuelve sola a su casilla"
