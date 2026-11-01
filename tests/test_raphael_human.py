"""Raphael played BY THE HUMAN through the panel (FakeTTS, batch mode): ANGER ISSUES, the numbers of his cards, the choices
the panel asks and what the table is told to do (the discards a card owes, the card Relentless shuffles away).
The bot's side of the same cards is in tests/test_raphael_effects.py."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, card_ids, human_attack, human_hand, said, set_hand
from test_e2_human_cards import press, put_adjacent
from test_choice_infra import visible_choices


@pytest.fixture
def rig(request, tmp_path):
    bot_hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "raphael", bot_hand)
    put_adjacent(game, table, cfg, "raphael", "hellboy")
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand):
    return pytest.mark.parametrize("rig", [bot_hand], indirect=True)


def defends(session, game, monkeypatch, title):
    card = next((c for c in game.players[0].hand if c.title == title), None)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: card)
    return card


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


TRAINING = "B.P.R.D. Training"      # a defense of value 3 that does not hurt Raphael


@with_rig(TRAINING, TRAINING)
def test_anger_issues_the_first_lost_attack_gives_an_action_back_and_the_second_does_not(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Let's do this!", "Let's do this!")
    msgs = attack(session, table, game, "raphael", "Let's do this!")
    assert said(msgs, "Tu habilidad: ANGER ISSUES: ganas 1 accion") and game.actions_left == 2 and game.fx.lost == [0, 1]
    click(session, table, Event.END_ACTION)
    set_hand(session, table, game, TRAINING)
    defends(session, game, monkeypatch, TRAINING)
    msgs = attack(session, table, game, "raphael", "Let's do this!")
    assert not said(msgs, "ANGER ISSUES") and game.actions_left == 1 and game.fx.lost == [0, 2]


@with_rig(TRAINING)
def test_anger_issues_a_won_attack_gives_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Sai")
    msgs = attack(session, table, game, "raphael", "Sai")
    assert not said(msgs, "ANGER ISSUES") and game.actions_left == 1 and game.fx.lost == [1, 0]     # the bot lost it


@with_rig(TRAINING, TRAINING)
def test_payback_time_after_a_lost_combat_this_turn_is_worth_five(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Let's do this!", "Payback time!")
    attack(session, table, game, "raphael", "Let's do this!")
    click(session, table, Event.END_ACTION)
    set_hand(session, table, game, TRAINING)
    defends(session, game, monkeypatch, TRAINING)
    msgs = attack(session, table, game, "raphael", "Payback time!")
    assert said(msgs, "Raphael ataca con Payback time! (5)") or said(msgs, "total 5"), msgs


@with_rig(TRAINING)
def test_relentless_is_shuffled_into_the_deck_and_the_human_is_told_to_do_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Relentless", "Sai")
    msgs = attack(session, table, game, "raphael", "Relentless")
    assert said(msgs, "Pon Relentless de tu zona de combate en tu mazo y baraja")
    assert not said(msgs, "Devuelve 1 carta de tu mano")
    assert not any(c.title == "Relentless" for c in game.players[1].discard) and said(msgs, "Tu carta: Relentless: robas 1")


@with_rig(TRAINING)
def test_unbridled_rage_asks_how_many_and_the_table_owes_those_discards(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Unbridled rage", "Sai", "Heroes in a half shell", "Let's do this!")
    msgs = attack(session, table, game, "raphael", "Unbridled rage")
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "amount"
    assert session.effect_run.awaiting.options == list(range(len(game.players[1].hand) + 1))
    msgs = press(session, table, 2)
    assert said(msgs, "Descarta 2 carta(s) (Unbridled rage)")
    assert said(msgs, "Unbridled rage (3) y Unbridled rage (+4): total 7") and said(msgs, "Dano 4")


@with_rig(TRAINING)
def test_unbridled_rage_with_zero_cards_is_just_a_three(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Unbridled rage", "Sai")
    attack(session, table, game, "raphael", "Unbridled rage")
    msgs = press(session, table, 0)
    assert said(msgs, "Raphael ataca con Unbridled rage (3): total 3") and not said(msgs, "Descarta")


@with_rig(TRAINING)
def test_break_something_cancels_the_bots_after_effect_and_hurts_nobody(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Break something")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "raphael", "Break something")
    assert not said(msgs, "Aplicado: B.P.R.D. Training") and game.fighters["hellboy"].hp == hp


@with_rig()
def test_break_something_against_no_defense_hits_an_adjacent_rival_for_two_more(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    human_hand(table, game, "Break something")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "raphael", "Break something")
    assert game.fighters["hellboy"].hp == hp - 2 - 2


@with_rig()
def test_crowd_control_draws_and_hurts_the_adjacent_rivals(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    human_hand(table, game, "Crowd control")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "raphael", "Crowd control")
    assert game.fighters["hellboy"].hp == hp - 2 - 1 and said(msgs, "Tu carta: Crowd control: ")


@with_rig()
def test_slapshot_by_casey_is_six_next_to_the_rival(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    put_adjacent(game, table, cfg, "casey", "hellboy")
    human_hand(table, game, "Slapshot")
    msgs = attack(session, table, game, "casey", "Slapshot")
    assert said(msgs, "Casey Jones ataca con Slapshot (2) y Slapshot (+4): total 6") or said(msgs, "total 6"), msgs
