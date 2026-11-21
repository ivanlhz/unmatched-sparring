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


# ---------------------------------------------------------------- the guards the first review found unproven

def _events(g, monkeypatch):
    seen = []
    real = type(g.fx).emit
    monkeypatch.setattr(type(g.fx), "emit", lambda self, name, *a, **kw: (seen.append(name), real(self, name, *a, **kw))[1])
    return seen


def test_the_combat_is_counted_once_for_the_events_that_count_combats_and_attacks(bprd, double, monkeypatch):
    g, hellboy, bigfoot, a, d = mk(bprd)
    seen = _events(g, monkeypatch)
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), None)
    assert res.second is not None
    assert seen.count("combat_lost") == 1 and seen.count("after_attack") == 1, "the second part is damage of the same card, not another attack"


def test_a_card_played_as_a_defense_records_no_second_attack(bprd, monkeypatch):
    skirmish = load_effects("bigfoot").card("Skirmish")
    monkeypatch.setitem(skirmish.moments, "after", [{"op": "second_attack", "amount": SECOND}])
    g, hellboy, bigfoot, a, d = mk(bprd)
    flow = CombatFlow(g, hellboy, bigfoot, give(g, a, "Service Pistol"), give(g, d, "Skirmish"))
    assert flow.run() is None and not flow.second_attack and not flow.second_due


def test_an_uncancelable_double_attack_card_keeps_its_second_part_against_a_feint(bprd, double, monkeypatch):
    import dataclasses
    from sparring.effects import modifiers
    cards = modifiers._cards_by_title()
    monkeypatch.setitem(cards, TITLE, dataclasses.replace(cards[TITLE], uncancelable=True))
    g, hellboy, bigfoot, a, d = mk(bprd)
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), give(g, d, "Feint"))
    assert res.cancelled == set() and res.second is not None and res.second.damage == SECOND


def test_a_real_cancel_of_only_the_after_effects_stops_the_second_attack(bprd, double, monkeypatch):
    monkeypatch.setitem(load_effects("bigfoot").card("Feint").moments, "immediately",
                        [{"op": "cancel_effects", "card": "opponent_card", "moments": ["after"]}])
    g, hellboy, bigfoot, a, d = mk(bprd)
    res = g.attack(hellboy, bigfoot, give(g, a, TITLE), give(g, d, "Feint"))
    assert res.cancelled_after == {"atk"} and res.second is None


def test_the_attacking_sidekick_defeated_by_the_defenders_after_leaves_no_second_attack(bprd, double, monkeypatch):
    monkeypatch.setitem(load_effects("bigfoot").card("It's Just Your Imagination").moments, "after",
                        [{"op": "damage", "target": "opposing", "amount": 99}])
    g, hellboy, bigfoot, a, d = mk(bprd)
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(g.board.adj[bigfoot.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    flow = CombatFlow(g, lobster, bigfoot, give(g, a, TITLE), give(g, d, "It's Just Your Imagination"))
    assert flow.run() is None
    assert not lobster.alive and g.winner is None and not flow.second_due, "the dead attacker's AFTER never recorded a second attack"


def test_a_fighter_that_falls_after_the_first_part_is_not_attacked_by_or_for_a_second_one(bprd, double):
    g, hellboy, bigfoot, a, d = mk(bprd)
    flow = CombatFlow(g, hellboy, bigfoot, give(g, a, TITLE), None)
    assert flow.run() is None and flow.second_due
    hellboy.hp = 0
    hellboy.alive = False
    assert not flow.second_due


def test_a_second_flow_stopped_at_the_defenders_boost_resumes_from_a_save(bprd, double):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("baba-yaga", "hellboy"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.dsl_heroes = {"baba-yaga", "hellboy"}
    hellboy, baba = pair(g, "hellboy", "baba")
    first = CombatFlow(g, hellboy, baba, give(g, 1, TITLE), None)
    assert first.run() is None and first.second_due
    out_of_time = give(g, 0, "Out Of Time")
    second = first.second_flow(out_of_time)
    wait = second.run()
    assert wait.choice.kind == "boost" and wait.choice.player == 0 and second.phase.value == "during"
    again = CombatFlow.from_dict(g, second.to_dict())
    assert again.second == SECOND and again.pending is not None and again.pending.kind == "boost"
    again.resume(None)
    assert again.run() is None and again.done and again.result.def_card is out_of_time


# ---------------------------------------------------------------- "won / lost the combat" reads the combat the card is in (Ivan 2026-11-20, D2)

WIN, LOSE = "Momentous Shift", "Regroup"      # defense 3 (beats the 2, ties the 3: wins both parts) / defense 1 (loses both)
DRAW_IF_WON = {WIN: 1, LOSE: 2}                        # cards drawn by each stub when its own combat is won (nothing when lost)


@pytest.fixture
def reads_won(monkeypatch):
    """Both defenders get the AFTER "if you won the combat, draw N cards" with a different N, so the hand says which card won what."""
    for title, n in DRAW_IF_WON.items():
        monkeypatch.setitem(load_effects("bigfoot").card(title).moments, "after", [
            {"op": "if", "condition": {"test": "combat_result", "result": "won"}, "then": [{"op": "draw", "player": "owner", "amount": n}]}])


def _play(g, hellboy, bigfoot, a, d, first, second):
    """Both parts through `g.attack`: `first` defends the first part, `second` the second (titles)."""
    g.controllers[d].choose_second_defense = lambda game, att, tgt, value, card: give(g, d, second)
    return g.attack(hellboy, bigfoot, give(g, a, TITLE), give(g, d, first))


@pytest.mark.parametrize("first, second, drawn", [(WIN, LOSE, DRAW_IF_WON[WIN]), (LOSE, WIN, DRAW_IF_WON[WIN])])
def test_the_first_part_card_reads_the_first_combat_only(bprd, double, reads_won, first, second, drawn):
    """Wins the first and loses the second: the first card's AFTER fires. Loses the first and wins the second: it does not."""
    g, hellboy, bigfoot, a, d = mk(bprd)
    res = _play(g, hellboy, bigfoot, a, d, first, second)
    first_won = first == WIN
    assert res.damage == (0 if first_won else 1) and res.second.damage == (SECOND - 1 if first_won else 0)
    assert len(g.players[d].hand) == drawn, "only the card that won ITS OWN combat drew"


@pytest.mark.parametrize("first, second", [(WIN, LOSE), (LOSE, WIN), (WIN, WIN), (LOSE, LOSE)])
def test_each_card_reads_its_own_combat_never_both(bprd, double, reads_won, first, second):
    """The defender's hand is the sum of what each card draws for ITS combat: a card never also reads the other part."""
    g, hellboy, bigfoot, a, d = mk(bprd)
    _play(g, hellboy, bigfoot, a, d, first, second)
    expected = (DRAW_IF_WON[first] if first == WIN else 0) + (DRAW_IF_WON[second] if second == WIN else 0)
    assert len(g.players[d].hand) == expected


def test_the_second_part_card_reads_the_second_combat_only(bprd, double, reads_won):
    """The second card's result is the second combat's, whatever the first one was."""
    for first, second, won in ((WIN, LOSE, False), (LOSE, WIN, True)):
        g, hellboy, bigfoot, a, d = mk(bprd)
        flow = CombatFlow(g, hellboy, bigfoot, give(g, a, TITLE), give(g, d, first))
        assert flow.run() is None and flow.second_due
        before = len(g.players[d].hand)
        sec = flow.second_flow(give(g, d, second))
        assert sec.run() is None
        assert sec.runs["after:def"].ctx.combat_result == ("won" if won else "lost")
        assert len(g.players[d].hand) - before == (DRAW_IF_WON[second] if won else 0)


@pytest.mark.parametrize("first, second", [(WIN, LOSE), (LOSE, WIN)])
def test_the_first_part_card_is_not_evaluated_again_with_the_second_combat(bprd, double, reads_won, first, second):
    g, hellboy, bigfoot, a, d = mk(bprd)
    flow = CombatFlow(g, hellboy, bigfoot, give(g, a, TITLE), give(g, d, first))
    assert flow.run() is None
    result, size = flow.result.attacker_won, len(g.players[d].hand)
    first_ctx = flow.runs["after:def"].ctx
    verdict = first_ctx.combat_result
    assert verdict == ("won" if first == WIN else "lost")
    sec = flow.second_flow(give(g, d, second))
    assert sec.run() is None
    assert flow.result.attacker_won == result and flow.runs["after:def"].ctx is first_ctx and first_ctx.combat_result == verdict
    own_draw = DRAW_IF_WON[second] if second == WIN else 0
    assert len(g.players[d].hand) == size + own_draw, "the hand grew only by what the second card drew: the first card did not fire again"
    assert sec.runs["after:def"] is not flow.runs["after:def"]
