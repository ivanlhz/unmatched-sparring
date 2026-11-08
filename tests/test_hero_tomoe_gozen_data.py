"""Tomoe Gozen's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-08), and her deck is told apart from the other nine decks of
the sheet (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "tomoe-gozen.json"
EFFECTS = HEROES_DIR / "effects" / "tomoe-gozen.json"
TTS = HEROES_DIR.parent / "tts" / "tomoe-gozen.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Witness My Last Battle": (2, "Tomoe Gozen", "attack", 7, 4),
    "Piercing Shot": (3, "Tomoe Gozen", "attack", 2, 1),
    "A Warrior's Way": (2, "Tomoe Gozen", "attack", 2, 1),
    "Five Against Thousands": (2, "Tomoe Gozen", "attack", 4, 1),
    "Fearsome Strength": (2, "Tomoe Gozen", "attack", 3, 1),
    "A Worthy Opponent": (3, "Tomoe Gozen", "versatile", 3, 3),
    "Confront Any Demon or God": (2, "Tomoe Gozen", "versatile", 3, 3),
    "Skirmish": (3, "Tomoe Gozen", "versatile", 4, 1),
    "Flash of Steel": (3, "Tomoe Gozen", "versatile", 2, 1),
    "Refuse to Retreat": (2, "Tomoe Gozen", "defense", 3, 2),
    "Deeds of Valor": (3, "Tomoe Gozen", "defense", 2, 2),
    "Lord Kiso's Final Stand": (3, "Tomoe Gozen", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Witness My Last Battle"] * 2 + ["Piercing Shot"] * 3 + ["A Warrior's Way"] * 2 + ["Five Against Thousands"] * 2
               + ["Fearsome Strength"] * 2 + ["A Worthy Opponent"] * 3 + ["Confront Any Demon or God"] * 2 + ["Skirmish"] * 3
               + ["Flash of Steel"] * 3 + ["Refuse to Retreat"] * 2 + ["Deeds of Valor"] * 3 + ["Lord Kiso's Final Stand"] * 3)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 354)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}
    assert overlay["triggers"] == [] and overlay["passives"] == [] and "reach_spaces" not in overlay


def test_generated_herodef_is_a_ranged_hero_without_sidekicks_and_deals_a_real_deck():
    h = load_hero("tomoe-gozen")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Tomoe Gozen", "tomoe", 14, 2, True, 0)
    assert h.sidekicks == () and [f.fid for f in h.fighters()] == ["tomoe"]
    assert h.ability == ("ATTACK OF OPPORTUNITY\nWhen an opposing hero leaves Tomoe Gozen's zone, deal 1 damage to that hero.")      # no flavour quote
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert next(c for c in deck if c.title == "Witness My Last Battle").text == (
        "This attack can only target a fighter adjacent to Tomoe Gozen. Play it face up. AFTER COMBAT: End the turn.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("tomoe-gozen").ai_profile
    assert set(profile) == {"tomoe"} and profile["tomoe"]["role"] == "hero" and profile["tomoe"]["ranged"]
    assert {e["title"] for e in profile["tomoe"]["exclusive"]} == set(REAL_CARDS)


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "tomoe-gozen"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert effects["plugins"] == [] and effects["ability"]["passives"] == []


def test_the_ability_is_one_left_zone_trigger_that_hurts_the_hero_that_left(effects):
    trigger, = effects["ability"]["triggers"]
    assert trigger["when"] == {"event": "left_zone", "fighter": {"side": "enemy", "kind": "hero"}}
    assert trigger["ops"] == [{"op": "damage", "target": "$fighter", "amount": 1}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Witness My Last Battle"]["after"] == [{"op": "end_turn"}]
    assert by["Piercing Shot"]["after"] == [{"op": "draw", "player": "owner", "amount": 2}]
    assert by["Deeds of Valor"]["during"] == [{"op": "cap_combat_damage", "target": "this", "amount": 2}]
    assert by["Lord Kiso's Final Stand"]["scheme"][0] == {"op": "move", "target": "hero", "amount": 3, "up_to": True, "through_sidekicks": True, "chooser": "owner"}
    assert [o["label"] for o in by["Lord Kiso's Final Stand"]["scheme"][1]["options"]] == ["Tomoe Gozen recovers 2 health", "Gain 1 action"]
    assert by["Refuse to Retreat"]["immediately"] == [{"op": "status", "name": "cannot_leave_space", "target": "this", "until": {"event": "end_of_turn"}}]
    assert by["A Worthy Opponent"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]
    assert by["Flash of Steel"]["immediately"][0]["then"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    five, = by["Five Against Thousands"]["after"]
    assert five["then"][0]["ops"] == [{"op": "put_in_hand", "cards": "this"}]
    assert five["then"][0]["cost"] == [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 1, "chooser": "owner"}}]


def test_witness_my_last_battle_is_the_only_adjacent_only_face_up_card(effects):
    assert [c["title"] for c in effects["cards"] if c.get("adjacent_only")] == ["Witness My Last Battle"]
    assert [c["title"] for c in effects["cards"] if c.get("face_up")] == ["Witness My Last Battle"]


def test_two_cards_are_word_for_word_the_ones_of_hellboy_and_bigfoot(effects):
    mine = {c["title"]: c for c in effects["cards"]}
    for slug, title in (("hellboy", "Confront Any Demon or God"), ("bigfoot", "Skirmish")):
        theirs = next(c for c in json.loads((HEROES_DIR / "effects" / f"{slug}.json").read_text(encoding="utf-8"))["cards"] if c["title"] == title)
        assert mine[title]["text"] == theirs["text"] and mine[title]["effects"] == theirs["effects"], title


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "tomoe-gozen" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 354
    assert set(tts["fighters"]) == {"tomoe"} and tts["fighters"]["tomoe"]["dial_max"] == 14
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["tomoe"]["piece"], tts["fighters"]["tomoe"]["dial"]) == (
        "c5fe82", "abfd59", "66c85f", "ca8e35")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_tomoe_gozen_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    tomoe, theirs = load_hero_table("tomoe-gozen"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert tomoe.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(tomoe.identity) & set(theirs.identity)
    for bot, human in (("tomoe-gozen", other), (other, "tomoe-gozen")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_tomoe_gozen_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("tomoe-gozen").deck()) & set(load_hero(other).deck())


def test_tomoe_gozen_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero("tomoe-gozen").deck())
    assert all(c not in set(load_hero("tomoe-gozen").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("tomoe-gozen", "tomoe-gozen")


def test_tomoe_gozen_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("tomoe-gozen"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("tomoe-gozen", other)
        assert detect_heroes(reading(at_bot(other), at_human("tomoe-gozen")), BOT_SPOT, HUMAN_SPOT) == (other, "tomoe-gozen")


def test_the_catalog_names_tomoe_gozen_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("tomoe-gozen") == "Tomoe Gozen"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("tomoe-gozen").identity]).slug == "tomoe-gozen"


def test_the_only_guid_tomoe_gozen_shares_with_another_hero_is_her_dial_with_donatellos():
    """The save gives her life dial the GUID of Donatello's (ca8e35, also Chupacabra's and Little Red's): `session_pieces.resolve_dials`
    tells the two apart by the dial's name when both heroes are on the table (the Lobster / Jackalope case). Her bag, deck and
    miniature are nobody else's."""
    mine = set(load_hero_table("tomoe-gozen").all_guids())
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "tomoe-gozen"]:
        for guid in mine & set(load_hero_table(slug).all_guids()):
            shared.setdefault(guid, []).append(slug)
    assert shared == {"ca8e35": ["donatello"]}
    assert load_hero_table("tomoe-gozen").fighters["tomoe"].dial == "ca8e35"
