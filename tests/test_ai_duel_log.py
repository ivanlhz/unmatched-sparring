"""tools/ai_duel.py --log: finished games go to a JSONL file as they end, a relaunch skips them, and a game that dies does not
take the matchup with it (F-AI-EVAL-RESOLUTION)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools import ai_duel

HEROES = ("raptors", "liz-sherman")
A, B = ai_duel.parse_config("ismcts:iterations=3"), ai_duel.parse_config("heuristic")


def fake_play(job):
    seed, _, _, _, _, seat, _ = job
    return dict(score=float(seat == 0), turns=5, fallbacks=0, secs=0.1)


def dies_once_then_plays(job):
    seed, _, _, _, _, seat, marker = job
    if seed == 11 and not Path(marker).exists():
        Path(marker).write_text("x")
        os._exit(3)                         # the worker is gone, as when the machine runs out of memory
    return fake_play(job)


def never_plays_seed_11(job):
    if job[0] == 11:
        raise RuntimeError("cannot play this one")
    return fake_play(job)


def matchup(runner, log, games=3, journal=None):
    return ai_duel.run_matchup(HEROES, "bprd-hq", A, B, games, 10, runner, None, 1, journal, str(log))


def test_every_finished_game_is_written_with_what_the_summary_needs(tmp_path):
    log = tmp_path / "duel.jsonl"
    res = matchup(ai_duel.Runner(1, fake_play), log)
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(lines) == 6 == res["games"]
    assert {"seed", "a_seat", "score", "turns", "secs", "fallbacks", "key"} <= set(lines[0])
    assert sorted((x["seed"], x["a_seat"]) for x in lines) == [(s, t) for s in (10, 11, 12) for t in (0, 1)]


def test_a_relaunch_plays_only_what_is_missing_and_aggregates_everything(tmp_path):
    log = tmp_path / "duel.jsonl"
    first = matchup(ai_duel.Runner(1, fake_play), log, games=2)
    played = []
    again = ai_duel.Runner(1, lambda job: played.append((job[0], job[5])) or fake_play(job))
    res = matchup(again, log, games=3)
    assert played == [(12, 0), (12, 1)]
    assert res["games"] == 6 and first["games"] == 4
    assert len(log.read_text().splitlines()) == 6
    assert matchup(again, log, games=3)["score"] == res["score"] and len(played) == 2


def test_a_log_of_another_configuration_is_not_reused(tmp_path):
    log = tmp_path / "duel.jsonl"
    matchup(ai_duel.Runner(1, fake_play), log, games=1)
    other = ai_duel.parse_config("ismcts:iterations=4")
    played = []
    ai_duel.run_matchup(HEROES, "bprd-hq", other, B, 1, 10, ai_duel.Runner(1, lambda j: played.append(j) or fake_play(j)), None, 1, None, str(log))
    assert len(played) == 2


def test_a_half_written_last_line_is_ignored(tmp_path):
    log = tmp_path / "duel.jsonl"
    matchup(ai_duel.Runner(1, fake_play), log, games=1)
    with open(log, "a") as fh:
        fh.write('{"key": "x", "seed"')
    assert len(ai_duel.load_log(str(log))) == 2


def test_a_game_that_keeps_failing_is_an_error_row_and_the_others_go_on(tmp_path):
    log = tmp_path / "duel.jsonl"
    res = matchup(ai_duel.Runner(1, never_plays_seed_11), log)
    assert res["games"] == 4 and res["errors"] == 2
    errors = [json.loads(x) for x in log.read_text().splitlines() if "error" in x]
    assert {e["seed"] for e in errors} == {11} and "cannot play" in errors[0]["error"]
    played = []
    matchup(ai_duel.Runner(1, lambda j: played.append(j[0]) or fake_play(j)), log)
    assert sorted(played) == [11, 11]       # the next launch tries the failed ones again


def test_a_worker_that_dies_does_not_end_the_matchup(tmp_path):
    marker = tmp_path / "died"
    runner = ai_duel.Runner(2, dies_once_then_plays)
    try:
        jobs = [(s, HEROES, "bprd-hq", A, B, seat, str(marker)) for s in (10, 11, 12) for seat in (0, 1)]
        rows = runner.run(jobs, lambda row: None)
    finally:
        runner.close()
    assert marker.exists() and len(rows) == 6 and not [r for r in rows if "error" in r]


def test_the_real_game_is_logged_and_skipped_on_relaunch(tmp_path, capsys):
    log = tmp_path / "duel.jsonl"
    argv = ["--a", "ismcts:iterations=3", "--b", "heuristic", "--matchup", "raptors:liz-sherman", "--games", "1", "--jobs", "1",
            "--first-seed", "5", "--log", str(log), "--out", str(tmp_path / "o.json")]
    assert ai_duel.main(argv) == 0
    first = log.read_text()
    assert len(first.splitlines()) == 2 and json.loads(first.splitlines()[0])["turns"] >= 1
    assert ai_duel.main(argv) == 0
    assert log.read_text() == first
    assert json.load(open(tmp_path / "o.json"))[0]["games"] == 2
