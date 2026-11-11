import pytest

from sparring.board import Board
from sparring.state import Game, RuleError
from conftest import give, place


@pytest.mark.parametrize("key,n", [("bprd-hq", 32), ("azuchi-castle", 31)])
def test_maps_load_symmetric_with_zones(key, n):
    b = Board.load(key)
    assert len(b.spaces) == n
    for a, ns in b.adj.items():
        assert a not in ns
        for x in ns:
            assert a in b.adj[x]
    assert all(b.zones(s) for s in b.spaces)
    assert all(b.distance(0, s) < 99 for s in b.spaces)


def test_multi_zone_space(bprd):
    assert bprd.zones(4) == {"blue", "gray", "brick"}


def test_movement_rules(bprd):
    b = bprd
    # 0 - 2 - 4 in a chain (0-2 and 2-4 adjacent); 0-4 are not adjacent
    assert 4 not in b.adj[0]
    r = b.reachable(0, 1, own=set(), enemy=set())
    assert r == b.adj[0]
    # does not end on a space occupied by its own, but passes through it
    r = b.reachable(0, 2, own={2}, enemy=set())
    assert 2 not in r and 4 in r
    # does not pass through a rival
    assert 4 not in b.reachable(0, 2, own=set(), enemy={2, 3})
    assert 4 in b.reachable(0, 2, own=set(), enemy={2})  # going around via 3
    # with an effect (Winged Frenzy) it passes through, but does not end on top of it
    r = b.reachable(0, 2, own=set(), enemy={2}, through_enemies=True)
    assert 4 in r and 2 not in r


def test_enemy_blocks_only_chokepoint(bprd):
    b = bprd
    # 3 only connects with 0 and 4: with a rival on 0 you have to go through 4 and not pass through 0
    r = b.reachable(3, 1, own=set(), enemy={0})
    assert r == {4}


def test_attack_reach(bprd):
    b = bprd
    assert b.can_reach_target(0, 1, ranged=False)
    shared = next((a, c) for a in b.spaces for c in b.spaces if a != c and not b.adjacent(a, c) and b.share_zone(a, c))
    assert b.can_reach_target(*shared, ranged=True)
    assert not b.can_reach_target(*shared, ranged=False)
    far = next((a, c) for a in b.spaces for c in b.spaces if not b.share_zone(a, c) and not b.adjacent(a, c))
    assert not b.can_reach_target(*far, ranged=True)


def test_setup_state(game):
    assert game.hero(0).name == "Medusa" and game.hero(0).hp == 16
    assert [f.name for f in game.own(0)].count("Harpy") == 3
    assert game.hero(1).hp == 18 and game.hero_named("Hellboy").move == 2
    lob = game.fighters["lobster"]
    assert lob.hp == 6 and lob.ranged
    assert game.fighters["medusa"].pos == game.board.starts["1"]
    assert game.fighters["hellboy"].pos == game.board.starts["2"]
    assert len({f.pos for f in game.fighters.values()}) == 6


def test_new_game_hands_and_decks(bprd):
    g = Game.new(bprd, seed=5, controllers={})
    assert all(len(p.hand) == 5 and len(p.deck) == 25 for p in g.players)
    g.begin_turn()
    assert g.actions_left == 2


def test_legal_move_through_own_not_through_enemy(game):
    place(game, medusa=0, harpy1=2, harpy2=20, harpy3=21, hellboy=1, lobster=15)
    assert 4 in game.legal_moves(game.fighters["medusa"], 2)
    place(game, harpy1=20, hellboy=2, lobster=3)
    assert 4 not in game.legal_moves(game.fighters["medusa"], 2)
    with pytest.raises(RuleError):
        game.move_fighter(game.fighters["medusa"], 2, 3)


def test_exhaustion_damages_each_own_fighter(game):
    game.players[0].deck.clear()
    drawn = game.draw(0)
    assert drawn == []
    assert game.hero(0).hp == 14
    assert all(h.hp <= 0 and not h.alive for h in game.own(0, alive_only=False) if h.name == "Harpy")
    assert game.players[1].deck  # the rival is not affected
    assert game.fighters["hellboy"].hp == 18


def test_exhaustion_can_defeat_hero(game):
    game.players[1].deck.clear()
    game.fighters["lobster"].hp = 2
    game.draw(1)
    assert not game.fighters["lobster"].alive and game.fighters["hellboy"].hp == 16
    game.fighters["hellboy"].hp = 2
    game.draw(1)
    assert game.winner == 0


def test_end_turn_discards_to_seven(game):
    for t in ["Snipe", "Snipe", "Snipe", "Dash", "Dash", "Dash", "Regroup", "Regroup", "Regroup"]:
        nth = sum(1 for c in game.players[0].hand if c.title == t)
        give(game, 0, t, nth)
    game.end_turn()
    assert len(game.players[0].hand) == 7 and len(game.players[0].discard) == 2
    assert game.turn == 1


def test_maneuver_draws_then_moves_with_boost(game):
    place(game, medusa=0)
    boost = give(game, 0, "Gaze of Stone")  # boost 4
    hand_before = len(game.players[0].hand)
    dests = game.legal_moves(game.fighters["medusa"], 7)
    far = max(dests, key=lambda s: game.board.distance(0, s))
    assert game.board.distance(0, far) > 3
    game.maneuver(0, {"medusa": far}, boost_card=boost)
    assert game.fighters["medusa"].pos == far
    assert len(game.players[0].hand) == hand_before  # +1 draw, -1 boost
    assert boost in game.players[0].discard and game.actions_left == 1


def test_maneuver_without_boost_limited(game):
    place(game, medusa=0)
    far = max(game.legal_moves(game.fighters["medusa"], 7), key=lambda s: game.board.distance(0, s))
    with pytest.raises(RuleError):
        game.maneuver(0, {"medusa": far})


def test_nearest_free_prefers_same_zone(bprd):
    start = 3
    nxt = bprd.nearest_free(start, {start}, zone_of=start)
    assert bprd.share_zone(start, nxt)
    other = min((s for s in bprd.spaces if s != start and not bprd.share_zone(start, s)),
                key=lambda s: bprd.distance(start, s))
    taken = {s for s in bprd.spaces if bprd.share_zone(start, s)}
    assert bprd.nearest_free(start, taken, zone_of=start) == other  # with no free slot in the zone, falls to the nearest one


def _raw(n=4, **extra):
    return {"key": "t", "name": "T", "starts": {"1": 0, "2": 1}, **extra,
            "spaces": [{"id": i, "local": [float(i), 0.0], "zones": ["red"], "adj": [j for j in (i - 1, i + 1) if 0 <= j < n]} for i in range(n)]}


def test_the_center_is_computed_from_the_graph_and_passages_and_one_way_edges_count():
    assert Board.from_raw(_raw(5)).center == (2,)                                  # 0-1-2-3-4: the middle
    assert Board.from_raw(_raw(4)).center == (1, 2) and Board.from_raw(_raw(4)).eccentricity == {0: 3, 1: 2, 2: 2, 3: 3}
    assert Board.from_raw(_raw(4, passages=[[0, 3]])).center == (0, 1, 2, 3)      # a passage shortens the walk
    assert Board.from_raw(_raw(3, one_way=[[0, 1]])).center == (0,)               # from 0 all is reachable; 1 and 2 cannot get back


def test_the_maps_own_center_replaces_the_computed_one_and_a_bad_one_is_rejected():
    assert Board.from_raw(_raw(5, center=[0, 4])).center == (0, 4)
    for bad in ([9], [1, 1], ["1"]):
        with pytest.raises(ValueError):
            Board.from_raw(_raw(5, center=bad))


@pytest.mark.parametrize("key, center", [
    ("bprd-hq", (14,)), ("baskerville-manor", (0, 10, 23, 31)), ("point-pleasant", (0, 1, 2, 3)),
    ("king-solomons-mine", (0, 2, 4, 5, 9, 10, 11, 18, 25))])
def test_the_computed_center_of_the_real_maps_matches_the_reference_site(key, center):
    assert Board.load(key).center == center
