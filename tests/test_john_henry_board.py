"""John Henry's free spaces on the board (`Board.reachable(..., free=)`, `walk_cost`, `track_route`, `hazard_path(..., free=)`):
entering a track space costs no step. Without free spaces everything is the old walk."""
from __future__ import annotations

import pytest

from sparring.board import Board, edge_key


def graph(adj: dict[int, list[int]], hazards: dict | None = None) -> Board:
    raw = {"key": "t", "name": "T", "starts": {"1": 0, "2": max(adj)},
           "spaces": [{"id": i, "local": [float(i), 0.0], "zones": ["red"], "adj": adj[i]} for i in sorted(adj)]}
    if hazards:
        raw["hazards"] = [{"edge": list(e), "damage": d} for e, d in hazards.items()]
    return Board.from_raw(raw)


LINE = graph({0: [1], 1: [0, 2], 2: [1, 3], 3: [2, 4], 4: [3, 5], 5: [4]})
# a diamond: 0-1-3 and 0-2-3, then 3-4
DIAMOND = graph({0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2, 4], 4: [3]})


def test_without_free_spaces_the_walk_is_the_old_one():
    for steps in range(5):
        assert LINE.reachable(0, steps, set(), set()) == set(range(1, steps + 1))
    bprd = Board.load("bprd-hq")
    for start in (0, 3, 7):
        for steps in (1, 2, 4):
            plain = bprd.reachable(start, steps, set(), set())
            assert plain == bprd.reachable(start, steps, set(), set(), free=frozenset())
            assert plain == {s for s in bprd.spaces if 0 < bprd.distance(start, s) <= steps}


def test_a_track_space_is_not_counted_when_entered():
    free = frozenset({1, 2, 3})
    assert LINE.reachable(0, 1, set(), set(), free=free) == {1, 2, 3, 4}          # three free spaces and one counted step
    assert LINE.reachable(0, 0, set(), set(), free=free) == {1, 2, 3}             # even with no step to spend the tracks are walked
    assert LINE.reachable(0, 2, set(), set(), free=free) == {1, 2, 3, 4, 5}


def test_the_free_spaces_must_be_connected_to_be_walked_for_nothing():
    assert LINE.reachable(0, 1, set(), set(), free=frozenset({2, 3})) == {1, 2, 3}      # 1 costs a step, 2 and 3 are free, 4 would cost another
    assert LINE.reachable(0, 1, set(), set(), free=frozenset({3})) == {1}


def test_a_rival_still_blocks_a_track_space_and_nobody_ends_on_a_taken_space():
    free = frozenset({1, 2, 3})
    assert LINE.reachable(0, 3, set(), {2}, free=free) == {1}                           # the rival holds 2: no way through
    assert LINE.reachable(0, 3, {2}, set(), free=free) == {1, 3, 4, 5}                  # a friend is crossed, never landed on


def test_the_walk_cost_counts_only_the_spaces_that_are_not_free():
    assert LINE.walk_cost(0, 4, frozenset({1, 2, 3})) == 1
    assert LINE.walk_cost(0, 4) == 4
    assert LINE.walk_cost(0, 4, frozenset({1, 2, 3}), blocked=frozenset({2})) is None
    assert LINE.walk_cost(0, 0, frozenset({1})) == 0


def test_the_route_goes_through_the_most_track_spaces_of_the_cheapest_walks():
    assert DIAMOND.track_route(0, 4, frozenset({1, 3})) == frozenset({1, 3})            # 0-1-3-4: two free spaces and one step
    assert DIAMOND.track_route(0, 4, frozenset({2, 3})) == frozenset({2, 3})
    assert DIAMOND.track_route(0, 4, frozenset({1, 2, 3})) == frozenset({1, 3}) or DIAMOND.track_route(0, 4, frozenset({1, 2, 3})) == frozenset({2, 3})
    assert LINE.track_route(0, 5, frozenset({1, 2, 3, 4})) == frozenset({1, 2, 3, 4})
    assert LINE.track_route(0, 3, frozenset()) == frozenset()
    assert LINE.track_route(3, 0, frozenset({1, 2})) == frozenset({1, 2})               # also backwards
    assert LINE.track_route(0, 3, frozenset({1, 2}), blocked=frozenset({2})) == frozenset()


def test_a_dearer_walk_through_more_tracks_is_not_taken():
    # 0-1-2-3 with tracks on 1,2 and a shortcut 0-3: the cheapest walk to 3 is the shortcut (1 step) or 1,2 free then 3 (1 step): both cost 1
    board = graph({0: [1, 3], 1: [0, 2], 2: [1, 3], 3: [0, 2]})
    assert board.walk_cost(0, 3, frozenset({1, 2})) == 1
    assert board.track_route(0, 3, frozenset({1, 2})) == frozenset({1, 2})              # a tie in cost: the walk with more tracks
    assert board.track_route(0, 3, frozenset({1})) == frozenset()                 # the shortcut is cheaper than the walk by the one track


def test_hazard_edges_on_track_spaces_are_still_crossed():
    board = graph({i: [j for j in (i - 1, i + 1) if 0 <= j <= 5] for i in range(6)}, hazards={edge_key(3, 4): 2})
    assert board.hazard_path(0, 5, 5) == [edge_key(3, 4)]
    assert board.hazard_path(0, 5, 2, free=frozenset({1, 2, 3, 4})) == [edge_key(3, 4)]     # free spaces cost no step, the edge is crossed
    assert board.hazard_path(0, 3, None, free=frozenset({1, 2, 3, 4})) == []
    assert board.hazard_path(0, 5, None, free=frozenset({1, 2, 3, 4})) == [edge_key(3, 4)]   # the cheapest walk: no step budget given
    assert board.hazard_path(0, 5, None, free=frozenset({1, 2, 3, 4}), hurt=True) == []


def test_the_hazard_walk_with_free_spaces_may_take_the_longer_way_with_less_damage():
    # 0-1-2 and 0-3-4-2: the direct way crosses the hazard 1-2, the long way is clean but costs 3 steps unless 3 and 4 are free
    board = graph({0: [1, 3], 1: [0, 2], 2: [1, 4], 3: [0, 4], 4: [3, 2]}, hazards={edge_key(1, 2): 3})
    assert board.hazard_path(0, 2, 2) == [edge_key(1, 2)]
    assert board.hazard_path(0, 2, 2, free=frozenset({3, 4})) == []


@pytest.mark.parametrize("steps", [0, 1, 2])
def test_hazard_path_is_unchanged_without_free_spaces(steps):
    bprd = Board.load("bprd-hq")
    bprd.hazards = {edge_key(0, 2): 1, edge_key(0, 3): 2}
    assert bprd.hazard_path(0, 4, 2 + steps) == bprd.hazard_path(0, 4, 2 + steps, free=frozenset())


def test_the_paths_of_a_walk_are_its_edges_and_the_cheapest_walk_through_the_most_new_ones_is_taken():
    assert LINE.edge_route(0, 3, frozenset()) == {edge_key(0, 1), edge_key(1, 2), edge_key(2, 3)}       # no track needed
    assert LINE.edge_route(3, 0, frozenset()) == LINE.edge_route(0, 3, frozenset())                     # an edge has no direction
    assert LINE.edge_route(2, 2, frozenset({1})) == frozenset()
    assert LINE.edge_route(0, 3, frozenset(), blocked=frozenset({2})) == frozenset()
    board = graph({0: [1, 3], 1: [0, 2], 2: [1, 3], 3: [0, 2]})                                         # a ring of four
    assert board.edge_route(0, 3, frozenset()) == {edge_key(0, 3)}                                      # the shortcut is the only 1-step walk
    long_way = {edge_key(0, 1), edge_key(1, 2), edge_key(2, 3)}
    assert board.edge_route(0, 3, frozenset({1, 2})) == long_way                                        # same cost over the tracks: more edges
    assert DIAMOND.edge_route(0, 3, frozenset(), known=frozenset({edge_key(0, 1), edge_key(1, 3)})) == {edge_key(0, 2), edge_key(2, 3)}


TRIANGLE = graph({0: [1, 2, 3], 1: [0, 2], 2: [0, 1], 3: [0]})          # 0-1-2 a triangle, 3 a tail off 0


def test_the_most_paths_go_round_a_loop_of_free_spaces_and_may_end_where_they_began():
    ring = {edge_key(0, 1), edge_key(1, 2), edge_key(0, 2)}
    assert TRIANGLE.most_paths(0, 0, frozenset({0, 1, 2}), frozenset(), 0) == ring                       # all free: round for nothing
    assert TRIANGLE.most_paths(0, 0, frozenset({1, 2}), frozenset(), 0) == frozenset()                    # back onto 0 costs a step
    assert TRIANGLE.most_paths(0, 0, frozenset({1, 2}), frozenset(), 1) == ring
    assert TRIANGLE.most_paths(3, 3, frozenset({0, 1, 2}), frozenset(), 1) == ring | {edge_key(0, 3)}     # out, round, back
    assert TRIANGLE.most_paths(0, 0, frozenset({1, 2}), frozenset({2}), 1) == {edge_key(0, 1)}            # blocked: there and back on one edge
    assert TRIANGLE.most_paths(0, 1, frozenset(), frozenset(), 0) == frozenset()                          # out of reach
    assert TRIANGLE.most_paths(0, 0, frozenset({0, 1, 2}), frozenset(), 0, known=ring) == frozenset()     # nothing new
    assert len(TRIANGLE.most_paths(3, 3, frozenset({0, 1, 2}), frozenset(), 1, cap=2)) >= 2


def test_the_most_paths_never_cross_an_edge_to_avoid_and_say_what_they_spend():
    free = frozenset({0, 1, 2})
    assert TRIANGLE.most_paths(0, 0, free, frozenset(), 0, avoid=frozenset({edge_key(1, 2)})) == {edge_key(0, 1), edge_key(0, 2)}
    got, spent = TRIANGLE.most_paths_walk(3, 3, free, frozenset(), 1)
    assert edge_key(0, 3) in got and spent == 1                                   # back onto the untracked 3: one step
    assert TRIANGLE.most_paths_walk(0, 1, frozenset(), frozenset(), 0) == (frozenset(), None)
