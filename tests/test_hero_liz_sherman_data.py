"""Datos de Liz Sherman (F07 paso 13, solo datos): el overlay carga, la hoja 199 cuadra con las copias de la carta
real, las 15 ardientes son las que dice la hoja, cada carta del mazo tiene efectos estructurados y los efectos solo
usan el vocabulario comun o lo que declaran. Sin FakeTTS ni sockets."""
import json
from collections import Counter

from sparring.heroes import HEROES_DIR, load_hero

OVERLAY = HEROES_DIR / "overlay" / "liz-sherman.json"
EFFECTS = HEROES_DIR / "effects" / "liz-sherman.json"

VOCABULARY = {"damage", "heal", "draw", "discard", "discard_random", "move", "place", "push", "swap", "revive",
              "cancel_effects", "modify_value", "status", "counter", "persistent_scheme", "look_hand", "reveal",
              "choose_n", "optional", "if", "for_each", "gain_action", "search_deck", "return_to_deck", "plugin"}

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


def plugin_ids_in(node):
    if isinstance(node, dict):
        if node.get("op") == "plugin":
            yield node["id"]
        for v in node.values():
            yield from plugin_ids_in(v)
    elif isinstance(node, list):
        for v in node:
            yield from plugin_ids_in(v)


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


def test_every_deck_card_has_structured_effects_and_only_known_or_declared_ops():
    eff = load(EFFECTS)
    assert eff["hero"] == "liz-sherman"
    titles = {c.title for c in load_hero("liz-sherman").deck()}
    by_title = {c["title"]: c for c in eff["cards"]}
    assert set(by_title) == titles
    moments = ("immediately", "during", "after", "scheme", "boost")
    for title, card in by_title.items():
        assert tuple(card["effects"]) == moments, title
        assert all(isinstance(card["effects"][m], list) for m in moments), title
    assert eff["ability"]["when"] == "start_of_turn" and eff["ability"]["ops"]
    declared = {p["op"] for p in eff["primitives_needed"] if not p["op"].startswith("card_flag:")}
    used = set(ops_in(eff["ability"])) | set(ops_in(eff["cards"]))
    assert used, "sin ops"
    assert used <= VOCABULARY | declared, used - (VOCABULARY | declared)
    assert declared <= VOCABULARY | {"plugin"}   # las extensiones declaradas son sobre ops del vocabulario
    plugins = {p["id"] for p in eff["plugins"]}
    assert set(plugin_ids_in(eff["ability"])) | set(plugin_ids_in(eff["cards"])) == plugins == {"liz:wildfire"}
    assert all(p["id"].startswith("liz:") for p in eff["plugins"])
    assert eff["hidden_info"] and eff["open_questions"]


def test_cards_with_ops_versus_plugin_coverage():
    eff = load(EFFECTS)
    with_ops = [c["title"] for c in eff["cards"] if any(c["effects"].values())]
    with_plugin = [c["title"] for c in eff["cards"] if "plugin" in set(ops_in(c))]
    assert len(with_ops) == 12 and with_plugin == []
    assert by_title_flag(eff, "Incinerate", "uncancelable") is True


def by_title_flag(eff, title, flag):
    return next(c for c in eff["cards"] if c["title"] == title).get(flag)
