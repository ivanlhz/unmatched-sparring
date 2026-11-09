"""Yennefer & Triss (both variants) against each of the other heroes in both seats: full session games to game over on FakeTTS (a passive
scripted human and a human who attacks every turn) and headless games with the heuristic and the search AI.

The same approach as tests/test_tomoe_gozen_matrix.py (docs/card-identity.md). The hero is ONE deck with TWO variants, each an ordinary
HeroDef over the same deck: `yennefer-triss` (Yennefer is the hero, Triss the sidekick) and `triss-yennefer` (the other way round); the two
never play each other (they are the same deck and the same bag). Their deck is sheet 176 like Medusa's and the other ten: the matrix is the
proof that the decks are told apart by image and owner. Their dials are four Custom_Models told apart by name and by their top value
(14 for the hero, 6 for the sidekick). Sorceress of Vengerberg (a free BOOST of Yennefer's attack), Merigold the Fearless (2 damage after
Triss's scheme) and Lodge of sorceresses run in these games."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_d3_table_effects import build, set_hand
from test_donatello_session import SPOTS, AsideTable
from sparring.tts.ui import Event as _Event  # noqa: F401
from test_michelangelo_games import Driver
from test_tmnt_matrix import place_by_hand, HERO_HP, MAX_STEPS, AttackDriver, human_step
from test_batch import click as _click  # noqa: F401

VARIANTS = ["yennefer-triss", "triss-yennefer"]
OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "houdini", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]
PAIRS = [(v, h) for v in VARIANTS for h in OTHERS] + [(b, v) for v in VARIANTS for b in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


class PayNothingDriver(AttackDriver):
    """The attacking human of the matrix declines every yes / no (the bot's Incinerate: "discard 2 cards to ignore its value", Telepathy's
    discard): the driver never moves cards to the pile by hand for a price, so paying would leave the discard owed for ever."""

    errors = 0

    def press(self, event, payload=None):
        for _ in range(30):
            if event == Event.CHOICE or self.session._paused() is None:
                break
            req = self.session._paused()[2].awaiting
            place_by_hand(self.session, self.table)
            Driver.press(self, Event.CHOICE, {"i": 2 if self._declines(req) else 1})
        place_by_hand(self.session, self.table)
        msgs = Driver.press(self, event, payload)
        self.errors = self.errors + 1 if any("Error de mesa" in m for m in msgs) else 0
        assert self.errors < 5, f"the table is stuck: {msgs}"          # a stall fails the test at once instead of spinning
        return msgs

    def human_turn(self):
        """AttackDriver's turn, except that with no card left in the hand the human maneuvers (it draws) instead of attacking: this driver
        never draws otherwise, and a game where its attacks do not kill (Incinerate ignored, Echoing blast walled) would spend the
        whole hand and then stall on a table with a negative hand."""
        g, bot_hero, me = self.game, self.game.hero(0), self.game.hero(1)
        for _ in range(6):
            if g.turn != 1 or g.winner is not None:
                return
            free = next((s for s in sorted(g.board.adj[bot_hero.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive)), None)
            if self.table.human_count < 1 or not g.fx.may_attack(1):
                self.press(Event.MANEUVER)
                self.end_action()
                continue
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
                    self.press(Event.NO_BOOST)
                self.choices()
            if g.winner is not None:
                return
            self.end_action()

    @staticmethod
    def _declines(req):
        return req.kind == "space" and req.min == 0 or req.kind == "optional"

    def choices(self, limit=30):
        n = 0
        while self.session.effect_run is not None and n < limit:
            req = self.session.effect_run.awaiting
            self.press(Event.CHOICE, {"i": 2 if self._declines(req) else 1})
            n += 1


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
        d = PayNothingDriver(session, table, game, cfg, attacks=True)
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


def test_the_matrix_has_both_variants_in_both_seats_against_every_other_hero():
    assert len(PAIRS) == 4 * len(OTHERS)
    assert all((v, h) in PAIRS and (h, v) in PAIRS for v in VARIANTS for h in OTHERS)


@pytest.mark.parametrize("bot,human", [("yennefer-triss", "triss-yennefer"), ("triss-yennefer", "yennefer-triss")])
def test_the_two_variants_cannot_face_each_other(bot, human):
    from sparring.state import Game, RuleError
    from sparring.board import Board
    with pytest.raises(RuleError):
        Game.new(Board.load("bprd-hq"), 1, heroes=(bot, human))
