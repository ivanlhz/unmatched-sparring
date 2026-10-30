"""tools/import_catalog.py: data/catalog/heroes.json out of a TTS savegame.

Units: a small synthetic save with the shape of the tournament one (nicknamed infinite bags holding an inner bag with
the deck; every deck on DeckID 176; a shared character-card sheet; decoys). Golden: the committed catalog is what the real
save gives today (skipped when saves/, gitignored, is not here)."""
import json

import pytest

from sparring.cards import repo_toplevel
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import hero_slugs
from sparring.tts.hero_table import load_hero_table
from tools import import_catalog
from tools.import_catalog import CATALOG_PATH, build_catalog, clean_name, render, slugify
from tools.import_save import load_save

SAVE = repo_toplevel() / "saves" / "Unmatched Official Tournament Table October 2026 (Hellboy).json"
SHARED = {"FaceURL": "https://x.test/shared-face/", "BackURL": "https://x.test/shared-back/"}


def sheet(tag):
    return {"FaceURL": f"https://x.test/{tag}-face/", "BackURL": f"https://x.test/{tag}-back/"}


def deck(guid, tag, n=30, name="DeckCustom", per_card=False):
    """n cards of sheet 176 plus the character card on the shared sheet "3"; `per_card` puts the CustomDeck in each card
    under another key (as 20 of Hellboy's 30 cards do) instead of only in the deck."""
    cards = [{"CardID": 17600 + i, "GUID": f"{guid}{i}",
              **({"CustomDeck": {"187": sheet(tag)}} if per_card else {})} for i in range(n)]
    cards.append({"CardID": 302, "GUID": f"{guid}c"})
    return {"Name": name, "GUID": guid, "Nickname": "", "ContainedObjects": cards,
            "CustomDeck": {"176": sheet(tag), "3": SHARED}}


def hero_bag(guid, nickname, *decks, minis=()):
    inner = {"Name": "Custom_Model_Bag", "GUID": guid + "i", "Nickname": "",
             "ContainedObjects": [*decks, *[{"Name": "Custom_Model", "GUID": g, "Nickname": n} for n, g in minis]]}
    return {"Name": "Custom_Model_Infinite_Bag", "GUID": guid, "Nickname": nickname, "ContainedObjects": [inner]}


@pytest.fixture
def objects():
    return [
        hero_bag("b1", "Raphael", deck("d1", "raph"), minis=[("[A32135]Raphael", "m1"), ("Casey Jones", "m2")]),
        hero_bag("b2", "Alice", deck("d2", "alice", per_card=True), deck("dx", "medusa", n=6)),
        hero_bag("b3", "Yennefer & Triss", deck("d3", "yen", n=25)),
        hero_bag("b4", "Twin A", deck("d4", "twin")),
        hero_bag("b5", "Twin B", deck("d5", "twin")),
        {"Name": "Infinite_Bag", "GUID": "pb", "Nickname": "Pick/Ban Deck",
         "ContainedObjects": [deck("d9", "pickban", n=77)]},
        hero_bag("b6", "Tournament Coins"),
        deck("loose", "orphan"),
    ]


def test_clean_name_and_slug():
    assert clean_name("[A32135]Raphael") == "Raphael" and clean_name(" Alice [-]") == "Alice"
    assert slugify("Yennefer & Triss") == "yennefer-triss"
    assert slugify("Dr. Jill Trent, Science Sleuth") == "dr-jill-trent-science-sleuth"


def test_every_hero_deck_is_found_by_its_bag_nickname_and_decoys_are_left_out(objects):
    cat = build_catalog(objects, "mini")
    assert [h["slug"] for h in cat["heroes"]] == ["alice", "raphael", "twin-a", "twin-b", "yennefer-triss"]
    raph = cat["heroes"][1]
    assert raph["name"] == "Raphael" and raph["card_count"] == 31 and raph["card_ids"] == [302, 17629]
    assert raph["deck_guid"] == "d1" and raph["bag_guid"] == "b1"
    assert raph["miniatures"] == [{"name": "Casey Jones", "guid": "m2"}, {"name": "Raphael", "guid": "m1"}]


def test_identity_is_the_decks_own_images_and_the_shared_sheet_is_left_out(objects):
    cat = build_catalog(objects, "mini")
    by = {h["slug"]: h for h in cat["heroes"]}
    assert by["raphael"]["identity"] == [{"face": "https://x.test/raph-face/", "back": "https://x.test/raph-back/"}]
    assert cat["shared_pairs"] == [{"face": SHARED["FaceURL"], "back": SHARED["BackURL"]}]
    assert by["alice"]["identity"] == [{"face": "https://x.test/alice-face/", "back": "https://x.test/alice-back/"}]
    assert by["alice"]["card_count"] == 31          # the 6-card leftover deck (Medusa's images) is not read


def test_unnamed_decks_and_identical_images_are_reported(objects):
    cat = build_catalog(objects, "mini")
    assert cat["unnamed"] == [{"bag_guid": "", "deck_guid": "loose", "card_count": 31}]
    assert cat["collisions"] == [["twin-a", "twin-b"]]
    assert "COLLISION twin-a, twin-b" in "\n".join(import_catalog.summary(cat))


def test_the_output_is_deterministic_whatever_the_order_of_the_save(objects):
    assert render(build_catalog(objects, "mini")) == render(build_catalog(list(reversed(objects)), "mini"))


def test_the_cli_writes_the_catalog_checks_it_and_never_overwrites_the_save(objects, tmp_path, capsys):
    save, out = tmp_path / "save.json", tmp_path / "out" / "heroes.json"
    save.write_text(json.dumps({"ObjectStates": objects}), encoding="utf-8")
    assert import_catalog.main([str(save), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["heroes"][0]["slug"] == "alice"
    assert import_catalog.main([str(save), "--out", str(out), "--check"]) == 0
    out.write_text("{}", encoding="utf-8")
    assert import_catalog.main([str(save), "--out", str(out), "--check"]) == 1
    with pytest.raises(SystemExit):
        import_catalog.main([str(save), "--out", str(save)])


# ---------- the committed catalog ----------
def test_the_catalog_names_every_playable_hero_with_its_own_images():
    cat = load_catalog()
    for slug in hero_slugs():
        hero = next(h for h in cat.heroes if h.slug == slug)
        mine = {f"{face}|{back}" for face, back in load_hero_table(slug).identity}
        assert mine <= hero.identity and cat.identify(sorted(mine)).slug == slug


def test_the_committed_catalog_has_no_collisions_or_unnamed_decks():
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert len(raw["heroes"]) >= 78 and raw["collisions"] == [] and raw["unnamed"] == []
    assert all(h["identity"] for h in raw["heroes"])


def test_the_real_save_regenerates_the_committed_catalog_byte_for_byte():
    if not SAVE.exists():
        pytest.skip("the tournament save is not here (saves/ is gitignored, read-only)")
    assert render(build_catalog(load_save(SAVE), SAVE.name)) == CATALOG_PATH.read_text(encoding="utf-8")
