"""The combat result reaches the table BEFORE the human answers an AFTER choice (Ivan, 31/10, Rekindle): the damage is
dealt at the reveal, so the summary, the bot's card lines and the health dials are out first; the choice follows, and
once answered "Tu carta: ..." is said. A resume from a save made at the pause repeats none of it."""
from __future__ import annotations

import json

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said, twin_session
from test_e2_human_cards import press, put_adjacent, rig, with_rig  # noqa: F401

REKINDLE_RIG = ("hellboy", "liz-sherman", "Glimpse Of Hell", "Right Hand Of Doom", "Excalibur", "Second Shot", "Pancakes!")


def hellboy_hits_rekindle(session, table, game, cfg):
    """Bot Hellboy attacks with Right Hand Of Doom (4); Liz defends with Rekindle (2) with Fireball and Evade on her
    pile. Returns the messages of Revelar, which stop at Rekindle's choice."""
    put_adjacent(game, table, cfg, "liz", "hellboy")
    fireball, evade = card_ids(game, 1, "Fireball", "Evade")
    table.human_discard = [fireball, evade]
    human_hand(table, game, "Rekindle", "Pyrotechnics")
    doom = next(c for c in game.players[0].hand if c.title == "Right Hand Of Doom")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="liz", card=doom)])
    rekindle = card_ids(game, 1, "Rekindle")[0]
    table.face_down = [{"id": rekindle, "guid": f"h{rekindle}"}]
    table.human_hand.remove(rekindle)
    table.human_count -= 1
    return click(session, table, Event.REVEAL), (fireball, evade)


@with_rig(*REKINDLE_RIG)
def test_the_summary_and_the_dial_come_before_the_after_choice(rig):
    session, table, game, fake, cfg = rig
    hp = game.fighters["liz"].hp
    dial = cfg.session_config().dials["liz"]
    msgs, _ = hellboy_hits_rekindle(session, table, game, cfg)
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "cards"
    assert game.fighters["liz"].hp == hp - 2
    assert said(msgs, "Combate: Hellboy ataca con Right Hand Of Doom (4)") and said(msgs, "Dano 2.")
    assert said(msgs, "El bot descarta Right Hand Of Doom por ataque")
    assert table.dials[dial]["value"] == hp - 2, "the dial moved at the reveal, not after the choice"
    assert not said(msgs, "Tu carta: Rekindle")
    summary = next(i for i, m in enumerate(msgs) if m.startswith("Combate:"))
    ask = next(i for i, m in enumerate(msgs) if "Rekindle: saca de tu descarte" in m)
    assert summary < ask


@with_rig(*REKINDLE_RIG)
def test_after_the_choice_the_card_is_narrated_and_the_summary_is_not_repeated(rig):
    session, table, game, fake, cfg = rig
    msgs, (fireball, evade) = hellboy_hits_rekindle(session, table, game, cfg)
    table.human_discard.remove(fireball)          # Ivan 31/10: the human shuffles them into the deck, the bot detects it
    table.human_discard.remove(evade)
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "Tu carta: Rekindle: ")
    assert not said(msgs, "Combate:") and not said(msgs, "El bot descarta Right Hand Of Doom")
    assert session.pending is None and game.fighters["liz"].hp == 14


@with_rig(*REKINDLE_RIG)
def test_a_resume_at_the_after_choice_repeats_nothing(rig):
    session, table, game, fake, cfg = rig
    hp = game.fighters["liz"].hp
    msgs, (fireball, evade) = hellboy_hits_rekindle(session, table, game, cfg)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert twin.effect_run.awaiting.kind == "cards" and twin.game.fighters["liz"].hp == hp - 2
    msgs = []
    table.human_discard.remove(fireball)
    table.human_discard.remove(evade)
    msgs = click(twin, table, Event.CHOICE, {"i": 1})
    assert twin.pending is None and twin.game.fighters["liz"].hp == hp - 2
    assert said(msgs, "Tu carta: Rekindle: ") and not said(msgs, "Combate:")
    assert table.dials[cfg.session_config().dials["liz"]]["value"] == hp - 2


@with_rig(*REKINDLE_RIG)
def test_rekindle_asks_for_up_to_n_by_hand_and_accepts_fewer(rig):
    session, table, game, fake, cfg = rig
    msgs, (fireball, evade) = hellboy_hits_rekindle(session, table, game, cfg)
    assert said(msgs, "Rekindle: saca de tu descarte hasta 2 cartas") and session.panel_labels()
    table.human_discard.remove(fireball)
    msgs = click(session, table, Event.CHOICE, {"i": 1})           # up to 3: one is valid
    assert said(msgs, "Anoto") and session.effect_run is None and not any("pulsa una de las opciones" in m for m in msgs)
