"""Confirm Suspicion on the table through the panel (FakeTTS, batch mode), both seats.

The bot's Holmes names a value and asks the human for a matching card: they lay it on their discard pile (the bot reads it and its BOOST hurts their hero), a
card of another value or a scheme is refused, saying "none" has the hand read once and a match found there is demanded, and the question survives a save. The
human's Holmes names the value on the panel: the bot discards a matching card or shows its hand in a row."""
from __future__ import annotations

import json

import pytest

from sparring import ai_sherlock
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import human_hand, said, twin_session
from test_e2_human_cards import human_scheme
from test_e3_hidden_info import human_reads, rig_for
from test_sherlock_human import BOT_HAND, HOLMES, HOLMES_BOT_HAND, HOLMES_HUMAN_HAND, dial, with_rig  # noqa: F401  (with_rig's fixture)

HELLBOY_HUMAN_HAND = ("B.P.R.D. Training", "Excalibur", "Service Pistol", "Glimpse Of Hell", "Right Hand Of Doom")


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand)
    game.fx.dsl_heroes |= {HOLMES}
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def bot_plays_confirm(session, table, game, monkeypatch, named, *human_cards):
    monkeypatch.setattr(ai_sherlock, "name_value", lambda g, me: named)
    human_hand(table, game, *human_cards)
    confirm = next(c for c in game.players[0].hand if c.title == "Confirm Suspicion")
    plan = [Act("scheme", fid="holmes", card=confirm)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


def awaiting(session):
    return session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting


def lay_on_pile(table, game, title):
    by_id = {c.card_id: c for c in game.players[1].full_set}
    i = next(i for i in table.human_hand if by_id[i].title == title)
    table.human_hand.remove(i)
    table.human_discard.append(i)
    table.human_count -= 1
    return i


# ---------------------------------------------------------------- the bot's Holmes against the human

@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_bots_confirm_suspicion_names_the_value_and_asks_the_human_for_a_matching_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = bot_plays_confirm(session, table, game, monkeypatch, 3, *HELLBOY_HUMAN_HAND)
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["pile_mode"] == "reveal" and req.extra["confirm"] == 3 and (req.min, req.max) == (0, 1)
    assert said(msgs, "Confirm Suspicion: pon en tu descarte una carta de tu mano con valor impreso 3"), msgs
    assert human_reads(table) == [], "the hand is not read while the human can answer"


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_a_matching_card_on_the_pile_is_read_and_its_boost_hurts_the_humans_hero(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 3, *HELLBOY_HUMAN_HAND)
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "B.P.R.D. Training")                                   # versatile 3, BOOST 2
    msgs = click(session, table, Event.CHOICE, {"i": 1})                            # Done
    assert game.fighters["hellboy"].hp == hp - 2 and session.effect_run is None and session._paused() is None
    assert said(msgs, "descartas B.P.R.D. Training: tu heroe recibe 2 de dano"), msgs
    assert human_reads(table) == []
    assert dial(session, cfg, table, "hellboy") == hp - 2
    assert session.pending_discard is None and not said(msgs, "de tu mano en tu descarte"), msgs      # the card they laid is not asked for again
    msgs = click(session, table, Event.MANEUVER)
    assert not said(msgs, "Ahora no es posible"), msgs                                            # their first action goes through


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_a_card_of_another_value_is_refused_and_the_question_stays(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 3, *HELLBOY_HUMAN_HAND)
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "Excalibur")                                           # printed 6
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "Excalibur (6) no es una carta de valor impreso 3"), msgs
    assert game.fighters["hellboy"].hp == hp and awaiting(session).extra["confirm"] == 3


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_a_scheme_never_matches(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 0, "And Upon His Brow Is Set A Crown Of Flame", "Excalibur")
    lay_on_pile(table, game, "And Upon His Brow Is Set A Crown Of Flame")           # a scheme has no value: it matches nothing, not even 0
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "no es una carta de valor impreso 0"), msgs


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_saying_none_has_the_hand_read_once_and_a_hand_without_a_match_ends_the_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 1, "Excalibur", "Service Pistol", "Glimpse Of Hell", "Right Hand Of Doom")
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.CHOICE, {"i": 1})                            # Done with nothing laid
    assert said(msgs, "ninguna carta de valor 1"), msgs
    assert len(human_reads(table)) == 1 and session.effect_run is None and game.fighters["hellboy"].hp == hp
    assert {c.title for c in game.players[0].known.cards(game.players[1])} >= {"Service Pistol"}


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_saying_none_while_holding_a_match_is_found_when_the_hand_is_read_and_the_card_is_demanded(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 3, *HELLBOY_HUMAN_HAND)
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": 1})                                   # "none", although B.P.R.D. Training is a 3
    req = awaiting(session)
    by_id = {c.card_id: c.title for c in game.players[1].full_set}
    assert len(human_reads(table)) == 1 and req.extra["recheck"] and [by_id[i] for i in req.options] == ["B.P.R.D. Training"]
    lay_on_pile(table, game, "B.P.R.D. Training")
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp - 2
    assert session.pending_discard is None and not said(msgs, "de tu mano en tu descarte"), msgs
    assert not said(click(session, table, Event.MANEUVER), "Ahora no es posible")


@with_rig(HOLMES, "hellboy", HOLMES_BOT_HAND)
def test_the_question_of_the_bots_confirm_suspicion_survives_a_save_and_is_answered_after_the_resume(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays_confirm(session, table, game, monkeypatch, 3, *HELLBOY_HUMAN_HAND)
    req = awaiting(session)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    again = awaiting(twin)
    assert again.kind == "cards" and again.extra["confirm"] == 3 and again.options == req.options
    twin.client = session.client
    lay_on_pile(table, twin.game, "B.P.R.D. Training")
    msgs = click(twin, table, Event.CHOICE, {"i": 1})                               # the twin's own AI goes on with the bot's turn after the card
    assert said(msgs, "descartas B.P.R.D. Training: tu heroe recibe 2 de dano"), msgs
    assert [c.title for c in twin.game.players[1].discard] == ["B.P.R.D. Training"] and twin._paused() is None


# ---------------------------------------------------------------- the human's Holmes against the bot

def human_plays_confirm(session, table, game):
    human_hand(table, game, *HOLMES_HUMAN_HAND)
    return human_scheme(session, table, game, "Confirm Suspicion")


@pytest.mark.parametrize("named, boost", [(3, 2), (6, 3)])
@with_rig("hellboy", HOLMES, BOT_HAND)
def test_the_human_names_the_value_and_the_bot_discards_a_matching_card_whose_boost_hurts_its_hero(rig, named, boost):
    session, table, game, fake, cfg = rig
    msgs = human_plays_confirm(session, table, game)
    req = awaiting(session)
    assert req.kind == "amount" and list(req.options) == list(range(8)) and req.extra["name_value"] is True
    assert said(msgs, "Nombra un valor"), msgs
    bot_hand = list(game.players[0].hand)
    hp = game.fighters["hellboy"].hp
    if named >= 5:
        click(session, table, Event.CHOICE, {"i": 6})                               # page 2: 5, 6, 7
        click(session, table, Event.CHOICE, {"i": named - 5 + 1})
    else:
        click(session, table, Event.CHOICE, {"i": named + 1})
    gone = [c for c in bot_hand if c not in game.players[0].hand]
    assert len(gone) == 1 and (gone[0].value or 0) == named
    assert game.fighters["hellboy"].hp == hp - gone[0].boost and gone[0].boost == boost


@with_rig("hellboy", HOLMES, BOT_HAND)
def test_a_value_the_bot_does_not_hold_shows_its_hand_in_a_row_for_the_human(rig):
    session, table, game, fake, cfg = rig
    human_plays_confirm(session, table, game)
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": 1})                                   # value 0: no card of the bot's hand is a 0
    assert game.fighters["hellboy"].hp == hp
    assert session.look is not None and session.look["mode"] == "reveal"
