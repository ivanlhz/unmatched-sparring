from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from .board import Board
from .cards import Card, can_be_boost
from .controller import Controller
from .heroes import HeroDef, load_hero

HAND_LIMIT = 7
START_HAND = 5
EXHAUST_DAMAGE = 2
DETECTIVE = "OCCULT DETECTIVE"      # nombres de las formas de Hellboy tal y como estan en data/heroes/hellboy.json
ANUNG = "ANUNG UN RAMA"             # (los anuncios de la sesion los usan; la regla vive en los datos)
DEFAULT_HEROES = ("medusa", "hellboy")     # (heroe del bot, heroe del humano)


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
class KnownHand:
    """Lo que un jugador sabe de la mano RIVAL por haberla visto con un efecto de «mira la mano del rival».

    Solo entran cartas vistas legitimamente (`observe`), nunca la mano real del humano. Cada carta vista se
    descuenta (`forget`) cuando sale de la mano rival por cualquier via: jugada en combate, descartada, perdida.
    `Game.card_left_hand` es el unico punto por el que se descuenta, asi una carta vista que ya salio nunca se da
    por jugable. La busqueda (F09) muestrea la mano oculta con `Game.hidden_hand`: las conocidas fijas y el resto
    sacado del multiconjunto de cartas que no se han visto en ninguna pila publica."""
    seen: list[int] = field(default_factory=list)   # CardID de las cartas vistas que siguen en la mano rival
    turn_no: int | None = None                      # turno en que se miro (la informacion envejece)

    def observe(self, cards: list[Card], turn_no: int) -> None:
        """Sustituye lo sabido: una mirada nueva es la foto completa de la mano en ese momento."""
        self.seen = [c.card_id for c in cards]
        self.turn_no = turn_no if self.seen else None

    def add(self, card: Card, turn_no: int) -> None:
        """Una carta concreta ha entrado a la vista en la mano rival (Wildfire: la ardiente descartada vuelve)."""
        self.seen.append(card.card_id)
        if self.turn_no is None:
            self.turn_no = turn_no

    def forget(self, card: Card) -> bool:
        """Descuenta UNA copia de esa carta (dos Second Shot vistas, una jugada: queda una). True si se sabia."""
        try:
            self.seen.remove(card.card_id)
        except ValueError:
            return False
        if not self.seen:
            self.turn_no = None
        return True

    def clear(self) -> None:
        self.seen, self.turn_no = [], None

    def cards(self, rival: "PlayerState") -> list[Card]:
        """Lo visto que aun PUEDE estar en la mano rival. Se defiende de las vias que mueven cartas sin avisar
        (reconciliacion con la mesa, adopcion): fuera lo que ya esta en su descarte o ha salido del motor."""
        by_id = {c.card_id: c for c in rival.full_set}
        out = []
        for i in self.seen:
            c = by_id.get(i)
            if c is not None and c not in rival.discard and (c in rival.hand or c in rival.deck):
                out.append(c)
        return out

    def copy(self) -> "KnownHand":
        return KnownHand(list(self.seen), self.turn_no)


@dataclass
class PlayerState:
    hero: HeroDef
    deck: list[Card]
    full_set: list[Card]
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    known: KnownHand = field(default_factory=KnownHand)   # lo que ESTE jugador sabe de la mano del rival

    @property
    def hero_name(self) -> str:
        return self.hero.name


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
        self.bot_player: int | None = None     # quien lleva el bot: sus efectos aun no codificados no los resuelve el humano
        self.effect_shield: dict[int, int] = {}
        # ONGOING de planes (Fight Or Flight): (bono, etiqueta) vivos de cada jugador, a TODAS sus cartas de combate
        self.combat_bonus: list[list[tuple[int, str]]] = [[], []]
        self.drawn = [0, 0]
        self.phantom_draws = 0   # robos esperados por la IA al simular (cartas desconocidas), nunca en partida real
        self.log: list[str] = []

    @classmethod
    def new(cls, board: Board, seed: int, controllers: dict[int, Controller] | None = None,
            bot_player: int = 0, starts: tuple[str, str] = ("1", "2"),
            heroes: tuple[str, str] = DEFAULT_HEROES) -> "Game":
        """`heroes`: (slug del heroe de `bot_player`, slug del otro); cada uno sale de data/heroes/<slug>.json.
        `starts`: casilla de salida del mapa de cada uno, en ese mismo orden."""
        rng = random.Random(seed)
        other = 1 - bot_player
        defs = {bot_player: load_hero(heroes[0]), other: load_hero(heroes[1])}
        if defs[bot_player].fid == defs[other].fid:
            raise RuleError(f"los dos jugadores no pueden llevar al mismo heroe ({heroes[0]})")
        players: list[PlayerState | None] = [None, None]
        for owner, h in defs.items():
            players[owner] = PlayerState(h, [], h.deck())
        start_spaces = {bot_player: board.starts[starts[0]], other: board.starts[starts[1]]}
        fighters, taken = [], set()
        for owner in (bot_player, other):
            for spec in defs[owner].fighters():
                if not spec.on_board:       # empieza en reserva: fuera del tablero hasta que un efecto lo invoque
                    fighters.append(Fighter(spec.fid, spec.name, owner, spec.hero, spec.hp, spec.hp, spec.move,
                                            spec.ranged, None, alive=False))
                    continue
                pos = board.nearest_free(start_spaces[owner], taken, zone_of=start_spaces[owner])
                taken.add(pos)
                fighters.append(Fighter(spec.fid, spec.name, owner, spec.hero, spec.hp, spec.hp, spec.move,
                                        spec.ranged, pos))
        for p in players:
            p.deck = list(p.full_set)
            rng.shuffle(p.deck)
        game = cls(board, fighters, players, rng, controllers, first=rng.randrange(2), start_spaces=start_spaces)
        game.bot_player = bot_player
        for pl in (0, 1):
            game.draw(pl, START_HAND, log=False)
        game.drawn = [0, 0]
        return game

    def clone(self) -> "Game":
        g = Game.__new__(Game)
        g.board, g.rng, g.controllers, g.start_spaces = self.board, self.rng, self.controllers, self.start_spaces
        g.fighters = {k: replace(f) for k, f in self.fighters.items()}
        g.players = [PlayerState(p.hero, list(p.deck), p.full_set, list(p.hand), list(p.discard), p.known.copy())
                     for p in self.players]
        g.turn, g.turn_no, g.actions_left, g.winner = self.turn, self.turn_no, self.actions_left, self.winner
        g.bot_player = self.bot_player
        g.effect_shield = dict(self.effect_shield)
        g.combat_bonus = [list(b) for b in self.combat_bonus]
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

    def hero_def(self, player: int) -> HeroDef:
        return self.players[player].hero

    def occupied(self, player: int) -> set[int]:
        return {f.pos for f in self.own(player)}

    def zone_mates(self, fighter: Fighter) -> list[Fighter]:
        return [f for f in self.fighters.values()
                if f.alive and f is not fighter and self.board.share_zone(fighter.pos, f.pos)]

    def counter(self, player: int, name: str) -> int:
        """Contador del heroe (Hellboy: destinos): cartas con su etiqueta en su pila."""
        c = self.players[player].hero.counters[name]
        pile = self.players[player].discard if c.pile == "discard" else []
        return sum(1 for card in pile if c.tag in card.tags)

    def counters(self, player: int) -> dict[str, int]:
        return {name: self.counter(player, name) for name in self.players[player].hero.counters}

    def destiny_count(self, player: int) -> int:
        return self.counter(player, "destiny") if "destiny" in self.players[player].hero.counters else 0

    def form(self, player: int) -> str | None:
        forms = self.players[player].hero.forms
        if forms is None:
            return None
        return forms.of(self.counter(player, forms.counter))

    def triggers(self, player: int, when: str) -> list[dict]:
        """Disparadores del heroe activos ahora: los de ese momento cuya forma (si la exigen) es la actual."""
        form = self.form(player)
        return [t for t in self.players[player].hero.triggers
                if t.get("when") == when and t.get("form", form) == form]

    def attack_bonus_parts(self, fighter: Fighter) -> list[tuple[int, str]]:
        """(bono, etiqueta) de cada pasiva de ataque activa del heroe (Hellboy en ANUNG UN RAMA: (2, 'ANUNG UN RAMA'))."""
        return (self.players[fighter.owner].hero.attack_bonuses(self.form(fighter.owner), fighter.hero)
                + self.combat_bonus_parts(fighter.owner))

    def add_combat_bonus(self, player: int, n: int, label: str) -> str | None:
        """A scheme with ONGOING "add n to the value of your combat cards" enters play. Ivan's ruling (28/10): only one
        active ONGOING per player, the new one replaces the old. Returns the label of the replaced one (or None)."""
        old = self.combat_bonus[player][-1][1] if self.combat_bonus[player] else None
        self.combat_bonus[player] = [(n, label)]
        return old

    def combat_bonus_parts(self, player: int) -> list[tuple[int, str]]:
        """(bonus, label) of `player`'s live ONGOING (at most one)."""
        return list(self.combat_bonus[player])

    def combat_bonus_total(self, player: int) -> int:
        return sum(n for n, _ in self.combat_bonus[player])

    def attack_bonus(self, fighter: Fighter) -> int:
        """Bono del PROXIMO ataque de `fighter` (lo usa la IA para medir amenazas). El ONGOING de un plan caduca al
        empezar el turno de su dueno: si ahora no es su turno, ese bono ya no llega a su siguiente ataque."""
        passives = self.players[fighter.owner].hero.attack_bonus(self.form(fighter.owner), fighter.hero)
        return passives + (self.combat_bonus_total(fighter.owner) if self.turn == fighter.owner else 0)

    def legal_moves(self, fighter: Fighter, steps: int, through_enemies: bool = False) -> set[int]:
        return self.board.reachable(fighter.pos, steps, self.occupied(fighter.owner) - {fighter.pos},
                                    self.occupied(1 - fighter.owner), through_enemies)

    def can_attack(self, attacker: Fighter, target: Fighter) -> bool:
        return (attacker.alive and target.alive and attacker.owner != target.owner
                and self.board.can_reach_target(attacker.pos, target.pos, attacker.ranged))

    # mano conocida del rival (efecto «mira la mano»): ver KnownHand
    def observe_hand(self, viewer: int, cards: list[Card]) -> None:
        """`viewer` acaba de ver la mano completa de su rival por un efecto de carta."""
        self.players[viewer].known.observe(cards, self.turn_no)

    def card_left_hand(self, owner: int, card: Card) -> None:
        """Una carta ha salido de la mano de `owner` (jugada, descartada, perdida): su rival deja de contar con ella."""
        self.players[1 - owner].known.forget(card)

    def hidden_hand(self, viewer: int, hand_size: int | None = None) -> tuple[list[Card], list[Card], int]:
        """Para muestrear la mano del rival de `viewer` sin trampas: (cartas conocidas, multiconjunto de candidatas
        para el resto, cuantas faltan por sortear). Las candidatas son las cartas del rival que no estan en ninguna
        pila publica (descarte) ni entre las conocidas; el mazo y la mano son indistinguibles desde fuera."""
        rival = self.players[1 - viewer]
        known = self.players[viewer].known.cards(rival)
        size = len(rival.hand) if hand_size is None else hand_size
        pool = list(rival.full_set)
        for c in (*rival.discard, *known):
            if c in pool:
                pool.remove(c)
        return list(known), pool, max(0, size - len(known))

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

    def take_from_hand(self, player: int, card: Card) -> None:
        """Saca la carta de la mano para jugarla (combate); va al descarte cuando el combate termina."""
        self.players[player].hand.remove(card)
        self.card_left_hand(player, card)

    def discard_card(self, player: int, card: Card) -> None:
        self.take_from_hand(player, card)
        self.players[player].discard.append(card)

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
    def begin_turn(self) -> list[tuple[int, str]]:
        """Empieza el turno de `self.turn`: 2 acciones y caducan sus planes ONGOING. Devuelve lo que caduco."""
        self.actions_left = 2
        expired, self.combat_bonus[self.turn] = self.combat_bonus_parts(self.turn), []
        return expired

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
            if not can_be_boost(boost_card):
                raise RuleError(f"{boost_card.title} no tiene valor de impulso")
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

    # habilidades de inicio de turno (hasta el paso 8 del plan siguen cableadas por heroe)
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
        """Robo de inicio de turno en la salida rival: el disparador `draw` activo en la forma actual (Hellboy en
        OCCULT DETECTIVE: 2 cartas) con la condicion `hero_on_rival_start`; cuantas, lo dicen los datos."""
        hero = self.hero(player)
        for t in self.triggers(player, "start_of_turn"):
            if t.get("effect") != "draw" or t.get("condition") != "hero_on_rival_start":
                continue
            if hero.alive and hero.pos == self.start_spaces[1 - player]:
                self.draw(player, int(t["n"]))
                return True
        return False
