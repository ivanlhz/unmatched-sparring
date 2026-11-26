"""How the bot answers Blackbeard's doubloon decisions (sparring/ai_blackbeard.py): a ransom as the opponent, Queen Anne's Revenge's payment, and the
doubloon for an action as Blackbeard; and whole games with the search AI on both sides of the table, where the doubloons always add up to three.

The generic answer to an optional is yes, so before the hooks the bot paid every ransom it could afford and bought an action every turn."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_blackbeard, sim
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import keep_value
from sparring.effects.choose import ChoiceRequest
from sparring.effects.select import counter_value
from sparring.search.controller import make_bot_ai
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair


def vs_blackbeard(bprd, hero="hellboy", seed=3):
    """The bot (player 0) plays `hero` against Blackbeard (player 1): the bot is the one asked about the ransom."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(hero, "blackbeard"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def as_blackbeard(bprd, foe="hellboy", seed=3):
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("blackbeard", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    ctl[0].queue = [[False]]
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def set_coins(g, held, treasury):
    g.fx.set_counter(1 if g.players[1].hero.slug == "blackbeard" else 0, "doubloons", held)
    g.fx.set_counter(1 if g.players[1].hero.slug == "blackbeard" else 0, "treasury", treasury)


def ransom(g, n, effect, treasury=2):
    req = ChoiceRequest("optional", 0, [True, False], 1, 1, None, "after/0:0", "pay the ransom?", {"ransom": n, "effect": effect, "treasury": treasury}, 1)
    return EffectAI(0).decide(g, req, nested=False)


# ---------------------------------------------------------------- the ransom, as the opponent

def test_the_bot_pays_two_doubloons_to_save_its_hero_from_the_pistols(bprd):
    g = vs_blackbeard(bprd)
    hero = g.hero(0)
    hero.hp = 3
    assert ransom(g, 2, {"what": "damage", "amount": 3, "fighters": [hero.fid]}) == [True]


def test_the_bot_does_not_pay_a_doubloon_for_one_point_of_damage_to_a_fresh_sidekick(bprd):
    g = vs_blackbeard(bprd)
    side = next(f for f in g.own(0) if not f.hero)
    assert ransom(g, 1, {"what": "damage", "amount": 1, "fighters": [side.fid]}) == [False]


def test_the_bot_pays_one_doubloon_to_save_a_sidekick_from_a_kill(bprd):
    g = vs_blackbeard(bprd)
    side = next(f for f in g.own(0) if not f.hero)
    side.hp = 1
    assert ransom(g, 1, {"what": "damage", "amount": 1, "fighters": [side.fid]}) == [True]


def test_damage_to_blackbeards_own_fighters_is_not_a_cost_of_the_bot(bprd):
    g = vs_blackbeard(bprd)
    assert ransom(g, 1, {"what": "damage", "amount": 3, "fighters": ["blackbeard"]}) == [False]


def test_the_bot_pays_to_keep_a_good_card_and_not_a_poor_one_from_a_discard(bprd):
    g = vs_blackbeard(bprd)
    cards = {c.title: c for c in g.players[0].full_set}
    hand = [cards["Excalibur"], cards["On Earth As It Is In Hell"], cards["Service Pistol"]]
    g.players[0].hand[:] = hand
    best = max(hand, key=lambda c: keep_value(c, hand))
    worst = min(hand, key=lambda c: keep_value(c, hand))
    assert ransom(g, 1, {"what": "discard", "cards": [best.card_id]}) == [keep_value(best, hand) > ai_blackbeard.COIN + ai_blackbeard.PAY_MARGIN]
    assert ransom(g, 1, {"what": "random_discard", "cards": [worst.card_id]}) == [keep_value(worst, hand) > ai_blackbeard.COIN + ai_blackbeard.PAY_MARGIN]
    assert keep_value(best, hand) > keep_value(worst, hand)


def test_the_bot_pays_to_keep_blackbeard_from_healing_when_he_is_hurt_and_not_when_he_is_whole(bprd):
    g = vs_blackbeard(bprd)
    g.hero(1).hp = 6
    assert ransom(g, 1, {"what": "heal", "amount": 2}) == [True]
    g.hero(1).hp = 13
    assert ransom(g, 1, {"what": "heal", "amount": 2}) == [False]


def test_a_cancel_with_nothing_to_cancel_is_never_paid(bprd):
    g = vs_blackbeard(bprd)
    assert ransom(g, 2, {"what": "cancel", "moments": 0}) == [False]


def test_a_ransom_is_priced_by_the_line_not_by_how_many_doubloons_are_left(bprd):
    g = vs_blackbeard(bprd)
    hero = g.hero(0)
    hero.hp = 3
    line = {"what": "damage", "amount": 3, "fighters": [hero.fid]}
    assert ransom(g, 1, line, treasury=1) == ransom(g, 1, line, treasury=3) == [True]


# ---------------------------------------------------------------- Queen Anne's Revenge

def queens(g, atk, dfn, queen_attacks, treasury, target):
    req = ChoiceRequest("amount", 0, list(range(treasury + 1)), 1, 1, None, "during/0:0", "doubloons to pay",
                        {"queens": 2, "treasury": treasury, "atk": atk, "dfn": dfn, "queen_attacks": queen_attacks, "target": target}, 1)
    return EffectAI(0).decide(g, req, nested=False)


def test_against_an_attacking_queen_anne_the_bot_pays_the_doubloons_that_save_hit_points_and_no_more(bprd):
    g = vs_blackbeard(bprd)
    hero = g.hero(0)
    assert queens(g, 7, 3, True, 3, hero.fid) == [2]           # 7 - 4 = 3: the blow is gone after two doubloons, the third saves nothing
    assert queens(g, 7, 3, True, 1, hero.fid) == [1]
    assert queens(g, 7, 7, True, 3, hero.fid) == [0]           # nothing to save


def test_against_a_defending_queen_anne_the_bot_pays_only_when_the_extra_damage_is_worth_it(bprd):
    g = vs_blackbeard(bprd)
    assert queens(g, 6, 7, False, 3, "blackbeard") == [3]      # 7 - 6 = 1 doubloon-free: each doubloon turns two points into damage on his hero
    assert queens(g, 2, 7, False, 3, "blackbeard") == [0]      # a 2 never gets through a 7 for three doubloons


def test_with_nothing_known_about_the_combat_the_bot_pays_nothing(bprd):
    g = vs_blackbeard(bprd)
    req = ChoiceRequest("amount", 0, [0, 1, 2], 1, 1, None, "during/0:0", "doubloons to pay", {"queens": 2, "treasury": 2}, 1)
    assert EffectAI(0).decide(g, req, nested=False) == [0]


# ---------------------------------------------------------------- the doubloon for an action, as Blackbeard

def ask_action(g, held=2, treasury=1):
    req = ChoiceRequest("optional", 0, [True, False], 1, 1, None, "doubloon_action/0:0", "do it?",
                        {"doubloon_action": 1, "held": held, "treasury": treasury}, None)
    return EffectAI(0).decide(g, req, nested=False)


def test_the_bot_buys_an_action_when_it_holds_a_card_to_play(bprd):
    g = as_blackbeard(bprd)
    give(g, 0, "Give No Quarter")
    give(g, 0, "A Brace of Primed Pistols")
    assert ask_action(g, 2, 1) == [True]


def test_the_bot_does_not_buy_an_action_with_nothing_to_play_it_on(bprd):
    g = as_blackbeard(bprd)
    give(g, 0, "Intimidating Visage")
    assert ask_action(g, 2, 1) == [False]


def test_the_bot_buys_an_action_even_with_two_doubloons_already_in_the_treasury(bprd):
    """Measured: a Treasury cap of 2 lost 41 games of 60 against 50 without it (tools/measure_blackbeard_ai.py caps)."""
    g = as_blackbeard(bprd)
    give(g, 0, "Give No Quarter")
    assert ask_action(g, 1, 2) == [True]


def test_a_scheme_counts_as_a_card_to_play(bprd):
    g = as_blackbeard(bprd)
    give(g, 0, "Plunder")
    assert ask_action(g, 2, 1) == [True]


def test_a_card_nobody_on_the_board_can_play_does_not_count(bprd):
    g = as_blackbeard(bprd)
    give(g, 0, "Light the Fuse")                    # a Sea Dog's card
    for d in ("seadog1", "seadog2"):
        g.defeat(g.fighters[d])
    assert ask_action(g, 2, 1) == [False]


# ---------------------------------------------------------------- whole games with the search AI

class Spy:
    """Counts what the hooks answered, so a game proves they were asked."""

    def __init__(self, monkeypatch):
        self.ransoms, self.amounts, self.actions = [], [], []
        for name, bucket in (("ransom_pays", self.ransoms), ("queens_amount", self.amounts), ("action_pays", self.actions)):
            orig = getattr(ai_blackbeard, name)

            def wrap(ai, game, req, orig=orig, bucket=bucket):
                out = orig(ai, game, req)
                bucket.append(out)
                return out
            monkeypatch.setattr(ai_blackbeard, name, wrap)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ismcts_plays_blackbeard_and_the_doubloons_always_add_up_to_three(monkeypatch, seed):
    spy = Spy(monkeypatch)
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="blackbeard", human_hero="hellboy", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0
    assert spy.actions, "the start-of-turn question was asked"
    g = out.game if hasattr(out, "game") else None
    if g is not None:
        assert counter_value(g, 0, "doubloons") + counter_value(g, 0, "treasury") == 3


def test_the_heuristic_ai_plays_blackbeard_too(monkeypatch):
    spy = Spy(monkeypatch)
    out = sim.play(1, bot_hero="blackbeard", human_hero="hellboy", rival="chaser", max_turns=40)
    assert out.winner in ("Blackbeard", "Hellboy", "draw") and spy.actions


@pytest.mark.parametrize("seed", [1, 2])
def test_ismcts_as_the_opponent_of_blackbeard_answers_ransoms_without_a_fallback(monkeypatch, seed):
    spy = Spy(monkeypatch)
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="hellboy", human_hero="blackbeard", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0
