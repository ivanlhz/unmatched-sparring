"""How the bot plays John Henry's tracks (docs/heroes/john-henry.md).

Where to summon: the free-walk distance from John Henry to the rival is what a track token buys, because every track space he enters
costs nothing. The token goes where it shortens most the walk to a space from which he can strike a rival fighter, counting the
tokens already on the board; among equal spaces it prefers one that joins an existing track or his own space (a chain is walked for
free from end to end and each of its spaces is a path) and then one farther from the rival's reach."""
from __future__ import annotations

from . import tracks


def strike_cost(game, owner: int, free: frozenset[int]) -> int:
    """The least steps John Henry needs to reach a space from which he can hit a rival fighter, entering `free` spaces for nothing
    (rival fighters block the way; 99 when nothing is in reach)."""
    hero = game.hero(owner)
    foes = [f for f in game.foes(owner) if f.pos is not None]
    if hero.pos is None or not foes:
        return 99
    board = game.board
    blocked = frozenset(f.pos for f in foes)
    costs = board.step_costs(hero.pos, free, blocked)
    best = 99
    for foe in foes:
        for s, c in costs.items():
            if c < best and (s == hero.pos or s not in blocked) and board.can_reach_target(s, foe.pos, hero.ranged, hero.reach):
                best = c
    return best


def pick_track_space(game, owner: int, options: list[int]) -> int:
    """The space of `options` (the free spaces of his zone) the next track token goes to."""
    hero = game.hero(owner)
    board = game.board
    placed = tracks.placed(game)
    foes = [f for f in game.foes(owner) if f.pos is not None]

    def key(s: int):
        joins = s in board.adj[hero.pos] or any(n in placed for n in board.adj[s]) or s == hero.pos
        away = min((board.distance(f.pos, s) for f in foes), default=0)
        return (strike_cost(game, owner, placed | {s}), not joins, -away, s)

    return min(options, key=key)
