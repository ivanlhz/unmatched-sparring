"""Bigfoot's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the
real cards of sheet 176 of the tournament save (read from the images on 2026-11-03), and his deck is told apart from Medusa's,
the four turtles' and Doctor Strange's (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "bigfoot.json"
EFFECTS = HEROES_DIR / "effects" / "bigfoot.json"
TTS = HEROES_DIR.parent / "tts" / "bigfoot.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Larger Than Life": (3, "Bigfoot", "attack", 6, 3),
    "Savagery": (3, "Bigfoot", "attack", 4, 3),
    "Disengage": (2, "any", "attack", 4, 2),
    "Momentous Shift": (3, "any", "versatile", 3, 1),
    "Skirmish": (3, "any", "versatile", 4, 1),
    "Hoax": (3, "any", "versatile", 4, 2),
    "Regroup": (3, "any", "versatile", 1, 2),
    "Feint": (3, "any", "versatile", 2, 2),
    "It's Just Your Imagination": (2, "any", "defense", 3, 3),
    "Crash Through the Trees": (2, "Bigfoot", "scheme", None, 3),
    "Jackalope Horns": (3, "The Jackalope", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Larger Than Life"] * 3 + ["Savagery"] * 3 + ["Disengage"] * 2 + ["Momentous Shift"] * 3 + ["Skirmish"] * 3
               + ["Hoax"] * 3 + ["Regroup"] * 3 + ["Feint"] * 3 + ["It's Just Your Imagination"] * 2
               + ["Crash Through the Trees"] * 2 + ["Jackalope Horns"] * 3)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 309)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"][0]["fid"] == "jackalope" and overlay["sidekicks"][0]["name"] == "The Jackalope"
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("bigfoot")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Bigfoot", "bigfoot", 16, 3, False)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("jackalope", "The Jackalope", 1, 6, 3, False)]
    assert h.ability == "At the end of your turn, if there are no opposing fighters in Bigfoot's zone, you may draw 1 card."
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert sum(1 for c in deck if c.fighter == "The Jackalope") == 3
    assert next(c for c in deck if c.title == "Skirmish").text.startswith("AFTER COMBAT: If you won the combat")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("bigfoot").ai_profile
    assert profile["bigfoot"]["role"] == "hero" and profile["jackalope"]["role"] == "striker"
    assert {e["title"] for e in profile["bigfoot"]["exclusive"]} == {"Larger Than Life", "Savagery", "Crash Through the Trees"}
    assert {e["title"] for e in profile["jackalope"]["exclusive"]} == {"Jackalope Horns"}
    horns = profile["jackalope"]["exclusive"][0]
    assert horns["impact"] >= 2.0                    # a scheme that deals 2 damage: killing the Jackalope early is worth it


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "bigfoot"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        if card["title"] != "Larger Than Life":                   # a plain attack: no text, no effect
            assert any(card["effects"][m] for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert effects["plugins"] == []


def test_the_ability_is_an_end_of_turn_trigger_that_needs_no_opposing_fighter_in_bigfoots_zone(effects):
    trig, = effects["ability"]["triggers"]
    assert trig["id"] == "bigfoot_draw"
    assert trig["when"] == {"event": "end_of_turn", "player": "owner"}
    assert trig["condition"] == {"not": {"test": "exists", "fighters": {"side": "enemy", "where": {"zone_of": "hero"}}}}
    optional, = trig["ops"]
    assert optional["op"] == "optional" and optional["chooser"] == "owner"
    assert optional["ops"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert effects["ability"]["passives"] == []


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Feint"]["immediately"] == by["It's Just Your Imagination"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Savagery"]["after"][0]["condition"] == {"test": "combat_result", "result": "won"}
    assert by["Savagery"]["after"][0]["then"] == [{"op": "damage", "target": {"side": "any", "where": {"adjacent_to": "hero"}, "pick": "all"}, "amount": 1}]
    assert by["Momentous Shift"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]
    assert by["Hoax"]["after"] == [{"op": "move", "target": "this", "amount": 5, "up_to": True, "through_enemies": True, "chooser": "owner"}]
    assert by["Crash Through the Trees"]["scheme"] == [{"op": "move", "target": "hero", "amount": 5, "up_to": True, "through_enemies": True, "chooser": "owner"}]
    assert [o["op"] for o in by["Jackalope Horns"]["scheme"]] == ["move", "damage"]
    assert by["Jackalope Horns"]["scheme"][1]["amount"] == 2
    regroup, = by["Regroup"]["after"]
    assert regroup["then"][0]["amount"] == 2 and regroup["else"][0]["amount"] == 1
    assert by["Skirmish"]["after"][0]["then"][0]["amount"] == 2 and not by["Skirmish"]["after"][0]["then"][0].get("through_enemies")


def test_table_data_names_both_pieces_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "bigfoot" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 309
    assert set(tts["fighters"]) == {"bigfoot", "jackalope"}
    assert (tts["fighters"]["bigfoot"]["dial_max"], tts["fighters"]["jackalope"]["dial_max"]) == (16, 6)
    assert tts["fighters"]["jackalope"]["nickname"] == "Jackalope"         # the token of the save is called Jackalope, the dial The Jackalope
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_bigfoot_shares_the_card_range_but_not_the_images_with_medusa_the_turtles_and_strange(other):
    bigfoot, theirs = load_hero_table("bigfoot"), load_hero_table(other)
    assert bigfoot.card_ids == theirs.card_ids == (17600, 17629)
    assert not set(bigfoot.identity) & set(theirs.identity)
    for bot, human in (("bigfoot", other), (other, "bigfoot")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == defaults["human_card_ids"] == [17600, 17629]
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_bigfoot_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("bigfoot").deck()) & set(load_hero(other).deck())


def test_bigfoot_cards_are_never_medusas_and_medusas_never_bigfoots():
    assert not any(is_medusa_card(c) for c in load_hero("bigfoot").deck())
    assert all(c not in set(load_hero("bigfoot").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("bigfoot", "bigfoot")


def test_bigfoot_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("bigfoot"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("bigfoot", other)
        assert detect_heroes(reading(at_bot(other), at_human("bigfoot")), BOT_SPOT, HUMAN_SPOT) == (other, "bigfoot")


def test_the_catalog_names_bigfoot_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("bigfoot") == "Bigfoot"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("bigfoot").identity]).slug == "bigfoot"


def test_the_only_piece_guid_bigfoot_shares_is_the_jackalope_dial_with_lobster_johnson():
    """The save gives The Jackalope's life dial the GUID 18c384, which is also Lobster Johnson's (Hellboy's bag); the same kind of
    collision as Abe Sapien's and Donatello's miniature (tests/test_piece_identity.py, docs/heroes/bigfoot.md)."""
    mine = set(load_hero_table("bigfoot").all_guids())
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "bigfoot"]:
        for g in mine & set(load_hero_table(slug).all_guids()):
            shared.setdefault(g, []).append(slug)
    assert shared == {"18c384": ["hellboy"]}
