"""Little Red against each of the other heroes in both seats: full session games to game over on FakeTTS (a passive scripted human and a human who
attacks every turn) and headless games with the heuristic and the search AI.

The same approach as tests/test_ciri_matrix.py (docs/card-identity.md): the human is a scripted player at the panel, the bot plays with its real AI,
and both heroes start worn down (HERO_HP) so a game ends in a few dozen steps. Her deck is sheet 177 (CardIDs 17700-17729), shared with a few loose
cards of other bags, and the loose Basket card (CardID 17600, the range of the sheet-176 decks) lies in her discard zone from the start: the table
of every game here has it in her pile, so no read may take it for a card of anybody's deck. A wild basket is a question the human answers on the
panel; the bot answers its own. The opponents are every other hero of `data/heroes`, so a hero added later is in the matrix without touching this file."""

from __future__ import annotations

import pytest

from sparring.heroes import available_heroes
from sparring.tts.ui import Event
from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_tmnt_matrix import HERO_HP, MAX_STEPS, AttackDriver, human_step

OTHERS = [h for h in available_heroes() if h != "little-red-riding-hood"]
PAIRS = [("little-red-riding-hood", h) for h in OTHERS] + [(b, "little-red-riding-hood") for b in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


BASKET_CARD = 17600
STRAY = ("17600", "La mesa manda:", "estaba suelta en la mesa")      # the Basket as a card, an extra discard adopted, a loose card taken back


def lay_the_basket(table, game):
    """The Basket lies in the discard zone of whoever plays Little Red, as the gate leaves it."""
    (table.bot_discard if game.players[0].hero.slug == "little-red-riding-hood" else table.human_discard).append(BASKET_CARD)


def basket_stayed_out_of_the_game(game, said) -> bool:
    """Her thirty cards are all there (the Basket is none of them: it is never counted, drawn or returned) and no read reported a stray card.
    A deck of sheet 176 does have a card 17600 of its own, so the id alone proves nothing about the opponent's zones."""
    for p in game.players:
        if p.hero.slug == "little-red-riding-hood":
            zones = [c for c in (*p.hand, *p.deck, *p.discard, *p.tucked, *p.removed) if c in p.full_set]       # Loki's TRICKs borrowed by her hand are not her cards
            if len(zones) != 30 or len(set(zones)) != 30:
                return False
    return not any(w in m for m in said for w in STRAY)


def play_to_the_end(tmp_path, bot: str, human: str):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    try:
        lay_the_basket(table, game)
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


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_a_full_session_game_reaches_game_over(tmp_path, bot, human):
    game, steps, said = play_to_the_end(tmp_path, bot, human)
    assert game.winner is not None, f"no winner after {steps} steps (turn {game.turn_no})"
    assert basket_stayed_out_of_the_game(game, said), said
    assert not any("Accion ilegal" in m or "Illegal action" in m for m in said), said


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_a_game_where_the_human_attacks_every_turn_reaches_game_over(tmp_path, bot, human):
    """The human walks up to the bot's hero and attacks with a card of their own deck each turn (so the CardIDs the table
    reports for the combat are resolved against the human's deck, never the bot's) and discards to the hand limit."""
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    try:
        lay_the_basket(table, game)
        set_hand(session, table, game, *[c.title for c in game.players[0].deck[:game.start_hand(0)]])
        table.human_count = game.start_hand(1)
        for player in (0, 1):
            hero = game.hero(player)
            hero.hp = HERO_HP
            guid = cfg.session_config().dials[hero.fid]
            table.dials[guid]["value"] = session.dials_written[guid] = HERO_HP
        d = AttackDriver(session, table, game, cfg, attacks=True)
        d.play_out()
        assert game.winner is not None and basket_stayed_out_of_the_game(game, d.log)
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


def test_the_matrix_has_little_red_in_both_seats_against_every_other_hero():
    assert len(PAIRS) == 2 * len(OTHERS) and all(("little-red-riding-hood", h) in PAIRS and (h, "little-red-riding-hood") in PAIRS for h in OTHERS)
