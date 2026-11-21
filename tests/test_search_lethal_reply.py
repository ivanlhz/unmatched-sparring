import random

from conftest import give
from sparring.board import Board
from sparring.search.adapter import EngineState, EvalWeights, Knowledge, RESOLUTION
from sparring.search.plans import continuation
from sparring.state import Game


def position(*, boost_known=True, protected=False):
    game = Game.new(Board.load("bprd-hq"), 5, {}, heroes=("hellboy", "medusa"))
    game.turn, game.turn_no, game.actions_left = 1, 21, 2
    game.hero(0).hp, game.hero(0).pos, game.hero(1).pos = 1, 1, 8
    for player in range(2):
        for fighter in game.own(player):
            if not fighter.hero:
                fighter.alive, fighter.pos = False, None
        deck, hand = game.players[player].deck, game.players[player].hand
        deck.extend(hand)
        hand.clear()
    glance = give(game, 1, "A Momentary Glance")
    boost = give(game, 1, "Second Shot")
    game.observe_hand(0, [glance, boost] if boost_known else [glance])
    if protected:
        game.effect_shield[0] = game.turn_no
    return game


def sampled(game):
    state = EngineState(game, observer=0, knowledge=Knowledge.from_game(game, 0), weights=EvalWeights(**RESOLUTION))
    state.determinize(0, random.Random(0))
    return state


def test_known_boost_and_scheme_are_a_lethal_reply_even_out_of_attack_range():
    game = position()
    state = sampled(game)
    rng_state = state.game.rng.getstate()
    assert state.evaluate(0) == 0
    assert state.game.rng.getstate() == rng_state
    move = state.rollout_move(random.Random(12))
    assert move == ("maneuver", "Second Shot")
    assert continuation(state, [move, state_after_boost(state, move)], random.Random(12), 1) == 0
    assert state.winner() == 1 and game.winner is None and game.hero(0).hp == 1


def state_after_boost(state, move):
    trial = state.clone()
    trial.apply(move)
    placement = trial.lethal_reply()
    assert placement and placement[0] == "place"
    return placement


def test_hidden_boost_cannot_prove_a_lethal_reply():
    assert sampled(position(boost_known=False)).lethal_reply() is None


def test_one_action_or_effect_protection_prevents_the_lethal_reply():
    game = position()
    game.actions_left = 1
    assert sampled(game).lethal_reply() is None
    assert sampled(position(protected=True)).lethal_reply() is None
