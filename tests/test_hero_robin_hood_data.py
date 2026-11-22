"""Robin Hood's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-22), and his deck is told apart from the other decks of the
sheet (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_card_identity import SHARING as SHARING_ALL
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "robin-hood.json"
EFFECTS = HEROES_DIR / "effects" / "robin-hood.json"
TTS = HEROES_DIR.parent / "tts" / "robin-hood.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = [s for s in SHARING_ALL if s != "robin-hood"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
SHARED_DIAL = "1fc8df"        # the save reuses this Custom_Model GUID for Robin Hood's and Yennenga's life dials (and Nikola Tesla's miniature)

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "A Hunter's Eye": (3, "Robin Hood", "attack", 5, 4),
    "Piercing Shot": (2, "Robin Hood", "attack", 2, 3),
    "Disarming Shot": (2, "Robin Hood", "attack", 4, 3),
    "Ambush": (2, "any", "attack", 2, 3),
    "Highway Robbery": (4, "Outlaw", "attack", 2, 2),
    "Regroup": (3, "any", "versatile", 1, 2),
    "Feint": (3, "any", "versatile", 2, 2),
    "Snark": (3, "any", "versatile", 3, 1),
    "Wily Fighting": (3, "any", "versatile", 3, 1),
    "Defenders of Sherwood": (2, "any", "defense", 3, 2),
    "Steal From the Rich": (3, "Robin Hood", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["A Hunter's Eye"] * 3 + ["Piercing Shot"] * 2 + ["Disarming Shot"] * 2 + ["Ambush"] * 2 + ["Highway Robbery"] * 4
               + ["Regroup"] * 3 + ["Feint"] * 3 + ["Snark"] * 3 + ["Wily Fighting"] * 3 + ["Defenders of Sherwood"] * 2
               + ["Steal From the Rich"] * 3)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 308)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []
    assert [(s["fid"], s["name"], s["count"], s["hp"], s["move"], s["attack"]) for s in overlay["sidekicks"]] == [("outlaw", "Outlaw", 4, 1, 2, "melee")]


def test_the_schemes_print_no_value_and_the_ambush_text_is_the_printed_one(overlay):
    sheet = overlay["deck"]["sheet"]
    assert all(e["text"] == "DURING COMBAT: Your opponent discards 1 random card. Add its BOOST value to this card's value."
               for e in sheet if e["title"] == "Ambush")
    deck = load_hero("robin-hood").deck()
    assert [c.value for c in deck if c.title == "Steal From the Rich"] == [None] * 3


def test_generated_herodef_is_a_ranged_hero_with_four_outlaws_and_deals_a_real_deck():
    h = load_hero("robin-hood")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Robin Hood", "robin", 13, 2, True, 0)
    assert h.ability == "After you attack, you may move your attacking fighter up to 2 spaces."
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("outlaw", "Outlaw", 4, 1, 2, False)]
    assert [(f.fid, f.on_board) for f in h.fighters()] == [("robin", True)] + [(f"outlaw{i}", True) for i in range(1, 5)]
    assert not h.counters and h.forms is None
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    assert [c.title for c in deck] == SHEET_ORDER
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert next(c for c in deck if c.title == "Defenders of Sherwood").text == (
        "AFTER COMBAT: Draw 1 card. Return a defeated Outlaw (if any) to any space in Robin Hood's zone.")
    assert next(c for c in deck if c.title == "Steal From the Rich").text == (
        "Draw 1 card, then choose an opponent. They may choose to discard 1 card. If they do not, draw 1 more card.")


def test_his_feint_carries_a_tag_because_it_is_word_for_word_another_decks():
    assert {c.tags for c in load_hero("robin-hood").deck() if c.title == "Feint"} == {frozenset({"robin-hood"})}
    assert all(not c.tags for c in load_hero("robin-hood").deck() if c.title != "Feint")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("robin-hood").ai_profile
    assert set(profile) == {"robin", "outlaw"}
    assert profile["robin"]["role"] == "hero" and profile["robin"]["ranged"] and not profile["outlaw"]["ranged"]


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "robin-hood"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS) or card["title"] == "A Hunter's Eye", card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert [p["id"] for p in effects["plugins"]] == ["robin:ambush"]


def test_the_ability_is_an_optional_move_of_up_to_two_after_each_attack_of_the_player(effects):
    assert effects["ability"]["passives"] == []
    assert effects["ability"]["triggers"] == [{
        "id": "robin_step", "when": {"event": "after_attack", "fighter": {"side": "own"}},
        "ops": [{"op": "optional", "chooser": "owner", "ops": [{"op": "move", "target": "$attacker", "amount": 2, "up_to": True}]}]}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Piercing Shot"]["after"] == [{"op": "draw", "player": "owner", "amount": 2}]
    assert by["Disarming Shot"]["after"] == [{"op": "draw", "player": "owner", "amount": {"stat": "damage_dealt_this_combat"}}]
    assert by["Ambush"]["during"] == [{"op": "plugin", "id": "robin:ambush"}]
    assert by["Highway Robbery"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"},
                                                    {"op": "set_value", "card": "opponent_card", "ignore": True}]
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    regroup = by["Regroup"]["after"][0]
    assert regroup["condition"] == {"test": "combat_result", "result": "won"}
    assert regroup["then"] == [{"op": "draw", "player": "owner", "amount": 2}] and regroup["else"] == [{"op": "draw", "player": "owner", "amount": 1}]
    snark = by["Snark"]["after"][0]
    assert snark["condition"] == {"test": "exists", "fighters": {"role": "opposing", "where": {"adjacent_to": "this"}}}
    assert snark["then"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by["Wily Fighting"]["after"] == [{"op": "damage", "target": {"side": "enemy", "where": {"adjacent_to": "this"}, "pick": "all"}, "amount": 1}]
    assert by["Defenders of Sherwood"]["after"] == [
        {"op": "draw", "player": "owner", "amount": 1},
        {"op": "revive", "target": {"side": "own", "name": "Outlaw", "state": "defeated"}, "where": {"zone_of": "hero"}, "hp": 1, "chooser": "owner"}]
    steal = by["Steal From the Rich"]["scheme"]
    assert steal[0] == {"op": "draw", "player": "owner", "amount": 1}
    assert steal[1]["chooser"] == "opponent" and steal[1]["ops"] == [] and steal[1]["else"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert steal[1]["cost"] == [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "opponent"}}]


def test_the_cards_other_heroes_print_word_for_word_are_the_same_data(effects):
    mine = {c["title"]: c for c in effects["cards"]}
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "bigfoot.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Feint")
    assert mine["Feint"]["text"] == theirs["text"] and mine["Feint"]["effects"] == theirs["effects"]
    raptors = next(c for c in json.loads((HEROES_DIR / "effects" / "raptors.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Ambush")
    assert mine["Ambush"]["text"] == raptors["text"] and mine["Ambush"]["effects"]["during"][0]["id"] != raptors["effects"]["during"][0]["id"]


def test_table_data_names_the_pieces_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "robin-hood" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 308
    assert set(tts["fighters"]) == {"robin", "outlaw1", "outlaw2", "outlaw3", "outlaw4"} and tts["fighters"]["robin"]["dial_max"] == 13
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("ee2fcc", "6c439e", "462e4d")
    assert (tts["fighters"]["robin"]["piece"], tts["fighters"]["robin"]["dial"]) == ("5aa21a", SHARED_DIAL)
    assert [tts["fighters"][f"outlaw{i}"]["piece"] for i in range(1, 5)] == ["88a446", "0d8360", "821507", "dc6b24"]
    assert all("dial" not in tts["fighters"][f"outlaw{i}"] for i in range(1, 5))       # an Outlaw has 1 hit point: no dial
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_robin_hood_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    mine, theirs = load_hero_table("robin-hood"), load_hero_table(other)
    assert mine.card_ids == (17600, 17629) and theirs.card_ids[0] in (17600, 18700)
    if theirs.card_ids[0] == 17600:
        assert not set(mine.identity) & set(theirs.identity)
        for bot, human in (("robin-hood", other), (other, "robin-hood")):
            defaults = table_defaults(bot, human)
            assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
            assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_robin_hood_equals_a_card_of_the_other_decks(other):
    assert not set(load_hero("robin-hood").deck()) & set(load_hero(other).deck())


def test_robin_hood_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("robin-hood").deck())
    assert all(c not in set(load_hero("robin-hood").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("robin-hood", "robin-hood")


def test_robin_hood_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("robin-hood"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("robin-hood", other)
        assert detect_heroes(reading(at_bot(other), at_human("robin-hood")), BOT_SPOT, HUMAN_SPOT) == (other, "robin-hood")


def test_the_catalog_names_robin_hood_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("robin-hood") == "Robin Hood"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("robin-hood").identity]).slug == "robin-hood"


def test_only_the_life_dial_guid_is_shared_with_other_heroes_and_only_with_yennenga():
    mine = set(load_hero_table("robin-hood").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "robin-hood"]:
        common = mine & set(load_hero_table(slug).all_guids())
        assert common == ({SHARED_DIAL} if slug == "yennenga" else set()), slug
