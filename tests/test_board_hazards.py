"""Hazard edges: the first time a fighter crosses one in a turn it takes the edge's damage, whoever's turn it is."""
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
    assert g.hazard_path(0, 1, 2) == []                                # 0-1 is free
    assert g.hazard_path(0, 4, 2, blocked=frozenset({3})) == [edge_key(0, 2)]
    assert g.hazard_path(0, 0, 2) == [] and Board.load("bprd-hq").hazard_path(0, 4, 2) == []


def test_a_move_across_a_hazard_edge_hurts_once_per_turn():
    g, med = duel()
    hp = med.hp
    g.move_fighter(med, 2, 1)
    assert med.hp == hp - 1 and g.hazard_hits == [("medusa", edge_key(0, 2), 1)]
    g.move_fighter(med, 0, 1)                                           # the same edge again, same turn: free
    g.move_fighter(med, 2, 1)
    assert med.hp == hp - 1
    g.move_fighter(med, 0, 1)
    g.move_fighter(med, 3, 1)                                           # another hazard edge hurts
    assert med.hp == hp - 3


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
    assert g.hazard_damage(med, 0, 1) == 0
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


def test_the_bot_does_not_walk_into_a_hazard_for_a_small_gain(monkeypatch):
    into_two = {edge_key(0, 2): 2, edge_key(1, 2): 2, edge_key(2, 4): 2}
    g, med = duel(hazards={})
    ai = MedusaAI(0)
    monkeypatch.setattr(ai, "position_value", lambda game, model, where: 1.0 if where[med.fid] == 2 else 0.0)
    assert ai.best_dest(g, Model(g, 0), med, 3, False) == 2
    g.board.hazards = into_two                                              # 2 costs 2 HP now: not worth 1 point
    assert ai.best_dest(g, Model(g, 0), med, 3, False) != 2
