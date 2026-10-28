"""Datos de Baba Yaga (F08): overlay, HeroDef generado y efectos estructurados (DSL v1, docs/effects-dsl.md)
concuerdan entre si y con las cartas reales de la hoja 331 del save del torneo (leidas de la imagen el 2026-10-28).
Sin motor, sin TTS, sin sockets."""
import json

import pytest

from sparring.heroes import HEROES_DIR, load_hero
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "baba-yaga.json"
EFFECTS = HEROES_DIR / "effects" / "baba-yaga.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")

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
PACT_END = {"event": "damage_taken", "target": "hero", "kind": "combat", "min": 2}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def walk_ops(ops):
    for op in ops:
        yield op
        for key in ("then", "else", "ops", "cost"):
            yield from walk_ops(op.get(key, ()))
        for opt in op.get("options", ()):
            yield from walk_ops(opt["ops"])


def all_ops(effects):
    for t in effects["ability"]["triggers"]:
        yield from walk_ops(t["ops"])
    for card in effects["cards"]:
        for moment in MOMENTS:
            yield from walk_ops(card["effects"][moment])
        for t in (card.get("ongoing") or {}).get("triggers", ()):
            yield from walk_ops(t["ops"])


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
    # el texto real de la carta (overlay `text`) manda sobre unmatched-memory
    assert all("ONGOING:" in c.text and "Discard this immediately" in c.text for c in deck if c.type == "scheme")
    assert all("Baba Yaga as possible" in c.text for c in deck if c.title == "Deathless")
    assert all("put the rest on the bottom" in c.text for c in deck if c.title == "Read The Bones")
    assert not any("Yaha" in c.text or "healt " in c.text for c in deck)


def test_effects_validate_and_every_pact_is_an_ongoing_scheme_that_ends_at_2_combat_damage(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "baba-yaga"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        is_pact = card["title"] in PACTS
        assert bool(card["effects"]["scheme"]) == is_pact, card["title"]
        if is_pact:
            assert card["ongoing"]["until"] == PACT_END, card["title"]
            assert card["ongoing"]["modifiers"] or card["ongoing"]["triggers"], card["title"]
            assert "ONGOING:" in card["text"] and "Discard this immediately" in card["text"]
        else:
            assert card.get("ongoing") is None
            assert card["effects"]["after"] or card["effects"]["during"] or card.get("may_boost"), card["title"]
    rules = {m["rule"] for c in effects["cards"] if c.get("ongoing") for m in c["ongoing"]["modifiers"] if m["kind"] == "rule"}
    assert rules == {"no_attack_as_first_action", "effect_damage_bonus", "max_hand_size", "no_gain_actions"}
    peace = next(c for c in effects["cards"] if c["title"] == "Pact Of Peace")
    trig, = peace["ongoing"]["triggers"]
    assert trig["when"] == {"event": "end_of_turn", "player": "any"}
    assert trig["ops"][0]["target"] == {"kind": "hero", "filter": {"attacked_this_turn": True}, "pick": "all"}


def test_fateful_bargains_is_an_optional_redirect_passive_and_bound_in_blood_the_mandatory_op(effects):
    passive, = effects["ability"]["passives"]
    assert (passive["id"], passive["kind"], passive["damage"], passive["optional"]) == ("fateful_bargains", "redirect_damage", "effect", True)
    assert passive["from"] == "hero" and passive["to"] == {"side": "own", "name": "Koschei"}
    assert effects["ability"]["triggers"] == []
    bound = next(c for c in effects["cards"] if c["title"] == "Bound In Blood")
    op, = bound["effects"]["during"]
    assert (op["op"], op["damage"], op.get("optional", False)) == ("redirect_damage", "combat", False)


def test_out_of_time_boosts_by_data_not_by_text(effects):
    card = next(c for c in effects["cards"] if c["title"] == "Out Of Time")
    assert "BOOST this card" in card["text"] and "boost this attack" not in card["text"].lower()
    assert card["may_boost"] is True and card["effects"]["after"] == [{"op": "end_turn"}]


def test_remove_a_painful_memory_looks_then_chooses_and_the_rival_decides(effects):
    after = next(c for c in effects["cards"] if c["title"] == "Remove A Painful Memory")["effects"]["after"]
    assert after[0] == {"op": "look_hand", "player": "opponent"}
    choose, optional = after[1]["then"]
    assert choose["op"] == "choose" and choose["as"] == "memory" and choose["cards"]["chooser"] == "owner"
    assert optional["chooser"] == "opponent"
    assert optional["ops"] == [{"op": "discard", "cards": "$memory"}]
    assert optional["else"] == [{"op": "damage", "target": "opposing", "amount": 2}]
    assert effects["plugins"] == []      # remove_painful_memory cabe en primitivas
    used = {op["op"] for op in all_ops(effects)}
    assert used >= {"redirect_damage", "look_hand", "choose", "optional", "search_deck", "revive", "place", "end_turn", "for_each"}
    assert {h["card"].split(",")[0] for h in effects["hidden_info"]} >= {"Remove A Painful Memory", "Read The Bones", "Pact Of Secrecy"}
    assert effects["open_questions"]
