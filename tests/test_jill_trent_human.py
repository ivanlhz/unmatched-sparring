"""Jill Trent at the live table (FakeTTS, batch mode), both seats: the gadget choice at the start of the human's turn, Hypnoray Blaster on
the human's attack (the bot's top card revealed in the chat), Utility Belt's three buttons, Insightful Deduction played by the human on
the bot's deck (which card goes to the bottom, the order of the rest, pinned in the session) and played by the bot on the human's deck
(the bot reads the real top three, says how to arrange them and does not touch the deck). The bot's side of the same cards is in
tests/test_jill_trent_effects.py.

Her deck is sheet 176 like Medusa's, the turtles', Strange's and the Marvel decks': every id the table reports is resolved against the
human's deck."""
from __future__ import annotations

import json
import re

import pytest

from sparring.ai_medusa import Act
from sparring.effects.select import counter_value
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said, twin_session
from test_donatello_future_session import DeckTable
from test_e2_human_cards import bot_defends_with, human_scheme, labels, press

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


class JillTable(DeckTable):
    """The deck table that also answers the read of several top cards (`count`)."""

    def do_peek_deck_top(self, s):
        out = super().do_peek_deck_top(s)
        count = re.search(r"math\.min\((\d+), #cards\)", s)
        if count and out.get("found"):
            out["ids"] = self.human_deck[:int(count.group(1))]
        return out


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=JillTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(bot, human, *hand):
    return pytest.mark.parametrize("rig", [(bot, human, hand)], indirect=True)


def choose_gadget(session, table, i=1):
    """The game opens on the human's turn: Jill's gadget choice waits on the panel (1 Hypnoray Blaster, 2 Ultrabiotic Tonic)."""
    assert session._paused() is not None
    click(session, table, Event.CHOICE, {"i": i})
    assert session._paused() is None


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


# ---------------------------------------------------------------- GADGETOLOGY

@with_rig("hellboy", "jill-trent", TRAINING)
def test_the_gadget_is_two_buttons_at_the_start_of_your_turn(rig):
    session, table, game, fake, cfg = rig
    bot_turn(session, table, [])
    req = session._paused()[2].awaiting if session.effect_run is None else session.effect_run.awaiting
    assert req.kind == "effect" and req.extra["tag"] == "gadget" and game.turn == 1
    assert labels(session) == ["Hypnoray Blaster", "Ultrabiotic Tonic"]
    click(session, table, Event.CHOICE, {"i": 2})
    assert counter_value(game, 1, "gadget") == 2
    assert session._paused() is None or session._paused()[2].awaiting is None


# ---------------------------------------------------------------- Hypnoray Blaster on your attack

@with_rig("hellboy", "jill-trent", TRAINING)
def test_your_hypnoray_reveals_the_top_card_of_the_bots_deck_in_the_chat(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    choose_gadget(session, table, 1)
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    pos = jill.pos
    hellboy.pos = next(s for s in sorted(game.board.adj[pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Battle of Wits", "Laser Pen")
    top = game.players[0].deck[0]
    msgs = attack(session, table, game, "jill", "Battle of Wits")
    assert said(msgs, f"Reveladas arriba de mi mazo: {top.title}"), msgs
    assert hellboy.hp == hellboy.max_hp - max(0, 2 + top.boost - 3)


# ---------------------------------------------------------------- Utility Belt

@with_rig("hellboy", "jill-trent", TRAINING)
def test_utility_belt_is_three_buttons(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    choose_gadget(session, table, 1)
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
    game.fx.set_counter(1, "gadget", 0)
    jill.hp = 9
    table.dials[cfg.session_config().dials["jill"]]["value"] = session.dials_written[cfg.session_config().dials["jill"]] = 9
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Utility Belt", "Laser Pen")
    attack(session, table, game, "jill", "Utility Belt")
    assert labels(session) == ["Jill Trent recovers 1 health", "Move Jill Trent 1 space", "Draw 1 card"]
    click(session, table, Event.CHOICE, {"i": 1})
    assert jill.hp == 10


# ---------------------------------------------------------------- Insightful Deduction, you play it

@with_rig("hellboy", "jill-trent", TRAINING)
def test_you_bury_one_card_of_the_bots_deck_and_order_the_rest_and_the_order_is_pinned(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    choose_gadget(session, table, 1)
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
    game.fx.set_counter(1, "gadget", 0)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    human_hand(table, game, "Insightful Deduction", "Laser Pen")
    top3 = list(game.players[0].deck[:3])
    attack(session, table, game, "jill", "Insightful Deduction")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["purpose"] == "bottom" and req.options == [c.card_id for c in top3]
    assert labels(session) == [c.title[:40] for c in top3]
    click(session, table, Event.CHOICE, {"i": 2})                          # the second of the three goes to the bottom
    req = session.effect_run.awaiting
    assert req.kind == "order" and sorted(req.options) == sorted([top3[0].card_id, top3[2].card_id])
    click(session, table, Event.CHOICE, {"i": 2})                          # the order: the third first, then the first
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    deck = game.players[0].deck
    assert [c.card_id for c in deck[:2]] == [top3[2].card_id, top3[0].card_id] and deck[-1] is top3[1], msgs
    assert said(msgs, "va debajo de mi mazo")
    assert session.peek_pins == {"top": [top3[2].card_id, top3[0].card_id], "bottom": [top3[1].card_id]}
    session.read_bot_hand()
    assert [c.card_id for c in game.players[0].deck[:2]] == [top3[2].card_id, top3[0].card_id] and game.players[0].deck[-1] is top3[1]
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    assert twin.peek_pins == session.peek_pins


# ---------------------------------------------------------------- Insightful Deduction, the bot plays it

@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_the_bot_reads_your_top_three_and_tells_you_how_to_arrange_your_deck(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(0, "gadget", 0)
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
    table.human_deck = card_ids(game, 1, "Excalibur", "Regroup" if False else "Right Hand Of Doom", "Service Pistol")
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Insightful Deduction")
    bot_turn(session, table, [Act("attack", fid="jill", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    before = list(table.human_deck)
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Reveladas arriba de tu mazo"), msgs
    assert said(msgs, "debajo de tu mazo") and said(msgs, "Hazlo a mano"), msgs
    assert table.human_deck == before, "the real deck is theirs: the bot never moves it"
    assert not [s for s in table.scripts if s.startswith("-- sparring:deck_top_to_bottom")]
