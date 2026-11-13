"""John Henry on the table through the panel (FakeTTS, batch mode), both seats: the human's start-of-turn token (laid by hand, read from the
table), the walks he makes by hand over the tracks and the paths they make, the moves his cards ask of the human, the free action that only
an attack may spend, and the bot's John Henry laying its tokens on the table itself. The bot's side of the same cards is in
tests/test_john_henry_effects.py.

The track tokens are Custom_Tokens taken from a stack of ten: the table scan recognises them by the picture they carry (`lua.read_tokens_by_image`)."""
from __future__ import annotations

import re

import pytest

from sparring import tracks
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import FxTable, bot_turn, build, card_ids, human_hand, said
from test_d3_table_effects import human_attack as human_plays_attack
from test_e2_human_cards import bot_defends_with_nothing, human_scheme, put_adjacent  # noqa: F401
from test_human_pile_to_hand import HandTable
from test_john_henry_effects import chain


class JohnTable(HandTable):
    """The fake table plus John Henry's tokens: the ones on the board (what a scan finds) and the copies the bot takes out of the stack."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.on_board: list[dict] = []             # tokens the human laid: {"guid", "space", "dist"}
        self.laid: list[int] = []                  # spaces the bot's tokens were laid on
        self.stack_empty = False

    def do_read_tokens_by_image(self, s):
        return {"tokens": [dict(t) for t in self.on_board], "stacks": 1}

    def do_place_token_at_space(self, s):
        if self.stack_empty:
            return {"taken": False}
        space = int(re.search(r"spaceWorld\((\d+)\)", s).group(1))
        self.laid.append(space)
        guid = f"trk{len(self.laid)}"
        self.on_board.append({"guid": guid, "space": space, "dist": 0.0})
        return {"taken": guid, "moved": guid, "via": "takeObject"}

    def lay(self, space, guid=None):
        self.on_board.append({"guid": guid or f"h{len(self.on_board)}", "space": space, "dist": 0.0})


def human_rig(tmp_path, bot="hellboy", hand=()):
    return build(tmp_path, bot, "john-henry", hand, table_cls=JohnTable)


@pytest.fixture
def mine(tmp_path):
    session, table, game, fake, cfg, client = human_rig(tmp_path)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.fixture
def bots(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "john-henry", "hellboy", ("Larger Than Life", "Striking Fire"), table_cls=JohnTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def free_row(game, n):
    return chain(game.board, n)


# ---------------------------------------------------------------- the human's tokens

def test_the_start_of_turn_asks_the_human_to_lay_a_track_token_and_waits_for_end_action(mine):
    session, table, game, fake, cfg = mine
    msgs = bot_turn(session, table, [])
    assert game.turn == 1 and session.ability_wait is not None
    assert said(msgs, "STEEL-DRIVING MAN: invoca una ficha de via en una casilla de la zona de John Henry")
    assert game.fx.tracks[1] == [], "the engine does not summon the human's token: the table is the source"


def test_the_token_the_human_lays_is_read_from_the_table_at_end_action(mine):
    session, table, game, fake, cfg = mine
    bot_turn(session, table, [])
    john = game.fighters["john"]
    space = next(s for s in sorted(game.board.spaces) if game.board.share_zone(john.pos, s) and s != john.pos)
    table.lay(space)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fx.tracks[1] == [space] and session.ability_wait is None
    assert said(msgs, "Ficha de via de John Henry") and said(msgs, "quedan 9 por invocar")


def test_tokens_that_are_not_on_the_board_or_are_the_stack_are_not_tracks(mine):
    session, table, game, fake, cfg = mine
    table.on_board = [{"guid": "far", "space": 3, "dist": 40.0}]
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert game.fx.tracks[1] == []


def test_a_token_the_human_takes_off_the_table_is_forgotten_and_two_on_a_space_count_once(mine):
    session, table, game, fake, cfg = mine
    table.lay(4)
    table.lay(4)
    table.lay(6)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert sorted(game.fx.tracks[1]) == [4, 6]
    table.on_board = [t for t in table.on_board if t["space"] != 4]
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert game.fx.tracks[1] == [6]


def test_a_table_that_cannot_be_read_leaves_the_engines_tokens_alone(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    game.fx.tracks[1] = [4]
    monkeypatch.setattr(JohnTable, "do_read_tokens_by_image", lambda self, s: {"no_board": True})
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert game.fx.tracks[1] == [4]


# ---------------------------------------------------------------- walking by hand over the tracks

def test_a_maneuver_by_hand_over_the_tracks_makes_the_paths(mine):
    session, table, game, fake, cfg = mine
    row = free_row(game, 7)
    john = game.fighters["john"]
    foe = game.fighters["hellboy"]
    foe.pos = next(s for s in sorted(game.board.spaces, reverse=True) if s not in row)
    table.positions[cfg.nicknames["hellboy"]] = foe.pos
    john.pos = row[0]
    table.positions[cfg.nicknames["john"]] = row[0]
    for s in row[1:5]:
        table.lay(s)
    game.fx.tracks[1] = list(row[1:5])
    game.turn, game.actions_left = 1, 2
    click(session, table, Event.MANEUVER)
    table.positions[cfg.nicknames["john"]] = row[5]                  # four free spaces and one step: more than his 2
    click(session, table, Event.END_ACTION)
    assert john.pos == row[5] and tracks.paths_used(game) == 4


def test_the_four_paths_cancel_the_bots_card_with_the_eighteen_pound_hammer(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = human_rig(tmp_path, "sinbad", ("Momentous Shift",))
    try:
        put_adjacent(game, table, cfg, "john", "sinbad")
        game.fx.paths = [90, 91, 92, 93]
        card = next(c for c in game.players[0].hand if c.title == "Momentous Shift")
        game.fx.turn_start_pos["sinbad"] = -1
        human_hand(table, game, "Eighteen-pound Hammer")
        monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: card)
        human_plays_attack(session, table, game, "john", "sinbad", "Eighteen-pound Hammer")
        msgs = click(session, table, Event.REVEAL)
        combat = next(m for m in msgs if m.startswith("Combate:"))
        assert "Momentous Shift (3)" in combat and "(5)" not in combat, msgs
    finally:
        client.close()
        fake.close()


# ---------------------------------------------------------------- the cards that move the human

def test_striking_fire_tells_the_human_the_tracks_do_not_count(mine):
    session, table, game, fake, cfg = mine
    human_hand(table, game, "Striking Fire", "Larger Than Life")
    game.fx.tracks[1] = [9]
    table.lay(9)
    msgs = human_scheme(session, table, game, "Striking Fire")
    assert said(msgs, "hasta 4 casillas") and said(msgs, "las casillas con ficha de via no cuentan"), msgs
    assert game.actions_left == 2, "1 spent on the scheme, 1 gained"


def test_without_a_token_on_the_board_the_move_says_nothing_about_tracks(mine):
    session, table, game, fake, cfg = mine
    human_hand(table, game, "Striking Fire", "Larger Than Life")
    msgs = human_scheme(session, table, game, "Striking Fire")
    assert said(msgs, "hasta 4 casillas") and not said(msgs, "ficha de via"), msgs


def test_power_through_names_the_tracks_only_for_a_move_of_john_henry(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    put_adjacent(game, table, cfg, "john", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Power Through", "Larger Than Life")
    game.fx.tracks[1] = [9]
    table.lay(9)
    human_plays_attack(session, table, game, "john", "hellboy", "Power Through")
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.CHOICE, {"i": 2})                  # the fighter to move: Hellboy, the rival's
    assert said(msgs, "hasta 2 casillas") and not said(msgs, "ficha de via"), msgs


# ---------------------------------------------------------------- the free action

def test_a_free_action_to_attack_is_not_a_maneuver_for_the_human(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    game.turn, game.actions_left, game.fx.attack_credit = 1, 1, 1
    msgs = click(session, table, Event.MANEUVER)
    assert said(msgs, "solo sirve para atacar") and game.actions_left == 1
    msgs = click(session, table, Event.SCHEME)
    assert said(msgs, "solo sirve para atacar") and game.actions_left == 1


# ---------------------------------------------------------------- the bot's John Henry

def test_the_bots_token_goes_where_the_engine_chose_and_is_laid_on_the_table(bots):
    session, table, game, fake, cfg = bots
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    assert game.turn == 1 and len(game.fx.tracks[0]) == 1
    assert table.laid == game.fx.tracks[0], "the table got the token on the space the engine chose"
    assert said(msgs, "John Henry invoca una ficha de via") and session.token_copies["track"] == ["trk1"]


def test_a_stack_that_gives_nothing_makes_the_bot_ask_the_human_for_the_token(bots):
    session, table, game, fake, cfg = bots
    table.stack_empty = True
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "No he podido sacar una ficha de via") and len(game.fx.tracks[0]) == 1


def test_the_bots_john_henry_walks_over_its_tracks_and_the_paths_are_counted_during_its_turn(bots):
    session, table, game, fake, cfg = bots
    row = free_row(game, 7)
    john, hellboy = game.fighters["john"], game.fighters["hellboy"]
    john.pos, hellboy.pos = row[0], row[6]
    table.positions[cfg.nicknames["john"]], table.positions[cfg.nicknames["hellboy"]] = row[0], row[6]
    for s in row[1:5]:
        tracks.add(game, 0, s)
    game.turn = 0
    seen = []
    session.ai.pick_ability_target = lambda g: None

    def plan(g):
        seen.append((g.actions_left, tracks.paths_used(g)))
        return Act("maneuver", fid="john", moves={"john": row[5]}) if g.actions_left == 2 else Act("maneuver", moves={})
    session.ai.plan = plan
    session._bot_continue()
    assert john.pos == row[5] and seen == [(2, 0), (1, 4)]


# ---------------------------------------------------------------- tokens left over from another game

def test_more_tokens_than_the_supply_on_the_board_are_warned_and_never_deleted(mine):
    session, table, game, fake, cfg = mine
    for s in range(12):
        table.lay(s)
    msgs = click(session, table, Event.MANEUVER) + click(session, table, Event.END_ACTION)
    assert said(msgs, "12 fichas de via") and len(table.on_board) == 12
    assert len(game.fx.tracks[1]) == tracks.SUPPLY


def test_several_tokens_on_the_board_on_the_first_turn_are_warned_as_left_over(mine):
    session, table, game, fake, cfg = mine
    game.turn_no = 2
    table.lay(3)
    table.lay(5)
    msgs = click(session, table, Event.MANEUVER) + click(session, table, Event.END_ACTION)
    assert said(msgs, "sobras de otra partida") and sorted(game.fx.tracks[1]) == [3, 5]


def test_the_one_token_laid_on_the_first_turn_is_no_warning(mine):
    session, table, game, fake, cfg = mine
    game.turn_no = 2
    table.lay(3)
    msgs = click(session, table, Event.MANEUVER) + click(session, table, Event.END_ACTION)
    assert not said(msgs, "sobras") and game.fx.tracks[1] == [3]
