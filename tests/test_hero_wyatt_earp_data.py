"""Wyatt Earp's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 187 of the tournament save (read from the images on 2026-11-13, including the character card 401 on sheet 4), and his deck, the only
one on sheet 187, is told apart from every other deck by its CardIDs and its own images. The transcription of the screenshots in
unmatched-memory (unverified when it was written) agrees with the images card by card: no mismatch. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "wyatt-earp.json"
EFFECTS = HEROES_DIR / "effects" / "wyatt-earp.json"
TTS = HEROES_DIR.parent / "tts" / "wyatt-earp.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
EVERYONE = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye",
            "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "sinbad", "eredin", "ciri", "hellboy", "abe-sapien", "baba-yaga",
            "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards of sheet 187.
REAL_CARDS = {
    "You Just Gonna Stand There And Bleed?": (3, "Wyatt Earp", "attack", 5, 1),
    "Fan The Hammer": (2, "Wyatt Earp", "attack", 1, 3),
    "Second Shot": (2, "any", "attack", 2, 1),
    "I Have Two Guns, One For Each Of You": (3, "Doc Holliday", "attack", 4, 1),
    "A Marshal And An Outlaw": (3, "Wyatt Earp", "versatile", 3, 2),
    "Gunfight At The O.K. Corral": (2, "Wyatt Earp", "versatile", 2, 3),
    "Better Swear Me In": (3, "any", "versatile", 2, 2),
    "I'm Your Huckleberry": (3, "any", "versatile", 3, 2),
    "You're A Daisy If You Do": (2, "Doc Holliday", "versatile", 4, 3),
    "Bring 'Em To Justice": (3, "Wyatt Earp", "defense", 0, 2),
    "You Die First": (2, "Wyatt Earp", "scheme", None, 3),
    "In Vino Veritas": (2, "Doc Holliday", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["You Just Gonna Stand There And Bleed?"] * 3 + ["Fan The Hammer"] * 2 + ["Second Shot"] * 2
               + ["I Have Two Guns, One For Each Of You"] * 3 + ["A Marshal And An Outlaw"] * 3 + ["Gunfight At The O.K. Corral"] * 2
               + ["Better Swear Me In"] * 3 + ["I'm Your Huckleberry"] * 3 + ["You're A Daisy If You Do"] * 2 + ["Bring 'Em To Justice"] * 3
               + ["You Die First"] * 2 + ["In Vino Veritas"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (18700, 187, 401)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "doc", "name": "Doc Holliday"}] and overlay["forms"] is None and overlay["counters"] == {}
    assert overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_ranged_hero_with_doc_holliday_and_deals_a_real_deck():
    h = load_hero("wyatt-earp")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Wyatt Earp", "wyatt", 15, 2, True, 0)
    assert [(s.fid, s.name, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("doc", "Doc Holliday", 8, 2, True)]
    assert h.ability.startswith("SHOWDOWN\nAfter you attack and win combat, choose one effect. You cannot choose the same effect twice in a turn.")
    assert h.counters == {} and h.forms is None
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(18700, 18730))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert {c.title: c.text for c in deck if c.title in ("Better Swear Me In", "Fan The Hammer")} == {
        "Better Swear Me In": "IMMEDIATELY: Cancel all effects on your opponent's card. AFTER COMBAT: Reveal the top card of your opponent's deck. "
                              "You may put it on the bottom of their deck.",
        "Fan The Hammer": "AFTER COMBAT: If the opposing fighter was defeated, return this card to your hand."}


def test_the_herodef_text_of_every_card_is_the_one_in_unmatched_memory():
    """The generator copies the texts of the transcription: the effects file's `text` must say the same, word for word."""
    effects = json.loads(EFFECTS.read_text(encoding="utf-8"))
    deck = {c.title: c for c in load_hero("wyatt-earp").deck()}
    for card in effects["cards"]:
        assert card["text"] == deck[card["title"]].text, card["title"]


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("wyatt-earp").ai_profile
    assert set(profile) == {"wyatt", "doc"} and profile["wyatt"]["role"] == "hero" and profile["wyatt"]["ranged"]
    assert {e["title"] for e in profile["wyatt"]["exclusive"]} == {
        "You Just Gonna Stand There And Bleed?", "Fan The Hammer", "A Marshal And An Outlaw", "Gunfight At The O.K. Corral",
        "Bring 'Em To Justice", "You Die First"}
    assert {e["title"] for e in profile["doc"]["exclusive"]} == {"I Have Two Guns, One For Each Of You", "You're A Daisy If You Do", "In Vino Veritas"}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "wyatt-earp"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert (any(card["effects"].get(m) for m in MOMENTS) or card["title"] in ("You Just Gonna Stand There And Bleed?", "Second Shot")
                or card.get("may_boost")), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert {c["title"] for c in effects["cards"] if c.get("may_boost")} == {"Second Shot"}
    assert {p["id"] for p in effects["plugins"]} == {"wyatt:free_attack", "wyatt:you_die_first", "wyatt:swear_me_in", "wyatt:bring_to_justice"}


def test_showdown_is_an_after_ability_with_three_effects_each_closed_once_a_turn(effects):
    ability = effects["ability"]
    assert ability["passives"] == [] and [t["id"] for t in ability["triggers"]] == ["showdown_reset"]
    assert set(ability["counters"]) == {"showdown_draw", "showdown_attack", "showdown_move"}
    (showdown,) = ability["after"]
    assert showdown["condition"] == {"all": [{"test": "combat_result", "result": "won"}, {"test": "played_as", "side": "attack"}]}
    (choice,) = showdown["ops"]
    assert (choice["op"], choice["amount"], choice["tag"], choice.get("distinct")) == ("choose_effect", 1, "showdown", None)
    assert [o["label"] for o in choice["options"]] == ["Draw 1 card", "Gain 1 free action to attack", "Move your fighter up to 1 space"]
    for option, counter in zip(choice["options"], ("showdown_draw", "showdown_attack", "showdown_move")):
        assert option["condition"] == {"test": "counter", "name": counter, "min": 0, "max": 0}
        assert option["ops"][0] == {"op": "counter", "name": counter, "set": 1}
    assert [o["op"] for t in ability["triggers"] for o in t["ops"]] == ["counter"] * 3


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["You're A Daisy If You Do"]["after"] == [{"op": "draw", "player": "owner", "amount": 2}]
    assert by["Better Swear Me In"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Better Swear Me In"]["after"] == [{"op": "plugin", "id": "wyatt:swear_me_in"}]
    assert by["Bring 'Em To Justice"]["during"] == [{"op": "plugin", "id": "wyatt:bring_to_justice"}]
    assert by["Fan The Hammer"]["after"][0]["then"] == [{"op": "put_in_hand", "cards": "this"}]
    assert by["A Marshal And An Outlaw"]["after"][0]["condition"] == {"test": "played_as", "side": "defense"}
    assert by["A Marshal And An Outlaw"]["after"][0]["then"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by["A Marshal And An Outlaw"]["after"][0]["else"] == [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "opponent"}}]
    assert by["I'm Your Huckleberry"]["after"][0]["condition"] == {"test": "combat_result", "result": "won"}
    assert [(o["op"], o.get("chooser", "owner")) for o in by["Gunfight At The O.K. Corral"]["after"]] == [
        ("damage", "owner"), ("damage", "opponent"), ("damage", "owner"), ("damage", "opponent")]
    assert all(o["amount"] == 1 and o["target"] == {"side": "any"} for o in by["Gunfight At The O.K. Corral"]["after"])
    two_guns = by["I Have Two Guns, One For Each Of You"]["after"][0]["then"][0]
    assert two_guns["target"] == {"side": "enemy", "where": {"zone_of": "this"}, "filter": {"except": "opposing"}}
    assert two_guns["amount"] == {"attr": "value", "of": "opponent_card"}
    assert by["In Vino Veritas"]["scheme"][0] == {"op": "draw", "player": "owner", "amount": {"hand_deficit": 4}}
    assert by["In Vino Veritas"]["scheme"][-1] == {"op": "plugin", "id": "wyatt:free_attack"}
    assert by["You Die First"]["scheme"] == [{"op": "plugin", "id": "wyatt:you_die_first"}]


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "wyatt-earp" and tts["deck"]["card_ids"] == [18700, 18729] and tts["deck"]["character_card_id"] == 401
    assert set(tts["fighters"]) == {"wyatt", "doc"}
    assert (tts["fighters"]["wyatt"]["dial_max"], tts["fighters"]["doc"]["dial_max"]) == (15, 8)
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("cde243", "494e23", "0e4426")
    assert (tts["fighters"]["wyatt"]["piece"], tts["fighters"]["wyatt"]["dial"]) == ("aa2509", "facfe3")
    assert (tts["fighters"]["doc"]["piece"], tts["fighters"]["doc"]["dial"]) == ("3f56bb", "7f71e0")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the card range of his own

def test_his_card_range_is_his_own():
    assert load_hero_table("wyatt-earp").card_ids == (18700, 18729)
    for slug in EVERYONE:
        assert not set(range(18700, 18730)) & set(range(load_hero_table(slug).card_ids[0], load_hero_table(slug).card_ids[1] + 1)), slug


@pytest.mark.parametrize("other", EVERYONE)
def test_wyatt_and_every_other_deck_get_distinct_images(other):
    for bot, human in (("wyatt-earp", other), (other, "wyatt-earp")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]
    assert not set(load_hero("wyatt-earp").deck()) & set(load_hero(other).deck())


def test_wyatt_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("wyatt-earp").deck())
    assert all(c not in set(load_hero("wyatt-earp").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("wyatt-earp", "wyatt-earp")


def test_wyatt_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("wyatt-earp"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("wyatt-earp", other)
        assert detect_heroes(reading(at_bot(other), at_human("wyatt-earp")), BOT_SPOT, HUMAN_SPOT) == (other, "wyatt-earp")


def test_the_catalog_names_wyatt_earp_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("wyatt-earp") == "Wyatt Earp"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("wyatt-earp").identity]).slug == "wyatt-earp"


def test_no_guid_of_wyatt_earp_is_shared_with_another_hero():
    mine = set(load_hero_table("wyatt-earp").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "wyatt-earp"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
