"""F12: ping de atacante y objetivo dentro del script del ataque del bot."""
import json
import re

import pytest

from sparring.ai_medusa import Act
from sparring.tts import lua
from sparring.tts.ui import Event
from conftest import TEST_IDENT
from test_batch import brig, click  # noqa: F401
from test_review9 import BOT_ID, conv, rt, run  # noqa: F401
from test_session import PIECES, rig, set_bot_hand  # noqa: F401


def play_scripts(table):
    return [s for s in table.scripts if s.startswith("-- sparring:play_card_face_down")]


def bot_attack(session, table, game):
    set_bot_hand(table, game, "Gaze of Stone")
    session.read_bot_hand()
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.pending is not None and session.pending.kind == "bot_attacks"
    return session.pending


def assert_pings(script, attacker_guid, target_guid, seat="Blue"):
    assert f'Player["{seat}"].pingTable' in script
    assert f'pingAt({{"{attacker_guid}"}})' in script
    assert f'local targets = {{"{target_guid}"}}' in script
    assert script.index("pingAt({") < script.index("o.setPosition")     # el ping sale antes de mover la carta


def test_bot_attack_script_pings_attacker_and_target(rig):
    session, table, game = rig
    p = bot_attack(session, table, game)
    scripts = play_scripts(table)
    assert len(scripts) == 1
    assert_pings(scripts[0], PIECES[p.attacker.fid], PIECES[p.target.fid])
    assert "pcall(function()" in scripts[0]


def test_ping_adds_no_extra_message(rig):
    session, table, game = rig
    bot_attack(session, table, game)
    assert not any("ping" in tag for tag in table.sent)      # el ping viaja dentro del script de la carta


def test_batch_ping_travels_inside_the_composite(brig, monkeypatch):
    session, table, game, fake = brig
    p = bot_attack(session, table, game)
    scripts = play_scripts(table)
    assert len(scripts) == 1
    assert_pings(scripts[0], PIECES[p.attacker.fid], PIECES[p.target.fid])
    assert not any("ping" in t for t in table.sent)
    assert sum(m.count("play_card_face_down") for m in table.msglog) == 1   # un solo script de carta, con el ping dentro


def test_human_attack_card_has_no_ping(rig):
    session, table, game = rig
    set_bot_hand(table, game, "Gaze of Stone")
    session.read_bot_hand()
    session.handle(Event.ATTACKER, {"attacker": "att_hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    for s in play_scripts(table):
        assert "pingTable" not in s


def test_ping_requires_guids():
    with pytest.raises(ValueError):
        lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=TEST_IDENT, ping=([], ["abc123"]))
    with pytest.raises(ValueError):
        lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=TEST_IDENT, ping=(["abc123"], ['x"); os.exit() --']))


def test_ping_script_stays_composable_and_without_banned_channels():
    s = lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=TEST_IDENT, ping=(["a1b2c3"], ["d4e5f6"]))
    lua.composite([s])
    assert "UI." not in s and "messageID" not in s


def test_lua_pings_both_pieces_and_survives_missing_ping_api(rt):
    rt.execute("""
mkobj({guid = 'aaa111', type = 'Figurine', pos = {x = 3, y = 1, z = 4}})
mkobj({guid = 'bbb222', type = 'Figurine', pos = {x = -2, y = 1, z = 7}})
mkobj({guid = 'c1', type = 'Card', cid = 17605, owner = 'medusa', hand = 'Green'})
""")
    script = lua.play_card_face_down(17605, "Green", 6.0, 1.6, -18.0, 0.0, identity=BOT_ID,
                                     ping=(["zzz999", "aaa111"], ["bbb222"]))
    res = run(rt, script)
    assert res == {"played": "c1"}
    # el segundo ping espera un temporizador (Wait.time); el primero ya ha salido
    pings = conv(rt.eval("PINGS"))
    assert pings == [{"color": "Green", "x": 3, "y": 1, "z": 4}]
    rt.execute("for _, f in ipairs(TIMERS) do f() end")
    pings = conv(rt.eval("PINGS"))
    assert [(p["x"], p["z"]) for p in pings] == [(3, 4), (-2, 7)]


def test_lua_ping_failure_never_breaks_the_attack(rt):
    rt.execute("""
mkobj({guid = 'aaa111', type = 'Figurine'})
mkobj({guid = 'bbb222', type = 'Figurine'})
mkobj({guid = 'c1', type = 'Card', cid = 17605, owner = 'medusa', hand = 'Green'})
local real = Player
Player = setmetatable({}, {__index = function(_, c)
  local p = real[c]
  p.pingTable = function() error('sin jugador sentado') end
  return p
end})
""")
    script = lua.play_card_face_down(17605, "Green", 6.0, 1.6, -18.0, 0.0, identity=BOT_ID,
                                     ping=(["aaa111"], ["bbb222"]))
    assert run(rt, script) == {"played": "c1"}
    rt.execute("for _, f in ipairs(TIMERS) do f() end")      # el temporizador tampoco lanza

