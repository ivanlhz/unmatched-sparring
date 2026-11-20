"""Achilles' VENGEANCE: "While Patroclus is defeated, add +2 to the value of all Achilles' attacks" (docs/heroes/achilles.md).

A hero whose HeroDef carries a passive `{"effect": "sidekick_defeated_bonus", "sidekick": "patroclus", "n": 2}` adds `n` to every attack
of the hero himself (not of his sidekicks) while that sidekick is not alive. Only attacks: `Game.attack_bonus_parts` and
`Game.attack_bonus` ask for it, a defense never gets it. The draw ("If Achilles wins combat, draw 1 card") is plain DSL in the effects
file (`ability.after`), the engine's half of the same definition is this bonus."""
from __future__ import annotations


def passive(game, player: int) -> dict | None:
    """The `sidekick_defeated_bonus` passive of `player`'s hero, None for any other hero."""
    for p in game.players[player].hero.passives:
        if p.get("effect") == "sidekick_defeated_bonus":
            return p
    return None


def bonus_parts(game, fighter) -> list[tuple[int, str]]:
    """(bonus, label) the passive adds to an attack of `fighter` right now."""
    p = passive(game, fighter.owner)
    if p is None or not fighter.hero:
        return []
    sidekick = game.fighters.get(p["sidekick"])
    if sidekick is None or sidekick.alive:
        return []
    return [(int(p["n"]), p["id"].replace("_", " ").upper())]
