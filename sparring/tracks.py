"""John Henry's track tokens (docs/effects-dsl.md, section 40).

STEEL-DRIVING MAN gives its owner 10 track tokens, one of them summoned at the start of every turn in a space of John Henry's zone,
and "when you move John Henry, do not count spaces with track tokens". The tokens are board state, not a counter: `fx.tracks[player]`
lists the spaces of that player's tokens (at most `SUPPLY`, one per space, never taken off) and `fx.paths` the track spaces John
Henry has entered in the current turn (the reading of "paths" the docs list under Pending Ivan).

The engine reaches this module from `Game.legal_moves` / `hazard_edges` / `walk` (the walks), from the `move` op (`over_tracks`, Power
Through), from the SpaceSel `track` and from the plugins of `effects/plugins_john.py`."""
from __future__ import annotations

SUPPLY = 10
RULE = "track_free_move"            # the passive rule of the hero's ability: every walk of John Henry ignores the track spaces
NEEDED_PATHS = 4                    # "at least 4 different paths this turn"


def placed(game, player: int | None = None) -> frozenset[int]:
    """The spaces with a track token: the player's, or all of them."""
    sides = game.fx.tracks
    if player is not None:
        return frozenset(sides[player])
    return frozenset(s for side in sides for s in side)


def left(game, player: int) -> int:
    """Track tokens `player` still holds in the supply."""
    return SUPPLY - len(game.fx.tracks[player])


def add(game, player: int, space: int) -> bool:
    """Lays a track token on `space`; False when the supply is empty, the space is not on the board or already has one."""
    if space not in game.board.spaces or space in placed(game) or left(game, player) <= 0:
        return False
    game.fx.tracks[player].append(space)
    return True


def free_spaces(game, fighter, over_tracks: bool = False) -> frozenset[int]:
    """The spaces that cost nothing to enter when `fighter` moves: every track space for John Henry (his rule) and for any fighter
    a card moves with "do not count spaces with track tokens" (`over_tracks`). Nothing when no token is on the board."""
    if not any(game.fx.tracks):
        return frozenset()
    if over_tracks or (fighter.hero and game.fx.hero_rule(fighter.owner, RULE)):
        return placed(game)
    return frozenset()


def record_walk(game, fighter, origin: int | None, dest: int, blocked: frozenset[int]) -> None:
    """John Henry walked from `origin` to `dest` in his own turn: the track spaces on the way count as paths used this turn.
    The walk is the cheapest one through the most track spaces (a table only shows where the piece started and ended)."""
    if origin is None or not fighter.hero or game.turn != fighter.owner or not any(game.fx.tracks):
        return
    if not game.fx.hero_rule(fighter.owner, RULE):
        return
    free = placed(game)
    for s in game.board.track_route(origin, dest, free, blocked):
        if s not in game.fx.paths:
            game.fx.paths.append(s)


def paths_used(game) -> int:
    """How many different track spaces John Henry has entered this turn."""
    return len(game.fx.paths)
