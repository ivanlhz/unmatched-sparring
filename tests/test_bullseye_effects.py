"""Bullseye on the engine, bot side (player 0 plays Bullseye, the controllers answer): his reach (up to 5 spaces away, zones ignored),
the tally of combats won this turn, "considered to have won", the free BOOST that draws when it is declined, a placement that
shares no zone, and every card with the numbers printed on it. The human side (panel, FakeTTS) is in tests/test_bullseye_human.py
and the full games in tests/test_bullseye_matrix.py."""
from __future__ import annotations

import pytest

from conftest import card, give
from sparring.board import Board
from sparring.state import Game
from sparring.effects.events import tracked
from test_bigfoot_effects import Answers, pick, start_turn, wall
from test_effects_combat import pair, put_adjacent


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Bullseye = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("bullseye", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def at_distance(board, a, n, zones_shared=None):
    """A space exactly `n` spaces (along adjacency) from `a`; with `zones_shared` True / False, one that does / does not share a zone with it."""
    for s in sorted(board.spaces):
        if board.spaces_apart(a, s) == n and (zones_shared is None or board.share_zone(a, s) == zones_shared):
            return s
    return None


def win_one_combat(g, bullseye, foe):
    """Bullseye attacks with a plain card and the rival does not defend: a combat won (the tally of the turn goes up)."""
    res = g.attack(bullseye, foe, give(g, 0, "I Never Miss"), None)
    assert res.attacker_won
    return res


# ---------------------------------------------------------------- the reach: up to 5 spaces away, zones ignored

def test_bullseye_is_a_ranged_hero_with_a_reach_of_five_spaces(bprd):
    g = mk(bprd)
    b = g.fighters["bullseye"]
    assert (b.hp, b.move, b.ranged, b.reach) == (14, 2, True, 5)
    assert [f.fid for f in g.own(0)] == ["bullseye"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_board_counts_spaces_along_the_adjacency_not_the_walk(bprd):
    assert bprd.spaces_apart(3, 3) == 0
    for a in sorted(bprd.spaces)[:6]:
        for n in bprd.adj[a]:
            assert bprd.spaces_apart(a, n) == 1
        assert all(bprd.spaces_apart(a, s) == bprd.spaces_apart(s, a) for s in bprd.spaces)


def test_reach_adds_spaces_out_of_zone_to_the_ranged_zone_rule(bprd):
    far_in_zone = [(a, b) for a in bprd.spaces for b in bprd.spaces if bprd.share_zone(a, b) and bprd.spaces_apart(a, b) > 5]
    near_out_of_zone = [(a, b) for a in bprd.spaces for b in bprd.spaces if not bprd.share_zone(a, b) and 1 < bprd.spaces_apart(a, b) <= 5]
    far_out_of_zone = [(a, b) for a in bprd.spaces for b in bprd.spaces if not bprd.share_zone(a, b) and bprd.spaces_apart(a, b) > 5]
    assert near_out_of_zone and far_in_zone and far_out_of_zone
    for a, b in near_out_of_zone[:20]:
        assert bprd.can_reach_target(a, b, True, 5) and not bprd.can_reach_target(a, b, True)
    for a, b in far_in_zone[:20]:
        assert bprd.can_reach_target(a, b, True, 5) and bprd.can_reach_target(a, b, True)      # the zone shot is still there
    for a, b in far_out_of_zone[:20]:
        assert not bprd.can_reach_target(a, b, True, 5)
    assert not bprd.can_reach_target(4, 4, True, 5)                  # never oneself


def test_same_zone_target_six_or_more_spaces_away_is_attackable_on_bprd_hq(bprd):
    g = mk(bprd)
    b, h = g.fighters["bullseye"], g.fighters["hellboy"]
    a, c = next((a, c) for a in sorted(bprd.spaces) for c in sorted(bprd.spaces) if bprd.share_zone(a, c) and bprd.spaces_apart(a, c) >= 6)
    b.pos, h.pos = a, c
    assert g.can_attack(b, h)
    res = g.attack(b, h, give(g, 0, "World's Greatest Assassin"), None)
    assert res.attacker_won


def test_the_bot_counts_a_same_zone_shot_beyond_five_spaces_as_a_strike_spot(bprd):
    from sparring.ai_medusa import MedusaAI
    pos = next(a for a in sorted(bprd.spaces) if any(bprd.share_zone(a, c) and bprd.spaces_apart(a, c) > 5 for c in bprd.spaces))
    spots = set(MedusaAI(0).strike_spots(bprd, pos, True, 5))
    assert any(bprd.share_zone(pos, s) and bprd.spaces_apart(pos, s) > 5 for s in bprd.spaces)
    assert spots == {s for s in bprd.spaces if s != pos and (bprd.share_zone(pos, s) or bprd.spaces_apart(pos, s) <= 5 or bprd.adjacent(pos, s))}


def test_the_engine_accepts_an_attack_from_five_spaces_and_refuses_it_from_six_out_of_zone(bprd):
    g = mk(bprd)
    b, h = g.fighters["bullseye"], g.fighters["hellboy"]
    for n, ok in ((1, True), (3, True), (5, True), (6, False)):
        spot = next((s for s in sorted(bprd.spaces) for a in [min(bprd.spaces)]
                     if bprd.spaces_apart(a, s) == n and (n <= 5 or not bprd.share_zone(a, s))), None)
        if spot is None:
            pytest.skip(f"no space {n} away on this map")
        b.pos, h.pos = min(bprd.spaces), spot
        assert g.can_attack(b, h) is ok, n


def test_a_five_space_attack_out_of_every_shared_zone_is_a_real_attack(bprd):
    g = mk(bprd)
    b, h = g.fighters["bullseye"], g.fighters["hellboy"]
    b.pos = min(bprd.spaces)
    h.pos = next(s for s in sorted(bprd.spaces) if bprd.spaces_apart(b.pos, s) == 5 and not bprd.share_zone(b.pos, s))
    attack = give(g, 0, "World's Greatest Assassin")
    res = g.attack(b, h, attack, None)
    assert res.attacker_won and h.hp == h.max_hp - 4


def test_a_rival_without_a_reach_is_not_helped_by_his(bprd):
    g = mk(bprd, "liz-sherman")
    liz, b = g.fighters["liz"], g.fighters["bullseye"]
    b.pos = min(bprd.spaces)
    liz.pos = next(s for s in sorted(bprd.spaces) if bprd.spaces_apart(b.pos, s) == 4 and not bprd.share_zone(b.pos, s))
    assert g.can_attack(b, liz) and not g.can_attack(liz, b)


def test_the_strike_spots_of_the_ai_follow_the_reach(bprd):
    from sparring.ai_medusa import MedusaAI
    from sparring.search.adapter import strike_spots
    pos = min(bprd.spaces)
    ranged, shooter = MedusaAI(0).strike_spots(bprd, pos, True), MedusaAI(0).strike_spots(bprd, pos, True, 5)
    assert set(shooter) == {s for s in bprd.spaces if s != pos and (bprd.spaces_apart(pos, s) <= 5 or bprd.share_zone(pos, s))}
    assert set(strike_spots(bprd, pos, True, 5)) == set(shooter) and set(strike_spots(bprd, pos, True)) == set(ranged)
    assert set(ranged) < set(shooter)


# ---------------------------------------------------------------- the tally "already won a combat this turn"

def test_the_tally_of_wins_is_tracked_for_bullseye_and_counts_both_sides(bprd):
    g = mk(bprd)
    assert "won" in tracked(frozenset(g.fx.dsl_heroes))
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    assert g.fx.won == [0, 0]
    win_one_combat(g, b, h)
    assert g.fx.won == [1, 0] and g.fx.lost == [0, 0]                 # losses are only counted when some hero reads them (Raphael)
    wall(g)
    res = g.attack(b, h, give(g, 0, "I Never Miss"), g.players[1].hand[0])
    assert not res.attacker_won and g.fx.won == [1, 1]
    start_turn(g)
    assert g.fx.won == [0, 0]                                         # a new turn starts the count again


def test_the_tally_is_saved_and_loaded(bprd):
    from sparring.effects.state import EffectState
    g = mk(bprd)
    g.fx.won = [2, 1]
    assert EffectState.from_dict(g.fx.to_dict()).won == [2, 1] and g.fx.copy().won == [2, 1]
    assert "won" not in EffectState().to_dict()


# ---------------------------------------------------------------- World's Greatest Assassin

def test_greatest_assassin_ignores_the_rivals_card_only_after_a_win_this_turn(bprd):
    g = mk(bprd, "leonardo")
    b, h = pair(g, "bullseye", "leonardo")
    start_turn(g)
    g.actions_left = 9
    first = g.attack(b, h, give(g, 0, "World's Greatest Assassin"), wall(g))
    assert not first.attacker_won and first.def_value > 4                    # no win yet: the wall holds
    g.fx.won[0] = 1                                                          # a combat won earlier in the turn
    second = g.attack(b, h, give(g, 0, "World's Greatest Assassin", 1), wall(g))
    assert second.attacker_won and second.atk_value == 4 and second.def_value == 0


# ---------------------------------------------------------------- I'm Better And I'll Prove It

def test_im_better_is_six_after_a_win_and_two_before(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    assert g.attack(b, h, give(g, 0, "I'm Better And I'll Prove It"), None).atk_value == 2
    g.fx.won[0] = 1
    assert g.attack(b, h, give(g, 0, "I'm Better And I'll Prove It", 1), None).atk_value == 6


def test_im_better_as_a_defense_reads_the_tally_of_the_turn_being_played(bprd):
    g = mk(bprd, turn=1)
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    g.actions_left = 2
    g.fx.won[0] = 1                                                          # Bullseye already won a combat in the rival's turn
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 5))
    res = g.attack(h, b, attack, give(g, 0, "I'm Better And I'll Prove It"))
    assert res.def_value == 6


# ---------------------------------------------------------------- Right Between The Eyes

def test_right_between_the_eyes_makes_the_rival_discard_only_after_a_win_this_turn(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    others = [c for c in g.players[1].deck][:3]
    for c in others:
        g.players[1].deck.remove(c)
        g.players[1].hand.append(c)
    g.attack(b, h, give(g, 0, "Right Between The Eyes"), None)
    assert len(g.players[1].hand) == 3                                       # nothing yet
    g.fx.won[0] = 1
    g.controllers[1].discards = [others[0]]
    g.attack(b, h, give(g, 0, "Right Between The Eyes", 1), None)
    assert len(g.players[1].hand) == 2 and others[0] in g.players[1].discard


# ---------------------------------------------------------------- I Planned To Be Here

def test_i_planned_to_be_here_is_five_when_he_started_the_turn_where_he_stands(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    assert g.attack(b, h, give(g, 0, "I Planned To Be Here"), None).atk_value == 5


def test_i_planned_to_be_here_is_two_after_he_moved(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    b.pos = next(s for s in sorted(bprd.adj[h.pos]) if s != b.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert g.attack(b, h, give(g, 0, "I Planned To Be Here"), None).atk_value == 2


# ---------------------------------------------------------------- I Never Miss

def test_i_never_miss_draws_a_card_when_the_boost_is_declined(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    never = give(g, 0, "I Never Miss")
    spare = [c for c in g.players[0].deck if c.title != "I Never Miss"][:2]
    for c in spare:
        g.players[0].deck.remove(c)
        g.players[0].hand.append(c)
    g.controllers[0].boost = None
    hand_before, deck_before = len(g.players[0].hand), len(g.players[0].deck)
    res = g.attack(b, h, never, None)
    assert res.atk_value == 3
    assert len(g.players[0].hand) == hand_before - 1 + 1 and len(g.players[0].deck) == deck_before - 1


def test_i_never_miss_does_not_draw_when_it_is_boosted(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    never = give(g, 0, "I Never Miss")
    boost = give(g, 0, "Master Strategist")                                  # BOOST 3
    g.controllers[0].boost = boost
    hand_before, deck_before = len(g.players[0].hand), len(g.players[0].deck)
    res = g.attack(b, h, never, None)
    assert res.atk_value == 3 + 3
    assert len(g.players[0].hand) == hand_before - 2 and len(g.players[0].deck) == deck_before


def test_i_never_miss_cancelled_by_a_feint_has_no_boost_and_no_draw(bprd):
    g = mk(bprd, "bigfoot")
    b, bf = pair(g, "bullseye", "bigfoot")
    never = give(g, 0, "I Never Miss")
    feint = give(g, 1, "Feint")
    deck_before = len(g.players[0].deck)
    res = g.attack(b, bf, never, feint)
    assert "atk" in res.cancelled and len(g.players[0].deck) == deck_before


# ---------------------------------------------------------------- For My Next Trick

def test_for_my_next_trick_moves_one_space_draws_one_and_gains_an_action(bprd):
    g = mk(bprd, "leonardo")
    b, h = pair(g, "bullseye", "leonardo")
    wall(g)
    g.actions_left = 2
    dest = next(s for s in sorted(bprd.adj[b.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[dest]]
    trick = give(g, 0, "For My Next Trick")
    deck_before = len(g.players[0].deck)
    g.attack(b, h, trick, g.players[1].hand[0])        # lost combat: it all happens anyway
    assert b.pos == dest and len(g.players[0].deck) == deck_before - 1 and g.actions_left == 2   # 2 - 1 (the attack) + 1


# ---------------------------------------------------------------- Feint

def test_feint_cancels_the_rivals_effects(bprd):
    g = mk(bprd, "liz-sherman")
    b, liz = pair(g, "bullseye", "liz")
    res = g.attack(b, liz, give(g, 0, "Feint"), give(g, 1, "Burning Barrier"))
    assert "def" in res.cancelled


# ---------------------------------------------------------------- Arrogant But Effective

def test_arrogant_but_effective_makes_a_lost_combat_a_won_one_and_moves_him_up_to_two(bprd):
    g = mk(bprd, "leonardo")
    b, h = pair(g, "bullseye", "leonardo")
    start_turn(g)
    wall(g)
    dest = next(s for s in sorted(bprd.spaces) if s != b.pos and 0 < bprd.distance(b.pos, s) <= 2 and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[dest]]
    res = g.attack(b, h, give(g, 0, "Arrogant But Effective"), g.players[1].hand[0])
    assert not res.attacker_won                                              # the damage is what it was
    assert g.fx.won == [1, 0]                                                # but the tally says Bullseye won
    assert b.pos == dest


def test_arrogant_but_effective_feeds_the_next_card_of_the_turn(bprd):
    g = mk(bprd, "leonardo")
    b, h = pair(g, "bullseye", "leonardo")
    start_turn(g)
    wall(g)
    g.controllers[0].queue = [[]]
    g.attack(b, h, give(g, 0, "Arrogant But Effective"), g.players[1].hand[0])
    assert g.attack(b, h, give(g, 0, "I'm Better And I'll Prove It"), None).atk_value == 6


def test_arrogant_but_effective_after_a_real_win_changes_nothing(bprd):
    g = mk(bprd)
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    g.controllers[0].queue = [[]]
    res = g.attack(b, h, give(g, 0, "Arrogant But Effective"), None)
    assert res.attacker_won and g.fx.won == [1, 0]


def test_the_flow_remembers_who_is_considered_the_winner_across_a_save(bprd):
    from sparring.combat_flow import CombatFlow
    g = mk(bprd, "leonardo")
    b, h = pair(g, "bullseye", "leonardo")
    g.controllers[0].queue = [[]]
    flow = g.begin_attack(b, h, give(g, 0, "Arrogant But Effective"), wall(g))
    flow.run()
    assert flow.considered_won == "atk" and flow.won_by("atk") and not flow.won_by("def")
    assert CombatFlow.from_dict(g, flow.to_dict()).considered_won == "atk"


# ---------------------------------------------------------------- Master Strategist

def test_master_strategist_moves_exactly_four_spaces_through_rivals(bprd):
    g = mk(bprd, "leonardo")
    b, h = pair(g, "bullseye", "leonardo")
    wall(g)
    start = b.pos
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]
    g.attack(b, h, give(g, 0, "Master Strategist"), g.players[1].hand[0])
    req = seen[0]
    assert req.extra["steps"] == 4 and req.extra["through"] and not req.extra["up_to"]
    assert req.options and all(bprd.distance(start, s) == 4 for s in req.options)      # exactly 4 away, not up to
    assert b.pos == max(req.options)


# ---------------------------------------------------------------- Ricochet

def test_ricochet_hits_a_fighter_in_the_opposing_fighters_zone_when_it_survives(bprd):
    g = mk(bprd, "hellboy")
    b, h = pair(g, "bullseye", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(bprd.spaces) if bprd.share_zone(h.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [["lobster"]]
    g.attack(b, h, give(g, 0, "Ricochet"), None)
    assert lobster.hp == lobster.max_hp - 1


def test_ricochet_does_nothing_when_the_opposing_fighter_is_defeated(bprd):
    g = mk(bprd, "hellboy")
    b, h = pair(g, "bullseye", "hellboy")
    h.hp = 1
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(bprd.spaces) if bprd.share_zone(h.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.attack(b, h, give(g, 0, "Ricochet"), None)
    assert not h.alive and lobster.hp == lobster.max_hp


def test_ricochet_with_nobody_else_in_the_zone_hits_the_opposing_fighter_again(bprd):
    g = mk(bprd, "leonardo")
    b, leo = pair(g, "bullseye", "leonardo")
    wall(g)
    g.controllers[0].queue = [["leonardo"]]
    hp = leo.hp
    g.attack(b, leo, give(g, 0, "Ricochet"), g.players[1].hand[0])
    assert leo.hp == hp - 1


# ---------------------------------------------------------------- Tactical Retreat

def test_tactical_retreat_places_him_on_a_space_that_shares_no_zone_with_his_own(bprd):
    g = mk(bprd, turn=1)
    b, h = pair(g, "bullseye", "hellboy")
    g.actions_left = 2
    start = b.pos
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]]]
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) <= 3))
    g.attack(h, b, attack, give(g, 0, "Tactical Retreat"))
    assert seen and all(not bprd.share_zone(start, s) for s in seen[0].options)
    assert b.pos != start and not bprd.share_zone(start, b.pos)


# ---------------------------------------------------------------- Study The Target

def test_study_the_target_draws_two(bprd):
    g = mk(bprd)
    g.actions_left = 2
    b = g.fighters["bullseye"]
    study = give(g, 0, "Study The Target")
    before = len(g.players[0].hand)
    g.play_scheme(0, b, study)
    assert len(g.players[0].hand) == before - 1 + 2 and g.actions_left == 1


def test_study_the_target_draws_three_and_gains_an_action_after_a_win(bprd):
    g = mk(bprd)
    g.actions_left = 2
    b, h = pair(g, "bullseye", "hellboy")
    start_turn(g)
    win_one_combat(g, b, h)
    study = give(g, 0, "Study The Target")
    before = len(g.players[0].hand)
    left = g.actions_left
    g.play_scheme(0, b, study)
    assert len(g.players[0].hand) == before - 1 + 3 and g.actions_left == left - 1 + 1
