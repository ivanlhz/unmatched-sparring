"""Differential harness: the production resolve_combat must behave exactly like the frozen pre-refactor copy
(tests/legacy_combat.py), both over whole simulated games and over hand-built scenarios.

Since D1 (the bot) and E2 (the human) every box hero resolves its cards through the interpreter (not
byte-identical to the legacy path, by design: tests/test_d1_bot_cards.py and tests/test_e2_human_cards.py pin the
new behaviour), so this oracle runs on the legacy rig of tests/legacy_medusa.py (nothing interpreted, the legacy
rules in force): it guards the CombatFlow machinery itself (phases, boosts, cancellations, the record kept).

DIFF_SEEDS=10 widens the simulated games (default 3 seeds per hero pair)."""
import itertools
import json
import os

import pytest

import legacy_combat
from conftest import Scripted, give, place
from legacy_medusa import legacy
from sparring import combat, persist, sim
from sparring.board import Board
from sparring.heroes import load_hero
from sparring.state import Game, RuleError

SLUGS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
PAIRS = [("medusa", human) for human in SLUGS[1:]]
SEEDS = range(int(os.environ.get("DIFF_SEEDS", 3)))
REAL_RESOLVE = combat.resolve_combat


def card_id(card):
    return None if card is None else card.card_id


MEDUSA_TITLES = {c.title for c in load_hero("medusa").deck()}


def result_record(res):
    """`applied` without the narrator's lines for Medusa's cards (D3: the bot narrates them; the legacy oracle never did)."""
    applied = [a for a in res.applied if a.split(": ", 1)[0] not in MEDUSA_TITLES]
    return {"attacker": res.attacker, "target": res.target, "atk_card": card_id(res.atk_card),
            "def_card": card_id(res.def_card), "atk_value": res.atk_value, "def_value": res.def_value,
            "damage": res.damage, "attacker_won": res.attacker_won, "cancelled": sorted(res.cancelled),
            "boost_card": card_id(res.boost_card), "human_effects": res.human_effects, "atk_parts": res.atk_parts,
            "def_parts": res.def_parts, "applied": applied, "bot_notes": res.bot_notes}


def recording(resolve, records):
    def wrapper(game, att, tgt, atk_card, def_card, values=(0, 0), boost=None):
        try:
            res = resolve(game, att, tgt, atk_card, def_card, values, boost)
        except RuleError as e:
            records.append({"error": str(e), "game": persist.game_to_dict(game), "log": list(game.log)})
            raise
        records.append({"result": result_record(res), "game": persist.game_to_dict(game), "log": list(game.log)})
        return res
    return wrapper


def play_with(monkeypatch, resolve, seed, bot, human):
    records, trace = [], []
    with monkeypatch.context() as m:
        m.setattr(combat, "resolve_combat", recording(resolve, records))
        outcome = sim.play(seed, bot_hero=bot, human_hero=human, trace=trace)
    return outcome, trace, records


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("bot,human", PAIRS)
def test_flow_matches_legacy_on_all_hero_pairs(monkeypatch, bot, human, seed):
    with legacy(monkeypatch):
        now = play_with(monkeypatch, REAL_RESOLVE, seed, bot, human)
        old = play_with(monkeypatch, legacy_combat.resolve_combat, seed, bot, human)
    assert now[0] == old[0]
    assert now[1] == old[1]
    assert len(now[2]) == len(old[2])
    for i, (a, b) in enumerate(zip(now[2], old[2])):
        assert a == b, f"combat #{i} differs"


# ---------- hand-built scenarios on twin games ----------
def make_game():
    """Same rig as the `game` fixture: Medusa = player 0 (bot), Hellboy = player 1, empty hands."""
    ctl = {0: Scripted(), 1: Scripted()}
    g = Game.new(Board.load("bprd-hq"), seed=3, controllers=ctl)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    place(g, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return g


def fill_destiny(g, n):
    g.players[1].discard = [c for c in g.players[1].full_set if c.destiny][:n]


def boost_card(g, player, title="Service Pistol"):
    return give(g, player, title)


def sc_planned_cancels_medusa_second_shot(g):
    g.controllers[0].boost = boost_card(g, 0, "Gaze of Stone")
    return "medusa", "hellboy", give(g, 0, "Second Shot"), give(g, 1, "Planned Recklessness"), (0, 0), None


def sc_feint_cancels_lobster_second_shot(g):
    place(g, lobster=1)
    return "lobster", "medusa", give(g, 1, "Second Shot"), give(g, 0, "Feint"), (0, 0), boost_card(g, 1)


def sc_second_shot_boosts_uncancelled(g):
    g.controllers[0].boost = boost_card(g, 0, "Gaze of Stone")
    return "medusa", "hellboy", give(g, 0, "Second Shot"), None, (1, 2), None


def sc_second_shot_bot_declines(g):
    return "medusa", "hellboy", give(g, 0, "Second Shot"), None, (0, 0), None


def sc_planned_defends_outside_anung(g):
    return "medusa", "hellboy", give(g, 0, "Gaze of Stone"), give(g, 1, "Planned Recklessness"), (0, 0), None


def sc_planned_defends_in_anung(g):
    fill_destiny(g, 6)
    return "medusa", "hellboy", give(g, 0, "Gaze of Stone"), give(g, 1, "Planned Recklessness"), (0, 0), None


def sc_planned_attacks_outside_anung(g):
    g.turn = 1
    return "hellboy", "medusa", give(g, 1, "Planned Recklessness"), give(g, 0, "Snipe"), (0, 0), None


def sc_planned_attacks_in_anung(g):
    fill_destiny(g, 6)
    g.turn = 1
    return "hellboy", "medusa", give(g, 1, "Planned Recklessness"), give(g, 0, "Snipe"), (0, 0), None


def sc_planned_vs_feint_defender_first(g):
    return "medusa", "hellboy", give(g, 0, "Feint"), give(g, 1, "Planned Recklessness"), (0, 0), None


def sc_on_earth_not_cancelled(g):
    fill_destiny(g, 4)
    return "medusa", "hellboy", give(g, 0, "Second Shot"), give(g, 1, "On Earth As It Is In Hell"), (0, 2), None


def sc_on_earth_cancelled(g):
    fill_destiny(g, 4)
    return "medusa", "hellboy", give(g, 0, "Feint"), give(g, 1, "On Earth As It Is In Hell"), (0, 2), None


def sc_flame_lash_deck_boost_zero(g):
    lash = give(g, 1, "Second Shot")
    object.__setattr__(lash, "title", "Flame Lash")
    object.__setattr__(lash, "text", "DURING COMBAT: Discard the bottom card of your deck. Add its BOOST value to "
                       "this card's value. AFTER COMBAT: Gain 1 action.")
    place(g, lobster=1)
    zero = give(g, 1, "Service Pistol")
    object.__setattr__(zero, "boost", 0)
    g.turn = 1
    return "lobster", "medusa", lash, None, (0, 0), zero


def sc_boost_without_boost_value_is_a_rule_error(g):
    place(g, lobster=1)
    nothing = give(g, 1, "Service Pistol")
    object.__setattr__(nothing, "boost", 0)
    g.turn = 1
    return "lobster", "medusa", give(g, 1, "Second Shot"), None, (0, 0), nothing


def sc_damage_kills_so_after_is_skipped(g):
    g.fighters["hellboy"].hp = 1
    return "medusa", "hellboy", give(g, 0, "Gaze of Stone"), give(g, 1, "Glimpse Of Hell"), (3, 0), None


def sc_gaze_kills_in_after(g):
    g.fighters["hellboy"].hp = 8
    return "medusa", "hellboy", give(g, 0, "Gaze of Stone"), give(g, 1, "Glimpse Of Hell"), (0, 3), None


def sc_death_mid_after_does_not_stop_the_attacker(g):
    g.fighters["medusa"].hp = 1
    place(g, harpy1=1)
    g.turn = 1
    return "hellboy", "medusa", give(g, 1, "Horseshoes And Hand Grenades"), give(g, 0, "Dash"), (0, 0), None


def sc_fight_or_flight_on_the_defender(g):
    g.add_combat_bonus(1, 1, combat.FIGHT_OR_FLIGHT)
    return "medusa", "hellboy", give(g, 0, "Snipe"), give(g, 1, "Glimpse Of Hell"), (0, 0), None


def sc_fight_or_flight_on_a_cancelled_on_earth(g):
    g.add_combat_bonus(1, 1, combat.FIGHT_OR_FLIGHT)
    fill_destiny(g, 3)
    return "medusa", "hellboy", give(g, 0, "Feint"), give(g, 1, "On Earth As It Is In Hell"), (0, 0), None


def sc_fight_or_flight_without_defense_card(g):
    g.add_combat_bonus(1, 1, combat.FIGHT_OR_FLIGHT)
    return "medusa", "hellboy", give(g, 0, "Snipe"), None, (0, 0), None


def sc_medusa_after_effects_with_human_notes(g):
    return "medusa", "hellboy", give(g, 0, "Clutching Claws"), give(g, 1, "Confront Any Demon or God"), (0, 0), None


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("sc_")]


def run_scenario(build, resolve):
    g = make_game()
    fa, ft, atk, dfn, values, boost = build(g)
    try:
        res = resolve(g, g.fighters[fa], g.fighters[ft], atk, dfn, values, boost)
        outcome = {"result": result_record(res)}
    except RuleError as e:
        outcome = {"error": str(e)}
    outcome.update(game=persist.game_to_dict(g), log=list(g.log), bot=g.bot_player)
    return json.loads(json.dumps(outcome, default=str))


@pytest.mark.parametrize("build", SCENARIOS, ids=lambda f: f.__name__)
def test_scenario_matches_legacy(monkeypatch, build):
    with legacy(monkeypatch):
        assert run_scenario(build, REAL_RESOLVE) == run_scenario(build, legacy_combat.resolve_combat)


def test_the_scenarios_actually_exercise_the_branches(monkeypatch):
    """Guards the harness against vacuous scenarios: the interesting outcomes really happen."""
    with legacy(monkeypatch):
        out = {f.__name__: run_scenario(f, legacy_combat.resolve_combat) for f in SCENARIOS}
    assert "error" in out["sc_boost_without_boost_value_is_a_rule_error"]
    assert out["sc_planned_cancels_medusa_second_shot"]["result"]["cancelled"] == ["atk"]
    assert out["sc_planned_cancels_medusa_second_shot"]["result"]["boost_card"] is None
    assert out["sc_second_shot_boosts_uncancelled"]["result"]["boost_card"] is not None
    assert out["sc_flame_lash_deck_boost_zero"]["result"]["boost_card"] is not None
    assert out["sc_planned_defends_in_anung"]["result"]["cancelled"] == []
    assert out["sc_planned_defends_outside_anung"]["result"]["cancelled"] == ["atk"]
    assert out["sc_damage_kills_so_after_is_skipped"]["game"]["winner"] is not None
