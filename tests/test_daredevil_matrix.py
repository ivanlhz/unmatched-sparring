"""Daredevil against every other hero, in both seats, played to game over: whole sessions on FakeTTS (a passive human and an
attacking one) and headless games with the heuristic and the search AI.

His deck is sheet 176 like Medusa's and the turtles' (CardIDs 17600-17621 for his 22 cards), told apart by deck image and seat
(docs/card-identity.md). The human is the scripted player of the TMNT matrix or the attacking driver, with the table-aware
answers of the Doctor Strange matrix (the one-button pauses of Take A Knee, the declaration of the ability's BLIND BOOST, the cards
the human lays on the pile). The bot plays with its real AI. Both heroes start worn down so that a game ends in a few dozen steps."""
from __future__ import annotations

import pytest

from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_doctor_strange_matrix import StrangeAttackDriver, play_to_the_end
from test_tmnt_matrix import HERO_HP

DAREDEVIL = "daredevil"
OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael",
          "doctor-strange", "houdini", "bigfoot"]
PAIRS = [(DAREDEVIL, h) for h in OTHERS] + [(b, DAREDEVIL) for b in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_a_full_session_game_reaches_game_over(tmp_path, bot, human):
    game, steps, said = play_to_the_end(tmp_path, bot, human)
    assert game.winner is not None, f"no winner after {steps} steps (turn {game.turn_no})"
    assert not any("Accion ilegal" in m or "Illegal action" in m for m in said), said


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_a_game_where_the_human_attacks_every_turn_reaches_game_over(tmp_path, bot, human):
    """The human walks up to the bot's hero and attacks with a card of their own deck each turn (Daredevil's cards are resolved
    against his 22-card deck, never Medusa's or a turtle's, whichever seat he sits in)."""
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    try:
        set_hand(session, table, game, *[c.title for c in game.players[0].deck[:game.start_hand(0)]])
        table.human_count = game.start_hand(1)
        for player in (0, 1):
            hero = game.hero(player)
            hero.hp = HERO_HP
            guid = cfg.session_config().dials[hero.fid]
            table.dials[guid]["value"] = session.dials_written[guid] = HERO_HP
        d = StrangeAttackDriver(session, table, game, cfg, attacks=True)
        d.play_out()
        assert game.winner is not None
        assert any("Combate" in m for m in d.log), "the human never attacked"
        assert not [m for m in d.log if "ilegal" in m.lower()], d.log[-5:]
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_headless_games_with_the_heuristic_and_the_search_ai(bot, human):
    from sparring import sim
    assert sim.play(1, bot_hero=bot, human_hero=human).winner != "draw"
    ai = sim.make_bot("ismcts", iterations=4, seed=1)
    out = sim.play(1, bot_hero=bot, human_hero=human, medusa=ai, max_turns=25)
    assert out.turns >= 1 and ai.fallbacks == 0
