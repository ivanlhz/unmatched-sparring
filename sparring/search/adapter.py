"""Adaptador del motor actual (Medusa vs Hellboy) al Protocol `SearchState`.

Que ve la busqueda: jugadas como tuplas hashables, con los titulos de las cartas (las copias de una carta son
equivalentes, asi que las estadisticas no se reparten entre ellas).
  ("ability", fid | None)                           habilidad de Medusa al empezar su turno
  ("anung", titulo, destino | None)                 descarte obligatorio + movimiento de ANUNG UN RAMA
  ("attack", fid, objetivo, titulo)                 el rival lo ve como ("attack", fid, objetivo, None)
  ("defend", titulo | None)                         resuelve el combate pendiente
  ("scheme", titulo, objetivo | None, variante)     planes con efecto codificado (solo los de Medusa hoy)
  ("maneuver", titulo_boost | None, ((fid, destino), ...))

Lo que el motor delega a mitad de resolucion (boost de Second Shot, Dash, Hounds, descarte forzado, recolocar
una Harpia) lo decide `SearchController` con heuristicas fijas: no es parte del arbol. Para que el factor de
ramificacion sea manejable, los ayudantes se mueven en bloque con una politica (quedarse, avanzar, retirarse) y
solo el heroe explora todos sus destinos.

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


def reach(game: Game, f: Fighter, steps: int, through: bool = False) -> frozenset[int]:
    """`Game.legal_moves` con cache: dentro de una busqueda las mismas posiciones se repiten miles de veces."""
    own = frozenset(game.occupied(f.owner) - {f.pos})
    enemy = frozenset(game.occupied(1 - f.owner))
    key = (game.board.key, f.pos, steps, own, enemy, through)
    r = _reach_cache.get(key)
    if r is None:
        r = _reach_cache[key] = frozenset(game.board.reachable(f.pos, steps, set(own), set(enemy), through))
    return r


def nearest_foe(game: Game, pos: int, foes: list[Fighter]) -> int:
    return min((game.board.distance(pos, e.pos) for e in foes), default=0)


def policy_dest(game: Game, f: Fighter, options, policy: str) -> int:
    foes = game.foes(f.owner)
    if policy == "stay" or not foes:
        return f.pos
    cands = sorted(set(options) | {f.pos})
    if policy == "advance":
        return min(cands, key=lambda d: (nearest_foe(game, d, foes), d))
    return max(cands, key=lambda d: (nearest_foe(game, d, foes), -d))


def sidekick_plan(game: Game, player: int, extra: int, policy: str) -> list[tuple[str, int]]:
    """Destinos de los ayudantes en orden de fid, con la ocupacion actualizada tras cada uno."""
    g = game.clone()
    out = []
    for h in sorted((x for x in g.own(player) if not x.hero), key=lambda x: x.fid):
        dest = policy_dest(g, h, reach(g, h, h.move + extra), policy)
        h.pos = dest
        out.append((h.fid, dest))
    return out


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
    foes = game.foes(player)
    return max(options, key=lambda s: (nearest_foe(game, s, foes), -s)) if options else None


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
    determinizacion la muestrea (el bot eligiendo defensa). `phase`: "start" (decisiones de inicio de turno) o
    "action"."""

    def __init__(self, game: Game, observer: int, knowledge: Knowledge | None = None,
                 pending: tuple[str, str, Card | None] | None = None, phase: str = "action"):
        self.game = game.clone()
        self.game.controllers = {0: SearchController(0, self), 1: SearchController(1, self)}
        self.observer = observer
        self.knowledge = knowledge or Knowledge()
        self.pending = pending
        self.phase = phase
        self.variant: str | None = None
        self._advance()

    # ---------- Protocol ----------
    def clone(self) -> "EngineState":
        c = EngineState.__new__(EngineState)
        c.game = self.game.clone()
        c.game.controllers = {0: SearchController(0, c), 1: SearchController(1, c)}
        c.observer, c.knowledge, c.pending, c.phase, c.variant = (self.observer, self.knowledge, self.pending,
                                                                  self.phase, self.variant)
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

    def legal_moves(self) -> list:
        g = self.game
        if self.pending is not None:
            return self._defend_moves()
        p = g.turn
        if self.phase == "start":
            return self._start_moves(p)
        moves = self._attack_moves(p) + self._scheme_moves(p)
        for boost in self._boost_variants(p):
            moves += self._maneuver_moves(p, boost)
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
            g.use_action()
            self.pending = (move[1], move[2], by_title(hand, move[3]))
        elif kind == "maneuver":
            boost = by_title(hand, move[1]) if move[1] is not None else None
            g.maneuver(p, dict(move[2]), boost)
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
            g.hellboy_anung_start(p, by_title(hand, move[1]), move[2])
            self.phase = "action"
        else:
            raise ValueError(f"jugada desconocida: {move!r}")
        self._advance()

    def observe(self, move, viewer: int):
        if move[0] == "attack" and self.game.fighters[move[1]].owner != viewer:
            return ("attack", move[1], move[2], None)
        return move

    def evaluate(self, player: int) -> float:
        g = self.game
        if g.winner is not None:
            return 1.0 if g.winner == player else 0.0
        d = self._side_value(player) - self._side_value(1 - player)
        return 1.0 / (1.0 + exp(-EVAL_SLOPE * d))

    def rollout_move(self, rng: random.Random):
        g = self.game
        if self.pending is not None:
            return rng.choice(self._defend_moves())
        p = g.turn
        if self.phase == "start":
            return rng.choice(self._start_moves(p))
        attacks = self._attack_moves(p)
        if attacks and rng.random() < ROLLOUT_ATTACK_PROB:
            return rng.choice(attacks)
        boosts = self._boost_variants(p)
        boost = rng.choice(boosts[1:]) if len(boosts) > 1 and rng.random() < ROLLOUT_BOOST_PROB else None
        return rng.choice(self._maneuver_moves(p, boost))

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
        out, seen = [], set()
        for c in g.players[p].hand:
            if c.title in seen:
                continue
            seen.add(c.title)
            out.append(("anung", c.title, None))
            out += [("anung", c.title, d) for d in sorted(reach(g, hero, c.boost))]
        return out

    def _defend_moves(self) -> list:
        g = self.game
        target = g.fighters[self.pending[1]]
        out, seen = [("defend", None)], set()
        for c in g.players[target.owner].hand:
            if c.can_defend and c.usable_by(target.name) and c.title not in seen:
                seen.add(c.title)
                out.append(("defend", c.title))
        return out

    def _attack_moves(self, p: int) -> list:
        g = self.game
        hand = g.players[p].hand
        out = []
        for f in g.own(p):
            titles = []
            seen = set()
            for c in hand:
                if c.can_attack and c.usable_by(f.name) and c.title not in seen:
                    seen.add(c.title)
                    titles.append(c.title)
            if not titles:
                continue
            for t in g.foes(p):
                if g.can_attack(f, t):
                    out += [("attack", f.fid, t.fid, title) for title in titles]
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

    def _maneuver_moves(self, p: int, boost: Card | None) -> list:
        g = self.game
        hero = g.hero(p)
        extra = boost.boost if boost else 0
        title = boost.title if boost else None
        dests = sorted(reach(g, hero, hero.move + extra) | {hero.pos})
        plans = {tuple(sidekick_plan(g, p, extra, policy)) for policy in SIDEKICK_POLICIES}
        out = []
        for d in dests:
            for plan in sorted(plans):
                # un ayudante cuyo destino es el del heroe se queda donde esta (el heroe mueve primero)
                moves = ((hero.fid, d),) + tuple((fid, dest if dest != d else g.fighters[fid].pos) for fid, dest in plan)
                out.append(("maneuver", title, moves))
        return list(dict.fromkeys(out))

    # ---------- evaluacion ----------
    def _side_value(self, p: int) -> float:
        g = self.game
        hero = g.hero(p)
        side = [f for f in g.own(p, alive_only=False) if not f.hero]
        side_max = sum(f.max_hp for f in side)
        side_hp = sum(f.hp for f in side if f.alive) / side_max if side_max else 0.0
        hand = min(len(g.players[p].hand), 7) / 7
        deck = min(len(g.players[p].deck), 10) / 10
        return max(hero.hp, 0) / hero.max_hp + EVAL_SIDEKICKS * side_hp + EVAL_HAND * hand + EVAL_DECK * deck
