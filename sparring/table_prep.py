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
DEFAULT_REMOVE_LIMITS = (26.0, 36.0)    # the central table: the hands sit at |x| 30, the hero bags past |z| 37


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


def removal_plan(raw: dict) -> tuple[tuple[str, str], ...]:
    """(GUID, expected TTS object name) of the loose objects destroyed at a fresh start (`remove_table`): exactly these,
    and each only if it still is that kind of object (TTS can hand a freed GUID to something else)."""
    plan = raw.get("remove_table") or {}
    if not isinstance(plan, dict) or not all(isinstance(g, str) and g and isinstance(n, str) and n for g, n in plan.items()):
        raise ValueError(t("cfg.remove_table"))
    return tuple(plan.items())


def removal_limits(raw: dict) -> tuple[float, float]:
    """(|x|, |z|) of the central table rectangle a listed object must be inside to be destroyed."""
    limits = raw.get("remove_table_limits", DEFAULT_REMOVE_LIMITS)
    if not isinstance(limits, (list, tuple)) or len(limits) != 2 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in limits):
        raise ValueError(t("cfg.remove_limits"))
    return float(limits[0]), float(limits[1])
