"""Catalog of every hero deck in the tournament save (`data/catalog/heroes.json`, written by `tools/import_catalog.py`).

It only NAMES heroes: a deck on the table is matched by its images (FaceURL|BackURL), so the detector can say "Raphael
(not playable yet)" instead of "unknown deck". What the bot can play is decided by `data/tts/<slug>.json`, not here."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .board import DATA_DIR

CATALOG_PATH = DATA_DIR / "catalog" / "heroes.json"


@dataclass(frozen=True)
class CatalogHero:
    slug: str
    name: str
    identity: frozenset[str]          # "face|back" of the images only this hero's deck uses


@dataclass(frozen=True)
class Catalog:
    heroes: tuple[CatalogHero, ...] = ()
    shared: frozenset[str] = frozenset()

    def name_of(self, slug: str) -> str | None:
        return next((h.name for h in self.heroes if h.slug == slug), None)

    def identify(self, images: list[str]) -> CatalogHero | None:
        """The one hero whose images include every distinctive image of the deck; None if there is none, the deck has
        no distinctive image, or several heroes fit (identical decks cannot be told apart)."""
        own = {i for i in images if isinstance(i, str)} - self.shared
        fits = [h for h in self.heroes if own and own <= h.identity]
        return fits[0] if len(fits) == 1 else None


def _key(pair: dict) -> str:
    return f"{pair['face']}|{pair['back']}"


def parse_catalog(raw: dict) -> Catalog:
    return Catalog(tuple(CatalogHero(h["slug"], h["name"], frozenset(_key(p) for p in h["identity"]))
                         for h in raw["heroes"]),
                   frozenset(_key(p) for p in raw.get("shared_pairs", ())))


@lru_cache(maxsize=None)
def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    """An absent or unreadable catalog is an empty one: the detector then behaves as before the catalog existed."""
    try:
        return parse_catalog(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return Catalog()
