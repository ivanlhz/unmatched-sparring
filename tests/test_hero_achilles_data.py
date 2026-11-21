"""Achilles' data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 176 of the tournament save (read from the images on 2026-11-20), and his deck is told apart from the other decks of the sheet
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

OVERLAY = HEROES_DIR / "overlay" / "achilles.json"
EFFECTS = HEROES_DIR / "effects" / "achilles.json"
TTS_DIR = HEROES_DIR.parent / "tts"
TTS = TTS_DIR / "achilles.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")


def _sharing() -> list[str]:
    """Every other hero whose deck is sheet 176 (CardIDs from 17600); one variant of Yennefer & Triss stands for both (same images)."""
    out = []
    for path in sorted(TTS_DIR.glob("*.json")):
        slug = path.stem
        if slug in ("achilles", "triss-yennefer") or load_hero_table(slug).card_ids[0] != 17600:
            continue
        out.append(slug)
    return out


SHARING = _sharing()
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Brothers In Arms": (3, "any", "attack", 4, 2),
    "Test For Weakness": (3, "any", "attack", 1, 3),
    "Battle Frenzy": (2, "Patroclus", "attack", 3, 2),
    "The Day of Your Doom": (2, "Patroclus", "attack", 3, 2),
    "Battle Hardened": (2, "any", "versatile", 2, 2),
    "Wily Fighting": (2, "any", "versatile", 3, 1),
    "Skirmish": (3, "any", "versatile", 4, 1),
    "Feint": (3, "any", "versatile", 2, 1),
    "Blessed By Hermes": (2, "any", "versatile", 3, 1),
    "Achilles' Heel": (3, "Achilles", "defense", 4, 2),
    "Under Achilles' Helm": (3, "Achilles", "defense", 2, 4),
    "Spear Throw": (2, "Achilles", "scheme", None, 1),
}
SHEET_ORDER = (["Brothers In Arms"] * 3 + ["Test For Weakness"] * 3 + ["Battle Frenzy"] * 2 + ["The Day of Your Doom"] * 2
               + ["Battle Hardened"] * 2 + ["Wily Fighting"] * 2 + ["Skirmish"] * 3 + ["Feint"] * 3 + ["Blessed By Hermes"] * 2
               + ["Achilles' Heel"] * 3 + ["Under Achilles' Helm"] * 3 + ["Spear Throw"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 318)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "patroclus", "name": "Patroclus"}] and overlay["fid"] == "achilles"
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == []
    assert overlay["passives"] == [{"id": "vengeance", "effect": "sidekick_defeated_bonus", "sidekick": "patroclus", "n": 2}]


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("achilles")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Achilles", "achilles", 18, 2, False)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("patroclus", "Patroclus", 1, 6, 2, False)]
    assert h.ability.splitlines()[0] == "When Patroclus is defeated, discard 2 random cards."
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert sum(1 for c in deck if c.fighter == "Patroclus") == 4


def test_effects_validate_and_every_card_says_what_it_prints(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "achilles"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert "achilles:replace_combatant" in [p["id"] for p in effects["plugins"]]


def test_the_ability_is_a_trigger_and_two_passives_on_patroclus_being_defeated(effects):
    ability = effects["ability"]
    trigger, = ability["triggers"]
    assert trigger["when"] == {"event": "fighter_defeated", "fighter": {"side": "own", "name": "Patroclus"}}
    assert trigger["ops"] == [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "random", "amount": 2}}]
    bonus, = ability["passives"]
    assert (bonus["kind"], bonus["amount"], bonus["cards"]) == ("modify_value", 2, {"player": "owner", "type": "attack", "fighter": "hero"})
    assert bonus["while"] == {"not": {"test": "exists", "fighters": {"side": "own", "name": "Patroclus"}}}
    draw, = ability["after"]
    assert draw["ops"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert {"test": "combat_result", "result": "won"} in draw["condition"]["all"]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    patroclus = {"side": "own", "name": "Patroclus"}
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    heel, = by["Achilles' Heel"]["after"]
    assert heel["condition"] == {"test": "combat_result", "result": "lost"}
    assert heel["then"] == [{"op": "gain_action", "amount": 1, "player": "opponent"}]
    arms, = by["Brothers In Arms"]["after"]
    assert arms["condition"] == {"test": "exists", "fighters": patroclus} and arms["then"] == [{"op": "gain_action", "amount": 1}]
    helm, = by["Under Achilles' Helm"]["immediately"]
    swap = helm["then"][0]["ops"]
    assert helm["condition"] == {"test": "exists", "fighters": patroclus}
    assert [o["op"] for o in swap] == ["swap", "plugin"] and swap[0]["with"] == patroclus and swap[1]["id"] == "achilles:replace_combatant"
    doom, = by["The Day of Your Doom"]["during"]
    assert doom["cost"] == [{"op": "damage", "target": patroclus, "amount": 2}]
    assert doom["ops"] == [{"op": "set_value", "card": "this", "amount": 5}]
    assert by["Battle Frenzy"]["after"] == [{"op": "damage", "target": {"role": "combatant", "pick": "all"}, "amount": 2}]
    assert by["Spear Throw"]["scheme"][0]["target"] == {"side": "enemy", "where": {"zone_of": "hero"}}
    assert by["Wily Fighting"]["after"][0]["target"]["where"] == {"adjacent_to": "this"}
    assert by["Blessed By Hermes"]["after"][0]["through_enemies"] is True and by["Blessed By Hermes"]["after"][0]["amount"] == 3
    assert by["Battle Hardened"]["after"][0]["op"] == "put_in_hand"
    assert by["Skirmish"]["after"][0]["then"][0]["target"] == "combatant"
    assert by["Test For Weakness"]["after"] == [{"op": "second_attack", "amount": 3}]          # RELENTLESS ASSAULT: the double attack (section 45)


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "achilles" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 318
    assert set(tts["fighters"]) == {"achilles", "patroclus"}
    assert (tts["fighters"]["achilles"]["dial_max"], tts["fighters"]["patroclus"]["dial_max"]) == (18, 6)
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("e9df2a", "42ac50", "70a2b2")
    assert (tts["fighters"]["achilles"]["piece"], tts["fighters"]["achilles"]["dial"]) == ("6b0ddb", "feaa22")
    assert (tts["fighters"]["patroclus"]["piece"], tts["fighters"]["patroclus"]["dial"]) == ("978237", "ec605e")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

def test_the_sheet_has_other_decks_to_share_with():
    assert {"medusa", "eredin", "sinbad", "yennefer-triss"} <= set(SHARING)


@pytest.mark.parametrize("other", SHARING)
def test_achilles_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    achilles, theirs = load_hero_table("achilles"), load_hero_table(other)
    assert achilles.card_ids == (17600, 17629) and theirs.card_ids[0] == 17600
    assert not set(achilles.identity) & set(theirs.identity)
    for bot, human in (("achilles", other), (other, "achilles")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_achilles_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("achilles").deck()) & set(load_hero(other).deck())


def test_achilles_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("achilles").deck())
    assert all(c not in set(load_hero("achilles").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("achilles", "achilles")


def test_achilles_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("achilles"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("achilles", other)
        assert detect_heroes(reading(at_bot(other), at_human("achilles")), BOT_SPOT, HUMAN_SPOT) == (other, "achilles")


def test_the_catalog_names_achilles_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("achilles") == "Achilles"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("achilles").identity]).slug == "achilles"


def test_no_guid_of_achilles_is_shared_with_another_hero():
    mine = set(load_hero_table("achilles").all_guids())
    for slug in [p.stem for p in TTS_DIR.glob("*.json") if p.stem != "achilles"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
