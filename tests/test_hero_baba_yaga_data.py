"""Datos de Baba Yaga (F08): overlay, HeroDef generado y efectos estructurados concuerdan entre si y con las
cartas reales de la hoja 331 del save del torneo (leidas de la imagen el 2026-10-28). Sin motor, sin TTS, sin sockets."""
import json

import pytest

from sparring.heroes import HEROES_DIR, load_hero

OVERLAY = HEROES_DIR / "overlay" / "baba-yaga.json"
EFFECTS = HEROES_DIR / "effects" / "baba-yaga.json"

# (titulo, copias, restriccion, tipo, valor, impulso) tal como estan impresos en las cartas.
REAL_CARDS = {
    "The Time For Deals Is Done": (2, "Baba Yaga", "attack", 5, 4),
    "Iron Teeth": (2, "Baba Yaga", "attack", 4, 2),
    "Remove A Painful Memory": (2, "any", "attack", 4, 1),
    "Death's Release": (2, "Koschei", "attack", 5, 1),
    "Read The Bones": (3, "Baba Yaga", "versatile", 3, 2),
    "Foul Journey": (3, "Baba Yaga", "versatile", 2, 2),
    "Hasten Towards Death": (2, "any", "versatile", 4, 3),
    "Out Of Time": (2, "any", "versatile", 2, 2),
    "Deathless": (3, "any", "versatile", 3, 1),
    "Exploit": (2, "any", "versatile", 4, 3),
    "Bound In Blood": (2, "Baba Yaga", "defense", 3, 3),
    "Pact Of Freedom": (1, "Baba Yaga", "scheme", None, 3),
    "Pact Of Mortality": (1, "Baba Yaga", "scheme", None, 3),
    "Pact Of Peace": (1, "Baba Yaga", "scheme", None, 3),
    "Pact Of Secrecy": (1, "Baba Yaga", "scheme", None, 3),
    "Pact Of Time": (1, "Baba Yaga", "scheme", None, 3),
}
PACTS = [t for t in REAL_CARDS if t.startswith("Pact Of")]

VOCABULARY = {
    "damage", "heal", "draw", "discard", "discard_random", "move", "place", "push", "swap", "revive",
    "cancel_effects", "modify_value", "status", "counter", "persistent_scheme", "look_hand", "reveal", "choose_n",
    "optional", "if", "for_each", "gain_action", "search_deck", "return_to_deck", "plugin",
}
NESTED_KEYS = ("ops", "then", "else", "ongoing")


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def walk_ops(ops):
    for op in ops:
        yield op
        for key in NESTED_KEYS:
            if isinstance(op.get(key), list):
                yield from walk_ops(op[key])


def all_ops(effects):
    yield from walk_ops(effects["ability"]["ops"])
    for card in effects["cards"]:
        for moment in ("immediately", "during", "after", "scheme", "boost"):
            yield from walk_ops(card["effects"][moment])


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (33100, 331, 33200)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert [e["title"] for e in sheet if "pact" in e.get("tags", ())] == PACTS
    assert overlay["sidekicks"] == [{"fid": "koschei", "name": "Koschei"}]
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == []
    assert [p["id"] for p in overlay["passives"]] == ["fateful_bargains"]


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("baba-yaga")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Baba Yaga", "baba", 13, 2, True)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("koschei", "Koschei", 1, 3, 2, False)]
    assert h.ability.startswith("FATEFUL BARGAINS\nIf Baba Yaga and Koschei share a zone")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(33100, 33130))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert sorted(c.title for c in deck if c.type == "scheme") == PACTS
    assert sum(1 for c in deck if c.fighter == "Koschei") == 2
    assert all(c.value is None for c in deck if c.type == "scheme")


def test_every_deck_card_has_effects_and_every_pact_is_a_persistent_scheme(effects):
    assert effects["hero"] == "baba-yaga"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert set(card["effects"]) == {"immediately", "during", "after", "scheme", "boost"}, card["title"]
        is_pact = card["title"] in PACTS
        assert bool(card["effects"]["scheme"]) == is_pact, card["title"]
        if is_pact:
            ps = [op for op in card["effects"]["scheme"] if op["op"] == "persistent_scheme"]
            assert len(ps) == 1 and ps[0]["ongoing"] and ps[0]["until"]["min"] == 2, card["title"]
            assert "ONGOING:" in card["text"] and "Discard this immediately" in card["text"]
        else:
            assert card["effects"]["after"] or card["effects"]["during"], card["title"]


def test_only_vocabulary_or_declared_ops_are_used_and_plugins_are_declared(effects):
    declared = {p["op"] for p in effects["primitives_needed"]}
    plugin_ids = {p["id"] for p in effects["plugins"]}
    used = set()
    for op in all_ops(effects):
        assert op["op"] in VOCABULARY | declared, op
        used.add(op["op"])
        if op["op"] == "plugin":
            assert op["id"] in plugin_ids and op["id"].startswith("baba:"), op
    assert used >= {"redirect_damage", "rule", "persistent_scheme", "look_hand", "choose_n", "optional"}
    assert "plugin" not in used and effects["plugins"] == []      # remove_painful_memory cabe en primitivas
    assert declared - VOCABULARY <= used                           # no se declara lo que no se usa
    assert {h["card"].split(",")[0] for h in effects["hidden_info"]} >= {"Remove A Painful Memory", "Read The Bones", "Pact Of Secrecy"}
    assert effects["open_questions"]
