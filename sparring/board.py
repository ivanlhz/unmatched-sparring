from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Space:
    id: int
    local: tuple[float, float]
    zones: frozenset[str]


@dataclass(frozen=True)
class MapEntry:
    """One map of the official save (data/maps/catalog.json). `status`: supported (data verified), excluded (needs
    tokens or doors: `reason`), unverified (extracted from the picture and waiting for a person to confirm it in
    tools/map_checker.py) or unavailable (its data did not pass the checks of tools/import_map.py)."""
    key: str
    name: str
    image_key: str          # the SHA-1 the board's image URL ends with: how a board on the table is recognised
    status: str
    reason: str | None = None


def catalog() -> list[MapEntry]:
    raw = json.loads((DATA_DIR / "maps" / "catalog.json").read_text(encoding="utf-8"))
    return [MapEntry(e["key"], e["name"], e["imageKey"], e["status"], e.get("reason")) for e in raw]


MAX_HAZARD = 3      # the largest damage a hazard edge may deal (the map checker accepts the same)


def edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


class Board:
    def __init__(self, key: str, name: str, spaces: list[Space], adj: dict[int, set[int]], starts: dict[str, int],
                 passages: tuple[tuple[int, ...], ...] = (),
                 bonuses: dict[tuple[int, int], int] | None = None,
                 one_way: tuple[tuple[int, int], ...] = (),
                 hazards: dict[tuple[int, int], int] | None = None,
                 center: tuple[int, ...] = ()):   # center: an override of the computed one (rarely needed)
        self.key = key
        self.name = name
        self.guid: str | None = None        # the board's GUID on the table, once found (set by the start-up)
        self.spaces = {s.id: s for s in spaces}
        self.adj = adj                      # true adjacency: melee, "adjacent" effects
        self.passages = passages            # groups of spaces (secret passages) a fighter can move between in one step
        self.moves = {s: set(n) for s, n in adj.items()}      # the movement graph (directed): adjacency plus passage links, minus one-way edges walked backwards
        for group in passages:
            for a in group:
                self.moves[a].update(b for b in group if b != a)
        self.bonuses = bonuses or {}        # (from, to) -> attack bonus of a fighter on `from` hitting one on `to` (stairs)
        self.hazards = hazards or {}        # (low id, high id) -> damage a fighter takes the first time in a turn it crosses that edge (once per turn in all, not per edge)
        self.one_way = one_way              # (from, to): moving is allowed from -> to only; still adjacent both ways
        for a, b in one_way:
            self.moves[b].discard(a)
        self.starts = starts
        self._dist = {s: self._bfs(s) for s in self.spaces}
        # eccentricity: the farthest another space is by walking (99 if one cannot be reached); the center is where it is smallest,
        # i.e. where any space is easiest to reach. Several spaces can tie and they need not touch. The map's own "center" replaces it.
        self.eccentricity = {s: max((self._dist[s].get(t, 99) for t in self.spaces), default=0) for s in self.spaces}
        low = min(self.eccentricity.values(), default=0)
        self.center: tuple[int, ...] = tuple(center) or tuple(sorted(s for s, e in self.eccentricity.items() if e == low))
        self._adj_dist: dict[int, dict[int, int]] | None = None     # built on first use: only a hero with a reach in spaces asks

    @classmethod
    def load(cls, key_or_path: str | Path) -> "Board":
        path = Path(key_or_path)
        if not path.suffix:
            path = DATA_DIR / "maps" / f"{key_or_path}.json"
        return cls.from_raw(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_raw(cls, raw: dict) -> "Board":
        spaces = [Space(s["id"], tuple(s["local"]), frozenset(s["zones"])) for s in raw["spaces"]]
        adj: dict[int, set[int]] = {s.id: set() for s in spaces}
        for s in raw["spaces"]:
            for n in s["adj"]:
                adj[s["id"]].add(n)
                adj[n].add(s["id"])
        passages = tuple(tuple(g) for g in raw.get("passages", ()))
        bonuses = {(b["from"], b["to"]): b["value"] for b in raw.get("bonuses", ())}
        one_way = tuple((a, b) for a, b in raw.get("one_way", ()))
        hazards: dict[tuple[int, int], int] = {}
        for h in raw.get("hazards", ()):
            edge, damage = h.get("edge"), h.get("damage")
            if (not isinstance(edge, list) or len(edge) != 2 or not all(type(v) is int for v in edge)
                    or type(damage) is not int or not 1 <= damage <= MAX_HAZARD
                    or edge[1] not in adj.get(edge[0], ()) or edge_key(*edge) in hazards):
                raise ValueError(f"{raw['key']}: bad hazard {h}")
            hazards[edge_key(*edge)] = damage
        center = tuple(raw.get("center", ()))
        if not all(type(c) is int and c in adj for c in center) or len(set(center)) != len(center):
            raise ValueError(f"{raw['key']}: bad center {list(center)}")
        return cls(raw["key"], raw["name"], spaces, adj, raw["starts"], passages, bonuses, one_way, hazards, center)

    def _bfs(self, src: int) -> dict[int, int]:
        return self._bfs_over(src, self.moves)

    @staticmethod
    def _bfs_over(src: int, graph: dict[int, set[int]]) -> dict[int, int]:
        dist = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for n in graph[cur]:
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    q.append(n)
        return dist

    def distance(self, a: int, b: int) -> int:
        """Steps a fighter needs to walk from a to b (99: it cannot)."""
        return self._dist[a].get(b, 99)

    def span(self, a: int, b: int) -> int:
        """Spaces between a and b whichever way they are walked (descriptions, nearest free space): `distance` is
        directional once the board has one-way edges."""
        return min(self.distance(a, b), self.distance(b, a))

    def adjacent(self, a: int, b: int) -> bool:
        return b in self.adj[a]

    def attack_bonus(self, a: int | None, b: int | None) -> int:
        """Bonus to the attack value of a fighter on `a` hitting one on `b` (high ground); directional, attack only."""
        return self.bonuses.get((a, b), 0)

    def hazard_path(self, src: int, dst: int, steps: int | None, blocked: frozenset[int] = frozenset(),
                    hurt: bool = False, free: frozenset[int] = frozenset()) -> list[tuple[int, int]]:
        """The hazard edge the mover pays for on the way assumed from src to dst: a fighter takes hazard damage at most
        once per turn, so only the FIRST hazard edge of the path counts (the list holds that one edge, or is empty).
        `hurt`: the fighter already took hazard damage this turn, so nothing is charged. `free`: spaces that cost no step to enter
        (John Henry's track tokens): the walk still crosses their edges, so the hazards on them count.
        The mover is assumed to take the path of least damage among those of at most `steps` steps (`None`: the
        shortest length, which is all a human's move on the table tells: only where the piece started and ended), the
        shortest of those on a tie; it cannot enter `blocked` spaces. Empty when the board has no hazards or there is no path."""
        if not self.hazards or src == dst or hurt:
            return []
        cap = steps
        if cap is None:                          # the cheapest way the blockers leave open
            cap = self.walk_cost(src, dst, free, blocked)
            if cap is None:
                return []
        # state: (space, already paid on this walk) -> (damage, (layer, state) it came from, hazard edge paid on the way in);
        # layer k holds the walks that spent k steps: entering a `free` space spends none and stays in the layer
        State = tuple[int, bool]
        layers: list[dict[State, tuple[int, tuple[int, State] | None, tuple[int, int] | None]]] = []

        def relax(k: int, layer: dict, frontier: list[State]) -> None:
            """Lets the walks of layer k enter free spaces (no step spent) until nothing gets cheaper."""
            while frontier:
                node, paid = frontier.pop()
                cost = layer[(node, paid)][0]
                for n in sorted(self.moves[node]):
                    if n in blocked or n not in free:
                        continue
                    edge = edge_key(node, n)
                    pays = edge in self.hazards and not paid
                    key = (n, paid or pays)
                    c = cost + (self.hazards[edge] if pays else 0)
                    if key not in layer or c < layer[key][0]:
                        layer[key] = (c, (k, (node, paid)), edge if pays else None)
                        frontier.append(key)

        first = {(src, False): (0, None, None)}
        relax(0, first, [(src, False)])
        layers.append(first)
        for k in range(1, cap + 1):
            nxt: dict[State, tuple[int, tuple[int, State] | None, tuple[int, int] | None]] = {}
            for (node, paid), (cost, _, _) in layers[-1].items():
                for n in sorted(self.moves[node]):
                    if n in blocked or n in free:
                        continue
                    edge = edge_key(node, n)
                    pays = edge in self.hazards and not paid
                    key = (n, paid or pays)
                    c = cost + (self.hazards[edge] if pays else 0)
                    if key not in nxt or c < nxt[key][0]:
                        nxt[key] = (c, (k - 1, (node, paid)), edge if pays else None)
            relax(k, nxt, list(nxt))
            layers.append(nxt)
        best = min(((layer[(dst, p)][0], k, p) for k, layer in enumerate(layers) for p in (False, True) if (dst, p) in layer),
                   default=None)
        if best is None:
            return []
        k, state = best[1], (dst, best[2])
        while True:
            _, prev, edge = layers[k][state]
            if edge is not None:
                return [edge]
            if prev is None:
                return []
            k, state = prev

    def walk_cost(self, src: int, dst: int, free: frozenset[int] = frozenset(), blocked: frozenset[int] = frozenset()) -> int | None:
        """Steps the cheapest walk from src to dst spends when entering a `free` space costs nothing (John Henry's tracks); None if
        `blocked` spaces cut every way. With no free spaces it is the plain distance over the walkable graph."""
        return self.step_costs(src, free, blocked).get(dst)

    def step_costs(self, src: int, free: frozenset[int], blocked: frozenset[int]) -> dict[int, int]:
        """0-1 BFS: the step cost of the cheapest walk from src to each space (entering a free space spends none)."""
        cost = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for n in sorted(self.moves[cur]):
                if n in blocked:
                    continue
                c = cost[cur] + (0 if n in free else 1)
                if n not in cost or c < cost[n]:
                    cost[n] = c
                    q.appendleft(n) if n in free else q.append(n)
        return cost

    def track_route(self, src: int, dst: int, free: frozenset[int], blocked: frozenset[int] = frozenset()) -> frozenset[int]:
        """The `free` spaces a walk from src to dst enters: of the cheapest walks (entering a free space costs nothing) the one through
        the most free spaces, each counted once (what a table that only shows where the piece started and ended is given the benefit
        of: John Henry's paths). Empty when there is no walk or no free space on it."""
        back = self.costs_to(dst, free, blocked)
        need = back.get(src)
        if need is None or not free:
            return frozenset()
        best: list[frozenset[int]] = [frozenset()]
        budget = [20000]

        def walk(node: int, spent: int, seen: tuple[int, ...], used: frozenset[int]) -> None:
            budget[0] -= 1
            if budget[0] < 0:
                return
            if node == dst:
                if spent == need and len(used) > len(best[0]):
                    best[0] = used
                return
            for n in sorted(self.moves[node]):
                if n in seen or n in blocked or n not in back:
                    continue
                c = spent + (0 if n in free else 1)
                if c + back[n] > need:
                    continue
                walk(n, c, seen + (n,), used | {n} if n in free else used)

        walk(src, 0, (src,), frozenset())
        return best[0]

    def edge_route(self, src: int, dst: int, free: frozenset[int], blocked: frozenset[int] = frozenset(),
                   known: frozenset[tuple[int, int]] = frozenset()) -> frozenset[tuple[int, int]]:
        """The paths (edges, as `(low, high)` like the hazards) a walk from src to dst crosses: of the cheapest walks (entering a free
        space costs nothing, no space twice) the one through the most edges not in `known`, the benefit a table that only shows where the
        piece started and ended is given (John Henry's "different paths"). Empty when there is no walk or src == dst."""
        back = self.costs_to(dst, free, blocked)
        need = back.get(src)
        if need is None or src == dst:
            return frozenset()
        best: list = [None, -1]
        budget = [20000]

        def walk(node: int, spent: int, seen: tuple[int, ...], edges: frozenset[tuple[int, int]]) -> None:
            budget[0] -= 1
            if budget[0] < 0:
                return
            if node == dst:
                gain = len(edges - known)
                if spent == need and gain > best[1]:
                    best[0], best[1] = edges, gain
                return
            for n in sorted(self.moves[node]):
                if n in seen or n in blocked or n not in back:
                    continue
                c = spent + (0 if n in free else 1)
                if c + back[n] > need:
                    continue
                walk(n, c, seen + (n,), edges | {edge_key(node, n)})

        walk(src, 0, (src,), frozenset())
        return best[0] or frozenset()

    def most_paths(self, src: int, dst: int, free: frozenset[int], blocked: frozenset[int], budget: int,
                   known: frozenset[tuple[int, int]] = frozenset(), cap: int | None = None,
                   avoid: frozenset[tuple[int, int]] = frozenset()) -> frozenset[tuple[int, int]]:
        """The new paths (edges `(low, high)` not in `known`) of the walk from src to dst, at most `budget` steps (entering a free space
        costs nothing), that crosses the most of them. Unlike `edge_route` a space may be entered again: a loop over free spaces (a
        triangle of track tokens) adds its edges for nothing, and src == dst is a walk too. The search stops at `cap` new edges (the
        rest of the way is then the cheapest one). The edges of `avoid` are never crossed (hazards nobody pays for). Empty when dst
        cannot be reached within the budget."""
        return self.most_paths_walk(src, dst, free, blocked, budget, known, cap, avoid)[0]

    def most_paths_walk(self, src: int, dst: int, free: frozenset[int], blocked: frozenset[int], budget: int,
                        known: frozenset[tuple[int, int]] = frozenset(), cap: int | None = None,
                        avoid: frozenset[tuple[int, int]] = frozenset()) -> tuple[frozenset[tuple[int, int]], int | None]:
        """`most_paths` and the steps that walk spends (None: no walk within the budget)."""
        back = self.costs_to(dst, free, blocked)
        if back.get(src) is None or back[src] > budget:
            return frozenset(), None
        best: list = [frozenset(), None]
        seen: set = set()
        stack = [(src, 0, frozenset())]
        work = 200000
        while stack and work > 0:
            work -= 1
            node, spent, got = stack.pop()
            if (node, spent, got) in seen:
                continue
            seen.add((node, spent, got))
            if cap is not None and len(got) >= cap:
                return got, spent + back[node]           # enough: the rest of the way is the cheapest one, its paths not needed
            if node == dst and (best[1] is None or len(got) > len(best[0])):
                best[0], best[1] = got, spent
            for n in sorted(self.moves[node]):
                if n in blocked or n not in back or edge_key(node, n) in avoid:
                    continue
                c = spent + (0 if n in free else 1)
                if c + back[n] > budget:
                    continue
                e = edge_key(node, n)
                stack.append((n, c, got if e in known else got | {e}))
        return best[0], best[1]

    def costs_to(self, dst: int, free: frozenset[int], blocked: frozenset[int]) -> dict[int, int]:
        """The step cost of the cheapest walk from each space to dst (the reverse of `step_costs`): a step onto a free space costs nothing."""
        cost = {dst: 0}
        q = deque([dst])
        while q:
            cur = q.popleft()
            gain = 0 if cur in free else 1           # stepping onto `cur` costs this
            for p in sorted(s for s in self.spaces if cur in self.moves[s]):
                if p in blocked:
                    continue
                c = cost[cur] + gain
                if p not in cost or c < cost[p]:
                    cost[p] = c
                    q.appendleft(p) if gain == 0 else q.append(p)
        return cost

    def zones(self, s: int) -> frozenset[str]:
        return self.spaces[s].zones

    def share_zone(self, a: int, b: int) -> bool:
        return bool(self.spaces[a].zones & self.spaces[b].zones)

    def spaces_apart(self, a: int, b: int) -> int:
        """Spaces between a and b counted along the printed adjacency (passages and one-way edges are about walking, not
        about distance): what a reach in spaces measures. 99 when the map has no such path."""
        if self._adj_dist is None:
            self._adj_dist = {s: self._bfs_over(s, self.adj) for s in self.spaces}
        return self._adj_dist[a].get(b, 99)

    def can_reach_target(self, a: int, b: int, ranged: bool, reach: int = 0) -> bool:
        """Melee: adjacent. Ranged: adjacent or shares at least one zone. `reach` > 0 (Bullseye: 5) adds anyone up to that many
        spaces away, whatever the zones: the ranged zone rule still holds."""
        if a == b:
            return False
        if self.adjacent(a, b) or (ranged and self.share_zone(a, b)):
            return True
        return bool(reach) and self.spaces_apart(a, b) <= reach

    def reachable(self, start: int, steps: int, own: set[int], enemy: set[int], through_enemies: bool = False,
                  passable: frozenset[int] | set[int] = frozenset(), free: frozenset[int] | set[int] = frozenset()) -> set[int]:
        """Spaces where it can end (moving along adjacency and passages): passes through own fighters, not rivals (unless an effect says so), ends on an empty one.
        `passable`: the rival spaces it may cross all the same (Tomoe Gozen moves through sidekicks), never end on.
        `free`: spaces that are not counted when entered (John Henry's track tokens): a walk may enter any number of them."""
        seen = {start: 0}
        q = deque([start])
        while q:
            cur = q.popleft()
            for n in sorted(self.moves[cur]):
                if n in enemy and not through_enemies and n not in passable:
                    continue
                c = seen[cur] + (0 if n in free else 1)
                if c > steps or (n in seen and seen[n] <= c):
                    continue
                seen[n] = c
                q.appendleft(n) if n in free else q.append(n)
        return {s for s in seen if s != start and s not in own and s not in enemy}

    def nearest_free(self, origin: int, taken: set[int], zone_of: int | None = None) -> int:
        """Nearest free space to `origin`; with `zone_of`, only spaces that share a zone with it."""
        free = [s for s in self.spaces if s not in taken]
        if zone_of is not None:
            same = [s for s in free if self.share_zone(zone_of, s)]
            free = same or free
        return min(free, key=lambda s: (self.span(origin, s), s))
