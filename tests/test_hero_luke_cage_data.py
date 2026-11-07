"""Luke Cage's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the
real cards of sheet 176 of the tournament save (read from the images on 2026-11-07), and his deck is told apart from Medusa's,
the four turtles', Doctor Strange's and Bigfoot's (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "luke-cage.json"
EFFECTS = HEROES_DIR / "effects" / "luke-cage.json"
TTS = HEROES_DIR.parent / "tts" / "luke-cage.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "bullseye"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Sweet Christmas!": (2, "Luke Cage", "attack", 6, 1),
    "Get Paid": (2, "Luke Cage", "attack", 4, 2),
    "Hero For Hire": (3, "Luke Cage", "attack", 3, 1),
    "Commanding Impact": (3, "any", "attack", 5, 1),
    "Still Standing": (2, "any", "attack", 4, 2),
    "Regroup": (3, "any", "versatile", 1, 3),
    "Pushback": (2, "Misty Knight", "versatile", 2, 3),
    "Daughter of the Dragon": (2, "Misty Knight", "versatile", 2, 2),
    "Power Man": (2, "Luke Cage", "defense", 2, 1),
    "Skin Like Titanium": (2, "Luke Cage", "defense", 0, 1),
    "Trash Talk": (3, "any", "defense", 2, 1),
    "Got My Back?": (2, "Misty Knight", "defense", 1, 2),
    "Where's My Money?": (2, "Luke Cage", "scheme", None, 1),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Sweet Christmas!"] * 2 + ["Get Paid"] * 2 + ["Hero For Hire"] * 3 + ["Commanding Impact"] * 3
               + ["Still Standing"] * 2 + ["Regroup"] * 3 + ["Pushback"] * 2 + ["Daughter of the Dragon"] * 2
               + ["Power Man"] * 2 + ["Skin Like Titanium"] * 2 + ["Trash Talk"] * 3 + ["Got My Back?"] * 2
               + ["Where's My Money?"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 322)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "misty", "name": "Misty Knight"}] and overlay["fid"] == "luke"
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("luke-cage")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Luke Cage", "luke", 13, 2, False)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("misty", "Misty Knight", 1, 6, 2, True)]
    assert h.ability.splitlines() == ["Luke Cage takes 2 less combat damage from attacks.",
                                      "When defending, Luke Cage wins combat if he takes no damage even if he didn't play a card."]
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert sum(1 for c in deck if c.fighter == "Misty Knight") == 6
    assert next(c for c in deck if c.title == "Trash Talk").text == (
        "IMMEDIATELY: Cancel all effects on your opponent's card. AFTER COMBAT: If you won the combat, end the turn.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("luke-cage").ai_profile
    assert profile["luke"]["role"] == "hero" and profile["misty"]["role"] == "striker"
    assert {e["title"] for e in profile["misty"]["exclusive"]} >= {"Pushback", "Daughter of the Dragon", "Got My Back?"}
    assert {"Sweet Christmas!", "Power Man", "Where's My Money?"} <= {e["title"] for e in profile["luke"]["exclusive"]}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "luke-cage"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        if card["title"] not in ("Sweet Christmas!", "Hero For Hire"):          # a plain attack; a free BOOST is `may_boost`
            assert any(card["effects"][m] for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert [p["id"] for p in effects["plugins"]] == ["luke:replace_combatant"]


def test_the_ability_is_a_passive_rule_that_takes_two_off_combat_damage(effects):
    assert effects["ability"]["triggers"] == []
    assert effects["ability"]["passives"] == [{"id": "luke_skin", "kind": "rule", "rule": "combat_damage_reduction", "amount": 2}]


def test_card_effects_say_what_the_real_cards_say(effects):
    cards = {c["title"]: c for c in effects["cards"]}
    by = {t: c["effects"] for t, c in cards.items()}
    assert cards["Hero For Hire"]["may_boost"] is True
    assert by["Trash Talk"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Trash Talk"]["after"][0]["condition"] == {"test": "combat_result", "result": "won"}
    assert by["Trash Talk"]["after"][0]["then"] == [{"op": "end_turn"}]
    assert by["Get Paid"]["after"][0]["then"] == [{"op": "draw", "player": "owner", "amount": 2}]
    assert by["Commanding Impact"]["after"] == [{"op": "draw", "player": "owner", "amount": 1}]
    regroup, = by["Regroup"]["after"]
    assert regroup["then"][0]["amount"] == 2 and regroup["else"][0]["amount"] == 1
    assert by["Pushback"]["after"] == [{"op": "move", "target": "opposing", "amount": 3, "up_to": True, "chooser": "owner"}]
    assert by["Daughter of the Dragon"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 6}]
    still, = by["Still Standing"]["after"]
    assert still["condition"] == {"test": "combat_result", "result": "won"}
    assert still["then"][0]["cards"]["zone"] == "discard" and still["then"][0]["cards"]["amount"] == 2
    assert still["then"][0]["position"] == "shuffle"
    skin, = by["Skin Like Titanium"]["after"]
    assert skin["condition"] == {"test": "combat_result", "result": "lost"}
    assert skin["then"] == [{"op": "damage", "target": "opposing", "amount": {"stat": "damage_taken_this_combat"}}]
    assert [o["op"] for o in by["Power Man"]["after"]] == ["move", "damage", "damage"]
    assert by["Power Man"]["after"][0]["amount"] == 3 and by["Power Man"]["after"][2]["target"]["filter"] == {"passed_by": "$mover"}
    assert by["Where's My Money?"]["scheme"] == [
        {"op": "place", "target": "hero", "where": {"next_to_nearest_foe": "hero"}, "chooser": "owner"},
        {"op": "gain_action", "amount": 1}]
    swap = by["Got My Back?"]["immediately"][0]["then"][0]["ops"]
    assert [o["op"] for o in swap] == ["swap", "plugin"] and swap[1]["id"] == "luke:replace_combatant"


def test_table_data_names_both_pieces_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "luke-cage" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 322
    assert set(tts["fighters"]) == {"luke", "misty"}
    assert (tts["fighters"]["luke"]["dial_max"], tts["fighters"]["misty"]["dial_max"]) == (13, 6)
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_luke_cage_shares_the_card_range_but_not_the_images_with_the_other_sheet_176_decks(other):
    luke, theirs = load_hero_table("luke-cage"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert luke.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(luke.identity) & set(theirs.identity)
    for bot, human in (("luke-cage", other), (other, "luke-cage")):
        defaults = table_defaults(bot, human)
        assert {tuple(defaults["bot_card_ids"]), tuple(defaults["human_card_ids"])} == {(17600, 17629), (17600, top)}
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_luke_cage_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("luke-cage").deck()) & set(load_hero(other).deck())


def test_luke_cage_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("luke-cage").deck())
    assert all(c not in set(load_hero("luke-cage").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("luke-cage", "luke-cage")


def test_luke_cage_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("luke-cage"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("luke-cage", other)
        assert detect_heroes(reading(at_bot(other), at_human("luke-cage")), BOT_SPOT, HUMAN_SPOT) == (other, "luke-cage")


def test_the_catalog_names_luke_cage_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("luke-cage") == "Luke Cage"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("luke-cage").identity]).slug == "luke-cage"


def test_luke_cage_shares_no_piece_guid_with_any_other_hero():
    mine = set(load_hero_table("luke-cage").all_guids())
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "luke-cage"]:
        for g in mine & set(load_hero_table(slug).all_guids()):
            shared.setdefault(g, []).append(slug)
    assert shared == {}
