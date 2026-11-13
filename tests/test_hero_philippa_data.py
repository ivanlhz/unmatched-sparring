"""Philippa's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 176 of the tournament save (read from the images on 2026-11-13), and her deck is told apart from the other decks of the sheet
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

OVERLAY = HEROES_DIR / "overlay" / "philippa.json"
EFFECTS = HEROES_DIR / "effects" / "philippa.json"
TTS_DIR = HEROES_DIR.parent / "tts"
TTS = TTS_DIR / "philippa.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")


def _sharing() -> list[str]:
    """Every other hero whose deck is sheet 176 (CardIDs from 17600); one variant of Yennefer & Triss stands for both (same images)."""
    out = []
    for path in sorted(TTS_DIR.glob("*.json")):
        slug = path.stem
        if slug in ("philippa", "triss-yennefer") or load_hero_table(slug).card_ids[0] != 17600:
            continue
        out.append(slug)
    return out


SHARING = _sharing()
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Owlform": (3, "Philippa", "attack", 3, 3),
    "Lightning bolt": (3, "Philippa", "attack", 3, 1),
    "Chain lightning": (2, "Philippa", "attack", 2, 3),
    "Regicide": (2, "any", "attack", 4, 2),
    "Spellbreaker": (3, "Philippa", "versatile", 2, 2),
    "Cunning": (2, "any", "versatile", 4, 1),
    "Redanian plot": (3, "any", "versatile", 2, 1),
    "Paralyzing fetters": (2, "Philippa", "defense", 2, 3),
    "Blinding dust": (2, "Philippa", "defense", 2, 2),
    "Do my bidding": (2, "any", "defense", 3, 3),
    "Polymorphy": (2, "Philippa", "scheme", None, 3),
    "Backup plan": (2, "Philippa", "scheme", None, 2),
    "Spymaster's ruse": (2, "Dijkstra", "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Owlform"] * 3 + ["Lightning bolt"] * 3 + ["Chain lightning"] * 2 + ["Regicide"] * 2 + ["Spellbreaker"] * 3
               + ["Cunning"] * 2 + ["Redanian plot"] * 3 + ["Paralyzing fetters"] * 2 + ["Blinding dust"] * 2 + ["Do my bidding"] * 2
               + ["Polymorphy"] * 2 + ["Backup plan"] * 2 + ["Spymaster's ruse"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 349)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "dijkstra", "name": "Dijkstra"}] and overlay["forms"] is None
    assert overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []
    assert next(e for e in sheet if e["title"] == "Polymorphy")["text"].endswith(
        "Discard this card at the end of your turn if Philippa is not in a zone with an opposing fighter.")


def test_generated_herodef_is_a_ranged_hero_with_dijkstra_and_deals_a_real_deck():
    h = load_hero("philippa")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Philippa", "philippa", 12, 2, True, 0)
    assert [(s.fid, s.name, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("dijkstra", "Dijkstra", 6, 2, False)]
    assert h.ability.startswith("TWO STEPS AHEAD") and "hand of 4 cards" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("philippa").ai_profile
    assert set(profile) == {"philippa", "dijkstra"} and profile["philippa"]["role"] == "hero" and profile["philippa"]["ranged"]
    assert {e["title"] for e in profile["dijkstra"]["exclusive"]} == {"Spymaster's ruse"}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "philippa"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert (card["title"] == "Polymorphy") == (card.get("ongoing") is not None)
    assert sorted(p["id"] for p in effects["plugins"]) == [
        "philippa:blinding_dust", "philippa:chain_lightning", "philippa:do_my_bidding", "philippa:owlform", "philippa:spymaster_ruse"]


def test_the_ability_draws_up_to_four_at_the_end_of_her_turn(effects):
    (trigger,) = effects["ability"]["triggers"]
    assert trigger["when"] == {"event": "end_of_turn", "player": "owner"}
    assert trigger["condition"] == {"test": "compare", "left": {"stat": "hand_size", "player": "owner"}, "op": "<", "right": 4}
    assert trigger["ops"] == [{"op": "optional", "chooser": "owner", "ops": [{"op": "draw", "player": "owner", "amount": {"hand_deficit": 4}}]}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Paralyzing fetters"]["immediately"] == [{"op": "lock_value", "card": "opponent_card"}]
    assert by["Spellbreaker"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}] and by["Spellbreaker"]["after"] == [{"op": "end_turn"}]
    assert by["Regicide"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 6}]
    assert by["Regicide"]["during"][0]["condition"] == {"test": "exists", "fighters": {"role": "opposing", "kind": "hero"}}
    assert by["Cunning"]["after"][0]["else"] == [{"op": "damage", "target": "opposing", "amount": 2}]
    assert by["Redanian plot"]["immediately"][0]["else"] == [{"op": "set_value", "card": "opponent_card", "ignore": True}]
    assert by["Lightning bolt"]["after"][0]["condition"]["right"] == 0
    assert by["Polymorphy"]["scheme"] == [{"op": "place", "target": "hero", "where": {"any": True}, "chooser": "owner"}]
    (choice,) = by["Backup plan"]["scheme"]
    assert [o["ops"] for o in choice["options"]] == [[{"op": "set_hp", "target": "hero", "amount": 5}], [{"op": "draw", "player": "owner", "amount": 3}]]
    assert by["Spymaster's ruse"]["scheme"][1] == {"op": "draw", "player": "opponent", "amount": 2}


def test_polymorphy_ongoing_sets_the_move_value_and_lapses_without_a_foe_in_her_zone(effects):
    card = next(c for c in effects["cards"] if c["title"] == "Polymorphy")
    assert card["ongoing"]["modifiers"] == [{"kind": "rule", "rule": "hero_move", "amount": 5}]
    assert card["ongoing"]["until"] == {"event": "end_of_turn", "player": "owner"}
    assert card["ongoing"]["until_condition"] == {"not": {"test": "exists", "fighters": {"side": "enemy", "where": {"zone_of": "hero"}}}}


def test_paralyzing_fetters_is_word_for_word_the_card_other_heroes_print(effects):
    mine = next(c for c in effects["cards"] if c["title"] == "Paralyzing fetters")
    theirs = next(c for c in json.loads((HEROES_DIR / "effects" / "yennefer-triss.json").read_text(encoding="utf-8"))["cards"]
                  if c["title"] == "Paralyzing fetters")
    assert mine["text"] == theirs["text"] and mine["effects"] == theirs["effects"]


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "philippa" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 349
    assert set(tts["fighters"]) == {"philippa", "dijkstra"}
    assert (tts["fighters"]["philippa"]["dial_max"], tts["fighters"]["dijkstra"]["dial_max"]) == (12, 6)
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("4dc6f9", "859216", "ea91d3")
    assert (tts["fighters"]["philippa"]["piece"], tts["fighters"]["philippa"]["dial"]) == ("e91869", "684429")
    assert (tts["fighters"]["dijkstra"]["piece"], tts["fighters"]["dijkstra"]["dial"]) == ("c97270", "ec1f51")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

def test_the_sheet_has_other_decks_to_share_with():
    assert {"medusa", "eredin", "sinbad", "yennefer-triss"} <= set(SHARING)


@pytest.mark.parametrize("other", SHARING)
def test_philippa_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    philippa, theirs = load_hero_table("philippa"), load_hero_table(other)
    assert philippa.card_ids == (17600, 17629) and theirs.card_ids[0] == 17600
    assert not set(philippa.identity) & set(theirs.identity)
    for bot, human in (("philippa", other), (other, "philippa")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_philippa_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("philippa").deck()) & set(load_hero(other).deck())


def test_philippa_cards_are_never_medusas_and_medusas_never_hers():
    assert not any(is_medusa_card(c) for c in load_hero("philippa").deck())
    assert all(c not in set(load_hero("philippa").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("philippa", "philippa")


def test_philippa_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("philippa"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("philippa", other)
        assert detect_heroes(reading(at_bot(other), at_human("philippa")), BOT_SPOT, HUMAN_SPOT) == (other, "philippa")


def test_the_catalog_names_philippa_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("philippa") == "Philippa"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("philippa").identity]).slug == "philippa"


def test_no_guid_of_philippa_is_shared_with_another_hero():
    mine = set(load_hero_table("philippa").all_guids())
    for slug in [p.stem for p in TTS_DIR.glob("*.json") if p.stem != "philippa"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug
