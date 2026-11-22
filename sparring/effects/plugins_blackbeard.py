"""Blackbeard's doubloons, ransoms and the two cards that need more than the DSL (docs/heroes/blackbeard.md).

The three doubloons are two counters of Blackbeard's player (`ability.counters`): `doubloons` (the ones he holds) and `treasury`; they always
add up to 3. A RANSOM ("unless N") is an `optional` of the OPPONENT whose cost moves N doubloons from the Treasury to Blackbeard and whose `else`
is the effect line, so paying ignores that one line (Ivan 2026-11-22, BB1). `can_pay` is what `ops_core._can_pay` asks about a cost that takes
doubloons: the option does not exist when the Treasury holds fewer than N. `ransom_context` is what the panel and the bot see about the question.

  * `blackbeard:random_discard` (Avast Ye!, IMMEDIATELY): "Your opponent discards 1 random card unless 1 doubloon". The random card is drawn FIRST, so the
    opponent decides knowing which card it is: a bot's or a simulation's hand is drawn here; the table player's is placeholders, so the engine names a
    POSITION of their hand (the Ambush flow, `random_discard`) and they lay that card on their discard pile if they do not pay.
  * `blackbeard:queens_revenge` (Queen Anne's Revenge, DURING): the opponent pays any number of doubloons from 0 to the Treasury's stock, each going to
    Blackbeard and taking 2 off the card's value (never below 0). It works on an uncancelable card because it is a payment, not a cancellation.
"""
from __future__ import annotations

from ..i18n import plural, t
from . import table
from .ops_core import OPS, _card_title, _random_positions_text, plugin
from .select import amount, counter_value

HELD, TREASURY = "doubloons", "treasury"
QUEENS_STEP = 2                  # Queen Anne's Revenge: the value falls by this much for each doubloon the opponent pays


def stock(game, player: int, name: str) -> int:
    return counter_value(game, player, name)


def treasury_cost(cost: list[dict]) -> int:
    """How many doubloons an optional's cost takes from the Treasury (0 when it takes none: not a ransom)."""
    return sum(-int(c["delta"]) for c in cost if c["op"] == "counter" and c["name"] == TREASURY and int(c.get("delta", 0)) < 0)


def hand_cost(cost: list[dict]) -> int:
    """How many doubloons Blackbeard pays out of his own hand (the action at the start of his turn)."""
    return sum(-int(c["delta"]) for c in cost if c["op"] == "counter" and c["name"] == HELD and int(c.get("delta", 0)) < 0)


def can_pay(game, owner: int, cost: list[dict]) -> bool:
    """A cost of the owner's own counters that would take one below what it holds cannot be paid (the Treasury has fewer than the ransom asks;
    Blackbeard has no doubloon to give for an action). Any other cost is not this function's business."""
    need: dict[str, int] = {}
    for c in cost:
        if c["op"] == "counter" and int(c.get("delta", 0)) < 0 and c.get("player", "owner") == "owner":
            need[c["name"]] = need.get(c["name"], 0) - int(c["delta"])
    return all(stock(game, owner, name) >= n for name, n in need.items())


def pay_ransom(run, game, n: int) -> None:
    """`n` doubloons from the Treasury to Blackbeard."""
    OPS["counter"](run, game, {"op": "counter", "name": TREASURY, "delta": -n})
    OPS["counter"](run, game, {"op": "counter", "name": HELD, "delta": n})


def describe_effect(game, run, ops: list[dict]) -> dict:
    """What the ransom line would do, for the panel and for a bot to price: {"what": "damage", "amount": 3, "fighters": [fid, ...]}, "discard"
    (`cards`: the ids of the chosen card), "cancel", "heal", "action", "summon"."""
    for o in ops:
        kind = o["op"]
        if kind == "damage":
            from .select import fighter_candidates
            return {"what": "damage", "amount": amount(game, run, o["amount"]),
                    "fighters": [f.fid for f in fighter_candidates(game, run, o["target"])[0]]}
        if kind == "discard":
            cards = o["cards"]
            if isinstance(cards, str):
                from .select import card_ref
                return {"what": "discard", "cards": [c.card_id for c in card_ref(game, run, cards)]}
            return {"what": "random_discard"}
        if kind == "cancel_effects":
            from .ops_core import _cancellable_moments
            return {"what": "cancel", "moments": _cancellable_moments(game, run)}
        if kind == "heal":
            return {"what": "heal", "amount": amount(game, run, o["amount"])}
        if kind == "gain_action":
            return {"what": "action"}
        if kind == "if":
            return {"what": "summon", "defeated": any(f.name == "Sea Dog" and not f.alive for f in game.own(run.ctx.owner, alive_only=False))}
    return {"what": "other"}


def ransom_context(game, run, spec: dict) -> dict:
    """The extra of a RANSOM question (an `optional` whose cost takes doubloons from the Treasury): `ransom` is its price."""
    n = treasury_cost(spec.get("cost") or [])
    if not n:
        return {}
    return {"ransom": n, "effect": describe_effect(game, run, spec.get("else") or []), "treasury": stock(game, run.ctx.owner, TREASURY)}


def action_context(game, run, spec: dict) -> dict:
    """The extra of the start-of-turn question: pay 1 doubloon to the Treasury for an action."""
    n = hand_cost(spec.get("cost") or [])
    if not n or treasury_cost(spec.get("cost") or []):
        return {}
    return {"doubloon_action": n, "held": stock(game, run.ctx.owner, HELD), "treasury": stock(game, run.ctx.owner, TREASURY)}


def coins_snapshot(game) -> dict:
    """{player: [doubloons held, doubloons in the Treasury]} of the players whose hero keeps doubloons, for the chat's before and after."""
    out = {}
    for player in (0, 1):
        if game.players[player].hero.slug == "blackbeard":
            out[str(player)] = [stock(game, player, HELD), stock(game, player, TREASURY)]
    return out


def coin_lines(game, before: dict) -> list[str]:
    """What the doubloons did since `before` (a `coins_snapshot`): who holds how many now. Said by the chat so the table (which the session does not
    read coins from) can follow: the human moves the tokens, or knows what the bot's side holds."""
    parts = []
    for key, (held0, _) in (before or {}).items():
        held, treasury = coins_snapshot(game).get(key, (held0, 0))
        if held > held0:
            parts.append(t("narr.coins.in", n=plural(held - held0, "noun.doubloon"), held=held, treasury=treasury))
        elif held < held0:
            parts.append(t("narr.coins.out", n=plural(held0 - held, "noun.doubloon"), held=held, treasury=treasury))
    return parts


# ---------------------------------------------------------------- Avast Ye!

@plugin("blackbeard:random_discard")
def _random_discard(run, game, spec):
    owner = run.ctx.owner
    victim = 1 - owner
    st = game.players[victim]
    n = int((spec.get("args") or {}).get("amount", 1))
    if not st.hand or not game.fx.can_force_discard(victim, owner):
        return
    physical = table.physical(game, victim)
    card = None if physical else run.random_sample(list(st.hand), 1)[0]
    which = _random_positions_text(game, run, victim, 1, _card_title(game, run)) if physical else None
    can_pay_it = stock(game, owner, TREASURY) >= n
    extra = {"ransom": n, "effect": {"what": "random_discard", **({"cards": [card.card_id]} if card is not None else {"which": which})},
             "treasury": stock(game, owner, TREASURY)}
    pays = can_pay_it and run.ask(game, "optional", victim, [True, False], 1, 1, "pay the ransom?", **extra)[0]
    if pays:
        game.fx.random_notice = None
        pay_ransom(run, game, n)
        return
    if not physical:
        game.discard_card(victim, card)
        return
    game.fx.whole_hand = False
    try:
        game.force_discard(victim, 1, which, owner)
    finally:
        game.fx.random_notice = None
    run.flags["physical_discard"] = True


# ---------------------------------------------------------------- Queen Anne's Revenge

@plugin("blackbeard:queens_revenge")
def _queens_revenge(run, game, spec):
    owner = run.ctx.owner
    victim = 1 - owner
    held = stock(game, owner, TREASURY)
    flow = getattr(run, "flow", None)
    combat = {} if flow is None or flow.ctx is None else {"atk": flow.ctx.atk_value, "dfn": flow.ctx.def_value, "target": flow.tgt.fid,
                                                         "queen_attacks": run.ctx.played_as == "attack"}
    paid = run.ask(game, "amount", victim, list(range(held + 1)), 1, 1, "doubloons to pay", queens=QUEENS_STEP, treasury=held,
                   **combat)[0] if held else 0
    if not paid:
        return
    pay_ransom(run, game, paid)
    OPS["modify_value"](run, game, {"op": "modify_value", "card": "this", "amount": -QUEENS_STEP * paid})
