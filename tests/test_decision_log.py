"""The decision journal (state/decisions.jsonl), the review tool and the duel bench."""
import json
import sys
from pathlib import Path

import pytest

from sparring import decision_log, game_log, sim
from sparring.ai_medusa import MedusaAI
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from test_batch import brig  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ai_duel          # noqa: E402
import review_decisions  # noqa: E402


def records(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def journaled_game(path, kind: str, turns: int = 4, seed: int = 1):
    ai = IsmctsMedusa(0, SearchConfig(time_budget=60.0, iterations=25, seed=0)) if kind == "ismcts" else MedusaAI(0)
    ai.journal = decision_log.DecisionJournal(path)
    sim.play(seed, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=turns)
    return ai


@pytest.mark.parametrize("kind", ["ismcts", "heuristic"])
def test_every_plan_and_defense_writes_a_decision_with_its_alternatives(tmp_path, kind):
    path = tmp_path / "decisions.jsonl"
    journaled_game(path, kind)
    recs = records(path)
    decisions = [r for r in recs if r["t"] == "decision"]
    assert {"plan", "defense"} <= {d["kind"] for d in decisions}
    for d in decisions:
        assert d["ai"] == kind and d["fallback"] is False
        assert set(d["own"]) == set(d["rival"]) == {"hand", "deck", "discard", "hero_hp"}
        assert isinstance(d["rival_known_in_hand"], list) and d["alternatives"] and d["chosen"] is not None
        assert d["game"] == recs[0]["game"] and d["turn"] >= 1
    if kind == "ismcts":
        assert all("visits" in a and "value" in a for d in decisions for a in d["alternatives"])
        assert recs[0]["t"] == "game" and recs[0]["iterations_cap"] == 25 and recs[0]["time_budget"] == 60.0
    else:
        assert all("score" in a for d in decisions for a in d["alternatives"])
        assert recs[0]["ai"] == "heuristic"


def test_each_decision_gets_a_linked_outcome_with_what_really_happened(tmp_path):
    path = tmp_path / "decisions.jsonl"
    journaled_game(path, "ismcts", turns=6)
    recs = records(path)
    outcomes = {r["seq"]: r for r in recs if r["t"] == "outcome"}
    decisions = [r for r in recs if r["t"] == "decision"]
    assert len(outcomes) >= len(decisions) - 1
    some = outcomes[decisions[0]["seq"]]
    assert {"damage_dealt", "damage_taken", "own_cards_spent", "rival_cards_played", "evaluation_after", "expected"} <= set(some)
    assert all(o["damage_dealt"] >= 0 and o["damage_taken"] >= 0 for o in outcomes.values())
    assert any(o["damage_dealt"] or o["damage_taken"] for o in outcomes.values())
    assert any(o["own_cards_spent"] for o in outcomes.values())


def test_a_search_that_fails_is_marked_as_a_fallback_in_the_journal(tmp_path, monkeypatch):
    path = tmp_path / "decisions.jsonl"
    ai = IsmctsMedusa(0, SearchConfig(time_budget=60.0, iterations=10, seed=0))
    ai.journal = decision_log.DecisionJournal(path)

    def boom(*a, **k):
        raise RuntimeError("search exploded")
    monkeypatch.setattr(ai, "_plan", boom)
    sim.play(1, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=1)
    plans = [r for r in records(path) if r["t"] == "decision" and r["kind"] == "plan"]
    assert plans and all(p["fallback"] is True and "search exploded" in p["error"] and p["alternatives"] for p in plans)
    assert ai.fallbacks == len(plans)


def test_a_journal_that_cannot_write_never_breaks_the_game(tmp_path, capsys):
    ai = MedusaAI(0)
    ai.journal = decision_log.DecisionJournal(tmp_path / "missing_folder" / "decisions.jsonl")
    outcome = sim.play(1, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=3)
    assert outcome.turns >= 1
    assert capsys.readouterr().err.count("decision journal disabled") == 1


def test_a_journal_that_raises_while_building_the_line_never_breaks_the_game(tmp_path, monkeypatch, capsys):
    ai = MedusaAI(0)
    ai.journal = decision_log.DecisionJournal(tmp_path / "decisions.jsonl")
    monkeypatch.setattr(decision_log, "_side", lambda *a: 1 / 0)
    assert sim.play(1, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=3).turns >= 1
    assert "decision journal disabled" in capsys.readouterr().err


def test_the_journal_sits_next_to_the_state_file(tmp_path):
    state = tmp_path / "state" / "session.json"
    assert decision_log.decisions_path(state) == tmp_path / "state" / "decisions.jsonl"
    assert decision_log.decisions_path(state).parent == game_log.log_path(state).parent
    assert decision_log.decisions_path(None) is None


def test_the_headers_name_the_ai_and_its_budget(brig, tmp_path):  # noqa: F811
    session, table, game, fake = brig
    state = tmp_path / "state" / "session.json"
    state.parent.mkdir()
    session.game_log.path, session.journal.path = game_log.log_path(state), decision_log.decisions_path(state)
    session.ai = IsmctsMedusa(0, SearchConfig(time_budget=3.0, iterations=None, seed=0))
    session._begin_game()
    header = [l for l in session.game_log.path.read_text(encoding="utf-8").splitlines() if l.startswith("====")][0]
    assert "| ai: ismcts (3 s per decision)" in header
    first = records(session.journal.path)[0]
    assert first["t"] == "game" and first["ai"] == "ismcts" and first["time_budget"] == 3.0 and first["iterations_cap"] is None
    assert session.ai.journal is session.journal
    assert decision_log.ai_label(MedusaAI(0)) == "heuristic"


def test_a_session_plan_lands_in_the_journal_with_the_hand_sizes(brig, tmp_path):  # noqa: F811
    session, table, game, fake = brig
    session.journal.path = tmp_path / "decisions.jsonl"
    session._begin_game()
    game.turn, game.actions_left = 0, 2
    session.ai.plan(game)
    recs = records(session.journal.path)
    plan = next(r for r in recs if r["t"] == "decision")
    assert plan["own"]["hand"] == len(game.players[0].hand) and plan["rival"]["hand"] == len(game.players[1].hand)


def test_review_lists_surprises_and_coin_flips(tmp_path, capsys):
    path = tmp_path / "decisions.jsonl"
    base = {"t": "decision", "game": "g1", "player": 0, "kind": "plan", "ai": "ismcts", "turn": 1, "chosen": {"kind": "maneuver"}}
    lines = [
        {"t": "game", "game": "g1", "bot_hero": "Raptor Blue", "rival_hero": "Liz Sherman", "ai": "ismcts", "time_budget": 3.0},
        {**base, "seq": 1, "expected": 0.9, "alternatives": [{"move": ["maneuver", None], "visits": 50, "value": 0.9}, {"move": ["maneuver", "Ambush"], "visits": 49, "value": 0.895}]},
        {"t": "outcome", "game": "g1", "seq": 1, "damage_dealt": 0, "damage_taken": 5, "own_cards_spent": [], "rival_cards_played": ["Fireball"], "evaluation_after": 0.5},
        {**base, "seq": 2, "expected": 0.8, "alternatives": [{"move": ["maneuver", None], "visits": 80, "value": 0.8}, {"move": ["scheme", "X"], "visits": 5, "value": 0.4}]},
        {"t": "outcome", "game": "g1", "seq": 2, "damage_dealt": 0, "damage_taken": 0, "own_cards_spent": [], "rival_cards_played": [], "evaluation_after": 0.79},
    ]
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\nnot json at all\n", encoding="utf-8")
    game = review_decisions.read_games(path)["g1"]
    assert [d["seq"] for d, _, _ in review_decisions.surprises(game, 0.15, 3.0)] == [1]
    assert [d["seq"] for d, _ in review_decisions.coin_flips(game, 0.01)] == [1]
    assert review_decisions.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "Outcome far from the expectation: 1" in out and "Top two alternatives within noise: 1" in out
    assert review_decisions.main([str(path), "--game", "nope"]) == 1


def test_duel_configs_wilson_interval_and_sequential_test():
    assert ai_duel.parse_config("heuristic") == {"ai": "heuristic", "spec": "heuristic"}
    cfg = ai_duel.parse_config("ismcts:iterations=40,seed=3")
    assert (cfg["iterations"], cfg["seed"]) == (40, 3)
    assert ai_duel.parse_config("ismcts:time=2")["iterations"] is None
    for bad in ("minimax", "ismcts:depth=3", "heuristic:time=2"):
        with pytest.raises(ValueError):
            ai_duel.parse_config(bad)
    lo, hi = ai_duel.wilson(0.5, 100)
    assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    assert ai_duel.wilson(1.0, 0) == (0.0, 1.0)
    sprt = ai_duel.Sprt(delta=0.1, alpha=0.05, beta=0.05)
    for _ in range(60):
        sprt.add(1.0)
    assert sprt.verdict() == "A better"
    even = ai_duel.Sprt(delta=0.1, alpha=0.05, beta=0.05)
    for i in range(400):
        even.add(float(i % 2))
        if even.verdict():
            break
    assert even.verdict() == "no difference of that size"


def test_a_short_duel_plays_both_seats_from_the_same_seeds(tmp_path):
    out = tmp_path / "duel.json"
    journal_dir = tmp_path / "journals"
    code = ai_duel.main(["--a", "ismcts:iterations=10", "--b", "heuristic", "--matchup", "raptors:liz-sherman", "--games", "1",
                         "--jobs", "1", "--journal-dir", str(journal_dir), "--out", str(out)])
    assert code == 0
    (row,) = json.loads(out.read_text())
    assert row["games"] == 2 and row["a_wins"] + row["b_wins"] + row["unfinished"] == 2
    assert row["a_as_p0"] is not None and row["a_as_p1"] is not None and 0 <= row["ci95"][0] <= row["score"] <= row["ci95"][1] <= 1
    assert len(list(journal_dir.glob("*.jsonl"))) == 4
