"""Eredin's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards
of sheet 176 of the tournament save (read from the images on 2026-11-09), and his deck is told apart from the other decks of the sheet
(same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "eredin.json"
EFFECTS = HEROES_DIR / "effects" / "eredin.json"
TTS = HEROES_DIR.parent / "tts" / "eredin.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Backhand": (3, "Eredin", "attack", 4, 3),
    "Brutal Strike": (3, "Eredin", "attack", 2, 3),
    "Foul Purpose": (2, "any", "attack", 3, 2),
    "Unyielding Hordes": (3, "Red Rider", "attack", 1, 2),
    "Icy Guile": (3, "any", "versatile", 2, 1),
    "Wild Hunt": (3, "any", "versatile", 3, 2),
    "Skirmish": (3, "any", "versatile", 4, 1),
    "Implacable": (3, "Eredin", "defense", 3, 3),
    "Portal Defense": (2, "Eredin", "defense", 0, 1),
    "Might Of The Aen Elle": (2, "Eredin", "scheme", None, 2),
    "Close For The Kill": (3, "any", "scheme", None, 4),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Backhand"] * 3 + ["Brutal Strike"] * 3 + ["Foul Purpose"] * 2 + ["Unyielding Hordes"] * 3 + ["Icy Guile"] * 3
               + ["Wild Hunt"] * 3 + ["Skirmish"] * 3 + ["Implacable"] * 3 + ["Portal Defense"] * 2 + ["Might Of The Aen Elle"] * 2
               + ["Close For The Kill"] * 3)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 350)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == []


def test_the_two_card_tags_are_on_the_two_cards_that_say_if_enraged_you_may(overlay):
    tags = {e["title"]: e["tags"] for e in overlay["deck"]["sheet"] if e.get("tags")}
    assert tags == {"Foul Purpose": ["any_space_if_enraged"], "Implacable": ["attack_if_enraged"]}


def test_generated_herodef_is_a_melee_hero_with_four_red_riders_and_deals_a_real_deck():
    h = load_hero("eredin")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Eredin", "eredin", 14, 2, False, 0)
    rider, = h.sidekicks
    assert (rider.fid, rider.name, rider.count, rider.hp, rider.move, rider.ranged, rider.start_on_board) == ("rider", "Red Rider", 4, 1, 2, False, 4)
    assert [f.fid for f in h.fighters()] == ["eredin", "rider1", "rider2", "rider3", "rider4"]
    assert h.passives == ({"id": "king_of_the_wild_hunt", "effect": "enraged", "combat_bonus": 1, "move": 3},)
    assert h.ability.startswith("KING OF THE WILD HUNT\nWhile all of your Red Riders are defeated, Eredin is ENRAGED.")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    by = {c.title: c for c in deck}
    assert "attack_if_enraged" in by["Implacable"].tags and "any_space_if_enraged" in by["Foul Purpose"].tags
    assert by["Might Of The Aen Elle"].text.endswith("Discard this card at the end of your turn if you didn't attack.")
    assert by["Portal Defense"].text == ("IMMEDIATELY: Eredin swaps spaces with an adjacent friendly fighter. That fighter is now the defender. "
                                          "AFTER COMBAT: If Eredin is ENRAGED, draw 2 cards.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("eredin").ai_profile
    assert set(profile) == {"eredin", "rider"} and profile["eredin"]["role"] == "hero" and not profile["eredin"]["ranged"]
    assert profile["rider"]["count"] == 4 and profile["rider"]["max_hp"] == 1


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "eredin"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        if card["title"] != "Implacable":                                     # a plain defense with a free BOOST; its attack is a card tag
            assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert [c["title"] for c in effects["cards"] if c.get("ongoing")] == ["Might Of The Aen Elle"]
    assert [c["title"] for c in effects["cards"] if c.get("may_boost")] == ["Implacable"]
    assert [c["title"] for c in effects["cards"] if c.get("uncancelable")] == ["Brutal Strike"]


def test_only_two_plugins_both_with_the_prefix_of_the_hero(effects):
    assert [p["id"] for p in effects["plugins"]] == ["eredin:replace_combatant", "eredin:opponent_card"]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c for c in effects["cards"]}
    assert by["Might Of The Aen Elle"]["ongoing"] == {
        "modifiers": [{"kind": "status", "name": "immune_to_effect_damage", "target": "hero"}], "triggers": [],
        "until": {"event": "end_of_turn", "player": "owner", "unless_attacked": True}}
    assert by["Might Of The Aen Elle"]["effects"]["scheme"] == [{"op": "draw", "player": "owner", "amount": 1}, {"op": "gain_action", "amount": 1}]
    assert by["Close For The Kill"]["effects"]["scheme"] == [
        {"op": "draw", "player": "owner", "amount": 2},
        {"op": "move", "target": {"side": "own", "pick": "all"}, "amount": 3, "up_to": True, "through_enemies": True, "chooser": "owner"}]
    assert by["Unyielding Hordes"]["effects"]["immediately"][0]["op"] == "revive"
    assert by["Icy Guile"]["effects"]["during"][0]["cost"] == [{"op": "defeat", "target": {"side": "own", "name": "Red Rider"}, "chooser": "owner"}]
    assert by["Foul Purpose"]["effects"]["after"][0]["cost"][0]["op"] == "defeat"
    assert by["Foul Purpose"]["effects"]["after"][0]["ops"] == [{"op": "put_in_hand", "cards": "this"}]


def test_skirmish_is_the_effect_of_bigfoots_and_tomoes_card_worded_as_on_the_card_of_golden_bat(effects):
    mine = next(c for c in effects["cards"] if c["title"] == "Skirmish")
    assert mine["text"] == "AFTER COMBAT: If you won the combat, move one of the fighters in the combat up to 2 spaces."
    for slug in ("bigfoot", "tomoe-gozen", "golden-bat"):
        theirs = next(c for c in json.loads((HEROES_DIR / "effects" / f"{slug}.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Skirmish")
        assert mine["effects"] == theirs["effects"], slug
    golden = next(c for c in json.loads((HEROES_DIR / "effects" / "golden-bat.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Skirmish")
    assert mine["text"] == golden["text"]


def test_table_data_names_the_pieces_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "eredin" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 350
    assert set(tts["fighters"]) == {"eredin", "rider1", "rider2", "rider3", "rider4"} and tts["fighters"]["eredin"]["dial_max"] == 14
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["eredin"]["piece"], tts["fighters"]["eredin"]["dial"]) == (
        "9183b3", "b0cd3e", "dd0bc4", "a0a36e")
    assert {k: v["nickname"] for k, v in tts["fighters"].items() if k != "eredin"} == {
        "rider1": "Maxwell", "rider2": "Aleksei", "rider3": "Adrian", "rider4": "Norman"}
    assert all("dial" not in v for k, v in tts["fighters"].items() if k != "eredin")        # a Red Rider has 1 hit point: no dial
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_eredin_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    eredin, theirs = load_hero_table("eredin"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert eredin.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(eredin.identity) & set(theirs.identity)
    for bot, human in (("eredin", other), (other, "eredin")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_eredin_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("eredin").deck()) & set(load_hero(other).deck())


def test_eredin_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("eredin").deck())
    assert all(c not in set(load_hero("eredin").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("eredin", "eredin")


def test_eredin_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("eredin"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("eredin", other)
        assert detect_heroes(reading(at_bot(other), at_human("eredin")), BOT_SPOT, HUMAN_SPOT) == (other, "eredin")


def test_the_catalog_names_eredin_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("eredin") == "Eredin"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("eredin").identity]).slug == "eredin"


def test_eredin_shares_no_guid_with_any_other_hero():
    """Bag, deck, miniature, dial and the four Red Rider tokens (Custom_Token in the save, which real TTS reports as "Tile") are all his own."""
    mine = set(load_hero_table("eredin").all_guids())
    assert len(mine) == 7
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "eredin"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
