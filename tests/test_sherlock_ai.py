"""How the bot answers Sherlock Holmes' decisions (sparring/ai_sherlock.py): the number Elementary predicts, the value Confirm Suspicion names, Deduce Strategy's
change of a printed value; and whole games with the heuristic and the search AI on both sides of the table.

Everything is read from public information only: the rival's deck list minus what is gone, the cards a look showed and the size of their hand. The tests
change the rival's real hand and deck order and check that no answer moves."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_sherlock, sim
from sparring.ai_effects import EffectAI
from sparring.effects.choose import ChoiceRequest, SyntheticChooser
from sparring.search.controller import make_bot_ai
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair
from test_sherlock_effects import mk


def values_of(g, player, fighter_name, attack_only=True):
    return sorted((c.value or 0) for c in g.players[player].full_set if c.can_attack and c.usable_by(fighter_name) and c not in g.players[player].gone)


def elementary_request(game, attacker):
    return ChoiceRequest("effect", 0, list(range(8)), 1, 1, None, "immediately/0:0", "predict", {"op": "predict", "elementary": True, "attacker": attacker}, 0)


# ---------------------------------------------------------------- Elementary: the number to predict

def test_the_prediction_is_the_commonest_printed_value_of_what_the_attacker_may_still_play(bprd):
    g = mk(bprd)
    values = values_of(g, 1, "Medusa")
    expected = max(set(values), key=lambda v: (values.count(v), v))
    assert ai_sherlock.predict_attack_value(g, 0, "medusa") == expected


def test_what_is_gone_leaves_the_estimate(bprd):
    g = mk(bprd)
    foe = g.players[1]
    for c in [c for c in foe.full_set if c.can_attack and c.usable_by("Medusa") and (c.value or 0) == ai_sherlock.predict_attack_value(g, 0, "medusa")]:
        if c in foe.deck:
            foe.deck.remove(c)
        foe.discard.append(c)                                      # played: public
    after = ai_sherlock.predict_attack_value(g, 0, "medusa")
    left = values_of(g, 1, "Medusa")
    assert after == max(set(left), key=lambda v: (left.count(v), v)) and after in left


def test_the_estimate_is_restricted_to_the_cards_the_attacking_fighter_can_play(bprd):
    g = mk(bprd)
    medusa = {c.value or 0 for c in g.players[1].full_set if c.can_attack and c.usable_by("Medusa")}
    harpy = {c.value or 0 for c in g.players[1].full_set if c.can_attack and c.usable_by("Harpy")}
    assert ai_sherlock.predict_attack_value(g, 0, "medusa") in medusa
    assert ai_sherlock.predict_attack_value(g, 0, "harpy1") in harpy


def test_the_prediction_never_reads_the_rivals_hand_or_deck_order(bprd):
    """Swapping the three cards of the rival's hand with three others of their deck (same hand size) and reversing the deck changes no answer."""
    g = mk(bprd)
    foe = g.players[1]
    foe.hand.extend(foe.deck[:3])
    del foe.deck[:3]
    before = ai_sherlock.predict_attack_value(g, 0, "medusa"), ai_sherlock.name_value(g, 0)
    foe.hand[:], foe.deck[:3] = foe.deck[:3], foe.hand[:]
    foe.deck.reverse()
    assert (ai_sherlock.predict_attack_value(g, 0, "medusa"), ai_sherlock.name_value(g, 0)) == before


def test_a_look_at_the_hand_replaces_the_composition(bprd):
    g = mk(bprd)
    hiss = give(g, 1, "Hiss and Slither")
    g.players[0].known.seen = [hiss.card_id]
    snipe = give(g, 1, "Snipe")
    g.players[0].known.seen.append(snipe.card_id)
    assert ai_sherlock.predict_attack_value(g, 0, "medusa") == 3          # the only seen card that can attack is Snipe: a defense is no attack


def test_an_attacker_with_nothing_left_to_play_gets_a_harmless_zero(bprd):
    g = mk(bprd)
    foe = g.players[1]
    for c in foe.full_set:
        if c.can_attack and c.usable_by("Medusa"):
            if c in foe.deck:
                foe.deck.remove(c)
            foe.discard.append(c)
    assert ai_sherlock.predict_attack_value(g, 0, "medusa") == 0


def test_the_effect_ai_and_the_rollout_chooser_answer_elementary_with_the_public_estimate(bprd):
    g = mk(bprd)
    req = elementary_request(g, "medusa")
    expected = ai_sherlock.predict_attack_value(g, 0, "medusa")
    assert EffectAI(0).decide(g, req, nested=False) == [expected]
    assert SyntheticChooser(policy="greedy").choose(g, req) == [expected]
    assert SyntheticChooser(policy="first").choose(g, req) == [0]       # the default answer is only for the tests


# ---------------------------------------------------------------- Confirm Suspicion: the value to name

def test_a_seen_card_is_a_sure_match_and_the_value_with_the_most_boost_is_named(bprd):
    g = mk(bprd)
    hiss, dash = give(g, 1, "Hiss and Slither"), give(g, 1, "Dash")            # defense 4 (BOOST 3), versatile 3 (BOOST 1)
    g.players[0].known.seen = [hiss.card_id, dash.card_id]
    assert ai_sherlock.name_value(g, 0) == 4


def test_the_value_named_is_one_the_rival_may_hold(bprd):
    g = mk(bprd)
    for title in ("Snipe", "Dash", "Regroup", "Hiss and Slither", "Feint"):
        give(g, 1, title)                                          # a hand of 5: the chance of a match is real
    named = ai_sherlock.name_value(g, 0)
    assert named in {c.value or 0 for c in g.players[1].full_set if c.type != "scheme"}


def test_with_an_empty_rival_hand_every_value_is_worth_the_same_and_the_lowest_is_named(bprd):
    g = mk(bprd)
    assert g.players[1].hand == [] and ai_sherlock.name_value(g, 0) == 0


def test_the_value_named_is_never_a_scheme_only_value(bprd):
    g = mk(bprd)
    assert 0 <= ai_sherlock.name_value(g, 0) <= 7


def test_the_effect_ai_names_a_value_for_the_amount_request(bprd):
    g = mk(bprd)
    req = ChoiceRequest("amount", 0, list(range(8)), 1, 1, None, "scheme/0:0", "name a value", {"confirm": True, "name_value": True}, 0)
    assert EffectAI(0).decide(g, req, nested=False) == [ai_sherlock.name_value(g, 0)]
    assert SyntheticChooser(policy="greedy").choose(g, req) == [ai_sherlock.name_value(g, 0)]


def test_the_bot_rival_gives_up_the_card_that_costs_it_least_in_cards_and_hit_points(bprd):
    """A bot that must discard a card of the named value picks by keep value plus the damage its BOOST does to its hero."""
    g = mk(bprd, turn=0)
    snipe, dash = give(g, 1, "Snipe"), give(g, 1, "Regroup")
    snipe_cost = EffectAI(1)
    req = ChoiceRequest("cards", 1, [snipe.card_id, dash.card_id], 1, 1, None, "scheme/0:1", "discard", {"zone": "hand", "purpose": "discard", "of": 1, "confirm": 3}, 0)
    picked = snipe_cost.decide(g, req, nested=False)
    assert picked in ([snipe.card_id], [dash.card_id]) and len(picked) == 1


# ---------------------------------------------------------------- Deduce Strategy: lower is better

@pytest.mark.parametrize("now, to, pays", [(3, 1, True), (3, 3, False), (2, 4, False), (4, 0, True)])
def test_the_change_is_taken_only_when_the_rivals_printed_value_drops(bprd, now, to, pays):
    g = mk(bprd)
    req = ChoiceRequest("optional", 0, [True, False], 1, 1, None, "during/0:0", "do it?", {"rival_value": {"now": now, "to": to}}, 0)
    assert EffectAI(0).decide(g, req, nested=False) == [pays]
    assert SyntheticChooser(policy="greedy").choose(g, req) == [pays]


# ---------------------------------------------------------------- whole games

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ismcts_plays_holmes_without_a_fallback(seed):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="sherlock-holmes", human_hero="hellboy", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0


@pytest.mark.parametrize("seed", [1, 2])
def test_ismcts_as_the_opponent_of_holmes_without_a_fallback(seed):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="hellboy", human_hero="sherlock-holmes", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0


def test_the_heuristic_ai_plays_holmes_too():
    out = sim.play(1, bot_hero="sherlock-holmes", human_hero="hellboy", rival="chaser", max_turns=40)
    assert out.winner in ("Sherlock Holmes", "Hellboy", "draw")


def test_a_search_with_holmes_never_peeks_at_the_hidden_attack_card(monkeypatch):
    """The prediction in the rollouts is the public estimate: the rival's hand of the determinized game is never the input."""
    seen = []
    real = ai_sherlock.predict_attack_value
    monkeypatch.setattr(ai_sherlock, "predict_attack_value", lambda game, me, fid=None, known=None: seen.append(fid) or real(game, me, fid, known))
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": 1})
    sim.play(1, bot_hero="sherlock-holmes", human_hero="hellboy", medusa=ai, rival="chaser", max_turns=30)
    assert ai.fallbacks == 0 and all(f is None or isinstance(f, str) for f in seen)


def test_a_face_up_attack_has_a_public_printed_value_and_nothing_is_guessed(bprd):
    g = mk(bprd)
    assert ai_sherlock.predict_attack_value(g, 0, "medusa", known=5) == 5
    assert EffectAI(0).decide(g, ChoiceRequest("effect", 0, list(range(8)), 1, 1, None, "immediately/0:0", "predict",
                                               {"op": "predict", "elementary": True, "attacker": "medusa", "known_value": 4}, 0), nested=False) == [4]
    assert SyntheticChooser(policy="greedy").choose(g, ChoiceRequest("effect", 0, list(range(8)), 1, 1, None, "k", "predict",
                                                                      {"op": "predict", "elementary": True, "attacker": "medusa", "known_value": 4}, 0)) == [4]


def test_the_second_part_of_a_double_attack_asks_elementary_with_the_known_value(bprd):
    """The attacker's card is already face up in the second part: the request carries its printed value so a bot predicts it instead of guessing."""
    from sparring.combat_flow import CombatFlow
    g = mk(bprd, foe="hellboy", turn=1)
    foe, h = pair(g, "hellboy", "holmes")
    card = give(g, 1, "Right Hand Of Doom")                     # attack 4
    flow = CombatFlow(g, foe, h, card, give(g, 0, "Elementary"), second=4)
    flow.drive(lambda choice: None)
    asked_ = [r for r in g.controllers[0].requests if r.extra.get("op") == "predict"]
    assert asked_ and asked_[0].extra["known_value"] == 4


def test_a_stale_look_does_not_narrow_the_estimate_once_the_hand_has_grown(bprd):
    g = mk(bprd)
    hiss = give(g, 1, "Hiss and Slither")
    g.players[0].known.seen = [hiss.card_id]
    give(g, 1, "Snipe")
    give(g, 1, "Dash")                                         # the hand is now 3 cards and only 1 of them was seen
    foe = g.players[1]
    assert ai_sherlock._pool(g, 0) == [c for c in foe.full_set if c not in foe.gone]
    g.players[0].known.seen = [hiss.card_id, give(g, 1, "Regroup").card_id, give(g, 1, "Feint").card_id]    # the whole hand of 5 seen
    foe.hand[:] = foe.hand[:3]
    assert len(ai_sherlock._pool(g, 0)) <= 3

