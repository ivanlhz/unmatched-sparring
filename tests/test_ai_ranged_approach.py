"""APPROACH_PULL: a ranged hero is pulled toward the nearest space from which it can attack, a melee hero toward the rival."""
import pytest

from sparring import ai_medusa
from sparring.ai_medusa import MedusaAI, Model
from sparring.board import Board
from sparring.state import Game
from conftest import Scripted

PULL = 1000.0


@pytest.fixture(scope="module")
def novigrad():
    return Board.load("streets-of-novigrad")


def rig(board, bot, human):
    g = Game.new(board, 3, controllers={0: MedusaAI(0), 1: Scripted()}, heroes=(bot, human))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    return g


def approach_penalty(monkeypatch, ai, game, fid, space):
    """What APPROACH_PULL subtracts from position_value with the hero at `space`."""
    monkeypatch.setattr(ai, "hit_and_run", lambda g: False)
    values = {}
    for pull in (0.0, PULL):
        monkeypatch.setattr(ai_medusa, "APPROACH_PULL", pull)
        values[pull] = ai.position_value(game, Model(game, 0), {fid: space})
    return values[0.0] - values[PULL]


def test_ranged_hero_is_not_pulled_once_it_can_shoot(novigrad, monkeypatch):
    g = rig(novigrad, "liz-sherman", "michelangelo")
    liz, mikey = g.hero(0), g.hero(1)
    assert liz.ranged and not mikey.ranged
    ai = MedusaAI(0)
    board = g.board
    occupied = {f.pos for f in g.foes(0)}
    spots = [s for s in ai.strike_spots(board, mikey.pos, True) if s not in occupied]
    far = [s for s in spots if board.distance(s, mikey.pos) >= 2]
    near = [s for s in spots if board.distance(s, mikey.pos) == 1]
    assert far and near
    assert approach_penalty(monkeypatch, ai, g, liz.fid, far[0]) == 0
    assert approach_penalty(monkeypatch, ai, g, liz.fid, near[0]) == 0


def test_ranged_hero_out_of_reach_is_pulled_by_the_distance_to_the_nearest_strike_spot(novigrad, monkeypatch):
    g = rig(novigrad, "liz-sherman", "michelangelo")
    liz, mikey = g.hero(0), g.hero(1)
    ai = MedusaAI(0)
    board = g.board
    spots = {s for e in g.foes(0) for s in ai.strike_spots(board, e.pos, True)}     # every rival piece counts
    out = max((s for s in board.spaces if s not in spots), key=lambda s: min(board.distance(s, x) for x in spots))
    expected = min(board.distance(out, x) for x in spots)
    assert expected > 0
    assert approach_penalty(monkeypatch, ai, g, liz.fid, out) == pytest.approx(PULL * expected)


def test_melee_hero_keeps_the_distance_to_the_rival(novigrad, monkeypatch):
    g = rig(novigrad, "michelangelo", "liz-sherman")
    mikey, liz = g.hero(0), g.hero(1)
    assert not mikey.ranged
    ai = MedusaAI(0)
    board = g.board
    for space in sorted(board.spaces)[:12]:
        if space == liz.pos:
            continue
        assert approach_penalty(monkeypatch, ai, g, mikey.fid, space) == pytest.approx(PULL * board.distance(space, liz.pos))
