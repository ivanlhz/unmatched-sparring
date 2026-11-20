"""Yennenga's AI hooks: how much damage the bot hands the Archers (docs/heroes/yennenga.md).

The ability asks one request per Archer in her zone (`effects/plugins_yennenga.ask_shares`, an "amount" request with `assign`).
The bot answers each with the split that is worth most for the whole damage still to place: the hit points of Yennenga and of the
Archers still to be asked, weighted as the rest of the evaluation weighs them (`EffectAI.hp_change`: a hero point costs more than a
sidekick point, a fallen sidekick costs its kill value and a fallen hero the game), and the chance that what is left of Yennenga is
killed in the rival's next turn (`MedusaAI.death_risk`, priced at LETHAL like the rest of the AI). So the Archers soak the blow while
they survive it, spare themselves when she can take it, and take all they can when she would be in killing range; while they can keep her
alive she is never left to fall."""
from __future__ import annotations

from itertools import product


def archer_share(game, req, ai=None) -> int:
    """The points of `req.extra["left"]` the Archer named by `assign` takes, among the options of the request. `ai` (the owner's
    MedusaAI) adds the risk of dying next turn; without it (a rollout) the hit point weights alone decide."""
    from .ai_effects import EffectAI
    from .ai_medusa import LETHAL, Model
    x, me = req.extra, req.player
    hero, left = game.fighters[x["fighter"]], x["left"]
    archers = [game.fighters[x["assign"]]] + [game.fighters[i] for i in x.get("later", ()) if game.fighters[i].alive]
    caps = [min(left, int(a.hp)) for a in archers]
    model = Model(game, me) if ai is not None else None
    risk: dict[int, float] = {}

    def danger(hp: float) -> float:
        if model is None or hp <= 0:
            return 0.0
        if hp not in risk:
            risk[hp] = ai.death_risk(game, model, hero, hp)
        return LETHAL * risk[hp]

    def worth(parts) -> float:
        rest = left - sum(parts)
        if rest < 0:
            return float("-inf")
        return (EffectAI.hp_change(hero, hero.hp - rest, me, game) - danger(hero.hp - rest)
                + sum(EffectAI.hp_change(a, a.hp - k, me, game) for a, k in zip(archers, parts)))
    splits = list(product(*(range(c + 1) for c in caps)))
    saving = [p for p in splits if hero.hp - (left - sum(p)) > 0]        # she never falls while the Archers can keep her up
    best = max(saving or splits, key=lambda parts: (worth(parts), -sum(parts), parts))
    return min(best[0], max(req.options))
