"""John Henry's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 187 of the tournament save (read from the images on 2026-11-13), and with the transcription of unmatched-memory he was first added
from (compared title by title: no difference). His deck is sheet 187, which other Stars and Stripes decks share (Wyatt Earp has the same CardIDs): the decks are told apart by image. No engine, no TTS,
no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, available_heroes, load_hero
from sparring.session_tracks import image_key, token_source
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "john-henry.json"
EFFECTS = HEROES_DIR / "effects" / "john-henry.json"
TTS = HEROES_DIR.parent / "tts" / "john-henry.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
HAMMERS = ["Nine-pound Hammer", "Twelve-pound Hammer", "Eighteen-pound Hammer"]

# (copies, restriction, type, value, boost) as printed on the cards of sheet 187.
REAL_CARDS = {
    "Nine-pound Hammer": (3, "John Henry", "attack", 3, 2),
    "Twelve-pound Hammer": (2, "John Henry", "attack", 4, 2),
    "Eighteen-pound Hammer": (2, "John Henry", "attack", 6, 2),
    "Hear That Cold Steel Ring": (2, "John Henry", "attack", 2, 3),
    "Larger Than Life": (2, "John Henry", "attack", 6, 4),
    "Bring Down The Mountain": (2, "John Henry", "versatile", 3, 1),
    "Knock Them Silly": (3, "John Henry", "versatile", 4, 1),
    "Momentous Shift": (3, "John Henry", "versatile", 3, 1),
    "Power Through": (3, "John Henry", "versatile", 3, 3),
    "Deeds Of Valor": (2, "John Henry", "defense", 2, 2),
    "Cool Drink Of Water": (3, "John Henry", "defense", 0, 2),
    "Striking Fire": (3, "John Henry", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Nine-pound Hammer"] * 3 + ["Twelve-pound Hammer"] * 2 + ["Eighteen-pound Hammer"] * 2 + ["Hear That Cold Steel Ring"] * 2
               + ["Larger Than Life"] * 2 + ["Bring Down The Mountain"] * 2 + ["Knock Them Silly"] * 3 + ["Momentous Shift"] * 3
               + ["Power Through"] * 3 + ["Deeds Of Valor"] * 2 + ["Cool Drink Of Water"] * 3 + ["Striking Fire"] * 3)
# the text of each card as printed on the image (unmatched-memory's transcription says the same)
PRINTED = {
    "Nine-pound Hammer": "AFTER COMBAT: If John Henry used at least 4 different paths this turn, deal 2 damage to each opposing fighter in his zone.",
    "Twelve-pound Hammer": "AFTER COMBAT: If John Henry used at least 4 different paths this turn, you may place a fighter in the combat in any space with a track token.",
    "Eighteen-pound Hammer": "IMMEDIATELY: If John Henry used at least 4 different paths this turn, cancel all effects on your opponent's card.",
    "Hear That Cold Steel Ring": "AFTER COMBAT: Draw 1 card. Move John Henry up to 1 space. Gain 1 free action to attack.",
    "Larger Than Life": "",
    "Bring Down The Mountain": "DURING COMBAT: Add +1 to this card's value for each HAMMER card in your discard pile.",
    "Knock Them Silly": "IMMEDIATELY: If you win this combat, cancel all AFTER COMBAT effects on your opponent's card.",
    "Momentous Shift": "DURING COMBAT: If John Henry started this turn in a different space, this card's value becomes 5.",
    "Power Through": "AFTER COMBAT: Move a fighter in the combat up to 2 spaces. Do not count spaces with track tokens.",
    "Deeds Of Valor": "DURING COMBAT: John Henry cannot take more than 2 combat damage this combat.",
    "Cool Drink Of Water": "AFTER COMBAT: John Henry recovers 3 health. Draw 1 card.",
    "Striking Fire": "Move John Henry up to 4 spaces. Gain 1 action.",
}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_the_transcription_of_unmatched_memory_equals_the_real_cards_when_it_is_there():
    """The HeroDef is generated from unmatched-memory (screenshots) + the overlay; the overlay carries nothing that overrides a figure or a text, so
    what the importer wrote is what unmatched-memory said, and it is what the card images say (compared by hand, 2026-11-13)."""
    for entry in json.loads(OVERLAY.read_text(encoding="utf-8"))["deck"]["sheet"]:
        assert not {"value", "boost", "text", "memory_title"} & set(entry), entry["title"]


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (18700, 187, 403)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert {e["title"] for e in sheet if "hammer" in e.get("tags", ())} == set(HAMMERS)
    assert overlay["fid"] == "john" and overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}
    assert overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_lone_melee_hero_and_deals_a_real_deck():
    h = load_hero("john-henry")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces, h.sidekicks) == ("John Henry", "john", 17, 2, False, 0, ())
    assert h.ability.startswith("STEEL-DRIVING MAN") and "10 track tokens" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(18700, 18730))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
        assert c.text == PRINTED[c.title], c.title
        assert ("hammer" in c.tags) == (c.title in HAMMERS), c.title
    assert sum("hammer" in c.tags for c in deck) == 7


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("john-henry").ai_profile
    assert set(profile) == {"john"} and profile["john"]["role"] == "hero" and not profile["john"]["ranged"]


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "john-henry"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert card["text"] == PRINTED[card["title"]]
        assert (any(card["effects"].get(m) for m in MOMENTS) or card["title"] == "Larger Than Life"), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert {p["id"] for p in effects["plugins"]} == {"john:summon_track", "john:paths"}


def test_the_ability_is_a_start_of_turn_summon_and_a_free_walk_rule(effects):
    ability = effects["ability"]
    assert [(t["id"], t["when"], t["ops"]) for t in ability["triggers"]] == [
        ("steel_driving_man", {"event": "start_of_turn", "player": "owner"}, [{"op": "plugin", "id": "john:summon_track"}])]
    assert ability["passives"] == [{"id": "track_free_move", "kind": "rule", "rule": "track_free_move"}]


def test_the_three_hammers_read_the_same_paths_test_and_nothing_else_does(effects):
    paths = {"test": "plugin", "id": "john:paths", "key": "four"}
    for card in effects["cards"]:
        text = json.dumps(card["effects"])
        assert ("john:paths" in text) == (card["title"] in HAMMERS), card["title"]
        if card["title"] in HAMMERS:
            moment = "immediately" if card["title"] == "Eighteen-pound Hammer" else "after"
            assert card["effects"][moment][0]["condition"] == paths, card["title"]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Eighteen-pound Hammer"]["immediately"][0]["then"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Nine-pound Hammer"]["after"][0]["then"] == [
        {"op": "damage", "target": {"side": "enemy", "where": {"zone_of": "hero"}, "pick": "all"}, "amount": 2}]
    assert by["Twelve-pound Hammer"]["after"][0]["then"] == [
        {"op": "optional", "ops": [{"op": "place", "target": {"role": "combatant"}, "where": {"track": True}}]}]
    assert by["Hear That Cold Steel Ring"]["after"] == [
        {"op": "draw", "player": "owner", "amount": 1}, {"op": "move", "target": {"role": "this"}, "amount": 1, "up_to": True},
        {"op": "gain_action", "amount": 1, "only": "attack"}]
    assert by["Knock Them Silly"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card", "moments": ["after"], "if_won": True}]
    assert by["Power Through"]["after"] == [{"op": "move", "target": {"role": "combatant"}, "amount": 2, "up_to": True, "over_tracks": True}]
    assert by["Bring Down The Mountain"]["during"] == [{"op": "modify_value", "card": "this", "amount": {
        "count_cards": {"zone": "discard", "player": "owner", "filter": {"tag": "hammer"}, "pick": "all"}}}]
    assert by["Deeds Of Valor"]["during"] == [{"op": "cap_combat_damage", "target": "this", "amount": 2}]
    assert by["Cool Drink Of Water"]["after"] == [{"op": "heal", "target": "this", "amount": 3}, {"op": "draw", "player": "owner", "amount": 1}]
    assert by["Striking Fire"]["scheme"] == [{"op": "move", "target": {"role": "this"}, "amount": 4, "up_to": True}, {"op": "gain_action", "amount": 1}]
    assert by["Momentous Shift"]["during"][0]["condition"] == {"test": "moved_this_turn", "fighter": "this"}
    assert by["Momentous Shift"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]


def test_the_cards_other_heroes_print_word_for_word_are_the_same_data(effects):
    mine = {c["title"]: c for c in effects["cards"]}
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "sinbad.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Momentous Shift")
    assert mine["Momentous Shift"]["effects"] == theirs["effects"]       # the words differ a little (his name), the effect is the same data


# ---------------------------------------------------------------- the table data

def test_table_data_names_the_piece_the_dial_the_deck_range_and_the_track_stack():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "john-henry" and tts["deck"]["card_ids"] == [18700, 18729] and tts["deck"]["character_card_id"] == 403
    assert set(tts["fighters"]) == {"john"} and tts["fighters"]["john"]["dial_max"] == 17
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("845f05", "646707", "c3109e")
    assert (tts["fighters"]["john"]["piece"], tts["fighters"]["john"]["dial"]) == ("041a3d", "887823")
    assert tts["tokens"] == {"track": "8ba84f"} and tts["counter_dials"] == {}
    assert token_source() == "8ba84f"


def test_the_track_token_is_found_by_the_picture_it_ends_with():
    key = image_key()
    assert key == "7E9563244F2F4DA4659AA9164EC339BCDC766607" and len(key) == 40
    assert "track" in load_hero_table("john-henry").token_sources


def test_the_character_card_and_the_deck_are_the_hero_of_the_catalog():
    catalog = load_catalog()
    assert catalog.name_of("john-henry") == "John Henry"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("john-henry").identity]).slug == "john-henry"


# ---------------------------------------------------------------- his own card range

def test_a_deck_with_his_card_ids_is_told_apart_by_its_images():
    """Sheet 187 is shared (Wyatt Earp has the same CardIDs 18700-18729, Washington the same key): the range alone never names a card."""
    mine = load_hero_table("john-henry")
    assert mine.card_ids == (18700, 18729)
    overlapping = []
    for slug in available_heroes():
        if slug == "john-henry":
            continue
        lo, hi = load_hero_table(slug).card_ids
        if lo <= 18729 and hi >= 18700:
            overlapping.append(slug)
            assert not set(mine.identity) & set(load_hero_table(slug).identity), slug
    assert "wyatt-earp" in overlapping


def test_no_card_of_john_henry_equals_a_card_of_another_deck_and_none_is_medusas():
    mine = set(load_hero("john-henry").deck())
    for slug in ("medusa", "sinbad", "eredin", "leonardo", "hellboy"):
        assert not mine & set(load_hero(slug).deck()), slug
    assert not any(is_medusa_card(c) for c in load_hero("john-henry").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("john-henry", "john-henry")


@pytest.mark.parametrize("other", ["medusa", "hellboy", "sinbad", "eredin", "yennefer-triss", "bigfoot", "abe-sapien", "houdini"])
def test_john_henry_is_detected_on_either_side_against_other_heroes(other):
    assert detect_heroes(reading(at_bot("john-henry"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("john-henry", other)
    assert detect_heroes(reading(at_bot(other), at_human("john-henry")), BOT_SPOT, HUMAN_SPOT) == (other, "john-henry")


def test_the_only_guid_john_henry_shares_with_another_hero_is_his_dial_with_raphaels():
    """The save gives his life dial ("Hero Health", nicknamed John Henry) the GUID of Raphael's (887823): `session_pieces.resolve_dials` tells
    the two apart by the dial's name when both heroes are on the table (the Lobster / Jackalope and Tomoe Gozen / Donatello case). His bag,
    deck, miniature and track stack are nobody else's."""
    mine = set(load_hero_table("john-henry").all_guids())
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "john-henry"]:
        for guid in mine & set(load_hero_table(slug).all_guids()):
            shared.setdefault(guid, []).append(slug)
    assert shared == {"887823": ["raphael"]}
    assert load_hero_table("john-henry").fighters["john"].dial == "887823"
