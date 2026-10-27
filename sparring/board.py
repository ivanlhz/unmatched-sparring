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


class Board:
    def __init__(self, key: str, name: str, spaces: list[Space], adj: dict[int, set[int]], starts: dict[str, int]):
        self.key = key
        self.name = name
        self.spaces = {s.id: s for s in spaces}
        self.adj = adj
        self.starts = starts
        self._dist = {s: self._bfs(s) for s in self.spaces}

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
        return cls(raw["key"], raw["name"], spaces, adj, raw["starts"])

    def _bfs(self, src: int) -> dict[int, int]:
        dist = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for n in self.adj[cur]:
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    q.append(n)
        return dist

    def distance(self, a: int, b: int) -> int:
        return self._dist[a].get(b, 99)

    def adjacent(self, a: int, b: int) -> bool:
        return b in self.adj[a]

    def zones(self, s: int) -> frozenset[str]:
        return self.spaces[s].zones

    def share_zone(self, a: int, b: int) -> bool:
        return bool(self.spaces[a].zones & self.spaces[b].zones)

    def can_reach_target(self, a: int, b: int, ranged: bool) -> bool:
        """Melee: adyacente. Alcance: adyacente o comparte al menos una zona."""
        if a == b:
            return False
        return self.adjacent(a, b) or (ranged and self.share_zone(a, b))

    def reachable(self, start: int, steps: int, own: set[int], enemy: set[int], through_enemies: bool = False) -> set[int]:
        """Casillas donde puede terminar: atraviesa propios, no rivales (salvo efecto), termina en vacía."""
        seen = {start: 0}
        q = deque([start])
        while q:
            cur = q.popleft()
            if seen[cur] == steps:
                continue
            for n in sorted(self.adj[cur]):
                if n in seen or (n in enemy and not through_enemies):
                    continue
                seen[n] = seen[cur] + 1
                q.append(n)
        return {s for s in seen if s != start and s not in own and s not in enemy}

    def nearest_free(self, origin: int, taken: set[int], zone_of: int | None = None) -> int:
        """Casilla libre mas cercana a `origin`; con `zone_of`, solo casillas que comparten zona con ella."""
        free = [s for s in self.spaces if s not in taken]
        if zone_of is not None:
            same = [s for s in free if self.share_zone(zone_of, s)]
            free = same or free
        return min(free, key=lambda s: (self.distance(origin, s), s))
