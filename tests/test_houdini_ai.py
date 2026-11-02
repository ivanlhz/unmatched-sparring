"""The bot's AI with Houdini: it prices the BOOSTED WITH of a card when it chooses what to boost with, uses ESCAPE ARTIST to leave a
threat or to land next to a target, plays Bess's scheme, and the search AI (ISMCTS) places Houdini on boosted Maneuvers legally."""
from __future__ import annotations

import random

import pytest

from conftest import give
from sparring.ai_medusa import MedusaAI, boost_effect_value, scheme_fighter
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from sparring.state import Game
from test_effects_combat import hand_filler, pair


def mk(bprd, foe="hellboy", seed=3):
    """Houdini = player 0 with the real AI; its turn, empty hands, the rival's pieces far away."""
    g = Game.new(bprd, seed, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("houdini", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def far_from(g, fid, fids):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return max((s for s in g.board.spaces if s not in taken),
               key=lambda s: min(g.board.distance(s, g.fighters[o].pos) for o in fids))


# ---------------------------------------------------------------- what a BOOSTED WITH is worth

def test_boost_effect_values_follow_the_text_of_the_card(bprd):
    g = mk(bprd)
    flourish, bess, stage = give(g, 0, "Flourish"), give(g, 0, "And the Beautiful Bess!"), give(g, 0, "Set the Stage")
    assert boost_effect_value(g, 0, flourish) == pytest.approx(0.4)                        # one unknown card
    assert boost_effect_value(g, 0, bess) > 0.5                                           # an action on its own turn
    g.turn = 1
    assert boost_effect_value(g, 0, bess) == 0                                            # none on the rival's: "if it's your turn"
    assert boost_effect_value(g, 0, stage) == 0                                           # the rival has no hand to look at
    give(g, 1, "Excalibur")
    assert boost_effect_value(g, 0, stage) > 1
    assert boost_effect_value(g, 0, give(g, 0, "For My Next Trick")) == 0                  # no BOOSTED WITH


def test_all_part_of_the_show_boost_is_worth_the_health_it_gives_back(bprd):
    g = mk(bprd)
    card = give(g, 0, "All Part of the Show")
    full = boost_effect_value(g, 0, card)
    g.fighters["houdini"].hp = 8
    assert full == 0 and boost_effect_value(g, 0, card) > 2


def test_misdirection_boost_is_worth_a_kill_on_a_weak_rival(bprd):
    g = mk(bprd)
    card = give(g, 0, "Misdirection")
    base = boost_effect_value(g, 0, card)
    g.fighters["lobster"].hp = 2
    assert boost_effect_value(g, 0, card) > base + 2          # it kills Lobster Johnson


def test_bess_plays_set_the_stage_and_houdini_cannot(bprd):
    g = mk(bprd)
    stage = give(g, 0, "Set the Stage")
    assert scheme_fighter(g, 0, stage).fid == "bess"
    assert scheme_fighter(g, 0, give(g, 0, "A Magician Never Reveals His Secrets")).fid == "houdini"
    g.damage(g.fighters["bess"], 5)
    assert scheme_fighter(g, 0, stage) is None


def test_the_bot_plays_a_scheme_only_bess_can_play(bprd):
    g = mk(bprd)
    give(g, 0, "Set the Stage")
    hand_filler(g, 0, 2, avoid=("Set the Stage",))
    g.actions_left = 2
    acts = MedusaAI(0).candidates(g, __import__("sparring.ai_medusa", fromlist=["Model"]).Model(g, 0))
    assert any(a.kind == "scheme" and a.fid == "bess" for a in acts)


# ---------------------------------------------------------------- choosing what to boost a Maneuver with

def test_the_boost_card_with_a_boosted_with_is_the_one_spent_on_a_maneuver(bprd):
    g = mk(bprd)
    trick, flourish = give(g, 0, "For My Next Trick"), give(g, 0, "Flourish")                  # both boost 2: only Flourish draws
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None and act.boost.title == "Flourish"


def test_a_boost_that_gains_an_action_is_chosen_to_get_the_action_back(bprd):
    g = mk(bprd)
    give(g, 0, "And the Beautiful Bess!")
    give(g, 0, "For My Next Trick")
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None and act.boost.title == "And the Beautiful Bess!"


def test_the_expected_state_after_a_boosted_maneuver_counts_the_action_it_gains(bprd):
    g = mk(bprd)
    bess = give(g, 0, "And the Beautiful Bess!")
    ai = MedusaAI(0)
    from sparring.ai_medusa import Act
    after = ai.apply_expected(g, Act("maneuver", moves={}, boost=bess))
    assert after.actions_left == g.actions_left            # one spent, one gained
    plain = ai.apply_expected(g, Act("maneuver", moves={}))
    assert plain.actions_left == g.actions_left - 1


# ---------------------------------------------------------------- ESCAPE ARTIST

def test_the_bot_places_houdini_next_to_the_rival_to_attack_when_it_has_a_boost_card(bprd):
    g = mk(bprd)
    hellboy, houdini = g.fighters["hellboy"], g.fighters["houdini"]
    hellboy.pos = far_from(g, "hellboy", ["houdini", "bess"])
    give(g, 0, "Flourish")
    give(g, 0, "Flourish", 1)
    give(g, 0, "The Big Reveal")
    assert g.board.distance(houdini.pos, hellboy.pos) > houdini.move + 3
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None
    assert g.board.adjacent(act.moves["houdini"], hellboy.pos)           # he lands in reach: the second action attacks


def test_the_bot_leaves_the_rival_when_it_is_threatened_and_holds_a_boost_card(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    houdini.hp = 3
    give(g, 0, "Flourish")
    give(g, 0, "Misdirection")
    for c in ("Excalibur", "Service Pistol", "Right Hand Of Doom"):
        give(g, 1, c)
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None
    assert g.board.distance(act.moves["houdini"], hellboy.pos) > hellboy.move + 1      # out of the rival's reach next turn


def test_without_a_boost_card_he_walks_like_any_hero(bprd):
    g = mk(bprd)
    houdini = g.fighters["houdini"]
    g.fighters["hellboy"].pos = far_from(g, "hellboy", ["houdini", "bess"])
    act = MedusaAI(0).plan(g)
    if act.kind == "maneuver":
        assert act.boost is None and g.board.distance(houdini.pos, act.moves.get("houdini", houdini.pos)) <= houdini.move


def test_the_planned_maneuver_is_always_legal_for_the_engine(bprd):
    """Whatever the heuristic plans with ESCAPE ARTIST, `Game.maneuver` accepts it."""
    for seed in range(6):
        g = mk(bprd, seed=seed)
        rng = random.Random(seed)
        for _ in range(3):
            hand_filler(g, 0, 2)
        for f in g.own(1):
            f.pos = rng.choice(sorted(s for s in g.board.spaces if all(o.pos != s for o in g.fighters.values() if o.alive)))
        g.actions_left = 2
        act = MedusaAI(0).plan(g)
        MedusaAI(0).execute(g, act)


# ---------------------------------------------------------------- the search AI

@pytest.mark.parametrize("foe", ["hellboy", "medusa", "raphael"])
def test_the_search_places_and_boosts_legally_and_never_falls_back(bprd, foe):
    g = mk(bprd, foe)
    g.controllers[0] = ai = IsmctsMedusa(0, SearchConfig(time_budget=30.0, iterations=6, seed=1))
    for _ in range(2):
        hand_filler(g, 0, 2)
    g.actions_left = 2
    for _ in range(2):
        if g.winner is None and g.actions_left > 0:
            ai.execute(g, ai.plan(g))
    assert ai.fallbacks == 0
