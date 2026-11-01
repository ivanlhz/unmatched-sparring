"""The session's chat and panel in English (batch 2 of the i18n work): a whole bot turn and a human turn run on the fake
table with `language = en` and nothing in Spanish may reach the chat, the broadcasts or the panel status."""
from __future__ import annotations

import re

import pytest

from sparring import i18n
from sparring.ai_medusa import Act
from sparring.tts.lua import _STATUS
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_review5_fixes import attack_plan
from conftest import place
from test_session import NICK, human_plays

# words of the Spanish texts that cannot be English (card titles and hero names are English-printed)
SPANISH = re.compile(r"\b(tu|tus|del|pulsa|mesa|carta|cartas|turno|mazo|descarte|mano|ataca|juega|accion|acciones|dano|"
                     r"fin de|ahora|aun|hay|ya|para|con|debes|puedes|robas|roba|elige|maniobra|plan|esquema|vida)\b", re.I)


def leaks(lines) -> list[str]:
    return [str(line) for line in lines if SPANISH.search(str(line)) or not str(line).isascii() or not str(line).strip()]


@pytest.fixture
def english():
    with i18n.using("en"):
        yield


def test_the_detector_knows_what_a_leak_looks_like():
    assert leaks(["Tu turno."]) and leaks(["Fin de accion"]) and leaks(["El bot juega Snipe"])
    assert leaks(["The bot plays Snipe", "Your turn.", "Combat: Medusa attacks with Snipe (3): total 3."]) == []


def test_a_whole_bot_turn_in_english_and_the_panel_with_it(brig, monkeypatch, english):
    session, table, game, fake = brig
    lines: list[str] = []
    statuses: list[str] = []

    def press(event, payload=None):
        out = click(session, table, event, payload)
        lines.extend(out)
        statuses.extend(status for status, _ in table.panels)
        return out

    press(Event.MANEUVER)                                       # the human's turn: a Maneuver, then the turn ends
    game.actions_left = 0
    attack_plan(session, monkeypatch)                           # the bot attacks first, then maneuvers
    plans = [Act("maneuver", moves={"medusa": 0})]
    first = session.ai.plan
    monkeypatch.setattr(session.ai, "plan", lambda g: first(g) if g.actions_left == 2 else plans[0])
    press(Event.END_ACTION)
    assert session.pending is not None and session.pending.kind == "bot_attacks"
    press(Event.REVEAL)                                         # no defense: the combat resolves, the bot goes on
    press(Event.END_ACTION)
    lines.extend(table.broadcasts)

    text = "\n".join(lines)
    for phrase in ("Maneuver:", "End of your turn. Bot's turn.", "The bot attacks", "Combat:", "total", "Damage"):
        assert phrase in text, phrase
    assert leaks(lines) == [], leaks(lines)
    assert statuses and all(_STATUS.fullmatch(s) for s in statuses)
    assert leaks(statuses) == [], leaks(statuses)
    assert any(s.startswith("Your turn") for s in statuses) and any("Bot's turn" in s for s in statuses)


def test_a_human_turn_in_english_from_attack_to_scheme(brig, monkeypatch, english):
    session, table, game, fake = brig
    lines: list[str] = []
    statuses: list[str] = []

    def press(event, payload=None):
        out = click(session, table, event, payload)
        lines.extend(out)
        statuses.extend(status for status, _ in table.panels)
        return out

    press(Event.ATTACKER, {"attacker": "att_hellboy"})
    press(Event.ATTACK, {"target": "medusa"})
    press(Event.REVEAL)                                         # nothing face down: the table asks for a card
    press(Event.ATTACK, {"target": "medusa"})                   # an attack is already open
    human_plays(table, game, "Service Pistol")
    press(Event.REVEAL)
    press(Event.HP, {"fighter": "lobster", "delta": 1})
    press(Event.HP, {"fighter": "lobster", "delta": 5})         # not a +1 / -1
    press(Event.VALUE, {"value": 500})                          # out of range
    press(Event.CANCEL)                                         # nothing to cancel
    press(Event.UNDO_GAME_OVER)
    game.actions_left = 2
    session.moving = False
    press(Event.SCHEME)                                         # the scheme prompt (no card on the table yet)
    press(Event.END_ACTION)
    lines.extend(table.broadcasts)

    text = "\n".join(lines)
    for phrase in ("attacks", "Reveal", "Scheme:", "There is nothing to cancel.", "There is no game over to undo."):
        assert phrase in text, phrase
    assert leaks(lines) == [], leaks(lines)
    assert all(_STATUS.fullmatch(s) for s in statuses) and leaks(statuses) == [], leaks(statuses)


def test_rule_errors_reach_the_chat_in_english(brig, english):
    session, table, game, fake = brig
    game.actions_left = 0
    out = click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    out += click(session, table, Event.MANEUVER)
    assert leaks(out) == [], leaks(out)
    game.actions_left = 2
    place(game, hellboy=1, medusa=30)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    out = click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    out += click(session, table, Event.ATTACK, {"target": "medusa"})
    assert any(m.startswith("Illegal action: ") and "cannot reach" in m for m in out), out
    assert leaks(out) == [], leaks(out)


def test_spanish_stays_the_default_and_a_spanish_turn_still_reads_spanish(brig):
    session, table, game, fake = brig
    out = click(session, table, Event.MANEUVER)
    assert any(m.startswith("Maniobra: robas 1") for m in out) or any(m.startswith("Maniobra") for m in out)
    assert i18n.language() == "es"


def test_no_english_catalog_text_is_left_in_spanish():
    import json
    from pathlib import Path
    en = json.loads((Path(i18n.__file__).resolve().parents[2] / "data" / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert {tag: text for tag, text in en.items() if SPANISH.search(text)} == {}


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_status_text_fits_the_panel_with_its_longest_arguments(lang):
    import json
    from pathlib import Path
    from sparring.session_choices import panel_text
    cat = json.loads((Path(i18n.__file__).resolve().parents[2] / "data" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
    with i18n.using(lang):
        head = i18n.tn("st.head", 2)
        for tag in sorted(t for t in cat if t.startswith("st.") and not t.startswith("st.head")):
            text = i18n.t(tag, head=head, title="PERFECT SHOT TWICE", name="Lobster Johnson", wait=i18n.t("st.wait.table"))
            assert _STATUS.fullmatch(panel_text(text)), (lang, tag, text)
            assert len(text) <= 90, (lang, tag, len(text))
