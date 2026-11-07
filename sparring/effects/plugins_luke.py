"""Luke Cage's plugin (docs/heroes/luke-cage.md): `luke:replace_combatant`.

Got My Back?: Misty Knight may swap spaces with Luke Cage and, if she does, Luke Cage is now the defender. After the swap
the combat changes who is in it exactly as Houdini's Smoke and Mirrors does, so the work is Houdini's own; the id carries the
fid of the hero whose file uses it (the validator demands it)."""
from __future__ import annotations

from .ops_core import plugin
from .plugins_houdini import _replace_combatant


@plugin("luke:replace_combatant")
def _got_my_back(run, game, spec):
    """When Misty and Luke did swap (`args.swapped` binds both), the one that did not play the card takes the place of the
    one that did, in this combat (the card stays in play for the new defender)."""
    return _replace_combatant(run, game, spec)
