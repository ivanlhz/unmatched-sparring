"""F20: the bot prepares the official community save itself at start-up.

The official "Unmatched Official Tournament Table" save has no discard zones and keeps two decks, a d20 and the Dice
Cannon in the middle of the table. At start-up the bot creates the zones (straight: rotY 270), straightens the
hand-made ones of the pre-sparring save, and destroys the loose objects of the save the bot does not want (a listed set of GUIDs, fresh start only).

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

REMOVED = ["addeca", "cb6cbc", "65be8d", "5085eb", "6126d5", "790396"]
KINDS = {"addeca": "DeckCustom", "cb6cbc": "DeckCustom", "65be8d": "Die_20", "5085eb": "Custom_Assetbundle",
         "6126d5": "Digital_Clock", "790396": "Digital_Clock"}
KEPT = ["d26d8c", "5c7e75", "45c723", "1523b0", "bf4717", "dfe8db", "28ff83", "f93f2a"]   # counters, board, fog of war, hand and scripting triggers


def raw_config() -> dict:
    return json.loads(REAL_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture
def tts():
    """A bare table: no zones, nothing in the middle."""
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    return runtime


def prepare(runtime, zones, remove, rid=1):
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(lua.prepare_table(zones, remove, table_prep.removal_limits(raw_config())), rid))
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


# ---------- 2. the loose objects of the save: Lua ----------
def table_objects(tts):
    """The six objects to remove (name and place as in the official save) and eight that must stay."""
    tts.execute("""
local at = {addeca = {'DeckCustom', -5.7, -1.5}, cb6cbc = {'DeckCustom', 5.5, -1.5}, ['65be8d'] = {'Die_20', -0.7, -1.6},
            ['5085eb'] = {'Custom_Assetbundle', 2.1, -30.0}, ['6126d5'] = {'Digital_Clock', 5.5, 27.2}, ['790396'] = {'Digital_Clock', -5.1, 27.2}}
for g, a in pairs(at) do mkobj({guid = g, type = 'Generic', name = a[1], pos = Vector(a[2], 1.6, a[3])}) end
for _, g in ipairs({'d26d8c', '5c7e75', '45c723', '1523b0', 'bf4717', 'dfe8db', '28ff83', 'f93f2a'}) do mkobj({guid = g, type = 'Generic', name = 'Keep'}) end
getObjectFromGUID('5085eb').locked = true""")


def present(tts, guid):
    return tts.eval(f"getObjectFromGUID('{guid}') ~= nil")


def test_only_the_listed_objects_are_destroyed_and_everything_else_stays(tts):
    table_objects(tts)
    res = prepare(tts, [], list(table_prep.removal_plan(raw_config())))
    assert sorted(r["guid"] for r in res["removed"]) == sorted(REMOVED)
    assert res["skipped"] == []
    assert not any(present(tts, g) for g in REMOVED)
    assert all(present(tts, g) for g in KEPT)
    assert tts.eval("#OBJECTS") == len(KEPT)


def test_an_absent_object_is_skipped_and_the_others_are_still_destroyed(tts):
    table_objects(tts)
    tts.execute("getObjectFromGUID('65be8d').destruct()")
    res = prepare(tts, [], list(table_prep.removal_plan(raw_config())))
    assert sorted(r["guid"] for r in res["removed"]) == sorted(["addeca", "cb6cbc", "5085eb", "6126d5", "790396"])


def test_nothing_to_remove_is_an_empty_answer(tts):
    assert prepare(tts, [], list(table_prep.removal_plan(raw_config())))["removed"] == []


def test_an_empty_list_destroys_nothing(tts):
    table_objects(tts)
    assert prepare(tts, [], [])["removed"] == [] and tts.eval("#OBJECTS") == len(REMOVED) + len(KEPT)


def test_the_builder_destroys_only_listed_guids_and_never_by_area_or_type():
    script = lua.prepare_table([], [("abc123", "Die_20"), ("def456", "DeckCustom")])
    assert script.count("destruct()") == 1 and "for _, r in ipairs(REMOVE)" in script
    assert 'local REMOVE = {{"abc123", "Die_20"}, {"def456", "DeckCustom"}}' in script
    body = script.split("for _, r in ipairs(REMOVE)", 1)[1]
    assert "getObjects()" not in body and "o.type" not in body and "getObjectFromGUID(g)" in body and "name ~= r[2]" in body
    for forbidden in ("takeObject", "putObject", "Global", "UI.", "spawnObjectData", "setLuaScript", "messageID"):
        assert forbidden not in script, forbidden


def test_the_default_list_never_holds_a_counter_a_zone_a_trigger_or_the_board():
    listed = {g for g, _ in table_prep.removal_plan(raw_config())}
    assert listed == set(REMOVED)
    assert dict(table_prep.removal_plan(raw_config())) == KINDS
    assert listed.isdisjoint(KEPT)
    assert listed.isdisjoint({"d26d8c", "5c7e75"}), "the two hand cards counters stay"
    raw = raw_config()
    assert listed.isdisjoint({raw["bot_discard_zone"], raw["human_discard_zone"], raw["board_guid"], *raw["probe_guids"]})


def test_the_builder_refuses_what_it_cannot_write_safely():
    with pytest.raises(ValueError):
        lua.prepare_table([], [(f"g{i}", "Die_20") for i in range(lua.MAX_PREP_REMOVE + 1)])
    with pytest.raises(ValueError):
        lua.prepare_table([("bot_discard_zone", ["bad guid!"], (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 270.0)], [])
    with pytest.raises(ValueError):
        lua.prepare_table([], [("bad guid!", "Die_20")])


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
    {"remove_table": ["addeca"]},                                           # not a GUID -> name map
    {"remove_table": {"addeca": 5}},                                        # name not a string
    {"remove_table_limits": [26.0]},                                        # not (|x|, |z|)
    {"remove_table_limits": [26.0, -1]},                                    # not positive
    {"bot_discard_zone_spawn": {"position": [1, 2, 3]}},                    # no scale
    {"human_discard_zone_spawn": {"position": [1, 2, "x"], "scale": [1, 1, 1]}},
])
def test_a_badly_written_key_is_a_configuration_error(cfg_file, over):
    with pytest.raises(ConfigError):
        load_config(cfg_file(**over)).session_config()


def test_the_session_config_carries_the_new_keys(cfg_file):
    scfg = load_config(cfg_file()).session_config()
    assert set(scfg.zone_spawns) == {"bot_discard_zone", "human_discard_zone"}
    assert [g for g, _ in scfg.remove_plan] == REMOVED and scfg.remove_limits == (26.0, 36.0)


def test_the_new_keys_are_documented_in_the_comment_block():
    notes = "\n".join(raw_config()["_notes"])
    for key in ("discard_zone_rot_y", "bot_discard_zone_spawn", "human_discard_zone_spawn", "remove_table", "remove_table_limits"):
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
    hands = [(-32.1, -27.9, -30.0, 28.0), (27.9, 32.1, -30.0, 28.0), (-16.1, 16.1, 28.0, 40.0)]   # the save's HandTriggers
    for spawn in table_prep.zone_spawns(raw_config()).values():
        x0, x1, z0, z1 = play._zone_rect((spawn.position[0], spawn.position[2], spawn.scale[0], spawn.scale[2], spawn.rot_y))
        for a0, a1, b0, b1 in hands:
            assert not (x0 < a1 and x1 > a0 and z0 < b1 and z1 > b0)


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


def answer(zones, removed=()):
    return {"zones": zones, "removed": [{"guid": g, "name": "DeckCustom"} for g in removed]}


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
                                        "human_discard_zone": CREATED["human_discard_zone"]}, removed=["addeca"])))
    i18n.set_language("en")
    s.prepare_table(resume=False)
    s._say_startup_notes()
    text = " | ".join(s.messages)
    assert "I straightened the bot discard zone (906a7a): rotation 0, 270, 0." in text
    assert "I created it (GUID newhum1)" in text
    assert "I removed DeckCustom addeca from the table" in text


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


def test_the_removed_objects_are_reported_one_by_one():
    s = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "906a7a", "status": "found"},
                                        "human_discard_zone": {"guid": "b7a0b8", "status": "found"}}, removed=REMOVED)))
    s.prepare_table(resume=False)
    s._say_startup_notes()
    assert [g for g in REMOVED if any(g in m and "quitado" in m for m in s.messages)] == REMOVED


def test_a_fresh_start_sends_the_removal_list_and_a_resume_does_not():
    fresh, resumed = FakeClient(answer(CREATED)), FakeClient(answer(CREATED))
    make_session(fresh).prepare_table(resume=False)
    make_session(resumed).prepare_table(resume=True)
    assert all(g in fresh.scripts[0] for g in REMOVED)
    assert not any(g in resumed.scripts[0] for g in REMOVED), "nothing is removed when resuming"
    assert "local REMOVE = {}" in resumed.scripts[0]


def test_nothing_is_sent_when_there_is_nothing_to_prepare():
    client = FakeClient(answer({}))
    make_session(client, zone_spawns={}, remove_plan=()).prepare_table(resume=False)
    make_session(client, zone_spawns={}, remove_plan=()).prepare_table(resume=True)
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
    s.prepare_table(resume=False, saved_zones={"bot_discard_zone": "newbot1", "bogus": "x"})
    assert '{"bot_discard_zone", {"906a7a", "newbot1"}' in client.scripts[0]
    assert '{"human_discard_zone", {"b7a0b8"}' in client.scripts[0]


def test_a_malformed_zones_live_is_ignored():
    for raw in (None, [], "x", {"bot_discard_zone": 5, "human_discard_zone": "bad guid", "other": "abc"}):
        assert Session.read_saved_zones(raw) == {}


def test_the_zones_the_save_was_made_with_do_not_change_the_table_identity_of_a_save_without_them():
    old = make_session(zone_spawns={}, remove_plan=())
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


def test_play_creates_the_zones_removes_the_loose_objects_and_saves_the_new_guids(live, cfg_file, tmp_path):
    table, fake, ports = live
    table.new_zones = {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    table.removable = set(REMOVED)
    state = tmp_path / "s.json"
    assert run_play(table, fake, ports, cfg_file(), state, until=state.exists) == 0
    assert len(table.prepared) == 1, "one message for the whole preparation"
    assert table.removed == REMOVED
    chat = " ".join(table.broadcasts)
    assert "la he creado" in chat and "He quitado" in chat
    assert json.loads(state.read_text())["zones_live"] == {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    assert any("newbot1" in s for s in table.markings + table.scripts if "draw_markings" in s), "the floor marks the new zone"


def test_play_resume_uses_the_saved_zone_and_removes_nothing(live, cfg_file, tmp_path):
    table, fake, ports = live
    table.new_zones = {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}
    table.removable = set(REMOVED)
    state = tmp_path / "s.json"
    assert run_play(table, fake, ports, cfg_file(), state, until=state.exists) == 0
    table.new_zones, table.removed, table.prepared = {}, [], []
    assert run_play(table, fake, ports, cfg_file(), state, ["--resume"],
                    until=lambda: any("reanudada" in b for b in table.broadcasts)) == 0, "the save of the first run is accepted"
    assert table.removed == [] and "local REMOVE = {}" in table.prepared[0]
    assert '{"bot_discard_zone", {"newbot1", "BOTZ"}' in table.prepared[0]
    assert json.loads(state.read_text())["zones_live"]["bot_discard_zone"] == "newbot1"


def test_play_with_an_old_style_config_prepares_nothing(live, cfg_file, tmp_path):
    table, fake, ports = live
    path = cfg_file()
    data = json.loads(path.read_text())
    for key in ("bot_discard_zone_spawn", "human_discard_zone_spawn", "remove_table"):
        data.pop(key)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert run_play(table, fake, ports, path, tmp_path / "s.json", until=(tmp_path / "s.json").exists) == 0
    assert table.prepared == []


# ---------- review fixes ----------
def test_a_zone_with_the_spawn_transform_under_an_unknown_guid_is_adopted_not_duplicated(tts):
    """An earlier run created the zones and died before saving their GUIDs: no state file, no known GUID."""
    first = prepare(tts, [spec(), spec("human_discard_zone", ("b7a0b8",))], [])
    assert tts.eval("#SPAWNS") == 2
    tts.execute("SPAWNS[1].rot = Vector(0, 12, 0)")          # any rotation counts
    again = prepare(tts, [spec(), spec("human_discard_zone", ("b7a0b8",))], [], rid=2)
    assert tts.eval("#SPAWNS") == 2, "nothing is spawned a second time"
    assert {k: v["guid"] for k, v in again["zones"].items()} == {k: v["guid"] for k, v in first["zones"].items()}
    assert again["zones"]["bot_discard_zone"]["status"] == "straightened"
    assert vec(tts, "SPAWNS[1]", "rot")["y"] == 270.0


def test_a_zone_that_is_far_from_the_transform_is_not_adopted(tts):
    tts.execute("""mkobj({guid = 'other1', type = 'Scripting', pos = Vector(14.9677, 4.1422, 12.0), scale = Vector(35.4306, 5.1, 8.5464)})
                  mkobj({guid = 'other2', type = 'Scripting', pos = Vector(14.9677, 4.1422, 0.7422), scale = Vector(3, 5.1, 3)})""")
    assert prepare(tts, [spec()], [])["zones"]["bot_discard_zone"]["status"] == "created"


def test_two_zones_never_adopt_the_same_object(tts):
    tts.execute("mkobj({guid = 'one111', type = 'Scripting', pos = Vector(14.9677, 4.1422, 0.7422), scale = Vector(35.4306, 5.1, 8.5464)})")
    res = prepare(tts, [spec(), spec("human_discard_zone", ("b7a0b8",))], [])
    assert res["zones"]["bot_discard_zone"]["guid"] == "one111"
    assert res["zones"]["human_discard_zone"]["status"] == "created"


def test_a_fresh_start_does_not_write_a_game_that_has_not_begun(tmp_path):
    s = make_session(FakeClient(answer(CREATED)))
    s.state_path = tmp_path / "s.json"
    s.prepare_table(resume=False)
    assert not s.state_path.exists(), "a file written now would look resumable; the first step of the game saves the zones"
    s._persist()
    assert json.loads(s.state_path.read_text())["zones_live"] == {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum1"}


def test_an_interrupted_start_leaves_zones_the_next_start_adopts_without_a_state_file(tts):
    first = prepare(tts, [spec(), spec("human_discard_zone", ("b7a0b8",))], [])          # the run that died before saving
    again = prepare(tts, [spec(), spec("human_discard_zone", ("b7a0b8",))], [], rid=2)
    assert {k: v["guid"] for k, v in again["zones"].items()} == {k: v["guid"] for k, v in first["zones"].items()}
    assert tts.eval("#SPAWNS") == 2


def test_a_resume_that_replaces_a_zone_saves_it_and_keeps_everything_else_of_the_file(tmp_path):
    first = make_session(FakeClient(answer(CREATED)))
    first.prepare_table(resume=False)
    first._deck_origin["bot_deck_guid"] = "d42056"                      # a deck GUID the table gave it earlier
    first.cfg.bot_deck_guid = "deckLIVE1"
    saved = json.loads(json.dumps(first.to_dict()))
    assert saved["deck_live"] == {"bot": "deckLIVE1"}
    second = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "newbot1", "status": "found"},
                                             "human_discard_zone": {"guid": "newhum2", "status": "created"}})))
    second.state_path = tmp_path / "s.json"
    second.load_dict(json.loads(json.dumps(saved)))
    second.prepare_table(resume=True)                                   # before load_identities: the deck is not adopted yet
    written = json.loads(second.state_path.read_text())
    assert written["zones_live"] == {"bot_discard_zone": "newbot1", "human_discard_zone": "newhum2"}
    assert written["deck_live"] == saved["deck_live"], "the saved deck GUID survives the early write"
    assert {k: v for k, v in written.items() if k not in ("zones_live", "version")} == {k: v for k, v in saved.items() if k != "zones_live"}


def test_a_resume_that_changes_no_zone_writes_nothing(tmp_path):
    first = make_session(FakeClient(answer(CREATED)))
    first.prepare_table(resume=False)
    saved = json.loads(json.dumps(first.to_dict()))
    second = make_session(FakeClient(answer({"bot_discard_zone": {"guid": "newbot1", "status": "found"},
                                             "human_discard_zone": {"guid": "newhum1", "status": "found"}})))
    second.state_path = tmp_path / "s.json"
    second.load_dict(saved)
    second.prepare_table(resume=True)
    assert not second.state_path.exists()


# ---------- the destroy guards ----------
def one_object(tts, guid, name, x, z):
    tts.execute(f"mkobj({{guid = '{guid}', type = 'Generic', name = '{name}', pos = Vector({x}, 1.6, {z})}})")


def test_an_object_that_is_not_the_expected_kind_is_left_alone_and_reported(tts):
    one_object(tts, "790396", "Bag", 5.0, 0.0)               # TTS gave the freed GUID to something else
    res = prepare(tts, [], [("790396", "Digital_Clock")])
    assert res["removed"] == [] and res["skipped"] == [{"guid": "790396", "name": "Bag", "why": "type"}]
    assert present(tts, "790396")


@pytest.mark.parametrize("x, z", [(26.5, 0.0), (-26.5, 0.0), (0.0, 36.5), (0.0, -36.5), (30.0, -9.0), (-10.5, 108.8)])
def test_an_object_outside_the_central_table_is_left_alone_and_reported(tts, x, z):
    one_object(tts, "790396", "Digital_Clock", x, z)           # e.g. the template in the Timers bag
    res = prepare(tts, [], [("790396", "Digital_Clock")])
    assert res["removed"] == [] and res["skipped"][0]["why"] == "place" and present(tts, "790396")


@pytest.mark.parametrize("x, z", [(26.0, 36.0), (-26.0, -36.0), (5.5, 27.2), (2.1, -30.0)])
def test_an_object_inside_the_limits_is_destroyed(tts, x, z):
    one_object(tts, "790396", "Digital_Clock", x, z)
    assert prepare(tts, [], [("790396", "Digital_Clock")])["removed"] == [{"guid": "790396", "name": "Digital_Clock"}]
    assert not present(tts, "790396")


def test_an_adopted_zone_is_never_destroyed_even_if_its_guid_is_listed(tts):
    tts.execute("mkobj({guid = 'zonexx', type = 'Scripting', name = 'Digital_Clock', pos = Vector(14.9677, 4.1422, 0.7422), scale = Vector(35.4306, 5.1, 8.5464)})")
    res = prepare(tts, [spec()], [("zonexx", "Digital_Clock")])
    assert res["zones"]["bot_discard_zone"]["guid"] == "zonexx"
    assert res["removed"] == [] and res["skipped"][0]["why"] == "zone" and present(tts, "zonexx")


def test_a_guid_the_bot_uses_is_never_sent_for_removal():
    client = FakeClient(answer(CREATED))
    s = make_session(client, remove_plan=(("906a7a", "Digital_Clock"), ("d42056", "Die_20"), ("04b2c9", "Die_20"), ("addeca", "DeckCustom")))
    s._saved_zones = {"bot_discard_zone": "newbot1"}
    s.cfg.remove_plan += (("newbot1", "Die_20"),)
    s.prepare_table(resume=False)
    assert 'local REMOVE = {{"addeca", "DeckCustom"}}' in client.scripts[0]


def test_the_skipped_objects_are_said_in_the_chat():
    s = make_session(FakeClient({**answer({"bot_discard_zone": {"guid": "906a7a", "status": "found"},
                                           "human_discard_zone": {"guid": "b7a0b8", "status": "found"}}),
                                 "skipped": [{"guid": "790396", "name": "Bag", "why": "type"},
                                             {"guid": "6126d5", "name": "Digital_Clock", "why": "place"}]}))
    s.prepare_table(resume=False)
    s._say_startup_notes()
    assert len(s.messages) == 2 and "790396" in s.messages[0] and "tipo" in s.messages[0] and "fuera" in s.messages[1]


def read_only(live, cfg_file, tmp_path, state_zones):
    table, fake, ports = live
    table.missing_guids = {"BOTZ"}
    state = tmp_path / "s.json"
    if state_zones:
        state.write_text(json.dumps({"version": 1, "zones_live": state_zones}), encoding="utf-8")
    assert play.main(["--config", str(cfg_file()), "--read-only", "--state", str(state), *ports]) == 0
    return table


def test_read_only_reports_the_saved_zone_instead_of_the_missing_configured_one(live, cfg_file, tmp_path, capsys):
    table = read_only(live, cfg_file, tmp_path, {"bot_discard_zone": "newbot1"})
    out = capsys.readouterr().out
    assert "newbot1" in out
    assert not any("NO existe" in line for line in out.splitlines() if "BOTZ" in line)
    assert any('"newbot1"' in s for s in table.scripts if s.startswith("-- sparring:read_discard"))
    assert not any(s.startswith("-- sparring:prepare_table") for s in table.scripts), "read-only creates nothing"


def test_read_only_without_a_saved_zone_still_says_the_configured_one_is_missing(live, cfg_file, tmp_path, capsys):
    read_only(live, cfg_file, tmp_path, None)
    out = capsys.readouterr().out
    assert any("BOTZ" in line and "NO existe" in line for line in out.splitlines())
