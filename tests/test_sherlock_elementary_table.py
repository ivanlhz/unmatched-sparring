"""Elementary at the table, the corners: the human changes the card after the question (the number they said no longer counts and the chat says so), and the human
attacks the bot's Holmes with a card a rule plays face up (Tomoe Gozen's Witness My Last Battle): its printed value is public, so the bot says that number instead
of guessing."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_hand, said
from test_e2_human_cards import put_adjacent
from test_e3_hidden_info import rig_for
from test_sherlock_human import BOT_HAND, HOLMES, HOLMES_HUMAN_HAND, bot_attacks, human_attacks, human_defends, with_rig


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand)
    game.fx.dsl_heroes |= {HOLMES}
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@with_rig("hellboy", HOLMES, BOT_HAND)
def test_a_card_swapped_for_elementary_after_the_question_withdraws_the_number(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    human_hand(table, game, *HOLMES_HUMAN_HAND)
    bot_attacks(session, table, game, "Excalibur", "hellboy", "holmes")
    human_defends(table, game, "Elementary")
    click(session, table, Event.REVEAL)
    assert session.pending.predict is not None
    feint = card_ids(game, 1, "Feint")[0]                                       # the human takes Elementary back and puts a Feint instead
    table.human_hand.append(table.face_down[0]["id"])
    table.human_hand.remove(feint)
    table.face_down = [{"id": feint, "guid": f"h{feint}"}]
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "Elementary ya no esta en la mesa: el numero que dijiste no cuenta"), msgs


@with_rig(HOLMES, "tomoe-gozen", ("Elementary", "Counterpunch", "Feint", "Confirm Suspicion", "Master of Disguise"))
def test_an_attack_played_face_up_is_predicted_by_its_printed_value(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    elementary = next(c for c in game.players[0].hand if c.title == "Elementary")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: elementary)
    tomoe = game.hero(1).fid
    put_adjacent(game, table, cfg, tomoe, "holmes")
    human_hand(table, game, "Witness My Last Battle", "Flash of Steel")
    human_attacks(session, table, game, tomoe, "holmes", "Witness My Last Battle")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "El bot juega Elementary boca arriba y dice que el valor impreso de ataque de tu carta es 7"), msgs
