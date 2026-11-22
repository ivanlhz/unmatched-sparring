"""More of Sherlock Holmes at the table (FakeTTS, batch mode): Deduce Strategy's yes/no that says what the change does, The Game is Afoot's move by hand, and the
save/resume of the questions that wait for the human: naming the value of Confirm Suspicion, and the recheck of a human who said "none" while holding a match.
Plus the engine test that a BOOST played on a card whose printed value Deduce Strategy changed still adds."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring import ai_sherlock
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import human_hand, said, twin_session
from test_e2_human_cards import human_scheme, labels, put_adjacent
from test_e3_hidden_info import human_reads, rig_for
from test_sherlock_confirm_human import HELLBOY_HUMAN_HAND, awaiting, bot_plays_confirm, lay_on_pile
from test_sherlock_effects import mk
from test_sherlock_human import BOT_HAND, HOLMES, HOLMES_BOT_HAND, HOLMES_HUMAN_HAND, with_rig
from test_sherlock_schemes_human import human_attacks_with
from test_effects_combat import pair


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand)
    game.fx.dsl_heroes |= {HOLMES}
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


# ---------------------------------------------------------------- Deduce Strategy by the human

@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_humans_deduce_strategy_says_what_the_change_does_and_yes_lowers_the_rivals_value(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")      # versatile 3, BOOST 2
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: training)
    human_hand(table, game, "Deduce Strategy", "Counterpunch", "Feint")
    human_attacks_with(session, table, game, "Deduce Strategy")
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.REVEAL)
    req = awaiting(session)
    assert req.kind == "optional" and req.extra["rival_value"] == {"now": 3, "to": 2}
    assert labels(session) == ["Cambiar 3 a 2", "No"]
    assert said(msgs, "Deduce Strategy: cambiar el valor impreso de la carta rival de 3 a su valor de POTENCIA, 2?"), msgs
    click(session, table, Event.CHOICE, {"i": 1})
    assert game.fighters["hellboy"].hp == hp - 1                          # Holmes' 3 against a 2


@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_humans_deduce_strategy_declined_leaves_the_tie(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: training)
    human_hand(table, game, "Deduce Strategy", "Counterpunch", "Feint")
    human_attacks_with(session, table, game, "Deduce Strategy")
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.REVEAL)
    click(session, table, Event.CHOICE, {"i": 2})
    assert game.fighters["hellboy"].hp == hp


def test_deduce_strategy_a_boost_played_on_top_still_adds(bprd):
    """Leonardo's Turtle power! (3, may BOOST) against Holmes' Deduce Strategy: the printed 3 becomes its BOOST, 2, then Katana's BOOST of 2 is added: 4 against 3."""
    g = mk(bprd, foe="leonardo", turn=1)
    foe, h = pair(g, "leonardo", "holmes")
    g.controllers[0].queue = [[True]]
    boost = give(g, 1, "Katana")
    flow = g.begin_attack(foe, h, give(g, 1, "Turtle power!"), give(g, 0, "Deduce Strategy"))
    flow.drive(lambda choice: boost if choice.kind == "boost" else None)
    assert flow.result.damage == 1 and h.hp == 15


# ---------------------------------------------------------------- The Game is Afoot by the human

@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_game_is_afoot_has_the_human_move_holmes_by_hand_up_to_three_spaces(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    human_hand(table, game, "The Game is Afoot", "Counterpunch", "Feint")
    human_attacks_with(session, table, game, "The Game is Afoot")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "hasta 3 casillas") and said(msgs, "pulsa Fin de accion"), msgs
    start = game.fighters["holmes"].pos
    spot = next(s for s in sorted(game.board.spaces) if s != start and game.board.distance(start, s) <= 3 and all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["holmes"]] = spot
    click(session, table, Event.END_ACTION)
    assert game.fighters["holmes"].pos == spot


# ---------------------------------------------------------------- save and resume

@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_humans_question_to_name_the_value_survives_a_save(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, *HOLMES_HUMAN_HAND)
    human_scheme(session, table, game, "Confirm Suspicion")
    req = awaiting(session)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    again = awaiting(twin)
    assert again.kind == "amount" and again.extra["confirm"] is True and list(again.options) == list(req.options)
    twin.client = session.client
    hand = list(twin.game.players[0].hand)
    hp = twin.game.fighters["hellboy"].hp
    click(twin, table, Event.CHOICE, {"i": 4})                                  # the value 3
    gone = [c for c in hand if c not in twin.game.players[0].hand]
    assert len(gone) == 1 and (gone[0].value or 0) == 3 and twin.game.fighters["hellboy"].hp == hp - gone[0].boost


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_recheck_after_saying_none_survives_a_save(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 3, *HELLBOY_HUMAN_HAND)
    click(session, table, Event.CHOICE, {"i": 1})                              # "none" although B.P.R.D. Training is a 3
    req = awaiting(session)
    assert req.extra["recheck"]
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    again = awaiting(twin)
    assert again.extra["recheck"] and again.options == req.options and again.extra["confirm"] == 3
    twin.client = session.client
    lay_on_pile(table, twin.game, "B.P.R.D. Training")
    msgs = click(twin, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "descartas B.P.R.D. Training: tu heroe recibe 2 de dano"), msgs
    assert twin.pending_discard is None and len(human_reads(table)) == 1
