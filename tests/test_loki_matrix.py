"""Loki against the other heroes in both seats: headless games with the heuristic and the search AI against every hero (the TRICKs change hands
in the engine and in the search), and full session games to game over on FakeTTS against the heroes whose CardIDs the fake table's per-seat lists
cannot confuse with his (Hellboy's box and Houdini: a TRICK in the human's hand is a card of another range there).

Against the decks of sheet 176 (Medusa, the turtles, ...) the table is the real thing's job: the ledger (`session_tricks`) tells a TRICK from the
human's own card of the same CardID by GUID, which the fake cannot give two objects of one id; the engine side of that collision is
tests/test_loki_effects.py (`test_a_trick_and_a_card_of_the_opponent_with_the_same_id_are_told_apart`)."""
from __future__ import annotations

import pytest

from sparring.heroes import available_heroes
from sparring.tts.ui import Event
from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_tmnt_matrix import HERO_HP, MAX_STEPS, AttackDriver, human_step

OTHERS = sorted(h for h in available_heroes() if h != "loki")
FAKE_OTHERS = ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]
SIM_PAIRS = [("loki", h) for h in OTHERS] + [(b, "loki") for b in OTHERS]
FAKE_PAIRS = [("loki", h) for h in FAKE_OTHERS] + [(b, "loki") for b in FAKE_OTHERS]


@pytest.mark.parametrize("bot,human", SIM_PAIRS, ids=[f"{b}-vs-{h}" for b, h in SIM_PAIRS])
def test_headless_games_with_the_heuristic_and_the_search_ai(bot, human):
    from sparring import sim
    assert sim.play(1, bot_hero=bot, human_hero=human).winner != "draw"
    ai = sim.make_bot("ismcts", iterations=4, seed=1)
    out = sim.play(1, bot_hero=bot, human_hero=human, medusa=ai, max_turns=25)
    assert out.turns >= 1 and ai.fallbacks == 0


def play_to_the_end(tmp_path, bot: str, human: str):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    try:
        for player in (0, 1):
            hero = game.hero(player)
            hero.hp = HERO_HP
            guid = cfg.session_config().dials[hero.fid]
            table.dials[guid]["value"] = session.dials_written[guid] = HERO_HP
        steps, said = 0, []
        while game.winner is None and steps < MAX_STEPS:
            if game.turn == session.human or session.pending is not None or session._paused() is not None or session.moving:
                said += human_step(session, table, game)
            else:
                session._bot_continue()
            steps += 1
        return game, steps, said
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("bot,human", FAKE_PAIRS, ids=[f"{b}-vs-{h}" for b, h in FAKE_PAIRS])
def test_a_full_session_game_reaches_game_over(tmp_path, bot, human):
    game, steps, said = play_to_the_end(tmp_path, bot, human)
    assert game.winner is not None, f"no winner after {steps} steps (turn {game.turn_no})"
    assert not any("Accion ilegal" in m or "Illegal action" in m for m in said), said


def test_the_matrix_has_loki_in_both_seats_against_every_other_hero():
    assert len(SIM_PAIRS) == 2 * len(OTHERS) and all(("loki", h) in SIM_PAIRS and (h, "loki") in SIM_PAIRS for h in OTHERS)
    assert {"medusa", "chupacabra", "pandora", "blackbeard"} <= set(OTHERS)


@pytest.mark.parametrize("bot,human", FAKE_PAIRS, ids=[f"{b}-vs-{h}" for b, h in FAKE_PAIRS])
def test_a_game_where_the_human_attacks_every_turn_reaches_game_over(tmp_path, bot, human):
    """The human walks up to the bot's hero and attacks with a card of their own deck each turn (a TRICK of Loki's among them when they are Loki's)
    and discards to the hand limit."""
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    try:
        set_hand(session, table, game, *[c.title for c in game.players[0].deck[:game.start_hand(0)]])
        table.human_count = game.start_hand(1)
        for player in (0, 1):
            hero = game.hero(player)
            hero.hp = HERO_HP
            guid = cfg.session_config().dials[hero.fid]
            table.dials[guid]["value"] = session.dials_written[guid] = HERO_HP
        d = AttackDriver(session, table, game, cfg, attacks=True)
        d.play_out()
        assert game.winner is not None
        assert any("Combate" in m for m in d.log), "the human never attacked"
        assert not [m for m in d.log if "ilegal" in m.lower()], d.log[-5:]
    finally:
        client.close()
        fake.close()
