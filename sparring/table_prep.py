"""Start-up preparation of a table that was not built for the bot (the official community save): the discard zones
it lacks are created, and what sits in the middle of the table is moved to a parking spot.

This module reads and validates the configuration (`ZoneSpawn`, `ParkPlan`); the table writes are one script
(`lua.prepare_table`) sent by `Session.prepare_table`."""
from __future__ import annotations

from dataclasses import dataclass

from .i18n import t

DISCARD_ZONE_KEYS = ("bot_discard_zone", "human_discard_zone")
SPAWN_SUFFIX = "_spawn"                 # config key of each zone's default transform: bot_discard_zone_spawn
DEFAULT_ZONE_ROT_Y = 270.0              # straight: the long side of both zones runs along z


@dataclass(frozen=True)
class ZoneSpawn:
    """Transform a missing Scripting zone is created with (and an existing one is straightened to)."""
    position: tuple[float, float, float]
    scale: tuple[float, float, float]
    rot_y: float


def _vec3(value, key: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        raise ValueError(t("cfg.vec3", key=key))
    return tuple(float(v) for v in value)       # type: ignore[return-value]


def zone_spawns(raw: dict) -> dict[str, ZoneSpawn]:
    """Default transform of each discard zone that has one in the configuration (`<zone key>_spawn`, with the shared
    `discard_zone_rot_y`). A zone without it is never created or straightened."""
    rot_y = float(raw.get("discard_zone_rot_y", DEFAULT_ZONE_ROT_Y))
    out = {}
    for key in DISCARD_ZONE_KEYS:
        spec = raw.get(key + SPAWN_SUFFIX)
        if spec is None:
            continue
        if not isinstance(spec, dict):
            raise ValueError(t("cfg.vec3", key=key + SPAWN_SUFFIX))
        out[key] = ZoneSpawn(_vec3(spec.get("position"), f"{key}{SPAWN_SUFFIX}.position"),
                             _vec3(spec.get("scale"), f"{key}{SPAWN_SUFFIX}.scale"), rot_y)
    return out


def park_plan(raw: dict) -> tuple[tuple[str, tuple[float, float, float]], ...]:
    """(GUID, parking spot) of each object cleared from the centre of the table: `clear_table_guids[i]` goes to
    `clear_table_spots[i]`."""
    guids, spots = raw.get("clear_table_guids") or [], raw.get("clear_table_spots") or []
    if not isinstance(guids, list) or not isinstance(spots, list) or not all(isinstance(g, str) for g in guids):
        raise ValueError(t("cfg.clear_table"))
    if len(guids) != len(spots):
        raise ValueError(t("cfg.clear_table"))
    return tuple((g, _vec3(s, "clear_table_spots")) for g, s in zip(guids, spots))
