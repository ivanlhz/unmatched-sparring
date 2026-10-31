"""The bot pings as the first seated seat (the human's, in solo play): those pings must not count as the human's pick
of a look row, and the owed-draws counter settling after a look row must not be narrated as draws."""
from sparring.tts import lua
from conftest import TEST_IDENT
from sparring.tts.ui import Event
from test_d3_table_effects import answers, human_hand
from test_e3_hidden_info import (HELLBOY_HAND, rig, attack, baba_human_with_a_pact, click, defend_with, row_ids,  # noqa: F401
                                 with_rig)
from test_look_hand import ping, ping_runtime


def at_time(rt, now):
    rt.execute(f"Time = {{time = {now}}}")


def test_a_bot_ping_inside_its_window_is_not_a_pick_but_a_later_human_ping_is():
    rt = ping_runtime()
    at_time(rt, 100.0)
    rt.globals().botPingUntil = 100.0 + lua.BOT_PING_WINDOW        # what the bot's pinger marks right before pinging
    assert ping(rt, obj="g2") == [], "the bot's own ping"
    at_time(rt, 100.0 + lua.BOT_PING_WINDOW + 0.1)
    assert ping(rt, obj="g2") == [{"event": "look_ping", "guid": "g2"}], "a human ping after the window"


def test_every_ping_script_marks_the_panel_before_pinging():
    scripts = [lua.ping_points(["Blue", "Red"], [(0, 1, 0)]), lua.ping_objects(["Blue", "Red"], [["abc123"]]),
               lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=TEST_IDENT, ping=(["a1b2c3"], ["d4e5f6"], ["Blue"]))]
    for s in scripts:
        assert f'p.setVar("{lua.BOT_PING_VAR}", Time.time + {lua.BOT_PING_WINDOW})' in s
        assert s.index("markBotPing()") < s.index("pingTable")
        assert "pcall(function()" in s


@with_rig("hellboy", "baba-yaga", HELLBOY_HAND)
def test_a_settled_owed_draw_during_the_look_is_not_narrated_as_a_draw(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defend_with(session, game, monkeypatch, "On Earth As It Is In Hell")
    monkeypatch.setattr(session.ai, "choose_effect", answers(optional=[True]))
    baba_human_with_a_pact(session, table, game)
    human_hand(table, game, "Remove A Painful Memory", "Exploit")
    game.drawn[session.bot] = 1
    attack(session, table, game, "baba", "hellboy", "Remove A Painful Memory")
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{row_ids(session)[0]}"})
    line = next(m for m in msgs if m.startswith("Tu carta"))
    assert "roba -" not in line and "del mazo a su mano" not in line
    assert "miras la mano del bot" in line and "descarta" in line
