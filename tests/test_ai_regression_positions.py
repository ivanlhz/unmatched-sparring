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


# ---------- the evaluation of F-AI-EVAL-RESOLUTION (`ai_eval` = RESOLUTION) on the positions of the live games of 17/11 ----------
# One test per position: the bot plays its turn with the ISMCTS at a fixed number of iterations from `SEEDS` different seeds and must do what
# the position asks in at least `NEEDED` of them (a single seed is noise; a per-seed xfail hid regressions).
SEEDS = tuple(range(8))
NEEDED = 6


def play_new_eval_turn(name: str, seed: int):
    """The bot's turn from the position, action by action: (game, actions, maneuvers that left the hero where he was with the hand at the limit)."""
    ai = make_ai("ismcts", seed=seed, new_eval=True)
    game = build(name, ai)
    acts, idle = [], 0
    while game.actions_left > 0 and game.winner is None and len(acts) < POSITIONS[name]["actions_left"]:
        act = ai.plan(game)
        acts.append(describe_act(act))
        pos, held = game.hero(0).pos, len(game.players[0].hand)
        ai.execute(game, act)
        idle += acts[-1]["kind"] == "maneuver" and game.hero(0).pos == pos and held >= game.hand_cap(0)
    return game, acts, idle


def attacks(game, acts, idle):
    return any(a["kind"] == "attack" for a in acts)


def keeps_a_card(game, acts, idle):
    return bool(game.players[0].hand)


def attacks_first(game, acts, idle):
    return acts[0]["kind"] == "attack"


def does_not_stay_put_twice(game, acts, idle):
    return idle <= 1


def does_not_end_where_it_began(game, acts, idle):
    return not (len(acts) == 2 and all(a["kind"] == "maneuver" for a in acts) and game.board.distance(game.start_pos, game.hero(0).pos) <= 1)


def attacks_and_keeps_a_card(game, acts, idle):
    return attacks(game, acts, idle) and keeps_a_card(game, acts, idle)


# position -> what a good player does there (the numbers behind each are in the fixture's `good_player`)
NEW_EVAL_POSITIONS = {
    "sinbad_liz_t4_idle_maneuvers": does_not_stay_put_twice,
    "sinbad_liz_t6_flees_from_an_attack": attacks,
    "sinbad_liz_t18_idle_maneuvers": does_not_end_where_it_began,
    "sinbad_liz_t24_attacks": attacks_first,
    "liz_sinbad_t13_last_card": keeps_a_card,
    "liz_sinbad_t15_incinerate": keeps_a_card,
    "liz_sinbad_t3_attacks_with_fireball": attacks_and_keeps_a_card,
    "medusa_hellboy_sim_t10_attacks": attacks,
    "hellboy_liz_sim_t8_attacks": attacks,
}


def new_eval_passes(name: str) -> tuple[int, list]:
    check, passed, seen = NEW_EVAL_POSITIONS[name], 0, []
    for seed in SEEDS:
        game, acts, idle = play_new_eval_turn(name, seed)
        game.start_pos = build(name, make_ai("heuristic")).hero(0).pos
        ok = check(game, acts, idle)
        passed += ok
        seen.append((seed, ok, [a["kind"] + (":" + str(a.get("card") or a.get("boost")) if a.get("card") or a.get("boost") else "") for a in acts]))
    return passed, seen


@pytest.mark.parametrize("name", list(NEW_EVAL_POSITIONS))
def test_the_new_evaluation_does_what_the_live_position_asks(name):
    passed, seen = new_eval_passes(name)
    assert passed >= NEEDED, f"{POSITIONS[name]['good_player']} {passed}/{len(SEEDS)} seeds do it: {seen}"


def test_the_sinbad_positions_are_the_live_ones():
    """The counts the decision journal of that game gives for each position (hand, deck and pile of the bot; hand, deck and pile of Liz), so a
    change of the fixture builder cannot move them quietly. VOYAGE cards in the bot's pile: 0, 2, 4, 4, 1."""
    expected = {"sinbad_liz_t4_idle_maneuvers": ((7, 20, 3), (7, 20, 3), 0), "sinbad_liz_t6_flees_from_an_attack": ((6, 18, 6), (7, 18, 5), 2),
                "sinbad_liz_t18_idle_maneuvers": ((4, 6, 20), (4, 9, 17), 4), "sinbad_liz_t24_attacks": ((5, 0, 25), (4, 4, 22), 4),
                "sinbad_liz_t25_defends_with_exploit": ((7, 0, 23), (2, 6, 22), 1)}
    for name, (mine, hers, voyages) in expected.items():
        me, liz = build(name, make_ai("heuristic")).players
        assert [(len(p.hand), len(p.deck), len(p.discard)) for p in (me, liz)] == [mine, hers], name
        assert sum("voyage" in c.tags for c in me.discard) == voyages, name


# ---------- turn 17 of the live game of 17/11 18:53 (Sinbad bot vs Liz): the only card that can defend is spent as a maneuver boost ----------
def keeps_a_defender(game, acts, idle):
    """The hero ends the turn with a card that can defend and that he may use (By Fortune and Fate needs the dead Porter). Measured after
    `Game.end_turn()`: the hand-limit discard (7) belongs to the turn, and the bot's own chooser decides it."""
    game.end_turn()
    hero = game.hero(0)
    return any(c.can_defend and c.usable_by(hero.name) for c in game.players[0].hand)


KEEP_A_DEFENDER = ("sinbad_liz_t17_keeps_regroup_scheme", "sinbad_liz_t17_keeps_regroup_boost")


@pytest.mark.xfail(strict=False, raises=AssertionError, reason=(
    "Live game 17/11 18:53, turn 17: the bot loses Regroup, the only card of its hand that can defend, and takes 1 + 3 damage with no defence on "
    "Liz's turn. Two causes. (1) The boost: the tree is only offered [no boost, the top/cheapest boost] (`_boost_variants`) and `card_worth` "
    "(adapter.py:179) ranks the dead By Fortune and Fate (3.5) above Regroup (1.5), so the dead card is never the boost (2 of 8 seeds spend "
    "Regroup there). (2) The hand limit: even without the boost the hand holds 9 and the end-of-turn discard to 7 throws Regroup away, "
    "because both choosers rank it the cheapest card: the in-tree `SearchController.choose_discard` (adapter.py:430-431, by `card_worth`) "
    "and the real one, `MedusaAI.choose_discard` (ai_medusa.py:1724, by `keep`/`keep_value`, which puts Regroup at 1.45 against 1.5 of a "
    "Voyage); both branches of the tree end with the same 7-card hand, hence their near-equal values. After `end_turn` no seed keeps a "
    "defender (0/8 on both positions, eval=new and eval=old)."))
@pytest.mark.parametrize("name", KEEP_A_DEFENDER)
def test_the_bot_does_not_lose_its_only_defence_card_in_the_turn(name):
    """Every seed must keep it, after the hand-limit discard: a good player neither boosts the maneuver with Regroup (the only possible
    boosts are Regroup and the dead By Fortune and Fate: the Voyages have boost 0, `can_be_boost`) nor discards it at the limit, where
    Voyage cards or By Fortune and Fate go first."""
    ok = [keeps_a_defender(*play_new_eval_turn(name, seed)) for seed in SEEDS]
    assert all(ok), f"{POSITIONS[name]['good_player']} {sum(ok)}/{len(SEEDS)} seeds keep a card that can defend: {ok}"


def test_the_t17_positions_are_the_live_ones():
    """The counts of the decision journal (decisions 25 and 26 of the game of 18:53): hand, deck and pile of the bot; hand, deck and pile of Liz."""
    expected = {"sinbad_liz_t17_keeps_regroup_scheme": ((6, 10, 14), (5, 12, 13)), "sinbad_liz_t17_keeps_regroup_boost": ((8, 7, 15), (5, 12, 13))}
    for name, (mine, hers) in expected.items():
        game = build(name, make_ai("heuristic"))
        assert [(len(p.hand), len(p.deck), len(p.discard)) for p in game.players] == [mine, hers], name
        assert not game.fighters["porter"].alive and game.fighters["sinbad"].hp == 7 and game.fighters["liz"].hp == 4


# ---------- turns 12 and 14 of the live game of 17/11 20:26 (Liz bot vs Sinbad): maneuvers in near ties with an attack available ----------
# INFORMATIONAL positions: no behaviour is asserted. Attacking was not shown to be better (see `good_player` in the fixture): the attacks in hand are
# defence cards played as attacks (Burning Barrier, Pyrotechnics) or Flame Lash, Sinbad has 13-14 HP, and continuing both sides with the new evaluation
# from a forced first action gives Liz 0.13 (attack) against 0.21 (maneuver) at T14 and 0.21 against 0.19 at T12, inside the noise (n ~ 20, +-0.09).
# What the positions do give: with eval=new at 300 iterations Liz attacks in 5/8 (T12) and 6/8 (T14) seeds, at 3 s in 3/8 and 6/8, mostly
# by maneuvering first and attacking with the Incinerate it draws; a criterion "attacks at least once" would be invented, not measured.
def test_the_t12_and_t14_liz_positions_are_the_live_ones():
    """The counts of the decision journal of the game of 20:26 (decisions 16, 19 and 20): hand, deck and pile of Liz (the bot); hand, deck and pile of
    Sinbad; VOYAGE cards in his pile (they give his attacks and maneuvers their bonus: 2 until Voyage Home returned them at T13, then 1); hit points."""
    expected = {"liz_sinbad_t12_maneuver_over_attack": ((4, 16, 10), (6, 15, 9), 2, (11, 14)),
                "liz_sinbad_t14_maneuver_over_attack": ((4, 15, 11), (7, 14, 9), 1, (10, 13)),
                "liz_sinbad_t14_second_action_maneuver_over_attack": ((5, 14, 11), (7, 14, 9), 1, (10, 13))}
    for name, (mine, his, voyages, hp) in expected.items():
        game = build(name, make_ai("heuristic"))
        assert [(len(p.hand), len(p.deck), len(p.discard)) for p in game.players] == [mine, his], name
        assert sum("voyage" in c.tags for c in game.players[1].discard) == voyages, name
        assert (game.hero(0).hp, game.hero(1).hp) == hp and not game.fighters["porter"].alive, name
