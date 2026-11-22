"""Blackbeard's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 2 of the tournament save (read from the images on 2026-11-22: the 30 cards, their bands and the hero card 362 on sheet 3). His deck is
on a sheet of its own (CardIDs 200-229) and carries a loose rules card (500), so the importer has to skip it. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.import_save import deck_sheet
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "blackbeard.json"
EFFECTS = HEROES_DIR / "effects" / "blackbeard.json"
TTS = HEROES_DIR.parent / "tts" / "blackbeard.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "eredin"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "A Brace of Primed Pistols": (2, "Blackbeard", "attack", 2, 2),
    "Avast Ye!": (2, "Blackbeard", "attack", 5, 3),
    "Give No Quarter": (3, "any", "attack", 3, 1),
    "Light the Fuse": (3, "Sea Dog", "attack", 2, 3),
    "Queen Anne's Revenge": (2, "Blackbeard", "versatile", 7, 3),
    "Fearsome and Calculating": (3, "Blackbeard", "versatile", 3, 1),
    "Show a Leg!": (2, "any", "versatile", 2, 2),
    "No Prey, No Pay": (3, "any", "versatile", 2, 2),
    "Parley": (3, "any", "versatile", 3, 2),
    "Intimidating Visage": (2, "Blackbeard", "defense", 4, 1),
    "Plunder": (3, "Blackbeard", "scheme", None, 2),
    "Scourge of the Seven Seas": (2, "Blackbeard", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["A Brace of Primed Pistols"] * 2 + ["Avast Ye!"] * 2 + ["Give No Quarter"] * 3 + ["Light the Fuse"] * 3 + ["Queen Anne's Revenge"] * 2
               + ["Fearsome and Calculating"] * 3 + ["Show a Leg!"] * 2 + ["No Prey, No Pay"] * 3 + ["Parley"] * 3 + ["Intimidating Visage"] * 2
               + ["Plunder"] * 3 + ["Scourge of the Seven Seas"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (200, 2, 362)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_ranged_hero_with_two_sea_dogs_on_the_board():
    h = load_hero("blackbeard")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Blackbeard", "blackbeard", 13, 2, True, 0)
    dog, = h.sidekicks
    assert (dog.fid, dog.name, dog.count, dog.hp, dog.move, dog.ranged, dog.start_on_board) == ("seadog", "Sea Dog", 2, 1, 2, False, None)
    assert [(f.fid, f.on_board) for f in h.fighters()] == [("blackbeard", True), ("seadog1", True), ("seadog2", True)]
    assert h.ability.startswith("PRIVATEER TURNED PIRATE")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(200, 230))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title


def test_the_card_texts_spell_out_the_doubloons_the_memory_data_draws_as_coins():
    by = {c.title: c for c in load_hero("blackbeard").deck()}
    assert by["A Brace of Primed Pistols"].text == "AFTER COMBAT: Deal 3 damage to an opposing fighter in Blackbeard's zone unless 2 doubloons."
    assert by["Parley"].text == "IMMEDIATELY: Cancel all effects on your opponent's card unless 2 doubloons."
    assert all("\U0001FA99" not in c.text for c in by.values())


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("blackbeard").ai_profile
    assert set(profile) == {"blackbeard", "seadog"} and profile["blackbeard"]["role"] == "hero" and profile["blackbeard"]["ranged"]
    assert profile["seadog"]["count"] == 2 and profile["seadog"]["max_hp"] == 1


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "blackbeard"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS) or card["title"] == "No Prey, No Pay", card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert [c["title"] for c in effects["cards"] if c.get("uncancelable")] == ["Queen Anne's Revenge"]
    assert [c["title"] for c in effects["cards"] if c.get("may_boost")] == ["No Prey, No Pay"]
    assert sorted(p["id"] for p in effects["plugins"]) == ["blackbeard:queens_revenge", "blackbeard:random_discard"]


def test_the_doubloons_are_two_counters_that_add_up_to_three(effects):
    counters = effects["ability"]["counters"]
    assert counters == {"doubloons": {"min": 0, "max": 3, "start": 2}, "treasury": {"min": 0, "max": 3, "start": 1}}


def test_the_ability_is_one_optional_action_at_the_start_of_the_turn_and_one_payment_for_combat_damage(effects):
    action, damage = effects["ability"]["triggers"]
    assert action["id"] == "doubloon_action" and action["when"] == {"event": "start_of_turn", "player": "owner"}
    assert [o["op"] for o in action["ops"]] == ["optional"] and action["ops"][0]["ops"] == [{"op": "gain_action", "amount": 1}]
    assert action["ops"][0]["cost"] == [{"op": "counter", "name": "doubloons", "delta": -1}, {"op": "counter", "name": "treasury", "delta": 1}]
    assert damage["id"] == "doubloon_damage" and damage["when"] == {"event": "damage_taken", "target": {"role": "hero"}, "damage": "combat"}
    assert damage["ops"] == [{"op": "counter", "name": "doubloons", "delta": -1}, {"op": "counter", "name": "treasury", "delta": 1}]


def ransom_lines(node):
    """Every `optional` of the opponent whose cost moves doubloons from the Treasury: (price, what the else branch does)."""
    out = []
    if isinstance(node, dict):
        if node.get("op") == "optional" and node.get("chooser") == "opponent":
            price = -sum(c["delta"] for c in node["cost"] if c["name"] == "treasury")
            out.append((price, [o["op"] for o in node["else"]]))
        for v in node.values():
            out += ransom_lines(v)
    elif isinstance(node, list):
        for v in node:
            out += ransom_lines(v)
    return out


def test_every_unless_line_of_the_real_cards_is_a_ransom_of_the_printed_price(effects):
    by = {c["title"]: ransom_lines(c["effects"]) for c in effects["cards"]}
    assert by["A Brace of Primed Pistols"] == [(2, ["damage"])]
    assert by["Avast Ye!"] == [(1, ["damage"])]                      # the random discard is the plugin's own ransom
    assert by["Give No Quarter"] == [(1, ["gain_action"])]
    assert by["Fearsome and Calculating"] == [(1, ["discard"])]
    assert by["Parley"] == [(2, ["cancel_effects"])]
    assert by["Scourge of the Seven Seas"] == [(1, ["heal"]), (1, ["if"]), (1, ["gain_action"])]
    assert [t for t, lines in by.items() if lines] == ["A Brace of Primed Pistols", "Avast Ye!", "Give No Quarter", "Fearsome and Calculating", "Parley", "Scourge of the Seven Seas"]


def test_a_ransom_ignores_the_line_it_never_cancels_the_card(effects):
    """The effect is the `else` of the optional and the paying branch does nothing (BB1: it ignores that one line)."""
    for card in effects["cards"]:
        for node in _optionals(card["effects"]):
            if node.get("chooser") == "opponent":
                assert node["ops"] == [], card["title"]


def _optionals(node):
    if isinstance(node, dict):
        if node.get("op") == "optional":
            yield node
        for v in node.values():
            yield from _optionals(v)
    elif isinstance(node, list):
        for v in node:
            yield from _optionals(v)


def test_table_data_names_the_pieces_the_dial_the_deck_range_the_tokens_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "blackbeard" and tts["deck"]["card_ids"] == [200, 229] and tts["deck"]["character_card_id"] == 362
    assert set(tts["fighters"]) == {"blackbeard", "seadog1", "seadog2"} and tts["fighters"]["blackbeard"]["dial_max"] == 13
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["blackbeard"]["piece"], tts["fighters"]["blackbeard"]["dial"]) == (
        "af6cfa", "2bfd21", "8841d2", "81e2ff")
    assert {k: v["piece"] for k, v in tts["fighters"].items() if k != "blackbeard"} == {"seadog1": "e815fe", "seadog2": "265d90"}
    assert all("dial" not in v for k, v in tts["fighters"].items() if k != "blackbeard")        # a Sea Dog has 1 hit point: no dial
    assert tts["tokens"] == {"treasury": "442da0", "doubloon": "a3b09d"} and tts["counter_dials"] == {}


def test_the_importer_skips_the_loose_rules_card_that_rides_in_the_deck():
    ids = list(range(200, 230)) + [500, 362]
    deck = {"DeckIDs": ids}
    assert deck_sheet(deck) is None
    assert deck_sheet(deck, extras=(500,)) == ((200, 229), 362)
    assert load_hero("blackbeard").tts == {"extra_card_ids": [500]}


# ---------------------------------------------------------------- the deck is his own

@pytest.mark.parametrize("other", SHARING)
def test_blackbeards_card_range_is_nobody_elses_and_neither_are_the_images(other):
    mine, theirs = load_hero_table("blackbeard"), load_hero_table(other)
    assert mine.card_ids == (200, 229) and mine.card_ids[1] < theirs.card_ids[0]
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("blackbeard", other), (other, "blackbeard")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_blackbeard_equals_a_card_of_the_other_decks(other):
    assert not set(load_hero("blackbeard").deck()) & set(load_hero(other).deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("blackbeard", "blackbeard")


def test_blackbeard_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("blackbeard"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("blackbeard", other)
        assert detect_heroes(reading(at_bot(other), at_human("blackbeard")), BOT_SPOT, HUMAN_SPOT) == (other, "blackbeard")


def test_the_catalog_names_blackbeard_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("blackbeard") == "Blackbeard"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("blackbeard").identity]).slug == "blackbeard"


def test_blackbeard_shares_no_guid_with_any_other_hero():
    """Deck, miniature, dial, the two Sea Dog tokens, the Treasury tile and the doubloon stack are all his own."""
    mine = set(load_hero_table("blackbeard").all_guids())
    assert len(mine) == 7
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "blackbeard"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
