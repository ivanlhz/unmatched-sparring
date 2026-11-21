"""Yennenga's Archer tokens at the table (Ivan, 2026-11-20): each Archer is a two-sided token, the face with a small yellow "2" is 2 health,
the face with no number is 1 health, and it is flipped as it is hurt; there is no dial. `data/tts/yennenga.json` gives the Z rotation of each
face (`faces`: 2 = 0, 1 = 180, to verify live). The bot turns its own tokens to the engine's life and says it; the session reads the human's and
asks them to flip a token that disagrees with the engine (and pings it). FakeTTS, both seats (sparring/session_archers.py)."""
from __future__ import annotations

import json

from sparring import session_archers
from sparring.heroes import HEROES_DIR
from test_d3_table_effects import said
from test_e2_human_cards import rig, with_rig  # noqa: F401


def guid(cfg, fid):
    return cfg.session_config().pieces[fid]


def look(session, announce=False):
    session_archers.track(session, announce=announce)
    session._commit()
    session._commit()                                                       # the ping a check queues goes out with the next closing


def capture(session):
    out = []
    session.say = lambda text, kind=None: out.append(text)
    return out


def test_the_data_records_which_face_is_which():
    tts = json.loads((HEROES_DIR.parent / "tts" / "yennenga.json").read_text(encoding="utf-8"))
    for fid in ("archer1", "archer2"):
        assert tts["fighters"][fid]["faces"] == {"2": 0, "1": 180} and tts["fighters"][fid]["verify_live"] is False


# ---------------------------------------------------------------- the bot's Archers

@with_rig("yennenga", "hellboy")
def test_the_bots_archers_start_on_the_two_face_and_a_hit_to_one_health_flips_the_token(rig):
    session, table, game, fake, cfg = rig
    out = capture(session)
    look(session, announce=True)
    assert table.archer_writes == [] and out == []                        # already on the "2" face: nothing to turn, nothing to say
    game.damage(game.fighters["archer1"], 1, "effect")
    look(session)
    assert table.archer_writes == [(guid(cfg, "archer1"), 180.0)]
    assert said(out, "Archer 1 tiene 1 de vida") and said(out, "ficha"), out
    look(session)
    assert len(table.archer_writes) == 1                                   # nothing changed: not turned again


@with_rig("yennenga", "hellboy")
def test_healing_to_two_flips_it_back_and_a_returned_archer_comes_back_on_the_two_face(rig):
    session, table, game, fake, cfg = rig
    a1, a2 = game.fighters["archer1"], game.fighters["archer2"]
    look(session, announce=True)
    game.damage(a1, 1, "effect")
    look(session)
    game.heal(a1, 1)                                                       # One With The Land
    look(session)
    assert [r for g, r in table.archer_writes if g == guid(cfg, "archer1")] == [180.0, 0.0]
    game.damage(a2, 1, "effect")
    look(session)
    game.damage(a2, 1, "effect")                                           # defeated: nothing to turn while it is off the board
    n = len(table.archer_writes)
    look(session)
    assert len(table.archer_writes) == n
    a2.alive, a2.hp, a2.pos = True, 2, next(s for s in sorted(game.board.spaces) if all(f.pos != s for f in game.fighters.values() if f.alive))
    look(session)                                                          # Surprise Volley / Shield Formation: back at 2, on the "2" face
    assert table.archer_rot[guid(cfg, "archer2")] == 0.0


@with_rig("yennenga", "hellboy")
def test_a_restart_puts_every_token_back_on_the_two_face(rig):
    session, table, game, fake, cfg = rig
    table.archer_rot[guid(cfg, "archer2")] = 180.0                         # left on the one-health face by the last game
    look(session, announce=True)
    assert table.archer_rot[guid(cfg, "archer2")] == 0.0


# ---------------------------------------------------------------- the human's Archers

@with_rig("hellboy", "yennenga")
def test_the_human_who_forgets_to_flip_is_told_and_the_piece_is_pinged_once(rig):
    session, table, game, fake, cfg = rig
    out = capture(session)
    look(session, announce=True)
    assert out == [] and table.archer_writes == []                         # the human's tokens are never turned by the bot
    game.damage(game.fighters["archer1"], 1, "effect")
    look(session)
    assert said(out, "Archer 1 tiene 1 de vida pero su ficha muestra 2"), out
    assert any([guid(cfg, "archer1")] in group for group in table.pings), table.pings
    n = len(out)
    look(session)
    assert len(out) == n                                                   # said once while the disagreement stays
    table.archer_rot[guid(cfg, "archer1")] = 180.0                         # the human flips it
    look(session)
    assert len(out) == n and table.archer_writes == []                     # agreement: silence


@with_rig("hellboy", "yennenga")
def test_a_token_flipped_the_wrong_way_is_said_and_a_new_disagreement_is_said_again(rig):
    session, table, game, fake, cfg = rig
    out = capture(session)
    table.archer_rot[guid(cfg, "archer2")] = 180.0                         # shows 1 health while the engine says 2
    look(session, announce=True)
    assert said(out, "Archer 2 tiene 2 de vida pero su ficha muestra 1"), out
    game.damage(game.fighters["archer2"], 1, "effect")                    # the engine now agrees with the token ...
    n = len(out)
    look(session)
    assert len(out) == n
    game.heal(game.fighters["archer2"], 1)                                 # ... and disagrees again
    look(session)
    assert len(out) == n + 1


@with_rig("hellboy", "yennenga")
def test_a_defeated_human_archer_is_not_read(rig):
    session, table, game, fake, cfg = rig
    out = capture(session)
    game.defeat(game.fighters["archer1"])
    look(session, announce=True)
    assert not said(out, "Archer 1"), out


@with_rig("yennenga", "hellboy")
def test_a_combat_that_hurts_the_bots_archer_flips_its_token_without_anybody_looking(rig, monkeypatch):
    from sparring.tts.ui import Event
    from test_batch import click
    from test_d3_table_effects import human_attack, human_hand
    from test_e2_human_cards import bot_defends_with_nothing, put_adjacent
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "archer1")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Excalibur")
    human_attack(session, table, game, "hellboy", "archer1", "Excalibur", value=-5)         # a 1 against no defense: one point
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["archer1"].hp == 1 and said(msgs, "Archer 1 tiene 1 de vida"), msgs
    assert table.archer_rot[guid(cfg, "archer1")] == 180.0
