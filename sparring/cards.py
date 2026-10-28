from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .board import DATA_DIR

MEDUSA_BASE = 17600
HELLBOY_BASE = 19700


def repo_toplevel(root: Path | None = None) -> Path:
    """Raiz del repo PRINCIPAL. Desde un worktree, `.git` es un fichero `gitdir: <principal>/.git/worktrees/<n>`
    (lo mismo que `git rev-parse --git-common-dir`); desde el repo principal, `.git` es la carpeta."""
    root = root or DATA_DIR.parent
    dotgit = root / ".git"
    if dotgit.is_file():
        text = dotgit.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text[len("gitdir:"):].strip())
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
            if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
                return gitdir.parent.parent.parent
    return root


def memory_dir() -> Path:
    """Carpeta `unmatched-memory` hermana del repo principal (nunca de un worktree ni de otra carpeta intermedia);
    `UNMATCHED_MEMORY` la fuerza. Solo la usa el importador de heroes (tools/import_hero.py), nunca la partida."""
    forced = os.environ.get("UNMATCHED_MEMORY")
    if forced:
        return Path(forced)
    return repo_toplevel().parent / "unmatched-memory"


def can_be_boost(card: "Card") -> bool:
    """Ivan's ruling (28/10): a card without a boost value cannot be used to boost."""
    return card.boost > 0


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
