"""Hazard edges: the first time in a turn a fighter crosses one it takes the edge's damage (once per turn in all), whoever's turn it is."""
from __future__ import annotations

import json

from conftest import Scripted, place
from sparring.ai_medusa import MedusaAI, Model
from sparring.board import Board, edge_key
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game

# bprd-hq around Medusa's start: 0-1, 0-2, 0-3, 1-2, 2-4, 3-4
HAZARDS = {edge_key(0, 2): 1, edge_key(0, 3): 2}


def duel(hazards=None, medusa=0, hellboy=15):
    g = Game.new(Board.load("bprd-hq"), seed=3, controllers={0: Scripted(), 1: Scripted()})
    g.board.hazards = dict(HAZARDS if hazards is None else hazards)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    place(g, medusa=medusa, hellboy=hellboy, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return g, g.fighters["medusa"]


def test_the_board_reads_hazards_from_its_data(tmp_path):
    adj = {0: [1], 1: [0, 2], 2: [1]}
    data = {"key": "t", "name": "T", "starts": {"1": 0, "2": 2}, "hazards": [{"edge": [2, 1], "damage": 2}],
            "spaces": [{"id": i, "local": [float(i), 0.0], "zones": ["red"], "adj": adj[i]} for i in range(3)]}
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    board = Board.load(path)
    assert board.hazards == {(1, 2): 2} and board.adjacent(1, 2) and not Board.load("bprd-hq").hazards


def test_the_mover_takes_the_way_with_least_damage():
    g = Board.load("bprd-hq")
    g.hazards = dict(HAZARDS)
    assert g.hazard_path(0, 4, 2) == [edge_key(0, 2)]                 # 0-2-4 costs 1, 0-3-4 costs 2
    g.hazards = {edge_key(0, 2): 3, edge_key(0, 3): 1}
    assert g.hazard_path(0, 4, 2) == [edge_key(0, 3)]
    assert g.hazard_path(0, 4, 2, hurt=True) == []                     # already hurt this turn: nothing more to pay
    assert g.hazard_path(0, 1, 2) == []                                # 0-1 is free
    assert g.hazard_path(0, 4, 2, blocked=frozenset({3})) == [edge_key(0, 2)]
    assert g.hazard_path(0, 0, 2) == [] and Board.load("bprd-hq").hazard_path(0, 4, 2) == []


def test_a_fighter_is_hurt_by_hazard_edges_once_per_turn_in_total():
    g, med = duel()
    hp = med.hp
    g.move_fighter(med, 2, 1)
    assert med.hp == hp - 1 and g.hazard_hits == [("medusa", edge_key(0, 2), 1, hp)]
    g.move_fighter(med, 0, 1)                                           # the same edge again, same turn: free
    g.move_fighter(med, 2, 1)
    assert med.hp == hp - 1
    g.move_fighter(med, 0, 1)
    g.move_fighter(med, 3, 1)                                           # another hazard edge: still free, one hurt per turn in all
    assert med.hp == hp - 1 and len(g.hazard_hits) == 1


def test_the_edge_hurts_again_the_next_turn_and_both_players_pay():
    g, med = duel()
    g.move_fighter(med, 2, 1)
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    hp = med.hp
    g.move_fighter(med, 0, 1)
    assert med.hp == hp - 1, "a new turn clears what was paid, even if it is the rival's turn"


def test_a_hazard_can_defeat_the_fighter_and_the_hero_loses_the_game():
    g, med = duel()
    med.hp = 1
    g.move_fighter(med, 2, 1)
    assert not med.alive and g.winner == 1


def test_a_move_without_hazards_changes_nothing():
    g, med = duel(hazards={})
    hp = med.hp
    g.move_fighter(med, 2, 1)
    assert med.hp == hp and not g.hazard_hits and not g.hazard_taken


def test_a_placement_is_not_a_move():
    g, med = duel()
    hp = med.hp
    g.place_fighter(med, 4)
    assert med.hp == hp


def test_hazard_damage_is_known_before_moving_and_the_clone_keeps_what_was_paid():
    g, med = duel()
    assert g.hazard_damage(med, 2, 1) == 1 and g.hazard_damage(med, 4, 2) == 1
    g.move_fighter(med, 2, 1)
    assert g.hazard_damage(med, 0, 1) == 0 and g.hazard_damage(med, 3, 1) == 0
    clone = g.clone()
    assert clone.hazard_taken == g.hazard_taken and clone.hazard_hits == []


def test_what_was_paid_survives_a_save():
    g, med = duel()
    g.move_fighter(med, 2, 1)
    saved = json.loads(json.dumps(game_to_dict(g)))
    other, _ = duel()
    apply_game(other, saved)
    assert other.hazard_taken == g.hazard_taken
    assert "hazard_taken" not in game_to_dict(duel()[0])


def test_an_old_save_with_fighter_and_edge_pairs_still_loads():
    g, _ = duel()
    saved = json.loads(json.dumps(game_to_dict(g)))
    saved["hazard_taken"] = [["medusa", [0, 2]], ["hellboy", [0, 3]]]
    apply_game(g, saved)
    assert g.hazard_taken == {"medusa", "hellboy"}


def test_the_least_damage_path_pays_only_its_first_hazard_edge():
    g, med = duel(hazards={edge_key(0, 2): 2, edge_key(2, 4): 3, edge_key(0, 3): 3, edge_key(3, 4): 3})
    assert g.board.hazard_path(0, 4, 2) == [edge_key(0, 2)]            # 0-2-4 would cost 5 per edge, now the first edge: 2
    hp = med.hp
    g.move_fighter(med, 4, 2)
    assert med.hp == hp - 2 and len(g.hazard_hits) == 1


def test_the_real_pandemonium_hazards_load_and_are_charged_once():
    b = Board.load("pandemonium")
    assert b.hazards == {edge_key(*e): 1 for e in [(16, 13), (18, 9), (8, 10), (10, 7), (5, 4), (27, 2), (26, 2)]}
    g = Game.new(b, seed=3, controllers={0: Scripted(), 1: Scripted()})
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    place(g, medusa=2, hellboy=15, harpy1=20, harpy2=21, harpy3=22, lobster=1)
    med = g.fighters["medusa"]
    path = b.hazard_path(2, 28, None)
    assert path == [] or len(path) == 1                                # a free equally short way is taken if there is one
    assert g.hazard_damage(med, 28, None, True) == (1 if path else 0)
    hp = med.hp
    g.walk(med, 28, None, True)
    assert med.hp == hp - len(path)


def test_the_bot_does_not_walk_into_a_hazard_for_a_small_gain(monkeypatch):
    into_two = {edge_key(0, 2): 2, edge_key(1, 2): 2, edge_key(2, 4): 2}
    g, med = duel(hazards={})
    ai = MedusaAI(0)
    monkeypatch.setattr(ai, "position_value", lambda game, model, where: 1.0 if where[med.fid] == 2 else 0.0)
    assert ai.best_dest(g, Model(g, 0), med, 3, False) == 2
    g.board.hazards = into_two                                              # 2 costs 2 HP now: not worth 1 point
    assert ai.best_dest(g, Model(g, 0), med, 3, False) != 2


def test_a_human_move_with_blockers_pays_for_the_way_that_is_open():
    g, _ = duel(hazards={})
    b = g.board
    for src in sorted(b.spaces):
        for dst in sorted(b.spaces):
            mids = [m for m in b.moves[src] if dst in b.moves[m]] if b.distance(src, dst) == 2 else []
            alts = [(x, y) for x in b.moves[src] if len(mids) == 1 and x != mids[0] for y in b.moves[x]
                    if y not in (src, mids[0]) and dst in b.moves[y]]
            if alts:
                x, y = alts[0]
                b.hazards = {edge_key(y, dst): 3}
                free = [q for q in sorted(b.spaces) if q not in {src, dst, mids[0], x, y}]
                place(g, hellboy=src, medusa=mids[0], lobster=free[0], harpy1=free[1], harpy2=free[2], harpy3=free[3])
                hb = g.fighters["hellboy"]
                hp = hb.hp
                g.walk(hb, dst, None)
                assert hb.hp == hp - 3, "the only open way crosses the hazard"
                return
    raise AssertionError("no such place on bprd-hq")


def test_the_hit_records_the_hp_before_and_the_damage_really_dealt(monkeypatch):
    g, med = duel(hazards={edge_key(0, 2): 2, edge_key(2, 4): 3, edge_key(0, 3): 3, edge_key(3, 4): 3})
    monkeypatch.setattr(type(g.fx), "adjust_damage", lambda self, f, n, source: n - 1)        # an effect that softens every hit by 1
    hp = med.hp
    g.move_fighter(med, 4, 2)
    assert g.hazard_hits == [("medusa", edge_key(0, 2), 1, hp)]


def test_a_hit_that_is_prevented_is_not_recorded(monkeypatch):
    g, med = duel()
    monkeypatch.setattr(type(g.fx), "adjust_damage", lambda self, f, n, source: 0)
    g.move_fighter(med, 2, 1)
    assert g.hazard_hits == [] and med.hp == med.max_hp and g.hazard_taken


def test_a_board_rejects_bad_hazards(tmp_path):
    adj = {0: [1], 1: [0, 2], 2: [1]}
    for bad in ([{"edge": [0, 2], "damage": 1}], [{"edge": [0, 1], "damage": 0}], [{"edge": [0, 1], "damage": 4}],
                [{"edge": [0, 1], "damage": 1.5}], [{"edge": [0, 1], "damage": 1}, {"edge": [1, 0], "damage": 2}],
                [{"edge": [0, 9], "damage": 1}], [{"damage": 1}]):
        data = {"key": "t", "name": "T", "starts": {"1": 0, "2": 2}, "hazards": bad,
                "spaces": [{"id": i, "local": [float(i), 0.0], "zones": ["red"], "adj": adj[i]} for i in range(3)]}
        path = tmp_path / "t.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            Board.load(path)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_a_clone_can_begin_a_turn_and_walk_across_a_hazard_without_announcing():
    g, med = duel()
    g.placing.add("lobster")
    g.hazard_hook = lambda: (_ for _ in ()).throw(AssertionError("a clone must never announce"))
    c = g.clone()
    assert c.placing == {"lobster"} and c.placing is not g.placing and c.hazard_hook is None
    c.end_turn()
    c.begin_turn()
    assert c.placing == set()
    cm = c.fighters["medusa"]
    hp = cm.hp
    c.move_fighter(cm, 2, 1)
    assert cm.hp == hp - 1 and med.hp == hp


def test_a_pending_hand_placement_survives_a_save():
    g, _ = duel()
    g.placing.add("lobster")
    other, _ = duel()
    apply_game(other, json.loads(json.dumps(game_to_dict(g))))
    assert other.placing == {"lobster"} and "placing" not in game_to_dict(duel()[0])
