"""The human's opening hand is dealt by the bot (from their deck to their seat), the mulligan is done by the bot too, and
every hand size comes from the hero (Michelangelo: 3), for the bot and for the human."""
from __future__ import annotations

import dataclasses
import json

import pytest

from sparring.heroes import load_hero
from sparring.tts.ui import Event
from test_review5_fixes import idle_bot, place_human, setup_rig
from test_session import rig  # noqa: F401


@pytest.fixture
def deal_rig(rig, monkeypatch):  # noqa: F811
    """Setup-mode rig whose human has a physical deck, and a fake table that tells the two seats' hands apart."""
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid="HDECK")
    idle_bot(session, monkeypatch)
    human_returns = []
    bot_return = table.do_return_hand_to_deck

    def do_return(s):
        if '"Red"' not in s:
            return bot_return(s)
        human_returns.append(table.human_count)
        table.human_deck_cards += table.human_count
        table.human_count = 0
        return {"returned": len(human_returns), "deck": True}
    table.do_return_hand_to_deck = do_return
    bot_shuffle = table.do_shuffle_deck

    def do_shuffle(s):
        if "HDECK" not in s:
            return bot_shuffle(s)
        table.human_shuffles = getattr(table, "human_shuffles", 0) + 1
        return {"shuffled": True, "quantity": len(game.players[1].full_set)}
    table.do_shuffle_deck = do_shuffle
    table.human_returns = human_returns
    return session, table, game


def set_start_hand(game, player: int, n: int) -> None:
    hero = game.players[player].hero
    game.players[player].hero = dataclasses.replace(hero, hand_start=n, hand_max=n)


def test_the_bot_deals_the_human_their_opening_hand_at_setup(deal_rig):
    session, table, game = deal_rig
    out = session.start()
    assert table.human_deals == [5] and table.human_count == 5
    assert any("Te he repartido tus 5 cartas iniciales" in m for m in out)
    assert not any("Roba tus" in m or "roba tus" in m for m in out)
    assert session.setup["stage"] == "wait_human"


def test_a_human_hand_already_on_the_table_is_not_dealt_again(deal_rig):
    session, table, game = deal_rig
    table.human_count = 5
    session.start()
    assert table.human_deals == []


def test_the_human_mulligan_returns_shuffles_and_deals_again(deal_rig):
    session, table, game = deal_rig
    session.start()
    out = session.handle(Event.MULLIGAN)
    assert table.human_returns == [5] and table.human_shuffles == 1
    assert table.human_deals == [5, 5] and table.human_count == 5
    assert any("Mulligan hecho" in m and "5 cartas nuevas" in m for m in out)
    place_human(table, hellboy=30, lobster=29, count=5)
    session.handle(Event.READY)
    assert session.setup is None


def test_without_a_human_deck_or_on_a_failed_deal_the_human_is_told_to_draw(deal_rig):
    session, table, game = deal_rig
    table.human_deal_fails = True
    out = session.start()
    assert any("roba tus 5 cartas iniciales a mano" in m for m in out)
    assert not any("Te he repartido" in m for m in out)


@pytest.mark.parametrize("who", ["human", "bot"])
def test_michelangelo_starts_with_three_cards_on_either_side(deal_rig, who):
    session, table, game = deal_rig
    player = 1 if who == "human" else 0
    set_start_hand(game, player, 3)
    out = session.start()
    if who == "human":
        assert table.human_deals == [3] and any("Te he repartido tus 3 cartas iniciales" in m for m in out)
        assert not any("Te he repartido tus 5" in m or "Roba tus 5" in m for m in out)
    else:
        assert table.deal_calls == [3] and len(table.bot_hand) == 3
        assert any("reparte sus 3 cartas" in m for m in out)
        assert table.human_deals == [5]


def test_michelangelo_mulligan_redeals_three(deal_rig):
    session, table, game = deal_rig
    set_start_hand(game, 1, 3)
    session.start()
    out = session.handle(Event.MULLIGAN)
    assert table.human_deals == [3, 3] and any("3 cartas nuevas" in m for m in out)
    place_human(table, hellboy=30, lobster=29, count=2)
    assert any("debes tener 3" in m for m in session.handle(Event.READY))


def test_setup_messages_carry_the_hand_size_not_a_literal_five():
    for lang in ("es", "en"):
        raw = json.loads(open(f"data/i18n/{lang}.json", encoding="utf-8").read())
        for key in ("setup.first.alone", "setup.first.single", "setup.first.several", "setup.then.alone",
                    "setup.then.names", "sess.deal_yours", "sess.draw_yours", "setup.mull.dealt.plain",
                    "setup.mull.dealt.sidekick"):
            assert "{n}" in raw[key] and " 5 " not in raw[key], (lang, key)


def test_every_hero_hand_size_comes_from_its_data():
    sizes = {slug: (load_hero(slug).hand_start, load_hero(slug).hand_max) for slug in ("michelangelo", "medusa", "hellboy")}
    assert sizes == {"michelangelo": (3, 3), "medusa": (5, 7), "hellboy": (5, 7)}
