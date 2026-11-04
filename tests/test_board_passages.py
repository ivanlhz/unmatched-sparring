"""Secret passages (padlock spaces): a fighter moves between them in one step, but they are not adjacent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sparring.board import Board

ROOT = Path(__file__).resolve().parents[1]
PADLOCKS = [0, 10, 21, 31]


@pytest.fixture(scope="module")
def manor():
    return Board.load("baskerville-manor")


def line_map(tmp_path, passages=None):
    """0-1-2 and 3-4-5, the two lines apart; a passage may join 0 and 5."""
    spaces = [{"id": i, "local": [float(i), 0.0], "zones": ["red"],
               "adj": {0: [1], 1: [0, 2], 2: [1], 3: [4], 4: [3, 5], 5: [4]}[i]} for i in range(6)]
    data = {"key": "t", "name": "T", "starts": {"1": 0, "2": 5}, "spaces": spaces}
    if passages is not None:
        data["passages"] = passages
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return Board.load(path)


def test_baskerville_padlocks_are_linked_for_movement_but_not_adjacent(manor):
    assert manor.passages == ((0, 10, 21, 31),)
    for a in PADLOCKS:
        for b in PADLOCKS:
            if a != b:
                assert not manor.adjacent(a, b) and not manor.can_reach_target(a, b, ranged=False)
                assert b in manor.moves[a] and manor.distance(a, b) == 1
                assert b in manor.reachable(a, 1, own=set(), enemy=set())


def test_baskerville_is_connected_once_passages_count(manor):
    assert all(manor.distance(0, s) < 99 for s in manor.spaces)
    assert len(manor.adj[31]) == 1          # the padlock at 31 only reaches the others through its passage


def test_adjacency_is_left_as_the_map_draws_it(manor):
    raw = json.loads((ROOT / "data" / "maps" / "baskerville-manor.json").read_text(encoding="utf-8"))
    drawn = {s["id"]: set(s["adj"]) for s in raw["spaces"]}
    assert all(manor.adj[i] >= n for i, n in drawn.items())
    assert not any(b in drawn[a] for a in PADLOCKS for b in PADLOCKS)


def test_movement_and_distance_cross_a_passage(tmp_path):
    b = line_map(tmp_path, [[0, 5]])
    assert b.distance(2, 3) == 5          # 2-1-0 ~ 5-4-3
    assert 5 in b.reachable(0, 1, set(), set())
    assert b.reachable(2, 2, set(), set()) == {1, 0}
    assert b.reachable(2, 3, set(), set()) == {1, 0, 5}
    assert not b.adjacent(0, 5) and not b.can_reach_target(0, 5, ranged=False)


def test_ranged_by_adjacency_does_not_cross_a_passage(tmp_path):
    b = line_map(tmp_path, [[0, 5]])
    b.spaces[5] = type(b.spaces[5])(5, b.spaces[5].local, frozenset({"blue"}))      # no zone shared with space 0
    assert not b.can_reach_target(0, 5, ranged=True)
    assert 5 not in b.adj[0] and 0 not in b.adj[5]


def test_an_enemy_on_a_padlock_blocks_passing_through_it(tmp_path):
    b = line_map(tmp_path, [[2, 3]])
    assert b.reachable(0, 4, set(), set()) == {1, 2, 3, 4}
    assert b.reachable(0, 4, set(), enemy={2}) == {1}                         # the padlock at 2 is the only way across
    assert b.reachable(0, 4, set(), enemy={3}) == {1, 2}                      # an enemy on the exit padlock stops it too
    assert b.reachable(0, 4, set(), enemy={2}, through_enemies=True) >= {3, 4}
    assert b.reachable(0, 4, own={2}, enemy=set()) == {1, 3, 4}               # own fighters can be passed


def test_a_map_without_passages_behaves_as_before(tmp_path):
    b = line_map(tmp_path)
    assert b.passages == () and b.moves == b.adj
    assert b.distance(0, 3) == 99
    assert b.reachable(0, 5, set(), set()) == {1, 2}
