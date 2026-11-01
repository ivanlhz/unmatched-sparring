"""Pause between the bot's actions (no extra messages to TTS) and the Attack button with a single message."""
import pytest

from sparring.ai_medusa import Act
from sparring.play import ConfigError, load_config, parse_args
from sparring.session import DEFAULT_BOT_PAUSE, SessionConfig
from sparring.tts.ui import Event
from test_batch import brig, click, human_plays  # noqa: F401
from test_play import REAL_CONFIG, cfg_file  # noqa: F401


def bot_turn(session, game, monkeypatch, fake, table, plan):
    """End action with the human out of actions: the bot plays its whole turn. Returns the messages it cost."""
    monkeypatch.setattr(session.ai, "plan", plan)
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    n = fake.lua_messages
    click(session, table, Event.END_ACTION)
    return fake.lua_messages - n


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr("sparring.session.time.sleep", calls.append)
    return calls


def maneuver(g):
    return Act("maneuver", moves={"medusa": 0})


# ---------- A: pause between actions ----------
def test_the_bot_pauses_after_each_action_and_before_your_turn(brig, monkeypatch, sleeps):
    session, table, game, fake = brig
    session.cfg.bot_pause = 1.0
    cost = bot_turn(session, game, monkeypatch, fake, table, maneuver)
    assert game.turn == 1 and game.turn_no == 4
    assert sleeps == [1.0, 1.0], "one pause after each of the 2 actions; the last one separates from \"Your turn\""
    assert table.sent[-3:] == ["composite"] * 3 and cost == 4, "a start-up snapshot and 3 composites, with a pause or not"


def test_a_zero_pause_never_sleeps_and_costs_the_same(brig, monkeypatch, sleeps):
    session, table, game, fake = brig
    assert session.cfg.bot_pause == 0.0 and SessionConfig.__dataclass_fields__["bot_pause"].default == 0.0
    assert bot_turn(session, game, monkeypatch, fake, table, maneuver) == 4     # same as with a pause
    assert sleeps == []


def test_no_pause_when_the_bot_attacks_it_waits_for_you(brig, monkeypatch, sleeps):
    session, table, game, fake = brig
    session.cfg.bot_pause = 1.0
    card = next(c for c in game.players[0].full_set if c.title == "Snipe")
    bot_turn(session, game, monkeypatch, fake, table,
             lambda g: Act("attack", fid="medusa", target="hellboy", card=card))
    assert session.pending is not None and session.pending.kind == "bot_attacks" and sleeps == []


def test_the_pause_is_measured_outside_the_timed_action(brig, monkeypatch):
    session, table, game, fake = brig
    session.cfg.bot_pause = 0.5
    clock = [0.0]
    monkeypatch.setattr("sparring.session.time.sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr("sparring.session.time.monotonic", lambda: clock[0])
    bot_turn(session, game, monkeypatch, fake, table, maneuver)
    actions = [took for label, _, took in session.cost_log if label == "accion del bot"]
    assert len(actions) == 2 and actions == [0.0, 0.0], "--timing mide mensajes, no la pausa"


def test_bot_pause_config_default_override_and_validation(cfg_file):
    assert DEFAULT_BOT_PAUSE == 1.0
    assert load_config(REAL_CONFIG).session_config().bot_pause == 1.0
    assert load_config(cfg_file()).session_config().bot_pause == DEFAULT_BOT_PAUSE
    assert load_config(cfg_file(bot_pause=0)).session_config().bot_pause == 0
    for bad in (-1, 31, "x"):
        with pytest.raises(ConfigError):
            load_config(cfg_file(bot_pause=bad)).session_config()
    assert parse_args(["--bot-pause", "0"]).bot_pause == 0 and parse_args([]).bot_pause is None


# ---------- B: the Attack button ----------
def click_attack(session, table):
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    n, k = session.client.calls, len(table.sent)
    click(session, table, Event.ATTACK, {"target": "medusa"})
    return session.client.calls - n, table.sent[k:]


def test_attack_never_reads_the_human_hand_and_costs_one_message(brig):
    session, table, game, fake = brig
    table.human_hand = []
    cost, sent = click_attack(session, table)
    assert session.pending is not None and not session.pending.defended
    assert cost == 1 and sent == ["composite"], sent
    assert not any(t in ("read_hand", "count_hand") for t in table.sent)


def test_button_message_counts_attack_vs_maneuver_vs_end_action(brig):
    session, table, game, fake = brig
    costs = {}
    for label, ev in (("maneuver", Event.MANEUVER), ("end action", Event.END_ACTION)):
        n = fake.lua_messages
        click(session, table, ev)
        costs[label] = fake.lua_messages - n
    costs["attack"] = click_attack(session, table)[0]
    assert costs == {"maneuver": 1, "end action": 1, "attack": 1}


def test_reveal_refuses_an_illegal_attack_card_before_the_bot_defends(brig):
    session, table, game, fake = brig
    click_attack(session, table)
    human_plays(table, game, "Pancakes!")                 # a scheme, no use for attacking
    click(session, table, Event.REVEAL)
    assert any("Carta ilegal" in m for m in session.messages)
    p = session.pending
    assert p is not None and not p.defended and p.bot_card is None, "the bot has not placed a defense"
    human_plays(table, game, "Service Pistol")            # changes the card and reveals again
    click(session, table, Event.REVEAL)
    assert session.pending is None


def test_reveal_without_any_card_warns_and_cancel_closes_cleanly(brig):
    session, table, game, fake = brig
    click_attack(session, table)
    click(session, table, Event.REVEAL)
    assert any("no hay ninguna carta tuya" in m for m in session.messages) and session.pending is not None
    click(session, table, Event.CANCEL)
    assert session.pending is None and session.chosen_attacker is None
