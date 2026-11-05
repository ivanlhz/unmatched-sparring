"""The pre-game gate on the OFFICIAL tournament table exactly as the save loads it (tests/fixtures/official_table.json:
GUID, TTS object name, position and bag contents of its 170 objects, taken from the save): no map out, no discard zones,
the six centre objects, every hero and map in a bag. Pressing the button must turn it into the prepared state and touch
nothing else."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from sparring import table_prep, table_reset
from sparring.cards import repo_toplevel
from sparring.session import SessionError
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_official_save_setup import KINDS, REMOVED, raw_config
from test_play import cfg_file, free_port, live  # noqa: F401
from test_session import Table, set_bot_hand
from test_table_reset import (BOT_DECK, said, GateTable, client_for, finish, game_started, press, run_main, session_for, shown,
                              wait_for)
from sparring.board import Board
from sparring.state import Game

FIXTURE = Path(__file__).parent / "fixtures" / "official_table.json"
SAVE = repo_toplevel() / "saves" / "Unmatched Official Tournament Table October 2026 (Hellboy).json"
OBJECTS = {o["guid"]: o for o in json.loads(FIXTURE.read_text(encoding="utf-8"))["objects"]}
PAD_KEY = next(o["image_key"] for o in OBJECTS.values() if o["name"] == "Custom_Board")
PAD_IMAGE = f"https://img.test/{PAD_KEY}/"
WRITES_ALLOWED = {"clear_markings", "create_panel", "set_panel", "broadcast", "prepare_table", "take_map", "unpack_from_bags",
                  "reset_deck", "place_piece", "set_health_dials", "flip_decks_down", "set_token_face", "set_state",
                  "composite", "hold", "name_pieces"}


class OfficialTable(GateTable):
    """The official table as it loads: heroes in bags, no map, no zones, the six objects of the centre."""

    def __init__(self):
        super().__init__()
        self.in_bags = True
        self.leftovers = {g: o["name"] for g, o in OBJECTS.items() if g in REMOVED}
        self.boards = [{"guid": g, "image": f"https://img.test/{o['image_key']}/"} for g, o in OBJECTS.items()
                       if o["name"] == "Custom_Board"]
        self.zones_on_table: set[str] = set()
        self.new_zones = {"bot_discard_zone": "zonebot", "human_discard_zone": "zonehum"}
        self.map_taken: list[str] = []
        self.destroyed: list[str] = []
        self.inner_on_table = set()                        # the inner bags are inside the heroes' infinite bags
        self.outers = {t.bag: (OBJECTS[t.bag]["nickname"], [c["guid"] for c in OBJECTS[t.bag]["contains"]])
                       for t in (load_hero_table("medusa"), load_hero_table("hellboy"))}

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

    def do_take_map(self, s):
        bag = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        board = re.search(r'e\.guid == "(\w+)"', s).group(1)
        listed = [c["guid"] for c in OBJECTS.get(bag, {}).get("contains", [])]
        if board not in listed:
            return {"taken": False, "why": "board"}
        where = re.search(r"Vector\(([^)]*)\),\s+rotation", s).group(1)
        self.map_taken.append(f"{bag}:{board}:{where}")
        self.boards.append({"guid": "newbrd", "image": Table().boards[0]["image"]})
        return {"taken": True, "guid": "newbrd"}

    def do_unpack_from_bags(self, s):
        was = self.in_bags
        out = super().do_unpack_from_bags(s)
        if was and not self.in_bags:
            self.positions = {n: i + 1 for i, n in enumerate(self.nick.values())}
            self.piece_dist = {n: 99.0 for n in self.positions}
            self.bot_deck = list(BOT_DECK)
            self.dials = {g: {"found": True, "name": "dial", "value": v, "max": 20} for g, v in self.dial_start.items()}
        return out


@pytest.fixture
def official(live, monkeypatch):  # noqa: F811
    _, fake, ports = live
    table = OfficialTable()
    table.dial_start = {"bcd809": 16, "046660": 18, "18c384": 6, "e17c66": 0}
    table.bot_deck, table.human_count, table.positions, table.dials = [], 0, {}, {}
    fake.return_value = table
    monkeypatch.setattr(table_reset, "PANEL_SETTLE", 0.0)
    return table, fake, ports


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
    plan = table_prep.map_plan(raw_config())
    assert plan is not None and plan.bag in OBJECTS and plan.board_guid in [c["guid"] for c in OBJECTS[plan.bag]["contains"]]
    assert "B.P.R.D" in OBJECTS[plan.bag]["nickname"]
    pads = [g for g, o in OBJECTS.items() if o["name"] == "Custom_Board"]
    assert sorted(pads) == ["45c723", "6bd0e3", "8315f0"] and plan.board_guid not in pads, "no map on the table, only the pads"
    assert not any(g in OBJECTS for g in ("906a7a", "b7a0b8")), "the save has no discard zones"
    for slug in ("medusa", "hellboy"):
        table = load_hero_table(slug)
        assert table.inner_bag in [c["guid"] for c in OBJECTS[table.bag]["contains"]], slug


def test_nothing_in_the_removal_list_is_a_bag_a_counter_a_hand_zone_or_the_pads():
    for g in REMOVED:
        assert OBJECTS[g]["name"] in ("DeckCustom", "Die_20", "Custom_Assetbundle", "Digital_Clock")
        assert abs(OBJECTS[g]["pos"][0]) <= 26 and abs(OBJECTS[g]["pos"][2]) <= 36, "inside the guard's limits"
    shelves = [g for g, o in OBJECTS.items() if abs(o["pos"][2]) > 36 or "Bag" in o["name"]]
    assert set(shelves).isdisjoint(REMOVED)


# ---------- the audit ----------
@pytest.mark.gate
def test_the_official_table_is_reported_not_ready_and_the_game_does_not_start(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: said(table, "Medusa y Hellboy")() and shown(table, "btn_prep") == (True, True))
        text = " ".join(table.broadcasts)
        for needle in ("objetos sueltos", "no hay ningun mapa", "faltan las zonas de descarte", "siguen en la bolsa"):
            assert needle in text, needle
        for guid in ("addeca", "cb6cbc", "65be8d", "5085eb", "6126d5", "790396"):
            assert guid in text, guid
        assert shown(table, "btn_start") == (False, False) and not game_started(table)
        assert table.panels and all(s in ((False, False),) for k, s in table.panels[0][1].items() if k not in ("btn_prep", "btn_start"))
    finally:
        finish(stop, t, result)


# ---------- the button ----------
@pytest.mark.gate
def test_the_button_turns_the_official_table_into_the_prepared_state_and_touches_nothing_else(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert shown(table, "btn_prep") == (False, False)
        # removes: exactly the six, nothing more
        assert sorted(table.destroyed) == sorted(REMOVED) and table.leftovers == {}
        # creates: the two discard zones and the map (from the B.P.R.D. HQ bag, with the configured transform)
        assert table.zones_on_table == {"zonebot", "zonehum"}
        assert table.map_taken == ["ab5e89:ec6f27:-0.35, 1.63, -3.18"]
        # moves: the heroes' objects out of their bags, cards in decks, dials full, pieces off the board
        assert table.unpacked == 1 and not table.in_bags and len(table.bot_deck) == 30
        assert sorted(table.bags_taken) == ["c592d8", "e5a45c"], "each inner bag came out of its infinite bag first"
        assert {g: r["value"] for g, r in table.dials.items()} == table.dial_start
        assert all(d == 99.0 for d in table.piece_dist.values()) and table.moves == []
        # no hand dealt, no game started
        assert table.bot_hand == [] and table.human_count == 0 and table.deal_calls == [] and not game_started(table)
        # nothing else was written to the table
        assert set(table.sent) <= WRITES_ALLOWED | {"list_boards", "table_audit", "deck_facing", "reset_plan", "piece_spaces_by_guid",
                                                    "read_health_dials", "zone_overlaps", "inspect_objects", "deck_identities",
                                                    "hand_identities", "find_pieces_by_name", "find_dials_by_name", "read_hand",
                                                    "read_discard", "count_hand", "snapshot", "inspect_guids"}, set(table.sent)
        text = " ".join(table.broadcasts)
        assert "mapa B.P.R.D. HQ" in text and "Mesa limpia y preparada" in text
        assert "heroes y el mapa que quieras probar" in text and "Comenzar partida" in text
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_second_press_on_the_prepared_official_table_changes_nothing(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        before = (list(table.map_taken), list(table.destroyed), table.unpacked, list(table.placed), list(table.resets))
        said = len(table.broadcasts)
        press(fake, "prepare_table")
        assert wait_for(lambda: any("nada que hacer" in b for b in table.broadcasts[said:]))
        assert (list(table.map_taken), list(table.destroyed), table.unpacked, list(table.placed), list(table.resets)) == before
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_start_game_after_the_button_runs_the_normal_start_on_the_map_that_was_laid(official, cfg_file, tmp_path):
    table, fake, _ = official
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
def test_a_table_with_a_map_already_out_does_not_get_a_second_one(official, cfg_file, tmp_path):
    table, fake, _ = official
    table.boards.append({"guid": "ec6f27", "image": Table().boards[0]["image"]})
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert not any("ningun mapa" in b for b in table.broadcasts)
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        assert table.map_taken == []
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_bag_that_does_not_give_the_map_is_said_and_the_button_stays(official, cfg_file, tmp_path):
    table, fake, _ = official
    table.do_take_map = lambda s: {"taken": False, "why": "bag"}
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "ab5e89", "arreglarla a mano"))
        assert "No he podido limpiar" in " ".join(table.broadcasts) and shown(table, "btn_prep") == (True, True)
        assert shown(table, "btn_start") == (False, False) and table.destroyed == [] and not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_hero_bag_that_does_not_give_its_inner_bag_is_said_with_what_to_do_by_hand(official, cfg_file, tmp_path):
    table, fake, _ = official
    table.outers["65070e"] = ("Not Medusa", table.outers["65070e"][1])      # the infinite bag carries another name
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "A mano", "arreglarla a mano"))
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        text = " ".join(table.broadcasts)
        assert "Medusa" in text and "e5a45c" in text and "65070e" in text and "otro nombre" in text
        assert "No he podido limpiar" in text and shown(table, "btn_prep") == (True, True)
        assert shown(table, "btn_start") == (False, False) and table.destroyed == [] and not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_slow_copy_fails_the_first_press_and_the_second_reuses_it_without_a_duplicate(official, cfg_file, tmp_path):
    table, fake, _ = official
    table.spawn_late = True                                  # TTS has not spawned the copies when the script answers
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "aun se estaba creando", "arreglarla a mano"))
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert shown(table, "btn_start") == (False, False) and table.copies_made == 2 and table.destroyed == []
        table.spawn_late = False                             # the copies are there now
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        assert table.copies_made == 2 and table.bags_taken == [], "the loose copies were reused, none was made again"
        assert not table.loose_copies and sorted(table.destroyed) == sorted(REMOVED)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_one_press_makes_exactly_one_copy_per_hero_bag(official, cfg_file, tmp_path):
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        assert table.copies_made == 2 and not table.loose_copies
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_the_audit_is_one_message_and_the_whole_cleaning_a_handful(official, cfg_file, tmp_path):
    table, fake, _ = official
    client = client_for(official)
    try:
        session = session_for(client, cfg_file())
        before = fake.lua_messages
        table_reset.audit(client, session, None, raw_config())
        assert fake.lua_messages - before <= 2, "one composite (plus the deck identities the first time)"
    finally:
        client.close()
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        before = len(table.sent)
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        steps = [x for x in table.sent[before:] if x != "broadcast"]          # the chat lines are not steps of the cleaning
        assert len(steps) <= 24, steps
    finally:
        finish(stop, t, result)


# ---------- the helpers ----------
def test_the_map_plan_is_validated_and_optional():
    assert table_prep.map_plan({}) is None
    plan = table_prep.map_plan(raw_config())
    assert (plan.board, plan.bag, plan.board_guid, plan.position, plan.rot_y, plan.scale) == \
        ("bprd-hq", "ab5e89", "ec6f27", (-0.35, 1.63, -3.18), 269.99, 0.85)
    for bad in ({"board": "x"}, {**raw_config()["prepare_map"], "scale": 0}, {**raw_config()["prepare_map"], "position": [1, 2]}):
        with pytest.raises(ValueError):
            table_prep.map_plan({"prepare_map": bad})


def test_ensure_map_leaves_alone_a_table_with_a_map_or_a_configuration_without_one():
    class Client:
        def __init__(self, boards):
            self.boards, self.sent = boards, []

        def call_lua(self, script):
            self.sent.append(script.split("\n", 1)[0])
            if script.startswith("-- sparring:composite"):         # the clearing, and the map if it was asked for
                n = len(re.findall(r"results\[\d+\] = run", script))
                return {"ops": [{}, {"taken": False, "why": "bag"}][:n]}
            return self.boards
    known = [{"guid": "ec6f27", "image": Table().boards[0]["image"]}]
    assert table_reset.clear_and_ensure_map(Client(known), raw_config()) is None
    assert table_reset.clear_and_ensure_map(Client([]), {}) is None
    empty = Client([{"guid": "45c723", "image": PAD_IMAGE}])
    with pytest.raises(SessionError, match="ab5e89"):
        table_reset.clear_and_ensure_map(empty, raw_config())
    assert empty.sent[0] == "-- sparring:list_boards" and empty.sent[1] == "-- sparring:composite"
