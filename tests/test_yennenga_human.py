"""Yennenga played BY THE HUMAN through the panel (FakeTTS, batch mode): the ability (the panel asks how much of the damage meant for
her each Archer in her zone takes, for the bot's blow and for its effect damage), the choices surviving a resume, and Surprise
Volley and Shield Formation from the table. The bot's side of the same cards is in tests/test_yennenga_effects.py.

Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: every id the table reports is resolved against the
human's deck. Her Archers have 2 life and no life dial in the save (`no_dial` in data/tts/yennenga.json): their life lives in the
engine and the chat, never in a dial."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said
from test_e2_human_cards import press, put_adjacent, rig, with_rig  # noqa: F401

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def archers_beside(game, table, cfg):
    """Yennenga's two Archers next to her (one zone), nobody else near."""
    yen = game.fighters["yennenga"]
    for fid in ("archer1", "archer2"):
        spot = next(s for s in sorted(game.board.spaces) if game.board.share_zone(yen.pos, s) and s != yen.pos
                    and all(f.pos != s for f in game.fighters.values() if f.alive))
        game.fighters[fid].pos = spot
        table.positions[cfg.nicknames[fid]] = spot


def bot_attacks(session, table, game, title, target, human_title=None):
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid="hellboy", target=target, card=card)])
    table.face_down = []
    if human_title is not None:
        cid = card_ids(game, 1, human_title)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    return click(session, table, Event.REVEAL)


# ---------------------------------------------------------------- the ability

@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_panel_asks_each_archer_how_much_of_the_blow_it_takes(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Point Blank", "Point Blank")
    yen, a1, a2 = game.fighters["yennenga"], game.fighters["archer1"], game.fighters["archer2"]
    msgs = bot_attacks(session, table, game, "Excalibur", "yennenga")
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra["assign"] == "archer1" and req.options == [0, 1, 2], msgs
    msgs = click(session, table, Event.CHOICE, {"i": 3})                   # button 3: two points to the first Archer
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.extra["assign"] == "archer2" and req.extra["left"] == 6 - 2, msgs
    msgs = click(session, table, Event.CHOICE, {"i": 2})                   # one point to the second
    assert not a1.alive and a2.hp == 1 and yen.hp == 15 - (6 - 3), msgs
    assert session.pending is None


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_assigning_nothing_leaves_the_blow_on_yennenga(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Point Blank", "Point Blank")
    bot_attacks(session, table, game, "Excalibur", "yennenga")
    click(session, table, Event.CHOICE, {"i": 1})
    click(session, table, Event.CHOICE, {"i": 1})
    assert game.fighters["yennenga"].hp == 15 - 6 and game.fighters["archer1"].hp == 2 and game.fighters["archer2"].hp == 2


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_question_survives_a_resume(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Point Blank", "Point Blank")
    bot_attacks(session, table, game, "Excalibur", "yennenga")
    saved = session.to_dict()
    session._restore(saved)                                                # what --resume does
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra["assign"] == "archer1"
    click(session, table, Event.CHOICE, {"i": 2})
    click(session, table, Event.CHOICE, {"i": 1})
    assert game.fighters["archer1"].hp == 1 and game.fighters["yennenga"].hp == 15 - 5


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_question_counts_the_blow_that_is_left_after_her_defense(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Shield Formation", "Point Blank")
    bot_attacks(session, table, game, "Excalibur", "yennenga", "Shield Formation")
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.extra["damage"] == 6 - 3 and req.extra["left"] == 3 and req.extra["source"] == "combat"
