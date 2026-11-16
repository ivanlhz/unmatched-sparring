"""Regression positions from the live games of 15-16/11 (tests/fixtures/ai_positions.json), asked to both AIs.

Each test states what a good player does there. The ones the bot still gets wrong are marked xfail with the reason: they are the
baseline that the AI evaluation work (phase 1) has to turn green; the markers are not strict, so an improvement shows as XPASS and
the marker is then removed. The positions are rebuilt from the logs (the real decks are not in them): the spaces, hands and turn
are the live ones; the cards of the rival's hand that the bot did not see are drawn from the pool it has not seen, as the bot
would draw them, and the rest is approximate and says so in the fixture."""
import pytest

from ai_positions import POSITIONS, build, make_ai
from sparring.ai_medusa import Model
from sparring.decision_log import describe_act

AIS = ("heuristic", "ismcts")
FAILS = {}      # (position, ai) -> reason: what the bot still gets wrong


def known_fail(reason: str, *cases: tuple[str, str]) -> None:
    FAILS.update({case: reason for case in cases})


known_fail("Opening of Raptors vs Liz: the search discards Ambush as a maneuver boost before any attack, as the live bot did",
           ("raptors_liz_t1_opening", "ismcts"))
known_fail("Raptors vs Hellboy, turn 2: the search spends four cards (scheme, a maneuver boost, two attacks) and ends the turn with fewer than three",
           ("raptors_hellboy_t2_empties_the_hand", "ismcts"))
known_fail("Echo pays its last defence card (Feint) against a face-down jab with a 14 % chance of killing it",
           ("raptors_liz_t2_echo_feint", "heuristic"), ("raptors_liz_t2_echo_feint", "ismcts"))
known_fail("Liz maneuvers twice without getting anywhere (out and back, or one space) while Wildfire burns the deck",
           ("liz_raptors_t6_back_and_forth", "heuristic"), ("liz_raptors_t14_back_and_forth", "heuristic"),
           ("liz_raptors_t14_back_and_forth", "ismcts"), ("liz_raptors_t20_back_and_forth", "heuristic"))


def case(name: str, ai: str):
    reason = FAILS.get((name, ai))
    marks = [pytest.mark.xfail(reason=reason, strict=False, raises=AssertionError)] if reason else []
    return pytest.param(name, ai, marks=marks, id=f"{name}-{ai}")


def play_turn(ai, game, limit: int = 4) -> list[dict]:
    """The bot's turn from the position, action by action, as `take_turn` does."""
    acts = []
    while game.actions_left > 0 and game.winner is None and len(acts) < limit:
        act = ai.plan(game)
        acts.append(describe_act(act))
        ai.execute(game, act)
    return acts


@pytest.mark.parametrize("name, ai_kind", [case("raptors_liz_t1_opening", k) for k in AIS])
def test_the_opening_does_not_spend_a_card_before_attacking(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    act = describe_act(ai.plan(game))
    assert act["kind"] in ("maneuver", "attack") and "boost" not in act, f"{POSITIONS[name]['good_player']} Bot played {act}"


@pytest.mark.parametrize("name, ai_kind", [case("raptors_hellboy_t2_empties_the_hand", k) for k in AIS])
def test_the_bot_does_not_empty_its_hand_against_hellboy(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    acts = play_turn(ai, game)
    held = len(game.players[0].hand)
    assert held >= 3, f"{POSITIONS[name]['good_player']} Bot did {acts} and holds {held}"


@pytest.mark.parametrize("name, ai_kind", [case("raptors_liz_t2_echo_feint", k) for k in AIS])
def test_echo_keeps_its_last_defence_card_against_a_jab_unless_the_kill_is_likely(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    spec = POSITIONS[name]
    attacker, target = game.fighters[spec["attack"]["attacker"]], game.fighters[spec["attack"]["target"]]
    # what the bot can know: Liz's unseen cards are the full set minus what is public (the heuristic's own model of the pool)
    kill = sum(p for p, value in Model(game, 0).committed_attack_dist(attacker, target) if value >= target.hp)
    card = ai.choose_defense(game, attacker, target)
    if kill > spec["kill_probability_limit"]:
        return      # the attack is likely to kill Echo: defending is a good decision, the rule does not apply
    assert card is None, f"probability that the face-down attack kills Echo: {kill:.0%} (limit {spec['kill_probability_limit']:.0%}). {spec['good_player']} Bot defended with {card.title}"


def test_the_kill_probability_of_the_echo_position_is_the_documented_one():
    """The number the rule above hangs on, printed in the failure reason: it comes from the real unseen pool."""
    ai = make_ai("heuristic")
    game = build("raptors_liz_t2_echo_feint", ai)
    liz, echo = game.fighters["liz"], game.fighters["echo"]
    dist = Model(game, 0).committed_attack_dist(liz, echo)
    assert abs(sum(p for p, _ in dist) - 1) < 1e-9
    assert [c.title for c in game.players[0].known.cards(game.players[1])] == ["Fireball"]
    assert len(game.players[1].hand) == 4 and game.fighters["liz"].hp == 12


@pytest.mark.parametrize("name, ai_kind", [case(n, k) for n in
                                          ("liz_raptors_t6_back_and_forth", "liz_raptors_t14_back_and_forth", "liz_raptors_t20_back_and_forth") for k in AIS])
def test_liz_does_not_maneuver_twice_to_stay_where_she_is(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    start = game.hero(0).pos
    acts = play_turn(ai, game, limit=POSITIONS[name]["actions_left"])
    net = game.board.distance(start, game.hero(0).pos)
    assert not (len(acts) == 2 and all(a["kind"] == "maneuver" for a in acts) and net <= 1), f"{POSITIONS[name]['good_player']} Bot did {acts}"
