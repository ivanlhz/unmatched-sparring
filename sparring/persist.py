"""Guardado y recuperacion de la partida: el estado del motor (`Game`) y de la sesion (`Session`) en JSON.

El guardado es atomico (fichero temporal + os.replace): un corte a mitad de escritura deja el guardado anterior
intacto. Las cartas se guardan por CardID y se resuelven contra el `full_set` de cada jugador al cargar."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .state import Game

VERSION = 1


class StateError(Exception):
    """El fichero de guardado no sirve para reanudar (version, formato o partida distinta)."""


def game_to_dict(g: Game) -> dict:
    return {
        "turn": g.turn, "turn_no": g.turn_no, "actions_left": g.actions_left, "winner": g.winner,
        "effect_shield": {str(k): v for k, v in g.effect_shield.items()}, "drawn": list(g.drawn),
        "fighters": {fid: {"hp": f.hp, "pos": f.pos, "alive": f.alive, "died_at": f.died_at} for fid, f in g.fighters.items()},
        "players": [{"deck": [c.card_id for c in p.deck], "hand": [c.card_id for c in p.hand],
                     "discard": [c.card_id for c in p.discard]} for p in g.players],
        "rng": list(g.rng.getstate()[:2]) + [g.rng.getstate()[2]],
    }


def apply_game(g: Game, d: dict) -> None:
    try:
        g.turn, g.turn_no, g.actions_left, g.winner = d["turn"], d["turn_no"], d["actions_left"], d["winner"]
        g.effect_shield = {int(k): v for k, v in d["effect_shield"].items()}
        g.drawn = list(d["drawn"])
        for fid, st in d["fighters"].items():
            f = g.fighters[fid]
            f.hp, f.pos, f.alive = st["hp"], st["pos"], st["alive"]
            f.died_at = st.get("died_at")
        for p, saved in zip(g.players, d["players"]):
            by_id = {c.card_id: c for c in p.full_set}
            p.deck[:] = [by_id[i] for i in saved["deck"]]
            p.hand[:] = [by_id[i] for i in saved["hand"]]
            p.discard[:] = [by_id[i] for i in saved["discard"]]
        version, internal, gauss = d["rng"]
        g.rng.setstate((version, tuple(internal), gauss))
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise StateError(f"guardado no valido: {e!r}") from None


def save_atomic(path: str | Path, data: dict) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"version": VERSION, **data}, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StateError(f"no puedo leer el guardado {path}: {e}") from None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise StateError(f"guardado de version desconocida en {path}")
    return data
