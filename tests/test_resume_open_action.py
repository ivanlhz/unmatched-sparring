"""A save taken while the human's step after an action is open (`moving`: "Resolve the effects ... press End action")
must not survive a resume as a stale flag: Ivan, 1/11 (Hellboy bot vs Raphael), resumed after the bot's combat, the
turn passed to the human at once and their first action button was refused with "You already have an action open"."""
from __future__ import annotations

import json

from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Session
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn
from test_e2_human_cards import HELLBOY_VS_ABE, put_adjacent, rig, with_rig  # noqa: F401


def reborn(session, cfg, saved):
    other = Session(Game.new(cfg.board, seed=3, controllers={}, bot_player=0, heroes=cfg.heroes), session.client,
                    MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(json.loads(json.dumps(saved)))
    other.snap = None
    other.ai.plan = lambda g: Act("maneuver", moves={})
    other.ai.pick_ability_target = lambda g: None
    return other


def after_bot_attack(session, table, game, cfg):
    put_adjacent(game, table, cfg, "abe", "hellboy")
    bot_turn(session, table, [Act("attack", fid="abe", target="hellboy", card=game.players[0].hand[0])])
    click(session, table, Event.REVEAL)


def said_open(twin):
    return any("accion abierta" in m or "action open" in m for m in twin.messages)


@with_rig(*HELLBOY_VS_ABE)
def test_resume_in_the_bots_after_step_keeps_waiting_for_end_action_then_the_human_can_act(rig):
    session, table, game, fake, cfg = rig
    after_bot_attack(session, table, game, cfg)
    assert session.moving and game.turn == session.bot and session.pending is None
    twin = reborn(session, cfg, session.to_dict())
    twin.resume()
    assert twin.moving and twin.game.turn == twin.bot, "the turn does not pass before End action"
    assert said_open(twin)
    click(twin, table, Event.END_ACTION)
    assert not twin.moving and twin.game.turn == twin.human
    before = twin.game.actions_left
    click(twin, table, Event.MANEUVER)
    assert twin.game.actions_left == before - 1 and twin.moving


@with_rig(*HELLBOY_VS_ABE)
def test_resume_on_the_humans_own_open_action_says_so_and_end_action_closes_it(rig):
    session, table, game, fake, cfg = rig
    click(session, table, Event.MANEUVER)
    assert session.moving and game.turn == session.human
    twin = reborn(session, cfg, session.to_dict())
    twin.resume()
    assert said_open(twin)
    click(twin, table, Event.END_ACTION)
    assert not twin.moving
    before = twin.game.actions_left
    click(twin, table, Event.MANEUVER)
    assert twin.game.actions_left == before - 1


@with_rig(*HELLBOY_VS_ABE)
def test_a_resume_with_nothing_open_has_no_stale_flag(rig):
    session, table, game, fake, cfg = rig
    twin = reborn(session, cfg, session.to_dict())
    twin.resume()
    assert not twin.moving and not said_open(twin)
    before = twin.game.actions_left
    click(twin, table, Event.MANEUVER)
    assert twin.game.actions_left == before - 1
