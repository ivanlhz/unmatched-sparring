"""Adaptador del motor actual (Medusa vs Hellboy) al Protocol `SearchState`.

Que ve la busqueda: jugadas como tuplas hashables, con los titulos de las cartas (las copias de una carta son
equivalentes, asi que las estadisticas no se reparten entre ellas). Una accion combinatoria se descompone en
subdecisiones encadenadas que comparten estadisticas en el arbol (la raiz tiene ~12 hijos en vez de ~150):
  ("ability", fid | None)                       habilidad de Medusa al empezar su turno
  ("anung", titulo) -> ("anung_to", d | None)   descarte obligatorio + movimiento de ANUNG UN RAMA
  ("attack", fid, objetivo) -> ("attack_card", fid, titulo)   el rival ve ("attack_card", fid, None)
  ("defend", titulo | None)                     resuelve el combate pendiente
  ("scheme", titulo, objetivo | None, variante) planes con efecto codificado (solo los de Medusa hoy)
  ("maneuver", boost | None) -> ("place", d, politica)   destino del heroe y politica de los ayudantes
Las subfases con una sola opcion se resuelven solas. `decision_pending()` dice si la accion esta a medias, para
que el controlador complete la jugada siguiendo la variacion principal.

Lo que el motor delega a mitad de resolucion (boost de Second Shot, Dash, Hounds, descarte forzado, recolocar
una Harpia) lo decide `SearchController` con heuristicas fijas: no es parte del arbol. Los ayudantes se mueven
en bloque con una politica (quedarse, avanzar, retirarse). En el arbol entran solo las colocaciones completas
(heroe y ayudantes ya movidos) mejor puntuadas por la evaluacion estatica como posicion de final de turno
(`PLACEMENT_KEEP`), mas las mejores desde las que el heroe golpea y quedarse quieto: con todas, la maniobra
tenia ~30 hojas con pocas visitas cada una y el ruido elegia la casilla. El rollout no poda.

Sin trampas: `determinize` solo usa `full_set`, `discard`, `len(hand)` y las cartas conocidas (`Knowledge`).

Evaluacion de hoja (`evaluate`): material de cada bando (PV del heroe, PV y numero de ayudantes, mano, mazo) menos
la amenaza sobre su heroe el turno que viene (`EngineState.threat`): dano esperado de los rivales que lo alcanzan
de verdad (sin atravesar luchadores propios, asi un ayudante en el pasillo es un escudo), con el ataque medio del
mazo completo del atacante contra la mejor defensa en mano, mas la probabilidad de que lo maten. Es generica
(cualquier heroe, cualquier ayudante) y, restada al bando contrario, es la presion propia: un ayudante a tiro del
heroe rival vale como atacante, no solo como PV que conservar. Los pesos viven en `EvalWeights` (F10 los ajusta).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import sqrt

from ..ai_medusa import GAZE
from ..cards import Card, can_be_boost
from ..combat import is_medusa_card, resolve_combat
from ..controller import Controller
from ..state import ANUNG, Fighter, Game, PlayerState

SIDEKICK_POLICIES = ("stay", "advance", "retreat")
FRENZY_VARIANTS = ("advance", "retreat")
ROLLOUT_ATTACK_PROB = 0.7     # en el rollout, quien puede atacar ataca casi siempre (hace visibles las amenazas)
ROLLOUT_BOOST_PROB = 0.3
ROLLOUT_APPROACH_PROB = 0.5   # en el rollout, el heroe que maniobra busca una casilla desde la que golpear
BOOST_STEPS = 2               # pasos extra que un atacante puede comprar con un boost (lo tipico del mazo)
PLACEMENT_KEEP = 6            # colocaciones de la maniobra en el arbol: las mejores por evaluacion estatica...
PLACEMENT_STRIKE_KEEP = 2     # ...mas las mejores desde las que el heroe golpea, mas quedarse quieto
ANUNG_FREE_STEPS = 2          # movimiento libre de ANUNG UN RAMA al empezar el turno (ver MedusaAI)


@dataclass(frozen=True)
class EvalWeights:
    """Pesos de la evaluacion de hoja. Unidades: 1.0 = todos los PV del heroe."""
    sidekicks: float = 1.0          # PV de los ayudantes vivos, medidos en PV maximos del heroe
    alive: float = 0.15             # ayudantes vivos: un caido es un atacante y un escudo menos
    hand: float = 0.15
    deck: float = 0.1
    threat: float = 0.6             # dano esperado sobre el heroe el turno que viene (fraccion de sus PV actuales)
    lethal: float = 0.5             # probabilidad de que ese turno lo mate
    victim_moves_first: float = 0.1 # descuento si el amenazado mueve antes: puede apartarse o golpear primero
    boost_reach: float = 0.4        # el atacante que necesita un boost para llegar: le cuesta una carta y es incierto
    defend_card_hp: float = 0.75    # cada ataque recibido cuesta ademas una carta de defensa (en PV equivalentes)
    slope: float = 1.5              # escala de `squash` sobre la diferencia entre bandos


@dataclass(frozen=True)
class Knowledge:
    """A frozen snapshot of the observer's `KnownHand` (the single source of truth, kept by the engine, already
    discounted of the cards that left): what a legitimate look-at-the-hand or reveal effect showed. The adapter only
    respects it. Keys are the RIVAL player whose hand/deck it describes.
    - known_in_hand: certainly in that hand.
    - possible_in_hand / possible_bounds: seen once, maybe gone face down; between lo and hi of them are in the hand.
    - top_of_deck: that deck's known prefix, top first."""
    known_in_hand: dict[int, tuple[Card, ...]] = field(default_factory=dict)
    possible_in_hand: dict[int, tuple[Card, ...]] = field(default_factory=dict)
    possible_bounds: dict[int, tuple[int, int]] = field(default_factory=dict)
    top_of_deck: dict[int, tuple[Card, ...]] = field(default_factory=dict)

    @classmethod
    def from_game(cls, game: Game, observer: int) -> "Knowledge":
        known, rival = game.players[observer].known, 1 - observer
        st = game.players[rival]
        poss = tuple(known.possible_cards(st))
        return cls({rival: tuple(known.cards(st))}, {rival: poss},
                   {rival: (min(known.possible_lo, len(poss)), min(known.possible_hi, len(poss)))},
                   {rival: tuple(known.top(st))})


def squash(x: float) -> float:
    """Ventaja (en vidas del heroe) a recompensa en (0, 1), con colas pesadas. Con la sigmoide, una posicion muy
    perdida (Medusa a 3 PV frente a Hellboy entero) valia ~0,04 hiciera lo que hiciera, y un 10 % de morir ahora
    pesaba menos que cancelar una carta; asi seguir viva se distingue de morir tambien ahi."""
    return 0.5 + 0.5 * x / (1.0 + abs(x))


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
    """`Game.legal_moves` con cache (un luchador inmovilizado por un efecto, Burning Barrier, se queda donde esta)."""
    if not game.fx.can_move(f):
        return frozenset({f.pos})
    own = frozenset(game.occupied(f.owner) - {f.pos})
    enemy = frozenset(game.occupied(1 - f.owner))
    return reach_from(game.board, f.pos, steps, own, enemy, through)


def nearest(board, pos: int, foes: tuple[int, ...]) -> int:
    key = (board.key, pos, foes)
    d = _near_cache.get(key)
    if d is None:
        d = _near_cache[key] = min((board.distance(pos, e) for e in foes), default=0)
    return d


_strike_cache: dict[tuple, frozenset[int]] = {}
_attack_values_cache: dict[tuple, tuple[int, ...]] = {}
_attack_stats_cache: dict[tuple, tuple[float, float]] = {}


def attack_stats(values: tuple[int, ...], delta: int, hp: float) -> tuple[float, float]:
    """(dano neto medio, fraccion de cartas que matan) de un mazo de valores `values` con `delta` = bonus del
    atacante menos la defensa del objetivo, contra `hp` PV. Se repite miles de veces por decision: con cache."""
    key = (values, delta, hp)
    r = _attack_stats_cache.get(key)
    if r is None:
        n = len(values)
        r = _attack_stats_cache[key] = (sum(max(0, v + delta) for v in values) / n,
                                        sum(1 for v in values if v + delta >= hp) / n)
    return r


def strike_spots(board, target_pos: int, ranged: bool) -> frozenset[int]:
    """Casillas desde las que un atacante (cuerpo a cuerpo o a distancia) golpea a quien esta en `target_pos`."""
    key = (board.key, target_pos, ranged)
    r = _strike_cache.get(key)
    if r is None:
        r = _strike_cache[key] = frozenset(s for s in board.spaces if board.can_reach_target(s, target_pos, ranged))
    return r


def attack_values(st: PlayerState, fighter_name: str) -> tuple[int, ...]:
    """Valores de ataque del mazo completo que puede usar `fighter_name`: informacion publica y fija en la partida."""
    key = (st.hero_name, fighter_name)
    v = _attack_values_cache.get(key)
    if v is None:
        v = _attack_values_cache[key] = tuple(c.value for c in st.full_set if c.can_attack and c.usable_by(fighter_name))
    return v


def free_steps(game: Game, f: Fighter) -> int:
    """Movimiento gratis antes de maniobrar (hoy, el de ANUNG UN RAMA; lo especifico del heroe queda aqui)."""
    return ANUNG_FREE_STEPS if f.hero and game.form(f.owner) == ANUNG else 0


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
        if not game.fx.can_move(h):
            out.append((h.fid, h.pos))
            continue
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
        for c in filter(can_be_boost, hand):
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
    ("attack_card", "maneuver_place", "anung_to") con la decision a medias en `partial`."""

    SUBPHASES = ("attack_card", "maneuver_place", "anung_to")

    def __init__(self, game: Game, observer: int, knowledge: Knowledge | None = None,
                 pending: tuple[str, str, Card | None] | None = None, phase: str = "action",
                 weights: EvalWeights | None = None):
        self.game = game.clone()
        self.game.controllers = {0: SearchController(0, self), 1: SearchController(1, self)}
        # lo propio en orden canonico: con la misma semilla la decision no depende del orden real del mazo ni de
        # la mano (lo del rival se sustituye entero al determinizar y no se lee aqui)
        mine = self.game.players[observer]
        mine.hand.sort(key=lambda c: c.card_id)
        mine.deck.sort(key=lambda c: c.card_id)
        self.observer = observer
        self.knowledge = knowledge or Knowledge()
        self.weights = weights or EvalWeights()
        self.pending = pending
        self.phase = phase
        self.partial: tuple = ()
        self.variant: str | None = None
        self._eval: float | None = None
        self._advance()

    # ---------- Protocol ----------
    def clone(self) -> "EngineState":
        c = EngineState.__new__(EngineState)
        c.game = self.game.clone()
        c.game.controllers = {0: SearchController(0, c), 1: SearchController(1, c)}
        c.observer, c.knowledge, c.pending, c.weights = self.observer, self.knowledge, self.pending, self.weights
        c.phase, c.partial, c.variant, c._eval = self.phase, self.partial, self.variant, self._eval
        return c

    def player_to_move(self) -> int:
        if self.pending is not None:
            return self.game.fighters[self.pending[1]].owner
        return self.game.turn

    def turn_owner(self) -> int:
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
                tuple((f.fid, f.pos, f.hp) for f in g.fighters.values() if f.alive),
                tuple(sorted(c.card_id for c in g.players[mover].hand)),
                tuple(f.fid for f in g.fighters.values() if f.alive and not g.fx.can_move(f)))    # pinned by an effect

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
        if self.phase == "maneuver_place":
            return [("place", d, policy) for d, policy in self._placements(p, hero)]
        moves = self._attack_moves(p) + self._scheme_moves(p)
        moves += [("maneuver", c.title if c else None) for c in self._boost_variants(p)]
        return moves

    def apply(self, move) -> None:
        g = self.game
        kind = move[0]
        p = self.player_to_move()
        hand = g.players[p].hand
        self._eval = None
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
            self.phase, self.partial = "maneuver_place", (move[1],)
        elif kind == "place":
            title, = self.partial
            _, d, policy = move
            self.phase, self.partial = "action", ()
            boost = by_title(hand, title) if title is not None else None
            plan = sidekick_plan(g, p, boost.boost if boost else 0, policy, hero_dest=d)
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
                g.use_ability(p, GAZE, g.fighters[move[1]])
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
        if self._eval is None:      # la busqueda pide la hoja desde los dos lados: se calcula una vez
            self._eval = squash(self.weights.slope * self._advantage(0))
        return self._eval if player == 0 else 1.0 - self._eval

    def _advantage(self, p: int, urgent: bool = False) -> float:
        return self._side_value(p, urgent) - self._side_value(1 - p, urgent)

    def _hero_options(self, hero: Fighter) -> frozenset[int]:
        """Donde puede acabar el heroe en la maniobra en curso (con el boost elegido), quedarse incluido."""
        return reach(self.game, hero, hero.move + self._extra()) | {hero.pos}

    def rollout_move(self, rng: random.Random):
        """Jugada legal para el motor; el destino del heroe sale del alcance completo (sin la poda del arbol, que
        cuesta una evaluacion por casilla y en el rollout no compensa)."""
        g = self.game
        if self.phase == "maneuver_place":
            p = g.turn
            dests = sorted(self._hero_options(g.hero(p)))
            d = self._approach_dest(dests, rng) if rng.random() < ROLLOUT_APPROACH_PROB else rng.choice(dests)
            return ("place", d, rng.choice(self._policies(p)))
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
        self._eval = None
        for p, st in enumerate(g.players):
            if p == observer:
                st.deck.sort(key=lambda c: c.card_id)   # el orden del propio mazo tambien es oculto: desde el canonico
                rng.shuffle(st.deck)
                continue
            known = [c for c in self.knowledge.known_in_hand.get(p, ()) if c not in st.discard]
            top = [c for c in self.knowledge.top_of_deck.get(p, ()) if c not in st.discard and c not in known]
            pool = sorted((c for c in st.full_set if c not in st.discard and c not in known and c not in top),
                          key=lambda c: c.card_id)
            if self.pending is not None and self.pending[2] is None and g.fighters[self.pending[0]].owner == p:
                attacker = g.fighters[self.pending[0]]
                legal = [c for c in known if c.can_attack and c.usable_by(attacker.name)]
                if not legal:
                    legal = [c for c in pool if c.can_attack and c.usable_by(attacker.name)]
                # descarte desincronizado (lo publico no explica el ataque): cualquier carta del pool, o del mazo entero
                card = rng.choice(legal or pool or list(st.full_set))
                if card not in known:
                    known.append(card)
                    if card in pool:
                        pool.remove(card)
                self.pending = (self.pending[0], self.pending[1], card)
            rng.shuffle(pool)
            k = max(0, len(st.hand) - len(known))
            maybe = [c for c in self.knowledge.possible_in_hand.get(p, ()) if c in pool]
            if maybe and k:
                # seen once but maybe gone face down: between lo and hi of them are in the hand, the rest back in the pool
                lo, hi = self.knowledge.possible_bounds.get(p, (0, len(maybe)))
                lo = min(lo, k, len(maybe))
                chosen = rng.sample(maybe, rng.randint(lo, min(max(hi, lo), k, len(maybe))))
                others = [c for c in pool if c not in maybe]
                st.hand = known + chosen + others[:k - len(chosen)]
                leftover = others[k - len(chosen):] + [c for c in maybe if c not in chosen]
                rng.shuffle(leftover)
                st.deck = top + leftover
                continue
            st.hand = known + pool[:k]
            st.deck = top + pool[k:]

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
            if self.phase == "maneuver_place":      # sin podar: aqui solo importa si hay eleccion
                hero = g.hero(p)
                if len(self._hero_options(hero)) == 1 and len(self._policies(p)) == 1:
                    self.apply(("place", hero.pos, "stay"))
                return
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
        hand = [c for c in self.game.players[p].hand if can_be_boost(c)]
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

    def _approach_dest(self, dests: list[int], rng: random.Random) -> int:
        """Destino del heroe en el rollout: una casilla desde la que golpea a un rival; si no hay, la mas cercana.
        Sin esto Hellboy nunca se acercaba a Medusa en 6 jugadas y quedar a su alcance no se castigaba."""
        g = self.game
        p = g.turn
        foes = foe_positions(g, p)
        striking = [d for d in dests if d in self._striking_spots(p)]
        if striking:
            return rng.choice(striking)
        return min(dests, key=lambda d: (nearest(g.board, d, foes), d))

    def _striking_spots(self, p: int) -> frozenset[int]:
        g = self.game
        hero = g.hero(p)
        return frozenset().union(*(strike_spots(g.board, e.pos, hero.ranged) for e in g.foes(p)))

    def _policies(self, p: int) -> tuple[str, ...]:
        return SIDEKICK_POLICIES if any(not f.hero for f in self.game.own(p)) else ("stay",)

    def _placements(self, p: int, hero: Fighter) -> list[tuple[int, str]]:
        """(destino del heroe, politica de ayudantes) que entran en el arbol: las `PLACEMENT_KEEP` mejores por la
        evaluacion estatica con todos ya movidos y vista como final de turno (el rival mueve despues), las
        `PLACEMENT_STRIKE_KEEP` mejores desde las que el heroe golpea, y quedarse quieto."""
        g = self.game
        options = sorted(self._hero_options(hero))
        policies = self._policies(p)
        if len(options) * len(policies) <= PLACEMENT_KEEP:
            return [(d, policy) for d in options for policy in policies]
        extra = self._extra()
        side = [f for f in g.own(p) if not f.hero]
        origin = {f.fid: f.pos for f in g.own(p)}
        scored = []
        for d in options:
            for policy in policies:
                plan = sidekick_plan(g, p, extra, policy, hero_dest=d)
                hero.pos = d
                for fid, dest in plan:
                    g.fighters[fid].pos = dest
                scored.append((self._exposure(1 - p, True) - self._exposure(p, True), d, policy))
                for f in side:
                    f.pos = origin[f.fid]
        hero.pos = origin[hero.fid]
        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        spots = self._striking_spots(p)
        striking = [(d, policy) for _, d, policy in scored if d in spots][:PLACEMENT_STRIKE_KEEP]
        keep = {(d, policy) for _, d, policy in scored[:PLACEMENT_KEEP]} | set(striking) | {(hero.pos, "stay")}
        return sorted(keep)

    # ---------- evaluacion ----------
    def _side_value(self, p: int, urgent: bool = False) -> float:
        g, w = self.game, self.weights
        hero = g.hero(p)
        side = [f for f in g.own(p, alive_only=False) if not f.hero]
        side_hp = sum(f.hp for f in side if f.alive) / hero.max_hp      # en PV del heroe: una Harpia vale menos que Lobster
        alive = sum(1 for f in side if f.alive) / len(side) if side else 0.0
        hand = min(len(g.players[p].hand), 7) / 7
        deck = min(len(g.players[p].deck), 10) / 10
        # raiz cuadrada: los primeros PV valen mas que los ultimos; seguir vivo a 3 PV no es casi lo mismo que morir
        return (sqrt(max(hero.hp, 0) / hero.max_hp) + w.sidekicks * side_hp + w.alive * alive + w.hand * hand
                + w.deck * deck - self._exposure(p, urgent))

    def _exposure(self, p: int, urgent: bool) -> float:
        """Lo que la amenaza sobre el heroe de `p` resta a su bando (`threat` ponderada)."""
        w = self.weights
        expected, lethal = self.threat(p, urgent)
        return w.threat * expected + w.lethal * lethal

    def threat(self, victim: int, urgent: bool = False) -> tuple[float, float]:
        """Amenaza sobre el heroe de `victim` en el proximo turno del rival: (dano esperado como fraccion de sus PV
        actuales, probabilidad de que lo maten). Cada rival cuenta si alcanza una casilla de golpeo con su movimiento
        (sin atravesar luchadores de `victim`: los ayudantes en el camino son escudo), con descuento si necesita un
        boost. El coste de un ataque es el valor medio del mazo completo del atacante contra la mejor defensa en
        mano, mas la carta de defensa que gasta. Las acciones limitan: quien ya esta a tiro puede pegar dos veces;
        quien tiene que maniobrar, una. Si el amenazado mueve antes, la amenaza se descuenta, salvo con `urgent`
        (la posicion se mira como final de turno: lo usa la poda de colocaciones)."""
        g, w = self.game, self.weights
        hero = g.hero(victim)
        if not hero.alive:
            return 0.0, 1.0
        attacker = 1 - victim
        hand = g.players[victim].hand
        best_def = max((c.value for c in hand if c.can_defend and c.usable_by(hero.name)), default=0)
        shield = frozenset(g.occupied(victim))
        mates = g.occupied(attacker)
        in_range: list[tuple[float, float]] = []       # (coste por ataque, p. de matar) de quien ya esta a tiro
        after_move: list[tuple[float, float]] = []     # idem de quien llega maniobrando (factor ya aplicado)
        for e in g.foes(victim):
            values = attack_values(g.players[attacker], e.name)
            if not values:
                continue
            spots = strike_spots(g.board, hero.pos, e.ranged)
            own = frozenset(mates - {e.pos})
            steps = e.move + free_steps(g, e)
            if e.pos in spots:
                factor, bucket = 1.0, in_range
            elif reach_from(g.board, e.pos, steps, own, shield) & spots:
                factor, bucket = 1.0, after_move
            elif reach_from(g.board, e.pos, steps + BOOST_STEPS, own, shield) & spots:
                factor, bucket = w.boost_reach, after_move
            else:
                continue
            net, kill = attack_stats(values, g.attack_bonus(e) - best_def, hero.hp)
            bucket.append((factor * (net + (w.defend_card_hp if best_def else 0.0)), factor * kill))
        if not in_range and not after_move:
            return 0.0, 0.0
        actions = g.actions_left if g.turn == attacker else 2
        now_cost = max((c for c, _ in in_range), default=0.0)
        now_kill = max((k for _, k in in_range), default=0.0)
        any_cost = max(c for c, _ in in_range + after_move)
        any_kill = max(k for _, k in in_range + after_move)
        # dos ataques seguidos desde donde esta, o una maniobra y el mejor ataque de todos
        expected = max(actions * now_cost, (actions - 1) * any_cost)
        lethal = max(1 - (1 - now_kill) ** actions, any_kill if actions >= 2 else 0.0)
        urgency = w.victim_moves_first if g.turn == victim and not urgent else 1.0
        # sobre los PV actuales, no los maximos: el mismo golpe esperado pesa mas cuanto menos vida queda
        return min(1.0, expected / hero.hp) * urgency, lethal * urgency
