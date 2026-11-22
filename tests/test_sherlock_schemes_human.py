"""Sherlock Holmes' other cards on the table through the panel (FakeTTS, batch mode), both seats: Master of Disguise (the swap of the two heroes), Administer Aid
(Watson placed beside Holmes), Eliminate the Impossible and Study Methods (the looks at a hand), The Game is Afoot (the move after the attack) and Deduce
Strategy (the yes/no that says what the change does). The panel and the table are the engine's own routes (translators, looks, moves by hand): these tests pin
that Holmes' cards use them the way the human needs."""
from __future__ import annotations

import json

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, human_attack, human_hand, said, twin_session
from test_e2_human_cards import by_hand, human_scheme, labels, press, put_adjacent
from test_e3_hidden_info import human_reads, rig_for
from test_sherlock_human import HOLMES, HOLMES_BOT_HAND, HOLMES_HUMAN_HAND, with_rig

BOT_HAND = ("Excalibur", "Service Pistol", "Right Hand Of Doom", "B.P.R.D. Training", "Second Shot")


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand)
    game.fx.dsl_heroes |= {HOLMES}
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def far_from(game, fid):
    return max(sorted(game.board.spaces), key=lambda s: game.board.distance(game.fighters[fid].pos, s))


# ---------------------------------------------------------------- Master of Disguise

@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_humans_master_of_disguise_swaps_the_heroes_at_any_distance_and_the_bot_moves_its_own_miniature(rig):
    session, table, game, fake, cfg = rig
    holmes, hell = game.fighters["holmes"], game.fighters["hellboy"]
    hell.pos = far_from(game, "holmes")
    table.positions[cfg.nicknames["hellboy"]] = hell.pos
    before = (holmes.pos, hell.pos)
    hp = hell.hp
    human_hand(table, game, *HOLMES_HUMAN_HAND)
    human_scheme(session, table, game, "Master of Disguise")
    assert (holmes.pos, hell.pos) == (before[1], before[0]) and hell.hp == hp - 1
    assert table.positions[cfg.nicknames["hellboy"]] == before[0], "the bot moved its own miniature"
    assert dial_value(session, cfg, table, "hellboy") == hp - 1


def dial_value(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_bots_master_of_disguise_tells_the_human_to_put_their_hero_where_holmes_was(rig):
    session, table, game, fake, cfg = rig
    holmes, hell = game.fighters["holmes"], game.fighters["hellboy"]
    master = next(c for c in game.players[0].hand if c.title == "Master of Disguise")
    human_hand(table, game, "Excalibur", "Service Pistol", "Glimpse Of Hell")
    before = (holmes.pos, hell.pos)
    msgs = bot_turn(session, table, [Act("scheme", fid="holmes", card=master)])
    assert (holmes.pos, hell.pos) == (before[1], before[0]), msgs
    assert said(msgs, "he intercambiado yo las miniaturas") or said(msgs, "Master of Disguise"), msgs


# ---------------------------------------------------------------- Administer Aid

@with_rig("hellboy", HOLMES, BOT_HAND)
def test_administer_aid_has_the_human_place_watson_beside_holmes_and_deals_the_card(rig):
    session, table, game, fake, cfg = rig
    holmes, watson = game.fighters["holmes"], game.fighters["watson"]
    holmes.hp = 10
    human_hand(table, game, "Administer Aid", "Counterpunch", "Feint")
    start = far_from(game, "holmes")
    watson.pos = start
    table.positions[cfg.nicknames["watson"]] = start
    msgs = human_scheme(session, table, game, "Administer Aid")
    assert holmes.hp == 11 and said(msgs, "coloca a watson en una casilla adyacente") and said(msgs, "Te he dado 1 carta"), msgs
    spot = next(s for s in sorted(game.board.adj[holmes.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["watson"]] = spot                          # the human puts the miniature there by hand
    click(session, table, Event.END_ACTION)
    assert game.fighters["watson"].pos == spot and spot in game.board.adj[holmes.pos]
    assert dial_value(session, cfg, table, "holmes") == 11


# ---------------------------------------------------------------- Eliminate the Impossible, Study Methods

@with_rig("hellboy", HOLMES, BOT_HAND)
def test_eliminate_the_impossible_has_the_human_look_at_the_bots_hand_on_the_table_and_lay_the_discard(rig):
    """The look-and-discard card of every hero (Ivan, 30/10): the human takes the cards out of the bot's green hand zone, lays the chosen one on the bot's discard pile
    and presses Done; the bot validates the table."""
    from sparring import session_hidden as hidden
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Eliminate the Impossible", "Counterpunch", "Feint")
    msgs = human_scheme(session, table, game, "Eliminate the Impossible")
    assert hidden.manual_request(session) is not None and said(msgs, "Eliminate the Impossible: miras la mano del bot") and said(msgs, "pulsa Hecho"), msgs
    assert not said(msgs, "Has perdido el combate"), msgs
    assert session.panel_labels() == {"btn_choice_1": "Hecho"}
    chosen = table.bot_hand[0]
    table.bot_hand.remove(chosen)
    table.bot_discard.append(chosen)
    click(session, table, Event.CHOICE, {"i": 1})
    assert chosen in [c.card_id for c in game.players[0].discard] and session.effect_run is None and session._paused() is None
    assert human_reads(table) == []


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_bots_eliminate_the_impossible_reads_the_humans_hand_once_and_the_human_lays_the_named_card(rig):
    session, table, game, fake, cfg = rig
    eliminate_in_hand = next((c for c in game.players[0].hand if c.title == "Eliminate the Impossible"), None)
    if eliminate_in_hand is None:                                        # the rig's hand has no copy: swap one in (the deck holds two)
        spare = next(c for c in game.players[0].deck if c.title == "Eliminate the Impossible")
        game.players[0].deck.remove(spare)
        game.players[0].hand.append(spare)
        table.bot_hand = [*table.bot_hand, spare.card_id]
        eliminate_in_hand = spare
    human_hand(table, game, "Excalibur", "Service Pistol", "Glimpse Of Hell")
    msgs = bot_turn(session, table, [Act("scheme", fid="holmes", card=eliminate_in_hand)])
    assert len(human_reads(table)) == 1, msgs
    named = session.pending_discard["cards"]
    assert len(named) == 1 and said(msgs, "Pon Excalibur de tu mano en tu descarte"), msgs
    table.human_hand.remove(named[0])
    table.human_discard.append(named[0])
    table.human_count -= 1
    click(session, table, Event.END_ACTION)
    assert named[0] in [c.card_id for c in game.players[1].discard] and session.pending_discard is None


# ---------------------------------------------------------------- the AFTER COMBAT cards of the human's Holmes

def human_attacks_with(session, table, game, title):
    click(session, table, Event.ATTACKER, {"attacker": "att_holmes"})
    click(session, table, Event.ATTACK, {"target": "hellboy"})
    from test_d3_table_effects import human_plays
    played = human_plays(table, game, title)
    table.human_hand.remove(played.card_id)
    table.human_count -= 1


@with_rig("hellboy", HOLMES, BOT_HAND)
def test_education_never_ends_lost_deals_the_human_two_cards(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: training)      # 3 against 3: the defender keeps the tie
    human_hand(table, game, "Education Never Ends", "Counterpunch", "Feint")
    human_attacks_with(session, table, game, "Education Never Ends")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Te he dado 2 cartas"), msgs


@with_rig("hellboy", HOLMES, BOT_HAND)
def test_study_methods_won_shows_the_bots_hand_in_a_row(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    human_hand(table, game, "Study Methods", "Counterpunch", "Feint")
    human_attacks_with(session, table, game, "Study Methods")
    click(session, table, Event.REVEAL)
    assert session.look is not None and session.look["mode"] == "reveal"
    assert human_reads(table) == []


@with_rig("hellboy", HOLMES, BOT_HAND)
def test_study_methods_lost_shows_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "holmes", "hellboy")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: training)
    human_hand(table, game, "Study Methods", "Counterpunch", "Feint")
    human_attacks_with(session, table, game, "Study Methods")
    click(session, table, Event.REVEAL)
    assert session.look is None

