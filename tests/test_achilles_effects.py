"""Achilles' ability and cards on the interpreter, bot side (player 0 plays Achilles, the controllers answer). The human side (panel,
FakeTTS) is in tests/test_achilles_human.py and the full games in tests/test_achilles_matrix.py. The numbers are the ones printed on the
real cards (data/heroes/achilles.json)."""
from __future__ import annotations

from conftest import give
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import hp, pair, put_adjacent


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Achilles = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("achilles", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def foe_attack(g, title="Service Pistol"):
    return give(g, 1, title)


def hand_of(g, player, n):
    """`n` cards of the deck in the hand (their titles do not matter)."""
    st = g.players[player]
    for c in st.deck[:n]:
        st.deck.remove(c)
        st.hand.append(c)
    return list(st.hand)


def fall(g):
    """Patroclus is defeated by an effect (the whole of his life)."""
    g.damage(g.fighters["patroclus"], g.fighters["patroclus"].hp, "effect")


# ---------------------------------------------------------------- the figures and the sheet

def test_achilles_is_interpreted_and_has_the_printed_figures(bprd):
    g = mk(bprd)
    assert "achilles" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["achilles", "patroclus"]
    achilles, patroclus = g.fighters["achilles"], g.fighters["patroclus"]
    assert (achilles.hp, achilles.move, patroclus.hp, patroclus.move) == (18, 2, 6, 2)
    assert not achilles.ranged and not patroclus.ranged
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 3, 6, 8, 10, 12, 14, 17, 20, 22, 25, 28)] == [
        "Brothers In Arms", "Test For Weakness", "Battle Frenzy", "The Day of Your Doom", "Battle Hardened", "Wily Fighting",
        "Skirmish", "Feint", "Blessed By Hermes", "Achilles' Heel", "Under Achilles' Helm", "Spear Throw"]
    assert {by_idx(i).fighter for i in (6, 7, 8, 9)} == {"Patroclus"}
    assert {by_idx(i).fighter for i in range(22, 30)} == {"Achilles"}


# ---------------------------------------------------------------- the ability

def test_when_patroclus_falls_achilles_discards_two_random_cards(bprd):
    g = mk(bprd)
    before = hand_of(g, 0, 4)
    discard = len(g.players[0].discard)
    fall(g)
    assert not g.fighters["patroclus"].alive
    assert len(g.players[0].hand) == 2 and len(g.players[0].discard) == discard + 2
    assert set(g.players[0].hand) < set(before)


def test_with_fewer_than_two_cards_he_discards_what_he_holds(bprd):
    g = mk(bprd)
    hand_of(g, 0, 1)
    fall(g)
    assert g.players[0].hand == []
    g2 = mk(bprd)
    fall(g2)
    assert g2.players[0].hand == [] and not g2.fighters["patroclus"].alive


def test_the_discard_happens_in_the_combat_that_defeats_patroclus_and_only_once(bprd):
    g = mk(bprd, turn=1)
    hellboy, patroclus = pair(g, "hellboy", "patroclus")
    hand_of(g, 0, 5)
    patroclus.hp = 3
    res = g.attack(hellboy, patroclus, foe_attack(g, "Service Pistol"), None)
    assert not patroclus.alive and res.target == "patroclus"
    assert len(g.players[0].hand) == 3
    g.damage(g.fighters["achilles"], 1, "effect")
    assert len(g.players[0].hand) == 3


def test_an_enemy_falling_discards_nothing(bprd):
    g = mk(bprd)
    hand_of(g, 0, 3)
    g.damage(g.fighters["lobster"], g.fighters["lobster"].hp, "effect")
    assert len(g.players[0].hand) == 3


def test_attacks_get_plus_two_only_while_patroclus_is_defeated(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    res = g.attack(achilles, hellboy, give(g, 0, "Brothers In Arms"), None)
    assert res.damage == 4
    fall(g)
    g.begin_turn()
    achilles, hellboy = pair(g, "achilles", "hellboy")
    hellboy.hp = hellboy.max_hp
    res = g.attack(achilles, hellboy, give(g, 0, "Brothers In Arms"), None)
    assert res.damage == 6


def test_the_bonus_covers_a_versatile_card_played_as_attack_and_not_a_defense(bprd):
    g = mk(bprd)
    fall(g)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    res = g.attack(achilles, hellboy, give(g, 0, "Skirmish"), None)
    assert res.damage == 4 + 2
    g2 = mk(bprd, turn=1)
    fall(g2)
    hell, ach = pair(g2, "hellboy", "achilles")
    atk = foe_attack(g2)
    res = g2.attack(hell, ach, atk, give(g2, 0, "Achilles' Heel"))
    assert res.damage == max(0, atk.value - 4)                          # a defense card keeps its printed 4


def test_the_draw_after_a_won_combat_only_while_patroclus_is_defeated(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    atk = give(g, 0, "Brothers In Arms")
    deck = len(g.players[0].deck)
    res = g.attack(achilles, hellboy, atk, None)
    assert res.attacker_won and len(g.players[0].hand) == 0 and len(g.players[0].deck) == deck
    fall(g)
    g.players[0].hand.clear()
    g.begin_turn()
    achilles, hellboy = pair(g, "achilles", "hellboy")
    atk = give(g, 0, "Brothers In Arms")
    deck = len(g.players[0].deck)
    res = g.attack(achilles, hellboy, atk, None)
    assert res.attacker_won and len(g.players[0].hand) == 1 and len(g.players[0].deck) == deck - 1


def test_a_defender_who_wins_draws_and_one_who_loses_does_not(bprd):
    g = mk(bprd, turn=1)
    fall(g)
    g.players[0].hand.clear()
    hellboy, achilles = pair(g, "hellboy", "achilles")
    res = g.attack(hellboy, achilles, foe_attack(g), give(g, 0, "Achilles' Heel"))
    assert res.attacker_won and len(g.players[0].hand) == 0              # the pistol's 5 beats the heel's 4: Achilles lost
    g2 = mk(bprd, turn=1)
    fall(g2)
    g2.players[0].hand.clear()
    hell, ach = pair(g2, "hellboy", "achilles")
    res = g2.attack(hell, ach, foe_attack(g2), give(g2, 0, "Achilles' Heel"), values=(-3, 0))
    assert not res.attacker_won and len(g2.players[0].hand) == 1         # "if Achilles wins combat", defending too


# ---------------------------------------------------------------- Achilles' Heel and Brothers In Arms

def test_achilles_heel_gives_the_opponent_an_action_only_when_it_lost(bprd):
    g = mk(bprd, turn=1)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    g.actions_left = 2
    res = g.attack(hellboy, achilles, foe_attack(g), give(g, 0, "Achilles' Heel"), values=(4, 0))
    assert res.attacker_won and g.actions_left == 2                      # the attack spent 1, the lost heel gave 1 back
    g2 = mk(bprd, turn=1)
    hell, ach = pair(g2, "hellboy", "achilles")
    g2.actions_left = 2
    res = g2.attack(hell, ach, foe_attack(g2), give(g2, 0, "Achilles' Heel"), values=(-4, 0))
    assert not res.attacker_won and g2.actions_left == 1


def test_brothers_in_arms_gains_an_action_while_patroclus_lives(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    g.actions_left = 2
    g.attack(achilles, hellboy, give(g, 0, "Brothers In Arms"), None)
    assert g.actions_left == 2 - 1 + 1
    g2 = mk(bprd)
    fall(g2)
    ach, hell = pair(g2, "achilles", "hellboy")
    g2.actions_left = 2
    g2.attack(ach, hell, give(g2, 0, "Brothers In Arms"), None)
    assert g2.actions_left == 2 - 1


# ---------------------------------------------------------------- Under Achilles' Helm

def test_under_achilles_helm_swaps_the_brothers_and_patroclus_takes_the_blow(bprd):
    g = mk(bprd, turn=1)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    patroclus = g.fighters["patroclus"]
    where_a = achilles.pos
    patroclus.pos = next(s for s in sorted(g.board.spaces, reverse=True)
                         if all(f.pos != s for f in g.fighters.values() if f.alive) and s != where_a)
    where_p = patroclus.pos
    g.controllers[0].queue = [[True]]
    atk = foe_attack(g)
    res = g.attack(hellboy, achilles, atk, give(g, 0, "Under Achilles' Helm"))
    assert (achilles.pos, patroclus.pos) == (where_p, where_a)
    assert res.target == "patroclus" and res.damage == max(0, atk.value - 2)
    assert patroclus.hp == 6 - res.damage and achilles.hp == 18


def test_under_achilles_helm_declined_changes_nobody(bprd):
    g = mk(bprd, turn=1)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    where = (achilles.pos, g.fighters["patroclus"].pos)
    g.controllers[0].queue = [[False]]
    atk = foe_attack(g)
    res = g.attack(hellboy, achilles, atk, give(g, 0, "Under Achilles' Helm"))
    assert (achilles.pos, g.fighters["patroclus"].pos) == where and res.target == "achilles" and res.damage == max(0, atk.value - 2)


def test_under_achilles_helm_offers_nothing_when_patroclus_is_defeated(bprd):
    g = mk(bprd, turn=1)
    fall(g)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    g.controllers[0].queue = [[True]]
    atk = foe_attack(g)
    res = g.attack(hellboy, achilles, atk, give(g, 0, "Under Achilles' Helm"))
    assert res.target == "achilles" and g.controllers[0].queue == [[True]]


def test_patroclus_dying_under_the_helm_costs_the_two_cards(bprd):
    g = mk(bprd, turn=1)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    patroclus = g.fighters["patroclus"]
    put_adjacent(g, "patroclus", "hellboy")
    patroclus.hp = 1
    hand_of(g, 0, 4)
    g.controllers[0].queue = [[True]]
    g.attack(hellboy, achilles, foe_attack(g), give(g, 0, "Under Achilles' Helm"))
    assert not patroclus.alive and len(g.players[0].hand) == 5 - 1 - 2     # the helm left the hand, two more fell at random


# ---------------------------------------------------------------- The Day of Your Doom and Battle Frenzy

def test_the_day_of_your_doom_costs_patroclus_two_for_a_five(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    g.controllers[0].queue = [[True]]
    res = g.attack(patroclus, hellboy, give(g, 0, "The Day of Your Doom"), None)
    assert patroclus.hp == 4 and res.damage == 5


def test_the_day_of_your_doom_declined_is_a_three(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    g.controllers[0].queue = [[False]]
    res = g.attack(patroclus, hellboy, give(g, 0, "The Day of Your Doom"), None)
    assert patroclus.hp == 6 and res.damage == 3


def test_the_day_of_your_doom_can_kill_patroclus_and_costs_the_cards(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    patroclus.hp = 2
    hand_of(g, 0, 4)
    g.controllers[0].queue = [[True]]
    res = g.attack(patroclus, hellboy, give(g, 0, "The Day of Your Doom"), None)
    assert not patroclus.alive
    assert len(g.players[0].hand) == 5 - 1 - 2
    assert res.damage in (0, 5)


def test_battle_frenzy_hurts_both_fighters_of_the_combat(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    atk = give(g, 0, "Battle Frenzy")
    res = g.attack(patroclus, hellboy, atk, None)
    assert hellboy.hp == hellboy.max_hp - res.damage - 2 and patroclus.hp == 6 - 2
    assert atk.value == 3


def test_battle_frenzy_can_defeat_the_player_who_plays_it(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    patroclus.hp = 2
    g.attack(patroclus, hellboy, give(g, 0, "Battle Frenzy"), None)
    assert not patroclus.alive


# ---------------------------------------------------------------- the other cards

def test_wily_fighting_hurts_each_opposing_fighter_adjacent_to_the_fighter(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    lobster = g.fighters["lobster"]
    put_adjacent(g, "lobster", "achilles")
    before = hp(g, "hellboy", "lobster")
    res = g.attack(achilles, hellboy, give(g, 0, "Wily Fighting"), None)
    after = hp(g, "hellboy", "lobster")
    assert after[1] == before[1] - 1 and after[0] == before[0] - res.damage - 1
    assert lobster.alive


def test_feint_cancels_the_effects_of_the_opponents_card(bprd):
    g = mk(bprd, turn=1)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    atk = foe_attack(g, "Service Pistol")
    res = g.attack(hellboy, achilles, atk, give(g, 0, "Feint"))
    assert res.damage == max(0, atk.value - 2)


def test_spear_throw_hits_an_opposing_fighter_in_achilles_zone(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    spear = give(g, 0, "Spear Throw")
    before = hellboy.hp
    g.actions_left = 2
    g.play_scheme(0, achilles, spear)
    assert hellboy.hp == before - 2


def test_battle_hardened_takes_a_card_back_from_the_discard_pile(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    gone = g.players[0].deck[0]
    g.players[0].deck.remove(gone)
    g.players[0].discard.append(gone)
    g.controllers[0].queue = [lambda req: [gone.card_id]]
    g.attack(achilles, hellboy, give(g, 0, "Battle Hardened"), None)
    assert gone in g.players[0].hand and gone not in g.players[0].discard
