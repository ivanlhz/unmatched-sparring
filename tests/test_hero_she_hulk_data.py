"""She-Hulk's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards (the hero card 336 and the first row of sheet 176 of the tournament save, read from the images on 2026-11-08; the rest of her
sheet in the save is Dr. Jill Trent's picture, see docs/heroes/she-hulk.md), and her deck is told apart from Medusa's, the four
turtles', Doctor Strange's, Bigfoot's and the Hell's Kitchen heroes' (same CardIDs 17600-17629) by image and owner. No engine, no TTS,
no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "she-hulk.json"
EFFECTS = HEROES_DIR / "effects" / "she-hulk.json"
TTS = HEROES_DIR.parent / "tts" / "she-hulk.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Omega-Level Threat": (2, "She-Hulk", "attack", 5, 2),
    "The Savage She-Hulk": (2, "She-Hulk", "attack", 3, 3),
    "Sensational": (3, "She-Hulk", "attack", 4, 2),
    "Legalese": (3, "She-Hulk", "versatile", 2, 1),
    "Nerve Cluster Strike": (3, "She-Hulk", "versatile", 3, 1),
    "Cease and Desist": (3, "She-Hulk", "versatile", 1, 2),
    "Green Energy": (3, "She-Hulk", "versatile", 4, 1),
    "Lady Justice": (3, "She-Hulk", "defense", 0, 2),
    "The Defense Rests": (2, "She-Hulk", "defense", 2, 2),
    "Jennifer Walters, Esq.": (2, "She-Hulk", "scheme", None, 1),
    "Leap Toward": (2, "She-Hulk", "scheme", None, 1),
    "Double Jeopardy": (2, "She-Hulk", "scheme", None, 2),
}
# idx order of the sheet: idx 0-7 read from the image (the rest of the picture is Dr. Jill Trent's), idx 8-29 assumed
SHEET_ORDER = (["Omega-Level Threat"] * 2 + ["The Savage She-Hulk"] * 2 + ["Sensational"] * 3 + ["Legalese"] * 3 + ["Nerve Cluster Strike"] * 3
               + ["Cease and Desist"] * 3 + ["Green Energy"] * 3 + ["Lady Justice"] * 3 + ["The Defense Rests"] * 2
               + ["Jennifer Walters, Esq."] * 2 + ["Leap Toward"] * 2 + ["Double Jeopardy"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 336)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    assert [e["title"] for e in sheet[:8]] == ["Omega-Level Threat"] * 2 + ["The Savage She-Hulk"] * 2 + ["Sensational"] * 3 + ["Legalese"]    # the visible row
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["name"] == "She-Hulk" and overlay["fid"] == "shehulk"
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}
    assert overlay["triggers"] == [] and overlay["passives"] == [] and "reach_spaces" not in overlay


def test_generated_herodef_is_a_melee_hero_with_twenty_health_and_deals_a_real_deck():
    h = load_hero("she-hulk")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("She-Hulk", "shehulk", 20, 2, False, 0)
    assert h.sidekicks == () and [f.fid for f in h.fighters()] == ["shehulk"]
    assert h.ability.startswith("JUST THROW SOMETHING\nAt the start of your turn, you may discard a card to deal damage equal to its BOOST value")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    omega = next(c for c in deck if c.title == "Omega-Level Threat")
    assert omega.text == "AFTER COMBAT: If you dealt 2 or more combat damage, your opponent discards 2 random cards."
    cease = next(c for c in deck if c.title == "Cease and Desist")
    assert cease.text == "IMMEDIATELY: Cancel all effects on your opponent's card. DURING COMBAT: If you are attacking, the value of this card is 4 instead."


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("she-hulk").ai_profile
    assert set(profile) == {"shehulk"} and profile["shehulk"]["role"] == "hero" and not profile["shehulk"]["ranged"]
    assert {e["title"] for e in profile["shehulk"]["exclusive"]} == set(REAL_CARDS)


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "she-hulk"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert [p["id"] for p in effects["plugins"]] == ["shehulk:throw", "shehulk:mill"] and effects["ability"]["passives"] == []


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Jennifer Walters, Esq."]["scheme"] == [{"op": "place", "target": "hero", "where": {"start": True}, "chooser": "owner"},
                                                       {"op": "draw", "player": "owner", "amount": 1}, {"op": "gain_action", "amount": 1}]
    leap, gain = by["Leap Toward"]["scheme"]
    assert leap == {"op": "move", "target": "hero", "amount": 4, "up_to": True, "through_enemies": True, "await_destination": True, "chooser": "owner"}
    assert gain["condition"] == {"test": "exists", "fighters": {"side": "enemy", "where": {"adjacent_to": "hero"}}}
    assert gain["then"] == [{"op": "gain_action", "amount": 1}]
    assert by["Double Jeopardy"]["scheme"] == [{"op": "draw", "player": "owner", "amount": 2}, {"op": "heal", "target": "hero", "amount": 2}]
    nerve, = by["Nerve Cluster Strike"]["immediately"]
    assert nerve["condition"] == {"test": "exists", "fighters": {"role": "opposing", "where": {"adjacent_to": "this"}}}
    assert nerve["then"] == [{"op": "status", "name": "cannot_leave_space", "target": "opposing", "until": {"event": "end_of_turn"}}]
    assert by["Cease and Desist"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Cease and Desist"]["during"] == [{"op": "if", "condition": {"test": "played_as", "side": "attack"},
                                                 "then": [{"op": "set_value", "card": "this", "amount": 4}]}]
    assert by["Lady Justice"]["during"] == [{"op": "plugin", "id": "shehulk:mill", "args": {"as": "milled"}},
                                            {"op": "modify_value", "card": "this", "amount": {"attr": "boost", "of": "$milled", "times": 2}}]
    omega, = by["Omega-Level Threat"]["after"]
    assert omega["condition"] == {"test": "compare", "left": {"stat": "damage_dealt_this_combat"}, "op": ">=", "right": 2}
    assert omega["then"] == [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 2}}]
    assert by["The Defense Rests"]["after"] == [{"op": "draw", "player": "owner", "amount": {"stat": "damage_taken_this_combat"}}]
    assert by["The Savage She-Hulk"]["during"] == [{"op": "optional", "chooser": "owner", "cost": [{"op": "spend_action", "amount": 1}],
                                                    "ops": [{"op": "set_value", "card": "this", "amount": 9}]}]
    sensational, = by["Sensational"]["after"]
    assert sensational["then"] == [{"op": "return_to_deck", "cards": {"zone": "discard", "player": "owner", "amount": 1, "up_to": True, "chooser": "owner"},
                                    "position": "shuffle"}]
    green, = by["Green Energy"]["after"]
    assert green["then"] == [{"op": "damage", "target": {"side": "any", "where": {"adjacent_to": "hero"}, "pick": "all"}, "amount": 1}]
    legalese, = by["Legalese"]["after"]
    assert [o["chooser"] for o in (legalese["then"][0], legalese["else"][0])] == ["opponent", "owner"]
    assert legalese["then"][0]["options"] == legalese["else"][0]["options"]


def test_the_ability_is_one_start_of_turn_trigger_that_needs_an_enemy_in_her_zone(effects):
    trig, = effects["ability"]["triggers"]
    assert trig["when"] == {"event": "start_of_turn", "player": "owner"}
    assert trig["condition"] == {"test": "exists", "fighters": {"side": "enemy", "where": {"zone_of": "hero"}}}
    assert [o["op"] for o in trig["ops"]] == ["plugin", "if"] and trig["ops"][1]["then"][0]["amount"] == {"attr": "boost", "of": "$thrown"}


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "she-hulk" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 336
    assert set(tts["fighters"]) == {"shehulk"} and tts["fighters"]["shehulk"]["dial_max"] == 20
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["shehulk"]["piece"], tts["fighters"]["shehulk"]["dial"]) == (
        "04711f", "346c1b", "95f90a", "268982")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_she_hulk_shares_the_card_range_but_not_the_images_with_the_other_sheet_176_decks(other):
    shehulk, theirs = load_hero_table("she-hulk"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert shehulk.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(shehulk.identity) & set(theirs.identity)
    for bot, human in (("she-hulk", other), (other, "she-hulk")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_she_hulk_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("she-hulk").deck()) & set(load_hero(other).deck())


def test_she_hulk_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero("she-hulk").deck())
    assert all(c not in set(load_hero("she-hulk").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("she-hulk", "she-hulk")


def test_she_hulk_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("she-hulk"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("she-hulk", other)
        assert detect_heroes(reading(at_bot(other), at_human("she-hulk")), BOT_SPOT, HUMAN_SPOT) == (other, "she-hulk")


def test_the_catalog_names_she_hulk_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("she-hulk") == "She-Hulk"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("she-hulk").identity]).slug == "she-hulk"


def test_no_piece_guid_of_she_hulk_is_shared_with_another_hero():
    mine = set(load_hero_table("she-hulk").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "she-hulk"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
