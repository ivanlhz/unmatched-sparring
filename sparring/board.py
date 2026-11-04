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


class Board:
    def __init__(self, key: str, name: str, spaces: list[Space], adj: dict[int, set[int]], starts: dict[str, int],
                 passages: tuple[tuple[int, ...], ...] = (),
                 bonuses: dict[tuple[int, int], int] | None = None,
                 one_way: tuple[tuple[int, int], ...] = ()):
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
        self.one_way = one_way              # (from, to): moving is allowed from -> to only; still adjacent both ways
        for a, b in one_way:
            self.moves[b].discard(a)
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
        passages = tuple(tuple(g) for g in raw.get("passages", ()))
        bonuses = {(b["from"], b["to"]): b["value"] for b in raw.get("bonuses", ())}
        one_way = tuple((a, b) for a, b in raw.get("one_way", ()))
        return cls(raw["key"], raw["name"], spaces, adj, raw["starts"], passages, bonuses, one_way)

    def _bfs(self, src: int) -> dict[int, int]:
        dist = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for n in self.moves[cur]:
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

    def zones(self, s: int) -> frozenset[str]:
        return self.spaces[s].zones

    def share_zone(self, a: int, b: int) -> bool:
        return bool(self.spaces[a].zones & self.spaces[b].zones)

    def can_reach_target(self, a: int, b: int, ranged: bool) -> bool:
        """Melee: adjacent. Ranged: adjacent or shares at least one zone."""
        if a == b:
            return False
        return self.adjacent(a, b) or (ranged and self.share_zone(a, b))

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
