"""F14: los mensajes del bot salen en el chat de TTS con el color de su categoria, sin mensajes extra."""
import json
import os

import pytest

from sparring import play
from sparring.ai_medusa import Act
from sparring.session import Msg
from sparring.tts import lua
from sparring.tts.lua import CHAT_COLORS, ChatKind
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_review5_fixes import attack_plan
from test_session import card

try:
    from lupa import lua54
except ImportError:                                  # sin lupa solo se salta la prueba de Lua
    lua54 = None


def colors_of(table, text):
    return {c for b, c in zip(table.broadcasts, table.broadcast_colors) if text in b}


# ---------- la tabla ----------
def test_every_category_has_a_distinct_color_in_range():
    assert set(CHAT_COLORS) == set(ChatKind)
    assert len(set(CHAT_COLORS.values())) == len(ChatKind)
    assert all(len(c) == 3 and all(0.0 <= v <= 1.0 for v in c) for c in CHAT_COLORS.values())
    assert all(max(c) >= 0.8 for c in CHAT_COLORS.values()), "legibles sobre el fondo oscuro del chat"


@pytest.mark.parametrize("kind", list(ChatKind))
def test_the_script_of_each_category_carries_its_color(kind):
    r, g, b = CHAT_COLORS[kind]
    script = lua.broadcast("Hola", kind)
    assert f"broadcastToAll(\"Hola\", {{{r}, {g}, {b}}})" in script and lua.is_sendable(script)


def test_default_is_neutral_and_free_strings_are_rejected():
    assert lua.broadcast("Hola") == lua.broadcast("Hola", ChatKind.NEUTRAL)
    assert lua.broadcast("Hola", "attack") == lua.broadcast("Hola", ChatKind.ATTACK)
    for bad in ("red", "1, 1, 1}); os.exit() --", None, (1, 0, 0)):
        with pytest.raises(ValueError):
            lua.broadcast("Hola", bad)


def test_msg_is_a_plain_string_with_a_kind():
    m = Msg("Tu turno", ChatKind.YOUR_TURN)
    assert m == "Tu turno" and m.kind is ChatKind.YOUR_TURN and Msg("x").kind is ChatKind.NEUTRAL
    assert "a" + m == "aTu turno" and json.dumps(m) == '"Tu turno"'


# ---------- mensajes reales ----------
def test_the_key_messages_carry_their_category(brig, monkeypatch):
    session, table, game, fake = brig
    msgs = click(session, table, Event.MANEUVER)
    assert [m.kind for m in msgs if m.startswith("Maniobra")] == [ChatKind.YOUR_TURN]
    assert colors_of(table, "Maniobra") == {CHAT_COLORS[ChatKind.YOUR_TURN]}

    attack_plan(session, monkeypatch)
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session.messages = []
    session._bot_continue()
    msgs = session._done()
    attack = [m for m in msgs if m.startswith("El bot ataca")]
    assert [m.kind for m in attack] == [ChatKind.ATTACK]
    assert colors_of(table, "El bot ataca") == {CHAT_COLORS[ChatKind.ATTACK]}


def test_a_warning_and_the_bot_actions_have_their_colors(brig, monkeypatch):
    session, table, game, fake = brig
    session.say("Aviso de prueba", ChatKind.WARNING)
    session._warn("medusa", "off", "Medusa esta fuera del tablero")
    assert [m.kind for m in session.messages] == [ChatKind.WARNING] * 2

    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.turn, game.actions_left, session.bot_stage = 0, 1, None
    session.messages = []
    session._bot_continue()
    moves = [m for m in session.messages if m.startswith("El bot hace maneuver")]
    assert [m.kind for m in moves] == [ChatKind.MOVE]
    assert session.messages[-1].kind is ChatKind.YOUR_TURN and session.messages[-1].startswith("Tu turno")


def test_a_plain_say_is_neutral(brig):
    session, table, game, fake = brig
    session.say("Sin categoria")
    assert session.messages[-1].kind is ChatKind.NEUTRAL


def test_colors_add_no_messages_to_tts(brig):
    session, table, game, fake = brig
    n = fake.lua_messages
    click(session, table, Event.MANEUVER)
    assert fake.lua_messages - n == 1 and table.broadcast_colors and len(table.broadcast_colors) == len(table.broadcasts)


def test_the_announcer_without_live_ui_colors_by_kind(brig):
    session, table, game, fake = brig
    play.make_announcer(session.client, echo=lambda s: None)(
        [Msg("Ataque", ChatKind.ATTACK), "Texto plano", Msg("Aviso", ChatKind.WARNING)])
    assert table.broadcast_colors == [CHAT_COLORS[ChatKind.ATTACK], CHAT_COLORS[ChatKind.NEUTRAL],
                                      CHAT_COLORS[ChatKind.WARNING]]


def test_the_terminal_echo_has_no_color_codes(brig):
    session, table, game, fake = brig
    shown = []
    play.make_announcer(session.client, echo=shown.append, to_table=False)([Msg("Ataque", ChatKind.ATTACK)])
    assert shown == ["[bot] Ataque"] and "\x1b" not in shown[0]


# ---------- Lua real ----------
@pytest.mark.skipif(lua54 is None, reason="sin lupa")
@pytest.mark.parametrize("kind", list(ChatKind))
def test_lua_runs_the_broadcast_with_the_color(kind):
    here = os.path.dirname(__file__)
    rt = lua54.LuaRuntime()
    rt.execute(open(os.path.join(here, "lua_stub.lua"), encoding="utf-8").read())
    rt.globals().JSON = rt.table_from({"encode": lambda v: "{}"})
    rt.execute("function __f()\n" + lua.broadcast("Hola mesa", kind) + "\nend\n__f()")
    last = rt.eval("BROADCASTS[#BROADCASTS]")
    assert last.text == "Hola mesa" and (last.r, last.g, last.b) == CHAT_COLORS[kind]
