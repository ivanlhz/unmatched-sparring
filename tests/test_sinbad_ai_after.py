"""F-SINBAD-AI-AFTER: the heuristic AI prices the AFTER of Sinbad's cards (draws, VOYAGE effects), so an attack that refills the hand
is not outbid by a maneuver at a full hand (live: Sinbad kept maneuvering with 7 cards and barely attacked with his versatile cards)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_sinbad
from sparring.ai_medusa import CARD_VALUE, W_MEDUSA_HP, MedusaAI, Model, hand_room
from test_effects_combat import hand_filler, put_adjacent
from test_sinbad_effects import VOYAGES, mk, to_discard

NO_EFFECT = "Momentous Shift"      # a versatile card (3) with nothing in its AFTER: the control of every comparison


def table(bprd, hand, foe="hellboy", actions=1, discard=()):
    g = mk(bprd, foe)
    g.controllers = {0: MedusaAI(0), 1: g.controllers[1]}
    for title in hand:
        give(g, 0, title, sum(1 for c in g.players[0].hand if c.title == title))
    to_discard(g, 0, *discard)
    g.actions_left = actions
    put_adjacent(g, "sinbad", g.hero(1).fid)
    return g


def value(g, title):
    ai, hero, foe = g.controllers[0], g.hero(0), g.hero(1)
    card = next(c for c in g.players[0].hand if c.title == title)
    return ai.attack_outcome(g, Model(g, 0), hero, foe, card)[0]


RIVALS = ("hellboy", "bigfoot")
HAND = ("Exploit", "Feint", "Feint", "Regroup", "Leap Away", "Toil and Danger", "Voyage Home")


@pytest.mark.parametrize("foe", RIVALS)
def test_the_attack_that_draws_is_played_while_the_hand_has_room(bprd, foe):
    """Seven cards: the six left take the card Exploit draws, and it beats the Leap Away (worth 4 on a win, nothing more)."""
    g = table(bprd, HAND, foe=foe)
    assert len(g.players[0].hand) == 7
    act = g.controllers[0].plan(g)
    assert (act.kind, act.card.title) == ("attack", "Exploit")


@pytest.mark.parametrize("room, cards", [(None, 2), (5, 2), (2, 2), (1, 1), (0, 0), (-1, 0)])
def test_by_fortune_and_fate_draws_only_what_fits(bprd, room, cards):
    g = table(bprd, ("By Fortune and Fate",))
    c = g.players[0].hand[0]
    assert ai_sinbad.after_value(g, 0, c, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP, room) == pytest.approx(CARD_VALUE * cards)


def test_a_card_that_draws_is_worth_nothing_extra_from_a_full_hand(bprd):
    """Seven cards with the Exploit among them: the six left take one more. Eight cards: the seven left are full."""
    seven = table(bprd, ("Exploit",))
    hand_filler(seven, 0, 6 - (len(seven.players[0].hand) - 1), avoid=("Exploit",))
    assert len(seven.players[0].hand) == 7 and hand_room(seven, 0) == 7
    eight = table(bprd, ("Exploit",))
    hand_filler(eight, 0, 7 - (len(eight.players[0].hand) - 1), avoid=("Exploit",))
    assert len(eight.players[0].hand) == 8
    assert value(seven, "Exploit") - value(eight, "Exploit") == pytest.approx(CARD_VALUE)


def test_voyage_home_values_the_cards_it_takes_back(bprd):
    bare = table(bprd, ("Voyage Home",))
    full = table(bprd, ("Voyage Home",), discard=VOYAGES[1:4])
    c = bare.players[0].hand[0]
    nothing = ai_sinbad.after_value(bare, 0, c, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP, 5)
    three = ai_sinbad.after_value(full, 0, c, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP, 5)
    capped = ai_sinbad.after_value(full, 0, c, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP, 1)
    assert nothing == 0.0 and three == pytest.approx(3 * CARD_VALUE * ai_sinbad.VOYAGE_BACK)
    assert capped == pytest.approx(CARD_VALUE * ai_sinbad.VOYAGE_BACK)


def test_the_whale_heals_only_what_is_missing_and_the_apes_hit_for_two(bprd):
    g = table(bprd, (VOYAGES[2], VOYAGES[4]))
    whale, apes = g.players[0].hand
    unhurt = ai_sinbad.after_value(g, 0, whale, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP)
    g.hero(0).hp -= 1
    hurt1 = ai_sinbad.after_value(g, 0, whale, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP)
    g.hero(0).hp -= 5
    hurt6 = ai_sinbad.after_value(g, 0, whale, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP)
    assert (unhurt, hurt1, hurt6) == (0.0, pytest.approx(W_MEDUSA_HP), pytest.approx(2 * W_MEDUSA_HP))
    assert ai_sinbad.after_value(g, 0, apes, 0.5, 0.8, CARD_VALUE, W_MEDUSA_HP, foe_hp=15) == pytest.approx(1.6)
    assert ai_sinbad.after_value(g, 0, apes, 0.5, 0.8, CARD_VALUE, W_MEDUSA_HP, foe_hp=1) == pytest.approx(0.8)


def test_a_card_of_another_hero_or_without_an_after_is_worth_nothing_here(bprd):
    g = table(bprd, (NO_EFFECT, "Feint"))
    for c in g.players[0].hand:
        assert ai_sinbad.after_value(g, 0, c, 0.5, 1.0, CARD_VALUE, W_MEDUSA_HP, 5) == 0.0
