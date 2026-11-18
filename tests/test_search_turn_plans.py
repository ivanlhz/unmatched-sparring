"""Hard ISMCTS turn decisions reconstructed from the 18 November table journal."""
import random

from ai_positions import build, make_ai
from sparring.decision_log import describe_act
from sparring.guard import free_steps, reach_from, strike_spots
from sparring.search.adapter import EngineState
from sparring.search.plans import compare_plans


def test_sinbad_can_engage_and_attack_in_one_turn():
    ai = make_ai("ismcts", new_eval=True)
    game = build("sinbad_liz_t17", ai)
    first = ai.plan(game)
    assert first.kind == "maneuver" and first.boost is None
    ai.execute(game, first)
    second = ai.plan(game)
    assert second.kind == "attack" and second.target == "liz"
    assert not ai.fallbacks


def test_ciri_escapes_sinbads_six_space_reply():
    ai = make_ai("ismcts", new_eval=True)
    game = build("ciri_sinbad_t15_flee", ai)
    for _ in range(2):
        ai.execute(game, ai.plan(game))
    enemy = game.hero(1)
    spots = strike_spots(game.board, game.hero(0).pos, enemy.ranged, enemy.reach)
    reach = reach_from(game.board, enemy.pos, enemy.move + free_steps(game, enemy),
                       frozenset(game.occupied(1) - {enemy.pos}), frozenset(game.occupied(0)))
    assert enemy.pos not in spots and not reach.intersection(spots)
    assert not ai.fallbacks


def test_compared_plans_use_only_public_information_and_keep_live_state():
    ai = make_ai("ismcts", new_eval=True)
    game = build("sinbad_liz_t17", ai)
    before = game.rng.getstate()
    first = describe_act(ai.plan(game))
    scores = ai.last_report.plans
    assert scores and scores["samples"] == 16
    enemy = game.players[1]
    enemy.hand, enemy.deck = enemy.deck[:len(enemy.hand)], enemy.hand + enemy.deck[len(enemy.hand):]
    random.Random(123).shuffle(game.players[0].deck)
    assert describe_act(ai.plan(game)) == first
    assert ai.last_report.plans == scores
    assert game.rng.getstate() == before


def test_hellboy_compares_lobsters_attack_with_stalling_on_the_shorter_deck():
    ai = make_ai("ismcts", new_eval=True)
    game = build("hellboy_wyatt_t15", ai)
    assert (game.form(0), len(game.players[0].deck), game.hero(0).hp) == ("ANUNG UN RAMA", 7, 1)
    root = EngineState(game, observer=0, knowledge=ai.knowledge(game), weights=ai.weights)
    walk = [("maneuver", None), ("place", 23, "stay")]
    _, result = compare_plans(root, walk, ai.config, deadline=None)
    assert result["turns"] == 4 and result["samples"] == 16
    assert result["pressure_line"][0] == ("attack", "lobster", "wyatt")
