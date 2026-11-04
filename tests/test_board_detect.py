"""Which map is on the table: found by its image, never by a fixed GUID.

The official save keeps every map in an infinite bag; a board taken out of it has a new GUID, so the bot reads the
Custom_Boards on the table, matches their image against data/maps/catalog.json and refuses (naming the map and the
supported ones) when the board is unknown, excluded or has no verified data. Everything runs on FakeTTS or on lupa."""
from __future__ import annotations

import pytest

from sparring import board_detect, i18n
from sparring.board import Board, MapEntry, catalog
from sparring.board_detect import BoardError, choose_board, image_key_of
from sparring.play import detect_board, load_config, main
from sparring.tts import lua
from sparring.tts.client import TTSClient
from test_play import cfg_file, live  # noqa: F401
from test_review9 import rt, run  # noqa: F401

BPRD = "1E5B373863CF97C6FF9E3478C687923A1C3E47AD"
AZUCHI = "35CA9807066CA49CED8A3F7DCB6BBD1AEF1C5AB4"
URL = "https://steamusercontent-a.akamaihd.net/ugc/10620501219968268988/{}/"


def url_of(key: str) -> str:
    return URL.format(key)


ENTRIES = [MapEntry("bprd-hq", "B.P.R.D. Headquarters", BPRD, "supported", None),
           MapEntry("azuchi-castle", "Azuchi Castle", AZUCHI, "supported", None),
           MapEntry("navy-pier", "Navy Pier", "A" * 40, "excluded", "tokens"),
           MapEntry("heorot", "Heorot", "B" * 40, "excluded", "doors"),
           MapEntry("soho", "Soho", "C" * 40, "unavailable", None)]


@pytest.fixture(autouse=True)
def spanish():
    i18n.set_language("es")
    yield
    i18n.set_language("es")


# ---------- the image key ----------
@pytest.mark.parametrize("url", [url_of(BPRD), url_of(BPRD.lower()), f"http://cloud-3.steamusercontent.com/ugc/1/{BPRD}",
                                 f"https://x.test/{BPRD}"])
def test_image_key_is_the_sha1_at_the_end_of_the_url_in_upper_case(url):
    assert image_key_of(url) == BPRD


@pytest.mark.parametrize("url", ["", "https://x.test/board.png", None, 17])
def test_a_url_without_a_key_has_none(url):
    assert image_key_of(url) is None


# ---------- choosing the board ----------
def test_a_supported_board_with_a_new_guid_is_chosen():
    entry, guid = choose_board([{"guid": "9a8b7c", "image": url_of(AZUCHI)}], ENTRIES)
    assert entry.key == "azuchi-castle" and guid == "9a8b7c"


def test_boards_that_are_not_maps_are_ignored_when_one_map_is_there():
    found = [{"guid": "6bd0e3", "image": "https://x.test/pad.png"}, {"guid": "111111", "image": url_of(BPRD)}]
    assert choose_board(found, ENTRIES)[1] == "111111"


@pytest.mark.parametrize("language, words", [("es", ("Navy Pier", "fichas", "Azuchi Castle")),
                                             ("en", ("Navy Pier", "tokens", "Azuchi Castle"))])
def test_an_excluded_map_is_refused_naming_it_and_the_supported_ones(language, words):
    i18n.set_language(language)
    with pytest.raises(BoardError) as e:
        choose_board([{"guid": "abc123", "image": url_of("A" * 40)}], ENTRIES)
    assert all(w in str(e.value) for w in words)
    assert "Soho" not in str(e.value) and "Heorot" not in str(e.value)       # only the supported maps are offered


def test_doors_are_named_as_the_reason():
    i18n.set_language("en")
    with pytest.raises(BoardError, match="Heorot.*doors"):
        choose_board([{"guid": "abc123", "image": url_of("B" * 40)}], ENTRIES)


def test_a_map_whose_data_did_not_pass_verification_is_refused():
    i18n.set_language("en")
    with pytest.raises(BoardError, match="Soho.*verif"):
        choose_board([{"guid": "abc123", "image": url_of("C" * 40)}], ENTRIES)


@pytest.mark.parametrize("language, word", [("es", "ningún tablero"), ("en", "No map board")])
def test_no_board_at_all_says_so(language, word):
    i18n.set_language(language)
    with pytest.raises(BoardError, match=word):
        choose_board([], ENTRIES)


def test_only_unknown_boards_say_the_image_and_list_the_supported_maps():
    i18n.set_language("en")
    with pytest.raises(BoardError) as e:
        choose_board([{"guid": "abc123", "image": "https://x.test/" + "D" * 40}], ENTRIES)
    assert "D" * 40 in str(e.value) and "Azuchi Castle" in str(e.value)


def test_two_maps_on_the_table_are_refused_naming_both():
    i18n.set_language("en")
    found = [{"guid": "111111", "image": url_of(BPRD)}, {"guid": "222222", "image": url_of(AZUCHI)}]
    with pytest.raises(BoardError, match="several") as e:
        choose_board(found, ENTRIES)
    assert "Azuchi Castle" in str(e.value) and "Headquarters" in str(e.value)


# ---------- the catalog ----------
def test_the_catalog_keeps_the_two_maps_that_were_always_there():
    entries = {e.key: e for e in catalog()}
    assert entries["bprd-hq"].image_key == BPRD and entries["bprd-hq"].status == "supported"
    assert entries["azuchi-castle"].image_key == AZUCHI and entries["azuchi-castle"].status == "supported"


# ---------- the Lua that reads the boards ----------
def test_list_boards_is_a_read_only_registered_script():
    s = lua.list_boards()
    assert s.startswith("-- sparring:list_boards") and lua._SENDABLE
    assert not any(w in s for w in ("setPosition", "destruct", "UI.", "spawn", "setRotation", "broadcast"))


def test_list_boards_returns_the_guid_and_image_of_each_board_on_the_table(rt):
    rt.execute("""
local board = mkobj({guid = '9a8b7c', type = 'Board'})
board.getCustomObject = function() return {image = 'https://x.test/ugc/AB/%s/'} end
mkobj({guid = '04b2c9', type = 'Figurine'})
local pad = mkobj({guid = '6bd0e3', type = 'Board'})
pad.getCustomObject = function() error('no custom object') end
""" % BPRD)
    found = run(rt, lua.list_boards())
    assert sorted(found, key=lambda b: b["guid"]) == [{"guid": "6bd0e3", "image": ""},
                                                       {"guid": "9a8b7c", "image": f"https://x.test/ugc/AB/{BPRD}/"}]


# ---------- the guid the scripts use ----------
def test_a_board_found_on_the_table_carries_its_guid_into_every_script():
    board = Board.load("azuchi-castle")
    board.guid = "9a8b7c"
    assert 'getObjectFromGUID("9a8b7c")' in lua.piece_spaces_by_guid(board, ["04b2c9"])
    assert 'getObjectFromGUID("9a8b7c")' in lua.move_piece(board, "04b2c9", 1)
    assert lua.board_guid(board) == "9a8b7c"


def test_without_a_found_guid_the_maps_that_were_always_supported_keep_theirs():
    assert lua.board_guid(Board.load("bprd-hq")) == "ec6f27"
    assert lua.board_guid(Board.load("azuchi-castle")) == "e57969"
    assert 'getObjectFromGUID("ec6f27")' in lua.piece_spaces_by_guid(Board.load("bprd-hq"), ["04b2c9"])


# ---------- start-up ----------
def with_boards(table, *boards):
    table.boards = [{"guid": g, "image": url_of(k)} for g, k in boards]


def test_the_map_on_the_table_is_used_whatever_the_config_says(live, cfg_file, capsys):
    table, fake, ports = live
    with_boards(table, ("9a8b7c", AZUCHI))
    assert main(["--config", str(cfg_file()), "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "Azuchi Castle" in out and "9a8b7c" in out and "ec6f27" not in out
    assert any(s.startswith("-- sparring:list_boards") for s in table.scripts)


def test_the_default_table_is_still_bprd(live, cfg_file, capsys):
    table, fake, ports = live
    assert main(["--config", str(cfg_file()), "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "B.P.R.D." in out and "ec6f27" in out


@pytest.mark.parametrize("key, word", [("A" * 40, "Navy Pier"), ("B" * 40, "Heorot")])
def test_start_up_stops_on_an_excluded_map_and_touches_nothing(live, cfg_file, capsys, key, word, monkeypatch):
    table, fake, ports = live
    monkeypatch.setattr(board_detect, "load_catalog", lambda: ENTRIES)
    with_boards(table, ("abc123", key))
    assert main(["--config", str(cfg_file()), *ports]) == 2
    err = capsys.readouterr().err
    assert word in err and "Azuchi Castle" in err
    assert {s.split("\n")[0] for s in table.scripts} <= {"-- sparring:list_boards"}


def test_the_chosen_map_is_the_one_the_game_is_built_on(live, cfg_file):
    table, fake, ports = live
    with_boards(table, ("9a8b7c", AZUCHI))
    client = TTSClient(send_port=fake.port, listen_port=int(ports[3]))
    client.start_listening()
    try:
        out = detect_board(client, load_config(cfg_file()), echo=lambda line: None)
    finally:
        client.close()
    assert out.board.key == "azuchi-castle" and out.board.guid == "9a8b7c"
    assert out.base["board"] == "azuchi-castle"          # a later rebuild of the configuration keeps the map
