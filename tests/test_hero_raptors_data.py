"""Raptors' data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards
of sheet 176 of the tournament save (read from the images on 2026-11-13), and their deck is told apart from the other decks of the
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

OVERLAY = HEROES_DIR / "overlay" / "raptors.json"
EFFECTS = HEROES_DIR / "effects" / "raptors.json"
TTS = HEROES_DIR.parent / "tts" / "raptors.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "yennefer-triss", "sinbad", "eredin", "ciri"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
FIGHTERS = ["blue", "delta", "echo"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Eviscerate": (2, "any", "attack", 5, 3),
    "Pack Hunters": (2, "any", "attack", 4, 2),
    "Clever Girl": (3, "any", "attack", 3, 3),
    "Disengage": (2, "any", "attack", 4, 2),
    "Ambush": (3, "any", "attack", 2, 3),
    "They Remember": (4, "any", "attack", 2, 2),
    "Feint": (3, "any", "versatile", 2, 1),
    "Eaten Alive": (3, "any", "versatile", 4, 2),
    "Decoy": (4, "any", "defense", 3, 1),
    "Coordinated Attack Pattern": (2, "any", "scheme", None, 2),
    "Working Things Out": (2, "any", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Eviscerate"] * 2 + ["Pack Hunters"] * 2 + ["Clever Girl"] * 3 + ["Disengage"] * 2 + ["Ambush"] * 3 + ["They Remember"] * 4
               + ["Feint"] * 3 + ["Eaten Alive"] * 3 + ["Decoy"] * 4 + ["Coordinated Attack Pattern"] * 2 + ["Working Things Out"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 313)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == []


def test_generated_herodef_is_a_team_of_three_melee_raptors_and_deals_a_real_deck():
    h = load_hero("raptors")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces, h.team) == ("Raptor Blue", "blue", 7, 3, False, 0, True)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged, s.team) for s in h.sidekicks] == [
        ("delta", "Raptor Delta", 1, 7, 3, False, True), ("echo", "Raptor Echo", 1, 7, 3, False, True)]
    assert [f.fid for f in h.fighters()] == FIGHTERS and [f.hero for f in h.fighters()] == [True, False, False]
    assert h.passives == ({"id": "pack_bonus", "effect": "pack_bonus", "n": 1},)
    assert h.ability == "Raptors add 1 to the value of their attack cards for each of your other Raptors adjacent to the defender."
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    by = {c.title: c for c in deck}
    assert by["Disengage"].text == "AFTER COMBAT: Move your Raptor to any other space in her zone."
    assert by["Ambush"].text == "DURING COMBAT: Your opponent discards 1 random card. Add its BOOST value to this card's value."
    assert by["Decoy"].text == "IMMEDIATELY: Choose one of your other undefeated Raptors. You may place her adjacent to the opposing fighter."


def test_only_the_raptors_are_a_team():
    teams = []
    for path in HEROES_DIR.glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if any(s.get("team") for s in raw.get("sidekicks") or ()):
            teams.append(path.stem)
    assert teams == ["raptors"]


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("raptors").ai_profile
    assert set(profile) == set(FIGHTERS) and profile["blue"]["role"] == "hero"
    assert all(profile[k]["role"] == "striker" and profile[k]["max_hp"] == 7 and not profile[k]["ranged"] for k in ("delta", "echo"))


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "raptors"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        if card["title"] != "Eviscerate":                                   # a plain attack: its value is all it does
            assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert [c["title"] for c in effects["cards"] if c.get("ongoing") or c.get("may_boost") or c.get("uncancelable")] == []
    assert effects["plugins"] == []                                          # no plugin: the pack bonus is the HeroDef passive read by sparring/pack.py


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c for c in effects["cards"]}
    assert by["Feint"]["effects"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["They Remember"]["effects"]["after"] == [{"op": "gain_action", "amount": 1}]
    assert by["Ambush"]["effects"]["during"] == [
        {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}, "as": "burnt"},
        {"op": "modify_value", "card": "this", "amount": {"attr": "boost", "of": "$burnt"}}]
    assert by["Working Things Out"]["effects"]["scheme"][-1] == {"op": "gain_action", "amount": 1}
    assert by["Working Things Out"]["effects"]["scheme"][0] == {
        "op": "move", "target": {"side": "own", "pick": "all"}, "amount": 3, "up_to": True, "through_enemies": True, "chooser": "owner"}
    pack_hunters = by["Pack Hunters"]["effects"]["after"][0]
    assert pack_hunters["condition"] == {"test": "combat_result", "result": "won"}
    assert pack_hunters["then"][0]["amount"] == {"count": {"side": "own", "where": {"adjacent_to": "opposing"}, "pick": "all"}}


def test_disengage_is_the_effect_of_bigfoots_card_worded_as_on_this_one(effects):
    mine = next(c for c in effects["cards"] if c["title"] == "Disengage")
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "bigfoot.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Disengage")
    assert mine["effects"] == theirs["effects"]
    assert mine["text"] == "AFTER COMBAT: Move your Raptor to any other space in her zone."


def test_feint_is_the_effect_of_the_feint_every_other_hero_has(effects):
    mine = next(c for c in effects["cards"] if c["title"] == "Feint")
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "sinbad.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Feint")
    assert mine["effects"] == theirs["effects"] and mine["text"] == theirs["text"]


def test_table_data_names_the_three_pieces_their_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "raptors" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 313
    assert set(tts["fighters"]) == set(FIGHTERS) and all(v["dial_max"] == 7 for v in tts["fighters"].values())
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("230e58", "9f42d9", "ab0add")
    assert {k: (v["piece"], v["dial"]) for k, v in tts["fighters"].items()} == {
        "blue": ("1a2945", "950174"), "delta": ("4573de", "c93049"), "echo": ("b5c3d5", "deff03")}
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_the_raptors_share_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    mine, theirs = load_hero_table("raptors"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert mine.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("raptors", other), (other, "raptors")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_the_raptors_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("raptors").deck()) & set(load_hero(other).deck())


def test_every_raptors_card_carries_the_tag_that_keeps_it_apart_from_the_same_looking_cards_of_other_decks(overlay):
    assert all(e["tags"] == ["raptors"] for e in overlay["deck"]["sheet"])
    assert all(c.tags == {"raptors"} for c in load_hero("raptors").deck())


def test_raptor_cards_are_never_medusas_and_medusas_never_theirs():
    assert not any(is_medusa_card(c) for c in load_hero("raptors").deck())
    assert all(c not in set(load_hero("raptors").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("raptors", "raptors")


def test_the_three_raptors_are_named_after_their_miniatures_on_the_table():
    defaults = table_defaults("raptors", "hellboy")
    assert {k: v for k, v in defaults["nicknames"].items() if k in FIGHTERS} == {
        "blue": "Raptor Blue", "delta": "Raptor Delta", "echo": "Raptor Echo"}
    assert {k: defaults["pieces"][k] for k in FIGHTERS} == {"blue": "1a2945", "delta": "4573de", "echo": "b5c3d5"}
    assert {k: defaults["dials"][k] for k in FIGHTERS} == {"blue": "950174", "delta": "c93049", "echo": "deff03"}


def test_the_raptors_are_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("raptors"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("raptors", other)
        assert detect_heroes(reading(at_bot(other), at_human("raptors")), BOT_SPOT, HUMAN_SPOT) == (other, "raptors")


def test_the_catalog_names_the_raptors_and_their_deck_is_their_own():
    catalog = load_catalog()
    assert catalog.name_of("raptors") == "Raptors"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("raptors").identity]).slug == "raptors"


def test_the_raptors_share_no_guid_with_any_other_hero():
    """Bag, deck, the three miniatures and the three dials (Custom_Assetbundle and Custom_Model in the save) are all theirs (the bag is not an object the bot moves)."""
    mine = set(load_hero_table("raptors").all_guids())
    assert len(mine) == 7
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "raptors"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
