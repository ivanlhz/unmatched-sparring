"""Doctor Strange against every other hero, in both seats, played to game over: whole sessions on FakeTTS (a passive human and
an attacking one) and headless games with the heuristic and the search AI.

His deck is sheet 176 like Medusa's and the four turtles': CardIDs 17600-17629 again, told apart by deck image and seat
(docs/card-identity.md). Every pair with Doctor Strange is one more proof, through the real session on the fake table, that
his cards are never read as Medusa's or a turtle's. The human is the scripted player of the TMNT matrix (maneuvers, first
button on every pause, never defends) or the attacking driver; the bot plays with its real AI. Both heroes start worn down
(`HERO_HP`) so that a game ends in a few dozen steps.

A pause the human's Doctor Strange meets that needs the table (DARK PACT's buttons, BLIND BOOST's discards, the card No,
Really, I'm a Doctor reveals) is answered by `StrangeAttackDriver` / `strange_step` the way a player would: the buttons, and
the cards put on the pile for the bot to read."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_tmnt_matrix import HERO_HP, MAX_STEPS, AttackDriver, human_step, settle_owed_discard

STRANGE = "doctor-strange"
OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael"]
PAIRS = [(STRANGE, h) for h in OTHERS] + [(b, STRANGE) for b in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


def lay_on_pile(session, table, game, n: int = 1) -> None:
    """The human puts n cards of their own deck on their discard pile (the table state a pile request waits for)."""
    st = game.players[session.human]
    have = {c.card_id for c in st.discard} | set(table.human_discard)
    ids = [c.card_id for c in st.full_set if c.card_id not in have][:n]
    table.human_discard += ids


def prepare_answer(session, table, game) -> dict:
    """What the human does on the table for the pause the panel waits at, and the button that answers it: a pile request that
    needs a card gets one laid on the pile; a fighter they must place (The Winds of Watoomb puts Doctor Strange in a starting
    space of THEIR choice) is carried by hand to the first legal space."""
    req = session._paused()[2].awaiting
    if req.kind == "cards" and req.extra.get("table_discard") and req.extra.get("pile_mode") == "reveal":
        lay_on_pile(session, table, game, 1)
    if req.kind == "space" and req.player == session.human and req.min == 1 and req.options:
        table.positions[session.cfg.nicknames[req.extra["fighter"]]] = req.options[0]
    return {"i": 2 if req.kind == "space" and req.min == 0 else 1}


def answer_pause(session, table, game) -> list[str]:
    """One press for the pause the panel waits at."""
    return click(session, table, Event.CHOICE, prepare_answer(session, table, game))


def strange_step(session, table, game) -> list[str]:
    """`human_step` of the TMNT matrix with `answer_pause` for the pauses that need the table."""
    settle_owed_discard(session, table, game)
    if session._paused() is not None:
        return answer_pause(session, table, game)
    return human_step(session, table, game)


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
                said += strange_step(session, table, game)
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


class StrangeAttackDriver(AttackDriver):
    """The attacking driver of the TMNT matrix, with `answer_pause` for the pauses that need the table."""

    def press(self, event, payload=None):
        for _ in range(30):
            if event == Event.CHOICE or self.session._paused() is None:
                break
            super().press(Event.CHOICE, self._answer())
        return super(AttackDriver, self).press(event, payload)

    def _answer(self) -> dict:
        return prepare_answer(self.session, self.table, self.game)

    def choices(self, limit=30):
        n = 0
        while self.session.effect_run is not None and n < limit:
            super(AttackDriver, self).press(Event.CHOICE, self._answer())
            n += 1


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_a_game_where_the_human_attacks_every_turn_reaches_game_over(tmp_path, bot, human):
    """The human walks up to the bot's hero and attacks with a card of their own deck each turn (Doctor Strange's cards are
    resolved against his deck, never Medusa's or a turtle's, whichever seat he sits in)."""
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
