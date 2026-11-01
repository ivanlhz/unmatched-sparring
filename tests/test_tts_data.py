"""data/tts/<slug>.json against the real save (read only) and against each hero's HeroDef."""
import json
import re

import pytest

from sparring.cards import repo_toplevel
from sparring.heroes import load_hero
from sparring.tts.hero_table import TTS_DIR, HeroTableError, load_hero_table, nicknames_for, parse_hero_table, table_defaults

SLUGS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
SAVE = repo_toplevel() / "saves" / "Unmatched Official Tournament Table October 2026 (Hellboy).json"


@pytest.fixture(scope="module")
def save_objects():
    if not SAVE.exists():
        pytest.skip("the tournament save is missing (saves/, read only)")
    return {o["GUID"]: o for o in json.loads(SAVE.read_text(encoding="utf-8"))["ObjectStates"]}


def walk(o):
    yield o
    for c in o.get("ContainedObjects", []):
        yield from walk(c)
    for st in (o.get("States") or {}).values():
        yield from walk(st)


@pytest.mark.parametrize("slug", SLUGS)
def test_every_guid_exists_in_the_hero_bag_of_the_real_save(save_objects, slug):
    t = load_hero_table(slug)
    outer = save_objects[t.bag]
    assert outer["Nickname"] and t.inner_bag in {c["GUID"] for c in outer["ContainedObjects"]}
    inner = next(c for c in outer["ContainedObjects"] if c["GUID"] == t.inner_bag)
    found = {o["GUID"]: o for o in walk(inner)}
    for guid in t.all_guids():
        assert guid in found, f"{slug}: {guid} is not in the bag {t.inner_bag}"
    # each fighter with a dial: its script reaches the HeroDef's maximum life
    specs = {f.fid: f for f in load_hero(slug).fighters()}
    for fid, f in t.fighters.items():
        if f.dial:
            assert int(re.search(r"MAX_VALUE = (\d+)", found[f.dial]["LuaScript"]).group(1)) == specs[fid].hp
    # the physical deck carries the 30 cards of the range plus the character one, with the declared image
    deck = found[t.deck_guid]
    lo, hi = t.card_ids
    assert sorted(deck["DeckIDs"]) == sorted([*range(lo, hi + 1), t.character_card_id])
    sheet = deck["CustomDeck"][str(lo // 100)]
    assert [(sheet["FaceURL"], sheet["BackURL"])] == list(t.identity)


def test_the_second_hellboy_state_is_a_state_of_the_first_miniature(save_objects):
    t = load_hero_table("hellboy")
    first, second = t.fighters["hellboy"].pieces
    inner = next(c for c in save_objects[t.bag]["ContainedObjects"] if c["GUID"] == t.inner_bag)
    mini = next(o for o in walk(inner) if o["GUID"] == first)
    assert [s["GUID"] for s in mini["States"].values()] == [second]


@pytest.mark.parametrize("slug", SLUGS)
def test_the_hero_table_matches_its_herodef(slug):
    hero, t = load_hero(slug), load_hero_table(slug)
    assert set(t.fighters) == {f.fid for f in hero.fighters()}
    assert t.card_ids == (hero.card_base, hero.card_base + 29)
    names = nicknames_for(hero, t)
    assert len(set(names.values())) == len(names)
    kinds = [k for k, _ in t.unpack_items()]
    assert kinds.count("deck") == 1 and kinds.count("piece") == len(t.fighters)


def test_the_abe_agents_carry_the_names_of_their_tokens_and_medusas_harpies_are_numbered():
    assert table_defaults("medusa", "abe-sapien")["nicknames"] == {
        "medusa": "Medusa", "harpy1": "Harpy 1", "harpy2": "Harpy 2", "harpy3": "Harpy 3", "abe": "Abe Sapien",
        "agent1": "Victor", "agent2": "Carla", "agent3": "Kate"}


def test_only_hellboy_needs_a_destiny_dial_on_whichever_side_he_plays():
    assert table_defaults("medusa", "hellboy")["destiny_dial"] == "e17c66"
    assert table_defaults("hellboy", "liz-sherman")["destiny_dial"] == "e17c66"      # bot Hellboy: the dial counts for the bot
    assert "destiny_dial" not in table_defaults("medusa", "baba-yaga")


def test_card_ranges_of_the_five_heroes_never_overlap():
    ranges = sorted(load_hero_table(s).card_ids for s in SLUGS)
    assert all(a[1] < b[0] for a, b in zip(ranges, ranges[1:]))


def test_a_table_file_that_disagrees_with_the_herodef_is_rejected():
    raw = json.loads((TTS_DIR / "medusa.json").read_text("utf-8"))
    hero = load_hero("medusa")
    bad = json.loads(json.dumps(raw))
    bad["fighters"]["medusa"]["dial_max"] = 12
    with pytest.raises(HeroTableError, match="the dial goes up to 12"):
        parse_hero_table(bad, hero)
    bad = json.loads(json.dumps(raw))
    del bad["fighters"]["harpy3"]
    with pytest.raises(HeroTableError, match="fighters"):
        parse_hero_table(bad, hero)
    bad = json.loads(json.dumps(raw))
    bad["deck"]["card_ids"] = [17700, 17729]
    with pytest.raises(HeroTableError, match="CardID range"):
        parse_hero_table(bad, hero)
