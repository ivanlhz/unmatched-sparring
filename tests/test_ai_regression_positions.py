"""Regression positions from the live games of 15-16/11 (tests/fixtures/ai_positions.json), asked to both AIs.

Each test states what a good player does there. The ones the bot still gets wrong are marked xfail with the reason: they are the
baseline that the AI evaluation work (phase 1) has to turn green; the markers are not strict, so an improvement shows as XPASS and
the marker is then removed. The positions are rebuilt from the logs (the real decks are not in them): the spaces, hands and turn
are the live ones; the cards of the rival's hand that the bot did not see are drawn from the pool it has not seen, as the bot
would draw them, and the rest is approximate and says so in the fixture."""
from math import comb

import pytest

from ai_positions import POSITIONS, build, make_ai
from sparring.decision_log import describe_act

AIS = ("heuristic", "ismcts")
FAILS = {}      # (position, ai) -> reason: what the bot still gets wrong


def known_fail(reason: str, *cases: tuple[str, str]) -> None:
    FAILS.update({case: reason for case in cases})


known_fail("Opening of Raptors vs Liz: the search discards Ambush as a maneuver boost before any attack, as the live bot did",
           ("raptors_liz_t1_opening", "ismcts"))
known_fail("Raptors vs Hellboy, turn 2: the bot spends more than one card on pure movement (Working Things Out as a scheme plus a maneuver boost)",
           ("raptors_hellboy_t2_pure_movement", "ismcts"))
known_fail("Echo pays its last defence card (Feint) against a face-down jab that is unlikely to kill it",
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


MOVE_ONLY_SCHEMES = frozenset({"Working Things Out"})     # schemes whose only effect is to move the pieces


def pure_movement_cards(acts: list[dict]) -> int:
    """Cards spent on movement alone: a scheme that only moves, and any card used as a maneuver boost. Attack and defence cards do not count."""
    return sum((a["kind"] == "scheme" and a.get("card") in MOVE_ONLY_SCHEMES) or (a["kind"] == "maneuver" and "boost" in a) for a in acts)


@pytest.mark.parametrize("name, ai_kind", [case("raptors_hellboy_t2_pure_movement", k) for k in AIS])
def test_the_bot_spends_at_most_one_card_on_pure_movement_in_a_turn(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    assert len(game.players[1].hand) == 7 and game.players[0].deck[0].title == "Disengage"
    acts = play_turn(ai, game)
    spent = pure_movement_cards(acts)
    assert spent <= POSITIONS[name]["pure_movement_limit"], f"{POSITIONS[name]['good_player']} Bot did {acts}: {spent} cards on pure movement"


def kill_probability(game, attacker, target) -> float:
    """Upper bound of the chance that the face-down attack kills `target`: some card among the rival's unknown ones can do it.
    The unknown cards are the hand minus what the bot knows, drawn from the rival's set minus its public discard and the known cards."""
    rival = game.players[attacker.owner]
    known = game.players[1 - attacker.owner].known.cards(rival)
    gone = {c.card_id for c in rival.discard} | {c.card_id for c in known}
    pool = [c for c in rival.full_set if c.card_id not in gone]
    unknown = len(rival.hand) - len(known)
    bonus = game.attack_bonus(attacker, target)
    killers = sum(1 for c in pool if c.can_attack and c.usable_by(attacker.name) and c.value + bonus >= target.hp)
    return 1 - comb(len(pool) - killers, unknown) / comb(len(pool), unknown)


@pytest.mark.parametrize("name, ai_kind", [case("raptors_liz_t2_echo_feint", k) for k in AIS])
def test_echo_keeps_its_last_defence_card_against_a_jab_unless_the_kill_is_likely(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    spec = POSITIONS[name]
    attacker, target = game.fighters[spec["attack"]["attacker"]], game.fighters[spec["attack"]["target"]]
    kill = kill_probability(game, attacker, target)
    if kill > spec["kill_probability_limit"]:
        pytest.skip(f"the face-down attack can kill Echo with probability {kill:.1%} (limit {spec['kill_probability_limit']:.0%}): defending is fine")
    card = ai.choose_defense(game, attacker, target)
    assert card is None, f"probability that the face-down attack kills Echo: {kill:.1%} (limit {spec['kill_probability_limit']:.0%}). {spec['good_player']} Bot defended with {card.title}"


def test_the_echo_position_has_the_documented_knowledge_and_probability():
    game = build("raptors_liz_t2_echo_feint", make_ai("heuristic"))
    liz = game.players[1]
    assert sorted(c.title for c in game.players[0].known.cards(liz)) == ["Fireball", "Flame Lash"]
    assert len(liz.hand) == 5 and game.fighters["liz"].hp == 12
    p = kill_probability(game, game.fighters["liz"], game.fighters["echo"])
    assert 0.10 < p < 0.12, f"3 unknown cards from 27 with one Incinerate: 3/27 = 11.1 %, got {p:.1%}"


@pytest.mark.parametrize("name, ai_kind", [case(n, k) for n in
                                          ("liz_raptors_t6_back_and_forth", "liz_raptors_t14_back_and_forth", "liz_raptors_t20_back_and_forth") for k in AIS])
def test_liz_does_not_maneuver_twice_to_stay_where_she_is(name, ai_kind):
    ai = make_ai(ai_kind)
    game = build(name, ai)
    start = game.hero(0).pos
    acts = play_turn(ai, game, limit=POSITIONS[name]["actions_left"])
    net = game.board.distance(start, game.hero(0).pos)
    assert not (len(acts) == 2 and all(a["kind"] == "maneuver" for a in acts) and net <= 1), f"{POSITIONS[name]['good_player']} Bot did {acts}"
