"""Tomoe Gozen and a tied combat (Iván, 2026-11-07/08): the DEFENDER wins when its defense value is >= the attack value. "If you won"
(Skirmish) and "if you lost" (Confront Any Demon or God) read the engine's result: on a tie she wins defending and loses attacking."""
from __future__ import annotations

import pytest

from conftest import give
from test_effects_combat import pair
from test_tomoe_gozen_effects import mk
from tie_helpers import plain_rival_card, record_after_results

TIE_CARDS = ("Confront Any Demon or God", "Skirmish")


def attack_tied(g, t, foe, played):
    return g.attack(t, foe, played, plain_rival_card(g, played.value + g.attack_bonus(t, foe), "defense"))


def defend_tied(g, t, foe, played):
    return g.attack(foe, t, plain_rival_card(g, played.value, "attack"), played)


def setup(bprd, defending):
    g = mk(bprd, turn=1 if defending else 0)
    t, h = pair(g, "tomoe", "hellboy")
    for _ in range(3):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    asked = []
    g.controllers[0].queue = [lambda req: asked.append(req) or [req.options[0]]] * 4
    return g, t, h, asked


@pytest.mark.parametrize("title", TIE_CARDS)
def test_a_tie_in_attack_is_lost_by_tomoe(bprd, monkeypatch, title):
    g, t, h, _ = setup(bprd, defending=False)
    seen = record_after_results(monkeypatch)
    res = attack_tied(g, t, h, give(g, 0, title))
    assert res.atk_value == res.def_value and not res.attacker_won
    assert (0, "lost") in seen and (0, "won") not in seen


@pytest.mark.parametrize("title", TIE_CARDS)
def test_a_tie_in_defense_is_won_by_tomoe(bprd, monkeypatch, title):
    g, t, h, _ = setup(bprd, defending=True)
    seen = record_after_results(monkeypatch)
    res = defend_tied(g, t, h, give(g, 0, title))
    assert res.atk_value == res.def_value and not res.attacker_won and t.hp == t.max_hp
    assert (0, "won") in seen and (0, "lost") not in seen


@pytest.mark.parametrize("defending", (False, True))
def test_confront_looks_at_the_rival_hand_only_after_a_loss(bprd, defending):
    g, t, h, _ = setup(bprd, defending)
    hand = len(g.players[1].hand)
    played = give(g, 0, "Confront Any Demon or God")
    (defend_tied if defending else attack_tied)(g, t, h, played)
    lost = not defending
    assert len(g.players[1].hand) == hand - (1 if lost else 0)        # the rival's plain card came in and went out; a loss strips one more


@pytest.mark.parametrize("defending", (False, True))
def test_skirmish_moves_a_fighter_only_after_a_win(bprd, defending):
    g, t, h, asked = setup(bprd, defending)
    start = (t.pos, h.pos)
    (defend_tied if defending else attack_tied)(g, t, h, give(g, 0, "Skirmish"))
    assert any(r.kind in ("fighter", "space") for r in asked) is defending
    assert defending or (t.pos, h.pos) == start
