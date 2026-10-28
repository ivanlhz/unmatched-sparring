"""Datos de Hellboy (F07, caja Hellboy): el overlay y el HeroDef generado describen el mazo real de la hoja 197, y
data/heroes/effects/hellboy.json cubre cada carta solo con ops del vocabulario comun o declaradas. Sin FakeTTS."""
import json
import re

from sparring.board import DATA_DIR
from sparring.heroes import HEROES_DIR, load_hero
from sparring.play import load_config

OVERLAY = HEROES_DIR / "overlay" / "hellboy.json"
EFFECTS = HEROES_DIR / "effects" / "hellboy.json"
CONFIG = DATA_DIR.parent / "config" / "partida.json"

VOCABULARY = frozenset({
    "damage", "heal", "draw", "discard", "discard_random", "move", "place", "push", "swap", "revive", "cancel_effects",
    "modify_value", "status", "counter", "persistent_scheme", "look_hand", "reveal", "choose_n", "optional", "if",
    "for_each", "gain_action", "search_deck", "return_to_deck"})
SLOTS = frozenset({"immediately", "during", "after", "scheme", "boost"})

# Leido de las imagenes de la hoja 197 el 2026-10-28 (copias impresas en cada carta): (copias, destiny, luchador)
EXPECTED = {
    "Excalibur": (1, True, "Hellboy"),
    "Right Hand Of Doom": (4, True, "Hellboy"),
    "Service Pistol": (1, False, "any"),
    "Horseshoes And Hand Grenades": (3, False, "any"),
    "Second Shot": (2, False, "Lobster Johnson"),
    "Confront Any Demon or God": (2, True, "Hellboy"),
    "Glimpse Of Hell": (3, False, "any"),
    "B.P.R.D. Training": (3, False, "any"),
    "Planned Recklessness": (2, False, "any"),
    "Posthumous Power": (3, False, "Lobster Johnson"),
    "On Earth As It Is In Hell": (2, True, "Hellboy"),
    "And Upon His Brow Is Set A Crown Of Flame": (2, True, "Hellboy"),
    "Pancakes!": (2, False, "Hellboy"),
}


def overlay() -> dict:
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


def effects() -> dict:
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def ops_in(node):
    """Todos los dicts con clave 'op' de una estructura anidada (then, ops, options, while...), en orden."""
    if isinstance(node, dict):
        if "op" in node:
            yield node
        for v in node.values():
            yield from ops_in(v)
    elif isinstance(node, list):
        for v in node:
            yield from ops_in(v)


def test_overlay_sheet_is_the_real_deck_card_by_card():
    ov = overlay()
    sheet = ov["deck"]["sheet"]
    assert ov["deck"]["card_base"] == 19700 and ov["deck"]["sheet_id"] == 197
    assert sorted(e["idx"] for e in sheet) == list(range(30))
    for title, (copies, destiny, fighter) in EXPECTED.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert all(e["fighter"] == fighter for e in entries), title
        assert all(("destiny" in e.get("tags", ())) == destiny for e in entries), title
    assert sum(c for c, _, _ in EXPECTED.values()) == 30
    assert sum(1 for e in sheet if "destiny" in e.get("tags", ())) == 11


def test_herodef_sidekick_and_forms_match_the_character_card_and_token():
    h = load_hero("hellboy")
    assert (h.hp, h.move, h.ranged) == (18, 2, False)
    lobster, = h.sidekicks
    assert (lobster.name, lobster.count, lobster.hp, lobster.move, lobster.ranged) == ("Lobster Johnson", 1, 6, 2, True)
    raw_lobster, = overlay()["sidekicks"]
    assert (raw_lobster["start_on_board"], raw_lobster["reserve"]) == (1, 0)
    assert (h.forms.counter, h.forms.threshold, h.forms.below, h.forms.at_or_above) == (
        "destiny", 6, "OCCULT DETECTIVE", "ANUNG UN RAMA")
    assert h.attack_bonus("ANUNG UN RAMA", True) == 2 and h.attack_bonus("OCCULT DETECTIVE", True) == 0


def test_every_deck_card_has_an_effects_entry_with_the_five_slots_and_its_copies():
    ef = effects()
    assert ef["hero"] == "hellboy"
    by_title = {c["title"]: c for c in ef["cards"]}
    deck_titles = {c.title for c in load_hero("hellboy").deck()}
    assert set(by_title) == deck_titles == set(EXPECTED)
    for title, card in by_title.items():
        assert set(card["effects"]) == SLOTS, title
        assert card["copies"] == EXPECTED[title][0], title
        assert all(isinstance(v, list) for v in card["effects"].values()), title


def test_only_vocabulary_or_declared_ops_are_used_and_plugins_are_explained():
    ef = effects()
    declared = {p["op"] for p in ef["primitives_needed"]}
    plugin_ids = {p["id"] for p in ef["plugins"]}
    assert all(p["spec"] for p in ef["primitives_needed"]) and all(p["why"] for p in ef["plugins"])
    assert all(i.startswith("hellboy:") for i in plugin_ids)
    used = list(ops_in(ef["ability"])) + [o for c in ef["cards"] for o in ops_in(c["effects"])]
    assert used, "sin ops"
    for op in used:
        name = op["op"]
        if name == "plugin":
            assert op["id"] in plugin_ids, op
        else:
            assert name in VOCABULARY | declared, op
    assert declared <= VOCABULARY           # lo declarado solo extiende argumentos de ops del vocabulario
    assert {"look_hand", "choose_n", "cancel_effects", "gain_action", "return_to_deck"} <= {o["op"] for o in used}


def test_cards_with_text_have_ops_and_blank_cards_have_none():
    ef = effects()
    deck = {c.title: c for c in load_hero("hellboy").deck()}
    for card in ef["cards"]:
        n_ops = sum(1 for _ in ops_in(card["effects"]))
        assert (n_ops > 0) == bool(deck[card["title"]].text.strip()), card["title"]


def test_hidden_info_covers_confront_and_table_objects_match_the_config():
    ef = effects()
    assert any(h["card"] == "Confront Any Demon or God" and "look_hand" in h["what"] for h in ef["hidden_info"])
    table = ef["table"]
    minis = {v["guid"] for v in table["hero_miniatures"].values() if isinstance(v, dict)}
    pieces = load_config(CONFIG).raw["pieces"]      # las piezas salen de data/tts/<slug>.json
    assert minis == set(pieces["hellboy"]) == {"f9789a", "e6f06e"}
    assert table["sidekick_miniature"]["guid"] == pieces["lobster"]
    assert re.fullmatch(r"[0-9a-f]{6}", table["ability_token"]["guid"])
    assert set(table["ability_token"]["faces"]) == {"1644a3", "30d50e"}
    assert ef["open_questions"] and all(isinstance(q, str) and q for q in ef["open_questions"])
