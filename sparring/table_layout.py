"""Where the pre-game gate leaves each side's objects: one slot per ROLE and SIDE in `layout` of config/table.json (deck,
character card, hero dial, sidekick dials, counter dials, tokens, pieces), mapped to the GUIDs of whatever hero sits on
that side through data/tts/<slug>.json, so another pair of heroes lands in the same slots. A hero with more objects than
slots keeps the extra ones where they were unpacked (`Plan.unplaced`)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .i18n import t
from .tts.hero_table import HeroTable

SINGLE_ROLES = ("deck", "character_card", "dial")
SETTLE_LIFT = 0.2       # laid this much above the height a slot rests at: TTS drops it the rest of the way
LIST_ROLES = ("sidekick_dials", "counter_dials", "tokens", "pieces")


@dataclass(frozen=True)
class Slot:
    pos: tuple[float, float, float]
    rot: tuple[float, float, float]


@dataclass(frozen=True)
class Placement:
    role: str
    guids: tuple[str, ...]          # the GUIDs of one object's states: the one that exists is placed
    slot: Slot


@dataclass
class Plan:
    placements: list[Placement] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)       # GUIDs (first state) with no slot


def _vec3(value, key: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        raise ValueError(t("cfg.vec3", key=key))
    return tuple(float(v) for v in value)       # type: ignore[return-value]


def _slot(spec, key: str) -> Slot:
    if not isinstance(spec, dict):
        raise ValueError(t("cfg.vec3", key=key))
    return Slot(_vec3(spec.get("pos"), f"{key}.pos"), _vec3(spec.get("rot"), f"{key}.rot"))


def slots(raw: dict, side: str) -> dict[str, Slot | list[Slot]]:
    """The slots of one side, validated. `{}` when the configuration has no `layout` for it."""
    spec = (raw.get("layout") or {}).get(side)
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise ValueError(t("cfg.vec3", key=f"layout.{side}"))
    out: dict[str, Slot | list[Slot]] = {}
    for role in SINGLE_ROLES:
        if role in spec:
            out[role] = _slot(spec[role], f"layout.{side}.{role}")
    for role in LIST_ROLES:
        rows = spec.get(role, [])
        if not isinstance(rows, list):
            raise ValueError(t("cfg.vec3", key=f"layout.{side}.{role}"))
        out[role] = [_slot(row, f"layout.{side}.{role}[{i}]") for i, row in enumerate(rows)]
    return out


def character_slot(raw: dict, side: str) -> Slot | None:
    slot = slots(raw, side).get("character_card")
    return slot if isinstance(slot, Slot) else None


@dataclass(frozen=True)
class Item:
    """One object of a hero that has a slot: the slot role it goes to, a key that names it (for the calibration), the GUIDs of
    its states and what it is ("deck", "dial", "token" or "piece")."""
    role: str
    key: str
    guids: tuple[str, ...]
    kind: str


def items(table: HeroTable) -> list[Item]:
    """The objects of `table`'s hero in the order their slots are given: the deck, the first life dial, the other life dials,
    the counter dials, the special tokens and the miniatures. The character card has its own slot (the gate lays it when it
    takes it out of the deck). The calibration reads the objects in this same order."""
    dials = [(fid, f.dial) for fid, f in table.fighters.items() if f.dial]
    out = [Item("deck", "deck", (table.deck_guid,), "deck")]
    if dials:
        out.append(Item("dial", f"dial:{dials[0][0]}", (dials[0][1],), "dial"))
    out += [Item("sidekick_dials", f"dial:{fid}", (g,), "dial") for fid, g in dials[1:]]
    out += [Item("counter_dials", f"counter:{name}", (g,), "dial") for name, g in table.counter_dials.items()]
    out += [Item("tokens", f"token:{name}", (g,), "token") for name, g in table.tokens.items()]
    out += [Item("pieces", f"piece:{fid}", f.pieces, "piece") for fid, f in table.fighters.items()]
    return out


def plan(raw: dict, side: str, table: HeroTable) -> Plan:
    """The placements of `table`'s hero on `side` (everything but the character card, which the gate lays when it takes it
    out of the deck)."""
    have = slots(raw, side)
    out = Plan()
    used: dict[str, int] = {}
    for item in items(table):
        slot = have.get(item.role)
        if isinstance(slot, list):
            n = used.get(item.role, 0)
            used[item.role] = n + 1
            slot = slot[n] if n < len(slot) else None
        if slot is None:
            out.unplaced.append(item.guids[0])
        else:
            out.placements.append(Placement(item.role, item.guids, slot))
    return out
