from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .board import DATA_DIR

MEDUSA_BASE = 17600
HELLBOY_BASE = 19700


def memory_dir() -> Path:
    """Carpeta `unmatched-memory` hermana del repo (o de cualquier antecesor: un worktree vive mas hondo);
    `UNMATCHED_MEMORY` la fuerza."""
    forced = os.environ.get("UNMATCHED_MEMORY")
    if forced:
        return Path(forced)
    for parent in DATA_DIR.parents:
        candidate = parent / "unmatched-memory"
        if (candidate / "data" / "heroes").is_dir():
            return candidate
    return DATA_DIR.parent.parent / "unmatched-memory"


HELLBOY_SOURCE = memory_dir() / "data" / "heroes" / "hellboy.json"


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
    raw = json.loads((DATA_DIR / "medusa_cards.json").read_text(encoding="utf-8"))
    return [
        Card(MEDUSA_BASE + c["idx"], c["title"], c["fighter"], c["type"], c["value"], c["boost"], c["text"])
        for c in raw["cards"]
    ]


def _hellboy_text(src: dict) -> str:
    parts = []
    for key, label in (("effect", ""), ("effectImmediately", "IMMEDIATELY: "), ("effectDuring", "DURING COMBAT: "), ("effectAfter", "AFTER COMBAT: ")):
        if src.get(key):
            parts.append(label + src[key].strip())
    return " ".join(parts)


def load_hellboy_deck(source=HELLBOY_SOURCE) -> list[Card]:
    """Valores, boost y texto desde hellboy.json (por título); restricción y destino desde hellboy_cards.json."""
    src = {c["title"]: c for c in json.loads(open(source, encoding="utf-8").read())["cards"]}
    raw = json.loads((DATA_DIR / "hellboy_cards.json").read_text(encoding="utf-8"))
    deck = []
    for c in raw["cards"]:
        s = src[c["title"]]
        deck.append(Card(HELLBOY_BASE + c["idx"], c["title"], c["fighter"], s["type"], s["value"], s["boostValue"],
                         _hellboy_text(s), frozenset({"destiny"} if c["destiny"] else ())))
    return deck
