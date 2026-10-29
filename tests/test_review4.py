"""Cuarta revision: emparejado de respuestas, adopcion de la mesa, PV por efectos, recarga de TTS, reanudacion,
piezas por GUID, zonas de descarte, cartas sueltas y los dos mutantes que sobrevivieron.

Las respuestas de TTS se modelan como las del TTS real: NO hay messageID 5; lo que devuelve un script llega como
messageID 4 con `sparring_reply` (ver FakeTTS)."""
from conftest import (TEST_IDENT, t_deal_cards, t_discard_cards, t_flip_card, t_play_card_face_down, t_reset_deck,
                      t_reset_plan, t_return_hand_to_deck, t_shuffle_deck)
import json
import re
import threading
import time

import pytest

from conftest import place
from fake_tts import FakeTTS
from sparring import persist, play
from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Session, SessionError
from sparring.state import Game
from sparring.tts import lua, ui
from sparring.tts.client import TTSClient, TTSLuaError
from sparring.tts.ui import Event, parse_event
from test_play import FILLED, TODO_ZONES, cfg_file, free_port, live  # noqa: F401
from test_review3 import claws_attack, maneuver_plan
from test_session import NICK, PIECES, Table, card, human_plays, ids, rig, set_bot_hand  # noqa: F401


def vanishing_discard(table):
    """Un descarte que TTS dice haber hecho pero cuya carta no aparece en la pila (desfase permanente)."""
    def fn(s):
        gone = [int(x) for x in re.findall(r"\[(\d+)\]=\{", s)]
        for i in gone:
            if i in table.bot_hand:
                table.bot_hand.remove(i)
        return {"moved": gone}
    table.do_discard_cards = fn


# ---------- D2: respuestas emparejadas con su peticion ----------
def make_client(reply, timeout=0.3):
    fake = FakeTTS(return_value=reply)
    client = TTSClient(send_port=fake.port, listen_port=0, timeout=timeout)
    fake.reply_port = client.start_listening().port
    return fake, client


def test_d2_late_reply_after_a_timeout_does_not_shift_later_answers():
    calls = {"n": 0}

    def reply(msg):
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.6)                      # TTS ocupado: contesta cuando el cliente ya se rindio
        return json.dumps({"tag": msg["script"].split("\n")[0]})
    fake, client = make_client(reply)
    try:
        with pytest.raises(TimeoutError):
            client.call_lua(lua.read_hand("Blue"))
        time.sleep(0.5)
        got = [client.call_lua(lua.count_hand("Red"))["tag"], client.call_lua(lua.read_discard("ABC"))["tag"],
               client.call_lua(lua.broadcast("x"))["tag"]]
        assert got == ["-- sparring:count_hand", "-- sparring:read_discard", "-- sparring:broadcast"]
        assert client.stale_replies >= 1
    finally:
        client.close()
        fake.close()


def test_d2_error_from_another_script_is_not_blamed_on_the_current_call():
    fake, client = make_client(lambda msg: json.dumps({"tag": msg["script"].split("\n")[0]}), timeout=1.0)
    try:
        fake.push({"messageID": 3, "error": "Global: onObjectEnterZone attempt to index nil", "guid": "-1"})
        time.sleep(0.2)
        assert client.call_lua(lua.read_hand("Blue")) == {"tag": "-- sparring:read_hand"}
        assert client.call_lua(lua.count_hand("Red")) == {"tag": "-- sparring:count_hand"}
        assert any("onObjectEnterZone" in e for e in client.foreign_errors)
    finally:
        client.close()
        fake.close()


def test_d2_foreign_error_arriving_during_the_wait_is_logged_and_ignored():
    def reply(msg):
        fake.push({"messageID": 3, "error": "otro script", "guid": "-1"})
        return json.dumps({"ok": 1})
    fake, client = make_client(reply, timeout=1.0)
    try:
        assert client.call_lua(lua.read_hand("Blue")) == {"ok": 1}
        assert list(client.foreign_errors) == ["otro script"]
    finally:
        client.close()
        fake.close()


def test_d2_only_a_reply_with_the_matching_id_counts_and_messageid_5_is_never_waited_for():
    fake, client = make_client(lambda msg: json.dumps({"ok": 1}), timeout=0.4)
    try:
        client.listener.messages.put({"messageID": 5, "returnValue": json.dumps({"ok": "return"})})
        client.listener.messages.put({"messageID": 4, "customMessage": {"sparring_reply": 1.0, "value": "{}"}})
        assert client.call_lua(lua.read_hand("Blue")) == {"ok": 1}
        fake.return_value = lambda msg: time.sleep(1) or "{}"
        assert client.listener.messages.empty()
    finally:
        client.close()
        fake.close()


def test_d2_a_stale_reply_that_arrives_during_the_wait_is_dropped_by_id():
    def reply(msg):
        fake.push({"messageID": 4, "customMessage": {"sparring_reply": 7.0, "value": json.dumps({"stale": 1})}})
        return json.dumps({"mine": 1})
    fake, client = make_client(reply, timeout=1.0)
    try:
        assert client.call_lua(lua.read_hand("Blue")) == {"mine": 1}
        assert client.stale_replies == 1
    finally:
        client.close()
        fake.close()


def test_d2_request_wrapper_carries_an_integer_id_and_errors_come_back_attributed():
    s = lua.request(lua.read_hand("Blue"), 12345)
    assert "local __rid = 12345" in s and "sendExternalMessage" in s and "pcall(function()" in s
    assert "return JSON.encode" in s and lua.is_sendable(s)
    assert not lua.is_sendable(s.replace("12345", "1; UI.setXml('x')"))
    for bad in ("1; os.exit()", 1.5, True, -1, None, 10 ** 15):
        with pytest.raises(ValueError):
            lua.request(lua.read_hand("Blue"), bad)
    with pytest.raises(ValueError):
        lua.request("return 1", 1)
    with pytest.raises(ValueError):
        lua.request(s, 2)                                   # no se envuelve dos veces


def test_d2_error_of_our_own_script_is_attributed_through_its_id():
    fake, client = make_client(lambda msg: {"__error__": "attempt to index a nil value"}, timeout=1.0)
    try:
        with pytest.raises(TTSLuaError, match="nil value"):
            client.call_lua(lua.read_hand("Blue"))
    finally:
        client.close()
        fake.close()


# ---------- D5: recarga de TTS (messageID 1) ----------
def test_d5_reload_message_is_recorded_once():
    fake, client = make_client(lambda msg: "{}")
    try:
        fake.push({"messageID": 1, "scriptStates": []})
        fake.push({"messageID": 4, "customMessage": {"event": "maneuver"}})
        time.sleep(0.3)
        assert client.poll_events() == [{"event": "maneuver"}]
        assert client.take_reload() is True and client.take_reload() is False
    finally:
        client.close()
        fake.close()


def run_loop_for(session, recover, seconds=0.8):
    said, stop = [], threading.Event()
    threading.Timer(seconds, stop.set).start()
    t = threading.Thread(target=play.run_loop, args=(session, session.client, stop, said.extend),
                         kwargs={"poll": 0.01, "recover": recover})
    t.start()
    return said, stop, t


def test_d5_reload_rechecks_guids_recreates_the_panel_and_tells_the_human(rig):
    session, table, game = rig
    fake = session.client.listener
    targets = [f.fid for f in game.own(0)]
    said, stop, t = run_loop_for(session, lambda: play.recover_after_reload(session, session.client, targets, (0, 1, -14)))
    session.client.listener.messages.put({"messageID": 1, "scriptStates": []})
    t.join(5)
    assert table.count("inspect_guids") == 1 and table.count("create_panel") == 1
    assert any("recargo" in m and "panel recreado" in m for m in said)
    assert session.dirty is True and fake is not None


def test_d5_reload_with_missing_guids_stops_safely_without_writing(rig, monkeypatch):
    session, table, game = rig
    table.missing_guids = {"DECK1"}
    handled = []
    monkeypatch.setattr(session, "handle", lambda *a, **k: handled.append(a) or [])
    targets = [f.fid for f in game.own(0)]
    said, stop, t = run_loop_for(session, lambda: play.recover_after_reload(session, session.client, targets, (0, 1, -14)),
                                 seconds=3)
    session.client.listener.messages.put({"messageID": 1})
    session.client.listener.messages.put({"messageID": 4, "customMessage": {"event": "maneuver"}})
    t.join(5)
    assert not t.is_alive() and stop.is_set()
    assert any("DECK1" in m and "--resume" in m for m in said)
    assert table.count("create_panel") == 0 and handled == []


def test_d5_reload_while_tts_is_still_loading_retries_and_keeps_the_buttons(rig):
    session, table, game = rig
    state = {"n": 0}

    def recover():
        state["n"] += 1
        return ("retry", ["cargando"]) if state["n"] < 3 else ("ok", ["listo"])
    said, stop, t = run_loop_for(session, recover, seconds=3)
    session.client.listener.messages.put({"messageID": 1})
    session.client.listener.messages.put({"messageID": 4, "customMessage": {"event": "scheme"}})
    deadline = time.time() + 3
    while time.time() < deadline and not any("Plan" in m for m in said):
        time.sleep(0.05)
    stop.set()
    t.join(5)
    assert state["n"] == 3 and any("Plan" in m for m in said) and game.actions_left == 1


# ---------- D3: la mesa manda ----------
def test_d3_human_moves_a_bot_hand_card_to_the_bot_discard_and_the_game_goes_on(rig, monkeypatch):
    session, table, game = rig
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    snipe = card(game, 0, "Snipe")
    table.bot_hand.remove(snipe.card_id)
    table.bot_discard.append(snipe.card_id)                  # Confront Any Demon or God
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert game.turn == 1 and not session.dirty, msgs
    assert snipe in game.players[0].discard and snipe not in game.players[0].hand + game.players[0].deck
    assert any("Snipe" in m and "descarte del bot" in m for m in msgs)


def boost_then_maneuver(session, monkeypatch, game):
    maneuver_plan(session, monkeypatch, boost=card(game, 0, "Dash"))


def test_d3_after_n_failed_flushes_the_table_state_is_adopted(rig, monkeypatch):
    session, table, game = rig
    boost_then_maneuver(session, monkeypatch, game)
    vanishing_discard(table)
    game.actions_left = 0
    for _ in range(session.cfg.adopt_after - 1):
        msgs = session.handle(Event.END_ACTION)
        assert any("no coincide" in m for m in msgs) and game.turn == 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Adopto" in m for m in msgs) and game.turn == 1 and not session.dirty
    dash = card(game, 0, "Dash")
    assert dash not in game.players[0].discard, "la mesa no la tiene en el descarte"


def test_d3_cancel_exits_a_dirty_table(rig, monkeypatch):
    session, table, game = rig
    boost_then_maneuver(session, monkeypatch, game)
    vanishing_discard(table)
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.dirty and game.turn == 0
    msgs = session.handle(Event.CANCEL)
    assert not session.dirty and session.unprojected is None and any("Adopto" in m for m in msgs)
    session.handle(Event.END_ACTION)
    assert game.turn == 1


# ---------- D4: PV y bajas por efectos ----------
def hp(session, fid, delta):
    return session.handle(Event.HP, {"fighter": fid, "delta": delta})


def test_d4_hp_buttons_hurt_and_heal_any_fighter_of_either_side(rig):
    session, table, game = rig
    hb, med = game.fighters["hellboy"], game.fighters["medusa"]
    hp(session, "hellboy", -1)
    hp(session, "medusa", -1)
    assert (hb.hp, med.hp) == (17, 15)
    hp(session, "hellboy", 1)
    hp(session, "hellboy", 1)
    assert hb.hp == hb.max_hp, "curar no pasa del maximo"
    game.effect_shield[0] = game.turn_no
    hp(session, "medusa", -1)
    assert med.hp == 14, "el ajuste manual ya viene resuelto: no lo frena el escudo de efectos"


def test_d4_remove_kills_a_harpy_and_a_dead_hero_ends_the_game_with_a_way_back(rig):
    session, table, game = rig
    msgs = session.handle(Event.REMOVE, {"fighter": "harpy1"})
    h1 = game.fighters["harpy1"]
    assert not h1.alive and h1.pos is None and any("retira su miniatura" in m for m in msgs)
    assert any("ya esta fuera" in m for m in session.handle(Event.REMOVE, {"fighter": "harpy1"}))
    game.fighters["hellboy"].hp = 1
    msgs = hp(session, "hellboy", -1)
    assert game.winner == 0 and any("Fin de partida" in m and "Deshacer" in m for m in msgs)
    assert any("ha terminado" in m for m in session.handle(Event.MANEUVER))
    msgs = session.handle(Event.UNDO_GAME_OVER)
    hb = game.fighters["hellboy"]
    assert game.winner is None and hb.alive and hb.hp == 1 and hb.pos == table.positions["Hellboy"]
    assert any("reabierta" in m for m in msgs)
    assert any("No hay fin de partida" in m for m in session.handle(Event.UNDO_GAME_OVER))


def test_d4_a_false_win_is_corrected_by_giving_the_hp_back(rig):
    session, table, game = rig
    game.fighters["lobster"].hp = 1
    hp(session, "lobster", -1)
    assert not game.fighters["lobster"].alive
    hp(session, "lobster", 1)
    assert game.fighters["lobster"].alive and game.fighters["lobster"].hp == 1


def test_d4_reviving_a_piece_that_is_off_the_board_is_refused(rig):
    session, table, game = rig
    session.handle(Event.REMOVE, {"fighter": "harpy2"})
    table.piece_dist["Harpy 2"] = 99.0
    msgs = hp(session, "harpy2", 1)
    assert not game.fighters["harpy2"].alive and any("no esta en el tablero" in m for m in msgs)


@pytest.mark.parametrize("payload", [{"fighter": "nadie", "delta": 1}, {"fighter": "medusa", "delta": 5},
                                     {"fighter": "medusa", "delta": True}, {"fighter": "medusa"}, {}])
def test_d4_bad_hp_input_is_a_message_not_a_crash(rig, payload):
    session, table, game = rig
    before = {f.fid: f.hp for f in game.fighters.values()}
    msgs = session.handle(Event.HP, payload)
    assert msgs and {f.fid: f.hp for f in game.fighters.values()} == before


def test_d4_panel_has_hp_remove_and_undo_buttons_for_every_fighter_and_one_label_for_the_end_button():
    xml = ui.panel_xml(["medusa", "harpy1", "harpy2", "harpy3"])
    for fid in ("medusa", "harpy1", "harpy2", "harpy3", "hellboy", "lobster"):
        assert f'id="hpm_{fid}"' in xml and f'id="hpp_{fid}"' in xml and f'id="rm_{fid}"' in xml
    assert "Deshacer fin de partida" in xml and ">Fin de accion<" in xml and "Terminar" not in xml
    script = ui.handler_script()
    for fn in ("onHp", "onRemove", "onUndoGameOver"):
        assert f"function {fn}(" in script
    assert parse_event({"event": "hp", "fighter": "medusa", "delta": -1}) == (Event.HP, {"fighter": "medusa", "delta": -1})
    assert parse_event({"event": "remove", "fighter": "harpy1"})[0] is Event.REMOVE
    assert parse_event({"event": "undo_game_over"})[0] is Event.UNDO_GAME_OVER


def test_d12_messages_name_the_button_exactly_as_the_panel_labels_it(rig):
    session, table, game = rig
    assert ui.END_ACTION_LABEL == "Fin de accion"
    assert any(ui.END_ACTION_LABEL in m for m in session.handle(Event.SCHEME))


def test_d4_dial_mismatch_is_reported_but_never_changes_the_engine(rig):
    session, table, game = rig
    session.cfg.dials = {"medusa": "bcd809", "hellboy": "046660"}
    table.dials = {"bcd809": {"found": True, "value": 14, "max": 16}, "046660": {"found": True, "value": 18, "max": 18}}
    msgs = session.handle(Event.END_ACTION)
    assert any("dial de Medusa marca 14" in m for m in msgs) and not any("Hellboy" in m and "dial" in m for m in msgs)
    assert game.fighters["medusa"].hp == 16


def test_d4_health_dial_reader_is_a_pure_read():
    s = lua.read_health_dials(["bcd809"])
    assert 'getTable("CONFIG")' in s and "VALUE" in s and "found = false" in s and lua.is_sendable(s)
    assert not any(w in s for w in ("setPosition", "setRotation", "deal(", "destruct", "UI.", "setValue", "setVar",
                                    "editButton"))


# ---------- D6: guardado, reanudacion y arranque ----------
def fresh_session(session):
    g = Game.new(session.game.board, seed=99, controllers={})
    return Session(g, session.client, MedusaAI(0), session.cfg)


def test_d6_state_is_saved_atomically_after_every_handle_and_round_trips(rig, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "sesion.json"
    session.handle(Event.MANEUVER)
    hp(session, "hellboy", -1)
    from sparring.session import Pending
    session.pending = Pending("human_attacks", game.fighters["hellboy"], game.fighters["medusa"], None)
    session.handle(Event.VALUE, {"value": 3})
    assert session.state_path.exists() and not list(tmp_path.glob("*.tmp"))
    saved = json.loads(session.state_path.read_text(encoding="utf-8"))
    other = fresh_session(session)
    other.load_dict(persist.load(session.state_path))
    assert json.loads(json.dumps(other.to_dict())) == {k: v for k, v in saved.items() if k != "version"}
    assert other.game.fighters["hellboy"].hp == 17 and other.pending_value == 3 and other.game.actions_left == 1
    assert [c.card_id for c in other.game.players[1].hand] == [c.card_id for c in game.players[1].hand]


def test_d6_a_pending_combat_survives_a_restart(rig, tmp_path):
    session, table, game = rig
    place(game, hellboy=40 if 40 in game.board.spaces else 31, lobster=1, medusa=0)
    table.positions.update({"Hellboy": game.fighters["hellboy"].pos, "Lobster Johnson": 1})
    table.human_hand = ids(game, 1, "Pancakes!")
    human_plays(table, game, "Second Shot")
    session.state_path = tmp_path / "s.json"
    session.handle(Event.ATTACKER, {"attacker": "lobster"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None
    other = fresh_session(session)
    other.load_dict(persist.load(session.state_path))
    p, q = session.pending, other.pending
    assert (q.kind, q.attacker.fid, q.target.fid, q.bot_card_guid) == (p.kind, p.attacker.fid, p.target.fid, p.bot_card_guid)
    assert (q.bot_card.card_id if q.bot_card else None) == (p.bot_card.card_id if p.bot_card else None)


def test_d6_corrupt_or_foreign_save_files_are_refused_with_a_clear_error(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{no json", encoding="utf-8")
    with pytest.raises(persist.StateError):
        persist.load(bad)
    bad.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(persist.StateError, match="version"):
        persist.load(bad)
    with pytest.raises(persist.StateError):
        persist.load(tmp_path / "no_existe.json")


def test_d6_resume_finishes_a_bot_turn_that_was_left_half_done(rig, monkeypatch, tmp_path):
    session, table, game = rig
    maneuver_plan(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    real, state = session.sync_positions, {"fail": True}

    def flaky():
        if state["fail"] and game.turn == 0:
            state["fail"] = False
            raise TimeoutError("TTS no devolvio valor")
        real()
    monkeypatch.setattr(session, "sync_positions", flaky)
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert game.turn == 0 and json.loads(session.state_path.read_text())["bot_stage"] == "start"
    other = fresh_session(session)
    maneuver_plan(other, monkeypatch)
    other.load_dict(persist.load(session.state_path))
    msgs = other.resume()
    assert other.game.turn == 1 and other.game.actions_left == 2 and msgs[0].startswith("Partida reanudada")


def test_d6_resume_mid_human_turn_says_how_many_actions_are_left(rig, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    session.handle(Event.SCHEME)
    other = fresh_session(session)
    other.load_dict(persist.load(session.state_path))
    assert any("te quedan 1 accion" in m for m in other.resume())


def test_d6_first_bot_start_with_a_table_failure_is_resumable_not_fatal(rig, monkeypatch):
    session, table, game = rig
    game.turn = 0
    game.begin_turn()
    real, state = session.read_bot_hand, {"fail": True}

    def flaky():
        if state["fail"]:
            state["fail"] = False
            raise TimeoutError("TTS no devolvio valor")
        real()
    monkeypatch.setattr(session, "read_bot_hand", flaky)
    maneuver_plan(session, monkeypatch)
    msgs = session.start()
    assert game.turn == 0 and session.bot_stage == "start" and any("Fin de accion" in m for m in msgs)
    session.handle(Event.END_ACTION)
    assert game.turn == 1 and game.actions_left == 2


def test_d6_tts_closed_is_a_connection_message_not_an_internal_error(rig, monkeypatch):
    session, table, game = rig

    def refused(*a, **k):
        raise ConnectionRefusedError("[WinError 10061] rechazada")
    monkeypatch.setattr(session.client, "call_lua", refused)
    msgs = session.handle(Event.MANEUVER)
    assert any("conexion" in m and "mesa" in m for m in msgs) and not any("interno" in m.lower() for m in msgs)
    assert game.actions_left == 2, "no se gasto la accion"
    said, stop = [], threading.Event()
    queue = [{"event": "scheme"}]
    monkeypatch.setattr(session.client, "poll_events", lambda: [queue.pop()] if queue else [])
    threading.Timer(0.2, stop.set).start()
    play.run_loop(session, session.client, stop, said.extend, poll=0.01)
    assert any("conexion" in m for m in said) and not any("Error interno" in m for m in said)


def test_startup_failure_of_the_session_is_a_clear_message_and_exit_2(live, cfg_file, monkeypatch, capsys):
    table, fake, ports = live

    def boom(self):
        raise SessionError("bot_deck_spot es obligatorio")
    monkeypatch.setattr(play.Session, "start", boom)
    assert play.main(["--config", str(cfg_file()), *ports, "--state", str(cfg_file().parent / "e.json")]) == 2
    err = capsys.readouterr().err
    assert "No puedo empezar" in err and "bot_deck_spot" in err and "Traceback" not in err


def test_startup_failure_without_tts_is_exit_3_and_resume_without_a_save_is_exit_2(cfg_file, tmp_path, capsys):
    ports = ["--send-port", str(free_port()), "--listen-port", str(free_port())]
    state = str(tmp_path / "s.json")
    assert play.main(["--config", str(cfg_file()), *ports, "--state", state]) == 3
    assert "No pude hablar con TTS" in capsys.readouterr().err
    assert play.main(["--config", str(cfg_file()), "--resume", *ports, "--state", state]) in (2, 3)


def test_d6_main_resume_reads_the_save_and_continues(live, cfg_file, tmp_path):
    table, fake, ports = live
    state = tmp_path / "s.json"
    stop = threading.Event()
    result = {}

    def run(extra):
        result["code"] = play.main(["--config", str(cfg_file()), "--poll", "0.02", "--first", "human", *ports, "--state", str(state), *extra],
                                   stop=stop)
    t = threading.Thread(target=run, args=([],))
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and not state.exists():
        time.sleep(0.02)
    fake.push({"messageID": 4, "customMessage": {"event": "scheme"}})
    deadline = time.time() + 5
    while time.time() < deadline and json.loads(state.read_text())["game"]["actions_left"] != 1:
        time.sleep(0.02)
    stop.set()
    t.join(5)
    assert json.loads(state.read_text())["game"]["actions_left"] == 1
    stop2 = threading.Event()
    threading.Timer(0.8, stop2.set).start()
    t2 = threading.Thread(target=lambda: result.setdefault("c2", play.main(
        ["--config", str(cfg_file()), "--poll", "0.02", "--first", "human", *ports, "--state", str(state), "--resume"], stop=stop2)))
    t2.start()
    t2.join(6)
    assert result["c2"] == 0
    assert any("reanudada" in b for b in table.broadcasts) and any("1 accion" in b for b in table.broadcasts)


# ---------- D7: piezas por GUID ----------
@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_d7_positions_are_read_by_guid_never_by_name(rig):
    session, table, game = rig
    table.positions["Hellboy"] = 5
    table.scripts.clear()
    session.sync_positions()
    assert game.fighters["hellboy"].pos == 5
    (script,) = [s for s in table.scripts if "piece_spaces" in s]
    assert script.startswith("-- sparring:piece_spaces_by_guid") and '"pchellboy"' in script
    assert "getName() ==" not in script
    assert not any(s.startswith(("-- sparring:piece_spaces\n", "-- sparring:move_miniature")) for s in table.scripts)


def test_d7_missing_piece_is_reported_once_and_keeps_its_last_square(rig):
    session, table, game = rig
    before = game.fighters["hellboy"].pos
    table.missing_pieces = {"pchellboy"}
    session.messages = []
    session.sync_positions()
    session.sync_positions()
    assert game.fighters["hellboy"].pos == before
    assert sum("No encuentro la pieza de Hellboy (pchellboy)" in m for m in session.messages) == 1


def test_d7_a_piece_far_from_every_square_is_off_the_board_and_does_not_snap(rig):
    session, table, game = rig
    before = game.fighters["lobster"].pos
    table.positions["Lobster Johnson"], table.piece_dist["Lobster Johnson"] = 3, 80.0
    session.messages = []
    session.sync_positions()
    assert game.fighters["lobster"].pos == before
    assert any("fuera del tablero" in m and "Retirar" in m for m in session.messages)
    table.piece_dist.clear()
    session.sync_positions()
    assert game.fighters["lobster"].pos == 3


def test_d7_project_checks_that_the_piece_really_moved(rig):
    session, table, game = rig
    h1 = game.fighters["harpy1"]
    before = session._snapshot_bot()
    h1.pos = 2
    table.move_fails = {"pcharpy1"}
    with pytest.raises(SessionError, match="pcharpy1"):
        session._project(before)
    table.move_fails = set()
    session._project(before)
    assert ("Harpy 1", 2) in table.moves


def test_d7_unmovable_piece_does_not_freeze_the_game(rig, monkeypatch):
    session, table, game = rig
    table.move_fails = {"pcmedusa", "pcharpy1", "pcharpy2", "pcharpy3"}
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": game.fighters["medusa"].pos}))
    session.ai.execute = lambda g, act: (setattr(game.fighters["harpy1"], "pos", 2), g.use_action(), g.draw(0))
    game.actions_left = 0
    for _ in range(4 * session.cfg.adopt_after):
        session.handle(Event.END_ACTION)
        if game.turn == 1:
            break
    assert game.turn == 1


def test_d7_move_and_piece_builders_validate_the_guid_and_square(bprd):
    s = lua.move_piece(bprd, "04b2c9", 4)
    assert 'getObjectFromGUID("04b2c9")' in s and "moved = false" in s
    for bad in (lambda: lua.move_piece(bprd, "a b", 4), lambda: lua.move_piece(bprd, "04b2c9", 9999),
                lambda: lua.piece_spaces_by_guid(bprd, ["ok", 'x"']), lambda: lua.move_piece(bprd, "", 1)):
        with pytest.raises((ValueError, TypeError)):
            bad()


# ---------- D1 y lectura pura ----------
def test_d1_read_only_flags_a_discard_zone_that_overlaps_a_hand_zone_or_shares_cards(live, cfg_file, capsys):
    table, fake, ports = live
    base = Game.new(play.Board.load("bprd-hq"), 0)
    pancakes = card(base, 1, "Pancakes!").card_id
    table.hand_zones = {"HUMZ": ["dd569b"]}
    table.human_hand = [pancakes]
    table.human_discard = [pancakes]
    assert play.main(["--config", str(cfg_file()), "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "AVISO: descarte humano HUMZ: se solapa con la zona de mano dd569b" in out
    assert "AVISO: descarte humano HUMZ: comparte 1 carta(s) con la mano" in out and "zona de MANO" in out


def test_d1_read_only_is_quiet_when_the_zones_are_fine(live, cfg_file, capsys):
    table, fake, ports = live
    assert play.main(["--config", str(cfg_file()), "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "zona de mano" not in out and "comparte" not in out


def test_d7_read_only_reports_every_piece_with_type_and_distance_and_flags_the_bad_ones(live, cfg_file, capsys):
    table, fake, ports = live
    table.missing_pieces = {"pcharpy1"}
    table.piece_dist["Hellboy"] = 40.0
    table.dials = {"bcd809": {"found": True, "name": "Medusa", "value": 16, "max": 16}}
    assert play.main(["--config", str(cfg_file(dials={"medusa": "bcd809", "hellboy": "046660"})),
                      "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "Custom_Token 'Medusa'" in out and "(a 0.10 del enganche)" in out
    assert "AVISO: miniatura harpy1 pcharpy1: NO existe" in out
    assert "AVISO: miniatura hellboy pchellboy esta fuera del tablero" in out
    assert "vida 16 de 16" in out and "AVISO: dial hellboy 046660: NO existe" in out
    tags = {s.split("\n")[0] for s in table.scripts}
    assert tags <= {f"-- sparring:{t}" for t in play.READ_ONLY_TAGS}
    assert {"-- sparring:read_health_dials", "-- sparring:zone_overlaps", "-- sparring:piece_spaces_by_guid"} <= tags


def _spec(board):
    return lua.SnapSpec(board, "Blue", "Red", "BOTZ", ("DECK1",), ((0.0, 3.0),), "HUMZ", (), (), 1.5, (0.0, 5.0),
                        (0.0, -5.0), 2.0, ("pca",), ("DM",))


def test_read_only_allowlist_is_exactly_the_pure_read_builders(bprd):
    import inspect
    builders = {
        "piece_spaces_by_guid": lambda: lua.piece_spaces_by_guid(bprd, ["04b2c9"]),
        "read_hand": lambda: lua.read_hand("Blue"), "count_hand": lambda: lua.count_hand("Blue"),
        "read_discard": lambda: lua.read_discard("abc", ["d42056"], [(1.0, 2.0)]),
        "read_face_down_cards": lambda: lua.read_face_down_cards(0, 0),
        "inspect_guids": lambda: lua.inspect_guids(["abc"]), "read_health_dials": lambda: lua.read_health_dials(["abc"]),
        "zone_overlaps": lambda: lua.zone_overlaps(["abc"]),
        "deck_identities": lambda: lua.deck_identities([("abc", (0.0, 3.0), lua.BOT_CARD_IDS)]),
        "deal_cards": lambda: t_deal_cards("abc", 1, "Blue", spot=(0, 0)),
        "return_card_to_hand": lambda: lua.return_card_to_hand("abc", "Blue"),
        "discard_cards": lambda: t_discard_cards([1], [(0, 0, 0)]), "broadcast": lambda: lua.broadcast("x"),
        "move_piece": lambda: lua.move_piece(bprd, "abc", sorted(bprd.spaces)[0]),
        "play_card_face_down": lambda: t_play_card_face_down(1, "Blue", 0, 0, 0),
        "flip_card": lambda: t_flip_card("abc"), "create_panel": lambda: lua.create_panel(["medusa"]),
        "draw_markings": lambda: lua.draw_markings([("DESCARTE", "abc")], [("COMBATE", 0, 0)]),
        "clear_markings": lambda: lua.clear_markings(),
        "set_health_dials": lambda: lua.set_health_dials({"abc": 3}),
        "name_pieces": lambda: lua.name_pieces({"abc": "Harpy 1"}),
        "place_piece": lambda: lua.place_piece("abc", 1.0, 2.0, 3.0),
        "table_heroes": lambda: lua.table_heroes([(1, 2)], ["abc"]),
        "unpack_from_bags": lambda: lua.unpack_from_bags([("piece", ("abc",), "def", (0.0, 0.0, 0.0), None)]),
        "return_hand_to_deck": lambda: t_return_hand_to_deck("Blue", "abc"),
        "shuffle_deck": lambda: t_shuffle_deck("abc", (0.0, 3.0)),
        "snapshot": lambda: lua.snapshot(_spec(bprd)),
        "composite": lambda: lua.composite([lua.broadcast("x")]),
        "reset_deck": lambda: t_reset_deck("abc", (0.0, 3.0), lua.BOT_CARD_IDS),
        "reset_plan": lambda: t_reset_plan([("abc", (0.0, 3.0), lua.BOT_CARD_IDS, TEST_IDENT)]),
        "hand_identities": lambda: lua.hand_identities("Blue", lua.BOT_CARD_IDS),
        "set_panel": lambda: lua.set_panel("Tu turno", {"btn_end": (True, True)}),
        "show_hand_row": lambda: lua.show_hand_row([1], [(0.0, 0.0, 0.0)], 90.0, "Blue", identity=TEST_IDENT),
        "resolve_hand_row": lambda: lua.resolve_hand_row(["abc"], "Blue", identity=TEST_IDENT),
        "set_look_row": lambda: lua.set_look_row([("abc", 0.0, 0.0)]),
        "set_state": lambda: lua.set_state("abc", 2), "set_token_face": lambda: lua.set_token_face("abc", 0),
        "flip_token": lambda: lua.flip_token("abc"),
        "ping_objects": lambda: lua.ping_objects(["Blue"], [["abc"]]),
        "ping_points": lambda: lua.ping_points(["Blue"], [(0.0, 0.0, 0.0)]),
        "card_to_deck_top": lambda: lua.card_to_deck_top("abc", "def", identity=TEST_IDENT),
        "card_to_deck_bottom": lambda: lua.card_to_deck_bottom("abc", "def", identity=TEST_IDENT),
        "shuffle_into_deck": lambda: lua.shuffle_into_deck("abc", ["def"]),
        "deal_row": lambda: lua.deal_row("abc", [(0.0, 0.0, 0.0)], identity=TEST_IDENT),
        "take_token_copy": lambda: lua.take_token_copy("abc", (0.0, 0.0, 0.0)),
        "remove_token": lambda: lua.remove_token("abc"),
        "place_from_bag": lambda: lua.place_from_bag("abc", "Rat", (0.0, 0.0, 0.0)),
        "inspect_objects": lambda: lua.inspect_objects(["abc"]),
    }
    registered = {n for n, f in inspect.getmembers(lua, inspect.isfunction) if hasattr(f, "__wrapped__")}
    assert registered == set(builders), registered ^ set(builders)

    class Rec:
        def call_lua(self, *a, **k):
            return None
    ro = play.ReadOnlyClient(Rec())
    passed = set()
    for n, b in builders.items():
        try:
            ro.call_lua(b())
            passed.add(n)
        except play.ReadOnlyViolation:
            pass
    assert passed == set(play.READ_ONLY_TAGS)
    mutators = ("setPosition", "setRotation", "flip", "takeObject", "deal", "destruct", "setName", "setLock",
                "setLuaScript", "UI.", "spawn", "putObject", "broadcast", "shuffle", "setState", "split", "setVar",
                "setValue", "editButton")
    for n in play.READ_ONLY_TAGS:
        body = builders[n]()
        assert not [m for m in mutators if m in body], (n, [m for m in mutators if m in body])


# ---------- D8 y D9: cartas sueltas ----------
def test_d8_an_untracked_bot_card_lying_on_the_table_is_adopted_instead_of_looping(rig):
    session, table, game = rig
    gaze = card(game, 0, "Gaze of Stone")
    table.bot_deck = []                                       # el mazo fisico no tiene nada que repartir
    game.draw(0)
    assert game.drawn[0] == 1
    table.stray_bot = [{"id": gaze.card_id, "guid": f"s{gaze.card_id}"}]
    session.dirty = True
    msgs = session.handle(Event.END_ACTION)
    assert not any("repartio 0 de 1" in m for m in msgs) and any("estaba suelta" in m for m in msgs), msgs
    assert not any("repartio" in m for m in session.handle(Event.END_ACTION))
    assert gaze.card_id in table.bot_hand and game.drawn[0] == 0 and not session.dirty


def test_d8_a_missing_card_with_nothing_on_the_table_still_reports_the_short_deal(rig):
    session, table, game = rig
    table.bot_deck = []
    game.draw(0)
    session.dirty = True
    with pytest.raises(SessionError, match="repartio 0 de 1"):
        session._reconcile_bot()


def test_d9_deal_fallback_only_takes_objects_whose_card_id_is_in_the_bot_deck_range():
    s = t_deal_cards("d42056", 1, "Green", spot=(11.5, 12.0))
    assert "17600" in s and "17629" in s
    assert s.index("ours(o)") < s.index("d = o") and "and ours(o) and (best == nil" in s and "o.is_face_down" in s
    custom = t_deal_cards("d42056", 1, "Green", spot=(1.0, 2.0), id_range=(100, 129))
    assert "id < 100 or id > 129" in custom
    assert "and ours(o) and (best == nil" not in t_deal_cards("d42056", 1, "Green"), "sin punto no hay busqueda"
    assert "if d ~= nil and not ours(d) then d = nil end" in s, "tambien el mazo hallado por GUID debe ser el nuestro"


# ---------- descarte ordenado en la zona ----------
def test_discard_slots_follow_the_grid_in_play_order_and_avoid_the_draw_deck(rig):
    session, table, game = rig
    c = session.cfg
    slots = [session._discard_slot(k) for k in range(30)]
    assert slots[0] == c.bot_discard_spot and slots[1][2] > slots[0][2]
    assert len(set(slots)) == 30
    assert all((x - c.bot_deck_spot[0]) ** 2 + (z - c.bot_deck_spot[1]) ** 2 > c.deck_clear ** 2 for x, _, z in slots)
    assert session._discard_slot(500)[::2] in {session._discard_slot(k)[::2] for k in range(100)}, "da la vuelta"


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_bot_discards_are_spread_in_order_and_the_draw_deck_is_never_read_as_discard(rig, monkeypatch):
    session, table, game = rig
    session.cfg.human_deck_guid, session.cfg.human_deck_spot = "HDECK", (-7.7, 12.5)
    boost = card(game, 0, "Dash")
    maneuver_plan(session, monkeypatch, boost=boost)
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert boost.card_id in table.discard_spots
    assert table.discard_spots[boost.card_id] == session._discard_slot(game.players[0].discard.index(boost))
    assert any("Vector(0, 90.0, 0)" in s for s in table.scripts if s.startswith("-- sparring:discard_cards"))
    bot_reads = [s for s in table.scripts if s.startswith("-- sparring:read_discard") and '"BOTZ"' in s]
    human_reads = [s for s in table.scripts if s.startswith("-- sparring:read_discard") and '"HUMZ"' in s]
    assert bot_reads and all('["DECK1"]=true' in s and "{0.0, 3.0}" in s for s in bot_reads)
    assert human_reads and all('["HDECK"]=true' in s and "{-7.7, 12.5}" in s for s in human_reads)


# ---------- D11: los dos mutantes que sobrevivian ----------
def test_d11_n1_human_combat_card_in_the_discard_does_not_count_as_the_forced_discard(rig, monkeypatch):
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    played = human_plays(table, game, "Glimpse Of Hell", 0)
    table.human_count = 1
    session.handle(Event.REVEAL)
    d = session.pending_discard
    assert d is not None and d["kind"] == "cards"
    table.human_discard = [played.card_id]                    # su carta de combate ya esta en el descarte...
    table.face_down = []
    maneuver_plan(session, monkeypatch)
    msgs = session.handle(Event.END_ACTION)
    assert session.pending_discard is not None, "...pero eso no es el descarte obligatorio de Clutching Claws"
    assert any("Aun falta descartar" in m for m in msgs)
    table.human_discard = [played.card_id, card(game, 1, "Glimpse Of Hell", 1).card_id]
    table.human_count = 0
    session.handle(Event.END_ACTION)
    assert session.pending_discard is None


def test_d11_n3_medusa_ability_still_fires_after_the_start_of_turn_retry(rig, monkeypatch):
    session, table, game = rig
    maneuver_plan(session, monkeypatch)
    place(game, medusa=0, hellboy=1)
    table.positions.update({"Medusa": 0, "Hellboy": 1})
    real, state = session.sync_positions, {"fail": True}

    def flaky():
        if state["fail"] and game.turn == 0:
            state["fail"] = False
            raise TimeoutError("TTS no devolvio valor")
        real()
    monkeypatch.setattr(session, "sync_positions", flaky)
    hp_before = game.fighters["hellboy"].hp
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert game.turn == 0 and game.fighters["hellboy"].hp == hp_before
    msgs = session.handle(Event.END_ACTION)
    assert any("Habilidad de Medusa" in m for m in msgs) and game.fighters["hellboy"].hp == hp_before - 1


# ---------- marcas en el suelo ----------
ZONES = [("DESCARTE HELLBOY", "b7a0b8"), ("DESCARTE MEDUSA", "906a7a")]
CARDS = [("COMBATE HELLBOY", -2.0, -18.0), ("COMBATE MEDUSA", 6.0, -18.0)]


def test_markings_draw_on_the_bots_own_panel_only_and_never_touch_the_global():
    s = lua.draw_markings(ZONES, CARDS)
    assert lua.is_sendable(s) and s.startswith("-- sparring:draw_markings")
    assert "panel.setVectorLines(lines)" in s and "panel.positionToLocal(wp)" in s
    assert 'getName() == "SparringPanel"' in s
    for forbidden in ("Global", "setDecals", "UI.", "setXml", "Global.setVectorLines"):
        assert forbidden not in s, forbidden
    assert s.count("setVectorLines") == 1 and "\n  setVectorLines" not in s and " setVectorLines(" not in s
    assert '{"DESCARTE HELLBOY", "b7a0b8"}' in s and "getObjectFromGUID(z[2])" in s and "getRotation()" in s and "getScale()" in s
    assert '"DESCARTE HELLBOY"' in s and '"COMBATE MEDUSA"' in s
    assert "{1.0, 0.45, 0.0}" in s and "{1.0, 1.0, 1.0}" in s, "un color por tipo"
    assert "{-1, -1}, {1, -1}, {1, 1}, {-1, 1}, {-1, -1}" in s, "contorno cerrado de 5 puntos"


def test_markings_are_idempotent_labels_are_reused_by_name_and_clear_removes_them():
    s = lua.draw_markings(ZONES, CARDS)
    assert 'local name = "SparringLabel" .. " " .. r.label' in s
    assert "if found == nil then" in s and "setText(found, r.label)" in s
    c = lua.clear_markings()
    assert lua.is_sendable(c) and "o.setVectorLines({})" in c and "o.destruct()" in c
    assert 'string.sub(name, 1, 13) == "SparringLabel"' in c and "Global" not in c


@pytest.mark.parametrize("build", [
    lambda: lua.draw_markings([('X"); UI.hide("y") --', "abc")], CARDS),
    lambda: lua.draw_markings([("DESCARTE", 'abc"); os.exit() --')], CARDS),
    lambda: lua.draw_markings([("DESCARTE", "abc")], [("C", "0) UI.hide('x') --", 0)]),
    lambda: lua.draw_markings([("DESCARTE", "abc")], [("C", 0, float("inf"))]),
    lambda: lua.draw_markings([("DESCARTE", "abc")], [("C", 0)]),
    lambda: lua.draw_markings([("DESCARTE",)], []),
    lambda: lua.draw_markings("b7a0b8", []),
    lambda: lua.draw_markings([], [("C", 0, 0)], card_size=("1) --", 3)),
    lambda: lua.draw_markings([], [("C", 0, 0)], card_size=(2,)),
    lambda: lua.draw_markings([(None, "abc")], []),
])
def test_markings_builders_reject_injection(build):
    with pytest.raises((ValueError, TypeError)):
        build()


def test_the_read_only_client_rejects_the_marking_builders():
    class Boom:
        def call_lua(self, *a, **k):
            raise AssertionError("no debia llegar al cliente real")
    ro = play.ReadOnlyClient(Boom())
    for script in (lua.draw_markings(ZONES, CARDS), lua.clear_markings()):
        with pytest.raises(play.ReadOnlyViolation):
            ro.call_lua(script)
    assert {"draw_markings", "clear_markings"}.isdisjoint(play.READ_ONLY_TAGS)


def test_play_draws_the_markings_once_at_startup_and_clears_them_on_exit(live, cfg_file):
    table, fake, ports = live
    stop = threading.Event()
    t = threading.Thread(target=lambda: play.main(["--config", str(cfg_file()), "--poll", "0.02", "--first", "human", *ports, "--state",
                                                   str(cfg_file().parent / "s.json")], stop=stop))
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and not table.markings:
        time.sleep(0.02)
    stop.set()
    t.join(5)
    assert len(table.markings) == 1 and table.count("clear_markings") == 2     # restos al empezar + todo al salir
    m = table.markings[0]
    assert '"DESCARTE HELLBOY", "HUMZ"' in m and '"DESCARTE MEDUSA", "BOTZ"' in m
    assert '"HELLBOY", 0.0, -5.0' in m and '"MEDUSA", 0.0, 5.0' in m


def test_read_only_never_draws(live, cfg_file):
    table, fake, ports = live
    assert play.main(["--config", str(cfg_file()), "--read-only", *ports]) == 0
    assert table.count("draw_markings") == 0 and table.count("clear_markings") == 0


def test_markings_are_redrawn_after_a_tts_reload(rig):
    session, table, game = rig
    targets = [f.fid for f in game.own(0)]
    status, _ = play.recover_after_reload(session, session.client, targets, (0, 1, -14))
    assert status == "ok" and len(table.markings) == 1
