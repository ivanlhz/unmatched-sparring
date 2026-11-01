"""Full FakeTTS games with Leonardo (bot or human) against each of the five other heroes, to game over.

The session runs for real (batch mode, one composite script per button) against the fake table of
tests/test_d3_table_effects.py. The human is a scripted player at the panel: it maneuvers, answers every pause with the
first button, never defends and passes. The bot (heuristic AI) attacks, plays its schemes and its start-of-turn
ability on its own. The game ends when a hero falls (the bot kills the human's hero) and nothing raises on the way."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build

OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
MAX_STEPS = 800
HERO_HP = 5


def settle_owed_discard(session, table, game) -> None:
    """The human puts on the table pile the cards they owe (a price they paid, the hand limit)."""
    owed = session.pending_discard
    if owed is None:
        return
    hand = [c.card_id for c in game.players[1].hand]
    named = list(owed.get("cards") or [])
    extra = max(0, len(hand) - 7) if owed["kind"] == "limit" else owed["n"] - len(named)
    ids = named + [i for i in hand if i not in named][:extra]
    table.human_discard += [i for i in ids if i not in table.human_discard]
    table.human_count = max(0, table.human_count - len([i for i in ids if i not in named]))
    session.snap = None


def human_step(session, table, game) -> None:
    """One click of the scripted human."""
    settle_owed_discard(session, table, game)
    paused = session._paused()
    if paused is not None:
        click(session, table, Event.CHOICE, {"i": 1})
        return
    if session.pending is not None:
        click(session, table, Event.REVEAL)
        return
    if session.ability_wait is not None or game.actions_left <= 0:
        click(session, table, Event.END_ACTION)
        return
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)


def play_to_the_end(tmp_path, bot, human):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, ())
    try:
        for player in (0, 1):                  # both heroes start worn down so that a game ends in a few dozen steps
            hero = game.hero(player)
            hero.hp = HERO_HP
            guid = cfg.session_config().dials[hero.fid]
            table.dials[guid]["value"] = session.dials_written[guid] = HERO_HP
        steps = 0
        while game.winner is None and steps < MAX_STEPS:
            if game.turn == 1 or session.pending is not None or session._paused() is not None:
                human_step(session, table, game)
            else:
                session._bot_continue()
            steps += 1
        return game, steps
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("other", OTHERS)
@pytest.mark.parametrize("leo_is_bot", [True, False])
def test_a_full_session_game_with_leonardo_reaches_game_over(tmp_path, other, leo_is_bot):
    bot, human = ("leonardo", other) if leo_is_bot else (other, "leonardo")
    game, steps = play_to_the_end(tmp_path, bot, human)
    assert game.winner is not None, f"no winner after {steps} steps (turn {game.turn_no})"


@pytest.mark.parametrize("other", OTHERS)
@pytest.mark.parametrize("leo_is_bot", [True, False])
def test_headless_games_with_the_heuristic_and_the_search_ai(other, leo_is_bot):
    from sparring import sim
    bot, human = ("leonardo", other) if leo_is_bot else (other, "leonardo")
    for seed in range(3):
        assert sim.play(seed, bot_hero=bot, human_hero=human).winner != "draw"
        ai = sim.make_bot("ismcts", iterations=6, seed=seed)
        out = sim.play(seed, bot_hero=bot, human_hero=human, medusa=ai, max_turns=30)
        assert out.turns >= 1 and ai.fallbacks == 0
