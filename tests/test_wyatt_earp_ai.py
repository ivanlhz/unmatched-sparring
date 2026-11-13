"""What the AI does with Wyatt Earp (docs/heroes/wyatt-earp.md): the SHOWDOWN choice by what each effect brings, the free actions to attack in
the heuristic and in the search (only attacks may spend them, and a free action nothing can use is lost, not looped on), Bring 'Em To
Justice priced as the defense it is, You Die First pulling the rival it can strike, Better Swear Me In burying only a card worth burying.
Verified with the search AI as well as with the heuristic (`make_bot_ai({"ai": "ismcts"})`), the one the live games use."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_wyatt
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import CARD_VALUE, MedusaAI, Model
from sparring.search.controller import make_bot_ai
from test_effects_combat import pair, put_adjacent
from test_wyatt_earp_effects import ATTACK, DRAW, MOVE, arena, half_shell, mk, win

STAND_TITLE = "You Just Gonna Stand There And Bleed?"


def bot(g, kind="heuristic"):
    ai = MedusaAI(0) if kind == "heuristic" else make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": 1})
    g.controllers = {0: ai, 1: g.controllers[1]}
    return ai


# ---------------------------------------------------------------- the SHOWDOWN choice

def test_with_an_attack_in_the_hand_the_free_action_beats_the_draw(bprd):
    g = mk(bprd)
    arena(g)
    give(g, 0, STAND_TITLE)                                      # a 5 against a defenseless Hellboy: a free swing is worth far more than a card
    ai = bot(g)
    assert ai_wyatt.pick_showdown(ai, g, 0, [DRAW, ATTACK, MOVE], "wyatt") == ATTACK


def test_without_an_attack_to_make_the_draw_is_taken(bprd):
    g = mk(bprd)
    arena(g)
    ai = bot(g)
    assert ai_wyatt.pick_showdown(ai, g, 0, [DRAW, ATTACK, MOVE], "wyatt") == DRAW


def test_a_weak_attack_is_not_worth_a_free_action_over_a_card(bprd):
    g = mk(bprd, "leonardo")
    arena(g, target="leonardo")
    give(g, 0, "Fan The Hammer")                                 # a 1 against Leonardo's defenses (5 at best): nothing to gain
    ai = bot(g)
    assert ai_wyatt.pick_showdown(ai, g, 0, [DRAW, ATTACK, MOVE], "wyatt") == DRAW


def test_the_draw_is_worth_less_than_nothing_at_the_hand_limit_when_no_action_is_left(bprd):
    g = mk(bprd)
    arena(g)
    for _ in range(g.hand_cap(0)):
        g.players[0].hand.append(g.players[0].deck.pop(0))
    g.actions_left = 0
    ai = bot(g)
    assert ai_wyatt.pick_showdown(ai, g, 0, [DRAW, MOVE], "wyatt") == MOVE      # the card would only be discarded by the limit
    assert ai_wyatt.pick_showdown(ai, g, 0, [DRAW], "wyatt") == DRAW           # the only option left is taken


def test_the_effect_ai_answers_the_showdown_request_with_pick_showdown(bprd, monkeypatch):
    g = mk(bprd)
    arena(g)
    give(g, 0, STAND_TITLE)
    g.controllers = {0: MedusaAI(0), 1: g.controllers[1]}
    calls = []
    real = ai_wyatt.pick_showdown
    monkeypatch.setattr(ai_wyatt, "pick_showdown", lambda ai, game, me, options, attacker: calls.append((options, attacker)) or real(ai, game, me, options, attacker))
    win(g)
    assert calls == [([0, 1, 2], "wyatt")]
    assert g.free_attacks == [None] or g.fx.counter_value(0, "showdown_draw", 0) == 1      # the best effect was taken
    assert ai_wyatt.rollout_showdown(g, 0, [DRAW, ATTACK, MOVE], greedy=False) == DRAW
    assert ai_wyatt.rollout_showdown(g, 0, [ATTACK], greedy=True) == ATTACK                  # never an empty answer


def test_the_rollouts_take_the_free_action_only_when_the_hand_can_use_it(bprd):
    g = mk(bprd)
    arena(g)
    assert ai_wyatt.rollout_showdown(g, 0, [DRAW, ATTACK, MOVE], greedy=True) == DRAW
    give(g, 0, STAND_TITLE)
    assert ai_wyatt.rollout_showdown(g, 0, [DRAW, ATTACK, MOVE], greedy=True) == ATTACK
    assert ai_wyatt.rollout_showdown(g, 0, [DRAW, ATTACK, MOVE], greedy=False) == DRAW


def test_the_move_is_chosen_when_it_is_the_only_effect_that_does_something(bprd):
    g = mk(bprd)
    arena(g)
    g.players[0].deck.clear()                                    # no card to draw, none to attack with
    ai = bot(g)
    assert ai_wyatt.pick_showdown(ai, g, 0, [DRAW, ATTACK, MOVE], "wyatt") == MOVE


def test_showdown_edge_counts_only_while_an_effect_is_open(bprd):
    g = mk(bprd)
    assert ai_wyatt.showdown_edge(g, 0, 1.0, CARD_VALUE, None) > 0
    assert ai_wyatt.showdown_edge(g, 0, 0.5, CARD_VALUE, 0) == 0
    for name in ai_wyatt.COUNTERS:
        g.fx.set_counter(0, name, 1)
    assert ai_wyatt.showdown_edge(g, 0, 1.0, CARD_VALUE, None) == 0
    assert ai_wyatt.showdown_edge(g, 1, 1.0, CARD_VALUE, None) == 0          # Hellboy has no SHOWDOWN


# ---------------------------------------------------------------- the free actions, in the heuristic and in the search

@pytest.mark.parametrize("kind", ["heuristic", "ismcts"])
def test_with_only_a_free_action_the_bot_attacks_and_never_maneuvers(bprd, kind):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    give(g, 0, STAND_TITLE)
    give(g, 0, "Second Shot")
    g.actions_left, g.free_attacks = 1, [None]
    g.fx.set_counter(0, "showdown_attack", 1)                    # SHOWDOWN cannot hand the free action back
    ai = bot(g, kind)
    act = ai.plan(g)
    assert act.kind == "attack" and act.target in ("hellboy", "lobster")
    ai.execute(g, act)
    assert g.actions_left == 0 and g.free_attacks == []


@pytest.mark.parametrize("kind", ["heuristic", "ismcts"])
def test_a_free_action_nothing_can_use_ends_the_turn_instead_of_looping(bprd, kind):
    g = mk(bprd)
    arena(g)
    g.actions_left, g.free_attacks = 1, [None]           # an empty hand
    ai = bot(g, kind)
    ai.take_turn(g)
    assert (g.actions_left, g.free_attacks) == (0, [])


@pytest.mark.parametrize("kind", ["heuristic", "ismcts"])
def test_a_free_action_bound_to_a_fighter_is_spent_on_that_fighter(bprd, kind):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    lobster = g.fighters["lobster"]
    put_adjacent(g, "lobster", "wyatt")
    give(g, 0, STAND_TITLE)
    g.actions_left, g.free_attacks = 1, ["lobster"]
    ai = bot(g, kind)
    act = ai.plan(g)
    assert act.kind == "attack" and act.target == "lobster"
    ai.execute(g, act)
    assert g.actions_left == 0 and not lobster.alive or lobster.hp < lobster.max_hp


@pytest.mark.parametrize("kind", ["heuristic", "ismcts"])
def test_full_turns_of_the_bot_never_exceed_the_chain_the_three_effects_allow(bprd, kind, monkeypatch):
    """Whatever the bot chooses, SHOWDOWN ends after three effects: with a hand full of attacks the bot makes at most the two printed
    actions, one free action, and the free actions its schemes bring (each paid for with the scheme's own action)."""
    g = mk(bprd, "leonardo", seed=5)
    arena(g, target="leonardo", hp=200)
    for nth in range(3):
        give(g, 0, STAND_TITLE, nth)
    give(g, 0, "Second Shot", 0)
    give(g, 0, "Second Shot", 1)
    ai = bot(g, kind)
    attacks = []
    real = type(g).use_action
    monkeypatch.setattr(type(g), "use_action", lambda self, attack_on=None: (attacks.append(attack_on) if attack_on and self is g else None, real(self, attack_on))[1])
    ai.take_turn(g)
    assert g.actions_left == 0 and 2 <= len(attacks) <= 3 and g.winner is None


# ---------------------------------------------------------------- the cards

def test_the_bot_defends_with_bring_em_to_justice_against_a_real_blow(bprd):
    g = mk(bprd, turn=1)
    ai = bot(g)
    pair(g, "wyatt", "hellboy")
    justice = give(g, 0, "Bring 'Em To Justice")
    assert ai.choose_defense(g, g.fighters["hellboy"], g.fighters["wyatt"]) is justice
    assert ai_wyatt.justice_value(ai.rival_average_boost(g)) > 2          # twice an average BOOST, not its printed 0


def test_after_values_are_priced_from_the_board(bprd):
    g = mk(bprd)
    arena(g, "doc")
    by = {c.title: c for c in g.players[0].full_set}
    value = lambda title, **kw: ai_wyatt.after_value(g, 0, by[title], kw.pop("p_win", 1.0), 1.0, CARD_VALUE, **kw)
    assert value(ai_wyatt.DAISY) == pytest.approx(2 * CARD_VALUE)
    assert value(ai_wyatt.DAISY, room=1) == pytest.approx(CARD_VALUE)                    # one card fits
    assert value(ai_wyatt.MARSHAL, defending=True) == pytest.approx(CARD_VALUE)
    g.players[1].hand.append(g.players[1].deck.pop(0))
    assert value(ai_wyatt.MARSHAL) == ai_wyatt.STRIP_AFTER                               # the rival has a card to lose
    g.players[1].hand.clear()
    assert value(ai_wyatt.MARSHAL) == 0.0
    assert value(ai_wyatt.HUCKLEBERRY, p_win=0.5) == pytest.approx(0.5)
    assert value(ai_wyatt.FAN, p_kill=0.5) == pytest.approx(0.5 * CARD_VALUE)
    assert value(ai_wyatt.TWO_GUNS, defending=True) == 0.0
    assert value("You Just Gonna Stand There And Bleed?") == 0.0
    other = ai_wyatt.after_value(g, 1, by[ai_wyatt.DAISY], 1.0, 1.0, CARD_VALUE)          # a card read for the other player's hero is still its title's
    assert other == pytest.approx(2 * CARD_VALUE)


def test_swear_me_in_buries_a_card_worth_more_than_the_average_and_leaves_a_weak_one(bprd):
    g = mk(bprd)
    rival = g.players[1]
    strong = max(rival.full_set, key=lambda c: (c.value or 0) + c.boost)
    weak = min(rival.full_set, key=lambda c: (c.value or 0) + c.boost)
    assert ai_wyatt.bury_rival(g, 0, strong.card_id) is True
    assert ai_wyatt.bury_rival(g, 0, weak.card_id) is False


def test_you_die_first_pulls_the_rival_the_hand_can_strike(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    lobster = g.fighters["lobster"]
    far = sorted((s for s in g.board.spaces if g.board.distance(wyatt.pos, s) >= 6 and all(f.pos != s for f in g.fighters.values() if f.alive)), reverse=True)
    lobster.pos = far[0]                                          # out of reach, with Hellboy in reach already
    give(g, 0, STAND_TITLE)
    ai = bot(g)
    picked = ai_wyatt.die_first_fighter(ai, g, 0, [hellboy, lobster])
    assert picked == "hellboy"
    dest = ai_wyatt.die_first_dest(ai, g, 0, hellboy, sorted(g.legal_moves(hellboy, 1)), may_stay=True)
    assert dest == [] or dest[0] in g.legal_moves(hellboy, 1)


def test_the_search_plays_you_die_first_and_the_free_attack_binds_to_the_fighter(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    give(g, 0, "You Die First")
    give(g, 0, STAND_TITLE)
    ai = bot(g, "ismcts")
    before = g.actions_left
    ai.take_turn(g)
    assert g.actions_left == 0 and g.winner is None and before == 2


def test_the_effect_ai_answers_the_requests_of_you_die_first_without_a_fallback(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    give(g, 0, STAND_TITLE)
    give(g, 0, "You Die First")
    g.controllers = {0: MedusaAI(0), 1: g.controllers[1]}
    g.play_scheme(0, wyatt, next(c for c in g.players[0].hand if c.title == "You Die First"))
    assert g.free_attacks in (["hellboy"], ["lobster"])
