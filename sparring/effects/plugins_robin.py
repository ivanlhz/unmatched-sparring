"""Robin Hood's plugin (docs/heroes/robin-hood.md): `robin:ambush` (the id carries the fid of the hero fighter, as the validator demands).

His Ambush reads word for word as the Raptors' ("Your opponent discards 1 random card. Add its BOOST value to this card's value"), so it
is that plugin under his own id: the discard from the hand by chance (the table player lays the card the bot names on their pile and the
bot reads it), a rule that forbids forced discards leaves nothing discarded, an empty hand adds 0."""
from __future__ import annotations

from .ops_core import plugin
from .plugins_raptors import _ambush

plugin("robin:ambush")(_ambush)
