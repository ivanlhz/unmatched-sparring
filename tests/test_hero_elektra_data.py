"""Elektra's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 176 of the tournament save (read from the images on 2026-11-22: the 20 cards, their bands, the character cards 340 / 341 on sheet 3).
Her deck is sheet 176 with 20 playing cards, her health dial has a second object for the resurrected side and her four Hand are identical
tokens. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.import_save import deck_sheet
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "elektra.json"
EFFECTS = HEROES_DIR / "effects" / "elektra.json"
TTS = HEROES_DIR.parent / "tts" / "elektra.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat",
           "jill-trent", "she-hulk", "tomoe-gozen", "eredin"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards: The Fist is THE HAND's, Ninjitsu is ANY, the rest are ELEKTRA's.
REAL_CARDS = {
    "Mystic Assassin": (2, "Elektra", "attack", 6, 1),
    "Hands of Red": (2, "Elektra", "attack", 4, 2),
    "The Fist": (2, "The Hand", "attack", 3, 3),
    "Cloaked In Shadow": (2, "Elektra", "versatile", 2, 1),
    "Sai": (2, "Elektra", "versatile", 4, 3),
    "Whirlwind": (2, "Elektra", "versatile", 2, 1),
    "Ninjitsu": (2, "any", "versatile", 3, 2),
    "Intercept": (2, "Elektra", "defense", 3, 4),
    "Snakeroot Clan": (2, "Elektra", "defense", 1, 2),
    "Mesmerize": (2, "Elektra", "scheme", None, 2),
}
SHEET_ORDER = [t for t in REAL_CARDS for _ in range(2)]


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 340)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(20))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies and {e["fighter"] for e in entries} == {fighter}, title
    assert overlay["tts"]["character_cards"] == [340, 341]


def test_generated_herodef_is_a_melee_hero_with_seven_health_and_four_hand_on_the_board():
    h = load_hero("elektra")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.deck_size) == ("Elektra", "elektra", 7, 2, False, 20)
    hand, = h.sidekicks
    assert (hand.fid, hand.name, hand.count, hand.hp, hand.move, hand.ranged, hand.start_on_board) == ("hand", "The Hand", 4, 1, 2, False, None)
    assert [f.fid for f in h.fighters()] == ["elektra", "hand1", "hand2", "hand3", "hand4"]
    assert h.ability.startswith("The first time Elektra would be defeated")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17620))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title


def test_the_card_texts_carry_the_resurrected_lines():
    by = {c.title: c for c in load_hero("elektra").deck()}
    assert by["Mystic Assassin"].text == "AFTER COMBAT: Elektra takes 3 damage. RESURRECTED: Elektra takes no damage instead."
    assert by["Sai"].text == ""
    assert by["Intercept"].text.startswith("DURING COMBAT: RESURRECTED: You may reveal a card named \"Sai\"")


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "elektra"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS) or card["title"] == "Sai", card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert sorted(p["id"] for p in effects["plugins"]) == ["elektra:flip", "elektra:replace_combatant"]


def test_the_resurrect_is_one_trigger_in_the_printed_order(effects):
    assert effects["ability"]["counters"] == {"life": {"min": 0, "max": 2, "start": 0}}
    resurrect, = effects["ability"]["triggers"]
    assert resurrect["when"] == {"event": "start_of_turn", "player": "owner"}
    assert resurrect["condition"] == {"test": "counter", "name": "life", "min": 1, "max": 1}
    ops = resurrect["ops"]
    assert [o["op"] for o in ops] == ["plugin", "return_to_deck", "revive", "revive", "revive"]
    assert ops[0]["id"] == "elektra:flip" and ops[1]["position"] == "shuffle" and ops[1]["cards"]["zone"] == "discard" and ops[1]["cards"]["pick"] == "all"
    assert [o["hp"] for o in ops[2:]] == [9, 1, 1]
    assert ops[3]["where"] == {"any": True, "apart_from_own": True}      # a zone each (E1, E2) ...
    assert ops[4]["where"] == {"any": True}                              # ... and the rest wherever there is room
    assert ops[3]["target"] == ops[4]["target"] and ops[3]["target"]["state"] == "defeated" and ops[3]["target"]["pick"] == "all"


def test_every_resurrected_line_reads_the_same_counter(effects):
    lines = json.dumps([c["effects"] for c in effects["cards"] if c["title"] in ("Mystic Assassin", "Cloaked In Shadow", "Intercept", "Mesmerize", "Whirlwind")])
    assert lines.count('"test": "counter"') == 5 and lines.count('"name": "life"') == 5


def test_table_data_names_the_pieces_both_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "elektra" and tts["deck"]["card_ids"] == [17600, 17619] and tts["deck"]["character_card_id"] == 340
    assert set(tts["fighters"]) == {"elektra", "hand1", "hand2", "hand3", "hand4"}
    e = tts["fighters"]["elektra"]
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"], e["piece"], e["dial"], e["dial_max"], e["dial_flipped"], e["dial_flipped_max"]) == (
        "85cef8", "070893", "7d538d", "e5bac5", "aace96", 7, "c32f50", 9)
    assert sorted(v["piece"] for k, v in tts["fighters"].items() if k != "elektra") == ["8f67bf", "9bdc1d", "b771c8", "d72373"]
    assert all("dial" not in v and "nickname" not in v for k, v in tts["fighters"].items() if k != "elektra")      # 1 health: no dial; four identical tokens: numbered by the bot
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


def test_the_hand_are_numbered_and_the_flipped_dial_reaches_the_session_defaults():
    defaults = table_defaults("elektra", "hellboy")
    assert [defaults["nicknames"][f"hand{i}"] for i in (1, 2, 3, 4)] == ["The Hand 1", "The Hand 2", "The Hand 3", "The Hand 4"]
    assert defaults["dials"]["elektra"] == "aace96" and defaults["flip_dials"] == {"elektra": "c32f50"}
    assert "flip_dials" not in table_defaults("hellboy", "medusa")


def test_both_dials_are_unpacked_from_the_bag_and_counted_among_her_guids():
    table = load_hero_table("elektra")
    assert ("dial", ("c32f50",)) in table.unpack_items() and "c32f50" in table.all_guids()
    assert len(table.all_guids()) == 1 + 1 + 2 + 4


def test_the_importer_counts_the_two_character_cards_of_her_deck():
    ids = list(range(17600, 17620)) + [341, 340]
    deck = {"DeckIDs": ids}
    assert deck_sheet(deck, 20, 2, 340) == ((17600, 17619), 340)
    assert load_hero("elektra").tts["flip_dial"] == {"fid": "elektra", "name": "Elektra Resurrected"}


# ---------------------------------------------------------------- the deck is her own

@pytest.mark.parametrize("other", SHARING)
def test_elektras_images_are_nobody_elses(other):
    mine, theirs = load_hero_table("elektra"), load_hero_table(other)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("elektra", other), (other, "elektra")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_elektra_equals_a_card_of_the_other_decks(other):
    assert not set(load_hero("elektra").deck()) & set(load_hero(other).deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("elektra", "elektra")


def test_elektra_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("elektra"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("elektra", other)
        assert detect_heroes(reading(at_bot(other), at_human("elektra")), BOT_SPOT, HUMAN_SPOT) == (other, "elektra")


def test_the_catalog_names_elektra_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("elektra") == "Elektra"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("elektra").identity]).slug == "elektra"


def test_elektra_shares_no_guid_with_any_other_hero():
    mine = set(load_hero_table("elektra").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "elektra"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
