"""What the AI does with Bloody Mary (docs/heroes/bloody-mary.md): the value of her third-action cards, Mirror Image priced as the copy
it is, and above all the PLAN for the third action: the bot ends a turn with exactly 3 cards in hand when it can (the next turn then has
three actions) and keeps Speak Three Times for the third action it takes.
Verified with the search AI as well as with the heuristic (`make_bot_ai({"ai": "ismcts"})`), the one the live games use."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_mary
from sparring.ai_medusa import MedusaAI
from sparring.search.adapter import RESOLUTION, EngineState, EvalWeights, Knowledge, hero_weights
from sparring.search.controller import make_bot_ai
from test_bloody_mary_effects import mk
from test_bigfoot_effects import start_turn
from test_effects_combat import pair


def bot(g, kind="heuristic", iterations=120, seed=1):
    ai = MedusaAI(0) if kind == "heuristic" else make_bot_ai({"ai": "ismcts", "ai_iterations": iterations, "ai_seed": seed})
    g.controllers = {0: ai, 1: g.controllers[1]}
    return ai


def arena(g):
    m, b = pair(g, "mary", "bat")
    start_turn(g)
    return m, b


# ---------------------------------------------------------------- the figures

def test_speak_three_times_is_a_seven_only_as_the_third_action(bprd):
    g = mk(bprd)
    m, b = arena(g)
    speak = give(g, 0, "Speak Three Times")
    assert ai_mary.attack_value(g, 0, speak, m) is None
    g.fx.taken = 2
    assert ai_mary.attack_value(g, 0, speak, m) == 7.0
    g.fx.taken = 3
    assert ai_mary.attack_value(g, 0, speak, m) is None


def test_the_figures_are_hers_only(bprd):
    g = mk(bprd)
    m, b = arena(g)
    g.fx.taken = 2
    assert ai_mary.attack_value(g, 1, give(g, 1, "Super Strength"), b) is None
    assert ai_mary.kept_cards_bonus(g, 1) == 0.0


def test_mirror_image_is_priced_at_the_attack_it_meets_and_the_mean_of_what_may_come_otherwise(bprd):
    g = mk(bprd, turn=1)
    m, b = pair(g, "mary", "bat")
    mirror = give(g, 0, "Mirror Image")
    strong = give(g, 1, "Super Strength")
    assert ai_mary.defense_value(g, 0, mirror, strong) == 5.0
    guess = ai_mary.defense_value(g, 0, mirror)
    assert 1.0 < guess < 5.0


def test_out_of_the_mirror_is_worth_its_value_plus_the_mean_boost_when_the_rival_has_cards(bprd):
    g = mk(bprd)
    m, b = arena(g)
    card = give(g, 0, "Out Of The Mirror")
    assert ai_mary.attack_value(g, 0, card, m) == 1.0
    give(g, 1, "Skirmish")
    assert 1.0 < ai_mary.attack_value(g, 0, card, m) < 5.0


def test_a_hand_of_exactly_three_cards_is_worth_an_extra_action(bprd):
    g = mk(bprd)
    arena(g)
    bonus = []
    for n in range(6):
        g.players[0].hand[:] = g.players[0].deck[:n]
        bonus.append(ai_mary.kept_cards_bonus(g, 0))
    assert bonus[3] > 0 and [b for i, b in enumerate(bonus) if i != 3] == [0.0] * 5


def test_the_heuristic_evaluation_prefers_a_hand_of_three_to_a_hand_of_four_for_her(bprd):
    g = mk(bprd)
    arena(g)
    ai = bot(g)
    g.players[0].hand[:] = g.players[0].deck[:3]
    three = ai.effect_ai().evaluate(g, 0)
    g.players[0].hand[:] = g.players[0].deck[:4]
    four = ai.effect_ai().evaluate(g, 0)
    assert three > four, "an extra card is worth less than the action that exactly three give"


def leaf(g, p=0):
    weights = hero_weights(EvalWeights(**RESOLUTION), g.players[p].hero.slug, frozenset(RESOLUTION))
    return EngineState(g, observer=p, knowledge=Knowledge.from_game(g, p), weights=weights)


def test_the_search_leaf_counts_the_third_action_of_a_hand_of_exactly_three_and_only_for_her(bprd):
    g = mk(bprd)
    arena(g)
    tempo = {}
    for held in (2, 3, 4):
        g.players[0].hand[:] = g.players[0].deck[:held]
        g.players[1].hand[:] = g.players[1].deck[:held]
        tempo[held] = (leaf(g)._side_terms(0, False)["tempo"], leaf(g)._side_terms(1, False)["tempo"])
    assert tempo[3][0] > 0 and tempo[2][0] == tempo[4][0] == 0
    assert tempo[2][1] == tempo[3][1] == tempo[4][1] == 0, "Golden Bat has no such ability"


# ---------------------------------------------------------------- Speak Three Times waits for the third action

def speak_turn(bprd, kind, seed, hand=("Speak Three Times", "Evade", "Evade")):
    """Three cards in hand at the start of the turn (the ability gives the third action), an undefended rival next to her."""
    g = mk(bprd, seed=seed)
    m, b = pair(g, "mary", "bat")
    g.players[0].hand.clear()
    for title in hand:
        give(g, 0, title, sum(1 for c in g.players[0].hand if c.title == title))
    g.players[1].hand.clear()
    g.begin_turn()
    assert g.actions_left == 3
    ai = bot(g, kind, iterations=300, seed=seed)
    return g, ai, b


@pytest.mark.parametrize("kind", ["heuristic", "ismcts"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_bot_spends_two_actions_first_and_plays_speak_three_times_as_the_third_for_seven(bprd, kind, seed):
    g, ai, b = speak_turn(bprd, kind, seed)
    ai.take_turn(g)
    assert b.max_hp - b.hp >= 7, "Speak Three Times was played before the third action (3 damage instead of 7)"
    assert g.players[0].discard[-1].title == "Speak Three Times"


@pytest.mark.parametrize("kind", ["heuristic", "ismcts"])
def test_the_first_move_of_the_turn_is_not_the_attack_it_is_waiting_to_make_stronger(bprd, kind):
    g, ai, b = speak_turn(bprd, kind, 1)
    act = ai.plan(g)
    assert not (act.kind == "attack" and act.card.title == "Speak Three Times")


def test_the_hold_ends_when_the_third_action_is_next_or_cannot_come(bprd):
    g = mk(bprd)
    m, b = arena(g)
    speak = give(g, 0, "Speak Three Times")
    g.actions_left, g.fx.taken = 2, 0
    assert not ai_mary.holds_for_third(g, 0, speak), "two actions, no Closer: a third cannot be reached"
    give(g, 0, "Closer Than She Appears")
    assert ai_mary.holds_for_third(g, 0, speak), "Closer Than She Appears gives the action back: it can"
    g.actions_left, g.fx.taken = 3, 0
    assert ai_mary.holds_for_third(g, 0, speak)
    g.actions_left, g.fx.taken = 1, 2
    assert not ai_mary.holds_for_third(g, 0, speak), "this is the third action: play it"
    g.actions_left, g.fx.taken = 2, 1
    assert ai_mary.holds_for_third(g, 0, speak)
    g.actions_left, g.fx.taken = 1, 1
    assert not ai_mary.holds_for_third(g, 0, speak) or any(c.title == "Closer Than She Appears" for c in g.players[0].hand)


def test_a_blow_that_finishes_the_rival_is_never_held(bprd):
    g = mk(bprd)
    m, b = arena(g)
    speak = give(g, 0, "Speak Three Times")
    g.actions_left, g.fx.taken = 3, 0
    assert ai_mary.holds_for_third(g, 0, speak)
    b.hp = 3
    assert not ai_mary.holds_for_third(g, 0, speak)


def test_it_only_holds_her_own_card_on_her_own_turn(bprd):
    g = mk(bprd)
    m, b = arena(g)
    speak = give(g, 0, "Speak Three Times")
    g.actions_left, g.fx.taken = 3, 0
    assert not ai_mary.holds_for_third(g, 1, speak)
    g.turn = 1
    assert not ai_mary.holds_for_third(g, 0, speak)


# ---------------------------------------------------------------- Broken Glass: the bot makes the values match when a step of 1 can

@pytest.mark.parametrize("defense,hp_lost,hand_after", [("Terrifying Roar", 2, 1), ("Skirmish", 2, 1)])
def test_the_bot_steps_broken_glass_to_match_the_rivals_card_and_draws_and_deals_two(bprd, defense, hp_lost, hand_after):
    g = mk(bprd)
    m, b = arena(g)
    bot(g)
    hp = b.hp
    res = g.attack(m, b, give(g, 0, "Broken Glass"), give(g, 1, defense))
    assert res.atk_value == res.def_value and b.hp == hp - hp_lost and len(g.players[0].hand) == hand_after


def test_the_bot_steps_broken_glass_down_to_match_a_two(bprd):
    g = mk(bprd)
    m, b = arena(g)
    bot(g)
    hp = b.hp
    res = g.attack(m, b, give(g, 0, "Broken Glass"), give(g, 1, "Sight Beyond Sight"))      # Golden Bat's 2: 3 - 1 matches
    assert (res.atk_value, res.def_value) == (2, 2) and b.hp == hp - 2


def test_the_bot_takes_the_extra_point_when_no_step_matches(bprd):
    g = mk(bprd)
    m, b = arena(g)
    bot(g)
    hp = b.hp
    res = g.attack(m, b, give(g, 0, "Broken Glass"), give(g, 1, "He Laughs at Your Feebleness"))      # 5: out of reach
    assert res.atk_value == 4 and b.hp == hp
    g2 = mk(bprd)
    m2, b2 = arena(g2)
    bot(g2)
    assert g2.attack(m2, b2, give(g2, 0, "Broken Glass"), None).atk_value == 4 and b2.hp == b2.max_hp - 4


def test_pick_broken_glass_reads_the_labels_and_keeps_to_the_options_offered():
    labels = ["+1", "-1", "0"]
    assert ai_mary.pick_broken_glass([3, 3], [0, 1, 2], labels) == 2
    assert ai_mary.pick_broken_glass([3, 4], [0, 1, 2], labels) == 0
    assert ai_mary.pick_broken_glass([3, 2], [0, 1, 2], labels) == 1
    assert ai_mary.pick_broken_glass([3, 9], [0, 1, 2], labels) == 0
    assert ai_mary.pick_broken_glass([3, 9], [2, 1], labels) == 2
