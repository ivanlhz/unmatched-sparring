"""Mensajes a TTS por boton en modo rapido (cada uno cuesta ~0.5 s en vivo).

Antes del cambio (medido con la misma mesa falsa y diales): inicio 9, Maniobra 7, Fin de accion 5, atacar 12,
Revelar 17 y Fin de accion + turno completo del bot 43 (mas un anuncio por mensaje y por trozo de 64 caracteres)."""
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import brig, click, human_plays  # noqa: F401
from test_review5_fixes import idle_bot, setup_rig


def test_message_budget_per_button(brig, monkeypatch):
    session, table, game, fake = brig
    spent = {}

    def run(label, fn):
        n = fake.lua_messages
        fn()
        spent[label] = fake.lua_messages - n
    run("maniobra", lambda: click(session, table, Event.MANEUVER))
    run("fin de accion", lambda: click(session, table, Event.END_ACTION))
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    run("atacar", lambda: click(session, table, Event.ATTACK, {"target": "medusa"}))
    human_plays(table, game, "Service Pistol")
    run("revelar", lambda: click(session, table, Event.REVEAL))
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    run("turno del bot", lambda: click(session, table, Event.END_ACTION))
    assert spent == {"maniobra": 1, "fin de accion": 1, "atacar": 3, "revelar": 2, "turno del bot": 3}, spent
    assert [c for label, c, _ in session.cost_log if label == "accion del bot"] == [1, 1]


def test_message_budget_of_the_start(brig, monkeypatch):
    session, table, game, fake = brig
    setup_rig(session, table, game, first=1)
    n = fake.lua_messages
    session.start()
    assert fake.lua_messages - n <= 4
