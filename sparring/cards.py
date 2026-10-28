from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .board import DATA_DIR

MEDUSA_BASE = 17600
HELLBOY_BASE = 19700


def memory_dir() -> Path:
    """Carpeta `unmatched-memory` hermana del repo (o de cualquier antecesor: un worktree vive mas hondo);
    `UNMATCHED_MEMORY` la fuerza. Solo la usa el importador de heroes (tools/import_hero.py), nunca la partida."""
    forced = os.environ.get("UNMATCHED_MEMORY")
    if forced:
        return Path(forced)
    for parent in DATA_DIR.parents:
        candidate = parent / "unmatched-memory"
        if (candidate / "data" / "heroes").is_dir():
            return candidate
    return DATA_DIR.parent.parent / "unmatched-memory"


@dataclass(frozen=True)
class Card:
    card_id: int
    title: str
    fighter: str
    type: str
    value: int | None
    boost: int
    text: str = ""
    tags: frozenset[str] = frozenset()     # etiquetas que cuentan los contadores del heroe (Hellboy: "destiny")

    @property
    def destiny(self) -> bool:
        return "destiny" in self.tags

    def usable_by(self, fighter_name: str) -> bool:
        return self.fighter == "any" or self.fighter == fighter_name

    @property
    def can_attack(self) -> bool:
        return self.type in ("attack", "versatile")

    @property
    def can_defend(self) -> bool:
        return self.type in ("defense", "versatile")

    @property
    def is_scheme(self) -> bool:
        return self.type == "scheme"


def load_medusa_deck() -> list[Card]:
    from .heroes import load_hero
    return load_hero("medusa").deck()


def load_hellboy_deck() -> list[Card]:
    from .heroes import load_hero
    return load_hero("hellboy").deck()
