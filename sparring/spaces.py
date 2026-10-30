"""Spaces the human can find on the table.

The board spaces are not numbered on the real map, so a raw id in the chat means nothing to the human. A space is
described by what the map data supports: the colours of its zones (`zones` in data/maps/*.json) and its distance to
the nearest fighter on the board ("a 2 casillas de Baba Yaga")."""
from __future__ import annotations

from typing import Callable


def zone_text(game, space: int) -> str:
    zones = sorted(game.board.zones(space))
    if not zones:
        return "sin zona"
    if len(zones) == 1:
        return f"zona de color {zones[0]}"
    return f"zonas de color {'/'.join(zones)}"


def describe(game, space: int | None, exclude=(), name: Callable = lambda f: f.name) -> str:
    """'zona de color rojo, a 2 casillas de Baba Yaga': `exclude` are fighter ids left out of the reference (the
    piece being moved). The reference is the nearest living fighter, the lowest fighter id on a tie."""
    if space is None:
        return "fuera del tablero"
    text = zone_text(game, space)
    refs = [f for f in game.fighters.values() if f.alive and f.pos is not None and f.fid not in exclude and f.pos != space]
    if not refs:
        return text
    near = min(refs, key=lambda f: (game.board.distance(space, f.pos), f.fid))
    d = game.board.distance(space, near.pos)
    rel = f"pegada a {name(near)}" if d == 1 else f"a {d} casillas de {name(near)}"
    return f"{text}, {rel}"
