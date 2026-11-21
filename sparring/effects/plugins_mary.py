"""Bloody Mary's plugin (docs/heroes/bloody-mary.md): `mary:out_of_the_mirror`.

Out Of The Mirror: "Your opponent discards 1 random card. Add its BOOST value to this card's value." The same flow as Chupacabra's
Ambush: `random_discard.discard_random_known` draws the card of the engine's player by chance and, for the table player, has them lay
the position the bot names on their discard pile and reads which card it was. A rule that forbids forced discards (Counterhex Shield)
leaves nothing discarded and nothing added; an empty hand adds 0.

The BOOST is read off the card object itself, never through an id binding: Bloody Mary's deck shares CardIDs 17600-17629 with the other
sheet-176 decks, so the id of the rival's card names a different card in her own deck (docs/card-identity.md)."""
from __future__ import annotations

from ..i18n import t
from . import modifiers
from .ops_core import plugin
from .plugins_strange import _flow
from .random_discard import discard_random_known


@plugin("mary:out_of_the_mirror")
def _out_of_the_mirror(run, game, spec):
    flow = _flow(run, "mary:out_of_the_mirror")
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    card = discard_random_known(run, game, rival) if game.fx.can_force_discard(rival, owner) else None
    if card is not None:
        modifiers.add_value(flow, "atk" if run.ctx.played_as == "attack" else "def", card.boost,
                            t("cf.ambush", title=card.title, boost=card.boost))
