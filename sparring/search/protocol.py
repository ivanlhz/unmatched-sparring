"""The minimum the search needs from a game engine.

The searcher (`ismcts.py`) knows nothing about Unmatched: it only talks to a `SearchState`. The adapter of the current
engine lives in `adapter.py`; the multi-hero engine (F07) implements this same Protocol and the search serves it
unchanged.

Moves (`Move`): any hashable value the adapter wants (tuples). Two rules:
  * `observe(move, viewer)` returns `move` as is when `viewer` is the one making it; for the others it may
    mask what is hidden (e.g. the card of a face-down attack). The search indexes each player's tree
    by what that player sees, so the simulated rival does not "read" a card it would not see at the table.
  * `determinize(observer, rng)` replaces ALL the information `observer` does not know (other hands, order of
    the decks, face-down cards) with a sample compatible with what is public. It must never read the rival's
    real hand: the sample comes from the whole deck minus what has been seen, and from the cards "known in hand" that the engine
    holds through a legitimate effect of looking at the hand.
"""
from __future__ import annotations

import random
from typing import Hashable, Protocol

Move = Hashable


class SearchState(Protocol):
    def clone(self) -> "SearchState":
        """Independent copy: applying moves to it does not touch the original."""
        ...

    def player_to_move(self) -> int: ...

    def turn_owner(self) -> int:
        """Whose turn it is (whoever moves may be another in mid-turn, e.g. the defender). The rollout
        ends when it changes: the leaf is evaluated as the end of the turn of whoever was moving, against the rival's turn."""
        ...

    def legal_moves(self) -> list[Move]:
        """Moves of whoever moves, with the current information (after determinizing, with the sampled hand)."""
        ...

    def apply(self, move: Move) -> None:
        """Applies the move and advances the automatic steps (end of turn, forced draws...) up to the next
        decision or the end."""
        ...

    def is_terminal(self) -> bool: ...

    def winner(self) -> int | None: ...

    def evaluate(self, player: int) -> float:
        """Value of the position for `player` in [0, 1] (1 = won). In a terminal state, 1 or 0."""
        ...

    def observe(self, move: Move, viewer: int) -> Hashable: ...

    def rollout_move(self, rng: random.Random) -> Move:
        """Cheap move for the rollout phase; may be a biased subset of the legal ones."""
        ...

    def determinize(self, observer: int, rng: random.Random) -> None: ...
