"""Regression positions from the live games of 15-16/11 (tests/fixtures/ai_positions.json), asked to both AIs.

Each test states what a good player does there. The ones the bot still gets wrong are marked xfail with the reason: they are the
baseline that the AI evaluation work (phase 1) has to turn green; the markers are not strict, so an improvement shows as XPASS and
the marker is then removed. The positions are rebuilt from the logs (the real decks are not in them): the spaces, hands and turn
are the live ones, the rest is approximate and says so in the fixture."""
import pytest

from ai_positions import POSITIONS, build, make_ai
from sparring.decision_log import describe_act

AIS = ("heuristic", "ismcts")


def known_fail(reason: str, *cases: tuple[str, str]):
    return {case: pytest.mark.xfail(reason=reason, strict=False) for case in cases}


def param(table: dict, name: str, ai: str):
    mark = table.get((name, ai))
    return pytest.param(name, ai, marks=[mark] if mark else [], id=f"{name}-{ai}")


SPENDS_AT_OPENING = known_fail(
    "Opening of Raptors vs Liz: the bot spends a card before any attack (Working Things Out as a scheme, or Ambush as a maneuver "
    "boost) when a plain maneuver keeps the hand",
    ("raptors_liz_t1_opening", "heuristic"), ("raptors_liz_t1_opening", "ismcts"))
PAYS_FOR_A_JAB = known_fail(
    "Echo defends a face-down attack that cannot kill it with a card from a three-card hand (live: Decoy and Feint against two "
    "Flame Lash of value 1)",
    ("raptors_liz_t2_echo_decoy", "heuristic"), ("raptors_liz_t2_echo_decoy", "ismcts"), ("raptors_liz_t2_echo_feint", "heuristic"))
GOES_BACK_AND_FORTH = known_fail(
    "Liz maneuvers twice without getting anywhere (out and back, or one space) while Wildfire burns the deck",
    ("liz_raptors_t14_back_and_forth", "heuristic"), ("liz_raptors_t20_back_and_forth", "heuristic"),
    ("liz_raptors_t20_back_and_forth", "ismcts"))


@pytest.mark.parametrize("name, ai_kind", [param(SPENDS_AT_OPENING, "raptors_liz_t1_opening", k) for k in AIS])
def test_the_opening_does_not_spend_a_card_before_attacking(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    act = describe_act(ai.plan(game))
    assert act["kind"] in ("maneuver", "attack") and "boost" not in act, f"{POSITIONS[name]['good_player']} Bot played {act}"


@pytest.mark.parametrize("name, ai_kind", [param(PAYS_FOR_A_JAB, n, k) for n in ("raptors_liz_t2_echo_decoy", "raptors_liz_t2_echo_feint") for k in AIS])
def test_echo_does_not_pay_a_card_to_stop_a_jab(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    pending = POSITIONS[name]["attack"]
    card = ai.choose_defense(game, game.fighters[pending["attacker"]], game.fighters[pending["target"]])
    assert card is None, f"{POSITIONS[name]['good_player']} Bot defended with {card.title}"


@pytest.mark.parametrize("name, ai_kind", [param(GOES_BACK_AND_FORTH, n, k) for n in
                                          ("liz_raptors_t6_back_and_forth", "liz_raptors_t14_back_and_forth", "liz_raptors_t20_back_and_forth") for k in AIS])
def test_liz_does_not_maneuver_twice_to_stay_where_she_is(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    start, acts = game.hero(0).pos, []
    for _ in range(POSITIONS[name]["actions_left"]):
        act = ai.plan(game)
        acts.append(describe_act(act))
        ai.execute(game, act)
        if game.winner is not None or game.actions_left <= 0:
            break
    net = game.board.distance(start, game.hero(0).pos)
    assert not (len(acts) == 2 and all(a["kind"] == "maneuver" for a in acts) and net <= 1), f"{POSITIONS[name]['good_player']} Bot did {acts}"
