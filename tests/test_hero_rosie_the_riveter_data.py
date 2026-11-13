"""Rosie the Riveter's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-13), and her deck is told apart from the other decks of the
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

SLUG = "rosie-the-riveter"
OVERLAY = HEROES_DIR / "overlay" / f"{SLUG}.json"
EFFECTS = HEROES_DIR / "effects" / f"{SLUG}.json"
TTS = HEROES_DIR.parent / "tts" / f"{SLUG}.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "yennefer-triss", "sinbad", "eredin", "ciri"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
ROSIE, WENDY = "Rosie The Riveter", "Wendy The Welder"

# (copies, restriction, type, value, boost) as printed on the cards, checked one by one against the images of sheet 176.
REAL_CARDS = {
    "We Can Do It!": (2, ROSIE, "attack", 4, 2),
    "D-Day": (3, ROSIE, "attack", 3, 1),
    "Overrun": (3, ROSIE, "attack", 3, 1),
    "Full Metal": (3, ROSIE, "versatile", 1, 3),
    "Momentous Shift": (3, "any", "versatile", 3, 1),
    "Loose Lips Sink Ships!": (3, "any", "versatile", 2, 2),
    "Technological Superiority": (3, "any", "versatile", 3, 2),
    "Arc Welding": (3, WENDY, "versatile", 3, 3),
    "Hasty Repairs": (3, ROSIE, "defense", 1, 2),
    "Rapid Development": (2, WENDY, "scheme", None, 3),
    '"E" Award': (2, WENDY, "scheme", None, 3),
}
# idx order of the sheet, as read from the image (it is not the order of unmatched-memory's transcription)
SHEET_ORDER = (["We Can Do It!"] * 2 + ["D-Day"] * 3 + ["Overrun"] * 3 + ["Full Metal"] * 3 + ["Momentous Shift"] * 3 + ["Loose Lips Sink Ships!"] * 3
               + ["Technological Superiority"] * 3 + ["Arc Welding"] * 3 + ["Hasty Repairs"] * 3 + ["Rapid Development"] * 2 + ['"E" Award'] * 2)
UPGRADES = [("merlin_engine", "Merlin Engine", {"maneuver_move": 1}), ("cavity_magnetron", "Cavity Magnetron", {"draw_after_attack": 1}),
            ("sedgley_fist_gun", "Sedgley Fist Gun", {"attack_bonus": 1}), ("whizbang", "Whizbang", {"ranged": True})]


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 402)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["fid"] == "rosie" and overlay["counters"] == {} and overlay["forms"] is None and overlay["triggers"] == []
    assert overlay["sidekicks"] == [{"fid": "wendy", "name": WENDY, "attack": "melee"}]       # her attack is blank in unmatched-memory; the hero card says MELEE


def test_the_upgrade_row_is_data_in_the_overlay_passive(overlay):
    (passive,) = overlay["passives"]
    assert passive["effect"] == "upgrades" and passive["id"] == "freedom_xk_ii"
    assert [(u["id"], u["name"], u["grants"]) for u in passive["row"]] == UPGRADES
    assert overlay["token_names"] == {"d670b6": "merlin_engine", "e5ef35": "cavity_magnetron", "85c49f": "sedgley_fist_gun", "f45e71": "whizbang"}


def test_generated_herodef_is_a_melee_hero_with_wendy_and_deals_a_real_deck():
    h = load_hero(SLUG)
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == (ROSIE, "rosie", 15, 2, False, 0)
    assert [(s.fid, s.name, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("wendy", WENDY, 7, 2, False)]
    assert h.ability.startswith("FREEDOM XK-II MECH SUIT\nYou have 4 upgrade tokens.") and h.counters == {} and h.forms is None
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    texts = {c.title: c.text for c in deck}
    assert texts["We Can Do It!"] == "IMMEDIATELY: Activate an upgrade."
    assert texts["Full Metal"] == "DURING COMBAT: Add +1 to this card's value for each active upgrade."
    assert texts["Technological Superiority"] == "IMMEDIATELY: If you have 3 or more active upgrades, cancel all effects on your opponent's card."
    assert texts["Hasty Repairs"] == "AFTER COMBAT: If you have any active upgrades, deactivate one, and Rosie recovers 3 health."
    assert texts['"E" Award'] == "Activate or deactivate an upgrade. Move each of your fighters up to 3 spaces."
    assert texts["Rapid Development"] == "Draw 2 cards. Activate or deactivate an upgrade. Gain 1 free action to attack."


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero(SLUG).ai_profile
    assert set(profile) == {"rosie", "wendy"} and profile["rosie"]["role"] == "hero" and not profile["rosie"]["ranged"]
    assert {e["title"] for e in profile["rosie"]["exclusive"]} == {"We Can Do It!", "D-Day", "Overrun", "Full Metal", "Hasty Repairs"}
    assert {e["title"] for e in profile["wendy"]["exclusive"]} == {"Arc Welding", "Rapid Development", '"E" Award'}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == SLUG
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert sorted(p["id"] for p in effects["plugins"]) == ["rosie:attack_bonus", "rosie:deactivate", "rosie:loose_lips", "rosie:upgrade"]


def test_the_ability_is_two_counters_two_triggers_cavity_magnetron_and_the_sedgley_during(effects):
    ability = effects["ability"]
    (during,) = ability["during"]
    assert during["id"] == "sedgley_fist_gun" and during["ops"] == [{"op": "plugin", "id": "rosie:attack_bonus"}]
    assert {"test": "plugin", "id": "rosie:upgrade", "key": "sedgley_fist_gun"} in during["condition"]["all"]
    assert {"test": "played_as", "side": "attack"} in during["condition"]["all"]
    assert ability["counters"] == {"upgrades": {"min": 0, "max": 4, "start": 0}, "upgrade_shift": {"min": 0, "max": 3, "start": 0}}
    triggers = {t["id"]: t for t in ability["triggers"]}
    assert set(triggers) == {"activate_at_start", "reset_at_end", "cavity_magnetron"}
    assert triggers["activate_at_start"]["when"] == {"event": "start_of_turn", "player": "owner"}
    assert triggers["activate_at_start"]["ops"] == [{"op": "counter", "name": "upgrades", "delta": 1}]
    assert triggers["reset_at_end"]["when"] == {"event": "end_of_turn", "player": "owner"}
    assert triggers["reset_at_end"]["condition"] == {"test": "counter", "name": "upgrades", "min": 4}
    assert triggers["reset_at_end"]["ops"] == [{"op": "counter", "name": "upgrades", "set": 0}]
    assert triggers["cavity_magnetron"]["when"] == {"event": "after_attack", "fighter": {"side": "own", "kind": "hero"}}
    assert triggers["cavity_magnetron"]["condition"] == {"test": "plugin", "id": "rosie:upgrade", "key": "cavity_magnetron"}
    assert triggers["cavity_magnetron"]["ops"] == [{"op": "optional", "ops": [{"op": "draw", "player": "owner", "amount": 1}]}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    up = {"op": "counter", "name": "upgrades", "delta": 1}
    assert by["We Can Do It!"]["immediately"] == [up]
    assert by["Full Metal"]["during"] == [{"op": "modify_value", "card": "this", "amount": {"counter": "upgrades"}}]
    assert by["Technological Superiority"]["immediately"] == [{"op": "if", "condition": {"test": "counter", "name": "upgrades", "min": 3},
                                                                "then": [{"op": "cancel_effects", "card": "opponent_card"}]}]
    assert by["Hasty Repairs"]["after"] == [{"op": "if", "condition": {"test": "counter", "name": "upgrades", "min": 1},
                                             "then": [{"op": "plugin", "id": "rosie:deactivate"}, {"op": "heal", "target": "hero", "amount": 3}]}]
    d_day = by["D-Day"]["after"]
    assert d_day[0] == {"op": "gain_action", "amount": 1} and d_day[1]["condition"] == {"test": "counter", "name": "upgrades", "min": 4}
    assert d_day[1]["then"] == [{"op": "damage", "target": "opposing", "amount": 1}, {"op": "heal", "target": "this", "amount": 1}]
    assert d_day[1]["else"] == [{"op": "counter", "name": "upgrades", "set": 4}]
    assert by["Overrun"]["after"][0] == {"op": "move", "target": "this", "amount": 3, "up_to": True, "through_enemies": True, "as": "mover"}
    assert by["Loose Lips Sink Ships!"]["during"] == [{"op": "plugin", "id": "rosie:loose_lips"}]
    arc = by["Arc Welding"]["after"][0]
    assert arc["op"] == "choose_effect" and [o["ops"][0]["op"] for o in arc["options"]] == ["counter", "damage"]
    scheme = by["Rapid Development"]["scheme"]
    assert [o["op"] for o in scheme] == ["draw", "choose_effect", "gain_action"] and scheme[0]["amount"] == 2
    scheme = by['"E" Award']["scheme"]
    assert [o["op"] for o in scheme] == ["choose_effect", "move"] and scheme[1]["amount"] == 3
    assert by["Momentous Shift"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]


def test_the_card_other_heroes_print_word_for_word_is_the_same_data(effects):
    mine = {c["title"]: c for c in effects["cards"]}
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "sinbad.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Momentous Shift")
    assert mine["Momentous Shift"]["effects"]["during"] == theirs["effects"]["during"]


def test_table_data_names_the_pieces_the_dials_the_deck_range_the_tokens_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == SLUG and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 402
    assert set(tts["fighters"]) == {"rosie", "wendy"}
    assert (tts["fighters"]["rosie"]["dial_max"], tts["fighters"]["wendy"]["dial_max"]) == (15, 7)
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("5a93d0", "628b52", "955c05")
    assert (tts["fighters"]["rosie"]["piece"], tts["fighters"]["rosie"]["dial"]) == ("862e16", "facfe3")
    assert (tts["fighters"]["wendy"]["piece"], tts["fighters"]["wendy"]["dial"]) == ("39768f", "45adc0")
    assert tts["tokens"] == {"merlin_engine": "d670b6", "cavity_magnetron": "e5ef35", "sedgley_fist_gun": "85c49f", "whizbang": "f45e71"}
    assert tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_rosie_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    rosie, theirs = load_hero_table(SLUG), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert rosie.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(rosie.identity) & set(theirs.identity)
    for bot, human in ((SLUG, other), (other, SLUG)):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_rosie_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero(SLUG).deck()) & set(load_hero(other).deck())


def test_rosie_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero(SLUG).deck())
    assert all(c not in set(load_hero(SLUG).deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults(SLUG, SLUG)


def test_rosie_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot(SLUG), at_human(other)), BOT_SPOT, HUMAN_SPOT) == (SLUG, other)
        assert detect_heroes(reading(at_bot(other), at_human(SLUG)), BOT_SPOT, HUMAN_SPOT) == (other, SLUG)


def test_the_catalog_names_rosie_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of(SLUG) == ROSIE
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table(SLUG).identity]).slug == SLUG


def test_no_guid_of_rosie_is_shared_with_another_hero():
    mine = set(load_hero_table(SLUG).all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != SLUG]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
