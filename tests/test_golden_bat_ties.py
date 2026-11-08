"""Golden Bat and a tied combat (Iván, 2026-11-07/08): the DEFENDER wins when its defense value is >= the attack value, so every
"if you won the combat" of his cards reads the engine's result and fires for the defender on a tie."""
from __future__ import annotations

import pytest

from conftest import give
from test_bigfoot_effects import start_turn
from test_effects_combat import pair
from test_golden_bat_effects import mk
from tie_helpers import plain_rival_card, record_after_results

TIE_CARDS = ("A Punch to Shake the Earth", "Skirmish", "Insight of the Ancients")


def attack_tied(g, b, foe, played):
    """Golden Bat attacks (no +2: the Maneuver was taken) into a defense of exactly the same value."""
    start_turn(g)
    g.maneuver(0, {})
    return g.attack(b, foe, played, plain_rival_card(g, played.value + g.attack_bonus(b, foe), "defense"))


def defend_tied(g, b, foe, played):
    """The rival attacks Golden Bat with exactly the value of the card he defends with."""
    return g.attack(foe, b, plain_rival_card(g, played.value, "attack"), played)


@pytest.mark.parametrize("title", TIE_CARDS)
def test_a_tie_in_attack_is_lost_by_golden_bat(bprd, monkeypatch, title):
    g = mk(bprd, "hellboy")
    b, h = pair(g, "bat", "hellboy")
    seen = record_after_results(monkeypatch)
    res = attack_tied(g, b, h, give(g, 0, title))
    assert res.atk_value == res.def_value and not res.attacker_won and res.damage == 0
    assert (0, "lost") in seen and (0, "won") not in seen


@pytest.mark.parametrize("title", ("Skirmish", "Insight of the Ancients"))
def test_a_tie_in_defense_is_won_by_golden_bat(bprd, monkeypatch, title):
    g = mk(bprd, "hellboy", turn=1)
    b, h = pair(g, "bat", "hellboy")
    seen = record_after_results(monkeypatch)
    res = defend_tied(g, b, h, give(g, 0, title))
    assert res.atk_value == res.def_value and not res.attacker_won and b.hp == b.max_hp
    assert (0, "won") in seen and (0, "lost") not in seen


def test_the_punch_deals_one_on_a_tie_in_attack(bprd):
    g = mk(bprd, "hellboy")
    b, h = pair(g, "bat", "hellboy")
    attack_tied(g, b, h, give(g, 0, "A Punch to Shake the Earth"))
    assert h.hp == h.max_hp - 1


@pytest.mark.parametrize("attacking", (True, False))
def test_insight_returns_a_card_after_a_tie_in_defense_but_not_in_attack(bprd, attacking):
    g = mk(bprd, "hellboy", turn=0 if attacking else 1)
    b, h = pair(g, "bat", "hellboy")
    pile = [c for c in g.players[0].deck if c.title in ("Super Strength", "Imposing Presence")][:2]
    for c in pile:
        g.players[0].deck.remove(c)
        g.players[0].discard.append(c)
    played = give(g, 0, "Insight of the Ancients")
    (attack_tied if attacking else defend_tied)(g, b, h, played)
    assert any(c in g.players[0].hand for c in pile) is (not attacking)


@pytest.mark.parametrize("attacking", (True, False))
def test_skirmish_asks_nothing_after_a_tie_in_attack_and_asks_after_a_tie_in_defense(bprd, attacking):
    g = mk(bprd, "hellboy", turn=0 if attacking else 1)
    b, h = pair(g, "bat", "hellboy")
    asked = []
    g.controllers[0].queue = [lambda req: asked.append(req) or [req.options[0]]] * 3
    (attack_tied if attacking else defend_tied)(g, b, h, give(g, 0, "Skirmish"))
    assert bool(asked) is (not attacking)
