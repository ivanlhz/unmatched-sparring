"""How the bot plays Robin Hood (sparring/ai_robin.py): the value an Ambush will have, Highway Robbery as a card that makes the defense count for
nothing, the price of each AFTER the data-driven profile does not read (Disarming Shot, Snark, Wily Fighting, Defenders of Sherwood), the answer
of the bot as the rival of Steal From the Rich, and whole games with the heuristic and the search AI in both seats."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_robin, sim
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import CARD_VALUE, MedusaAI, Model
from sparring.effects.choose import ChoiceRequest
from sparring.search.controller import make_bot_ai
from test_effects_combat import pair, put_adjacent
from test_robin_hood_effects import mk


def steal_request(g, rival=1):
    """What the interpreter asks the RIVAL of Robin Hood when he plays Steal From the Rich: discard a card (yes) or let him draw one more (no)."""
    steal = give(g, 0, "Steal From the Rich")
    return ChoiceRequest("optional", rival, [True, False], key="scheme/1:0", prompt="", card_id=steal.card_id, card_owner=0, extra={"cost_cards": 1})


# ---------------------------------------------------------------- the value of the attacks

def test_ambush_is_worth_two_plus_the_average_boost_of_what_the_rival_may_still_hold(bprd):
    g = mk(bprd)
    ambush = give(g, 0, "Ambush")
    rival = g.players[1]
    rival.hand.append(rival.deck[0])
    left = [c for c in rival.full_set if c not in rival.gone]
    assert ai_robin.attack_value(g, 0, ambush) == pytest.approx(2 + sum(c.boost for c in left) / len(left))
    rival.hand.clear()
    assert ai_robin.attack_value(g, 0, ambush) == 2


def test_only_robin_hoods_own_ambush_and_highway_robbery_are_priced_here(bprd):
    g = mk(bprd)
    assert ai_robin.attack_value(g, 0, give(g, 0, "A Hunter's Eye")) is None
    assert ai_robin.attack_value(g, 1, give(g, 0, "Ambush")) is None          # the rival of Robin Hood does not play it
    assert not ai_robin.ignores_defense(g, 0, give(g, 0, "Piercing Shot")) and ai_robin.ignores_defense(g, 0, give(g, 0, "Highway Robbery"))
    assert not ai_robin.ignores_defense(g, 1, give(g, 0, "Highway Robbery"))


def test_the_planner_reads_highway_robbery_as_a_blow_that_nothing_blocks(bprd):
    g = mk(bprd)
    outlaw, hellboy = pair(g, "outlaw1", "hellboy")
    robbery = give(g, 0, "Highway Robbery")
    assert MedusaAI.ignores_defense(g, outlaw, hellboy, robbery)
    ai = MedusaAI(0)
    model = Model(g, 0)
    ignoring = ai.attack_outcome(g, model, outlaw, hellboy, robbery)
    plain = ai.attack_outcome(g, model, outlaw, hellboy, give(g, 0, "Regroup"))          # versatile 1: the same 2 against a 0 would be a poor blow
    assert ignoring[1] >= 2 - 1e-9 and ignoring[1] > plain[1]


def test_the_planner_values_the_ambush_above_its_printed_two(bprd):
    g = mk(bprd)
    g.players[1].hand.append(g.players[1].deck[0])
    robin, hellboy = pair(g, "robin", "hellboy")
    ambush = give(g, 0, "Ambush")
    assert MedusaAI(0).card_value(g, robin, hellboy, ambush) > 2


# ---------------------------------------------------------------- the AFTER effects

def test_disarming_shot_is_worth_the_cards_it_draws_when_it_wins(bprd):
    g = mk(bprd)
    card = give(g, 0, "Disarming Shot")
    assert ai_robin.after_value(g, 0, card, 1.0, 1.0, CARD_VALUE) == pytest.approx(CARD_VALUE * ai_robin.DISARMING_DRAWS)
    assert ai_robin.after_value(g, 0, card, 0.0, 1.0, CARD_VALUE) == 0
    assert ai_robin.after_value(g, 1, card, 1.0, 1.0, CARD_VALUE) == 0           # not his card for the rival of Robin Hood


def test_snark_and_wily_fighting_are_worth_something_only_next_to_a_rival(bprd):
    g = mk(bprd, foe="yennenga")
    robin, yen = pair(g, "robin", "yennenga")
    far = max(s for s in g.board.spaces if not g.board.share_zone(robin.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    for f in g.fighters.values():
        if f.owner == 1:
            f.pos = far if f is yen else f.pos
    snark, wily = give(g, 0, "Snark"), give(g, 0, "Wily Fighting")
    assert ai_robin.after_value(g, 0, snark, 0.5, 1.0, CARD_VALUE) == 0 and ai_robin.after_value(g, 0, wily, 0.5, 1.0, CARD_VALUE) == 0
    put_adjacent(g, "yennenga", "robin")
    put_adjacent(g, "archer1", "robin")
    assert ai_robin.after_value(g, 0, snark, 0.5, 1.0, CARD_VALUE) == CARD_VALUE
    assert ai_robin.after_value(g, 0, wily, 0.5, 1.0, CARD_VALUE) == 2.0


def test_the_planner_adds_the_after_of_disarming_shot_to_the_attack_and_of_defenders_of_sherwood_to_the_defense(bprd, monkeypatch):
    g = mk(bprd)
    robin, hellboy = pair(g, "robin", "hellboy")
    ai = MedusaAI(0)
    ai._attacker, ai._defender = hellboy, robin               # the combat the defense is chosen in
    shot, defenders = give(g, 0, "Disarming Shot"), give(g, 0, "Defenders of Sherwood")
    with_hook = ai.attack_outcome(g, Model(g, 0), robin, hellboy, shot)[0], ai.eval_defense(g, Model(g, 0), [(1.0, 5)], robin, defenders)
    monkeypatch.setattr(ai_robin, "after_value", lambda *args: 0.0)
    without = ai.attack_outcome(g, Model(g, 0), robin, hellboy, shot)[0], ai.eval_defense(g, Model(g, 0), [(1.0, 5)], robin, defenders)
    assert with_hook[0] > without[0] and with_hook[1] > without[1]


def test_defenders_of_sherwood_is_worth_more_with_an_outlaw_to_bring_back(bprd):
    g = mk(bprd)
    card = give(g, 0, "Defenders of Sherwood")
    alone = ai_robin.after_value(g, 0, card, 1.0, 1.0, CARD_VALUE)
    g.damage(g.fighters["outlaw1"], 1, "effect")
    g.fighters["outlaw1"].died_at = 1
    assert ai_robin.after_value(g, 0, card, 1.0, 1.0, CARD_VALUE) > alone == CARD_VALUE


# ---------------------------------------------------------------- Steal From the Rich, answered by the bot

def test_the_bot_rival_discards_a_card_worth_less_than_the_one_robin_would_draw(bprd):
    g = mk(bprd)
    g.players[1].hand[:] = [give(g, 1, "Horseshoes And Hand Grenades")]
    assert EffectAI(1).decide(g, steal_request(g), nested=False) == [True]


def test_the_bot_rival_keeps_a_hand_of_cards_dearer_than_the_one_robin_would_draw(bprd):
    g = mk(bprd)
    g.players[1].hand[:] = [give(g, 1, "Excalibur")]
    assert EffectAI(1).decide(g, steal_request(g), nested=False) == [False]


def test_the_bot_rival_judges_by_the_cards_robin_may_still_hold_not_by_his_hand(bprd):
    from sparring.search.adapter import card_worth
    g = mk(bprd)
    robin = g.players[0]
    average = lambda cards: sum(card_worth(c) for c in cards) / len(cards)
    weak = sorted(robin.full_set, key=card_worth)[:12]
    held = next(c for c in g.players[1].full_set if average(weak) < card_worth(c) < average(robin.full_set))
    g.players[1].hand[:] = [give(g, 1, held.title)]
    assert EffectAI(1).decide(g, steal_request(g), nested=False) == [True]       # all of his cards are still to come: one is worth more than this
    robin.discard.extend(c for c in robin.full_set if c not in weak)              # the strong ones are on his pile, in the open
    assert EffectAI(1).decide(g, steal_request(g), nested=False) == [False]      # what he may still draw is worth less than this


def test_only_steal_from_the_rich_is_answered_here(bprd):
    g = mk(bprd)
    req = steal_request(g)
    other = ChoiceRequest("optional", 1, [True, False], key="scheme/1:0", prompt="", card_id=g.players[1].full_set[0].card_id, card_owner=1, extra={"cost_cards": 1})
    assert ai_robin.is_steal(g, req) and not ai_robin.is_steal(g, other)


# ---------------------------------------------------------------- whole games

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ismcts_plays_robin_hood_in_a_game(seed):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="robin-hood", human_hero="hellboy", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0


@pytest.mark.parametrize("seed", [1, 2])
def test_the_search_plays_against_a_human_robin_hood(seed):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 30, "ai_seed": seed})
    out = sim.play(seed, bot_hero="hellboy", human_hero="robin-hood", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0


def test_the_heuristic_ai_plays_robin_hood_and_wins_most_games_against_the_chaser():
    wins = sum(sim.play(seed, bot_hero="robin-hood", human_hero="hellboy", rival="chaser", max_turns=40).winner == "Robin Hood" for seed in range(6))
    assert wins >= 3


def test_snark_and_wily_fighting_are_priced_from_the_fighter_that_plays_them_not_from_robin(bprd, monkeypatch):
    g = mk(bprd)
    outlaw, hellboy = pair(g, "outlaw1", "hellboy")                      # the Outlaw stands next to the rival, Robin is far away
    snark, wily = give(g, 0, "Snark"), give(g, 0, "Wily Fighting")
    assert ai_robin.after_value(g, 0, snark, 0.5, 1.0, CARD_VALUE) == 0       # no fighter given: Robin Hood, who is not next to anyone
    assert ai_robin.after_value(g, 0, snark, 0.5, 1.0, CARD_VALUE, outlaw) == CARD_VALUE
    assert ai_robin.after_value(g, 0, wily, 0.5, 1.0, CARD_VALUE, outlaw) == 1.0
    seen = []
    real = ai_robin.after_value
    monkeypatch.setattr(ai_robin, "after_value", lambda *args: seen.append(args[-1]) or real(*args))
    MedusaAI(0).attack_outcome(g, Model(g, 0), outlaw, hellboy, snark)
    assert seen == [outlaw]                                                    # the planner passes the attacker, not the hero
