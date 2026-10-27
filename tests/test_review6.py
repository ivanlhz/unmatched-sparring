"""Probes de la revision 6 (reviewer). Se ejecutan con rootdir del proyecto y tests/ en sys.path."""
import dataclasses
import json

import pytest

from conftest import place
from sparring import persist
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
import test_session
from test_session import NICK, card, ids, rig  # noqa: F401
from test_review5_fixes import (setup_rig, idle_bot, HIND, bot_attack_on, dial_rig, destiny_rig, fresh,
                                attack_plan, lobster_glance, maneuver_once, destiny_ids)


# P1: mulligan cortado a medias -> la mano del bot queda vacia y la partida sigue
def test_p1_mulligan_interrupted_after_return_leaves_bot_without_hand(rig, monkeypatch, tmp_path):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND)
    idle_bot(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    real = table.do_shuffle_deck
    table.do_shuffle_deck = lambda s: {"shuffled": False, "quantity": 0}     # barajar falla una vez (o Ctrl+C)
    out = session.start()
    print("START", out)
    assert session.setup["stage"] == "mulligan" and session.setup["mull_done"] is False      # no se da por hecho
    assert table.bot_hand == [] and session.setup["mull_step"] == "returned"
    table.do_shuffle_deck = real
    out = session.handle(Event.READY)
    print("READY", out)
    print("table hand", table.bot_hand, "engine hand", [c.title for c in game.players[0].hand])
    assert len(table.bot_hand) == 5, f"BUG: tras reintentar, el bot tiene {len(table.bot_hand)} cartas en la mesa"
    assert sorted(table.bot_hand) == sorted(c.card_id for c in game.players[0].hand)
    assert table.returns == 1 and table.shuffles == 1              # lo ya hecho no se repite


# P2: Lobster muere por la habilidad de Medusa (turno del bot): se anuncia su caida?
def test_p2_lobster_killed_by_medusa_ability_is_announced(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    place(game, medusa=0, hellboy=30, lobster=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    game.fighters["lobster"].hp = 1
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    game.turn, game.actions_left, session.bot_stage = 0, 2, "start"
    session.messages = []
    session._bot_continue()
    out = session.messages
    print(out)
    assert not game.fighters["lobster"].alive
    assert any("cae" in m or "fuera" in m for m in out), "BUG: la muerte de Lobster por la habilidad no se anuncia"


# P2b: Lobster muere por A Momentary Glance
def test_p2b_lobster_killed_by_glance_is_announced(rig, monkeypatch):
    session, table, game = rig
    lobster_glance(session, table, game, monkeypatch)
    game.fighters["lobster"].hp = 2
    table.dials["dL"]["value"] = 2
    out = session.handle(Event.END_ACTION)
    print(out)
    assert not game.fighters["lobster"].alive
    assert any(("cae" in m or "fuera" in m) and "Lobster" in m for m in out), "BUG: muerte por Glance no anunciada"


# P3: una Harpia muerta por Retirar / -1 (efecto del humano): la aparta el bot?
def test_p3_harpy_removed_by_button_is_moved_off_by_bot(rig):
    session, table, game = rig
    destiny_rig(session, table)
    out = session.handle(Event.REMOVE, {"fighter": "harpy1"})
    print(out, table.placed)
    assert table.placed, "BUG: una Harpia muerta por efecto (Retirar) no la aparta el bot; se pide al humano"


# P4: flush con la carta del bot pendiente boca abajo y deuda de mesa (drawn)
def test_p4_flush_with_pending_bot_card_and_owed_draw(rig, monkeypatch):
    session, table, game = rig
    c = bot_attack_on(session, table, game, monkeypatch, "hellboy")
    hand_before = list(table.bot_hand)
    # deuda: el motor cuenta un robo que el mazo aun no repartio
    game.drawn[0] = 1
    st = game.players[0]
    st.hand.append(st.deck.pop(0))
    session.dirty = True
    session.messages = []
    try:
        session._flush_table()
        ok = True
    except Exception as e:
        ok = False
        print("flush raised", e)
    print("deal calls", table.deal_calls, "table hand", len(table.bot_hand), "before", len(hand_before))
    assert ok, "BUG: flush con carta pendiente falla"
    assert len(table.bot_hand) == len(hand_before) + 1, "BUG: reparte de mas o de menos"


# P4b: flush sin deuda de robo pero dirty con carta pendiente
def test_p4b_flush_with_pending_bot_card_dirty_only(rig, monkeypatch):
    session, table, game = rig
    bot_attack_on(session, table, game, monkeypatch, "hellboy")
    session.dirty = True
    session._flush_table()      # no debe lanzar
    assert session.dirty is False


# P5: el dial de destinos que falla una vez no se reintenta nunca
def test_p5_destiny_dial_failure_is_retried(rig):
    session, table, game = rig
    destiny_rig(session, table)
    table.dial_ignores_writes = True
    table.human_discard = destiny_ids(game, 2)
    out1 = session.handle(Event.END_ACTION)
    print(out1)
    table.dial_ignores_writes = False
    out2 = session.handle(Event.END_ACTION)
    print(out2, table.dials)
    assert table.dials["dD"]["value"] == 2, "BUG: el dial de destinos no se reintenta tras fallar"


# P6: un dial que falla al resolver el ataque del bot (turno del bot) no pausa: Fin de accion sigue sin re-verificar
def test_p6_dial_failure_on_bot_attack_reveal_pauses(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    bot_attack_on(session, table, game, monkeypatch, "hellboy")
    table.dial_ignores_writes = True
    out = session.handle(Event.REVEAL)
    print(out)
    assert session.dial_debt, "BUG: fallo de dial al revelar no deja deuda; Fin de accion seguira sin comprobar"


# P7: adoptar la mesa reordena el descarte por CardID (no cronologico) y el siguiente hueco puede pisar uno ocupado
def test_p7_adopt_keeps_chronological_order(rig, monkeypatch):
    session, table, game = rig
    st = game.players[0]
    a, b = card(game, 0, "Snipe"), card(game, 0, "Dash")
    # cronologico: Dash primero (id mayor?) luego Snipe
    first, second = (a, b) if a.card_id > b.card_id else (b, a)
    for c in (first, second):
        if c in st.hand:
            st.hand.remove(c)
        if c in st.deck:
            st.deck.remove(c)
        st.discard.append(c)
    table.bot_hand = [i for i in table.bot_hand if i not in (a.card_id, b.card_id)]
    table.bot_discard = [first.card_id, second.card_id]
    session.bot_discarded = {first.card_id, second.card_id}
    session.adopt_table()
    print([c.title for c in st.discard], first.title, second.title)
    assert st.discard[0] is first


# P8: Crown descarta la mano y entre ella hay un Pancakes!: se "detecta" Pancakes como jugado
def test_p8_crown_discarding_a_pancakes_is_not_two_schemes(rig):
    session, table, game = rig
    session.handle(Event.SCHEME)
    crown, pan = card(game, 1, "And Upon His Brow Is Set A Crown Of Flame"), card(game, 1, "Pancakes!")
    table.human_discard = [crown.card_id, pan.card_id]
    out = session.handle(Event.END_ACTION)
    print(out)
    assert not any("Pancakes" in m for m in out), "BUG: Pancakes descartado por Crown se anuncia como plan jugado"


# ---------- 9. return_card_to_hand es instantaneo ----------
def test_return_card_to_hand_moves_instantly():
    from sparring.tts import lua
    s = lua.return_card_to_hand("g17603", "Blue")
    assert "setPosition(t.position)" in s and "Smooth" not in s


# ---------- 1. mulligan reanudable ----------
def test_mulligan_interrupted_is_resumed_from_a_saved_state_in_a_new_process(rig, monkeypatch, tmp_path):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND)
    idle_bot(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    table.do_shuffle_deck = lambda s: {"shuffled": False, "quantity": 0}
    session.start()
    assert table.bot_hand == [] and table.returns == 1
    saved = json.loads(session.state_path.read_text())
    del table.do_shuffle_deck                                          # vuelve el barajado real
    s2 = fresh(session)
    s2.load_dict(saved)
    s2.resume()
    assert len(table.bot_hand) == 5 and table.returns == 1 and table.shuffles == 1
    assert s2.setup["stage"] == "wait_human"


def test_mulligan_cut_before_the_hand_returned_returns_it_on_retry(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND)
    idle_bot(session, monkeypatch)
    real = table.do_return_hand_to_deck
    table.do_return_hand_to_deck = lambda s: {"returned": 0, "deck": False}       # no encuentra el mazo
    session.start()
    assert session.setup["stage"] == "mulligan" and not session.setup["mull_done"] and len(table.bot_hand) == 5
    table.do_return_hand_to_deck = real
    session.handle(Event.READY)
    assert session.setup["stage"] == "wait_human" and len(table.bot_hand) == 5 and table.shuffles == 1


def test_setup_does_not_advance_while_the_table_hand_differs_from_the_engine(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    session.start()
    assert session.setup["stage"] == "wait_human"
    session.setup["stage"] = "place_bot"
    table.bot_hand.pop()                                              # el humano se llevo una carta del bot
    out = session.handle(Event.READY)
    assert session.setup["stage"] == "place_bot" and any("no coincide" in m for m in out)


# ---------- 10. mulligan configurable ----------
def test_mulligan_bot_false_keeps_the_hand_and_human_button_follows_its_key(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND, mulligan=False)
    idle_bot(session, monkeypatch)
    out = session.start()
    assert table.shuffles == 0 and any("se queda la mano" in m for m in out)
    session.cfg = dataclasses.replace(session.cfg, mulligan_human=False)
    assert any("desactivado" in m for m in session.handle(Event.MULLIGAN))
    assert not session.setup["human_mull"]


def test_human_mulligan_button_during_setup_once_and_listo_checks_five_cards(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    session.start()
    out = session.handle(Event.MULLIGAN)
    assert session.setup["human_mull"] and any("devuelve tu mano" in m and "baraja" in m for m in out)
    assert any("solo se puede una vez" in m for m in session.handle(Event.MULLIGAN))
    table.positions["Hellboy"], table.positions["Lobster Johnson"] = 30, 29
    table.human_count = 3
    assert any("debes tener 5" in m for m in session.handle(Event.READY))
    table.human_count = 5
    session.handle(Event.READY)
    assert session.setup is None
    assert any("solo se hace durante la preparacion" in m for m in session.handle(Event.MULLIGAN))


def test_mulligan_defaults_and_panel_button():
    from sparring.session import SessionConfig
    from sparring.tts import ui
    fields = {f.name: f.default for f in dataclasses.fields(SessionConfig)}
    assert fields["mulligan_bot"] is True and fields["mulligan_human"] is True
    assert ui.Event("mulligan") is Event.MULLIGAN
    assert 'onClick="onMulligan">Mulligan<' in ui.panel_xml(["medusa"]) and "function onMulligan" in ui.handler_script()
    assert ui.parse_event({"event": "mulligan"}) == (Event.MULLIGAN, {})


# ---------- 5. un dial tocado a mano no se pisa ----------
def test_a_dial_changed_by_hand_is_not_overwritten_and_asks_the_human(rig):
    session, table, game = rig
    dial_rig(session, table)
    assert session._write_dials() and table.dials["dL"]["value"] == 6 and session.dials_written["dL"] == 6
    table.dials["dL"]["value"] = 3                                     # el humano lo cambia a mano
    writes = len(table.dial_writes)
    game.damage(game.fighters["lobster"], 1, "manual")                 # el motor ahora dice 5
    session.messages = []
    assert session._write_dials() is False
    assert table.dials["dL"]["value"] == 3 and session.dial_debt
    assert not [w for w in table.dial_writes[writes:] if w[0] == "dL"], "solo ese dial se respeta"
    assert {w[0] for w in table.dial_writes[writes:]} == {"dM", "dH"}, "los demas se siguen escribiendo"
    assert any("cambiado a mano" in m and "Lobster Johnson" in m for m in session.messages)
    game.damage(game.fighters["lobster"], 2, "manual")                 # el humano reconcilia con -1: el motor llega a 3
    assert session._write_dials() is True and not session.dial_debt


def test_the_last_written_dials_survive_a_save_and_a_dial_nobody_wrote_yet_is_written(rig):
    session, table, game = rig
    dial_rig(session, table)
    table.dials["dL"]["value"] = 2                                     # sin baseline previo: se escribe
    assert session._write_dials() and table.dials["dL"]["value"] == 6
    d = session.to_dict()
    assert d["dials_written"]["dL"] == 6
    s2 = fresh(session)
    s2.load_dict(d)
    assert s2.dials_written == session.dials_written


# ---------- 4. todo fallo de dial deja deuda ----------
def test_any_dial_failure_sets_the_debt_and_a_verified_write_clears_it(rig):
    session, table, game = rig
    dial_rig(session, table)
    table.dial_ignores_writes = True
    session.handle(Event.HP, {"fighter": "lobster", "delta": -1})
    assert session.dial_debt
    table.dial_ignores_writes = False
    assert session._write_dials() and not session.dial_debt


# ---------- 3. bajas del bot por efecto: las aparta el bot ----------
def test_a_harpy_taken_to_zero_by_minus_one_is_moved_and_announced(rig):
    session, table, game = rig
    destiny_rig(session, table)
    game.fighters["harpy1"].hp = 1
    out = session.handle(Event.HP, {"fighter": "harpy1", "delta": -1})
    assert table.placed and table.placed[0][0] == "Harpy 1"
    assert any("Harpy 1 cae: la he apartado" in m for m in out)


def test_the_burial_is_read_back_and_a_piece_that_stays_on_the_board_is_reported(rig):
    session, table, game = rig
    destiny_rig(session, table)
    table.do_place_piece = lambda s: {"moved": "pcharpy2"}            # TTS dice que la movio y no es verdad
    out = session.handle(Event.REMOVE, {"fighter": "harpy2"})
    assert any("Harpy 2 cae: retira su miniatura" in m for m in out)


def test_a_human_piece_removed_is_announced_with_the_same_wording(rig):
    session, table, game = rig
    out = session.handle(Event.REMOVE, {"fighter": "lobster"})
    assert any("Lobster Johnson (tuyo) cae: retira su miniatura de la mesa." in m for m in out)


# ---------- 6. destiny_seen solo avanza con escritura verificada ----------
def test_destiny_seen_only_advances_after_a_verified_write(rig):
    session, table, game = rig
    destiny_rig(session, table)
    session.handle(Event.END_ACTION)
    before = session.destiny_seen
    table.dial_ignores_writes = True
    table.human_discard = destiny_ids(game, 2)
    session.handle(Event.END_ACTION)
    assert session.destiny_seen == before
    table.dial_ignores_writes = False
    session.handle(Event.END_ACTION)
    assert session.destiny_seen[0] == 2


# ---------- 8. Pancakes jugado como plan si cuenta ----------
def test_a_pancakes_played_as_the_scheme_is_still_detected(rig):
    session, table, game = rig
    session.handle(Event.SCHEME)
    table.human_discard = [card(game, 1, "Pancakes!").card_id]
    out = session.handle(Event.END_ACTION)
    assert any("Detecto Pancakes!" in m for m in out)
