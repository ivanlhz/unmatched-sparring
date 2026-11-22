"""Sherlock Holmes' data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of sheet 176
of the tournament save (read from the images on 2026-11-22: the 30 cards, their bands and the hero card 304 on sheet 3), and his deck is told apart from the
other decks of the sheet (same CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_card_identity import SHARING as SHARING_ALL
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

SLUG = "sherlock-holmes"
OVERLAY = HEROES_DIR / "overlay" / f"{SLUG}.json"
EFFECTS = HEROES_DIR / "effects" / f"{SLUG}.json"
TTS = HEROES_DIR.parent / "tts" / f"{SLUG}.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = [s for s in SHARING_ALL if s != SLUG]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
H, W = "Sherlock Holmes", "Dr. Watson"

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "The Game is Afoot": (2, H, "attack", 5, 2),
    "Service Revolver": (2, W, "attack", 5, 3),
    "Deduce Strategy": (3, H, "versatile", 3, 1),
    "Counterpunch": (3, H, "versatile", 3, 1),
    "Study Methods": (2, "any", "versatile", 3, 2),
    "Education Never Ends": (2, "any", "versatile", 3, 1),
    "Feint": (3, "any", "versatile", 2, 1),                          # unmatched-memory files the effect under DURING; the card reads IMMEDIATELY
    "Fixed Point in a Changing Age": (2, W, "versatile", 3, 1),
    "Elementary": (2, H, "defense", 3, 3),
    "Master of Disguise": (2, H, "scheme", None, 2),
    "Confirm Suspicion": (3, H, "scheme", None, 1),
    "Eliminate the Impossible": (2, H, "scheme", None, 2),
    "Administer Aid": (2, W, "scheme", None, 2),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["The Game is Afoot"] * 2 + ["Service Revolver"] * 2 + ["Deduce Strategy"] * 3 + ["Counterpunch"] * 3 + ["Study Methods"] * 2
               + ["Education Never Ends"] * 2 + ["Feint"] * 3 + ["Fixed Point in a Changing Age"] * 2 + ["Elementary"] * 2 + ["Master of Disguise"] * 2
               + ["Confirm Suspicion"] * 3 + ["Eliminate the Impossible"] * 2 + ["Administer Aid"] * 2)
BANDED = {t for t, (_, band, *_rest) in REAL_CARDS.items() if band != "any"}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 304)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_only_the_feints_carry_the_tag_that_tells_them_from_the_other_decks_feints(overlay):
    tagged = [e["title"] for e in overlay["deck"]["sheet"] if e.get("tags")]
    assert tagged == ["Feint"] * 3 and all(e["tags"] == ["sherlock"] for e in overlay["deck"]["sheet"] if e["title"] == "Feint")


def test_generated_herodef_is_a_melee_hero_with_a_ranged_doctor_watson_on_the_board():
    h = load_hero(SLUG)
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == (H, "holmes", 16, 2, False, 0)
    watson, = h.sidekicks
    assert (watson.fid, watson.name, watson.count, watson.hp, watson.move, watson.ranged, watson.start_on_board) == ("watson", W, 1, 8, 2, True, None)
    assert [(f.fid, f.on_board) for f in h.fighters()] == [("holmes", True), ("watson", True)]
    assert h.ability.startswith("Effects on HOLMES and DR. WATSON cards cannot be canceled")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title


def test_generated_herodef_is_the_importers_output():
    from tools.import_hero import build, render
    from pathlib import Path
    import os
    memory = Path(os.environ.get("UNMATCHED_MEMORY", ""))
    if not (memory / "data" / "heroes" / "sherlock-holmes.json").exists():
        pytest.skip("unmatched-memory is not available")
    assert (HEROES_DIR / f"{SLUG}.json").read_text(encoding="utf-8") == render(build(SLUG, memory))


def test_the_card_texts_are_the_real_ones():
    by = {c.title: c for c in load_hero(SLUG).deck()}
    assert by["Feint"].text == "IMMEDIATELY: Cancel all effects on your opponent's card."
    assert by["Elementary"].text.startswith("Play this card face up. Predict the printed attack value of the opponent's card.")
    assert by["Counterpunch"].text == "AFTER COMBAT: If Holmes is adjacent to the opposing fighter, deal 2 damage to that fighter."


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero(SLUG).ai_profile
    assert set(profile) == {"holmes", "watson"} and profile["holmes"]["role"] == "hero" and not profile["holmes"]["ranged"]
    assert profile["watson"]["max_hp"] == 8 and profile["watson"]["ranged"]


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == SLUG
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS) or card["title"] == "Service Revolver", card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert sorted(p["id"] for p in effects["plugins"]) == ["holmes:confirm_suspicion", "holmes:deduce_strategy", "holmes:elementary"]


def test_the_ability_every_holmes_and_watson_card_is_uncancelable_and_no_any_card_is(effects):
    """"Effects on HOLMES and DR. WATSON cards cannot be canceled by an opponent; effects on ANY cards can be.\""""
    uncancelable = {c["title"] for c in effects["cards"] if c.get("uncancelable")}
    assert uncancelable == BANDED
    assert not {"Feint", "Education Never Ends", "Study Methods"} & uncancelable


def test_elementary_is_a_prediction_then_a_forced_cancel_and_an_ignored_value(effects):
    card = next(c for c in effects["cards"] if c["title"] == "Elementary")["effects"]
    assert card["immediately"] == [{"op": "plugin", "id": "holmes:elementary"}]
    cond = {"test": "plugin", "id": "holmes:elementary", "key": "predicted_correctly"}
    assert card["during"] == [{"op": "if", "condition": cond, "then": [
        {"op": "cancel_effects", "card": "opponent_card", "force": True}, {"op": "set_value", "card": "opponent_card", "ignore": True}]}]


def test_master_of_disguise_does_no_damage_when_the_swap_did_not_happen(effects):
    scheme = next(c for c in effects["cards"] if c["title"] == "Master of Disguise")["effects"]["scheme"]
    assert scheme[0]["op"] == "swap" and scheme[0]["as"] == "swapped"
    assert scheme[1]["op"] == "if" and scheme[1]["condition"]["fighters"] == {"role": "$swapped", "side": "enemy"}
    assert scheme[1]["then"] == [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 1}]


def test_table_data_names_the_pieces_the_dials_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == SLUG and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 304
    assert set(tts["fighters"]) == {"holmes", "watson"} and tts["fighters"]["holmes"]["dial_max"] == 16 and tts["fighters"]["watson"]["dial_max"] == 8
    assert (tts["bag"]["guid"], tts["deck"]["guid"]) == ("248c8e", "9b3289")
    assert {k: (v["piece"], v["dial"]) for k, v in tts["fighters"].items()} == {"holmes": ("7c5cc7", "feaa22"), "watson": ("c0fd6e", "ec605e")}
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_sherlock_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    mine, theirs = load_hero_table(SLUG), load_hero_table(other)
    assert mine.card_ids == (17600, 17629) and theirs.card_ids[0] in (17600, 18700)
    if theirs.card_ids[0] == 17600:
        assert not set(mine.identity) & set(theirs.identity)
        for bot, human in ((SLUG, other), (other, SLUG)):
            defaults = table_defaults(bot, human)
            assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
            assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_sherlock_equals_a_card_of_the_other_decks(other):
    assert not set(load_hero(SLUG).deck()) & set(load_hero(other).deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults(SLUG, SLUG)


def test_sherlock_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot(SLUG), at_human(other)), BOT_SPOT, HUMAN_SPOT) == (SLUG, other)
        assert detect_heroes(reading(at_bot(other), at_human(SLUG)), BOT_SPOT, HUMAN_SPOT) == (other, SLUG)


def test_the_catalog_names_sherlock_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of(SLUG) == H
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table(SLUG).identity]).slug == SLUG


def test_sherlock_shares_only_the_two_dial_guids_with_achilles_and_patroclus():
    """The deck and the two miniatures are his; the dials of Holmes (feaa22) and Watson (ec605e) are Achilles' and Patroclus' (Custom_Models named
    after their fighter: told apart by name, tests/test_piece_identity.py)."""
    mine = set(load_hero_table(SLUG).all_guids())
    assert len(mine) == 5
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != SLUG]:
        for g in mine & set(load_hero_table(slug).all_guids()):
            shared.setdefault(g, []).append(slug)
    assert shared == {"feaa22": ["achilles"], "ec605e": ["achilles"]}
