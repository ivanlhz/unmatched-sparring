"""The plain-text game log next to the state file: header, resume line, chat lines, state changes, harmless failures."""
import re

import pytest

from sparring import game_log
from sparring.tts.lua import ChatKind
from test_batch import brig  # noqa: F401
from test_chat_colors import attack_plan

STAMP = re.compile(r"^\d\d:\d\d:\d\d ")


@pytest.fixture
def logged(brig, tmp_path):
    session, table, game, fake = brig
    session.state_path = tmp_path / "estado" / "sesion.json"
    session.state_path.parent.mkdir()
    session.game_log.path = game_log.log_path(session.state_path)
    return session, game, session.game_log.path


def lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_the_log_sits_next_to_the_state_file(tmp_path):
    assert game_log.log_path(tmp_path / "estado" / "sesion.json") == tmp_path / "estado" / "partida.log"
    assert game_log.log_path(None) is None


def test_a_new_game_writes_a_header_with_date_and_heroes(logged):
    session, game, path = logged
    session._begin_game()
    header = [l for l in lines(path) if l.startswith("====")]
    assert len(header) == 1
    assert re.search(r"New game \d{4}-\d\d-\d\d \d\d:\d\d:\d\d \| bot: Medusa vs human: Hellboy", header[0])


def test_resume_appends_a_resumed_line_and_keeps_the_old_game(logged):
    session, game, path = logged
    session._begin_game()
    before = lines(path)
    session.resume()
    after = lines(path)
    assert after[:len(before)] == before
    assert any(STAMP.match(l) and "resumed" in l for l in after[len(before):])
    assert sum(l.startswith("====") for l in after) == 1


def test_every_chat_message_lands_in_the_log_with_a_timestamp(logged):
    session, game, path = logged
    session.say("Tu turno: Maniobra", ChatKind.YOUR_TURN)
    session.say("Aviso de prueba", ChatKind.WARNING)
    assert [l[9:] for l in lines(path)] == ["Tu turno: Maniobra", "Aviso de prueba"]
    assert all(STAMP.match(l) for l in lines(path))


def test_the_combat_line_of_a_bot_attack_is_logged(logged, monkeypatch):
    session, game, path = logged
    attack_plan(session, monkeypatch)
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session._bot_continue()
    session._done()
    assert any("El bot ataca" in l for l in lines(path))


def test_damage_healing_moves_draws_and_discards_are_logged_once(logged):
    session, game, path = logged
    session.game_log.observe(game, session._name)                    # baseline
    hellboy = game.fighters["hellboy"]
    hp = hellboy.hp
    hellboy.hp -= 3
    hellboy.pos = min(game.legal_moves(hellboy, 1))
    game.draw(1, 1)
    game.discard_card(1, game.players[1].hand[0])
    session._done()
    text = "\n".join(lines(path))
    assert f"{hp:g} -> {hp - 3:g} HP" in text
    assert text.count("MOVE:") == 1 and "DRAW: P1 draws 1" in text and "DISCARD: P1 " in text
    before = len(lines(path))
    session._done()
    assert len(lines(path)) == before                                 # nothing changed: nothing logged
    hellboy.hp += 2
    session._done()
    assert "HEALING:" in lines(path)[-1]


def test_turn_start_and_game_over_are_logged(logged):
    session, game, path = logged
    session.game_log.observe(game, session._name)
    game.turn, game.turn_no = 0, game.turn_no + 1
    game.winner = 0
    session._done()
    text = "\n".join(lines(path))
    assert "TURN " in text and "GAME OVER: Medusa (P0) wins" in text


def test_an_unwritable_log_never_breaks_the_game(brig, tmp_path, capsys):
    session, table, game, fake = brig
    session.game_log.path = tmp_path / "missing-dir" / "partida.log"
    session.say("sigue la partida")
    session.say("y sigue")
    session._done()
    assert "sigue la partida" in session.messages
    assert capsys.readouterr().err.count("[warning]") == 1             # one warning, not one per line


def test_no_state_file_means_no_log(brig, tmp_path, monkeypatch):
    session, table, game, fake = brig
    monkeypatch.chdir(tmp_path)
    session.say("hola")
    session._done()
    assert not list(tmp_path.glob("**/*.log"))


def test_observe_survives_odd_state_with_and_without_a_path(tmp_path, capsys):
    game_log.GameLog(None).observe(object(), str)
    log = game_log.GameLog(tmp_path / "partida.log")
    log.observe(object(), str)
    log.observe(object(), str)
    assert capsys.readouterr().err.count("[warning]") == 1
    assert not (tmp_path / "partida.log").exists()


def test_a_lone_surrogate_in_the_chat_is_harmless(tmp_path):
    log = game_log.GameLog(tmp_path / "partida.log")
    log.chat("bad\ud800 text")
    assert "text" in (tmp_path / "partida.log").read_text(encoding="utf-8")
