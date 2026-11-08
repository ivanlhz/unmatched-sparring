"""Jill Trent and a tied combat (Iván, 2026-11-07/08): the DEFENDER wins when its defense value is >= the attack value. Caught
Red-Handed ("2 cards if you won") reads the engine's result: on a tie the defender made the rival discard 2, the attacker only 1."""
from __future__ import annotations

import pytest

from conftest import give
from test_effects_combat import pair
from test_jill_trent_effects import HYPNORAY, TONIC, mk, on_top
from tie_helpers import plain_rival_card, record_after_results


def fill_rival_hand(g, n=4):
    for c in list(g.players[1].deck)[:n]:
        g.players[1].deck.remove(c)
        g.players[1].hand.append(c)


def attack_tied(g, jill, foe, played):
    return g.attack(jill, foe, played, plain_rival_card(g, played.value + g.attack_bonus(jill, foe), "defense"))


def defend_tied(g, jill, foe, played):
    return g.attack(foe, jill, plain_rival_card(g, played.value, "attack"), played)


def test_a_tie_in_attack_is_lost_by_jill_and_the_rival_discards_one(bprd, monkeypatch):
    g = mk(bprd, gadget=0)
    jill, h = pair(g, "jill", "hellboy")
    fill_rival_hand(g)
    seen = record_after_results(monkeypatch)
    before = len(g.players[1].hand)
    res = attack_tied(g, jill, h, give(g, 0, "Caught Red-Handed"))
    assert res.atk_value == res.def_value and not res.attacker_won
    assert (0, "lost") in seen and (0, "won") not in seen
    assert len(g.players[1].hand) == before - 1            # the plain defense came and went; ONE card discarded


def test_a_tie_in_defense_is_won_by_jill_and_the_rival_discards_two(bprd, monkeypatch):
    g = mk(bprd, turn=1, gadget=0)
    jill, h = pair(g, "jill", "hellboy")
    fill_rival_hand(g)
    seen = record_after_results(monkeypatch)
    before = len(g.players[1].hand)
    res = defend_tied(g, jill, h, give(g, 0, "Caught Red-Handed"))
    assert res.atk_value == res.def_value and not res.attacker_won and jill.hp == jill.max_hp
    assert (0, "won") in seen and (0, "lost") not in seen
    assert len(g.players[1].hand) == before - 2


def test_no_card_against_her_counts_as_value_zero_for_both_gadgets(bprd):
    """Iván, 2026-11-08: a missing card is worth 0 in every gadget comparison: the Tonic fires, the Blaster does not."""
    g = mk(bprd, gadget=TONIC)
    jill, h = pair(g, "jill", "hellboy")
    jill.hp = 8
    g.attack(jill, h, give(g, 0, "Laser Pen"), None)
    assert jill.hp == 9
    g = mk(bprd, gadget=HYPNORAY)
    jill, h = pair(g, "jill", "hellboy")
    on_top(g, 1, "Second Shot")
    res = g.attack(jill, h, give(g, 0, "Laser Pen"), None)
    assert res.atk_value == 2 and g.players[0].known.top_of_deck == []
