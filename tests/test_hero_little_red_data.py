"""Little Red Riding Hood's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 177 of the tournament save (read from the images on 2026-11-22: the 30 cards, their bands, their corner symbols and the hero card
310 on sheet 3). Two values of unmatched-memory were slips (Big Eyes 3, Stones in the Belly 2) and are pinned here. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.import_save import deck_sheet
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

SLUG = "little-red-riding-hood"
OVERLAY = HEROES_DIR / "overlay" / f"{SLUG}.json"
EFFECTS = HEROES_DIR / "effects" / f"{SLUG}.json"
TTS = HEROES_DIR.parent / "tts" / f"{SLUG}.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
OTHERS = sorted(p.stem for p in TTS.parent.glob("*.json") if p.stem != SLUG)
EVERYONE = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini", "chupacabra", "loki", "pandora", "blackbeard", "rosie-the-riveter", "donatello"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "What Large Hands You Have": (2, "Little Red", "attack", 2, 3),
    "What Big Ears You Have": (2, "Little Red", "attack", 4, 2),
    "Long Have I Sought You": (3, "Huntsman", "attack", 4, 2),
    "What Big Eyes You Have": (2, "Little Red", "versatile", 3, 2),
    "What's That In My Basket?": (4, "Little Red", "versatile", 4, 3),
    "Once Upon a Time": (2, "any", "versatile", 2, 1),
    "Stones in the Belly": (3, "any", "versatile", 2, 1),
    "What a Terrible Big Mouth You Have": (2, "Little Red", "defense", 2, 2),
    "The Wolf's Skin": (3, "any", "defense", 2, 2),
    "Never Leave the Path": (2, "Little Red", "scheme", None, 1),
    "Into the Woods": (3, "Little Red", "scheme", None, 2),
    "A Grimm Tale": (2, "Huntsman", "scheme", None, 3),
}
# idx order of the sheet and the corner symbol of every copy, as read from the image
SHEET_ORDER = (["What Large Hands You Have"] * 2 + ["What Big Ears You Have"] * 2 + ["Long Have I Sought You"] * 3 + ["What Big Eyes You Have"] * 2
               + ["What's That In My Basket?"] * 4 + ["Once Upon a Time"] * 2 + ["Stones in the Belly"] * 3
               + ["What a Terrible Big Mouth You Have"] * 2 + ["The Wolf's Skin"] * 3 + ["Never Leave the Path"] * 2 + ["Into the Woods"] * 3
               + ["A Grimm Tale"] * 2)
SYMBOLS = (["wolf"] * 2 + ["wolf"] * 2 + ["axe"] * 3 + ["wolf"] * 2 + ["wild"] * 4 + ["rose"] * 2 + ["rose"] * 3 + ["axe"] * 2 + ["axe"] * 3
           + ["wolf"] * 2 + ["rose", "wolf", "axe"] + ["rose"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17700, 177, 310)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_melee_hero_with_one_ranged_huntsman():
    h = load_hero(SLUG)
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Little Red", "red", 14, 2, False, 0)
    hunter, = h.sidekicks
    assert (hunter.fid, hunter.name, hunter.count, hunter.hp, hunter.move, hunter.ranged, hunter.start_on_board) == ("huntsman", "Huntsman", 1, 9, 2, True, None)
    assert [(f.fid, f.on_board) for f in h.fighters()] == [("red", True), ("huntsman", True)]
    assert h.ability.startswith("Resolve an effect on a card you play if the symbol")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17700, 17730))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title


def test_the_two_slips_of_unmatched_memory_are_corrected_from_the_images():
    by = {c.title: c for c in load_hero(SLUG).deck()}
    assert (by["What Big Eyes You Have"].type, by["What Big Eyes You Have"].value) == ("versatile", 3)       # memory says 2
    assert (by["Stones in the Belly"].type, by["Stones in the Belly"].value, by["Stones in the Belly"].boost) == ("versatile", 2, 1)  # memory has no value


def test_every_copy_carries_the_symbol_printed_in_its_corner():
    deck = load_hero(SLUG).deck()
    got = []
    for c in deck:
        symbols = [t[len("symbol:"):] for t in c.tags if t.startswith("symbol:")]
        assert len(symbols) == 1, c.title
        got.append(symbols[0])
    assert got == SYMBOLS
    # the three Into the Woods print ONE symbol each, not three at once: three different cards
    woods = [c for c in deck if c.title == "Into the Woods"]
    assert len({c.tags for c in woods}) == 3


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero(SLUG).ai_profile
    assert set(profile) == {"red", "huntsman"} and profile["red"]["role"] == "hero" and not profile["red"]["ranged"]
    assert profile["huntsman"]["count"] == 1 and profile["huntsman"]["max_hp"] == 9 and profile["huntsman"]["ranged"]


def test_effects_validate_and_every_card_has_ops_except_the_two_that_are_pure_properties(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == SLUG
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS) or card["title"] in ("What Big Ears You Have", "What's That In My Basket?"), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert sorted(p["id"] for p in effects["plugins"]) == ["red:basket", "red:stones"]
    assert not [c["title"] for c in effects["cards"] if c.get("uncancelable") or c.get("may_boost")]


def basket_keys(node):
    """Every symbol a `red:basket` test of the node asks for."""
    if isinstance(node, dict):
        if node.get("test") == "plugin" and node.get("id") == "red:basket":
            yield node["key"]
        for v in node.values():
            yield from basket_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from basket_keys(v)


def test_each_line_is_tested_against_the_symbol_printed_in_front_of_it(effects):
    by = {c["title"]: sorted(set(basket_keys(c["effects"]))) for c in effects["cards"]}
    assert by == {"What Large Hands You Have": ["rose"], "What Big Ears You Have": [], "Long Have I Sought You": [], "What Big Eyes You Have": ["rose"],
                  "What's That In My Basket?": [], "Once Upon a Time": ["axe"], "Stones in the Belly": ["axe"], "What a Terrible Big Mouth You Have": ["wolf"],
                  "The Wolf's Skin": ["wolf"], "Never Leave the Path": ["axe", "rose", "wolf"], "Into the Woods": [], "A Grimm Tale": ["wolf"]}


def test_the_text_of_every_card_names_the_symbols_in_words(effects):
    by = {c.title: c.text for c in load_hero(SLUG).deck()}
    for card in effects["cards"]:
        assert card["text"] == by[card["title"]], card["title"]
    assert by["Never Leave the Path"] == ("(wolf) Place Little Red in any space. Gain 1 action. (axe) Deal 2 damage to each opposing fighter in Little Red's zone. "
                                          "(rose) Draw 3 cards.")


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_the_basket():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == SLUG and tts["deck"]["card_ids"] == [17700, 17729] and tts["deck"]["character_card_id"] == 310
    assert set(tts["fighters"]) == {"red", "huntsman"} and tts["fighters"]["red"]["dial_max"] == 14 and tts["fighters"]["huntsman"]["dial_max"] == 9
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["red"]["piece"], tts["fighters"]["red"]["dial"]) == ("9a5f4e", "75e561", "eb1971", "ca8e35")
    assert (tts["fighters"]["huntsman"]["piece"], tts["fighters"]["huntsman"]["dial"]) == ("83d1f2", "091f30")
    assert tts["tokens"] == {"basket": "51f3b8"} and tts["counter_dials"] == {}
    slots = tts["token_slots"]["basket"]
    assert set(slots) == {"bot", "human"} and all(len(v) == 1 for v in slots.values())


def test_the_importer_lets_the_overlay_name_a_loose_card_as_a_token(overlay):
    assert overlay["token_names"] == {"51f3b8": "basket"} and overlay["tts"] == {"bag_name": "Little Red Riding Hood"}


def test_the_deck_object_holds_the_thirty_cards_and_the_character_card():
    deck = {"DeckIDs": list(range(17700, 17730)) + [310]}
    assert deck_sheet(deck) == ((17700, 17729), 310)


# ---------------------------------------------------------------- the deck is her own

@pytest.mark.parametrize("other", OTHERS)
def test_her_images_are_nobody_elses_and_two_decks_with_the_same_range_are_told_apart_by_image(other):
    mine, theirs = load_hero_table(SLUG), load_hero_table(other)
    assert mine.card_ids == (17700, 17729)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in ((SLUG, other), (other, SLUG)):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", OTHERS)
def test_no_card_of_little_red_equals_a_card_of_another_deck(other):
    from sparring.heroes import available_heroes
    if other not in available_heroes():
        pytest.skip("table data only")
    assert not set(load_hero(SLUG).deck()) & set(load_hero(other).deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults(SLUG, SLUG)


def test_little_red_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot(SLUG), at_human(other)), BOT_SPOT, HUMAN_SPOT) == (SLUG, other)
        assert detect_heroes(reading(at_bot(other), at_human(SLUG)), BOT_SPOT, HUMAN_SPOT) == (other, SLUG)


def test_the_catalog_names_her_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of(SLUG) == "Little Red Riding Hood"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table(SLUG).identity]).slug == SLUG


def test_she_shares_only_the_life_dial_guid_with_other_heroes():
    """The dial `ca8e35` is Donatello's, Chupacabra's and Tomoe Gozen's too (told apart by name, tests/test_piece_identity.py); the rest is hers."""
    mine = set(load_hero_table(SLUG).all_guids())
    assert len(mine) == 6           # deck, two pieces, two dials, the Basket
    shared = {}
    for slug in OTHERS:
        common = mine & set(load_hero_table(slug).all_guids())
        if common:
            shared[slug] = common
    assert all(c == {"ca8e35"} for c in shared.values()), shared
    assert {"donatello", "chupacabra", "tomoe-gozen"} <= set(shared)
