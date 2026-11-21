"""Hard ISMCTS turn decisions reconstructed from the 18 November table journal."""
import random

from ai_positions import build, make_ai
from sparring.decision_log import describe_act
from sparring.guard import free_steps, reach_from, strike_spots
from sparring.search.adapter import EngineState
from sparring.search.plans import apply_line, best_blow, compare_plans, pressure_actions


def test_sinbad_can_engage_and_attack_in_one_turn():
    ai = make_ai("ismcts", new_eval=True)
    game = build("sinbad_liz_t17", ai)
    first = ai.plan(game)
    assert first.kind == "maneuver" and first.boost is None
    ai.execute(game, first)
    second = ai.plan(game)
    assert second.kind == "attack" and second.target == "liz"
    assert not ai.fallbacks


def test_pressure_compares_distinct_approaches_with_and_without_boost():
    ai = make_ai("ismcts", new_eval=True)
    game = build("sinbad_liz_t17", ai)
    root = EngineState(game, observer=0, knowledge=ai.knowledge(game), weights=ai.weights)
    routes = pressure_actions(root, ai.config.seed, deadline=None)
    assert len({route[1][1] for route in routes}) >= 2
    assert {route[0][1] is None for route in routes} == {False, True}
    for route in routes:
        trial = root.clone()
        trial.determinize(0, random.Random(1))
        apply_line(trial, route)
        assert best_blow(trial)[0]
    _, report = compare_plans(root, [("maneuver", None), ("place", game.hero(0).pos, "stay")], ai.config, deadline=None)
    assert list(report["pressure_lines"].values()) == routes
    assert all(name in report["gains"] for name in report["pressure_lines"])


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


# Root values of the live tree at 18/11 22:48:53 (decisions.jsonl, game 20261118-223509-dcd5, seq 22).
CIRI_T15_TREE = {("scheme", "Child of the Elder Blood", None, None): 0.4666, ("maneuver", None): 0.4507,
                 ("maneuver", "Channel the source"): 0.4303, ("attack", "ciri", "strange"): 0.425,
                 ("maneuver", "The lady of space and time"): 0.4191}


def test_plans_keep_the_action_the_tree_clearly_preferred():
    """Seed 0 reproduces the live comparison (tree 0.365, hit and withdraw 0.405). The +0.040 gain is consistent across samples,
    so only the tree's own 0.042 preference for the scheme keeps it; without the tree's values the swap that lost 5 life comes back."""
    scheme = [("scheme", "Child of the Elder Blood", None, None)]
    picks = {}
    for tree_values in (None, CIRI_T15_TREE):
        ai = make_ai("ismcts", new_eval=True)
        game = build("ciri_strange_t15_hit_and_withdraw", ai)
        root = EngineState(game, observer=0, knowledge=ai.knowledge(game), weights=ai.weights)
        line, result = compare_plans(root, scheme, ai.config, deadline=None, tree_values=tree_values)
        picks[tree_values is not None] = (result["selected"], line)
        assert round(result["tree"], 3) == 0.365 and round(result["hit_and_withdraw"], 3) == 0.405
    assert picks[False][0] == "hit_and_withdraw"
    assert picks[True] == ("tree", scheme)


def test_tree_preference_is_zero_when_the_tree_did_not_weigh_the_plans_first_action():
    from sparring.search.plans import tree_preference
    scheme = [("scheme", "Child of the Elder Blood", None, None)]
    assert tree_preference(CIRI_T15_TREE, scheme, [("attack", "ciri", "strange"), ("attack_card", "ciri", "Blink")]) == 0.4666 - 0.425
    assert tree_preference(CIRI_T15_TREE, scheme, [("attack", "ihuarraquax", "strange")]) == 0.0
    assert tree_preference(None, scheme, [("attack", "ciri", "strange")]) == 0.0
    assert tree_preference(CIRI_T15_TREE, [("attack", "ciri", "strange")], scheme) == 0.0
