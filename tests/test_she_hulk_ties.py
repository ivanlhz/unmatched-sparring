"""She-Hulk and a tied combat (Iván, 2026-11-07/08): the DEFENDER wins when its defense value is >= the attack value. Legalese,
Sensational and Green Energy read the engine's won/lost result, so on a tie they fire for the defender, never for the attacker."""
from __future__ import annotations

import pytest

from conftest import card, give
from test_effects_combat import pair
from test_she_hulk_effects import mk
from tie_helpers import plain_rival_card, record_after_results

TIE_CARDS = ("Legalese", "Sensational", "Green Energy")


def attack_tied(g, sh, foe, played):
    """She-Hulk attacks into a defense of exactly the same value."""
    return g.attack(sh, foe, played, plain_rival_card(g, played.value + g.attack_bonus(sh, foe), "defense"))


def defend_tied(g, sh, foe, played):
    """The rival attacks She-Hulk with exactly the value of the card she defends with."""
    return g.attack(foe, sh, plain_rival_card(g, played.value, "attack"), played)


@pytest.mark.parametrize("title", TIE_CARDS)
def test_a_tie_in_attack_is_lost_by_she_hulk(bprd, monkeypatch, title):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    seen = record_after_results(monkeypatch)
    res = attack_tied(g, sh, h, give(g, 0, title))
    assert res.atk_value == res.def_value and not res.attacker_won
    assert (0, "lost") in seen and (0, "won") not in seen


@pytest.mark.parametrize("title", ("Legalese", "Green Energy"))
def test_a_tie_in_defense_is_won_by_she_hulk(bprd, monkeypatch, title):
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    seen = record_after_results(monkeypatch)
    res = defend_tied(g, sh, h, give(g, 0, title))
    assert res.atk_value == res.def_value and not res.attacker_won and sh.hp == sh.max_hp
    assert (0, "won") in seen and (0, "lost") not in seen


def test_legalese_on_a_tie_in_attack_she_chooses(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    g.controllers[0].queue = [[0]]
    attack_tied(g, sh, h, give(g, 0, "Legalese"))
    assert [r.kind for r in g.controllers[0].requests] == ["effect"]
    assert not [r for r in g.controllers[1].requests if r.kind == "effect"]


def test_legalese_on_a_tie_in_defense_the_attacker_chooses(bprd):
    """She-Hulk won (defender on a tie): her OPPONENT makes the choice, not her."""
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    g.controllers[1].queue = [[0]]
    defend_tied(g, sh, h, give(g, 0, "Legalese"))
    assert [r.kind for r in g.controllers[1].requests if r.kind == "effect"] == ["effect"]
    assert not [r for r in g.controllers[0].requests if r.kind == "effect"]


def test_green_energy_hurts_the_fighters_next_to_her_after_a_tie_in_defense_only(bprd):
    for defending in (True, False):
        g = mk(bprd, turn=1 if defending else 0)
        sh, h = pair(g, "shehulk", "hellboy")
        lobster = g.fighters["lobster"]
        lobster.pos = next(s for s in sorted(g.board.adj[sh.pos]) if s != h.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
        played = give(g, 0, "Green Energy")
        (defend_tied if defending else attack_tied)(g, sh, h, played)
        assert (lobster.hp == lobster.max_hp - 1) is defending


def test_sensational_asks_for_nothing_after_a_tie_in_attack(bprd):
    """Sensational only attacks, so the tie is always in attack: she lost, nothing is asked."""
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    old = card(g, 0, "Green Energy")
    if old in g.players[0].deck:
        g.players[0].deck.remove(old)
    g.players[0].discard.append(old)
    g.controllers[0].queue = [[old.card_id]]
    attack_tied(g, sh, h, give(g, 0, "Sensational"))
    assert old in g.players[0].discard and g.controllers[0].queue == [[old.card_id]]
