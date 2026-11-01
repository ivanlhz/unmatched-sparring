"""Whole games on FakeTTS (batch sessions, the panel's buttons only) with Michelangelo on either side.

Michelangelo (bot) against the four heroes that can share his table, each of them played by a human who only
maneuvers (the bot attacks, draws with PIZZA PARTY and keeps its hand at 3); and each of those heroes as the bot
against Michelangelo as the human, who walks up to the bot's hero and attacks every turn (PIZZA PARTY deals cards to
his seat, the hand limit is 3). Every game must reach "game over" without an illegal action.

Medusa and Michelangelo cannot sit at the same table: the tournament save gives both the CardIDs 17600..17629 and the
bridge refuses ranges that overlap (tests below); they are played against each other in the simulator
(tests/test_bot_any_hero.py)."""
from __future__ import annotations

import pytest

from sparring.play import ConfigError
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, set_hand
from test_hero_detect import at_bot, at_human, detect, reading
from test_multihero_bridge import config_for

OTHERS = ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
MAX_STEPS = 300


class Driver:
    """The human of a FakeTTS game: answers what the panel asks with the first sensible button."""

    def __init__(self, session, table, game, cfg, attacks: bool):
        self.session, self.table, self.game, self.cfg, self.attacks = session, table, game, cfg, attacks
        self.used = 0
        self.deals_seen = 0
        self.log: list[str] = []

    def press(self, event, payload=None):
        msgs = click(self.session, self.table, event, payload)
        self.log += msgs
        return msgs

    def choices(self, limit=30):
        n = 0
        while self.session.effect_run is not None and n < limit:
            req = self.session.effect_run.awaiting
            self.press(Event.CHOICE, {"i": 2 if req.kind == "space" and req.min == 0 else 1})   # "No mover": no piece by hand
            n += 1

    def end_action(self):
        self.press(Event.END_ACTION)
        for _ in range(5):
            owed = self.session.pending_discard
            if not owed:
                break
            ids = [c.card_id for c in self.game.players[1].full_set if c.card_id not in self.table.human_discard][:owed["n"]]
            self.table.human_discard += ids
            self.table.human_count -= owed["n"]
            self.press(Event.END_ACTION)

    def attack_card(self):
        hero = self.game.hero(1)
        cards = [c for c in self.game.players[1].full_set
                 if c.can_attack and c.usable_by(hero.name) and c.value is not None]
        self.used += 1
        return cards[self.used % len(cards)]

    def human_turn(self):
        g, bot_hero, me = self.game, self.game.hero(0), self.game.hero(1)
        for i in range(6):
            if g.turn != 1 or g.winner is not None:
                return
            if self.attacks and i > 0:
                spot = next((s for s in sorted(g.board.adj[bot_hero.pos])
                             if all(f.pos != s for f in g.fighters.values() if f.alive)), None)
                if spot is not None:
                    self.table.positions[self.cfg.nicknames[me.fid]] = spot
                self.press(Event.ATTACKER, {"attacker": f"att_{me.fid}"})
                self.press(Event.ATTACK, {"target": bot_hero.fid})
                if self.session.pending is not None:
                    card = self.attack_card()
                    self.table.face_down = [{"id": card.card_id, "guid": f"h{card.card_id}"}]
                    self.table.human_count -= 1
                    self.press(Event.REVEAL)
                    if self.session.pending is not None and self.game.turn == 1:
                        self.press(Event.NO_BOOST)                  # Turtle Power!! offers its free BOOST
                    self.choices()
            else:
                self.press(Event.MANEUVER)
            if g.winner is not None:
                return
            self.end_action()

    def play_out(self):
        steps = 0
        while self.game.winner is None and steps < MAX_STEPS:
            steps += 1
            if self.game.turn == 1:
                self.human_turn()
            elif self.session.pending_discard:
                owed = self.session.pending_discard
                ids = [c.card_id for c in self.game.players[1].full_set if c.card_id not in self.table.human_discard][:owed["n"]]
                self.table.human_discard += ids
                self.table.human_count -= owed["n"]
                self.press(Event.END_ACTION)
            elif self.session.pending is not None:
                self.table.face_down = []
                self.press(Event.REVEAL)
                self.choices()
            elif self.session.effect_run is not None:
                self.choices()
            else:
                self.press(Event.END_ACTION)
        return steps


def start_game(tmp_path, bot, human, attacks):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, ())
    set_hand(session, table, game, *[c.title for c in game.players[0].deck[:game.start_hand(0)]])
    table.human_count = game.start_hand(1)
    return Driver(session, table, game, cfg, attacks), fake, client


@pytest.mark.parametrize("human", OTHERS)
def test_michelangelo_bot_plays_a_whole_game_against_each_hero(tmp_path, human):
    d, fake, client = start_game(tmp_path, "michelangelo", human, attacks=False)
    try:
        assert len(d.game.players[0].hand) == 3
        steps = d.play_out()
        assert d.game.winner is not None and steps < MAX_STEPS
        assert not [m for m in d.log if "ilegal" in m.lower()]
        assert d.game.winner == 0 and d.game.hero(1).hp <= 0
        assert len(d.game.players[0].hand) <= 3              # the bot never ends a turn with more than 3 cards
        assert any("Michelangelo ataca" in m for m in d.log)
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("bot", OTHERS)
def test_each_hero_as_the_bot_plays_a_whole_game_against_michelangelo_human(tmp_path, bot):
    d, fake, client = start_game(tmp_path, bot, "michelangelo", attacks=True)
    try:
        assert d.table.human_count == 3
        steps = d.play_out()
        assert d.game.winner is not None and steps < MAX_STEPS
        assert not [m for m in d.log if "ilegal" in m.lower()]
        assert d.table.human_count <= 3 or d.game.winner is not None
    finally:
        client.close()
        fake.close()


def test_the_human_michelangelo_is_dealt_the_pizza_party_card_after_attacking(tmp_path):
    d, fake, client = start_game(tmp_path, "hellboy", "michelangelo", attacks=True)
    try:
        d.press(Event.MANEUVER)
        d.end_action()
        spot = next(s for s in sorted(d.game.board.adj[d.game.hero(0).pos])
                    if all(f.pos != s for f in d.game.fighters.values() if f.alive))
        d.table.positions[d.cfg.nicknames["mikey"]] = spot
        d.press(Event.ATTACKER, {"attacker": "att_mikey"})
        d.press(Event.ATTACK, {"target": "hellboy"})
        card = next(c for c in d.game.players[1].full_set if c.title == "Boisterous Beatdown")
        d.table.face_down = [{"id": card.card_id, "guid": f"h{card.card_id}"}]
        d.table.human_count -= 1
        deals = len(d.table.human_deals)
        msgs = d.press(Event.REVEAL)
        assert d.table.human_deals[deals:] == [1], (d.table.human_deals, msgs)
    finally:
        client.close()
        fake.close()


def test_the_human_michelangelo_discards_down_to_3_at_the_end_of_the_turn(tmp_path):
    d, fake, client = start_game(tmp_path, "hellboy", "michelangelo", attacks=False)
    try:
        d.table.human_count = 5
        d.game.players[1].hand[:] = [d.game.players[1].full_set[i] for i in range(5)]
        d.press(Event.MANEUVER)                    # 6 cards now
        msgs = d.press(Event.END_ACTION)
        d.press(Event.MANEUVER)
        msgs = d.press(Event.END_ACTION)
        assert any("hasta tener 3" in m for m in d.log), d.log[-6:]
        assert d.session.pending_discard and d.session.pending_discard["kind"] == "limit" and d.session.pending_discard["n"] == 4
    finally:
        client.close()
        fake.close()


def test_the_bot_michelangelo_is_dealt_3_cards_and_a_mulligan_returns_3(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "michelangelo", "hellboy", ())
    try:
        assert game.start_hand(0) == 3 and game.start_hand(1) == 5
        game.drawn[0] = 0
        game.draw(0, game.start_hand(0), log=False)
        assert game.drawn[0] == 3
    finally:
        client.close()
        fake.close()


def test_medusa_and_michelangelo_are_refused_at_the_table_with_a_clear_message(tmp_path):
    for pair in (("medusa", "michelangelo"), ("michelangelo", "medusa")):
        with pytest.raises(ConfigError, match="CardID ranges"):
            config_for(tmp_path, *pair)


def test_auto_detection_recognises_michelangelo_on_either_side():
    assert detect(reading(at_bot("michelangelo"), at_human("hellboy"))) == ("michelangelo", "hellboy")
    assert detect(reading(at_bot("liz-sherman"), at_human("michelangelo"))) == ("liz-sherman", "michelangelo")


def test_the_deck_identity_of_michelangelo_is_not_medusas():
    from sparring.tts.hero_table import load_hero_table
    assert not set(load_hero_table("michelangelo").identity) & set(load_hero_table("medusa").identity)
