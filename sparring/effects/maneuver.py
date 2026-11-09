"""Extra movement in a Maneuver given by the hero's ability (docs/effects-dsl.md, section 36).

The passive rule `{"kind": "rule", "rule": "maneuver_move_per_counter", "counter": "<name>"}` adds one space to the move of
every fighter of the owner in a Maneuver for each card the HeroDef counter `<name>` counts (Sinbad: the VOYAGE cards of his
discard pile). It only widens the reach: moving less is always allowed, so "you may" needs no decision."""
from __future__ import annotations

from .model import load_effects

RULE = "maneuver_move_per_counter"


def maneuver_bonus(game, player: int, boost=None) -> int:
    """Spaces added to each of `player`'s fighters in a Maneuver. `boost`: the card about to be spent as the Maneuver's BOOST that
    is not in the discard pile yet (a planner asks before it happens); a boost card that carries the counter's tag is counted
    because it reaches the pile before anyone moves. 0 for a hero without the rule."""
    hero = game.players[player].hero
    if hero.slug not in game.fx.dsl_heroes:
        return 0
    total = 0
    for passive in load_effects(hero.slug).passives:
        if passive["kind"] == "rule" and passive["rule"] == RULE:
            counter = hero.counters[passive["counter"]]
            total += game.counter(player, passive["counter"]) + (1 if boost is not None and counter.tag in boost.tags else 0)
    return total
