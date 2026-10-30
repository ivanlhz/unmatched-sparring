"""Pact Of Peace in a live session (Ivan, 30/10: "no esta aplicando el dano correctamente cuando termina el turno").

Baba Yaga is the human with the Pact in play, Liz Sherman the bot. At the end of each turn every HERO that attacked
that turn loses 1 hp (effect damage); the dial of that hero must follow and the chat must say it, whichever end of
turn it is (the bot's, inside `_bot_continue`, or the human's, in `_after_human_action`)."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, human_attack, human_hand, said
from test_e2_human_cards import put_adjacent, rig, with_rig  # noqa: F401

LIZ_HAND = ("B.P.R.D. Training", "Evade", "Pyrotechnics", "Rekindle", "Searing Clarity")
BABA_HAND = ("Iron Teeth", "Exploit", "Deathless", "Foul Journey", "Out Of Time")


def pact_in_play(game):
    pact = next(c for c in game.players[1].deck if c.title == "Pact Of Peace")
    game.players[1].deck.remove(pact)
    game.fx.set_ongoing(1, pact.card_id)
    return pact


def dial(session, table, fid):
    return table.dials[session.cfg.dials[fid]]["value"]


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND)
def test_the_bot_hero_that_attacked_loses_1_at_the_end_of_its_turn_and_its_dial_follows(rig):
    session, table, game, fake, cfg = rig
    pact_in_play(game)
    put_adjacent(game, table, cfg, "koschei", "liz")
    human_hand(table, game, "Exploit", "Iron Teeth")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    liz, baba = game.fighters["liz"], game.fighters["baba"]
    bot_turn(session, table, [Act("attack", fid="liz", target="koschei", card=training)])
    table.face_down = []
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.END_ACTION)
    assert game.turn == 1 and liz.hp == 15 and baba.hp == 13
    assert dial(session, table, "liz") == 15, "the dial of the bot hero follows the end-of-turn damage"
    assert dial(session, table, "baba") == 13
    assert not said(msgs, "Aviso: el dial")
    assert said(msgs, "Pact Of Peace") and said(msgs, "liz -1 PV (15)")


def baba_attacks_and_ends_her_turn(session, table, game, cfg):
    """Baba hits Liz with Iron Teeth (she picks Liz), Koschei stands in her zone, and the turn ends on its own."""
    put_adjacent(game, table, cfg, "liz", "baba")
    put_adjacent(game, table, cfg, "koschei", "baba")
    human_hand(table, game, *BABA_HAND)
    human_attack(session, table, game, "baba", "liz", "Iron Teeth")
    click(session, table, Event.REVEAL)
    click(session, table, Event.CHOICE, {"i": 1})                  # Iron Teeth: the fighter it hurts
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND)
@pytest.mark.parametrize("pass_to_koschei", [True, False])
def test_fateful_bargains_at_the_end_of_your_turn_still_applies_the_pact_damage(rig, pass_to_koschei):
    """Ivan, 30/10: 'Koschei recibe el dano (1) en lugar de Baba Yaga?' then 'Efecto resuelto' and nobody lost a hit
    point: the next turn began while the question waited and cleared who attacked."""
    session, table, game, fake, cfg = rig
    pact_in_play(game)
    baba, koschei = game.fighters["baba"], game.fighters["koschei"]
    msgs = baba_attacks_and_ends_her_turn(session, table, game, cfg)
    assert said(msgs, "Koschei recibe el dano (1) en lugar de Baba Yaga? - Pact Of Peace")
    assert baba.hp == 13 and koschei.hp == 3
    msgs = click(session, table, Event.CHOICE, {"i": 1 if pass_to_koschei else 2})
    assert (baba.hp, koschei.hp) == ((13, 2) if pass_to_koschei else (12, 3))
    assert dial(session, table, "baba") == baba.hp and dial(session, table, "koschei") == koschei.hp
    assert game.turn == 0 or said(msgs, "Tu turno")
    assert said(msgs, "Pact Of Peace")


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND)
def test_baba_that_attacked_loses_1_at_the_end_of_your_turn_without_koschei_and_her_dial_follows(rig):
    session, table, game, fake, cfg = rig
    pact_in_play(game)
    put_adjacent(game, table, cfg, "liz", "baba")
    human_hand(table, game, *BABA_HAND)
    human_attack(session, table, game, "baba", "liz", "Iron Teeth")
    click(session, table, Event.REVEAL)
    click(session, table, Event.CHOICE, {"i": 1})
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    baba = game.fighters["baba"]
    assert baba.hp == 12 and dial(session, table, "baba") == 12
    assert said(msgs, "Pact Of Peace: baba -1 PV (12)")
