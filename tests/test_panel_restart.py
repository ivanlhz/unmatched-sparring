"""New panel (status, buttons turned off by state), restart, the human's casualties and floor labels."""
from conftest import t_reset_deck
import dataclasses
import json
import re

import pytest

from sparring.tts import lua, ui
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401  (brig is a fixture)
from test_session import card, human_plays, set_bot_hand

PLAY_CONFIG = json.loads(open(__file__.replace("tests\\test_panel_restart.py", "config\\table.json")
                              .replace("tests/test_panel_restart.py", "config/table.json"), encoding="utf-8").read())


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def with_cfg(session, **kw):
    session.cfg = dataclasses.replace(session.cfg, **kw)


# ---------- status line and buttons by state ----------
def test_status_line_says_what_the_bot_expects(brig):
    session, table, game, fake = brig
    status, _ = session.panel_view()
    assert status == "Tu turno · 2 acciones · esperando tu accion"
    click(session, table, Event.MANEUVER)
    assert table.panels[-1][0] == "Tu turno · 1 accion · esperando Fin de accion"
    click(session, table, Event.END_ACTION)
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    assert table.panels[-1][0] == "Tu turno · 1 accion · esperando elegir objetivo"
    click(session, table, Event.ATTACK, {"target": "medusa"})
    assert table.panels[-1][0] == "Tu turno · 1 accion · esperando Revelar"


def test_buttons_that_cannot_be_used_are_greyed_out(brig):
    session, table, game, fake = brig
    _, st = session.panel_view()
    assert st["btn_reveal"] == (False, True) and st["btn_cancel"] == (False, True)
    assert st["medusa"][0] is False, "with no chosen attacker there are no targets"
    assert st["btn_maneuver"] == (True, True) and st["att_hellboy"] == (True, True)
    assert st["btn_undo"] == (False, False)
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    _, st = session.panel_view()
    game.fighters["hellboy"].pos = max(game.board.spaces)
    _, st = session.panel_view()
    assert st["medusa"] == (False, True), "Medusa is far from Hellboy: out of range"
    assert st["btn_cancel"] == (True, True)
    game.fighters["hellboy"].pos = min(game.board.adj[game.fighters["medusa"].pos])
    _, st = session.panel_view()
    assert st["medusa"] == (True, True), "in range"
    table.positions["Hellboy"] = game.fighters["hellboy"].pos
    click(session, table, Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None
    _, st = session.panel_view()
    assert st["btn_reveal"] == (True, True) and st["btn_maneuver"][0] is False


def test_dead_fighters_have_their_hp_and_remove_buttons_greyed_and_endgame_enables_undo(brig):
    session, table, game, fake = brig
    click(session, table, Event.REMOVE, {"fighter": "harpy1"})
    _, st = session.panel_view()
    assert st["hpm_harpy1"][0] is False and st["rm_harpy1"][0] is False and st["hpp_harpy1"][0] is True
    for fid in ("medusa",):
        click(session, table, Event.REMOVE, {"fighter": fid})
    assert game.winner is not None
    status, st = session.panel_view()
    assert status.startswith("Fin de partida") and st["btn_undo"] == (True, True)
    assert st["btn_maneuver"][0] is False and st["btn_end"][0] is False


def test_setup_buttons_are_visible_only_in_setup_and_restart_only_in_game(brig):
    session, table, game, fake = brig
    with_cfg(session, setup=True)
    session.setup = {"stage": "wait_human", "mull_done": True, "mull_decision": False, "mull_step": "start",
                     "human_mull": False}
    status, st = session.panel_view()
    assert st["btn_ready"] == (True, True) and st["btn_mulligan"] == (True, True) and st["btn_restart"][1] is False
    assert "Listo" in status and st["btn_maneuver"][0] is False
    session.setup["human_mull"] = True
    assert session.panel_view()[1]["btn_mulligan"][0] is False
    session.setup = None
    _, st = session.panel_view()
    assert st["btn_ready"][1] is False and st["btn_mulligan"][1] is False and st["btn_restart"] == (True, True)


def test_the_panel_reply_re_enables_the_buttons_and_releases_the_local_lock(brig):
    session, table, game, fake = brig
    click(session, table, Event.MANEUVER)
    assert fake.lua_messages >= 1 and table.sent[-1] == "composite" and len(table.panels) == 1
    s = lua.set_panel("Tu turno", {"btn_end": (True, True)})
    assert 'panel.setVar("busy", false)' in s


# ---------- restart game ----------
def prepared(brig, tmp_path):
    session, table, game, fake = brig
    clock = Clock()
    session.clock = clock
    with_cfg(session, dead_spot=(24.0, 2.5, -20.0), setup=False)
    session.state_path = tmp_path / "session.json"
    return session, table, game, clock


def test_one_press_only_arms_the_restart_and_changes_nothing(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    click(session, table, Event.MANEUVER)
    old_id, turn_no = session.game_id, game.turn_no
    n = len(table.sent)
    msgs = click(session, table, Event.RESTART)
    assert any("otra vez en 3 segundos" in m for m in msgs) and session.restart_armed()
    assert "confirmar" in table.panels[-1][0]
    assert session.game_id == old_id and session.game is game and not table.dial_writes[1:]
    assert not any(t.startswith(("-- sparring:reset_deck", "-- sparring:place_piece")) for t in table.scripts)
    assert game.turn_no == turn_no and len(table.sent) == n + 1 and (tmp_path / "session.json").exists()


def test_a_press_after_three_seconds_arms_again_instead_of_restarting(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    click(session, table, Event.RESTART)
    clock.now += 3.5
    assert not session.restart_armed()
    click(session, table, Event.RESTART)
    assert session.game is game and session.restart_armed()


def test_another_button_between_the_two_presses_disarms_it(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    click(session, table, Event.RESTART)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.RESTART)
    assert session.game is game


def test_double_press_restarts_everything_in_one_message_and_goes_back_to_the_draw(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    with_cfg(session, human_deck_guid="HDECK", human_deck_spot=(-4.6, 13.67), setup=True)
    session._snap_spec = None
    click(session, table, Event.MANEUVER)
    game.damage(game.fighters["medusa"], 4, "manual")
    table.dials["DM"]["value"], table.dials["DD"]["value"] = 12, 3
    table.human_discard = [card(game, 1, "Excalibur").card_id]
    table.bot_discard = [card(game, 0, "Dash").card_id]
    table.bot_hand.remove(card(game, 0, "Dash").card_id)
    table.face_down = [{"id": card(game, 1, "Service Pistol").card_id, "guid": "hx"}]
    table.human_count = 4
    old_id = session.game_id
    click(session, table, Event.RESTART)
    n = brig[3].lua_messages
    msgs = click(session, table, Event.RESTART)
    assert session.game is not game and session.game_id != old_id
    assert table.resets == ["bot", "human"]
    assert table.human_discard == [] and table.face_down == [] and table.human_count == session.game.start_hand(1), "the bot deals the new opening hand"
    assert table.bot_discard == [] and len(table.bot_hand) + len(table.bot_deck) + len(table.bot_play) == 30
    assert table.dials["DM"]["value"] == 16 and table.dials["DH"]["value"] == 18 and table.dials["DD"]["value"] == 0
    assert any("Partida reiniciada" in m for m in msgs)
    assert session.setup is not None and session.setup["stage"] in ("wait_human_first", "wait_human", "hand")
    assert json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))["fingerprint"]["game_id"] == session.game_id
    assert brig[3].lua_messages - n <= 7, "restarting does not cost dozens of messages (6 + the human's opening deal, which needs the seat read first)"


def test_restart_moves_every_piece_off_the_board_to_the_two_dead_spots(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    click(session, table, Event.RESTART)
    click(session, table, Event.RESTART)
    placed = {name: (x, z) for name, x, y, z in table.placed}
    assert set(placed) == set(session.cfg.nicknames.values())
    assert all(placed[n][0] > 20 for n in ("Medusa", "Harpy 1", "Harpy 2", "Harpy 3"))
    assert all(placed[n][0] < -20 for n in ("Hellboy", "Lobster Johnson"))
    assert len({v for v in placed.values()}) == 6, "each piece in its slot"


def test_a_failed_restart_leaves_the_engine_untouched_and_can_be_repeated(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    with_cfg(session, human_deck_guid="HDECK", human_deck_spot=(-4.6, 13.67))
    table.dials["DM"]["value"] = 10
    table.dial_ignores_writes = True
    click(session, table, Event.RESTART)
    msgs = click(session, table, Event.RESTART)
    assert session.game is game and any("no ha dejado la mesa limpia" in m for m in msgs)
    table.dial_ignores_writes = False
    click(session, table, Event.RESTART)
    clock.now += 0.1
    click(session, table, Event.RESTART)
    assert session.game is not game


def test_restart_needs_a_dead_spot(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    with_cfg(session, dead_spot=None)
    click(session, table, Event.RESTART)
    msgs = click(session, table, Event.RESTART)
    assert session.game is game and any("dead_spot" in m for m in msgs)


def test_restart_event_and_handler_exist():
    assert ui.Event("restart") is Event.RESTART and ui.parse_event({"event": "restart"}) == (Event.RESTART, {})
    assert "function onRestart" in ui.handler_script() and 'onClick="onRestart">Reiniciar partida<' in ui.panel_xml(["medusa"])


@pytest.mark.parametrize("kw", [{"id_range": (1,)}, {"id_range": ("a", 2)}, {"deck_guid": 'x") os.exit() --'},
                               {"spot": (1.0,)}, {"radius": float("inf")}])
def test_reset_deck_rejects_bad_arguments(kw):
    args = {"deck_guid": "abc", "spot": (1.0, 2.0), "id_range": lua.BOT_CARD_IDS, "radius": 2.0, **kw}
    with pytest.raises((ValueError, TypeError)):
        t_reset_deck(**args)


def test_reset_deck_is_registered_composable_and_only_takes_its_own_side():
    s = t_reset_deck("abc", (1.0, 2.0), lua.HUMAN_CARD_IDS)
    assert lua.is_sendable(s) and "id < 19700 or id > 19729" in s and "held_by_color" in s
    assert "shuffle()" in s and "Global" not in s
    assert lua.is_sendable(lua.composite([s, lua.set_health_dials({"abc": 3})]))


# ---------- the human's casualties ----------
def test_a_dead_human_fighter_is_moved_off_the_board_and_announced(brig):
    session, table, game, fake = brig
    with_cfg(session, dead_spot=(24.0, 2.5, -20.0))
    msgs = click(session, table, Event.REMOVE, {"fighter": "lobster"})
    assert "Lobster Johnson cae: lo he apartado." in msgs
    assert table.placed == [("Lobster Johnson", -25.5, 2.5, -20.0)]
    assert table.piece_dist["Lobster Johnson"] > session.cfg.off_board_dist


def test_a_dead_human_fighter_goes_to_the_configured_human_dead_spot(brig):
    session, table, game, fake = brig
    with_cfg(session, dead_spot=(24.0, 2.5, -20.0), human_dead_spot=(-30.0, 3.0, 10.0))
    click(session, table, Event.REMOVE, {"fighter": "hellboy"})
    assert table.placed == [("Hellboy", -30.0, 3.0, 10.0)]


def test_without_any_dead_spot_the_human_is_asked_to_remove_the_miniature(brig):
    session, table, game, fake = brig
    msgs = click(session, table, Event.REMOVE, {"fighter": "lobster"})
    assert any("(tuyo) cae: retira su miniatura" in m for m in msgs) and table.placed == []


def test_a_piece_that_does_not_move_is_reported(brig):
    session, table, game, fake = brig
    with_cfg(session, dead_spot=(24.0, 2.5, -20.0))
    table.move_fails.add("pclobster")
    msgs = click(session, table, Event.REMOVE, {"fighter": "lobster"})
    assert any("Lobster Johnson (tuyo) cae: retira su miniatura" in m for m in msgs)


def test_a_dead_fighter_cannot_be_chosen_as_attacker_and_the_message_says_why(brig):
    session, table, game, fake = brig
    click(session, table, Event.REMOVE, {"fighter": "lobster"})
    msgs = click(session, table, Event.ATTACKER, {"attacker": "att_lobster"})
    assert "Lobster Johnson esta muerto: no puede atacar." in msgs and session.chosen_attacker is None
    msgs = click(session, table, Event.ATTACKER, {"attacker": "medusa"})
    assert any("no valido" in m for m in msgs)


# ---------- floor labels ----------
CARD_W, CARD_D = lua.CARD_SIZE


def boxes():
    """(label, cx, cz, width, depth, rotY) of the boxes of the real game."""
    b = PLAY_CONFIG["bot_discard_bounds"]
    out = [("DESCARTE MEDUSA", b[0], b[1], b[2], b[3], b[4]),
           ("DESCARTE HELLBOY", -12.5, 0.7, 8.55, 35.43, 90.0),         # zone b7a0b8 (center -12.5, 0.7)
           ("HELLBOY", *PLAY_CONFIG["human_card_spot"], CARD_W, CARD_D, 0.0),
           ("MEDUSA", PLAY_CONFIG["bot_card_spot"][0], PLAY_CONFIG["bot_card_spot"][2], CARD_W, CARD_D, 0.0)]
    return [(t, cx, cz, w, d, r) for t, cx, cz, w, d, r in out]


def rect(x, z, ext_x, ext_z):
    return (x - ext_x / 2, x + ext_x / 2, z - ext_z / 2, z + ext_z / 2)


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


def aabb(cx, cz, w, d, rot):
    import math
    t = math.radians(rot)
    hx = abs(math.cos(t)) * w / 2 + abs(math.sin(t)) * d / 2
    hz = abs(math.sin(t)) * w / 2 + abs(math.cos(t)) * d / 2
    return (cx - hx, cx + hx, cz - hz, cz + hz)


def test_floor_labels_sit_outside_their_box_facing_white_and_never_overlap():
    labels = {}
    for text, cx, cz, w, d, rot in boxes():
        x, z, ext_x, ext_z = lua.label_position(cx, cz, w, d, rot, text)
        box = aabb(cx, cz, w, d, rot)
        r = rect(x, z, ext_x, ext_z)
        assert not overlap(r, box), f"{text} overlaps its own box"
        assert r[1] <= box[0], f"{text} is not on the edge facing White (-x)"
        labels[text] = r
    items = list(labels.items())
    for i, (ta, ra) in enumerate(items):
        for tb, rb in items[i + 1:]:
            assert not overlap(ra, rb), f"{ta} y {tb} se solapan"
        for text, cx, cz, w, d, rot in boxes():
            if text != ta:
                assert not overlap(ra, aabb(cx, cz, w, d, rot)), f"{ta} pisa la caja de {text}"


def test_the_two_combat_labels_do_not_overlap_across_the_gap():
    (hx, hz, hex_, hez), (mx, mz, mex, mez) = (
        lua.label_position(PLAY_CONFIG["human_card_spot"][0], PLAY_CONFIG["human_card_spot"][1], CARD_W, CARD_D, 0, "HELLBOY"),
        lua.label_position(PLAY_CONFIG["bot_card_spot"][0], PLAY_CONFIG["bot_card_spot"][2], CARD_W, CARD_D, 0, "MEDUSA"))
    assert not overlap(rect(hx, hz, hex_, hez), rect(mx, mz, mex, mez))


def test_floor_label_script_uses_a_small_configurable_font_and_the_white_seat_rotation(bprd):
    s = lua.draw_markings([("DESCARTE MEDUSA", "abc")], [("MEDUSA", 0, 0)])
    assert "setFontSize(30.0)" in s and "rotation = {90.0, 90.0, 0.0}" in s and "setFontSize(90)" not in s
    big = lua.draw_markings([("A", "abc")], [("B", 0, 0)], label_font=45.0, label_rotation=(90.0, 180.0, 0.0))
    assert "setFontSize(45.0)" in big and "rotation = {90.0, 180.0, 0.0}" in big
    assert lua.LABEL_FONT * 3 == 90
    for bad in ({"label_font": 0}, {"label_font": 500}, {"label_rotation": (1, 2)}, {"label_font": float("nan")}):
        with pytest.raises((ValueError, TypeError)):
            lua.draw_markings([("A", "abc")], [("B", 0, 0)], **bad)


def test_the_lua_label_formula_matches_the_python_mirror():
    s = lua.draw_markings([("A", "abc")], [("B", 0, 0)])
    assert f"{lua.LABEL_MARGIN!r}" in s and f"{lua.LABEL_CHAR_H!r}" in s and "cx - half" in s
