"""John Henry on the engine, bot side (player 0 plays him, the controllers answer): STEEL-DRIVING MAN (a track token at the start of his turn,
the track spaces not counted when he moves, the paths (edges) he crossed), every card of his deck with the numbers printed on it, the free action
that only an attack can spend, and the state (clone, save). The human side (panel, FakeTTS) is in tests/test_john_henry_human.py and the
full games in tests/test_john_henry_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import tracks
from sparring.ai_john import pick_track_space, strike_cost
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers, start_turn
from test_effects_combat import hp

HAMMERS = ["Nine-pound Hammer", "Twelve-pound Hammer", "Eighteen-pound Hammer"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """John Henry = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands, no track token yet."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("john-henry", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.tracks, g.fx.paths = [[], []], []
    return g


def chain(board, n, start=None):
    """n spaces in a row: each one adjacent to the next and no shortcut between two of them (a shortest walk along them)."""
    def grow(path):
        if len(path) == n:
            return path
        for s in sorted(board.adj[path[-1]]):
            if s not in path and all(board.distance(p, s) == len(path) - i for i, p in enumerate(path)):
                got = grow(path + [s])
                if got:
                    return got
        return None
    for a in ([start] if start is not None else sorted(board.spaces)):
        got = grow([a])
        if got:
            return got
    raise AssertionError(f"no chain of {n} spaces")


def stage(g, row, foes_at=None):
    """John Henry on row[0]; every opposing fighter far from the row (or at `foes_at`: {fid: space}); his own fighters stay where they are."""
    john = g.fighters["john"]
    john.pos = row[0]
    far = sorted((s for s in g.board.spaces if s not in row and not g.board.share_zone(row[0], s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f is not john], far):
        f.pos = s
    for fid, s in (foes_at or {}).items():
        g.fighters[fid].pos = s
    return john


def to_discard(g, player, *titles):
    """Cards of the deck straight into the discard pile (what a played card does at the end of its combat)."""
    st = g.players[player]
    for title in titles:
        c = next(c for c in st.full_set if c.title == title and c not in st.discard)
        for zone in (st.deck, st.hand):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)


def lay(g, spaces, player=0):
    for s in spaces:
        assert tracks.add(g, player, s)


# ---------------------------------------------------------------- the hero

def test_john_henry_is_a_lone_melee_hero_with_seventeen_life_and_a_deck_of_his_own(bprd):
    g = mk(bprd)
    john = g.fighters["john"]
    assert (john.hp, john.move, john.ranged, john.name, john.hero) == (17, 2, False, "John Henry", True)
    assert [f.fid for f in g.fighters.values() if f.owner == 0] == ["john"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 18700 and deck[-1].card_id == 18729
    assert "john-henry" in g.fx.dsl_heroes
    assert sum("hammer" in c.tags for c in deck) == 7


# ---------------------------------------------------------------- the tokens

def test_a_track_token_is_summoned_in_his_zone_at_the_start_of_his_turn(bprd):
    g = mk(bprd)
    john = g.fighters["john"]
    g.turn = 0
    g.begin_turn()
    (space,) = g.fx.tracks[0]
    assert g.board.share_zone(john.pos, space) and tracks.left(g, 0) == 9


def test_his_own_space_is_in_his_zone_and_a_space_with_a_fighter_takes_a_token_too(bprd):
    g = mk(bprd)
    john = g.fighters["john"]
    zone = [s for s in g.board.spaces if g.board.share_zone(john.pos, s)]
    assert john.pos in zone
    from sparring.effects.plugins_john import summon_options
    assert john.pos in summon_options(g, 0)
    assert set(summon_options(g, 0)) == set(zone)


def test_one_token_per_turn_never_two_on_a_space_and_none_on_the_rivals_turn(bprd):
    g = mk(bprd)
    john = g.fighters["john"]
    zone = [s for s in g.board.spaces if g.board.share_zone(john.pos, s)]
    seen = []
    for turn in range(len(zone)):
        g.turn = 1
        g.begin_turn()
        assert len(g.fx.tracks[0]) == len(seen), "the rival's turn summons nothing"
        g.turn = 0
        g.begin_turn()
        assert len(g.fx.tracks[0]) == len(seen) + 1 and len(set(g.fx.tracks[0])) == turn + 1
        seen = list(g.fx.tracks[0])
    assert sorted(seen) == sorted(zone), "a zone he does not leave fills up, one space each"


def test_the_supply_is_ten_tokens_and_the_eleventh_is_not_summoned(bprd):
    g = mk(bprd)
    john = g.fighters["john"]
    where = sorted(g.board.spaces)
    for k in range(14):
        john.pos = where[(k * 3) % len(where)]
        g.turn = 0
        g.begin_turn()
    assert len(g.fx.tracks[0]) == tracks.SUPPLY == 10 and tracks.left(g, 0) == 0
    assert not tracks.add(g, 0, next(s for s in where if s not in g.fx.tracks[0]))


def test_a_zone_full_of_tokens_gets_no_more(bprd):
    g = mk(bprd)
    john = g.fighters["john"]
    for s in g.board.spaces:
        if g.board.share_zone(john.pos, s):
            tracks.add(g, 0, s)
    before = list(g.fx.tracks[0])
    g.turn = 0
    g.begin_turn()
    assert g.fx.tracks[0] == before


def test_the_bot_puts_the_token_where_it_shortens_most_the_walk_to_a_rival(bprd):
    g = mk(bprd)
    row = chain(bprd, 6)
    john = stage(g, row, foes_at={"hellboy": row[5]})
    options = [s for s in sorted(g.board.spaces) if g.board.share_zone(john.pos, s)]
    chosen = pick_track_space(g, 0, options)
    free = tracks.placed(g)
    best = min(strike_cost(g, 0, free | {s}) for s in options)
    assert strike_cost(g, 0, free | {chosen}) == best < strike_cost(g, 0, free)


# ---------------------------------------------------------------- moving over the tracks

def test_the_track_spaces_are_not_counted_when_he_moves_and_nobody_elses_are(bprd):
    g = mk(bprd)
    row = chain(bprd, 7)
    john = stage(g, row)
    lay(g, row[1:4])
    reach = g.legal_moves(john, 2)
    assert set(row[1:6]) <= reach and row[6] not in reach          # three free spaces, then two steps
    plain = g.board.reachable(john.pos, 2, set(), g.occupied(1))
    assert row[5] not in plain
    hellboy = g.fighters["hellboy"]
    hellboy.pos = row[0]
    john.pos = row[6]
    assert g.legal_moves(hellboy, 2) == g.board.reachable(hellboy.pos, 2, g.occupied(1) - {hellboy.pos}, g.occupied(0)), "the rival's walk costs what it always did"


def test_a_maneuver_goes_as_far_as_the_free_spaces_allow_and_not_one_more(bprd):
    g = mk(bprd)
    row = chain(bprd, 8)
    john = stage(g, row)
    lay(g, row[1:5])
    g.players[0].hand.append(g.players[0].deck.pop(0))
    assert row[6] in g.legal_moves(john, 2) and row[7] not in g.legal_moves(john, 2)
    with pytest.raises(RuleError):
        g.maneuver(0, {"john": row[7]})
    g.actions_left = 2                                          # the refused Maneuver spent its action before the walk was judged
    g.maneuver(0, {"john": row[6]})
    assert john.pos == row[6] and g.actions_left == 1


def test_a_move_effect_ignores_the_tracks_for_him_too(bprd):
    g = mk(bprd)
    row = chain(bprd, 7)
    john = stage(g, row)
    lay(g, row[1:5])
    g.controllers[0].queue = [lambda req: [row[6]]]
    g.play_scheme(0, john, give(g, 0, "Striking Fire"))
    assert john.pos == row[6]


def test_the_free_walk_pays_the_hazard_of_the_edges_it_crosses(bprd, monkeypatch):
    g = mk(bprd)
    row = chain(bprd, 6)
    john = stage(g, row)
    lay(g, row[1:5])
    monkeypatch.setattr(g.board, "hazards", {(min(row[2], row[3]), max(row[2], row[3])): 2})      # the board is shared by the whole session
    g.walk(john, row[5], None)
    assert john.hp == 15


# ---------------------------------------------------------------- the paths

def edges(row):
    """The paths (edges, `(low, high)`) of a walk along `row`."""
    return [(min(a, b), max(a, b)) for a, b in zip(row, row[1:])]


def test_his_paths_are_the_edges_he_crosses_with_or_without_tracks_on_them(bprd):
    g = mk(bprd)
    row = chain(bprd, 6)
    john = stage(g, row)
    lay(g, [row[0], row[1], row[3]])
    g.walk(john, row[4], None)                                  # 0 -> 1 -> 2 -> 3 -> 4: four edges, two of them onto untracked spaces
    assert sorted(g.fx.paths) == sorted(edges(row[:5])) and tracks.paths_used(g) == 4


def test_a_walk_without_any_track_token_also_uses_paths(bprd):
    g = mk(bprd)
    row = chain(bprd, 3)
    john = stage(g, row)
    g.walk(john, row[2], None)
    assert sorted(g.fx.paths) == sorted(edges(row)) and tracks.paths_used(g) == 2


def test_four_different_paths_make_the_hammers_test_true(bprd):
    g = mk(bprd)
    row = chain(bprd, 7)
    john = stage(g, row)
    lay(g, row[1:4])
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {"john": row[4]})                             # three free track spaces and one step: four edges at least
    assert tracks.paths_used(g) >= 4
    from sparring.effects.ops_core import plugin_test
    assert plugin_test(g, None, {"id": "john:paths", "key": "four"}) is True


def test_the_same_path_crossed_twice_counts_once_in_either_direction(bprd):
    g = mk(bprd)
    row = chain(bprd, 5)
    john = stage(g, row)
    g.walk(john, row[2], None)
    g.walk(john, row[0], None)
    g.walk(john, row[1], None)
    assert sorted(g.fx.paths) == sorted(edges(row[:3])) and tracks.paths_used(g) == 2


def test_a_placement_and_the_rivals_moves_are_no_paths_and_a_new_turn_forgets_them(bprd):
    g = mk(bprd)
    row = chain(bprd, 5)
    john = stage(g, row)
    lay(g, row[1:3])
    g.place_fighter(john, row[3])
    assert g.fx.paths == []
    g.walk(john, row[0], None)                                  # 3 -> 2 -> 1 -> 0: three edges
    assert sorted(g.fx.paths) == sorted(edges(row[:4]))
    g.turn = 1
    g.begin_turn()
    assert g.fx.paths == [] and len(g.fx.tracks[0]) == 2, "the tokens stay, the paths are of the turn"
    hellboy = g.fighters["hellboy"]
    hellboy.pos = row[4]
    g.walk(hellboy, row[3], None)
    assert g.fx.paths == []


def test_with_fewer_than_four_the_hammers_do_nothing_extra_and_the_test_says_no(bprd):
    g = mk(bprd)
    row = chain(bprd, 5)
    john = stage(g, row)
    lay(g, row[1:3])
    g.walk(john, row[3], None)
    assert tracks.paths_used(g) == 3
    from sparring.effects.ops_core import plugin_test
    assert plugin_test(g, None, {"id": "john:paths", "key": "four"}) is False


def triangle(g):
    """Three spaces each adjacent to the other two."""
    b = g.board
    for a in sorted(b.spaces):
        for x in sorted(b.adj[a]):
            for y in sorted(b.adj[a]):
                if x < y and y in b.adj[x]:
                    return [a, x, y]
    raise AssertionError("no triangle on the board")


def test_a_maneuver_that_ends_where_it_began_goes_round_a_triangle_of_tracks(bprd):
    g = mk(bprd)
    a, x, y = triangle(g)
    john = stage(g, [a, x, y])
    lay(g, [a, x, y])
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.move_fighter(john, a, 0)                                  # no step at all: round the triangle for nothing
    assert sorted(g.fx.paths) == sorted(edges([a, x, y, a])) and john.pos == a
    g.fx.paths = []
    g.maneuver(0, {"john": a})                                  # a Maneuver that leaves him where he was: the round and his 2 steps
    assert tracks.paths_used(g) >= 4 and john.pos == a


def test_staying_puts_no_loop_where_no_step_is_left_for_it(bprd):
    g = mk(bprd)
    a, x, y = triangle(g)
    john = stage(g, [a, x, y])
    lay(g, [x, y])                                              # the way back onto his untracked space costs a step
    g.move_fighter(john, a, 0)
    assert g.fx.paths == []
    g.move_fighter(john, a, 1)
    assert sorted(g.fx.paths) == sorted(edges([a, x, y, a]))


def test_a_john_henry_who_cannot_move_goes_round_no_loop(bprd, monkeypatch):
    g = mk(bprd)
    a, x, y = triangle(g)
    john = stage(g, [a, x, y])
    lay(g, [a, x, y])
    monkeypatch.setattr(type(g.fx), "can_move", lambda self, f: False)      # Burning Barrier keeps him where he is
    g.move_fighter(john, a, 2)
    assert g.fx.paths == []


def test_the_loop_does_not_cross_a_hazard_he_has_not_paid(bprd, monkeypatch):
    g = mk(bprd)
    a, x, y = triangle(g)
    john = stage(g, [a, x, y])
    lay(g, [a, x, y])
    monkeypatch.setattr(g.board, "hazards", {(min(x, y), max(x, y)): 1})
    g.move_fighter(john, a, 0)
    assert (min(x, y), max(x, y)) not in g.fx.paths and john.hp == 17
    g.hazard_taken.add("john")                                  # paid this turn: every hazard edge is free now
    g.move_fighter(john, a, 0)
    assert (min(x, y), max(x, y)) in g.fx.paths


# ---------------------------------------------------------------- the hammers

def fight(g, foe="sinbad", at=None):
    """John Henry next to the rival's hero (the rest of the rival's fighters far away)."""
    row = chain(g.board, 6)
    john = stage(g, row, foes_at={foe: row[1]})
    return john, g.fighters[foe]


def four_paths(g):
    g.fx.paths = [(90, 91), (91, 92), (92, 93), (93, 94)]


def test_the_eighteen_pound_hammer_cancels_the_rivals_card_with_four_paths(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    start_turn(g)
    g.fx.turn_start_pos["sinbad"] = -1                          # Sinbad "started the turn elsewhere": his Momentous Shift would be 5
    four_paths(g)
    res = g.attack(john, sinbad, give(g, 0, "Eighteen-pound Hammer"), give(g, 1, "Momentous Shift"))
    assert res.atk_value == 6 and res.def_value == 3, "its DURING effect is cancelled: the printed 3 stays"


def test_the_eighteen_pound_hammer_cancels_nothing_without_four_paths(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    start_turn(g)
    g.fx.turn_start_pos["sinbad"] = -1
    g.fx.paths = [(90, 91), (91, 92), (92, 93)]
    res = g.attack(john, sinbad, give(g, 0, "Eighteen-pound Hammer"), give(g, 1, "Momentous Shift"))
    assert res.def_value == 5


def test_the_nine_pound_hammer_hits_every_opposing_fighter_in_his_zone_for_two(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    porter = g.fighters["porter"]
    porter.pos = next(s for s in g.board.spaces if s != john.pos and g.board.share_zone(john.pos, s) and s != sinbad.pos)
    four_paths(g)
    res = g.attack(john, sinbad, give(g, 0, "Nine-pound Hammer"), None)
    assert res.damage == 3 and sinbad.hp == sinbad.max_hp - 3 - 2 and porter.hp == porter.max_hp - 2


def test_the_nine_pound_hammer_deals_nothing_extra_without_four_paths(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    porter = g.fighters["porter"]
    porter.pos = next(s for s in g.board.spaces if s != john.pos and g.board.share_zone(john.pos, s) and s != sinbad.pos)
    g.attack(john, sinbad, give(g, 0, "Nine-pound Hammer"), None)
    assert sinbad.hp == sinbad.max_hp - 3 and porter.hp == porter.max_hp


def test_the_twelve_pound_hammer_places_either_fighter_of_the_combat_on_a_track_space(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    spot = next(s for s in sorted(g.board.spaces) if s not in (john.pos, sinbad.pos) and all(f.pos != s for f in g.fighters.values() if f.alive))
    lay(g, [spot])
    four_paths(g)
    lay(g, [john.pos])                                          # a token under a fighter: not a space to place one on
    asked = []
    g.controllers[0].queue = [[True], lambda req: asked.append(req.options) or ["sinbad"]]
    g.attack(john, sinbad, give(g, 0, "Twelve-pound Hammer"), None)
    assert asked == [["john", "sinbad"]], "either fighter of the combat, the owner picks"
    assert sinbad.pos == spot, "the only empty space with a track token: no second question"


def test_the_twelve_pound_hammer_places_nothing_without_four_paths_and_may_be_declined(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    spot = next(s for s in sorted(g.board.spaces) if s not in (john.pos, sinbad.pos) and all(f.pos != s for f in g.fighters.values() if f.alive))
    lay(g, [spot])
    where = sinbad.pos
    g.attack(john, sinbad, give(g, 0, "Twelve-pound Hammer"), None)
    assert sinbad.pos == where and g.controllers[0].requests == []
    four_paths(g)
    g.controllers[0].queue = [[False]]
    g.attack(john, sinbad, give(g, 0, "Twelve-pound Hammer", 1), None)
    assert sinbad.pos == where


def test_bring_down_the_mountain_adds_one_for_each_hammer_in_the_discard_pile(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    to_discard(g, 0, HAMMERS[0], HAMMERS[0], HAMMERS[1], HAMMERS[2], "Larger Than Life")
    res = g.attack(john, hellboy, give(g, 0, "Bring Down The Mountain"), None)
    assert res.atk_value == 3 + 4, "the three hammers of the pile and the fourth, not Larger Than Life"


def test_the_card_in_play_is_not_in_the_pile_when_bring_down_the_mountain_counts(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    assert g.attack(john, hellboy, give(g, 0, "Bring Down The Mountain"), None).atk_value == 3


# ---------------------------------------------------------------- the other attacks and the versatile cards

def test_larger_than_life_is_a_plain_six(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    assert g.attack(john, hellboy, give(g, 0, "Larger Than Life"), None).atk_value == 6


def test_hear_that_cold_steel_ring_draws_moves_one_and_gives_a_free_action_that_only_an_attack_may_spend(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    hand = len(g.players[0].hand)
    g.controllers[0].queue = [[]]                                # moves nothing: up to 1
    g.attack(john, hellboy, give(g, 0, "Hear That Cold Steel Ring"), None)
    assert len(g.players[0].hand) == hand + 1 and g.actions_left == 2 and g.fx.attack_credit == 1
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {})                                           # the real action
    assert g.actions_left == 1 and g.attack_only()
    with pytest.raises(RuleError):
        g.maneuver(0, {})
    with pytest.raises(RuleError):
        g.play_scheme(0, john, give(g, 0, "Striking Fire"))
    assert g.actions_left == 1
    res = g.attack(john, hellboy, give(g, 0, "Larger Than Life"), None)
    assert res.atk_value == 6 and g.actions_left == 0 and g.fx.attack_credit == 0


def test_the_free_attack_action_is_spent_before_the_real_one_and_the_credit_does_not_outlive_the_turn(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    g.fx.attack_credit, g.actions_left = 1, 2
    g.attack(john, hellboy, give(g, 0, "Larger Than Life"), None)
    assert g.actions_left == 1 and g.fx.attack_credit == 0 and not g.attack_only()
    g.fx.attack_credit, g.actions_left = 1, 1
    g.turn = 1
    g.begin_turn()
    assert g.fx.attack_credit == 0


def test_a_free_action_to_attack_gained_when_it_cannot_gain_actions_gives_nothing(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    g.fx.statuses.append({"name": "cannot_gain_actions", "player": 0, "until": {"event": "end_of_turn"}})
    g.controllers[0].queue = [[]]
    g.attack(john, hellboy, give(g, 0, "Hear That Cold Steel Ring"), None)
    assert g.actions_left == 1 and g.fx.attack_credit == 0


def test_knock_them_silly_cancels_the_rivals_after_effects_when_he_wins(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    give(g, 1, "Regroup")                                      # AFTER: draw 1 (2 if it won)
    regroup = g.players[1].hand[0]
    hand = len(g.players[1].hand)
    res = g.attack(john, sinbad, give(g, 0, "Knock Them Silly"), regroup)
    assert res.attacker_won and len(g.players[1].hand) == hand - 1, "no card drawn"


def test_knock_them_silly_cancels_nothing_when_he_loses_or_ties(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    exploit = give(g, 1, "Exploit")                            # value 4: a tie, which the defender wins
    hand = len(g.players[1].hand)
    res = g.attack(john, sinbad, give(g, 0, "Knock Them Silly"), exploit)
    assert not res.attacker_won and len(g.players[1].hand) == hand - 1 + 1, "Exploit's AFTER draw is still there"


def test_knock_them_silly_cancels_the_rivals_after_effects_when_he_defends_and_wins(bprd):
    g = mk(bprd, "sinbad", turn=1)
    john, sinbad = fight(g)
    g.actions_left = 2
    attack = give(g, 1, "Exploit")                              # Exploit as an attack (4): AFTER draw 1
    hand = len(g.players[1].hand)
    res = g.attack(sinbad, john, attack, give(g, 0, "Knock Them Silly"))      # 4 against 4: the defender wins
    assert not res.attacker_won and len(g.players[1].hand) == hand - 1, "his AFTER draw was cancelled"


def test_the_cancelled_after_effects_are_those_of_the_rivals_card_not_his(bprd):
    g = mk(bprd, "sinbad")
    john, sinbad = fight(g)
    john_hand = len(g.players[0].hand)
    g.attack(john, sinbad, give(g, 0, "Knock Them Silly"), None)
    assert len(g.players[0].hand) == john_hand, "Knock Them Silly has no AFTER of its own"


def test_momentous_shift_is_three_in_place_and_five_when_he_began_the_turn_elsewhere(bprd):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    start_turn(g)
    assert g.attack(john, hellboy, give(g, 0, "Momentous Shift"), None).atk_value == 3
    g.actions_left = 2
    john.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if s != john.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert g.attack(john, hellboy, give(g, 0, "Momentous Shift", 1), None).atk_value == 5


def test_power_through_walks_john_henry_over_the_tracks_for_free(bprd):
    g = mk(bprd)
    row = chain(bprd, 8)
    john, hellboy = fight(g, "hellboy")
    john.pos, hellboy.pos = row[7], row[0]
    lay(g, row[2:5])
    g.fighters["hellboy"].pos = row[0]
    john.pos = row[1]
    asked = []
    g.controllers[0].queue = [lambda req: ["john"], lambda req: asked.append(req.options) or [row[6]]]
    g.attack(john, hellboy, give(g, 0, "Power Through"), None)
    assert john.pos == row[6] and row[6] in asked[0] and row[7] not in asked[0]


def test_a_rival_moved_by_power_through_pays_full_cost_for_the_track_spaces(bprd):
    g = mk(bprd)
    row = chain(bprd, 8)
    john, hellboy = fight(g, "hellboy")
    john.pos, hellboy.pos = row[0], row[1]
    lay(g, row[2:5])
    asked = []
    g.controllers[0].queue = [lambda req: ["hellboy"], lambda req: asked.append(req.options) or [row[3]]]
    g.attack(john, hellboy, give(g, 0, "Power Through"), None)
    assert row[3] in asked[0] and row[4] not in asked[0] and row[6] not in asked[0] and hellboy.pos == row[3]


def test_power_through_without_tracks_is_an_ordinary_two_space_move(bprd):
    g = mk(bprd)
    row = chain(bprd, 8)
    john, hellboy = fight(g, "hellboy")
    john.pos, hellboy.pos = row[0], row[1]
    asked = []
    g.controllers[0].queue = [lambda req: ["hellboy"], lambda req: asked.append(req.options) or [row[3]]]
    g.attack(john, hellboy, give(g, 0, "Power Through"), None)
    assert row[3] in asked[0] and row[4] not in asked[0] and hellboy.pos == row[3]


# ---------------------------------------------------------------- the defenses and the scheme

def test_deeds_of_valor_takes_at_most_two_combat_damage(bprd):
    g = mk(bprd, "sinbad", turn=1)
    john, sinbad = fight(g)
    g.actions_left = 2
    res = g.attack(sinbad, john, give(g, 1, "Commanding Impact"), give(g, 0, "Deeds Of Valor"))     # 5 against 2
    assert res.attacker_won and john.hp == 15


def test_a_cool_drink_of_water_heals_three_and_draws_a_card(bprd):
    g = mk(bprd, "sinbad", turn=1)
    john, sinbad = fight(g)
    g.actions_left = 2
    john.hp = 10
    defense = give(g, 0, "Cool Drink Of Water")
    hand = len(g.players[0].hand)
    g.attack(sinbad, john, give(g, 1, "Commanding Impact"), defense)      # 5 against 0: 5 damage, then 3 back
    assert john.hp == 10 - 5 + 3 and len(g.players[0].hand) == hand - 1 + 1


def test_cool_drink_of_water_does_not_heal_past_the_maximum(bprd):
    g = mk(bprd, "sinbad", turn=1)
    john, sinbad = fight(g)
    g.actions_left = 2
    g.attack(sinbad, john, give(g, 1, "Exploit"), give(g, 0, "Cool Drink Of Water"))               # 4 damage: 13, then 16
    assert john.hp == 16
    john.hp = 17
    g.actions_left = 2
    g.attack(sinbad, john, give(g, 1, "Exploit", 1), give(g, 0, "Cool Drink Of Water", 1))
    assert john.hp == 16, "13 + 3: a heal never goes past the maximum, here it does not reach it"


def test_striking_fire_moves_him_up_to_four_and_gains_an_action(bprd):
    g = mk(bprd)
    row = chain(bprd, 6)
    john = stage(g, row)
    g.controllers[0].queue = [lambda req: [row[4]]]
    g.play_scheme(0, john, give(g, 0, "Striking Fire"))
    assert john.pos == row[4] and g.actions_left == 2 and g.fx.attack_credit == 0


# ---------------------------------------------------------------- state

def test_the_state_survives_a_clone_and_a_save(bprd):
    g = mk(bprd)
    row = chain(bprd, 6)
    stage(g, row)
    lay(g, row[1:4])
    g.fx.paths = edges(row[:3])
    g.fx.attack_credit = 1
    twin = g.clone()
    assert twin.fx.tracks == g.fx.tracks and twin.fx.paths == g.fx.paths and twin.fx.attack_credit == 1
    twin.fx.tracks[0].append(row[5])
    assert len(g.fx.tracks[0]) == 3, "the clone owns its lists"
    saved = game_to_dict(g)
    assert saved["fx"]["tracks"] == [row[1:4], []] and saved["fx"]["paths"] == [list(e) for e in edges(row[:3])] and saved["fx"]["attack_credit"] == 1
    fresh = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("john-henry", "hellboy"), bot_player=0)
    apply_game(fresh, saved)
    assert fresh.fx.tracks == g.fx.tracks and fresh.fx.paths == g.fx.paths and fresh.fx.attack_credit == 1


def test_a_game_without_tracks_saves_exactly_as_before(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("sinbad", "hellboy"), bot_player=0)
    fx = game_to_dict(g).get("fx", {})
    assert "tracks" not in fx and "paths" not in fx and "attack_credit" not in fx


def test_the_walk_costs_of_other_heroes_are_untouched(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("sinbad", "hellboy"), bot_player=0)
    sinbad = g.fighters["sinbad"]
    assert g.legal_moves(sinbad, 2) == bprd.reachable(sinbad.pos, 2, g.occupied(0) - {sinbad.pos}, g.occupied(1))
    assert hp(g, "sinbad") == [15]


# ---------------------------------------------------------------- a turn whose only action left is a free action to attack

def credit_turn(bprd, hand=()):
    g = mk(bprd)
    john, hellboy = fight(g, "hellboy")
    g.actions_left, g.fx.attack_credit = 1, 1
    for title in hand:
        give(g, 0, title)
    return g, john, hellboy


def test_turn_goes_on_ends_the_turn_when_the_free_action_has_no_attack_to_spend_it_on(bprd):
    g, john, hellboy = credit_turn(bprd, ("Striking Fire",))
    assert g.attack_only() and not tracks.turn_goes_on(g)
    give(g, 0, "Larger Than Life")
    assert tracks.turn_goes_on(g)
    g.fx.attack_credit = 0
    g.players[0].hand.clear()
    assert tracks.turn_goes_on(g), "a real action left: anything may spend it"


def controllers():
    from sparring import sim
    from sparring.ai_medusa import MedusaAI
    from sparring.hellboy_script import ChasingHellboy, ScriptedHellboy
    return {"heuristic": lambda: MedusaAI(0), "ismcts": lambda: sim.make_bot("ismcts", iterations=4, seed=1),
            "scripted": lambda: ScriptedHellboy(0, 1), "chasing": lambda: ChasingHellboy(0, 1)}


@pytest.mark.parametrize("kind", ["heuristic", "ismcts", "scripted", "chasing"])
def test_a_free_action_with_nothing_to_attack_with_ends_the_turn_without_a_maneuver(bprd, kind):
    g, john, hellboy = credit_turn(bprd, ("Striking Fire",))
    where, hand = john.pos, len(g.players[0].hand)
    controllers()[kind]().take_turn(g)
    assert g.actions_left == 1 and john.pos == where and len(g.players[0].hand) == hand, "no Maneuver, no scheme"


@pytest.mark.parametrize("kind", ["heuristic", "ismcts", "scripted", "chasing"])
def test_a_free_action_with_an_attack_card_and_a_rival_next_to_him_attacks(bprd, kind):
    g, john, hellboy = credit_turn(bprd, ("Larger Than Life",))
    life = hellboy.hp
    controllers()[kind]().take_turn(g)
    assert hellboy.hp < life and g.actions_left == 0 and g.fx.attack_credit == 0


def test_the_session_loop_ends_the_bots_turn_on_a_free_action_it_cannot_use(tmp_path):
    from test_john_henry_human import JohnTable
    from test_d3_table_effects import build
    from sparring.ai_medusa import MedusaAI
    session, table, game, fake, cfg, client = build(tmp_path, "john-henry", "hellboy", ("Striking Fire",), table_cls=JohnTable)
    try:
        game.turn, game.actions_left, game.fx.attack_credit = 0, 1, 1
        session.ai.pick_ability_target = lambda g: None
        session._bot_continue()
        assert game.turn == 1 and session.pending is None
    finally:
        client.close()
        fake.close()


def test_the_session_loop_lets_the_bot_attack_with_the_free_action(tmp_path):
    from test_john_henry_human import JohnTable
    from test_d3_table_effects import build
    from test_e2_human_cards import put_adjacent
    session, table, game, fake, cfg, client = build(tmp_path, "john-henry", "hellboy", ("Larger Than Life",), table_cls=JohnTable)
    try:
        put_adjacent(game, table, cfg, "john", "hellboy")
        game.turn, game.actions_left, game.fx.attack_credit = 0, 1, 1
        session.ai.pick_ability_target = lambda g: None
        session._bot_continue()
        assert session.pending is not None and session.pending.kind == "bot_attacks"
    finally:
        client.close()
        fake.close()


def test_the_plan_spends_the_free_action_like_the_engine(bprd):
    from sparring.ai_medusa import MedusaAI, Model
    g, john, hellboy = credit_turn(bprd, ("Larger Than Life",))
    ai = MedusaAI(0)
    act = next(a for a in ai.attack_acts(g, Model(g, 0)) if a.kind == "attack")
    after = ai.apply_expected(g, act)
    assert after.actions_left == 0 and after.fx.attack_credit == 0
