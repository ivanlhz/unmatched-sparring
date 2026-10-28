"""HeroDef y su cargador (F07 paso 1): los datos de data/heroes/<slug>.json describen exactamente lo que hoy
esta cableado en el motor para Medusa y Hellboy, y el resto de la caja Hellboy carga sus datos basicos."""
import json

import pytest

from sparring.cards import memory_dir
from sparring.heroes import (HEROES_DIR, HeroDataError, available_heroes, load_hero, parse_hero)
from sparring.state import ANUNG, DETECTIVE


def test_available_heroes_are_the_hellboy_box_plus_medusa():
    assert available_heroes() == ["abe-sapien", "baba-yaga", "hellboy", "liz-sherman", "medusa"]


def test_medusa_herodef_matches_the_wired_fighters_and_deck():
    from sparring.cards import load_medusa_deck
    h = load_hero("medusa")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Medusa", "medusa", 16, 3, True)
    assert [(f.fid, f.name, f.hero, f.hp, f.move, f.ranged) for f in h.fighters()] == [
        ("medusa", "Medusa", True, 16, 3, True), ("harpy1", "Harpy", False, 1, 3, False),
        ("harpy2", "Harpy", False, 1, 3, False), ("harpy3", "Harpy", False, 1, 3, False)]
    assert h.deck() == load_medusa_deck()
    assert h.forms is None and h.counters == {} and h.attack_bonus(None, True) == 0
    assert "Medusa's zone" in h.ability


def test_hellboy_herodef_matches_the_wired_fighters_deck_forms_and_bonus():
    from sparring.cards import load_hellboy_deck
    h = load_hero("hellboy")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Hellboy", "hellboy", 18, 2, False)
    assert [(f.fid, f.name, f.hero, f.hp, f.move, f.ranged) for f in h.fighters()] == [
        ("hellboy", "Hellboy", True, 18, 2, False), ("lobster", "Lobster Johnson", False, 6, 2, True)]
    deck = h.deck()
    assert deck == load_hellboy_deck()
    assert sum(c.destiny for c in deck) == 11 and all("destiny" in c.tags for c in deck if c.destiny)
    assert h.forms.counter == "destiny" and h.forms.threshold == 6
    assert h.forms.of(5) == DETECTIVE and h.forms.of(6) == ANUNG
    assert h.counters["destiny"].pile == "discard" and h.counters["destiny"].tag == "destiny"
    assert h.attack_bonus(ANUNG, True) == 2 and h.attack_bonus(DETECTIVE, True) == 0
    assert h.attack_bonus(ANUNG, False) == 0          # Lobster no suma el +2
    assert {t["id"] for t in h.triggers} == {"detective_draw", "anung_discard_move"}


@pytest.mark.parametrize("slug, name, hp, move, ranged, sidekicks", [
    ("abe-sapien", "Abe Sapien", 13, 2, True, [("agent", "B.P.R.D. Agent", 3, 1, 2, True)]),
    ("baba-yaga", "Baba Yaga", 13, 2, True, [("koschei", "Koschei", 1, 3, 2, False)]),
    ("liz-sherman", "Liz Sherman", 16, 3, True, []),
])
def test_rest_of_the_hellboy_box_loads_basic_data_but_cannot_deal_a_deck(slug, name, hp, move, ranged, sidekicks):
    h = load_hero(slug)
    assert (h.name, h.hp, h.move, h.ranged) == (name, hp, move, ranged)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == sidekicks
    assert h.card_base is None and sum(c["copies"] for c in h.cards) == 30
    with pytest.raises(HeroDataError, match="sin hoja de CardID"):
        h.deck()


def test_loading_an_unknown_hero_or_a_mismatched_slug_is_a_clear_error(tmp_path):
    with pytest.raises(HeroDataError, match="no hay HeroDef para 'dracula'"):
        load_hero("dracula", tmp_path)
    (tmp_path / "x.json").write_text(json.dumps({"slug": "y"}), encoding="utf-8")
    with pytest.raises(HeroDataError, match="el slug del fichero es 'y', no 'x'"):
        load_hero("x", tmp_path)


def _hero(**over):
    raw = json.loads((HEROES_DIR / "hellboy.json").read_text(encoding="utf-8"))
    raw.update(over)
    return raw


def test_validation_rejects_bad_restrictions_sizes_types_and_counters():
    raw = _hero()
    raw["deck"]["cards"][0]["fighter"] = "Medusa"
    with pytest.raises(HeroDataError, match="restriccion 'Medusa' no es un luchador"):
        parse_hero(raw)
    raw = _hero()
    raw["deck"]["cards"].pop()
    with pytest.raises(HeroDataError, match="tiene 29 cartas"):
        parse_hero(raw)
    raw = _hero()
    raw["deck"]["cards"][3]["type"] = "spell"
    with pytest.raises(HeroDataError, match="tipo 'spell'"):
        parse_hero(raw)
    with pytest.raises(HeroDataError, match="contador 'fate', que no existe"):
        parse_hero(_hero(forms={"counter": "fate", "threshold": 6, "below": "a", "at_or_above": "b"}))
    with pytest.raises(HeroDataError, match="ataque desconocido 'laser'"):
        parse_hero(_hero(attack="laser"))
    with pytest.raises(HeroDataError, match="ids de luchador repetidos"):
        parse_hero(_hero(sidekicks=[{"fid": "hellboy", "name": "X", "count": 1, "hp": 1, "move": 1, "attack": "melee"}]))


def test_generated_herodefs_are_up_to_date_with_memory_and_overlays():
    """`tools/import_hero.py --all --check`: lo versionado es lo que sale del importador (solo si unmatched-memory
    esta en esta maquina)."""
    if not (memory_dir() / "data" / "heroes" / "hellboy.json").exists():
        pytest.skip("sin unmatched-memory en esta maquina")
    import importlib.util
    spec = importlib.util.spec_from_file_location("import_hero", HEROES_DIR.parent.parent / "tools" / "import_hero.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--all", "--check"]) == 0
