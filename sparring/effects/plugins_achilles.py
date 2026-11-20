"""Achilles' plugin (docs/heroes/achilles.md): `achilles:replace_combatant`.

Under Achilles' Helm: Achilles may swap spaces with Patroclus and, if he does, Patroclus is now the defender. After the swap the
combat changes who is in it exactly as Houdini's Smoke and Mirrors and Luke Cage's Got My Back? do, so the work is Houdini's own;
the id carries the fid of the hero whose file uses it (the validator demands it)."""
from __future__ import annotations

from .ops_core import plugin
from .plugins_houdini import _replace_combatant


@plugin("achilles:replace_combatant")
def _under_achilles_helm(run, game, spec):
    """When Achilles and Patroclus did swap (`args.swapped` binds both), Patroclus takes Achilles' place in this combat."""
    return _replace_combatant(run, game, spec)
