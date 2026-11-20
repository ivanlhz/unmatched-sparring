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


def _first_part(session, table):
    """Reveal of the first part, then the human's AFTER step is over: End action starts the second attack."""
    click(session, table, Event.REVEAL)
    assert session.pending is None and session.second_next is not None and session.moving, "the second part waits for End action"
    return click(session, table, Event.END_ACTION)


def _bot_defends(session, game, first=None, second=None):
    """The bot's two defense choices (None: no card) and a record of what it was asked for the second."""
    asked = []
    session.ai.choose_defense = lambda g, a, t, attack_card=None: next((c for c in g.players[0].hand if c.title == first), None)

    def second_defense(g, att, tgt, value, card):
        asked.append((att.fid, tgt.fid, value, card.title))
        return next((c for c in g.players[0].hand if c.title == second), None)
    session.ai.choose_second_defense = second_defense
    return asked


HUMAN_HAND = (TITLE, "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")


def test_the_human_attacks_and_the_bot_defends_the_second_part_with_a_new_card(human_hellboy):
    session, table, game, cfg = human_hellboy
    medusa = game.fighters["medusa"]
    asked = _bot_defends(session, game, first=None, second="Feint")
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    hp, actions = medusa.hp, game.actions_left
    _first_part(session, table)
    assert game.actions_left == actions - 1, "the attack action is spent with the first part"
    p = session.pending
    assert p is not None and p.second["value"] == SECOND and p.kind == "human_attacks"
    assert p.second["spent"] == card_ids(game, 1, TITLE), "only the human's own first card is excluded, by its own CardID"
    assert medusa.hp == hp - 2, "the first part dealt its 2"
    assert asked == [("hellboy", "medusa", SECOND, TITLE)] and p.bot_card.title == "Feint" and p.bot_card_guid
    msgs = click(session, table, Event.REVEAL)     # the first card still lies face up on the table, as on the real one
    assert game.actions_left == actions - 1, "the second part costs no action"
    assert session.pending is None and medusa.hp == hp - 2 - (SECOND - 2), "3 against Feint's 2"
    assert any("3" in m and "Feint" in m for m in msgs), msgs


def test_the_bot_may_defend_the_second_part_with_no_card(human_hellboy):
    session, table, game, cfg = human_hellboy
    medusa = game.fighters["medusa"]
    _bot_defends(session, game, first=None, second=None)
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    hp = medusa.hp
    _first_part(session, table)
    assert session.pending.bot_card is None
    click(session, table, Event.REVEAL)
    assert session.pending is None and medusa.hp == hp - 2 - SECOND


def test_the_second_attack_waits_for_the_humans_after_step_and_ignores_where_they_stand_then(human_hellboy):
    session, table, game, cfg = human_hellboy
    medusa, hellboy = game.fighters["medusa"], game.fighters["hellboy"]
    asked = _bot_defends(session, game, first=None, second=None)
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    hp = medusa.hp
    click(session, table, Event.REVEAL)
    assert asked == [] and session.pending is None, "no second defense is asked while the first combat's step is open"
    far = max(game.board.spaces, key=lambda sp: game.board.distance(hellboy.pos, sp))
    table.positions[cfg.nicknames["medusa"]] = far         # the human moves the pieces by hand in that step
    click(session, table, Event.END_ACTION)
    assert medusa.pos == far and not game.board.can_reach_target(hellboy.pos, far, hellboy.ranged, hellboy.reach)
    assert asked == [("hellboy", "medusa", SECOND, TITLE)] and session.pending.second is not None
    click(session, table, Event.REVEAL)
    assert session.pending is None and medusa.hp == hp - 2 - SECOND, "out of reach, and it still lands"


def test_a_feint_at_the_first_part_leaves_no_second_attack(human_hellboy):
    session, table, game, cfg = human_hellboy
    _bot_defends(session, game, first="Feint", second=None)
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    click(session, table, Event.REVEAL)
    assert session.pending is None and session.second_next is None


def test_cancel_does_not_take_the_second_part_back_and_a_save_keeps_it(human_hellboy):
    session, table, game, cfg = human_hellboy
    _bot_defends(session, game, first=None, second="Feint")
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "hellboy", "medusa", TITLE)
    click(session, table, Event.REVEAL)
    waiting = session.second_next
    saved = session.to_dict()                                # saved while the first combat's step is open
    session.second_next = None
    session.load_dict(saved)
    assert session.second_next == waiting and session.moving
    click(session, table, Event.END_ACTION)
    before = session.pending.second
    click(session, table, Event.CANCEL)
    assert session.pending is not None and session.pending.second == before, "the card was played"
    saved = session.to_dict()
    session.pending = None
    session.load_dict(saved)
    assert session.pending.second == before and session.pending.bot_card.title == "Feint"


def _bot_attacks(session, table, game, human_cards, defense=None):
    horseshoes = next(c for c in game.players[0].hand if c.title == TITLE)
    human_hand(table, game, *human_cards)
    bot_turn(session, table, [Act("attack", fid="hellboy", target="medusa", card=horseshoes)])
    if defense is not None:
        card_id = card_ids(game, 1, defense)[0]
        table.face_down = [{"id": card_id, "guid": f"h{card_id}"}]
        table.human_hand.remove(card_id)
        table.human_count -= 1
    return horseshoes


def test_the_bot_attacks_and_the_human_defends_the_second_part_with_a_new_card(bot_hellboy):
    session, game, table = bot_hellboy[0], bot_hellboy[2], bot_hellboy[4]
    horseshoes = _bot_attacks(session, table, game, ("Feint", "Snipe", "Regroup", "Dash", "Second Shot"))
    medusa = game.fighters["medusa"]
    hp = medusa.hp
    click(session, table, Event.REVEAL)                      # no defense for the first part
    click(session, table, Event.END_ACTION)
    p = session.pending
    assert p is not None and p.kind == "bot_attacks" and p.second["value"] == SECOND and medusa.hp == hp - 2
    assert p.bot_card is horseshoes and p.second["spent"] == []
    feint = card_ids(game, 1, "Feint")[0]
    table.face_down = [{"id": feint, "guid": f"h{feint}"}]
    table.human_hand.remove(feint)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session.pending is None and medusa.hp == hp - 2 - (SECOND - 2)
    assert feint in {c.card_id for c in game.players[1].discard}


def test_the_first_defense_still_on_the_table_is_not_taken_for_the_second_one(bot_hellboy):
    session, game, table = bot_hellboy[0], bot_hellboy[2], bot_hellboy[4]
    _bot_attacks(session, table, game, ("Dash", "Snipe", "Regroup", "Feint", "Second Shot"), defense="Dash")
    medusa = game.fighters["medusa"]
    click(session, table, Event.REVEAL)
    dash = card_ids(game, 1, "Dash")[0]
    assert any(r["id"] == dash for r in table.face_up), "the real table leaves the played card face up at its spot"
    after_first = medusa.hp
    click(session, table, Event.END_ACTION)
    assert session.pending is not None and session.pending.second["spent"] == [dash]
    click(session, table, Event.REVEAL)                      # nothing new down: no defense for the second part
    assert session.pending is None and medusa.hp == after_first - SECOND, "the full 3, Dash does not defend twice"
    assert sum(1 for c in game.players[1].discard if c.card_id == dash) == 1


def test_the_human_may_defend_the_second_part_with_no_card(bot_hellboy):
    session, game, table = bot_hellboy[0], bot_hellboy[2], bot_hellboy[4]
    _bot_attacks(session, table, game, ("Feint", "Snipe", "Regroup", "Dash", "Second Shot"))
    hp = game.fighters["medusa"].hp
    click(session, table, Event.REVEAL)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.REVEAL)
    assert session.pending is None and game.fighters["medusa"].hp == hp - 2 - SECOND


# ---------------------------------------------------------------- a parked choice of the first combat (Doctor Strange's DARK PACT)

from test_doctor_strange_human import done, rig, with_rig  # noqa: E402,F401  (the fixture and its helpers)


@with_rig(TITLE, "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")
def test_a_parked_after_combat_choice_is_answered_before_the_second_attack_and_never_asked_twice(rig):
    session, table, game, fake, cfg = rig
    horseshoes = next(c for c in game.players[0].hand if c.title == TITLE)
    human_hand(table, game, "Master of Kamar-Taj", "Feint", "Bolts of Balthakk")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="strange", card=horseshoes)])
    seven = card_ids(game, 1, "Master of Kamar-Taj")[0]
    table.face_down = [{"id": seven, "guid": f"h{seven}"}]
    table.human_hand.remove(seven)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session._paused()[2].label == "dark_pact" and session.second_next is not None and session.pending is None
    click(session, table, Event.END_ACTION)                      # the pact is still to be answered: nothing starts
    assert session.pending is None and session.second_next is not None
    done(session, table, 2)                                      # No
    assert session._paused() is None and session.second_next is not None
    click(session, table, Event.END_ACTION)
    assert session.pending is not None and session.pending.second["spent"] == [seven]
    click(session, table, Event.REVEAL)                          # no new defense
    assert session.pending is None and session._paused() is None, "the first card's pact is not offered again"
