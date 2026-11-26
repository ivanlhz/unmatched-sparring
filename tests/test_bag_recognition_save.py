"""Every hero's bag, as the tournament save holds it, is recognised when the player drags it onto the table (Ivan, 22/11/2026:
Blackbeard and Pandora came out as "a bag I do not recognise": the bag holds an object the bot never uses, the loose rules
card d0e886 and the deck of Miseries 4581f8, and `player_setup._bag_hero` needs every GUID in the bag to be the hero's)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sparring import hero_detect
from sparring.cards import repo_toplevel
from sparring.player_setup import _bag_family, _bag_hero
from sparring.tts.hero_table import load_hero_table, variants_of

ROOT = Path(__file__).resolve().parent.parent
SAVE = repo_toplevel() / "saves" / "Unmatched Official Tournament Table October 2026 (Hellboy).json"
TABLES = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}


def _walk(objs):
    for o in objs:
        yield o
        yield from _walk(o.get("ContainedObjects") or [])


@pytest.fixture(scope="module")
def by_guid():
    if not SAVE.exists():
        pytest.skip("the tournament save is not in saves/")
    return {o.get("GUID"): o for o in _walk(json.loads(SAVE.read_text(encoding="utf-8"))["ObjectStates"])}


@pytest.mark.parametrize("slug", sorted(TABLES))
def test_the_heros_bag_from_the_save_is_recognised(by_guid, slug):
    inner = by_guid.get(TABLES[slug].inner_bag_guid if hasattr(TABLES[slug], "inner_bag_guid") else None) \
        or by_guid.get(json.loads((ROOT / "data" / "tts" / f"{slug}.json").read_text(encoding="utf-8"))["bag"]["inner"])
    if inner is None:
        pytest.skip(f"{slug}: its inner bag is not in the save")
    held = [c["GUID"] for c in inner.get("ContainedObjects") or []]
    family = variants_of(slug)
    if len(family) > 1:                          # a box of several heroes: the family is recognised, the player picks the leader
        assert _bag_hero(held, TABLES) in family or _bag_family(held, TABLES) == family
    else:
        assert _bag_hero(held, TABLES) == slug, [g for g in held if g not in {*TABLES[slug].all_guids(), *TABLES[slug].ignored_tokens}]


@pytest.mark.parametrize("slug", sorted(s for s in TABLES if TABLES[s].ignored_tokens))
def test_the_bag_left_after_unpacking_with_only_ignored_objects_is_nobodys(slug):
    """Unpacking leaves the ignored objects in the dropped copy: that leftover must not read as the hero at the next Prepare."""
    assert _bag_hero(list(TABLES[slug].ignored_tokens), TABLES) is None


def test_clean_table_counts_the_ignored_objects_as_the_heros():
    """So the leftover copy holding only them is destroyed by Clean table like any other bag of hero pieces."""
    from sparring import player_setup
    raw = json.loads((ROOT / "config" / "table.json").read_text(encoding="utf-8"))
    script = player_setup.clear_script(raw)
    for slug, table in TABLES.items():
        for guid in table.ignored_tokens:
            assert guid in script, (slug, guid)
