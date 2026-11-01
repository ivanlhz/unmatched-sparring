"""Raphael played BY THE HUMAN through the panel (FakeTTS, batch mode): ANGER ISSUES, the numbers of his cards, the choices
the panel asks and what the table is told to do (the discards a card owes, the card Relentless shuffles away).
The bot's side of the same cards is in tests/test_raphael_effects.py."""
from __future__ import annotations

import pytest

from sparring.state import Game
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


def relentless_id(game):
    return next(c.card_id for c in game.players[1].full_set if c.title == "Relentless")


@with_rig(TRAINING)
def test_relentless_is_moved_into_the_deck_shuffled_and_one_card_is_dealt_by_the_bot(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Relentless", "Sai")
    rid = relentless_id(game)
    msgs = attack(session, table, game, "raphael", "Relentless")
    assert said(msgs, "Meto Relentless de tu zona de combate en tu mazo y lo barajo")
    assert not said(msgs, "Pon Relentless de tu zona de combate")           # nothing left for the human to do by hand
    assert table.deck_moves == [("shuffle", [rid])] and table.human_deck == [rid] and table.face_down == []
    assert table.human_deals == [1] and said(msgs, "Te he dado 1 carta")       # the deal comes after the shuffle
    assert rid in [c.card_id for c in game.players[1].deck] and not any(c.card_id == rid for c in game.players[1].discard)
    assert rid not in table.human_discard
    assert len(game.players[1].hand) == table.human_count
    session.snap = None
    click(session, table, Event.HP, {"fighter": "hellboy", "delta": 0})        # the next reading: nothing is flagged
    assert rid in [c.card_id for c in game.players[1].deck] and not any(c.card_id == rid for c in game.players[1].discard)


@with_rig(TRAINING)
def test_relentless_falls_back_to_the_instruction_when_the_table_refuses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Relentless", "Sai")
    table.stuck_in_pile = {relentless_id(game)}
    msgs = attack(session, table, game, "raphael", "Relentless")
    assert said(msgs, "Pon Relentless de tu zona de combate en tu mazo y baraja")
    assert not any(c.title == "Relentless" for c in game.players[1].discard) and said(msgs, "Tu carta: Relentless: robas 1")


def give_up(table, game, *titles):
    """The human puts these cards (from their hand) in their discard pile on the table."""
    ids = card_ids(game, 1, *titles)
    for i in ids:
        if i in table.human_hand:
            table.human_hand.remove(i)
    table.human_discard += ids
    table.human_count -= len(ids)
    return ids


def done(session, table):
    return click(session, table, Event.CHOICE, {"i": 1})


@with_rig(TRAINING)
def test_unbridled_rage_waits_for_the_cards_on_the_discard_pile_and_counts_two_each(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Unbridled rage", "Sai", "Heroes in a half shell", "Let's do this!")
    msgs = attack(session, table, game, "raphael", "Unbridled rage")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.min == 0 and not any(i in req.options for i in card_ids(game, 1, "Let's do this!"))
    assert said(msgs, "pon en tu descarte las cartas de defensa o versatiles") and not said(msgs, "Elige una cantidad")
    assert session.panel_view()[0].startswith("Pon las cartas a sacrificar")
    ids = give_up(table, game, "Sai", "Heroes in a half shell")
    msgs = done(session, table)
    assert said(msgs, "cuento Sai, Heroes in a half shell") and said(msgs, "+4")
    assert said(msgs, "Unbridled rage (3) y Unbridled rage (+4): total 7") and said(msgs, "Dano 4")
    assert session.effect_run is None and sorted(c.card_id for c in game.players[1].discard if c.card_id in ids) == sorted(ids)
    assert len(game.players[1].hand) == table.human_count                     # the engine's hand follows the table
    assert not said(msgs, "Descarta 2 carta(s)")


@with_rig(TRAINING)
def test_unbridled_rage_rejects_an_attack_card_says_why_and_accepts_it_once_taken_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Unbridled rage", "Sai", "Let's do this!")
    attack(session, table, game, "raphael", "Unbridled rage")
    sai, lets = give_up(table, game, "Sai", "Let's do this!")
    msgs = done(session, table)
    assert said(msgs, "Let's do this! (ataque) no se puede sacrificar con Unbridled rage") and said(msgs, "defensa y versatiles")
    assert not said(msgs, "Sai (") and session.effect_run is not None            # nothing was applied, still waiting
    assert game.players[1].discard == [] or lets not in [c.card_id for c in game.players[1].discard]
    table.human_discard.remove(lets)                                              # taken back to the hand
    table.human_hand.append(lets)
    table.human_count += 1
    msgs = done(session, table)
    assert said(msgs, "cuento Sai") and said(msgs, "total 5") and session.effect_run is None


@with_rig(TRAINING)
def test_unbridled_rage_with_zero_cards_is_just_a_three(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Unbridled rage", "Sai")
    attack(session, table, game, "raphael", "Unbridled rage")
    msgs = done(session, table)
    assert said(msgs, "no sacrificas ninguna carta") and said(msgs, "Raphael ataca con Unbridled rage (3): total 3")


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


# ---------------------------------------------------------------- the free boost of Turtle power! and the rival's cancel

PLANNED = "Planned Recklessness"


def hellboy_form(monkeypatch, form):
    """Planned Recklessness only cancels the rival's effects while Hellboy is OCCULT DETECTIVE."""
    real = Game.form
    monkeypatch.setattr(Game, "form", lambda self, player: form if player == 0 else real(self, player))


@with_rig(PLANNED, PLANNED)
def test_a_cancelled_turtle_power_is_not_offered_a_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hellboy_form(monkeypatch, "OCCULT DETECTIVE")
    defends(session, game, monkeypatch, PLANNED)
    human_hand(table, game, "Turtle power!", "Sai")
    msgs = attack(session, table, game, "raphael", "Turtle power!")
    assert said(msgs, "Planned Recklessness te quita el boost de Turtle power!")
    assert not said(msgs, "si quieres potenciar") and session.pending is None and session.pending_value == 0
    assert any(m.startswith("Combate:") for m in msgs)
    assert "total 3" in next(m for m in msgs if m.startswith("Combate:"))


@with_rig(PLANNED, PLANNED)
def test_turtle_power_keeps_its_boost_when_the_rival_does_not_cancel_anything(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hellboy_form(monkeypatch, "ANUNG UN RAMA")                 # as ANUNG UN RAMA Planned Recklessness cancels nothing
    defends(session, game, monkeypatch, PLANNED)
    human_hand(table, game, "Turtle power!", "Sai")
    msgs = attack(session, table, game, "raphael", "Turtle power!")
    assert said(msgs, "Turtle power! revelado: si quieres potenciar") and session.pending.wait is not None
    assert not said(msgs, "te quita el boost")


def test_short_circuit_cancels_only_the_after_effects_so_the_boost_stays(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = build(tmp_path, "donatello", "raphael", ("Short circuit",))
    put_adjacent(game, table, cfg, "raphael", "donatello")
    defends(session, game, monkeypatch, "Short circuit")
    human_hand(table, game, "Turtle power!", "Sai")
    try:
        msgs = attack(session, table, game, "raphael", "Turtle power!", target="donatello")
        assert said(msgs, "Turtle power! revelado: si quieres potenciar") and not said(msgs, "te quita el boost")
    finally:
        client.close()
        fake.close()


def test_break_something_takes_the_boost_of_a_humans_leonardo_turtle_power(tmp_path, monkeypatch):
    """DURING and AFTER are cancelled by the bot's IMMEDIATELY: the boost goes with the DURING."""
    session, table, game, fake, cfg, client = build(tmp_path, "raphael", "leonardo", ("Break something",))
    put_adjacent(game, table, cfg, "leonardo", "raphael")
    try:
        defends(session, game, monkeypatch, "Break something")
        human_hand(table, game, "Turtle power!", "For Sensei")
        msgs = attack(session, table, game, "leonardo", "Turtle power!", target="raphael")
        assert said(msgs, "Break something te quita el boost de Turtle power!") and not said(msgs, "si quieres potenciar")
        assert session.pending is None
    finally:
        client.close()
        fake.close()
