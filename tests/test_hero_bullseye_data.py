"""Bullseye's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the
real cards of sheet 176 of the tournament save (read from the images on 2026-11-07), his reach (5 spaces, zones ignored) is a
HeroDef parameter the engine reads, and his deck is told apart from Medusa's, the four turtles', Doctor Strange's and Bigfoot's
(same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.board import Board
from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.state import Game
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "bullseye.json"
EFFECTS = HEROES_DIR / "effects" / "bullseye.json"
TTS = HEROES_DIR.parent / "tts" / "bullseye.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "World's Greatest Assassin": (2, "Bullseye", "attack", 4, 3),
    "I Planned To Be Here": (2, "Bullseye", "attack", 2, 3),
    "I Never Miss": (4, "Bullseye", "attack", 3, 2),
    "For My Next Trick": (3, "Bullseye", "attack", 2, 2),
    "Feint": (2, "Bullseye", "versatile", 2, 2),
    "Arrogant But Effective": (3, "Bullseye", "versatile", 2, 2),
    "I'm Better And I'll Prove It": (2, "Bullseye", "versatile", 2, 2),
    "Master Strategist": (2, "Bullseye", "versatile", 3, 3),
    "Ricochet": (3, "Bullseye", "versatile", 3, 2),
    "Right Between The Eyes": (2, "Bullseye", "versatile", 3, 3),
    "Tactical Retreat": (3, "Bullseye", "defense", 3, 2),
    "Study The Target": (2, "Bullseye", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["World's Greatest Assassin"] * 2 + ["I Planned To Be Here"] * 2 + ["I Never Miss"] * 4 + ["For My Next Trick"] * 3
               + ["Feint"] * 2 + ["Arrogant But Effective"] * 3 + ["I'm Better And I'll Prove It"] * 2 + ["Master Strategist"] * 2
               + ["Ricochet"] * 3 + ["Right Between The Eyes"] * 2 + ["Tactical Retreat"] * 3 + ["Study The Target"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 339)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}
    assert overlay["triggers"] == [] and overlay["passives"] == [] and overlay["reach_spaces"] == 5


def test_generated_herodef_is_a_ranged_hero_with_a_five_space_reach_and_deals_a_real_deck():
    h = load_hero("bullseye")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Bullseye", "bullseye", 14, 2, True, 5)
    assert h.sidekicks == () and [f.fid for f in h.fighters()] == ["bullseye"]
    assert h.fighters()[0].reach == 5
    assert h.ability == "Bullseye can attack from up to 5 spaces away (ignoring zones)."
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    next_trick = next(c for c in deck if c.title == "For My Next Trick")
    assert next_trick.text == "AFTER COMBAT: Move Bullseye up to 1 space. Draw 1 card. Gain 1 action."     # the card, not unmatched-memory
    assert next(c for c in deck if c.title == "Study The Target").text.startswith("Draw 2 cards. If you won")


def test_the_other_heroes_have_no_reach_in_spaces():
    assert {s: load_hero(s).reach_spaces for s in ("medusa", "hellboy", "doctor-strange", "bigfoot", "liz-sherman")} == dict.fromkeys(
        ("medusa", "hellboy", "doctor-strange", "bigfoot", "liz-sherman"), 0)


def test_the_game_gives_the_reach_to_his_fighter_only():
    g = Game.new(Board.load("bprd-hq"), 1, {}, heroes=("bullseye", "hellboy"), bot_player=0)
    assert g.fighters["bullseye"].reach == 5 and g.fighters["bullseye"].ranged
    assert all(f.reach == 0 for f in g.fighters.values() if f.owner == 1)


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("bullseye").ai_profile
    assert set(profile) == {"bullseye"} and profile["bullseye"]["role"] == "hero" and profile["bullseye"]["ranged"]
    assert {e["title"] for e in profile["bullseye"]["exclusive"]} == set(REAL_CARDS)


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "bullseye"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in (*MOMENTS, "unboosted")), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert effects["plugins"] == [] and effects["ability"]["triggers"] == [] and effects["ability"]["passives"] == []


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    won = {"test": "compare", "left": {"stat": "combats_won_this_turn", "player": "owner"}, "op": ">=", "right": 1}
    assert by["World's Greatest Assassin"]["immediately"] == [{"op": "if", "condition": won, "then": [{"op": "set_value", "card": "opponent_card", "ignore": True}]}]
    assert by["I'm Better And I'll Prove It"]["during"] == [{"op": "if", "condition": won, "then": [{"op": "set_value", "card": "this", "amount": 6}]}]
    assert by["Right Between The Eyes"]["immediately"][0]["condition"] == won
    assert by["Right Between The Eyes"]["immediately"][0]["then"] == [
        {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "opponent"}}]
    assert by["I Planned To Be Here"]["during"] == [{"op": "if", "condition": {"not": {"test": "moved_this_turn", "fighter": "this"}},
                                                     "then": [{"op": "set_value", "card": "this", "amount": 5}]}]
    assert by["I Never Miss"]["unboosted"] == [{"op": "draw", "player": "owner", "amount": 1}] and by["I Never Miss"]["during"] == []
    assert by["For My Next Trick"]["after"] == [{"op": "move", "target": "hero", "amount": 1, "up_to": True, "chooser": "owner"},
                                                {"op": "draw", "player": "owner", "amount": 1}, {"op": "gain_action", "amount": 1}]
    assert by["Arrogant But Effective"]["after"] == [{"op": "consider_won"},
                                                     {"op": "move", "target": "hero", "amount": 2, "up_to": True, "chooser": "owner"}]
    assert by["Master Strategist"]["after"] == [{"op": "move", "target": "hero", "amount": 4, "up_to": False, "through_enemies": True, "chooser": "owner"}]
    assert by["Tactical Retreat"]["after"] == [{"op": "place", "target": "hero", "where": {"no_zone_of": "hero", "other": True}, "chooser": "owner"}]
    ricochet, = by["Ricochet"]["after"]
    assert ricochet["condition"] == {"test": "exists", "fighters": {"role": "opposing"}}
    assert ricochet["then"] == [{"op": "damage", "target": {"side": "any", "where": {"zone_of": "opposing"}}, "amount": 1, "chooser": "owner"}]
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    study = by["Study The Target"]["scheme"]
    assert study[0] == {"op": "draw", "player": "owner", "amount": 2} and study[1]["condition"] == won
    assert study[1]["then"] == [{"op": "draw", "player": "owner", "amount": 1}, {"op": "gain_action", "amount": 1}]


def test_i_never_miss_is_the_only_card_that_may_boost_and_has_unboosted_ops(effects):
    assert [c["title"] for c in effects["cards"] if c.get("may_boost")] == ["I Never Miss"]
    assert [c["title"] for c in effects["cards"] if c["effects"].get("unboosted")] == ["I Never Miss"]


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "bullseye" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 339
    assert set(tts["fighters"]) == {"bullseye"} and tts["fighters"]["bullseye"]["dial_max"] == 14
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["bullseye"]["piece"], tts["fighters"]["bullseye"]["dial"]) == (
        "4c1656", "303a39", "ca1bc5", "166320")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_bullseye_shares_the_card_range_but_not_the_images_with_medusa_the_turtles_strange_and_bigfoot(other):
    bullseye, theirs = load_hero_table("bullseye"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert bullseye.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(bullseye.identity) & set(theirs.identity)
    for bot, human in (("bullseye", other), (other, "bullseye")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_bullseye_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("bullseye").deck()) & set(load_hero(other).deck())


def test_bullseye_cards_are_never_medusas_and_medusas_never_bullseyes():
    assert not any(is_medusa_card(c) for c in load_hero("bullseye").deck())
    assert all(c not in set(load_hero("bullseye").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("bullseye", "bullseye")


def test_bullseye_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("bullseye"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("bullseye", other)
        assert detect_heroes(reading(at_bot(other), at_human("bullseye")), BOT_SPOT, HUMAN_SPOT) == (other, "bullseye")


def test_the_catalog_names_bullseye_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("bullseye") == "Bullseye"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("bullseye").identity]).slug == "bullseye"


def test_no_piece_guid_of_bullseye_is_shared_with_another_hero():
    mine = set(load_hero_table("bullseye").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "bullseye"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
