"""Eredin's plugins (docs/heroes/eredin.md): `eredin:replace_combatant` and the test `eredin:opponent_card`.

Portal Defense: Eredin swaps spaces with an adjacent friendly fighter and "that fighter is now the defender". After the swap the
combat changes who is in it exactly as Houdini's Smoke And Mirrors does, so the work is Houdini's own (`CombatFlow.replace_combatant`);
the id carries the fid of the hero whose file uses it (the validator demands it).

Brutal Strike: "If your opponent's card has an IMMEDIATELY effect, ignore their card's value." The printed text decides, never what the
effect did or whether it was cancelled: `has_immediately` is true when the card the rival played says IMMEDIATELY."""
from __future__ import annotations

from .model import EffectError
from .ops_core import plugin, plugin_condition
from .plugins_houdini import _replace_combatant
from .select import card_ref


@plugin("eredin:replace_combatant")
def _portal_defense(run, game, spec):
    """When Eredin and the friendly fighter did swap (`args.swapped` binds both), the one that did not play the card takes the place of
    the one that did, in this combat (the card stays in play for the new defender)."""
    return _replace_combatant(run, game, spec)


@plugin_condition("eredin:opponent_card")
def _opponent_card_says(game, run, key: str) -> bool:
    """`has_immediately`: the rival's card in this combat carries an IMMEDIATELY effect in its printed text."""
    if key != "has_immediately":
        raise EffectError(f"eredin:opponent_card: unknown key {key!r}")
    cards = card_ref(game, run, "opponent_card")
    return bool(cards) and "IMMEDIATELY:" in cards[0].text
