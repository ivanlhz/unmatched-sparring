"""Chupacabra's plugins (docs/heroes/chupacabra.md): `chupacabra:ambush` and `chupacabra:tooth_and_tail`.

Ambush: "Your opponent discards 1 random card. Add its BOOST value to this card's attack value." The engine knows the bot's
hand and a simulation's, so the card is drawn from it. The human's hand is on the table (the engine's copy holds
placeholders): the engine draws the POSITION from the hand size (`ops_core._random_positions_text`, as every random discard from
the human's hand), the human discards that card by hand and presses its BOOST value, which is all the bot is ever told.

Tooth and Tail: "Deal 1 damage to up to 2 fighters adjacent to Chupacabra. Chupacabra recovers 1 health for each fighter damaged
this way." The DSL has no "up to N distinct targets", and the heal counts the fighters that really took the damage."""
from __future__ import annotations

from ..i18n import t
from . import modifiers, table
from .ops_core import _card_title, _random_positions_text, plugin
from .plugins_strange import _flow
from .select import fighter_candidates

ADJACENT = {"side": "any", "where": {"adjacent_to": "hero"}, "pick": "all"}
MOST_TARGETS = 2


@plugin("chupacabra:ambush")
def _ambush(run, game, spec):
    flow = _flow(run, "chupacabra:ambush")
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    side = "atk" if run.ctx.played_as == "attack" else "def"
    st = game.players[rival]
    if not st.hand:
        return
    if table.physical(game, rival):
        boost = _physical_discard(run, game, rival)
        if boost is None:
            return
        label = t("cf.ambush_unseen", boost=boost)
    else:
        card = run.random_sample(list(st.hand), 1)[0]
        game.discard_card(rival, card)
        boost = card.boost
        label = t("cf.ambush", title=card.title, boost=boost)
    modifiers.add_value(flow, side, boost, label)


def _physical_discard(run, game, rival: int) -> int | None:
    """The human discards the card at the drawn position by hand (settled at End action) and says its BOOST value. The discard is
    registered once even if the op reruns after the answer; None when they had nothing left to give (or a status stops the discard)."""
    if not run.flags.get("ambush_discard"):
        owed = table.discards_owed(game, rival)
        reason = _random_positions_text(game, run, rival, 1, _card_title(game, run))
        game.force_discard(rival, 1, reason, run.ctx.owner)               # the table's copy of the hand holds placeholders: nothing is returned
        run.flags["ambush_discard"] = table.discards_owed(game, rival) > owed
    if not run.flags["ambush_discard"]:
        return None
    boosts = sorted({c.boost for c in game.players[rival].full_set})
    return int(run.ask(game, "amount", rival, boosts, 1, 1, "boost value of the discarded card", ambush_boost=True)[0])


@plugin("chupacabra:tooth_and_tail")
def _tooth_and_tail(run, game, spec):
    owner = run.ctx.owner
    cands = fighter_candidates(game, run, ADJACENT)[0]
    if len(cands) > MOST_TARGETS:
        got = run.ask(game, "fighter", owner, [f.fid for f in cands], 0, MOST_TARGETS, "choose up to 2 fighters", op="damage", amount=1)
        cands = [game.fighters[i] for i in got]
    hit = [f for f in cands if game.damage(f, 1, "effect") > 0]
    if hit:
        game.heal(game.hero(owner), len(hit))
