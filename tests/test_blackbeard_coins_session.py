"""The bot moves Blackbeard's coins on the table whoever plays him (sparring/session_blackbeard.py, `lua_blackbeard.set_doubloons`): at the start of a
game the Treasury gets its one coin, and every change of the engine's count (a ransom the human pays at the panel, the human's own payment for an
action or for a blow, the bot's) is written to the table in the same step. The Lua itself is tested on the lupa stub in
tests/test_blackbeard_coins_lua.py; here the fake table imitates what it answers."""
from __future__ import annotations

import re

from sparring import session_blackbeard
from sparring.effects.select import counter_value
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import FxTable, build, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with_nothing, press, put_adjacent

import pytest

HELLBOY_HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom", "Second Shot")


class CoinTable(FxTable):
    """The fake table plus a stack of three coins whose Treasury count the bot writes."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.coin_writes: list[int] = []            # the Treasury count of each write, in order
        self.coins_on_table = 3

    def do_set_doubloons(self, s):
        wanted = int(re.search(r"local WANT = (\d+)", s).group(1))
        self.coin_writes.append(wanted)
        total = self.coins_on_table
        return {"total": total, "treasury": min(wanted, total), "held": max(0, total - wanted), "moved": 1, "guids": ["coin1"]}


@pytest.fixture
def coin_rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=CoinTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_coins(bot, human, *hand):
    return pytest.mark.parametrize("coin_rig", [(bot, human, hand)], indirect=True)


def coins(game, player):
    return counter_value(game, player, "doubloons"), counter_value(game, player, "treasury")


@with_coins("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_start_of_a_game_gives_the_treasury_its_coin(coin_rig):
    session, table, game, fake, cfg = coin_rig
    session_blackbeard.track(session, announce=True)         # what `_begin_game` does: the stack starts whole, the Treasury holds one
    press(session, table, False)                             # the step that sends what was queued
    assert table.coin_writes == [1]


@with_coins("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_human_blackbeards_payment_for_an_action_is_written_to_the_table(coin_rig):
    session, table, game, fake, cfg = coin_rig
    session_blackbeard.track(session, announce=True)
    press(session, table, True)                              # the doubloon for an action
    assert coins(game, 1) == (1, 2) and table.coin_writes == [1, 2]


@with_coins("hellboy", "blackbeard", *HELLBOY_HAND)
def test_a_step_that_changes_nothing_writes_nothing(coin_rig):
    session, table, game, fake, cfg = coin_rig
    session_blackbeard.track(session, announce=True)
    press(session, table, False)
    before = len(table.coin_writes)
    click(session, table, Event.MANEUVER)
    assert len(table.coin_writes) == before


@with_coins("blackbeard", "hellboy", "A Brace of Primed Pistols", "Avast Ye!", "Parley", "Give No Quarter", "Queen Anne's Revenge")
def test_the_bots_blackbeard_gets_a_ransom_paid_by_the_human_on_the_table(coin_rig, monkeypatch):
    from sparring import ai_blackbeard
    from test_blackbeard_human import bot_attacks, next_to_the_human, set_coins
    session, table, game, fake, cfg = coin_rig
    monkeypatch.setattr(ai_blackbeard, "action_pays", lambda ai, g, req: False)
    next_to_the_human(session, table, game, cfg)
    set_coins(game, 0, 1, 2)
    session_blackbeard.track(session, announce=True)
    human_hand(table, game, "B.P.R.D. Training", "Excalibur", "Service Pistol", "Glimpse Of Hell", "Right Hand Of Doom")
    bot_attacks(session, table, game, "A Brace of Primed Pistols", "blackbeard", "hellboy", None)
    press(session, table, True)                     # the human pays the 2 doubloons of the ransom
    assert coins(game, 0) == (3, 0) and table.coin_writes[-1] == 0


@with_coins("hellboy", "blackbeard", *HELLBOY_HAND)
def test_a_table_with_a_coin_missing_says_so_once(coin_rig):
    session, table, game, fake, cfg = coin_rig
    table.coins_on_table = 2
    session_blackbeard.track(session, announce=True)
    msgs = press(session, table, True)
    assert said(msgs, "Blackbeard") and said(msgs, "2"), msgs
    assert any("moneda" in m.lower() or "doblon" in m.lower() for m in msgs), msgs


@with_coins("hellboy", "leonardo", *HELLBOY_HAND)
def test_nobody_playing_blackbeard_means_the_coins_are_never_touched(coin_rig):
    session, table, game, fake, cfg = coin_rig
    assert table.coin_writes == [] and session_blackbeard._player(session) is None
