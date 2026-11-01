"""Multiple-observer ISMCTS (Cowling, Powley and Whitehouse, 2012).

Why multiple observers and not just one: with a single tree (the bot's) the rival's nodes are indexed by
the whole move, so the simulated rival "sees" the bot's face-down attack card and always
counters it (strategy fusion). In Unmatched that would make any weak attack with a strong effect useless. Here there is
one tree per player and each is indexed by `observe(move, viewer)`: the defender's node is the same for
all the possible attack cards, as at the table.

Each iteration: clone the root, determinize (sample what is hidden for the root player), descend the trees
choosing with UCB1 over the moves available in THAT determinization (with availability counting), expand
a new move, rollout with `rollout_move` until the turn changes (cap `rollout_depth`) and backpropagate the
reward from the point of view of whoever moved on each edge.

Why the rollout stops when the turn changes: with a fixed number of moves the leaf systematically landed at the
start of the turn of whoever moved at the root, and the evaluation (which discounts the threat on whoever is about to move)
rewarded staying glued to the rival. Evaluating at the end of the mover's turn is looking at the position as the
rival who is going to play it would; its turn is explored by the tree, not by the rollout.
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
    iterations: int | None = None     # None: only time rules
    time_budget: float = 1.5          # seconds per decision
    seed: int = 0
    c_uct: float = 0.7                # rewards in [0, 1]
    rollout_depth: int = 10           # cap on rollout moves; normally it stops earlier, when the turn changes


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
            raise ValueError("no legal moves at the root")
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
        # most visited move; a tie is broken by the order of `legal_moves` (stable with the same seed)
        best = max(moves, key=lambda m: edges[m].visits if m in edges else -1)
        visits = {m: edges[m].visits for m in moves if m in edges}
        values = {m: edges[m].reward / edges[m].visits for m in moves if m in edges and edges[m].visits}
        return best, SearchReport(best, n, elapsed, visits, values)

    def principal_variation(self, player: int, start: Hashable | None = None, min_visits: int = 1) -> list[Hashable]:
        """Most visited keys from the root of `player`'s tree, as long as there are edges with enough visits.
        With `start` (the move `search` returned) the first edge is that one, so a tie of visits at the root
        does not follow another line. Used to complete an action decomposed into sub-moves."""
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
                # new player: its tree is born here and its cursor repeats what was already played as it sees it
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
