"""The atomic save on Windows: `os.replace` fails with PermissionError while another handle holds the save (a reader,
a virus scanner on the fresh temporary file). The save waits that out instead of losing the write."""
import threading
import time

import pytest

from sparring import persist


def test_the_save_waits_for_a_reader_that_holds_the_file_open(tmp_path):
    path = tmp_path / "s.json"
    persist.save_atomic(path, {"n": 1})
    opened = threading.Event()

    def hold():
        with open(path, encoding="utf-8"):
            opened.set()
            time.sleep(0.3)
    reader = threading.Thread(target=hold)
    reader.start()
    assert opened.wait(2)
    persist.save_atomic(path, {"n": 2})
    reader.join()
    assert persist.load(path)["n"] == 2


def test_a_lock_that_never_lifts_is_still_an_error(tmp_path, monkeypatch):
    def locked(src, dst):
        raise PermissionError(13, "Access denied")
    monkeypatch.setattr(persist.os, "replace", locked)
    monkeypatch.setattr(persist, "REPLACE_WAIT", 0.05)
    with pytest.raises(PermissionError):
        persist.save_atomic(tmp_path / "s.json", {"n": 1})
