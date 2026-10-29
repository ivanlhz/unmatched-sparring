"""F16: mirar la mano del bot (Confront Any Demon or God y similares).

El bot pone su mano boca arriba en fila delante del humano y la lee en el chat; el humano hace ping (Tab) sobre la carta que
descarta (`onPlayerPing` en el script del panel) o gira una boca abajo y pulsa Fin de accion; Cancelar las devuelve.
Sesion contra FakeTTS (normal y SPARRING_BATCH=1) y Lua real con lupa para el handler de ping y los scripts de mesa."""
import json
import os

import pytest

from sparring import play
from sparring.persist import StateError
from sparring.session import SessionConfig
from sparring.tts import lua, ui
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_review9 import BOT_ID, conv, make_panel_runtime, rt, run  # noqa: F401
from test_session import rig, set_bot_hand  # noqa: F401

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

HAND = ("Snipe", "Dash", "Gaze of Stone", "Regroup", "A Momentary Glance")


def press(session, table, event, payload=None):
    """Un clic del panel: en modo rapido lleva la instantanea de la mesa."""
    return click(session, table, event, payload) if session.cfg.batch else session.handle(event, payload)


def start(session, table, game, *titles):
    session.grant_look()                      # the button is hidden and refused unless a card grants the look
    set_bot_hand(table, game, *(titles or HAND))
    session.read_bot_hand()
    session.snap = None
    return list(table.bot_hand)


def say(session):
    return [str(m) for m in session.messages]


# ---------- sesion ----------
def test_look_shows_the_whole_hand_in_a_row_and_reads_every_card(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    assert session.look is not None and session.look["ids"] == ids
    assert table.bot_hand == [] and table.look_row == ids
    text = "\n".join(say(session))
    for title, kind, extra in (("Snipe", "versatil", "valor 3, impulso 1"),
                               ("Gaze of Stone", "ataque", "deal 8 damage"),
                               ("A Momentary Glance", "esquema", "impulso 4")):
        assert title in text and kind in text and extra in text, (title, text)
    assert "valor None" not in text
    kinds = {m.kind for m in session.messages}
    assert lua.ChatKind.SCHEME in kinds and lua.ChatKind.YOUR_TURN in kinds
    assert game.actions_left == 2, "mirar no gasta accion"


def test_the_row_is_centred_on_the_configured_spot_and_does_not_leave_the_discard_rotation(rig):
    session, table, game = rig
    start(session, table, game)
    session.cfg.look_spot, session.cfg.look_step = (-20.0, 2.5, 4.0), (0.0, 3.0)
    press(session, table, Event.LOOK)
    zs = sorted(z for _, _, z in table.look_spots.values())
    assert zs == [-2.0, 1.0, 4.0, 7.0, 10.0]
    assert {x for x, _, _ in table.look_spots.values()} == {-20.0}
    script = next(s for s in table.scripts if s.startswith("-- sparring:show_hand_row"))
    assert f"Vector(0, {session.cfg.bot_discard_rot_y}, 0)" in script


def test_ping_discards_that_card_returns_the_rest_and_the_engine_counts_it(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    before_discard = len(game.players[0].discard)
    chosen = ids[2]
    known_before = game.players[0].known.cards(game.players[1])
    press(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    st = game.players[0]
    assert session.look is None
    assert table.bot_discard == [chosen] and sorted(table.bot_hand) == sorted(set(ids) - {chosen})
    assert [c.card_id for c in st.discard][before_discard:] == [chosen]
    assert chosen not in [c.card_id for c in st.hand] and len(st.hand) == 4
    assert chosen in session.bot_discarded
    assert any("descarta Gaze of Stone" in m for m in say(session))
    assert game.players[0].known.cards(game.players[1]) == known_before == []


def test_the_discard_goes_to_the_next_free_slot_of_the_discard_grid(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    slot = session._discard_slot(len(game.players[0].discard))
    press(session, table, Event.LOOK_PING, {"guid": f"g{ids[0]}"})
    assert table.resolve_args["spot"] == pytest.approx(slot)


def test_looking_never_reads_or_deals_with_the_human_hand(rig):
    session, table, game = rig
    ids = start(session, table, game)
    n, m = len(table.sent), len(table.scripts)
    press(session, table, Event.LOOK)
    press(session, table, Event.LOOK_PING, {"guid": f"g{ids[1]}"})
    assert not any("count_hand" in t for t in table.sent[n:]), table.sent[n:]
    human = [s for s in table.scripts[m:] if 'Player["Red"]' in s]
    assert human == [], [s.split(chr(10))[0] for s in human]


def test_flip_one_card_face_down_and_end_action_discards_it(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    table.look_down = {ids[3]}
    actions = game.actions_left
    press(session, table, Event.END_ACTION)
    assert session.look is None and table.bot_discard == [ids[3]] and len(table.bot_hand) == 4
    assert game.turn == 1 and game.actions_left == actions, "resolver la mirada no termina la accion"


@pytest.mark.parametrize("down", [set(), "two"])
def test_plan_b_with_zero_or_several_face_down_cards_changes_nothing(rig, down):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    table.look_down = set(ids[:2]) if down == "two" else set()
    press(session, table, Event.END_ACTION)
    assert session.look is not None and table.bot_discard == [] and sorted(table.look_row) == sorted(ids)
    assert any("boca abajo" in m for m in say(session))


def test_cancel_returns_everything_without_discarding(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    press(session, table, Event.CANCEL)
    assert session.look is None and table.look_row == [] and sorted(table.bot_hand) == sorted(ids)
    assert table.bot_discard == [] and len(game.players[0].hand) == 5 and game.players[0].discard == []
    assert any("devuelta" in m for m in say(session))


def test_ping_on_a_card_the_table_no_longer_has_rolls_the_discard_back(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    table.look_row.remove(ids[1])                    # el humano se la llevo de la fila
    press(session, table, Event.LOOK_PING, {"guid": f"g{ids[1]}"})
    assert session.look is not None and session.look["ids"] == ids and table.bot_discard == []
    assert len(game.players[0].hand) == 5 and game.players[0].discard == []
    assert any("sigue a la vista" in m for m in say(session))


def test_if_the_table_only_moves_some_cards_the_row_keeps_those(rig):
    session, table, game = rig
    ids = start(session, table, game)
    table.look_refuse = {ids[0], ids[4]}
    press(session, table, Event.LOOK)
    assert session.look["ids"] == ids[1:4] and sorted(table.bot_hand) == sorted([ids[0], ids[4]])
    assert len(game.players[0].hand) == 5 and any("Solo he podido sacar 3 de 5" in m for m in say(session))
    press(session, table, Event.CANCEL)
    assert sorted(table.bot_hand) == sorted(ids) and session.look is None


def test_if_the_table_moves_none_the_look_is_undone(rig):
    session, table, game = rig
    ids = start(session, table, game)
    table.look_refuse = set(ids)
    press(session, table, Event.LOOK)
    assert session.look is None and sorted(table.bot_hand) == sorted(ids) and len(game.players[0].hand) == 5
    assert any("No he podido sacar" in m for m in say(session))


def test_cancel_with_the_whole_row_gone_adopts_the_table_instead_of_trapping_the_session(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    table.look_row.clear()                           # apiladas en un Deck, borradas...
    press(session, table, Event.CANCEL)
    assert session.look is None and session.dirty
    assert any("a mano" in m for m in say(session))
    press(session, table, Event.MANEUVER)
    assert game.actions_left == 1, "los botones vuelven a funcionar"
    assert len(game.players[0].hand) + len(game.players[0].deck) + len(game.players[0].discard) == 30


def test_ping_when_the_whole_row_is_gone_also_exits(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    table.look_row.clear()
    press(session, table, Event.LOOK_PING, {"guid": f"g{ids[0]}"})
    assert session.look is None and game.players[0].discard == []


def test_a_second_cancel_forces_the_exit_when_the_table_keeps_failing(rig, monkeypatch):
    session, table, game = rig
    start(session, table, game)
    press(session, table, Event.LOOK)
    real = table.do_resolve_hand_row
    monkeypatch.setattr(table, "do_resolve_hand_row", lambda s: {"__error__": "TTS roto"})
    press(session, table, Event.CANCEL)
    assert session.look is not None and session.look_fails == 1
    press(session, table, Event.CANCEL)
    assert session.look is None and session.look_fails == 0


def test_a_failed_ping_does_not_make_the_first_cancel_force_the_exit(rig, monkeypatch):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK)
    real = table.do_resolve_hand_row
    monkeypatch.setattr(table, "do_resolve_hand_row", lambda s: {"__error__": "TTS roto"})
    press(session, table, Event.LOOK_PING, {"guid": f"g{ids[0]}"})
    assert session.look is not None and session.look_fails == 0
    monkeypatch.setattr(table, "do_resolve_hand_row", real)
    press(session, table, Event.CANCEL)
    assert session.look is None and sorted(table.bot_hand) == sorted(ids) and table.look_row == []


def test_the_failure_counter_survives_neither_a_new_row_nor_a_restart(rig, monkeypatch):
    session, table, game = rig
    start(session, table, game)
    press(session, table, Event.LOOK)
    real = table.do_resolve_hand_row
    monkeypatch.setattr(table, "do_resolve_hand_row", lambda s: {"__error__": "TTS roto"})
    press(session, table, Event.CANCEL)
    assert session.look_fails == 1
    monkeypatch.setattr(table, "do_resolve_hand_row", real)
    press(session, table, Event.RESTART)
    press(session, table, Event.RESTART)
    assert session.look is None and session.look_fails == 0
    session.look_fails = 1                            # un resto anterior no pasa a la fila nueva
    session.setup = None
    set_bot_hand(table, game, *HAND)
    session.read_bot_hand()
    session.grant_look()                              # the first look used up the grant; the restart cleared it too
    press(session, table, Event.LOOK)
    assert session.look is not None and session.look_fails == 0
    press(session, table, Event.CANCEL)
    assert session.look is None and table.look_row == [] and len(table.bot_hand) == 5


def test_restart_is_allowed_with_the_row_out_and_clears_it(rig):
    session, table, game = rig
    start(session, table, game)
    press(session, table, Event.LOOK)
    assert session.panel_view()[1]["btn_restart"][0] is True
    press(session, table, Event.RESTART)
    press(session, table, Event.RESTART)
    assert session.look is None and table.look_row == []


def test_while_looking_other_buttons_are_refused(rig):
    session, table, game = rig
    start(session, table, game)
    press(session, table, Event.LOOK)
    for event in (Event.MANEUVER, Event.SCHEME, Event.REVEAL, Event.LOOK):
        press(session, table, event)
        assert session.look is not None and any("a la vista" in m for m in say(session)), event
    assert game.actions_left == 2


def test_a_ping_on_something_that_is_not_in_the_row_or_without_a_row_is_ignored(rig):
    session, table, game = rig
    ids = start(session, table, game)
    press(session, table, Event.LOOK_PING, {"guid": f"g{ids[0]}"})
    assert any("No hay cartas" in m for m in say(session)) and table.bot_discard == []
    press(session, table, Event.LOOK)
    press(session, table, Event.LOOK_PING, {"guid": "zzzzzz"})
    assert session.look is not None and table.bot_discard == [] and any("ping no era" in m for m in say(session))


def test_the_look_button_follows_the_state(rig):
    session, table, game = rig
    start(session, table, game)
    assert session.panel_view()[1]["btn_look"] == (True, True)
    game.players[0].hand.clear()
    assert session.panel_view()[1]["btn_look"][0] is False
    session.read_bot_hand()
    assert session.panel_view()[1]["btn_look"][0] is True
    game.turn = 0
    assert session.panel_view()[1]["btn_look"][0] is False
    press(session, table, Event.LOOK)
    assert any("tu turno" in m for m in say(session)) and session.look is None
    game.turn = 1
    press(session, table, Event.LOOK)
    states = session.panel_view()
    assert states[1]["btn_look"][0] is False and states[1]["btn_cancel"][0] is True
    assert states[1]["btn_end"][0] is True and states[1]["btn_maneuver"][0] is False
    assert "Tab" in states[0]


def test_it_can_be_used_during_a_combat_the_human_effect_allows(rig):
    session, table, game = rig
    ids = start(session, table, game)
    from sparring.session import Pending
    held = game.players[0].hand[0]
    session.pending = Pending("human_attacks", game.fighters["hellboy"], game.fighters["medusa"], held, f"g{held.card_id}")
    table.bot_hand.remove(held.card_id)
    table.bot_play.append(held.card_id)
    session.read_bot_hand()
    assert session.panel_view()[1]["btn_look"][0] is True
    press(session, table, Event.LOOK)
    assert session.look["ids"] == [i for i in ids if i != held.card_id] and held in game.players[0].hand
    press(session, table, Event.CANCEL)
    assert session.look is None and session.pending is not None, "Cancelar solo cierra la mirada, no el combate"
    assert held in game.players[0].hand


def test_pending_look_survives_the_save_and_resume_restores_the_panel_row(rig):
    session, table, game = rig
    start(session, table, game)
    press(session, table, Event.LOOK)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["look"]["ids"] == session.look["ids"]
    row = dict(session.look)
    session.look = None
    session.load_dict(saved)
    assert session.look == row
    session.resume()
    assert table.look_vars and all(g in table.look_vars[-1] for g in row["guids"])
    assert any("sigue a la vista" in m for m in say(session))
    assert len(game.players[0].hand) == 5, "la mano del motor incluye las cartas de la fila"


@pytest.mark.parametrize("bad", [{"ids": [1], "guids": ["a1"], "spots": [[0, 0, 0]]}, {"ids": [1, 2], "guids": ["a"], "spots": []},
                                 {"ids": ["x"], "guids": ["a1"], "spots": [[0, 0]]}, [], {"ids": [], "guids": [], "spots": []},
                                 {"ids": [1], "guids": ["a;b"], "spots": [[0, 0]]}])
def test_a_corrupt_pending_look_is_refused_when_loading(rig, bad):
    session, table, game = rig
    saved = session.to_dict()
    saved["look"] = bad
    with pytest.raises(StateError):
        session.load_dict(saved)


def test_without_a_look_the_save_just_says_none(rig):
    session, table, game = rig
    assert session.to_dict()["look"] is None
    session.load_dict(session.to_dict())
    assert session.look is None


# ---------- mensajes a TTS ----------
def test_show_and_ping_cost_one_message_each_in_batch_mode(brig):  # noqa: F811
    session, table, game, fake = brig
    ids = start(session, table, game)
    n = fake.lua_messages
    click(session, table, Event.LOOK)
    assert fake.lua_messages - n == 1 and table.sent[-1] == "composite"
    assert sum(m.count("show_hand_row") for m in table.msglog) == 1
    n = fake.lua_messages
    click(session, table, Event.LOOK_PING, {"guid": f"g{ids[0]}"})
    assert fake.lua_messages - n == 1 and table.sent[-1] == "composite"
    assert sum(m.count("resolve_hand_row") for m in table.msglog) == 1
    assert session.look is None and table.bot_discard == [ids[0]]


def test_cancel_costs_one_message_in_batch_mode(brig):  # noqa: F811
    session, table, game, fake = brig
    start(session, table, game)
    click(session, table, Event.LOOK)
    n = fake.lua_messages
    click(session, table, Event.CANCEL)
    assert fake.lua_messages - n == 1


def test_batch_row_and_the_announcements_travel_in_the_same_composite(brig):  # noqa: F811
    session, table, game, fake = brig
    start(session, table, game)
    click(session, table, Event.LOOK)
    ops = table.msglog[-1]
    assert ops[0] == "show_hand_row" and "set_panel" in ops and ops.count("broadcast") >= 6


# ---------- el panel ----------
def test_the_panel_has_the_look_button_and_the_ping_handler():
    xml = ui.panel_xml(["medusa"])
    assert 'id="btn_look" onClick="onLook">Mirar mano del bot<' in xml
    script = ui.handler_script(None, ui.element_ids(["medusa"]), "White")
    assert "function onLook()" in script and "function onPlayerPing(player, position, object)" in script
    assert 'HUMAN_SEAT = "White"' in script and "btn_look" in script
    assert 'HUMAN_SEAT = nil' in ui.handler_script()
    with pytest.raises(ValueError):
        ui.handler_script(None, [], 'White"; os.exit() --')
    lua54.LuaRuntime().execute("return function() " + script + "\nend")


def test_create_panel_takes_the_human_seat_from_the_snapshot_spec_or_the_argument(brig):  # noqa: F811
    session, table, game, fake = brig
    assert 'HUMAN_SEAT = "Red"' in lua.create_panel(["medusa"], snapshot=session.snapshot_spec())
    assert 'HUMAN_SEAT = "Blue"' in lua.create_panel(["medusa"], human_seat="Blue")
    assert "HUMAN_SEAT = nil" in lua.create_panel(["medusa"])


# ---------- Lua real con lupa: el ping ----------
ROW = "g1|-23.0|-2.6,g2|-23.0|0.0,g3|-23.0|2.6"


def ping_runtime(row=ROW):
    runtime = make_panel_runtime()
    runtime.execute(ui.handler_script(None, ["btn_end"], "White"))
    runtime.globals().lookRow = row
    runtime.execute("mkobj({guid = 'g2', type = 'Card'}) mkobj({guid = 'far', type = 'Figurine'})")
    return runtime


def ping(runtime, color="White", pos=(-23.0, 1.0, 0.0), obj=None):
    g = runtime.globals()
    g.busy = False
    sent = len(g.SENT)
    g.onPlayerPing(runtime.table_from({"color": color}), runtime.table_from({"x": pos[0], "y": pos[1], "z": pos[2]}),
                   g.getObjectFromGUID(obj) if obj else None)
    return [conv(g.SENT[i]) for i in range(sent + 1, len(g.SENT) + 1)]


def test_a_ping_on_a_row_card_object_sends_the_look_ping_event():
    rt = ping_runtime()
    assert ping(rt, obj="g2", pos=(0.0, 1.0, 50.0)) == [{"event": "look_ping", "guid": "g2"}]


def test_without_the_object_the_nearest_row_card_to_the_position_is_used():
    rt = ping_runtime()
    assert ping(rt, pos=(-23.2, 1.0, -2.3)) == [{"event": "look_ping", "guid": "g1"}]
    assert ping(rt, pos=(-22.9, 1.0, 2.9)) == [{"event": "look_ping", "guid": "g3"}]


def test_pings_that_are_not_for_a_row_card_do_nothing():
    rt = ping_runtime()
    assert ping(rt, color="Blue", obj="g2") == [], "otro asiento"
    assert ping(rt, pos=(5.0, 1.0, 5.0), obj="far") == [], "una pieza lejos de la fila"
    assert ping(rt, pos=(-23.0, 1.0, 8.0)) == [], "a mas de 1.6 de cualquier carta"
    rt.globals().lookRow = ""
    assert ping(rt, obj="g2") == [], "sin fila a la vista"
    nobody = make_panel_runtime()
    nobody.execute(ui.handler_script(None, ["btn_end"]))
    nobody.globals().lookRow = ROW
    nobody.execute("mkobj({guid = 'g2', type = 'Card'})")
    assert ping(nobody, obj="g2") == [], "sin asiento humano configurado no reconoce ninguno"


def test_a_ping_while_the_panel_is_busy_is_ignored():
    rt = ping_runtime()
    g = rt.globals()
    g.onManeuver()
    n = len(g.SENT)
    g.onPlayerPing(rt.table_from({"color": "White"}), rt.table_from({"x": -23.0, "y": 1.0, "z": 0.0}), g.getObjectFromGUID("g2"))
    assert len(g.SENT) == n


def test_the_ping_carries_the_snapshot_of_the_click_in_batch_mode(brig):  # noqa: F811
    session, table, game, fake = brig
    script = ui.handler_script(lua.snapshot_lua(session.snapshot_spec(), "wseq"), ["btn_end"], "Red")
    assert script.index("function onPlayerPing") > script.index("sparringSnapshot")
    assert "send({event = \"look_ping\", guid = hit})" in script and "pcall(sparringSnapshot)" in script


# ---------- Lua real con lupa: la mesa ----------
SEAT_LOOK = lua.Scope(("Green", "White"), ("906a7a", "b7a0b8"), ((6.0, -18.0), (-2.0, -18.0), (11.5, 12.0)))


def hand_table(rt):
    rt.execute("""
mkobj({guid = 'pnl', type = 'BlockSquare', name = 'SparringPanel', gm = 'sparring'})
for i = 0, 3 do mkobj({guid = 'c' .. i, type = 'Card', cid = 17600 + i, owner = 'medusa', hand = 'Green'}) end
mkobj({guid = 'alien', type = 'Card', cid = 17604, owner = 'alice', hand = 'Green'})
mkobj({guid = 'other', type = 'Card', cid = 17605, owner = 'medusa', pos = {x = 3, y = 1, z = 3}})
""")


def card(rt, guid):
    return rt.globals().getObjectFromGUID(guid)


def panel_row(rt):
    return conv(card(rt, "pnl").vars)["lookRow"]


def show(rt, ids=(17600, 17601, 17602, 17603, 17604)):
    spots = [(-23.0, 2.5, -5.2 + 2.6 * i) for i in range(len(ids))]
    return run(rt, lua.show_hand_row(list(ids), spots, 90.0, "Green", identity=BOT_ID))


def test_show_moves_only_our_cards_from_the_hand_face_up_and_notes_the_row_in_the_panel(rt):
    hand_table(rt)
    res = show(rt)
    assert [e["id"] for e in res["shown"]] == [17600, 17601, 17602, 17603]       # la ajena (alice) no se toca
    assert card(rt, "alien").moved_count is None and card(rt, "other").moved_count is None
    assert card(rt, "c2").pos.x == -23.0 and card(rt, "c2").pos.z == pytest.approx(0.0)
    assert card(rt, "c0").rot.z == 0 and card(rt, "c0").rot.y == 90.0
    entries = [e.split("|") for e in panel_row(rt).split(",")]
    assert [e[0] for e in entries] == ["c0", "c1", "c2", "c3"] and float(entries[0][2]) == pytest.approx(-5.2)


def test_discard_by_guid_puts_that_card_on_the_pile_and_hands_back_the_rest_and_clears_the_row(rt):
    hand_table(rt)
    show(rt)
    res = run(rt, lua.resolve_hand_row(["c0", "c1", "c2", "c3", "alien"], "Green", identity=BOT_ID, discard="c1",
                                       spot=(15.0, 2.0, -14.0), rot_y=90.0))
    assert res["discarded"] == 17601 and sorted(res["returned"]) == [17600, 17602, 17603] and res["found"] == 4
    assert (card(rt, "c1").pos.x, card(rt, "c1").pos.z) == (15.0, -14.0)
    assert card(rt, "c0").pos.x == 0 and card(rt, "c3").pos.x == 0, "el resto vuelve a la posicion de su mano"
    assert card(rt, "alien").moved_count is None, "una carta ajena en la lista no se mueve"
    assert panel_row(rt) == ""


def test_face_down_mode_discards_only_the_single_face_down_card(rt):
    hand_table(rt)
    show(rt)
    args = dict(identity=BOT_ID, face_down=True, spot=(15.0, 2.0, -14.0), rot_y=90.0)
    row = ["c0", "c1", "c2", "c3"]
    none = run(rt, lua.resolve_hand_row(row, "Green", **args))
    assert none["discarded"] is False and none["down"] == 0 and card(rt, "c0").pos.x == -23.0
    card(rt, "c0").is_face_down = True
    card(rt, "c3").is_face_down = True
    two = run(rt, lua.resolve_hand_row(row, "Green", **args))
    assert two["discarded"] is False and two["down"] == 2 and card(rt, "c3").pos.x == -23.0
    card(rt, "c0").is_face_down = False
    one = run(rt, lua.resolve_hand_row(row, "Green", **args))
    assert one["discarded"] == 17603 and sorted(one["returned"]) == [17600, 17601, 17602]
    assert (card(rt, "c3").pos.x, card(rt, "c3").pos.z) == (15.0, -14.0)


def test_cancel_brings_all_back_and_a_missing_or_unknown_pick_moves_nothing(rt):
    hand_table(rt)
    show(rt)
    row = ["c0", "c1", "c2", "c3"]
    miss = run(rt, lua.resolve_hand_row(row, "Green", identity=BOT_ID, discard="nope99"))
    assert miss["discarded"] is False and card(rt, "c0").pos.x == -23.0 and panel_row(rt) != ""
    res = run(rt, lua.resolve_hand_row(row, "Green", identity=BOT_ID))
    assert res["discarded"] is False and sorted(res["returned"]) == [17600, 17601, 17602, 17603]
    assert all(card(rt, g).pos.x == 0 for g in row) and panel_row(rt) == ""


def test_set_look_row_writes_the_panel_variable(rt):
    hand_table(rt)
    run(rt, lua.set_look_row([("c0", -23.0, -2.6), ("c1", -23.0, 0.0)]))
    assert panel_row(rt) == "c0|-23.0|-2.6,c1|-23.0|0.0"
    run(rt, lua.set_look_row([]))
    assert panel_row(rt) == ""


def test_look_scripts_reject_what_is_not_valid_lua_input():
    ident = dict(identity=BOT_ID)
    for bad in (lambda: lua.show_hand_row([], [], 0, "Green", **ident),
                lambda: lua.show_hand_row([1], [(0, 0)], 0, "Green", **ident),
                lambda: lua.show_hand_row([1], [(0, 0, 0)], 0, "Nobody", **ident),
                lambda: lua.show_hand_row([1] * 13, [(0, 0, 0)] * 13, 0, "Green", **ident),
                lambda: lua.resolve_hand_row([], "Green", **ident),
                lambda: lua.resolve_hand_row(['a"b'], "Green", **ident),
                lambda: lua.resolve_hand_row(["a1"], "Green", discard='x"); os.exit() --', **ident),
                lambda: lua.resolve_hand_row(["a1"], "Green", discard="a1", face_down=True, **ident),
                lambda: lua.set_look_row([('a"b', 0.0, 0.0)]),
                lambda: lua.set_look_row([("a1", float("nan"), 0.0)])):
        with pytest.raises((ValueError, TypeError)):
            bad()
    for tag in (lua.show_hand_row([1], [(0, 0, 0)], 0, "Green", **ident),
                lua.resolve_hand_row(["a1"], "Green", **ident), lua.set_look_row([])):
        assert lua.is_sendable(tag) and "UI." not in tag and "Global" not in tag


# ---------- configuracion ----------
def test_the_real_config_row_does_not_overlap_the_panel_or_the_floor_boxes():
    cfg = play.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "partida.json"))
    assert play.look_row_warnings(cfg, play.floor_layout(cfg)) == []
    assert play.floor_layout_warnings(cfg) == []


def test_a_row_that_would_cover_the_combat_boxes_or_the_panel_is_warned_about():
    cfg = play.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "partida.json"))
    cfg.raw["look_spot"] = [6.0, 2.5, -18.0]
    assert any("pisa caja de combate" in w for w in play.floor_layout_warnings(cfg))
    cfg.raw["look_spot"] = [cfg.panel_position[0], 2.5, cfg.panel_position[2]]
    assert any("pisa el panel" in w for w in play.floor_layout_warnings(cfg))


def test_look_keys_reach_the_session_config():
    cfg = play.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "partida.json"))
    scfg = cfg.session_config()
    assert scfg.look_spot == (-23.0, 2.5, 0.0) and scfg.look_step == (0.0, 2.6) and scfg.look_rot_y is None
    cfg.raw.update({"look_spot": [1, 2, 3], "look_step": [0.5, 0.0], "look_rot_y": 180})
    scfg = cfg.session_config()
    assert (scfg.look_spot, scfg.look_step, scfg.look_rot_y) == ((1.0, 2.0, 3.0), (0.5, 0.0), 180.0)
    cfg.raw["look_spot"] = [1, 2]
    with pytest.raises(play.ConfigError):
        cfg.session_config()
    assert SessionConfig.look_step == (0.0, 2.6)


def test_default_unpack_columns_do_not_cross_the_look_row():
    cfg = play.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "partida.json"))
    x0, x1, z0, z1 = play.look_row_rect(cfg, 7)
    for side, (x, _, z) in play.UNPACK_SPOTS.items():
        for n in range(8):
            zz = z + n * play.UNPACK_STEP[2]
            assert not (x0 - 1 < x < x1 + 1 and z0 - 1 < zz < z1 + 1), (side, n)
