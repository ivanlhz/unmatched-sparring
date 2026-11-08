"""Jill Trent's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-08), and her deck is told apart from Medusa's, the four
turtles', Doctor Strange's, Bigfoot's and the Marvel decks' (same CardIDs 17600-17629) by image and owner. No engine, no TTS,
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

OVERLAY = HEROES_DIR / "overlay" / "jill-trent.json"
EFFECTS = HEROES_DIR / "effects" / "jill-trent.json"
TTS = HEROES_DIR.parent / "tts" / "jill-trent.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "she-hulk", "tomoe-gozen"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
J, D = "Dr. Jill Trent", "Daisy"

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Battle of Wits": (3, J, "attack", 2, 4),
    "Energizing Spray": (2, "any", "attack", 5, 1),
    "Utility Belt": (3, J, "versatile", 3, 3),
    "Stasis Diffuser": (2, "any", "versatile", 3, 1),
    "Laser Pen": (3, "any", "versatile", 2, 2),
    "Insightful Deduction": (2, "any", "versatile", 3, 2),
    "Caught Red-Handed": (2, "any", "versatile", 1, 2),
    "Gyroscopic Jetpack": (3, "any", "versatile", 4, 2),
    "Ace Fighter": (2, D, "versatile", 5, 3),
    "Sisters in Arms": (2, D, "versatile", 3, 1),
    "Hypnotist": (2, J, "defense", 3, 1),
    "Indestructible Cloth": (2, "any", "defense", 5, 2),
    "Helpful Assistant": (2, D, "scheme", None, 3),
}
SHEET_ORDER = [t for t, (copies, *_) in REAL_CARDS.items() for _ in range(copies)]       # the order of the sheet is the order of the dict


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 348)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies and {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "daisy", "name": "Daisy"}] and overlay["memory_slug"] == "dr-jill-trent"
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_is_a_melee_hero_with_daisy_and_deals_a_real_deck():
    h = load_hero("jill-trent")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Dr. Jill Trent", "jill", 13, 2, False, 0)
    assert [(s.fid, s.name, s.hp, s.move, s.ranged, s.count) for s in h.sidekicks] == [("daisy", "Daisy", 6, 2, False, 1)]
    assert [f.fid for f in h.fighters()] == ["jill", "daisy"]
    assert h.ability.startswith("GADGETOLOGY: At the start of your turn, activate one of your gadgets.")
    assert "Hypnoray Blaster: DURING COMBAT" in h.ability and "Ultrabiotic Tonic: AFTER COMBAT" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("jill-trent").ai_profile
    assert set(profile) == {"jill", "daisy"} and profile["jill"]["role"] == "hero" and not profile["jill"]["ranged"]
    assert {e["title"] for e in profile["jill"]["exclusive"]} == {"Battle of Wits", "Utility Belt", "Hypnotist"}
    assert {e["title"] for e in profile["daisy"]["exclusive"]} == {"Ace Fighter", "Sisters in Arms", "Helpful Assistant"}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "jill-trent"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
    assert [c["title"] for c in effects["cards"] if c.get("uncancelable")] == ["Sisters in Arms"]
    assert {p["id"] for p in effects["plugins"]} == {"jill:hypnoray", "jill:reveal_tops", "jill:insightful_deduction"}


def test_the_ability_is_a_counter_a_trigger_and_two_effects_of_the_hero(effects):
    ability = effects["ability"]
    assert ability["counters"] == {"gadget": {"min": 0, "max": 2, "start": 0}} and ability["passives"] == []
    trigger, = ability["triggers"]
    assert trigger["when"] == {"event": "start_of_turn", "player": "owner"}
    options, = [o["options"] for o in trigger["ops"]]
    assert [o["label"] for o in options] == ["Hypnoray Blaster", "Ultrabiotic Tonic"]
    assert [o["ops"] for o in options] == [[{"op": "counter", "name": "gadget", "set": 1}], [{"op": "counter", "name": "gadget", "set": 2}]]
    during, after = ability["during"], ability["after"]
    assert [e["id"] for e in during] == ["hypnoray_blaster"] and during[0]["ops"] == [{"op": "plugin", "id": "jill:hypnoray"}]
    assert [e["id"] for e in after] == ["ultrabiotic_tonic"] and after[0]["ops"] == [{"op": "heal", "target": "hero", "amount": 1}]
    lower = {"test": "compare", "left": {"attr": "value", "of": "this"}, "op": "<", "right": {"attr": "value", "of": "opponent_card"}}
    assert lower in during[0]["condition"]["all"] and {**lower, "op": ">"} in after[0]["condition"]["all"]
    for e in (*during, *after):          # Jill herself, attacking
        assert {"test": "exists", "fighters": {"role": "this", "kind": "hero"}} in e["condition"]["all"]
        assert {"test": "played_as", "side": "attack"} in e["condition"]["all"]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    hypno = {"test": "counter", "name": "gadget", "min": 1, "max": 1}
    assert by["Hypnotist"]["immediately"] == [{"op": "if", "condition": hypno, "then": [{"op": "cancel_effects", "card": "opponent_card"}]}]
    assert by["Stasis Diffuser"]["immediately"] == [{"op": "lock_value", "card": "opponent_card"}]
    assert by["Indestructible Cloth"]["immediately"] == [{"op": "status", "name": "immune_to_effect_damage", "target": "this",
                                                          "until": {"event": "after_attack", "fighter": {"side": "any"}}}]
    assert by["Energizing Spray"]["after"] == [{"op": "gain_action", "amount": 1}]
    assert by["Ace Fighter"]["after"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by["Laser Pen"]["after"] == [{"op": "damage", "target": "opposing", "amount": 1}]
    assert by["Gyroscopic Jetpack"]["after"] == [{"op": "move", "target": "this", "amount": 2, "up_to": True, "through_enemies": True, "chooser": "owner"}]
    caught, = by["Caught Red-Handed"]["after"]
    assert caught["condition"] == {"test": "combat_result", "result": "won"}
    assert [o["cards"]["amount"] for o in (*caught["then"], *caught["else"])] == [2, 1]
    assert by["Helpful Assistant"]["scheme"][0]["cards"] == {"zone": "discard", "player": "owner", "filter": {"fighter": J}, "amount": 3,
                                                             "up_to": True, "chooser": "owner"}
    assert by["Helpful Assistant"]["scheme"][1] == {"op": "draw", "player": "owner", "amount": 1}
    belt, = by["Utility Belt"]["after"]
    assert [o["label"] for o in belt["options"]] == ["Jill Trent recovers 1 health", "Move Jill Trent 1 space", "Draw 1 card"]
    assert belt["options"][1]["ops"][0]["up_to"] is False
    assert by["Battle of Wits"]["after"][0] == {"op": "plugin", "id": "jill:reveal_tops"}
    assert by["Battle of Wits"]["after"][1]["then"] == [{"op": "damage", "target": "opposing", "amount": 3}]
    assert by["Insightful Deduction"]["after"] == [{"op": "plugin", "id": "jill:insightful_deduction"}]
    sisters = by["Sisters in Arms"]
    assert sisters["during"][0]["then"] == [{"op": "plugin", "id": "jill:hypnoray"}]
    assert sisters["after"][0]["then"] == [{"op": "heal", "target": "this", "amount": 1}]


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "jill-trent" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 348
    assert set(tts["fighters"]) == {"jill", "daisy"}
    assert (tts["bag"]["guid"], tts["deck"]["guid"]) == ("55b9e4", "f918b9")
    assert tts["fighters"]["jill"] == {"piece": "448a24", "dial": "9bb234", "dial_max": 13}
    assert tts["fighters"]["daisy"] == {"piece": "0bf463", "dial": "e10c99", "dial_max": 6}
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_jill_shares_the_card_range_but_not_the_images_with_the_other_sheet_176_decks(other):
    jill, theirs = load_hero_table("jill-trent"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert jill.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(jill.identity) & set(theirs.identity)
    for bot, human in (("jill-trent", other), (other, "jill-trent")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_jill_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("jill-trent").deck()) & set(load_hero(other).deck())


def test_jill_cards_are_never_medusas_and_medusas_never_jills():
    assert not any(is_medusa_card(c) for c in load_hero("jill-trent").deck())
    assert all(c not in set(load_hero("jill-trent").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("jill-trent", "jill-trent")


def test_jill_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("jill-trent"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("jill-trent", other)
        assert detect_heroes(reading(at_bot(other), at_human("jill-trent")), BOT_SPOT, HUMAN_SPOT) == (other, "jill-trent")


def test_the_catalog_names_her_by_the_catalog_slug_and_her_deck_is_her_own():
    entry = load_catalog().identify([f"{f}|{b}" for f, b in load_hero_table("jill-trent").identity])
    assert entry.slug == "dr-jill-trent-science-sleuth" and entry.name == "Dr. Jill Trent, Science Sleuth"      # the project slug is jill-trent


def test_the_only_piece_guid_jill_shares_with_another_hero_is_daisys_token_with_abes_agent_carla():
    """Told apart by name (docs/card-identity.md, "Piece identity"); tests/test_piece_identity.py pins the collision and the matrix plays
    Abe Sapien against her in both seats."""
    mine = set(load_hero_table("jill-trent").all_guids())
    shared = {slug: mine & set(load_hero_table(slug).all_guids())
              for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "jill-trent"]}
    assert {slug: g for slug, g in shared.items() if g} == {"abe-sapien": {"0bf463"}}
