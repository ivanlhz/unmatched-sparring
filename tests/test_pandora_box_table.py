"""Pandora's Misery deck on the table (Ivan, 22/11/2026): the real deck of seven Miseries is her Box, so Prepare takes it out of the bag next
to her other pieces whoever plays her (`extras` of data/tts/pandora.json). When the HUMAN plays her they reveal the cards themselves. When the
BOT plays her, each Misery the engine draws is taken out of that deck (by CardID) and laid face up in a row beside it, and at the end of the
bot's turn they all go back and the deck is shuffled. A table with no Misery deck gets one chat warning and the old chat-only Box. Clean table
removes a loose Misery deck like any other hero piece."""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sparring import box_layout, play, player_setup, session_pandora
from sparring.i18n import t
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from sparring.tts.ui import Event
from test_batch import click
from sparring.ai_medusa import Act
from test_d3_table_effects import FxTable, bot_turn, said
from test_e2_human_cards import labels, press, with_rig, rig  # noqa: F401
from test_jill_gadget_token import RAW
from test_multihero_bridge import config_for
from test_pandora_human import BOT_HAND, HAND, IDX, keeps, order, reload  # noqa: F401
from test_review10 import rt  # noqa: F401
from test_review9 import STUB, conv, run

MISERIES = "4581f8"
BOX = load_hero_table("pandora").box
TEST_IDENTITY = (("https://img.test/misery/face", "https://img.test/misery/back"),)      # what the Lua stub gives the cards of owner "misery"
SPOT = (24.0, 2.0)
ROOT = Path(__file__).resolve().parent.parent
REAL_TABLE = ROOT / "config" / "table.json"
RAW = json.loads(REAL_TABLE.read_text(encoding="utf-8"))
TTS_FILE = Path(__file__).resolve().parent.parent / "data" / "tts" / "pandora.json"


def _taken(plan):
    return [guids for kind, guids, *_ in plan if MISERIES in guids]


# ---------------------------------------------------------------- the data and the set-up

def test_the_misery_deck_is_a_box_the_table_can_find():
    table = load_hero_table("pandora")
    assert table.extras == (MISERIES,) and BOX.guid == MISERIES and len(BOX.identity) == 1


def real_config(bot, human):
    """The configuration of the REAL table (config/table.json: its deck spots, discard zones, layout and seats), only the heroes chosen."""
    return play.load_config(REAL_TABLE, bot, human)


def box_row(plan):
    return next(r for r in plan if MISERIES in r[1])


def test_the_human_pandora_s_box_lies_to_the_left_of_her_deck_from_her_seat_face_down_in_the_yaw_of_her_deck():
    """Ivan 26/11/2026: the Box goes to the LEFT of her own deck as she sees it from her seat. White sits at -x looking +x: her left is +z."""
    row = box_row(play.unpack_plan(real_config("medusa", "pandora")))
    assert row[0] == "token" and row[2] == load_hero_table("pandora").inner_bag
    assert (row[3][0], row[3][2]) == pytest.approx((-6.7, 17.55 + lua.BOX_CARD_SHORT + lua.BOX_GAP)) and row[6] == (0.0, 270.0, 180.0)
    assert row[3][2] > RAW["human_deck_spot"][1], "+z: the left of a player looking toward +x"


def test_the_bot_pandora_s_box_would_lie_to_the_left_of_its_deck_toward_minus_z_but_its_layout_is_there_so_it_falls_back_beside_the_deck():
    """Green sits at +x looking -x: its left is -z, where its character card (5.28, 15.0) and dial lie, so the Box takes the side away from its
    discard zone as before: (1.53, 17.71)."""
    cfg = real_config("pandora", "medusa")
    assert cfg.seat_geo("bot").left == (0.0, -1.0) and cfg.seat_geo("human").left == (0.0, 1.0)
    row = box_row(play.unpack_plan(cfg))
    assert (row[3][0], row[3][2]) == pytest.approx((1.53, 17.71)) and row[6] == (0.0, 90.0, 180.0)


def test_the_bot_s_box_is_to_the_left_of_its_deck_when_nothing_of_its_layout_is_there():
    raw = {**RAW, "layout": {"bot": {"deck": RAW["layout"]["bot"]["deck"]}, "human": RAW["layout"]["human"]}}
    geo = box_layout.seat_geo(raw, "bot")
    x, z, yaw = box_layout.box_place(raw, "bot", geo)
    assert (x, z, yaw) == pytest.approx((RAW["bot_deck_spot"][0], RAW["bot_deck_spot"][1] - lua.BOX_CARD_SHORT - lua.BOX_GAP, 90.0))


@pytest.mark.parametrize("bot, human, side", [("pandora", "medusa", "bot"), ("medusa", "pandora", "human")])
def test_the_box_beside_the_deck_touches_no_hand_discard_zone_or_piece_of_her_layout(bot, human, side):
    cfg = real_config(bot, human)
    x, _, z = box_row(play.unpack_plan(cfg))[3]
    geo = cfg.seat_geo(side)
    hx, hz = box_layout._card_half(geo.up_yaw)
    box = (x, z, hx, hz)
    blocked = [*geo.keep, *(box_layout._discard_rect(RAW, o) for o in ("bot", "human"))]
    assert not any(box_layout._overlap(box, b) for b in blocked)
    assert abs(x) + hx <= RAW["hand_edge"] and abs(z) + hz <= RAW["remove_table_limits"][1]


@pytest.mark.parametrize("bot, human, key", [("pandora", "medusa", "bot_deck_spot"), ("medusa", "pandora", "human_deck_spot")])
def test_without_a_deck_spot_the_box_is_unpacked_in_the_row_it_always_was(tmp_path, bot, human, key):
    cfg = config_for(tmp_path, bot, human)
    cfg.raw[key] = None
    row = box_row(play.unpack_plan(cfg))
    assert len(row) == 5 and (row[3][0] < 0) == (human == "pandora"), "the unpack row of her side, no rotation"


def test_the_unpack_lays_the_box_turned_face_down_where_the_plan_says():
    plan = play.unpack_plan(real_config("pandora", "medusa"))
    script = lua.unpack_from_bags([box_row(plan)])
    assert "{0.0, 90.0, 180.0}" in script and "give.rotation = Vector(it[11][1], it[11][2], it[11][3])" in script
    other = lua.unpack_from_bags([("piece", ("abc",), "def", (0.0, 0.0, 0.0), None)])
    assert "{0.0, 90.0, 180.0}" not in other and ", nil}" in other
    with pytest.raises(TypeError):
        lua.unpack_from_bags([("token", ("abc",), "def", (0.0, 0.0, 0.0), None, None, (0.0, 90.0))])


def test_the_session_config_knows_where_the_bot_s_box_is_put(tmp_path):
    plan = play.unpack_plan(config_for(tmp_path, "pandora", "medusa"))
    x, _, z = next(r[3] for r in plan if MISERIES in r[1])
    assert config_for(tmp_path, "pandora", "medusa").session_config().box_spot == (x, z)
    assert config_for(tmp_path, "medusa", "pandora").session_config().box_spot is None, "only the bot's Box is the bot's business"
    human = config_for(tmp_path, "medusa", "pandora")
    hx, _, hz = next(r[3] for r in play.unpack_plan(human) if MISERIES in r[1])
    assert human.session_config().human_box_spot == (hx, hz) and hx < 0
    assert config_for(tmp_path, "pandora", "medusa").session_config().human_box_spot is None


def test_clean_table_removes_a_loose_misery_deck(rt):  # noqa: F811
    rt.execute(f"""
local cards = {{}}
for i = 0, 6 do table.insert(cards, {{cid = 17700 + i, guid = 'm' .. i}}) end
realshape(mkobj({{guid = '{MISERIES}', type = 'Deck', name = '', cards = cards, pos = {{x = -9, y = 1, z = 9}},
                 deckcd = {{["177"] = {{FaceURL = 'https://img.test/misery/', BackURL = 'https://img.test/misery-back/'}}}}}}))
""")
    assert rt.globals().getObjectFromGUID(MISERIES) is not None
    run(rt, player_setup.clear_script(RAW))
    assert rt.globals().getObjectFromGUID(MISERIES) is None


# ---------------------------------------------------------------- the Lua of the Box

def pile_at(x=10.0, z=2.0, up=90.0, down=(1.0, 0.0), **kw):
    """Her deck at (x, z) and her seat toward +x on a table with nothing else on it."""
    kw.setdefault("limits", (80.0, 80.0))
    return lua.BoxPile((x, z), up, down, **kw)


def reveal(card, slot, pile=None, **kw):
    return lua.box_reveal(MISERIES, card % 100, slot, identity=TEST_IDENTITY, spot=SPOT, pile=pile or pile_at(), **kw)


def put_back():
    return lua.box_put_back(MISERIES, identity=TEST_IDENTITY, spot=SPOT)


def make_deck(rt, ids=range(17700, 17707), guid=MISERIES, at=(24, 2), yaw=90):
    rt.execute("local cs = {}\nfor _, id in ipairs({" + ", ".join(map(str, ids)) + "}) do table.insert(cs, {cid = id, guid = 'c' .. id, owner = 'misery'}) end\n"
               f"mkobj({{guid = '{guid}', type = 'Deck', cards = cs, pos = Vector({at[0]}, 2.5, {at[1]}), rot = Vector(0, {yaw}, 180)}})")


def loose(rt, cid, x, z, guid=None, owner="misery", up=True):
    rt.execute(f"mkobj({{guid = '{guid or 'c' + str(cid)}', type = 'Card', cid = {cid}, owner = '{owner}', "
               f"is_face_down = {str(not up).lower()}, pos = Vector({x}, 2, {z}), rot = Vector(0, 90, {0 if up else 180})}})")


def test_a_misery_is_taken_out_of_the_box_by_its_card_id_and_laid_face_up_in_the_pile_below_her_deck(rt):  # noqa: F811
    make_deck(rt, ids=[17704, 17701, 17706, 17700, 17703, 17702, 17705])
    rt.execute("local d = getObjectFromGUID('4581f8'); local take = d.takeObject\n"
               "d.takeObject = function(t) TAKEN = {guid = t.guid, rot = t.rotation, pos = t.position, smooth = t.smooth}; return take(t) end")
    out = run(rt, reveal(17703, 2))
    assert out == {"taken": True, "guid": "c17703", "crowded": False, "side": "below"}
    got = rt.eval("TAKEN")
    assert (got.guid, got.smooth) == ("c17703", False)
    first = 10 + 1.65 + lua.BOX_PILE_GAP + 1.65                                   # her deck's far edge, the gap, half a card
    assert (got.pos.x, got.pos.z) == (pytest.approx(first + lua.BOX_PILE_STEPS[0]), 2), "the second place: one step further toward her seat"
    assert got.pos.y == pytest.approx(2.5 + 1 + 0.25), "lifted off the table a little more for each card, so it lands on the one before"
    assert got.rot.y == 90 and got.rot.z == 0                       # face up (the Box lies face down at z = 180), upright for her seat
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 6


def test_the_last_misery_of_the_box_is_moved_as_it_is(rt):  # noqa: F811
    loose(rt, 17702, 24, 2, guid=MISERIES, up=False)
    assert run(rt, reveal(17701, 1)) == {"taken": False}
    assert run(rt, reveal(17702, 1)) == {"taken": True, "guid": MISERIES, "crowded": False, "side": "below"}
    card = rt.globals().getObjectFromGUID(MISERIES)
    assert card.pos.x == pytest.approx(10 + 1.65 + lua.BOX_PILE_GAP + 1.65) and card.pos.z == 2 and card.rot.z == 0 and card.rot.y == 90


def test_a_missing_box_or_a_card_of_another_hero_with_a_misery_card_id_is_left_alone(rt):  # noqa: F811
    assert run(rt, reveal(17703, 1)) == {"taken": False, "deck": False}
    loose(rt, 17700, 24, 2, guid="houdini", owner="houdini", up=False)          # Houdini's character card shares CardID 17700
    assert run(rt, reveal(17700, 1)) == {"taken": False, "deck": False}
    assert rt.globals().getObjectFromGUID("houdini").pos.z == 2
    assert run(rt, put_back()) == {"added": 0, "deck": False}


def test_the_box_is_found_beside_where_it_was_put_when_its_guid_changed(rt):  # noqa: F811
    make_deck(rt, guid="regrouped")
    assert run(rt, reveal(17703, 1))["taken"] is True


def test_the_end_of_the_turn_puts_every_loose_misery_back_and_shuffles_the_box(rt):  # noqa: F811
    make_deck(rt, ids=[17700, 17701, 17704, 17706])
    for slot, cid in enumerate((17702, 17703, 17705), 1):
        loose(rt, cid, 24, 2 + 3 * slot)
    loose(rt, 17700, 10, 10, guid="houdini", owner="houdini")
    assert run(rt, put_back()) == {"added": 3, "deck": True, "quantity": 7}
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is True
    assert rt.globals().getObjectFromGUID("houdini") is not None and rt.globals().getObjectFromGUID("c17703") is None
    assert run(rt, put_back()) == {"added": 0, "deck": True}, "nothing left out: nothing to do"


def test_with_no_box_left_the_first_misery_back_becomes_it(rt):  # noqa: F811
    for slot, cid in enumerate((17702, 17703), 1):
        loose(rt, cid, 24, 2 + 3 * slot)
    out = run(rt, put_back())
    assert out["added"] == 2 and out["deck"] is True and out["quantity"] == 2


# ---------------------------------------------------------------- the Box's own zone

ZONE = "boxzone"


def zone_around(rt, x, z, guid=ZONE, half=1.9, half_z=None):
    rt.execute(f"local z = mkobj({{guid = '{guid}', type = 'Scripting', cx = {x}, cz = {z}, hw = {half}, hd = {half_z or half}}}); "
               f"z.pos = Vector({x}, 4, {z}); z.setPosition = function(p) z.pos = Vector(p); z.cx, z.cz = p.x, p.z end")


def make_zone(candidates=(), recenter=False):
    return lua.box_zone(list(candidates), MISERIES, identity=TEST_IDENTITY, spot=SPOT, recenter=recenter)


def test_the_zone_is_made_around_where_the_box_lies_now_face_down_or_up(rt):  # noqa: F811
    rt.execute("mkobj({guid = '4581f8', type = 'Deck', is_face_down = false, pos = Vector(10, 2.5, 5), rot = Vector(0, 0, 0), "
               "cards = {{cid = 17700, guid = 'a', owner = 'misery'}, {cid = 17701, guid = 'b', owner = 'misery'}}})")
    out = run(rt, make_zone())
    assert out["status"] == "created" and out["box"] is True
    zone = rt.globals().getObjectFromGUID(out["guid"])
    assert (zone.pos.x, zone.pos.z) == (10, 5) and (zone.scale.x, zone.scale.z) == pytest.approx((2.4, 3.5)), "the deck's own footprint, not turned: 2.2 x 3.3 and a margin"
    assert zone.type == "Scripting" and zone.scale.y == lua.BOX_ZONE_HEIGHT
    assert [o.guid for o in zone.getObjects().values()] == ["4581f8"], "the zone holds the Box and nothing else"


def test_a_box_still_in_the_bag_gets_its_zone_where_the_unpack_lays_it(rt):  # noqa: F811
    out = run(rt, make_zone())
    zone = rt.globals().getObjectFromGUID(out["guid"])
    assert out["status"] == "created" and out["box"] is False and (zone.pos.x, zone.pos.z) == SPOT
    assert (zone.scale.x, zone.scale.z) == (lua.BOX_ZONE_SIZE, lua.BOX_ZONE_SIZE), "its turn is not known yet: a square that fits both ways"


def test_the_box_is_found_by_its_cards_when_its_guid_is_not_the_one_of_the_data(rt):  # noqa: F811
    loose(rt, 17705, 10, 5, guid="whatever", up=False)                       # one loose card left: TTS gave it a GUID of its own
    out = run(rt, make_zone())
    zone = rt.globals().getObjectFromGUID(out["guid"])
    assert out["box"] is True and (zone.pos.x, zone.pos.z) == (10, 5)


def test_a_zone_that_exists_is_used_kept_on_resume_and_moved_to_the_box_on_a_new_game(rt):  # noqa: F811
    make_deck(rt)                                                            # at (24, 2)
    zone_around(rt, 0, 20)                                                   # an old one, far from the Box
    assert run(rt, make_zone([ZONE])) == {"guid": ZONE, "status": "found", "box": False}
    assert rt.globals().getObjectFromGUID(ZONE).pos.z == 20, "a resume leaves it where it is"
    assert run(rt, make_zone([ZONE], recenter=True)) == {"guid": ZONE, "status": "moved", "box": True}
    assert rt.globals().getObjectFromGUID(ZONE).pos.x == 24
    assert run(rt, make_zone([ZONE], recenter=True))["status"] == "found"
    assert len(rt.globals().SPAWNS) == 0, "nothing was created"


def test_an_unsaved_zone_of_an_earlier_run_is_adopted_not_duplicated(rt):  # noqa: F811
    make_deck(rt)
    rt.execute(f"local z = mkobj({{guid = 'old', type = 'Scripting', cx = 24, cz = 2, hw = 1.75, hd = 1.2}}); z.pos = Vector(24, 4, 2); "
               f"z.scale = Vector(3.5, 5, 2.4)")
    assert run(rt, make_zone()) == {"guid": "old", "status": "adopted", "box": True}


def test_the_box_is_found_inside_its_zone_whatever_its_guid_and_far_from_the_spot(rt):  # noqa: F811
    make_deck(rt, guid="regrouped")
    rt.execute("getObjectFromGUID('regrouped').pos = Vector(-8, 2.5, 14)")
    zone_around(rt, -8, 14)
    out = run(rt, reveal(17703, 1, zone=ZONE))
    assert out["taken"] is True
    assert run(rt, reveal(17704, 1)) == {"taken": False, "deck": False}, "without a zone the Box this far from the spot is not found"


def test_a_box_outside_its_zone_is_not_the_box(rt):  # noqa: F811
    make_deck(rt)                                                            # (24, 2)
    zone_around(rt, 0, 20)
    assert run(rt, reveal(17703, 1, zone=ZONE)) == {"taken": False, "deck": False}


def hand_zone(rt, guid, cx, cz, hw, hd):
    """A hand zone like the table's (type Hand, its bounds are real)."""
    rt.execute(f"local h = mkobj({{guid = '{guid}', type = 'Hand'}}); h.getBounds = function() return {{center = Vector({cx}, 1, {cz}), size = Vector({hw * 2}, 1, {hd * 2})}} end")


def table_zones(rt):
    """The real table (config/table.json): Green's hand from x 25.1 and White's to x -25.1, and the discard zones as the config puts them
    (world bounds of 35.43 x 8.55 turned 270 degrees: long along z)."""
    hand_zone(rt, "greenhand", 30.0, 0.0, 4.9, 12.0)
    hand_zone(rt, "whitehand", -30.0, 0.0, 4.9, 12.0)
    rt.execute("HAND_ZONES = {{color = 'Green', cx = 30.0, cz = 0.0, hw = 4.9, hd = 12.0}, {color = 'White', cx = -30.0, cz = 0.0, hw = 4.9, hd = 12.0}}")
    for guid, cx, cz, hw, hd in (("906a7a", 17.4677, 0.7422, 4.2732, 17.7153), ("b7a0b8", -15.4623, 0.6652, 5.47615, 16.58125)):
        rt.execute(f"local z = getObjectFromGUID('{guid}') or mkobj({{guid = '{guid}', type = 'Scripting', cx = 0, cz = 0, hw = 1, hd = 1}}); "
                   f"z.cx, z.cz, z.hw, z.hd = {cx}, {cz}, {hw}, {hd}; z.pos = Vector({cx}, 4.1, {cz})")


LIMITS = (26.0, 36.0)
BOT_PILES = [(5.13, 17.71), (17.5, -14.0)]
AVOID = ["906a7a", "b7a0b8"]


def card_rect(x, z, yaw):
    """The table footprint of a card turned `yaw`: (x0, x1, z0, z1)."""
    c, s = abs(math.cos(math.radians(yaw))), abs(math.sin(math.radians(yaw)))
    hx, hz = (lua.BOX_CARD_SHORT * c + lua.BOX_CARD_LONG * s) / 2, (lua.BOX_CARD_SHORT * s + lua.BOX_CARD_LONG * c) / 2
    return x - hx, x + hx, z - hz, z + hz


def overlap(a, b, tol=lua.BOX_OVERLAP_TOLERANCE):
    return min(a[1], b[1]) - max(a[0], b[0]) > tol and min(a[3], b[3]) - max(a[2], b[2]) > tol


def zone_rect(rt, guid):
    b = rt.eval(f"(function() local z = getObjectFromGUID('{guid}'); local b = z.getBounds(); return {{b.center.x, b.center.z, b.size.x, b.size.z}} end)()")
    cx, cz, sx, sz = b[1], b[2], b[3], b[4]
    return cx - sx / 2, cx + sx / 2, cz - sz / 2, cz + sz / 2


ORDER = (17701, 17702, 17703, 17704, 17705, 17706, 17700)        # the seven Miseries in the order they are revealed (the last one is the Box's last card: a Card, moved)


def real_session(bot, human):
    """What the session knows of the REAL table (config/table.json) when `bot` plays against `human`."""
    cfg = real_config(bot, human).session_config()
    cfg.bot_discard_zone, cfg.human_discard_zone = "906a7a", "b7a0b8"
    return SimpleNamespace(cfg=cfg)


def lay_the_real_table(rt, session, human):
    """Hands, discards and the Box beside her deck with its zone, as the unpack and the start-up leave them; returns the pile of her side."""
    table_zones(rt)
    side = "human" if human else "bot"
    geo = session.cfg.human_seat_geo if human else session.cfg.bot_seat_geo
    x, z, yaw = box_layout.box_place(RAW, side, geo)
    make_deck(rt, at=(x, z), yaw=yaw)
    zone = run(rt, lua.box_zone([], MISERIES, identity=TEST_IDENTITY, spot=(x, z), avoid=AVOID))["guid"]
    setattr(session.cfg, "human_box_zone" if human else "box_zone", zone)
    return session_pandora.pile_of(session, human), zone


def lay_pile(rt, pile, zone, reveal=None, order=ORDER, spot=None):
    """The seven reveals in a row on the stub table; returns the answers and where each card ended up: (x, z, yaw, y, hand)."""
    spot = spot or tuple(RAW["human_deck_spot"])
    answers = []
    for slot, card in enumerate(order, 1):
        if reveal is None:
            answers.append(run(rt, lua.box_reveal(MISERIES, card % 100, slot, identity=TEST_IDENTITY, spot=spot, zone=zone, pile=pile)))
        else:
            answers.append(run(rt, lua.box_draw_top(MISERIES, slot, identity=TEST_IDENTITY, spot=spot, zone=zone, reveal_zone=reveal, pile=pile)))
    objs = [rt.globals().getObjectFromGUID(f"c{card}") for card in order]
    return answers, [(o.pos.x, o.pos.z, o.rot.y, o.pos.y, o.hand) for o in objs]


def heading(dx, dz):
    return math.degrees(math.atan2(dx, dz)) % 360


def assert_pile_is_clear(rt, spots, pile, zone, keep):
    """No card of the pile lies in a hand or on a hand zone (the stub sends a card dropped there to that hand), a discard, the Box's zone,
    something of her layout or off the table, and no two cards of it sit at the same place."""
    blocked = [zone_rect(rt, g) for g in ("greenhand", "whitehand", "906a7a", "b7a0b8", zone)] + [(k[0] - k[2], k[0] + k[2], k[1] - k[3], k[1] + k[3]) for k in keep]
    rects = []
    for x, z, yaw, _, hand in spots:
        rect = card_rect(x, z, yaw)
        rects.append(rect)
        assert hand is None, "a card dropped in a hand zone goes to that hand"
        assert not any(overlap(rect, b) for b in blocked), (x, z, yaw)
        assert -LIMITS[0] <= rect[0] and rect[1] <= LIMITS[0] and abs(rect[2]) <= LIMITS[1] and abs(rect[3]) <= LIMITS[1]
    assert len({(round(x, 3), round(z, 3)) for x, z, *_ in spots}) == 7


def test_the_bot_s_pile_lies_below_her_deck_toward_her_seat_on_the_real_table(rt):  # noqa: F811
    """Green's seat is at +x: below her deck is +x, between the deck (5.13, 17.71) and her discard zone (from x 13.2): seven cards fit when each lies
    half a step tighter than the roomy one, the cards upright for her seat (the yaw of her deck)."""
    session = real_session("pandora", "hellboy")
    pile, zone = lay_the_real_table(rt, session, human=False)
    answers, spots = lay_pile(rt, pile, zone)
    assert [a["side"] for a in answers] == ["below"] * 7 and not any(a["crowded"] for a in answers)
    assert_pile_is_clear(rt, spots, pile, zone, session.cfg.bot_seat_geo.keep)
    assert {round(z, 3) for _, z, *_ in spots} == {17.71} and {round(yaw % 360) for _, _, yaw, *_ in spots} == {90}
    xs = [x for x, *_ in spots]
    steps = {round(b - a, 3) for a, b in zip(xs, xs[1:])}
    assert xs == sorted(xs) and xs[0] == pytest.approx(5.13 + 1.65 + lua.BOX_PILE_GAP + 1.65) and len(steps) == 1
    assert 0.45 <= steps.pop() <= 0.6, "each card shows at least a strip of the one under it"


def test_the_human_s_pile_lies_below_their_box_toward_their_seat_on_the_real_table(rt):  # noqa: F811
    """Ivan 26/11/2026: the human's pile is anchored on the Box (-6.7, 20.05), not on their deck: starting just below it from the White seat
    (toward -x), upright (yaw 270), the cascade toward the seat. It clears their discard zone (which ends at z 17.246 and x -9.986), the
    hand zones, their deck, the Box's zone, their layout and the edge of the table."""
    session = real_session("hellboy", "pandora")
    pile, zone = lay_the_real_table(rt, session, human=True)
    assert pile.anchor == pytest.approx((-6.7, 20.05))
    answers, spots = lay_pile(rt, pile, zone, spot=(-6.7, 20.05))
    assert [a["side"] for a in answers] == ["below"] * 7 and not any(a["crowded"] for a in answers)
    assert_pile_is_clear(rt, spots, pile, zone, session.cfg.human_seat_geo.keep)
    assert {round(z, 3) for _, z, *_ in spots} == {20.05}
    xs = [round(x, 2) for x, *_ in spots]
    assert xs == [-10.2, -10.8, -11.4, -12.0, -12.6, -13.2, -13.8], "just below the Box (gap 0.2), every 0.6 toward their seat (-x)"
    assert {round(yaw % 360) for _, _, yaw, *_ in spots} == {270}
    assert min(z for _, z, *_ in spots) - 1.1 > 17.246 and max(xs) + 1.65 < -8.0, "clear of the discard zone (to z 17.246) and of the Box"


def test_the_human_s_pile_goes_to_a_side_of_the_box_and_then_above_it_when_below_is_blocked(rt):  # noqa: F811
    for keep, side in ((((-11.0, 20.05, 1.0, 1.0),), "side"), (((-11.0, 20.05, 1.0, 1.0), (-8.0, 22.9, 5.0, 0.9), (-8.0, 17.2, 5.0, 0.9)), "above")):
        make_deck(rt, at=(-6.7, 20.05), yaw=270)
        out = run(rt, lua.box_reveal(MISERIES, 1, 1, identity=TEST_IDENTITY, spot=(-6.7, 20.05),
                                     pile=pile_at(x=-6.7, z=20.05, up=270.0, down=(-1.0, 0.0), keep=keep)))
        assert out["side"] == side and out["crowded"] is False
        rt.execute("getObjectFromGUID('c17701'):destruct()") if False else rt.execute("for _, o in ipairs(getObjects()) do o.destruct() end")


@pytest.mark.parametrize("human", [False, True])
def test_the_cards_of_the_pile_are_turned_so_their_bottom_edge_points_along_the_cascade(rt, human):  # noqa: F811
    """Whatever side the pile takes, the card's yaw is the one the layout was computed for: relative to the way her seat faces, the bottom
    edge of each card points the way the cascade runs (an earlier bug laid the row with the orientation it was not planned for)."""
    session = real_session("hellboy", "pandora") if human else real_session("pandora", "hellboy")
    pile, zone = lay_the_real_table(rt, session, human)
    _, spots = lay_pile(rt, pile, zone)
    geo = session.cfg.human_seat_geo if human else session.cfg.bot_seat_geo
    cascade = heading(spots[1][0] - spots[0][0], spots[1][1] - spots[0][1])
    assert (cascade - spots[0][2]) % 360 == pytest.approx((heading(*geo.down) - geo.up_yaw) % 360)
    rects = [card_rect(x, z, yaw) for x, z, yaw, *_ in spots]
    assert all(overlap(a, b, 0.0) for a, b in zip(rects, rects[1:])), "each card overlaps the one before it: a pile, not a row"
    assert all(spots[i + 1][3] > spots[i][3] for i in range(6)), "and lies higher, so it ends on top of it"


def test_the_stub_hands_a_card_laid_in_a_hand_zone_to_that_hand(rt):  # noqa: F811
    """The control of the next test: a fake that never drops a card into a hand zone would prove nothing."""
    table_zones(rt)
    make_deck(rt, at=(10, 2))
    rt.execute("getObjectFromGUID('4581f8').takeObject({position = Vector(30, 2, 0)})")
    assert rt.eval("getObjectFromGUID('c17700').hand") == "Green"


def test_a_pile_that_cannot_go_below_her_deck_does_not_reach_a_hand_zone_and_the_table_does_not_hand_it_a_card(rt):  # noqa: F811
    table_zones(rt)
    make_deck(rt, at=(10, 2))
    pile = pile_at(x=20.0, z=2.0, limits=LIMITS)                   # her deck by the hand zone, her seat beyond it: below would end in the hand
    answers, spots = lay_pile(rt, pile, None, spot=(10.0, 2.0))
    assert [a["side"] for a in answers] == ["side"] * 7, "below would be the hand zone: the next side"
    assert all(hand is None for *_, hand in spots)


def test_with_no_free_side_anywhere_the_least_crowded_is_taken_and_said(rt):  # noqa: F811
    make_deck(rt)
    out = run(rt, reveal(17701, 1, pile=pile_at(limits=(5.0, 5.0))))
    assert out["taken"] is True and out["crowded"] is True
    assert run(rt, reveal(17702, 2))["crowded"] is False


BELOW_BLOCKED = ((14.0, 2.5, 2.0, 0.5),)                         # something where her seat's side of the deck is
SIDES_BLOCKED = (*BELOW_BLOCKED, (12.0, 4.4, 5.0, 0.9), (12.0, -0.4, 5.0, 0.9))


@pytest.mark.parametrize("keep, side", [((), "below"), (BELOW_BLOCKED, "side"), (SIDES_BLOCKED, "above")])
def test_the_sides_are_tried_in_order_below_a_side_then_above_and_each_clear_one_is_not_crowded(rt, keep, side):  # noqa: F811
    """`keep` = rectangles of what lies around her deck (her character card, dial, pieces)."""
    make_deck(rt)
    out = run(rt, reveal(17701, 1, pile=pile_at(keep=keep)))
    assert out["side"] == side and out["crowded"] is False


@pytest.mark.parametrize("discard_z, toward", [(-20.0, 1), (20.0, -1)])
def test_the_side_the_pile_falls_back_to_is_the_one_away_from_her_discard(rt, discard_z, toward):  # noqa: F811
    make_deck(rt)
    run(rt, reveal(17701, 1, pile=pile_at(keep=BELOW_BLOCKED, away_from=((10.0, discard_z),))))
    assert (rt.globals().getObjectFromGUID("c17701").pos.z - 2) * toward > 0


def test_the_pile_of_the_other_seat_runs_toward_minus_x_upright_for_that_seat(rt):  # noqa: F811
    make_deck(rt)
    run(rt, reveal(17701, 1, pile=pile_at(x=-10.0, up=270.0, down=(-1.0, 0.0))))
    card = rt.globals().getObjectFromGUID("c17701")
    assert card.pos.x == pytest.approx(-10 - 1.65 - lua.BOX_PILE_GAP - 1.65) and card.rot.y == 270


def put_back_in(zone):
    return lua.box_put_back(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=zone)


def test_nothing_revealed_lies_in_the_zone_and_the_end_of_the_turn_gathers_it_all_back(rt):  # noqa: F811
    make_deck(rt)
    zone_around(rt, 24, 2, half=1.75, half_z=1.2)
    for slot, card in enumerate((17701, 17703, 17706), 1):
        assert run(rt, lua.box_reveal(MISERIES, card % 100, slot, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE, pile=pile_at(x=10.0)))["taken"]
    assert [o.guid for o in rt.globals().getObjectFromGUID(ZONE).getObjects().values()] == [MISERIES], "only the Box is in its zone"
    assert run(rt, lua.box_put_back(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE)) == {"added": 3, "deck": True, "quantity": 7}
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is True


def test_with_no_box_left_the_first_misery_back_is_laid_at_the_centre_of_the_zone(rt):  # noqa: F811
    zone_around(rt, 5, 6)
    for slot, cid in enumerate((17702, 17703), 1):
        loose(rt, cid, 24, 2 + 3 * slot)
    out = run(rt, lua.box_put_back(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE))
    assert out["added"] == 2 and out["deck"] is True and out["quantity"] == 2


def test_the_box_is_shuffled_at_set_up_and_a_single_card_has_nothing_to_shuffle(rt):  # noqa: F811
    make_deck(rt)
    zone_around(rt, 24, 2, half=1.2)
    assert run(rt, lua.box_shuffle(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE)) == {"deck": True, "shuffled": True}
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is True
    rt.execute("getObjectFromGUID('4581f8').destruct()")
    assert run(rt, lua.box_shuffle(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE)) == {"deck": False, "shuffled": False}


# ---------------------------------------------------------------- the human's Box in Lua

REVEAL = "revzone"


def reveal_zone_at(rt, x, z, half_x=8.95, half_z=1.85):
    rt.execute(f"local z = mkobj({{guid = '{REVEAL}', type = 'Scripting', cx = {x}, cz = {z}, hw = {half_x}, hd = {half_z}}}); z.pos = Vector({x}, 4, {z})")


def draw(slot=1, zone=ZONE, pile=None):
    return lua.box_draw_top(MISERIES, slot, identity=TEST_IDENTITY, spot=SPOT, zone=zone, reveal_zone=REVEAL, pile=pile or pile_at())


def make_reveal_zone(rt, pile, guid=REVEAL):
    """The reveal zone as the start-up makes it around `pile`, under a GUID the tests know."""
    out = run(rt, lua.box_reveal_zone([], pile))
    rt.execute(f"getObjectFromGUID('{out['guid']}').guid = '{guid}'")
    return out


def test_the_reveal_zone_is_made_around_the_pile_of_seven_places_and_holds_every_card_of_it(rt):  # noqa: F811
    make_deck(rt)
    pile = pile_at()
    out = make_reveal_zone(rt, pile)
    assert out["status"] == "created" and out["crowded"] is False and out["side"] == "below"
    zone = zone_rect(rt, REVEAL)
    first = 10 + 1.65 + lua.BOX_PILE_GAP
    length = 3.3 + 6 * lua.BOX_PILE_STEPS[0]
    assert zone[0] == pytest.approx(first - lua.BOX_PILE_MARGIN) and zone[1] == pytest.approx(first + length + lua.BOX_PILE_MARGIN)
    assert (zone[3] - zone[2]) == pytest.approx(lua.BOX_CARD_SHORT + 2 * lua.BOX_PILE_MARGIN) and (zone[2] + zone[3]) / 2 == pytest.approx(2)
    for slot in range(1, 8):
        assert run(rt, draw(slot, pile=pile))["taken"]
    inside = rt.eval("(function() local n = 0 for _, o in ipairs(getObjectFromGUID('revzone').getObjects()) do if o.type == 'Card' then n = n + 1 end end return n end)()")
    assert inside == 7, "all seven cards of the pile lie in the reveal zone, the Box's own not among them"


@pytest.mark.parametrize("human, bot_name, human_name", [(False, "pandora", "hellboy"), (True, "hellboy", "pandora")])
def test_the_reveal_zone_covers_the_pile_and_keeps_clear_of_hands_discards_the_box_and_the_edge_with_the_real_geometry(rt, human, bot_name, human_name):  # noqa: F811
    session = real_session(bot_name, human_name)
    pile, zone = lay_the_real_table(rt, session, human)
    out = make_reveal_zone(rt, pile)
    assert out["crowded"] is False
    reveal = zone_rect(rt, REVEAL)
    keep = (session.cfg.human_seat_geo if human else session.cfg.bot_seat_geo).keep
    blocked = [zone_rect(rt, g) for g in ("greenhand", "whitehand", "906a7a", "b7a0b8", zone)] + [(k[0] - k[2], k[0] + k[2], k[1] - k[3], k[1] + k[3]) for k in keep]
    assert not any(overlap(reveal, b) for b in blocked), reveal
    assert -LIMITS[0] <= reveal[0] and reveal[1] <= LIMITS[0] and abs(reveal[2]) <= LIMITS[1] and abs(reveal[3]) <= LIMITS[1]
    _, spots = lay_pile(rt, pile, zone, reveal=REVEAL)
    for x, z, yaw, *_ in spots:
        rect = card_rect(x, z, yaw)
        assert reveal[0] - 1e-6 <= rect[0] and rect[1] <= reveal[1] + 1e-6 and reveal[2] - 1e-6 <= rect[2] and rect[3] <= reveal[3] + 1e-6, (rect, reveal)


def test_the_reveal_zone_with_nowhere_to_go_is_made_where_it_hurts_least_and_said(rt):  # noqa: F811
    assert run(rt, lua.box_reveal_zone([], pile_at(limits=(5.0, 5.0))))["crowded"] is True


def test_an_existing_reveal_zone_is_used_moved_on_a_new_game_and_never_duplicated(rt):  # noqa: F811
    first = run(rt, lua.box_reveal_zone([], pile_at()))["guid"]
    spawned = len(rt.globals().SPAWNS)
    rt.execute(f"local z = getObjectFromGUID('{first}'); z.setPosition = function(p) z.pos = Vector(p); z.cx, z.cz = p.x, p.z end")
    assert run(rt, lua.box_reveal_zone([first], pile_at()))["status"] == "found"
    assert run(rt, lua.box_reveal_zone([first], pile_at(x=-30.0), recenter=True))["status"] == "moved"
    assert len(rt.globals().SPAWNS) == spawned


def test_a_zone_of_the_same_size_that_is_somebody_else_s_is_never_taken_for_the_reveal_zone(rt):  # noqa: F811
    made = run(rt, lua.box_reveal_zone([], pile_at()))["guid"]
    rt.execute(f"getObjectFromGUID('{made}').guid = 'otherzone'")
    out = run(rt, lua.box_reveal_zone([], pile_at(avoid=("otherzone",))))
    assert out["status"] == "created" and out["guid"] not in ("otherzone", made)
    assert run(rt, lua.box_reveal_zone([], pile_at()))["status"] == "adopted", "an unsaved one of an earlier run is adopted"


def test_the_button_takes_the_top_card_face_up_into_the_next_place_of_the_pile_and_reads_its_card_id(rt):  # noqa: F811
    make_deck(rt, ids=[17704, 17701, 17706, 17700, 17703, 17702, 17705])      # the first one is the top
    zone_around(rt, 24, 2, half=1.75, half_z=1.2)
    pile = pile_at()
    make_reveal_zone(rt, pile)
    rt.execute("local d = getObjectFromGUID('4581f8'); local take = d.takeObject\n"
               "d.takeObject = function(t) TAKEN = {pos = t.position, guid = t.guid, rot = t.rotation}; return take(t) end")
    out = run(rt, draw(1, pile=pile))
    assert out == {"taken": True, "idx": 4, "guid": "c17704", "crowded": False, "side": "below"}, "the top card, not one chosen by the engine"
    assert rt.eval("TAKEN.guid") is None and rt.eval("TAKEN.rot.y") == 90 and rt.eval("TAKEN.rot.z") == 0, "no GUID asked for: the top; face up, upright for her seat"
    first = 10 + 1.65 + lua.BOX_PILE_GAP + 1.65
    assert round(rt.eval("TAKEN.pos.x"), 3) == round(first, 3) and rt.eval("TAKEN.pos.z") == 2
    assert run(rt, draw(2, pile=pile))["idx"] == 1 and round(rt.eval("TAKEN.pos.x"), 3) == round(first + lua.BOX_PILE_STEPS[0], 3)
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 5
    assert run(rt, lua.box_read(REVEAL, identity=TEST_IDENTITY)) == {"zone": True, "cards": [{"idx": 4, "guid": "c17704"}, {"idx": 1, "guid": "c17701"}]}


def test_the_last_loose_card_of_the_box_is_dealt_and_an_empty_or_missing_box_or_zone_is_not(rt):  # noqa: F811
    zone_around(rt, 24, 2, half=1.2)
    assert run(rt, draw()) == {"taken": False, "deck": False}, "no Box on the table"
    loose(rt, 17703, 24, 2, guid="lastone", up=False)
    assert run(rt, draw()) == {"taken": False, "zone": False}, "no reveal zone: nothing is taken"
    make_reveal_zone(rt, pile_at())
    assert run(rt, draw()) == {"taken": True, "idx": 3, "guid": "lastone", "crowded": False, "side": "below"}
    assert rt.globals().getObjectFromGUID("lastone").pos.x > 10 + 1.65
    assert run(rt, draw(2)) == {"taken": False, "deck": False}, "the Box lies in the zone no more"


def test_the_reveal_zone_read_lists_the_miseries_face_up_and_only_those(rt):  # noqa: F811
    reveal_zone_at(rt, 34.7, 2)
    loose(rt, 17702, 30, 2, up=True)
    loose(rt, 17703, 31, 2, up=False)                                          # face down: not revealed
    loose(rt, 17700, 32, 2, guid="houdini", owner="houdini", up=True)          # Houdini's character card shares 17700
    loose(rt, 17704, 5, 5, up=True)                                            # face up but elsewhere
    out = run(rt, lua.box_read(REVEAL, identity=TEST_IDENTITY))
    assert out == {"zone": True, "cards": [{"idx": 2, "guid": "c17702"}]}
    assert run(rt, lua.box_read("nozone", identity=TEST_IDENTITY)) == {"zone": False, "cards": []}


def test_a_face_up_deck_in_the_reveal_zone_counts_card_by_card_and_only_its_own(rt):  # noqa: F811
    reveal_zone_at(rt, 34.7, 2)
    rt.execute("mkobj({guid = 'stack', type = 'Deck', is_face_down = false, pos = Vector(30, 2, 2), cards = {"
               "{cid = 17702, guid = 'a', owner = 'misery'}, {cid = 17703, guid = 'b', owner = 'houdini'}, {cid = 17704, guid = 'c', owner = 'misery'}}})")
    assert run(rt, lua.box_read(REVEAL, identity=TEST_IDENTITY))["cards"] == [{"idx": 2, "guid": "a"}, {"idx": 4, "guid": "c"}]


@pytest.mark.parametrize("up", [False, True])
def test_the_top_card_is_peeked_without_moving_it_inside_the_box_zone_face_up_or_down(rt, up):  # noqa: F811
    make_deck(rt, ids=[17705, 17701, 17700], guid="regrouped")
    rt.execute(f"local d = getObjectFromGUID('regrouped'); d.is_face_down = {str(not up).lower()}")
    zone_around(rt, 24, 2, half=1.2)
    out = run(rt, lua.box_peek_top(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE))
    assert out == {"found": True, "idx": 5} and rt.eval("getObjectFromGUID('regrouped').getQuantity()") == 3


class OnTable:
    """The session's client with the generated Lua run for real against the stub table."""
    def __init__(self, rt):
        self.rt = rt

    def call_lua(self, script):
        return run(self.rt, script)


def on_the_stub(session, rt, monkeypatch, bot_box=SPOT, human_box=None):  # noqa: F811
    real = session_pandora._table_of
    monkeypatch.setattr(session_pandora, "_table_of", lambda s, p: (lambda tb: tb and replace(tb, box=tb.box and replace(tb.box, identity=TEST_IDENTITY)))(real(s, p)))
    session.client = OnTable(rt)
    session.cfg.box_spot, session.cfg.human_box_spot = bot_box, human_box
    session.cfg.zone_spawns, session.cfg.remove_plan = {}, ()                 # only the Box's zone is at stake
    session._startup_notes = []
    return session


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_start_up_creates_the_zone_around_the_box_and_the_session_file_keeps_it(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch)
    make_deck(rt)
    session.prepare_table(resume=False)
    guid = session.cfg.box_zone
    assert guid and rt.globals().getObjectFromGUID(guid).type == "Scripting"
    assert session.to_dict()["zones_live"] == {"box_zone": guid}
    assert any(guid in text and t("pandora.box_zone_at_box") in text for text, _ in session._startup_notes)


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_resume_finds_the_saved_zone_and_makes_no_other(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch)
    make_deck(rt)
    session.prepare_table(resume=False)
    saved = session.to_dict()["zones_live"]
    spawned = len(rt.globals().SPAWNS)
    session.cfg.box_zone = None                                              # a new process: the configuration does not know it
    session._zone_origin.pop("box_zone")
    session._saved_zones = session.read_saved_zones(saved)
    session.prepare_table(resume=True)
    assert session.cfg.box_zone == saved["box_zone"] and len(rt.globals().SPAWNS) == spawned
    assert session.to_dict()["zones_live"] == saved


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_zone_overlapping_another_one_is_said_in_the_chat(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch)
    make_deck(rt)
    session.cfg.bot_deck_zone = "906a7a"
    rt.execute("local z = getObjectFromGUID('906a7a'); z.cx, z.cz = 24, 2")
    session.prepare_table(resume=False)
    assert any("906a7a" in text and session.cfg.box_zone in text for text, _ in session._startup_notes)


@pytest.mark.parametrize("yaw, said_it", [(0, False), (90, True)])
@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_box_zone_next_to_a_hand_zone_is_only_warned_about_when_the_overlap_is_real(rig, rt, monkeypatch, yaw, said_it):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=(24.0, -4.0))
    table_zones(rt)
    make_deck(rt, at=(24, -4), yaw=yaw)
    session.cfg.bot_discard_zone, session.cfg.human_discard_zone = "906a7a", "b7a0b8"
    session.prepare_table(resume=False)
    assert any(t("pandora.box_zone_overlaps", guid=session.cfg.box_zone, others="greenhand") == text for text, _ in session._startup_notes) == said_it
    assert not any("906a7a" in text or "b7a0b8" in text for text, _ in session._startup_notes if "overlaps" in text or "solapa" in text)


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_the_box_is_shuffled_when_the_game_is_set_up_but_not_when_it_is_resumed(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch)
    make_deck(rt)
    session.prepare_table(resume=False)
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is True
    rt.execute("getObjectFromGUID('4581f8').shuffled = nil")
    saved = session.to_dict()["zones_live"]
    session.cfg.box_zone = None
    session._zone_origin.pop("box_zone")
    session._saved_zones = session.read_saved_zones(saved)
    session.prepare_table(resume=True)
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is None, "a game resumed mid-turn keeps its order"


@with_rig("hellboy", "pandora", *HAND)
def test_the_human_s_box_is_shuffled_at_set_up_too(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=None, human_box=(-24.0, 10.5))
    make_deck(rt)
    rt.execute("getObjectFromGUID('4581f8').pos = Vector(-20, 2.5, 8)")
    session.prepare_table(resume=False)
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is True


@with_rig("hellboy", "pandora", *HAND)
def test_the_human_pandora_s_box_gets_a_zone_and_a_reveal_zone_saved_on_resume(rig, rt, monkeypatch):  # noqa: F811
    session = rig[0]
    on_the_stub(session, rt, monkeypatch, bot_box=None, human_box=(-6.7, 20.05))
    session.cfg.human_deck_spot = (-6.7, 17.55)
    make_deck(rt, at=(-6.7, 20.05), yaw=270)
    session.prepare_table(resume=False)
    guid, reveal_guid = session.cfg.human_box_zone, session.cfg.human_reveal_zone
    zone, reveal_zone = rt.globals().getObjectFromGUID(guid), rt.globals().getObjectFromGUID(reveal_guid)
    assert guid and reveal_guid and session.cfg.box_zone is None and (zone.pos.x, zone.pos.z) == (-6.7, 20.05)
    length = lua.BOX_CARD_LONG + 6 * lua.BOX_PILE_STEPS[0] + 2 * lua.BOX_PILE_MARGIN
    first = -6.7 - 1.65 - lua.BOX_PILE_GAP
    assert (reveal_zone.pos.x, reveal_zone.pos.z) == pytest.approx((first - length / 2 + lua.BOX_PILE_MARGIN, 20.05)), "below their Box, toward their seat at -x"
    assert (reveal_zone.scale.x, reveal_zone.scale.z) == pytest.approx((length, lua.BOX_CARD_SHORT + 2 * lua.BOX_PILE_MARGIN)), "the pile of seven cards"
    assert session.to_dict()["zones_live"] == {"human_box_zone": guid, "human_reveal_zone": reveal_guid}
    spawned = len(rt.globals().SPAWNS)
    for key in ("human_box_zone", "human_reveal_zone"):                      # a new process: the configuration does not know them
        setattr(session.cfg, key, None)
        session._zone_origin.pop(key)
    session._saved_zones = session.read_saved_zones({"human_box_zone": guid, "human_reveal_zone": reveal_guid})
    session.prepare_table(resume=True)
    assert (session.cfg.human_box_zone, session.cfg.human_reveal_zone) == (guid, reveal_guid) and len(rt.globals().SPAWNS) == spawned


@with_rig("hellboy", "pandora", *HAND)
def test_the_human_s_start_up_lays_the_reveal_zone_around_the_pile_below_their_box_and_says_nothing(rig, rt, monkeypatch):  # noqa: F811
    """The real table: the pile lies just below the Box (toward -x), clear of their discard zone, so nothing needs saying."""
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=None, human_box=(-6.7, 20.05))
    session.cfg.bot_discard_zone, session.cfg.human_discard_zone = "906a7a", "b7a0b8"
    table_zones(rt)
    make_deck(rt, at=(-6.7, 20.05), yaw=270)
    session.prepare_table(resume=False)
    made = rt.globals().getObjectFromGUID(session.cfg.human_reveal_zone)
    assert made.pos.x + made.scale.x / 2 < -8.0 and made.pos.z == pytest.approx(20.05), "from just below the Box toward their seat (-x)"
    assert not [text for text, _ in session._startup_notes if t("pandora.pile_moved", where=t("pandora.pile_where.above")) == text or "pile_moved" in text]
    assert not session._pile_moved_said


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_the_bot_says_once_that_its_pile_is_not_below_its_deck_and_where_it_lies_instead(rig, order, monkeypatch):  # noqa: F811
    session, table, game, fake, cfg = rig
    table.box_pile_side = "side"
    msgs = box_turn(rig, order, monkeypatch, ("Toil", "Pain"), keep=(True, False))
    assert sum(t("pandora.pile_moved", where=t("pandora.pile_where.side")) in m for m in msgs) == 1, msgs


# ---------------------------------------------------------------- the human's Box: the bot deals it, reads it and looks at it

def human_box(rig, *top_first, row=(), start=False):
    """The human's Box on the table, its zones known. `start` opens the question like the turn does: the bot deals the first Misery by itself."""
    session, table = rig[0], rig[1]
    session.cfg.human_box_zone, session.cfg.human_reveal_zone = "hboxz", "hrevz"
    table.human_box, table.human_row = list(top_first), list(row)
    if start:
        session._announce_human_start()               # the start of their turn as the session runs it: it shows the question, the bot deals
    return session, table, rig[2]


def button(session, table, i):
    return click(session, table, Event.CHOICE, {"i": i})


def misery(name):
    return 17700 + IDX[name]


@with_rig("hellboy", "pandora", *HAND)
def test_the_panel_offers_the_three_ways_to_reveal_and_the_button_deals_the_top_card_to_the_engine(rig):
    session, table, game = human_box(rig, misery("Misfortune"), misery("Toil"))
    assert labels(session) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")]
    msgs = button(session, table, 1)
    assert said(msgs, t("pandora.dealt", misery=t("pandora.misery.misfortune")))
    assert table.human_row == [misery("Misfortune")] and table.human_slots == [1] and game.fx.counter_value(1, "box_mask") == 1 << IDX["Misfortune"]
    assert session.effect_run.awaiting.kind == "optional" and labels(session) == [t("choice.yes"), t("choice.no")], "not three feathers: asks to go on"


@with_rig("hellboy", "pandora", *HAND)
def test_the_first_misery_of_the_turn_is_revealed_by_the_bot_with_no_click(rig):
    """The first reveal is mandatory: the question is not even shown, the bot takes the top card of the real Box and tells the engine which it is."""
    session, table, game = human_box(rig, misery("Misfortune"), misery("Toil"), start=True)
    assert table.human_row == [misery("Misfortune")] and table.human_slots == [1] and table.human_box == [misery("Toil")]
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Misfortune"], "the engine knows which one it is"
    assert session.effect_run.awaiting.kind == "optional" and labels(session) == [t("choice.yes"), t("choice.no")], "the only question: reveal another or stop"


@with_rig("hellboy", "pandora", *HAND)
def test_yes_reveals_the_next_misery_by_itself_and_stopping_is_the_other_button(rig):
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"), misery("Greed"), start=True)
    assert labels(session) == [t("choice.yes"), t("choice.no")]
    msgs = press(session, table, True)
    assert said(msgs, t("pandora.dealt", misery=t("pandora.misery.pain"))) and table.human_row == [misery("Toil"), misery("Pain")]
    assert table.human_slots == [1, 2], "the next place of the pile"
    assert labels(session) == [t("choice.yes"), t("choice.no")], "the Reveal buttons are not shown again"
    press(session, table, False)
    assert session.effect_run is None and game.fighters["pandora"].hp == 14 and table.human_box == [misery("Greed")]


@with_rig("hellboy", "pandora", *HAND)
def test_three_feathers_stop_with_the_damage_and_no_further_question(rig):
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"), misery("Misfortune"), start=True)
    press(session, table, True)
    msgs = press(session, table, True)                                        # 1 + 1 + 2 feathers
    assert session.effect_run is None and game.fighters["pandora"].hp == 14 - 3, msgs
    assert said(msgs, t("narr.notice.pandora_three_feathers")) and table.human_slots == [1, 2, 3]
    assert said(msgs, t("pandora.dealt", misery=t("pandora.misery.misfortune")))


@with_rig("hellboy", "pandora", *HAND)
def test_the_automatic_reveal_works_on_every_turn_of_the_human(rig):
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"), start=True)
    press(session, table, False)
    bot_turn(session, table, [])
    assert table.human_row == [misery("Pain")], "the second turn opened with a reveal: the first one went back into the Box at the end of the first"
    assert game.turn == 1 and game.fx.counter_value(1, "box_mask") != 0
    assert labels(session) == [t("choice.yes"), t("choice.no")]


@with_rig("hellboy", "pandora", *HAND)
def test_when_the_bot_cannot_take_the_card_the_three_buttons_stay_and_it_does_not_try_again_by_itself(rig):
    """Fallbacks: Reveal Misery (try again), I revealed it (zone detection) and Pick on panel."""
    session, table, game = human_box(rig, misery("Pain"), misery("Toil"))
    table.box_gone = True
    session._show_choice(session.effect_run.awaiting)
    assert labels(session) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")] and game.fx.counter_value(1, "box_mask") == 0
    tries = sum("sparring:box_draw_top" in s for s in table.scripts)
    session._show_choice(session.effect_run.awaiting)
    assert sum("sparring:box_draw_top" in s for s in table.scripts) == tries, "one automatic try per question"
    table.box_gone = False
    msgs = button(session, table, 1)
    assert said(msgs, t("pandora.dealt", misery=t("pandora.misery.pain"))) and game.fx.counter_value(1, "box_mask") == 1 << IDX["Pain"]


@with_rig("hellboy", "pandora", *HAND)
def test_a_failed_automatic_reveal_says_why_and_a_missing_reveal_zone_deals_nothing(rig):
    session, table, game = human_box(rig, misery("Pain"), misery("Toil"))
    table.human_zones_missing = {"hrevz"}
    session._show_choice(session.effect_run.awaiting)
    assert table.human_box == [misery("Pain"), misery("Toil")] and table.human_row == [], "a zone that is not there: nothing is taken"
    assert labels(session)[0] == t("btn.pandora_reveal")
    table.human_zones_missing = set()
    msgs = button(session, table, 2)
    assert said(msgs, t("pandora.nothing_new")), "nothing lies on the pile to read"


@with_rig("hellboy", "pandora", *HAND)
def test_a_card_the_table_hands_to_a_hand_zone_is_still_the_answer_but_is_not_on_the_pile(rig):
    """The fake is as unkind as real TTS: a card laid in a hand zone goes to the hand, and the zone does not see it."""
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"))
    table.human_row_in_hand = True
    session._show_choice(session.effect_run.awaiting)
    assert table.human_hand == [misery("Toil")] and table.human_row == []
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Toil"], "the answer came from the card itself"


@with_rig("hellboy", "pandora", *HAND)
def test_the_end_of_the_human_s_turn_puts_the_row_back_in_the_box_and_shuffles_it(rig):
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"))
    button(session, table, 1)
    press(session, table, False)
    assert table.human_row == [misery("Toil")]
    bot_turn(session, table, [])
    assert table.human_returned == [[misery("Toil")]], "the Miseries of the turn went back into the Box"
    assert sorted(table.human_box + table.human_row) == [misery("Toil"), misery("Pain")] and table.human_row == [misery("Pain")], "and the next turn opened with a new reveal"


@with_rig("hellboy", "pandora", *HAND)
def test_a_reveal_zone_that_is_not_on_the_table_deals_nothing_on_the_button_either(rig):
    """Real TTS answers a script that names a zone which is not there with no zone and no card."""
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"))
    table.human_zones_missing = {"hrevz"}
    msgs = button(session, table, 1)
    assert said(msgs, t("pandora.no_top")) and table.human_box[0] == misery("Toil") and game.fx.counter_value(1, "box_mask") == 0


@with_rig("hellboy", "pandora", *HAND)
def test_a_misery_turned_up_by_hand_in_the_zone_is_read_and_two_at_once_or_none_go_to_the_panel(rig):
    session, table, game = human_box(rig)
    msgs = button(session, table, 2)                                          # nothing there
    assert said(msgs, t("pandora.nothing_new")) and labels(session)[:2] == ["Woe", "Toil"], "the panel question as before"
    session._box_by_panel = None
    table.human_row = [misery("Pain"), misery("Greed")]
    msgs = button(session, table, 2)
    assert said(msgs, t("pandora.several_new", n=2)) and labels(session)[:2] == ["Woe", "Toil"]
    session._box_by_panel = None
    table.human_row = [misery("Pain")]
    msgs = button(session, table, 2)
    assert said(msgs, t("pandora.seen", misery=t("pandora.misery.pain"))) and game.fx.counter_value(1, "box_mask") == 1 << IDX["Pain"]
    msgs = press(session, table, True)                                         # Yes: the Box is empty, the bot cannot deal the next one
    assert said(msgs, t("pandora.auto_failed")) and labels(session) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")]
    table.human_row = [misery("Pain"), misery("Woe")]
    button(session, table, 2)
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Pain"] | 1 << IDX["Woe"], "the one the engine already counted is not new"


@with_rig("hellboy", "pandora", *HAND)
def test_a_box_that_is_not_there_leaves_the_panel_question_as_it_was(rig):
    session, table, game = human_box(rig, misery("Toil"))
    table.box_gone = True
    msgs = button(session, table, 1)
    assert said(msgs, t("pandora.no_top")) and labels(session)[:2] == ["Woe", "Toil"] and game.fx.counter_value(1, "box_mask") == 0
    press(session, table, IDX["Toil"])
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Toil"]


@with_rig("hellboy", "pandora", *HAND)
def test_hope_offers_a_look_that_names_the_top_card_tells_the_engine_and_the_next_reveal_takes_it(rig):
    session, table, game = human_box(rig, misery("Hope"), misery("Greed"), misery("Toil"), start=True)
    assert labels(session) == [t("choice.yes"), t("choice.no"), t("btn.pandora_look")], "after HOPE: the look is offered"
    msgs = button(session, table, 3)
    assert said(msgs, t("pandora.looked", misery=t("pandora.misery.greed"))) and game.fx.counter_value(1, "box_top") == IDX["Greed"] + 1
    assert table.human_box == [misery("Greed"), misery("Toil")], "looking moves nothing"
    assert t("pandora.top_is", misery=t("pandora.misery.greed")) in " ".join(msgs) and labels(session) == [t("choice.yes"), t("choice.no")]
    msgs = press(session, table, True)
    assert not said(msgs, t("pandora.top_differs", misery=t("pandora.misery.greed"))) and table.human_row == [misery("Hope"), misery("Greed")]
    assert game.fx.counter_value(1, "box_top") == 0


@with_rig("hellboy", "pandora", *HAND)
def test_a_look_is_optional_and_a_top_that_changed_is_trusted_from_the_table(rig):
    session, table, game = human_box(rig, misery("Hope"), misery("Greed"), misery("Toil"), start=True)
    button(session, table, 3)
    table.human_box.insert(0, misery("Pain"))                                  # the human shuffled meanwhile
    msgs = press(session, table, True)
    assert said(msgs, t("pandora.top_differs", misery=t("pandora.misery.greed"))) and game.fx.counter_value(1, "box_mask") & 1 << IDX["Pain"]


@with_rig("hellboy", "pandora", *HAND)
def test_after_hope_the_human_may_answer_without_looking(rig):
    session, table, game = human_box(rig, misery("Hope"), misery("Toil"), start=True)
    button(session, table, 1)                                                 # Yes: reveal another, no look
    assert table.human_row == [misery("Hope"), misery("Toil")] and game.fx.counter_value(1, "box_top") == 0


@with_rig("hellboy", "pandora", *HAND)
def test_a_look_with_no_box_says_so_once_and_the_question_is_as_before(rig):
    session, table, game = human_box(rig, misery("Hope"), misery("Greed"))
    button(session, table, 1)
    table.box_gone = True
    msgs = button(session, table, 3)
    assert said(msgs, t("pandora.look_failed")) and game.fx.counter_value(1, "box_top") == 0
    assert labels(session) == [t("choice.yes"), t("choice.no")]


@with_rig("hellboy", "pandora", *HAND)
def test_the_markers_of_a_panel_fallback_and_a_look_belong_to_the_turn(rig):
    """The markers of "the panel names it" and "already looked" belong to the turn: the request's own key is the same every turn."""
    session, table, game = human_box(rig, misery("Toil"))
    msgs = button(session, table, 2)                                           # turn 1: nothing to read: the question with the names
    assert said(msgs, t("pandora.nothing_new")) and labels(session)[:2] == ["Woe", "Toil"]
    press(session, table, IDX["Hope"])
    assert labels(session)[2] == t("btn.pandora_look")
    button(session, table, 3)                                                  # and Look at the top card
    assert game.fx.counter_value(1, "box_top") == IDX["Toil"] + 1
    press(session, table, False)
    table.human_box = [misery("Hope"), misery("Greed"), misery("Toil")]
    bot_turn(session, table, [])
    assert game.turn == 1 and table.human_row == [misery("Hope")], "turn 2: the bot reveals the first one by itself, the markers are fresh"
    assert labels(session) == [t("choice.yes"), t("choice.no"), t("btn.pandora_look")], "HOPE again: and so is Look"
    msgs = button(session, table, 3)
    assert said(msgs, t("pandora.looked", misery=t("pandora.misery.greed")))


@with_rig("hellboy", "pandora", *HAND)
def test_a_reply_lost_after_the_card_moved_is_read_back_from_the_pile(rig):
    session, table, game = human_box(rig, misery("Pain"), misery("Toil"))
    client = session.client
    real = client.call_lua

    def lost_after(script):
        out = real(script)
        if "sparring:box_draw_top" in script:
            raise TimeoutError("TTS no devolvio valor")
        return out
    client.call_lua = lost_after
    msgs = button(session, table, 1)
    assert said(msgs, t("pandora.seen", misery=t("pandora.misery.pain"))) and game.fx.counter_value(1, "box_mask") == 1 << IDX["Pain"], msgs


@with_rig("hellboy", "pandora", *HAND)
def test_a_reply_lost_before_the_card_moved_leaves_the_buttons_and_the_engine_counts_nothing(rig):
    session, table, game = human_box(rig, misery("Pain"), misery("Toil"))
    real = session.client.call_lua

    def lost_before(script):
        if "sparring:box_draw_top" in script:
            raise TimeoutError("TTS no devolvio valor")
        return real(script)
    session.client.call_lua = lost_before
    session._show_choice(session.effect_run.awaiting)                         # the automatic try
    assert labels(session) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")]
    msgs = button(session, table, 1)                                          # and the button, which falls back on the names
    assert said(msgs, t("pandora.deal_unknown")) and not said(msgs, t("pandora.no_top")) and labels(session)[:2] == ["Woe", "Toil"]
    assert game.fx.counter_value(1, "box_mask") == 0, "the engine counted nothing it did not see"


@with_rig("hellboy", "pandora", *HAND)
def test_a_human_pandora_in_a_table_with_no_box_spot_gets_no_zone(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=None, human_box=None)
    make_deck(rt)
    session.prepare_table(resume=False)
    assert session.cfg.human_box_zone is None and len(rt.globals().SPAWNS) == 0


def test_the_builders_refuse_what_is_not_a_slot_or_a_spot():
    with pytest.raises(ValueError):
        reveal(17700, 0)
    with pytest.raises(TypeError):
        lua.box_put_back(MISERIES, identity=BOX.identity, spot=(1.0,))


# ---------------------------------------------------------------- the session (FakeTTS, batch mode)

def box_turn(rig, order, monkeypatch, picks, keep=()):
    session, table, game, fake, cfg = rig
    order.extend(IDX[p] for p in picks)
    keeps(monkeypatch, *keep)
    return bot_turn(session, table, [])


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_each_misery_the_bot_reveals_is_taken_out_face_up_in_order_and_goes_back_at_the_end_of_its_turn(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = box_turn(rig, order, monkeypatch, ("Toil", "Pain", "Greed"), keep=(True, True))
    assert table.box_returned == [[(17701, 1), (17702, 2), (17705, 3)]], "CardID 17700 + the engine's index, one place further each"
    assert sorted(table.box_deck) == list(range(17700, 17707)) and table.box_row == []
    assert said(msgs, t("tr.pandora.reveal", hero="Pandora", misery=t("pandora.misery.toil"), feathers=1)), "the chat still names it"
    assert not said(msgs, t("pandora.box_missing"))


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_no_misery_deck_on_the_table_falls_back_to_the_chat_with_one_warning(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    table.box_gone = True
    msgs = box_turn(rig, order, monkeypatch, ("Toil", "Pain", "Greed"), keep=(True, True))
    assert sum(t("pandora.box_missing") in m for m in msgs) == 1, msgs
    assert said(msgs, t("tr.pandora.reveal", hero="Pandora", misery=t("pandora.misery.greed"), feathers=3))
    assert game.fighters["pandora"].hp == 14 - 3 and game.fx.counter_value(0, "box_mask") == 0


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_deck_that_does_not_hold_the_card_is_not_said_to_be_missing(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    table.box_deck = [misery("Greed")]                                          # on the table, but not the Misery the engine drew
    msgs = box_turn(rig, order, monkeypatch, ("Toil",), keep=(False,))
    assert said(msgs, t("pandora.box_card_missing")) and not said(msgs, t("pandora.box_missing"))
    assert sum(t("pandora.box_card_missing") in m for m in msgs) == 1


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_pile_with_no_free_place_is_said_once(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    table.box_crowded = True
    msgs = box_turn(rig, order, monkeypatch, ("Toil", "Pain"), keep=(True, False))
    assert sum(t("pandora.pile_crowded") in m for m in msgs) == 1


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_table_that_cannot_say_where_the_box_is_never_crashes_the_turn(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    session.cfg.box_spot = None
    msgs = box_turn(rig, order, monkeypatch, ("Toil",), keep=(False,))
    assert sum(t("pandora.box_missing") in m for m in msgs) == 1 and table.box_row == [] and game.fx.counter_value(0, "box_mask") == 0


@with_rig("hellboy", "pandora", *HAND)
def test_a_human_pandora_without_zones_is_never_touched_by_the_bot_through_reveals_and_the_end_of_the_turn(rig):
    session, table, game, fake, cfg = rig
    press(session, table, IDX["Toil"])                                          # the panel names it, as before the zones
    press(session, table, True)
    press(session, table, IDX["Pain"])
    press(session, table, False)
    bot_turn(session, table, [])
    assert game.fx.counter_value(1, "box_mask") == 0, "the turn did end"
    assert table.box_row == [] and table.box_returned == [] and table.human_row == [] and table.human_returned == []
    assert not any("sparring:box_" in s or "sparring:peek_deck_top" in s and "4581f8" in s for s in table.scripts)


@with_rig("hellboy", "pandora", *HAND)
def test_the_human_pandora_s_box_is_put_back_at_the_end_of_the_turn_with_its_own_zone(rig):
    session, table, game = human_box(rig, misery("Pain"), misery("Toil"))
    button(session, table, 1)
    press(session, table, False)
    bot_turn(session, table, [])
    assert table.human_returned == [[misery("Pain")]] and any("sparring:box_put_back" in s and "hboxz" in s for s in table.scripts)


def test_the_importer_keeps_the_hand_written_extras_and_box_of_the_file():
    from tools import import_save
    existing = json.loads((TTS_FILE).read_text(encoding="utf-8"))
    derived = {"slug": "pandora", "bag": existing["bag"], "deck": existing["deck"], "fighters": existing["fighters"], "tokens": {},
               "counter_dials": {}, "_token_children": {}}
    report = import_save.Report("pandora")
    out = import_save.merge(derived, existing, report)
    assert out["extras"] == [MISERIES] and out["box"] == existing["box"] and {"extras", "box"} <= set(report.kept)


# ---------------------------------------------------------------- the whole thing on the Lua stub: real Box order, real hand zones, real pile

@pytest.mark.parametrize("human", [False, True])
def test_the_pile_goes_back_into_the_box_and_it_is_shuffled_at_the_end_of_the_turn_with_the_real_geometry(rt, human):  # noqa: F811
    """Both sides: whatever the reveals left loose (the whole pile) goes back into the Box, shuffled."""
    session = real_session("hellboy", "pandora") if human else real_session("pandora", "hellboy")
    pile, zone = lay_the_real_table(rt, session, human)
    _, spots = lay_pile(rt, pile, zone, order=ORDER[:5])
    assert all(hand is None for *_, hand in spots)
    out = run(rt, lua.box_put_back(MISERIES, identity=TEST_IDENTITY, spot=tuple(RAW["human_deck_spot"]), zone=zone))
    assert out == {"added": 5, "deck": True, "quantity": 7}
    assert rt.eval("(function() local n = 0 for _, o in ipairs(getObjects()) do if o.type == 'Card' then n = n + 1 end end return n end)()") == 0
    assert any(o.shuffled for o in rt.globals().getObjects().values() if o.type == "Deck")


class StubBoxTable(FxTable):
    """The fake table with the human's Misery deck on the Lua stub: the scripts of the Box run for real, so the order of the cards, the pile, the
    hand zones (a card laid in one goes to that hand) and a zone that is not there behave as in TTS."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from lupa import lua54
        self.rt = lua54.LuaRuntime()
        self.rt.execute(STUB)
        self.rt.globals().JSON = self.rt.table_from({"encode": lambda v: json.dumps(conv(v))})

    def _stub(self, s):
        if "local __rid" in s:
            n = len(self.rt.globals().SENT)
            self.rt.execute(s)
            reply = conv(self.rt.globals().SENT[n + 1])
            return {"__error__": reply["err"]} if "err" in reply else json.loads(reply["value"])
        self.rt.execute("function __OP()\n" + s + "\nend")
        return json.loads(self.rt.eval("__OP()"))

    do_box_draw_top = do_box_read = do_box_peek_top = _stub

    def do_box_put_back(self, s):
        return self._stub(s) if '"hboxz"' in s or "hbox" in s else super().do_box_put_back(s)


def stub_table(rig, top_first):
    """The real table on the stub for the human's Box: hands, discards, the Box (cards in the given order, top first) beside their deck with its zone,
    and the reveal zone made around the pile as the start-up makes it."""
    session, table, game, fake, cfg = rig
    rt = table.rt
    session.cfg.bot_discard_zone, session.cfg.human_discard_zone = "BOTZ", "HUMZ"
    table_zones(rt)
    rt.execute("getObjectFromGUID('906a7a').guid = 'BOTZ'; getObjectFromGUID('b7a0b8').guid = 'HUMZ'")
    x, z, yaw = box_layout.box_place(RAW, "human", session.cfg.human_seat_geo)
    make_deck(rt, ids=top_first, at=(x, z), yaw=yaw)
    rt.execute(f"mkobj({{guid = 'hboxz', type = 'Scripting', cx = {x}, cz = {z}, hw = 1.3, hd = 1.15}})")
    session.cfg.human_box_zone, session.cfg.human_box_spot = "hboxz", (x, z)
    out = run(rt, lua.box_reveal_zone([], session_pandora.pile_of(session, human=True)))
    session.cfg.human_reveal_zone = out["guid"]
    table.human_reveal_guid = out["guid"]
    return session, table, game, rt


@pytest.fixture
def stub_rig(request, tmp_path, monkeypatch):
    from sparring import session_box
    from test_d3_table_effects import build
    real = session_pandora._table_of
    with_test_image = lambda s, p: (lambda tb: tb and replace(tb, box=tb.box and replace(tb.box, identity=TEST_IDENTITY)))(real(s, p))
    monkeypatch.setattr(session_pandora, "_table_of", with_test_image)
    monkeypatch.setattr(session_box, "_table_of", with_test_image)
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=StubBoxTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def on_the_real_stub(*hand):
    return pytest.mark.parametrize("stub_rig", [("hellboy", "pandora", hand)], indirect=True)


def card_at(rt, cid):
    o = rt.globals().getObjectFromGUID(f"c{cid}")
    return o.pos.x, o.pos.z, o.rot.y, o.hand


@on_the_real_stub(*HAND)
def test_the_human_s_first_misery_is_taken_from_the_real_box_in_the_real_order_and_lies_upright_on_the_pile_beside_their_deck(stub_rig):
    session, table, game, rt = stub_table(stub_rig, [17703, 17701, 17706, 17700, 17702, 17705, 17704])
    session._announce_human_start()                                           # the start of their turn, as the session runs it
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Misfortune"], "the top card of the real Box, whatever the engine would have drawn"
    x, z, yaw, hand = card_at(rt, 17703)
    assert (round(x, 2), round(z, 2), yaw % 360, hand) == (-10.2, 20.05, 270, None), "just below their Box, upright for their seat"
    assert session.effect_run.awaiting.kind == "optional"
    press(session, table, True)
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Misfortune"] | 1 << IDX["Toil"]
    x2, z2, _, hand2 = card_at(rt, 17701)
    assert z2 == pytest.approx(z) and x - x2 == pytest.approx(lua.BOX_PILE_STEPS[0]) and hand2 is None
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 5


@on_the_real_stub(*HAND)
def test_the_human_s_three_feathers_through_the_real_box_stop_with_the_damage_and_the_end_of_the_turn_puts_the_pile_back_shuffled(stub_rig):
    session, table, game, rt = stub_table(stub_rig, [17701, 17702, 17703, 17700, 17704, 17705, 17706])
    session._announce_human_start()                                           # Toil
    press(session, table, True)                                               # Pain
    msgs = press(session, table, True)                                        # Misfortune: 1 + 1 + 2 feathers
    assert session.effect_run is None and game.fighters["pandora"].hp == 14 - 3 and said(msgs, t("narr.notice.pandora_three_feathers"))
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 4
    bot_turn(session, table, [])
    loose_cards = [o for o in rt.globals().getObjects().values() if o.type == "Card"]
    assert len(loose_cards) == 1, "the three of the turn went back; the next turn opened with one new reveal"
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 6 and rt.eval("getObjectFromGUID('4581f8').shuffled") is True
    assert game.fx.counter_value(1, "box_mask") == 1 << (loose_cards[0].cid - 17700)


@on_the_real_stub(*HAND)
def test_the_human_s_box_with_the_deck_moved_out_of_its_zone_is_not_dealt_and_the_buttons_stay(stub_rig):
    session, table, game, rt = stub_table(stub_rig, [17701, 17702])
    rt.execute("getObjectFromGUID('4581f8').pos = Vector(0, 2.5, 0)")                  # somebody moved the deck out of its zone
    session._show_choice(session.effect_run.awaiting)
    assert game.fx.counter_value(1, "box_mask") == 0
    assert labels(session) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")]


# ---------------------------------------------------------------- the Lua of TTS (MoonSharp, Lua 5.2) is not the Lua of the tests (5.4)

def test_the_stub_refuses_what_lua_5_2_does_not_have(rt):  # noqa: F811
    with pytest.raises(Exception, match="two-argument math.atan"):
        rt.execute("return math.atan(1, 2)")
    assert rt.eval("math.atan(1)") == pytest.approx(math.atan(1)) and rt.eval("math.tointeger") is None and rt.eval("utf8") is None


def test_no_script_of_the_box_uses_what_exists_only_from_lua_5_3():
    """TTS runs MoonSharp (Lua 5.2): no two-argument math.atan (it is math.atan2), no integer division `//`, math.tointeger, utf8 or goto."""
    import re
    pile = lua.BoxPile((5.0, 17.0), 90.0, (1.0, 0.0), keep=((1.0, 1.0, 1.0, 1.0),))
    plan = play.unpack_plan(real_config("pandora", "medusa"))
    scripts = [lua.box_zone([], "abc", identity=TEST_IDENTITY, spot=SPOT), lua.box_reveal("abc", 0, 1, identity=TEST_IDENTITY, spot=SPOT, pile=pile),
               lua.box_put_back("abc", identity=TEST_IDENTITY, spot=SPOT), lua.box_shuffle("abc", identity=TEST_IDENTITY, spot=SPOT),
               lua.box_peek_top("abc", identity=TEST_IDENTITY, spot=SPOT), lua.box_reveal_zone([], pile), lua.box_read("abc", identity=TEST_IDENTITY),
               lua.box_draw_top("abc", 1, identity=TEST_IDENTITY, spot=SPOT, zone=None, reveal_zone="def", pile=pile),
               lua.box_lay("abc", identity=TEST_IDENTITY, at=SPOT, yaw=90.0), lua.unpack_from_bags([box_row(plan)])]
    for script in scripts:
        code = re.sub(r'"[^"\\\n]*"', '""', script)
        assert not re.search(r"math\.atan\s*\([^()]*,", code), "two-argument math.atan"
        assert not re.search(r"//|math\.tointeger|utf8|\bgoto\b", code), re.findall(r"//|math\.tointeger|utf8|\bgoto\b", code)


# ---------------------------------------------------------------- the box already on the table at set-up

@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_box_already_on_the_table_face_up_or_far_from_her_deck_is_laid_beside_it_face_down_and_the_chat_says_so(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=(1.5, 3.0))
    make_deck(rt, at=(15, 8), yaw=0)
    rt.execute("getObjectFromGUID('4581f8').is_face_down = false; getObjectFromGUID('4581f8').rot = Vector(0, 0, 0)")
    session.prepare_table(resume=False)
    box = rt.globals().getObjectFromGUID(MISERIES)
    assert (box.pos.x, box.pos.z) == (1.5, 3.0) and box.rot.z == 180 and box.rot.y == 90 and box.is_face_down
    assert any(text == t("pandora.box_laid") for text, _ in session._startup_notes)
    zone = rt.globals().getObjectFromGUID(session.cfg.box_zone)
    assert (zone.pos.x, zone.pos.z) == (1.5, 3.0), "its zone is made where it lies now"


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_box_that_already_lies_beside_her_deck_face_down_is_left_alone_and_a_resume_never_moves_it(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=(1.5, 3.0))
    make_deck(rt, at=(1.9, 3.3), yaw=90)
    session.prepare_table(resume=False)
    assert rt.eval("getObjectFromGUID('4581f8').pos.x") == 1.9 and not any(text == t("pandora.box_laid") for text, _ in session._startup_notes)
    rt.execute("getObjectFromGUID('4581f8').pos = Vector(15, 2.5, 8)")
    saved = session.to_dict()["zones_live"]
    session.cfg.box_zone = None
    session._zone_origin.pop("box_zone")
    session._saved_zones = session.read_saved_zones(saved)
    session.prepare_table(resume=True)
    assert rt.eval("getObjectFromGUID('4581f8').pos.x") == 15


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_without_a_deck_spot_a_box_is_left_where_it_lies(rig, rt, monkeypatch):  # noqa: F811
    session = on_the_stub(rig[0], rt, monkeypatch, bot_box=(1.5, 3.0))
    session.cfg.bot_deck_spot = None
    make_deck(rt, at=(15, 8), yaw=0)
    session.prepare_table(resume=False)
    assert rt.eval("getObjectFromGUID('4581f8').pos.x") == 15 and not any(text == t("pandora.box_laid") for text, _ in session._startup_notes)


# ---------------------------------------------------------------- a deal whose answer was lost is never dealt twice

@with_rig("hellboy", "pandora", *HAND)
def test_a_lost_reply_and_a_failed_read_back_then_the_reveal_button_adopts_the_card_on_the_pile_instead_of_drawing_another(rig):
    session, table, game = human_box(rig, misery("Pain"), misery("Toil"))
    real = session.client.call_lua

    def lost(script):
        out = real(script)
        if "sparring:box_draw_top" in script or "sparring:box_read" in script:
            raise TimeoutError("TTS no devolvio valor")
        return out
    session.client.call_lua = lost
    session._show_choice(session.effect_run.awaiting)                         # the card moved, nothing could be read back
    assert table.human_row == [misery("Pain")] and game.fx.counter_value(1, "box_mask") == 0
    assert labels(session) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")]
    session.client.call_lua = real
    msgs = button(session, table, 1)
    assert said(msgs, t("pandora.seen", misery=t("pandora.misery.pain"))) and game.fx.counter_value(1, "box_mask") == 1 << IDX["Pain"]
    assert table.human_row == [misery("Pain")] and table.human_box == [misery("Toil")], "no second card was drawn"


# ---------------------------------------------------------------- resume

@with_rig("hellboy", "pandora", *HAND)
def test_a_resume_with_the_question_pending_adopts_a_misery_already_lying_on_the_pile_and_deals_nothing_again(rig):
    """The save was written before the bot dealt (or it crashed after the card moved and before the next save): the card on the pile is the answer."""
    session, table, game = human_box(rig, misery("Pain"), row=[misery("Toil")])
    assert session.effect_run.awaiting.extra["tag"] == "misery"
    other = reload(session, table)
    assert other.game.fx.counter_value(1, "box_mask") == 1 << IDX["Toil"] and other.effect_run.awaiting.kind == "optional"
    assert table.human_row == [misery("Toil")] and table.human_box == [misery("Pain")], "nothing was dealt"


@with_rig("hellboy", "pandora", *HAND)
def test_a_resume_with_the_question_pending_and_nothing_on_the_pile_shows_the_buttons_and_deals_nothing(rig):
    session, table, game = human_box(rig, misery("Toil"), misery("Pain"))
    other = reload(session, table)
    assert table.human_row == [] and game.fx.counter_value(1, "box_mask") == 0
    assert labels(other) == [t("btn.pandora_reveal"), t("btn.pandora_read"), t("btn.pandora_pick")]
    msgs = button(other, table, 1)
    assert said(msgs, t("pandora.dealt", misery=t("pandora.misery.toil")))


# ---------------------------------------------------------------- a failed answer is shown once

@with_rig("hellboy", "pandora", *HAND)
def test_a_card_the_engine_cannot_accept_shows_the_panel_question_once(rig):
    session, table, game = human_box(rig, misery("Toil"), misery("Toil"), start=True)           # the second top card is one already out
    msgs = press(session, table, True)
    assert said(msgs, t("pandora.not_expected", misery=t("pandora.misery.toil")))
    assert sum("Woe" in m and "Pain" in m for m in msgs) <= 1 and labels(session)[:2] == ["Woe", "Pain"], "the names, shown once"


# ---------------------------------------------------------------- Pandora goes FIRST in a fresh game

def fresh_first(rig, first):
    """The rig's session with a game built as a new game is (`play.build_game`: its first triggers wait for `Session._open`), `first` playing first."""
    session, table, game, fake, cfg = rig
    fresh = play.build_game(cfg, first, 0)
    for fid, f in fresh.fighters.items():
        f.pos = game.fighters[fid].pos
    fresh.controllers[session.bot] = session.ai
    fresh.controllers[session.human] = session.game.controllers[session.human]
    fresh.nicknames = dict(cfg.session_config().nicknames)
    session.game = fresh
    session._attach_choosers()
    session.first_turn_pending = True
    table.positions = {cfg.nicknames[f]: g.pos for f, g in fresh.fighters.items() if g.pos is not None}
    return session, table, fresh


@with_rig("hellboy", "pandora", *HAND)
def test_a_human_pandora_who_goes_first_gets_the_first_misery_dealt_by_the_bot_when_the_game_opens(rig):
    session, table, game = fresh_first(rig, "human")
    human_box(rig, misery("Toil"), misery("Pain"))
    session._open(announce_turn=True)
    assert game.turn == 1 and table.human_row == [misery("Toil")] and game.fx.counter_value(1, "box_mask") == 1 << IDX["Toil"]
    assert session.effect_run.awaiting.kind == "optional" and labels(session) == [t("choice.yes"), t("choice.no")]


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_a_bot_pandora_who_goes_first_reveals_from_the_box_when_the_game_opens(rig, order, monkeypatch):
    session, table, game = fresh_first(rig, "bot")
    order.extend([IDX["Toil"]])
    keeps(monkeypatch, False)
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session._open(announce_turn=True)
    assert game.fx.counter_value(0, "box_mask") != 0 or table.box_returned or table.box_row, "the first Misery was revealed at the start"
    assert any(c == 17701 for c, _ in table.box_row) or any(17701 == c for row in table.box_returned for c, _ in row)


# ---------------------------------------------------------------- TTS renumbers the DeckID of the Misery deck (live 26/11/2026: 17800-17806)

RENUMBERED = [178, 2345]       # what TTS gave the sheet when it came out of the bag (177 is Houdini's character card), and something arbitrary


def misery_ids(base, order=range(7)):
    """CardIDs of a Misery deck whose DeckID TTS renumbered to `base`, the cards in `order` (their places in the sheet), top first."""
    return [base * 100 + i for i in order]


def lay_renumbered(rt, base, order=range(7), at=(24, 2), yaw=90):
    make_deck(rt, ids=misery_ids(base, order), at=at, yaw=yaw)
    zone_around(rt, at[0], at[1], half=1.75, half_z=1.2)
    reveal_zone_at(rt, 34.7, 2)


@pytest.mark.parametrize("base", RENUMBERED)
def test_a_renumbered_box_is_found_and_shuffled_dealt_read_peeked_and_gathered_by_image_and_place_in_the_sheet(rt, base):  # noqa: F811
    lay_renumbered(rt, base, order=[4, 1, 6, 0, 3, 2, 5])                       # the live deck came out unshuffled and in the wrong order for the first Reveal
    loose(rt, 17700, 24, 8, guid="houdini", owner="houdini", up=False)          # Houdini's character card: CardID 17700, another image
    loose(rt, base * 100 + 3, 26, 8, guid="stranger", owner="medusa", up=False)  # a card of another deck in a Misery's CardID
    assert run(rt, lua.box_shuffle(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE)) == {"deck": True, "shuffled": True}
    assert run(rt, lua.box_peek_top(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE)) == {"found": True, "idx": 4}
    pile = pile_at()
    out = run(rt, lua.box_draw_top(MISERIES, 1, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE, reveal_zone=REVEAL, pile=pile))
    assert out["taken"] is True and out["idx"] == 4 and out["guid"] == f"c{base * 100 + 4}"
    out = run(rt, lua.box_reveal(MISERIES, 6, 2, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE, pile=pile))
    assert out["taken"] is True and out["guid"] == f"c{base * 100 + 6}", "the engine's Misery number 6 is the card at place 6 of the sheet"
    out = run(rt, lua.box_read(REVEAL, identity=TEST_IDENTITY))
    assert out["zone"] is True
    assert run(rt, lua.box_put_back(MISERIES, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE)) == {"added": 2, "deck": True, "quantity": 7}
    assert rt.globals().getObjectFromGUID("houdini") is not None and rt.globals().getObjectFromGUID("stranger") is not None
    assert run(rt, lua.box_reveal(MISERIES, 3, 1, identity=TEST_IDENTITY, spot=SPOT, zone=ZONE, pile=pile))["guid"] == f"c{base * 100 + 3}"


@pytest.mark.parametrize("base", RENUMBERED)
def test_a_renumbered_box_face_up_in_the_reveal_zone_is_read_by_its_place_in_the_sheet(rt, base):  # noqa: F811
    reveal_zone_at(rt, 34.7, 2)
    loose(rt, base * 100 + 2, 30, 2, up=True)
    loose(rt, base * 100 + 5, 31, 2, up=False)
    loose(rt, 17700, 32, 2, guid="houdini", owner="houdini", up=True)
    assert run(rt, lua.box_read(REVEAL, identity=TEST_IDENTITY)) == {"zone": True, "cards": [{"idx": 2, "guid": f"c{base * 100 + 2}"}]}


@pytest.mark.parametrize("base", RENUMBERED)
def test_a_renumbered_box_is_laid_beside_the_deck_and_its_zone_made_around_it(rt, base):  # noqa: F811
    make_deck(rt, ids=misery_ids(base), at=(-3.1, 17.55), yaw=270)                # where the live Box lay, away from its new place
    assert run(rt, lua.box_lay(MISERIES, identity=TEST_IDENTITY, at=(-6.7, 20.05), yaw=270.0)) == {"found": True, "moved": True}
    box = rt.globals().getObjectFromGUID(MISERIES)
    assert (box.pos.x, box.pos.z, box.rot.y, box.rot.z) == (pytest.approx(-6.7), pytest.approx(20.05), 270, 180)
    made = run(rt, lua.box_zone([], MISERIES, identity=TEST_IDENTITY, spot=SPOT))
    assert made["box"] is True and made["status"] == "created"
    assert zone_rect(rt, made["guid"])[0] < -6.7 < zone_rect(rt, made["guid"])[1]


def test_a_misery_deck_with_a_card_outside_the_seven_places_is_not_the_box(rt):  # noqa: F811
    make_deck(rt, ids=[17800, 17801, 17807])
    assert run(rt, lua.box_shuffle(MISERIES, identity=TEST_IDENTITY, spot=SPOT)) == {"deck": False, "shuffled": False}


@pytest.mark.parametrize("base", RENUMBERED)
def test_clean_table_removes_a_renumbered_box_and_the_loose_miseries_but_not_a_card_outside_the_seven_places(rt, base):  # noqa: F811
    rt.execute(f"""
local cards = {{}}
for i = 0, 6 do table.insert(cards, {{cid = {base} * 100 + i, guid = 'm' .. i, owner = 'misery'}}) end
mkobj({{guid = 'newdeckguid', type = 'Deck', cards = cards, pos = {{x = -9, y = 1, z = 9}}}})
mkobj({{guid = 'looseone', type = 'Card', cid = {base} * 100 + 2, owner = 'misery', pos = {{x = -9, y = 1, z = 12}}}})
""")
    loose(rt, base * 100 + 7, -9, 14, guid="notamisery", owner="misery")
    medusa = load_hero_table("medusa")
    run(rt, lua.clear_setup([(medusa.card_ids, medusa.identity, medusa.character_card_id)], [], [], [], (26.0, 36.0), (), (TEST_IDENTITY,)))
    assert rt.globals().getObjectFromGUID("newdeckguid") is None and rt.globals().getObjectFromGUID("looseone") is None
    assert rt.globals().getObjectFromGUID("notamisery") is not None


@pytest.mark.parametrize("base", [177, *RENUMBERED])
@on_the_real_stub(*HAND)
def test_the_human_s_renumbered_box_is_dealt_through_the_real_start_of_turn_and_the_keep_revealing_loop(stub_rig, base):
    session, table, game, rt = stub_table(stub_rig, misery_ids(base, [3, 1, 6, 0, 2, 5, 4]))
    session._announce_human_start()
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Misfortune"], "the top card is Misery number 3 of the sheet, whatever the DeckID"
    x, z, yaw, hand = card_at(rt, base * 100 + 3)
    assert hand is None and yaw % 360 == 270
    press(session, table, True)
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Misfortune"] | 1 << IDX["Toil"]
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 5


@pytest.mark.parametrize("base", [177, *RENUMBERED])
@on_the_real_stub(*HAND)
def test_the_human_s_hope_looks_at_a_renumbered_top_card(stub_rig, base):
    session, table, game, rt = stub_table(stub_rig, misery_ids(base, [IDX["Hope"], IDX["Greed"], 0, 1, 2, 3, 6]))
    session._announce_human_start()                                        # the bot deals HOPE, the question "reveal another?" has a third button, Look
    assert game.fx.counter_value(1, "box_mask") == 1 << IDX["Hope"]
    button(session, table, 3)
    assert game.fx.counter_value(1, "box_top") == IDX["Greed"] + 1 and rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 6, "looked at, not moved"


class StubBotBoxTable(StubBoxTable):
    """The same, with the BOT's Misery deck on the Lua stub as well."""
    do_box_reveal = StubBoxTable._stub

    def do_box_put_back(self, s):
        return self._stub(s)


@pytest.fixture
def stub_bot_rig(tmp_path, monkeypatch):
    from sparring import session_box
    from test_d3_table_effects import build
    real = session_pandora._table_of
    with_test_image = lambda s, p: (lambda tb: tb and replace(tb, box=tb.box and replace(tb.box, identity=TEST_IDENTITY)))(real(s, p))
    monkeypatch.setattr(session_pandora, "_table_of", with_test_image)
    monkeypatch.setattr(session_box, "_table_of", with_test_image)
    session, table, game, fake, cfg, client = build(tmp_path, "pandora", "hellboy", BOT_HAND, table_cls=StubBotBoxTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.mark.parametrize("base", [177, *RENUMBERED])
def test_the_bot_s_renumbered_box_is_revealed_card_by_card_and_gathered_at_the_end_of_its_turn(stub_bot_rig, order, monkeypatch, base):
    session, table, game, fake, cfg = stub_bot_rig
    rt = table.rt
    table_zones(rt)
    x, z, yaw = box_layout.box_place(RAW, "bot", session.cfg.bot_seat_geo)
    make_deck(rt, ids=misery_ids(base, [3, 1, 6, 0, 2, 5, 4]), at=(x, z), yaw=yaw)
    made = run(rt, lua.box_zone([], MISERIES, identity=TEST_IDENTITY, spot=(x, z), avoid=AVOID))
    session.cfg.box_zone, session.cfg.box_spot = made["guid"], (x, z)
    order.extend([IDX["Toil"], IDX["Pain"], IDX["Greed"]])
    keeps(monkeypatch, True, True)
    seen = []
    take = rt.eval("function(f) return f end")
    msgs = bot_turn(session, table, [])
    assert not said(msgs, t("pandora.box_missing")) and not said(msgs, t("pandora.box_card_missing"))
    assert rt.eval("getObjectFromGUID('4581f8').getQuantity()") == 7 and rt.eval("getObjectFromGUID('4581f8').shuffled") is True
    assert not [o for o in rt.globals().getObjects().values() if o.type == "Card"], "the three Miseries of the turn went back into the Box"


# ---------------------------------------------------------------- a new game: the Box is where Ivan wants it, shuffled, and the reveal zone is where the pile goes

@pytest.mark.parametrize("base", RENUMBERED)
@with_rig("hellboy", "pandora", *HAND)
def test_a_new_game_lays_a_renumbered_box_to_the_left_of_their_deck_shuffles_it_and_moves_a_stale_reveal_zone(rig, rt, monkeypatch, base):  # noqa: F811
    """The live table of 26/11/2026: the Box face down at (-3.1, 17.55), unshuffled, CardIDs 17800-17806; a reveal zone of yesterday's version at
    (-12, 17.55) adopted from the session file."""
    session = rig[0]
    on_the_stub(session, rt, monkeypatch, bot_box=None, human_box=session.cfg.human_box_spot)
    assert session.cfg.human_box_spot == pytest.approx((-6.7, 20.05)) and session.cfg.human_deck_spot == (-6.7, 17.55)
    table_zones(rt)
    session.cfg.bot_discard_zone, session.cfg.human_discard_zone = "906a7a", "b7a0b8"
    make_deck(rt, ids=misery_ids(base, [6, 5, 4, 3, 2, 1, 0]), at=(-3.1, 17.55), yaw=270)
    zone_around(rt, -3.1, 17.55, guid="oldboxz", half=1.3, half_z=1.15)
    reveal_zone_at(rt, -12, 17.55)
    rt.execute(f"getObjectFromGUID('{REVEAL}').guid = 'oldrevz'")
    saved = {"human_box_zone": "oldboxz", "human_reveal_zone": "oldrevz"}
    session.prepare_table(resume=False, saved_zones=saved)
    box = rt.globals().getObjectFromGUID(MISERIES)
    assert (box.pos.x, box.pos.z, box.rot.y, box.is_face_down) == (pytest.approx(-6.7), pytest.approx(20.05), 270, True)
    assert rt.eval("getObjectFromGUID('4581f8').shuffled") is True, "a new game shuffles the Box"
    assert session.cfg.human_box_zone == "oldboxz" and session.cfg.human_reveal_zone == "oldrevz", "the saved zones are the ones used"
    boxzone = zone_rect(rt, "oldboxz")
    assert boxzone[0] < -6.7 < boxzone[1] and boxzone[2] < 20.05 < boxzone[3], "its zone follows the Box"
    pile = session_pandora.pile_of(session, human=True)
    answers, spots = lay_pile(rt, pile, "oldboxz", reveal="oldrevz", order=misery_ids(base), spot=(-6.7, 20.05))
    made = rt.globals().getObjectFromGUID("oldrevz")                                    # a zone is its position and its scale
    revealed = (made.pos.x - made.scale.x / 2, made.pos.x + made.scale.x / 2, made.pos.z - made.scale.z / 2, made.pos.z + made.scale.z / 2)
    assert all(revealed[0] <= x - 1.65 and x + 1.65 <= revealed[1] and revealed[2] <= z - 1.1 and z + 1.1 <= revealed[3] for x, z, *_ in spots),         "the reveal zone holds the whole pile: it was moved and resized to the pile plan"
    assert revealed[3] > 19.5, "no longer where yesterday's version left it, around z 17.55"


@pytest.mark.parametrize("out, moved", [(0, True), (1 << IDX["Toil"], False)])
@with_rig("hellboy", "pandora", *HAND)
def test_a_resumed_game_moves_a_stale_reveal_zone_only_while_no_misery_lies_out(rig, rt, monkeypatch, out, moved):  # noqa: F811
    session = rig[0]
    on_the_stub(session, rt, monkeypatch, bot_box=None, human_box=session.cfg.human_box_spot)
    table_zones(rt)
    session.cfg.bot_discard_zone, session.cfg.human_discard_zone = "906a7a", "b7a0b8"
    make_deck(rt, ids=misery_ids(178), at=(-6.7, 20.05), yaw=270)
    reveal_zone_at(rt, -12, 17.55)
    session._saved_zones = {"human_reveal_zone": REVEAL}
    session.game.fx.set_counter(session.human, "box_mask", out)
    session.prepare_table(resume=True)
    assert (rt.globals().getObjectFromGUID(REVEAL).pos.z != 17.55) == moved
