"""The console (`--help`, warnings, errors, the read-only report) follows the language like the chat and the panel, and a
resumed game keeps the language it was played in unless `--language` is given explicitly."""
from __future__ import annotations

import json

import pytest

from sparring import game_log, i18n, play
from test_play import cfg_file, free_port, live  # noqa: F401


def interrupted(*a, **k):
    raise KeyboardInterrupt


def play_once(argv, monkeypatch):
    monkeypatch.setattr(play, "run_loop", interrupted)
    return play.main(argv)


# ---------------------------------------------------------------- the language the console starts in

def test_the_early_language_is_the_flag_then_the_config_key_then_spanish(cfg_file, tmp_path):
    assert play.early_language(["--language", "en", "--config", str(cfg_file(language="es"))]) == "en"
    assert play.early_language(["--config", str(cfg_file(language="en"))]) == "en"
    assert play.early_language(["--config", str(cfg_file(language=None))]) == i18n.DEFAULT
    assert play.early_language(["--config", str(tmp_path / "missing.json")]) == i18n.DEFAULT


def test_help_comes_out_in_the_requested_language(capsys):
    with pytest.raises(SystemExit):
        play.parse_args(["--language", "en", "--help"])
    out = capsys.readouterr().out
    assert "who goes first" in out and "quien empieza" not in out
    with pytest.raises(SystemExit):
        play.parse_args(["--language", "es", "--help"])
    out = capsys.readouterr().out
    assert "quien empieza" in out and "who goes first" not in out


def test_a_config_error_is_printed_in_the_language_of_the_run(tmp_path, capsys):
    missing = str(tmp_path / "missing.json")
    assert play.main(["--config", missing, "--language", "en"]) == 2
    assert "Configuration: cannot read the configuration" in capsys.readouterr().err
    assert play.main(["--config", missing, "--language", "es"]) == 2
    assert "Configuracion: no puedo leer la configuracion" in capsys.readouterr().err


def test_the_read_only_report_is_in_english_with_language_en(live, cfg_file, capsys):
    table, fake, ports = live
    assert play.main(["--config", str(cfg_file()), "--read-only", "--language", "en", *ports]) == 0
    out = capsys.readouterr().out
    assert "READ-ONLY REPORT" in out and "end of report" in out and "INFORME" not in out


def test_a_start_up_warning_about_the_floor_is_in_english(cfg_file):
    cfg = play.load_config(cfg_file(panel_position=[0, 1.8, -18]), language="en")
    warnings = play.floor_layout_warnings(cfg)
    assert warnings and all("ends up under the panel" in w for w in warnings)


# ---------------------------------------------------------------- the saved game keeps its language

def test_the_save_carries_the_language_it_was_played_in(live, cfg_file, tmp_path, monkeypatch):
    table, fake, ports = live
    state = tmp_path / "s.json"
    assert play_once(["--config", str(cfg_file(language="en")), "--first", "human", *ports, "--state", str(state)], monkeypatch) == 130
    assert json.loads(state.read_text(encoding="utf-8"))["language"] == "en"
    assert play.saved_language(state) == "en"


def test_resume_reuses_the_saved_language_unless_one_is_given(live, cfg_file, tmp_path, monkeypatch, capsys):
    table, fake, ports = live
    state = tmp_path / "s.json"
    play_once(["--config", str(cfg_file(language="en")), "--first", "human", *ports, "--state", str(state)], monkeypatch)
    capsys.readouterr()
    i18n.set_language("es")
    # the configuration says Spanish, the save says English: the save wins
    play_once(["--config", str(cfg_file(language="es")), "--resume", *ports, "--state", str(state)], monkeypatch)
    assert i18n.language() == "en"
    assert "ability_wait" not in capsys.readouterr().err


def test_resume_with_an_explicit_language_wins_and_warns_that_old_lines_may_stay(live, cfg_file, tmp_path, monkeypatch, capsys):
    table, fake, ports = live
    state = tmp_path / "s.json"
    play_once(["--config", str(cfg_file(language="en")), "--first", "human", *ports, "--state", str(state)], monkeypatch)
    capsys.readouterr()
    play_once(["--config", str(cfg_file()), "--resume", "--language", "es", *ports, "--state", str(state)], monkeypatch)
    assert i18n.language() == "es"
    err = capsys.readouterr().err
    assert "ability_wait" in err and "--language es" in err


def test_resume_of_a_save_without_a_language_follows_the_configuration(live, cfg_file, tmp_path, monkeypatch):
    table, fake, ports = live
    state = tmp_path / "s.json"
    play_once(["--config", str(cfg_file(language="es")), "--first", "human", *ports, "--state", str(state)], monkeypatch)
    data = json.loads(state.read_text(encoding="utf-8"))
    del data["language"]                                          # a save from before the language was kept
    state.write_text(json.dumps(data), encoding="utf-8")
    assert play.saved_language(state) is None
    play_once(["--config", str(cfg_file(language="en")), "--resume", *ports, "--state", str(state)], monkeypatch)
    assert i18n.language() == "en"


# ---------------------------------------------------------------- the old names still work

def test_the_old_config_name_is_found_but_always_announced(tmp_path, cfg_file):
    table = tmp_path / "table.json"
    table.write_text(cfg_file().read_text(encoding="utf-8"), encoding="utf-8")
    cfg = play.load_config(tmp_path / "partida.json")             # does not exist: table.json beside it is used
    assert cfg.raw == play.load_config(table).raw
    assert [w for w in cfg.warnings if "partida.json" in w and "table.json" in w]
    (tmp_path / "partida.json").write_text(table.read_text(encoding="utf-8"), encoding="utf-8")
    assert [w for w in play.load_config(tmp_path / "partida.json").warnings if "table.json" in w]     # also when it exists
    assert not [w for w in play.load_config(table).warnings if "partida" in w]
    with pytest.raises(play.ConfigError):
        play.load_config(tmp_path / "other.json")                 # only the old name is mapped


def test_the_default_config_is_table_json_even_if_the_old_file_exists():
    assert play.DEFAULT_CONFIG.name == "table.json" and not hasattr(play, "default_config_path")


def legacy_layout(tmp_path, monkeypatch):
    new, old = tmp_path / "state" / "session.json", tmp_path / "estado" / "sesion.json"
    monkeypatch.setattr(play, "DEFAULT_STATE", new)
    monkeypatch.setattr(play, "LEGACY_STATE", old)
    old.parent.mkdir()
    return new, old


def test_an_old_save_and_log_are_moved_once_with_a_notice(tmp_path, monkeypatch):
    new, old = legacy_layout(tmp_path, monkeypatch)
    old.write_text("{}", encoding="utf-8")
    (old.parent / "partida.log").write_text("log\n", encoding="utf-8")
    notices = play.migrate_legacy_files(new)
    assert len(notices) == 2 and "sesion.json" in notices[0] and "session.json" in notices[0]
    assert new.read_text(encoding="utf-8") == "{}" and (new.parent / "session.log").read_text(encoding="utf-8") == "log\n"
    assert not old.exists() and not (old.parent / "partida.log").exists()          # never an old+new pair
    assert play.migrate_legacy_files(new) == []                                       # and only once


def test_an_old_save_is_not_moved_over_a_new_one(tmp_path, monkeypatch):
    new, old = legacy_layout(tmp_path, monkeypatch)
    old.write_text("old", encoding="utf-8")
    new.parent.mkdir()
    new.write_text("new", encoding="utf-8")
    assert play.migrate_legacy_files(new) == []
    assert new.read_text(encoding="utf-8") == "new" and old.exists()


def test_a_log_next_to_an_explicit_state_file_is_renamed(tmp_path, monkeypatch):
    legacy_layout(tmp_path, monkeypatch)
    state = tmp_path / "mine" / "game.json"
    state.parent.mkdir()
    (state.parent / "partida.log").write_text("log", encoding="utf-8")
    notices = play.migrate_legacy_files(state)
    assert len(notices) == 1 and (state.parent / "session.log").read_text(encoding="utf-8") == "log"
    assert game_log.log_path(state) == state.parent / "session.log"


def test_main_prints_the_migration_notice_in_the_console(live, cfg_file, tmp_path, monkeypatch, capsys):
    table, fake, ports = live
    new, old = legacy_layout(tmp_path, monkeypatch)
    old.write_text("{}", encoding="utf-8")
    play_once(["--config", str(cfg_file()), "--first", "human", *ports, "--language", "en"], monkeypatch)
    err = capsys.readouterr().err
    assert "was moved to" in err and new.exists() and not old.exists()
