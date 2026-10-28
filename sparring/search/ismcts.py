"""ISMCTS de observadores multiples (Cowling, Powley y Whitehouse, 2012).

Por que multiples observadores y no uno solo: con un solo arbol (el del bot) los nodos del rival se indexan por
la jugada completa, asi que el rival simulado "ve" la carta de ataque boca abajo del bot y siempre la
contrarresta (strategy fusion). En Unmatched eso haria inutil cualquier ataque flojo con efecto fuerte. Aqui hay
un arbol por jugador y cada uno se indexa por `observe(move, viewer)`: el nodo del defensor es el mismo para
todas las cartas de ataque posibles, como en la mesa.

Cada iteracion: clonar la raiz, determinizar (muestrear lo oculto para el jugador raiz), bajar por los arboles
eligiendo con UCB1 sobre las jugadas disponibles en ESA determinizacion (con conteo de disponibilidad), expandir
una jugada nueva, rollout con `rollout_move` hasta que cambie el turno (tope `rollout_depth`) y retropropagar la
recompensa desde el punto de vista de quien movio en cada arista.

Por que el rollout para al cambiar el turno: con un numero fijo de jugadas la hoja caia sistematicamente al
empezar el turno de quien movio en la raiz, y la evaluacion (que descuenta la amenaza sobre quien va a mover)
premiaba quedarse pegado al rival. Evaluar al final del turno de quien movia es mirar la posicion como lo haria
el rival que va a jugarla; su turno lo explora el arbol, no el rollout.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Hashable

from .protocol import Move, SearchState


@dataclass
class SearchConfig:
    iterations: int | None = None     # None: solo manda el tiempo
    time_budget: float = 1.5          # segundos por decision
    seed: int = 0
    c_uct: float = 0.7                # recompensas en [0, 1]
    rollout_depth: int = 10           # tope de jugadas de rollout; normalmente para antes, al cambiar el turno


@dataclass
class SearchReport:
    move: Move
    iterations: int
    elapsed: float
    visits: dict[Hashable, int] = field(default_factory=dict)
    values: dict[Hashable, float] = field(default_factory=dict)


class Edge:
    __slots__ = ("node", "visits", "reward", "avail")

    def __init__(self):
        self.node = Node()
        self.visits = 0
        self.reward = 0.0
        self.avail = 0


class Node:
    __slots__ = ("edges",)

    def __init__(self):
        self.edges: dict[Hashable, Edge] = {}


class ISMCTS:
    def __init__(self, config: SearchConfig | None = None):
        self.cfg = config or SearchConfig()
        self.trees: dict[int, Node] = {}

    def search(self, root: SearchState, root_player: int) -> tuple[Move, SearchReport]:
        moves = root.legal_moves()
        if not moves:
            raise ValueError("sin jugadas legales en la raiz")
        if len(moves) == 1:
            return moves[0], SearchReport(moves[0], 0, 0.0, {moves[0]: 0})
        rng = random.Random(self.cfg.seed)
        self.trees = {root_player: Node()}
        t0 = time.perf_counter()
        n = 0
        while True:
            self._iterate(root, root_player, rng)
            n += 1
            if self.cfg.iterations is not None and n >= self.cfg.iterations:
                break
            if self.cfg.iterations is None and time.perf_counter() - t0 >= self.cfg.time_budget:
                break
        elapsed = time.perf_counter() - t0
        edges = self.trees[root_player].edges
        # jugada mas visitada; el empate lo rompe el orden de `legal_moves` (estable con la misma semilla)
        best = max(moves, key=lambda m: edges[m].visits if m in edges else -1)
        visits = {m: edges[m].visits for m in moves if m in edges}
        values = {m: edges[m].reward / edges[m].visits for m in moves if m in edges and edges[m].visits}
        return best, SearchReport(best, n, elapsed, visits, values)

    def principal_variation(self, player: int, start: Hashable | None = None, min_visits: int = 1) -> list[Hashable]:
        """Claves mas visitadas desde la raiz del arbol de `player`, mientras haya aristas con visitas suficientes.
        Con `start` (la jugada que devolvio `search`) la primera arista es esa, asi un empate de visitas en la raiz
        no sigue otra linea. Sirve para completar una accion descompuesta en subjugadas."""
        out = []
        node = self.trees.get(player)
        if start is not None and node is not None:
            edge = node.edges.get(start)
            if edge is None:
                return []
            out.append(start)
            node = edge.node
        while node is not None and node.edges:
            key, edge = max(node.edges.items(), key=lambda kv: kv[1].visits)
            if edge.visits < min_visits:
                break
            out.append(key)
            node = edge.node
        return out

    def _iterate(self, root: SearchState, root_player: int, rng: random.Random) -> None:
        s = root.clone()
        s.determinize(root_player, rng)
        cursor = {p: tree for p, tree in self.trees.items()}
        path: list[tuple[Edge, int]] = []
        applied: list[tuple[Move, int]] = []
        while not s.is_terminal():
            mover = s.player_to_move()
            if mover not in cursor:
                # jugador nuevo: su arbol nace aqui y su cursor repite lo ya jugado tal como el lo ve
                node = self.trees.setdefault(mover, Node())
                for m, who in applied:
                    edge = node.edges.setdefault(s.observe(m, mover), Edge())
                    path.append((edge, who))
                    node = edge.node
                cursor[mover] = node
            node = cursor[mover]
            moves = s.legal_moves()
            untried = [m for m in moves if m not in node.edges]
            for m in moves:
                if m in node.edges:
                    node.edges[m].avail += 1
            if untried:
                move, expanded = rng.choice(untried), True
            else:
                move, expanded = max(moves, key=lambda m: self._ucb(node.edges[m])), False
            for p in list(cursor):
                key = s.observe(move, p)
                edge = cursor[p].edges.get(key)
                if edge is None:
                    edge = cursor[p].edges[key] = Edge()
                path.append((edge, mover))
                cursor[p] = edge.node
            applied.append((move, mover))
            s.apply(move)
            if expanded:
                break
        depth = 0
        owner = s.turn_owner() if not s.is_terminal() else None
        while not s.is_terminal() and depth < self.cfg.rollout_depth and s.turn_owner() == owner:
            s.apply(s.rollout_move(rng))
            depth += 1
        rewards: dict[int, float] = {}
        for edge, mover in path:
            if mover not in rewards:
                rewards[mover] = s.evaluate(mover)
            edge.visits += 1
            edge.reward += rewards[mover]

    def _ucb(self, e: Edge) -> float:
        return e.reward / e.visits + self.cfg.c_uct * math.sqrt(math.log(max(e.avail, 1)) / e.visits)
