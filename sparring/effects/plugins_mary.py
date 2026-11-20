"""Bloody Mary's plugin (docs/heroes/bloody-mary.md): `mary:out_of_the_mirror`.

Out Of The Mirror: "Your opponent discards 1 random card. Add its BOOST value to this card's value." The same flow as the Raptors' and
Chupacabra's Ambush: `random_discard.discard_random_known` draws the card of the engine's player by chance and, for the table player,
has them lay the position the bot names on their discard pile and reads which card it was. A rule that forbids forced discards
(Counterhex Shield) leaves nothing discarded and nothing added; an empty hand adds 0."""
from __future__ import annotations

from .model import EffectError
from .ops_core import OPS, plugin
from .random_discard import discard_random_known


@plugin("mary:out_of_the_mirror")
def _out_of_the_mirror(run, game, spec):
    if getattr(run, "flow", None) is None:
        raise EffectError("mary:out_of_the_mirror: only inside a combat")
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    card = discard_random_known(run, game, rival) if game.fx.can_force_discard(rival, owner) else None
    run.bind("cards", "burnt", [] if card is None else [card.card_id])
    OPS["modify_value"](run, game, {"op": "modify_value", "card": "this", "amount": {"attr": "boost", "of": "$burnt"}})
