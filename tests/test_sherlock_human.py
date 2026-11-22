"""Sherlock Holmes on the table through the panel (FakeTTS, batch mode), both seats.

The human as Holmes: Elementary (the panel asks the number BEFORE the bot's card is revealed, the card is played face up, the answer survives a save),
Confirm Suspicion (the value is named on the panel, the bot discards a matching card or shows its hand) and the other schemes. The bot as Holmes against
the human: Elementary face up with a number guessed from public information only, Confirm Suspicion (the human lays a matching card on their discard pile or
none, and a human who says none has their hand read; a matching card found there must be discarded). The bot's side of the same cards is in
tests/test_sherlock_effects.py and tests/test_sherlock_cards.py; the AI numbers in tests/test_sherlock_ai.py.

Anti-cheat tripwires: the bot's defense never sees the attack card, the human's hand is read only by the look a card orders."""
from __future__ import annotations

import json

import pytest

from sparring import session_hidden as hidden
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said, twin_session
from test_e2_human_cards import by_hand, human_scheme, labels, press, put_adjacent
from test_e3_hidden_info import human_reads, rig_for

BOT_HAND = ("Excalibur", "Service Pistol", "Right Hand Of Doom", "B.P.R.D. Training", "Second Shot")
HOLMES_BOT_HAND = ("Elementary", "Counterpunch", "Feint", "Confirm Suspicion", "Master of Disguise")
HOLMES_HUMAN_HAND = ("Elementary", "Counterpunch", "Confirm Suspicion", "Master of Disguise", "Feint")
HOLMES = "sherlock-holmes"


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand)
    game.fx.dsl_heroes |= {HOLMES}
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(bot, human, hand):
    return pytest.mark.parametrize("rig", [(bot, human, hand)], indirect=True)


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def human_attacks(session, table, game, attacker, target, title):
    click(session, table, Event.ATTACKER, {"attacker": f"att_{attacker}"})
    click(session, table, Event.ATTACK, {"target": target})
    from test_d3_table_effects import human_plays
    played = human_plays(table, game, title)
    if played.card_id in table.human_hand:
        table.human_hand.remove(played.card_id)
    table.human_count -= 1


def bot_attacks(session, table, game, title, fid, target):
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid=fid, target=target, card=card)])
    return card


def human_defends(table, game, title):
    cid = card_ids(game, 1, title)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    return cid


# ---------------------------------------------------------------- the bot's Holmes defends with Elementary (the human attacks)

@pytest.mark.parametrize("guess, stopped", [(6, True), (4, False)])
@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_bots_elementary_is_played_face_up_with_a_number_and_a_right_number_stops_the_attack(rig, monkeypatch, guess, stopped):
    session, table, game, fake, cfg = rig
    elementary = next(c for c in game.players[0].hand if c.title == "Elementary")
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(attack_card) or elementary)
    monkeypatch.setattr(hidden, "predict_attack_value", lambda g, me, fid=None: guess)
    put_adjacent(game, table, cfg, "hellboy", "holmes")
    human_hand(table, game, "Excalibur", "Service Pistol", "Glimpse Of Hell")
    human_attacks(session, table, game, "hellboy", "holmes", "Excalibur")
    hp = game.fighters["holmes"].hp
    msgs = click(session, table, Event.REVEAL)
    assert seen == [None], "the bot defends without seeing the attack card"
    assert said(msgs, f"El bot juega Elementary boca arriba y dice que el valor impreso de ataque de tu carta es {guess}"), msgs
    assert game.fighters["holmes"].hp == (hp if stopped else hp - 3)               # Excalibur 6 against Elementary 3
    assert dial(session, cfg, table, "holmes") == game.fighters["holmes"].hp
    assert human_reads(table) == []


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_bots_elementary_prediction_is_saved_with_the_pending_combat(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    elementary = next(c for c in game.players[0].hand if c.title == "Elementary")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: elementary)
    monkeypatch.setattr(hidden, "predict_attack_value", lambda g, me, fid=None: 5)
    p = None
    put_adjacent(game, table, cfg, "hellboy", "holmes")
    human_hand(table, game, "Excalibur", "Service Pistol")
    human_attacks(session, table, game, "hellboy", "holmes", "Excalibur")
    # the bot places its defense at Reveal; the prediction is on the pending until the combat is resolved in the same click
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "dice que el valor impreso de ataque de tu carta es 5")
    assert table.flips, "the bot's card was turned face up"


# ---------------------------------------------------------------- the human's Holmes defends with Elementary (the bot attacks)

@pytest.mark.parametrize("answer, stopped", [(6, True), (3, False)])
@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_human_says_the_number_before_the_bots_card_is_revealed(rig, answer, stopped):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    human_hand(table, game, *HOLMES_HUMAN_HAND)
    bot_attacks(session, table, game, "Excalibur", "hellboy", "holmes")
    human_defends(table, game, "Elementary")
    flips = len(table.flips)
    hp = game.fighters["holmes"].hp
    msgs = click(session, table, Event.REVEAL)
    p = session.pending
    assert p is not None and p.predict is not None and session._paused()[0] == "predict"
    assert said(msgs, "Elementary: di con los botones del panel el valor impreso de ataque de la carta del bot"), msgs
    assert len(table.flips) == flips, "the bot's card stays face down until the number is given"
    assert session.panel_labels()["btn_choice_1"] == "Valor 0" and session.panel_view()[1]["btn_reveal"][0] is False
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert twin._paused()[0] == "predict" and twin.panel_labels() == session.panel_labels()
    twin.client = session.client
    if answer >= 5:                                                                # page 1 shows the values 0..4 and "Mas"; page 2 the values 5..7
        click(twin, table, Event.CHOICE, {"i": 6})
    msgs = click(twin, table, Event.CHOICE, {"i": answer - 5 + 1 if answer >= 5 else answer + 1})
    assert said(msgs, f"Dices que la carta de ataque del bot tiene valor impreso {answer}"), msgs
    assert twin.pending is None and twin._paused() is None
    assert twin.game.fighters["holmes"].hp == (hp if stopped else hp - 3)
    assert human_reads(table) == []
