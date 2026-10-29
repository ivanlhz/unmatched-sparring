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
from tools.import_save import (Report, SaveImportError, deck_sheet, dial_max, expected_token_keys, extract_hero,
                               find_hero_bag, import_hero, load_save, merge, render)

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
    assert expected_token_keys(raw, None) == {"ability"}          # Hellboy has forms: the ability token flips
    data = extract_hero(mini, load_hero("hellboy"), raw, report, {"ability"})
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
    assert expected_token_keys(raw, None) == {"intuition"}         # named by Abe's triggers
    report = Report("abe-sapien")
    data = extract_hero(save, load_hero("abe-sapien"), raw, report, {"intuition"})
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
    assert "not imported (PROBLEM lines above; --force overrides): medusa" in err


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


# --- review of 51451f4: problems block the write ------------------------------------------------------------------

def _edited(mini, edit):
    """A deep copy of the fixture after `edit(objects_by_guid)`."""
    save = json.loads(json.dumps(mini))
    edit({o["GUID"]: o for o in import_save.walk_all(save)})
    return save


def _run(tmp_path, save, *args):
    """main() over a save written under tmp_path/save, output under tmp_path/out; returns (rc, out dir)."""
    (tmp_path / "save").mkdir(exist_ok=True)
    path = tmp_path / "save" / "mini.json"
    path.write_text(json.dumps({"SaveName": "mini", "ObjectStates": save}), encoding="utf-8")
    return import_save.main([str(path), "--out", str(tmp_path / "out"), *args]), tmp_path / "out"


def _without(by, bag, guid):
    by[bag]["ContainedObjects"] = [o for o in by[bag]["ContainedObjects"] if o["GUID"] != guid]


def test_a_deck_dealt_onto_the_table_blocks_the_write_and_never_keeps_the_old_deck(mini, tmp_path, capsys):
    rc, out = _run(tmp_path, mini, "--hero", "hellboy")
    assert rc == 0
    before = (out / "hellboy.json").read_text(encoding="utf-8")
    dealt = _edited(mini, lambda by: _without(by, "in0001", "dk0001"))
    rc, out = _run(tmp_path, dealt, "--hero", "hellboy")
    captured = capsys.readouterr()
    assert rc == 1 and "PROBLEM deck: 0 physical hero decks" in captured.out
    assert "not imported (PROBLEM lines above; --force overrides): hellboy" in captured.err
    assert (out / "hellboy.json").read_text(encoding="utf-8") == before      # untouched
    data, report = import_hero(dealt, "hellboy", out)
    assert "deck" not in data and not report.kept       # the old deck GUID is not carried over


def test_force_writes_despite_problems_and_says_so(mini, tmp_path, capsys):
    dealt = _edited(mini, lambda by: _without(by, "in0001", "dk0001"))
    rc, out = _run(tmp_path, dealt, "--hero", "hellboy", "--force")
    captured = capsys.readouterr()
    assert rc == 0 and "written despite PROBLEM lines (--force): hellboy" in captured.err
    assert "deck" not in json.loads((out / "hellboy.json").read_text(encoding="utf-8"))
    with pytest.raises(SystemExit):
        _run(tmp_path, mini, "--hero", "hellboy", "--force", "--check")


def test_ambiguous_dials_are_a_problem_that_blocks_the_write(mini, tmp_path, capsys):
    def twin(by):
        by["in0001"]["ContainedObjects"].append({**by["dl0001"], "GUID": "dl0001b"})
    rc, out = _run(tmp_path, _edited(mini, twin), "--hero", "hellboy")
    assert rc == 1 and not (out / "hellboy.json").exists()
    assert "PROBLEM fighter 'hellboy': several dials match, took dl0001" in capsys.readouterr().out


def test_a_missing_counter_dial_is_a_problem_that_blocks_the_write(mini, tmp_path, capsys):
    rc, out = _run(tmp_path, _edited(mini, lambda by: _without(by, "in0001", "dl0003")), "--hero", "hellboy")
    assert rc == 1 and not (out / "hellboy.json").exists()
    assert "PROBLEM counter 'destiny': 0 dials named after it" in capsys.readouterr().out


def test_two_unnamed_copies_of_a_hero_bag_are_rejected_like_two_named_ones(mini, tmp_path):
    def duplicate(by):
        by["bg0001"]["ContainedObjects"].append(json.loads(json.dumps(by["ob0002"])))
    save = _edited(mini, duplicate)
    with pytest.raises(SaveImportError, match=r"2 decks of CardIDs 19900\.\.19929: dk0002, dk0002"):
        find_hero_bag(save, load_hero("liz-sherman"))
    data, report = import_hero(save, "liz-sherman", tmp_path)
    assert data is None and report.problems[0].startswith("hero not found in the save: no bag named 'Liz Sherman' and 2")

    def rename(by):
        by["ob0002"]["Nickname"] = "Hellboy"
    with pytest.raises(SaveImportError, match="2 bags named 'Hellboy'"):
        find_hero_bag(_edited(mini, rename), load_hero("hellboy"))


def test_a_stray_unnamed_token_is_a_problem_not_a_new_ability_token(mini, tmp_path, capsys):
    def stray(by):
        by["in0002"]["ContainedObjects"].append({"Name": "Custom_Token", "GUID": "st01", "Nickname": ""})
        by["in0001"]["ContainedObjects"].append({"Name": "Custom_Token", "GUID": "st02", "Nickname": ""})
    rc, out = _run(tmp_path, _edited(mini, stray), "--hero", "liz-sherman", "--hero", "hellboy")
    captured = capsys.readouterr().out
    assert rc == 1 and not list(out.glob("*.json"))
    assert "PROBLEM token 'ability' (st01, nickname ''): Liz Sherman uses no such token (expected: none)" in captured
    assert "PROBLEM token 'ability': more than one object (tk0001, st02)" in captured
    assert "unused objects in the inner bag: st01 Custom_Token ''" in captured


def test_a_token_the_hero_uses_but_the_bag_lacks_is_a_problem(mini, tmp_path):
    data, report = import_hero(_edited(mini, lambda by: _without(by, "in0001", "tk0001")), "hellboy", tmp_path)
    assert data["tokens"] == {}
    assert "token 'ability': Hellboy uses it and the inner bag has no such token" in report.problems


def test_the_existing_files_token_keys_count_as_expected():
    existing = {"tokens": {"intuition": "x"}, "token_sources": {"intuition": {}}, "token_faces": {"glow": {}}}
    assert expected_token_keys({"triggers": [], "forms": None}, existing) == {"intuition", "glow"}


def test_the_output_folder_can_never_hold_the_save(tmp_path):
    save = tmp_path / "saves" / "mini.json"
    save.parent.mkdir()
    save.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    for out in (save, save.parent, tmp_path):
        with pytest.raises(SystemExit) as e:
            import_save.main([str(save), "--out", str(out)])
        assert e.value.code == 2
    assert save.read_text(encoding="utf-8") == FIXTURE.read_text(encoding="utf-8")
    assert import_save.main([str(save), "--hero", "hellboy", "--out", str(tmp_path / "out")]) == 0
