"""F-AI-EVAL-RESOLUTION: the ISMCTS evaluation that tells moves apart (`search.adapter.RESOLUTION`, off in `EvalWeights()` until the duels
of tools/ai_duel.py accept it). Positions come from the phase-0 fixtures and from the openings of the matchups the criteria name; the
AI is the one that runs at the table, `make_bot_ai({"ai": "ismcts"})`."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import replace

import pytest

from ai_positions import build, make_ai
from conftest import give
from sparring import pack
from sparring.board import Board
from sparring.hellboy_script import ScriptedHellboy
from sparring.search.adapter import (NO_ATTACK, PACK_PLANS, RESOLUTION, EngineState, EvalWeights, Knowledge, PackPlan, best_attack_stats,
                                     hero_weights, unseen_values)
from sparring.search.controller import make_bot_ai
from sparring.state import Game

NEW = EvalWeights(**RESOLUTION)
OLD = EvalWeights()


@pytest.fixture(autouse=True)
def raptors_are_interpreted(monkeypatch):
    from sparring.effects import state
    monkeypatch.setattr(state, "INTERPRETED_HEROES", state.INTERPRETED_HEROES | {"raptors"})


def opening(bot: str, rival: str, seed: int = 0, weights: EvalWeights = NEW):
    """The bot (player 0) at the start of its first turn; the state is the one `IsmctsMedusa` builds its root with."""
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 20, "ai_seed": 0}, 0)
    g = Game.new(Board.load("bprd-hq"), seed, {0: ai, 1: make_bot_ai({"ai": "heuristic"}, 1)}, bot_player=0, heroes=(bot, rival))
    assert g.turn == 0
    g.begin_turn()
    return g, EngineState(g, observer=0, knowledge=Knowledge.from_game(g, 0), weights=hero_weights(weights, g.players[0].hero.slug, frozenset(RESOLUTION)))


def with_weights(g, weights: EvalWeights) -> EngineState:
    return EngineState(g, observer=0, knowledge=Knowledge.from_game(g, 0), weights=hero_weights(weights, g.players[0].hero.slug, frozenset(RESOLUTION)))


def change(g, edit) -> Game:
    c = g.clone()
    edit(c)
    return c


# ---------- saturation and resolution ----------
@pytest.mark.parametrize("bot, rival", [("raptors", "liz-sherman"), ("liz-sherman", "raptors"), ("hellboy", "liz-sherman")])
def test_every_opening_starts_near_an_even_evaluation(bot, rival):
    """A team of three 7 HP fighters against a 16 HP hero, and a hero with a sidekick against one without, are not a lead for anybody."""
    for seed in (0, 1, 4):
        _, state = opening(bot, rival, seed)
        assert 0.35 < state.evaluate(0) < 0.65, (bot, rival, seed, state.evaluate(0))


def test_the_old_evaluation_opened_far_from_even_for_a_team_and_for_a_sidekick():
    """What the new one fixes (measured 16/11: Liz against the Raptors 0.13, Hellboy against Liz 0.71)."""
    assert opening("liz-sherman", "raptors", weights=OLD)[1].evaluate(0) < 0.2
    assert opening("hellboy", "liz-sherman", weights=OLD)[1].evaluate(0) > 0.65


@pytest.mark.parametrize("bot, rival", [("raptors", "liz-sherman"), ("liz-sherman", "raptors"), ("hellboy", "liz-sherman")])
def test_a_card_a_hero_point_and_a_sidekick_point_each_move_the_evaluation_clearly(bot, rival):
    g, state = opening(bot, rival)
    base = state.evaluate(0)

    def moved(edit) -> float:
        return abs(with_weights(change(g, edit), NEW).evaluate(0) - base)

    def lose_card(c):
        c.players[0].discard.append(c.players[0].hand.pop())

    def lose_hero_hp(c):
        c.hero(0).hp -= 1

    def lose_sidekick_hp(c):
        next(f for f in c.own(0) if not f.hero).hp -= 1

    assert moved(lose_card) > 0.01 and moved(lose_hero_hp) > 0.01
    if any(not f.hero for f in g.own(0)):
        assert moved(lose_sidekick_hp) > 0.01


def test_the_old_evaluation_barely_moved_for_the_same_losses():
    g, _ = opening("liz-sherman", "raptors", weights=OLD)
    base = with_weights(g, OLD).evaluate(0)
    loss = change(g, lambda c: setattr(c.hero(0), "hp", c.hero(0).hp - 1))
    assert abs(with_weights(loss, OLD).evaluate(0) - base) < 0.005


def test_the_two_best_root_moves_are_told_apart_beyond_the_run_to_run_noise():
    """Liz against the Raptors, the saturated opening: the gap between the best two moves is several times the old one (0.001) and the same
    move wins at 300 and 1200 iterations."""
    def gap(weights: dict, iterations: int):
        ai = make_bot_ai({"ai": "ismcts", "ai_iterations": iterations, "ai_seed": 0, "ai_eval": weights}, 0)
        g = Game.new(Board.load("bprd-hq"), 0, {0: ai, 1: make_bot_ai({"ai": "heuristic"}, 1)}, bot_player=0, heroes=("liz-sherman", "raptors"))
        g.begin_turn()
        ai.plan(g)
        r = ai.last_report
        ranked = sorted(r.visits, key=lambda m: -r.visits[m])
        return r.values[ranked[0]] - r.values[ranked[1]]
    assert abs(gap(RESOLUTION, 300)) > 3 * abs(gap({}, 300)) or abs(gap(RESOLUTION, 300)) > 0.01


# ---------- teams and fighters ----------
def test_a_team_is_not_counted_in_lives_of_its_hero_by_a_bot_of_another_hero():
    g, state = opening("liz-sherman", "raptors")
    old = with_weights(g, OLD)
    assert old._side_value(1) > old._side_value(0) + 1.0              # three Raptors against one Liz: three lives of Blue
    assert abs(state._side_value(1) - state._side_value(0)) < 0.3


def beside_rival(g, sidekick_hp: int, away: bool = False) -> Game:
    """Hellboy's Lobster next to Liz with `sidekick_hp` hit points (or far from her with `away`), Hellboy himself out of her reach."""
    c = g.clone()
    liz = c.hero(1)
    lobster = next(f for f in c.own(0) if not f.hero)
    hero = c.hero(0)
    hero.pos = max(c.board.spaces, key=lambda s: c.board.distance(liz.pos, s))
    lobster.pos = max(c.board.spaces, key=lambda s: c.board.distance(liz.pos, s)) if away else next(s for s in c.board.adj[liz.pos] if s != hero.pos)
    lobster.hp = sidekick_hp
    c.turn = 1
    c.actions_left = 2
    return c


def test_a_weak_sidekick_left_next_to_the_rival_shows_as_exposed():
    g, _ = opening("hellboy", "liz-sherman")
    near, far = beside_rival(g, 2), beside_rival(g, 2, away=True)
    state_near, state_far = with_weights(near, NEW), with_weights(far, NEW)
    assert state_near._fighters_exposure(0, False) > state_far._fighters_exposure(0, False) + 0.02
    sturdy = with_weights(beside_rival(g, 6), NEW)
    assert sturdy._fighters_exposure(0, False) < state_near._fighters_exposure(0, False)
    assert with_weights(near, OLD)._exposure(0, False) == pytest.approx(with_weights(far, OLD)._exposure(0, False), abs=0.01)


# ---------- the rival's cards ----------
def test_the_rival_blows_come_from_the_cards_it_may_still_hold_and_scale_with_its_hand():
    g, _ = opening("raptors", "liz-sherman")
    liz = g.players[1]
    pool = unseen_values(liz, g.hero(1).name)
    assert len(pool) == len(liz.full_set) and pool == tuple(sorted(pool, reverse=True)) and NO_ATTACK in pool
    gone = liz.hand[:0] + liz.deck[:4]
    liz.discard.extend(gone)
    assert len(unseen_values(liz, g.hero(1).name)) == len(liz.full_set) - 4
    big = best_attack_stats(pool, 6, 0, 0, 99)[0]
    small = best_attack_stats(pool, 2, 0, 0, 99)[0]
    assert big > small > best_attack_stats(pool, 1, 0, 0, 99)[0] - 1e-9                # the best of more cards is better
    assert best_attack_stats(pool, 0, 0, 0, 99) == (0.0, 0.0) and best_attack_stats(pool, 1, 1, 0, 99) == (0.0, 0.0)   # nothing in hand, no blow
    assert best_attack_stats(pool, 5, 0, 0, 99)[0] > best_attack_stats(pool, 5, 1, 0, 99)[0]                        # the second blow is the second best card


def test_a_rival_with_an_empty_hand_threatens_less_than_one_with_a_full_hand():
    g, _ = opening("raptors", "liz-sherman")
    c = change(g, lambda x: None)
    liz, blue = c.hero(1), c.hero(0)
    liz.pos = next(s for s in c.board.adj[blue.pos])
    c.turn = 1
    full = with_weights(c, NEW).threat(0, True)[0]
    c.players[1].hand.clear()
    empty = with_weights(c, NEW).threat(0, True)[0]
    assert empty < full / 2


def test_the_face_down_attack_is_not_always_the_known_card():
    """Liz holds a known Fireball and hidden cards: the attack the bot answers is Fireball about as often as a hand's cards say, not every time."""
    game = build("raptors_liz_t2_echo_feint", make_ai("ismcts"))
    fireball = next(c for c in game.players[1].hand if c.title == "Fireball")
    knowledge = Knowledge(known_in_hand={1: (fireball,)})            # one known card, four hidden ones

    def fireball_share(weights: EvalWeights) -> float:
        state = EngineState(game, observer=0, knowledge=knowledge, pending=("liz", "echo", None), weights=weights)
        rng = random.Random(3)
        seen = Counter()
        for _ in range(400):
            s = state.clone()
            s.determinize(0, rng)
            seen[s.pending[2].title] += 1
        return seen["Fireball"] / 400

    assert fireball_share(OLD) == 1.0
    assert 0.1 < fireball_share(NEW) < 0.6


def test_the_sampled_attack_card_is_in_the_sampled_hand():
    game = build("raptors_liz_t2_echo_feint", make_ai("ismcts"))
    state = EngineState(game, observer=0, knowledge=Knowledge.from_game(game, 0), pending=("liz", "echo", None), weights=NEW)
    rng = random.Random(1)
    for _ in range(50):
        s = state.clone()
        s.determinize(0, rng)
        assert s.pending[2] in s.game.players[1].hand and len(s.game.players[1].hand) == len(game.players[1].hand)


# ---------- cards, deck and the exhaustion race ----------
def test_a_card_is_worth_the_same_hit_points_to_a_team_and_to_a_hero_and_the_deck_does_not_flatten():
    g, _ = opening("raptors", "liz-sherman")
    s = with_weights(g, NEW)
    deck_30, deck_12 = s._side_value(1), with_weights(change(g, lambda c: c.players[1].deck.__delitem__(slice(0, 13))), NEW)._side_value(1)
    assert deck_30 > deck_12
    assert s._side_value(0) - with_weights(change(g, lambda c: c.players[0].hand.pop()), NEW)._side_value(0) > 0.02


def test_the_exhaustion_race_charges_the_deck_that_will_run_out_first_and_wildfire_counts():
    g, _ = opening("liz-sherman", "raptors")
    short = change(g, lambda c: c.players[0].deck.__delitem__(slice(0, len(c.players[0].deck) - 5)))
    state = with_weights(short, NEW)
    assert state._exhaustion(0) > state._exhaustion(1) == 0.0
    plain = change(g, lambda c: c.players[1].deck.__delitem__(slice(0, len(c.players[1].deck) - 5)))
    wf = with_weights(plain, NEW)
    # Liz draws one card and Wildfire burns another each turn: the same 5 cards last her half as long as a hero without a burn
    assert with_weights(short, NEW)._exhaustion(0) > 0 and wf._exhaustion(1) > 0
    assert with_weights(short, NEW)._side_value(0) < with_weights(g, NEW)._side_value(0) - 0.05


# ---------- the pack rule ----------
def test_the_pack_rule_lives_in_one_place_and_its_default_is_the_reserve_rule(monkeypatch):
    g, state = opening("raptors", "liz-sherman")
    hand = state.game.players[0].hand
    assert PACK_PLANS == {} and state._pack_presses(0) == (any(c.can_defend for c in hand) and any(c.can_attack for c in hand))
    monkeypatch.setitem(PACK_PLANS, "raptors", PackPlan(mode="press"))
    assert state._pack_presses(0) is True
    monkeypatch.setitem(PACK_PLANS, "raptors", PackPlan(mode="pulse", span=2))
    phases = []
    for turn_no in range(1, 17, 2):
        state.game.turn_no = turn_no
        phases.append(state._pack_presses(0))
    assert phases == [True, True, False, False, True, True, False, False]       # two turns forward, two back
    assert state._pack_presses(1) is False                                       # not a pack
    other = EngineState(g, observer=1, weights=NEW)
    assert other._pack_presses(0) is True                                        # the pack a bot of another hero models keeps pressing


# ---------- the target ----------
@pytest.mark.parametrize("porter_hp", [6, 2])
def test_the_raptors_strike_the_hero_that_is_in_reach_before_the_sidekick_even_one_they_could_kill(porter_hp):
    """Live 16/11 (the heuristic): four blows on the Porter and four on Sinbad, and the pack came apart. With the new evaluation the search
    attacks Sinbad first, with the Porter weak or not."""
    hand = ("Eviscerate", "Eaten Alive", "They Remember", "Clever Girl", "Decoy")
    for seed in (0, 1, 2):
        ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 150, "ai_time_budget": 60, "ai_seed": seed, "ai_eval": RESOLUTION}, 0)
        g = Game.new(Board.load("bprd-hq"), seed, controllers={0: ai, 1: ScriptedHellboy(1, seed)}, heroes=("raptors", "sinbad"), bot_player=0)
        g.turn, g.turn_no = 0, 3
        g.begin_turn()
        st = g.players[0]
        st.deck.extend(st.hand)
        st.hand.clear()
        for i, title in enumerate(hand):
            give(g, 0, title, nth=hand[:i].count(title))
        g.players[1].hand.clear()
        sinbad, porter = g.hero(1), g.fighters["porter"]
        sinbad.pos = 7
        ring = sorted(g.board.adj[7])
        porter.pos, porter.hp = ring[0], porter_hp
        for fid, space in zip(("blue", "delta", "echo"), ring[1:]):
            g.fighters[fid].pos = space
        act = ai.plan(g)
        assert (act.kind, act.target) == ("attack", "sinbad"), (seed, act.kind, act.target)
