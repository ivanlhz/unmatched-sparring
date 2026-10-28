"""Datos de Liz Sherman (F07 paso 13, solo datos): el overlay carga, la hoja 199 cuadra con las copias de la carta
real, las 15 ardientes son las que dice la hoja, y data/heroes/effects/liz-sherman.json cubre cada carta en el DSL v1
(docs/effects-dsl.md). Sin FakeTTS ni sockets."""
import json
from collections import Counter

from sparring.heroes import HEROES_DIR, load_hero
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "liz-sherman.json"
EFFECTS = HEROES_DIR / "effects" / "liz-sherman.json"

# (copias, valor, impulso, tipo, ardiente) leidos de la hoja 199 del save del torneo
SHEET = {
    "Incinerate": (1, 7, 0, "attack", True),
    "Fireball": (2, 5, 0, "attack", True),
    "Flame Lash": (3, 1, 0, "attack", True),
    "Fleeting Moments": (3, 4, 3, "attack", False),
    "Burning Barrier": (3, 2, 0, "versatile", True),
    "Pyrotechnics": (3, 3, 0, "versatile", True),
    "B.P.R.D. Training": (2, 3, 1, "versatile", False),
    "Rekindle": (2, 2, 3, "versatile", False),
    "Feint": (3, 2, 3, "versatile", False),
    "Evade": (2, 3, 1, "defense", False),
    "Searing Clarity": (3, None, 0, "scheme", True),
    "Fight Or Flight": (3, None, 2, "scheme", False),
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ops_in(node):
    """Todos los nombres de op que aparecen en un arbol de efectos (listas y dicts anidados)."""
    if isinstance(node, dict):
        yield from ([node["op"]] if "op" in node else [])
        for v in node.values():
            yield from ops_in(v)
    elif isinstance(node, list):
        for v in node:
            yield from ops_in(v)


def test_overlay_is_the_sheet_199_with_liz_on_every_card_and_no_sidekicks():
    ov = load(OVERLAY)
    assert ov["fid"] == "liz" and ov["sidekicks"] == [] and ov["forms"] is None and ov["counters"] == {}
    assert ov["deck"]["card_base"] == 19900 and ov["deck"]["sheet_id"] == 199
    sheet = ov["deck"]["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert {e["fighter"] for e in sheet} == {"Liz Sherman"}
    assert Counter(e["title"] for e in sheet) == {t: n for t, (n, *_) in SHEET.items()}
    burning = {e["title"] for e in sheet if "burning" in e.get("tags", ())}
    assert burning == {t for t, (*_, b) in SHEET.items() if b}
    assert sum("burning" in e.get("tags", ()) for e in sheet) == 15


def test_generated_herodef_deals_30_cards_with_the_real_values_and_the_ongoing_of_fight_or_flight():
    h = load_hero("liz-sherman")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.sidekicks) == ("Liz Sherman", "liz", 16, 3, True, ())
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(19900, 19930))
    for c in deck:
        copies, value, boost, kind, burning = SHEET[c.title]
        assert (c.value, c.boost, c.type, c.fighter) == (value, boost, kind, "Liz Sherman"), c.title
        assert ("burning" in c.tags) == burning, c.title
    assert all(c.boost == 0 for c in deck if "burning" in c.tags)      # las ardientes no tienen impulso
    fof = next(c for c in deck if c.title == "Fight Or Flight")
    assert "ONGOING: Add +1 to the value of your combat cards" in fof.text
    assert {t["id"] for t in h.triggers} == {"wildfire_start"} and {p["id"] for p in h.passives} == {"wildfire_return"}


def test_effects_validate_and_cover_every_deck_card_without_plugins():
    assert validate_file(EFFECTS) == []
    eff = load(EFFECTS)
    assert eff["schema"] == 1 and eff["hero"] == "liz-sherman"
    titles = {c.title for c in load_hero("liz-sherman").deck()}
    by_title = {c["title"]: c for c in eff["cards"]}
    assert set(by_title) == titles
    assert all(c["effects"][m] is not None for c in eff["cards"] for m in ("immediately", "during", "after", "scheme", "boost"))
    assert eff["plugins"] == [] and "plugin" not in set(ops_in(eff["cards"])) | set(ops_in(eff["ability"]))
    with_ops = [c["title"] for c in eff["cards"] if any(c["effects"].values()) or c.get("ongoing")]
    assert len(with_ops) == 12
    assert by_title["Incinerate"]["uncancelable"] is True
    assert eff["hidden_info"] and eff["open_questions"]


def test_wildfire_is_two_triggers_the_bottom_discard_and_the_burning_return():
    ab = load(EFFECTS)["ability"]
    start, back = ab["triggers"]
    assert start["id"] == "wildfire_start" and start["when"] == {"event": "start_of_turn", "player": "owner"}
    assert start["condition"] == {"test": "exists", "cards": {"zone": "deck", "player": "owner"}}   # mazo vacio: nada
    burn, branch = start["ops"]
    assert burn == {"op": "discard", "cards": {"zone": "deck", "player": "owner", "pick": "bottom", "amount": 1}, "as": "burnt"}
    assert branch["condition"] == {"test": "card", "card": "$burnt", "filter": {"tag": "burning"}}
    assert branch["then"][0]["op"] == "damage" and branch["else"][0] == {"op": "move", "target": "hero", "amount": 2, "up_to": True}
    assert back["id"] == "wildfire_return"
    assert back["when"] == {"event": "card_discarded", "player": "owner", "from": ["hand", "deck"], "cause_not": "hand_limit", "filter": {"tag": "burning"}}
    assert back["ops"] == [{"op": "put_in_hand", "cards": "$card"}]
    assert ab["passives"] == []


def test_incinerate_flame_lash_and_fight_or_flight_in_the_dsl():
    by_title = {c["title"]: c for c in load(EFFECTS)["cards"]}
    optional, = by_title["Incinerate"]["effects"]["during"]
    assert optional["chooser"] == "opponent" and optional["cost"][0]["cards"]["amount"] == 2
    assert optional["ops"] == [{"op": "set_value", "card": "this", "amount": 0}]
    lash = by_title["Flame Lash"]["effects"]["during"]
    assert lash[0]["as"] == "burnt" and lash[1] == {"op": "modify_value", "card": "this", "amount": {"attr": "boost", "of": "$burnt"}}
    fof = by_title["Fight Or Flight"]
    assert fof["effects"]["scheme"][1] == {"op": "move", "target": "hero", "amount": 5, "up_to": True, "through_enemies": True}
    assert fof["ongoing"] == {"modifiers": [{"kind": "modify_value", "cards": {"player": "owner"}, "amount": 1}],
                              "triggers": [], "until": {"event": "start_of_turn", "player": "owner"}}
    assert by_title["Fleeting Moments"]["effects"]["after"][1]["cards"]["pick"] == "random"
