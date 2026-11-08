"""Golden Bat's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-08), THE FIRST SUPERHERO is a HeroDef passive the engine
reads, and his deck is told apart from the other nine decks of the range (same CardIDs 17600-17629) by image and owner. No engine,
no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "golden-bat.json"
EFFECTS = HEROES_DIR / "effects" / "golden-bat.json"
TTS = HEROES_DIR.parent / "tts" / "golden-bat.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Super Strength": (2, "Golden Bat", "attack", 5, 1),
    "Vaporizing Eyebeams": (3, "Golden Bat", "attack", 2, 2),
    "A Punch to Shake the Earth": (3, "Golden Bat", "attack", 1, 1),
    "Sight Beyond Sight": (3, "Golden Bat", "versatile", 2, 1),
    "Terrifying Roar": (3, "Golden Bat", "versatile", 3, 1),
    "Skirmish": (2, "Golden Bat", "versatile", 4, 1),
    "Like a Flash of Golden Light": (3, "Golden Bat", "versatile", 2, 2),
    "Insight of the Ancients": (2, "Golden Bat", "versatile", 3, 2),
    "Imposing Presence": (2, "Golden Bat", "defense", 3, 2),
    "He Laughs at Your Feebleness": (2, "Golden Bat", "defense", 5, 3),
    "Arrive Just in Time": (2, "Golden Bat", "scheme", None, 2),
    "Alpine Fortress": (3, "Golden Bat", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Super Strength"] * 2 + ["Vaporizing Eyebeams"] * 3 + ["A Punch to Shake the Earth"] * 3 + ["Sight Beyond Sight"] * 3
               + ["Terrifying Roar"] * 3 + ["Skirmish"] * 2 + ["Like a Flash of Golden Light"] * 3 + ["Insight of the Ancients"] * 2
               + ["Imposing Presence"] * 2 + ["He Laughs at Your Feebleness"] * 2 + ["Arrive Just in Time"] * 2 + ["Alpine Fortress"] * 3)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 345)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == []
    assert overlay["passives"] == [{"id": "THE FIRST SUPERHERO", "effect": "attack_bonus", "n": 2, "fighter": "hero", "unless": "maneuver"}]


def test_generated_herodef_is_a_melee_hero_with_18_life_and_deals_a_real_deck():
    h = load_hero("golden-bat")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Golden Bat", "bat", 18, 3, False, 0)
    assert h.sidekicks == () and [f.fid for f in h.fighters()] == ["bat"]
    assert h.ability.startswith("THE FIRST SUPERHERO") and "Maneuver action" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    by = {c.title: c.text for c in deck}
    assert by["A Punch to Shake the Earth"] == ("AFTER COMBAT: Deal 1 damage to each opposing fighter in your zone. "
                                                "If you won the combat, deal 2 damage instead.")           # the card, not unmatched-memory
    assert by["Skirmish"] == "AFTER COMBAT: If you won the combat, move one of the fighters in the combat up to 2 spaces."
    assert by["Like a Flash of Golden Light"].startswith("DURING COMBAT: If Golden Bat shares no zones") and "AFTER COMBAT: Move Golden Bat up to 5 spaces." in by["Like a Flash of Golden Light"]
    assert by["Alpine Fortress"] == "Choose a card in your discard pile and shuffle it into your deck. Draw 2 cards. Move Golden Bat up to 4 spaces."


def test_the_passive_is_off_after_a_maneuver_and_only_for_the_hero():
    h = load_hero("golden-bat")
    assert h.attack_bonuses(None, True) == [(2, "THE FIRST SUPERHERO")] and h.attack_bonus(None, True) == 2
    assert h.attack_bonuses(None, True, maneuvered=True) == [] and h.attack_bonus(None, True, True) == 0
    assert h.attack_bonuses(None, False) == []
    assert all(load_hero(s).attack_bonus(None, True) == 0 for s in ("medusa", "bullseye", "luke-cage", "doctor-strange"))


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("golden-bat").ai_profile
    assert set(profile) == {"bat"} and profile["bat"]["role"] == "hero" and not profile["bat"]["ranged"]
    assert {e["title"] for e in profile["bat"]["exclusive"]} == set(REAL_CARDS)


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "golden-bat"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        has_ops = any(card["effects"].get(m) for m in MOMENTS)
        assert has_ops or card["title"] in ("Super Strength", "He Laughs at Your Feebleness"), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert effects["plugins"] == [] and effects["ability"]["triggers"] == []


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    won = {"test": "combat_result", "result": "won"}
    zone = {"side": "enemy", "where": {"zone_of": "this"}, "pick": "all"}
    assert by["Vaporizing Eyebeams"]["after"] == [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}}]
    assert by["A Punch to Shake the Earth"]["after"] == [{"op": "if", "condition": won, "then": [{"op": "damage", "target": zone, "amount": 2}],
                                                          "else": [{"op": "damage", "target": zone, "amount": 1}]}]
    assert by["Sight Beyond Sight"]["after"] == [{"op": "search_deck", "player": "opponent", "look": 3, "take": {"amount": 0}, "to": "hand",
                                                  "rest": "top_ordered", "chooser": "owner"}]
    assert by["Terrifying Roar"]["immediately"] == [{"op": "status", "name": "cannot_leave_space", "target": {"side": "any", "pick": "all"},
                                                     "until": {"event": "end_of_turn"}}]
    assert by["Skirmish"]["after"] == [{"op": "if", "condition": won, "then": [{"op": "move", "target": "combatant", "amount": 2, "up_to": True, "chooser": "owner"}]}]
    assert by["Like a Flash of Golden Light"]["during"] == [{"op": "if", "condition": {"test": "no_zone_with_turn_start", "fighter": "this"},
                                                             "then": [{"op": "set_value", "card": "this", "amount": 4}]}]
    assert by["Like a Flash of Golden Light"]["after"] == [{"op": "move", "target": "hero", "amount": 5, "up_to": True, "chooser": "owner"}]
    assert by["Insight of the Ancients"]["after"] == [{"op": "if", "condition": won, "then": [
        {"op": "put_in_hand", "cards": {"zone": "discard", "player": "owner", "pick": "random", "amount": 1}}]}]
    assert by["Imposing Presence"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Arrive Just in Time"]["scheme"] == [{"op": "place", "target": "hero", "where": {"any": True}, "chooser": "owner"}]
    assert by["Alpine Fortress"]["scheme"] == [
        {"op": "return_to_deck", "cards": {"zone": "discard", "player": "owner", "amount": 1, "chooser": "owner"}, "position": "shuffle"},
        {"op": "draw", "player": "owner", "amount": 2},
        {"op": "move", "target": "hero", "amount": 4, "up_to": True, "chooser": "owner"}]
    assert not any(by[t][m] for t in ("Super Strength", "He Laughs at Your Feebleness") for m in MOMENTS)


def test_the_ability_passive_documents_the_data_rule(effects):
    passive, = effects["ability"]["passives"]
    assert passive["kind"] == "modify_value" and passive["amount"] == 2
    assert passive["while"] == {"test": "compare", "left": {"stat": "maneuvers_this_turn", "player": "owner"}, "op": "==", "right": 0}


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "golden-bat" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 345
    assert set(tts["fighters"]) == {"bat"} and tts["fighters"]["bat"]["dial_max"] == 18
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["bat"]["piece"], tts["fighters"]["bat"]["dial"]) == (
        "4732a0", "29a029", "b0ebcc", "0f46cb")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_golden_bat_shares_the_card_range_but_not_the_images_with_the_other_decks_of_sheet_176(other):
    bat, theirs = load_hero_table("golden-bat"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert bat.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(bat.identity) & set(theirs.identity)
    for bot, human in (("golden-bat", other), (other, "golden-bat")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_golden_bat_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("golden-bat").deck()) & set(load_hero(other).deck())


def test_golden_bat_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("golden-bat").deck())
    assert all(c not in set(load_hero("golden-bat").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("golden-bat", "golden-bat")


def test_golden_bat_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("golden-bat"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("golden-bat", other)
        assert detect_heroes(reading(at_bot(other), at_human("golden-bat")), BOT_SPOT, HUMAN_SPOT) == (other, "golden-bat")


def test_the_catalog_names_golden_bat_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("golden-bat") == "Golden Bat"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("golden-bat").identity]).slug == "golden-bat"


def test_no_piece_guid_of_golden_bat_is_shared_with_another_hero():
    mine = set(load_hero_table("golden-bat").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "golden-bat"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
