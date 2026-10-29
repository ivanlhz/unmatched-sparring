"""tools/import_save.py: data/tts/<slug>.json out of a TTS savegame.

Golden: the real tournament save (saves/, gitignored, read-only) regenerates today's data/tts files byte for byte.
Units: a tiny synthetic save in tests/fixtures/mini_save.json (a Hellboy bag nested in a 'Heroes' bag, an unnamed bag
holding Liz Sherman's deck, decoys) that needs no real save."""
import json
from pathlib import Path

import pytest

from sparring.cards import repo_toplevel
from sparring.heroes import available_heroes, hero_path, load_hero
from sparring.tts.hero_table import TTS_DIR, parse_hero_table
from tools import import_save
from tools.import_save import (Report, deck_sheet, dial_max, extract_hero, find_hero_bag, import_hero, load_save,
                               merge, render)

SAVE = repo_toplevel() / "saves" / "Unmatched Official Tournament Table October 2026 (Hellboy).json"
FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.json"


@pytest.fixture(scope="module")
def mini():
    return load_save(FIXTURE)


@pytest.fixture(scope="module")
def real_save():
    if not SAVE.exists():
        pytest.skip("the tournament save is not here (saves/ is gitignored, read-only)")
    return load_save(SAVE)


# --- golden ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slug", available_heroes())
def test_the_real_save_regenerates_todays_file_byte_for_byte(real_save, slug):
    data, report = import_hero(real_save, slug, TTS_DIR)
    assert data is not None and not report.problems and not report.changed, report.lines()
    assert render(data) == (TTS_DIR / f"{slug}.json").read_text(encoding="utf-8")


def test_check_mode_passes_on_the_real_save(real_save, capsys):
    assert import_save.main([str(SAVE), "--check"]) == 0
    assert "CHANGED" not in capsys.readouterr().out


# --- walking the save -----------------------------------------------------------------------------------------

def test_walk_reaches_bag_contents_deck_cards_and_states(mini):
    guids = {o["GUID"] for o in import_save.walk_all(mini)}
    assert {"bg0001", "ob0001", "in0001", "dk0001", "c19700", "pc0001", "pc0001b", "ob0002", "dl0004"} <= guids
    assert "ch0001" not in guids       # ChildObjects (glued) are not contents


def test_dial_max_comes_from_the_scripts_max_value(mini):
    dials = {o["GUID"]: dial_max(o) for o in import_save.walk_all(mini) if dial_max(o) is not None}
    assert dials == {"dl0001": 18, "dl0002": 6, "dl0003": 11, "dl0004": 16}
    assert dial_max({"LuaScript": "MAX_VALUE=  7"}) == 7 and dial_max({"Name": "Custom_Model"}) is None


def test_deck_sheet_splits_the_30_cards_from_the_character_card():
    assert deck_sheet({"DeckIDs": [302, *range(17600, 17630)]}) == ((17600, 17629), 302)
    assert deck_sheet({"DeckIDs": list(range(17600, 17630))}) is None          # no character card
    assert deck_sheet({"DeckIDs": [302, *range(17600, 17629), 17640]}) is None  # not contiguous


# --- locating the bag -----------------------------------------------------------------------------------------

def test_the_hero_bag_is_found_by_name_inside_another_bag_and_the_decoy_is_ignored(mini):
    outer, inner = find_hero_bag(mini, load_hero("hellboy"))
    assert (outer["GUID"], inner["GUID"]) == ("ob0001", "in0001")


def test_an_unnamed_bag_is_found_through_the_deck_with_the_heros_card_ids(mini):
    outer, inner = find_hero_bag(mini, load_hero("liz-sherman"))
    assert (outer["GUID"], inner["GUID"]) == ("ob0002", "in0002")


def test_a_missing_hero_is_reported_not_raised(mini, tmp_path):
    data, report = import_hero(mini, "medusa", tmp_path)
    assert data is None
    assert report.problems == ["hero not found in the save: no bag named 'Medusa' and no deck of CardIDs 17600..17629"]


# --- extracting -----------------------------------------------------------------------------------------------

def test_hellboy_pieces_states_dials_token_and_counter_dial(mini):
    report = Report("hellboy")
    raw = json.loads(hero_path("hellboy").read_text(encoding="utf-8"))
    data = extract_hero(mini, load_hero("hellboy"), raw, report)
    assert data["bag"] == {"guid": "ob0001", "inner": "in0001"}
    assert data["deck"] == {"guid": "dk0001", "card_ids": [19700, 19729], "character_card_id": 19600,
                            "identity": [{"face": "https://example.test/hellboy-face/",
                                          "back": "https://example.test/hellboy-back/"}]}
    assert data["fighters"] == {"hellboy": {"piece": ["pc0001", "pc0001b"], "dial": "dl0001", "dial_max": 18},
                                "lobster": {"piece": "pc0002", "dial": "dl0002", "dial_max": 6}}
    assert data["tokens"] == {"ability": "tk0001"} and data["_token_children"] == {"ability": "tk0002"}
    assert data["counter_dials"] == {"destiny": "dl0003"}
    assert not report.problems and not report.unused


def test_a_hero_whose_dial_or_piece_is_missing_is_reported(mini):
    hero = load_hero("liz-sherman")
    save = json.loads(json.dumps(mini))
    inner = next(o for o in import_save.walk_all(save) if o["GUID"] == "in0002")
    inner["ContainedObjects"] = [o for o in inner["ContainedObjects"] if o["GUID"] != "dl0004"]
    report = Report("liz-sherman")
    extract_hero(save, hero, {"sidekicks": []}, report)
    assert report.problems == ["fighter 'liz': 16 HP and no dial named 'Liz Sherman'"]
    inner["ContainedObjects"] = [o for o in inner["ContainedObjects"] if o["GUID"] != "pc0003"]
    report = Report("liz-sherman")
    assert "fighters" in extract_hero(save, hero, {"sidekicks": []}, report)
    assert report.problems == ["fighter 'liz': no piece named 'Liz Sherman'"]


def test_same_name_sidekicks_are_numbered_in_the_order_the_bag_hands_them_out(mini):
    """A bag gives out its last object first: harpy1 is the last Harpy in ContainedObjects (as in data/tts/medusa)."""
    save = json.loads(json.dumps(mini))
    inner = next(o for o in import_save.walk_all(save) if o["GUID"] == "in0002")
    inner["ContainedObjects"] += [{"Name": "Custom_Token", "GUID": g, "Nickname": "Harpy"} for g in ("h1", "h2", "h3")]
    hero = load_hero("medusa")
    outer = next(o for o in import_save.walk_all(save) if o["GUID"] == "ob0002")
    outer["Nickname"] = "Medusa"
    inner["ContainedObjects"][0]["Nickname"] = "Medusa"
    report = Report("medusa")
    data = extract_hero(save, hero, {"sidekicks": []}, report)
    assert [data["fighters"][f]["piece"] for f in ("harpy1", "harpy2", "harpy3")] == ["h3", "h2", "h1"]


def test_sidekicks_with_named_tokens_get_their_nickname(mini):
    save = json.loads(json.dumps(mini))
    outer = next(o for o in import_save.walk_all(save) if o["GUID"] == "ob0002")
    outer["Nickname"] = "Abe Sapien"
    inner = outer["ContainedObjects"][0]
    inner["ContainedObjects"][0]["Nickname"] = "Abe Sapien"
    inner["ContainedObjects"][1]["Nickname"] = "Abe Sapien"
    inner["ContainedObjects"][1]["LuaScript"] = "MAX_VALUE = 13"
    inner["ContainedObjects"] += [{"Name": "Custom_Token", "GUID": g, "Nickname": n}
                                  for g, n in (("a1", "Victor"), ("a2", "Carla"), ("a3", "Kate"))]
    inner["ContainedObjects"].append({"Name": "Custom_Token_Stack", "GUID": "it01", "Nickname": "Intuition Token"})
    raw = json.loads(hero_path("abe-sapien").read_text(encoding="utf-8"))
    report = Report("abe-sapien")
    data = extract_hero(save, load_hero("abe-sapien"), raw, report)
    assert {f: v.get("nickname") for f, v in data["fighters"].items()} == {
        "abe": None, "agent1": "Victor", "agent2": "Carla", "agent3": "Kate"}
    assert data["tokens"] == {"intuition": "it01"}
    assert report.problems == ["deck dk0002: CardIDs 19900..19929 but the HeroDef sheet starts at 19400 "
                               "(identity by image is phase G2)"]


# --- merging with the versioned file --------------------------------------------------------------------------

def test_merge_keeps_notes_and_token_blocks_refreshes_the_child_guid_and_reports_changes():
    derived = {"slug": "hellboy", "bag": {"guid": "ob0001", "inner": "in0001"}, "deck": {"guid": "dk0001"},
               "fighters": {}, "tokens": {"ability": "tk0001"}, "counter_dials": {},
               "_token_children": {"ability": "tk0002"}}
    existing = {"slug": "hellboy", "_notes": ["hand-written"], "bag": {"guid": "old", "inner": "in0001"},
                "deck": {"guid": "dk0001"}, "fighters": {}, "tokens": {"ability": "tk0001"},
                "token_faces": {"ability": {"child": "oldchild", "verify_live": True, "faces": {"a": 0}}},
                "counter_dials": {}}
    report = Report("hellboy")
    out = merge(derived, existing, report)
    assert list(out) == ["slug", "_notes", "bag", "deck", "fighters", "tokens", "token_faces", "counter_dials"]
    assert out["_notes"] == ["hand-written"] and out["bag"]["guid"] == "ob0001"
    assert out["token_faces"]["ability"] == {"child": "tk0002", "verify_live": True, "faces": {"a": 0}}
    assert existing["token_faces"]["ability"]["child"] == "oldchild"      # the existing dict is not mutated
    assert report.changed == ["token_faces.ability.child: 'oldchild' -> 'tk0002'",
                              'bag: {"guid": "old", "inner": "in0001"} -> {"guid": "ob0001", "inner": "in0001"}']
    assert report.kept == ["_notes", "token_faces"]


def test_without_an_existing_file_only_derived_fields_are_written(mini, tmp_path):
    data, report = import_hero(mini, "hellboy", tmp_path)
    assert list(data) == ["slug", "bag", "deck", "fighters", "tokens", "counter_dials"]
    assert not report.kept and not report.changed and not report.problems
    parse_hero_table(data, load_hero("hellboy"))


# --- command line ---------------------------------------------------------------------------------------------

def test_main_writes_the_found_heroes_and_fails_for_the_missing_ones(tmp_path, capsys):
    rc = import_save.main([str(FIXTURE), "--hero", "hellboy", "--hero", "liz-sherman", "--hero", "medusa",
                           "--out", str(tmp_path)])
    assert rc == 1
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["hellboy.json", "liz-sherman.json"]
    for slug in ("hellboy", "liz-sherman"):
        parse_hero_table(json.loads((tmp_path / f"{slug}.json").read_text(encoding="utf-8")), load_hero(slug))
    err = capsys.readouterr().err
    assert "not imported: medusa" in err


def test_check_writes_nothing_fails_when_stale_and_passes_when_current(tmp_path, capsys):
    assert import_save.main([str(FIXTURE), "--hero", "hellboy", "--out", str(tmp_path), "--check"]) == 1
    assert not list(tmp_path.glob("*.json"))
    assert "+ \"slug\": \"hellboy\"" in capsys.readouterr().out
    assert import_save.main([str(FIXTURE), "--hero", "hellboy", "--out", str(tmp_path)]) == 0
    assert import_save.main([str(FIXTURE), "--hero", "hellboy", "--out", str(tmp_path), "--check"]) == 0
    stale = json.loads((tmp_path / "hellboy.json").read_text(encoding="utf-8"))
    stale["deck"]["guid"] = "other"
    (tmp_path / "hellboy.json").write_text(render(stale), encoding="utf-8")
    assert import_save.main([str(FIXTURE), "--hero", "hellboy", "--out", str(tmp_path), "--check"]) == 1
    out = capsys.readouterr().out
    assert '-  "guid": "other"' in out and '+  "guid": "dk0001"' in out and "CHANGED deck" in out
