"""Chupacabra's plugins (docs/heroes/chupacabra.md): `chupacabra:ambush` and `chupacabra:tooth_and_tail`.

Ambush: "Your opponent discards 1 random card. Add its BOOST value to this card's attack value." The engine knows the bot's
hand and a simulation's, so the card is drawn from it. The human's hand is on the table: the bot names a position, the human
discards that card and presses Done, and the bot reads the card on the table (`random_discard.discard_random_known`).

Tooth and Tail: "Deal 1 damage to up to 2 fighters adjacent to Chupacabra. Chupacabra recovers 1 health for each fighter damaged
this way." The DSL has no "up to N distinct targets", and the heal counts the fighters that really took the damage."""
from __future__ import annotations

from ..i18n import t
from . import modifiers
from .ops_core import plugin
from .random_discard import discard_random_known
from .plugins_strange import _flow
from .select import fighter_candidates

ADJACENT = {"side": "any", "where": {"adjacent_to": "hero"}, "pick": "all"}
MOST_TARGETS = 2


@plugin("chupacabra:ambush")
def _ambush(run, game, spec):
    flow = _flow(run, "chupacabra:ambush")
    side = "atk" if run.ctx.played_as == "attack" else "def"
    card = discard_random_known(run, game, 1 - run.ctx.owner)
    if card is not None:
        modifiers.add_value(flow, side, card.boost, t("cf.ambush", title=card.title, boost=card.boost))


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
