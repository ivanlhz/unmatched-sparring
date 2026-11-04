"""data/maps: the catalog of the official save's maps and the data file of each one.

The data comes from tools/import_map.py and is checked by eye on docs/maps-check; these tests keep it consistent:
every map of the catalog is accounted for, a supported map is a connected, symmetric graph with a zone on every space and
distinct start spaces, a map that needs tokens or doors has no data file, and every zone colour has a name in both
catalogs."""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

import pytest

from sparring.board import Board, catalog

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "data" / "maps"
ENTRIES = catalog()
SUPPORTED = [e for e in ENTRIES if e.status == "supported"]
EXCLUDED = {"helicarrier": "tokens", "hells-kitchen": "tokens", "navy-pier": "tokens", "sanctum-sanctorum": "tokens",
            "the-raft": "tokens", "heorot": "doors"}


def data_of(key: str) -> dict:
    return json.loads((MAPS / f"{key}.json").read_text(encoding="utf-8"))


def test_every_map_of_the_save_is_in_the_catalog_once():
    keys = [e.key for e in ENTRIES]
    assert len(keys) == len(set(keys)) == 37
    assert len({e.image_key for e in ENTRIES}) == 37
    assert all(re.fullmatch(r"[0-9A-F]{40}", e.image_key) for e in ENTRIES)
    assert {e.status for e in ENTRIES} <= {"supported", "unverified", "excluded", "unavailable"}


def test_the_maps_that_need_tokens_or_doors_are_the_excluded_ones():
    assert {e.key: e.reason for e in ENTRIES if e.status == "excluded"} == EXCLUDED
    for key in EXCLUDED:
        assert not (MAPS / f"{key}.json").exists()        # no data: nothing could play on them by mistake


def test_the_two_maps_that_were_always_supported_still_are():
    assert {"bprd-hq", "azuchi-castle"} <= {e.key for e in SUPPORTED}


def test_every_data_file_is_in_the_catalog_and_the_other_way_round():
    files = {p.stem for p in MAPS.glob("*.json")} - {"catalog"}
    assert files == {e.key for e in ENTRIES if e.status != "excluded"}


@pytest.mark.parametrize("entry", [e for e in ENTRIES if e.status == "unverified"], ids=lambda e: e.key)
def test_an_extracted_map_waits_for_a_person_before_it_is_played(entry):
    raw = data_of(entry.key)
    assert raw["playable"] is True and raw["verified"] is False


@pytest.mark.parametrize("entry", SUPPORTED, ids=lambda e: e.key)
def test_a_supported_map_is_a_sound_board(entry):
    raw = data_of(entry.key)
    board = Board.load(entry.key)
    assert raw["key"] == entry.key and raw["imageKey"] == entry.image_key
    assert raw.get("playable", True) is True and raw["verified"] is True
    ids = sorted(board.spaces)
    assert ids == list(range(len(ids))) and len(ids) >= 20
    for a in ids:
        assert a not in board.adj[a] and all(a in board.adj[b] for b in board.adj[a])          # symmetric, no loops
        assert board.adj[a], f"space {a} has no neighbour"
        assert board.zones(a), f"space {a} has no zone"
    seen, queue = {0}, deque([0])
    while queue:
        for n in board.moves[queue.popleft()]:
            if n not in seen:
                seen.add(n)
                queue.append(n)
    assert len(seen) == len(ids), "the board is not connected"
    assert {"1", "2"} <= set(board.starts) and board.starts["1"] != board.starts["2"]
    assert all(s in board.spaces for s in board.starts.values())
    assert len(set(board.starts.values())) == len(board.starts)


@pytest.mark.parametrize("entry", [e for e in ENTRIES if e.status == "unavailable"], ids=lambda e: e.key)
def test_an_unavailable_map_says_why_in_its_own_file(entry):
    raw = data_of(entry.key)
    assert raw["playable"] is False and raw["problems"]


def test_every_zone_colour_has_a_name_in_both_languages():
    zones = {z for e in ENTRIES if e.status != "excluded" for s in data_of(e.key)["spaces"] for z in s["zones"]}
    for lang in ("en", "es"):
        names = json.loads((ROOT / "data" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert {z for z in zones if f"spaces.color.{z}" not in names} == set()
