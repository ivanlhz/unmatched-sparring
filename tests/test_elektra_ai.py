"""How the search AI plays with and against Elektra: a hero taken off the board and NOT defeated is worth a fresh hero a turn behind (not a dead one and
not a win for whoever removed her), a turn whose mover has no fighter on the board is over, and whole games with the search on either side finish
without the search falling back to the heuristic (the first version crashed in `_hero_options` with the hero off the board)."""
from __future__ import annotations

import pytest

from sparring import sim
from sparring.search.adapter import RESOLUTION, EngineState, EvalWeights
from sparring.search.controller import IsmctsMedusa, make_bot_ai
from sparring.search.ismcts import SearchConfig
from sparring.state import Game
from conftest import give
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
    remove_elektra(g)
    away = EngineState(g, observer=1, weights=EvalWeights())
    assert away._hero_life(g.fighters["elektra"]) > 0.5
    h = mk(bprd)[0]
    spread(h)
    h.fx.set_counter(0, "life", 2)           # resurrected: a hero at 0 health is simply dead
    h.fighters["elektra"].hp = 0
    h.fighters["elektra"].alive = False
    assert EngineState(h, observer=1, weights=EvalWeights())._hero_life(h.fighters["elektra"]) == 0


def test_removing_her_in_her_first_life_is_not_a_loss_for_the_one_who_does_it(bprd):
    """Her first life reads above the away value (the second life is in it), so the search that attacks a 1 health Elektra sees no drop."""
    g, _ = mk(bprd, turn=0)
    spread(g)
    g.fighters["elektra"].hp = 1
    before = EngineState(g, observer=0, weights=EvalWeights())
    assert before._hero_life(g.fighters["elektra"]) >= 0.85
    mine = EngineState(g, observer=1, weights=EvalWeights()).evaluate(1)       # the remover is player 1 (Hellboy)
    g.damage(g.fighters["elektra"], 5, "effect")
    after = EngineState(g, observer=1, weights=EvalWeights()).evaluate(1)
    assert after >= mine - 0.05, (mine, after)


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


@pytest.mark.parametrize("seat", ["bot", "human"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_scripted_chaser_plays_against_an_elektra_that_goes_off_the_board(seat, seed):
    pair = ("elektra", "hellboy") if seat == "bot" else ("hellboy", "elektra")
    assert sim.play(seed, bot_hero=pair[0], human_hero=pair[1], rival="chaser").winner != "draw"


@pytest.mark.parametrize("seat", ["bot", "human"])
@pytest.mark.parametrize("seed", [21, 22, 23])
def test_search_games_against_tomoe_gozen_never_fall_back_to_the_heuristic(seat, seed, monkeypatch):
    FELL_BACK.clear()
    monkeypatch.setattr(IsmctsMedusa, "_fell_back", lambda self, where: FELL_BACK.append(where))
    pair = ("elektra", "tomoe-gozen") if seat == "bot" else ("tomoe-gozen", "elektra")
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 12, "ai_seed": seed})
    sim.play(seed, bot_hero=pair[0], human_hero=pair[1], medusa=ai)
    assert FELL_BACK == [], FELL_BACK


def test_nothing_can_be_hit_while_she_is_away_so_her_threat_is_zero_and_no_kill(bprd):
    g, _ = mk(bprd, turn=0)
    spread(g)
    remove_elektra(g)
    state = EngineState(g, observer=1, weights=EvalWeights())
    assert state.threat(0) == (0.0, 0.0) and state._fighters_exposure(0, False) == 0.0


# ---------------------------------------------------------------- a rival next to her first life (review of the first-life value)

WEIGHTS = {"default": EvalWeights(), "resolution": EvalWeights(**RESOLUTION)}
PROBE_SEEDS = range(8)


def beside(bprd, hp, foe="elektra", resurrected=False):
    """The reviewer's probe: Hellboy (the bot, player 0, his turn) holds Service Pistol and Excalibur and stands next to `foe`'s hero at `hp`;
    every other fighter is out of his zone."""
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("hellboy", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    hellboy, rival = g.hero(0), g.hero(1)
    hellboy.pos = min(g.board.spaces)
    rival.pos = min(g.board.adj[hellboy.pos])
    taken = {hellboy.pos, rival.pos}
    for f in g.fighters.values():
        if f is not hellboy and f is not rival:
            f.pos = next(s for s in sorted(g.board.spaces, reverse=True) if s not in taken and not g.board.share_zone(s, hellboy.pos))
            taken.add(f.pos)
    if resurrected:
        g.fx.set_counter(1, "life", 2)
        rival.max_hp = 9
    rival.hp = hp
    give(g, 0, "Service Pistol")
    give(g, 0, "Excalibur")
    return g


def remover_value(g, weights):
    return EngineState(g, observer=0, weights=weights).evaluate(0)


@pytest.mark.parametrize("profile", WEIGHTS)
def test_next_to_her_every_point_of_her_first_life_is_worth_something_and_removing_her_the_most(bprd, profile):
    """Her first life read a flat 0.85 from 5 health down and the threat on her vanished with her, so the rival beside her valued the position
    at +0.75 with her at 1 and +0.41 once she was gone, and did not attack. One pool with her second life: each point lost raises the
    remover's value and the removal raises it again."""
    w = WEIGHTS[profile]
    values = [remover_value(beside(bprd, hp), w) for hp in range(7, 0, -1)]
    assert all(b > a + 0.002 for a, b in zip(values, values[1:])), values
    g = beside(bprd, 1)
    g.damage(g.fighters["elektra"], 1, "effect")
    assert g.fighters["elektra"].off_board and g.winner is None
    assert remover_value(g, w) > values[-1] + 0.01, (values[-1], remover_value(g, w))


@pytest.mark.parametrize("profile", WEIGHTS)
def test_her_side_never_reads_better_away_than_on_the_board_however_threatened(bprd, profile):
    w = WEIGHTS[profile]
    away = beside(bprd, 1)
    away.damage(away.fighters["elektra"], 1, "effect")
    gone = EngineState(away, observer=0, weights=w)._side_value(1)
    for hp in range(1, 8):
        for urgent in (False, True):
            assert EngineState(beside(bprd, hp), observer=0, weights=w)._side_value(1, urgent) > gone, (hp, urgent)


def test_the_blow_that_removes_her_is_not_a_chance_of_winning_the_game(bprd):
    """With `lethal_mix` the leaf is won with the chance the rival's hero is killed next: her removal ends nothing, so it stays out of it."""
    w = EvalWeights(**{**RESOLUTION, "lethal_mix": 1.0})
    first = EngineState(beside(bprd, 1), observer=0, weights=w)
    assert first.threat(1)[1] > 0.5                       # the blow that takes her out is likely...
    first._lethal = {}
    first._exposure(1, False)
    assert first._lethal == {}                           # ...and nothing says the game ends with it
    second = EngineState(beside(bprd, 1, resurrected=True), observer=0, weights=w)
    second._lethal = {}
    second._exposure(1, False)
    assert second._lethal[1] > 0.5                       # her second defeat is a real one


@pytest.mark.parametrize("hp", [1, 2, 5])
def test_hellboy_next_to_a_first_life_elektra_attacks_her(bprd, hp):
    """The reviewer's probe (ISMCTS, 200 iterations, 8 seeds): he attacked her in 0, 0 and 2 of 8 at 1, 2 and 5 health, and in 8 of 8 once resurrected."""
    attacks = 0
    for seed in PROBE_SEEDS:
        act = IsmctsMedusa(0, SearchConfig(iterations=200, seed=seed)).plan(beside(bprd, hp))
        attacks += act.kind == "attack" and act.target == "elektra"
    assert attacks >= 7, attacks


# (hero, resurrected, health) -> the remover's value before this change, default and resolution weights: nobody else's evaluation moved
UNCHANGED = {
    ("elektra", True, 9): (0.665372, 0.729021),
    ("elektra", True, 5): (0.782056, 0.802323),
    ("elektra", True, 2): (0.848738, 0.86059),
    ("elektra", True, 1): (0.857656, 0.865949),
    ("medusa", False, 16): (0.689434, 0.603849),
    ("medusa", False, 5): (0.831409, 0.79287),
    ("medusa", False, 1): (0.875921, 0.860217),
    ("bullseye", False, 3): (0.879347, 0.845581),
}


@pytest.mark.parametrize("case", sorted(UNCHANGED))
def test_a_resurrected_elektra_and_any_other_hero_evaluate_as_before(bprd, case):
    foe, resurrected, hp = case
    g = beside(bprd, hp, foe, resurrected)
    got = tuple(round(remover_value(g, w), 6) for w in WEIGHTS.values())
    assert got == pytest.approx(UNCHANGED[case], abs=2e-6), got
    rival = g.hero(1)
    assert EngineState(g, observer=0, weights=EvalWeights())._hero_life(rival) == pytest.approx((hp / rival.max_hp) ** 0.5)
