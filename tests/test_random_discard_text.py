"""A random discard of the human's hand names how many cards it was drawn among and is shouted once (Ivan, 16/11):
the draw is uniform, but nobody knew between how many cards it was made."""
import re
from collections import Counter

import pytest

from conftest import Scripted
from sparring import i18n
from sparring.board import Board
from sparring.effects.ops_core import _random_positions_text, random_discard_alert
from sparring.effects.run import Ctx, EffectRun
from sparring.state import Game
from sparring.tts import lua


def hand_of(game, size):
    st = game.players[1]
    st.hand[:] = st.full_set[:size]


def fresh_run():
    return EffectRun([{"op": "discard", "cards": {"player": "opponent", "pick": "random"}}], Ctx(owner=0))


@pytest.fixture
def game():
    return Game.new(Board.load("bprd-hq"), seed=3, controllers={0: Scripted(), 1: Scripted()})


def test_the_text_says_among_how_many_cards_it_was_drawn(game):
    hand_of(game, 3)
    text = _random_positions_text(game, fresh_run(), 1, 1, "Fleeting Moments")
    assert re.fullmatch(r"Fleeting Moments, al azar: la carta [123] de las 3 de tu mano, contando desde la izquierda", text), text
    hand_of(game, 5)
    text = _random_positions_text(game, fresh_run(), 1, 2, "Ambush")
    assert re.fullmatch(r"Ambush, al azar: las cartas [1-5] y [1-5] de las 5 de tu mano, contando desde la izquierda", text), text


def test_the_english_text_says_the_size_too(game):
    i18n.set_language("en")
    hand_of(game, 3)
    assert "of the 3 in your hand, counting from the left" in _random_positions_text(game, fresh_run(), 1, 1, "Ambush")


@pytest.mark.parametrize("lang,one,many", [
    ("es", "DESCARTE AL AZAR: CARTA 2 DE 3 (DESDE LA IZQUIERDA)", "DESCARTE AL AZAR: CARTAS 1 Y 3 DE 5 (DESDE LA IZQUIERDA)"),
    ("en", "RANDOM DISCARD: CARD 2 OF 3 (FROM THE LEFT)", "RANDOM DISCARD: CARDS 1 AND 3 OF 5 (FROM THE LEFT)"),
])
def test_the_loud_line_is_in_capitals_and_fits_the_chat(lang, one, many):
    i18n.set_language(lang)
    assert random_discard_alert([2], 3) == one and random_discard_alert([1, 3], 5) == many
    for line in (one, many, random_discard_alert([1, 2, 3, 4, 5, 6], 10), random_discard_alert([1, 2, 3, 4], 7)):
        assert len(line) <= 64
        assert lua.broadcast(line, lua.ChatKind.WARNING)         # the whitelist of the chat accepts it


def test_the_draw_is_memoized_and_the_notice_is_left_once(game):
    hand_of(game, 5)
    run = fresh_run()
    first = _random_positions_text(game, run, 1, 1, "Ambush")
    assert game.fx.random_notice is not None
    game.fx.random_notice = None                                  # the session said it
    assert _random_positions_text(game, run, 1, 1, "Ambush") == first
    assert game.fx.random_notice is None                          # a rerun does not shout again


def test_every_position_comes_out_and_none_dominates(game):
    hand_of(game, 5)
    counts = Counter()
    for _ in range(500):
        _random_positions_text(game, fresh_run(), 1, 1, "Ambush")
        counts[game.fx.random_notice[0][0]] += 1
    assert set(counts) == {1, 2, 3, 4, 5}
    assert max(counts.values()) / 500 <= 0.30, counts


def test_a_hand_of_one_card_says_so_and_shouts_nothing(game):
    hand_of(game, 1)
    assert _random_positions_text(game, fresh_run(), 1, 1, "Ambush") == "Ambush, al azar: tu unica carta"
    assert game.fx.random_notice is None
    i18n.set_language("en")
    assert _random_positions_text(game, fresh_run(), 1, 1, "Ambush") == "Ambush, at random: your only card"


def test_the_draw_is_among_the_cards_the_player_still_holds_after_what_they_owe(game, monkeypatch):
    hand_of(game, 3)
    monkeypatch.setattr("sparring.effects.ops_core.table.discards_owed", lambda g, p: 2)
    assert _random_positions_text(game, fresh_run(), 1, 1, "Ambush") == "Ambush, al azar: tu unica carta"
    monkeypatch.setattr("sparring.effects.ops_core.table.discards_owed", lambda g, p: 3)
    assert _random_positions_text(game, fresh_run(), 1, 1, "Ambush") == "Ambush"


def test_the_bots_own_random_discard_names_no_position_and_shouts_nothing(game):
    from sparring.effects.random_discard import discard_random_known
    hand_of(game, 4)
    run = fresh_run()
    run._game = game
    assert discard_random_known(run, game, 1) is not None
    assert game.fx.random_notice is None and not run.flags
