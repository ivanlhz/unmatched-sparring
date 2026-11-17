"""Live bug (17/11, Liz bot vs human Sinbad): Fleeting Moments makes the human discard at random while their Toil and Danger lets
Sinbad walk 3 spaces. One End action settled the discard and also closed the walk, and the bot went on with its second action.
The walk now gets its own step when the discard is settled by a press that finds the miniature where it was."""
from __future__ import annotations

import json

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said, twin_session
from test_d3_table_effects import rig as d3_rig  # noqa: F401
from test_e2_human_cards import put_adjacent, rig, with_rig  # noqa: F401

LIZ_VS_SINBAD = ("liz-sherman", "sinbad", "Fleeting Moments", "Evade", "Fireball", "Pyrotechnics", "Rekindle")
ASK = "Descarte hecho. Ahora mueve a Sinbad hasta 3 casillas y pulsa Fin de accion"


def fleeting_into_toil(session, table, game, cfg):
    """Bot Liz attacks Sinbad with Fleeting Moments; the human defends with Toil and Danger and holds three more cards."""
    put_adjacent(game, table, cfg, "liz", "sinbad")
    human_hand(table, game, "Toil and Danger", "Exploit", "Feint", "Regroup")
    fleeting = next(c for c in game.players[0].hand if c.title == "Fleeting Moments")
    other = next(c for c in game.players[0].hand if c is not fleeting)
    bot_turn(session, table, [Act("attack", fid="liz", target="sinbad", card=fleeting),
                              Act("attack", fid="liz", target="sinbad", card=other)])
    toil = card_ids(game, 1, "Toil and Danger")[0]
    table.face_down = [{"id": toil, "guid": f"h{toil}"}]
    table.human_hand.remove(toil)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


def discard_on_table(table):
    table.human_discard.append(table.human_hand.pop(0))
    table.human_count -= 1


def free_space_at_3(game):
    start = game.fighters["sinbad"].pos
    taken = {f.pos for f in game.fighters.values() if f.alive}
    return next(s for s in sorted(game.board.spaces) if game.board.distance(start, s) == 3 and s not in taken)


@with_rig(*LIZ_VS_SINBAD)
def test_discard_alone_then_the_walk_gets_its_own_step(rig):
    session, table, game, fake, cfg = rig
    msgs = fleeting_into_toil(session, table, game, cfg)
    assert session.pending_discard is not None and "sinbad" in game.hand_moves, msgs
    start = game.fighters["sinbad"].pos
    discard_on_table(table)
    msgs = click(session, table, Event.END_ACTION)               # only the discard is done
    assert said(msgs, ASK), msgs
    assert not said(msgs, "El bot ataca") and "sinbad" in game.hand_moves and game.turn == 0 and session.moving
    assert said(msgs, "Te he dado 1 carta")                       # the draw is not held back by the walk
    dest = free_space_at_3(game)
    table.positions[cfg.nicknames["sinbad"]] = dest
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["sinbad"].pos == dest != start and "sinbad" not in game.hand_moves
    assert not said(msgs, "Descarte hecho")


@with_rig(*LIZ_VS_SINBAD)
def test_discard_and_walk_before_one_press_ask_nothing_more(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    discard_on_table(table)
    dest = free_space_at_3(game)
    table.positions[cfg.nicknames["sinbad"]] = dest
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["sinbad"].pos == dest and not said(msgs, "Descarte hecho"), msgs
    assert game.hand_moves == {} and session.pending_discard is None


@with_rig(*LIZ_VS_SINBAD)
def test_walk_first_then_the_discard_later(rig):
    """The walk done and the discard missing: the press waits for the discard and the walk is not lost."""
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    dest = free_space_at_3(game)
    table.positions[cfg.nicknames["sinbad"]] = dest
    click(session, table, Event.END_ACTION)                      # nothing discarded yet
    assert session.pending_discard is not None and game.fighters["sinbad"].pos == dest
    discard_on_table(table)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["sinbad"].pos == dest and session.pending_discard is None and not said(msgs, "Descarte hecho")


@with_rig(*LIZ_VS_SINBAD)
def test_a_press_that_does_not_settle_the_discard_keeps_the_walk_open(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    click(session, table, Event.END_ACTION)
    assert session.pending_discard is not None and "sinbad" in game.hand_moves


@with_rig(*LIZ_VS_SINBAD)
def test_staying_put_is_legal_with_a_second_press(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    start = game.fighters["sinbad"].pos
    discard_on_table(table)
    click(session, table, Event.END_ACTION)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["sinbad"].pos == start and game.hand_moves == {}
    assert not said(msgs, "Descarte hecho")


@with_rig(*LIZ_VS_SINBAD)
def test_after_the_second_press_the_bot_does_one_action(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    discard_on_table(table)
    click(session, table, Event.END_ACTION)
    calls, plan = [], session.ai.plan
    session.ai.plan = lambda g: (calls.append(1), plan(g))[1]
    msgs = click(session, table, Event.END_ACTION)
    assert len(calls) == 1 and said(msgs, "El bot ataca con liz a sinbad"), msgs
    assert session.pending is not None


@with_rig(*LIZ_VS_SINBAD)
def test_a_resume_after_the_discard_keeps_waiting_for_the_walk(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    discard_on_table(table)
    click(session, table, Event.END_ACTION)
    assert session.moving
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    assert twin.moving and "sinbad" in twin.game.hand_moves
    msgs = twin.resume()
    assert said(msgs, "Hay una accion abierta"), msgs
    dest = free_space_at_3(twin.game)
    table.positions[cfg.nicknames["sinbad"]] = dest
    click(twin, table, Event.END_ACTION)
    assert twin.game.fighters["sinbad"].pos == dest and twin.game.hand_moves == {}


@with_rig(*LIZ_VS_SINBAD)
def test_a_dead_fighter_is_not_asked_to_move(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_toil(session, table, game, cfg)
    game.fighters["sinbad"].alive = False
    discard_on_table(table)
    msgs = click(session, table, Event.END_ACTION)
    assert not said(msgs, "Descarte hecho"), msgs


def test_the_text_fits_exactly_and_several_miniatures(tmp_path):
    from sparring import i18n
    from test_sinbad_human import human_rig
    session, table, game, fake, cfg, client = human_rig(tmp_path)
    try:
        game.hand_moves.update({"sinbad": {"steps": 3, "up_to": False, "through": False}})
        assert "sin tocar" not in session._walk_after_discard_text({"sinbad"})
        assert "sinbad exactamente 3 casillas" in session._walk_after_discard_text({"sinbad"}).lower()
        game.hand_moves.update({"sinbad": {"steps": 3, "up_to": True, "through": False}, "hellboy": {"steps": 2, "up_to": True, "through": False}})
        text = session._walk_after_discard_text({"sinbad", "hellboy"})
        assert "moverlas" in text and "sin tocarlas" in text, text
        i18n.set_language("en")
        assert "leave them where they are" in session._walk_after_discard_text({"sinbad", "hellboy"})
    finally:
        i18n.set_language("es")
        client.close()
        fake.close()


@pytest.mark.parametrize("d3_rig", [("hellboy", "abe-sapien", ("Confront Any Demon or God", "Right Hand Of Doom", "Service Pistol",
                                                              "Excalibur", "B.P.R.D. Training"))], indirect=True)
def test_abe_hits_with_faster_stronger_and_confront_leaves_a_named_discard(d3_rig, monkeypatch):
    """The inverse order, as it happens in play: the human attacker's own move ("IMMEDIATELY: Move Abe up to 2") and the discard
    the bot's Confront Any Demon or God names. The press that settles the discard does not close the move."""
    session, table, game, fake, cfg = d3_rig
    confront = next(c for c in game.players[0].hand if c.title == "Confront Any Demon or God")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: confront)
    human_hand(table, game, "Faster. Stronger.", "Leap Away", "Concussion Device", "Secure The Scene", "Advanced Psychometry")
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.", value=5)
    real = list(table.human_hand)
    click(session, table, Event.REVEAL)
    gone = session.pending_discard["cards"][0]
    assert "abe" in game.hand_moves
    start = game.fighters["abe"].pos
    table.human_discard += [card_ids(game, 1, "Faster. Stronger.")[0], gone]
    table.human_count = len(real) - 1
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Descarte hecho. Ahora mueve a Abe Sapien hasta 2 casillas") and "abe" in game.hand_moves
    taken = {f.pos for f in game.fighters.values() if f.alive}
    dest = next(s for s in sorted(game.board.spaces) if 0 < game.board.distance(start, s) <= 2 and s not in taken)
    table.positions[cfg.nicknames["abe"]] = dest
    click(session, table, Event.END_ACTION)
    assert game.fighters["abe"].pos == dest and game.hand_moves == {}


# ---------------------------------------------------------------- the permission a plan grants in the same press

def test_a_plan_move_keeps_its_permission_and_a_longer_walk_is_refused(tmp_path):
    """Crash Through the Trees recognised at End action grants "up to 5": the press must not spend it (review 17/11)."""
    from test_bigfoot_human import TRAINING
    from test_d3_table_effects import build
    from test_e2_human_cards import human_scheme
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "bigfoot", (TRAINING,))
    try:
        human_hand(table, game, "Crash Through the Trees", "Hoax")
        human_scheme(session, table, game, "Crash Through the Trees")
        assert game.hand_moves["bigfoot"]["steps"] == 5
        start = game.fighters["bigfoot"].pos
        taken = {f.pos for f in game.fighters.values() if f.alive}
        far = next(s for s in sorted(game.board.spaces) if game.board.distance(start, s) == 6 and s not in taken)
        table.positions[cfg.nicknames["bigfoot"]] = far
        msgs = click(session, table, Event.END_ACTION)
        assert game.fighters["bigfoot"].pos == start and said(msgs, "el maximo es 5"), msgs
    finally:
        client.close()
        fake.close()


def test_a_plan_move_as_the_last_action_with_a_hand_limit_discard_keeps_the_walk(tmp_path):
    from test_bigfoot_human import TRAINING
    from test_d3_table_effects import build
    from test_e2_human_cards import human_scheme
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "bigfoot", (TRAINING,))
    try:
        game.actions_left = 1
        human_hand(table, game, "Crash Through the Trees", *["Hoax"] * 2, *["Skirmish"] * 2, "Regroup", "Disengage", "Savagery", "Hoax")
        msgs = human_scheme(session, table, game, "Crash Through the Trees")
        assert session.pending_discard is not None and "bigfoot" in game.hand_moves, msgs
        n = session.pending_discard["n"]
        played = card_ids(game, 1, "Crash Through the Trees")[0]
        table.human_hand = [i for i in table.human_hand if i != played]      # the scheme is already on the pile
        table.human_discard += table.human_hand[:n]
        table.human_hand = table.human_hand[n:]
        table.human_count = len(table.human_hand)
        start = game.fighters["bigfoot"].pos
        msgs = click(session, table, Event.END_ACTION)
        assert said(msgs, "Descarte hecho. Ahora mueve a Bigfoot hasta 5 casillas"), msgs
        assert game.fighters["bigfoot"].pos == start
    finally:
        client.close()
        fake.close()
