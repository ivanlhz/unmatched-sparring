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


def grid_slots():
    """The slots of the bot's discard grid, as `Session._grid_slots` lays them out."""
    x0, _, z0 = RAW["bot_discard_spot"]
    dx, dz = RAW["bot_discard_step"]
    kx, kz = RAW["bot_deck_spot"]
    cols = 8
    return [(x0 + col * dx, z0 + row * dz) for i in range(cols * RAW["bot_discard_rows"]) for col, row in [divmod(i, RAW["bot_discard_rows"])]
            if inside(ZONES["bot"], x0 + col * dx, z0 + row * dz) and (x0 + col * dx - kx) ** 2 + (z0 + row * dz - kz) ** 2 > 9.0]


def test_the_bots_basket_lies_off_every_slot_of_its_discard_grid_so_no_discard_stacks_on_it():
    """A Basket under a discard would merge into the pile's Deck, which the restart does not treat as hers and in which the card has no GUID."""
    slot, = table_layout.own_token_slots("bot", LITTLE_RED, "basket")
    assert min(math.hypot(slot.pos[0] - x, slot.pos[2] - z) for x, z in grid_slots()) >= 3.0


def test_the_humans_basket_lies_in_the_corner_of_their_zone_away_from_the_deck():
    slot, = table_layout.own_token_slots("human", LITTLE_RED, "basket")
    kx, kz = RAW["human_deck_spot"]
    assert math.hypot(slot.pos[0] - kx, slot.pos[2] - kz) > 8.0


def test_every_object_of_her_bag_has_a_place_on_both_sides():
    for side in ("bot", "human"):
        plan = table_layout.plan(RAW, side, LITTLE_RED)
        assert plan.unplaced == [], side
        placed = {g for p in plan.placements for g in p.guids}
        assert {BASKET, "eb1971", "83d1f2", "ca8e35", "091f30"} <= placed


# ---------------------------------------------------------------- the Lua that puts the Basket back on its own spot (the lupa stub of TTS)

from sparring.tts import lua_little_red                              # noqa: E402
from test_effects_bridge import rt, run, table_py                    # noqa: E402,F401  (rt is a fixture)

SPOT = (20.8, 2.0, -14.0)
ROT = (0, 90, 0)


def basket_on_table(rt, x, z):
    rt.execute(f"mkobj({{guid = '{BASKET}', type = 'Card', pos = Vector({x}, 2.0, {z})}})")


def aside(rt):
    return run(rt, lua_little_red.basket_aside(BASKET, SPOT, ROT))


def where(rt):
    return table_py(rt, f"""(function() local o = getObjectFromGUID('{BASKET}'); return {{o.pos.x, o.pos.y, o.pos.z, o.moved_count or 0}} end)()""")


def test_a_loose_basket_lying_elsewhere_is_laid_on_its_own_spot(rt):
    basket_on_table(rt, 17.5, -14.0)                                  # on the stacking spot of the grid
    assert aside(rt) == {"found": True, "taken": False, "moved": True}
    x, y, z, _ = where(rt)
    assert (round(x, 2), round(y, 2), round(z, 2)) == SPOT


def test_a_basket_already_on_its_spot_is_left_alone(rt):
    basket_on_table(rt, 20.9, -14.1)
    assert aside(rt) == {"found": True, "taken": False, "moved": False}
    assert where(rt)[3] == 0


def test_a_basket_inside_the_pile_deck_is_taken_out_onto_its_spot(rt):
    rt.execute(f"""
local deck = mkobj({{guid = 'pile01', type = 'Deck', pos = Vector(17.5, 2.0, -14.0),
  data = {{ContainedObjects = {{{{GUID = 'c1'}}, {{GUID = '{BASKET}'}}, {{GUID = 'c2'}}}}}}}})
deck.takeObject = function(t)
  assert(t.guid == '{BASKET}')
  return mkobj({{guid = t.guid, type = 'Card', pos = Vector(t.position)}})
end""")
    assert aside(rt) == {"found": True, "taken": True, "moved": True}
    x, y, z, _ = where(rt)
    assert (round(x, 2), round(z, 2)) == (SPOT[0], SPOT[2])


def test_a_basket_that_is_nowhere_is_reported_not_invented(rt):
    rt.execute("mkobj({guid = 'pile01', type = 'Deck', data = {ContainedObjects = {{GUID = 'c1'}}}})")
    assert aside(rt) == {"found": False, "taken": False, "moved": False}
