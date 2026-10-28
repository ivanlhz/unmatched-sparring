from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from .board import Board
from .cards import Card, load_hellboy_deck, load_medusa_deck
from .controller import Controller

HAND_LIMIT = 7
START_HAND = 5
EXHAUST_DAMAGE = 2
DETECTIVE = "OCCULT DETECTIVE"
ANUNG = "ANUNG UN RAMA"
ANUNG_THRESHOLD = 6


class RuleError(Exception):
    pass


@dataclass
class Fighter:
    fid: str
    name: str
    owner: int
    hero: bool
    hp: float
    max_hp: int
    move: int
    ranged: bool
    pos: int | None = None
    alive: bool = True
    died_at: int | None = None     # casilla donde cayo: un error de PV se deshace devolviendola ahi


@dataclass
class PlayerState:
    hero_name: str
    deck: list[Card]
    full_set: list[Card]
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)


class Game:
    def __init__(self, board: Board, fighters: list[Fighter], players: list[PlayerState], rng: random.Random,
                 controllers: dict[int, Controller] | None = None, first: int = 0,
                 start_spaces: dict[int, int] | None = None):
        self.board = board
        self.fighters = {f.fid: f for f in fighters}
        self.players = players
        self.rng = rng
        self.controllers = controllers or {}
        self.start_spaces = start_spaces or {}
        self.turn = first
        self.turn_no = 1
        self.actions_left = 2
        self.winner: int | None = None
        self.effect_shield: dict[int, int] = {}
        self.drawn = [0, 0]
        self.phantom_draws = 0   # robos esperados por la IA al simular (cartas desconocidas), nunca en partida real
        self.log: list[str] = []

    @classmethod
    def new(cls, board: Board, seed: int, controllers: dict[int, Controller] | None = None,
            medusa_player: int = 0, starts: tuple[str, str] = ("1", "2")) -> "Game":
        rng = random.Random(seed)
        hb = 1 - medusa_player
        players: list[PlayerState | None] = [None, None]
        players[medusa_player] = PlayerState("Medusa", [], load_medusa_deck())
        players[hb] = PlayerState("Hellboy", [], load_hellboy_deck())
        specs = {
            medusa_player: [("medusa", "Medusa", True, 16, 3, True)]
            + [(f"harpy{i}", "Harpy", False, 1, 3, False) for i in (1, 2, 3)],
            hb: [("hellboy", "Hellboy", True, 18, 2, False), ("lobster", "Lobster Johnson", False, 6, 2, True)],
        }
        start_spaces = {medusa_player: board.starts[starts[0]], hb: board.starts[starts[1]]}
        fighters, taken = [], set()
        for owner, lst in specs.items():
            for fid, name, hero, hp, mv, ranged in lst:
                pos = board.nearest_free(start_spaces[owner], taken, zone_of=start_spaces[owner])
                taken.add(pos)
                fighters.append(Fighter(fid, name, owner, hero, hp, hp, mv, ranged, pos))
        for p in players:
            p.deck = list(p.full_set)
            rng.shuffle(p.deck)
        game = cls(board, fighters, players, rng, controllers, first=rng.randrange(2), start_spaces=start_spaces)
        for pl in (0, 1):
            game.draw(pl, START_HAND, log=False)
        game.drawn = [0, 0]
        return game

    def clone(self) -> "Game":
        g = Game.__new__(Game)
        g.board, g.rng, g.controllers, g.start_spaces = self.board, self.rng, self.controllers, self.start_spaces
        g.fighters = {k: replace(f) for k, f in self.fighters.items()}
        g.players = [PlayerState(p.hero_name, list(p.deck), p.full_set, list(p.hand), list(p.discard))
                     for p in self.players]
        g.turn, g.turn_no, g.actions_left, g.winner = self.turn, self.turn_no, self.actions_left, self.winner
        g.effect_shield = dict(self.effect_shield)
        g.drawn = [0, 0]
        g.phantom_draws = self.phantom_draws
        g.log = []
        return g

    # consultas
    def own(self, player: int, alive_only: bool = True) -> list[Fighter]:
        return [f for f in self.fighters.values() if f.owner == player and (f.alive or not alive_only)]

    def foes(self, player: int) -> list[Fighter]:
        return self.own(1 - player)

    def hero(self, player: int) -> Fighter:
        return next(f for f in self.fighters.values() if f.owner == player and f.hero)

    def hero_named(self, name: str) -> Fighter:
        return next(f for f in self.fighters.values() if f.hero and f.name == name)

    def occupied(self, player: int) -> set[int]:
        return {f.pos for f in self.own(player)}

    def zone_mates(self, fighter: Fighter) -> list[Fighter]:
        return [f for f in self.fighters.values()
                if f.alive and f is not fighter and self.board.share_zone(fighter.pos, f.pos)]

    def destiny_count(self, player: int) -> int:
        return sum(1 for c in self.players[player].discard if c.destiny)

    def form(self, player: int) -> str | None:
        if self.players[player].hero_name != "Hellboy":
            return None
        return ANUNG if self.destiny_count(player) >= ANUNG_THRESHOLD else DETECTIVE

    def legal_moves(self, fighter: Fighter, steps: int, through_enemies: bool = False) -> set[int]:
        return self.board.reachable(fighter.pos, steps, self.occupied(fighter.owner) - {fighter.pos},
                                    self.occupied(1 - fighter.owner), through_enemies)

    def can_attack(self, attacker: Fighter, target: Fighter) -> bool:
        return (attacker.alive and target.alive and attacker.owner != target.owner
                and self.board.can_reach_target(attacker.pos, target.pos, attacker.ranged))

    # mutaciones
    def move_fighter(self, fighter: Fighter, dest: int, steps: int, through_enemies: bool = False) -> None:
        if dest == fighter.pos:
            return
        if dest not in self.legal_moves(fighter, steps, through_enemies):
            raise RuleError(f"{fighter.fid}: movimiento ilegal a {dest} (max {steps})")
        fighter.pos = dest

    def damage(self, fighter: Fighter, n: float, source: str = "effect") -> float:
        if not fighter.alive or n <= 0:
            return 0
        if source == "effect" and self.effect_shield.get(fighter.owner) == self.turn_no:
            self.log.append(f"{fighter.fid}: dano de efecto evitado")
            return 0
        fighter.hp -= n
        self.log.append(f"{fighter.fid} -{n} ({fighter.hp:g} pv)")
        if fighter.hp <= 0:
            fighter.died_at = fighter.pos if fighter.pos is not None else fighter.died_at
            fighter.alive, fighter.pos = False, None
            if fighter.hero:
                self.winner = 1 - fighter.owner
        return n

    def heal(self, fighter: Fighter, n: int) -> None:
        if fighter.alive:
            fighter.hp = min(fighter.max_hp, fighter.hp + n)

    def draw(self, player: int, n: int = 1, log: bool = True) -> list[Card]:
        p, drawn = self.players[player], []
        for _ in range(n):
            if not p.deck:
                for f in self.own(player):
                    self.damage(f, EXHAUST_DAMAGE, "exhaustion")
                continue
            card = p.deck.pop(0)
            p.hand.append(card)
            drawn.append(card)
            self.drawn[player] += 1
        if log and drawn:
            self.log.append(f"P{player} roba {len(drawn)}")
        return drawn

    def discard_card(self, player: int, card: Card) -> None:
        p = self.players[player]
        p.hand.remove(card)
        p.discard.append(card)

    def force_discard(self, player: int, n: int, reason: str) -> list[Card]:
        hand = self.players[player].hand
        n = min(n, len(hand))
        if not n:
            return []
        chosen = self.controllers[player].choose_discard(self, player, n, reason)[:n]
        for c in chosen:
            self.discard_card(player, c)
        return chosen

    def grant_actions(self, n: int) -> None:
        self.actions_left += n

    # turno
    def begin_turn(self) -> None:
        self.actions_left = 2

    def use_action(self) -> None:
        if self.actions_left <= 0:
            raise RuleError("sin acciones")
        self.actions_left -= 1

    def end_turn(self) -> None:
        hand = self.players[self.turn].hand
        if len(hand) > HAND_LIMIT:
            self.force_discard(self.turn, len(hand) - HAND_LIMIT, "limite de mano")
        self.turn = 1 - self.turn
        self.turn_no += 1

    # acciones
    def maneuver(self, player: int, moves: dict[str, int], boost_card: Card | None = None) -> None:
        self.use_action()
        alive0 = {fid for fid, f in self.fighters.items() if f.alive}
        self.draw(player)    # el agotamiento puede matar luchadores (y acabar la partida) antes de moverlos
        if self.winner is not None:
            return
        moves = {fid: d for fid, d in moves.items() if fid not in alive0 or self.fighters[fid].alive}
        extra = 0
        if boost_card is not None:
            extra = boost_card.boost
            self.discard_card(player, boost_card)
        for fid, dest in moves.items():
            f = self.fighters[fid]
            if f.owner != player or not f.alive:
                raise RuleError(f"{fid} no puede moverse")
            self.move_fighter(f, dest, f.move + extra)

    def play_scheme(self, player: int, fighter: Fighter, card: Card, **opts) -> None:
        from .combat import check_scheme, resolve_scheme
        if not card.is_scheme or not card.usable_by(fighter.name) or card not in self.players[player].hand:
            raise RuleError(f"{card.title} no se puede jugar con {fighter.fid}")
        check_scheme(self, fighter, card, **opts)
        self.use_action()
        self.discard_card(player, card)
        resolve_scheme(self, player, fighter, card, **opts)

    @staticmethod
    def check_attack_card(fighter: Fighter, card: Card) -> None:
        if not card.can_attack:
            raise RuleError(f"{card.title} es de tipo {card.type}: no sirve para atacar")
        if not card.usable_by(fighter.name):
            raise RuleError(f"{card.title} es de {card.fighter}: {fighter.name} no la puede jugar")

    @staticmethod
    def check_defense_card(fighter: Fighter, card: Card) -> None:
        if not card.can_defend:
            raise RuleError(f"{card.title} es de tipo {card.type}: no sirve para defender")
        if not card.usable_by(fighter.name):
            raise RuleError(f"{card.title} es de {card.fighter}: {fighter.name} no la puede jugar")

    def attack(self, attacker: Fighter, target: Fighter, card: Card, def_card="ask",
               values: tuple[int, int] = (0, 0), boost: Card | None = None):
        """Transaccional: valida alcance y las dos cartas antes de gastar la accion."""
        from .combat import resolve_combat
        if not self.can_attack(attacker, target):
            raise RuleError(f"{attacker.fid} no alcanza a {target.fid}")
        self.check_attack_card(attacker, card)
        if card not in self.players[attacker.owner].hand:
            raise RuleError(f"{card.title} no esta en la mano de {attacker.fid}")
        if def_card not in ("ask", None):
            self.check_defense_card(target, def_card)
            if def_card not in self.players[target.owner].hand:
                raise RuleError(f"{def_card.title} no esta en la mano de {target.fid}")
        self.use_action()
        if def_card == "ask":
            def_card = self.controllers[target.owner].choose_defense(self, attacker, target)
        return resolve_combat(self, attacker, target, card, def_card, values, boost)

    # habilidades de inicio de turno
    def medusa_ability(self, target: Fighter) -> None:
        medusa = self.hero_named("Medusa")
        if target.owner == medusa.owner or not target.alive or not self.board.share_zone(medusa.pos, target.pos):
            raise RuleError("objetivo invalido para la habilidad")
        self.damage(target, 1)

    def hellboy_anung_start(self, player: int, card: Card, dest: int | None) -> None:
        self.discard_card(player, card)
        if dest is not None:
            self.move_fighter(self.hero_named("Hellboy"), dest, card.boost)

    def hellboy_detective_draw(self, player: int) -> bool:
        hb = self.hero_named("Hellboy")
        if self.form(player) == DETECTIVE and hb.pos == self.start_spaces[1 - player]:
            self.draw(player, 2)
            return True
        return False
