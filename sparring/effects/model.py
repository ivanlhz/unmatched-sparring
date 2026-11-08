"""Loads and indexes `data/heroes/effects/<slug>.json` (docs/effects-dsl.md section 1). Read-only: the ops lists
returned are shared and must never be mutated (an EffectRun keeps its own copy of what it needs)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator

from ..board import DATA_DIR

EFFECTS_DIR = DATA_DIR / "heroes" / "effects"
MOMENTS = ("immediately", "during", "after", "scheme", "boost", "unboosted")      # unboosted: a `may_boost` card's DURING ops for when its owner did not BOOST (I Never Miss)


class EffectError(Exception):
    """The effect data or its use is wrong (as opposed to NotImplementedError: right, but not built yet)."""


@dataclass(frozen=True)
class CounterRange:
    min: int
    max: int
    start: int


@dataclass(frozen=True)
class CardEffects:
    title: str
    moments: dict[str, list[dict]]
    may_boost: bool = False
    uncancelable: bool = False
    ongoing: dict | None = None
    invention: dict | None = None        # {"modifiers": [...], "triggers": [...]}: holds once tucked under the hero card
    max_boosts: int = 1                  # with `may_boost`: how many cards its owner may BOOST it with (The Big Reveal: 2)
    defers_defeat: bool = False          # played in a combat, the defeat of its fighter's hero waits for the AFTER effects (All Part of the Show)
    look_shield: bool = False            # held in hand, its owner may reveal it to cancel a look at their hand (A Magician Never Reveals His Secrets)
    adjacent_only: bool = False          # an attack that can only target a fighter adjacent to the attacker (Witness My Last Battle)
    face_up: bool = False                # an attack played face up: the defense may know it (Witness My Last Battle)


@dataclass(frozen=True)
class HeroEffects:
    slug: str
    cards: dict[str, CardEffects]
    triggers: tuple[dict, ...] = ()
    passives: tuple[dict, ...] = ()
    counters: dict[str, CounterRange] = field(default_factory=dict)
    plugins: frozenset[str] = frozenset()
    ability_during: tuple[dict, ...] = ()       # the hero's own DURING COMBAT effects: [{id, condition?, ops}] (Daredevil, section 29)

    def card(self, title: str) -> CardEffects:
        try:
            return self.cards[title]
        except KeyError:
            raise EffectError(f"{self.slug}: no effects for card {title!r}") from None

    def moment_ops(self, title: str, moment: str) -> list[dict]:
        if moment not in MOMENTS:
            raise EffectError(f"unknown moment {moment!r}")
        return self.card(title).moments.get(moment, [])

    def trigger(self, trigger_id: str) -> dict:
        for t in self.triggers:
            if t["id"] == trigger_id:
                return t
        raise EffectError(f"{self.slug}: no ability trigger {trigger_id!r}")

    def counter_range(self, name: str) -> CounterRange:
        try:
            return self.counters[name]
        except KeyError:
            raise EffectError(f"{self.slug}: no ability counter {name!r}") from None


def parse_effects(raw: dict) -> HeroEffects:
    try:
        cards = {c["title"]: CardEffects(c["title"], dict(c.get("effects") or {}), bool(c.get("may_boost")),
                                         bool(c.get("uncancelable")), c.get("ongoing"), c.get("invention"),
                                         int(c.get("max_boosts", 1)), bool(c.get("defers_defeat")), bool(c.get("look_shield")),
                                         bool(c.get("adjacent_only")), bool(c.get("face_up")))
                 for c in raw["cards"]}
        ability = raw.get("ability") or {}
        counters = {k: CounterRange(int(v["min"]), int(v["max"]), int(v.get("start", v["min"])))
                    for k, v in (ability.get("counters") or {}).items()}
        return HeroEffects(raw["hero"], cards, tuple(ability.get("triggers") or ()),
                           tuple(ability.get("passives") or ()), counters,
                           frozenset(p["id"] for p in raw.get("plugins") or ()), tuple(ability.get("during") or ()))
    except (KeyError, TypeError, ValueError) as e:
        raise EffectError(f"invalid effects file ({e!r})") from None


@lru_cache(maxsize=None)
def load_effects(slug: str) -> HeroEffects:
    path = EFFECTS_DIR / f"{slug}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise EffectError(f"no effects file for {slug!r}: {path} is missing") from None
    except ValueError as e:
        raise EffectError(f"{path}: invalid JSON ({e})") from None
    return parse_effects(raw)


def walk_ops(node) -> Iterator[dict]:
    """Every op dict anywhere inside a JSON tree (then/else/ops/cost lists, choose_effect options, whole files)."""
    if isinstance(node, dict):
        if "op" in node and "test" not in node:      # a `compare` condition also has an "op" (the comparator)
            yield node
        for v in node.values():
            yield from walk_ops(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_ops(v)
