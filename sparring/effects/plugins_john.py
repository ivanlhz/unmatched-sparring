"""John Henry's plugins (docs/heroes/john-henry.md): `john:summon_track` and the test `john:paths`.

STEEL-DRIVING MAN: "At the start of your turn, summon a track token in a space in John Henry's zone." The track tokens are board
state (`sparring/tracks.py`): the plugin lays one on a space of his zone that has none, while the owner holds one of the ten. The bot
chooses the space (`ai_john.pick_track_space`) and the session lays the physical token (intent `track`); the human's trigger is
physical at the table (the engine does not run it: `table.start_of_turn_is_physical`), so the human lays theirs and the session
reads the table's tokens.

Eighteen-, Twelve- and Nine-pound Hammer: "If John Henry used at least 4 different paths this turn". The test counts the paths (the edges
between spaces, Iván 2026-11-20) he crossed this turn (`tracks.paths_used`)."""
from __future__ import annotations

from .. import tracks
from ..ai_john import pick_track_space
from . import table
from .model import EffectError
from .ops_core import plugin, plugin_condition


def summon_options(game, owner: int) -> list[int]:
    """The spaces a new track token may go to: any space of John Henry's zone (his own included) with no token yet."""
    hero = game.hero(owner)
    if not hero.alive or hero.pos is None or tracks.left(game, owner) <= 0:
        return []
    taken = tracks.placed(game)
    return [s for s in sorted(game.board.spaces) if game.board.share_zone(hero.pos, s) and s not in taken]


@plugin("john:summon_track")
def _summon_track(run, game, spec):
    owner = run.ctx.owner
    options = summon_options(game, owner)
    if not options or table.physical(game, owner):       # the human lays their token by hand: the table is the source
        return
    space = pick_track_space(game, owner, options)
    if tracks.add(game, owner, space):
        table.intent(game, op="track", owner=owner, space=space)


@plugin_condition("john:paths")
def _paths_used(game, run, key: str) -> bool:
    """`four`: John Henry has crossed at least four different paths (edges) this turn."""
    if key != "four":
        raise EffectError(f"john:paths: unknown key {key!r}")
    return tracks.paths_used(game) >= tracks.NEEDED_PATHS
