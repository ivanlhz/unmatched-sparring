"""Raphael's plugin (docs/effects-dsl.md, section "Raphael"): `raphael:unbridled_rage`.

"DURING COMBAT: Discard any number of defense or versatile cards. Add +2 to this card's value for each card
discarded this way." The count of cards is free and feeds a value, which no op expresses.

- A bot (or a simulation) asks its controller for the cards (a `cards` request with `purpose: "bonus"`, `min 0`);
  `EffectAI` weighs each card's keep value against the damage the next +2 adds (`extra`: `foe`, `margin`, `per_card`).
- The human (table mode) never has their hand in the engine: a `cards` request (`purpose: "bonus"`, `table_discard`)
  waits while they put the cards they give up in their discard pile; the session reads the pile, checks each new card is
  a defense or versatile card of theirs (`session_rage`) and answers with them, so the engine discards exactly those."""
from __future__ import annotations

from ..i18n import t
from . import modifiers, table
from .model import EffectError
from .ops_core import plugin


@plugin("raphael:unbridled_rage")
def _unbridled_rage(run, game, spec):
    args = spec.get("args") or {}
    types = tuple(args["types"])
    discard_for_bonus(run, game, int(args["per_card"]), lambda c: c.type in types, "raphael:unbridled_rage")


def discard_for_bonus(run, game, per_card: int, wanted, plugin_id: str, **ask_extra) -> None:
    """"Discard any number of `wanted` cards. Add +`per_card` to this card's value for each": Raphael's Unbridled rage
    (defense or versatile cards) and Ciri's Channel the source (Source cards). `ask_extra` rides in the request
    (Ciri's `tag`, which the human's panel reads to name the cards that do not qualify)."""
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError(f"{plugin_id}: only inside a combat")
    owner = run.ctx.owner
    side = "atk" if run.ctx.played_as == "attack" else "def"
    hand = game.players[owner].hand
    if table.physical(game, owner):
        st = game.players[owner]
        gone = {c.card_id for c in (*st.discard, *st.removed, *st.tucked)}
        options = [c.card_id for c in st.full_set if wanted(c) and c.card_id not in gone]
        got = run.ask(game, "cards", owner, options, 0, len(options), "put the cards to give up in your discard pile",
                      zone="discard", purpose="bonus", of=owner, per_card=per_card, table_discard=True, **ask_extra)
        by_id = {c.card_id: c for c in st.full_set}
        for card_id in got:
            table.make_known(game, owner, by_id[card_id], keep=tuple(by_id[i] for i in got))
            game.discard_card(owner, by_id[card_id])
        n = len(got)
    else:
        eligible = [c for c in hand if wanted(c)]
        foe = flow.tgt if side == "atk" else flow.att
        mine, theirs = (flow.ctx.atk_value, flow.ctx.def_value) if side == "atk" else (flow.ctx.def_value, flow.ctx.atk_value)
        got = run.ask(game, "cards", owner, [c.card_id for c in eligible], 0, len(eligible), "bonus discard",
                      zone="hand", purpose="bonus", of=owner, per_card=per_card, foe=foe.fid, attacking=side == "atk",
                      margin=mine - theirs, **ask_extra)
        by_id = {c.card_id: c for c in eligible}
        for card_id in got:
            game.discard_card(owner, by_id[card_id])
        n = len(got)
    if n:
        modifiers.add_value(flow, side, per_card * n, card_title(run, game))


def card_title(run, game) -> str:
    card = None if run.ctx.card_id is None else game.card_of(run.ctx.card_id, run.ctx.owner)
    return card.title if card is not None else t("cause.effect")
