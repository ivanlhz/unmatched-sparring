"""Combat as a serializable state machine. See docs/combat-flow.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Phase(str, Enum):
    DECLARED = "declared"
    CARDS_SET = "cards_set"
    REVEALED = "revealed"
    IMMEDIATELY = "immediately"
    DURING = "during"
    DAMAGE = "damage"
    AFTER = "after"
    DONE = "done"


_RESERVED = {"kind", "player", "card", "deck"}


@dataclass
class PendingChoice:
    """A decision the flow is waiting for. The flat dict form is the save format of `Pending.boost_wait`."""
    kind: str                    # only "boost" in this delivery
    player: int                  # who decides
    card_id: int                 # card whose effect asks
    deck: bool = False           # Flame Lash: the boost is the bottom card of the deck
    extra: dict = field(default_factory=dict)    # caller-owned JSON-safe data (session: guid, baseline, hand, stuck)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "player": self.player, "card": self.card_id, "deck": self.deck, **self.extra}

    @classmethod
    def from_dict(cls, raw, *, default_player: int, deck_of: Callable[[int], bool]) -> "PendingChoice":
        """Also reads the old format (no "kind"/"player"): a boost of `default_player`, `deck` recomputed from the
        card. KeyError if the structure is invalid."""
        if not isinstance(raw, dict):
            raise KeyError("pending choice")
        kind, player, card = raw.get("kind", "boost"), raw.get("player", default_player), raw.get("card")
        if kind != "boost" or not _is_int(player) or not _is_int(card):
            raise KeyError("pending choice")
        deck = raw.get("deck") is True or deck_of(card)
        return cls(kind, player, card, deck, {k: v for k, v in raw.items() if k not in _RESERVED})


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
