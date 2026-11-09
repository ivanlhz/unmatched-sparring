"""Sinbad's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 176 of the tournament save (read from the images on 2026-11-09), and his deck is told apart from the other decks of the sheet
(same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "sinbad.json"
EFFECTS = HEROES_DIR / "effects" / "sinbad.json"
TTS = HEROES_DIR.parent / "tts" / "sinbad.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
VOYAGE_TITLES = ["Voyage Home", "Voyage to the Valley of the Giant Snakes", "Voyage to the Island That Was a Whale",
                 "Voyage to the Creature With Eyes Like Coals of Fire", "Voyage to the City of the Man-Eating Apes",
                 "Voyage to the City of the King of Serendib", "Voyage to the Cannibals With the Root of Madness"]

# (copies, restriction, type, value, boost) as printed on the cards (no BOOST value on six VOYAGE cards: 0).
REAL_CARDS = {
    "Voyage Home": (1, "Sinbad", "attack", 2, 1),
    "Voyage to the Valley of the Giant Snakes": (1, "Sinbad", "attack", 2, 0),
    "Voyage to the Island That Was a Whale": (1, "Sinbad", "attack", 2, 0),
    "Voyage to the Creature With Eyes Like Coals of Fire": (1, "Sinbad", "attack", 2, 0),
    "Voyage to the City of the Man-Eating Apes": (1, "Sinbad", "attack", 2, 0),
    "Voyage to the City of the King of Serendib": (1, "Sinbad", "attack", 2, 0),
    "Voyage to the Cannibals With the Root of Madness": (1, "Sinbad", "attack", 2, 0),
    "Commanding Impact": (1, "any", "attack", 5, 2),
    "By Fortune and Fate": (3, "The Porter", "attack", 3, 1),
    "Momentous Shift": (3, "any", "versatile", 3, 1),
    "Regroup": (3, "any", "versatile", 1, 1),
    "Toil and Danger": (4, "Sinbad", "versatile", 3, 1),
    "Leap Away": (2, "any", "versatile", 4, 1),
    "Feint": (3, "any", "versatile", 2, 1),
    "Exploit": (2, "any", "versatile", 4, 1),
    "Riches Beyond Compare": (2, "Sinbad", "scheme", None, 1),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (VOYAGE_TITLES + ["Commanding Impact"] + ["By Fortune and Fate"] * 3 + ["Momentous Shift"] * 3 + ["Regroup"] * 3
               + ["Toil and Danger"] * 4 + ["Leap Away"] * 2 + ["Feint"] * 3 + ["Exploit"] * 2 + ["Riches Beyond Compare"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 303)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert {e["title"] for e in sheet if "voyage" in e.get("tags", ())} == set(VOYAGE_TITLES)
    assert overlay["counters"] == {"voyage": {"pile": "discard", "tag": "voyage"}}
    assert overlay["sidekicks"] == [{"fid": "porter", "name": "The Porter"}] and overlay["forms"] is None
    assert overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_melee_hero_with_the_porter_and_deals_a_real_deck():
    h = load_hero("sinbad")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Sinbad", "sinbad", 15, 2, False, 0)
    assert [(s.fid, s.name, s.hp, s.move) for s in h.sidekicks] == [("porter", "The Porter", 6, 2)]
    assert h.ability == "When you maneuver, you may move your fighters +1 space for each VOYAGE card in your discard pile."
    assert set(h.counters) == {"voyage"} and h.forms is None
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
        assert ("voyage" in c.tags) == (c.title in VOYAGE_TITLES), c.title
    assert next(c for c in deck if c.title == "Voyage Home").text == (
        "DURING COMBAT: This card's value is +1 for each other VOYAGE card in your discard pile. "
        "AFTER COMBAT: Take all other VOYAGE cards from your discard pile and add them to your hand.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("sinbad").ai_profile
    assert set(profile) == {"sinbad", "porter"} and profile["sinbad"]["role"] == "hero" and not profile["sinbad"]["ranged"]
    assert {e["title"] for e in profile["sinbad"]["exclusive"]} == set(VOYAGE_TITLES) | {"Toil and Danger", "Riches Beyond Compare"}
    assert {e["title"] for e in profile["porter"]["exclusive"]} == {"By Fortune and Fate"}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "sinbad"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert (any(card["effects"].get(m) for m in MOMENTS) or card["title"] == "Commanding Impact"), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert effects["plugins"] == []


def test_the_ability_is_a_passive_rule_that_reads_the_voyage_counter(effects):
    assert effects["ability"]["triggers"] == []
    assert effects["ability"]["passives"] == [{"id": "voyage_reach", "kind": "rule", "rule": "maneuver_move_per_counter", "counter": "voyage"}]


def test_every_voyage_card_adds_the_pile_to_its_value_and_no_other_card_does(effects):
    for card in effects["cards"]:
        during = card["effects"]["during"]
        if card["title"] in VOYAGE_TITLES:
            assert during == [{"op": "modify_value", "card": "this", "amount": {"counter": "voyage"}}], card["title"]
            assert card["text"].startswith("DURING COMBAT: This card's value is +1 for each other VOYAGE card in your discard pile."), card["title"]
        else:
            assert not any(op.get("amount") == {"counter": "voyage"} for op in during), card["title"]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Voyage Home"]["after"] == [{"op": "put_in_hand", "cards": {"zone": "discard", "player": "owner", "filter": {"tag": "voyage"},
                                                                         "pick": "all", "except": "this"}}]
    assert by["Voyage to the Creature With Eyes Like Coals of Fire"]["after"] == [
        {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}}]
    assert by["Voyage to the City of the King of Serendib"]["after"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by["Voyage to the Valley of the Giant Snakes"]["after"] == [{"op": "look_hand", "player": "opponent"}]
    assert by["Voyage to the City of the Man-Eating Apes"]["after"] == [{"op": "damage", "target": "opposing", "amount": 2}]
    assert by["Voyage to the Island That Was a Whale"]["after"] == [{"op": "heal", "target": "this", "amount": 2}]
    assert by["Voyage to the Cannibals With the Root of Madness"]["after"] == [{"op": "move", "target": "this", "amount": 2, "up_to": True}]
    assert by["Toil and Danger"]["after"] == [{"op": "move", "target": "this", "amount": 3, "up_to": True}]
    assert by["Exploit"]["after"] == by["Commanding Impact"]["after"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by["By Fortune and Fate"]["after"] == [{"op": "draw", "player": "owner", "amount": 2}]
    assert by["Riches Beyond Compare"]["scheme"] == [{"op": "draw", "player": "owner", "amount": 3}]
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Momentous Shift"]["during"][0]["condition"] == {"test": "moved_this_turn", "fighter": "this"}
    assert by["Momentous Shift"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]


def test_the_cards_other_heroes_print_word_for_word_are_the_same_data(effects):
    mine = {c["title"]: c for c in effects["cards"]}
    for slug, title in (("bigfoot", "Momentous Shift"), ("luke-cage", "Regroup"), ("abe-sapien", "Leap Away"), ("luke-cage", "Commanding Impact"),
                        ("bigfoot", "Feint"), ("baba-yaga", "Exploit")):
        theirs = next(c for c in json.loads((HEROES_DIR / "effects" / f"{slug}.json").read_text(encoding="utf-8"))["cards"] if c["title"] == title)
        assert mine[title]["text"] == theirs["text"] and mine[title]["effects"] == theirs["effects"], (slug, title)


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "sinbad" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 303
    assert set(tts["fighters"]) == {"sinbad", "porter"}
    assert (tts["fighters"]["sinbad"]["dial_max"], tts["fighters"]["porter"]["dial_max"]) == (15, 6)
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("6e6722", "e22b3b", "09f73c")
    assert (tts["fighters"]["sinbad"]["piece"], tts["fighters"]["sinbad"]["dial"]) == ("ff509a", "c48fac")
    assert (tts["fighters"]["porter"]["piece"], tts["fighters"]["porter"]["dial"]) == ("36ccb4", "7859ab")
    assert tts["tokens"] == {} and tts["counter_dials"] == {"voyage": "10bbcb"}          # the 'Voyages' dial (0-7) of the bag


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_sinbad_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    sinbad, theirs = load_hero_table("sinbad"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert sinbad.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(sinbad.identity) & set(theirs.identity)
    for bot, human in (("sinbad", other), (other, "sinbad")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_sinbad_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("sinbad").deck()) & set(load_hero(other).deck())


def test_sinbad_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("sinbad").deck())
    assert all(c not in set(load_hero("sinbad").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("sinbad", "sinbad")


def test_sinbad_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("sinbad"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("sinbad", other)
        assert detect_heroes(reading(at_bot(other), at_human("sinbad")), BOT_SPOT, HUMAN_SPOT) == (other, "sinbad")


def test_the_catalog_names_sinbad_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("sinbad") == "Sinbad"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("sinbad").identity]).slug == "sinbad"


def test_no_guid_of_sinbad_is_shared_with_another_hero():
    mine = set(load_hero_table("sinbad").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "sinbad"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
