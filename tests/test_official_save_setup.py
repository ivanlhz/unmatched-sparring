"""F20: the bot prepares the official community save itself at start-up.

The official "Unmatched Official Tournament Table" save has no discard zones and keeps two decks, a d20 and the Dice
Cannon in the middle of the table. At start-up the bot creates the zones (straight: rotY 270), straightens the
hand-made ones of the pre-sparring save, and parks those four objects out of the way (fresh start only).

The Lua tests run the generated script with lupa (tests/lua_stub.lua); the session ones use a fake client; the
`play` ones go through `play.main` against the fake table."""
from __future__ import annotations

import dataclasses
import json
import threading
import time

import pytest

from sparring import i18n, play, table_prep
from sparring.ai_medusa import MedusaAI
from sparring.board import Board
from sparring.play import ConfigError, load_config
from sparring.session import Session, SessionConfig, SessionError
from sparring.state import Game
from sparring.tts import lua
from test_play import REAL_CONFIG, cfg_file, live  # noqa: F401
from test_review10 import STUB, conv
from test_session import NICK, PIECES, Table  # noqa: F401

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

CENTRE_GUIDS = ["addeca", "cb6cbc", "65be8d", "5085eb"]


def raw_config() -> dict:
    return json.loads(REAL_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture
def tts():
    """A bare table: no zones, nothing in the middle."""
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    return runtime


def prepare(runtime, zones, park, rid=1):
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(lua.prepare_table(zones, park), rid))
    reply = conv(runtime.globals().SENT[n + 1])
    assert "err" not in reply, reply
    return json.loads(reply["value"])


def spec(key="bot_discard_zone", candidates=("906a7a",)):
    s = table_prep.zone_spawns(raw_config())[key]
    return (key, list(candidates), s.position, s.scale, s.rot_y)


def vec(runtime, name, attr):
    return {k: runtime.eval(f"{name}.{attr}.{k}") for k in "xyz"}


# ---------- 1. zones: Lua ----------
def test_a_missing_zone_is_created_straight_with_the_configured_transform(tts):
    res = prepare(tts, [spec()], [])
    assert res["zones"] == {"bot_discard_zone": {"guid": "zone1", "status": "created"}}
    assert tts.eval("#SPAWNS") == 1
    assert tts.eval("SPAWNS[1].type") == "Scripting"                      # TTS reports a ScriptingTrigger as Scripting
    assert vec(tts, "SPAWNS[1]", "rot") == {"x": 0, "y": 270.0, "z": 0}
    assert vec(tts, "SPAWNS[1]", "pos") == pytest.approx({"x": 14.9677, "y": 4.1422, "z": 0.7422})
    assert vec(tts, "SPAWNS[1]", "scale") == pytest.approx({"x": 35.4306, "y": 5.1, "z": 8.5464})


def test_both_zones_are_created_with_their_own_transform(tts):
    res = prepare(tts, [spec(), spec("human_discard_zone", ("b7a0b8",))], [])
    assert {k: v["status"] for k, v in res["zones"].items()} == {"bot_discard_zone": "created", "human_discard_zone": "created"}
    assert res["zones"]["bot_discard_zone"]["guid"] != res["zones"]["human_discard_zone"]["guid"]
    assert vec(tts, "SPAWNS[2]", "pos") == pytest.approx({"x": -12.4623, "y": 4.1422, "z": 0.6652})
    assert vec(tts, "SPAWNS[2]", "scale") == pytest.approx({"x": 33.1625, "y": 5.1, "z": 10.9523})
    assert vec(tts, "SPAWNS[2]", "rot")["y"] == 270.0


def test_a_crooked_zone_that_exists_is_straightened_and_nothing_else_changes(tts):
    tts.execute("""mkobj({guid = '906a7a', type = 'Scripting', cx = 15, cz = 0.7, hw = 17, hd = 4,
                        pos = Vector(14.9677, 4.1422, 0.7422), rot = Vector(0, 269.09, 0)})""")
    res = prepare(tts, [spec()], [])
    assert res["zones"] == {"bot_discard_zone": {"guid": "906a7a", "status": "straightened"}}
    assert tts.eval("#SPAWNS") == 0, "the hand-made zone is not replaced"
    assert vec(tts, "getObjectFromGUID('906a7a')", "rot") == {"x": 0, "y": 270.0, "z": 0}
    assert vec(tts, "getObjectFromGUID('906a7a')", "pos") == pytest.approx({"x": 14.9677, "y": 4.1422, "z": 0.7422})
    assert tts.eval("getObjectFromGUID('906a7a').scale") is None


def test_a_zone_that_is_already_straight_is_left_alone(tts):
    tts.execute("""local z = mkobj({guid = '906a7a', type = 'Scripting', cx = 15, cz = 0.7, hw = 17, hd = 4, rot = Vector(0, 270.0, 0)})
                  local set = z.setRotation
                  z.setRotation = function(r) TURNED = true; set(r) end""")
    assert prepare(tts, [spec()], [])["zones"]["bot_discard_zone"]["status"] == "found"
    assert tts.eval("TURNED") is None


def test_a_tilted_zone_is_straightened_on_every_axis(tts):
    tts.execute("mkobj({guid = '906a7a', type = 'Scripting', cx = 15, cz = 0.7, hw = 17, hd = 4, rot = Vector(1.5, 270, 0.4)})")
    assert prepare(tts, [spec()], [])["zones"]["bot_discard_zone"]["status"] == "straightened"
    assert vec(tts, "getObjectFromGUID('906a7a')", "rot") == {"x": 0, "y": 270.0, "z": 0}


def test_an_object_with_the_zone_guid_that_is_not_a_zone_does_not_count(tts):
    tts.execute("mkobj({guid = '906a7a', type = 'Deck'})")
    assert prepare(tts, [spec()], [])["zones"]["bot_discard_zone"]["status"] == "created"


def test_the_first_candidate_on_the_table_wins_and_the_missing_ones_are_skipped(tts):
    tts.execute("""mkobj({guid = 'live01', type = 'Scripting', cx = 15, cz = 0.7, hw = 17, hd = 4, rot = Vector(0, 270, 0)})
                  mkobj({guid = '906a7a', type = 'Scripting', cx = 15, cz = 0.7, hw = 17, hd = 4, rot = Vector(0, 270, 0)})""")
    assert prepare(tts, [spec(candidates=("gone01", "live01", "906a7a"))], [])["zones"]["bot_discard_zone"]["guid"] == "live01"
    assert prepare(tts, [spec(candidates=("gone01", "906a7a"))], [], rid=2)["zones"]["bot_discard_zone"]["guid"] == "906a7a"


def test_a_spawn_without_a_guid_is_reported_not_trusted(tts):
    tts.execute("local spawn = spawnObject; spawnObject = function(t) local z = spawn(t); z.getGUID = function() return '' end; return z end")
    assert prepare(tts, [spec()], [])["zones"]["bot_discard_zone"] == {"guid": "", "status": "no_guid"}


# ---------- 2. the centre of the table: Lua ----------
def centre(tts):
    tts.execute("""
mkobj({guid = 'addeca', type = 'Deck', name = 'DeckCustom', pos = Vector(-5.7, 2.0, -1.5), rot = Vector(0, 270, 180)})
mkobj({guid = 'cb6cbc', type = 'Deck', name = 'DeckCustom', pos = Vector(5.5, 2.0, -1.5), rot = Vector(0, 90, 180)})
mkobj({guid = '65be8d', type = 'Die_20', name = 'Die_20', pos = Vector(-0.7, 2.7, -1.6), rot = Vector(0, 270.4, 0)})
mkobj({guid = '5085eb', type = 'Generic', name = 'Custom_Assetbundle', pos = Vector(2.1, 1.7, -30.0), rot = Vector(0, 0, 0)})""")


def where(tts, guid):
    return {k: tts.eval(f"getObjectFromGUID('{guid}').pos.{k}") for k in "xz"}


def test_the_objects_of_the_centre_are_moved_to_their_spot_keeping_their_rotation(tts):
    centre(tts)
    plan = table_prep.park_plan(raw_config())
    before = {g: vec(tts, f"getObjectFromGUID('{g}')", "rot") for g in CENTRE_GUIDS}
    count = tts.eval("#OBJECTS")
    res = prepare(tts, [], list(plan))
    assert [p["guid"] for p in res["parked"]] == CENTRE_GUIDS
    for guid, spot in plan:
        assert where(tts, guid) == pytest.approx({"x": spot[0], "z": spot[2]})
        assert vec(tts, f"getObjectFromGUID('{guid}')", "rot") == before[guid], "the rotation is kept"
    assert tts.eval("#OBJECTS") == count, "nothing is destroyed or created"


def test_an_absent_object_is_skipped_and_the_others_still_move(tts):
    centre(tts)
    tts.execute("getObjectFromGUID('65be8d').destruct()")
    res = prepare(tts, [], list(table_prep.park_plan(raw_config())))
    assert [p["guid"] for p in res["parked"]] == ["addeca", "cb6cbc", "5085eb"]


def test_nothing_to_move_is_an_empty_answer(tts):
    assert prepare(tts, [], list(table_prep.park_plan(raw_config())))["parked"] == []


def test_the_preparation_script_never_opens_destroys_or_touches_the_global_ui():
    script = lua.prepare_table([spec()], list(table_prep.park_plan(raw_config())))
    for forbidden in ("destruct", "takeObject", "putObject", "Global", "UI.", "spawnObjectData", "setLuaScript", "messageID"):
        assert forbidden not in script, forbidden
    assert script.startswith("-- sparring:prepare_table")


def test_the_builder_refuses_what_it_cannot_write_safely():
    with pytest.raises(ValueError):
        lua.prepare_table([], [(f"g{i}", (0.0, 0.0, 0.0)) for i in range(lua.MAX_PREP_PARK + 1)])
    with pytest.raises(ValueError):
        lua.prepare_table([("bot_discard_zone", ["bad guid!"], (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 270.0)], [])
    with pytest.raises(TypeError):
        lua.prepare_table([], [("abc", (0.0, 0.0))])


# ---------- configuration ----------
def test_the_default_transforms_come_from_the_config_and_are_straight():
    spawns = table_prep.zone_spawns(raw_config())
    assert set(spawns) == {"bot_discard_zone", "human_discard_zone"}
    assert spawns["bot_discard_zone"].position == (14.9677, 4.1422, 0.7422)
    assert spawns["bot_discard_zone"].scale == (35.4306, 5.1, 8.5464)
    assert spawns["human_discard_zone"].position == (-12.4623, 4.1422, 0.6652)
    assert spawns["human_discard_zone"].scale == (33.1625, 5.1, 10.9523)
    assert {s.rot_y for s in spawns.values()} == {270.0}


def test_a_zone_without_a_spawn_key_is_never_created_or_straightened():
    raw = raw_config()
    del raw["human_discard_zone_spawn"]
    assert set(table_prep.zone_spawns(raw)) == {"bot_discard_zone"}
    raw.pop("bot_discard_zone_spawn")
    assert table_prep.zone_spawns(raw) == {}


def test_bot_discard_bounds_describe_the_zone_as_it_is_created():
    raw = raw_config()
    spawn = table_prep.zone_spawns(raw)["bot_discard_zone"]
    assert raw["bot_discard_bounds"] == [spawn.position[0], spawn.position[2], spawn.scale[0], spawn.scale[2], spawn.rot_y]


@pytest.mark.parametrize("over", [
    {"clear_table_spots": [[0, 2, -28]]},                                   # fewer spots than GUIDs
    {"clear_table_guids": "addeca"},                                        # not a list
    {"clear_table_spots": [[0, 2], [0, 2], [0, 2], [0, 2]]},                # not (x, y, z)
    {"bot_discard_zone_spawn": {"position": [1, 2, 3]}},                    # no scale
    {"human_discard_zone_spawn": {"position": [1, 2, "x"], "scale": [1, 1, 1]}},
])
def test_a_badly_written_key_is_a_configuration_error(cfg_file, over):
    with pytest.raises(ConfigError):
        load_config(cfg_file(**over)).session_config()


def test_the_session_config_carries_the_new_keys(cfg_file):
    scfg = load_config(cfg_file()).session_config()
    assert set(scfg.zone_spawns) == {"bot_discard_zone", "human_discard_zone"}
    assert [g for g, _ in scfg.clear_plan] == CENTRE_GUIDS


def test_the_new_keys_are_documented_in_the_comment_block():
    notes = "\n".join(raw_config()["_notes"])
    for key in ("discard_zone_rot_y", "bot_discard_zone_spawn", "human_discard_zone_spawn", "clear_table_guids", "clear_table_spots"):
        assert key in notes, key


# ---------- the discard grid, the overlaps and the zone's rotation ----------
def grid_session(rot_y: float) -> Session:
    scfg = load_config(REAL_CONFIG).session_config()
    bounds = list(scfg.bot_discard_bounds)
    bounds[4] = rot_y
    scfg = dataclasses.replace(scfg, bot_discard_bounds=tuple(bounds))
    return Session(Game.new(Board.load("bprd-hq"), seed=3, controllers={}), None, MedusaAI(0), scfg)


def test_the_discard_grid_is_the_same_with_the_straight_zone_and_fits_inside_it():
    straight, crooked = grid_session(270.0), grid_session(269.1)
    assert straight.cfg.bot_discard_bounds[4] == 270.0
    assert straight._grid_slots() == crooked._grid_slots(), "straightening the zone does not move or drop a slot"
    x0, x1, z0, z1 = play._zone_rect(straight.cfg.bot_discard_bounds)
    slots = straight._grid_slots()
    assert len(slots) >= 28                                   # two columns of 15 minus the ones next to the draw deck
    assert all(x0 <= x <= x1 and z0 <= z <= z1 for x, _, z in slots)
    straight._check_config()                                  # the start-up check still finds slots


def test_the_floor_layout_uses_the_straight_zone_and_still_clears_the_panel():
    cfg = load_config(REAL_CONFIG)
    assert dict(play.floor_layout(cfg))
    assert play.floor_layout_warnings(cfg) == []
    assert not any("DESCARTE" in w or "descarte" in w for w in play.floor_layout_warnings(cfg))


def test_the_created_zones_overlap_no_hand_zone_of_the_official_save():
    for spawn in table_prep.zone_spawns(raw_config()).values():
        x0, x1, z0, z1 = play._zone_rect((spawn.position[0], spawn.position[2], spawn.scale[0], spawn.scale[2], spawn.rot_y))
        for _, (a0, a1, b0, b1) in play.HAND_AREAS:
            assert not (x0 < a1 and x1 > a0 and z0 < b1 and z1 > b0)


# ---------- the parking spots ----------
def test_every_parking_spot_is_clear_of_everything_the_bot_uses():
    cfg = load_config(REAL_CONFIG)
    assert play.park_warnings(cfg) == []
    areas = play.reserved_areas(cfg)
    names = " | ".join(n for n, _ in areas)
    for expected in ("caja de combate", "ONGOING", "zonas de mano", "panel", "tablero", "mazo de robo", "descarte", "fila", "bot_tuck_spot", "bot_removed_spot",
                     "card_zoom_spot", "dead_spot", "unpack"):
        assert expected.lower() in names.lower(), expected
    half = play.PARK_FOOTPRINT / 2
    for guid, (x, y, z) in table_prep.park_plan(cfg.raw):
        assert y >= 1.7, "above the table, not in it"
        for name, (x0, x1, z0, z1) in areas:
            assert not (x - half < x1 and x + half > x0 and z - half < z1 and z + half > z0), (guid, name)


def test_the_parking_spots_do_not_overlap_each_other():
    spots = [(g, s) for g, s in table_prep.park_plan(raw_config())]
    for i, (_, a) in enumerate(spots):
        for _, b in spots[i + 1:]:
            assert abs(a[0] - b[0]) >= play.PARK_FOOTPRINT or abs(a[2] - b[2]) >= play.PARK_FOOTPRINT


@pytest.mark.parametrize("spot, what", [
    ([-12.5, 2.0, -24.5], "panel"),                    # under the panel
    ([-2.0, 2.0, -18.0], "caja"),                      # on the human's combat box
    ([15.0, 2.0, 0.0], "zona"),                        # inside the bot's discard zone
    ([-12.0, 2.0, 5.0], "zona"),                       # inside the human's discard zone
    ([11.5, 2.0, -29.0], "fila"),              # on the look column
    ([30.0, 2.0, -9.0], "mano"),                       # on a hand zone
])
def test_a_parking_spot_on_something_the_bot_uses_is_warned(spot, what):
    raw = {**raw_config(), "clear_table_spots": [spot, [4.0, 2.0, -28.0], [8.0, 2.0, -28.0], [2.1, 2.0, -33.0]]}
    cfg = play.build_config(raw, ("default", "default"))
    warnings = play.park_warnings(cfg)
    assert warnings and what in " ".join(warnings), warnings
    assert warnings == [w for w in play.floor_layout_warnings(cfg) if "clear_table_spots" in w], "start-up prints them"


# ---------- 3. the session ----------
class FakeClient:
    def __init__(self, reply=None):
        self.scripts: list[str] = []
        self.reply = reply

    def call_lua(self, script, *a, **k):
        self.scripts.append(script)
        return self.reply(script) if callable(self.reply) else self.reply


def make_session(client=None, **over) -> Session:
    scfg = dataclasses.replace(load_config(REAL_CONFIG).session_config(), **over)
    return Session(Game.new(Board.load("bprd-hq"), seed=3, controllers={}), client or FakeClient(), MedusaAI(0), scfg)


def answer(zones, parked=()):
    return {"zones": zones, "parked": [{"guid": g, "name": "DeckCustom", "x": 1.0, "z": -28.0} for g in parked]}


CREATED = {"bot_discard_zone": {"guid": "newbot1", "status": "created"},
           "human_discard_zone": {"guid": "newhum1", "status": "created"}}


@pytest.fixture(autouse=True)
def spanish():
    i18n.set_language("es")
    yield
    i18n.set_language("es")


def test_a_created_zone_is_used_for_the_rest_of_the_session_and_said_in_the_chat():
    s = make_session(FakeClient(answer(CREATED)))
    s.prepare_table(resume=False)
    assert (s.cfg.bot_discard_zone, s.cfg.human_discard_zone) == ("newbot1", "newhum1")
    assert {"newbot1", "newhum1"} <= set(s.guids_in_use())
    s._say_startup_notes()
    assert any("la he creado" in m and "newbot1" in m for m in s.messages)
    assert any("la he creado" in m and "newhum1" in m for m in s.messages)


def test_the_chat_lines_come_out_in_english_too():
    s = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "906a7a", "status": "straightened"},
                                        "human_discard_zone": CREATED["human_discard_zone"]}, parked=["addeca"])))
    i18n.set_language("en")
    s.prepare_table(resume=False)
    s._say_startup_notes()
    text = " | ".join(s.messages)
    assert "I straightened the bot discard zone (906a7a): rotation 0, 270, 0." in text
    assert "I created it (GUID newhum1)" in text
    assert "I moved DeckCustom addeca out of the centre of the table to x 1.0, z -28.0" in text


def test_a_straightened_zone_keeps_its_guid_and_is_said():
    s = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "906a7a", "status": "straightened"},
                                        "human_discard_zone": {"guid": "b7a0b8", "status": "found"}})))
    s.prepare_table(resume=False)
    s._say_startup_notes()
    assert (s.cfg.bot_discard_zone, s.cfg.human_discard_zone) == ("906a7a", "b7a0b8")
    assert s.to_dict().get("zones_live") is None
    assert len(s.messages) == 1 and "enderezado" in s.messages[0]


def test_a_zone_that_was_already_straight_says_nothing():
    s = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "906a7a", "status": "found"},
                                        "human_discard_zone": {"guid": "b7a0b8", "status": "found"}})))
    s.prepare_table(resume=False)
    s._say_startup_notes()
    assert s.messages == []


def test_the_parked_objects_are_reported_one_by_one():
    s = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "906a7a", "status": "found"},
                                        "human_discard_zone": {"guid": "b7a0b8", "status": "found"}}, parked=CENTRE_GUIDS)))
    s.prepare_table(resume=False)
    s._say_startup_notes()
    assert [g for g in CENTRE_GUIDS if any(g in m and "movido" in m for m in s.messages)] == CENTRE_GUIDS


def test_a_fresh_start_sends_the_parking_plan_and_a_resume_does_not():
    fresh, resumed = FakeClient(answer(CREATED)), FakeClient(answer(CREATED))
    make_session(fresh).prepare_table(resume=False)
    make_session(resumed).prepare_table(resume=True)
    assert all(g in fresh.scripts[0] for g in CENTRE_GUIDS)
    assert not any(g in resumed.scripts[0] for g in CENTRE_GUIDS), "nothing is moved when resuming"
    assert "local PARK = {}" in resumed.scripts[0]


def test_nothing_is_sent_when_there_is_nothing_to_prepare():
    client = FakeClient(answer({}))
    make_session(client, zone_spawns={}, clear_plan=()).prepare_table(resume=False)
    make_session(client, zone_spawns={}, clear_plan=()).prepare_table(resume=True)
    assert client.scripts == []
    only_resume = make_session(client, zone_spawns={})
    only_resume.prepare_table(resume=True)
    assert client.scripts == [], "resuming with no zones to prepare sends nothing"


def test_a_zone_without_a_guid_stops_the_start_up_with_a_clear_message():
    s = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "", "status": "no_guid"},
                                        "human_discard_zone": CREATED["human_discard_zone"]})))
    with pytest.raises(SessionError, match="GUID"):
        s.prepare_table(resume=False)
    with pytest.raises(SessionError):
        make_session(FakeClient(None)).prepare_table(resume=False)


def test_the_identity_of_the_table_keeps_the_configured_zones():
    s = make_session(FakeClient(answer(CREATED)))
    before = (s.fingerprint(), s.guids_in_use(configured=True))
    s.prepare_table(resume=False)
    assert (s.fingerprint(), s.guids_in_use(configured=True)) == before, "a save of the old table is still this table"
    assert "906a7a" in s.guids_in_use(configured=True) and "906a7a" not in s.guids_in_use()


def test_the_created_guids_are_saved_and_the_next_resume_looks_for_them_first():
    first = make_session(FakeClient(answer(CREATED)))
    first.prepare_table(resume=False)
    saved = first.to_dict()
    assert saved["zones_live"] == {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    client = FakeClient(answer({"bot_discard_zone": {"guid": "newbot1", "status": "found"},
                                "human_discard_zone": {"guid": "newhum1", "status": "found"}}))
    second = make_session(client)                      # a new process: the configuration is the file's again
    second.load_dict(json.loads(json.dumps(saved)))    # the fingerprint accepts the save
    second.prepare_table(resume=True)
    assert '{"bot_discard_zone", {"newbot1", "906a7a"}' in client.scripts[0], "the persisted GUID first, the configured second"
    assert '{"human_discard_zone", {"newhum1", "b7a0b8"}' in client.scripts[0]
    assert (second.cfg.bot_discard_zone, second.cfg.human_discard_zone) == ("newbot1", "newhum1")
    assert second.to_dict()["zones_live"] == saved["zones_live"]


def test_a_persisted_zone_that_is_gone_on_resume_is_replaced_by_the_configured_one_or_a_new_one():
    first = make_session(FakeClient(answer(CREATED)))
    first.prepare_table(resume=False)
    saved = first.to_dict()
    second = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "906a7a", "status": "straightened"},
                                             "human_discard_zone": {"guid": "newhum2", "status": "created"}})))
    second.load_dict(json.loads(json.dumps(saved)))
    second.prepare_table(resume=True)
    assert (second.cfg.bot_discard_zone, second.cfg.human_discard_zone) == ("906a7a", "newhum2")
    assert second.to_dict()["zones_live"] == {"human_discard_zone": "newhum2"}


def test_a_fresh_start_prefers_the_configured_zone_and_reuses_a_leftover_one_before_creating_more():
    client = FakeClient(answer(CREATED))
    s = make_session(client)
    s._saved_zones = {"bot_discard_zone": "newbot1", "bogus": "x"}
    s.prepare_table(resume=False)
    assert '{"bot_discard_zone", {"906a7a", "newbot1"}' in client.scripts[0]
    assert '{"human_discard_zone", {"b7a0b8"}' in client.scripts[0]


def test_a_malformed_zones_live_is_ignored():
    for raw in (None, [], "x", {"bot_discard_zone": 5, "human_discard_zone": "bad guid", "other": "abc"}):
        assert Session.read_saved_zones(raw) == {}


def test_the_zones_the_save_was_made_with_do_not_change_the_table_identity_of_a_save_without_them():
    old = make_session(zone_spawns={}, clear_plan=())
    new = make_session()
    assert old.fingerprint()["config_hash"] == new.fingerprint()["config_hash"]


# ---------- 4. play: the whole start-up against the fake table ----------
def run_play(table, fake, ports, cfg_path, state, extra=(), until=None):
    """Runs `play.main` until `until()` holds (the bot said what it had to, the save was written) and stops it."""
    stop = threading.Event()
    code = {}
    th = threading.Thread(target=lambda: code.setdefault("c", play.main(
        ["--config", str(cfg_path), "--poll", "0.02", "--first", "human", *ports, "--state", str(state), *extra], stop=stop)))
    th.start()
    deadline = time.time() + 15
    while th.is_alive() and time.time() < deadline and not (until and until()):
        time.sleep(0.02)
    time.sleep(0.3)                                  # let the start-up finish writing its save
    stop.set()
    th.join(8)
    assert not th.is_alive()
    return code["c"]


def test_play_creates_the_zones_parks_the_centre_and_saves_the_new_guids(live, cfg_file, tmp_path):
    table, fake, ports = live
    table.new_zones = {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    table.parkable = set(CENTRE_GUIDS)
    state = tmp_path / "s.json"
    assert run_play(table, fake, ports, cfg_file(), state, until=state.exists) == 0
    assert len(table.prepared) == 1, "one message for the whole preparation"
    assert table.parked == CENTRE_GUIDS
    chat = " ".join(table.broadcasts)
    assert "la he creado" in chat and "He movido" in chat
    assert json.loads(state.read_text())["zones_live"] == {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    assert any("newbot1" in s for s in table.markings + table.scripts if "draw_markings" in s), "the floor marks the new zone"


def test_play_resume_uses_the_saved_zone_and_moves_nothing(live, cfg_file, tmp_path):
    table, fake, ports = live
    table.new_zones = {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    table.parkable = set(CENTRE_GUIDS)
    state = tmp_path / "s.json"
    assert run_play(table, fake, ports, cfg_file(), state, until=state.exists) == 0
    table.new_zones, table.parked, table.prepared = {}, [], []
    assert run_play(table, fake, ports, cfg_file(), state, ["--resume"],
                    until=lambda: any("reanudada" in b for b in table.broadcasts)) == 0, "the save of the first run is accepted"
    assert table.parked == [] and "local PARK = {}" in table.prepared[0]
    assert '{"bot_discard_zone", {"newbot1", "BOTZ"}' in table.prepared[0]
    assert json.loads(state.read_text())["zones_live"]["bot_discard_zone"] == "newbot1"


def test_play_with_an_old_style_config_prepares_nothing(live, cfg_file, tmp_path):
    table, fake, ports = live
    path = cfg_file()
    data = json.loads(path.read_text())
    for key in ("bot_discard_zone_spawn", "human_discard_zone_spawn", "clear_table_guids", "clear_table_spots"):
        data.pop(key)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert run_play(table, fake, ports, path, tmp_path / "s.json", until=(tmp_path / "s.json").exists) == 0
    assert table.prepared == []
