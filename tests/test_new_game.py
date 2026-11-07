"""New game button: a confirmed second press discards the game and sends the bot back to the pre-game gate."""
import threading

from sparring import play
from sparring.tts import ui
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401  (brig is a fixture)
from test_panel_restart import Clock, prepared  # noqa: F401


def test_one_press_only_arms_it(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    msgs = click(session, table, Event.NEW_GAME)
    assert session.new_game_armed() and not session.back_to_gate
    assert any("Nueva partida" in m for m in msgs) and "confirmar" in table.panels[-1][0]
    assert (tmp_path / "session.json").exists() and session.game is game


def test_second_press_discards_the_save_and_asks_to_go_back_to_the_gate(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    click(session, table, Event.NEW_GAME)
    msgs = click(session, table, Event.NEW_GAME)
    assert session.back_to_gate and not (tmp_path / "session.json").exists()
    assert any("puerta de inicio" in m for m in msgs)
    assert not table.placed, "the table is left as it is: the player clears it at the gate"


def test_late_second_press_arms_again_and_other_button_disarms(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    click(session, table, Event.NEW_GAME)
    clock.now += 3.5
    click(session, table, Event.NEW_GAME)
    assert not session.back_to_gate and session.new_game_armed()
    click(session, table, Event.MANEUVER)
    click(session, table, Event.NEW_GAME)
    assert not session.back_to_gate


def test_it_is_accepted_whatever_the_game_is_waiting_for(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    session.ability_wait = "Some ability"
    click(session, table, Event.NEW_GAME)
    assert session.new_game_armed()
    session.ability_wait = None
    session.setup = {"stage": "wait_human"}
    click(session, table, Event.NEW_GAME)
    assert session.back_to_gate


def test_button_is_visible_in_setup_midgame_and_after_game_over_unless_there_is_no_gate(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)
    assert session.panel_view()[1]["btn_newgame"] == (True, True)
    session.setup = {"stage": "wait_human"}
    assert session.panel_view()[1]["btn_newgame"] == (True, True)
    session.setup = None
    game.winner = 0
    assert session.panel_view()[1]["btn_newgame"] == (True, True)
    session.can_regate = False
    assert session.panel_view()[1]["btn_newgame"][1] is False
    click(session, table, Event.NEW_GAME)
    assert not session.back_to_gate and not session.new_game_armed()


def test_panel_has_the_button_and_its_handler():
    xml = ui.panel_xml(["medusa"])
    assert 'id="btn_newgame"' in xml and "btn_newgame" in ui.element_ids(["medusa"])
    assert 'send({event = "new_game"})' in ui.handler_script()


def test_run_loop_returns_as_soon_as_the_game_is_discarded(brig, tmp_path):
    session, table, game, clock = prepared(brig, tmp_path)

    class Client:
        def __init__(self):
            self.batches = [[{"event": "new_game"}, {"event": "new_game"}, {"event": "maneuver"}]]

        def poll_events(self):
            return self.batches.pop(0) if self.batches else []

        def take_reload(self):
            return False
    handled = []
    real = session.handle
    session.handle = lambda e, p=None: handled.append(e) or real(e, p)
    play.run_loop(session, Client(), threading.Event(), lambda m: None, poll=0.01)
    assert handled == [Event.NEW_GAME, Event.NEW_GAME] and session.back_to_gate
