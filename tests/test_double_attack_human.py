"""DOUBLE ATTACK at the live table (FakeTTS): the second part of a card is a pending combat of its own after the first one.

Stub card: Hellboy's Horseshoes And Hand Grenades (attack 2) with `after: [second_attack 3]`. Both seats attack and both defend:
  * the human attacks: the bot chooses and places its defense for the second part at once, the human reveals;
  * the bot attacks: the human puts a new defense face down (or none) and reveals;
  * a Feint at the first part stops it; Cancel does not take the card's second part back; a save in between keeps it."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.effects.model import load_effects
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand
from test_e2_human_cards import put_adjacent

TITLE = "Horseshoes And Hand Grenades"
SECOND = 3
BOT_HAND = ("Feint", "Snipe", "Regroup", "Dash", "Second Shot")


@pytest.fixture(autouse=True)
def stub_double_attack(monkeypatch):
    monkeypatch.setitem(load_effects("hellboy").card(TITLE).moments, "after", [{"op": "second_attack", "amount": SECOND}])


@pytest.fixture
def human_hellboy(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "medusa", "hellboy", BOT_HAND)
    put_adjacent(game, table, cfg, "hellboy", "medusa")
    yield session, table, game, cfg
    client.close()
    fake.close()


@pytest.fixture
def bot_hellboy(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "medusa", ("Horseshoes And Hand Grenades", "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training"))
    put_adjacent(game, table, cfg, "hellboy", "medusa")
    yield session, table, game, cfg, table
    client.close()
    fake.close()


def _bot_defends(session, game, first=None, second=None):
    """The bot's two defense choices (None: no card) and a record of what it was asked for the second."""
    asked = []
    session.ai.choose_defense = lambda g, a, t, attack_card=None: next((c for c in g.players[0].hand if c.title == first), None)

    def second_defense(g, att, tgt, value, card):
        asked.append((att.fid, tgt.fid, value, card.title))
        return next((c for c in g.players[0].hand if c.title == second), None)
    session.ai.choose_second_defense = second_defense
    return asked


def test_the_human_attacks_and_the_bot_defends_the_second_part_with_a_new_card(human_hellboy):
    session, table, game, cfg = human_hellboy
    medusa = game.fighters["medusa"]
    asked = _bot_defends(session, game, first=None, second="Feint")
    human_hand(table, game, TITLE, "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    hp, actions = medusa.hp, game.actions_left
    click(session, table, Event.REVEAL)
    assert game.actions_left == actions - 1, "the attack action is spent with the first part"
    p = session.pending
    assert p is not None and p.second == {"value": SECOND, "card": card_ids(game, 1, TITLE)[0]} and p.kind == "human_attacks"
    assert medusa.hp == hp - 2, "the first part dealt its 2"
    assert asked == [("hellboy", "medusa", SECOND, TITLE)] and p.bot_card.title == "Feint" and p.bot_card_guid
    msgs = click(session, table, Event.REVEAL)
    assert game.actions_left == actions - 1, "the second part costs no action"
    assert session.pending is None and medusa.hp == hp - 2 - (SECOND - 2), "3 against Feint's 2"
    assert any("3" in m and "Feint" in m for m in msgs), msgs


def test_the_bot_may_defend_the_second_part_with_no_card(human_hellboy):
    session, table, game, cfg = human_hellboy
    medusa = game.fighters["medusa"]
    _bot_defends(session, game, first=None, second=None)
    human_hand(table, game, TITLE, "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    hp = medusa.hp
    click(session, table, Event.REVEAL)
    assert session.pending.bot_card is None
    click(session, table, Event.REVEAL)
    assert session.pending is None and medusa.hp == hp - 2 - SECOND


def test_a_feint_at_the_first_part_leaves_no_second_attack(human_hellboy):
    session, table, game, cfg = human_hellboy
    _bot_defends(session, game, first="Feint", second=None)
    human_hand(table, game, TITLE, "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    click(session, table, Event.REVEAL)
    assert session.pending is None


def test_cancel_does_not_take_the_second_part_back_and_a_save_keeps_it(human_hellboy):
    session, table, game, cfg = human_hellboy
    _bot_defends(session, game, first=None, second="Feint")
    human_hand(table, game, TITLE, "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    click(session, table, Event.REVEAL)
    before = session.pending.second
    click(session, table, Event.CANCEL)
    assert session.pending is not None and session.pending.second == before, "the card was played"
    saved = session.to_dict()
    session.pending = None
    session.load_dict(saved)
    assert session.pending.second == before and session.pending.bot_card.title == "Feint"


def test_the_bot_attacks_and_the_human_defends_the_second_part_with_a_new_card(bot_hellboy):
    session, game, table = bot_hellboy[0], bot_hellboy[2], bot_hellboy[4]
    horseshoes = next(c for c in game.players[0].hand if c.title == TITLE)
    human_hand(table, game, "Feint", "Snipe", "Regroup", "Dash", "Second Shot")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="medusa", card=horseshoes)])
    medusa = game.fighters["medusa"]
    hp = medusa.hp
    click(session, table, Event.REVEAL)                      # no defense for the first part
    p = session.pending
    assert p is not None and p.kind == "bot_attacks" and p.second["value"] == SECOND and medusa.hp == hp - 2
    assert p.bot_card is horseshoes
    feint = card_ids(game, 1, "Feint")[0]
    table.face_down = [{"id": feint, "guid": f"h{feint}"}]
    table.human_hand.remove(feint)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session.pending is None and medusa.hp == hp - 2 - (SECOND - 2)
    assert feint in {c.card_id for c in game.players[1].discard}


def test_the_human_may_defend_the_second_part_with_no_card(bot_hellboy):
    session, game, table = bot_hellboy[0], bot_hellboy[2], bot_hellboy[4]
    horseshoes = next(c for c in game.players[0].hand if c.title == TITLE)
    human_hand(table, game, "Feint", "Snipe", "Regroup", "Dash", "Second Shot")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="medusa", card=horseshoes)])
    hp = game.fighters["medusa"].hp
    click(session, table, Event.REVEAL)
    click(session, table, Event.REVEAL)
    assert session.pending is None and game.fighters["medusa"].hp == hp - 2 - SECOND
