from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cards import Card
    from .state import Fighter, Game


class Controller:
    """Decisiones que el motor delega en quien lleva a cada jugador (IA, guion o puente con el humano)."""

    def take_turn(self, game: "Game") -> None:
        raise NotImplementedError

    def choose_defense(self, game: "Game", attacker: "Fighter", target: "Fighter") -> "Card | None":
        return None

    def choose_combat_boost(self, game: "Game", ctx) -> "Card | None":
        return None

    def choose_discard(self, game: "Game", player: int, n: int, reason: str) -> list["Card"]:
        hand = game.players[player].hand
        return hand[-n:] if n else []

    def choose_move(self, game: "Game", fighter: "Fighter", steps: int, through_enemies: bool = False) -> int | None:
        return None

    def choose_placement(self, game: "Game", fighter: "Fighter", options: list[int]) -> int | None:
        return options[0] if options else None

    def choose_effect(self, game: "Game", req) -> list | None:
        """Answer a DSL ChoiceRequest (sparring/effects/choose.py). None = use the generic per-kind fallback, which
        goes through choose_move / choose_discard / choose_placement."""
        return None
