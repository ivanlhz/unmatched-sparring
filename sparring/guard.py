"""Shared by both AIs: where a sidekick stands to block the rivals' paths to its own hero ("guard"), and the reach
primitives that ask it (cached: the same positions repeat thousands of times within a search). `path_steps` and
`hero_shielded` let the heuristic value that block: the rival's walk around the fighters in its way."""
from __future__ import annotations

from .state import ANUNG, Fighter, Game

ANUNG_FREE_STEPS = 2          # free movement of ANUNG UN RAMA at the start of the turn (see MedusaAI)

_reach_cache: dict[tuple, frozenset[int]] = {}


def reach_from(board, pos: int, steps: int, own: frozenset[int], enemy: frozenset[int],
               through: bool = False) -> frozenset[int]:
    """`Board.reachable` with a cache: within a search the same positions repeat thousands of times."""
    key = (board.key, pos, steps, own, enemy, through)
    r = _reach_cache.get(key)
    if r is None:
        r = _reach_cache[key] = frozenset(board.reachable(pos, steps, set(own), set(enemy), through))
    return r


_strike_cache: dict[tuple, frozenset[int]] = {}


def strike_spots(board, target_pos: int, ranged: bool, reach: int = 0) -> frozenset[int]:
    """Spaces from which an attacker (melee, ranged or with a reach in spaces) strikes whoever is at `target_pos`."""
    key = (board.key, target_pos, ranged, reach)
    r = _strike_cache.get(key)
    if r is None:
        r = _strike_cache[key] = frozenset(s for s in board.spaces if board.can_reach_target(s, target_pos, ranged, reach))
    return r


_boosts_cache: dict[str, tuple[tuple[int, int], ...]] = {}


def boost_reach(game: Game, player: int) -> int:
    """Most extra steps `player` can buy with a maneuver boost: the biggest boost value among its cards not played yet (its
    whole set minus its public piles: discard, tucked, removed, and its ONGOING card in play), plus what an effect in play adds to its BOOST values
    (Advisor to the king: +1). Public information: its hand is never read. 0 once no card is left, or none that boosts."""
    st = game.players[player]
    by_value = _boosts_cache.get(st.hero_name)
    if by_value is None:
        counts: dict[int, int] = {}
        for c in st.full_set:
            counts[c.boost] = counts.get(c.boost, 0) + 1
        by_value = _boosts_cache[st.hero_name] = tuple(sorted(counts.items(), reverse=True))
    played: dict[int, int] = {}
    in_play = game.fx.ongoing_card_id(player)
    for c in st.gone + [c for c in st.full_set if c.card_id == in_play and c not in st.gone]:
        played[c.boost] = played.get(c.boost, 0) + 1
    best = next((boost for boost, copies in by_value if copies > played.get(boost, 0)), 0)
    return best + game.fx.boost_bonus(player) if best else 0


def free_steps(game: Game, f: Fighter) -> int:
    """Free movement before maneuvering (today, ANUNG UN RAMA's; what is specific to the hero stays here)."""
    return (ANUNG_FREE_STEPS if f.hero and game.form(f.owner) == ANUNG else 0) + game.maneuver_bonus(f.owner)


_guard_cache: dict[tuple, int] = {}
GUARD_CACHE_MAX = 50_000
_path_cache: dict[tuple, int] = {}


def path_steps(board, start: int, targets: frozenset[int], blocked: frozenset[int], cap: int) -> int:
    """Fewest steps from `start` to any of `targets` without entering a `blocked` space (the fighters of the side the
    walker attacks: it cannot cross them); `cap` when none is nearer than that. Memoized by position."""
    if start in targets:
        return 0
    key = (board.key, start, targets, blocked, cap)
    best = _path_cache.get(key)
    if best is not None:
        return best
    best = cap
    seen, frontier, depth = {start}, [start], 0
    while frontier and best == cap and depth + 1 < cap:
        depth += 1
        nxt = []
        for cur in frontier:
            for n in board.moves[cur]:
                if n in seen or n in blocked:
                    continue
                if n in targets:
                    best = depth
                seen.add(n)
                nxt.append(n)
        frontier = nxt
    if len(_path_cache) >= GUARD_CACHE_MAX:
        _path_cache.clear()
    _path_cache[key] = best
    return best


def hero_shielded(board, foe_pos: int, ranged: bool, reach: int, hero_pos: int, sidekicks: frozenset[int],
                  own: frozenset[int], occupied: frozenset[int], cap: int) -> bool:
    """The sidekicks (at `sidekicks`, part of `own`: the spaces of the hero's side the rival walks around) make the rival
    at `foe_pos` walk farther to a space it strikes the hero from: they stand on its strike spots or in its way. `occupied`
    is every taken space; the walk with the sidekicks is compared with the same walk had they not been on the board."""
    if not sidekicks:
        return False
    spots = strike_spots(board, hero_pos, ranged, reach)
    taken, bare = occupied - {foe_pos}, occupied - sidekicks - {foe_pos}
    return (path_steps(board, foe_pos, spots - taken, own, cap) >
            path_steps(board, foe_pos, spots - bare, own - sidekicks, cap))


def guard_dest(game: Game, hero_pos: int, options, fid: str, own: dict[str, int]) -> int:
    """Space (staying included) where the sidekick `fid` best blocks the rivals' paths to its hero at `hero_pos`.
    `own` has every fighter of the side at the position it will have (the hero already moved, the sidekicks before
    this one too), so with several sidekicks each next one covers a path still open. A rival counts as in
    `EngineState.threat`: it reaches a striking space with its movement, or only with a boost (the biggest one its side still
    has to play, `boost_reach`: with none left it cannot boost), or the fighters in the way
    stop it; the strike spots it can still reach break ties between spaces that block the same rivals. Least exposure
    wins; on a tie the sidekick stays where it is, else the space nearest the hero, then the lowest id.
    Only a space some rival can walk through (boost included) changes anything: the rest all share the exposure of
    leaving the way as it is, so they are only compared among themselves by distance. Memoized by position."""
    board, me = game.board, game.fighters[fid].owner
    mates = frozenset(game.occupied(1 - me))
    others = frozenset(v for k, v in own.items() if k != fid)
    cands = frozenset(options) | {own[fid]}
    bonus, anung = game.maneuver_bonus(1 - me), game.form(1 - me) == ANUNG      # what `free_steps` adds, once per call
    foes = tuple((e.pos, e.ranged, e.reach, e.move + bonus + (ANUNG_FREE_STEPS if anung and e.hero else 0))
                 for e in game.foes(me))
    boost = boost_reach(game, 1 - me)
    key = (board.key, hero_pos, own[fid], others, cands, mates, foes, boost)
    best = _guard_cache.get(key)
    if best is not None:
        return best

    def walks(e_pos: int, steps: int, shield: frozenset[int]) -> frozenset[int]:
        return reach_from(board, e_pos, steps, mates - {e_pos}, shield)

    def exposure_of(foe: tuple, shield: frozenset[int]) -> tuple[int, int]:
        e_pos, ranged, reach, steps = foe
        spots = strike_spots(board, hero_pos, ranged, reach)
        if e_pos in spots:
            return 2, 0
        walk = walks(e_pos, steps, shield) & spots
        if walk:
            return 2, len(walk)
        far = walks(e_pos, steps + boost, shield) & spots if boost else walk
        return (1 if far else 0), len(far)

    base = [exposure_of(foe, others) for foe in foes]
    if all(b == (0, 0) for b in base):      # nothing reaches the hero: no block can improve that, so it stays
        best = own[fid]
        _guard_cache[key] = best
        return best
    # a space off a rival's reach (boost included) changes nothing for that rival: only the rivals it is on the way of are recomputed
    ways = [walks(pos, steps + boost, others) for pos, _, _, steps in foes]

    def exposure(d: int) -> tuple[int, int]:
        shield = others | {d}
        parts = [exposure_of(foe, shield) if d in way else b for foe, way, b in zip(foes, ways, base)]
        return sum(t for t, _ in parts), sum(o for _, o in parts)

    on_the_way = frozenset().union(*ways)
    base_sum = (sum(t for t, _ in base), sum(o for _, o in base))
    best, best_exposure = None, None
    # in tie-break order (stay, nearest the hero, lowest id) the first space with the least exposure wins, and nothing beats (0, 0)
    for d in sorted(cands, key=lambda d: (d != own[fid], board.distance(d, hero_pos), d)):
        e = exposure(d) if d in on_the_way else base_sum
        if best_exposure is None or e < best_exposure:
            best, best_exposure = d, e
            if e == (0, 0):
                break
    if len(_guard_cache) >= GUARD_CACHE_MAX:
        _guard_cache.clear()
    _guard_cache[key] = best
    return best
