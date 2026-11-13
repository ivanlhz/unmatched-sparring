"""The Raptors' plugin (docs/heroes/raptors.md): `blue:ambush` (the id carries the fid of the hero fighter, as the validator demands).

Ambush: "Your opponent discards 1 random card. Add its BOOST value to this card's value." The discard is `random_discard.discard_random_known`
(the engine's player: by chance; the table player: the bot names a position, they discard that card and the bot reads it); a rule that
forbids forced discards (Counterhex Shield) leaves nothing discarded and nothing added; an empty hand adds 0."""
from __future__ import annotations

from .model import EffectError
from .ops_core import OPS, plugin
from .random_discard import discard_random_known


@plugin("blue:ambush")
def _ambush(run, game, spec):
    if getattr(run, "flow", None) is None:
        raise EffectError("blue:ambush: only inside a combat")
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    card = discard_random_known(run, game, rival) if game.fx.can_force_discard(rival, owner) else None
    run.bind("cards", "burnt", [] if card is None else [card.card_id])
    OPS["modify_value"](run, game, {"op": "modify_value", "card": "this", "amount": {"attr": "boost", "of": "$burnt"}})
