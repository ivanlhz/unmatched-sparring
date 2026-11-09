"""Ciri's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of sheet
176 of the tournament save (read from the images on 2026-11-09), and her deck is told apart from the other decks of the sheet (same CardIDs
17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "ciri.json"
EFFECTS = HEROES_DIR / "effects" / "ciri.json"
TTS = HEROES_DIR.parent / "tts" / "ciri.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost, Source orb on the art band) as printed on the cards.
REAL_CARDS = {
    "Lion cub of Cintra": (3, "Ciri", "attack", 2, 2, True),
    "Channel the source": (3, "Ciri", "attack", 2, 3, False),
    "Bane of the Aen Elle": (3, "Ihuarraquax", "attack", 4, 4, False),
    "Pushed to the brink": (3, "Ciri", "versatile", 3, 2, True),
    "Zireael": (3, "Ciri", "versatile", 2, 2, True),
    "The lady of space and time": (2, "Ciri", "versatile", 2, 2, True),
    "Blink": (3, "Ciri", "versatile", 4, 1, False),
    "Searching strike": (3, "Ihuarraquax", "versatile", 3, 3, False),
    "Parry": (3, "any", "defense", 3, 1, False),
    "Child of the Elder Blood": (2, "Ciri", "scheme", None, 2, True),
    "Unicorn ally": (2, "any", "scheme", None, 2, False),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Lion cub of Cintra"] * 3 + ["Channel the source"] * 3 + ["Bane of the Aen Elle"] * 3 + ["Pushed to the brink"] * 3
               + ["Zireael"] * 3 + ["The lady of space and time"] * 2 + ["Blink"] * 3 + ["Searching strike"] * 3 + ["Parry"] * 3
               + ["Child of the Elder Blood"] * 2 + ["Unicorn ally"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 344)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_rest, orb) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
        assert all(("source" in e.get("tags", [])) is orb for e in entries), title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert sum(1 for e in sheet if "source" in e.get("tags", [])) == 13
    assert overlay["sidekicks"] == [{"fid": "ihuarraquax", "name": "Ihuarraquax"}] and overlay["forms"] is None
    assert overlay["counters"] == {"source": {"pile": "discard", "tag": "source"}}


def test_generated_herodef_is_a_melee_hero_with_a_sidekick_a_counter_and_deals_a_real_deck():
    h = load_hero("ciri")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Ciri", "ciri", 15, 2, False, 0)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("ihuarraquax", "Ihuarraquax", 1, 7, 2, False)]
    assert [f.fid for f in h.fighters()] == ["ciri", "ihuarraquax"]
    assert h.ability == "UNCONTAINABLE POWER\nSOURCE 7: Effects on Ciri's cards cannot be canceled."
    assert set(h.counters) == {"source"} and h.counters["source"].pile == "discard" and h.counters["source"].tag == "source"
    assert h.forms is None
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost, orb = REAL_CARDS[c.title]
        assert (c.fighter.lower() if fighter == "any" else c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
        assert ("source" in c.tags) is orb, c.title
    assert next(c for c in deck if c.title == "Unicorn ally").text.endswith("if you have 5 or more cards in your hand.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("ciri").ai_profile
    assert set(profile) == {"ciri", "ihuarraquax"} and profile["ciri"]["role"] == "hero" and not profile["ciri"]["ranged"]
    assert {e["title"] for e in profile["ciri"]["exclusive"]} | {e["title"] for e in profile["ihuarraquax"]["exclusive"]} <= set(REAL_CARDS)


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "ciri"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert (card["title"] == "Unicorn ally") == bool(card.get("ongoing")) and not card.get("may_boost")
    assert [p["id"] for p in effects["plugins"]] == ["ciri:channel_the_source"]


def test_the_ability_is_a_passive_rule_that_holds_while_the_source_is_seven(effects):
    passive, = effects["ability"]["passives"]
    assert passive == {"id": "uncontainable_power", "kind": "rule", "rule": "cards_uncancelable",
                       "while": {"test": "counter", "name": "source", "min": 7}}
    assert effects["ability"]["triggers"] == []


def thresholds(ops):
    """The Source thresholds of a tier chain, highest first."""
    out = []
    while ops:
        node, = ops
        out.append(node["condition"]["min"])
        ops = node.get("else")
    return out


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert thresholds(by["Pushed to the brink"]["after"]) == [7, 2]
    assert thresholds(by["Zireael"]["during"]) == [5, 3]
    assert thresholds(by["Lion cub of Cintra"]["during"]) == [5, 1]
    assert thresholds(by["Child of the Elder Blood"]["scheme"]) == [9, 4]
    assert thresholds(by["The lady of space and time"]["after"]) == [8, 3]
    assert by["Lion cub of Cintra"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 7}]
    assert by["Parry"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Blink"]["after"] == [{"op": "move", "target": "hero", "amount": 3, "up_to": True, "through_enemies": True, "chooser": "owner"}]
    bane = by["Bane of the Aen Elle"]["after"]
    assert bane[0]["target"] == "this" and bane[0]["amount"] == 4 and bane[0]["through_enemies"]
    assert bane[1] == {"op": "damage", "target": {"side": "enemy", "filter": {"passed_by": "$mover"}}, "amount": 1, "chooser": "owner"}
    assert by["Channel the source"]["during"] == [{"op": "plugin", "id": "ciri:channel_the_source"}]
    assert by["Unicorn ally"]["scheme"] == [{"op": "heal", "target": "hero", "amount": 2}]
    search = by["Searching strike"]["after"][0]
    assert search["condition"] == {"test": "combat_result", "result": "won"}
    assert search["then"][0]["op"] == "optional" and search["then"][0]["ops"][0]["take"]["filter"] == {"tag": "source"}


def test_unicorn_ally_draws_after_every_combat_and_discards_itself_with_five_cards(effects):
    unicorn = next(c for c in effects["cards"] if c["title"] == "Unicorn ally")
    draw, leaves = unicorn["ongoing"]["triggers"]
    assert draw["when"] == {"event": "after_attack", "fighter": {"side": "any"}}
    assert draw["ops"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert leaves["when"] == {"event": "end_of_turn", "player": "owner"}
    assert leaves["condition"] == {"test": "compare", "left": {"stat": "hand_size"}, "op": ">=", "right": 5}


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "ciri" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 344
    assert set(tts["fighters"]) == {"ciri", "ihuarraquax"}
    assert (tts["fighters"]["ciri"]["dial_max"], tts["fighters"]["ihuarraquax"]["dial_max"]) == (15, 7)
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"], tts["fighters"]["ciri"]["piece"], tts["fighters"]["ciri"]["dial"],
            tts["fighters"]["ihuarraquax"]["piece"], tts["fighters"]["ihuarraquax"]["dial"]) == (
        "45ae7e", "f2c999", "9bd73c", "f6fea4", "e6da98", "4ec239", "341412")
    assert tts["tokens"] == {} and tts["counter_dials"] == {"source": "46aa92"}          # the Source dial: MAX_VALUE 13, a Custom_Model like Hellboy's


def test_the_source_dial_reaches_the_session_defaults_on_either_side():
    for bot, human in (("ciri", "hellboy"), ("hellboy", "ciri"), ("ciri", "medusa"), ("medusa", "ciri")):
        defaults = table_defaults(bot, human)
        assert defaults["source_dial"] == "46aa92"
        assert ("destiny_dial" in defaults) is ("hellboy" in (bot, human))
    assert "source_dial" not in table_defaults("hellboy", "medusa")


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_ciri_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    ciri, theirs = load_hero_table("ciri"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert ciri.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(ciri.identity) & set(theirs.identity)
    for bot, human in (("ciri", other), (other, "ciri")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_ciri_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("ciri").deck()) & set(load_hero(other).deck())


def test_ciri_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero("ciri").deck())
    assert all(c not in set(load_hero("ciri").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("ciri", "ciri")


def test_ciri_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("ciri"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("ciri", other)
        assert detect_heroes(reading(at_bot(other), at_human("ciri")), BOT_SPOT, HUMAN_SPOT) == (other, "ciri")


def test_the_catalog_names_ciri_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("ciri") == "Ciri"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("ciri").identity]).slug == "ciri"


def test_ciris_guids_are_nobody_elses():
    mine = set(load_hero_table("ciri").all_guids())
    for path in HEROES_DIR.parent.joinpath("tts").glob("*.json"):
        if path.stem != "ciri":
            assert not mine & set(load_hero_table(path.stem).all_guids()), path.stem
