from conftest import t_deal_cards, t_discard_cards, t_flip_card, t_play_card_face_down
import json
import re
import socket

import pytest

from fake_tts import FakeTTS
from sparring.tts import lua, ui
from sparring.tts.client import LISTEN_PORT, SEND_PORT, TTSClient, TTSLuaError, UnsafeMessage, is_sendable


@pytest.fixture
def fake():
    f = FakeTTS()
    yield f
    f.close()


@pytest.fixture
def client(fake):
    c = TTSClient(send_port=fake.port, listen_port=0)
    yield c
    c.close()


def wait_for(fake, n=1):
    import time
    for _ in range(100):
        if len(fake.received) >= n:
            return
        time.sleep(0.02)
    raise AssertionError("el servidor falso no recibio el mensaje")


def test_default_ports_are_the_real_ones():
    assert (SEND_PORT, LISTEN_PORT) == (39999, 39998)


def test_custom_message_uses_id_2(client, fake):
    client.send_custom({"hello": 1})
    wait_for(fake)
    assert fake.received == [{"messageID": 2, "customMessage": {"hello": 1}}]


def test_execute_lua_uses_id_3_on_global(client, fake):
    script = lua.read_hand("Blue")
    client.execute_lua(script)
    wait_for(fake)
    assert fake.received == [{"messageID": 3, "guid": "-1", "script": script}]


@pytest.mark.parametrize("bad", [0, 1, 4, 5, None])
def test_other_message_ids_are_refused_and_nothing_is_sent(client, fake, bad):
    with pytest.raises(UnsafeMessage):
        client.send({"messageID": bad, "script": "x"})
    assert fake.received == []


@pytest.mark.parametrize("script", [
    'UI.setXml("<Panel/>")',
    'Global.UI.setXml("x")',
    'UI.hide("panel")',
    '_G.UI.setXml("x")',
    'local u = UI' + chr(10) + 'u.setXml("x")',
    'Global.call("anything")',
    'UI . setXml("x")',
    'Global.setLuaScript("x")',
    "panel.UI.setXml('<Panel/>')",   # ni siquiera lo "seguro" pasa si no lo genero un constructor
    "return 1",
    "",
])
def test_arbitrary_lua_is_refused_and_nothing_is_sent(client, fake, script):
    with pytest.raises(UnsafeMessage):
        client.execute_lua(script)
    with pytest.raises(UnsafeMessage):
        client.call_lua(script)
    assert fake.received == []


def test_builder_output_is_sendable_but_a_modified_copy_is_not(client, fake):
    script = lua.read_hand("Blue")
    assert is_sendable(script)
    with pytest.raises(UnsafeMessage):
        client.execute_lua(script + chr(10) + "UI.setXml('x')")
    assert fake.received == []


def test_call_lua_returns_decoded_value():
    f = FakeTTS(return_value=json.dumps({"hellboy": {"space": 4}}))
    c = TTSClient(send_port=f.port, listen_port=0)
    try:
        listener = c.start_listening()
        f.reply_port = listener.port
        assert c.call_lua(lua.read_hand("Blue")) == {"hellboy": {"space": 4}}
    finally:
        c.close()
        f.close()


def test_lua_error_of_our_own_script_raises():
    f = FakeTTS(return_value=lambda m: {"__error__": "boom"})
    c = TTSClient(send_port=f.port, listen_port=0)
    try:
        f.reply_port = c.start_listening().port
        with pytest.raises(TTSLuaError, match="boom"):
            c.call_lua(lua.read_hand("Blue"), timeout=2)
    finally:
        c.close()
        f.close()


def test_button_events_arrive_as_custom_messages():
    f = FakeTTS()
    c = TTSClient(send_port=f.port, listen_port=0)
    try:
        listener = c.start_listening()
        f.push({"messageID": 4, "customMessage": {"event": "attack", "target": "medusa"}}, port=listener.port)
        f.push({"messageID": 2, "message": "print ignored"}, port=listener.port)
        import time
        time.sleep(0.3)
        events = c.poll_events()
        assert [ui.parse_event(e) for e in events] == [(ui.Event.ATTACK, {"target": "medusa"})]
    finally:
        c.close()
        f.close()


def test_suite_guard_refuses_real_ports_without_connecting():
    import conftest
    with pytest.raises(AssertionError):
        conftest.refuse_real_ports(("127.0.0.1", SEND_PORT))
    with pytest.raises(AssertionError):
        conftest.refuse_real_ports(("127.0.0.1", LISTEN_PORT))
    conftest.refuse_real_ports(("127.0.0.1", 50123))
    assert socket.socket.connect is not conftest.REAL_CONNECT  # el guardia esta instalado en todo el suite


# ---- snippets Lua ----
def test_piece_spaces_by_guid_snippet(bprd):
    s = lua.piece_spaces_by_guid(bprd, ["04b2c9", "f9789a"])
    assert 'getObjectFromGUID("ec6f27")' in s and 'wanted = {"04b2c9", "f9789a"}' in s
    assert "board.positionToWorld" in s and "getObjectFromGUID(g)" in s and "dist = math.sqrt(bd)" in s
    assert "found = false" in s and "getObjects()" not in s and "getName() ==" not in s
    assert f"[4]={{{bprd.spaces[4].local[0]},{bprd.spaces[4].local[1]}}}" in s
    assert s.count("]={") >= len(bprd.spaces)
    assert is_sendable(s)


def test_read_hand_and_discard_snippets():
    h = lua.read_hand("Blue")
    assert 'Player["Blue"].getHandObjects(1)' in h and "CardID" in h
    d = lua.read_discard("abc123")
    assert 'getObjectFromGUID("abc123")' in d and "ContainedObjects" in d
    for s in (h, d):
        assert is_sendable(s)


def test_move_piece_snippet(bprd):
    s = lua.move_piece(bprd, "04b2c9", 7)
    assert "spaceWorld(7)" in s and "setPositionSmooth" in s and 'getObjectFromGUID("04b2c9")' in s
    assert "getName()" not in s and "moved = false" in s
    assert is_sendable(s)
    with pytest.raises(ValueError):
        lua.move_piece(bprd, "04b2c9", 999)
    with pytest.raises(ValueError):
        lua.move_piece(bprd, 'Med"; os.exit() --', 1)


def test_play_and_flip_card_snippets():
    p = t_play_card_face_down(17615, "Blue", 1.5, 2.0, -3.0, rot_y=270)
    assert "CardID == 17615" in p and "Vector(0, 270.0, 180)" in p and "setPosition(" in p and "Smooth" not in p
    f_up = t_flip_card("g1", rot_y=270)
    assert "Vector(0, 270.0, 0.0)" in f_up
    assert "Vector(0, 270.0, 180.0)" in t_flip_card("g1", 270, face_up=False)
    for s in (p, f_up):
        assert is_sendable(s)


def test_panel_goes_on_own_object_not_global():
    xml = ui.panel_xml(["medusa", "harpy1"])
    s = lua.create_panel(["medusa", "harpy1"])
    assert "p.UI.setXml" in s and "spawnObject" in s and "setLuaScript" in s
    assert not re.search(r"(?<![\w.])UI\.setXml", s)
    assert is_sendable(s)
    with pytest.raises(ValueError):
        ui.panel_xml(['x" onClick="evil'])
    for name in ("onManeuver", "onAttack", "onScheme", "onReveal", "onEndAction", "onValueSend"):
        assert name in xml and f"function {name}" in ui.handler_script()
    assert 'id="harpy1"' in xml
    assert "sendExternalMessage" in ui.handler_script()


def test_read_face_down_snippet_does_not_flip():
    s = lua.read_face_down_cards(1.5, -2.0, 2.0)
    assert "is_face_down" in s and "flip" not in s and "CardID" in s and is_sendable(s)


def test_new_physical_snippets(bprd):
    d = t_deal_cards("abc123", 2, "Blue")
    assert "d.deal(k, \"Blue\")" in d and "math.min(2," in d
    x = t_discard_cards([17600, 17603], [(5.0, 1.0, 5.0), (5.0, 1.0, 7.2)], 90)
    assert "[17600]={5.0, 1.0, 5.0}" in x and "[17603]={5.0, 1.0, 7.2}" in x and "Vector(0, 90.0, 0)" in x
    c = lua.count_hand("Red")
    assert 'Player["Red"]' in c
    for s in (d, x, c):
        assert is_sendable(s) and s.startswith("-- sparring:")


# ---- S5: inyeccion por argumentos de los constructores ----
PAYLOAD = "0) UI.hide('roster') --"
BAD = [
    lambda b: t_play_card_face_down(17600, "Blue", PAYLOAD, 0, 0),
    lambda b: t_play_card_face_down(17600, "Blue", 0, PAYLOAD, 0),
    lambda b: t_play_card_face_down(17600, "Blue", 0, 0, PAYLOAD),
    lambda b: t_play_card_face_down(17600, "Blue", 0, 0, 0, PAYLOAD),
    lambda b: t_play_card_face_down("17600) UI.hide('x') --", "Blue", 0, 0, 0),
    lambda b: t_play_card_face_down(17600, 'Blue"] UI.hide("x") --', 0, 0, 0),
    lambda b: t_play_card_face_down(17600, "Notacolor", 0, 0, 0),
    lambda b: t_play_card_face_down(True, "Blue", 0, 0, 0),
    lambda b: t_play_card_face_down(17600, "Blue", float("nan"), 0, 0),
    lambda b: lua.read_hand(PAYLOAD),
    lambda b: lua.count_hand('Red"] UI.hide("x") --'),
    lambda b: lua.read_discard('abc"); UI.hide("x") --'),
    lambda b: t_deal_cards("abc123", PAYLOAD, "Blue"),
    lambda b: t_deal_cards('a"); UI.hide("x") --', 1, "Blue"),
    lambda b: t_deal_cards("abc123", 1, PAYLOAD),
    lambda b: t_discard_cards([PAYLOAD], [(0, 0, 0)]),
    lambda b: t_discard_cards([17600], [(PAYLOAD, 0, 0)]),
    lambda b: t_discard_cards([17600], [(0, 0, 0)], PAYLOAD),
    lambda b: lua.flip_card('g"); UI.hide("x") --'),
    lambda b: lua.flip_card("g1", PAYLOAD),
    lambda b: lua.move_piece(b, 'abc") UI.hide("x") --', 1),
    lambda b: lua.move_piece(b, "04b2c9", PAYLOAD),
    lambda b: lua.move_piece(b, "04b2c9", 1, board_guid='x"); UI.hide("y") --'),
    lambda b: lua.move_piece(b, None, 1),
    lambda b: lua.move_piece(b, "04b2c9", True),
    lambda b: lua.piece_spaces_by_guid(b, ['a"]=true UI.hide("x") --']),
    lambda b: lua.piece_spaces_by_guid(b, "04b2c9"),
    lambda b: lua.piece_spaces_by_guid(b, [None]),
    lambda b: lua.piece_spaces_by_guid(b, ["a"], board_guid=PAYLOAD),
    lambda b: lua.read_health_dials(['bcd809"); UI.hide("x") --']),
    lambda b: lua.read_health_dials("bcd809"),
    lambda b: lua.read_health_dials([7]),
    lambda b: lua.zone_overlaps(['bf62a8"); UI.hide("x") --']),
    lambda b: lua.zone_overlaps("bf62a8"),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(0, 0), id_range=(PAYLOAD, 17629)),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(0, 0), id_range=(17600,)),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(0, 0), id_range=(True, 17629)),
    lambda b: lua.read_face_down_cards(PAYLOAD, 0),
    lambda b: lua.read_face_down_cards(0, PAYLOAD),
    lambda b: lua.read_face_down_cards(0, 0, PAYLOAD),
    lambda b: lua.create_panel(['x" onClick="evil']),
    lambda b: lua.create_panel(["a"], position=(PAYLOAD, 0, 0)),
]


@pytest.mark.parametrize("build", BAD, ids=range(len(BAD)))
def test_injection_attempts_in_builder_arguments_are_rejected(bprd, build):
    with pytest.raises((ValueError, TypeError)):
        build(bprd)


def test_sendable_registration_is_module_private():
    import sparring.tts.client as client_mod
    assert not hasattr(client_mod, "sendable") and not hasattr(lua, "sendable")
    assert lua._sendable.__name__.startswith("_")


def test_numeric_arguments_are_formatted_with_repr():
    s = t_play_card_face_down(17600, "Blue", 1, 2, 3)
    assert "Vector(1.0, 2.0, 3.0)" in s and "CardID == 17600" in s


def test_deal_cards_handles_single_card_and_empty_deck():
    s = t_deal_cards("abc123", 2, "Blue", spot=(5.0, -3.0), radius=2.0)
    assert "d.deal(k, \"Blue\")" in s and "math.min(2," in s
    assert '"Card"' in s and "5.0" in s and "-3.0" in s and "getHandTransform" in s and is_sendable(s)
    assert "UI." not in s and "Global" not in s


def test_return_card_to_hand_snippet():
    s = lua.return_card_to_hand("g17603", "Blue")
    assert 'getObjectFromGUID("g17603")' in s and 'Player["Blue"].getHandTransform' in s and is_sendable(s)
    assert s.startswith("-- sparring:return_card_to_hand")


def test_cancel_button_and_handler_exist():
    assert ui.Event("cancel") is ui.Event.CANCEL
    assert 'onClick="onCancel"' in ui.panel_xml(["medusa"]) and "function onCancel" in ui.handler_script()
    assert ui.parse_event({"event": "cancel"}) == (ui.Event.CANCEL, {})


BAD_NEW = [
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(PAYLOAD, 0)),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(0, PAYLOAD)),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(0, 0), radius=PAYLOAD),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(float("inf"), 0)),
    lambda b: t_deal_cards("abc123", 1, "Blue", spot=(0,)),
    lambda b: lua.return_card_to_hand('g"); UI.hide("x") --', "Blue"),
    lambda b: lua.return_card_to_hand("g1", PAYLOAD),
    lambda b: lua.return_card_to_hand("g1", 'Blue"] UI.hide("x") --'),
    lambda b: lua.return_card_to_hand(17600, "Blue"),
]


@pytest.mark.parametrize("build", BAD_NEW, ids=range(len(BAD_NEW)))
def test_injection_attempts_in_new_builders_are_rejected(bprd, build):
    with pytest.raises((ValueError, TypeError)):
        build(bprd)


# ---- revision 3: constructores nuevos o cambiados ----
BAD_R3 = [
    lambda b: t_discard_cards([17600], [(PAYLOAD, 0, 0)]),
    lambda b: t_discard_cards([17600], [(0, PAYLOAD, 0)]),
    lambda b: t_discard_cards([17600], [(0, 0, PAYLOAD)]),
    lambda b: t_discard_cards([17600], [(0, 0, 0)], rot_y=PAYLOAD),
    lambda b: t_discard_cards([PAYLOAD], [(0, 0, 0)]),
    lambda b: t_discard_cards(["1]=true} os.exit() --"], [(0, 0, 0)]),
    lambda b: t_discard_cards("17600", [(0, 0, 0)]),
    lambda b: t_discard_cards([17600], [(float("nan"), 0, 0)]),
    lambda b: t_discard_cards([17600, 17601], [(0, 0, 0)]),
    lambda b: t_discard_cards([17600], [(0, 0)]),
    lambda b: t_discard_cards([17600], "000"),
    lambda b: lua.read_discard("abc", ['x"); UI.hide("y") --']),
    lambda b: lua.read_discard("abc", [], [(PAYLOAD, 0)]),
    lambda b: lua.read_discard("abc", [], [(0, 0, 0)]),
    lambda b: lua.read_discard("abc", "d42056"),
    lambda b: lua.read_discard("abc", [], [], PAYLOAD),
    lambda b: lua.inspect_guids(['x"}) os.exit() --']),
    lambda b: lua.inspect_guids([PAYLOAD]),
    lambda b: lua.inspect_guids([17600]),
    lambda b: lua.inspect_guids("abc123"),
    lambda b: lua.broadcast('hola"); os.exit() --'),
    lambda b: lua.broadcast("x" * 65),
    lambda b: lua.broadcast("acentos: piña"),
    lambda b: lua.broadcast("linea\nnueva"),
    lambda b: lua.broadcast(None),
]


@pytest.mark.parametrize("build", BAD_R3, ids=range(len(BAD_R3)))
def test_injection_attempts_in_revision3_builders_are_rejected(bprd, build):
    with pytest.raises((ValueError, TypeError)):
        build(bprd)


def test_inspect_broadcast_and_piece_count_snippets(bprd):
    i = lua.inspect_guids(["ec6f27", "d42056"])
    b = lua.broadcast("Tu turno: Revela!")
    p = lua.piece_spaces_by_guid(bprd, ["04b2c9"])
    assert 'getObjectFromGUID(g)' in i and '"ec6f27"' in i and not any(w in i for w in ("setPosition", "deal(", "destruct", "UI."))
    assert "broadcastToAll" in b and "type = obj.type" in p
    for s in (i, b, p):
        assert is_sendable(s) and s.startswith("-- sparring:")


def test_ascii_text_chunks_are_all_accepted_by_broadcast():
    text = "Combate: 7 contra 3, dano 4. Resuelve los efectos de despues del combate (mover piezas) y pulsa Fin de accion. ¿Listo?"
    chunks = lua.ascii_text(text)
    assert len(chunks) > 1 and all(len(c) <= 64 for c in chunks)
    for c in chunks:
        assert is_sendable(lua.broadcast(c))
    assert lua.ascii_text("áéíñ ¿?") == ["aein"]


def test_buttons_pressed_while_waiting_for_lua_are_not_lost():
    fake = FakeTTS()
    c = TTSClient(send_port=fake.port, listen_port=0)
    try:
        fake.reply_port = c.start_listening().port

        def answer(msg):
            fake.push({"messageID": 4, "customMessage": {"event": "reveal"}})
            return {"ok": 1}
        fake.return_value = answer
        assert c.call_lua(lua.read_hand("Blue")) == {"ok": 1}
        assert c.poll_events() == [{"event": "reveal"}]
        assert c.poll_events() == []
    finally:
        c.close()
        fake.close()


def test_send_retries_while_windows_has_no_ephemeral_port_and_fails_on_anything_else(monkeypatch):
    """WinError 10048 (ports in TIME_WAIT) is retried with a short wait, as FakeTTS.push does; any other error is
    raised at once and the retries are bounded."""
    from sparring.tts import client as mod
    sent, attempts, slept = [], [], []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def sendall(self, data):
            sent.append(data)

    def connect(addr, timeout):
        attempts.append(addr)
        if len(attempts) <= 2:
            raise OSError(10048, "address in use", None, 10048)
        return Conn()
    monkeypatch.setattr(mod.socket, "create_connection", connect)
    monkeypatch.setattr(mod.time, "sleep", slept.append)
    c = TTSClient(send_port=12345, listen_port=0)
    c.send({"messageID": 2, "customMessage": {"x": 1}})
    assert len(attempts) == 3 and len(sent) == 1 and slept == [mod.PORT_RETRY_WAIT] * 2

    def refused(addr, timeout):
        attempts.append(addr)
        raise OSError(10061, "refused", None, 10061)
    monkeypatch.setattr(mod.socket, "create_connection", refused)
    attempts.clear()
    with pytest.raises(OSError):
        c.send({"messageID": 2, "customMessage": {"x": 1}})
    assert len(attempts) == 1

    def always_busy(addr, timeout):
        attempts.append(addr)
        raise OSError(10048, "address in use", None, 10048)
    monkeypatch.setattr(mod.socket, "create_connection", always_busy)
    attempts.clear()
    with pytest.raises(OSError):
        c.send({"messageID": 2, "customMessage": {"x": 1}})
    assert len(attempts) == mod.PORT_RETRIES
