"""Start-up preparation of a table that was not built for the bot (the official community save): the discard zones
it lacks are created, and the loose objects of the save that the bot does not want on the table are removed.

This module reads and validates the configuration (`ZoneSpawn`, `removal_list`); the table writes are one script
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


def removal_list(raw: dict) -> tuple[str, ...]:
    """GUIDs of the loose objects destroyed at a fresh start (`remove_table_guids`): exactly these, never by area."""
    guids = raw.get("remove_table_guids") or []
    if not isinstance(guids, list) or not all(isinstance(g, str) and g for g in guids):
        raise ValueError(t("cfg.remove_table"))
    return tuple(guids)
