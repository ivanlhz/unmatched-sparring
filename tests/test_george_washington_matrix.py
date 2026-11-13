"""George Washington against each of the other heroes in both seats: full session games to game over on FakeTTS (a passive scripted human
and a human who attacks every turn) and headless games with the heuristic and the search AI.

The same approach as tests/test_eredin_matrix.py (docs/card-identity.md): the human is a scripted player at the panel, the bot plays with its
real AI, and both heroes start worn down (HERO_HP) so a game ends in a few dozen steps. Washington's deck is sheet 187 (CardIDs 18700-18729):
shared with Wyatt Earp's and John Henry's decks: the matrix proves the decks are told apart by image and owner. His life dial has
Bullseye's GUID (166320): the pair is the one that exercises the tell-apart-by-name of the two dials in both seats. His three Spies (tokens
named Anna Strong, Pompey Lamb and Austin Roe), ESPIONAGE (the ruse token the bot spends, the question the human answers) and the schemes run
in these games, on the bot's side and on the table player's."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_tmnt_matrix import HERO_HP, MAX_STEPS, AttackDriver, human_step

OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "houdini", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "ciri", "eredin", "sinbad", "yennefer-triss", "triss-yennefer", "wyatt-earp", "john-henry", "chupacabra", "philippa", "raptors", "rosie-the-riveter"]
PAIRS = [("george-washington", h) for h in OTHERS] + [(b, "george-washington") for b in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


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
            if game.turn == session.human or session.pending is not None or session._paused() is not None:
                said += human_step(session, table, game)
            else:
                session._bot_continue()
            steps += 1
        return game, steps, said
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_a_full_session_game_reaches_game_over(tmp_path, bot, human):
    game, steps, said = play_to_the_end(tmp_path, bot, human)
    assert game.winner is not None, f"no winner after {steps} steps (turn {game.turn_no})"
    assert not any("Accion ilegal" in m or "Illegal action" in m for m in said), said


RIG_LIMIT: set = set()


def attack_params():
    return [pytest.param(b, h, id=i, marks=[pytest.mark.xfail(reason="fake-table hand count (RIG_LIMIT)", strict=False)] if (b, h) in RIG_LIMIT else [])
            for (b, h), i in zip(PAIRS, IDS)]


@pytest.mark.parametrize("bot,human", attack_params())
def test_a_game_where_the_human_attacks_every_turn_reaches_game_over(tmp_path, bot, human):
    """The human walks up to the bot's hero and attacks with a card of their own deck each turn (so the CardIDs the table
    reports for the combat are resolved against the human's deck, never the bot's) and discards to the hand limit."""
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


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_headless_games_with_the_heuristic_and_the_search_ai(bot, human):
    from sparring import sim
    assert sim.play(1, bot_hero=bot, human_hero=human).winner != "draw"
    ai = sim.make_bot("ismcts", iterations=4, seed=1)
    out = sim.play(1, bot_hero=bot, human_hero=human, medusa=ai, max_turns=25)
    assert out.turns >= 1 and ai.fallbacks == 0


def test_the_matrix_has_washington_in_both_seats_against_every_other_hero():
    assert len(PAIRS) == 2 * len(OTHERS) and all(("george-washington", h) in PAIRS and (h, "george-washington") in PAIRS for h in OTHERS)
