"""One-way edges: movement crosses them from -> to only; the spaces stay adjacent both ways (attacks, adjacency effects)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sparring.board import Board

ROOT = Path(__file__).resolve().parents[1]


def line(tmp_path, one_way=None):
    """0-1-2-3 in a row."""
    adj = {0: [1], 1: [0, 2], 2: [1, 3], 3: [2]}
    data = {"key": "t", "name": "T", "starts": {"1": 0, "2": 3},
            "spaces": [{"id": i, "local": [float(i), 0.0], "zones": ["red"], "adj": adj[i]} for i in range(4)]}
    if one_way is not None:
        data["one_way"] = one_way
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return Board.load(path)


def test_movement_goes_only_from_to(tmp_path):
    b = line(tmp_path, [[1, 2]])
    assert b.reachable(0, 3, set(), set()) == {1, 2, 3}
    assert b.reachable(3, 3, set(), set()) == {2}                 # 2 -> 1 is closed
    assert 1 not in b.reachable(2, 1, set(), set())


def test_adjacency_and_attacks_stay_symmetric(tmp_path):
    b = line(tmp_path, [[1, 2]])
    assert b.adjacent(1, 2) and b.adjacent(2, 1)
    assert b.can_reach_target(1, 2, ranged=False) and b.can_reach_target(2, 1, ranged=False)
    assert b.adj[1] == {0, 2} and b.adj[2] == {1, 3}


def test_distance_is_directional(tmp_path):
    b = line(tmp_path, [[1, 2]])
    assert b.distance(0, 3) == 3 and b.distance(3, 0) == 99
    assert b.distance(1, 2) == 1 and b.distance(2, 1) == 99
    assert b.span(3, 0) == 3 and b.span(0, 3) == 3             # undirected description / placement distance


def test_a_fighter_cannot_pass_back_through_a_one_way_edge_even_with_steps_to_spare(tmp_path):
    b = line(tmp_path, [[1, 2]])
    assert b.reachable(3, 9, set(), set(), through_enemies=True) == {2}


def test_a_map_without_one_way_is_unchanged(tmp_path):
    b = line(tmp_path)
    assert b.one_way == () and b.moves == b.adj
    assert b.distance(3, 0) == 3 and b.span(3, 0) == 3


def test_nearest_free_uses_the_undirected_span(tmp_path):
    b = line(tmp_path, [[1, 2]])
    assert b.nearest_free(3, taken={3, 2}) == 1


def test_kaer_morhen_one_way_is_a_real_adjacent_pair():
    b = Board.load("kaer-morhen")
    assert b.one_way == ((11, 12),) or (11, 12) in b.one_way
    assert b.adjacent(11, 12) and b.adjacent(12, 11)
    assert 12 in b.moves[11] and 11 not in b.moves[12]
    assert b.distance(11, 12) == 1 and b.distance(12, 11) > 1
