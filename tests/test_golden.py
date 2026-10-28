"""Tests dorados (F07, paso 0): fijan el comportamiento de Medusa vs Hellboy antes del motor multiheroe.

Tres fotos del comportamiento actual, guardadas en tests/golden/:
  * sim.json: resultado y registro por turno del simulador con semillas fijas (dos mapas);
  * session_batch.json y session_classic.json: transcripcion de una sesion con FakeTTS (mensajes del bot, scripts
    enviados, estado del panel y mesa tras cada boton) y el guardado final;
  * game_save.json: el guardado de una partida a medias y su ida y vuelta por persist.

Si el comportamiento cambia A PROPOSITO se regeneran con `GOLDEN_UPDATE=1 pytest tests/test_golden.py`; el diff del
fixture es la prueba de lo que cambio."""
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
    """Lo que se guarda en JSON (tuplas como listas): asi se compara lo mismo que se escribe."""
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
    assert actual == expected, (f"{name}: el comportamiento de Medusa vs Hellboy cambio; si es a proposito, "
                                "regenera con GOLDEN_UPDATE=1 y revisa el diff del fixture")


# ---------- simulador ----------
def test_golden_simulator_outcomes_and_turn_logs():
    out = {}
    for board, seed in SIM_GAMES:
        trace: list[str] = []
        o = sim.play(seed, board, trace=trace)
        out[f"{board}/{seed}"] = {"winner": o.winner, "turns": o.turns, "medusa_hp": o.medusa_hp,
                                  "hellboy_hp": o.hellboy_hp, "trace": trace}
    check("sim.json", out)


# ---------- sesion con FakeTTS ----------
STEPS = [
    ("maniobra", Event.MANEUVER, None, None),
    ("fin de accion", Event.END_ACTION, None, None),
    ("ataca hellboy", Event.ATTACKER, {"attacker": "att_hellboy"}, None),
    ("atacar a medusa", Event.ATTACK, {"target": "medusa"}, "Service Pistol"),
    ("revelar", Event.REVEAL, None, None),
    ("fin de accion: turno del bot", Event.END_ACTION, None, None),
    ("maniobra", Event.MANEUVER, None, None),
    ("fin de accion", Event.END_ACTION, None, None),
    ("plan", Event.SCHEME, None, None),
    ("fin de accion: turno del bot", Event.END_ACTION, None, None),
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
    session.cfg = dataclasses.replace(session.cfg, batch=False, live_ui=False)    # tambien con SPARRING_BATCH=1
    session.broadcast = False
    set_bot_hand(table, game, "Snipe", "Dash")
    session.read_bot_hand()
    check("session_classic.json", transcript(session, table, game, lambda e, p: session.handle(e, p)))


# ---------- guardado ----------
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
    persist.apply_game(again, fixture)         # un guardado anterior a cualquier cambio sigue cargando
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
