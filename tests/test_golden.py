"""Golden tests (F07, step 0): they pin down the behaviour of Medusa vs Hellboy before the multi-hero engine.

Three snapshots of the current behaviour, saved in tests/golden/:
  * sim.json: result and per-turn log of the simulator with fixed seeds (two maps);
  * session_batch.json and session_classic.json: transcript of a session with FakeTTS (bot messages, scripts
    sent, panel state and table after each button) and the final save; the chat lines are the Spanish catalog's;
  * game_save.json: the save of a half-played game and its round trip through persist.

If the behaviour changes ON PURPOSE they are regenerated with `GOLDEN_UPDATE=1 pytest tests/test_golden.py`; the diff of the
fixture is the proof of what changed."""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

from sparring import persist, sim
from sparring.ai_medusa import MedusaAI
from sparring.hellboy_script import ScriptedHellboy
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_session import human_plays, rig, set_bot_hand  # noqa: F401

GOLDEN = Path(__file__).resolve().parent / "golden"
UPDATE = bool(os.environ.get("GOLDEN_UPDATE"))
SIM_GAMES = [("bprd-hq", s) for s in range(6)] + [("azuchi-castle", 0), ("azuchi-castle", 1)]


def jsonable(value):
    """What is saved as JSON (tuples as lists): this way what is compared is what is written."""
    return json.loads(json.dumps(value))


def check(name: str, actual) -> None:
    path = GOLDEN / name
    actual = jsonable(actual)
    text = json.dumps(actual, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if UPDATE:
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected, (f"{name}: the behaviour of Medusa vs Hellboy changed; if on purpose, "
                                "regenerate with GOLDEN_UPDATE=1 and review the fixture diff")


# ---------- simulator ----------
def test_golden_simulator_outcomes_and_turn_logs():
    out = {}
    for board, seed in SIM_GAMES:
        trace: list[str] = []
        o = sim.play(seed, board, trace=trace)
        out[f"{board}/{seed}"] = {"winner": o.winner, "turns": o.turns, "medusa_hp": o.medusa_hp,
                                  "hellboy_hp": o.hellboy_hp, "trace": trace}
    check("sim.json", out)


# ---------- session with FakeTTS ----------
STEPS = [
    ("maneuver", Event.MANEUVER, None, None),
    ("end action", Event.END_ACTION, None, None),
    ("hellboy attacks", Event.ATTACKER, {"attacker": "att_hellboy"}, None),
    ("attack medusa", Event.ATTACK, {"target": "medusa"}, "Service Pistol"),
    ("reveal", Event.REVEAL, None, None),
    ("end action: bot's turn", Event.END_ACTION, None, None),
    ("maneuver", Event.MANEUVER, None, None),
    ("end action", Event.END_ACTION, None, None),
    ("plan", Event.SCHEME, None, None),
    ("end action: bot's turn", Event.END_ACTION, None, None),
]


def transcript(session, table, game, press) -> dict:
    steps = []
    for label, event, payload, human_card in STEPS:
        if human_card:
            human_plays(table, game, human_card)
        n = len(table.sent)
        said = press(event, payload)
        steps.append({
            "step": label, "said": said, "sent": table.sent[n:],
            "status": table.panels[-1][0] if table.panels else None,
            "bot_hand": list(table.bot_hand), "bot_discard": list(table.bot_discard),
            "human_discard": list(table.human_discard), "positions": dict(table.positions),
            "engine": {"turn": game.turn, "turn_no": game.turn_no, "actions_left": game.actions_left,
                       "hp": {fid: f.hp for fid, f in game.fighters.items()},
                       "pos": {fid: f.pos for fid, f in game.fighters.items()}, "form": game.form(1)},
        })
    session.game_id = "golden"
    return {"steps": steps, "save": session.to_dict()}


def test_golden_session_transcript_batch(brig):
    session, table, game, _ = brig
    check("session_batch.json", transcript(session, table, game, lambda e, p: click(session, table, e, p)))


def test_golden_session_transcript_classic(rig):
    session, table, game = rig
    session.cfg = dataclasses.replace(session.cfg, batch=False, live_ui=False)    # also with SPARRING_BATCH=1
    session.broadcast = False
    set_bot_hand(table, game, "Snipe", "Dash")
    session.read_bot_hand()
    check("session_classic.json", transcript(session, table, game, lambda e, p: session.handle(e, p)))


# ---------- saving ----------
def midgame(board) -> Game:
    controllers = {0: MedusaAI(0), 1: ScriptedHellboy(1, 3)}
    game = Game.new(board, seed=3, controllers=controllers)
    for _ in range(4):
        game.begin_turn()
        controllers[game.turn].take_turn(game)
        game.log.clear()
        if game.winner is None:
            game.end_turn()
    return game


def test_golden_game_save_and_round_trip(bprd, tmp_path):
    saved = persist.game_to_dict(midgame(bprd))
    check("game_save.json", saved)
    persist.save_atomic(tmp_path / "s.json", {"game": saved})
    loaded = persist.load(tmp_path / "s.json")["game"]
    fresh = Game.new(bprd, seed=0, controllers={})
    persist.apply_game(fresh, loaded)
    assert jsonable(persist.game_to_dict(fresh)) == jsonable(saved)
    fixture = json.loads((GOLDEN / "game_save.json").read_text(encoding="utf-8"))
    again = Game.new(bprd, seed=0, controllers={})
    persist.apply_game(again, fixture)         # a save from before any change still loads
    assert jsonable(persist.game_to_dict(again)) == fixture


def test_golden_session_save_round_trip(brig):
    session, table, game, _ = brig
    transcript(session, table, game, lambda e, p: click(session, table, e, p))
    before = jsonable(session.to_dict())
    session.load_dict(before)
    assert jsonable(session.to_dict()) == before
    fixture = json.loads((GOLDEN / "session_batch.json").read_text(encoding="utf-8"))["save"]
    session.load_dict(fixture)
    assert jsonable(session.to_dict()) == fixture
