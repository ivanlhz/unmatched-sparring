"""How the search AI plays with and against Elektra: a hero taken off the board and NOT defeated is worth a fresh hero a turn behind (not a dead one and
not a win for whoever removed her), a turn whose mover has no fighter on the board is over, and whole games with the search on either side finish
without the search falling back to the heuristic (the first version crashed in `_hero_options` with the hero off the board)."""
from __future__ import annotations

import pytest

from sparring import sim
from sparring.search.adapter import EngineState, EvalWeights
from sparring.search.controller import IsmctsMedusa, make_bot_ai
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_elektra_effects import HANDS, first, remove_elektra, spread

OTHERS = ["hellboy", "medusa", "bullseye"]


def mk(bprd, bot="elektra", human="hellboy", turn=1):
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, 3, controllers=ctl, heroes=(bot, human), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g, ctl


def value(g, observer, player):
    return EngineState(g, observer=observer, weights=EvalWeights())._side_value(player)


def test_a_hero_off_the_board_is_worth_nearly_a_fresh_hero_and_much_more_than_a_dead_one(bprd):
    g, _ = mk(bprd)
    spread(g)
    whole = value(g, 1, 1)
    remove_elektra(g)
    away = value(g, 1, 1)
    h = mk(bprd)[0]
    spread(h)
    h.fighters["elektra"].hp = 0
    h.fighters["elektra"].alive = False
    dead = value(h, 1, 1)
    assert dead < away < whole + 0.5, (dead, away, whole)
    assert away > 0.5 * whole


def test_what_the_rival_gains_from_removing_her_is_not_the_value_of_a_kill(bprd):
    g, _ = mk(bprd, turn=0)
    spread(g)
    state = EngineState(g, observer=0, weights=EvalWeights())
    before = state.evaluate(0)
    remove_elektra(g)
    after = EngineState(g, observer=0, weights=EvalWeights()).evaluate(0)
    assert after < before + 1.0
    assert not (g.winner is not None)


def test_a_mover_with_every_fighter_off_the_board_ends_the_turn_inside_the_search(bprd):
    g, _ = mk(bprd, turn=0)
    spread(g)
    remove_elektra(g)
    state = EngineState(g, observer=0, weights=EvalWeights())
    state._advance()
    assert state.game.turn == 1 and g.turn == 0         # the search plays on its own copy


FELL_BACK = []


@pytest.mark.parametrize("foe", OTHERS)
@pytest.mark.parametrize("seat", ["bot", "human"])
def test_games_with_the_search_ai_reach_the_end_without_falling_back_to_the_heuristic(foe, seat, monkeypatch):
    FELL_BACK.clear()
    monkeypatch.setattr(IsmctsMedusa, "_fell_back", lambda self, where: FELL_BACK.append(where))
    pair = ("elektra", foe) if seat == "bot" else (foe, "elektra")
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 12, "ai_seed": 5})
    outcome = sim.play(5, bot_hero=pair[0], human_hero=pair[1], medusa=ai)
    assert outcome.winner != "draw"
    assert FELL_BACK == [], FELL_BACK


# ---------------------------------------------------------------- the bot's own choices

def test_the_bot_swaps_a_hand_in_when_the_blow_would_take_her_out(bprd):
    from sparring.ai_medusa import MedusaAI
    from conftest import give
    from test_effects_combat import pair
    for hp in (2, 1):
        ctl = {0: MedusaAI(0), 1: Answers()}
        g = Game.new(bprd, 3, controllers=ctl, heroes=("elektra", "leonardo"), bot_player=0)
        g.turn, g.turn_no = 1, 2
        g.begin_turn()
        for p in g.players:
            p.hand.clear()
        foe, e = pair(g, "leonardo", "elektra")
        spread_far = [s for s in sorted(g.board.spaces, reverse=True) if not g.board.share_zone(s, e.pos) and all(f.pos != s for f in g.fighters.values() if f.alive)]
        for h, s in zip(HANDS, spread_far):
            g.fighters[h].pos = s
        e.hp = hp
        res = g.attack(foe, e, give(g, 1, "Katana"), give(g, 0, "Snakeroot Clan"))
        assert res.target in HANDS and e.alive and g.fx.counter_value(0, "life") == 0, (hp, res.target)       # a Hand takes the blow: she is not removed
