"""What the AI makes of Chupacabra's cards (sparring/ai_chupacabra.py and its hooks in `MedusaAI`): the value an attack will have, the
AFTER of each card, and the bot playing him with the heuristic and with the search (`make_bot_ai({"ai": "ismcts"})`)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_chupacabra as ai
from sparring.ai_medusa import MedusaAI, Model
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_chupacabra_effects import mk
from test_effects_combat import pair

TRAINING = "B.P.R.D. Training"


def card_of(g, title):
    return next(c for c in g.players[0].full_set if c.title == title)


# ---------------------------------------------------------------- the figures

def test_the_more_they_struggle_is_twice_the_average_block_the_rival_may_hold(bprd):
    g = mk(bprd)
    blocks = [c.value for c in g.players[1].full_set if c.can_defend and c.value is not None]
    assert ai.attack_value(g, 0, card_of(g, ai.MORE)) == pytest.approx(2 * sum(blocks) / len(blocks))
    assert ai.attack_value(g, 0, card_of(g, ai.MORE)) > 4


def test_the_rival_cards_already_played_leave_the_average(bprd):
    g = mk(bprd)
    before = ai.attack_value(g, 0, card_of(g, ai.MORE))
    for c in [c for c in g.players[1].full_set if c.title == TRAINING]:        # the rival's value-3 blocks gone
        g.players[1].deck.remove(c) if c in g.players[1].deck else None
        g.players[1].discard.append(c)
    assert ai.attack_value(g, 0, card_of(g, ai.MORE)) != before


def test_ambush_is_worth_its_two_plus_the_average_boost_only_when_the_rival_holds_a_card(bprd):
    g = mk(bprd)
    ambush = card_of(g, ai.AMBUSH)
    assert ai.attack_value(g, 0, ambush) == 2.0
    give(g, 1, "Excalibur")
    assert 3.0 < ai.attack_value(g, 0, ambush) < 6.0


@pytest.mark.parametrize("hp,value", [(7, 5.0), (3, 5.0), (8, None), (14, None)])
def test_wounded_beast_is_a_five_for_a_hero_with_seven_or_less_health(bprd, hp, value):
    g = mk(bprd)
    g.fighters["chupacabra"].hp = hp
    assert ai.attack_value(g, 0, card_of(g, ai.WOUNDED)) == value
    assert ai.defense_value(g, 0, card_of(g, ai.WOUNDED)) == value


def test_the_other_cards_keep_their_printed_value_and_the_rivals_are_never_touched(bprd):
    g = mk(bprd)
    assert ai.attack_value(g, 0, card_of(g, "Feeding")) is None
    other = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("hellboy", "chupacabra"), bot_player=0)
    assert ai.attack_value(other, 0, next(c for c in other.players[0].full_set)) is None
    assert ai.after_value(other, 0, card_of(g, "Feeding"), 0.5, 1, 1, 1, 1) == 0.0


def test_the_afters_are_priced_from_his_health_and_the_board(bprd):
    g = mk(bprd)
    chupa, hellboy = pair(g, "chupacabra", "hellboy")
    args = (0.5, 1.0, 1.0, 1.0, 1.0)         # p_win, foe weight, card value, hero weight, action value
    assert ai.after_value(g, 0, card_of(g, "Feeding"), *args) == 0.0                         # healthy: nothing
    chupa.hp = 5
    assert ai.after_value(g, 0, card_of(g, "Feeding"), *args) == 2.0                         # a hit point and the action
    assert ai.after_value(g, 0, card_of(g, ai.LUNGE), 1.0, 1, 1, 1, 1) == 2.0                # won: two
    assert ai.after_value(g, 0, card_of(g, ai.LUNGE), 0.0, 1, 1, 1, 1) == 1.0                # lost: one
    assert ai.after_value(g, 0, card_of(g, ai.TOOTH), *args) == 2.0                          # one fighter beside him: one blow, one heal
    assert ai.after_value(g, 0, card_of(g, ai.TOUGHNESS), 0.0, 1, 1, 1, 1) == ai.TOUGHNESS_RETURN
    assert ai.after_value(g, 0, card_of(g, ai.TOUGHNESS), 1.0, 1, 1, 1, 1) == 0.0


# ---------------------------------------------------------------- the heuristic reads them

def test_the_heuristic_values_the_more_they_struggle_as_the_attack_it_is(bprd):
    g = mk(bprd)
    chupa, hellboy = pair(g, "chupacabra", "hellboy")
    ai_ = MedusaAI(0)
    more = give(g, 0, ai.MORE)
    assert ai_.card_value(g, chupa, hellboy, more) == ai.attack_value(g, 0, more) > 4
    chupa.hp = 6
    assert ai_.card_value(g, chupa, hellboy, give(g, 0, ai.WOUNDED)) == 5.0


def test_the_heuristic_defends_with_a_wounded_beast_worth_five(bprd):
    g = mk(bprd, turn=1)
    chupa, hellboy = pair(g, "chupacabra", "hellboy")
    chupa.hp = 6
    ai_ = MedusaAI(0)
    model = Model(g, 0)
    beast = give(g, 0, ai.WOUNDED)
    healthy_beast = ai_.eval_defense(g, model, [(1.0, 5)], chupa, beast)
    chupa.hp = 12
    assert healthy_beast > ai_.eval_defense(g, model, [(1.0, 5)], chupa, beast)


# ---------------------------------------------------------------- the search plays him

@pytest.mark.parametrize("foe", ["hellboy", "bigfoot", "medusa"])
def test_the_search_bot_plays_chupacabra_to_the_end_without_falling_back(foe):
    from sparring import sim
    ai_ = sim.make_bot("ismcts", iterations=20, seed=1)
    out = sim.play(1, bot_hero="chupacabra", human_hero=foe, medusa=ai_, max_turns=40)
    assert out.turns >= 1 and ai_.fallbacks == 0 and out.winner != "draw"
