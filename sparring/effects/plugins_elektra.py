"""Elektra's plugins (docs/heroes/elektra.md): `elektra:flip` and `elektra:replace_combatant`.

The removal of Elektra and the Hand (her first defeat) is not a plugin: `Game._fall` asks `sparring/off_board.py`, because every defeat
(combat, effect, exhaustion) passes there. The Resurrect is the trigger `resurrect` of her effects file; its first step, `elektra:flip`, is
`off_board.release`, and the rest are ordinary ops (shuffle the discard pile into the deck, `revive` Elektra and the Hand)."""
from __future__ import annotations

from .. import off_board
from .ops_core import plugin
from .plugins_houdini import _replace_combatant


@plugin("elektra:flip")
def _flip(run, game, spec):
    """Resurrect: the health dial flips (nine health at most) and the fighters taken off the board can be returned."""
    off_board.release(game, run.ctx.owner)


@plugin("elektra:replace_combatant")
def _snakeroot_clan(run, game, spec):
    """Snakeroot Clan: when Elektra and a Hand did swap (`args.swapped` binds both), that Hand takes her place in this combat."""
    return _replace_combatant(run, game, spec)
