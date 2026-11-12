"""Scripted rivals for the simulation. `ScriptedHellboy`: walks to the nearest piece, attacks with his best card, defends at
random. `ChasingHellboy`: hunts the rival hero and defends like a person. Neither plays schemes."""
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
        extra = (boost.boost if boost else 0) + game.maneuver_bonus(self.me, boost)
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


class ChasingHellboy(ScriptedHellboy):
    """The yardstick a kiting bot has to beat: the scripted rival played the way a person plays a melee chaser. It hunts the
    rival hero with its own: it strikes it when it can, otherwise it walks into reach of it (boosting exactly when the plain
    move does not get there and a boost does, with the cheapest card that does); only then its sidekick shoots, or it settles
    for a sidekick. Its hero is always defended when the hand holds a defense, and its shooter keeps its distance.
    `ScriptedHellboy` walks to the nearest piece, defends 60 % of the time and boosts half its maneuvers at random, so
    stepping out of its plain move wins games there that it loses at the table."""

    def take_turn(self, game: Game) -> None:
        self.start_of_turn(game)
        while game.actions_left > 0 and game.winner is None:
            if self.strike(game, [game.hero(self.me)]):
                continue
            if game.actions_left >= 2 and self.holds_attack(game) and self.maneuver(game, hunting=True):
                continue
            if not self.strike(game, game.own(self.me)) and not self.try_attack(game):
                self.maneuver(game)

    def strike(self, game: Game, fighters) -> bool:
        """The first of `fighters` that can attack the rival hero does, with its best card."""
        prey, hand = game.hero(1 - self.me), game.players[self.me].hand
        for f in fighters:
            cards = [c for c in hand if f.alive and game.can_declare_attack(f, prey) and enraged.may_attack_with(game, self.me, c)
                     and c.usable_by(f.name) and game.attack_card_reaches(f, prey, c)]
            if cards:
                game.attack(f, prey, max(cards, key=lambda c: (c.value, -c.card_id)))
                return True
        return False

    def holds_attack(self, game: Game) -> bool:
        hero = game.hero(self.me)
        return hero.alive and any(c.can_attack and c.usable_by(hero.name) for c in game.players[self.me].hand)

    def maneuver(self, game: Game, hunting: bool = False) -> bool:
        """`hunting`: only the maneuver that ends with my hero in reach of the rival hero (False when none does: nothing is
        spent). Otherwise the plain walk towards it."""
        boost = None
        if hunting:
            boost = self.reach_boost(game)
            if boost is None and not self.reaches(game, game.maneuver_bonus(self.me, None)):
                return False
        extra = (boost.boost if boost else 0) + game.maneuver_bonus(self.me, boost)
        moves, taken = {}, set()
        for f in game.own(self.me):
            options = {d for d in game.legal_moves(f, f.move + extra) if d not in taken}
            dest = self.firing_spot(game, f, options | {f.pos}) if f.ranged else self.strike_spot(game, f, options)
            if dest is not None and dest != f.pos:
                moves[f.fid] = dest
                taken.add(dest)
        game.maneuver(self.me, moves, boost)
        return True

    def strike_spot(self, game: Game, f: Fighter, options) -> int | None:
        """Where `f` can attack the rival hero from, if the move gets there (a space one step away through a secret passage is
        near and still out of reach); else as near as it gets."""
        prey = game.hero(1 - self.me)
        spots = [d for d in options if game.board.can_reach_target(d, prey.pos, f.ranged, f.reach)]
        return min(spots) if spots else self.closer(game, f, options)

    def closer(self, game: Game, f: Fighter, options) -> int | None:
        """Towards the rival hero, not the nearest piece."""
        prey = game.hero(1 - self.me)
        if not options or prey.pos is None:
            return None
        score = lambda d: (game.board.distance(d, prey.pos), d)
        best = min(options, key=score)
        return best if score(best)[0] < game.board.distance(f.pos, prey.pos) else None

    def firing_spot(self, game: Game, f: Fighter, options) -> int | None:
        """A shooter stands where it reaches the rival hero from as far as it can (it does not walk into its arms); with no
        such space it closes in like the rest."""
        board, prey = game.board, game.hero(1 - self.me)
        spots = [d for d in options if board.can_reach_target(d, prey.pos, True, f.reach)]
        if not spots:
            return self.closer(game, f, options - {f.pos})
        return max(spots, key=lambda d: (board.distance(d, prey.pos), -d))

    def reaches(self, game: Game, extra: int) -> bool:
        """My hero ends a maneuver of `extra` more spaces where it can attack the rival hero."""
        f, prey = game.hero(self.me), game.hero(1 - self.me)
        return any(game.board.can_reach_target(d, prey.pos, f.ranged, f.reach) for d in game.legal_moves(f, f.move + extra) | {f.pos})

    def reach_boost(self, game: Game):
        """The card to boost with: none when the plain move already reaches (or no boost does), else the lowest boost that
        does and, among those, the card of least value. The last attack card is never the one spent: it is the blow."""
        if self.reaches(game, game.maneuver_bonus(self.me, None)):
            return None
        hand = game.players[self.me].hand
        attacks = [c for c in hand if c.can_attack]
        cards = sorted((c for c in hand if can_be_boost(c) and (len(attacks) > 1 or c not in attacks)),
                       key=lambda c: (c.boost, c.value or 0, c.card_id))
        return next((c for c in cards if self.reaches(game, c.boost + game.maneuver_bonus(self.me, c))), None)

    def choose_defense(self, game: Game, attacker: Fighter, target: Fighter, attack_card=None):
        """The hero is always defended, with its highest card (a pure defense before a versatile of the same value); a
        sidekick only with a pure defense or from a hand of four or more."""
        hand = game.players[self.me].hand
        cards = [c for c in hand if c.can_defend and c.usable_by(target.name)]
        if not target.hero:
            cards = [c for c in cards if not c.can_attack or len(hand) >= 4]
        return max(cards, key=lambda c: (c.value or 0, not c.can_attack, -c.card_id), default=None)
