"""The ten cards of Elektra on the engine (bot side), with the RESURRECTED lines both ways (before and after the Resurrect).
Helpers and the off-board state are in tests/test_elektra_effects.py."""
from __future__ import annotations

from conftest import give
from sparring.effects.select import counter_value
from test_effects_combat import pair, put_adjacent
from test_elektra_effects import HANDS, first, hand_of, katana, life, mk, remove_elektra, resurrect, resurrected, spread, wall


def hp(g, *fids):
    return [g.fighters[f].hp for f in fids]


def attack_pair(g, **kw):
    e, foe = pair(g, "elektra", "leonardo")
    return e, foe


# ---------------------------------------------------------------- Mystic Assassin

def test_mystic_assassin_costs_elektra_3_health_in_her_first_life(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    g.attack(e, foe, give(g, 0, "Mystic Assassin"), wall(g))
    assert e.hp == 7 - 3 and life(g) == 0


def test_mystic_assassin_costs_nothing_once_she_is_resurrected(bprd):
    g = resurrected(mk(bprd))
    e, foe = attack_pair(g)
    g.attack(e, foe, give(g, 0, "Mystic Assassin"), wall(g))
    assert e.hp == 9


def test_mystic_assassin_that_takes_her_out_on_her_own_turn_removes_her_and_she_returns_at_her_next_turn(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    e.hp = 3
    g.attack(e, foe, give(g, 0, "Mystic Assassin"), wall(g))
    assert g.winner is None and life(g) == 1 and not e.alive and e.off_board
    g.end_turn()
    g.begin_turn()
    assert life(g) == 1
    g.end_turn()
    g.controllers[0].queue = [first] * 12
    g.begin_turn()
    assert life(g) == 2 and e.alive and e.hp == 9


# ---------------------------------------------------------------- The Fist

def fist_game(bprd, hand_hp=1):
    g = mk(bprd)
    h = g.fighters["hand1"]
    foe = g.fighters["leonardo"]
    h.pos = min(g.board.spaces)
    foe.pos = sorted(g.board.adj[h.pos])[0]
    h.hp = hand_hp
    return g, h, foe


def test_the_fist_returns_to_the_hand_and_gains_an_action_when_the_hand_hurts_itself(bprd):
    g, h, foe = fist_game(bprd, hand_hp=3)
    card = give(g, 0, "The Fist")
    g.controllers[0].queue = [[True]]
    actions = g.actions_left
    g.attack(h, foe, card, wall(g))
    assert h.hp == 2 and card in g.players[0].hand and g.actions_left == actions       # the attack spent one, the card gave one back


def test_the_fist_still_returns_and_gains_the_action_when_its_damage_defeats_the_hand(bprd):
    g, h, foe = fist_game(bprd, hand_hp=1)       # Ivan 2026-11-22, E4
    card = give(g, 0, "The Fist")
    g.controllers[0].queue = [[True]]
    actions = g.actions_left
    g.attack(h, foe, card, wall(g))
    assert not h.alive and not h.off_board and card in g.players[0].hand and g.actions_left == actions
    assert g.winner is None


def test_the_fist_declined_stays_in_the_discard_pile(bprd):
    g, h, foe = fist_game(bprd, hand_hp=3)
    card = give(g, 0, "The Fist")
    g.controllers[0].queue = [[False]]
    actions = g.actions_left
    g.attack(h, foe, card, wall(g))
    assert h.hp == 3 and card in g.players[0].discard and g.actions_left == actions - 1


# ---------------------------------------------------------------- Hands of Red

def test_hands_of_red_returns_a_defeated_hand_with_one_health_to_her_zone(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    g.defeat(g.fighters["hand2"])
    g.attack(e, foe, give(g, 0, "Hands of Red"), wall(g))
    h = g.fighters["hand2"]
    assert h.alive and h.hp == 1 and g.board.share_zone(e.pos, h.pos)


def test_hands_of_red_does_nothing_with_no_hand_defeated(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    before = {h: g.fighters[h].pos for h in HANDS}
    g.attack(e, foe, give(g, 0, "Hands of Red"), wall(g))
    assert {h: g.fighters[h].pos for h in HANDS} == before


# ---------------------------------------------------------------- Snakeroot Clan

def test_snakeroot_clan_swaps_her_with_a_hand_and_that_hand_is_the_defender_out_of_range(bprd):
    g = mk(bprd, turn=1)
    foe, e = pair(g, "leonardo", "elektra")
    far = g.fighters["hand3"]
    far_pos, e_pos = far.pos, e.pos
    g.controllers[0].queue = [[True], ["hand3"]]
    res = g.attack(foe, e, katana(g), give(g, 0, "Snakeroot Clan"))
    assert e.pos == far_pos and far.died_at == e_pos          # she stands where the Hand stood; the Hand took her place and fell
    assert res.target == "hand3" and not far.alive and e.alive      # the Hand took the blow (6 - 1): the swap saved her


def test_snakeroot_clan_declined_leaves_her_the_defender(bprd):
    g = mk(bprd, turn=1)
    foe, e = pair(g, "leonardo", "elektra")
    g.controllers[0].queue = [[False]]
    res = g.attack(foe, e, katana(g), give(g, 0, "Snakeroot Clan"))
    assert res.target == "elektra"


def test_snakeroot_clan_with_no_hand_on_the_board_asks_nothing(bprd):
    g = mk(bprd, turn=1)
    foe, e = pair(g, "leonardo", "elektra")
    for h in HANDS:
        g.defeat(g.fighters[h])
    res = g.attack(foe, e, katana(g), give(g, 0, "Snakeroot Clan"))
    assert res.target == "elektra" and g.controllers[0].requests == []


# ---------------------------------------------------------------- Cloaked In Shadow

def test_cloaked_in_shadow_cancels_the_card_and_moves_her_only_when_resurrected(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    where = e.pos
    g.attack(e, foe, give(g, 0, "Cloaked In Shadow"), wall(g))
    assert e.pos == where and g.controllers[0].requests == []


def test_cloaked_in_shadow_resurrected_moves_her_up_to_three_spaces_after_combat(bprd):
    g = resurrected(mk(bprd))
    e, foe = attack_pair(g)
    where = e.pos
    g.controllers[0].queue = [lambda r: [max(r.options, key=lambda s: g.board.distance(where, s))]]
    g.attack(e, foe, give(g, 0, "Cloaked In Shadow"), wall(g))
    assert e.pos != where and 0 < g.board.distance(where, e.pos) <= 3


# ---------------------------------------------------------------- Intercept

def test_intercept_is_3_before_the_resurrect_even_with_a_sai_in_hand(bprd):
    g = mk(bprd, turn=1)
    foe, e = pair(g, "leonardo", "elektra")
    hand_of(g, 0, "Sai")
    res = g.attack(foe, e, katana(g), give(g, 0, "Intercept"))
    assert res.def_value == 3 and res.damage == 6 - 3


def test_intercept_resurrected_with_a_sai_revealed_is_5(bprd):
    g = resurrected(mk(bprd, turn=1))
    g.turn = 1
    foe, e = pair(g, "leonardo", "elektra")
    hand_of(g, 0, "Sai")
    g.controllers[0].queue = [[True]]
    res = g.attack(foe, e, katana(g), give(g, 0, "Intercept"))
    assert res.def_value == 5 and res.damage == 1
    assert any(c.title == "Sai" for c in g.players[0].hand)           # shown, not discarded


def test_intercept_resurrected_with_no_sai_in_hand_asks_nothing_and_is_3(bprd):
    g = resurrected(mk(bprd, turn=1))
    g.turn = 1
    foe, e = pair(g, "leonardo", "elektra")
    g.controllers[0].requests.clear()
    res = g.attack(foe, e, katana(g), give(g, 0, "Intercept"))
    assert res.def_value == 3 and g.controllers[0].requests == []


# ---------------------------------------------------------------- Mesmerize, Ninjitsu, Sai, Whirlwind

def mesmerize_game(g):
    k, w = hand_of(g, 1, "Katana"), wall(g)
    card = give(g, 0, "Mesmerize")
    actions = g.actions_left
    g.play_scheme(0, g.fighters["elektra"], card)
    return k, w, actions


def test_mesmerize_looks_at_the_hand_and_gains_an_action_and_discards_nothing_before_the_resurrect(bprd):
    g = mk(bprd)
    k, w, actions = mesmerize_game(g)
    assert len(g.players[1].hand) == 2 and g.actions_left == actions          # one spent, one gained
    assert sorted(c.card_id for c in g.players[0].known.cards(g.players[1])) == sorted([k.card_id, w.card_id])


def test_mesmerize_resurrected_also_makes_them_discard_the_card_she_chooses(bprd):
    g = resurrected(mk(bprd))
    k = hand_of(g, 1, "Katana")
    w = wall(g)
    g.controllers[0].queue = [lambda r: [k.card_id] if k.card_id in r.options else list(r.options)[:1]]
    actions = g.actions_left
    g.play_scheme(0, g.fighters["elektra"], give(g, 0, "Mesmerize"))
    assert g.players[1].hand == [w] and k in g.players[1].discard and g.actions_left == actions


def test_ninjitsu_places_the_fighter_that_played_it_in_any_space(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    spot = max(s for s in g.board.spaces if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[spot]]
    g.attack(e, foe, give(g, 0, "Ninjitsu"), wall(g))
    assert e.pos == spot


def test_whirlwind_resurrected_hits_each_adjacent_opposing_fighter_for_1(bprd):
    g = resurrected(mk(bprd))
    e, foe = attack_pair(g)
    other = g.fighters["leonardo"]
    before = other.hp
    g.attack(e, foe, give(g, 0, "Whirlwind"), wall(g))
    assert other.hp == before - 1


def test_whirlwind_before_the_resurrect_does_nothing(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    before = foe.hp
    g.attack(e, foe, give(g, 0, "Whirlwind"), wall(g))
    assert foe.hp == before


def test_sai_is_a_plain_versatile_4(bprd):
    g = mk(bprd)
    e, foe = attack_pair(g)
    res = g.attack(e, foe, give(g, 0, "Sai"), None)
    assert res.atk_value == 4 and res.damage == 4
