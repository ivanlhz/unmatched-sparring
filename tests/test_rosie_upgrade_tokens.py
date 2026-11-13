"""Rosie the Riveter's four upgrade tokens on the table: the Lua builder `lua_rosie.set_upgrade_tokens` on the lupa stub (objects with a Z
rotation like the live ones: 0 = inactive face up, 180 = active face up, flips and swaps of places, pings), and the session that drives it
for the bot's Rosie on FakeTTS (the objects imitate the live tokens: GUID, Z rotation, position), including a resume. A human Rosie
flips her own tokens by hand: the session only says it in the chat."""
from __future__ import annotations

import pytest

from sparring import session_rosie, upgrades
from sparring.tts import lua_rosie
from sparring.tts.hero_table import load_hero_table
from test_effects_bridge import conv, rt, run, table_py  # noqa: F401  (rt is a fixture)

SLUG = "rosie-the-riveter"
ROW = ["merlin_engine", "cavity_magnetron", "sedgley_fist_gun", "whizbang"]
GUIDS = {"merlin_engine": "d670b6", "cavity_magnetron": "e5ef35", "sedgley_fist_gun": "85c49f", "whizbang": "f45e71"}
FACES = {g: (180.0, 0.0) for g in GUIDS.values()}
ORDER = [GUIDS[u] for u in ROW]
SLOTS = [(10.0, 1.5, 4.0), (11.0, 1.5, 4.0), (12.0, 1.5, 4.0), (13.0, 1.5, 4.0)]


def near(a: float, b: float) -> float:
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def lay(rt, order=ORDER, z=0):
    for guid, slot in zip(order, SLOTS):
        rt.execute(f"mkobj({{guid = '{guid}', type = 'Custom_Token', pos = Vector({slot[0]}, {slot[1]}, {slot[2]}), rot = Vector(0, 90, {z})}})")


def where(rt, guid):
    return table_py(rt, f'(function() local o = getObjectFromGUID("{guid}") return {{o.pos.x, o.pos.z, o.rot.z, o.rot.y}} end)()')


def fire_timers(rt):
    rt.execute("for _, f in ipairs(TIMERS) do f() end TIMERS = {}")


def test_the_first_active_tokens_of_the_row_are_flipped_to_the_active_face_and_pinged(rt):
    lay(rt)
    rt.execute("SEATED = {Blue = true}")
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 2, SLOTS, ["Blue"]))
    assert (out["found"], out["total"], out["flipped"], out["moved"]) == (4, 4, 2, 0)
    assert out["guids"] == ORDER[:2]
    assert [where(rt, g)[2] for g in ORDER] == [180, 180, 0, 0] and where(rt, ORDER[0])[3] == 90      # only Z turns
    fire_timers(rt)
    assert [(p["x"], p["z"]) for p in table_py(rt, "PINGS")] == [(10, 4), (11, 4)]
    assert all(p["color"] == "Blue" for p in table_py(rt, "PINGS"))


def test_a_token_already_on_its_face_and_spot_is_left_alone_and_not_pinged(rt):
    lay(rt)
    run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 2, SLOTS, ["Blue"]))
    fire_timers(rt)
    rt.execute("PINGS = nil")
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 2, SLOTS, ["Blue"]))
    assert (out["flipped"], out["moved"], out["guids"]) == (0, 0, [])
    fire_timers(rt)
    assert rt.eval("PINGS") is None


def test_a_deactivation_turns_the_row_the_first_token_goes_face_down_to_the_end_and_the_others_shift_left(rt):
    lay(rt)
    run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 2, SLOTS, ["Blue"]))        # merlin, cavity active
    new_order = ORDER[1:] + ORDER[:1]                                               # row now: cavity, sedgley, whizbang, merlin; one active
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, new_order, 1, SLOTS, ["Blue"]))
    assert out["moved"] == 4 and out["flipped"] == 1                                # merlin face down; every token changes place
    by_guid = {g: where(rt, g) for g in ORDER}
    assert [by_guid[g][0] for g in new_order] == [10, 11, 12, 13]
    assert [by_guid[g][2] for g in new_order] == [180, 0, 0, 0]
    assert out["before"] == [[11.0, 1.5, 4.0], [12.0, 1.5, 4.0], [13.0, 1.5, 4.0], [10.0, 1.5, 4.0]]      # where each token of the new row lay


def test_without_slots_only_the_faces_are_set_and_the_positions_are_reported(rt):
    lay(rt)
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 4, None, ["Blue"]))
    assert (out["flipped"], out["moved"]) == (4, 0)
    assert [tuple(p) for p in out["before"]] == SLOTS
    assert [where(rt, g)[2] for g in ORDER] == [180] * 4


def test_the_reset_turns_all_four_faces_down_again(rt):
    lay(rt)
    run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 4, SLOTS, ["Blue"]))
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 0, SLOTS, ["Blue"]))
    assert out["flipped"] == 4 and [where(rt, g)[2] for g in ORDER] == [0] * 4


def test_a_missing_token_is_not_found_and_nothing_else_breaks(rt):
    lay(rt, ORDER[:3])
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 4, SLOTS, ["Blue"]))
    assert (out["found"], out["total"], out["flipped"]) == (3, 4, 3)


def test_anything_that_is_not_a_token_is_never_touched(rt):
    rt.execute("mkobj({guid = 'd670b6', type = 'Deck', pos = Vector(1, 1, 1), rot = Vector(0, 0, 0)})")
    out = run(rt, lua_rosie.set_upgrade_tokens(FACES, ORDER, 4, SLOTS, ["Blue"]))
    assert out["found"] == 0 and where(rt, "d670b6")[2:3] == [0]


def test_the_builder_refuses_nonsense():
    with pytest.raises(ValueError):
        lua_rosie.set_upgrade_tokens(FACES, ORDER[:3], 1, None, ["Blue"])
    with pytest.raises(ValueError):
        lua_rosie.set_upgrade_tokens(FACES, ORDER, 5, None, ["Blue"])
    with pytest.raises(ValueError):
        lua_rosie.set_upgrade_tokens(FACES, ORDER, 1, SLOTS[:2], ["Blue"])
    with pytest.raises(ValueError):
        lua_rosie.set_upgrade_tokens(FACES, ORDER, 1, None, [])


def test_the_data_gives_each_token_its_two_faces_like_abes_tokens():
    table = load_hero_table(SLUG)
    assert table.tokens == GUIDS
    for name, guid in GUIDS.items():
        spec = table.token_faces[name]
        assert spec["faces"] == {"inactive": 0, "active": 180} and spec["child"]


def test_the_tables_reset_knows_the_starting_face_of_each_upgrade_token():
    from sparring import table_reset
    table = load_hero_table(SLUG)
    for name in GUIDS:
        assert table_reset.START_FACE[name] == "inactive" and "inactive" in table.token_faces[name]["faces"] and table.tokens[name]
