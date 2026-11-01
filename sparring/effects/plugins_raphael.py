"""Raphael's plugin (docs/effects-dsl.md, section "Raphael"): `raphael:unbridled_rage`.

"DURING COMBAT: Discard any number of defense or versatile cards. Add +2 to this card's value for each card
discarded this way." The count of cards is free and feeds a value, which no op expresses.

- A bot (or a simulation) asks its controller for the cards (a `cards` request with `purpose: "bonus"`, `min 0`);
  `EffectAI` weighs each card's keep value against the damage the next +2 adds (`extra`: `foe`, `margin`, `per_card`).
- The human (table mode) never has their hand in the engine: the panel asks HOW MANY (an `amount` request) and the
  table owes that many discards from their hand, the way every physical discard goes (`Game.force_discard`)."""
from __future__ import annotations

from ..i18n import t
from . import modifiers, table
from .model import EffectError
from .ops_core import plugin


@plugin("raphael:unbridled_rage")
def _unbridled_rage(run, game, spec):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError("raphael:unbridled_rage: only inside a combat")
    args = spec.get("args") or {}
    types, per_card = tuple(args["types"]), int(args["per_card"])
    owner = run.ctx.owner
    side = "atk" if run.ctx.played_as == "attack" else "def"
    hand = game.players[owner].hand
    if table.physical(game, owner):
        n = run.ask(game, "amount", owner, list(range(len(hand) + 1)), 1, 1, "discard how many", op="bonus_discard")[0]
        if n:
            game.force_discard(owner, n, card_title(run, game), owner)
            run.flags["physical_discard"] = True
    else:
        eligible = [c for c in hand if c.type in types]
        foe = flow.tgt if side == "atk" else flow.att
        mine, theirs = (flow.ctx.atk_value, flow.ctx.def_value) if side == "atk" else (flow.ctx.def_value, flow.ctx.atk_value)
        got = run.ask(game, "cards", owner, [c.card_id for c in eligible], 0, len(eligible), "bonus discard",
                      zone="hand", purpose="bonus", of=owner, per_card=per_card, foe=foe.fid, attacking=side == "atk",
                      margin=mine - theirs)
        by_id = {c.card_id: c for c in eligible}
        for card_id in got:
            game.discard_card(owner, by_id[card_id])
        n = len(got)
    if n:
        modifiers.add_value(flow, side, per_card * n, card_title(run, game))


def card_title(run, game) -> str:
    card = next((c for p in game.players for c in p.full_set if c.card_id == run.ctx.card_id), None)
    return card.title if card is not None else t("cause.effect")
