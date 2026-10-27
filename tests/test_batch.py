"""Modo rapido: el clic trae la instantanea, las escrituras salen en un script compuesto y el panel se actualiza."""
import dataclasses
import json
import re

import pytest

from fake_tts import FakeTTS
from sparring.ai_medusa import Act, MedusaAI
from sparring.board import Board
from sparring.session import Session, SessionConfig
from sparring.state import Game
from sparring.tts import lua, ui
from sparring.tts.client import TTSClient
from sparring.tts.ui import Event
from conftest import place
from test_session import NICK, PIECES, Table, card, human_plays, set_bot_hand


@pytest.fixture
def brig(bprd):
    table = Table()
    fake = FakeTTS(return_value=table)
    client = TTSClient(send_port=fake.port, listen_port=0)
    fake.reply_port = client.start_listening().port
    game = Game.new(bprd, seed=3, controllers={})
    cfg = SessionConfig("Blue", "Red", NICK, (0.0, 1.0, 5.0), (0.0, -5.0), (5.0, 1.0, 5.0), "BOTZ", "DECK1", "HUMZ",
                        (0.0, 3.0), PIECES, settle_tries=4, settle_wait=0.0, batch=True, live_ui=True,
                        dials={"medusa": "DM", "hellboy": "DH", "lobster": "DL"}, destiny_dial="DD")
    session = Session(game, client, MedusaAI(0), cfg)
    game.turn, game.turn_no = 1, 2
    game.begin_turn()
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    for g, v in (("DM", 16), ("DH", 18), ("DL", 6), ("DD", 0)):
        table.dials[g] = {"found": True, "name": g, "value": v, "max": v}
    for fid, g in cfg.dials.items():
        session.dials_written[g] = game.fighters[fid].hp
    set_bot_hand(table, game, "Snipe", "Dash")
    session.read_bot_hand()
    session.snap = None
    yield session, table, game, fake
    client.close()
    fake.close()


def click(session, table, event, payload=None):
    """Un clic del panel: lleva la instantanea de la mesa en el momento de pulsar."""
    return session.handle(event, {**(payload or {}), "snapshot": json.dumps(table.snapshot_state())})


def spec(board):
    return lua.SnapSpec(board, "Blue", "Red", "BOTZ", ("DECK1",), ((0.0, 3.0),), "HUMZ", (), (), 1.5, (0.0, 5.0),
                        (0.0, -5.0), 2.0, ("pca",), ("DM",))


# ---------- mensajes por boton ----------
def test_human_buttons_cost_one_message_each(brig):
    session, table, game, fake = brig
    for event in (Event.MANEUVER, Event.END_ACTION):
        n = fake.lua_messages
        click(session, table, event)
        assert fake.lua_messages - n == 1 and table.sent[-1] == "composite", event
    game.actions_left = 2
    session.moving = False
    n = fake.lua_messages
    click(session, table, Event.SCHEME)
    assert fake.lua_messages - n == 1


def test_attack_and_reveal_cost_at_most_two_messages(brig):
    session, table, game, fake = brig
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    n = fake.lua_messages
    click(session, table, Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None and not session.pending.defended
    assert fake.lua_messages - n <= 2                                   # validar mano + cierre; el bot aun no pone nada
    human_plays(table, game, "Service Pistol")
    n = fake.lua_messages
    click(session, table, Event.REVEAL)
    assert session.pending is None and fake.lua_messages - n <= 3   # defensa del bot + giro/resolucion + cierre
    assert len(table.flips) == 1, "la carta del bot se descarta en el mismo compuesto: no se gira, solo la del humano"


def test_each_bot_action_costs_at_most_two_messages(brig, monkeypatch):
    session, table, game, fake = brig
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    n = fake.lua_messages
    click(session, table, Event.END_ACTION)
    assert game.turn == 1 and game.turn_no == 4
    actions = [c for label, c, _ in session.cost_log if label == "accion del bot"]
    assert actions and max(actions) <= 2
    assert fake.lua_messages - n <= 6, "el turno entero del bot: 2 acciones, fin de turno y cierre"


def test_everything_the_button_did_goes_in_one_composite_with_the_state_and_the_announcements(brig):
    session, table, game, fake = brig
    click(session, table, Event.MANEUVER)
    status, states = table.panels[-1]
    assert status.startswith("Tu turno") and "esperando Fin de accion" in status
    assert states["btn_end"] == (True, True) and states["btn_maneuver"] == (False, True)
    assert any("Maniobra" in b for b in table.broadcasts)


def test_a_click_without_snapshot_primes_with_a_single_read(brig):
    session, table, game, fake = brig
    n = fake.lua_messages
    session.handle(Event.MANEUVER)
    assert table.sent[-2:] == ["snapshot", "composite"] and fake.lua_messages - n == 2


def test_the_snapshot_is_dropped_after_each_button(brig):
    session, table, game, fake = brig
    click(session, table, Event.MANEUVER)
    assert session.snap is None and session._queue == []


def test_the_click_snapshot_counts_as_a_confirmed_read(brig):
    session, table, game, fake = brig
    click(session, table, Event.END_ACTION)
    n = fake.lua_messages
    table.human_discard = [card(game, 1, "Excalibur").card_id]
    click(session, table, Event.END_ACTION)
    assert fake.lua_messages - n == 1


# ---------- el compuesto ----------
def test_composite_is_registered_and_only_wraps_allowlisted_operations(bprd):
    ops = [lua.broadcast("hola"), lua.move_piece(bprd, "abc", sorted(bprd.spaces)[0])]
    s = lua.composite(ops)
    assert lua.is_sendable(s) and s.startswith("-- sparring:composite") and s.count("-- sparring:") == 3
    assert "sparringSnapshot" not in s and "Wait.condition" in s
    with_state = lua.composite(ops, spec(bprd), ("Blue", 5))
    assert "sparringSnapshot()" in with_state and 'local expectSeat, expectN = "Blue", 5' in with_state


@pytest.mark.parametrize("bad", [
    ["print('hola')"], ["-- sparring:broadcast\nbroadcastToAll('x')"], [], [""], [None], [5], "no es una lista",
    ["x"] * 65,
])
def test_composite_rejects_anything_that_is_not_an_allowlisted_operation(bad):
    with pytest.raises((ValueError, TypeError)):
        lua.composite(bad)


def test_composite_rejects_too_many_operations():
    with pytest.raises(ValueError):
        lua.composite([lua.broadcast("a")] * 65)


def test_composite_rejects_nesting_wrapped_requests_and_forged_headers(bprd):
    with pytest.raises(ValueError):
        lua.composite([lua.composite([lua.broadcast("a")])])
    with pytest.raises(ValueError):
        lua.composite([lua.snapshot(spec(bprd))])
    with pytest.raises(ValueError):
        lua.composite([lua.request(lua.broadcast("a"), 5)])
    with pytest.raises(ValueError):
        lua.composite([lua.broadcast("a") + "-- sparring:broadcast\nos.execute('x')\n"])
    with pytest.raises(ValueError):
        lua.composite([lua.broadcast("a")], expect_hand=("Nobody", 5))
    with pytest.raises(TypeError):
        lua.composite([lua.broadcast("a")], expect_hand=("Blue", True))


def test_the_client_refuses_a_hand_made_composite():
    client = TTSClient(send_port=1, listen_port=0)
    with pytest.raises(Exception):
        client.call_lua("-- sparring:composite\nlocal results = {}\nos.execute('x')\n")


@pytest.mark.parametrize("status,states", [
    ('x" ..os.execute("y") .. "', {}), ("ok\nnewline", {}), ("a" * 200, {}),
    ("ok", {'btn" ] = 1 --': (True, True)}), ("ok", {"btn_end": (1, True)}), ("ok", {"btn_end": (True,)}),
    ("ok", {"": (True, True)}), ("ok", ["btn_end"]),
])
def test_set_panel_rejects_injection_and_bad_shapes(status, states):
    with pytest.raises((ValueError, TypeError)):
        lua.set_panel(status, states)


def test_set_panel_only_touches_the_own_panel_ui():
    s = lua.set_panel("Tu turno · 2 acciones", {"btn_end": (True, False)})
    assert lua.is_sendable(s) and "panel.UI.setAttribute" in s and "Global" not in s
    assert 'o.getGMNotes() == "sparring"' in s


@pytest.mark.parametrize("kw", [{"bot_seat": "Nobody"}, {"bot_zone": 'x") os.exit() --'}, {"pieces": ('a" b',)},
                               {"dials": ("ok", 5)}, {"exclude_radius": float("nan")}])
def test_snapshot_rejects_bad_arguments(bprd, kw):
    with pytest.raises((ValueError, TypeError)):
        lua.snapshot(dataclasses.replace(spec(bprd), **kw))


def test_snapshot_only_counts_the_human_hand(bprd):
    s = lua.snapshot_lua(spec(bprd))
    assert 'snap.human_count = #Player["Red"].getHandObjects(1)' in s and 'cardIds(Player["Red"]' not in s


# ---------- el panel ----------
def test_panel_script_locks_buttons_locally_and_sends_the_snapshot(bprd):
    script = ui.handler_script(lua.snapshot_lua(spec(bprd)), ui.element_ids(["medusa"]))
    assert 'UI.setValue("status", "Procesando...")' in script and "setAll(false)" in script
    assert "tbl.snapshot = JSON.encode(snap)" in script and "function sparringSnapshot" in script
    assert script.index("setAll(false)") < script.index("sendExternalMessage(tbl)")
    panel = lua.create_panel(["medusa"], snapshot=spec(bprd))
    assert "sparringSnapshot" in panel and lua.is_sendable(panel)
    assert not re.search(r"(?<![\w.])UI\.setXml", panel)


def test_panel_ids_cover_every_button_of_the_xml():
    xml = ui.panel_xml(["medusa", "harpy1"])
    assert set(re.findall(r'<Button [^>]*id="(\w+)"', xml)) == set(ui.element_ids(["medusa", "harpy1"]))
    assert 'id="status"' in xml and "TURNO" in xml and "VIDA" in xml and "PARTIDA" in xml
    assert 'rotation="0 0 270"' in xml


# ---------- los dos fallos de la partida 3 ----------
def test_a_face_up_card_next_to_the_human_deck_is_never_excluded_from_the_discard(bprd):
    s = lua.read_discard("abc", ["deck1"], [(-7.7, 12.5)], 1.5)
    assert "<= r2 and o.is_face_down" in s and '["deck1"]=true' in s
    assert "<= r2 and o.is_face_down" in lua.snapshot_lua(spec(bprd))


def test_a_transient_drop_of_a_discarded_card_never_lowers_the_destiny_counter(brig):
    session, table, game, fake = brig
    destiny = [c for c in game.players[1].full_set if c.destiny][:2]
    table.human_discard = [c.card_id for c in destiny]
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2 and table.dials["DD"]["value"] == 2
    table.human_discard = [destiny[0].card_id]                   # una lectura pierde una carta
    msgs = click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2 and table.dials["DD"]["value"] == 2
    assert not any("Destinos de Hellboy: 1" in m or "cambiado a mano" in m for m in msgs)
    table.human_discard = [c.card_id for c in destiny]           # vuelve
    msgs = click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 2 and not any("Destinos de Hellboy" in m for m in msgs)
    table.human_discard = [destiny[0].card_id]                   # y si sigue faltando en otro boton, ya es real
    click(session, table, Event.END_ACTION)
    click(session, table, Event.END_ACTION)
    assert game.destiny_count(1) == 1


def test_one_dial_changed_by_hand_does_not_block_the_others(brig):
    session, table, game, fake = brig
    click(session, table, Event.END_ACTION)
    table.dials["DD"]["value"] = 5                               # el humano toca el de destinos
    session.dials_written["DD"] = 0
    game.fighters["lobster"].hp = 3
    table.dial_writes.clear()
    click(session, table, Event.HP, {"fighter": "medusa", "delta": -1})
    assert table.dials["DM"]["value"] == 15 and table.dials["DL"]["value"] == 3
    assert table.dials["DD"]["value"] == 5, "el tocado no se pisa"
    assert not [w for w in table.dial_writes if w[0] == "DD"]
    assert session.dial_debt


# ---------- --timing y el bucle de eventos ----------
def test_timing_flag_and_per_button_cost_lines(brig):
    from sparring import play
    assert play.parse_args(["--timing"]).timing is True and play.parse_args([]).timing is False
    session, table, game, fake = brig
    lines = []
    session.timing = lines.append
    click(session, table, Event.MANEUVER)
    assert lines and lines[0].startswith("[tiempo] boton maneuver: 1 mensajes a TTS")
    label, calls, took = session.cost_log[-1]
    assert label == "boton maneuver" and calls == 1 and took >= 0


def test_client_counts_calls_and_traces_each_one(brig):
    session, table, game, fake = brig
    traced = []
    session.client.trace = traced.append
    before = session.client.calls
    click(session, table, Event.MANEUVER)
    assert session.client.calls == before + 1 and len(traced) == 1 and traced[0].endswith("composite")


def test_only_the_first_click_of_a_batch_keeps_its_snapshot():
    import threading
    from sparring import play

    class Spy:
        def __init__(self):
            self.seen = []

        def handle(self, event, payload):
            self.seen.append(dict(payload))
            return []

    class Client:
        def __init__(self):
            self.events = [[{"event": "maneuver", "snapshot": "{}"}, {"event": "end_action", "snapshot": "{}"}], []]
            self.reloads = 0

        def poll_events(self):
            return self.events.pop(0) if self.events else []

        def take_reload(self):
            return False
    stop, spy = threading.Event(), Spy()
    threading.Timer(0.3, stop.set).start()
    play.run_loop(spy, Client(), stop, lambda m: None, poll=0.01)
    assert spy.seen == [{"snapshot": "{}"}, {}]


def test_with_live_ui_the_announcements_travel_in_the_closing_composite_not_one_by_one(brig):
    session, table, game, fake = brig
    msgs = click(session, table, Event.MANEUVER)
    assert session.broadcast and table.broadcasts and table.sent.count("broadcast") == 0
    assert len(table.broadcasts) >= len(msgs)
