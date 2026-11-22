"""Little Red's Basket on the table without a session: the loose card of her bag is a token the pre-game gate lays down with her other
objects, and its resting place on each side is INSIDE that side's discard zone (the Basket starts in her discard pile). The spots are estimates
from config/table.json (verify live, docs/live-checklist.md)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from sparring import table_layout
from sparring.tts.hero_table import load_hero_table

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "config" / "table.json").read_text(encoding="utf-8"))
LITTLE_RED = load_hero_table("little-red-riding-hood")
BASKET = "51f3b8"
ZONES = {"bot": RAW["bot_discard_bounds"], "human": RAW["human_discard_bounds"]}


def inside(bounds, x: float, z: float) -> bool:
    """The same test as `Session._in_discard_zone`: the centre falls inside the rotated rectangle."""
    cx, cz, sx, sz, rot = bounds
    t = math.radians(rot)
    dx, dz = x - cx, z - cz
    lx, lz = dx * math.cos(t) - dz * math.sin(t), dx * math.sin(t) + dz * math.cos(t)
    return abs(lx) <= sx / 2 and abs(lz) <= sz / 2


def test_the_basket_is_a_token_of_her_bag_and_not_a_card_of_her_deck():
    assert LITTLE_RED.tokens == {"basket": BASKET}
    assert BASKET not in {g for g in (LITTLE_RED.deck_guid, *(p for f in LITTLE_RED.fighters.values() for p in f.pieces))}
    assert LITTLE_RED.card_ids == (17700, 17729)            # the Basket is CardID 17600 of a one-image sheet: outside her range


@pytest.mark.parametrize("side", ["bot", "human"])
def test_the_gate_lays_the_basket_down_inside_the_discard_zone_of_her_side(side):
    plan = table_layout.plan(RAW, side, LITTLE_RED)
    placed = [p for p in plan.placements if BASKET in p.guids]
    assert len(placed) == 1 and placed[0].role == "tokens" and BASKET not in plan.unplaced
    x, y, z = placed[0].slot.pos
    assert inside(ZONES[side], x, z), (side, x, z)


def test_the_bots_basket_lies_on_the_first_slot_of_its_discard_grid_so_the_first_card_lands_on_it():
    x0, y0, z0 = RAW["bot_discard_spot"]
    slot, = table_layout.own_token_slots("bot", LITTLE_RED, "basket")
    assert (slot.pos[0], slot.pos[2]) == (x0, z0)


def test_every_object_of_her_bag_has_a_place_on_both_sides():
    for side in ("bot", "human"):
        plan = table_layout.plan(RAW, side, LITTLE_RED)
        assert plan.unplaced == [], side
        placed = {g for p in plan.placements for g in p.guids}
        assert {BASKET, "eb1971", "83d1f2", "ca8e35", "091f30"} <= placed
