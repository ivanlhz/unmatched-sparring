"""The pairing matrix: every ordered pair (bot hero, human hero) of the nine heroes, played to game over on FakeTTS and in
the simulator.

Medusa and the four turtles all have CardIDs 17600-17629 (DeckID 176 of the tournament save): the table tells their cards
apart by deck image and seat, the engine by (owner, CardID) (docs/card-identity.md). The matrix is what proves it: Medusa
against each turtle and a turtle against another turtle, in both seats, through the real session on the fake table.

The human is a scripted player at the panel (maneuvers, answers every pause with the first button, never defends); the bot
plays with its real heuristic AI. Both heroes start worn down (HERO_HP) so that a game ends in a few dozen steps."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_michelangelo_games import Driver

HEROES = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael"]
TURTLES = ["leonardo", "donatello", "michelangelo", "raphael"]
PAIRS = [(b, h) for b in HEROES for h in HEROES if b != h]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]
MAX_STEPS = 900
HERO_HP = 5


def settle_owed_discard(session, table, game) -> None:
    """The human puts on the table pile the cards they owe (a price they paid, the hand limit)."""
    owed = session.pending_discard
    if owed is None:
        return
    hand = [c.card_id for c in game.players[session.human].hand]
    named = list(owed.get("cards") or [])
    extra = max(0, len(hand) - game.hand_cap(session.human)) if owed["kind"] == "limit" else owed["n"] - len(named)
    ids = named + [i for i in hand if i not in named][:extra]
    table.human_discard += [i for i in ids if i not in table.human_discard]
    table.human_count = max(0, table.human_count - len([i for i in ids if i not in named]))
    session.snap = None


def place_by_hand(session, table) -> None:
    """The human moves the miniature a mandatory placement asks for (Strange's "Your opponent places Dr. Strange in a starting
    space") to the first allowed space, the way a real player does before pressing Done."""
    from sparring.session_moves import manual_request
    req = manual_request(session)
    if req is not None and req.min > 0:
        table.positions[session.cfg.nicknames[req.extra["fighter"]]] = req.options[0]


def human_step(session, table, game) -> list[str]:
    """One click of the scripted human."""
    settle_owed_discard(session, table, game)
    place_by_hand(session, table)
    if session._paused() is not None:
        return click(session, table, Event.CHOICE, {"i": 1})
    if session.pending is not None:
        return click(session, table, Event.REVEAL)
    if session.ability_wait is not None or session.moving or game.actions_left <= 0:
        return click(session, table, Event.END_ACTION)
    msgs = click(session, table, Event.MANEUVER)
    return msgs + click(session, table, Event.END_ACTION)


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


def test_the_matrix_covers_medusa_against_each_turtle_and_turtle_against_turtle_in_both_seats():
    for a in TURTLES:
        assert ("medusa", a) in PAIRS and (a, "medusa") in PAIRS
        for b in TURTLES:
            assert a == b or (a, b) in PAIRS



@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_headless_games_with_the_heuristic_and_the_search_ai(bot, human):
    from sparring import sim
    assert sim.play(1, bot_hero=bot, human_hero=human).winner != "draw"
    ai = sim.make_bot("ismcts", iterations=4, seed=1)
    out = sim.play(1, bot_hero=bot, human_hero=human, medusa=ai, max_turns=25)
    assert out.turns >= 1 and ai.fallbacks == 0



class AttackDriver(Driver):
    """The Michelangelo game driver, on the pieces-aside table, with two additions of the matrix: whatever decision the panel
    waits for (a pause parked by an effect, a Perfect Shot prediction) is answered with a button before the next action;
    and when an attack is not possible (Pact Of Freedom as the first action, the bot's hero walled in by its own pieces:
    Medusa's Harpies) the human maneuvers instead."""

    def press(self, event, payload=None):
        for _ in range(30):
            if event == Event.CHOICE or self.session._paused() is None:
                break
            req = self.session._paused()[2].awaiting
            place_by_hand(self.session, self.table)
            super().press(Event.CHOICE, {"i": 2 if req.kind == "space" and req.min == 0 else 1})   # "No mover": no piece by hand
        place_by_hand(self.session, self.table)
        return super().press(event, payload)

    def human_turn(self):
        g, bot_hero, me = self.game, self.game.hero(0), self.game.hero(1)
        for _ in range(6):
            if g.turn != 1 or g.winner is not None:
                return
            if not g.fx.may_attack(1):                           # Pact Of Freedom: not as the first action of the turn
                self.press(Event.MANEUVER)
                self.end_action()
                continue
            free = next((s for s in sorted(g.board.adj[bot_hero.pos])
                         if all(f.pos != s for f in g.fighters.values() if f.alive)), None)
            if free is not None and not g.can_attack(me, bot_hero):
                self.table.positions[self.cfg.nicknames[me.fid]] = free
            elif not g.can_attack(me, bot_hero):
                self.press(Event.MANEUVER)
                self.end_action()
                continue
            self.press(Event.ATTACKER, {"attacker": f"att_{me.fid}"})
            self.press(Event.ATTACK, {"target": bot_hero.fid})
            if self.session.pending is not None:
                card = self.attack_card()
                self.table.face_down = [{"id": card.card_id, "guid": f"h{card.card_id}"}]
                self.table.human_count -= 1
                self.press(Event.REVEAL)
                if self.session.pending is not None and g.turn == 1:
                    self.press(Event.NO_BOOST)                  # Turtle Power!! offers its free BOOST
                self.choices()
            if g.winner is not None:
                return
            self.end_action()


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
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
