"""Yennenga's AI hooks: how much damage the bot hands the Archers (docs/heroes/yennenga.md).

The ability asks one request per Archer in her zone (`effects/plugins_yennenga.ask_shares`, an "amount" request with `assign`).
The bot answers each with the split that is worth most for the whole damage still to place: the hit points of Yennenga and of the
Archers still to be asked, weighted as the rest of the evaluation weighs them (`EffectAI.hp_change`: a hero point costs more than a
sidekick point, a fallen sidekick costs its kill value and a fallen hero the game). So the Archers soak the blow while they survive
it, keep out of a killing one when Yennenga can take it, and take it all when she could not."""
from __future__ import annotations

from itertools import product


def archer_share(game, req) -> int:
    """The points of `req.extra["left"]` the Archer named by `assign` takes, among the options of the request."""
    from .ai_effects import EffectAI
    x, me = req.extra, req.player
    hero, left = game.fighters[x["fighter"]], x["left"]
    archers = [game.fighters[x["assign"]]] + [game.fighters[i] for i in x.get("later", ()) if game.fighters[i].alive]
    caps = [min(left, int(a.hp)) for a in archers]

    def worth(parts) -> float:
        rest = left - sum(parts)
        if rest < 0:
            return float("-inf")
        return EffectAI.hp_change(hero, hero.hp - rest, me, game) + sum(
            EffectAI.hp_change(a, a.hp - k, me, game) for a, k in zip(archers, parts))
    best = max(product(*(range(c + 1) for c in caps)), key=lambda parts: (worth(parts), -sum(parts), parts))
    return min(best[0], max(req.options))
