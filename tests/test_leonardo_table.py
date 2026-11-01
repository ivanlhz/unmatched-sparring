"""Leonardo played by the HUMAN at the table (FakeTTS sessions, batch mode, same rig as tests/test_e2_human_cards.py):
TEAM TACTICS gates the panel until End action, and each card with an effect does what the card says in the engine while
the human moves their own miniatures by hand and the bot's pieces are chosen on the panel."""
from __future__ import annotations

import json

from sparring.session import Session
from sparring.state import Game
from sparring.ai_medusa import MedusaAI
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import (adjacent_free, bot_defends_with_nothing, by_hand, human_scheme, labels, press,  # noqa: F401
                                 put_adjacent, rig, with_rig)

LEO_VS_HELLBOY = ("hellboy", "leonardo", "Excalibur", "Service Pistol")


@with_rig(*LEO_VS_HELLBOY)
def test_team_tactics_blocks_every_button_but_end_action_until_done_and_survives_a_resume(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Katana", "Quick strike")
    msgs = bot_turn(session, table, [])
    assert game.turn == 1 and session.ability_wait is not None and said(msgs, "TEAM TACTICS: puedes mover cualquier luchador 1 casilla")
    states = session.panel_view()[1]
    assert states["btn_end"] == (True, True) and states["btn_maneuver"] == (False, False)
    msgs = click(session, table, Event.MANEUVER)
    assert said(msgs, "Primero tu habilidad de inicio de turno") and game.actions_left == 2
    saved = json.loads(json.dumps(session.to_dict()))
    other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    assert other.ability_wait == session.ability_wait and said(other.resume(), "Tu habilidad de inicio de turno sigue pendiente")
    foe = cfg.nicknames["hellboy"]
    table.positions[foe] = adjacent_free(game, "hellboy")                       # the human moved the BOT's miniature one space
    msgs = click(session, table, Event.END_ACTION)
    assert session.ability_wait is None and said(msgs, "Habilidad de inicio de turno hecha")
    assert session.panel_view()[1]["btn_maneuver"] == (True, True)


@with_rig(*LEO_VS_HELLBOY)
def test_quick_strike_draws_in_the_engine_and_the_cards_are_dealt_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Quick strike", "Katana")
    human_attack(session, table, game, "leonardo", "hellboy", "Quick strike")
    msgs = click(session, table, Event.REVEAL)
    assert len(game.players[1].hand) == 2 - 1 + 1 and table.human_deals == [1]
    assert any("Tu carta: Quick strike: robas 1" in m for m in msgs), msgs


@with_rig(*LEO_VS_HELLBOY)
def test_for_sensei_moves_the_bots_piece_by_panel_and_yours_by_hand_then_asks_for_the_price(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "For Sensei", "Katana", "Quick strike")
    human_attack(session, table, game, "leonardo", "hellboy", "For Sensei")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy"           # the rival's piece first (fighter id order)
    dest = req.options[0]
    by_hand(session, table, cfg, "hellboy", dest)                               # the human puts the bot's piece there
    assert game.fighters["hellboy"].pos == dest                                 # yours is never asked: it is a note
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "optional"
    msgs = press(session, table, False)
    assert session.pending is None and game.actions_left == 1                    # no discard, no extra action
    assert any("en la mesa: mueve a leonardo hasta 1 casilla" in m for m in msgs), msgs


@with_rig(*LEO_VS_HELLBOY)
def test_protective_father_swaps_by_hand_and_heals_both(rig):
    session, table, game, fake, cfg = rig
    game.fighters["leonardo"].hp, game.fighters["splinter"].hp = 10, 4
    human_hand(table, game, "Protective father", "Katana")
    click(session, table, Event.SCHEME)
    cid = card_ids(game, 1, "Protective father")[0]
    table.human_discard.append(cid)
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "optional"
    press(session, table, True)
    assert game.fighters["leonardo"].hp == 12 and game.fighters["splinter"].hp == 6
    assert game.actions_left >= 1


@with_rig(*LEO_VS_HELLBOY)
def test_leonardo_leads_leaves_both_miniatures_to_you_and_draws(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Leonardo leads", "Katana")
    click(session, table, Event.SCHEME)
    table.human_discard.append(card_ids(game, 1, "Leonardo leads")[0])
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert any("Aplico Leonardo leads" in m and "en la mesa: mueve a" in m and "leonardo" in m and "splinter" in m for m in msgs), msgs
    assert any("robas 1" in m for m in msgs)


@with_rig(*LEO_VS_HELLBOY)
def test_eat_sleep_and_breathe_ninjutsu_asks_where_the_bots_adjacent_piece_goes(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Eat, sleep, and breathe ninjutsu", "Katana")
    human_attack(session, table, game, "leonardo", "hellboy", "Eat, sleep, and breathe ninjutsu")
    before = game.fighters["hellboy"].pos
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy" and req.extra["op"] == "place"
    assert before not in req.options and all(game.board.share_zone(before, s) for s in req.options)
    by_hand(session, table, cfg, "hellboy", req.options[0])
    assert game.fighters["hellboy"].pos == req.options[0] and session.pending is None
