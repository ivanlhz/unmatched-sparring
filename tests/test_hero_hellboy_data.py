"""Datos de Hellboy (F07, caja Hellboy): el overlay y el HeroDef generado describen el mazo real de la hoja 197, y
data/heroes/effects/hellboy.json cubre cada carta en el DSL v1 (docs/effects-dsl.md). Sin FakeTTS."""
import json
import re

from sparring.board import DATA_DIR
from sparring.heroes import HEROES_DIR, load_hero
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "hellboy.json"
EFFECTS = HEROES_DIR / "effects" / "hellboy.json"
CONFIG = DATA_DIR.parent / "config" / "partida.json"

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
    """Todos los dicts con clave 'op' de una estructura anidada (then, ops, options...), en orden."""
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


def test_effects_validate_and_cover_every_deck_card_with_its_copies():
    assert validate_file(EFFECTS) == []
    ef = effects()
    assert ef["schema"] == 1 and ef["hero"] == "hellboy"
    by_title = {c["title"]: c for c in ef["cards"]}
    assert set(by_title) == {c.title for c in load_hero("hellboy").deck()} == set(EXPECTED)
    for title, card in by_title.items():
        assert card["copies"] == EXPECTED[title][0], title


def test_ability_in_the_dsl_matches_the_herodef_triggers_and_passive():
    ab = effects()["ability"]
    assert [t["id"] for t in ab["triggers"]] == ["detective_draw", "anung_discard_move"]
    assert all(t["when"] == {"event": "start_of_turn", "player": "owner"} for t in ab["triggers"])
    detective, anung = ab["triggers"]
    assert detective["optional"] is True and detective["ops"] == [{"op": "draw", "player": "owner", "amount": 2}]
    assert {"test": "form_is", "form": "OCCULT DETECTIVE"} in detective["condition"]["all"]
    assert [op["op"] for op in anung["ops"]] == ["discard", "move"]
    assert anung["ops"][0]["as"] == "fuel" and anung["ops"][1]["amount"] == {"attr": "boost", "of": "$fuel"}
    passive, = ab["passives"]
    assert (passive["kind"], passive["amount"], passive["while"]) == ("modify_value", 2, {"test": "form_is", "form": "ANUNG UN RAMA"})
    assert passive["cards"] == {"player": "owner", "type": "attack", "fighter": "hero"}


def test_cards_with_text_have_ops_or_may_boost_and_blank_cards_have_none():
    ef = effects()
    deck = {c.title: c for c in load_hero("hellboy").deck()}
    for card in ef["cards"]:
        has_semantics = any(True for _ in ops_in(card["effects"])) or card.get("may_boost", False)
        assert has_semantics == bool(deck[card["title"]].text.strip()), card["title"]
    assert ef["cards"][4]["title"] == "Second Shot" and ef["cards"][4]["may_boost"] is True
    assert ef["plugins"] == []   # la coreografia del cambio de forma esta en table, no es un efecto
    used = {op["op"] for c in ef["cards"] for op in ops_in(c["effects"])}
    assert {"look_hand", "choose_effect", "cancel_effects", "gain_action", "return_to_deck", "set_value", "status"} <= used
    pancakes = next(c for c in ef["cards"] if c["title"] == "Pancakes!")
    choose, = pancakes["effects"]["scheme"]
    assert (choose["op"], choose["amount"], choose["distinct"], len(choose["options"])) == ("choose_effect", 2, True, 3)


def test_hidden_info_covers_confront_and_table_objects_match_the_config():
    ef = effects()
    assert any(h["card"] == "Confront Any Demon or God" and "look_hand" in h["what"] for h in ef["hidden_info"])
    table = ef["table"]
    minis = {v["guid"] for v in table["hero_miniatures"].values() if isinstance(v, dict)}
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert minis == set(cfg["pieces"]["hellboy"]) == {"f9789a", "e6f06e"}
    assert table["sidekick_miniature"]["guid"] == cfg["pieces"]["lobster"]
    assert re.fullmatch(r"[0-9a-f]{6}", table["ability_token"]["guid"])
    assert set(table["ability_token"]["faces"]) == {"1644a3", "30d50e"}
    assert ef["open_questions"] and all(isinstance(q, str) and q for q in ef["open_questions"])
