"""C5 differential: Medusa through the effects interpreter behaves exactly like the pre-C5 engine.

The oracle is tests/legacy_medusa.py (verbatim copies of the deleted code, installed by `legacy(monkeypatch)`): under
it games are built with Medusa out of `fx.dsl_heroes`, her legacy combat rules and `Game.play_scheme` /
`Game.use_ability` are the old ones. Checked here:
  * whole simulated games (heuristic bot and ISMCTS bot), turn by turn: logs, saves (rng included) and outcomes;
  * the goldens: the legacy engine reproduces tests/golden/*.json byte for byte (test_golden.py checks the
    interpreter does), FakeTTS transcripts and saves included;
  * per-card twins: the same scenario on two games, legacy and DSL, same final save, log, combat result and the
    same controller calls in the same order (the rng is only touched through those).
Since D3 (Ivan, 29/10) the bot also narrates Medusa's cards in the chat (`effects/narrate.py`: "Dash: medusa moves to
3"); the legacy engine never did, so the oracles compare `applied` and the chat with those lines removed
(`without_narration`), and nothing else.
The one ruled divergence (Ivan, 28/10): Winged Frenzy's return of a defeated Harpy is mandatory. The legacy engine
let `choose_placement` answer None and left the Harpy dead; the interpreter returns it anyway. `test_frenzy_return_is_mandatory_the_only_divergence`
pins exactly that, nothing else differs."""
from __future__ import annotations

import json

import pytest

from conftest import Scripted, give, place
from legacy_medusa import legacy
from sparring import persist, sim
from sparring.ai_medusa import GAZE, MedusaAI
from sparring.board import Board
from sparring.effects.model import EFFECTS_DIR, walk_ops
from sparring.effects.ops_core import OPS, PENDING_PHASES
from sparring.effects.state import INTERPRETED_HEROES
from sparring.hellboy_script import ScriptedHellboy
from sparring.heroes import load_hero
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from sparring.state import Game
from test_batch import brig, click  # noqa: F401
from test_combat_flow_diff import result_record
from test_golden import GOLDEN, SIM_GAMES, jsonable, midgame, transcript
from test_session import human_plays, rig, set_bot_hand  # noqa: F401

BOARDS = {key: Board.load(key) for key in ("bprd-hq", "azuchi-castle")}
BOX = INTERPRETED_HEROES - {"medusa"}
MEDUSA_TITLES = {c.title for c in load_hero("medusa").deck()}


def is_narration(line: str) -> bool:
    """A chat / `applied` line of the narrator for a Medusa card ("Dash: ..." or "Aplicado: Dash: ...")."""
    return line.removeprefix("Aplicado: ").split(": ", 1)[0] in MEDUSA_TITLES


def without_narration(out: dict) -> dict:
    """The same transcript or twin record with the narrator's lines (and only those) removed from the chat and
    from `applied`, so the legacy engine, which never narrated, can be compared with it."""
    out = jsonable(out)
    for step in out.get("steps", []):
        step["said"] = [m for m in step["said"] if not is_narration(m)]
    result = out.get("result")
    if isinstance(result, dict):
        result["applied"] = [a for a in result["applied"] if not is_narration(a)]
    return out


# ---------------------------------------------------------------- whole games

def play_turns(seed, board_key, bot=None, max_turns=200):
    """sim.play's loop, keeping what every turn left behind: the engine log and the full save (rng included)."""
    controllers = {0: bot or MedusaAI(0), 1: ScriptedHellboy(1, seed)}
    game = Game.new(BOARDS[board_key], seed, controllers, bot_player=0)
    turns = []
    while game.winner is None and game.turn_no <= max_turns:
        game.begin_turn()
        controllers[game.turn].take_turn(game)
        turns.append({"log": list(game.log), "save": jsonable(persist.game_to_dict(game))})
        game.log.clear()
        if game.winner is None:
            game.end_turn()
    return turns, game.winner


@pytest.mark.parametrize("board_key,seed", SIM_GAMES + [("bprd-hq", s) for s in range(6, 12)])
def test_heuristic_games_are_identical_turn_by_turn(monkeypatch, board_key, seed):
    with legacy(monkeypatch, keep=BOX):           # only Medusa leaves the interpreter: Hellboy stays in (E2)
        old = play_turns(seed, board_key)
    new = play_turns(seed, board_key)
    assert new[1] == old[1] and len(new[0]) == len(old[0])
    for i, (a, b) in enumerate(zip(new[0], old[0])):
        assert a == b, f"turn {i + 1} differs"


def ismcts_bot():
    return IsmctsMedusa(0, SearchConfig(time_budget=60.0, iterations=6, seed=0))


@pytest.mark.parametrize("seed", [0, 1])
def test_ismcts_games_are_identical_turn_by_turn(monkeypatch, seed):
    with legacy(monkeypatch, keep=BOX):
        old = play_turns(seed, "bprd-hq", ismcts_bot(), max_turns=14)
    new = play_turns(seed, "bprd-hq", ismcts_bot(), max_turns=14)
    assert new[1] == old[1] and len(new[0]) == len(old[0])
    for i, (a, b) in enumerate(zip(new[0], old[0])):
        assert a == b, f"turn {i + 1} differs"


# ---------------------------------------------------------------- the goldens under the legacy engine
# The live goldens moved with E2 (the human's Hellboy is interpreted); the pre-E2 ones the legacy engine reproduces
# are kept under tests/golden/legacy/: they run the old engine under the current AI, so the shared AI moves these
# goldens whenever it changes and they are regenerated with it (engine equivalence is held by the turn-by-turn diffs).

def golden(name):
    return json.loads((GOLDEN / "legacy" / name).read_text(encoding="utf-8"))


def test_legacy_engine_reproduces_the_simulator_golden(monkeypatch):
    with legacy(monkeypatch):
        out = {}
        for board, seed in SIM_GAMES:
            trace = []
            o = sim.play(seed, board, trace=trace)
            out[f"{board}/{seed}"] = {"winner": o.winner, "turns": o.turns, "medusa_hp": o.medusa_hp,
                                      "hellboy_hp": o.hellboy_hp, "trace": trace}
    assert jsonable(out) == golden("sim.json")


def test_legacy_engine_reproduces_the_game_save_golden(monkeypatch, bprd):
    with legacy(monkeypatch):
        saved = jsonable(persist.game_to_dict(midgame(bprd)))
    assert saved == golden("game_save.json")


def test_legacy_engine_reproduces_the_batch_session_golden(monkeypatch, request):
    with legacy(monkeypatch):
        session, table, game, _ = request.getfixturevalue("brig")
        assert game.fx.dsl_heroes == set()
        out = transcript(session, table, game, lambda e, p: click(session, table, e, p))
    assert without_narration(out) == without_narration(golden("session_batch.json"))


def test_legacy_engine_reproduces_the_classic_session_golden(monkeypatch, request):
    import dataclasses
    with legacy(monkeypatch):
        session, table, game = request.getfixturevalue("rig")
        session.cfg = dataclasses.replace(session.cfg, batch=False, live_ui=False)
        session.broadcast = False
        set_bot_hand(table, game, "Snipe", "Dash")
        session.read_bot_hand()
        out = transcript(session, table, game, lambda e, p: session.handle(e, p))
    assert without_narration(out) == without_narration(golden("session_classic.json"))


# ---------------------------------------------------------------- per-card twins

class Recording(Scripted):
    """Every decision the engine delegates, in order: the differential of the controller calls (the only place
    where the rng and the heuristics are consulted)."""

    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    def choose_defense(self, game, attacker, target):
        self.calls.append(("defense", attacker.fid, target.fid))
        return super().choose_defense(game, attacker, target)

    def choose_combat_boost(self, game, ctx):
        self.calls.append(("boost", ctx.attacker.fid, ctx.atk_value, ctx.def_value))
        return super().choose_combat_boost(game, ctx)

    def choose_discard(self, game, player, n, reason):
        self.calls.append(("discard", player, n, reason))
        return super().choose_discard(game, player, n, reason)

    def choose_move(self, game, fighter, steps, through_enemies=False):
        self.calls.append(("move", fighter.fid, steps, through_enemies, fighter.pos))
        return super().choose_move(game, fighter, steps, through_enemies)

    def choose_placement(self, game, fighter, options):
        self.calls.append(("placement", fighter.fid, list(options)))
        return super().choose_placement(game, fighter, options)


def twin():
    """Medusa = player 0 (bot), Hellboy = player 1, Medusa's turn, empty hands, everybody out of each other's way."""
    calls = []
    ctl = {0: Recording(calls), 1: Recording(calls)}
    g = Game.new(BOARDS["bprd-hq"], seed=3, controllers=ctl)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    place(g, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return g, ctl, calls


def kill(g, fid):
    f = g.fighters[fid]
    f.died_at, f.alive, f.pos, f.hp = f.pos, False, None, 0


def attack(g, att, tgt, atk_title, def_title=None, values=(0, 0)):
    return g.attack(g.fighters[att], g.fighters[tgt], give(g, g.fighters[att].owner, atk_title),
                    give(g, g.fighters[tgt].owner, def_title) if def_title else None, values)


# ---- combat cards (what each returns is the CombatResult or None)
def sc_second_shot_boosted(g, ctl):
    ctl[0].boost = give(g, 0, "Gaze of Stone")
    return attack(g, "medusa", "hellboy", "Second Shot", "Confront Any Demon or God")


def sc_second_shot_without_boost(g, ctl):
    return attack(g, "medusa", "hellboy", "Second Shot")


def sc_second_shot_cancelled_by_planned_recklessness(g, ctl):
    ctl[0].boost = give(g, 0, "Gaze of Stone")
    return attack(g, "medusa", "hellboy", "Second Shot", "Planned Recklessness")


def sc_gaze_of_stone_won(g, ctl):
    return attack(g, "medusa", "hellboy", "Gaze of Stone", values=(5, 0))


def sc_gaze_of_stone_won_against_a_fighter_the_combat_already_killed(g, ctl):
    place(g, lobster=4)
    return attack(g, "medusa", "lobster", "Gaze of Stone", values=(5, 0))


def sc_gaze_of_stone_lost(g, ctl):
    return attack(g, "medusa", "hellboy", "Gaze of Stone", "Confront Any Demon or God", values=(0, 6))


def sc_gaze_of_stone_shielded_by_planned_recklessness(g, ctl):
    g.players[1].discard += [c for c in g.players[1].full_set if c.destiny][:6]     # ANUNG: Planned does not cancel
    return attack(g, "medusa", "hellboy", "Gaze of Stone", "Planned Recklessness", values=(5, 0))


def sc_regroup_won(g, ctl):
    return attack(g, "medusa", "hellboy", "Regroup", values=(4, 0))


def sc_regroup_lost(g, ctl):
    return attack(g, "medusa", "hellboy", "Regroup", "Confront Any Demon or God")


def sc_snipe_draws_from_an_empty_deck(g, ctl):
    g.players[0].deck.clear()
    return attack(g, "medusa", "hellboy", "Snipe")


def sc_dash_moves(g, ctl):
    ctl[0].moves["medusa"] = 3
    return attack(g, "medusa", "hellboy", "Dash")


def sc_dash_stays(g, ctl):
    return attack(g, "medusa", "hellboy", "Dash")


def sc_dash_in_defense_of_a_dying_medusa(g, ctl):
    g.fighters["medusa"].hp = 2
    ctl[0].moves["medusa"] = 3
    return attack(g, "hellboy", "medusa", "Service Pistol", "Dash", values=(3, 0))


def sc_feint_cancels_the_defense(g, ctl):
    g.fighters["hellboy"].hp = 10                    # On Earth would heal 2 after a lost combat: cancelled
    return attack(g, "medusa", "hellboy", "Feint", "On Earth As It Is In Hell")


def sc_feint_against_no_card(g, ctl):
    return attack(g, "medusa", "hellboy", "Feint")


def sc_defending_feint_cancels_the_attack(g, ctl):
    place(g, lobster=2)
    return attack(g, "hellboy", "medusa", "Horseshoes And Hand Grenades", "Feint")


def sc_hounds_move_the_harpies_in_fid_order(g, ctl):
    place(g, harpy1=2, harpy2=3, harpy3=4)
    ctl[0].moves.update({"harpy1": 6, "harpy2": 2, "harpy3": 3})     # 2 and 3 are free only once the earlier ones left
    return attack(g, "harpy1", "hellboy", "The Hounds of Mighty Zeus")


def sc_hounds_with_a_dead_harpy(g, ctl):
    place(g, harpy1=2, harpy2=3)
    kill(g, "harpy3")
    ctl[0].moves.update({"harpy1": 6, "harpy2": 5})
    return attack(g, "harpy1", "hellboy", "The Hounds of Mighty Zeus")


def sc_clutching_claws_opponent_discards(g, ctl):
    place(g, harpy1=2)
    g.players[1].hand += g.players[1].deck[:3]
    ctl[1].discards = [g.players[1].hand[0]]
    return attack(g, "harpy1", "hellboy", "Clutching Claws")


def sc_hiss_and_slither_in_defense(g, ctl):
    g.players[1].hand += g.players[1].deck[:2]
    return attack(g, "hellboy", "medusa", "Service Pistol", "Hiss and Slither")


def sc_clutching_claws_against_an_empty_hand(g, ctl):
    place(g, harpy1=2)
    return attack(g, "harpy1", "hellboy", "Clutching Claws")


# ---- schemes and the ability (return None)
def sc_glance_hits_the_enemy_hero(g, ctl):
    g.play_scheme(0, g.hero(0), give(g, 0, "A Momentary Glance"), target=g.fighters["hellboy"])


def sc_glance_hits_an_own_harpy(g, ctl):
    place(g, harpy1=2)
    g.play_scheme(0, g.hero(0), give(g, 0, "A Momentary Glance"), target=g.fighters["harpy1"])


def sc_glance_hits_medusa_herself(g, ctl):
    g.play_scheme(0, g.hero(0), give(g, 0, "A Momentary Glance"), target=g.fighters["medusa"])


def sc_frenzy_moves_everybody_and_returns_a_harpy(g, ctl):
    place(g, harpy1=2, harpy2=3)
    kill(g, "harpy3")
    # fid order: harpy1 leaves 2, harpy2 takes it, then Medusa takes 3 (free only because harpy2 left first)
    ctl[0].moves.update({"harpy1": 5, "harpy2": 2, "medusa": 3})
    ctl[0].placement = 4
    g.play_scheme(0, g.hero(0), give(g, 0, "Winged Frenzy"))


def sc_frenzy_moves_through_enemies(g, ctl):
    place(g, lobster=4, harpy1=2)
    ctl[0].moves.update({"harpy1": 5})           # 2 -> 4 (Lobster) -> 5: only through an opposing fighter
    g.play_scheme(0, g.hero(0), give(g, 0, "Winged Frenzy"))


def sc_frenzy_without_a_dead_harpy(g, ctl):
    ctl[0].moves.update({"medusa": 3})
    g.play_scheme(0, g.hero(0), give(g, 0, "Winged Frenzy"))


def sc_frenzy_returns_the_first_dead_harpy(g, ctl):
    kill(g, "harpy2")
    kill(g, "harpy3")
    g.play_scheme(0, g.hero(0), give(g, 0, "Winged Frenzy"))


def sc_gaze_ability_on_the_hero(g, ctl):
    g.use_ability(0, GAZE, g.fighters["hellboy"])


def sc_gaze_ability_kills_lobster(g, ctl):
    place(g, lobster=2)
    g.fighters["lobster"].hp = 1
    g.use_ability(0, GAZE, g.fighters["lobster"])


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("sc_")]


def run_twin(build):
    g, ctl, calls = twin()
    res = build(g, ctl)
    out = {"game": persist.game_to_dict(g), "log": list(g.log), "calls": calls,
           "result": None if res is None else result_record(res)}
    return without_narration(out)


@pytest.mark.parametrize("build", SCENARIOS, ids=lambda f: f.__name__)
def test_each_card_twin_matches_legacy(monkeypatch, build):
    with legacy(monkeypatch, keep=BOX):
        old = run_twin(build)
    assert run_twin(build) == old


def test_the_twins_actually_exercise_the_branches(monkeypatch):
    with legacy(monkeypatch, keep=BOX):
        out = {f.__name__: run_twin(f) for f in SCENARIOS}
    fighters = lambda name: out[name]["game"]["fighters"]
    assert out["sc_second_shot_boosted"]["result"]["boost_card"] is not None
    assert out["sc_second_shot_cancelled_by_planned_recklessness"]["result"]["cancelled"] == ["atk"]
    assert fighters("sc_gaze_of_stone_won")["hellboy"]["hp"] == 18 - 7 - 8
    assert fighters("sc_gaze_of_stone_won_against_a_fighter_the_combat_already_killed")["lobster"]["alive"] is False
    assert fighters("sc_gaze_of_stone_lost")["hellboy"]["hp"] == 18
    assert fighters("sc_gaze_of_stone_shielded_by_planned_recklessness")["hellboy"]["hp"] == 18 - 4
    assert len(out["sc_regroup_won"]["game"]["players"][0]["hand"]) == 2
    assert len(out["sc_regroup_lost"]["game"]["players"][0]["hand"]) == 1
    assert fighters("sc_snipe_draws_from_an_empty_deck")["medusa"]["hp"] == 14
    assert fighters("sc_dash_moves")["medusa"]["pos"] == 3 and fighters("sc_dash_stays")["medusa"]["pos"] == 0
    assert fighters("sc_dash_in_defense_of_a_dying_medusa")["medusa"]["alive"] is False
    assert out["sc_feint_cancels_the_defense"]["result"]["cancelled"] == ["def"]
    assert fighters("sc_feint_cancels_the_defense")["hellboy"]["hp"] == 10 - 2
    assert out["sc_feint_against_no_card"]["result"]["cancelled"] == ["def"]
    assert out["sc_defending_feint_cancels_the_attack"]["result"]["cancelled"] == ["atk"]
    assert fighters("sc_defending_feint_cancels_the_attack")["lobster"]["hp"] == 6
    assert fighters("sc_hounds_with_a_dead_harpy")["harpy2"]["pos"] == 5
    assert [fighters("sc_hounds_move_the_harpies_in_fid_order")[h]["pos"] for h in ("harpy1", "harpy2", "harpy3")] == [6, 2, 3]
    assert len(out["sc_clutching_claws_opponent_discards"]["game"]["players"][1]["hand"]) == 2
    assert len(out["sc_hiss_and_slither_in_defense"]["game"]["players"][1]["hand"]) == 1
    assert fighters("sc_glance_hits_the_enemy_hero")["hellboy"]["hp"] == 16
    assert fighters("sc_glance_hits_an_own_harpy")["harpy1"]["alive"] is False
    assert fighters("sc_glance_hits_medusa_herself")["medusa"]["hp"] == 14
    frenzy = fighters("sc_frenzy_moves_everybody_and_returns_a_harpy")
    assert (frenzy["medusa"]["pos"], frenzy["harpy1"]["pos"], frenzy["harpy2"]["pos"]) == (3, 5, 2)
    assert frenzy["harpy3"] == {"hp": 1, "pos": 4, "alive": True, "died_at": 22}
    assert fighters("sc_frenzy_moves_through_enemies")["harpy1"]["pos"] == 5
    back = fighters("sc_frenzy_returns_the_first_dead_harpy")
    assert back["harpy2"]["alive"] is True and back["harpy3"]["alive"] is False
    assert fighters("sc_gaze_ability_on_the_hero")["hellboy"]["hp"] == 17
    assert fighters("sc_gaze_ability_kills_lobster")["lobster"]["alive"] is False
    assert [c[0] for c in out["sc_frenzy_moves_everybody_and_returns_a_harpy"]["calls"]] == ["move"] * 3 + ["placement"]


# ---------------------------------------------------------------- the one divergence Ivan ruled

def frenzy_declining_the_return(g, ctl):
    place(g, harpy1=2, harpy2=3)
    kill(g, "harpy3")
    ctl[0].choose_placement = lambda game, fighter, options: None     # the legacy engine accepted this
    g.play_scheme(0, g.hero(0), give(g, 0, "Winged Frenzy"))


def test_frenzy_return_is_mandatory_the_only_divergence(monkeypatch):
    with legacy(monkeypatch, keep=BOX):
        old = run_twin(frenzy_declining_the_return)
    new = run_twin(frenzy_declining_the_return)
    assert old["game"]["fighters"]["harpy3"] == {"hp": 0, "pos": None, "alive": False, "died_at": 22}
    assert new["game"]["fighters"]["harpy3"] == {"hp": 1, "pos": 4, "alive": True, "died_at": 22}   # the lowest free space of Medusa's zone
    del old["game"]["fighters"]["harpy3"], new["game"]["fighters"]["harpy3"]
    assert new == old


# ---------------------------------------------------------------- the switch itself

def test_every_medusa_op_has_a_real_handler():
    raw = json.loads((EFFECTS_DIR / "medusa.json").read_text(encoding="utf-8"))
    names = {o["op"] for o in walk_ops(raw)}
    assert names == {"optional", "damage", "if", "draw", "move", "cancel_effects", "discard", "revive"}
    assert names <= set(OPS) and not names & set(PENDING_PHASES)


def test_medusa_is_interpreted_by_default_and_the_save_does_not_change(bprd, tmp_path):
    assert "medusa" in INTERPRETED_HEROES
    g = Game.new(bprd, seed=3, controllers={})
    assert g.fx.dsl_heroes == {"medusa", "hellboy"} and g.clone().fx.dsl_heroes == {"medusa", "hellboy"}
    assert "fx" not in persist.game_to_dict(g)                        # the default is derived, never written
    other = Game.new(bprd, seed=3, controllers={}, heroes=("abe-sapien", "hellboy"))
    assert other.fx.dsl_heroes == {"abe-sapien", "hellboy"} and "fx" not in persist.game_to_dict(other)    # D1 / E2
    loaded = Game.new(bprd, seed=0, controllers={})
    persist.apply_game(loaded, json.loads((GOLDEN / "legacy" / "game_save.json").read_text(encoding="utf-8")))
    assert loaded.fx.dsl_heroes == {"medusa", "hellboy"}              # an old save: interpreted on load
    g.fx.dsl_heroes = set()                                           # an explicit choice away from the default is kept
    assert persist.game_to_dict(g)["fx"] == {"dsl_heroes": []}
    again = Game.new(bprd, seed=0, controllers={})
    persist.apply_game(again, persist.game_to_dict(g))
    assert again.fx.dsl_heroes == set()


def test_no_turn_bookkeeping_is_recorded_for_heroes_that_never_read_it(bprd):
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()})
    g.begin_turn()
    g.use_action()
    g.fx.emit("attacked", g.hero(0), g.hero(1), None)
    assert g.fx.turn_start_pos == {} and g.fx.attacked == [] and g.fx.taken == 0
    assert "fx" not in persist.game_to_dict(g)
