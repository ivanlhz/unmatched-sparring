"""Every bot action is announced first, held `action_announce_hold` seconds and only then written (Ivan, 30/10).

Batch mode: the line and the pause (`lua.hold`) ride one TTS script that goes out BEFORE the script with the action's
table writes. Nothing here sleeps (the hold is a marker op inside the script) and nothing touches the real ports."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from sparring.play import ConfigError, load_config
from sparring.session import DEFAULT_ACTION_ANNOUNCE_HOLD, SessionConfig
from test_multihero_bridge import REAL_CONFIG
from test_pausa_y_ataque import cfg_file  # noqa: F401
from test_d3_table_effects import bot_turn, human_hand
from test_e2_human_cards import put_adjacent, rig, with_rig  # noqa: F401

LIZ_HAND = ("B.P.R.D. Training", "Evade", "Pyrotechnics", "Rekindle", "Searing Clarity")
HOLD = {"action_announce_hold": 2.0}


def tag_of(script: str) -> str:
    return script.split(chr(10), 1)[0].removeprefix("-- sparring:")


def announced_at(scripts, text):
    """Index of the hold that follows the broadcast of `text` (a long line goes out in several chunks)."""
    for i, s in enumerate(scripts):
        if tag_of(s) == "broadcast" and text in s:
            j = i
            while tag_of(scripts[j]) == "broadcast":
                j += 1
            if tag_of(scripts[j]) == "hold":
                return j
    raise AssertionError(f"{text!r} is never broadcast and then held: {[tag_of(s) for s in scripts]}")


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND, **HOLD)
def test_a_maneuver_is_said_and_held_before_the_bot_moves_anything(rig):
    session, table, game, fake, cfg = rig
    assert cfg.session_config().action_announce_hold == 2.0
    human_hand(table, game, "Exploit", "Iron Teeth")
    mark = len(table.scripts)
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    scripts = table.scripts[mark:]
    first = announced_at(scripts, "El bot maniobra")
    after = [tag_of(x) for x in scripts[first + 1:]]
    assert after[:2] == ["deal_cards", "set_health_dials"], "the draw and the dials are written after the pause"
    assert "deal_cards" not in [tag_of(x) for x in scripts[first - 2:first]]
    bot_lines = [m for m in msgs if m.startswith("El bot maniobra")]
    assert len(bot_lines) == 2 and all(m.shown for m in bot_lines), "said once: not broadcast again"


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND, **HOLD)
def test_an_attack_is_said_and_held_before_the_card_goes_down(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "koschei", "liz")
    human_hand(table, game, "Exploit", "Iron Teeth")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    mark = len(table.scripts)
    msgs = bot_turn(session, table, [Act("attack", fid="liz", target="koschei", card=training)])
    scripts = table.scripts[mark:]
    said_at = announced_at(scripts, "El bot ataca con liz a koschei")
    assert tag_of(scripts[said_at + 1]) == "play_card_face_down"
    assert not any("El bot ataca con liz a koschei: deja" in m for m in msgs)
    assert "Deja tu defensa boca abajo (o nada) y pulsa Revelar." in msgs


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND, **HOLD)
def test_the_result_of_the_bots_attack_is_said_and_held_before_the_discards_and_dials(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "koschei", "liz")
    human_hand(table, game, "Exploit", "Iron Teeth")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    bot_turn(session, table, [Act("attack", fid="liz", target="koschei", card=training)])
    table.face_down = []
    mark = len(table.scripts)
    click(session, table, Event.REVEAL)
    scripts = table.scripts[mark:]
    said_at = announced_at(scripts, "Combate: Liz Sherman ataca con B.P.R.D.")
    assert "set_health_dials" in [tag_of(s) for s in scripts[said_at + 1:]]
    assert "set_health_dials" not in [tag_of(s) for s in scripts[:said_at]]


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND, batch=False, **HOLD)
def test_without_batch_the_pause_is_a_sleep_between_the_announcement_and_the_writes(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    events = []
    monkeypatch.setattr("sparring.session.time.sleep", lambda s: events.append(("sleep", s)))
    real_w = session._w
    monkeypatch.setattr(session, "_w", lambda script, *a, **k: events.append(("w", script.split(chr(10), 1)[0])) or real_w(script, *a, **k))
    human_hand(table, game, "Exploit", "Iron Teeth")
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    events.clear()
    click(session, table, Event.END_ACTION)
    sleeps = [i for i, e in enumerate(events) if e == ("sleep", 2.0)]
    assert len(sleeps) == 2
    assert events[sleeps[0] - 1][1] == "-- sparring:broadcast"
    assert any(e == ("w", "-- sparring:deal_cards") for e in events[sleeps[0] + 1:sleeps[1]])


def test_the_hold_is_2_seconds_in_the_real_config_0_in_the_session_default_and_validated(cfg_file):
    assert DEFAULT_ACTION_ANNOUNCE_HOLD == 2.0 and SessionConfig.__dataclass_fields__["action_announce_hold"].default == 0.0
    assert load_config(REAL_CONFIG).session_config().action_announce_hold == 2.0
    assert load_config(cfg_file(action_announce_hold=0)).session_config().action_announce_hold == 0
    assert load_config(cfg_file(action_announce_hold=1.5)).session_config().action_announce_hold == 1.5
    for bad in (-1, 1000, "x"):
        with pytest.raises(ConfigError):
            load_config(cfg_file(action_announce_hold=bad)).session_config()


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND, **HOLD)
def test_a_failed_placement_retried_does_not_announce_the_attack_twice(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "koschei", "liz")
    human_hand(table, game, "Exploit", "Iron Teeth")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    session.ai.plan = lambda g: Act("attack", fid="liz", target="koschei", card=training)
    session.ai.pick_ability_target = lambda g: None
    mark = len(table.scripts)
    table.fail_play = True                                        # the table refuses to put the card down
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending is None and any("Error de mesa" in m for m in msgs)
    table.fail_play = False
    msgs = click(session, table, Event.END_ACTION)                # the retry
    assert session.pending is not None
    sent = [s for s in table.scripts[mark:] if tag_of(s) == "broadcast" and "El bot ataca con liz a koschei" in s]
    assert len(sent) == 1, "the line went out once, before the first try"
    assert "Deja tu defensa boca abajo (o nada) y pulsa Revelar." in msgs
