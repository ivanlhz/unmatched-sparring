"""The pre-game gate on the OFFICIAL tournament table exactly as the save loads it (tests/fixtures/official_table.json:
GUID, TTS object name, position and bag contents of its 170 objects, taken from the save): no map out, no discard zones,
the six centre objects, every hero and map in an infinite bag of the roster. Clean table must touch nothing but the leftovers
of the save; the player then drags a map and two heroes from the roster and Prepare turns it into the prepared state."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from sparring import table_reset
from sparring.cards import repo_toplevel
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_official_save_setup import KINDS, REMOVED, raw_config
from test_play import cfg_file, free_port, live  # noqa: F401
from test_review10 import conv
from test_table_reset import said, client_for, finish, game_started, press, run_main, session_for, shown, wait_for
from test_player_setup import Obj, SetupTable

FIXTURE = Path(__file__).parent / "fixtures" / "official_table.json"
SAVE = repo_toplevel() / "saves" / "Unmatched Official Tournament Table October 2026 (Hellboy).json"
OBJECTS = {o["guid"]: o for o in json.loads(FIXTURE.read_text(encoding="utf-8"))["objects"]}
PAD_KEY = next(o["image_key"] for o in OBJECTS.values() if o["name"] == "Custom_Board")
PAD_IMAGE = f"https://img.test/{PAD_KEY}/"
WRITES_ALLOWED = {"clear_markings", "create_panel", "set_panel", "broadcast", "prepare_table", "clear_setup", "place_map",
                  "unpack_from_bags", "reset_deck", "place_piece", "set_health_dials", "flip_decks_down", "set_token_face",
                  "set_state", "composite", "hold", "name_pieces", "take_character_cards", "arrange_objects", "split_token_stack"}


def run_real_lua(script: str, world: str = ""):
    """The generated script itself under lupa on an empty table (plus `world`, Lua that sets it up): the fake must not stand in
    for what the real script does with a table that lacks something. Returns the decoded reply or {"__error__": ...}."""
    lupa = pytest.importorskip("lupa")
    from lupa import lua54
    rt = lua54.LuaRuntime()
    rt.execute((Path(__file__).parent / "lua_stub.lua").read_text(encoding="utf-8"))
    replies = []
    rt.globals().JSON = rt.table_from({"encode": lambda v: replies.append(json.dumps(conv(v))) or ""})
    try:
        rt.execute(world)
        rt.execute(script)
    except lupa.LuaError as e:
        return {"__error__": str(e)}
    return json.loads(replies[0]) if replies else None


class OfficialTable(SetupTable):
    """The official table as it loads: heroes and maps in the roster (nothing of them on the table), no zones, the six objects of
    the centre; the player's drops come from `SetupTable`."""

    def __init__(self):
        super().__init__("medusa", "hellboy")
        self.positions = {n: i + 1 for i, n in enumerate(self.nick.values())}
        self.leftovers = {g: o["name"] for g, o in OBJECTS.items() if g in REMOVED}
        self.world = [Obj("pad", g, image=f"https://img.test/{o['image_key']}/") for g, o in OBJECTS.items() if o["name"] == "Custom_Board"]
        self.zones_on_table: set[str] = set()
        self.new_zones = {"bot_discard_zone": "zonebot", "human_discard_zone": "zonehum"}
        self.destroyed: list[str] = []

    def do_table_audit(self, s):
        out = super().do_table_audit(s)
        for row in list(out["removable"]):                 # the place guard, with the positions of the save
            x, _, z = OBJECTS[row["guid"]]["pos"]
            if abs(x) > 26 or abs(z) > 36:
                out["removable"].remove(row)
                out["blocked"].append({**row, "why": "place"})
        return out

    def do_zone_overlaps(self, s):
        guids = re.findall(r'"(\w+)"', re.search(r"ipairs\(\{(.*?)\}\)", s).group(1))
        return {g: ({"found": True, "zone": True, "hands": []} if g in self.zones_on_table else {"found": False}) for g in guids}

    def do_prepare_table(self, s):
        out = super().do_prepare_table(s)
        self.zones_on_table |= {z["guid"] for z in out["zones"].values()}
        self.destroyed += [r["guid"] for r in out["removed"]]
        return out

    def do_piece_spaces_by_guid(self, s):
        if all(o.kind == "pad" for o in self.world if o.kind in ("pad", "board")):      # no map on the table: the real script, not a fake's answer
            return run_real_lua(s)
        return super().do_piece_spaces_by_guid(s)


@pytest.fixture
def official(live, monkeypatch):  # noqa: F811
    _, fake, ports = live
    table = OfficialTable()
    fake.return_value = table
    monkeypatch.setattr(table_reset, "PANEL_SETTLE", 0.0)
    return table, fake, ports


def drag_prepared_pair(table):
    """The player drags the B.P.R.D. HQ board and Medusa's and Hellboy's bags from the roster: Medusa to the bot's half."""
    table.drop_map("bprd-hq")
    table.drop_bag("medusa", 7)
    table.drop_bag("hellboy", -7)


# ---------- the fixture is the save ----------
def test_the_fixture_is_the_official_save():
    if not SAVE.exists():
        pytest.skip("the official save is not in this checkout")
    save = json.loads(SAVE.read_text(encoding="utf-8"))
    assert [(o["GUID"], o["Name"], bool(o.get("Locked"))) for o in save["ObjectStates"]] == \
        [(o["guid"], o["name"], o["locked"]) for o in OBJECTS.values()]


def test_the_official_table_has_what_the_configuration_expects():
    assert len(OBJECTS) == 170
    assert {g: OBJECTS[g]["name"] for g in REMOVED} == KINDS, "the names the removal guard expects are the ones the save has"
    pads = [g for g, o in OBJECTS.items() if o["name"] == "Custom_Board"]
    assert sorted(pads) == ["45c723", "6bd0e3", "8315f0"], "no map on the table, only the pads"
    assert not any(g in OBJECTS for g in ("906a7a", "b7a0b8")), "the save has no discard zones"
    for slug in ("medusa", "hellboy"):
        table = load_hero_table(slug)
        assert table.inner_bag in [c["guid"] for c in OBJECTS[table.bag]["contains"]], slug


def test_the_roster_is_what_the_player_drags_from_infinite_bags_far_from_the_play_area():
    """Dragging from an infinite bag gives a copy of its single object: a hero's inner bag, a map's board."""
    assert OBJECTS["ab5e89"]["name"] == "Custom_Model_Infinite_Bag" and "B.P.R.D" in OBJECTS["ab5e89"]["nickname"]
    assert [c["guid"] for c in OBJECTS["ab5e89"]["contains"]] == ["ec6f27"]
    heroes = {load_hero_table(slug).bag for slug in ("medusa", "hellboy", "bigfoot", "houdini")}
    assert all(OBJECTS[b]["name"] == "Custom_Model_Infinite_Bag" for b in heroes)
    roster = [g for g, o in OBJECTS.items() if "Infinite_Bag" in o["name"]]
    assert len(roster) > 100 and all(abs(OBJECTS[g]["pos"][2]) > 36 for g in roster), "outside the limits Clean table works in"


def test_nothing_in_the_removal_list_is_a_bag_a_counter_a_hand_zone_or_the_pads():
    for g in REMOVED:
        assert OBJECTS[g]["name"] in ("DeckCustom", "Die_20", "Custom_Assetbundle", "Digital_Clock")
        assert abs(OBJECTS[g]["pos"][0]) <= 26 and abs(OBJECTS[g]["pos"][2]) <= 36, "inside the guard's limits"
    shelves = [g for g, o in OBJECTS.items() if abs(o["pos"][2]) > 36 or "Bag" in o["name"]]
    assert set(shelves).isdisjoint(REMOVED)


def test_clean_table_script_destroys_nothing_on_the_official_table_as_it_loads():
    """The REAL script on a world made of the save: no object of it is a hero's or a map's, so the cleaning finds nothing."""
    from sparring import player_setup
    kinds = {"Custom_Model_Infinite_Bag": "Infinite", "Infinite_Bag": "Infinite", "DeckCustom": "Deck", "CardCustom": "Card",
             "Custom_Board": "Board", "HandTrigger": "ScriptingTrigger", "ScriptingTrigger": "ScriptingTrigger",
             "FogOfWarTrigger": "ScriptingTrigger"}
    world = []
    for g, o in OBJECTS.items():
        nick = re.sub(r"[^A-Za-z0-9 ._:-]", " ", o["nickname"] or "")
        x, y, z = o["pos"]
        kind = kinds.get(o["name"], "Custom_Model")
        extra = {"Card": ", cid = 1, owner = 'rules'", "Deck": ", cards = {}"}.get(kind, "")
        world.append(f"mkobj({{guid = '{g}', type = '{kind}', name = '{nick}', pos = Vector({x}, {y}, {z}){extra}}})")
    world.append("for _, o in ipairs(getObjects()) do if o.type == 'Board' then "
                 "o.getCustomObject = function() return {image = 'https://x.test/ugc/AB/98097621768AC24FF097E6997A46CF69EE91FE46/'} end end end")
    got = run_real_lua(player_setup.clear_script(raw_config()), "\n".join(world))
    assert got == {"cards": 0, "boards": 0, "bags": 0, "objects": 0, "mixed": []}, got


# ---------- the audit ----------
@pytest.mark.gate
def test_the_official_table_is_reported_not_ready_and_the_game_does_not_start(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: said(table, "pulsa Preparar")() and shown(table, "btn_prep") == (True, True))
        text = " ".join(table.broadcasts)
        for needle in ("objetos sueltos", "no hay ningun mapa", "faltan las zonas de descarte", "siguen en la bolsa"):
            assert needle in text, needle
        for guid in ("addeca", "cb6cbc", "65be8d", "5085eb", "6126d5", "790396"):
            assert guid in text, guid
        assert shown(table, "btn_start") == (False, False) and not game_started(table)
        assert table.panels and all(s in ((False, False),) for k, s in table.panels[0][1].items()
                                    if k not in ("btn_clean", "btn_prep", "btn_start"))
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_the_audit_never_crashes_on_a_table_without_a_map(official, cfg_file, tmp_path):
    """Live: the pieces read did `board.positionToWorld` on the nil board and the whole audit died."""
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        text = " ".join(table.broadcasts)
        assert "No he podido revisar la mesa" not in text and "Ha fallado un paso" not in text
        assert "no hay ningun mapa" in text and "pieces_on_board" not in text
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_the_unreadable_map_and_heroes_are_one_short_line_while_the_gate_waits(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        text = " ".join(table.broadcasts)
        assert "No he podido leer la mesa tal como esta" not in text and "No puedo saber el heroe" not in text
        assert text.count("Aun no he leido el mapa") == 1
    finally:
        finish(stop, t, result)


# ---------- the buttons ----------
READS = {"list_boards", "table_audit", "deck_facing", "reset_plan", "piece_spaces_by_guid", "read_health_dials", "zone_overlaps",
         "inspect_objects", "deck_identities", "hand_identities", "find_pieces_by_name", "find_dials_by_name", "read_hand",
         "read_discard", "count_hand", "snapshot", "inspect_guids", "list_bags", "table_heroes"}


@pytest.mark.gate
def test_clean_table_creates_the_zones_removes_the_six_objects_and_touches_nothing_else(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_clean") == (True, True))
        press(fake, "clean_table")
        assert wait_for(said(table, "Arrastra ahora el mapa")), table.broadcasts[-5:]
        assert sorted(table.destroyed) == sorted(REMOVED) and table.leftovers == {}
        assert table.zones_on_table == {"zonebot", "zonehum"}
        assert [o.kind for o in table.world] == ["pad"] * 3, "the table pads stay"
        assert table.unpacked == 0 and table.arranged == {} and not game_started(table)
        assert set(table.sent) <= WRITES_ALLOWED | READS, set(table.sent)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_clean_then_drag_then_prepare_turns_the_official_table_into_the_prepared_state(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_clean") == (True, True))
        press(fake, "clean_table")
        assert wait_for(said(table, "Arrastra ahora el mapa"))
        drag_prepared_pair(table)
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert shown(table, "btn_prep") == (False, False)
        assert sorted(table.destroyed) == sorted(REMOVED) and table.zones_on_table == {"zonebot", "zonehum"}
        # B.P.R.D. HQ is calibrated: the transform the gate had before maps were calibrated
        assert table.map_placed == [("mapcopy1", (0.07, 1.64, -1.93), 270.0, 1.1)]
        assert table.unpacked == 1 and not table.in_bags and len(table.bot_deck) == 30
        assert {g: r["value"] for g, r in table.dials.items()} == table.dial_start
        assert all(d == 99.0 for d in table.piece_dist.values()) and table.moves == []
        assert table.bot_hand == [] and table.human_count == 0 and table.deal_calls == [] and not game_started(table)
        deck = raw_config()["layout"]["bot"]["deck"]["pos"]
        assert table.arranged["d42056"][0] == (deck[0], deck[1] + 0.2, deck[2]), "Medusa's deck at the bot's slot of the map"
        assert set(table.sent) <= WRITES_ALLOWED | READS, set(table.sent)
        text = " ".join(table.broadcasts)
        assert "Bot: Medusa Tu: Hellboy Mapa: B.P.R.D. Headquarters" in text and "Mesa preparada" in text and "Comenzar partida" in text
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_start_game_after_preparing_runs_the_normal_start_on_the_map_that_was_laid(official, cfg_file, tmp_path):
    table, fake, _ = official
    drag_prepared_pair(table)
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        time.sleep(0.4)
        assert not game_started(table)
        press(fake, "start_game")
        assert wait_for(lambda: any("Tu turno" in b for b in table.broadcasts))
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_the_audit_is_one_message_and_cleaning_and_preparing_are_a_handful(official, cfg_file, tmp_path):
    table, fake, _ = official
    client = client_for(official)
    try:
        session = session_for(client, cfg_file())
        before = fake.lua_messages
        table_reset.audit(client, session, None)
        assert fake.lua_messages - before <= 2, "one composite (plus the deck identities the first time)"
    finally:
        client.close()
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_clean") == (True, True))
        before = len(table.sent)
        press(fake, "clean_table")
        assert wait_for(said(table, "Arrastra ahora el mapa"))
        steps = [x for x in table.sent[before:] if x != "broadcast"]          # the chat lines are not steps
        assert len(steps) <= 8, steps
        drag_prepared_pair(table)
        before = len(table.sent)
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        steps = [x for x in table.sent[before:] if x != "broadcast"]
        # budget of the whole Prepare press: scan, map, unpack, the table_heroes rescan that reads the decks' real DeckIDs (it
        # can repeat while the decks spawn), the preparing session, the character cards, resets and the closing batch; raise it
        # only for a step the player's table really needs
        assert len(steps) <= 26, steps
    finally:
        finish(stop, t, result)
