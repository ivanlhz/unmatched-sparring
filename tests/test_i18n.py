"""Player-facing texts in several languages (`sparring/i18n`, catalogs in data/i18n/<lang>.json).

The catalogs are flat tag -> template maps. These tests keep them honest: every tag the code uses exists in both
files, both files have the same tags and the same `{placeholders}`, a missing tag or language falls back to Spanish
and never crashes, and the panel and the chat really come out in English with `language = en`."""
from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path

import pytest

from sparring import i18n, play
from sparring.tts import ui
from sparring.tts.ui import Event
from test_d3_table_effects import said
from test_human_moves_by_hand import HELLBOY_VS_ABE, hecho, rhod_asks_for_abe, rig, with_rig  # noqa: F401
from test_play import cfg_file  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "sparring").rglob("*.py"))
# tags built at run time (`t(f"prefix.{kind}")`): the prefix and the suffixes the code can produce
DYNAMIC = {
    "choice.prompt.": ("fighter", "space", "cards", "effect", "optional", "order", "amount", "default", "one_card",
                       "predict", "discards", "else_damage", "redirect", "use_effect"),
    "hidden.fail.where_": ("discard", "deck"),
    "narr.fstatus.": ("cannot_leave_space", "immune_to_effect_damage"),
    "narr.status.": tuple(f"{n}.{side}" for n in ("cannot_gain_actions", "cannot_draw", "immune_to_effect_damage",
                                                   "next_attack_bonus") for side in ("bot", "human")),
    "narr.v.": tuple(f"{w}.{side}" for w in ("draw", "discard", "return", "poss", "gain") for side in ("bot", "human")),
    "fx.ability.": ("detective_draw", "anung_discard_move", "wildfire_start"),
}


def load(lang: str) -> dict[str, str]:
    return json.loads((ROOT / "data" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def used_tags() -> tuple[set[str], set[str]]:
    """(plain tags, plural tags) passed as literals to t() / has() and to tn() / plural() in the package."""
    plain: set[str] = set()
    plurals: set[str] = set()
    for path in SOURCES:
        if path.parent.name == "i18n":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if fn not in ("t", "tn", "plural", "has"):
                continue
            at = 1 if fn in ("tn", "plural") else 0
            arg = node.args[at] if len(node.args) > at else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "." in arg.value:
                (plurals if fn in ("tn", "plural") else plain).add(arg.value)
    return plain, plurals


def test_both_catalogs_have_the_same_tags():
    es, en = load("es"), load("en")
    assert sorted(set(es) ^ set(en)) == []


def test_placeholders_match_between_languages():
    es, en = load("es"), load("en")
    bad = {tag: (placeholders(es[tag]), placeholders(en[tag])) for tag in es if placeholders(es[tag]) != placeholders(en[tag])}
    assert bad == {}


def test_every_tag_used_in_the_code_exists_in_every_catalog():
    es, en = load("es"), load("en")
    plain, plurals = used_tags()
    needed = set(plain)
    for tag in plurals:
        needed.update((tag + ".one", tag + ".other"))
    for prefix, suffixes in DYNAMIC.items():
        needed.update(prefix + s for s in suffixes)
    assert sorted(n for n in needed if n not in es) == []
    assert sorted(n for n in needed if n not in en) == []
    assert len(needed) > 100                      # the scan finds the code's tags, not an empty set


def test_no_catalog_tag_is_dead():
    text = "\n".join(p.read_text(encoding="utf-8") for p in SOURCES)
    dead = []
    for tag in load("es"):
        base = re.sub(r"\.(one|other)$", "", tag)
        stem = next((p for p in DYNAMIC if tag.startswith(p)), None)
        if f'"{tag}"' in text or f'"{base}"' in text or stem is not None or f'"{tag.rsplit(".", 1)[0]}.' in text:
            continue
        dead.append(tag)
    assert dead == []


def test_plural_tags_come_in_pairs():
    for lang in ("es", "en"):
        cat = load(lang)
        ones = {t[:-4] for t in cat if t.endswith(".one")}
        others = {t[:-6] for t in cat if t.endswith(".other")}
        assert ones == others


# ---------------------------------------------------------------- the API

def test_default_is_spanish_and_unknown_languages_fall_back_to_it():
    assert i18n.language() == "es"
    assert i18n.set_language("xx") == "es"
    assert i18n.set_language(None) == "es"
    assert i18n.set_language("../es") == "es"
    assert i18n.t("panel.end_action") == "Fin de accion"


def test_english_texts_and_plurals():
    with i18n.using("en"):
        assert i18n.t("panel.end_action") == "End action"
        assert i18n.plural(1, "noun.card") == "1 card" and i18n.plural(3, "noun.card") == "3 cards"
        assert i18n.t("moves.stays", name="Abe") == "Abe stays where it is."
    assert i18n.plural(3, "noun.card") == "3 cartas" and i18n.t("moves.stays", name="Abe") == "Abe se queda donde esta."


def test_missing_tag_and_bad_arguments_never_crash():
    assert i18n.t("no.such.tag") == "no.such.tag"
    assert i18n.t("moves.stays") == "moves.stays"            # a placeholder with no argument: the tag, not a KeyError
    assert i18n.t("moves.stays", name="X", extra=1) == "X se queda donde esta."


def test_a_tag_missing_in_the_chosen_language_falls_back_to_spanish(monkeypatch):
    en = dict(i18n.catalog("en"))
    en.pop("panel.end_action")
    monkeypatch.setitem(i18n._cache, "en", en)
    with i18n.using("en"):
        assert i18n.t("panel.end_action") == "Fin de accion"
        assert i18n.t("panel.maneuver") == "Maneuver"


def test_another_language_is_one_more_file(tmp_path, monkeypatch):
    (tmp_path / "es.json").write_text(json.dumps(load("es")), encoding="utf-8")
    (tmp_path / "fr.json").write_text(json.dumps({"panel.end_action": "Fin de l'action"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "CATALOG_DIR", tmp_path)
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.available() == ("es", "fr")
    with i18n.using("fr"):
        assert i18n.t("panel.end_action") == "Fin de l'action"
        assert i18n.t("panel.maneuver") == "Maniobra"


def test_unreadable_catalog_is_empty_not_an_error(tmp_path, monkeypatch):
    (tmp_path / "es.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(i18n, "CATALOG_DIR", tmp_path)
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.t("panel.end_action") == "panel.end_action"


# ---------------------------------------------------------------- the panel

def ids_of(xml: str) -> list[str]:
    return re.findall(r'id="([^"]+)"', xml)


def test_panel_in_english_has_english_captions_and_the_same_button_ids():
    es = ui.panel_xml(["medusa"], ("hellboy",))
    with i18n.using("en"):
        en = ui.panel_xml(["medusa"], ("hellboy",))
        script = ui.handler_script()
        assert ui.END_ACTION_LABEL == "End action"
    assert ids_of(en) == ids_of(es)
    for caption in ("End action", "Maneuver", "Scheme", "Reveal", "Cancel attack", "Look at bot's hand", "Restart game",
                    "Send value", "Attack medusa", "hellboy attacks", "TURN", "LIFE"):
        assert f">{caption}<" in en, caption
    for spanish in ("Fin de accion", "Maniobra", "Reiniciar", "TURNO", "VIDA"):
        assert spanish not in en
    assert "Processing..." in script and "No reply from the bot" in script
    assert ui.END_ACTION_LABEL == "Fin de accion" and "Procesando..." in ui.handler_script()


def test_button_events_do_not_depend_on_the_displayed_text():
    es = ui.handler_script(ids=["btn_end"])
    with i18n.using("en"):
        en = ui.handler_script(ids=["btn_end"])
    for fn in ("onEndAction", "onManeuver", "onAttacker", "onChoice"):
        assert f"function {fn}" in es and f"function {fn}" in en
    assert 'event = "end_action"' in en


# ---------------------------------------------------------------- configuration and command line

def test_language_flag_and_config_key(cfg_file):
    assert play.parse_args([]).language is None
    assert play.parse_args(["--language", "en"]).language == "en"
    with pytest.raises(SystemExit):
        play.parse_args(["--language", "klingon"])
    assert play.load_config(cfg_file()).language == "es"
    assert play.load_config(cfg_file(), language="en").language == "en"
    assert play.load_config(cfg_file(language="en")).language == "en"
    assert play.load_config(cfg_file(language="en"), language="es").language == "es"      # the flag beats the file
    cfg = play.load_config(cfg_file(language="klingon"))
    assert cfg.language == "es" and any("klingon" in w for w in cfg.warnings)


def test_the_shipped_configuration_names_the_language_and_documents_it():
    cfg = json.loads((ROOT / "config" / "partida.json").read_text(encoding="utf-8"))
    assert cfg["language"] == "es"
    assert any(n.startswith("language:") for n in cfg["_notes"])


# ---------------------------------------------------------------- the chat, end to end

@with_rig(*HELLBOY_VS_ABE)
def test_the_human_move_prompt_and_buttons_come_out_in_english(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    i18n.set_language("en")
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    assert req.kind == "space"
    assert said(session.messages, f"Right Hand Of Doom: Move {cfg.nicknames['abe']} up to 1 space and press Done")
    assert not said(session.messages, "pulsa Hecho")
    assert session.panel_labels() == {"btn_choice_1": "Done", "btn_choice_2": "Don't move"}
    assert session.panel_view()[0].endswith("on the table and press Done")


@with_rig(*HELLBOY_VS_ABE)
def test_a_wrong_move_is_refused_in_english_and_nothing_changes(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    i18n.set_language("en")
    rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    before = session.effect_run.awaiting.key
    hecho(session, table)
    assert said(session.messages, "has not moved: move it")
    assert session.effect_run.awaiting.key == before


@with_rig(*HELLBOY_VS_ABE)
def test_english_button_captions_reach_the_table_as_text_attributes(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    i18n.set_language("en")
    rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    scripts = [m.get("script", "") for m in fake.received]
    assert any('"btn_choice_1", "text", "Done"' in s for s in scripts)
    assert any('"btn_choice_2", "text", "Don\'t move"' in s for s in scripts)
