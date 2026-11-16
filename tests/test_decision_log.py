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
        assert set(d["own"]) == set(d["rival"]) == {"hand", "deck", "discard", "hero_hp", "fighters"}
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
    assert capsys.readouterr().err.count("decision journal problem") == 1


def test_a_journal_that_raises_while_building_the_line_never_breaks_the_game(tmp_path, monkeypatch, capsys):
    ai = MedusaAI(0)
    ai.journal = decision_log.DecisionJournal(tmp_path / "decisions.jsonl")
    monkeypatch.setattr(decision_log, "_side", lambda *a: 1 / 0)
    assert sim.play(1, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=3).turns >= 1
    assert "decision journal problem" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["ismcts", "heuristic"])
def test_a_line_that_cannot_be_described_never_breaks_the_game_and_without_a_journal_nothing_is_computed(tmp_path, monkeypatch, capsys, kind):
    calls = []

    def boom(act):
        calls.append(act)
        raise RuntimeError("cannot describe")
    monkeypatch.setattr(decision_log, "describe_act", boom)
    ai = IsmctsMedusa(0, SearchConfig(time_budget=60.0, iterations=10, seed=0)) if kind == "ismcts" else MedusaAI(0)
    assert sim.play(1, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=2).turns >= 1
    assert calls == [], "no journal attached: nothing is built"
    ai.journal = decision_log.DecisionJournal(tmp_path / "decisions.jsonl")
    assert sim.play(1, bot_hero="raptors", human_hero="liz-sherman", medusa=ai, max_turns=3).turns >= 1
    assert calls and "decision journal problem" in capsys.readouterr().err


def test_the_chosen_move_is_always_written_and_the_cut_is_declared(tmp_path):
    path = tmp_path / "decisions.jsonl"
    journaled_game(path, "heuristic", turns=8)
    plans = [r for r in records(path) if r["t"] == "decision" and r["kind"] == "plan"]
    assert plans and all(p["alternatives_total"] >= len(p["alternatives"]) for p in plans)
    assert all(sum(1 for a in p["alternatives"] if a.get("chosen")) == 1 for p in plans)
    assert all(next(a for a in p["alternatives"] if a.get("chosen"))["move"] == p["chosen"] for p in plans)
    journal = decision_log.DecisionJournal(path)
    many = [{"move": i, "score": -i} for i in range(100)] + [{"move": "last", "score": -999, "chosen": True}]
    ai = MedusaAI(0)
    game = sim_game()
    journal.decision(game, 0, "plan", ai, "last", many)
    line = records(path)[-1]
    assert line["alternatives_total"] == 101 and len(line["alternatives"]) == decision_log.MAX_ALTERNATIVES + 1
    assert line["alternatives"][-1]["chosen"] is True


def sim_game():
    from sparring.board import Board
    from sparring.state import Game
    return Game.new(Board.load("bprd-hq"), 1, {0: MedusaAI(0), 1: MedusaAI(1)}, bot_player=0, heroes=("raptors", "liz-sherman"))


def test_the_outcome_names_the_card_played_even_if_it_never_reaches_the_discard_and_keeps_deck_bottom_cards_apart(tmp_path):
    path = tmp_path / "decisions.jsonl"
    game = sim_game()
    journal = decision_log.DecisionJournal(path)
    me = game.players[0]
    played = me.hand[0]
    journal.decision(game, 0, "plan", MedusaAI(0), {"kind": "scheme", "card": played.title}, [{"move": 1, "chosen": True}])
    game.take_from_hand(0, played)                       # an ONGOING card leaves the hand and stays in play
    bottom = game.players[1].deck.pop()                   # Wildfire: the bottom card of the rival's deck goes to its discard
    game.players[1].discard.append(bottom)
    game.turn_no += 1
    journal.settle(game)
    out = records(path)[-1]
    assert out["t"] == "outcome" and out["own_cards_spent"] == [played.title]
    assert out["rival_cards_played"] == [] and out["rival_deck_bottom_discards"] == [bottom.title]


def test_resuming_keeps_the_game_id_and_the_numbering(tmp_path):
    path = tmp_path / "decisions.jsonl"
    ai = journaled_game(path, "heuristic", turns=2)
    before = ai.journal.game_id, ai.journal.seq
    ai.journal.resume(sim_game(), 0, ai)
    line = records(path)[-1]
    assert line["t"] == "resume" and line["game"] == before[0] and line["seq"] == before[1] and ai.journal.seq == before[1]
    fresh = decision_log.DecisionJournal(path)
    fresh.resume(sim_game(), 0, ai)
    assert records(path)[-1]["t"] == "game" and records(path)[-1]["resumed"] is True


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


def test_several_cards_taken_off_the_deck_bottom_in_one_window_are_told_apart(tmp_path):
    path = tmp_path / "decisions.jsonl"
    game = sim_game()
    journal = decision_log.DecisionJournal(path)
    journal.decision(game, 0, "plan", MedusaAI(0), {"kind": "maneuver"}, [{"move": 1, "chosen": True}])
    rival = game.players[1]
    first, second = rival.deck.pop(), rival.deck.pop()
    played = rival.hand[0]
    game.take_from_hand(1, played)
    rival.discard.extend([first, played, second])
    game.turn_no += 1
    journal.settle(game)
    out = records(path)[-1]
    assert sorted(out["rival_deck_bottom_discards"]) == sorted([first.title, second.title])
    assert out["rival_cards_played"] == [played.title]


def test_review_joins_a_game_resumed_in_another_process(tmp_path):
    path = tmp_path / "decisions.jsonl"
    head = {"bot_hero": "Raptor Blue", "rival_hero": "Liz Sherman", "ai": "heuristic"}
    dec = {"t": "decision", "player": 0, "kind": "plan", "ai": "heuristic", "turn": 1, "chosen": {}, "alternatives": []}
    lines = [{"t": "game", "game": "a", **head}, {**dec, "game": "a", "seq": 1}, {**dec, "game": "a", "seq": 2},
             {"t": "game", "game": "b", "resumed": True, **head}, {**dec, "game": "b", "seq": 1},
             {"t": "outcome", "game": "b", "seq": 1}, {"t": "game", "game": "c", "bot_hero": "Other", "rival_hero": "Liz Sherman", "ai": "heuristic"}]
    path.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    games = review_decisions.read_games(path)
    assert set(games) == {"a", "c"} and sorted(games["a"]["decisions"]) == [1, 2, 3] and 3 in games["a"]["outcomes"]


def test_the_heuristic_scores_every_listed_alternative_with_the_value_that_decided(tmp_path):
    """Two actions left: the choice is the best first action plus the best second one, so the listed score is that total (the
    chosen one is the highest), and the journal says how it chose; the ranking's own score stays beside it."""
    path = tmp_path / "decisions.jsonl"
    journaled_game(path, "heuristic", turns=6)
    plans = [r for r in records(path) if r["t"] == "decision" and r["kind"] == "plan"]
    assert {p["via"] for p in plans} <= {"ranked", "lethal", "two_actions"} and any(p["via"] == "two_actions" for p in plans)
    for p in plans:
        chosen = next(a for a in p["alternatives"] if a.get("chosen"))
        if p["via"] == "two_actions":
            assert p["expected"] == pytest.approx(chosen["score"], abs=1e-3)
            assert all(chosen["score"] >= a["score"] - 1e-6 for a in p["alternatives"])
            assert all("one_step" in a for a in p["alternatives"])


def test_a_team_journal_line_carries_the_hit_points_of_every_fighter(tmp_path):
    path = tmp_path / "decisions.jsonl"
    journaled_game(path, "heuristic", turns=2)
    own = next(r for r in records(path) if r["t"] == "decision")["own"]
    assert len(own["fighters"]) == 3 and all(isinstance(hp, int) for hp in own["fighters"].values())


def test_the_fallen_leader_of_a_team_shows_zero_hit_points():
    from ai_positions import build, make_ai
    game = build("raptors_liz_t1_opening", make_ai("heuristic"))
    blue = next(f for f in game.own(0) if f.hero)
    blue.alive = False        # a fallen fighter keeps the hit points it fell with
    side = decision_log._side(game, 0)
    assert blue.hp > 0 and side["fighters"][blue.fid] == 0 and side["hero_hp"] > 0 and sum(side["fighters"].values()) > 0
