"""What the AIs do with Loki's TRICKs moving between hands: the search never invents or loses one (determinization), the heuristic prices
his cards. The rules are in tests/test_loki_effects.py; the design in docs/heroes/loki.md."""
from __future__ import annotations

import random

import pytest

from conftest import give
from sparring import tricks
from sparring.search.adapter import EngineState, Knowledge
from test_loki_effects import BALDR, FREYJA, LURE, SINDRI, lend, mk

import sparring.effects.plugins_loki  # noqa: F401


def sampled(g, observer, seed=1):
    st = EngineState(g, observer, Knowledge.from_game(g, observer))
    st.determinize(observer, random.Random(seed))
    return st.game


@pytest.mark.parametrize("seed", range(12))
def test_the_known_trick_stays_in_the_rivals_hand_when_the_bot_is_loki(bprd, seed):
    g = mk(bprd)
    trick = lend(g, 1, BALDR)
    for _ in range(4):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    world = sampled(g, 0, seed)
    hand = world.players[1].hand
    assert trick in hand and len(hand) == 5
    assert sum(1 for c in hand if tricks.is_trick(c)) == 1                         # no other TRICK is dealt to them: they are Loki's, not theirs
    assert len(set(hand)) == 5


@pytest.mark.parametrize("seed", range(12))
def test_a_trick_in_the_bots_hand_is_not_also_in_lokis_sampled_hand(bprd, seed):
    g = mk(bprd, turn=1)                                                            # the bot is Medusa (player 1); Loki, player 0, is the human
    g.bot_player = 1
    trick = lend(g, 1, FREYJA)
    for _ in range(5):
        g.players[0].hand.append(g.players[0].deck.pop(0))
    world = sampled(g, 1, seed)
    assert trick in world.players[1].hand and trick not in world.players[0].hand and trick not in world.players[0].deck
    assert len(world.players[0].hand) == 5


def test_a_world_that_lost_the_known_trick_would_fail_this_test(bprd):
    """Mutation guard: without `foreign` in Knowledge the sampler cannot place the TRICK (the rival's own pool does not hold it)."""
    g = mk(bprd)
    trick = lend(g, 1, SINDRI)
    g.players[1].hand.append(g.players[1].deck.pop(0))
    st = EngineState(g, 0, Knowledge())
    st.determinize(0, random.Random(1))
    assert trick not in st.game.players[1].hand


# ---------------------------------------------------------------- the heuristic's figures (sparring/ai_loki.py)

from sparring import ai_loki
from test_effects_combat import hand_filler


def test_ragnarok_is_worth_three_per_trick_the_engine_tracks_in_their_hand(bprd):
    g = mk(bprd)
    card = give(g, 0, "Ragnarök")
    assert ai_loki.attack_value(g, 0, card) == 0.0
    lend(g, 1, BALDR)
    lend(g, 1, SINDRI)
    assert ai_loki.attack_value(g, 0, card) == 6.0 and ai_loki.attack_value(g, 1, card) is None


def test_shapeshifter_underhanded_and_laevateinn_are_priced_from_the_hands(bprd):
    g = mk(bprd)
    hand_filler(g, 1, 3)
    assert ai_loki.attack_value(g, 0, give(g, 0, "Shapeshifter")) == 3.0
    assert ai_loki.attack_value(g, 0, give(g, 0, "Underhanded")) == 6.0                  # 3 cards against their 1 after playing it
    hand_filler(g, 0, 4)
    assert ai_loki.attack_value(g, 0, g.players[0].hand[1]) is None                   # 5 cards (4 after playing it) against 3: not more
    mean = ai_loki.attack_value(g, 0, give(g, 0, "Laevateinn"))
    assert 2.0 < mean < 5.0


def test_a_trick_costs_the_player_who_is_not_loki_what_its_not_loki_part_does(bprd):
    g = mk(bprd, turn=1)
    weights = dict(p_win=0.5, foe_hp_weight=1.0, card_value=1.0, hero_hp_weight=1.0)
    baldr, freyja, sindri = lend(g, 1, BALDR), lend(g, 1, FREYJA), lend(g, 1, SINDRI)
    g.fighters["loki"].hp = 10
    g.players[0].discard.append(g.players[0].deck.pop(0))
    assert ai_loki.after_value(g, 1, baldr, **weights) == -2.0
    assert ai_loki.after_value(g, 1, freyja, **weights) == -3.0
    assert ai_loki.after_value(g, 1, sindri, **weights) == -1.0
    mine = give(g, 0, BALDR)
    assert ai_loki.after_value(g, 0, mine, **weights) == 1.0                              # Loki's own Baldr's Downfall draws
