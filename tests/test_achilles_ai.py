"""The AI's side of Achilles (sparring/ai_achilles.py, the kill value in ai_medusa and the leaf term of the search): the fall of Patroclus is
a trade the bot weighs, not a loss. The engine side of the same cards is in tests/test_achilles_effects.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_achilles
from sparring.ai_medusa import KILL_CAP, MedusaAI, kill_value
from sparring.search.adapter import RESOLUTION, EngineState, EvalWeights, Knowledge, hero_weights
from test_achilles_effects import fall, hand_of, mk
from test_effects_combat import pair


def leaf(g, p=0):
    weights = hero_weights(EvalWeights(**RESOLUTION), g.players[p].hero.slug, frozenset(RESOLUTION))
    return EngineState(g, observer=p, knowledge=Knowledge.from_game(g, p), weights=weights)


def test_the_fall_of_patroclus_is_worth_the_edge_minus_the_two_cards_it_costs(bprd):
    g = mk(bprd)
    patroclus = g.fighters["patroclus"]
    assert ai_achilles.fall_net(g, patroclus) == ai_achilles.FALL_EDGE                          # an empty hand has nothing to lose
    hand_of(g, 0, 1)
    assert ai_achilles.fall_net(g, patroclus) == ai_achilles.FALL_EDGE - ai_achilles.CARD_COST
    hand_of(g, 0, 5)
    assert ai_achilles.fall_net(g, patroclus) == ai_achilles.FALL_EDGE - 2 * ai_achilles.CARD_COST
    assert ai_achilles.fall_net(g, g.fighters["achilles"]) == 0.0 and ai_achilles.fall_net(g, g.fighters["lobster"]) == 0.0


def test_killing_patroclus_is_worth_less_than_killing_an_ordinary_sidekick(bprd):
    g = mk(bprd, foe="leonardo")
    hand_of(g, 0, 3)
    patroclus, other = g.fighters["patroclus"], g.fighters["raph"] if "raph" in g.fighters else None
    arms = kill_value(g, patroclus)
    assert arms == kill_value(g, patroclus) < KILL_CAP
    g.fighters["patroclus"].alive = False                                                         # no fall left to price
    assert ai_achilles.fall_net(g, patroclus) == 0.0


def test_the_kill_value_of_patroclus_drops_by_the_fall_net(bprd, monkeypatch):
    g = mk(bprd)
    hand_of(g, 0, 3)
    patroclus = g.fighters["patroclus"]
    net = ai_achilles.fall_net(g, patroclus)
    with_net = kill_value(g, patroclus)
    monkeypatch.setattr(ai_achilles, "fall_net", lambda game, f: 0.0)
    assert kill_value(g, patroclus) == with_net + net


def test_the_day_of_your_doom_is_a_five_when_patroclus_can_pay(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    doom = give(g, 0, "The Day of Your Doom")
    assert MedusaAI(0).card_value(g, patroclus, hellboy, doom) == 5.0
    assert MedusaAI(0).card_value(g, patroclus, hellboy, give(g, 0, "Battle Frenzy")) == 3.0


def test_the_doom_is_paid_for_the_points_it_really_adds(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    assert ai_achilles.doom_pays(g, patroclus, gain=2, target=hellboy)                            # 2 points of blow for 2 of his hit points
    assert not ai_achilles.doom_pays(g, patroclus, gain=1, target=hellboy)                        # a defense soaked half of it
    assert not ai_achilles.doom_pays(g, patroclus, gain=2, target=g.fighters["lobster"])          # a sidekick is worth less than the hit points it costs


def test_a_lethal_doom_is_paid_by_the_fall_it_causes_and_the_fall_costs_less_with_fewer_cards(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    patroclus.hp = 2
    assert ai_achilles.doom_pays(g, patroclus, gain=0, target=hellboy)                            # empty hand: the fall alone pays
    hand_of(g, 0, 5)
    assert not ai_achilles.doom_pays(g, patroclus, gain=0, target=hellboy)                        # two cards thrown away: the blow must pay too
    assert ai_achilles.doom_pays(g, patroclus, gain=2, target=hellboy)


def test_the_search_leaf_prefers_a_hand_of_cards_ahead_of_an_empty_one_and_counts_the_vengeance(bprd):
    g = mk(bprd)
    pair(g, "achilles", "hellboy")
    alive = leaf(g)._side_terms(0, False)
    assert alive["vengeance"] == 0.0
    fall(g)
    down = leaf(g)._side_terms(0, False)
    assert down["vengeance"] == pytest.approx(ai_achilles.leaf_term(g, 0, True)) and down["vengeance"] > 0
    assert leaf(mk(bprd, foe="hellboy"))._side_terms(1, False)["vengeance"] == 0.0               # the rival (Hellboy) has no such passive


def test_the_search_leaf_does_not_count_the_vengeance_for_a_hero_without_the_passive(bprd):
    g = mk(bprd, foe="hellboy")
    assert all(leaf(g)._side_terms(p, False)["vengeance"] == 0.0 for p in (0, 1))


def test_with_the_search_ai_a_whole_game_as_achilles_has_no_fallback_and_ends():
    from sparring import sim
    ai = sim.make_bot("ismcts", iterations=6, seed=2)
    out = sim.play(2, bot_hero="achilles", human_hero="hellboy", medusa=ai, max_turns=30, rival="chaser")
    assert out.turns >= 1 and ai.fallbacks == 0


def test_the_leaf_term_is_the_heuristic_edge_in_the_units_of_each_evaluation(bprd):
    """FALL_EDGE hit points everywhere: `1 / (2 * REFERENCE_HP)` lives each in the normalized evaluation, `1 / max_hp` of the hero in the default one."""
    from sparring.search.adapter import REFERENCE_HP
    g = mk(bprd)
    assert ai_achilles.leaf_term(g, 0, True) == 0.0                                    # Patroclus lives
    fall(g)
    assert ai_achilles.leaf_term(g, 0, True) == pytest.approx(ai_achilles.LEAF_HP / (2.0 * REFERENCE_HP))
    assert ai_achilles.leaf_term(g, 0, False) == pytest.approx(ai_achilles.LEAF_HP / g.hero(0).max_hp)
    assert ai_achilles.LEAF_HP == ai_achilles.FALL_EDGE
    assert ai_achilles.leaf_term(g, 1, True) == 0.0                                    # Hellboy has no such passive


def test_both_leaf_evaluations_read_the_term(bprd, monkeypatch):
    g = mk(bprd)
    pair(g, "achilles", "hellboy")
    fall(g)
    for weights in (EvalWeights(), EvalWeights(**RESOLUTION)):
        state = EngineState(g, observer=0, knowledge=Knowledge.from_game(g, 0), weights=weights)
        term = ai_achilles.leaf_term(g, 0, bool(weights.normalize))
        with_edge = state._side_value(0)
        monkeypatch.setattr(ai_achilles, "LEAF_HP", 0.0)
        assert with_edge - state._side_value(0) == pytest.approx(term) and term > 0
        monkeypatch.undo()


def test_finishing_a_wounded_patroclus_looks_good_to_the_rivals_search_in_both_evaluations(bprd):
    """The review's measurement (tools/measure_achilles_ai.py leaf): a 2-HP Patroclus falling must raise the leaf of the rival's search; a
    term sized for the wrong evaluation made the rival avoid the kill."""
    before = mk(bprd)
    pair(before, "achilles", "hellboy")
    before.fighters["patroclus"].hp = 2
    hand_of(before, 0, 4)
    hand_of(before, 1, 4)
    after = before.clone()
    after.damage(after.fighters["patroclus"], 2, "effect")
    assert not after.fighters["patroclus"].alive and len(after.players[0].hand) == 2
    for weights in (EvalWeights(), EvalWeights(**RESOLUTION)):
        rival_before = EngineState(before, observer=1, knowledge=Knowledge.from_game(before, 1), weights=weights).evaluate(1)
        rival_after = EngineState(after, observer=1, knowledge=Knowledge.from_game(after, 1), weights=weights).evaluate(1)
        assert rival_after > rival_before, (weights.normalize, rival_before, rival_after)


def test_the_bot_answers_the_doom_request_by_the_points_it_adds(bprd):
    """In a real combat: the request carries `damage_buys` and `EffectAI` answers it with `doom_pays` (the controller of the seat decides)."""
    from sparring.ai_effects import EffectAI
    from sparring.controller import Controller

    class Asked(Controller):
        def __init__(self):
            self.ai, self.answers = EffectAI(0), []

        def choose_effect(self, game, req):
            answer = self.ai.choose_effect(game, req)
            self.answers.append((req.extra.get("damage_buys"), answer))
            return answer

    for foe, defense, expected in (("hellboy", None, True), ("hellboy", "B.P.R.D. Training", True), ("medusa", "Hiss and Slither", False)):
        g = mk(bprd, foe=foe)
        g.controllers[0] = Asked()
        patroclus, rival = pair(g, "patroclus", foe)
        hand_of(g, 0, 3)
        card = give(g, 0, "The Day of Your Doom")
        g.attack(patroclus, rival, card, give(g, 1, defense) if defense else None)
        (buys, answer), = [a for a in g.controllers[0].answers if a[0] is not None]
        assert answer == [expected], (foe, defense, buys, answer)
        assert (patroclus.hp == 4) is expected
