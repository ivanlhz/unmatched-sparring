"""What the AI knows about Sinbad's cards (docs/heroes/sinbad.md): the value a VOYAGE attack will have, and Momentous Shift's 5.

`ai_medusa.card_value` and the rival models read the printed value, so a card whose DURING raises it needs these figures to be
played (or feared) for what it is worth: a VOYAGE card is worth its printed 2 plus the VOYAGE cards in its owner's discard pile
(the card in play is not there yet), Momentous Shift 5 when its fighter started the turn on another space."""
from __future__ import annotations

MOMENTOUS_SHIFT = "Momentous Shift"
MOMENTOUS_VALUE = 5


def voyage_count(game, owner: int) -> int:
    """VOYAGE cards in `owner`'s discard pile (0 for a hero without the counter)."""
    return game.counter(owner, "voyage") if "voyage" in game.players[owner].hero.counters else 0


def voyage_extra(card, count: int) -> int:
    """The bonus a VOYAGE card gets from `count` cards in its owner's pile."""
    return count if "voyage" in card.tags else 0


def own_value(game, fighter, card) -> float | None:
    """The value `card` will have for `fighter` when its DURING is known now, or None when it is the printed one."""
    if "voyage" in card.tags:
        return float(card.value + voyage_count(game, fighter.owner))
    if card.title == MOMENTOUS_SHIFT:
        start = game.fx.turn_start_pos.get(fighter.fid)
        return float(MOMENTOUS_VALUE) if start is not None and fighter.pos != start else None
    return None
