"""Chupacabra on the interpreter, bot side (player 0 plays Chupacabra, the controllers answer): THE HUNGER, every card of the deck
with the numbers printed on it (sheet 176, read from the images on 2026-11-13) and the two plugins (Ambush, Tooth and Tail). The human
side (panel, FakeTTS) is in tests/test_chupacabra_human.py and the full games in tests/test_chupacabra_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import hand_filler, pair, put_adjacent

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Chupacabra = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("chupacabra", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def fight(g, title, foe_card=None, foe="hellboy"):
    chupa, rival = pair(g, "chupacabra", foe)
    attack = give(g, 0, title)
    defense = give(g, 1, foe_card) if foe_card else None
    return g.attack(chupa, rival, attack, defense), chupa, rival


# ---------------------------------------------------------------- the hero

def test_chupacabra_is_a_melee_hero_without_sidekicks_and_has_the_printed_deck(bprd):
    g = mk(bprd)
    chupa = g.fighters["chupacabra"]
    assert (chupa.hp, chupa.move, chupa.ranged, chupa.name) == (14, 3, False, "Chupacabra")
    assert [f.fid for f in g.own(0)] == ["chupacabra"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "chupacabra" in g.fx.dsl_heroes


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 3, 5, 8, 11, 14, 17, 20, 23, 25, 28)] == [
        "The More They Struggle", "Ambush", "Feeding", "Blood in the Air", "Wounded Beast", "Tooth and Tail", "Feint",
        "Ravenous Lunge", "Natural Toughness", "Traveler of the Night", "Unsettle"]
    assert {c.fighter for c in deck.values()} == {"Chupacabra"}
    assert [(by_idx(i).type, by_idx(i).value, by_idx(i).boost) for i in (0, 3, 5, 8, 11, 14, 17, 20, 23)] == [
        ("attack", 0, 3), ("attack", 2, 3), ("attack", 4, 2), ("attack", 4, 4), ("versatile", 3, 1), ("versatile", 2, 2),
        ("versatile", 2, 2), ("versatile", 3, 2), ("defense", 3, 3)]
    assert [(by_idx(i).type, by_idx(i).value, by_idx(i).boost) for i in (25, 28)] == [("scheme", None, 3), ("scheme", None, 2)]


# ---------------------------------------------------------------- THE HUNGER

def test_the_owner_who_says_yes_draws_a_card_after_he_attacks(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[True]]
    deck = len(g.players[0].deck)
    fight(g, "Feint", TRAINING)
    assert len(g.players[0].hand) == 1 and len(g.players[0].deck) == deck - 2      # one for the card played, one drawn


def test_the_owner_who_declines_draws_nothing(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[False]]
    fight(g, "Feint", TRAINING)
    assert not g.players[0].hand


def test_the_hunger_does_not_fire_when_chupacabra_defends(bprd):
    g = mk(bprd, turn=1)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    g.controllers[0].queue = [[True]]
    g.attack(rival, chupa, give(g, 1, "Service Pistol"), give(g, 0, "Natural Toughness"))
    assert g.controllers[0].queue == [[True]]


# ---------------------------------------------------------------- the attacks

def test_the_more_they_struggle_is_twice_the_printed_value_of_the_rival_card(bprd):
    g = mk(bprd)
    res, *_ = fight(g, "The More They Struggle", TRAINING)
    assert res.atk_value == 6 and res.def_value == 3


def test_the_more_they_struggle_against_no_defense_is_worth_nothing(bprd):
    g = mk(bprd)
    res, chupa, rival = fight(g, "The More They Struggle")
    assert res.atk_value == 0 and rival.hp == rival.max_hp


def test_ambush_discards_a_random_card_of_the_rival_and_adds_its_boost(bprd):
    g = mk(bprd)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    victim = give(g, 1, "Excalibur")
    res = g.attack(chupa, rival, give(g, 0, "Ambush"), None)
    assert victim in g.players[1].discard and not g.players[1].hand
    assert res.atk_value == 2 + victim.boost


def test_ambush_against_an_empty_hand_is_a_plain_two(bprd):
    g = mk(bprd)
    res, *_ = fight(g, "Ambush")
    assert res.atk_value == 2


def test_ambush_takes_one_card_only(bprd):
    g = mk(bprd)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    cards = [give(g, 1, t) for t in ("Excalibur", "Service Pistol", TRAINING)]
    res = g.attack(chupa, rival, give(g, 0, "Ambush"), None)
    gone = [c for c in cards if c in g.players[1].discard]
    assert len(gone) == 1 and res.atk_value == 2 + gone[0].boost


def test_ambush_that_is_cancelled_discards_nothing(bprd):
    g = mk(bprd)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    kept = give(g, 1, "Excalibur")
    res = g.attack(chupa, rival, give(g, 0, "Ambush"), give(g, 1, "Planned Recklessness"))
    assert kept in g.players[1].hand and res.atk_value == 2


def test_blood_in_the_air_may_be_boosted_after_a_combat_won_this_turn(bprd):
    g = mk(bprd)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    g.fx.won[0] = 1
    spare = give(g, 0, "Wounded Beast")
    g.controllers[0].boost = spare
    res = g.attack(chupa, rival, give(g, 0, "Blood in the Air"), None)
    assert spare in g.players[0].discard and res.atk_value == 4 + spare.boost


def test_blood_in_the_air_may_not_be_boosted_before_a_combat_is_won(bprd):
    g = mk(bprd)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    spare = give(g, 0, "Wounded Beast")
    g.controllers[0].boost = spare
    res = g.attack(chupa, rival, give(g, 0, "Blood in the Air"), None)
    assert spare in g.players[0].hand and res.atk_value == 4


def test_feeding_with_seven_or_less_health_gains_an_action_and_recovers_one(bprd):
    g = mk(bprd)
    g.fighters["chupacabra"].hp = 7
    g.actions_left = 2
    res, chupa, _ = fight(g, "Feeding", TRAINING)
    assert chupa.hp == 8 and g.actions_left == 2          # one action spent by the attack, one gained


def test_feeding_with_eight_health_does_nothing(bprd):
    g = mk(bprd)
    g.fighters["chupacabra"].hp = 8
    g.actions_left = 2
    res, chupa, _ = fight(g, "Feeding", TRAINING)
    assert chupa.hp == 8 and g.actions_left == 1


# ---------------------------------------------------------------- versatile and defense cards

@pytest.mark.parametrize("hp,value", [(7, 5), (6, 5), (8, 3), (14, 3)])
def test_wounded_beast_is_worth_five_with_seven_or_less_health(bprd, hp, value):
    g = mk(bprd)
    g.fighters["chupacabra"].hp = hp
    res, *_ = fight(g, "Wounded Beast")
    assert res.atk_value == value


def test_wounded_beast_also_defends_for_five(bprd):
    g = mk(bprd, turn=1)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    chupa.hp = 7
    res = g.attack(rival, chupa, give(g, 1, "Service Pistol"), give(g, 0, "Wounded Beast"))
    assert res.def_value == 5


def test_feint_cancels_the_effects_of_the_rival_card(bprd):
    g = mk(bprd)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    res = g.attack(chupa, rival, give(g, 0, "Feint"), give(g, 1, "Planned Recklessness"))
    assert (res.atk_value, res.def_value) == (2, 3)          # Planned Recklessness would have cancelled the Feint's effects


def test_ravenous_lunge_recovers_one_and_two_when_the_combat_is_won(bprd):
    g = mk(bprd)
    g.fighters["chupacabra"].hp = 5
    fight(g, "Ravenous Lunge", TRAINING)             # 3 against 3: the defender wins ties
    assert g.fighters["chupacabra"].hp == 6
    g2 = mk(bprd)
    g2.fighters["chupacabra"].hp = 5
    fight(g2, "Ravenous Lunge")
    assert g2.fighters["chupacabra"].hp == 7


def test_natural_toughness_returns_to_the_hand_only_when_the_combat_is_lost(bprd):
    g = mk(bprd, turn=1)
    chupa, rival = pair(g, "chupacabra", "hellboy")
    toughness = give(g, 0, "Natural Toughness")
    g.attack(rival, chupa, give(g, 1, "Right Hand Of Doom"), toughness)          # 5+ against 3: lost
    assert toughness in g.players[0].hand and toughness not in g.players[0].discard
    g2 = mk(bprd, turn=1)
    chupa, rival = pair(g2, "chupacabra", "hellboy")
    toughness = give(g2, 0, "Natural Toughness")
    g2.attack(rival, chupa, give(g2, 1, "Glimpse Of Hell"), toughness)           # 2 against 3: held
    assert toughness in g2.players[0].discard


# ---------------------------------------------------------------- Tooth and Tail

def test_tooth_and_tail_damages_up_to_two_adjacent_fighters_and_heals_for_each(bprd):
    g = mk(bprd)
    chupa, hellboy = pair(g, "chupacabra", "hellboy")
    put_adjacent(g, "lobster", "chupacabra")
    chupa.hp = 5
    hp = (hellboy.hp, g.fighters["lobster"].hp)
    g.attack(chupa, hellboy, give(g, 0, "Tooth and Tail"), give(g, 1, TRAINING))
    assert (hellboy.hp, g.fighters["lobster"].hp) == (hp[0] - 1, hp[1] - 1) and chupa.hp == 7


def test_tooth_and_tail_heals_nothing_when_the_combat_left_nobody_adjacent(bprd):
    g = mk(bprd)
    chupa, lobster = pair(g, "chupacabra", "lobster")
    chupa.hp, lobster.hp = 5, 1
    g.attack(chupa, lobster, give(g, 0, "Tooth and Tail"), None)                  # the only fighter near him dies in the combat
    assert not lobster.alive and chupa.hp == 5


def test_tooth_and_tail_lets_the_owner_choose_two_of_three(bprd):
    g = mk(bprd, "eredin")
    chupa, eredin = pair(g, "chupacabra", "eredin", others_away=False)
    riders = [f for f in g.fighters.values() if f.owner == 1 and f.fid != "eredin"]
    spots = [s for s in sorted(g.board.adj[chupa.pos]) if s != eredin.pos][:2]
    if len(spots) < 2:
        pytest.skip("the space has fewer than three neighbours")
    for rider, spot in zip(riders[:2], spots):
        rider.pos = spot
    for far in riders[2:]:
        far.pos = max(g.board.spaces)
    chupa.hp = 4
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [riders[0].fid, "eredin"]]
    before = {f.fid: f.hp for f in (eredin, *riders[:2])}
    g.attack(chupa, eredin, give(g, 0, "Tooth and Tail"), None)
    assert seen and seen[0].kind == "fighter" and seen[0].max == 2
    hit = [f.fid for f in (eredin, *riders[:2]) if f.hp < before[f.fid] or not f.alive]
    assert sorted(hit) == sorted([riders[0].fid, "eredin"]) and chupa.hp == 6


# ---------------------------------------------------------------- the schemes

def test_traveler_of_the_night_moves_up_to_four_through_enemies_and_gains_an_action(bprd):
    g = mk(bprd)
    chupa, _ = pair(g, "chupacabra", "hellboy")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or []]
    g.actions_left = 2
    g.play_scheme(0, chupa, give(g, 0, "Traveler of the Night"))
    assert g.actions_left == 2
    assert seen[0].extra["steps"] == 4 and seen[0].extra["through"] is True


def test_unsettle_makes_the_rival_discard_one_card(bprd):
    g = mk(bprd)
    chupa, _ = pair(g, "chupacabra", "hellboy")
    hand_filler(g, 1, 3)
    g.controllers[0].queue = [[False]]
    g.actions_left = 2
    g.play_scheme(0, chupa, give(g, 0, "Unsettle"))
    assert len(g.players[1].hand) == 2 and chupa.hp == 14


def test_unsettle_for_two_damage_makes_the_rival_discard_two_cards(bprd):
    g = mk(bprd)
    chupa, _ = pair(g, "chupacabra", "hellboy")
    hand_filler(g, 1, 3)
    g.controllers[0].queue = [[True]]
    g.play_scheme(0, chupa, give(g, 0, "Unsettle"))
    assert len(g.players[1].hand) == 1 and chupa.hp == 12


def test_unsettle_needs_an_opposing_fighter_in_his_zone(bprd):
    g = mk(bprd)
    chupa, _ = pair(g, "chupacabra", "hellboy")
    outside = [s for s in sorted(g.board.spaces, reverse=True) if not g.board.share_zone(chupa.pos, s)]
    for fighter, space in zip([f for f in g.fighters.values() if f.owner == 1], outside):
        fighter.pos = space
    hand_filler(g, 1, 3)
    g.controllers[0].queue = [[True]]
    g.play_scheme(0, chupa, give(g, 0, "Unsettle"))
    assert len(g.players[1].hand) == 3 and chupa.hp == 14 and g.controllers[0].queue == [[True]]
