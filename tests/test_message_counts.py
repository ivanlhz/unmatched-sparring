"""Messages to TTS per button in fast mode (each costs ~0.5 s live).

Before the change (measured with the same fake table and dials): start 9, Maneuver 7, End action 5, attack 12,
Reveal 17 and End action + the bot's whole turn 43 (plus one announcement per message and per 64-character chunk)."""
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
    run("maneuver", lambda: click(session, table, Event.MANEUVER))
    run("end action", lambda: click(session, table, Event.END_ACTION))
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    run("attack", lambda: click(session, table, Event.ATTACK, {"target": "medusa"}))
    human_plays(table, game, "Service Pistol")
    run("reveal", lambda: click(session, table, Event.REVEAL))
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    run("bot turn", lambda: click(session, table, Event.END_ACTION))
    assert spent == {"maneuver": 1, "end action": 1, "attack": 1, "reveal": 3, "bot turn": 3}, spent
    assert [c for label, c, _ in session.cost_log if label == "accion del bot"] == [1, 1]


def test_message_budget_of_the_start(brig, monkeypatch):
    session, table, game, fake = brig
    setup_rig(session, table, game, first=1)
    n = fake.lua_messages
    session.start()
    assert fake.lua_messages - n <= 5      # 4 + the read of the decks' identity
