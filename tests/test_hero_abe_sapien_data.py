"""Datos de Abe Sapien (F07/F08, solo datos): overlay con hoja 194 verificada contra la imagen del save, HeroDef
generado, y la especificacion de efectos data/heroes/effects/abe-sapien.json con el vocabulario comun del DSL."""
import json
from pathlib import Path

import pytest

from sparring.heroes import HEROES_DIR, load_hero

OVERLAY = HEROES_DIR / "overlay" / "abe-sapien.json"
EFFECTS = HEROES_DIR / "effects" / "abe-sapien.json"

VOCABULARY = {"damage", "heal", "draw", "discard", "discard_random", "move", "place", "push", "swap", "revive",
              "cancel_effects", "modify_value", "status", "counter", "persistent_scheme", "look_hand", "reveal",
              "choose_n", "optional", "if", "for_each", "gain_action", "search_deck", "return_to_deck", "plugin"}
MOMENTS = ("immediately", "during", "after", "scheme", "boost")

# (titulo, copias, tipo, valor, boost, restriccion) leidos de la hoja 194 del save el 2026-10-28
SHEET = [
    ("Faster. Stronger.", 2, "attack", 5, 2, "Abe Sapien"),
    ("Advanced Psychometry", 3, "attack", 4, 3, "Abe Sapien"),
    ("Perfect Shot", 2, "attack", 3, 2, "Abe Sapien"),
    ("Secure The Scene", 3, "attack", 3, 3, "B.P.R.D. Agent"),
    ("Leap Away", 2, "versatile", 4, 2, "any"),
    ("Concussion Device", 2, "versatile", 2, 1, "any"),
    ("Arcane Dampener", 2, "versatile", 2, 1, "any"),
    ("B.P.R.D. Training", 2, "versatile", 3, 1, "any"),
    ("Shock And Awe", 2, "versatile", 2, 2, "any"),
    ("Cold Iron And Holy Water", 2, "versatile", 3, 2, "any"),
    ("Ward And Prepare", 2, "defense", 2, 1, "any"),
    ("Every Possible Angle", 2, "scheme", None, 4, "Abe Sapien"),
    ("Counterhex Shield", 2, "scheme", None, 2, "Abe Sapien"),
    ("B.P.R.D. Utility Belt", 2, "scheme", None, 3, "Abe Sapien"),
]


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def walk_ops(ops):
    """Todas las ops, incluidas las anidadas en then/else/ops de if, for_each, optional y persistent_scheme."""
    for op in ops:
        yield op
        for key in ("then", "else", "ops"):
            yield from walk_ops(op.get(key, ()))


def test_overlay_sheet_is_the_tts_sheet_194_with_the_right_copies_and_restrictions(overlay):
    deck = overlay["deck"]
    assert deck["card_base"] == 19400 and deck["sheet_id"] == 194
    assert [e["idx"] for e in deck["sheet"]] == list(range(30))
    for title, copies, _, _, _, fighter in SHEET:
        entries = [e for e in deck["sheet"] if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for _, c, *_ in SHEET) == 30


def test_overlay_sidekicks_and_triggers(overlay):
    (agent,) = overlay["sidekicks"]
    assert (agent["fid"], agent["name"], agent["count"], agent["hp"], agent["move"], agent["attack"]) == \
        ("agent", "B.P.R.D. Agent", 3, 1, 2, "range")
    assert agent["start_on_board"] + agent["reserve"] == agent["count"]
    assert len(agent["tts_tokens"]) == agent["count"]
    assert overlay["forms"] is None and overlay["counters"] == {}
    assert {t["id"] for t in overlay["triggers"]} == {"intuition_activate", "intuition_spend"}
    assert {t["when"] for t in overlay["triggers"]} == {"combat_damage_dealt", "attacked"}


def test_generated_herodef_deals_the_deck_with_real_cardids_values_and_fighters():
    h = load_hero("abe-sapien")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Abe Sapien", "abe", 13, 2, True)
    assert [f.fid for f in h.fighters()] == ["abe", "agent1", "agent2", "agent3"]
    assert all(not f.hero and f.hp == 1 and f.move == 2 and f.ranged for f in h.fighters()[1:])
    deck = h.deck()
    assert len(deck) == 30 and sorted(c.card_id for c in deck) == list(range(19400, 19430))
    for title, copies, type_, value, boost, fighter in SHEET:
        cards = [c for c in deck if c.title == title]
        assert len(cards) == copies, title
        assert {(c.type, c.value, c.boost, c.fighter) for c in cards} == {(type_, value, boost, fighter)}, title
    assert "Intuition tokens" in h.ability
    assert h.card_base + 0 == deck[0].card_id and deck[0].title == "Faster. Stronger."


def test_every_deck_card_has_an_effects_entry_and_nothing_else(effects):
    assert effects["hero"] == "abe-sapien"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(t for t, *_ in SHEET)
    assert len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert set(card["effects"]) == set(MOMENTS), card["title"]
        assert card["text"].strip() and card["notes"].strip(), card["title"]


def test_effects_use_only_the_common_vocabulary_or_declared_primitives_and_plugins(effects):
    declared = {p["op"] for p in effects["primitives_needed"]}
    plugin_ids = {p["id"] for p in effects["plugins"]}
    allowed = VOCABULARY | declared
    all_ops = list(walk_ops(effects["ability"]["ops"]))
    for trig in effects["ability"]["triggers"]:
        all_ops += list(walk_ops(trig["ops"]))
    for card in effects["cards"]:
        for moment in MOMENTS:
            all_ops += list(walk_ops(card["effects"][moment]))
    assert all_ops, "sin ops"
    for op in all_ops:
        assert op["op"] in allowed, op
        if op["op"] == "plugin":
            assert op["id"] in plugin_ids and op["id"].startswith("abe:"), op
    used = {op["op"] for op in all_ops}
    assert {"look_hand", "revive", "persistent_scheme", "return_to_deck"} <= used
    for p in effects["primitives_needed"]:
        assert p["spec"].strip(), p["op"]


def test_perfect_shot_is_the_only_plugin_and_uncanny_intuition_fits_in_primitives(effects):
    assert [p["id"] for p in effects["plugins"]] == ["abe:perfect_shot"]
    cards_with_plugin = {c["title"] for c in effects["cards"]
                         if any(op["op"] == "plugin" for m in MOMENTS for op in walk_ops(c["effects"][m]))}
    assert cards_with_plugin == {"Perfect Shot"}
    spend = next(t for t in effects["ability"]["triggers"] if t["id"] == "intuition_spend")
    assert [op["op"] for op in spend["ops"]] == ["counter", "draw", "reveal"]
    assert effects["ability"]["tokens"]["intuition"]["total"] == 2


def test_hidden_information_effects_are_all_listed_with_a_bot_rule(effects):
    listed = {h["card"] for h in effects["hidden_info"]}
    for card in effects["cards"]:
        ops = [op for m in MOMENTS for op in walk_ops(card["effects"][m])]
        if any(op["op"] in ("look_hand", "reveal") for op in ops):
            assert card["title"] in listed, card["title"]
    assert "UNCANNY INTUITION" in listed and "Perfect Shot" in listed
    assert all(h["bot_rule"].strip() for h in effects["hidden_info"])
    assert effects["open_questions"] and effects["discrepancies"]


def test_counterhex_shield_keeps_the_real_ongoing_text_in_effects_and_in_the_dealt_deck(effects):
    card = next(c for c in effects["cards"] if c["title"] == "Counterhex Shield")
    assert "Ongoing" in card["text"] and "Discard this at the start of your next turn" in card["text"]
    assert any(op["op"] == "persistent_scheme" for op in card["effects"]["scheme"])
    dealt = [c for c in load_hero("abe-sapien").deck() if c.title == "Counterhex Shield"]
    assert len(dealt) == 2 and all(c.text == card["text"] for c in dealt)   # el overlay manda sobre unmatched-memory
