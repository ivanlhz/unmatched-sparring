"""Ciri's plugin (docs/heroes/ciri.md): `ciri:channel_the_source`.

"DURING COMBAT: You may discard any number of Source cards from your hand. Add +2 to this card's value for each Source card you
discarded." The free count of cards feeding a value is Raphael's Unbridled rage with another filter, so the mechanism is
`plugins_raphael.discard_for_bonus` (the bot weighs each card against the damage 2 more points add; the human lays the cards on
their discard pile and the session reads them, `session_rage`). Every other card of her deck is plain DSL, UNCONTAINABLE POWER
included (`cards_uncancelable`, `modifiers.is_uncancelable`)."""
from __future__ import annotations

from .ops_core import plugin
from .plugins_raphael import discard_for_bonus

SOURCE_TAG = "source"
BONUS_PER_CARD = 2


@plugin("ciri:channel_the_source")
def _channel_the_source(run, game, spec):
    discard_for_bonus(run, game, BONUS_PER_CARD, lambda c: SOURCE_TAG in c.tags, "ciri:channel_the_source", tag=SOURCE_TAG)
