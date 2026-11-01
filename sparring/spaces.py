"""Spaces the human can find on the table.

The board spaces are not numbered on the real map, so a raw id in the chat means nothing to the human. A space is
described by what the map data supports: the colours of its zones (`zones` in data/maps/*.json, named in the catalogs) and its distance to
the nearest fighter on the board (spoken as "2 spaces from Baba Yaga")."""
from __future__ import annotations

from typing import Callable

from .i18n import t


def zone_text(game, space: int) -> str:
    colors = sorted(t(f"spaces.color.{zone}") for zone in game.board.zones(space))
    if not colors:
        return t("spaces.no_zone")
    if len(colors) == 1:
        return t("spaces.zone_one", color=colors[0])
    return t("spaces.zone_many", color="/".join(colors))


def describe(game, space: int | None, exclude=(), name: Callable = lambda f: f.name) -> str:
    """'red zone, 2 spaces from Baba Yaga': `exclude` are fighter ids left out of the reference (the
    piece being moved). The reference is the nearest living fighter, the lowest fighter id on a tie."""
    if space is None:
        return t("spaces.off_board")
    text = zone_text(game, space)
    refs = [f for f in game.fighters.values() if f.alive and f.pos is not None and f.fid not in exclude and f.pos != space]
    if not refs:
        return text
    near = min(refs, key=lambda f: (game.board.distance(space, f.pos), f.fid))
    d = game.board.distance(space, near.pos)
    rel = t("spaces.next_to", name=name(near)) if d == 1 else t("spaces.distance", d=d, name=name(near))
    return f"{text}, {rel}"
