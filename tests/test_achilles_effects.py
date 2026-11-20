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
    assert res.damage == 5 and hellboy.hp == hellboy.max_hp - 5            # the 5 of the paid Doom lands, the fall did not undo it
    assert len(g.players[0].hand) == 4 - 2                                  # four cards held, the Doom played, two thrown away at random


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


# ---------------------------------------------------------------- Test For Weakness (the double attack)

def test_test_for_weakness_is_a_one_followed_by_an_undefended_three(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    hp = hellboy.hp
    res = g.attack(achilles, hellboy, give(g, 0, "Test For Weakness"), None)
    assert res.damage == 1 and res.second is not None and res.second.damage == 3
    assert hellboy.hp == hp - 1 - 3


def test_the_foe_may_defend_the_second_attack_with_a_new_card(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    block = give(g, 1, "B.P.R.D. Training")                                          # defense 3: stops the 3
    g.controllers[1].choose_second_defense = lambda game, att, tgt, value, card: block
    res = g.attack(achilles, hellboy, give(g, 0, "Test For Weakness"), None)
    assert res.second.def_card is block and res.second.damage == 0


def test_a_feint_against_test_for_weakness_leaves_no_second_attack_and_a_plain_defense_does_not(bprd):
    g = mk(bprd, foe="medusa")
    achilles, medusa = pair(g, "achilles", "medusa")
    res = g.attack(achilles, medusa, give(g, 0, "Test For Weakness"), give(g, 1, "Feint"))
    assert res.second is None and medusa.hp == medusa.max_hp - 0               # the Feint cancels the card's effects, the second attack with them
    g2 = mk(bprd)
    ach, hell = pair(g2, "achilles", "hellboy")
    res = g2.attack(ach, hell, give(g2, 0, "Test For Weakness"), give(g2, 1, "B.P.R.D. Training"))
    assert res.second is not None


def test_the_plus_two_of_achilles_applies_to_both_parts_once_patroclus_is_down(bprd):
    g = mk(bprd)
    fall(g)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    res = g.attack(achilles, hellboy, give(g, 0, "Test For Weakness"), None)
    assert res.damage == 1 + 2 and res.second.damage == 3 + 2                         # the engine's reading: a passive applies to the second attack (docs/combat-flow.md, Pending Ivan 3)


# ---------------------------------------------------------------- what the bot is told about the price of The Day of Your Doom

def test_the_doom_request_carries_the_fighter_the_damage_and_the_points_it_really_adds(bprd):
    g = mk(bprd)
    patroclus, hellboy = pair(g, "patroclus", "hellboy")
    g.controllers[0].queue = [[False]]
    g.attack(patroclus, hellboy, give(g, 0, "The Day of Your Doom"), None)
    asked = [r for r in g.controllers[0].requests if r.kind == "optional"]
    assert asked[0].extra["damage_buys"] == {"fighter": "patroclus", "damage": 2, "gain": 2, "target": "hellboy"}
    g2 = mk(bprd)
    patroclus, hellboy = pair(g2, "patroclus", "hellboy")
    g2.controllers[0].queue = [[False]]
    g2.attack(patroclus, hellboy, give(g2, 0, "The Day of Your Doom"), give(g2, 1, "B.P.R.D. Training"))
    asked = [r for r in g2.controllers[0].requests if r.kind == "optional"]
    assert asked[0].extra["damage_buys"]["gain"] == 2                       # Training (3) against 3 and 5: 0 then 2


def test_the_helm_request_tells_a_bot_that_the_swap_replaces_the_combatant(bprd):
    g = mk(bprd, turn=1)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    put_adjacent(g, "patroclus", "achilles")
    g.controllers[0].queue = [[False]]
    g.attack(hellboy, achilles, foe_attack(g), give(g, 0, "Under Achilles' Helm"))
    asked = [r for r in g.controllers[0].requests if r.kind == "optional"]
    assert asked[0].extra["replaces_combatant"] == {"this": "achilles", "role": "defense"}


# ---------------------------------------------------------------- Ivan 2026-11-20: the draw without a card and in the second attack

def test_a_defender_who_plays_no_card_and_wins_draws_while_patroclus_is_down(bprd):
    g = mk(bprd, turn=1)
    fall(g)
    g.players[0].hand.clear()
    hellboy, achilles = pair(g, "hellboy", "achilles")
    res = g.attack(hellboy, achilles, foe_attack(g), None, values=(-5, 0))          # the pistol's 5 become 0: Achilles takes no damage and wins
    assert not res.attacker_won and len(g.players[0].hand) == 1


def test_no_draw_without_a_card_when_he_loses_or_when_patroclus_lives(bprd):
    g = mk(bprd, turn=1)
    fall(g)
    g.players[0].hand.clear()
    hellboy, achilles = pair(g, "hellboy", "achilles")
    res = g.attack(hellboy, achilles, foe_attack(g), None)                           # 5 on an open defender: he lost
    assert res.attacker_won and len(g.players[0].hand) == 0
    g2 = mk(bprd, turn=1)
    hell, ach = pair(g2, "hellboy", "achilles")
    res = g2.attack(hell, ach, foe_attack(g2), None, values=(-5, 0))
    assert not res.attacker_won and len(g2.players[0].hand) == 0


def test_winning_both_parts_of_test_for_weakness_draws_two(bprd):
    g = mk(bprd)
    fall(g)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    card = give(g, 0, "Test For Weakness")
    res = g.attack(achilles, hellboy, card, None)
    assert res.attacker_won and res.second.attacker_won and len(g.players[0].hand) == 2


def test_each_combat_is_judged_on_its_own_for_the_draw(bprd):
    g = mk(bprd)
    fall(g)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    block = give(g, 1, "B.P.R.D. Training")                                          # 3 against 1+2: the first part is lost, the second (3+2) is undefended
    res = g.attack(achilles, hellboy, give(g, 0, "Test For Weakness"), block)
    assert not res.attacker_won and res.second.attacker_won and len(g.players[0].hand) == 1


def test_without_the_flag_nobody_else_reads_the_second_attack_differently(bprd):
    """Wyatt Earp's and Jill Trent's AFTER abilities carry no `second_attack` flag: the second attack does not run them."""
    from sparring.effects.model import load_effects
    for slug in ("wyatt-earp", "jill-trent"):
        assert not any(e.get("second_attack") or e.get("cardless") for e in load_effects(slug).ability_after)
    assert [e["id"] for e in load_effects("achilles").ability_after if e.get("second_attack") and e.get("cardless")] == ["vengeance_draw"]


def test_achilles_defending_a_double_attack_draws_for_the_second_combat_he_wins(bprd, monkeypatch):
    from sparring.effects.model import load_effects
    monkeypatch.setitem(load_effects("hellboy").card("Horseshoes And Hand Grenades").moments, "after", [{"op": "second_attack", "amount": 3}])
    g = mk(bprd, turn=1)
    fall(g)
    hellboy, achilles = pair(g, "hellboy", "achilles")
    heel = give(g, 0, "Achilles' Heel")
    g.controllers[0].choose_second_defense = lambda game, att, tgt, value, card: heel
    res = g.attack(hellboy, achilles, give(g, 1, "Horseshoes And Hand Grenades"), None)
    assert res.attacker_won and res.second is not None and not res.second.attacker_won     # lost the open first part, won the second with the 4
    assert len(g.players[0].hand) == 1                                                       # the heel left the hand, one card drawn


# ---------------------------------------------------------------- the AI's estimate of the next attack (Game.attack_bonus)

def test_the_ai_estimate_of_an_attack_counts_the_vengeance(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    patroclus = g.fighters["patroclus"]
    assert g.attack_bonus(achilles, hellboy) == 0
    fall(g)
    assert g.attack_bonus(achilles, hellboy) == 2 and g.attack_bonus(achilles) == 2
    assert g.attack_bonus(g.fighters["hellboy"], achilles) == 0 and not patroclus.alive


# ---------------------------------------------------------------- Blessed By Hermes and Skirmish

def test_blessed_by_hermes_moves_both_fighters_up_to_three_through_enemies(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    patroclus = g.fighters["patroclus"]
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]] for _ in range(4)]
    start = (achilles.pos, patroclus.pos)
    g.attack(achilles, hellboy, give(g, 0, "Blessed By Hermes"), None)
    moved = {r.extra["fighter"] for r in seen if r.kind == "space"}
    assert moved == {"achilles", "patroclus"} and all(r.extra.get("through") is True for r in seen if r.kind == "space")
    assert all(r.extra["steps"] == 3 for r in seen if r.kind == "space")
    assert (achilles.pos, patroclus.pos) != start


def test_skirmish_moves_one_fighter_of_the_combat_only_when_the_combat_was_won(bprd):
    g = mk(bprd)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]] for _ in range(3)]
    g.attack(achilles, hellboy, give(g, 0, "Skirmish"), None)
    spaces = [r for r in seen if r.kind == "space"]
    assert spaces and spaces[0].extra["steps"] == 2 and spaces[0].extra["fighter"] in ("achilles", "hellboy")
    g2 = mk(bprd)
    ach, hell = pair(g2, "achilles", "hellboy")
    seen2 = []
    g2.controllers[0].queue = [lambda req: seen2.append(req) or [req.options[-1]] for _ in range(3)]
    g2.attack(ach, hell, give(g2, 0, "Skirmish"), give(g2, 1, "B.P.R.D. Training"), values=(-2, 0))    # a lost combat: nothing moves
    assert not [r for r in seen2 if r.kind == "space"]


def test_a_first_combat_won_by_achilles_with_a_card_draws_once_and_never_asks_the_cardless_hook_for_the_attacker(bprd, monkeypatch):
    """`hero_after` and `run_moment` share the run key `after:atk`; the flow only calls the hook for the attacker of a second attack. Were the two
    to diverge, this first combat would draw twice."""
    from sparring.effects import ops_combat
    calls = []
    real = ops_combat.hero_after
    monkeypatch.setattr(ops_combat, "hero_after", lambda flow, name: calls.append(name) or real(flow, name))
    g = mk(bprd)
    fall(g)
    achilles, hellboy = pair(g, "achilles", "hellboy")
    res = g.attack(achilles, hellboy, give(g, 0, "Brothers In Arms"), give(g, 1, "B.P.R.D. Training"), values=(5, 0))
    assert res.attacker_won and res.second is None and len(g.players[0].hand) == 1
    assert "atk" not in calls and "def" not in calls                   # a card was played on each side: neither side is cardless
