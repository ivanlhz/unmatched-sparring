"""F-STRANGE-REALLY-FULL-HP: the search does not play a scheme that only spends cards and an action (live 12/11:
turn 1, Doctor Strange at 14/14 played No, Really, I'm a Doctor, which heals nobody and puts a hand card back)."""
from __future__ import annotations

import random

import pytest

from sparring.board import Board
from sparring.search.adapter import EngineState
from sparring.search.controller import make_bot_ai
from sparring.state import Game
from conftest import give

REALLY = "No, Really, I'm a Doctor"
HAND = ["The Mists of Munnopor", REALLY, "Steadfast Disciple", "The Winds of Watoomb", "The Rings of Raggadorr"]
ITER = 300


def table(seed: int = 0, strange_hp: int = 14, wong_hp: int | None = None, wong: int = 35):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": ITER, "ai_seed": seed}, 0)
    g = Game.new(Board.load("new-york-city"), seed, controllers={0: ai}, heroes=("doctor-strange", "liz-sherman"), bot_player=0)
    g.turn, g.turn_no = 0, 1
    g.begin_turn()
    mine = g.players[0]
    mine.deck.extend(mine.hand)
    mine.hand.clear()
    for title in HAND:
        give(g, 0, title)
    g.fighters["strange"].pos, g.fighters["wong"].pos, g.hero(1).pos = 39, wong, 6
    g.fighters["strange"].hp = strange_hp
    if wong_hp is not None:
        g.fighters["wong"].hp = wong_hp
    g.actions_left = 2
    return ai, g


def scheme_moves(ai, g) -> list:
    root = EngineState(g, observer=0, knowledge=ai.knowledge(g), weights=ai.weights)
    return [m for m in root.legal_moves() if m[0] == "scheme"]


def test_a_heal_that_heals_nobody_is_not_a_move_of_the_search():
    ai, g = table()
    assert scheme_moves(ai, g) == []


@pytest.mark.parametrize("seed", range(3))
def test_the_search_does_not_play_really_at_full_health(seed):
    ai, g = table(seed)
    act = ai.plan(g)
    assert (act.kind, act.card and act.card.title) != ("scheme", REALLY)
    assert ai.fallbacks == 0


def test_really_stays_a_move_when_strange_is_hurt():
    ai, g = table(strange_hp=6)
    assert [m[1] for m in scheme_moves(ai, g)] == [REALLY]


def test_really_stays_a_move_when_wong_beside_strange_is_hurt():
    beside = sorted(Board.load("new-york-city").adj[39])[0]
    ai, g = table(wong_hp=2, wong=beside)
    assert [m[1] for m in scheme_moves(ai, g)] == [REALLY]


def test_a_hurt_wong_away_from_strange_is_nobody_to_heal():
    ai, g = table(wong_hp=2)
    assert g.board.distance(39, 35) > 1
    assert scheme_moves(ai, g) == []


def test_really_stays_a_move_with_an_empty_deck():
    ai, g = table()
    g.players[0].deck.clear()
    assert [m[1] for m in scheme_moves(ai, g)] == [REALLY]


def test_the_search_heals_a_badly_hurt_strange():
    ai, g = table(strange_hp=4)
    act = ai.plan(g)
    assert (act.kind, act.card.title) == ("scheme", REALLY)


def test_really_is_not_a_move_inside_the_tree_after_a_draw():
    """`Game.clone` resets the draw counter: the verdict must not read a draw made earlier in the turn as the scheme's."""
    ai, g = table()
    node = EngineState(g, observer=0, knowledge=ai.knowledge(g), weights=ai.weights)
    node.determinize(0, random.Random(1))
    node.apply(("maneuver", None))
    node.apply(next(m for m in node.legal_moves() if m[0] == "place"))
    assert node.game.drawn[0] == 1 and node.game.actions_left == 1
    assert any(c.title == REALLY for c in node.game.players[0].hand)
    assert REALLY not in [m[1] for m in node.legal_moves() if m[0] == "scheme"]


def test_the_second_action_does_not_play_really_at_full_health():
    """The first action played for real, then planned again: the moves the first search cached for the nodes after its
    maneuver must not hand the scheme to the root of the second."""
    held = 0
    for seed in range(8):
        ai, g = table(seed)
        first = ai.plan(g)
        assert first.kind == "maneuver"
        g.maneuver(0, dict(first.moves), first.boost)
        if not any(c.title == REALLY for c in g.players[0].hand):
            continue                                        # the maneuver was boosted with it
        held += 1
        assert g.fighters["strange"].hp == 14 and g.actions_left == 1
        assert REALLY not in [m[1] for m in scheme_moves(ai, g)], seed
        second = ai.plan(g)
        assert (second.kind, second.card and second.card.title) != ("scheme", REALLY), seed
        assert ai.fallbacks == 0
    assert held >= 4


@pytest.mark.parametrize("scheme", [REALLY, "Eye of Agamotto"])
def test_judging_a_scheme_leaves_the_live_rng_alone(scheme):
    ai, g = table(strange_hp=6)
    if scheme != REALLY:
        give(g, 0, scheme)
    g.players[0].discard.extend(g.players[0].deck[:6])       # something for a shuffling scheme to shuffle back
    del g.players[0].deck[:6]
    before = g.rng.getstate()
    assert scheme in [m[1] for m in scheme_moves(ai, g)]
    assert g.rng.getstate() == before
