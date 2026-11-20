"""What the AI knows about Sun Wukong (docs/heroes/sun-wukong.md): when the 1 hit point of CLONES is worth a Clone, and what a Clone adds to the
cards that count the Clones or the fighters beside the rival.

The interpreter asks "take 1 damage to summon a Clone?" at the start of his turn (trigger id `clone_summon`) and the generic answer to an
optional is yes: the bot would pay with 1 hit point left. `summon_pays` is the policy `EffectAI._optional` uses instead, built like DARK PACT's
(`EffectAI._dark_pact`): never below a floor of hit points, never when the hit point raises the chance of dying in the rival's next turn, and
otherwise when the Clone is worth more than the hit point (a hit point is `W_MEDUSA_HP`; a Clone is a body worth `HARPY_VALUE` per hit point
plus what it does for the cards in the hand)."""
from __future__ import annotations

from .ai_medusa import HARPY_VALUE, LETHAL, SURVIVAL_P, W_MEDUSA_HP, Model

CLONES_KEY = "clone_summon"           # the key prefix of the request: the id of the ability's trigger
CLONES = 3                            # the Clones of the hero
FLOOR = 5                             # CLONES never leaves Sun Wukong with fewer hit points than this
COMFORT = 9                           # below this many hit points left, each one costs more (URGENCY per missing point)
URGENCY = 0.12
RISK_STEP = 0.1                       # ... and the hit point does not raise the chance of dying next turn by more than this
BODY = 0.9                            # what a Clone is worth beyond its own hit point: a body that takes a blow instead of the hero, holds a space, can strike
PRICE_MARGIN = 0.0                    # the Clone must be worth more than the hit point by this much
STRIKES_BONUS = 0.35                  # an Infinite Strikes in hand: each Clone beside the rival is +1 to it
PHOENIX_BONUS = 0.8                   # a Phoenix Form in hand: each Clone on the board heals a hit point (a hit point is W_MEDUSA_HP), while he is hurt
WILY_BONUS = 0.15                     # a Wily Fighting in hand: a Clone beside the rival is one more fighter to strike from


def clones_on_board(game, me: int) -> int:
    return sum(1 for f in game.own(me) if f.name == "Clone")


def clone_worth(game, me: int) -> float:
    """What one more Clone is worth to `me` now, in the AI's hit-point units: the body (less each one already out: the third adds less than
    the first) and the cards in hand that count it."""
    out = clones_on_board(game, me)
    hero = game.hero(me)
    worth = (HARPY_VALUE + BODY) * (CLONES - out) / CLONES
    for c in game.players[me].hand:
        if c.title == "Infinite Strikes":
            worth += STRIKES_BONUS
        elif c.title == "Phoenix Form" and hero.hp < hero.max_hp:
            worth += PHOENIX_BONUS * W_MEDUSA_HP
        elif c.title == "Wily Fighting":
            worth += WILY_BONUS
    return worth


def summon_pays(ai, game, req) -> bool:
    """CLONES: 1 hit point for a Clone. Never when it kills him or leaves him under `FLOOR`, nor when it raises the chance of dying in the rival's
    next turn to SURVIVAL_P or by more than RISK_STEP; otherwise when the Clone is worth more than the hit point."""
    me = req.player
    hero = game.hero(me)
    left = hero.hp - 1
    if left < FLOOR or clones_on_board(game, me) >= CLONES:
        return False
    medusa, model = ai.medusa(me), Model(game, me)
    now, after = medusa.death_risk(game, model, hero, hero.hp), medusa.death_risk(game, model, hero, left)
    if after >= SURVIVAL_P or after > now + RISK_STEP:
        return False
    cost = W_MEDUSA_HP * (1 + URGENCY * max(0, COMFORT - left)) + LETHAL * (after - now)
    return clone_worth(game, me) - cost > PRICE_MARGIN
