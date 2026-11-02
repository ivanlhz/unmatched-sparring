"""`--launcher` (the desktop launcher's protocol) and the frozen executable's paths, against FakeTTS."""
import queue
import socket
import threading
import time

from sparring import play
from sparring.play import STATUS_PREFIX, main, state_dir, tts_error_kind
from test_play import cfg_file, free_port, live  # noqa: F401


class PipeStdin:
    """stdin fed line by line from the test; None closes it (EOF)."""

    def __init__(self):
        self.lines: queue.Queue = queue.Queue()

    def __iter__(self):
        return iter(self.lines.get, None)


def statuses(out: str) -> list[str]:
    return [line[len(STATUS_PREFIX) + 1:] for line in out.splitlines() if line.startswith(STATUS_PREFIX)]


def run_until_panel(live, cfg_file, tmp_path, monkeypatch, ending):
    table, fake, ports = live
    stdin = PipeStdin()
    monkeypatch.setattr("sys.stdin", stdin)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("code", main(
        ["--config", str(cfg_file()), "--first", "human", "--poll", "0.02", *ports,
         "--state", str(tmp_path / "s.json"), "--launcher"])))
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and table.count("create_panel") == 0:
        time.sleep(0.02)
    assert table.count("create_panel") == 1
    cleared_before = table.count("clear_markings")
    stdin.lines.put(ending)
    t.join(5)
    assert not t.is_alive()
    return result["code"], table.count("clear_markings") - cleared_before


def test_a_quit_line_on_stdin_stops_like_ctrl_c_and_cleans_the_table(live, cfg_file, tmp_path, monkeypatch, capsys):
    code, cleared = run_until_panel(live, cfg_file, tmp_path, monkeypatch, "quit\n")
    assert code == 0 and cleared == 1                       # the panel and the floor labels are removed
    assert statuses(capsys.readouterr().out) == ["connecting", "playing", "exit 0"]


def test_stdin_closing_stops_too_so_a_dead_launcher_leaves_no_bot_behind(live, cfg_file, tmp_path, monkeypatch):
    code, cleared = run_until_panel(live, cfg_file, tmp_path, monkeypatch, None)
    assert code == 0 and cleared == 1


def test_other_lines_on_stdin_are_ignored(live, cfg_file, tmp_path, monkeypatch, capsys):
    table, fake, ports = live
    stdin = PipeStdin()
    monkeypatch.setattr("sys.stdin", stdin)
    stop = threading.Event()
    t = threading.Thread(target=main, args=(["--config", str(cfg_file()), "--poll", "0.02", *ports,
                                             "--state", str(tmp_path / "s.json"), "--launcher"],), kwargs={"stop": stop})
    t.start()
    stdin.lines.put("hello\n")
    time.sleep(0.3)
    try:
        assert t.is_alive()
    finally:
        stop.set()
        stdin.lines.put(None)
        t.join(5)


def test_tts_not_open_is_a_plain_status_and_exit_3(cfg_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", PipeStdin())
    code = main(["--config", str(cfg_file()), "--send-port", str(free_port()), "--listen-port", str(free_port()),
                 "--state", str(tmp_path / "s.json"), "--launcher"])
    assert code == 3
    assert statuses(capsys.readouterr().out) == ["connecting", "error tts_unreachable", "exit 3"]


def test_listen_port_in_use_is_its_own_status(cfg_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", PipeStdin())
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        code = main(["--config", str(cfg_file()), "--send-port", str(free_port()),
                     "--listen-port", str(busy.getsockname()[1]), "--state", str(tmp_path / "s.json"), "--launcher"])
    assert code == 3
    assert statuses(capsys.readouterr().out)[-2:] == ["error port_in_use", "exit 3"]


def test_without_launcher_the_output_has_no_status_lines(cfg_file, tmp_path, capsys):
    code = main(["--config", str(cfg_file()), "--send-port", str(free_port()), "--listen-port", str(free_port()),
                 "--state", str(tmp_path / "s.json")])
    captured = capsys.readouterr()
    assert code == 3 and STATUS_PREFIX not in captured.out + captured.err


def test_a_config_error_reports_its_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", PipeStdin())
    assert main(["--config", str(tmp_path / "missing.json"), "--launcher"]) == 2
    assert statuses(capsys.readouterr().out) == ["error config", "exit 2"]


def test_error_kinds():
    assert tts_error_kind(ConnectionRefusedError(10061, "refused")) == "tts_unreachable"
    assert tts_error_kind(TimeoutError("no reply")) == "tts_timeout"
    assert tts_error_kind(OSError(None, "in use", None, 10048)) == "port_in_use"
    assert tts_error_kind(PermissionError(13, "denied", None, 10013)) == "port_in_use"    # bind with SO_REUSEADDR
    assert tts_error_kind(OSError(play.errno.EADDRINUSE, "in use")) == "port_in_use"
    assert tts_error_kind(OSError(5, "other")) == "tts_error"


def test_the_frozen_executable_saves_under_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert state_dir(frozen=True) == tmp_path / "UnmatchedSparring" / "state"
    assert state_dir(frozen=False) == play.ROOT / "state"
