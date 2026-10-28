"""Adaptador del motor actual (Medusa vs Hellboy) al Protocol `SearchState`.

Que ve la busqueda: jugadas como tuplas hashables, con los titulos de las cartas (las copias de una carta son
equivalentes, asi que las estadisticas no se reparten entre ellas). Una accion combinatoria se descompone en
subdecisiones encadenadas que comparten estadisticas en el arbol (la raiz tiene ~12 hijos en vez de ~150):
  ("ability", fid | None)                       habilidad de Medusa al empezar su turno
  ("anung", titulo) -> ("anung_to", d | None)   descarte obligatorio + movimiento de ANUNG UN RAMA
  ("attack", fid, objetivo) -> ("attack_card", fid, titulo)   el rival ve ("attack_card", fid, None)
  ("defend", titulo | None)                     resuelve el combate pendiente
  ("scheme", titulo, objetivo | None, variante) planes con efecto codificado (solo los de Medusa hoy)
  ("maneuver", boost | None) -> ("hero_to", d) -> ("sidekicks", politica)
Las subfases con una sola opcion se resuelven solas. `decision_pending()` dice si la accion esta a medias, para
que el controlador complete la jugada siguiendo la variacion principal.

Lo que el motor delega a mitad de resolucion (boost de Second Shot, Dash, Hounds, descarte forzado, recolocar
una Harpia) lo decide `SearchController` con heuristicas fijas: no es parte del arbol. Los ayudantes se mueven
en bloque con una politica (quedarse, avanzar, retirarse) y solo el heroe explora todos sus destinos.

Sin trampas: `determinize` solo usa `full_set`, `discard`, `len(hand)` y las cartas conocidas (`Knowledge`).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import exp

from ..cards import Card
from ..combat import is_medusa_card, resolve_combat
from ..controller import Controller
from ..state import ANUNG, Fighter, Game

SIDEKICK_POLICIES = ("stay", "advance", "retreat")
FRENZY_VARIANTS = ("advance", "retreat")
ROLLOUT_ATTACK_PROB = 0.7     # en el rollout, quien puede atacar ataca casi siempre (hace visibles las amenazas)
ROLLOUT_BOOST_PROB = 0.3
EVAL_SIDEKICKS = 0.4
EVAL_ALIVE = 0.15
EVAL_HAND = 0.15
EVAL_DECK = 0.1
EVAL_SLOPE = 2.5


@dataclass(frozen=True)
class Knowledge:
    """Cartas que el observador sabe que estan en la mano de un jugador por un efecto legitimo de mirar la mano,
    ya descontadas de las que han salido (el motor las mantiene; el adaptador solo las respeta)."""
    known_in_hand: dict[int, tuple[Card, ...]] = field(default_factory=dict)


def card_worth(c: Card) -> float:
    return (c.value or 0) + 0.5 * c.boost + (2.0 if c.is_scheme else 0.0)


def by_title(hand: list[Card], title: str) -> Card:
    return next(c for c in hand if c.title == title)


_reach_cache: dict[tuple, frozenset[int]] = {}
_near_cache: dict[tuple, int] = {}
_moves_cache: dict[tuple, list] = {}
MOVES_CACHE_MAX = 50_000


def reach_from(board, pos: int, steps: int, own: frozenset[int], enemy: frozenset[int],
               through: bool = False) -> frozenset[int]:
    """`Board.reachable` con cache: dentro de una busqueda las mismas posiciones se repiten miles de veces."""
    key = (board.key, pos, steps, own, enemy, through)
    r = _reach_cache.get(key)
    if r is None:
        r = _reach_cache[key] = frozenset(board.reachable(pos, steps, set(own), set(enemy), through))
    return r


def reach(game: Game, f: Fighter, steps: int, through: bool = False) -> frozenset[int]:
    """`Game.legal_moves` con cache."""
    own = frozenset(game.occupied(f.owner) - {f.pos})
    enemy = frozenset(game.occupied(1 - f.owner))
    return reach_from(game.board, f.pos, steps, own, enemy, through)


def nearest(board, pos: int, foes: tuple[int, ...]) -> int:
    key = (board.key, pos, foes)
    d = _near_cache.get(key)
    if d is None:
        d = _near_cache[key] = min((board.distance(pos, e) for e in foes), default=0)
    return d


def policy_dest_from(board, pos: int, options, foes: tuple[int, ...], policy: str) -> int:
    if policy == "stay" or not foes:
        return pos
    cands = set(options) | {pos}
    if policy == "advance":
        return min(cands, key=lambda d: (nearest(board, d, foes), d))
    return max(cands, key=lambda d: (nearest(board, d, foes), -d))


def foe_positions(game: Game, player: int) -> tuple[int, ...]:
    return tuple(sorted(game.occupied(1 - player)))


def policy_dest(game: Game, f: Fighter, options, policy: str) -> int:
    return policy_dest_from(game.board, f.pos, options, foe_positions(game, f.owner), policy)


def sidekick_plan(game: Game, player: int, extra: int, policy: str,
                  hero_dest: int | None = None) -> tuple[tuple[str, int], ...]:
    """Destinos de los ayudantes en orden de fid, con la ocupacion actualizada tras cada uno (y el heroe ya en
    `hero_dest` si se da): exactamente el orden en que el motor valida la maniobra. Sin clonar el `Game`."""
    board = game.board
    own = {f.fid: f.pos for f in game.own(player)}
    if hero_dest is not None:
        own[game.hero(player).fid] = hero_dest
    enemy = frozenset(game.occupied(1 - player))
    foes = tuple(sorted(enemy))
    out = []
    for h in sorted((x for x in game.own(player) if not x.hero), key=lambda x: x.fid):
        others = frozenset(v for k, v in own.items() if k != h.fid)
        dest = policy_dest_from(board, own[h.fid], reach_from(board, own[h.fid], h.move + extra, others, enemy),
                                foes, policy)
        own[h.fid] = dest
        out.append((h.fid, dest))
    return tuple(out)


def plan_frenzy(game: Game, player: int, variant: str) -> tuple[dict[str, int], int | None]:
    """Movimientos de Winged Frenzy (todos los luchadores, 3 pasos, a traves de rivales) y la casilla donde vuelve
    la Harpia caida, con la misma politica que usa la simulacion."""
    g = game.clone()
    moves = {}
    for f in sorted(g.own(player), key=lambda x: x.fid):
        dest = policy_dest(g, f, reach(g, f, 3, True), variant)
        f.pos = dest
        moves[f.fid] = dest
    spot = None
    dead = [f for f in g.own(player, alive_only=False) if not f.hero and not f.alive]
    if dead:
        hero = g.hero(player)
        taken = {f.pos for f in g.fighters.values() if f.alive}
        options = sorted(s for s in g.board.spaces if s not in taken and g.board.share_zone(hero.pos, s))
        spot = placement_choice(g, player, options)
    return moves, spot


def placement_choice(game: Game, player: int, options: list[int]) -> int | None:
    foes = foe_positions(game, player)
    return max(options, key=lambda s: (nearest(game.board, s, foes), -s)) if options else None


class SearchController(Controller):
    """Decisiones delegadas por el motor dentro de la simulacion: heuristicas fijas y baratas."""

    def __init__(self, me: int, state: "EngineState"):
        self.me = me
        self.state = state

    def choose_combat_boost(self, game: Game, ctx):
        hand = game.players[self.me].hand
        t = ctx.target
        now = min(max(0, ctx.atk_value - ctx.def_value), t.hp)
        best, best_gain = None, 0.0
        for c in hand:
            net = min(max(0, ctx.atk_value + c.boost - ctx.def_value), t.hp)
            gain = net - now - 0.3 * card_worth(c)
            if gain > best_gain:
                best, best_gain = c, gain
        return best

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        return sorted(game.players[player].hand, key=lambda c: (card_worth(c), c.card_id))[:n]

    def choose_move(self, game: Game, fighter: Fighter, steps: int, through_enemies: bool = False):
        policy = self.state.variant
        if policy is None:      # Dash y Hounds: el heroe a distancia se aleja, los demas se acercan
            policy = "retreat" if (fighter.hero and fighter.ranged) else "advance"
        return policy_dest(game, fighter, reach(game, fighter, steps, through_enemies), policy)

    def choose_placement(self, game: Game, fighter: Fighter, options: list[int]):
        return placement_choice(game, fighter.owner, options)


class EngineState:
    """`pending`: (fid atacante, fid objetivo, carta | None). Con carta None la jugada esta boca abajo y la
    determinizacion la muestrea (el bot eligiendo defensa). `phase`: "start", "action" o una subfase
    ("attack_card", "maneuver_hero", "maneuver_side", "anung_to") con la decision a medias en `partial`."""

    SUBPHASES = ("attack_card", "maneuver_hero", "maneuver_side", "anung_to")

    def __init__(self, game: Game, observer: int, knowledge: Knowledge | None = None,
                 pending: tuple[str, str, Card | None] | None = None, phase: str = "action"):
        self.game = game.clone()
        self.game.controllers = {0: SearchController(0, self), 1: SearchController(1, self)}
        self.observer = observer
        self.knowledge = knowledge or Knowledge()
        self.pending = pending
        self.phase = phase
        self.partial: tuple = ()
        self.variant: str | None = None
        self._advance()

    # ---------- Protocol ----------
    def clone(self) -> "EngineState":
        c = EngineState.__new__(EngineState)
        c.game = self.game.clone()
        c.game.controllers = {0: SearchController(0, c), 1: SearchController(1, c)}
        c.observer, c.knowledge, c.pending = self.observer, self.knowledge, self.pending
        c.phase, c.partial, c.variant = self.phase, self.partial, self.variant
        return c

    def player_to_move(self) -> int:
        if self.pending is not None:
            return self.game.fighters[self.pending[1]].owner
        return self.game.turn

    def is_terminal(self) -> bool:
        return self.game.winner is not None

    def winner(self) -> int | None:
        return self.game.winner

    def pending_card(self) -> Card | None:
        return self.pending[2] if self.pending else None

    def decision_pending(self) -> bool:
        return self.phase in self.SUBPHASES

    def legal_moves(self) -> list:
        """Memorizada por firma (fase, pendiente, posiciones, mano de quien mueve): la raiz es la misma en todas
        las iteraciones y los nodos del rival se repiten mucho. La lista devuelta no se modifica."""
        key = self._signature()
        moves = _moves_cache.get(key)
        if moves is None:
            if len(_moves_cache) >= MOVES_CACHE_MAX:
                _moves_cache.clear()
            moves = _moves_cache[key] = self._generate_moves()
        return moves

    def _signature(self) -> tuple:
        g = self.game
        mover = self.player_to_move()
        return (g.board.key, g.turn, self.phase, self.partial, self.pending[:2] if self.pending else None,
                g.form(1 - g.turn) if self.phase == "start" else None,
                tuple((f.fid, f.pos) for f in g.fighters.values() if f.alive),
                tuple(sorted(c.card_id for c in g.players[mover].hand)))

    def _generate_moves(self) -> list:
        g = self.game
        if self.pending is not None:
            return self._defend_moves()
        p = g.turn
        hero = g.hero(p)
        if self.phase == "start":
            return self._start_moves(p)
        if self.phase == "anung_to":
            card = by_title(g.players[p].hand, self.partial[0])
            return [("anung_to", None)] + [("anung_to", d) for d in sorted(reach(g, hero, card.boost))]
        if self.phase == "attack_card":
            f = g.fighters[self.partial[0]]
            return [("attack_card", f.fid, t) for t in self._attack_titles(p, f)]
        if self.phase == "maneuver_hero":
            return [("hero_to", d) for d in sorted(reach(g, hero, hero.move + self._extra()) | {hero.pos})]
        if self.phase == "maneuver_side":
            if not any(not f.hero for f in g.own(p)):
                return [("sidekicks", "stay")]
            return [("sidekicks", policy) for policy in SIDEKICK_POLICIES]
        moves = self._attack_moves(p) + self._scheme_moves(p)
        moves += [("maneuver", c.title if c else None) for c in self._boost_variants(p)]
        return moves

    def apply(self, move) -> None:
        g = self.game
        kind = move[0]
        p = self.player_to_move()
        hand = g.players[p].hand
        if kind == "defend":
            att, tgt, atk_card = self.pending
            self.pending = None
            def_card = by_title(hand, move[1]) if move[1] is not None else None
            resolve_combat(g, g.fighters[att], g.fighters[tgt], atk_card, def_card)
        elif kind == "attack":
            self.phase, self.partial = "attack_card", (move[1], move[2])
        elif kind == "attack_card":
            att, tgt = self.partial
            self.phase, self.partial = "action", ()
            g.use_action()
            self.pending = (att, tgt, by_title(hand, move[2]))
        elif kind == "maneuver":
            self.phase, self.partial = "maneuver_hero", (move[1],)
        elif kind == "hero_to":
            self.phase, self.partial = "maneuver_side", (self.partial[0], move[1])
        elif kind == "sidekicks":
            title, d = self.partial
            self.phase, self.partial = "action", ()
            boost = by_title(hand, title) if title is not None else None
            plan = sidekick_plan(g, p, boost.boost if boost else 0, move[1], hero_dest=d)
            g.maneuver(p, dict(((g.hero(p).fid, d),) + plan), boost)
        elif kind == "scheme":
            card = by_title(hand, move[1])
            if move[2] is not None:
                g.play_scheme(p, g.hero(p), card, target=g.fighters[move[2]])
            else:
                self.variant = move[3]
                try:
                    g.play_scheme(p, g.hero(p), card)
                finally:
                    self.variant = None
        elif kind == "ability":
            if move[1] is not None:
                g.medusa_ability(g.fighters[move[1]])
            self.phase = "action"
        elif kind == "anung":
            self.phase, self.partial = "anung_to", (move[1],)
        elif kind == "anung_to":
            title, = self.partial
            self.phase, self.partial = "action", ()
            g.hellboy_anung_start(p, by_title(hand, title), move[1])
        else:
            raise ValueError(f"jugada desconocida: {move!r}")
        self._advance()

    def observe(self, move, viewer: int):
        if move[0] == "attack_card" and self.game.fighters[move[1]].owner != viewer:
            return ("attack_card", move[1], None)
        return move

    def evaluate(self, player: int) -> float:
        g = self.game
        if g.winner is not None:
            return 1.0 if g.winner == player else 0.0
        d = self._side_value(player) - self._side_value(1 - player)
        return 1.0 / (1.0 + exp(-EVAL_SLOPE * d))

    def rollout_move(self, rng: random.Random):
        g = self.game
        if self.pending is not None or self.phase != "action":
            return rng.choice(self.legal_moves())
        p = g.turn
        attacks = self._attack_moves(p)
        if attacks and rng.random() < ROLLOUT_ATTACK_PROB:
            return rng.choice(attacks)
        boosts = self._boost_variants(p)
        boost = rng.choice(boosts[1:]) if len(boosts) > 1 and rng.random() < ROLLOUT_BOOST_PROB else None
        return ("maneuver", boost.title if boost else None)

    def determinize(self, observer: int, rng: random.Random) -> None:
        g = self.game
        for p, st in enumerate(g.players):
            if p == observer:
                rng.shuffle(st.deck)        # el orden del propio mazo tambien es oculto
                continue
            known = [c for c in self.knowledge.known_in_hand.get(p, ()) if c not in st.discard]
            pool = [c for c in st.full_set if c not in st.discard and c not in known]
            if self.pending is not None and self.pending[2] is None and g.fighters[self.pending[0]].owner == p:
                attacker = g.fighters[self.pending[0]]
                legal = [c for c in known if c.can_attack and c.usable_by(attacker.name)]
                if not legal:
                    legal = [c for c in pool if c.can_attack and c.usable_by(attacker.name)]
                card = rng.choice(legal)
                if card not in known:
                    known.append(card)
                    pool.remove(card)
                self.pending = (self.pending[0], self.pending[1], card)
            rng.shuffle(pool)
            k = max(0, len(st.hand) - len(known))
            st.hand = known + pool[:k]
            st.deck = pool[k:]

    # ---------- pasos automaticos ----------
    def _advance(self) -> None:
        g = self.game
        while g.winner is None:
            if self.pending is not None:
                if self.pending[2] is None or len(self._defend_moves()) > 1:
                    return
                self.apply(("defend", None))
                return
            p = g.turn
            if self.phase == "start":
                hero = g.hero(p)
                if hero.name == "Medusa":
                    if self._ability_targets(p):
                        return
                    self.phase = "action"
                    continue
                if hero.name == "Hellboy":
                    if g.form(p) == ANUNG and g.players[p].hand:
                        return
                    g.hellboy_detective_draw(p)
                self.phase = "action"
                continue
            if self.phase in self.SUBPHASES:
                moves = self.legal_moves()
                if len(moves) == 1:         # subfase sin eleccion real: se resuelve sola
                    self.apply(moves[0])
                return
            if g.actions_left <= 0:
                g.end_turn()
                g.begin_turn()
                self.phase = "start"
                continue
            return

    # ---------- generadores ----------
    def _ability_targets(self, p: int) -> list[Fighter]:
        medusa = self.game.hero(p)
        return [f for f in self.game.foes(p) if self.game.board.share_zone(medusa.pos, f.pos)]

    def _start_moves(self, p: int) -> list:
        g = self.game
        hero = g.hero(p)
        if hero.name == "Medusa":
            return [("ability", f.fid) for f in self._ability_targets(p)] + [("ability", None)]
        return [("anung", t) for t in dict.fromkeys(c.title for c in g.players[p].hand)]

    def _defend_moves(self) -> list:
        g = self.game
        target = g.fighters[self.pending[1]]
        out, seen = [("defend", None)], set()
        for c in g.players[target.owner].hand:
            if c.can_defend and c.usable_by(target.name) and c.title not in seen:
                seen.add(c.title)
                out.append(("defend", c.title))
        return out

    def _attack_titles(self, p: int, f: Fighter) -> list[str]:
        return list(dict.fromkeys(c.title for c in self.game.players[p].hand if c.can_attack and c.usable_by(f.name)))

    def _attack_moves(self, p: int) -> list:
        g = self.game
        out = []
        for f in g.own(p):
            if not self._attack_titles(p, f):
                continue
            out += [("attack", f.fid, t.fid) for t in g.foes(p) if g.can_attack(f, t)]
        return out

    def _scheme_moves(self, p: int) -> list:
        g = self.game
        hero = g.hero(p)
        out, seen = [], set()
        for c in g.players[p].hand:
            if not c.is_scheme or not is_medusa_card(c) or not c.usable_by(hero.name) or c.title in seen:
                continue
            seen.add(c.title)
            if c.title == "A Momentary Glance":
                out += [("scheme", c.title, t.fid, None) for t in g.foes(p) if g.board.share_zone(hero.pos, t.pos)]
            elif c.title == "Winged Frenzy":
                out += [("scheme", c.title, None, v) for v in FRENZY_VARIANTS]
        return out

    def _boost_variants(self, p: int) -> list[Card | None]:
        """Sin boost, la carta mas barata con el boost maximo y la carta mas barata de la mano (si su boost es
        otro): tres alcances como mucho."""
        hand = [c for c in self.game.players[p].hand if c.boost > 0]
        if not hand:
            return [None]
        cheapest = min(hand, key=lambda c: (card_worth(c), c.card_id))
        top = max(hand, key=lambda c: (c.boost, -card_worth(c), -c.card_id))
        out = [None, top]
        if cheapest.boost != top.boost:
            out.append(cheapest)
        return out

    def _extra(self) -> int:
        title = self.partial[0]
        return by_title(self.game.players[self.game.turn].hand, title).boost if title is not None else 0

    # ---------- evaluacion ----------
    def _side_value(self, p: int) -> float:
        g = self.game
        hero = g.hero(p)
        side = [f for f in g.own(p, alive_only=False) if not f.hero]
        side_max = sum(f.max_hp for f in side)
        side_hp = sum(f.hp for f in side if f.alive) / side_max if side_max else 0.0
        alive = sum(1 for f in side if f.alive) / len(side) if side else 0.0    # un ayudante caido es un atacante menos
        hand = min(len(g.players[p].hand), 7) / 7
        deck = min(len(g.players[p].deck), 10) / 10
        return (max(hero.hp, 0) / hero.max_hp + EVAL_SIDEKICKS * side_hp + EVAL_ALIVE * alive
                + EVAL_HAND * hand + EVAL_DECK * deck)
