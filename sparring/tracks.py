"""John Henry's track tokens (docs/effects-dsl.md, section 40).

STEEL-DRIVING MAN gives its owner 10 track tokens, one of them summoned at the start of every turn in a space of John Henry's zone,
and "when you move John Henry, do not count spaces with track tokens". The tokens are board state, not a counter: `fx.tracks[player]`
lists the spaces of that player's tokens (at most `SUPPLY`, one per space, never taken off) and `fx.paths` the paths (edges between
spaces, `(low, high)`) John Henry has crossed in the current turn (Iván, 2026-11-20: a path is a connection, not a track space).

The engine reaches this module from `Game.legal_moves` / `hazard_edges` / `walk` (the walks), from the `move` op (`over_tracks`, Power
Through, which frees nothing by itself: only John Henry's own walks ignore the tokens), from the SpaceSel `track` and from the plugins of `effects/plugins_john.py`."""
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
    """The spaces that cost nothing to enter when `fighter` moves: every track space, for John Henry only (his rule; Power Through's
    `over_tracks` adds nothing for any other fighter). Nothing when no token is on the board."""
    fx = getattr(game, "fx", None)
    if fx is None or not any(fx.tracks):
        return frozenset()
    if fighter.hero and game.fx.hero_rule(fighter.owner, RULE):       # only John Henry's own walks (Power Through's `over_tracks` adds nothing for a rival: Iván, 2026-11-13)
        return placed(game)
    return frozenset()


def record_walk(game, fighter, origin: int | None, dest: int, blocked: frozenset[int], steps: int | None = None) -> int | None:
    """John Henry walked from `origin` to `dest` (the same space too: a loop) in his own turn with `steps` to spend: the paths (the edges
    between spaces, Ivan 2026-11-20) the walk crosses count as paths used this turn, with or without track tokens on them. A table (and the
    bot's move) only gives the two ends, so the walk is the one within `steps` (None: the cheapest cost) that crosses the most paths not
    used yet, loops over the track spaces (free) included. A hazard edge is only part of that walk when he has paid a hazard this turn
    (the walk charges the least-hazard way: call this after the charge). A John Henry who cannot move (Burning Barrier) uses none.
    Returns the steps the walk spent (None when nothing is recorded), for a caller that splits one Maneuver into several reads."""
    if origin is None or not fighter.hero or game.turn != fighter.owner or not fighter.alive:
        return None
    if not game.fx.hero_rule(fighter.owner, RULE) or not game.fx.can_move(fighter):
        return None
    free = free_spaces(game, fighter)
    cheapest = game.board.walk_cost(origin, dest, free, blocked)
    if cheapest is None:
        return None
    budget = cheapest if steps is None else max(steps, cheapest)
    known = frozenset(game.fx.paths)
    cap = max(1, NEEDED_PATHS - len(known))
    avoid = frozenset() if fighter.fid in game.hazard_taken else frozenset(game.board.hazards)
    got, spent = game.board.most_paths_walk(origin, dest, free, blocked, budget, known, cap, avoid)
    for edge in sorted(got):
        if edge not in known:
            game.fx.paths.append(edge)
    return cheapest if spent is None else spent


def paths_used(game) -> int:
    """How many different paths (edges) John Henry has crossed this turn."""
    return len(game.fx.paths)


def attack_only(game) -> bool:
    """Every action left is a free action that only an attack may spend (Hear That Cold Steel Ring; Wyatt Earp's `Game.free_attacks`)."""
    return 0 < game.actions_left <= game.fx.attack_credit or (game.actions_left > 0 and game.paid_actions <= 0)


def turn_goes_on(game) -> bool:
    """The player whose turn it is still has something to do: an action is left and, when all that is left is a free action to attack,
    an attack is possible with the hand they hold (otherwise the turn is over: nothing else may spend it)."""
    game.prune_free_attacks(game.turn)       # a free action to attack nobody can use is lost (Wyatt Earp)
    if game.actions_left <= 0 or not game.own(game.turn):         # no action left, or no fighter on the board to spend one (Elektra removed in her own turn)
        return False
    if not attack_only(game):
        return True
    from . import enraged
    me = game.turn
    return any(game.can_declare_attack(f, foe) and enraged.may_attack_with(game, me, c) and c.usable_by(f.name)
               and game.attack_card_reaches(f, foe, c)
               for f in game.own(me) for foe in game.foes(me) for c in game.players[me].hand)
