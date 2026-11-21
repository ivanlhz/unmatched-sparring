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


def mk(bprd, foe="golden-bat", seed=3, turn=0):
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


def duel(g, foe_fid="bat"):
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
    assert attack(g, m, h, "Speak Three Times", "Terrifying Roar").atk_value == 3
    assert attack(g, m, h, "Speak Three Times", "Terrifying Roar", 1).atk_value == 3
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
    give(g, 1, "Terrifying Roar")
    card = give(g, 0, "Out Of The Mirror")
    hand = len(g.players[0].hand)
    g.attack(m, h, card, None)
    assert len(g.players[0].hand) == hand - 1                              # the first action: the card played, nothing drawn
    g2 = mk(bprd)
    m2, h2 = duel(g2)
    g2.actions_left = 3
    spend_two_actions_first(g2, m2, h2)
    give(g2, 1, "Terrifying Roar")
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
    m, h = pair(g, "mary", "bat")
    start_turn(g)
    assert g.fx.taken == 0
    from sparring.effects.select import amount
    from sparring.effects.run import Ctx, EffectRun
    run = EffectRun([], Ctx(owner=0, this_fid="mary"))
    assert amount(g, run, {"stat": "actions_taken_this_turn", "player": "owner"}) == 0


# ---------------------------------------------------------------- Mirror Image

def test_mirror_image_is_worth_the_printed_value_of_the_rivals_card_not_the_bonus_added_to_it(bprd):
    g = mk(bprd, turn=1)
    m, b = pair(g, "mary", "bat")
    start_turn(g)
    res = g.attack(b, m, give(g, 1, "Super Strength"), give(g, 0, "Mirror Image"))
    assert res.def_value == 5 and res.atk_value == 5 + 2          # the +2 of THE FIRST SUPERHERO is not printed on the card
    assert m.hp == 16 - 2                                          # 7 against the 5 she copies: the bonus is the 2 she takes


def test_mirror_image_against_a_card_with_a_printed_value_of_two_is_two(bprd):
    g = mk(bprd, turn=1)
    m, b = pair(g, "mary", "bat")
    start_turn(g)
    res = g.attack(b, m, give(g, 1, "Vaporizing Eyebeams"), give(g, 0, "Mirror Image"))
    assert res.def_value == 2


# ---------------------------------------------------------------- Broken Glass

@pytest.mark.parametrize("answer,value", [(0, 4), (1, 2), (2, 3)])
def test_broken_glass_may_add_one_take_one_or_change_nothing(bprd, answer, value):
    g = mk(bprd)
    m, b = duel(g)
    g.controllers[0].queue = [[answer]]
    assert attack(g, m, b, "Broken Glass").atk_value == value


def test_broken_glass_matching_the_rivals_value_draws_a_card_and_deals_two(bprd):
    g = mk(bprd)
    m, b = duel(g)
    g.controllers[0].queue = [[2]]                                   # 3 against Terrifying Roar's 3
    hand, hp = len(g.players[0].hand), b.hp
    res = attack(g, m, b, "Broken Glass", "Terrifying Roar")
    assert (res.atk_value, res.def_value) == (3, 3)
    assert b.hp == hp - 2 and len(g.players[0].hand) == hand + 1       # the card played left an empty hand, the drawn one is in it


def test_broken_glass_changed_to_match_by_the_during_choice(bprd):
    g = mk(bprd)
    m, b = duel(g)
    g.controllers[0].queue = [[0]]                                   # 3 + 1 = 4 against Skirmish's 4
    hp = b.hp
    res = attack(g, m, b, "Broken Glass", "Skirmish")
    assert (res.atk_value, res.def_value) == (4, 4) and b.hp == hp - 2


def test_broken_glass_that_does_not_match_does_nothing_extra(bprd):
    g = mk(bprd)
    m, b = duel(g)
    g.controllers[0].queue = [[2]]
    hp, hand = b.hp, len(g.players[0].hand)
    res = attack(g, m, b, "Broken Glass", "Skirmish")                # 3 against 4
    assert res.atk_value == 3 and b.hp == hp and len(g.players[0].hand) == hand


# ---------------------------------------------------------------- Out Of The Mirror

def test_out_of_the_mirror_adds_the_boost_of_the_card_the_rival_discards_at_random(bprd):
    g = mk(bprd)
    m, b = duel(g)
    theirs = give(g, 1, "Alpine Fortress")                           # the only card they hold: BOOST 3
    res = attack(g, m, b, "Out Of The Mirror")
    assert res.atk_value == 1 + 3 and theirs in g.players[1].discard and not g.players[1].hand


def test_out_of_the_mirror_with_an_empty_rival_hand_adds_nothing(bprd):
    g = mk(bprd)
    m, b = duel(g)
    assert attack(g, m, b, "Out Of The Mirror").atk_value == 1


def test_out_of_the_mirror_discards_exactly_one_of_several(bprd):
    g = mk(bprd)
    m, b = duel(g)
    give(g, 1, "Alpine Fortress")
    give(g, 1, "Super Strength")
    res = attack(g, m, b, "Out Of The Mirror")
    assert len(g.players[1].hand) == 1 and len(g.players[1].discard) == 1
    assert res.atk_value == 1 + g.players[1].discard[0].boost


# ---------------------------------------------------------------- Stolen Memories

def test_stolen_memories_discards_the_card_when_the_rival_agrees(bprd):
    g = mk(bprd)
    m, b = duel(g)
    theirs = give(g, 1, "Alpine Fortress")
    g.controllers[1].queue = [[True]]
    g.play_scheme(0, m, give(g, 0, "Stolen Memories"))
    assert theirs in g.players[1].discard and b.hp == b.max_hp


def test_stolen_memories_hurts_their_hero_by_the_boost_value_when_the_rival_refuses(bprd):
    g = mk(bprd)
    m, b = duel(g)
    theirs = give(g, 1, "Alpine Fortress")                           # BOOST 3
    g.controllers[1].queue = [[False]]
    g.play_scheme(0, m, give(g, 0, "Stolen Memories"))
    assert theirs in g.players[1].hand and b.hp == b.max_hp - 3


def test_stolen_memories_asks_nothing_of_an_empty_hand(bprd):
    g = mk(bprd)
    m, b = duel(g)
    g.controllers[1].queue = [[False]]
    g.play_scheme(0, m, give(g, 0, "Stolen Memories"))
    assert b.hp == b.max_hp and g.controllers[1].queue == [[False]]


# ---------------------------------------------------------------- Jump Scare

def far_pair(g, m, b):
    """Mary where she shares no zone with the space she started the turn on, the foe next to her."""
    start = m.pos

    def free(s):
        return all(f.pos != s for f in g.fighters.values() if f.alive)
    for s in sorted(g.board.spaces):
        if free(s) and not g.board.share_zone(start, s):
            near = [t for t in sorted(g.board.adj[s]) if free(t) and t != start]
            if near:
                m.pos, b.pos = s, near[0]
                return
    raise AssertionError("no such spaces on the board")


def test_jump_scare_is_6_when_she_shares_no_zone_with_where_she_started_the_turn(bprd):
    g = mk(bprd)
    m, b = duel(g)
    far_pair(g, m, b)
    assert attack(g, m, b, "Jump Scare").atk_value == 6


def test_jump_scare_is_3_when_she_did_not_move(bprd):
    g = mk(bprd)
    m, b = duel(g)
    assert attack(g, m, b, "Jump Scare").atk_value == 3


def test_jump_scare_as_a_defense_is_3_when_she_did_not_move(bprd):
    g = mk(bprd, turn=1)
    m, b = pair(g, "mary", "bat")
    start_turn(g)
    res = g.attack(b, m, give(g, 1, "Super Strength"), give(g, 0, "Jump Scare"))
    assert res.def_value == 3


# ---------------------------------------------------------------- movement and the rest

def test_closer_than_she_appears_moves_up_to_one_space_draws_one_and_gains_an_action(bprd):
    g = mk(bprd)
    m, b = duel(g)
    dest = next(s for s in sorted(g.board.adj[m.pos]) if s != b.pos)
    g.controllers[0].moves = {"mary": dest}
    hand = len(g.players[0].hand)
    g.play_scheme(0, m, give(g, 0, "Closer Than She Appears"))
    assert m.pos == dest and len(g.players[0].hand) == hand + 1 and g.actions_left == 2


def test_evade_draws_a_card_after_combat(bprd):
    g = mk(bprd, turn=1)
    m, b = pair(g, "mary", "bat")
    start_turn(g)
    res = g.attack(b, m, give(g, 1, "Super Strength"), give(g, 0, "Evade"))
    assert res.def_value == 3 and len(g.players[0].hand) == 1


def test_trick_of_the_light_places_her_next_to_the_rival_when_she_says_so(bprd):
    g = mk(bprd)
    m, b = duel(g)
    spots = [s for s in sorted(g.board.adj[b.pos]) if s != m.pos and all(f.pos != s for f in g.fighters.values() if f.alive)]
    assert spots
    g.controllers[0].queue = [[True], [spots[0]]]
    attack(g, m, b, "Trick of the Light")
    assert m.pos == spots[0] and g.board.adjacent(m.pos, b.pos)


def test_trick_of_the_light_declined_leaves_her_where_she_is(bprd):
    g = mk(bprd)
    m, b = duel(g)
    here = m.pos
    g.controllers[0].queue = [[False]]
    attack(g, m, b, "Trick of the Light")
    assert m.pos == here


def test_infinity_mirror_moves_one_fighter_of_the_combat_up_to_four_spaces(bprd):
    g = mk(bprd)
    m, b = duel(g)
    far = max((s for s in g.board.spaces if 0 < g.board.distance(b.pos, s) <= 4 and all(f.pos != s for f in g.fighters.values() if f.alive)),
              key=lambda s: g.board.distance(b.pos, s))
    g.controllers[0].queue = [["bat"], [far]]
    attack(g, m, b, "Infinity Mirror")
    assert b.pos == far and g.board.distance(b.pos, g.fighters["mary"].pos) > 1


def test_infinity_mirror_may_move_bloody_mary_herself(bprd):
    g = mk(bprd)
    m, b = duel(g)
    far = max((s for s in g.board.spaces if 0 < g.board.distance(m.pos, s) <= 4 and all(f.pos != s for f in g.fighters.values() if f.alive)),
              key=lambda s: g.board.distance(m.pos, s))
    g.controllers[0].queue = [["mary"], [far]]
    attack(g, m, b, "Infinity Mirror")
    assert m.pos == far


def test_ghostly_touch_may_be_boosted_for_free_and_a_boost_adds_its_value(bprd):
    g = mk(bprd)
    m, b = duel(g)
    booster = give(g, 0, "Trick of the Light")                           # BOOST 3
    g.controllers[0].boost = booster
    res = attack(g, m, b, "Ghostly Touch")
    assert res.atk_value == 1 + 3 and booster in g.players[0].discard


def test_feint_cancels_the_effects_of_the_rivals_card(bprd):
    g = mk(bprd, turn=1)
    m, b = pair(g, "mary", "bat")
    start_turn(g)
    give(g, 0, "Evade")
    before = len(g.players[0].hand)
    res = g.attack(b, m, give(g, 1, "Vaporizing Eyebeams"), give(g, 0, "Feint"))
    assert res.def_value == 2 and len(g.players[0].hand) == before


# ---------------------------------------------------------------- Bloody Requiem (a DOUBLE ATTACK)

def test_bloody_requiem_second_attack_is_worth_the_printed_value_of_the_card_played_against_it(bprd):
    g = mk(bprd)
    m, b = duel(g)
    hp = b.hp
    res = attack(g, m, b, "Bloody Requiem", "He Laughs at Your Feebleness")       # 3 against 5: the first part does nothing
    assert res.damage == 0 and res.second is not None
    assert res.second.atk_value == 5 and res.second.damage == 5 and b.hp == hp - 5


def test_bloody_requiem_against_no_card_has_a_second_attack_of_zero(bprd):
    g = mk(bprd)
    m, b = duel(g)
    hp = b.hp
    res = attack(g, m, b, "Bloody Requiem")
    assert res.damage == 3 and (res.second is None or res.second.damage == 0) and b.hp == hp - 3


def test_bloody_requiem_second_attack_may_be_defended_with_a_new_card(bprd):
    g = mk(bprd)
    m, b = duel(g)
    wall = give(g, 1, "Imposing Presence")                                            # defense 3 against the second attack of 3: it ties, the defender wins
    g.controllers[1].choose_second_defense = lambda game, att, tgt, value, card: wall
    res = attack(g, m, b, "Bloody Requiem", "Terrifying Roar")
    assert res.second.atk_value == 3 and res.second.def_card is wall and res.second.damage == 0


def test_feint_against_bloody_requiem_stops_the_second_attack(bprd):
    g = mk(bprd)
    m, b = duel(g)
    hp = b.hp
    res = attack(g, m, b, "Bloody Requiem", "Imposing Presence")                       # Golden Bat's Feint: cancels all effects of the card
    assert res.second is None and b.hp == hp
