"""Scripted Hellboy for the simulation: chases, attacks with his best card, defends at random.
He plays no schemes and resolves no text effects (the human does that live)."""
from __future__ import annotations

import random

from . import enraged
from .cards import can_be_boost
from .controller import Controller
from .state import ANUNG, Fighter, Game

DEFEND_PROB = 0.6
BOOST_PROB = 0.5


class ScriptedHellboy(Controller):
    def __init__(self, me: int = 1, seed: int = 0):
        self.me = me
        self.rng = random.Random(seed)

    def take_turn(self, game: Game) -> None:
        self.start_of_turn(game)
        while game.actions_left > 0 and game.winner is None:
            if not self.try_attack(game):
                self.maneuver(game)

    def start_of_turn(self, game: Game) -> None:
        hand = game.players[self.me].hand
        if game.form(self.me) == ANUNG and hand:
            card = max(hand, key=lambda c: (c.boost, -c.card_id))
            hb = game.hero_named("Hellboy")
            dest = self.closer(game, hb, game.legal_moves(hb, card.boost))
            game.hellboy_anung_start(self.me, card, dest)
        else:
            game.hellboy_detective_draw(self.me)

    def try_attack(self, game: Game) -> bool:
        hand = game.players[self.me].hand
        for f in sorted(game.own(self.me), key=lambda x: not x.hero):
            targets = [t for t in game.foes(self.me) if game.can_declare_attack(f, t)]
            if not targets:
                continue
            target = min(targets, key=lambda t: (not t.hero, t.hp))
            cards = [c for c in hand if enraged.may_attack_with(game, self.me, c) and c.usable_by(f.name)
                     and game.attack_card_reaches(f, target, c)]          # an adjacent-only card or a far target needs the right card
            if cards:
                card = max(cards, key=lambda c: (c.value, -c.card_id))
                game.attack(f, target, card)
                return True
        return False

    def maneuver(self, game: Game) -> None:
        hand = [c for c in game.players[self.me].hand if can_be_boost(c)]
        boost = None
        if hand and self.rng.random() < BOOST_PROB:
            boost = max(hand, key=lambda c: (c.boost, -c.card_id))
        extra = boost.boost if boost else 0
        moves = {}
        taken = set()
        for f in game.own(self.me):
            options = {d for d in game.legal_moves(f, f.move + extra) if d not in taken}
            dest = self.closer(game, f, options)
            if dest is not None:
                moves[f.fid] = dest
                taken.add(dest)
        game.maneuver(self.me, moves, boost)

    def closer(self, game: Game, f: Fighter, options) -> int | None:
        foes = game.foes(self.me)
        if not foes or not options:
            return None
        score = lambda d: (min(game.board.distance(d, e.pos) for e in foes), d)
        best = min(options, key=score)
        return best if score(best)[0] < min(game.board.distance(f.pos, e.pos) for e in foes) else None

    def choose_defense(self, game: Game, attacker: Fighter, target: Fighter, attack_card=None):
        """`attack_card` (the attack played face up, E3) is ignored: this script defends at random."""
        hand = game.players[self.me].hand
        cards = [c for c in hand if c.can_defend and c.usable_by(target.name)]
        if cards and self.rng.random() < DEFEND_PROB:
            return max(cards, key=lambda c: (c.value or 0, -c.card_id))
        return None

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        hand = game.players[player].hand
        return sorted(hand, key=lambda c: (not c.is_scheme, c.value or 0, c.card_id))[:n]

    def choose_move(self, game: Game, fighter: Fighter, steps: int, through_enemies: bool = False):
        return self.closer(game, fighter, game.legal_moves(fighter, steps, through_enemies))
