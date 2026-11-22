"""Chupacabra's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-13), and his deck is told apart from the other decks of the
sheet (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "chupacabra.json"
EFFECTS = HEROES_DIR / "effects" / "chupacabra.json"
TTS = HEROES_DIR.parent / "tts" / "chupacabra.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "ciri", "eredin", "sinbad", "yennefer-triss"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
SHARED_DIAL = "ca8e35"        # the save reuses this Custom_Model GUID for Chupacabra's, Donatello's and Tomoe Gozen's life dials

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "The More They Struggle": (3, "Chupacabra", "attack", 0, 3),
    "Ambush": (2, "Chupacabra", "attack", 2, 3),
    "Feeding": (3, "Chupacabra", "attack", 4, 2),
    "Blood in the Air": (3, "Chupacabra", "attack", 4, 4),
    "Wounded Beast": (3, "Chupacabra", "versatile", 3, 1),
    "Tooth and Tail": (3, "Chupacabra", "versatile", 2, 2),
    "Feint": (3, "Chupacabra", "versatile", 2, 2),
    "Ravenous Lunge": (3, "Chupacabra", "versatile", 3, 2),
    "Natural Toughness": (2, "Chupacabra", "defense", 3, 3),
    "Traveler of the Night": (3, "Chupacabra", "scheme", None, 3),
    "Unsettle": (2, "Chupacabra", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["The More They Struggle"] * 3 + ["Ambush"] * 2 + ["Feeding"] * 3 + ["Blood in the Air"] * 3 + ["Wounded Beast"] * 3
               + ["Tooth and Tail"] * 3 + ["Feint"] * 3 + ["Ravenous Lunge"] * 3 + ["Natural Toughness"] * 2
               + ["Traveler of the Night"] * 3 + ["Unsettle"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 360)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}
    assert overlay["triggers"] == [] and overlay["passives"] == []


def test_the_schemes_print_no_value_whatever_unmatched_memory_says(overlay):
    assert {e["title"] for e in overlay["deck"]["sheet"] if "value" in e and e["value"] is None} == {"Traveler of the Night", "Unsettle"}


def test_generated_herodef_is_a_melee_hero_without_sidekicks_and_deals_a_real_deck():
    h = load_hero("chupacabra")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Chupacabra", "chupacabra", 14, 3, False, 0)
    assert h.sidekicks == [] or not h.sidekicks
    assert h.ability == "THE HUNGER\nAfter you attack, you may draw a card."
    assert not h.counters and h.forms is None
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    assert [c.title for c in deck] == SHEET_ORDER
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert next(c for c in deck if c.title == "Unsettle").text == (
        "Choose an opponent with a fighter in Chupacabra's zone. They discard 1 card. You may deal 2 damage to Chupacabra "
        "to make them discard 2 cards instead.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("chupacabra").ai_profile
    assert set(profile) == {"chupacabra"} and profile["chupacabra"]["role"] == "hero" and not profile["chupacabra"]["ranged"]


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "chupacabra"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert [p["id"] for p in effects["plugins"]] == ["chupacabra:ambush", "chupacabra:tooth_and_tail"]


def test_the_hunger_is_an_optional_draw_after_each_attack_of_the_player(effects):
    assert effects["ability"]["passives"] == []
    assert effects["ability"]["triggers"] == [{
        "id": "the_hunger", "when": {"event": "after_attack", "fighter": {"side": "own"}},
        "ops": [{"op": "optional", "chooser": "owner", "ops": [{"op": "draw", "player": "owner", "amount": 1}]}]}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["The More They Struggle"]["during"] == [
        {"op": "modify_value", "card": "this", "amount": {"attr": "value", "of": "opponent_card", "times": 2}}]
    assert by["Ambush"]["during"] == [{"op": "plugin", "id": "chupacabra:ambush"}]
    assert by["Tooth and Tail"]["after"] == [{"op": "plugin", "id": "chupacabra:tooth_and_tail"}]
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    for title in ("Feeding", "Wounded Beast"):                                       # "7 or less health"
        branch = by[title]["after" if title == "Feeding" else "during"][0]
        assert branch["condition"] == {"test": "compare", "left": {"stat": "hp", "fighter": "hero"}, "op": "<=", "right": 7}
    assert by["Wounded Beast"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]
    assert by["Feeding"]["after"][0]["then"] == [{"op": "gain_action", "amount": 1}, {"op": "heal", "target": "hero", "amount": 1}]
    assert by["Blood in the Air"]["during"][0]["then"] == [{"op": "allow_boost", "card": "this"}]
    assert by["Blood in the Air"]["during"][0]["condition"]["right"] == 1
    assert by["Ravenous Lunge"]["after"][0]["then"] == [{"op": "heal", "target": "hero", "amount": 2}]
    assert by["Ravenous Lunge"]["after"][0]["else"] == [{"op": "heal", "target": "hero", "amount": 1}]
    assert by["Natural Toughness"]["after"][0]["condition"] == {"test": "combat_result", "result": "lost"}
    assert by["Natural Toughness"]["after"][0]["then"] == [{"op": "put_in_hand", "cards": "this"}]
    assert by["Traveler of the Night"]["scheme"] == [
        {"op": "move", "target": "this", "amount": 4, "up_to": True, "through_enemies": True, "chooser": "owner"},
        {"op": "gain_action", "amount": 1}]
    unsettle = by["Unsettle"]["scheme"][0]
    assert unsettle["condition"] == {"test": "exists", "fighters": {"side": "enemy", "where": {"zone_of": "hero"}}}
    pay = unsettle["then"][0]
    assert pay["cost"] == [{"op": "damage", "target": "hero", "amount": 2}]
    assert [o["cards"]["amount"] for o in (*pay["ops"], *pay["else"])] == [2, 1]
    assert all(o["cards"]["chooser"] == "opponent" for o in (*pay["ops"], *pay["else"]))


def test_the_cards_other_heroes_print_word_for_word_are_the_same_data(effects):
    mine = {c["title"]: c for c in effects["cards"]}
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "bigfoot.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Feint")
    assert mine["Feint"]["text"] == theirs["text"] and mine["Feint"]["effects"] == theirs["effects"]


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "chupacabra" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 360
    assert set(tts["fighters"]) == {"chupacabra"} and tts["fighters"]["chupacabra"]["dial_max"] == 14
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("a20352", "d980fa", "3516ce")
    assert (tts["fighters"]["chupacabra"]["piece"], tts["fighters"]["chupacabra"]["dial"]) == ("4137cf", SHARED_DIAL)
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_chupacabra_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    mine, theirs = load_hero_table("chupacabra"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert mine.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("chupacabra", other), (other, "chupacabra")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_chupacabra_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("chupacabra").deck()) & set(load_hero(other).deck())


def test_chupacabra_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("chupacabra").deck())
    assert all(c not in set(load_hero("chupacabra").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("chupacabra", "chupacabra")


def test_chupacabra_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("chupacabra"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("chupacabra", other)
        assert detect_heroes(reading(at_bot(other), at_human("chupacabra")), BOT_SPOT, HUMAN_SPOT) == (other, "chupacabra")


def test_the_catalog_names_chupacabra_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("chupacabra") == "Chupacabra"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("chupacabra").identity]).slug == "chupacabra"


def test_only_the_life_dial_guid_is_shared_with_other_heroes_and_only_with_donatello_tomoe_gozen_and_little_red():
    mine = set(load_hero_table("chupacabra").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "chupacabra"]:
        common = mine & set(load_hero_table(slug).all_guids())
        assert common == ({SHARED_DIAL} if slug in ("donatello", "tomoe-gozen", "little-red-riding-hood") else set()), slug
