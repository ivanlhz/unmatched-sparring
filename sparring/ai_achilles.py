"""What the AI knows about Achilles (docs/heroes/achilles.md): the worth of Patroclus' fall and The Day of Your Doom.

Patroclus' fall is a trade, not a loss. When he falls his owner discards 2 random cards, and from then on Achilles' attacks are worth +2
and each combat he wins draws a card (`vengeance`, `data/heroes/effects/achilles.json`). The generic AI values a sidekick's death as a
loss (`ai_medusa.kill_value`); here `fall_net` is what the trade is worth to the owner, and `kill_value` subtracts it, so

  - Achilles' bot spends Patroclus when the +2 and the draws outweigh the cards it throws away (he pays The Day of Your Doom's 2 damage
    even when it kills him, takes a blow on him under the Helm), and keeps him alive while the discard would cost more;
  - a bot facing Achilles values the kill of Patroclus less: it empties the rival's hand of two cards and arms his hero.

The units are the evaluation's hit points (`W_HERO`, `HARPY_VALUE`). The search leaf (`search.adapter._side_terms`) reads the same
edge in its own units (`LEAF_EDGE`)."""
from __future__ import annotations

from . import vengeance

FALL_EDGE = 3.0       # what +2 on every attack and a draw per won combat are worth over the rest of a game, in hit-point weights
CARD_COST = 1.2       # a card thrown away at random (the `CARD_FLAT` of the evaluation: an average card)
DISCARDS = 2          # "discard 2 random cards"
DOOM = "The Day of Your Doom"
DOOM_VALUE = 5.0
DOOM_DAMAGE = 2
PAY_MARGIN = 0.1
LEAF_EDGE = 0.4       # the search leaf: lives gained by an Achilles whose Patroclus is down; 8 games of the search AI against the chasing rival: 1 won with 0, 3 with 0.12, 5 with 0.3, 6 with 0.5


def passive(game, player: int):
    return vengeance.passive(game, player)


def is_patroclus(game, f) -> bool:
    """`f` is the sidekick whose fall arms Achilles' owner."""
    p = vengeance.passive(game, f.owner)
    return p is not None and not f.hero and f.fid == p["sidekick"]


def fall_net(game, f) -> float:
    """What the fall of `f` is worth to its owner right now: the edge of the passive minus the cards he is about to discard; 0 for any
    other fighter. Positive while the hand is small, negative once the two cards thrown away cost more than the edge."""
    if not is_patroclus(game, f) or not f.alive:
        return 0.0
    cards = min(DISCARDS, len(game.players[f.owner].hand))
    return FALL_EDGE - CARD_COST * cards


def doom_pays(game, f, gain: float = DOOM_VALUE - 3, target=None) -> bool:
    """The Day of Your Doom: 2 damage to Patroclus for a 5 instead of a 3. Pays when the `gain` points the blow really adds (the combat
    tells: a defense that already stops the 3 and the 5 alike adds less) are worth more than the hit points it costs him; if the damage
    defeats him the fall is part of the price (or of the prize)."""
    from .ai_medusa import HARPY_VALUE, W_HERO, W_SIDEKICK
    if f is None or not f.alive:
        return False
    cost = HARPY_VALUE * min(DOOM_DAMAGE, f.hp)
    if f.hp <= DOOM_DAMAGE:
        cost -= fall_net(game, f)
    return (W_SIDEKICK if target is not None and not target.hero else W_HERO) * gain > cost + PAY_MARGIN


def attack_value(game, f, card) -> float | None:
    """The value The Day of Your Doom will have when `f` plays it (None for any other card): 5 if the bot will pay for it."""
    return DOOM_VALUE if card.title == DOOM and doom_pays(game, f) else None
