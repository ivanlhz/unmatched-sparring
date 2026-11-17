"""Live bug (17/11, Liz bot vs human Sinbad): Fleeting Moments makes the human discard at random while their Toil and Danger lets
Sinbad walk 3 spaces. One End action settled the discard and also closed the walk, and the bot went on with its second action.
The walk now gets its own step when the discard is settled by a press that finds the miniature where it was."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said
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


def test_the_human_attackers_walk_with_an_owed_discard_gets_the_same_step(tmp_path, monkeypatch):
    """The inverse order: the walk comes from the human's own attack (Toil and Danger) and a discard is owed on top."""
    from test_e2_human_cards import bot_defends_with_nothing
    from test_sinbad_human import attack, human_rig
    session, table, game, fake, cfg, client = human_rig(tmp_path)
    try:
        bot_defends_with_nothing(session, monkeypatch)
        put_adjacent(game, table, cfg, "sinbad", "hellboy")
        human_hand(table, game, "Toil and Danger", "Exploit", "Feint")
        attack(session, table, game, "Toil and Danger")
        assert "sinbad" in game.hand_moves
        session.pending_discard = {"n": 1, "baseline": len(game.players[1].discard), "kind": "cards", "hand": True}
        discard_on_table(table)
        msgs = click(session, table, Event.END_ACTION)
        assert said(msgs, "Descarte hecho. Ahora mueve a Sinbad hasta 3 casillas") and "sinbad" in game.hand_moves
        dest = free_space_at_3(game)
        table.positions[cfg.nicknames["sinbad"]] = dest
        click(session, table, Event.END_ACTION)
        assert game.fighters["sinbad"].pos == dest and game.hand_moves == {}
    finally:
        client.close()
        fake.close()
