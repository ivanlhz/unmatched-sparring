"""What the AI knows about Rosie the Riveter's cards (docs/heroes/rosie-the-riveter.md): the value Full Metal will have and the worth of the
AFTER / IMMEDIATELY of the cards that move her upgrade row.

`ai_medusa.card_value` and the rival models read the printed value, so Full Metal (1, plus 1 per active upgrade) would be played as a 1.
The reach of Whizbang and the Merlin Engine's extra space need nothing here: they are the hero's `Fighter.ranged` and `Fighter.move`
(`upgrades.sync`), which the AI already reads. Sedgley Fist Gun's +1 is a DURING effect of the combat, not in `Game.attack_bonus`, so the
AI's estimate of a blow does not see it. The weights are the AI's usual ones, passed in by the caller so
this module never imports the AI."""
from __future__ import annotations

from . import upgrades

FULL_METAL = "Full Metal"
WE_CAN = "We Can Do It!"
D_DAY = "D-Day"
OVERRUN = "Overrun"
ARC = "Arc Welding"
HASTY = "Hasty Repairs"

UPGRADE_STEP = 0.3         # one more active upgrade, in cards: it is worth something for the rest of the turn, and nothing once all four reset
FREE_ACTION = 0.8          # D-Day's extra action (the AI's ACTION_VALUE is 1.0; it can only be spent as the rules allow it, which the engine does not check)
MOVE_AFTER = 0.3           # Overrun's move
HEAL_LIMIT = 3             # what Hasty Repairs recovers


def own_value(game, fighter, card) -> float | None:
    """The value `card` will have when its DURING is known now: Full Metal is 1 plus one per active upgrade, None for any other card."""
    if card.title == FULL_METAL and upgrades.has(game, fighter.owner):
        return float(card.value + upgrades.count(game, fighter.owner))
    return None


def _room(game, owner: int) -> int:
    """Upgrades that are still inactive."""
    return max(0, upgrades.size(game, owner) - upgrades.count(game, owner))


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, hero_hp_weight: float,
                foe_hp: float = 0.0) -> float:
    """The worth of the effects of a Rosie card that the AI's `AFTER_BONUS` does not list, in the AI's units (`card_value` per card,
    `foe_hp_weight` per hit point of the opposing fighter, `hero_hp_weight` per hit point of Rosie)."""
    if not upgrades.has(game, owner):
        return 0.0
    title = card.title
    room = _room(game, owner)
    hero = game.hero(owner)
    if title == WE_CAN:
        return UPGRADE_STEP if room else 0.0
    if title == D_DAY:
        already = upgrades.count(game, owner) >= upgrades.size(game, owner)
        hit = foe_hp_weight * min(1.0, foe_hp) + hero_hp_weight * min(1.0, hero.max_hp - hero.hp) if already else UPGRADE_STEP * room
        return FREE_ACTION + hit
    if title == OVERRUN:
        return MOVE_AFTER + foe_hp_weight * 0.5
    if title == ARC:
        return max(UPGRADE_STEP if room else 0.0, foe_hp_weight * 0.5)
    if title == HASTY:
        return hero_hp_weight * min(float(HEAL_LIMIT), hero.max_hp - hero.hp) if upgrades.count(game, owner) else 0.0
    return 0.0
