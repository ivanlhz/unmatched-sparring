"""Saving and restoring the game: the engine state (`Game`) and the session state (`Session`) as JSON.

Saving is atomic (temporary file + os.replace): a cut in mid-write leaves the previous save intact. Cards are
saved by CardID and resolved against each player's `full_set` on load."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .effects import ongoing
from .effects.state import EffectState, default_dsl_heroes
from .i18n import t
from .state import Game, KnownHand

VERSION = 1


class StateError(Exception):
    """The save file cannot be resumed (version, format or a different game)."""


def game_to_dict(g: Game) -> dict:
    legacy = [ongoing.legacy_parts(g, p) for p in (0, 1)]       # pre-DSL ONGOING bonuses keep their old key
    fx = g.fx.to_dict()
    if g.fx.dsl_heroes == default_dsl_heroes(g):      # the default follows the heroes in play: nothing to remember
        fx.pop("dsl_heroes", None)
    else:
        fx["dsl_heroes"] = sorted(g.fx.dsl_heroes)
    return {
        "turn": g.turn, "turn_no": g.turn_no, "actions_left": g.actions_left, "winner": g.winner,
        "effect_shield": {str(k): v for k, v in g.effect_shield.items()}, "drawn": list(g.drawn),
        **({"combat_bonus": [[list(b) for b in side] for side in legacy]} if any(legacy) else {}),
        **({"fx": fx} if fx else {}),
        "fighters": {fid: {"hp": f.hp, "pos": f.pos, "alive": f.alive, "died_at": f.died_at} for fid, f in g.fighters.items()},
        "players": [{"deck": [c.card_id for c in p.deck], "hand": [c.card_id for c in p.hand],
                     "discard": [c.card_id for c in p.discard],
                     # known rival hand (effect "look at the hand"): only written if there is something to remember
                     **({"known": p.known.to_dict()} if not p.known.is_empty() else {})}
                    for p in g.players],
        "rng": list(g.rng.getstate()[:2]) + [g.rng.getstate()[2]],
    }


def apply_game(g: Game, d: dict) -> None:
    try:
        g.turn, g.turn_no, g.actions_left, g.winner = d["turn"], d["turn_no"], d["actions_left"], d["winner"]
        g.effect_shield = {int(k): v for k, v in d["effect_shield"].items()}
        g.drawn = list(d["drawn"])
        fx = d.get("fx") or {}
        g.fx = EffectState.from_dict(fx)
        if "dsl_heroes" not in fx:
            g.fx.dsl_heroes = default_dsl_heroes(g)
        g.fx.attach(g)
        for player, side in enumerate(d.get("combat_bonus") or [[], []]):
            if side:                                  # one ONGOING per player: keep the last
                ongoing.set_legacy(g, player, int(side[-1][0]), str(side[-1][1]))
        for fid, st in d["fighters"].items():
            f = g.fighters[fid]
            f.hp, f.pos, f.alive = st["hp"], st["pos"], st["alive"]
            f.died_at = st.get("died_at")
        for p, saved in zip(g.players, d["players"]):
            by_id = {c.card_id: c for c in p.full_set}
            p.deck[:] = [by_id[i] for i in saved["deck"]]
            p.hand[:] = [by_id[i] for i in saved["hand"]]
            p.discard[:] = [by_id[i] for i in saved["discard"]]
            p.known = KnownHand.from_dict(saved.get("known"))
        version, internal, gauss = d["rng"]
        g.rng.setstate((version, tuple(internal), gauss))
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise StateError(t("save.invalid", error=repr(e))) from None


def save_atomic(path: str | Path, data: dict) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"version": VERSION, **data}, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StateError(t("save.unreadable", path=path, error=e)) from None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise StateError(t("save.version", path=path))
    return data
