"""What the AI knows about Philippa's cards (docs/heroes/philippa.md): Regicide's 6, the damage her lightning does to the zone, and a price
for the effects `ai_medusa.AFTER_BONUS` (a fixed table) cannot express because they depend on the board.

`ai_medusa.card_value` reads the printed value, so Regicide against a hero needs `attack_value`; `after_value` is added to an attack's
outcome and to a defense's evaluation like `ai_sinbad.after_value`. The choices her plugins ask for (`EffectAI._cards`, purposes
`dust`, `bidding`, `ruse`, `ruse_reveal`, and the zone of Chain lightning) live in `ai_effects.py`; the helpers they share are here."""
from __future__ import annotations

REGICIDE = "Regicide"
REGICIDE_VALUE = 6
SPELLBREAKER = "Spellbreaker"

PLOT_EDGE = 0.8          # Redanian plot: the opponent discards a card (a cost to them) or their value counts nothing
CUNNING_DISCARD = 0.9    # Cunning: the opponent's cheapest way out is a card of the hand (about its keep value); else 2 damage
BIDDING_EDGE = 0.9       # Do my bidding: the rival's best card is replaced by the one the bot picks (the weakest it holds)
FETTERS_EDGE = 0.6       # Paralyzing fetters: the rival's total goes back to the printed value (every bonus and boost of theirs wasted)
DUST_EDGE = 0.3          # Blinding dust: the discard for a blow is decided at the AFTER, by the keep value against the damage
SPELL_EDGE = 0.2         # Spellbreaker: the cancel is priced by `cancels_effects`; what is left is the turn it ends for the rival


def attack_value(card, target) -> float | None:
    """The value `card` will have against `target` when its DURING is known now, or None when it is the printed one."""
    return float(REGICIDE_VALUE) if card.title == REGICIDE and target is not None and target.hero else None


def foes_in_zone(game, owner: int, zone: str | None = None) -> list:
    """The living opposing fighters in Philippa's zones (every zone her space belongs to), or only in `zone`."""
    hero = game.hero(owner)
    if not hero.alive or hero.pos is None:
        return []
    zones = game.board.zones(hero.pos)
    wanted = zones if zone is None else {zone} & zones
    return [f for f in game.foes(owner) if f.alive and f.pos is not None and game.board.zones(f.pos) & wanted]


def best_zone_hits(game, owner: int) -> int:
    """The most opposing fighters one zone of Philippa's holds (Chain lightning picks that zone)."""
    hero = game.hero(owner)
    if not hero.alive or hero.pos is None:
        return 0
    return max((len(foes_in_zone(game, owner, z)) for z in game.board.zones(hero.pos)), default=0)


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float) -> float:
    """What the AFTER (or IMMEDIATELY) of a Philippa card is worth, in the AI's units (`card_value` per card, `foe_hp_weight` per hit
    point of the opposing fighter). Cards of any other hero are worth 0 here."""
    title = card.title
    if title == "Lightning bolt":
        return 0.0 if game.fx.maneuvered(owner) else foe_hp_weight * len(foes_in_zone(game, owner))
    if title == "Chain lightning":
        return foe_hp_weight * best_zone_hits(game, owner)
    if title == "Cunning":
        return min(2 * foe_hp_weight, CUNNING_DISCARD * card_value)
    if title == "Redanian plot":
        return PLOT_EDGE
    if title == "Do my bidding":
        return BIDDING_EDGE
    if title == "Paralyzing fetters":
        return FETTERS_EDGE
    if title == "Blinding dust":
        return DUST_EDGE
    if title == SPELLBREAKER:
        return SPELL_EDGE
    if title == "Owlform":
        return 0.8
    return 0.0


def ends_turn(card) -> bool:
    """The card's AFTER ends the turn (the actions still to spend are lost when it is played as an attack)."""
    return card.title == SPELLBREAKER
