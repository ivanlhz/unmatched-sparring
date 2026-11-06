"""Per-map calibration: how the pre-game gate lays a map and where, on THAT map, each side's objects go.

A map is bigger or smaller than the next, so the scale it is played at, its place on the table and the slots of the decks,
dials and miniatures around it differ from map to map. `config/map_setups.json` holds one entry per calibrated map, keyed by
the catalog key (`data/maps/catalog.json`):

    {"bprd-hq": {"scale": 1.1, "position": [x, y, z], "rot_y": 270.0, "layout": {"bot": {...}, "human": {...}}}}

`layout` has the shape of the `layout` key of config/table.json (see `sparring/table_layout.py`). A map without an entry is
"not calibrated": the gate uses it as it lies (no scaling, no moving) with the default `layout` of config/table.json.

Nobody writes this file by hand: Ivan arranges the table with the map and both heroes and runs `python -m sparring.calibrate
--map <key>`, which reads the live transforms and calls `save` here."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import table_layout
from .i18n import t

SETUPS_PATH = Path(__file__).resolve().parent.parent / "config" / "map_setups.json"
SIDES = ("bot", "human")


@dataclass(frozen=True)
class MapSetup:
    scale: float
    position: tuple[float, float, float]
    rot_y: float
    layout: dict            # {"bot": {role: slot...}, "human": {...}} as in config/table.json


def _number(value, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(t("cfg.map_setups_bad", key=key))
    return float(value)


def parse_setup(slug: str, spec) -> MapSetup:
    """One validated entry; `ValueError` (worded for the player) when it is malformed."""
    if not isinstance(spec, dict):
        raise ValueError(t("cfg.map_setups_bad", key=slug))
    scale = _number(spec.get("scale"), f"{slug}.scale")
    if not 0 < scale < 10:
        raise ValueError(t("cfg.map_setups_bad", key=f"{slug}.scale"))
    position = table_layout._vec3(spec.get("position"), f"{slug}.position")
    layout = spec.get("layout")
    if not isinstance(layout, dict):
        raise ValueError(t("cfg.map_setups_bad", key=f"{slug}.layout"))
    for side in SIDES:
        found = table_layout.slots({"layout": layout}, side)
        if "deck" not in found or "character_card" not in found:
            raise ValueError(t("cfg.map_setups_bad", key=f"{slug}.layout.{side}"))
    return MapSetup(scale, position, _number(spec.get("rot_y", 0.0), f"{slug}.rot_y"), {s: layout[s] for s in SIDES})


def load_all(path: Path | None = None) -> dict[str, MapSetup]:
    """Every calibrated map. A missing file is no calibration at all; an unreadable one is an error."""
    path = path or SETUPS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ValueError(t("cfg.map_setups_unreadable", path=path, error=e)) from None
    if not isinstance(raw, dict):
        raise ValueError(t("cfg.map_setups_bad", key="/"))
    return {slug: parse_setup(slug, spec) for slug, spec in raw.items() if not slug.startswith("_")}


def setup_for(slug: str, path: Path | None = None) -> MapSetup | None:
    return load_all(path).get(slug)


def overrides(slug: str, path: Path | None = None) -> dict:
    """The keys of config/table.json that a calibrated map replaces: its `layout` and the two deck spots the game finds the
    draw decks at (the deck slots of the layout, as (x, z)). `{}` for a map that is not calibrated."""
    setup = setup_for(slug, path)
    if setup is None:
        return {}
    decks = {side: table_layout.slots({"layout": setup.layout}, side)["deck"].pos for side in SIDES}
    return {"layout": setup.layout, "bot_deck_spot": [decks["bot"][0], decks["bot"][2]],
            "human_deck_spot": [decks["human"][0], decks["human"][2]]}


def save(slug: str, setup: MapSetup, path: Path | None = None) -> None:
    """Writes (or replaces) the entry of one map and keeps the others."""
    path = path or SETUPS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    raw[slug] = {"scale": setup.scale, "position": list(setup.position), "rot_y": setup.rot_y, "layout": setup.layout}
    parse_setup(slug, raw[slug])
    path.write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
