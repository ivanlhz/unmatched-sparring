"""What Ciri's cards are worth to the heuristic AI (`ai_medusa.MedusaAI`): the SOURCE tiers change the value a card has and the damage its
AFTER does, so the printed numbers alone would have the bot sell her strongest cards short. Everything here reads the Source from the
discard pile (`Game.counter`) at the moment the bot decides, the same moment the interpreter reads it when the card resolves.

The numbers are the ones printed on the cards (docs/heroes/ciri.md); the weights are the AI's usual ones, passed in by the caller so this
module never imports the AI."""
from __future__ import annotations

SOURCE = "source"
VALUE_TIERS = {                       # title -> ((Source at least, value instead), ...) lowest first
    "Lion cub of Cintra": ((1, 4), (5, 7)),
    "Zireael": ((3, 4),),
}
LADY, SEARCHING, PUSHED = "The lady of space and time", "Searching strike", "Pushed to the brink"
CHANNEL = "Channel the source"
SPARE_DISCOUNT = 0.5                  # the cards Channel the source gives up are not free: half of the +2 each is counted
RETURN_VALUE = 0.5                    # a card from the discard pile back to the deck's top / the hand, in cards
SEARCH_GAIN = 0.8                     # a Source card found for a win, in cards


def source(game, owner: int) -> int | None:
    """The owner's Source, None when the hero has no such counter."""
    return game.counter(owner, SOURCE) if SOURCE in game.players[owner].hero.counters else None


def attack_value(game, owner: int, card) -> float | None:
    """The value a Source attack will have: the highest tier the Source reaches (None for any other card)."""
    tiers = VALUE_TIERS.get(card.title)
    n = source(game, owner)
    if tiers is None or n is None:
        return None
    value = float(card.value)
    for need, instead in tiers:
        if n >= need:
            value = float(instead)
    return value


def during_gain(game, owner: int, card, hand) -> float:
    """Channel the source: +2 for each Source card it can spare from the hand (it keeps one card besides this one)."""
    if card.title != CHANNEL:
        return 0.0
    spare = [c for c in hand if SOURCE in c.tags and c is not card]
    return 2.0 * SPARE_DISCOUNT * min(len(spare), max(0, len(hand) - 2))


def after_value(game, owner: int, card, p_win: float, hp_weight: float, card_value: float) -> float:
    """The worth of the AFTER of Pushed to the brink, The lady of space and time and Searching strike at the current Source, in the AI's
    units (`hp_weight` per hit point, `card_value` per card)."""
    n = source(game, owner)
    if n is None:
        return 0.0
    if card.title == PUSHED:
        return hp_weight * (2.0 if n >= 7 else 1.0 if n >= 2 else 0.0)
    if card.title == LADY:
        return card_value * RETURN_VALUE * (3.0 if n >= 8 else 1.0 if n >= 3 else 0.0)
    if card.title == SEARCHING:
        has = any(SOURCE in c.tags for c in game.players[owner].deck)
        return card_value * SEARCH_GAIN * p_win if has else 0.0
    return 0.0
