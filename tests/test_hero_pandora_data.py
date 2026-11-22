"""Pandora's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of sheet 176
and the seven MISERIES of sheet 177 of the tournament save (read from the images on 2026-11-22), and her deck is told apart from the other decks of
the sheet (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.effects import plugins_pandora as box
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_card_identity import SHARING as SHARING_ALL
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "pandora.json"
EFFECTS = HEROES_DIR / "effects" / "pandora.json"
TTS = HEROES_DIR.parent / "tts" / "pandora.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = [s for s in SHARING_ALL if s != "pandora"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Hera's Curiosity": (3, "Pandora", "attack", 3, 4),
    "Hindsight": (3, "Pandora", "attack", 3, 2),
    "Aphrodite's Beauty": (3, "any", "attack", 0, 3),                  # unmatched-memory says 3 / 2
    "Spite": (2, "Kakodaemon", "attack", 3, 2),
    "Divine Intervention": (2, "Pandora", "versatile", 3, 1),
    "Feint": (3, "any", "versatile", 2, 2),
    "Guided by the Fates": (3, "any", "versatile", 2, 3),
    "Malice": (2, "Kakodaemon", "versatile", 2, 2),
    "Offering to the Gods": (2, "Pandora", "defense", 2, 1),
    "Celestial Raiments": (2, "Pandora", "defense", 0, 3),
    "Zeus's Mischief": (2, "Pandora", "scheme", None, 1),
    "Forged by Hephaestus": (3, "any", "scheme", None, 1),
}
SHEET_ORDER = (["Hera's Curiosity"] * 3 + ["Hindsight"] * 3 + ["Aphrodite's Beauty"] * 3 + ["Spite"] * 2 + ["Divine Intervention"] * 2 + ["Feint"] * 3
               + ["Guided by the Fates"] * 3 + ["Malice"] * 2 + ["Offering to the Gods"] * 2 + ["Celestial Raiments"] * 2 + ["Zeus's Mischief"] * 2
               + ["Forged by Hephaestus"] * 3)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 359)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_melee_hero_whose_two_kakodaemons_start_in_the_reserve():
    h = load_hero("pandora")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Pandora", "pandora", 14, 2, False, 0)
    kako, = h.sidekicks
    assert (kako.fid, kako.name, kako.count, kako.hp, kako.move, kako.ranged, kako.start_on_board) == ("kakodaemon", "Kakodaemon", 2, 1, 2, False, 0)
    assert [(f.fid, f.on_board) for f in h.fighters()] == [("pandora", True), ("kakodaemon1", False), ("kakodaemon2", False)]
    assert "Do not start with any Kakodaemons on the board" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    by = {c.title: c for c in deck}
    assert by["Aphrodite's Beauty"].text == "IMMEDIATELY: Cancel all effects on your opponent's card. AFTER COMBAT: Pandora recovers 1 health for each revealed MISERY."


def test_the_three_feints_carry_a_tag_so_they_differ_from_medusas():
    assert {c.tags for c in load_hero("pandora").deck() if c.title == "Feint"} == {frozenset({"pandora"})}
    assert not set(load_hero("pandora").deck()) & set(load_hero("medusa").deck())


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("pandora").ai_profile
    assert set(profile) == {"pandora", "kakodaemon"} and profile["pandora"]["role"] == "hero" and not profile["pandora"]["ranged"]
    assert profile["kakodaemon"]["count"] == 2 and profile["kakodaemon"]["max_hp"] == 1
    assert {e["title"] for e in profile["kakodaemon"]["exclusive"]} == {"Spite", "Malice"}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "pandora"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS) or card.get("may_boost"), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert [c["title"] for c in effects["cards"] if c.get("may_boost")] == ["Offering to the Gods"]
    assert sorted(p["id"] for p in effects["plugins"]) == ["pandora:close", "pandora:look", "pandora:reveal"]


def test_the_box_is_a_start_of_turn_loop_and_its_miseries_are_the_ones_on_the_cards(effects):
    box_trigger, shuffle = effects["ability"]["triggers"]
    assert box_trigger["id"] == "pandora_box" and box_trigger["when"] == {"event": "start_of_turn", "player": "owner"}
    assert shuffle["id"] == "pandora_shuffle" and shuffle["when"] == {"event": "end_of_turn", "player": "owner"}
    ops = box_trigger["ops"]
    assert ops[0] == {"op": "plugin", "id": "pandora:reveal"} and ops[-1] == {"op": "plugin", "id": "pandora:close"}
    effect_of = {o["condition"]["min"]: o["then"] for o in ops[1:-1]}
    assert sorted(effect_of) == [1, 2, 3, 5, 6, 7]                       # Misfortune (4) has no effect
    assert effect_of[1][0]["op"] == "if" and effect_of[1][0]["else"][0] == {"op": "summon", "name": "Kakodaemon", "where": {"zone_of": "hero"}}
    assert effect_of[2] == [{"op": "status", "name": "attack_bonus", "target": "hero", "amount": 1, "until": {"event": "end_of_turn"}}]
    assert effect_of[3][0]["op"] == "damage" and effect_of[3][0]["amount"] == 1
    assert effect_of[5] == [{"op": "plugin", "id": "pandora:look"}]
    assert effect_of[6] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert effect_of[7] == [{"op": "move", "target": "hero", "amount": 1, "up_to": True}]
    assert {o["name"] for o in shuffle["ops"]} == set(effects["ability"]["counters"]) - set()
    assert all(o["set"] == 0 for o in shuffle["ops"])


def test_the_miseries_have_the_printed_feathers():
    assert box.NAMES == ("Woe", "Toil", "Pain", "Misfortune", "Hope", "Greed", "Confusion")
    assert box.FEATHERS == (0, 1, 1, 2, 0, 1, 0) and sum(box.FEATHERS) == 5
    assert box.FIRST_CARD_ID == 17700 and box.STOP_AT == 3


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c for c in effects["cards"]}
    revealed = {"counter": "revealed"}
    assert by["Hera's Curiosity"]["effects"]["during"] == [{"op": "modify_value", "card": "this", "amount": revealed}]
    assert by["Hera's Curiosity"]["effects"]["after"] == [{"op": "look_hand", "player": "opponent"}]
    assert by["Aphrodite's Beauty"]["effects"]["after"] == [{"op": "heal", "target": "hero", "amount": revealed}]
    assert by["Zeus's Mischief"]["effects"]["scheme"][0] == {"op": "draw", "player": "owner", "amount": revealed}
    assert by["Celestial Raiments"]["effects"]["during"][0]["then"] == [{"op": "set_value", "card": "opponent_card", "ignore": True}]
    assert by["Divine Intervention"]["effects"]["after"] == [{"op": "move", "target": "hero", "amount": 5, "up_to": True}]


def test_table_data_names_the_pieces_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "pandora" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 359
    assert set(tts["fighters"]) == {"pandora", "kakodaemon1", "kakodaemon2"} and tts["fighters"]["pandora"]["dial_max"] == 14
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["pandora"]["piece"], tts["fighters"]["pandora"]["dial"]) == (
        "15414a", "b24a1c", "8603fa", "eeaab5")
    assert {k: (v["piece"], v["nickname"]) for k, v in tts["fighters"].items() if k != "pandora"} == {
        "kakodaemon1": ("7cd57e", "Thanatos"), "kakodaemon2": ("fed318", "Olethros")}
    assert all("dial" not in v for k, v in tts["fighters"].items() if k != "pandora")       # a Kakodaemon has 1 hit point: no dial
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_pandora_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    pandora, theirs = load_hero_table("pandora"), load_hero_table(other)
    assert pandora.card_ids == (17600, 17629) and theirs.card_ids[0] in (17600, 18700)
    if theirs.card_ids[0] == 17600:
        assert not set(pandora.identity) & set(theirs.identity)
        for bot, human in (("pandora", other), (other, "pandora")):
            defaults = table_defaults(bot, human)
            assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
            assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_pandora_equals_a_card_of_the_other_decks(other):
    assert not set(load_hero("pandora").deck()) & set(load_hero(other).deck())


def test_pandora_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero("pandora").deck())
    assert all(c not in set(load_hero("pandora").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("pandora", "pandora")


def test_pandora_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("pandora"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("pandora", other)
        assert detect_heroes(reading(at_bot(other), at_human("pandora")), BOT_SPOT, HUMAN_SPOT) == (other, "pandora")


def test_the_catalog_names_pandora_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("pandora") == "Pandora"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("pandora").identity]).slug == "pandora"


def test_pandora_shares_no_guid_with_any_other_hero():
    """Deck, miniature, dial and the two Kakodaemon tokens (Custom_Token in the save, which real TTS reports as "Tile") are all hers."""
    mine = set(load_hero_table("pandora").all_guids())
    assert len(mine) == 5
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "pandora"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
