"""Houdini's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 178 of the tournament save (read from the images on 2026-11-02), and the deck is told apart from every other
hero's by CardID range and image. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, available_heroes, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "houdini.json"
EFFECTS = HEROES_DIR / "effects" / "houdini.json"
OTHERS = [h for h in available_heroes() if h != "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "The Big Reveal": (2, "Houdini", "attack", 2, 3),
    "An Illusion of My Own Design": (2, "Houdini", "attack", 4, 1),
    "Sleight of Hand": (2, "any", "attack", 1, 3),
    "For My Next Trick": (2, "any", "attack", 2, 2),
    "Flourish": (4, "any", "attack", 3, 2),
    "Vanishing Act": (3, "Houdini", "versatile", 2, 2),
    "Smoke and Mirrors": (2, "any", "versatile", 3, 1),
    "Misdirection": (3, "any", "versatile", 2, 1),
    "And the Beautiful Bess!": (2, "Bess", "versatile", 3, 1),
    "Grand Escape": (3, "Houdini", "defense", 2, 3),
    "All Part of the Show": (2, "any", "defense", 2, 2),
    "Set the Stage": (2, "Bess", "scheme", None, 2),
    "A Magician Never Reveals His Secrets": (1, "Houdini", "scheme", None, 4),
}
BOOSTED_WITH = {"Sleight of Hand", "Flourish", "Misdirection", "And the Beautiful Bess!", "All Part of the Show", "Set the Stage"}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17800, 178, 17700)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "bess", "name": "Bess"}]
    assert overlay["memory_slug"] == "harry-houdini" and overlay["name"] == "Houdini"


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("houdini")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Houdini", "houdini", 14, 2, False)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("bess", "Bess", 1, 5, 2, False)]
    deck = h.deck()
    assert len(deck) == 30 and deck[0].card_id == 17800 and deck[-1].card_id == 17829
    for title, (copies, fighter, kind, value, boost) in REAL_CARDS.items():
        cards = [c for c in deck if c.title == title]
        assert len(cards) == copies and {(c.fighter, c.type, c.value, c.boost) for c in cards} == {(fighter, kind, value, boost)}, title


def test_the_boosted_with_text_is_part_of_the_card_text():
    by_title = {c.title: c for c in load_hero("houdini").deck()}
    for title in BOOSTED_WITH:
        assert "BOOSTED WITH:" in by_title[title].text, title
    assert not any("BOOSTED WITH" in c.text for t, c in by_title.items() if t not in BOOSTED_WITH)


def test_the_effects_file_validates_and_has_a_boost_moment_for_exactly_the_boosted_with_cards(effects):
    assert validate_file(EFFECTS) == []
    with_boost = {c["title"] for c in effects["cards"] if c["effects"]["boost"]}
    assert with_boost == BOOSTED_WITH
    may_boost = {c["title"] for c in effects["cards"] if c.get("may_boost")}
    assert may_boost == {"The Big Reveal", "An Illusion of My Own Design", "Flourish", "Grand Escape"}      # "You may BOOST this card"
    assert [c["title"] for c in effects["cards"] if c.get("max_boosts")] == ["The Big Reveal"]
    assert effects["ability"]["passives"] == [{"kind": "rule", "id": "escape_artist", "rule": "maneuver_boost_places_hero"}]


def test_every_plugin_is_declared_and_registered(effects):
    from sparring.effects.ops_core import PLUGINS
    assert {p["id"] for p in effects["plugins"]} == {"houdini:replace_combatant", "houdini:return_boosted", "houdini:sleight_of_hand"}
    assert all(p["id"] in PLUGINS for p in effects["plugins"])


# ---------------------------------------------------------------- the table data and the deck identity

def test_the_table_data_is_the_save_and_names_every_piece_once():
    t = load_hero_table("houdini")
    assert t.card_ids == (17800, 17829) and t.character_card_id == 17700
    assert {fid: (f.pieces, f.dial, f.dial_max) for fid, f in t.fighters.items()} == {
        "houdini": (("3ec3d1",), "fdb21e", 14), "bess": (("a73e79",), "ede1d4", 5)}
    assert len(t.identity) == 1
    mine = set(t.all_guids())
    for slug in OTHERS:
        assert not mine & set(load_hero_table(slug).all_guids()), slug         # no GUID of the other nine is Houdini's


def test_houdinis_card_range_belongs_to_nobody_else_and_so_does_his_image():
    t = load_hero_table("houdini")
    for slug in OTHERS:
        other = load_hero_table(slug)
        assert other.card_ids[1] < 17800 or other.card_ids[0] > 17829, slug
        assert not set(t.identity) & set(other.identity), slug
        assert table_defaults("houdini", slug)["bot_card_ids"] == [17800, 17829]
        assert table_defaults(slug, "houdini")["human_card_ids"] == [17800, 17829]


def test_two_houdini_decks_are_refused():
    with pytest.raises(HeroTableError):
        table_defaults("houdini", "houdini")


def test_houdini_is_detected_on_either_side_against_any_hero():
    for other in OTHERS:
        assert detect_heroes(reading(at_bot("houdini"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("houdini", other)
        assert detect_heroes(reading(at_bot(other), at_human("houdini")), BOT_SPOT, HUMAN_SPOT) == (other, "houdini")


def test_the_catalog_names_houdini_with_the_images_of_both_sheets():
    catalog = load_catalog()
    assert catalog.name_of("houdini") == "Houdini"
    mine = f"{load_hero_table('houdini').identity[0][0]}|{load_hero_table('houdini').identity[0][1]}"
    assert catalog.identify([mine]).slug == "houdini"
