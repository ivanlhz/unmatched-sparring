"""The Raptors' pack bonus (docs/heroes/raptors.md).

A hero whose HeroDef carries a passive `{"effect": "pack_bonus", "n": 1}` ("Raptors add 1 to the value of their attack cards for each of
your other Raptors adjacent to the defender") adds `n` to each attack card of a fighter of the owner for every OTHER undefeated
fighter of the owner standing next to the defender. Only attacks count ("their attack cards"): `Game.attack_bonus_parts` and
`Game.attack_bonus` ask for it with the attacker and the target, so a defense never gets it and a question without a target
(the AI measuring a threat in general) reads 0."""
from __future__ import annotations

from .i18n import t



def passive(game, player: int) -> dict | None:
    """The `pack_bonus` passive of `player`'s hero, None for any other hero."""
    for p in game.players[player].hero.passives:
        if p.get("effect") == "pack_bonus":
            return p
    return None


def mates_adjacent(game, attacker, target) -> list:
    """The other undefeated fighters of the attacker's owner standing next to `target`."""
    if target is None or target.pos is None:
        return []
    around = game.board.adj[target.pos]
    return [f for f in game.own(attacker.owner) if f is not attacker and f.pos is not None and f.pos in around]


def bonus_parts(game, attacker, target) -> list[tuple[int, str]]:
    """(bonus, label) the passive adds to an attack of `attacker` against `target` right now."""
    p = passive(game, attacker.owner)
    if p is None or target is None:
        return []
    n = len(mates_adjacent(game, attacker, target))
    return [(int(p["n"]) * n, t("raptors.pack_bonus"))] if n else []
