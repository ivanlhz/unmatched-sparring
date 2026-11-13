"""Chupacabra on the table through the panel (FakeTTS, batch mode), both seats: the human's cards (The More They Struggle against the bot's
card, Ambush taking a random card of the bot's hand, Feeding and Ravenous Lunge healing on the dial, Tooth and Tail hurting the bot's
fighters, Traveler of the Night and the move the human makes by hand, Unsettle's choice of paying two damage), THE HUNGER asked after each
attack, and the bot's Chupacabra against a human: Ambush (the human discards the position the bot names and says its BOOST value),
Unsettle (the human chooses what to discard), Tooth and Tail and the bot's own draws. The bot's side of the same cards is in
tests/test_chupacabra_effects.py.

His deck is sheet 176 like the other nineteen: every id the table reports is resolved against the owner's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable
from test_donatello_session import SPOTS
from test_e2_human_cards import by_hand, human_scheme, press, put_adjacent

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=StrangeTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand, bot="hellboy", human="chupacabra"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def no_defense(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)


def attack(session, table, game, title, attacker="chupacabra", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def dial(cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def decline_the_hunger(session, table):
    """THE HUNGER asks after every attack of his: Yes / No (the panel's `optional`)."""
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "optional"
    press(session, table, False)


# ---------------------------------------------------------------- the human plays his cards

@with_rig(TRAINING)
def test_the_more_they_struggle_is_twice_the_printed_value_of_the_bots_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: next(c for c in g.players[0].hand if c.title == TRAINING))
    human_hand(table, game, "The More They Struggle", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "The More They Struggle")
    assert game.fighters["hellboy"].hp == hp - (6 - 3), msgs


@with_rig("Excalibur", "Service Pistol")
def test_ambush_makes_the_bot_discard_a_random_card_and_adds_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Ambush", "Feint")
    before, hp = len(game.players[0].hand), game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Ambush")
    gone = game.players[0].discard[-1]
    assert len(game.players[0].hand) == before - 1 and gone.card_id in table.bot_discard, msgs
    assert game.fighters["hellboy"].hp == hp - (2 + gone.boost), msgs


@with_rig()
def test_feeding_at_seven_health_heals_the_dial_and_gives_the_action_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    game.fighters["chupacabra"].hp = 7
    human_hand(table, game, "Feeding", "Feint")
    attack(session, table, game, "Feeding")
    decline_the_hunger(session, table)
    assert game.fighters["chupacabra"].hp == 8 and game.actions_left == 2


@with_rig()
def test_ravenous_lunge_won_recovers_two_on_the_dial(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    game.fighters["chupacabra"].hp = 6
    human_hand(table, game, "Ravenous Lunge", "Feint")
    attack(session, table, game, "Ravenous Lunge")
    decline_the_hunger(session, table)
    assert game.fighters["chupacabra"].hp == 8
    assert cfg.session_config().dials["chupacabra"] in {g for g, _ in table.dial_writes}


@with_rig()
def test_tooth_and_tail_hurts_two_adjacent_bot_fighters_and_heals_the_human(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    put_adjacent(game, table, cfg, "lobster", "chupacabra")
    game.fighters["chupacabra"].hp = 5
    human_hand(table, game, "Tooth and Tail", "Feint")
    hp = (game.fighters["hellboy"].hp, game.fighters["lobster"].hp)
    attack(session, table, game, "Tooth and Tail")
    decline_the_hunger(session, table)
    assert (game.fighters["hellboy"].hp, game.fighters["lobster"].hp) == (hp[0] - 2 - 1, hp[1] - 1) and game.fighters["chupacabra"].hp == 7


@with_rig()
def test_traveler_of_the_night_leaves_the_move_to_the_human_and_gives_the_action_back(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Traveler of the Night", "Feint")
    msgs = human_scheme(session, table, game, "Traveler of the Night")
    assert said(msgs, "hasta 4 casillas"), msgs
    assert game.actions_left == 2


BOT_CARDS = ("Excalibur", "Service Pistol", "Right Hand Of Doom")


@with_rig(*BOT_CARDS)
def test_unsettle_paid_with_two_damage_makes_the_bot_discard_two_cards(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Unsettle", "Feint")
    before = len(game.players[0].hand)
    human_scheme(session, table, game, "Unsettle")
    assert session.effect_run.awaiting.kind == "optional"
    press(session, table, True)
    assert game.fighters["chupacabra"].hp == 12 and len(game.players[0].hand) == before - 2
    assert len(table.bot_discard) == 2


@with_rig(*BOT_CARDS)
def test_unsettle_declined_makes_the_bot_discard_one_card(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Unsettle", "Feint")
    before = len(game.players[0].hand)
    human_scheme(session, table, game, "Unsettle")
    press(session, table, False)
    assert game.fighters["chupacabra"].hp == 14 and len(game.players[0].hand) == before - 1 and len(table.bot_discard) == 1


@with_rig()
def test_the_hunger_asks_after_the_attack_and_the_bot_deals_the_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Feeding")
    attack(session, table, game, "Feint")
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "optional"
    press(session, table, True)
    assert table.human_deals == [1]


@with_rig()
def test_declining_the_hunger_deals_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Feeding")
    attack(session, table, game, "Feint")
    decline_the_hunger(session, table)
    assert table.human_deals == []


# ---------------------------------------------------------------- the bot plays Chupacabra against the human

def bot_attacks(session, table, game, title, *human_cards):
    human_hand(table, game, *human_cards)
    card = next(c for c in game.players[0].hand if c.title == title)
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    first = bot_turn(session, table, [Act("attack", fid="chupacabra", target="hellboy", card=card)])
    return [*first, *click(session, table, Event.REVEAL)]


@with_rig("Ambush", "Feint", bot="chupacabra", human="hellboy")
def test_the_bots_ambush_names_a_position_and_the_human_says_the_boost_of_the_card(rig):
    session, table, game, fake, cfg = rig
    msgs = bot_attacks(session, table, game, "Ambush", TRAINING, "Excalibur", "Service Pistol")
    assert said(msgs, "al azar: la carta"), msgs
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra.get("ambush_boost") and set(req.options) == {1, 2, 3, 4}
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": req.options.index(3) + 1})
    assert session.pending is None
    assert game.fighters["hellboy"].hp == hp - (2 + 3)


@with_rig("Unsettle", "Feint", bot="chupacabra", human="hellboy")
def test_the_bots_unsettle_makes_the_human_discard_by_hand_one_card_or_two_as_the_bot_pays(rig):
    session, table, game, fake, cfg = rig
    unsettle = next(c for c in game.players[0].hand if c.title == "Unsettle")
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
    msgs = bot_turn(session, table, [Act("scheme", fid="chupacabra", card=unsettle)])
    paid = game.fighters["chupacabra"].hp == 12
    assert said(msgs, "Descarta 2 carta(s)" if paid else "Descarta 1 carta(s)"), msgs
    assert game.fighters["chupacabra"].hp in (12, 14)


@with_rig("Tooth and Tail", "Feint", bot="chupacabra", human="hellboy")
def test_the_bots_tooth_and_tail_hurts_the_humans_fighters_and_the_dials_follow(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "lobster", "chupacabra")
    game.fighters["chupacabra"].hp = 5
    hp = game.fighters["lobster"].hp
    bot_attacks(session, table, game, "Tooth and Tail", TRAINING, "Excalibur")
    assert game.fighters["lobster"].hp == hp - 1 and game.fighters["chupacabra"].hp >= 5
    assert cfg.session_config().dials["lobster"] in {g for g, _ in table.dial_writes}
