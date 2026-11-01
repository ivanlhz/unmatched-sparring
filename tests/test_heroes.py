"""HeroDef and its loader (F07 step 1): the data in data/heroes/<slug>.json describe exactly what is
wired in the engine today for Medusa and Hellboy, and the rest of the Hellboy box loads its basic data."""
import json
from pathlib import Path

import pytest

from sparring.cards import load_hellboy_deck, load_medusa_deck, memory_dir, repo_toplevel
from sparring.heroes import (HEROES_DIR, HeroDataError, available_heroes, load_hero, parse_hero)
from sparring.state import ANUNG, DETECTIVE

GOLDEN_DECKS = Path(__file__).resolve().parent / "golden" / "decks.json"
DECK_FIELDS = ("card_id", "title", "fighter", "type", "value", "boost", "text", "destiny")


def golden_deck(hero: str) -> list[dict]:
    """The 30 Cards of each deck as the old loaders gave them (cards.py + data/*.json of commit
    3e84597, dumped once): the HeroDef's independent reference."""
    return json.loads(GOLDEN_DECKS.read_text(encoding="utf-8"))[hero]


def as_dicts(deck) -> list[dict]:
    return [{k: getattr(c, k) for k in DECK_FIELDS} for c in deck]


def test_available_heroes_are_the_hellboy_box_plus_medusa():
    assert {"abe-sapien", "baba-yaga", "hellboy", "liz-sherman", "medusa"} <= set(available_heroes())


def test_medusa_herodef_matches_the_wired_fighters_and_the_golden_deck():
    h = load_hero("medusa")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Medusa", "medusa", 16, 3, True)
    assert [(f.fid, f.name, f.hero, f.hp, f.move, f.ranged) for f in h.fighters()] == [
        ("medusa", "Medusa", True, 16, 3, True), ("harpy1", "Harpy", False, 1, 3, False),
        ("harpy2", "Harpy", False, 1, 3, False), ("harpy3", "Harpy", False, 1, 3, False)]
    assert as_dicts(h.deck()) == golden_deck("medusa") and as_dicts(load_medusa_deck()) == golden_deck("medusa")
    assert h.forms is None and h.counters == {} and h.attack_bonus(None, True) == 0
    assert "Medusa's zone" in h.ability


def test_hellboy_herodef_matches_the_wired_fighters_golden_deck_forms_and_bonus():
    h = load_hero("hellboy")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Hellboy", "hellboy", 18, 2, False)
    assert [(f.fid, f.name, f.hero, f.hp, f.move, f.ranged) for f in h.fighters()] == [
        ("hellboy", "Hellboy", True, 18, 2, False), ("lobster", "Lobster Johnson", False, 6, 2, True)]
    deck = h.deck()
    assert as_dicts(deck) == golden_deck("hellboy") and as_dicts(load_hellboy_deck()) == golden_deck("hellboy")
    assert sum(c.destiny for c in deck) == 11 and all("destiny" in c.tags for c in deck if c.destiny)
    assert h.forms.counter == "destiny" and h.forms.threshold == 6
    assert h.forms.of(5) == DETECTIVE and h.forms.of(6) == ANUNG
    assert h.counters["destiny"].pile == "discard" and h.counters["destiny"].tag == "destiny"
    assert h.attack_bonus(ANUNG, True) == 2 and h.attack_bonus(DETECTIVE, True) == 0
    assert h.attack_bonus(ANUNG, False) == 0          # Lobster does not add the +2
    assert {t["id"] for t in h.triggers} == {"detective_draw", "anung_discard_move"}


@pytest.mark.parametrize("slug, name, hp, move, ranged", [
    ("hellboy", "Hellboy", 18, 2, False),
    ("abe-sapien", "Abe Sapien", 13, 2, True),
    ("baba-yaga", "Baba Yaga", 13, 2, True),
    ("liz-sherman", "Liz Sherman", 16, 3, True),
])
def test_every_hero_of_the_hellboy_box_deals_a_30_card_deck(slug, name, hp, move, ranged):
    h = load_hero(slug)
    assert (h.name, h.hp, h.move, h.ranged) == (name, hp, move, ranged)
    deck = h.deck()
    assert len(deck) == 30 and len({c.card_id for c in deck}) == 30


def test_loading_an_unknown_hero_or_a_mismatched_slug_is_a_clear_error(tmp_path):
    with pytest.raises(HeroDataError, match="no HeroDef for 'dracula'"):
        load_hero("dracula", tmp_path)
    (tmp_path / "x.json").write_text(json.dumps({"slug": "y"}), encoding="utf-8")
    with pytest.raises(HeroDataError, match="the file's slug is 'y', not 'x'"):
        load_hero("x", tmp_path)


def _hero(**over):
    raw = json.loads((HEROES_DIR / "hellboy.json").read_text(encoding="utf-8"))
    raw.update(over)
    return raw


def test_validation_rejects_bad_restrictions_sizes_types_and_counters():
    raw = _hero()
    raw["deck"]["cards"][0]["fighter"] = "Medusa"
    with pytest.raises(HeroDataError, match="restriction 'Medusa' is not a fighter"):
        parse_hero(raw)
    raw = _hero()
    raw["deck"]["cards"].pop()
    with pytest.raises(HeroDataError, match="the deck has 29 cards"):
        parse_hero(raw)
    raw = _hero()
    raw["deck"]["cards"][3]["type"] = "spell"
    with pytest.raises(HeroDataError, match="type 'spell'"):
        parse_hero(raw)
    with pytest.raises(HeroDataError, match="counter 'fate', which does not exist"):
        parse_hero(_hero(forms={"counter": "fate", "threshold": 6, "below": "a", "at_or_above": "b"}))
    with pytest.raises(HeroDataError, match="unknown attack 'laser'"):
        parse_hero(_hero(attack="laser"))
    with pytest.raises(HeroDataError, match="repeated fighter ids"):
        parse_hero(_hero(sidekicks=[{"fid": "hellboy", "name": "X", "count": 1, "hp": 1, "move": 1, "attack": "melee"}]))


def test_memory_dir_hangs_from_the_main_repo_not_from_a_worktree_or_a_closer_folder(tmp_path, monkeypatch):
    main = tmp_path / "develop" / "unmatched-sparring"
    (main / ".git" / "worktrees" / "wt1").mkdir(parents=True)
    wt = main / ".claude" / "worktrees" / "wt1"
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt1'}\n", encoding="utf-8")
    (main / ".claude" / "worktrees" / "unmatched-memory" / "data" / "heroes").mkdir(parents=True)   # a nearby decoy
    assert repo_toplevel(wt) == main and repo_toplevel(main) == main
    monkeypatch.setattr("sparring.cards.DATA_DIR", wt / "data")
    monkeypatch.delenv("UNMATCHED_MEMORY", raising=False)
    assert memory_dir() == tmp_path / "develop" / "unmatched-memory"
    monkeypatch.setenv("UNMATCHED_MEMORY", str(tmp_path / "otro"))
    assert memory_dir() == tmp_path / "otro"


def test_generated_herodefs_are_up_to_date_with_memory_and_overlays():
    """`tools/import_hero.py --all --check`: what is versioned is what the importer produces (only if unmatched-memory
    is on this machine)."""
    if not (memory_dir() / "data" / "heroes" / "hellboy.json").exists():
        pytest.skip("no unmatched-memory on this machine")
    import importlib.util
    spec = importlib.util.spec_from_file_location("import_hero", HEROES_DIR.parent.parent / "tools" / "import_hero.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--all", "--check"]) == 0
