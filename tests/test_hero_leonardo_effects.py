"""Leonardo (TMNT box): every card with an effect and TEAM TACTICS, played by the bot (player 0) against the box heroes
and Medusa on the interpreter (docs/heroes/leonardo.md). Decisions are answered by `Plan`, a scripted controller: a
destination per fighter, a yes/no per optional, a fighter per pick. The human's side is tests/test_leonardo_table.py."""
from __future__ import annotations

import pytest

from conftest import Scripted, give
from sparring.board import Board
from sparring.combat import can_boost, is_medusa_card
from sparring.state import Game
from test_d1_bot_cards import fight, kill, mk
from test_effects_combat import hand_filler, hp, pair, put_adjacent


class Plan(Scripted):
    """Answers the effect decisions: `dest` fid -> space (absent: stay), `optional` yes/no, `pick` fid for a fighter
    pick, `cards` titles to give up. Everything asked is kept in `requests`."""

    def __init__(self, dest=None, optional=True, pick=None):
        super().__init__()
        self.dest, self.optional, self.pick = dict(dest or {}), optional, pick
        self.requests: list = []

    def choose_effect(self, game, req):
        self.requests.append(req)
        if req.kind == "optional":
            return [self.optional]
        if req.kind == "fighter" and self.pick in req.options:
            return [self.pick]
        if req.kind == "space":
            want = self.dest.get(req.extra.get("fighter"))
            return [want] if want in req.options else ([] if req.min == 0 else None)
        return None


def duel(bprd, human="hellboy", bot="leonardo", **plan):
    """Leonardo (bot) and the rival adjacent; the other fighters far away; hands empty; TEAM TACTICS declined."""
    g = mk(bprd, bot, human)
    ctl = Plan(**plan)
    g.controllers[0] = ctl
    leo, foe = pair(g, "leonardo", g.hero(1).fid)
    return g, ctl, leo, foe


def free_spaces(g, near):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return [s for s in sorted(g.board.adj[near]) if s not in taken]


# ---------------------------------------------------------------- cards without an effect, boost

def test_katana_and_heroes_in_a_half_shell_have_no_effect(bprd):
    g, ctl, leo, foe = duel(bprd)
    res = fight(g, "leonardo", "hellboy", "Katana")
    assert res.applied == [] and res.human_effects == [] and res.damage == 6
    g, ctl, leo, foe = duel(bprd)
    res = fight(g, "hellboy", "leonardo", "Excalibur", "Heroes in a half shell")
    assert res.applied == [] and res.damage == 1 and leo.hp == 15                    # 6 against 5


def test_turtle_power_may_boost_itself(bprd):
    g, ctl, leo, foe = duel(bprd)
    card = next(c for c in g.players[0].full_set if c.title == "Turtle power!")
    assert can_boost(card)
    assert not can_boost(next(c for c in g.players[0].full_set if c.title == "Katana"))
    good = next(c for c in g.players[0].deck if c.boost > 0)
    g.players[0].deck.remove(good)
    g.players[0].hand.append(good)
    ctl.boost = good
    res = fight(g, "leonardo", "hellboy", "Turtle power!")
    assert res.atk_value == 3 + good.boost and res.boost_card is good


def test_leonardos_cards_are_not_medusas_even_though_they_share_her_card_ids():
    g = Game.new(Board.load("bprd-hq"), 3, controllers={}, heroes=("leonardo", "medusa"), bot_player=0)
    assert not any(is_medusa_card(c) for c in g.players[0].full_set)
    assert all(is_medusa_card(c) for c in g.players[1].full_set)


# ---------------------------------------------------------------- AFTER COMBAT

def test_for_sensei_moves_both_fighters_and_a_discarded_card_buys_an_action(bprd):
    g, ctl, leo, foe = duel(bprd)
    hand_filler(g, 0, 3)
    foe_to = free_spaces(g, foe.pos)[0]
    leo_to = next(s for s in free_spaces(g, leo.pos) if s != foe_to)
    ctl.dest = {"leonardo": leo_to, "hellboy": foe_to}
    start = g.actions_left
    res = fight(g, "leonardo", "hellboy", "For Sensei")
    assert (leo.pos, foe.pos) == (leo_to, foe_to)
    assert g.actions_left == start - 1 + 1                           # the attack spent one, the discard gave one back
    assert len(g.players[0].hand) == 3 - 1 and any("For Sensei" in line for line in res.applied)


def test_for_sensei_declined_or_with_an_empty_hand_gives_no_action(bprd):
    g, ctl, leo, foe = duel(bprd, optional=False)
    hand_filler(g, 0, 2)
    start = g.actions_left
    fight(g, "leonardo", "hellboy", "For Sensei")
    assert g.actions_left == start - 1 and len(g.players[0].hand) == 2
    g, ctl, leo, foe = duel(bprd)
    fight(g, "leonardo", "hellboy", "For Sensei")                    # nothing in hand: the price cannot be paid
    assert g.actions_left == start - 1 and not any(r.kind == "optional" and r.extra.get("cost_cards") for r in ctl.requests)


def test_for_sensei_does_not_move_a_fighter_defeated_in_the_combat(bprd):
    g, ctl, leo, foe = duel(bprd)
    lobster = g.fighters["lobster"]
    lobster.pos, lobster.hp = free_spaces(g, leo.pos)[0], 1
    ctl.dest = {"leonardo": free_spaces(g, leo.pos)[-1]}
    fight(g, "leonardo", "lobster", "For Sensei")
    assert not lobster.alive and {r.extra.get("fighter") for r in ctl.requests if r.kind == "space"} == {"leonardo"}


def test_fearless_leader_adds_two_per_other_friendly_fighter_next_to_the_opponent(bprd):
    g, ctl, leo, foe = duel(bprd)
    base = fight(g, "leonardo", "hellboy", "Fearless leader").atk_value
    assert base == 3                                                  # Splinter is far away
    g, ctl, leo, foe = duel(bprd)
    put_adjacent(g, "splinter", "hellboy")
    assert fight(g, "leonardo", "hellboy", "Fearless leader").atk_value == 5
    g, ctl, leo, foe = duel(bprd)
    put_adjacent(g, "splinter", "hellboy")                           # Splinter attacks, Leonardo (already adjacent) is the "other"
    assert fight(g, "splinter", "hellboy", "Fearless leader").atk_value == 5


def test_fearless_leader_does_not_count_the_rival_fighters(bprd):
    g, ctl, leo, foe = duel(bprd)
    put_adjacent(g, "lobster", "hellboy")                            # a rival fighter next to the defender is no friend
    assert fight(g, "leonardo", "hellboy", "Fearless leader").atk_value == 3


def test_wise_beyond_his_years_hits_only_when_the_opponent_is_in_fewer_zones(bprd):
    g, ctl, leo, foe = duel(bprd)
    assert (len(bprd.zones(leo.pos)), len(bprd.zones(foe.pos))) == (2, 1)
    before = foe.hp
    res = fight(g, "leonardo", "hellboy", "Wise beyond his years")
    assert foe.hp == before - 2 - 2 and any("Wise beyond his years" in line for line in res.applied)     # combat 2, then the effect
    g, ctl, leo, foe = duel(bprd)
    leo.pos, foe.pos = 1, 0                                           # now Leonardo is in the single-zone space
    before = foe.hp
    fight(g, "leonardo", "hellboy", "Wise beyond his years")
    assert foe.hp == before - 2                                       # only the combat damage
    g, ctl, leo, foe = duel(bprd)
    leo.pos, foe.pos = 1, 2                                           # 1 zone against 2
    before = foe.hp
    fight(g, "leonardo", "hellboy", "Wise beyond his years")
    assert foe.hp == before - 2
    g, ctl, leo, foe = duel(bprd)
    leo.pos, foe.pos = 0, 2                                           # equal (2 and 2): not fewer
    before = foe.hp
    fight(g, "leonardo", "hellboy", "Wise beyond his years")
    assert foe.hp == before - 2


def test_quick_strike_draws_a_card(bprd):
    g, ctl, leo, foe = duel(bprd)
    res = fight(g, "leonardo", "hellboy", "Quick strike")
    assert len(g.players[0].hand) == 1 and any("Quick strike" in line for line in res.applied)


def test_spatial_awareness_needs_splinter_to_be_in_more_zones_and_then_hits_and_draws(bprd):
    g, ctl, leo, foe = duel(bprd)
    splinter = g.fighters["splinter"]
    splinter.pos, leo.pos = 0, 5                                      # Splinter on 2 zones next to a one-zone rival
    foe.pos = 1
    before = foe.hp
    fight(g, "splinter", "hellboy", "Spatial awareness")
    assert foe.hp == before - 3 - 1 and len(g.players[0].hand) == 1
    g, ctl, leo, foe = duel(bprd)
    splinter = g.fighters["splinter"]
    splinter.pos, foe.pos, leo.pos = 1, 0, 6                          # one zone against two: nothing
    before = foe.hp
    fight(g, "splinter", "hellboy", "Spatial awareness")
    assert foe.hp == before - 3 and len(g.players[0].hand) == 0


def test_spatial_awareness_draws_nothing_when_the_opponent_fell_in_the_combat(bprd):
    g, ctl, leo, foe = duel(bprd)
    splinter = g.fighters["splinter"]
    splinter.pos, leo.pos, foe.pos = 0, 5, 1
    foe.hp = 1
    fight(g, "splinter", "hellboy", "Spatial awareness")
    assert not foe.alive and len(g.players[0].hand) == 0


def test_eat_sleep_and_breathe_ninjutsu_places_each_adjacent_fighter_in_another_space_of_its_zone(bprd):
    g, ctl, leo, foe = duel(bprd)
    put_adjacent(g, "splinter", "leonardo")
    spl = g.fighters["splinter"]
    old = {"hellboy": foe.pos, "splinter": spl.pos}
    taken = {f.pos for f in g.fighters.values() if f.alive}
    foe_to = next(s for s in sorted(bprd.spaces) if s not in taken and bprd.share_zone(foe.pos, s))
    spl_to = next(s for s in sorted(bprd.spaces) if s not in taken | {foe_to} and bprd.share_zone(spl.pos, s))
    ctl.dest = {"hellboy": foe_to, "splinter": spl_to}
    res = fight(g, "leonardo", "hellboy", "Eat, sleep, and breathe ninjutsu")
    assert (foe.pos, spl.pos) == (foe_to, spl_to) and foe.pos != old["hellboy"] and spl.pos != old["splinter"]
    for req in (r for r in ctl.requests if r.kind == "space" and r.extra.get("op") == "place"):
        fid = req.extra["fighter"]
        assert old[fid] not in req.options, "another space: never the one it stands on"
        assert all(bprd.share_zone(old[fid], s) for s in req.options)
    assert any("Eat, sleep" in line for line in res.applied)


# ---------------------------------------------------------------- IMMEDIATELY

def test_i_have_a_plan_pays_a_card_to_cancel_the_effects_and_ignore_the_value(bprd):
    g, ctl, leo, foe = duel(bprd)
    hand_filler(g, 0, 2, avoid=("I have a plan",))
    hb = foe
    leo_hp = leo.hp
    hand = len(g.players[0].hand)
    # Hellboy's Horseshoes: 2 + AFTER 1 damage to each other fighter in the zone: both are ignored
    res = fight(g, "hellboy", "leonardo", "Horseshoes And Hand Grenades", "I have a plan")
    assert leo.hp == leo_hp and res.damage == 0
    assert len(g.players[0].hand) == hand - 1                       # the paid card; the plan itself was not in the hand
    assert any("I have a plan" in line for line in res.applied)


def test_i_have_a_plan_declined_changes_nothing(bprd):
    g, ctl, leo, foe = duel(bprd, optional=False)
    hand_filler(g, 0, 2, avoid=("I have a plan",))
    res = fight(g, "hellboy", "leonardo", "Excalibur", "I have a plan")
    assert res.damage == 6 - 2 and len(g.players[0].hand) == 2


def test_i_have_a_plan_without_a_card_to_pay_cannot_be_used(bprd):
    g, ctl, leo, foe = duel(bprd)
    res = fight(g, "hellboy", "leonardo", "Excalibur", "I have a plan")
    assert res.damage == 4


def test_i_have_a_plan_against_an_uncancelable_card_only_ignores_its_value(bprd):
    g, ctl, leo, foe = duel(bprd, human="liz-sherman")
    hand_filler(g, 0, 1, avoid=("I have a plan",))
    res = fight(g, "liz", "leonardo", "Incinerate", "I have a plan")
    assert res.damage == 0


# ---------------------------------------------------------------- schemes

def test_leonardo_leads_moves_both_fighters_up_to_three_and_draws(bprd):
    g, ctl, leo, foe = duel(bprd)
    spl = g.fighters["splinter"]
    leo_to = sorted(g.legal_moves(leo, 3))[-1]
    ctl.dest = {"leonardo": leo_to}
    scheme = give(g, 0, "Leonardo leads")
    g.play_scheme(0, leo, scheme)
    assert leo.pos == leo_to and len(g.players[0].hand) == 1
    assert {r.extra["fighter"] for r in ctl.requests if r.kind == "space"} == {"leonardo", "splinter"}
    assert max(r.extra["steps"] for r in ctl.requests if r.kind == "space") == 3
    assert spl.alive and spl.pos is not None


def test_protective_father_swaps_splinter_and_leonardo_and_heals_both(bprd):
    g, ctl, leo, foe = duel(bprd)
    spl = g.fighters["splinter"]
    leo.hp, spl.hp = 10, 4
    a, b = leo.pos, spl.pos
    start = g.actions_left
    g.play_scheme(0, spl, give(g, 0, "Protective father"))
    assert (leo.pos, spl.pos) == (b, a) and (leo.hp, spl.hp) == (12, 6)
    assert g.actions_left == start - 1 + 1


def test_protective_father_heals_no_more_than_the_maximum(bprd):
    g, ctl, leo, foe = duel(bprd)
    spl = g.fighters["splinter"]
    leo.hp, spl.hp = leo.max_hp, 8
    g.play_scheme(0, spl, give(g, 0, "Protective father"))
    assert (leo.hp, spl.hp) == (leo.max_hp, 9)


def test_protective_father_declined_still_gains_the_action(bprd):
    g, ctl, leo, foe = duel(bprd, optional=False)
    spl = g.fighters["splinter"]
    leo.hp = 10
    a, b = leo.pos, spl.pos
    start = g.actions_left
    g.play_scheme(0, spl, give(g, 0, "Protective father"))
    assert (leo.pos, spl.pos) == (a, b) and leo.hp == 10 and g.actions_left == start - 1 + 1


def test_protective_father_with_leonardo_down_only_gains_the_action(bprd):
    g, ctl, leo, foe = duel(bprd)
    spl = g.fighters["splinter"]
    spl.hp = 4
    kill(g, "leonardo")
    pos, start = spl.pos, g.actions_left
    g.play_scheme(0, spl, give(g, 0, "Protective father"))
    assert spl.pos == pos and spl.hp == 4 and g.actions_left == start - 1 + 1
    assert not any(r.kind == "optional" for r in ctl.requests if r.extra.get("op") != "move")


# ---------------------------------------------------------------- TEAM TACTICS

def begin_with(bprd, human="hellboy", **plan):
    ctl = Plan(**plan)
    g = Game.new(bprd, 3, controllers={0: ctl, 1: Scripted()}, heroes=("leonardo", human), bot_player=0)
    g.turn, g.turn_no = 0, 2
    return g, ctl


def test_team_tactics_moves_any_fighter_one_space_at_the_start_of_the_turn(bprd):
    g, ctl = begin_with(bprd)
    foe = g.hero(1)
    step = free_spaces(g, foe.pos)[0]
    ctl.dest, ctl.pick = {"hellboy": step}, "hellboy"
    g.begin_turn()
    opts = next(r for r in ctl.requests if r.kind == "fighter")
    assert {"leonardo", "splinter", "hellboy", "lobster"} <= set(opts.options)      # the rival's fighters too
    assert foe.pos == step


def test_team_tactics_is_optional_and_moves_at_most_one_space(bprd):
    g, ctl = begin_with(bprd, optional=False)
    before = {fid: f.pos for fid, f in g.fighters.items()}
    g.begin_turn()
    assert {fid: f.pos for fid, f in g.fighters.items()} == before
    g, ctl = begin_with(bprd)
    g.begin_turn()
    assert all(r.extra["steps"] == 1 for r in ctl.requests if r.kind == "space")


def test_team_tactics_only_fires_on_leonardos_own_turn(bprd):
    g, ctl = begin_with(bprd)
    g.turn = 1
    g.begin_turn()
    assert ctl.requests == []


# ---------------------------------------------------------------- shared CardIDs: Leonardo and Medusa

@pytest.mark.parametrize("bot,human", [("leonardo", "medusa"), ("medusa", "leonardo")])
def test_leonardo_and_medusa_share_card_ids_and_each_card_resolves_its_own_effect(bprd, bot, human):
    g = mk(bprd, bot, human)
    g.controllers = {0: Plan(), 1: Plan()}
    pair(g, "leonardo", "medusa")
    me = g.fighters["leonardo"].owner
    plan = give(g, me, "I have a plan")
    foe_card = next(c for c in g.players[1 - me].full_set if c.card_id == plan.card_id)
    assert foe_card.title != plan.title                              # the same CardID, another card
    hand_filler(g, me, 1, avoid=("I have a plan",))
    g.turn = 1 - me
    res = g.attack(g.fighters["medusa"], g.fighters["leonardo"], give(g, 1 - me, "Second Shot"), plan)
    assert res.damage == 0 and len(g.players[me].hand) == 0          # cancelled and ignored, the paid card is gone
    assert any("I have a plan" in line for line in res.applied + res.human_effects) or res.applied == []
