"""Sun Wukong's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards
of sheet 176 of the tournament save (read from the images on 2026-11-20), and his deck is told apart from the other decks of the sheet
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

OVERLAY = HEROES_DIR / "overlay" / "sun-wukong.json"
EFFECTS = HEROES_DIR / "effects" / "sun-wukong.json"
TTS = HEROES_DIR.parent / "tts" / "sun-wukong.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "eredin"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Ox Form": (2, "any", "attack", 7, 2),
    "Ruyi Jingo Bang": (3, "any", "attack", 0, 3),
    "Taunting Laughter": (3, "any", "attack", 3, 2),
    "Infinite Strikes": (3, "any", "attack", 2, 2),
    "Sly Monkey": (4, "any", "versatile", 2, 3),
    "72 Transformations": (3, "any", "versatile", 2, 2),
    "Wily Fighting": (3, "any", "versatile", 3, 1),
    "Bewilderment": (2, "any", "defense", 0, 2),
    "Tortoise Form": (2, "any", "defense", 5, 2),
    "Golden Chain Mail": (2, "any", "defense", 4, 2),
    "Fiery Eyes That See": (2, "any", "scheme", None, 1),
    "Phoenix Form": (1, "any", "scheme", None, 1),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Ox Form"] * 2 + ["Ruyi Jingo Bang"] * 3 + ["Taunting Laughter"] * 3 + ["Infinite Strikes"] * 3 + ["Sly Monkey"] * 4
               + ["72 Transformations"] * 3 + ["Wily Fighting"] * 3 + ["Bewilderment"] * 2 + ["Tortoise Form"] * 2 + ["Golden Chain Mail"] * 2
               + ["Fiery Eyes That See"] * 2 + ["Phoenix Form"])


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 320)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_the_three_forms_carry_the_form_tag_72_transformations_looks_for(overlay):
    tags = {e["title"]: e["tags"] for e in overlay["deck"]["sheet"] if e.get("tags")}
    assert tags == {"Ox Form": ["form"], "Tortoise Form": ["form"], "Phoenix Form": ["form"]}


def test_generated_herodef_is_a_melee_hero_whose_three_clones_start_in_the_reserve():
    h = load_hero("sun-wukong")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Sun Wukong", "wukong", 17, 2, False, 0)
    clone, = h.sidekicks
    assert (clone.fid, clone.name, clone.count, clone.hp, clone.move, clone.ranged, clone.start_on_board) == ("clone", "Clone", 3, 1, 2, False, 0)
    assert [(f.fid, f.on_board) for f in h.fighters()] == [("wukong", True), ("clone1", False), ("clone2", False), ("clone3", False)]
    assert h.ability.startswith("At the start of your turn, you may take 1 damage to summon a Clone")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    by = {c.title: c for c in deck}
    assert by["Bewilderment"].text == "DURING COMBAT: Prevent all combat damage. AFTER COMBAT: You may place your fighter in any space."     # the card says combat damage
    assert by["Ruyi Jingo Bang"].text.startswith("AFTER COMBAT: If your opponent played a defense card, TRICKED YOU.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("sun-wukong").ai_profile
    assert set(profile) == {"wukong", "clone"} and profile["wukong"]["role"] == "hero" and not profile["wukong"]["ranged"]
    assert profile["clone"]["count"] == 3 and profile["clone"]["max_hp"] == 1


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "sun-wukong"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert [c["title"] for c in effects["cards"] if c.get("uncancelable")] == ["Ox Form"]
    assert effects["plugins"] == []                                         # every card and the ability are ops of the DSL


def test_the_ability_is_one_optional_start_of_turn_trigger(effects):
    trigger, = effects["ability"]["triggers"]
    assert trigger["id"] == "clone_summon" and trigger["when"] == {"event": "start_of_turn", "player": "owner"}
    assert [o["op"] for o in trigger["ops"]] == ["optional"]
    inner = trigger["ops"][0]["ops"]
    assert inner[0] == {"op": "damage", "target": "hero", "amount": 1}
    assert inner[1]["op"] == "if" and inner[1]["then"][0]["op"] == "revive" and inner[1]["else"][0]["op"] == "summon"


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c for c in effects["cards"]}
    assert by["Ruyi Jingo Bang"]["effects"]["after"] == [
        {"op": "if", "condition": {"test": "card", "card": "opponent_card", "filter": {}}, "then": [{"op": "second_attack", "amount": 4}]}]
    assert by["Golden Chain Mail"]["effects"]["during"] == [{"op": "redirect_damage", "from": "this", "to": {"role": "attacker"}, "damage": "combat"}]
    assert by["Bewilderment"]["effects"]["during"] == [{"op": "cap_combat_damage", "target": {"role": "combatant", "pick": "all"}, "amount": 0}]
    assert by["Phoenix Form"]["effects"]["scheme"] == [{"op": "heal", "target": "hero", "amount": {"count": {"side": "own", "name": "Clone"}}}]
    assert by["Infinite Strikes"]["effects"]["after"] == [{"op": "gain_action", "amount": 1}]
    assert by["72 Transformations"]["effects"]["after"][0]["cards"]["filter"] == {"tag": "form"}
    assert [o["op"] for o in by["Fiery Eyes That See"]["effects"]["scheme"]] == ["look_hand", "return_to_deck", "draw", "draw"]
    assert by["Fiery Eyes That See"]["effects"]["scheme"][1]["position"] == "bottom"
    assert by["Sly Monkey"]["effects"]["after"][0]["condition"] == {"test": "exists", "fighters": {"role": "this", "kind": "hero"}}


def test_table_data_names_the_pieces_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "sun-wukong" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 320
    assert set(tts["fighters"]) == {"wukong", "clone1", "clone2", "clone3"} and tts["fighters"]["wukong"]["dial_max"] == 17
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["wukong"]["piece"], tts["fighters"]["wukong"]["dial"]) == (
        "ce28ea", "63ee45", "dad584", "bfe46d")
    assert {k: v["piece"] for k, v in tts["fighters"].items() if k != "wukong"} == {"clone1": "9fdce3", "clone2": "582f73", "clone3": "d17daa"}
    assert all("dial" not in v for k, v in tts["fighters"].items() if k != "wukong")        # a Clone has 1 hit point: no dial
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_wukong_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    wukong, theirs = load_hero_table("sun-wukong"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert wukong.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(wukong.identity) & set(theirs.identity)
    for bot, human in (("sun-wukong", other), (other, "sun-wukong")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_wukong_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("sun-wukong").deck()) & set(load_hero(other).deck())


def test_wukong_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("sun-wukong").deck())
    assert all(c not in set(load_hero("sun-wukong").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("sun-wukong", "sun-wukong")


def test_wukong_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("sun-wukong"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("sun-wukong", other)
        assert detect_heroes(reading(at_bot(other), at_human("sun-wukong")), BOT_SPOT, HUMAN_SPOT) == (other, "sun-wukong")


def test_the_catalog_names_wukong_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("sun-wukong") == "Sun Wukong"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("sun-wukong").identity]).slug == "sun-wukong"


def test_wukong_shares_no_guid_with_any_other_hero():
    """Deck, miniature, dial and the three Clone tokens (Custom_Token in the save, which real TTS reports as "Tile") are all his own."""
    mine = set(load_hero_table("sun-wukong").all_guids())
    assert len(mine) == 6
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "sun-wukong"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
