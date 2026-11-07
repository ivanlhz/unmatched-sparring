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
                 hazards: dict[tuple[int, int], int] | None = None):
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
        self._adj_dist: dict[int, dict[int, int]] | None = None     # built on first use: only a hero with a reach in spaces asks

    @classmethod
    def load(cls, key_or_path: str | Path) -> "Board":
        path = Path(key_or_path)
        if not path.suffix:
            path = DATA_DIR / "maps" / f"{key_or_path}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
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
        return cls(raw["key"], raw["name"], spaces, adj, raw["starts"], passages, bonuses, one_way, hazards)

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
                    hurt: bool = False) -> list[tuple[int, int]]:
        """The hazard edge the mover pays for on the way assumed from src to dst: a fighter takes hazard damage at most
        once per turn, so only the FIRST hazard edge of the path counts (the list holds that one edge, or is empty).
        `hurt`: the fighter already took hazard damage this turn, so nothing is charged.
        The mover is assumed to take the path of least damage among those of at most `steps` steps (`None`: the
        shortest length, which is all a human's move on the table tells: only where the piece started and ended), the
        shortest of those on a tie; it cannot enter `blocked` spaces. Empty when the board has no hazards or there is no path."""
        if not self.hazards or src == dst or hurt:
            return []
        cap = steps
        if cap is None:                          # the shortest way the blockers leave open
            seen, frontier, cap = {src}, [src], 0
            while frontier and dst not in seen:
                cap += 1
                frontier = [n for node in frontier for n in sorted(self.moves[node])
                            if n not in seen and n not in blocked and not seen.add(n)]
            if dst not in seen:
                return []
        # state: (space, already paid on this walk) -> (damage, state it came from, hazard edge paid on the way in)
        State = tuple[int, bool]
        layers: list[dict[State, tuple[int, State | None, tuple[int, int] | None]]] = [{(src, False): (0, None, None)}]
        for _ in range(cap):
            nxt: dict[State, tuple[int, State | None, tuple[int, int] | None]] = {}
            for (node, paid), (cost, _, _) in layers[-1].items():
                for n in sorted(self.moves[node]):
                    if n in blocked:
                        continue
                    edge = edge_key(node, n)
                    pays = edge in self.hazards and not paid
                    key = (n, paid or pays)
                    c = cost + (self.hazards[edge] if pays else 0)
                    if key not in nxt or c < nxt[key][0]:
                        nxt[key] = (c, (node, paid), edge if pays else None)
            layers.append(nxt)
        best = min(((layer[(dst, p)][0], k, p) for k, layer in enumerate(layers) for p in (False, True) if (dst, p) in layer),
                   default=None)
        if best is None:
            return []
        state = (dst, best[2])
        for k in range(best[1], 0, -1):
            _, prev, edge = layers[k][state]
            if edge is not None:
                return [edge]
            state = prev
        return []

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

    def reachable(self, start: int, steps: int, own: set[int], enemy: set[int], through_enemies: bool = False) -> set[int]:
        """Spaces where it can end (moving along adjacency and passages): passes through own fighters, not rivals (unless an effect says so), ends on an empty one."""
        seen = {start: 0}
        q = deque([start])
        while q:
            cur = q.popleft()
            if seen[cur] == steps:
                continue
            for n in sorted(self.moves[cur]):
                if n in seen or (n in enemy and not through_enemies):
                    continue
                seen[n] = seen[cur] + 1
                q.append(n)
        return {s for s in seen if s != start and s not in own and s not in enemy}

    def nearest_free(self, origin: int, taken: set[int], zone_of: int | None = None) -> int:
        """Nearest free space to `origin`; with `zone_of`, only spaces that share a zone with it."""
        free = [s for s in self.spaces if s not in taken]
        if zone_of is not None:
            same = [s for s in free if self.share_zone(zone_of, s)]
            free = same or free
        return min(free, key=lambda s: (self.span(origin, s), s))
