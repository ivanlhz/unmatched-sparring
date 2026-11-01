"""Michelangelo on the interpreter, bot side and engine rules: every card effect, PIZZA PARTY (the draw after an
attack or a scheme) and the hand size of 3 (opening hand and end-of-turn limit). The human's side runs through
FakeTTS in tests/test_michelangelo_session.py.

Player 0 plays Michelangelo (the bot), player 1 Hellboy; hands are set by hand."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring import persist
from sparring.ai_effects import EffectAI
from sparring.state import Game
from test_d1_bot_cards import mk, to_discard
from test_effects_combat import hand_filler, hp, pair, put_adjacent


@pytest.fixture
def g(bprd):
    return mk(bprd, "michelangelo", "hellboy")


def titles(cards):
    return [c.title for c in cards]


def attack(g, att, tgt, title, def_title=None, **kw):
    a, t = g.fighters[att], g.fighters[tgt]
    return g.attack(a, t, give(g, a.owner, title), give(g, t.owner, def_title) if def_title else None, **kw)


def answers(g, *queue, player=0):
    g.controllers[player].queue[:] = list(queue)
    return g.controllers[player]


# ---------------------------------------------------------------- hand size 3 (PIZZA PARTY, second sentence)

def test_the_opening_hand_is_3_for_michelangelo_and_5_for_the_others(bprd):
    fresh = Game.new(bprd, 3, controllers={}, heroes=("michelangelo", "hellboy"), bot_player=0)
    assert [len(p.hand) for p in fresh.players] == [3, 5]
    assert [fresh.start_hand(p) for p in (0, 1)] == [3, 5] and [fresh.hand_cap(p) for p in (0, 1)] == [3, 7]
    other = Game.new(bprd, 3, controllers={}, heroes=("hellboy", "michelangelo"), bot_player=0)
    assert [len(p.hand) for p in other.players] == [5, 3]


def test_end_of_turn_discards_down_to_3_for_michelangelo_but_not_for_a_rival_with_7(g):
    for player in (0, 1):
        hand_filler(g, player, 6)
    assert len(g.players[0].hand) == 6
    g.end_turn()
    assert len(g.players[0].hand) == 3
    g.begin_turn()
    g.end_turn()
    assert len(g.players[1].hand) == 6            # Hellboy keeps up to 7


def test_the_hand_cap_comes_back_to_the_default_for_every_other_hero(bprd):
    for slug in ("medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"):
        gm = Game.new(bprd, 3, controllers={}, heroes=(slug, "michelangelo"), bot_player=0)
        assert (gm.start_hand(0), gm.hand_cap(0)) == (5, 7)


# ---------------------------------------------------------------- PIZZA PARTY: draw after attacking or scheming

def test_pizza_party_draws_one_card_after_an_attack_defended_or_not(g):
    pair(g, "mikey", "hellboy")
    n0 = g.draw_events[0]
    attack(g, "mikey", "hellboy", "Turtle Power!!")
    assert g.draw_events[0] - n0 == 1
    d0 = g.draw_events[1]
    attack(g, "mikey", "hellboy", "Turtle Power!!", "Planned Recklessness")      # defended
    assert g.draw_events[0] - n0 == 2
    assert g.draw_events[1] == d0                        # the defender draws nothing


def test_pizza_party_counts_exactly_one_draw_per_attack(g):
    pair(g, "mikey", "hellboy")
    card = give(g, 0, "Turtle Power!!")
    n0 = g.draw_events[0]
    g.attack(g.fighters["mikey"], g.fighters["hellboy"], card, None)
    assert g.draw_events[0] - n0 == 1
    assert len(g.players[0].hand) == 1


def test_pizza_party_fires_for_a_sidekick_attack_but_not_when_michelangelo_defends(g):
    a, t = pair(g, "april", "hellboy")
    card = give(g, 0, "Hard-Hitting Investigation")
    n0 = g.draw_events[0]
    g.attack(a, t, card, None)
    assert g.draw_events[0] - n0 == 1
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    n0 = g.draw_events[0]
    g.attack(g.fighters["hellboy"], g.fighters["mikey"], give(g, 1, "Service Pistol"), give(g, 0, "Heroes In A Half Shell"))
    assert g.draw_events[0] == n0


def test_pizza_party_draws_one_card_after_a_scheme(g):
    card = give(g, 0, "Michelangelo Is A Party Dude!!")
    n0 = g.draw_events[0]
    g.play_scheme(0, g.hero(0), card)
    assert g.draw_events[0] - n0 == 1
    assert g.players[0].discard[-1] is card


def test_pizza_party_does_not_draw_after_the_rivals_attack_or_a_maneuver(g):
    n0 = g.draw_events[0]
    g.maneuver(0, {})                                    # the Maneuver's own draw, nothing else
    assert g.draw_events[0] - n0 == 1


def test_the_draw_after_the_attack_comes_after_the_cards_are_in_the_discard_pile(g):
    pair(g, "mikey", "hellboy")
    card = give(g, 0, "Turtle Power!!")
    g.attack(g.fighters["mikey"], g.fighters["hellboy"], card, None)
    assert card in g.players[0].discard and card not in g.players[0].hand


# ---------------------------------------------------------------- the twelve cards

def test_hi_yaaaaah_hits_an_adjacent_rival_and_pays_a_card_for_an_action(g):
    a, t = pair(g, "mikey", "hellboy")
    card = give(g, 0, "Hi-Yaaaaah!!")
    junk, keep = hand_filler(g, 0, 2, avoid=("Hi-Yaaaaah!!",))
    answers(g, [True], [junk.card_id])
    g.attack(a, t, card, None)
    assert t.hp == 18 - 4 - 1
    assert g.players[0].deck[-1] is junk and junk not in g.players[0].hand
    assert g.actions_left == 2                           # the attack cost 1, the card gave 1
    assert keep in g.players[0].hand


def test_hi_yaaaaah_declined_keeps_the_card_and_the_action_is_not_gained(g):
    a, t = pair(g, "mikey", "hellboy")
    card = give(g, 0, "Hi-Yaaaaah!!")
    junk, = hand_filler(g, 0, 1, avoid=("Hi-Yaaaaah!!",))
    answers(g, [False])
    g.attack(a, t, card, None)
    assert g.actions_left == 1 and junk in g.players[0].hand


def test_hi_yaaaaah_cannot_be_paid_with_an_empty_hand_and_still_hits(g):
    a, t = pair(g, "mikey", "hellboy")
    card = give(g, 0, "Hi-Yaaaaah!!")
    ctl = answers(g, [True])
    g.hero(0)
    n_hand = len(g.players[0].hand)
    g.draw = lambda *args, **kw: []                      # no Pizza Party draw: the hand is really empty at the AFTER
    g.attack(a, t, card, None)
    assert n_hand == 1 and t.hp == 18 - 4 - 1 and g.actions_left == 1
    assert not [r for r in ctl.requests if r.kind == "optional"]


def test_hi_yaaaaah_damage_reaches_a_sidekick_next_to_the_attacker_not_only_the_defender(g):
    a, t = pair(g, "mikey", "hellboy")
    put_adjacent(g, "lobster", "mikey")
    card = give(g, 0, "Hi-Yaaaaah!!")
    answers(g, ["lobster"], [False])
    g.attack(a, t, card, None)
    assert hp(g, "lobster") == [5] and t.hp == 18 - 4


def test_boisterous_beatdown_gains_two_actions_when_it_wins_and_one_when_it_does_not(g):
    a, t = pair(g, "mikey", "hellboy")
    attack(g, "mikey", "hellboy", "Boisterous Beatdown")
    assert g.actions_left == 1 + 2
    g.actions_left = 2
    attack(g, "mikey", "hellboy", "Boisterous Beatdown", "Glimpse Of Hell")        # 2 against 2: lost
    assert g.actions_left == 1 + 1


def test_turtle_power_lets_the_owner_boost_its_attack(g):
    from sparring.combat import can_boost
    assert can_boost(give(g, 0, "Turtle Power!!")) and not can_boost(give(g, 0, "Hi-Yaaaaah!!"))


def test_hard_hitting_investigation_hits_the_opposing_fighter_and_gains_an_action(g):
    a, t = pair(g, "april", "hellboy")
    attack(g, "april", "hellboy", "Hard-Hitting Investigation")
    assert t.hp == 18 - 0 - 1 and g.actions_left == 2
    assert not give(g, 0, "Hard-Hitting Investigation").usable_by("Michelangelo")      # April's card only


def test_cowabunga_adds_one_for_each_other_card_played_this_turn(g):
    pair(g, "mikey", "hellboy")
    first = attack(g, "mikey", "hellboy", "Cowabunga!!")
    assert first.atk_value == 3                                      # nothing else played yet
    second = attack(g, "mikey", "hellboy", "Cowabunga!!")
    assert second.atk_value == 3 + 1                                 # the first Cowabunga counts
    g.actions_left = 2
    g.play_scheme(0, g.hero(0), give(g, 0, "Michelangelo Is A Party Dude!!"))
    third = attack(g, "mikey", "hellboy", "Cowabunga!!")
    assert third.atk_value == 3 + 3                                  # two attacks and a scheme


def test_cowabunga_counts_the_defenses_made_on_the_rivals_turn_and_resets_every_turn(g):
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    first = attack(g, "hellboy", "mikey", "Service Pistol", "Heroes In A Half Shell")
    assert first.def_value == 5
    g.actions_left = 2
    second = attack(g, "hellboy", "mikey", "Service Pistol", "Cowabunga!!")
    assert second.def_value == 3 + 1                                 # the first defense counts
    g.end_turn()
    g.begin_turn()
    pair(g, "mikey", "hellboy")
    assert attack(g, "mikey", "hellboy", "Cowabunga!!").atk_value == 3      # a new turn: nothing counted


def test_lets_go_moves_a_friendly_fighter_up_to_3_spaces_after_combat(g):
    a, t = pair(g, "mikey", "hellboy")
    april = g.fighters["april"]
    before = april.pos
    dest = sorted(g.legal_moves(april, 3))[0]
    answers(g, ["april"], [dest])
    attack(g, "mikey", "hellboy", "Let's Go!!")
    assert april.pos == dest != before and g.board.distance(before, dest) <= 3


def test_guaranteed_delivery_cancels_the_rivals_card_effects_for_a_card_and_draws_two_when_empty(g):
    pair(g, "hellboy", "mikey")
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    junk, = hand_filler(g, 0, 1, avoid=("Guaranteed Delivery",))
    answers(g, [True], [junk.card_id])
    res = attack(g, "hellboy", "mikey", "Horseshoes And Hand Grenades", "Guaranteed Delivery")
    assert "atk" in res.cancelled and g.players[0].deck[-1] is junk
    assert len(g.players[0].hand) == 2                               # empty hand at the AFTER: draws 2


def test_guaranteed_delivery_does_not_draw_with_cards_in_hand_and_does_not_cancel_when_declined(g):
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    hand_filler(g, 0, 2, avoid=("Guaranteed Delivery",))
    answers(g, [False])
    res = attack(g, "hellboy", "mikey", "Horseshoes And Hand Grenades", "Guaranteed Delivery")
    assert "atk" not in res.cancelled and len(g.players[0].hand) == 2


def test_heroes_in_a_half_shell_is_a_plain_5(g):
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    res = attack(g, "hellboy", "mikey", "Service Pistol", "Heroes In A Half Shell")
    assert res.def_value == 5 and res.damage == 0


def test_back_for_seconds_shuffles_two_random_discards_into_the_deck(g):
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    to_discard(g, 0, "Heroes In A Half Shell", "Cowabunga!!", "Let's Go!!")
    give(g, 0, "Back For Seconds")
    discard0, deck0 = len(g.players[0].discard), len(g.players[0].deck)
    g.attack(g.fighters["hellboy"], g.fighters["mikey"], give(g, 1, "Service Pistol"), g.players[0].hand[0])
    assert len(g.players[0].deck) == deck0 + 2
    assert len(g.players[0].discard) == discard0 - 2 + 1             # two out, Back For Seconds in after the combat
    assert g.players[0].discard[-1].title == "Back For Seconds"


def test_nunchaku_adds_one_to_every_attack_of_michelangelo_this_turn_and_gains_an_action(g):
    pair(g, "mikey", "hellboy")
    g.play_scheme(0, g.hero(0), give(g, 0, "Nunchaku"))
    assert g.actions_left == 2 - 1 + 1
    g.actions_left = 3
    first = attack(g, "mikey", "hellboy", "Turtle Power!!")
    second = attack(g, "mikey", "hellboy", "Turtle Power!!")
    assert (first.atk_value, second.atk_value) == (4, 4)             # both attacks, not only the first
    g.end_turn()
    assert not g.fx.statuses


def test_nunchaku_stacks_and_does_not_touch_april_or_defenses(g):
    g.play_scheme(0, g.hero(0), give(g, 0, "Nunchaku"))
    g.play_scheme(0, g.hero(0), give(g, 0, "Nunchaku", 1))
    pair(g, "april", "hellboy")
    assert attack(g, "april", "hellboy", "Hard-Hitting Investigation").atk_value == 0
    g.end_turn()
    g.begin_turn()
    pair(g, "hellboy", "mikey")
    assert attack(g, "hellboy", "mikey", "Service Pistol", "Heroes In A Half Shell").def_value == 5
    g.end_turn()
    g.begin_turn()
    pair(g, "mikey", "hellboy")
    assert attack(g, "mikey", "hellboy", "Turtle Power!!").atk_value == 3      # the status ended with the turn


def test_party_dude_heals_each_friendly_fighter_by_one_and_not_the_rival(g):
    for fid, n in (("mikey", 3), ("april", 2), ("hellboy", 5), ("lobster", 4)):
        g.fighters[fid].hp = g.fighters[fid].max_hp - n
    g.play_scheme(0, g.hero(0), give(g, 0, "Michelangelo Is A Party Dude!!"))
    assert hp(g, "mikey", "april", "hellboy", "lobster") == [11 + 1, 4 + 1, 13, 2]


def test_party_dude_does_not_bring_back_a_defeated_april(g):
    f = g.fighters["april"]
    f.alive, f.hp, f.pos, f.died_at = False, 0, None, 4
    g.play_scheme(0, g.hero(0), give(g, 0, "Michelangelo Is A Party Dude!!"))
    assert not f.alive and f.hp == 0


def test_shell_insertion_makes_two_different_choices_and_resolves_them_in_printed_order(g):
    to_discard(g, 0, "Heroes In A Half Shell", "Cowabunga!!")
    give(g, 1, "Excalibur")
    hand_filler(g, 1, 1, avoid=("Excalibur",))
    junk, = hand_filler(g, 0, 1)
    g.controllers[1].discards = []
    answers(g, [2], [0], [junk.card_id])           # chose "put a card" then "opponent discards": printed order is discard first
    card = give(g, 0, "Shell Insertion")
    deck0 = len(g.players[0].deck)
    g.play_scheme(0, g.fighters["april"], card)
    assert len(g.players[1].hand) == 1             # the rival discarded 1 of 2
    assert g.players[0].deck[-1] is junk and g.actions_left == 2 - 1 + 1
    assert len(g.players[0].deck) == deck0 + 1 - 1            # one put at the bottom, one drawn by PIZZA PARTY


def test_shell_insertion_shuffle_and_move_options(g):
    to_discard(g, 0, "Heroes In A Half Shell", "Cowabunga!!")
    april = g.fighters["april"]
    dest = sorted(g.legal_moves(april, 2))[0]
    answers(g, [1], [3], ["april"], [dest])
    card = give(g, 0, "Shell Insertion")
    deck0, disc0 = len(g.players[0].deck), len(g.players[0].discard)
    g.play_scheme(0, april, card)
    assert april.pos == dest
    assert len(g.players[0].deck) == deck0 + 2 - 1 and len(g.players[0].discard) == disc0 - 2 + 1


def test_shell_insertion_offers_four_options_and_asks_twice_without_repeating(g):
    april = g.fighters["april"]
    ctl = answers(g, [0], [1], ["april"], [sorted(g.legal_moves(april, 2))[0]])
    give(g, 1, "Excalibur")
    g.play_scheme(0, g.fighters["april"], give(g, 0, "Shell Insertion"))
    first, second = [r for r in ctl.requests if r.kind == "effect"][:2]
    assert len(first.options) == 4 and first.extra["labels"][0] == "Opponent discards 1 card"
    assert 0 not in second.options and len(second.options) == 3     # distinct: the same effect cannot be chosen twice


# ---------------------------------------------------------------- the bot's decisions and the save

def test_the_bot_pays_a_card_for_an_action_only_while_a_card_that_can_use_it_stays(g):
    ai = EffectAI(0)
    req = type("R", (), {"player": 0, "extra": {"gains_action": True}})()
    give(g, 0, "Hi-Yaaaaah!!")
    assert not ai._card_from_hand_pays(g, req)                       # the only card would be the one given up
    give(g, 0, "Turtle Power!!")
    assert ai._card_from_hand_pays(g, req)
    g.players[0].hand[:] = [give(g, 0, "Heroes In A Half Shell"), give(g, 0, "Back For Seconds")]
    assert not ai._card_from_hand_pays(g, req)                       # two defenses: nothing to spend the action on


def test_the_bot_cancels_only_a_card_that_has_effects(g):
    ai = EffectAI(0)
    give(g, 0, "Back For Seconds")
    assert ai._card_from_hand_pays(g, type("R", (), {"player": 0, "extra": {"cancels": 2}})())
    assert not ai._card_from_hand_pays(g, type("R", (), {"player": 0, "extra": {"cancels": 0}})())


def test_cards_played_counter_survives_a_clone_and_a_save(g, bprd):
    pair(g, "mikey", "hellboy")
    attack(g, "mikey", "hellboy", "Cowabunga!!")
    assert g.fx.played == [1, 0] and g.clone().fx.played == [1, 0]
    saved = json.loads(json.dumps(persist.game_to_dict(g)))
    fresh = Game.new(bprd, 0, controllers={}, heroes=("michelangelo", "hellboy"))
    persist.apply_game(fresh, saved)
    assert fresh.fx.played == [1, 0]


def test_a_game_without_michelangelo_does_not_track_the_plays(bprd):
    gm = mk(bprd, "liz-sherman", "hellboy")
    pair(gm, "liz", "hellboy")
    attack(gm, "liz", "hellboy", "Fireball")
    assert gm.fx.played == [0, 0] and "played" not in gm.fx.to_dict()


# ---------------------------------------------------------------- simulator games, Medusa included (engine only)

OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]


@pytest.mark.parametrize("other", OTHERS)
def test_simulated_games_with_michelangelo_on_both_sides_finish_with_heuristic_and_ismcts(other):
    from sparring import sim
    for bot, human in (("michelangelo", other), (other, "michelangelo")):
        for seed in range(3):
            assert sim.play(seed, bot_hero=bot, human_hero=human).turns >= 1
        ai = sim.make_bot("ismcts", iterations=6, seed=0)
        assert sim.play(0, bot_hero=bot, human_hero=human, medusa=ai, max_turns=30).turns >= 1 and ai.fallbacks == 0
