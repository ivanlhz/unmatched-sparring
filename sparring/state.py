from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from .board import Board
from .cards import Card, can_be_boost
from .controller import Controller
from .effects import ongoing
from .effects.state import EffectState
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
    """What a player knows about the RIVAL's hand and deck top, learned only through card effects.

    Only legitimately seen cards enter (`observe`, `add`, `set_top`), never the real human hand. Every seen card is
    forgotten (`forget`) when it leaves the rival hand by any route; `Game.card_left_hand` is the single place that
    does it, so a seen card that is gone is never counted as playable. Search (F09) samples the hidden hand with
    `Game.hidden_hand`: the known cards fixed and the rest drawn from the multiset of cards not seen in a public pile.

    Three levels of certainty:
    - `seen`: certainly in the rival hand (looked at, or revealed).
    - `possible` with `possible_lo`..`possible_hi`: cards that were seen but may have left face down (Glimpse Of
      Hell, Pyrotechnics, Pact Of Secrecy); between lo and hi of them are still in the hand. They stay in the
      sampling pool, no longer as certainty.
    - `top_of_deck`: the rival deck's known prefix, top first (Every Possible Angle puts a chosen card on top)."""
    seen: list[int] = field(default_factory=list)       # CardID of the seen cards still in the rival hand
    turn_no: int | None = None                          # turn when it was looked at (information ages)
    possible: list[int] = field(default_factory=list)   # seen cards that may have left face down
    possible_lo: int = 0
    possible_hi: int = 0
    top_of_deck: list[int] = field(default_factory=list)

    def observe(self, cards: list[Card], turn_no: int) -> None:
        """Replaces what was known: a new look is the complete snapshot of the hand at that moment."""
        self.seen = [c.card_id for c in cards]
        self.possible, self.possible_lo, self.possible_hi = [], 0, 0
        self.turn_no = turn_no if self.seen else None

    def add(self, card: Card, turn_no: int) -> None:
        """A concrete card came into view in the rival hand (Wildfire: the burning card returns)."""
        self.seen.append(card.card_id)
        if self.turn_no is None:
            self.turn_no = turn_no

    def forget(self, card: Card) -> bool:
        """Discounts ONE copy of that card (two Second Shot seen, one played: one left). True if it was known."""
        try:
            self.seen.remove(card.card_id)
            found = True
        except ValueError:
            found = False
        if not found and card.card_id in self.possible:     # it was in the hand: one fewer of the possible ones
            self.possible.remove(card.card_id)
            self.possible_lo, self.possible_hi = max(0, self.possible_lo - 1), max(0, self.possible_hi - 1)
            found = True
            self._settle()
        if not self.seen and not self.possible:
            self.turn_no = None
        return found

    def degrade(self, removed: int, hand_after: int) -> None:
        """`removed` cards left the rival hand face down (it now has `hand_after`): which ones is unknown, so
        everything seen becomes "possible" with the count bounds that follow."""
        pool = self.seen + self.possible
        if not pool or removed <= 0:
            return
        certain = len(self.seen) + self.possible_lo
        in_hand_max = len(self.seen) + self.possible_hi
        self.possible = pool
        self.possible_lo = max(0, certain - removed)
        self.possible_hi = max(self.possible_lo, min(len(pool), hand_after, in_hand_max))
        self.seen = []
        self._settle()

    def _settle(self) -> None:
        """Bounds that pin the set down: all of them certainly in (promote), none in (drop)."""
        n = len(self.possible)
        self.possible_hi = min(self.possible_hi, n)
        self.possible_lo = min(self.possible_lo, self.possible_hi)
        if self.possible_hi == 0:
            self.possible, self.possible_lo = [], 0
        elif self.possible_lo == n:
            self.seen, self.possible, self.possible_lo, self.possible_hi = self.seen + self.possible, [], 0, 0

    def clear(self) -> None:
        self.seen, self.turn_no = [], None
        self.possible, self.possible_lo, self.possible_hi = [], 0, 0

    # ---- known deck top
    def set_top(self, ids: list[int]) -> None:
        self.top_of_deck = list(ids)

    def push_top(self, ids: list[int]) -> None:
        """`ids` (top first) were put on top of the deck in plain sight."""
        self.top_of_deck = list(ids) + self.top_of_deck

    def drop_top(self, card_id: int) -> None:
        """A card left the deck by a route that is not a draw: it is no longer part of the known prefix."""
        if card_id in self.top_of_deck:
            self.top_of_deck.remove(card_id)

    def clear_top(self) -> None:
        self.top_of_deck = []

    def drawn(self, card: Card, turn_no: int) -> None:
        """The rival drew `card`; if it was the known top, it is now a seen card in their hand."""
        if self.possible:        # a blind draw may bring back one of them; the identity is not looked at
            self.possible_hi = min(len(self.possible), self.possible_hi + 1)
        if not self.top_of_deck:
            return
        if self.top_of_deck[0] == card.card_id:
            self.top_of_deck.pop(0)
            self.add(card, turn_no)
        else:
            self.top_of_deck = []        # an unknown card was on top: the known prefix cannot be trusted

    def cards(self, rival: "PlayerState") -> list[Card]:
        """The seen cards that can still be in the rival hand. Defends against routes that move cards without
        notice (table reconciliation, adoption): what is already in their discard (public) is out, per copy. It
        never looks at the rival hand or deck."""
        return self._resolve(self.seen, rival)

    def possible_cards(self, rival: "PlayerState") -> list[Card]:
        return self._resolve(self.possible, rival)

    def top(self, rival: "PlayerState") -> list[Card]:
        """The known prefix of the rival deck as cards, top first."""
        by_id = {c.card_id: c for c in rival.full_set}
        return [by_id[i] for i in self.top_of_deck if i in by_id]

    @staticmethod
    def _resolve(ids: list[int], rival: "PlayerState") -> list[Card]:
        by_id = {c.card_id: c for c in rival.full_set}
        public = {c.card_id for c in rival.discard}
        return [by_id[i] for i in ids if i in by_id and i not in public]

    def copy(self) -> "KnownHand":
        return KnownHand(list(self.seen), self.turn_no, list(self.possible), self.possible_lo, self.possible_hi,
                         list(self.top_of_deck))

    def is_empty(self) -> bool:
        return not (self.seen or self.possible or self.top_of_deck)

    def to_dict(self) -> dict:
        """Only what is non-empty, so a game that never looked at a hand saves byte-identical to before."""
        out: dict = {}
        if self.seen:
            out["seen"] = list(self.seen)
        if self.seen or self.possible:
            out["turn_no"] = self.turn_no
        if self.possible:
            out["possible"] = {"ids": list(self.possible), "lo": self.possible_lo, "hi": self.possible_hi}
        if self.top_of_deck:
            out["top"] = list(self.top_of_deck)
        return out

    @classmethod
    def from_dict(cls, raw: dict | None) -> "KnownHand":
        raw = raw or {}
        poss = raw.get("possible") or {}
        return cls([int(i) for i in raw.get("seen", [])], raw.get("turn_no"), [int(i) for i in poss.get("ids", [])],
                   int(poss.get("lo", 0)), int(poss.get("hi", 0)), [int(i) for i in raw.get("top", [])])


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
        self.drawn = [0, 0]
        self.phantom_draws = 0   # robos esperados por la IA al simular (cartas desconocidas), nunca en partida real
        self.log: list[str] = []
        self.fx = EffectState()    # DSL interpreter state and hooks (docs/effects-dsl.md); inert unless fx.dsl_heroes
        self.fx.attach(self)

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
        g.drawn = [0, 0]
        g.phantom_draws = self.phantom_draws
        g.log = []
        g.fx = self.fx.copy()
        g.fx.attach(g)
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

    @property
    def combat_bonus(self) -> list[list[tuple[int, str]]]:
        """(bonus, label) of each player's live ONGOING, to ALL their combat cards: a view over `fx.ongoing`."""
        return [self.combat_bonus_parts(0), self.combat_bonus_parts(1)]

    @combat_bonus.setter
    def combat_bonus(self, sides) -> None:
        ongoing.set_legacy_all(self, sides)

    def add_combat_bonus(self, player: int, n: int, label: str) -> str | None:
        """A scheme with ONGOING "add n to the value of your combat cards" enters play. Ivan's ruling (28/10): only one
        active ONGOING per player, the new one replaces the old. Returns the label of the replaced one (or None)."""
        return ongoing.set_legacy(self, player, n, label)

    def combat_bonus_parts(self, player: int) -> list[tuple[int, str]]:
        """(bonus, label) of `player`'s live ONGOING (at most one)."""
        return ongoing.bonus_parts(self, player)

    def combat_bonus_total(self, player: int) -> int:
        return sum(n for n, _ in self.combat_bonus_parts(player))

    def attack_bonus(self, fighter: Fighter) -> int:
        """Bono del PROXIMO ataque de `fighter` (lo usa la IA para medir amenazas). El ONGOING de un plan caduca al
        empezar el turno de su dueno: si ahora no es su turno, ese bono ya no llega a su siguiente ataque."""
        passives = self.players[fighter.owner].hero.attack_bonus(self.form(fighter.owner), fighter.hero)
        return passives + (self.combat_bonus_total(fighter.owner) if self.turn == fighter.owner else 0)

    def legal_moves(self, fighter: Fighter, steps: int, through_enemies: bool = False) -> set[int]:
        if not self.fx.can_move(fighter):
            return {fighter.pos}
        return self.board.reachable(fighter.pos, steps, self.occupied(fighter.owner) - {fighter.pos},
                                    self.occupied(1 - fighter.owner), through_enemies)

    def can_attack(self, attacker: Fighter, target: Fighter) -> bool:
        return (attacker.alive and target.alive and attacker.owner != target.owner
                and self.fx.may_attack(attacker.owner)
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

    def damage(self, fighter: Fighter, n: float, source: str = "effect", by: Fighter | None = None) -> float:
        if not fighter.alive or n <= 0:
            return 0
        if source == "effect" and self.effect_shield.get(fighter.owner) == self.turn_no:
            self.log.append(f"{fighter.fid}: dano de efecto evitado")
            return 0
        n = self.fx.adjust_damage(fighter, n, source)
        if n <= 0:
            return 0
        fighter.hp -= n
        self.log.append(f"{fighter.fid} -{n} ({fighter.hp:g} pv)")
        self.fx.on_damage(fighter, n, source, by)
        if fighter.hp <= 0:
            fighter.died_at = fighter.pos if fighter.pos is not None else fighter.died_at
            fighter.alive, fighter.pos = False, None
            if fighter.hero:
                self.winner = 1 - fighter.owner
            self.fx.emit("fighter_defeated", fighter)
        return n

    def heal(self, fighter: Fighter, n: int) -> None:
        if fighter.alive:
            fighter.hp = min(fighter.max_hp, fighter.hp + n)

    def draw(self, player: int, n: int = 1, log: bool = True) -> list[Card]:
        p, drawn = self.players[player], []
        if not self.fx.can_draw(player):
            return drawn
        for _ in range(n):
            if not p.deck:
                for f in self.own(player):
                    self.damage(f, EXHAUST_DAMAGE, "exhaustion")
                continue
            card = p.deck.pop(0)
            p.hand.append(card)
            drawn.append(card)
            self.drawn[player] += 1
            self.players[1 - player].known.drawn(card, self.turn_no)
        if log and drawn:
            self.log.append(f"P{player} roba {len(drawn)}")
        return drawn

    def take_from_hand(self, player: int, card: Card) -> None:
        """Saca la carta de la mano para jugarla (combate); va al descarte cuando el combate termina."""
        self.players[player].hand.remove(card)
        self.card_left_hand(player, card)

    def discard_card(self, player: int, card: Card, played: bool = False, cause: str | None = None) -> None:
        """`played`: the card is being used (a scheme), not discarded by an effect: no `card_discarded` event.
        `cause`: why it was discarded when that matters to a trigger ("hand_limit": Wildfire does not return it)."""
        self.take_from_hand(player, card)
        self.players[player].discard.append(card)
        if not played:
            self.fx.emit("card_discarded", player, card, "hand", cause)

    def force_discard(self, player: int, n: int, reason: str, source: int | None = None,
                      cause: str | None = None) -> list[Card]:
        hand = self.players[player].hand
        n = min(n, len(hand))
        if not n:
            return []
        if not self.fx.can_force_discard(player, player if source is None else source):
            return []
        self.fx.emit("force_discard", player, n)
        chosen = self.controllers[player].choose_discard(self, player, n, reason)[:n]
        for c in chosen:
            self.discard_card(player, c, cause=cause)
        return chosen

    def grant_actions(self, n: int) -> None:
        if not self.fx.can_gain_actions(self.turn):
            return
        self.actions_left += n

    # turno
    def begin_turn(self) -> list[tuple[int, str]]:
        """Empieza el turno de `self.turn`: 2 acciones y caducan sus planes ONGOING. Devuelve lo que caduco."""
        self.actions_left = 2
        expired = ongoing.expiring_parts(self, self.turn)
        ongoing.expire_legacy(self, self.turn)
        self.fx.emit("start_of_turn", self.turn)
        return expired

    def use_action(self) -> None:
        if self.actions_left <= 0:
            raise RuleError("sin acciones")
        self.actions_left -= 1
        self.fx.count_action()

    def end_turn(self) -> None:
        self.fx.emit("end_of_turn", self.turn)
        hand = self.players[self.turn].hand
        limit = self.fx.hand_limit(self.turn, HAND_LIMIT)
        if len(hand) > limit:
            self.force_discard(self.turn, len(hand) - limit, "limite de mano", cause="hand_limit")
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
        self.fx.emit("after_maneuver", player)

    def play_scheme(self, player: int, fighter: Fighter, card: Card, **opts) -> None:
        from .combat import check_scheme, resolve_scheme
        if not card.is_scheme or not card.usable_by(fighter.name) or card not in self.players[player].hand:
            raise RuleError(f"{card.title} no se puede jugar con {fighter.fid}")
        check_scheme(self, fighter, card, **opts)
        self.use_action()
        self.discard_card(player, card, played=True)
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
        def_card = self._declare_attack(attacker, target, card, def_card)
        return resolve_combat(self, attacker, target, card, def_card, values, boost)

    def begin_attack(self, attacker: Fighter, target: Fighter, card: Card, def_card="ask",
                     values: tuple[int, int] = (0, 0)) -> "CombatFlow":
        """Like `attack`, but returns the combat as a flow the caller drives step by step (the session stops it at the
        panel when a card effect asks the human something). The action is already spent when it returns."""
        from .combat_flow import CombatFlow
        def_card = self._declare_attack(attacker, target, card, def_card)
        return CombatFlow(self, attacker, target, card, def_card, values)

    def _declare_attack(self, attacker: Fighter, target: Fighter, card: Card, def_card) -> Card | None:
        """Everything before the cards resolve: checks, the action, the `attacked` event and the defense choice."""
        if not self.fx.may_attack(attacker.owner):
            raise RuleError(f"{attacker.fid} no puede atacar como primera accion del turno")
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
        self.fx.emit("attacked", attacker, target, card)
        if def_card == "ask":
            def_card = self.controllers[target.owner].choose_defense(self, attacker, target)
        return def_card

    # habilidades de inicio de turno (hasta el paso 8 del plan siguen cableadas por heroe)
    def medusa_ability(self, target: Fighter) -> None:
        medusa = self.hero_named("Medusa")
        if target.owner == medusa.owner or not target.alive or not self.board.share_zone(medusa.pos, target.pos):
            raise RuleError("objetivo invalido para la habilidad")
        self.damage(target, 1)

    def hellboy_anung_start(self, player: int, card: Card, dest: int | None) -> None:
        if "hellboy" in self.fx.dsl_heroes:      # the DSL trigger anung_discard_move already ran at begin_turn
            return
        self.discard_card(player, card)
        if dest is not None:
            self.move_fighter(self.hero_named("Hellboy"), dest, card.boost)

    def hellboy_detective_draw(self, player: int) -> bool:
        """Robo de inicio de turno en la salida rival: el disparador `draw` activo en la forma actual (Hellboy en
        OCCULT DETECTIVE: 2 cartas) con la condicion `hero_on_rival_start`; cuantas, lo dicen los datos."""
        if "hellboy" in self.fx.dsl_heroes:      # the DSL trigger detective_draw already ran at begin_turn
            return False
        hero = self.hero(player)
        for t in self.triggers(player, "start_of_turn"):
            if t.get("effect") != "draw" or t.get("condition") != "hero_on_rival_start":
                continue
            if hero.alive and hero.pos == self.start_spaces[1 - player]:
                self.draw(player, int(t["n"]))
                return True
        return False
