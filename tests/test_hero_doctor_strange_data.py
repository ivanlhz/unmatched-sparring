"""Doctor Strange's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with
the real cards of sheet 176 of the tournament save (read from the images on 2026-11-02), and his deck is told apart from
Medusa's and the four turtles' (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import itertools
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "doctor-strange.json"
EFFECTS = HEROES_DIR / "effects" / "doctor-strange.json"
TTS = HEROES_DIR.parent / "tts" / "doctor-strange.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "The Winds of Watoomb": (3, "Doctor Strange", "attack", 4, 1),
    "The Rings of Raggadorr": (3, "any", "attack", 4, 1),
    "Bolts of Balthakk": (4, "any", "attack", 2, 3),
    "Seven Suns of Cinnibus": (3, "Doctor Strange", "versatile", 3, 2),
    "Cloak of Levitation": (2, "Doctor Strange", "versatile", 2, 1),
    "Feint": (2, "any", "versatile", 2, 1),
    "Master of Kamar-Taj": (3, "any", "versatile", 2, 2),
    "Steadfast Disciple": (3, "Wong", "versatile", 2, 2),
    "The Mists of Munnopor": (3, "Doctor Strange", "defense", 2, 2),
    "No, Really, I'm a Doctor": (2, "Doctor Strange", "scheme", None, 3),
    "Eye of Agamotto": (2, "Doctor Strange", "scheme", None, 2),
}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 337)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "wong", "name": "Wong"}]
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("doctor-strange")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Doctor Strange", "strange", 14, 2, True)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("wong", "Wong", 1, 6, 2, True)]
    assert h.ability.startswith("DARK PACT") and "put that card on the bottom of your deck and draw 1 card" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert sum(1 for c in deck if c.fighter == "Wong") == 3
    # the real text of the card wins over unmatched-memory's (a Black Panther text on The Rings of Raggadorr)
    rings = next(c for c in deck if c.title == "The Rings of Raggadorr")
    assert "recover health equal to the damage dealt" in rings.text and "Black Panther" not in rings.text


def test_the_ai_profile_knows_wong_is_a_ranged_striker():
    profile = load_hero("doctor-strange").ai_profile
    assert profile["strange"]["role"] == "hero" and profile["wong"]["role"] == "striker" and profile["wong"]["ranged"]
    assert {e["title"] for e in profile["wong"]["exclusive"]} == {"Steadfast Disciple"}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "doctor-strange"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"][m] for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert sorted(p["id"] for p in effects["plugins"]) == ["strange:blind_boost", "strange:mists_of_munnopor", "strange:reveal_to_top"]


def test_dark_pact_is_a_trigger_after_each_combat_in_which_strange_himself_played_a_card(effects):
    trig, = effects["ability"]["triggers"]
    assert trig["id"] == "dark_pact"
    assert trig["when"] == {"event": "after_combat", "player": "owner", "fighter": "hero"}
    optional, = trig["ops"]
    assert optional["op"] == "optional" and optional["chooser"] == "owner"
    assert [o["op"] for o in optional["ops"]] == ["damage", "return_to_deck", "draw"]
    assert optional["ops"][0] == {"op": "damage", "target": "hero", "amount": 1}
    assert optional["ops"][1] == {"op": "return_to_deck", "cards": "$card", "position": "bottom"}
    assert effects["ability"]["passives"] == []


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["The Winds of Watoomb"]["after"][0] == {"op": "place", "target": "this", "where": {"start": True}, "chooser": "opponent"}
    assert by["The Winds of Watoomb"]["after"][2] == {"op": "shuffle_deck", "player": "all"}
    assert by["Eye of Agamotto"]["scheme"] == [
        {"op": "return_to_deck", "cards": {"zone": "hand", "player": "owner", "pick": "all"}, "position": "shuffle"},
        {"op": "draw", "player": "owner", "amount": 5}, {"op": "gain_action", "amount": 1}]
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Bolts of Balthakk"]["during"][0]["args"] == {"times": 1}
    assert by["Seven Suns of Cinnibus"]["during"][0]["args"] == {"times": 2}
    assert by["Seven Suns of Cinnibus"]["during"][1]["condition"]["right"] == 7


def test_table_data_names_both_pieces_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "doctor-strange" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 337
    assert set(tts["fighters"]) == {"strange", "wong"}
    assert (tts["fighters"]["strange"]["dial_max"], tts["fighters"]["wong"]["dial_max"]) == (14, 6)
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_strange_shares_the_card_range_but_not_the_images_with_medusa_and_each_turtle(other):
    strange, theirs = load_hero_table("doctor-strange"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert strange.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(strange.identity) & set(theirs.identity)
    for bot, human in (("doctor-strange", other), (other, "doctor-strange")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_strange_equals_a_card_of_medusa_or_a_turtle(other):
    """A Card is a frozen value: the title and the restriction differ, so a card of one deck is never another's by `==`."""
    assert not set(load_hero("doctor-strange").deck()) & set(load_hero(other).deck())


def test_strange_cards_are_never_medusas_and_medusas_never_strange():
    assert not any(is_medusa_card(c) for c in load_hero("doctor-strange").deck())
    assert all(not (c in set(load_hero("doctor-strange").deck())) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("doctor-strange", "doctor-strange")


def test_strange_is_detected_on_either_side_against_any_hero():
    for other in ("medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael"):
        assert detect_heroes(reading(at_bot("doctor-strange"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("doctor-strange", other)
        assert detect_heroes(reading(at_bot(other), at_human("doctor-strange")), BOT_SPOT, HUMAN_SPOT) == (other, "doctor-strange")


def test_the_catalog_names_strange_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("doctor-strange") == "Doctor Strange"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("doctor-strange").identity]).slug == "doctor-strange"


def test_no_piece_guid_of_strange_is_shared_with_another_hero():
    """The one known collision of the save is Abe Sapien's and Donatello's (tests/test_piece_identity.py); Strange has none."""
    mine = set(load_hero_table("doctor-strange").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "doctor-strange"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
