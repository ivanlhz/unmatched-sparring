"""Jill Trent at the live table (FakeTTS, batch mode), both seats: the gadget choice at the start of the human's turn, Hypnoray Blaster on
the human's attack (the bot's top card revealed in the chat), Utility Belt's three buttons, Insightful Deduction played by the human on
the bot's deck (which card goes to the bottom, the order of the rest, pinned in the session) and played by the bot on the human's deck
(the bot reads the real top three and reorders them blind: a count in the chat, never a name). The bot's side of the same cards is in
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
    """The deck table that also answers the read of several top cards (`count`), of the human's deck and of the bot's."""

    foreign: frozenset = frozenset()          # CardIDs on the bot's deck that are not its own (a card dropped on it)

    def do_peek_deck_top(self, s):
        if not self._human_side(s):
            return self.read_bot_top(s)
        out = super().do_peek_deck_top(s)
        count = re.search(r"math\.min\((\d+), #cards\)", s)
        if count and out.get("found"):
            out["ids"] = self.human_deck[:int(count.group(1))]
        return out

    def stack(self, *top_first):
        """The human picks the laid cards up and drops them on the bot's deck one by one: a card dropped on a deck ends on top, so the
        last one dropped (the first of `top_first`) is the top card."""
        for i in reversed(top_first):
            self.row.remove(i)
            self.bot_deck.insert(0, i)

    def read_bot_top(self, s):
        """The bot's physical deck (top first): the read stops at the first card that is not the bot's own."""
        count = int(re.search(r"math\.min\((\d+), #cards\)", s).group(1))
        ids = []
        for i in self.bot_deck[:count]:
            if i in self.foreign:
                break
            ids.append(i)
        return {"found": bool(ids), "id": ids[0] if ids else None, "ids": ids, "quantity": len(self.bot_deck)}


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
    assert sorted(table.row) == sorted(req.options) and labels(session) == ["Hecho"], "the two cards lie on the table: only Done"
    table.stack(top3[2].card_id, top3[0].card_id)                          # the order: the third first, then the first
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
def test_the_bot_reads_your_top_three_and_reorders_your_real_deck_blind(rig):
    """Ivan, 2026-11-08: the bot moves the cards itself. The reveal is the card's own (public) and is told; what the bot did with
    the cards is not: the reorder line has a count and no title, and the real deck ends in the order the bot keeps in its head."""
    session, table, game, fake, cfg = rig
    game.fx.set_counter(0, "gadget", 0)
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
    table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]       # none of them in the engine's virtual hand; a fourth stays below
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Insightful Deduction")
    bot_turn(session, table, [Act("attack", fid="jill", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    before = list(table.human_deck)
    msgs = click(session, table, Event.REVEAL)
    line = next((m for m in msgs if "reordenado" in m), "")
    assert "he reordenado las 3 cartas superiores de tu mazo y he mandado 1 al fondo" in line, msgs
    titles = [c.title for c in game.players[1].full_set if c.card_id in before]
    assert not [t for t in titles if t in line] and not said(msgs, "Hazlo a mano") and not said(msgs, "debajo de tu mazo"), msgs
    assert len(table.reorders) == 1 and table.reorders[0][0] == before[:3] and len(table.reorders[0][2]) == 1
    top = game.players[0].known.top_of_deck
    assert len(top) == 2 and table.human_deck[:2] == top, "the two on top are the ones the bot keeps in mind, in its order"
    assert table.human_deck[-1] == table.reorders[0][2][0] and table.human_deck[2] == before[3], "the buried one is at the bottom"
    assert sorted(table.human_deck) == sorted(before), "same cards, same count"
    assert not [s for s in table.scripts if s.startswith("-- sparring:deck_top_to_bottom")]
    game.draw(1, 1)
    assert game.players[0].known.top_of_deck == []


@pytest.mark.parametrize("events", [
    [Event.END_ACTION, Event.END_ACTION, Event.END_ACTION],
    [Event.MANEUVER, Event.END_ACTION, Event.MANEUVER, Event.END_ACTION],
])
@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_later_buttons_never_name_the_order_or_the_buried_card(rig, events):
    """Regression (review of b0040f5): after the blind reorder the next button named the cards left on top. The reveal itself is
    public and may be named in its own step; afterwards the bot's order and the buried card never are."""
    session, table, game, fake, cfg = rig
    game.fx.set_counter(0, "gadget", 0)
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
    table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Insightful Deduction")
    bot_turn(session, table, [Act("attack", fid="jill", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    titles = [c.title for c in game.players[1].full_set if c.card_id in table.human_deck[:3]]
    click(session, table, Event.REVEAL)
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    later = [str(m) for ev in events for m in click(session, table, ev)]
    assert not [(t, m) for m in later for t in titles if t in m]


@pytest.mark.parametrize("gadget", [1, 2])
@with_rig("jill-trent", "hellboy", "Battle of Wits", "Laser Pen", "Energizing Spray")
def test_the_bots_reveal_of_your_top_card_is_not_read_as_a_card_going_from_your_hand_to_your_deck(rig, gadget):
    """Regression (review of bdce8bc): in the same step the chat said "Pon X de tu mano en tu mazo y baraja" for the revealed top card."""
    session, table, game, fake, cfg = rig
    game.fx.set_counter(0, "gadget", gadget)
    adjacent_free(game, table, cfg)
    table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Battle of Wits")
    bot_turn(session, table, [Act("attack", fid="jill", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    top_title = next(c.title for c in game.players[1].full_set if c.card_id == table.human_deck[0])
    msgs = [str(m) for m in click(session, table, Event.REVEAL)]
    assert any("Reveladas arriba de tu mazo" in m and top_title in m for m in msgs), "the reveal itself is public and named"
    assert not [m for m in msgs if "mano" in m and "mazo" in m and top_title in m and "Pon " in m], msgs
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    later = [str(m) for ev in (Event.END_ACTION, Event.END_ACTION) for m in click(session, table, ev)]
    assert not [m for m in later if top_title in m]


def adjacent_free(game, table, cfg):
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos
