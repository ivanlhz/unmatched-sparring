"""What the AI knows about Blackbeard (docs/heroes/blackbeard.md): when a doubloon is worth paying, whoever the bot is.

Three decisions the interpreter asks (`EffectAI._optional`, `EffectAI._amount`), none of which the generic answers can price:

  * `ransom_pays`: the bot is the OPPONENT of Blackbeard and an effect line says "unless N doubloons". Paying takes N doubloons out of the Treasury
    (it will not be able to ransom later) and hands them to Blackbeard (who can spend one on an action). The line's cost to the bot is what the
    effect would do to it, in the AI's units; it pays when that beats the doubloons by `PAY_MARGIN`. The card of a random or chosen discard is a
    card of the bot's OWN hand, so its keep value is known; nothing of the rival's hidden hand is read.
  * `queens_amount`: Queen Anne's Revenge, how many doubloons (0 to the Treasury) to pay at 2 off the card's value each: the count that maximises
    the swing in the combat damage, less the doubloons.
  * `action_pays`: the bot IS Blackbeard at the start of his turn: 1 doubloon to the Treasury for 1 action. A doubloon in the Treasury is a ransom
    the opponent can pay later (and a coin off Queen Anne's Revenge's strength), so the action is bought only when the hand can use two actions and
    the Treasury stays small.
"""
from __future__ import annotations

from .ai_medusa import HARPY_VALUE, W_HERO, keep_value

COIN = 1.0                      # a doubloon out of the Treasury, in the units of hit points the evaluation uses
PAY_MARGIN = 0.25               # a ransom is paid only when the line costs the bot this much more than the doubloons
ACTION_BONUS = 1.4              # an action for Blackbeard (Give No Quarter, Scourge of the Seven Seas)
SEA_DOG_BACK = HARPY_VALUE + 0.9        # a defeated Sea Dog that returns: a body and its hit point
SEA_DOG_MOVE = 0.4              # nobody defeated: a Sea Dog only repositions
TREASURY_CAP = 2                # the action is not bought if it would put more than this many doubloons in the Treasury
USEFUL_ACTIONS = 2              # ... nor unless the hand can play this many attacks or schemes


def _my_cards(game, me: int, ids) -> list:
    by_id = {c.card_id: c for c in game.players[me].full_set}
    return [by_id[i] for i in ids if i in by_id]


def effect_cost(ai, game, me: int, effect: dict) -> float:
    """What the ransom line would cost `me` if it were not ransomed, in evaluation units."""
    what = effect.get("what")
    if what == "damage":
        return sum(ai.blow_value(game.fighters[fid], effect["amount"], game) for fid in effect["fighters"]
                   if fid in game.fighters and game.fighters[fid].owner == me)
    if what in ("discard", "random_discard"):
        cards = _my_cards(game, me, effect.get("cards") or ())
        if cards:
            return sum(keep_value(c, game.players[me].hand) for c in cards)
        return ai.medusa(me).avg_unseen_keep(game)
    if what == "cancel":
        return 0.9 * effect.get("moments", 1)
    if what == "heal":
        rival = game.hero(1 - me)
        return W_HERO * min(effect["amount"], max(0, rival.max_hp - rival.hp))
    if what == "action":
        return ACTION_BONUS
    if what == "summon":
        return SEA_DOG_BACK if effect.get("defeated") else SEA_DOG_MOVE
    return 0.0


def ransom_pays(ai, game, req) -> bool:
    """Pay `req.extra["ransom"]` doubloons from the Treasury to ignore the line `req.extra["effect"]`?"""
    me, n = req.player, req.extra["ransom"]
    return effect_cost(ai, game, me, req.extra["effect"]) > COIN * n + PAY_MARGIN


def queens_amount(ai, game, req) -> int:
    """Queen Anne's Revenge: the number of doubloons (one of `req.options`) that leaves the bot best off. Attacking Queen Anne: each doubloon
    takes 2 off the blow the bot's fighter would take; defending Queen Anne: each takes 2 off the wall the bot's attack meets."""
    x, me = req.extra, req.player
    target = game.fighters.get(x.get("target"))
    if target is None:
        return min(req.options)
    queen, other, queen_attacks = (x["atk"], x["dfn"], True) if x["queen_attacks"] else (x["dfn"], x["atk"], False)

    def score(k: int) -> float:
        value = max(0, queen - x["queens"] * k)
        if queen_attacks:
            dmg = game.combat_damage_taken(target, max(0, value - other))
            return -ai.blow_value(target, dmg, game) - COIN * k
        dmg = game.combat_damage_taken(target, max(0, other - value))
        return ai.blow_value(target, dmg, game) - COIN * k
    return max(req.options, key=lambda k: (score(k), -k))


def action_pays(ai, game, req) -> bool:
    """Blackbeard (the bot) at the start of his turn: 1 doubloon to the Treasury for 1 action."""
    me = req.player
    hero = game.hero(me)
    if req.extra.get("treasury", 0) + 1 > TREASURY_CAP:
        return False
    usable = [c for c in game.players[me].hand
              if (c.can_attack or c.type == "scheme") and any(c.usable_by(f.name) for f in game.own(me))]
    return len(usable) >= USEFUL_ACTIONS and hero.alive
