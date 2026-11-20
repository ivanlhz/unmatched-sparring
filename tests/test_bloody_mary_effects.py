"""Bloody Mary on the engine, bot side (player 0 plays Bloody Mary, the controllers answer): THE ability (exactly 3 cards in hand at the
start of the turn gives a third action), the "third action this turn" cards, Mirror Image, Broken Glass, Out Of The Mirror, Stolen
Memories, Jump Scare, the movement cards, Feint, Evade and Ghostly Touch, with the numbers printed on the cards.

"Third action" is `actions_taken_this_turn == 3`: every action SPENT this turn counts (the card's own action included), however it was
gained. The human side (panel, FakeTTS) is tests/test_bloody_mary_human.py; the full games are tests/test_bloody_mary_matrix.py."""
from __future__ import annotations

import pytest

import sparring.effects.plugins_mary  # noqa: F401  (registers mary:out_of_the_mirror)

from conftest import give
from sparring.effects.events import tracked
from sparring.state import Game
from test_bigfoot_effects import Answers, start_turn
from test_effects_combat import pair


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Bloody Mary = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("bloody-mary", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def fresh_turn(g, cards: int):
    """The owner's turn starts again with exactly that many cards in hand: the ability fires (or not) as it would live."""
    st = g.players[g.turn]
    st.hand.clear()
    st.hand.extend(st.deck[:cards])
    del st.deck[:cards]
    g.begin_turn()


def duel(g, foe_fid="hellboy"):
    m, h = pair(g, "mary", foe_fid)
    start_turn(g)
    return m, h


def attack(g, m, h, atk_title, def_title=None, nth=0):
    return g.attack(m, h, give(g, 0, atk_title, nth), give(g, 1, def_title) if def_title else None)


def spend_two_actions_first(g, m, h, n=2):
    """Takes `n` plain actions (Maneuvers that move nobody) so the next action is number n+1."""
    for _ in range(n):
        g.maneuver(0, {})


# ---------------------------------------------------------------- the hero card

def test_bloody_mary_is_a_melee_hero_with_16_life_move_3_and_no_sidekick(bprd):
    g = mk(bprd)
    m = g.fighters["mary"]
    assert (m.hp, m.move, m.ranged, m.reach) == (16, 3, False, 0)
    assert [f.fid for f in g.own(0)] == ["mary"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "taken" in tracked(frozenset(g.fx.dsl_heroes))              # the action tally is recorded for her


# ---------------------------------------------------------------- the ability

@pytest.mark.parametrize("cards,actions", [(0, 2), (1, 2), (2, 2), (3, 3), (4, 2), (5, 2), (7, 2)])
def test_exactly_three_cards_in_hand_at_the_start_of_the_turn_give_a_third_action(bprd, cards, actions):
    g = mk(bprd)
    fresh_turn(g, cards)
    assert g.actions_left == actions


def test_the_ability_reads_the_hand_when_the_turn_starts_not_later(bprd):
    g = mk(bprd)
    fresh_turn(g, 3)
    assert g.actions_left == 3
    give(g, 0, "Feint")                                   # a fourth card after the start: nothing is taken away
    assert g.actions_left == 3


def test_the_ability_is_for_the_owners_own_turn_only(bprd):
    g = mk(bprd, turn=1)
    g.players[0].hand.clear()
    for i in range(3):
        give(g, 0, "Evade", i)
    g.begin_turn()                                        # the RIVAL's turn starts: Mary's hand of 3 changes nothing
    assert g.actions_left == 2


def test_the_ability_respects_a_rule_that_forbids_gaining_actions(bprd):
    from sparring.effects import modifiers
    g = mk(bprd)
    modifiers.add_status(g.fx, "cannot_gain_actions", owner=1, until={"event": "end_of_turn"}, player=0)
    fresh_turn(g, 3)
    assert g.actions_left == 2


# ---------------------------------------------------------------- the third action

def test_speak_three_times_is_3_as_the_first_and_second_action_and_7_as_the_third(bprd):
    g = mk(bprd)
    m, h = duel(g)
    g.actions_left = 3
    assert attack(g, m, h, "Speak Three Times", "B.P.R.D. Training").atk_value == 3
    assert attack(g, m, h, "Speak Three Times", "B.P.R.D. Training", 1).atk_value == 3
    g2 = mk(bprd)
    m2, h2 = duel(g2)
    g2.actions_left = 3
    spend_two_actions_first(g2, m2, h2)
    assert attack(g2, m2, h2, "Speak Three Times").atk_value == 7


def test_the_third_action_counts_every_kind_of_action_and_the_gained_ones(bprd):
    g = mk(bprd)
    m, h = duel(g)
    assert g.actions_left == 2
    g.play_scheme(0, m, give(g, 0, "Closer Than She Appears"))        # spends 1, gives 1 back
    assert g.fx.taken == 1 and g.actions_left == 2
    g.maneuver(0, {})                                                    # the second action
    assert g.fx.taken == 2 and g.actions_left == 1
    assert attack(g, m, h, "Speak Three Times").atk_value == 7           # the third: only possible through the gained action
    assert g.fx.taken == 3 and g.actions_left == 0


def test_a_fourth_action_is_not_a_third(bprd):
    g = mk(bprd)
    m, h = duel(g)
    g.actions_left = 4
    spend_two_actions_first(g, m, h, 3)
    assert attack(g, m, h, "Speak Three Times").atk_value == 3


def test_the_action_tally_starts_again_every_turn(bprd):
    g = mk(bprd)
    m, h = duel(g)
    g.actions_left = 3
    spend_two_actions_first(g, m, h)
    assert g.fx.taken == 2
    g.turn, g.turn_no = 0, g.turn_no + 2
    g.begin_turn()
    assert g.fx.taken == 0


def test_out_of_the_mirror_draws_a_card_only_as_the_third_action(bprd):
    g = mk(bprd)
    m, h = duel(g)
    g.actions_left = 3
    give(g, 1, "B.P.R.D. Training")
    card = give(g, 0, "Out Of The Mirror")
    hand = len(g.players[0].hand)
    g.attack(m, h, card, None)
    assert len(g.players[0].hand) == hand - 1                              # the first action: the card played, nothing drawn
    g2 = mk(bprd)
    m2, h2 = duel(g2)
    g2.actions_left = 3
    spend_two_actions_first(g2, m2, h2)
    give(g2, 1, "B.P.R.D. Training")
    card2 = give(g2, 0, "Out Of The Mirror")
    hand2 = len(g2.players[0].hand)
    g2.attack(m2, h2, card2, None)
    assert len(g2.players[0].hand) == hand2 - 1 + 1                        # the third action: the card played, one drawn


def test_ghostly_touch_recovers_3_as_the_third_action_and_never_above_the_maximum(bprd):
    g = mk(bprd)
    m, h = duel(g)
    g.actions_left = 3
    m.hp = 10
    attack(g, m, h, "Ghostly Touch")
    assert m.hp == 10                                                      # the first action
    g2 = mk(bprd)
    m2, h2 = duel(g2)
    g2.actions_left = 3
    spend_two_actions_first(g2, m2, h2)
    m2.hp = 10
    attack(g2, m2, h2, "Ghostly Touch")
    assert m2.hp == 13
    g3 = mk(bprd)
    m3, h3 = duel(g3)
    g3.actions_left = 3
    spend_two_actions_first(g3, m3, h3)
    m3.hp = 15
    attack(g3, m3, h3, "Ghostly Touch")
    assert m3.hp == 16


def test_the_third_action_cards_do_nothing_extra_on_the_rivals_turn_or_as_a_first_action(bprd):
    g = mk(bprd, turn=1)
    m, h = pair(g, "mary", "hellboy")
    start_turn(g)
    assert g.fx.taken == 0
    from sparring.effects.select import amount
    from sparring.effects.run import Ctx, EffectRun
    run = EffectRun([], Ctx(owner=0, this_fid="mary"))
    assert amount(g, run, {"stat": "actions_taken_this_turn", "player": "owner"}) == 0
