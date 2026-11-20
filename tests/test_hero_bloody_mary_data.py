"""Bloody Mary's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards
of sheet 176 of the tournament save (read from the images on 2026-11-20), her ability is a start-of-turn trigger of the effects file, and her
deck is told apart from the other decks of the range (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "bloody-mary.json"
EFFECTS = HEROES_DIR / "effects" / "bloody-mary.json"
TTS = HEROES_DIR.parent / "tts" / "bloody-mary.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat",
           "jill-trent", "she-hulk", "tomoe-gozen", "yennefer-triss", "sinbad", "chupacabra", "eredin", "ciri", "philippa", "raptors", "rosie-the-riveter"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini", "wyatt-earp", "john-henry", "george-washington"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Speak Three Times": (2, "Bloody Mary", "attack", 3, 2),
    "Bloody Requiem": (3, "Bloody Mary", "attack", 3, 4),
    "Out Of The Mirror": (2, "Bloody Mary", "attack", 1, 2),
    "Ghostly Touch": (2, "Bloody Mary", "attack", 1, 2),
    "Feint": (2, "Bloody Mary", "versatile", 2, 2),
    "Jump Scare": (2, "Bloody Mary", "versatile", 3, 2),
    "Infinity Mirror": (2, "Bloody Mary", "versatile", 4, 2),
    "Broken Glass": (3, "Bloody Mary", "versatile", 3, 2),
    "Trick of the Light": (3, "Bloody Mary", "versatile", 2, 3),
    "Evade": (3, "Bloody Mary", "defense", 3, 1),
    "Mirror Image": (2, "Bloody Mary", "defense", 0, 2),
    "Closer Than She Appears": (2, "Bloody Mary", "scheme", None, 2),
    "Stolen Memories": (2, "Bloody Mary", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Speak Three Times"] * 2 + ["Bloody Requiem"] * 3 + ["Out Of The Mirror"] * 2 + ["Ghostly Touch"] * 2 + ["Feint"] * 2
               + ["Jump Scare"] * 2 + ["Infinity Mirror"] * 2 + ["Broken Glass"] * 3 + ["Trick of the Light"] * 3 + ["Evade"] * 3
               + ["Mirror Image"] * 2 + ["Closer Than She Appears"] * 2 + ["Stolen Memories"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 321)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}


def test_generated_herodef_is_a_melee_hero_with_16_life_and_no_sidekick_and_deals_a_real_deck():
    h = load_hero("bloody-mary")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Bloody Mary", "mary", 16, 3, False, 0)
    assert h.sidekicks == () and [f.fid for f in h.fighters()] == ["mary"], "the 'Patroclus' of unmatched-memory is a slip"
    assert h.ability == "At the start of your turn, if you have exactly 3 cards in hand, gain 1 action."
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    by = {c.title: c.text for c in deck}
    assert by["Closer Than She Appears"] == "Move Bloody Mary up to 1 space. Draw 1 card. Gain 1 action."          # the card, not unmatched-memory
    assert by["Speak Three Times"] == "DURING COMBAT: If this is your third action this turn, this card's value is 7 instead."
    assert by["Bloody Requiem"].startswith("AFTER COMBAT: BLOODY REPRISE: 0 ATK")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("bloody-mary").ai_profile
    assert set(profile) == {"mary"} and profile["mary"]["role"] == "hero" and not profile["mary"]["ranged"]
    assert {e["title"] for e in profile["mary"]["exclusive"]} == set(REAL_CARDS)


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "bloody-mary"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert [p["id"] for p in effects["plugins"]] == ["mary:out_of_the_mirror"]


def test_the_ability_is_a_start_of_turn_trigger_that_gains_one_action_with_exactly_three_cards(effects):
    trigger, = effects["ability"]["triggers"]
    assert trigger["when"] == {"event": "start_of_turn", "player": "owner"}
    assert trigger["condition"] == {"test": "compare", "left": {"stat": "hand_size", "player": "owner"}, "op": "==", "right": 3}
    assert trigger["ops"] == [{"op": "gain_action", "amount": 1}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    third = {"test": "compare", "left": {"stat": "actions_taken_this_turn", "player": "owner"}, "op": "==", "right": 3}
    assert by["Speak Three Times"]["during"] == [{"op": "if", "condition": third, "then": [{"op": "set_value", "card": "this", "amount": 7}]}]
    assert by["Out Of The Mirror"]["after"] == [{"op": "if", "condition": third, "then": [{"op": "draw", "player": "owner", "amount": 1}]}]
    assert by["Out Of The Mirror"]["during"] == [{"op": "plugin", "id": "mary:out_of_the_mirror"}]
    assert by["Ghostly Touch"]["after"] == [{"op": "if", "condition": third, "then": [{"op": "heal", "target": "hero", "amount": 3}]}]
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Jump Scare"]["during"] == [{"op": "if", "condition": {"test": "no_zone_with_turn_start", "fighter": "this"},
                                           "then": [{"op": "set_value", "card": "this", "amount": 6}]}]
    assert by["Mirror Image"]["during"] == [{"op": "set_value", "card": "this", "amount": {"attr": "value", "of": "opponent_card"}}]
    assert by["Infinity Mirror"]["after"] == [{"op": "move", "target": "combatant", "amount": 4, "up_to": True, "chooser": "owner"}]
    assert by["Evade"]["after"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by["Closer Than She Appears"]["scheme"] == [{"op": "move", "target": "hero", "amount": 1, "up_to": True, "chooser": "owner"},
                                                       {"op": "draw", "player": "owner", "amount": 1}, {"op": "gain_action", "amount": 1}]
    assert by["Bloody Requiem"]["after"] == [{"op": "second_attack", "amount": {"attr": "value", "of": "opponent_card"}}]
    glass = by["Broken Glass"]
    assert [o["label"] for o in glass["during"][0]["options"]] == ["+1", "-1", "0"]
    assert glass["after"][0]["then"] == [{"op": "draw", "player": "owner", "amount": 1}, {"op": "damage", "target": "opposing", "amount": 2}]
    memories = by["Stolen Memories"]["scheme"]
    assert memories[0] == {"op": "look_hand", "player": "opponent"}
    assert memories[1]["then"][1]["else"] == [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": {"attr": "boost", "of": "$memory"}}]


def test_ghostly_touch_is_the_only_card_that_may_boost_for_free(effects):
    assert [c["title"] for c in effects["cards"] if c.get("may_boost")] == ["Ghostly Touch"]


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "bloody-mary" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 321
    assert set(tts["fighters"]) == {"mary"} and tts["fighters"]["mary"]["dial_max"] == 16
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["mary"]["piece"], tts["fighters"]["mary"]["dial"]) == (
        "a3a6c6", "48a6aa", "98d2b5", "51c4a7")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_bloody_mary_shares_the_card_range_but_not_the_images_with_the_other_decks_of_sheet_176(other):
    mary, theirs = load_hero_table("bloody-mary"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert mary.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(mary.identity) & set(theirs.identity)
    for bot, human in (("bloody-mary", other), (other, "bloody-mary")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_bloody_mary_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("bloody-mary").deck()) & set(load_hero(other).deck())


def test_bloody_mary_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero("bloody-mary").deck())
    assert all(c not in set(load_hero("bloody-mary").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("bloody-mary", "bloody-mary")


def test_bloody_mary_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("bloody-mary"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("bloody-mary", other)
        assert detect_heroes(reading(at_bot(other), at_human("bloody-mary")), BOT_SPOT, HUMAN_SPOT) == (other, "bloody-mary")


def test_the_catalog_names_bloody_mary_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("bloody-mary") == "Bloody Mary"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("bloody-mary").identity]).slug == "bloody-mary"


def test_no_piece_guid_of_bloody_mary_is_shared_with_another_hero():
    mine = set(load_hero_table("bloody-mary").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "bloody-mary"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
