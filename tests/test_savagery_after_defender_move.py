"""Live bug, turn 15 on Pandemonium: Bigfoot (human) won with Savagery against Abe's B.P.R.D. Training; the defender's AFTER
moved Carla next to Bigfoot, and Savagery (which resolves next, combat_flow.py: defender first) must hit her."""
from __future__ import annotations

from conftest import give
from sparring.board import Board
from sparring.effects import ongoing
from sparring.state import Game
from test_bigfoot_effects import Answers


def training_then_savagery(shield: bool):
    board = Board.load("pandemonium")
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(board, 3, controllers=ctl, heroes=("abe-sapien", "bigfoot"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    abe, carla, bigfoot = g.hero(0), g.fighters["agent2"], g.hero(1)
    far = sorted((s for s in board.spaces if board.distance(9, s) > 3), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f not in (abe, carla, bigfoot)], far):
        f.pos = s
    abe.pos, carla.pos, bigfoot.pos = 10, 6, 9
    assert 8 in board.adj[9] and 10 in board.adj[9]

    def answer(req):
        return [5] if 5 in req.options else [8] if 8 in req.options else []
    ctl[0].queue = [answer] * 3
    if shield:
        ongoing.enter_play(g, 0, give(g, 0, "Counterhex Shield"))      # the bot's, played the turn before (live log, turn 14)
    savagery, training = give(g, 1, "Savagery"), give(g, 0, "B.P.R.D. Training")
    hp = carla.hp
    res = g.attack(bigfoot, abe, savagery, training)
    assert res.attacker_won and abe.pos == 5
    return carla, hp, res


def test_savagery_hits_the_sidekick_the_defenders_training_just_moved_next_to_bigfoot():
    carla, hp, res = training_then_savagery(shield=False)
    assert not carla.alive and carla.died_at == 8 and carla.hp == hp - 1      # a 1 HP sidekick dies where Training left her


def test_counterhex_shield_in_play_is_why_savagery_hurt_nobody_in_the_live_game():
    carla, hp, res = training_then_savagery(shield=True)
    assert carla.alive and carla.pos == 8 and carla.hp == hp      # the ONGOING stops the other player's effect damage
    assert any(line.startswith("Savagery") for line in res.human_effects)


# ---------------------------------------------------------------- the same combat through the panel (human attacker)
import pytest  # noqa: E402
from sparring.tts.ui import Event  # noqa: E402
from test_batch import click  # noqa: E402
from test_bigfoot_human import attack  # noqa: E402
from test_d3_table_effects import build  # noqa: E402
from test_dial_identity import split_shared_dials  # noqa: E402


def test_session_savagery_after_the_bots_training_moved_a_sidekick_next_to_bigfoot(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = build(tmp_path, "abe-sapien", "bigfoot", ("B.P.R.D. Training",))
    try:
        from test_d3_table_effects import human_hand
        abe, carla, bigfoot = game.fighters["abe"], game.fighters["agent2"], game.fighters["bigfoot"]
        board = game.board
        far = sorted((s for s in board.spaces if board.distance(9, s) > 3), reverse=True)
        for f, s in zip([f for f in game.fighters.values() if f not in (abe, carla, bigfoot)], far):
            f.pos = s
        b = 9
        a = sorted(board.adj[b])[0]
        e = sorted(board.adj[b] - {a})[0]
        c = sorted(s for s in board.spaces if board.distance(e, s) == 2 and s not in (a, b) and s not in board.adj[b])[0]
        abe.pos, carla.pos, bigfoot.pos = a, c, b
        for f in game.fighters.values():
            table.positions[cfg.nicknames[f.fid]] = f.pos
        card = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
        monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: card)
        human_hand(table, game, "Savagery", "Hoax")
        hp = carla.hp
        msgs = attack(session, table, game, "bigfoot", "Savagery", target="abe")
        print(msgs, abe.pos, carla.pos, carla.hp)
        assert not carla.alive and carla.died_at == 8
    finally:
        client.close()
        fake.close()
