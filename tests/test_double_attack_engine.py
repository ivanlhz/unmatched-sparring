"""DOUBLE ATTACK in the engine (Ivan's rules of 20/11/2026, docs/combat-flow.md "Double attack"), on a stub card: Hellboy's
Horseshoes And Hand Grenades (attack 2) with `after: [second_attack 3]` patched in. Bigfoot defends (Feint, Skirmish, a plain
defense); both players play the attacker's seat.

1. the first part is a normal combat; 2. the second attack is against the same defender and may be defended with a new card;
3. it is an AFTER effect: Feint (or any cancel) stops it; 4. a Skirmish move during the first combat does not stop it, even
out of reach; 5. the defender's AFTER of the first combat resolves before it."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.combat_flow import CombatFlow
from sparring.effects.model import load_effects
from sparring.state import Game
from test_bigfoot_effects import Answers, pick
from test_effects_combat import pair

TITLE = "Horseshoes And Hand Grenades"
SECOND = 3


@pytest.fixture
def double(monkeypatch):
    """The stub: the attack's AFTER is a second attack worth 3, whoever plays it."""
    card = load_effects("hellboy").card(TITLE)
    monkeypatch.setitem(card.moments, "after", [{"op": "second_attack", "amount": SECOND}])


def mk(bprd, attacker_seat=1):
    """Bigfoot defends; Hellboy attacks from `attacker_seat` (the bot or the human seat: the engine must not care)."""
    ctl = {0: Answers(), 1: Answers()}
    heroes = ("bigfoot", "hellboy") if attacker_seat == 1 else ("hellboy", "bigfoot")
    g = Game.new(bprd, 3, controllers=ctl, heroes=heroes, bot_player=0)
    g.turn, g.turn_no = attacker_seat, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.dsl_heroes = {"bigfoot", "hellboy"}
    defender = 1 - attacker_seat
    att, tgt = pair(g, "hellboy", "bigfoot")
    return g, att, tgt, attacker_seat, defender


@pytest.mark.parametrize("seat", (0, 1))
def test_undefended_second_attack_hits_the_same_defender_after_the_first(bprd, double, seat):
    g, hellboy, bigfoot, a, d = mk(bprd, seat)
    hp = bigfoot.hp
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), None)
    assert res.damage == 2 and res.second is not None
    assert res.second.damage == res.second.atk_value == SECOND
    assert bigfoot.hp == hp - 2 - SECOND
    assert any(f"({SECOND})" in part for part in res.second.atk_parts)


@pytest.mark.parametrize("seat", (0, 1))
def test_the_defender_may_defend_the_second_attack_with_a_new_card(bprd, double, seat):
    g, hellboy, bigfoot, a, d = mk(bprd, seat)
    pure = give(g, d, "It's Just Your Imagination")       # defense 3: stops the 3
    g.controllers[d].choose_second_defense = lambda game, att, tgt, value, card: pure
    hp = bigfoot.hp
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), None)
    assert res.second.def_card is pure and res.second.damage == 0 and pure not in g.players[d].hand
    assert pure in g.players[d].discard and bigfoot.hp == hp - 2


def test_without_a_card_to_defend_with_the_second_attack_lands_unopposed(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), None)
    assert res.second.def_card is None and res.second.damage == SECOND


def test_the_attacker_card_is_not_taken_from_the_hand_twice_and_no_action_is_spent(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    g.actions_left = 2
    g.attack(hellboy, bigfoot, give(g, a, TITLE), None)
    assert g.actions_left == 1, "one attack action for the whole card"
    assert sum(c.title == TITLE for c in g.players[a].discard) == 1


# ---------------------------------------------------------------- rule 3: cancelling stops it

def test_feint_stops_the_second_attack(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    hp = bigfoot.hp
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), give(g, d, "Feint"))
    assert res.second is None and bigfoot.hp == hp, "Feint cancelled the card: no first damage either (2 vs 2)"
    assert res.cancelled == {"atk"}


def test_a_cancel_of_only_the_after_effects_stops_it_too(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    flow = CombatFlow(g, hellboy, bigfoot, give(g, a, TITLE), None)
    while flow.phase.value != "during":
        flow.step()
    flow.ctx.cancelled_after.add("atk")
    flow.run()
    assert not flow.second_attack and not flow.second_due


def test_the_second_attack_is_not_played_once_the_first_ended_the_game(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    bigfoot.hp = 1
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), None)
    assert res.second is None and g.winner == a


def test_a_sidekick_defeated_by_the_first_part_is_not_attacked_again(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    jackalope = next(f for f in g.fighters.values() if f.owner == d and not f.hero)
    jackalope.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    jackalope.hp = 1
    res = g.attack(hellboy, jackalope, give(g, a, TITLE), None)
    assert not jackalope.alive and res.second is None


# ---------------------------------------------------------------- rules 4 and 5: Skirmish

def test_a_skirmish_that_takes_the_attacker_out_of_reach_does_not_stop_the_second_attack(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    far = pick(lambda s: g.board.distance(hellboy.pos, s) == 2 and not g.board.can_reach_target(s, bigfoot.pos, hellboy.ranged, hellboy.reach))
    g.controllers[d].queue = [["hellboy"], far]
    seen = {}
    real = g.controllers[d].choose_second_defense

    def second_defense(game, att, tgt, value, card):
        seen["reaches"] = game.can_attack(att, tgt, card)       # the Skirmish already resolved: where do they stand now?
        seen["second"] = value
        return real(game, att, tgt, value, card)

    g.controllers[d].choose_second_defense = second_defense
    hp = bigfoot.hp
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), give(g, d, "Skirmish"))
    assert res.second is not None and seen == {"reaches": False, "second": SECOND}, "the defender's AFTER moved first, then the second attack"
    assert res.second.damage == SECOND and bigfoot.hp == hp - SECOND


def test_a_skirmish_that_takes_the_defender_out_of_the_zone_does_not_stop_it_either(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    g.controllers[d].queue = [["bigfoot"], pick(lambda s: g.board.distance(bigfoot.pos, s) == 2)]
    start = bigfoot.pos
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), give(g, d, "Skirmish"))
    assert g.board.distance(start, bigfoot.pos) == 2 and res.second is not None and res.second.damage == SECOND


# ---------------------------------------------------------------- the flow itself

def test_the_second_attack_is_a_flow_of_its_own_that_survives_a_save(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    first = CombatFlow(g, hellboy, bigfoot, give(g, a, TITLE), None)
    assert first.run() is None and first.second_due
    assert CombatFlow.from_dict(g, first.to_dict()).second_attack == {"value": SECOND, "card": first.atk_card.card_id}
    second = first.second_flow(None)
    saved = second.to_dict()
    assert saved["second"] == SECOND
    again = CombatFlow.from_dict(g, saved)
    assert again.second == SECOND and again.atk_card is second.atk_card
    assert second.run() is None and second.result.damage == SECOND and not second.second_due
    assert not second.second_attack and "after:atk" not in second.runs, "the second part is damage only, not the card played again"
