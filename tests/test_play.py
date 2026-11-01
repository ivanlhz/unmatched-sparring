"""Entry point `python -m sparring.play`, always against FakeTTS on ephemeral ports."""
from conftest import t_deal_cards, t_discard_cards, t_flip_card
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from fake_tts import FakeTTS
from sparring import play
from sparring.board import Board
from sparring.play import ConfigError, ReadOnlyClient, ReadOnlyViolation, load_config, main, run_loop
from sparring.state import Game
from sparring.tts import lua
from sparring.tts.ui import Event
from test_session import NICK, PIECES, Table, card, rig, set_bot_hand  # noqa: F401

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "table.json"
TODO_ZONES = {"bot_discard_zone": "TODO: crear zona", "human_discard_zone": "TODO: crear zona"}
HAND_ZONES = {"dd569b", "f8d527", "742715", "6ec8d9", "bf62a8", "d8628b"}      # D1: hand zones, never discard zones
FILLED = {"bot_seat": "Blue", "human_seat": "Red", "bot_card_spot": [0.0, 1.0, 5.0], "human_card_spot": [0.0, -5.0],
          "bot_discard_spot": [5.0, 1.0, 5.0], "bot_discard_zone": "BOTZ", "bot_deck_guid": "DECK1",
          "human_discard_zone": "HUMZ", "bot_deck_spot": [0.0, 3.0], "pieces": PIECES, "dials": {}, "bot_discard_bounds": None, "setup": False}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def cfg_file(tmp_path):
    def make(**over):
        raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
        raw.update(FILLED)
        raw.update(bot_hero="medusa", human_hero="hellboy")     # explicit: detection on the table has its own tests
        raw.update(over)
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        return p
    return make


@pytest.fixture
def live():
    """FakeTTS with a Table; `ports` carries the ephemeral ports for `main`."""
    table = Table()
    fake = FakeTTS(return_value=table)
    listen = free_port()
    fake.reply_port = listen
    table.positions = {n: i + 1 for i, n in enumerate(NICK.values())}
    table.dials = {}
    set_bot_hand(table, Game.new(Board.load("bprd-hq"), 0), "Snipe", "Dash")
    ports = ["--send-port", str(fake.port), "--listen-port", str(listen)]
    yield table, fake, ports
    fake.close()


# ---------- configuration ----------
def test_real_config_is_complete_and_its_discard_zones_are_not_hand_zones():
    cfg = load_config(REAL_CONFIG)
    assert cfg.raw["board_guid"] == lua.BOARD_GUIDS["bprd-hq"] == "ec6f27"
    assert cfg.todos == []
    assert cfg.raw["bot_deck_guid"] == "d42056"
    assert cfg.raw["pieces"] == {"medusa": "04b2c9", "harpy1": "328e52", "harpy2": "33c5ec", "harpy3": "01eb1f",
                                 "hellboy": ["f9789a", "e6f06e"], "lobster": "e33604"}
    assert {cfg.raw["human_discard_zone"], cfg.raw["bot_discard_zone"]}.isdisjoint(HAND_ZONES)
    scfg = cfg.session_config()
    assert scfg.pieces["medusa"] == "04b2c9" and scfg.dials["medusa"] == "bcd809"


def test_a_config_with_todo_zones_lists_them_and_refuses_to_build(cfg_file):
    cfg = load_config(cfg_file(**TODO_ZONES))
    assert set(cfg.todos) == set(TODO_ZONES)
    with pytest.raises(ConfigError, match="faltan"):
        cfg.session_config()


def test_filled_config_builds_a_valid_session_config(cfg_file):
    scfg = load_config(cfg_file()).session_config()
    assert scfg.bot_deck_spot == (0.0, 3.0) and scfg.bot_seat == "Blue"


@pytest.mark.parametrize("over, match", [({"bot_seat": "Rojo"}, "no valida"), ({"bot_deck_guid": 'x"); --'}, "no valida"),
                                         ({"bot_deck_spot": [1]}, "no valida"), ({"board": "nope"}, "tablero"),
                                         ({"board_guid": "zzz999"}, "board_guid")])
def test_bad_config_values_fail_before_anything_is_sent(cfg_file, over, match):
    with pytest.raises(ConfigError, match=match):
        load_config(cfg_file(**over)).session_config()


def test_main_refuses_to_play_with_todos_and_sends_nothing(live, cfg_file):
    table, fake, ports = live
    assert main(["--config", str(cfg_file(**TODO_ZONES)), *ports]) == 2
    assert fake.received == []


def test_main_missing_config_file_is_exit_2(tmp_path):
    assert main(["--config", str(tmp_path / "no.json")]) == 2


# ---------- read-only mode ----------
def test_read_only_reports_and_sends_only_read_scripts(live, cfg_file, capsys):
    table, fake, ports = live
    table.missing_guids = {"f8d527"}
    table.human_discard = [card(Game.new(Board.load("bprd-hq"), 0), 1, "Pancakes!").card_id]
    code = main(["--config", str(cfg_file()), "--read-only", *ports])
    out = capsys.readouterr().out
    assert code == 0
    assert "SOLO LECTURA" in out and "Pancakes!" in out and "Snipe" in out and "casilla" in out
    assert "f8d527" in out and "NO existe" in out and "miniaturas por GUID" in out
    tags = {s.split("\n")[0] for s in table.scripts}
    assert tags and tags <= {f"-- sparring:{t}" for t in play.READ_ONLY_TAGS}
    assert {m["messageID"] for m in fake.received} == {3}


def test_read_only_with_todo_zones_reports_them_and_still_reads(live, cfg_file, capsys):
    table, fake, ports = live
    assert main(["--config", str(cfg_file(**TODO_ZONES)), "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "TODO" in out and "bot_discard_zone" in out and "crea una zona de scripting" in out
    assert not any(s.startswith(("-- sparring:move", "-- sparring:create_panel", "-- sparring:broadcast",
                                 "-- sparring:discard", "-- sparring:deal", "-- sparring:play"))
                   for s in table.scripts)


@pytest.mark.parametrize("script", [lambda: lua.create_panel(["medusa"]), lambda: lua.broadcast("hola"),
                                    lambda: t_deal_cards("abc", 1, "Blue", spot=(0, 0)),
                                    lambda: t_discard_cards([17600], [(0, 0, 0)]),
                                    lambda: t_flip_card("g1"), lambda: "return 1"])
def test_read_only_client_refuses_anything_that_could_change_the_table(script):
    class Boom:
        def call_lua(self, *a, **k):
            raise AssertionError("no debia llegar al cliente real")
    with pytest.raises(ReadOnlyViolation):
        ReadOnlyClient(Boom()).call_lua(script())


# ---------- event loop and play ----------
def test_play_creates_the_panel_announces_and_pumps_button_events(live, cfg_file, capsys, tmp_path):
    table, fake, ports = live
    stop = threading.Event()
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("code", main(
        ["--config", str(cfg_file()), "--first", "human", "--poll", "0.02", *ports, "--state", str(tmp_path / "s.json")],
        stop=stop)))
    t.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and table.count("create_panel") == 0:
            time.sleep(0.02)
        assert table.count("create_panel") == 1
        fake.push({"messageID": 4, "customMessage": {"event": "maneuver"}})
        fake.push({"messageID": 4, "customMessage": {"event": "no_existe"}})
        deadline = time.time() + 5
        while time.time() < deadline and not any("Maniobra" in b for b in table.broadcasts):
            time.sleep(0.02)
    finally:
        stop.set()
        t.join(5)
    assert result["code"] == 0 and not t.is_alive()
    assert any("Maniobra" in b for b in table.broadcasts) and any("Tu turno" in b for b in table.broadcasts)
    assert "Evento desconocido" in capsys.readouterr().out or any("desconocido" in b for b in table.broadcasts)
    assert all(m["messageID"] == 3 for m in fake.received)


def test_ctrl_c_exits_cleanly_and_frees_the_listener_port(live, cfg_file, monkeypatch, capsys, tmp_path):
    table, fake, ports = live

    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(play, "run_loop", interrupted)
    assert main(["--config", str(cfg_file()), *ports, "--state", str(tmp_path / "s.json")]) == 130
    assert "Interrumpido" in capsys.readouterr().out
    with socket.socket() as s:                       # the listener closed: the port can be opened again
        s.bind(("127.0.0.1", int(ports[3])))


def test_loop_survives_an_internal_error_and_unknown_events(rig, monkeypatch):
    session, table, game = rig
    said, stop = [], threading.Event()
    calls = {"n": 0}

    class Client:
        def poll_events(self):
            calls["n"] += 1
            return {1: [{"event": "cancel"}, {"event": "???"}, "basura"],
                    2: [{"event": "scheme"}]}.get(calls["n"], [])

    def explode(event, payload=None):
        if event is Event.CANCEL:
            raise RuntimeError("bug")
        return ["ok"]
    monkeypatch.setattr(session, "handle", explode)
    threading.Timer(0.3, stop.set).start()
    run_loop(session, Client(), stop, said.extend, poll=0.01)
    assert any("Error interno" in m for m in said) and any("desconocido" in m for m in said) and "ok" in said


def test_announcer_echoes_and_broadcasts_ascii_chunks(rig):
    session, table, game = rig
    shown = []
    play.make_announcer(session.client, echo=shown.append)(["Tu turno (forma: OCCULT DETECTIVE). ¿Listo? " * 3])
    assert shown and table.broadcasts and all(len(b) <= 64 for b in table.broadcasts)
    assert all(ord(ch) < 128 for b in table.broadcasts for ch in b)


def test_first_turn_option(cfg_file):
    cfg = load_config(cfg_file())
    g = play.build_game(cfg, "bot", 0)
    assert g.turn == 0 and g.actions_left == 2
    assert play.build_game(cfg, "human", 0).turn == 1
