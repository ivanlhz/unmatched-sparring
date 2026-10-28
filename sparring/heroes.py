"""HeroDef: lo propio de cada heroe, leido de `data/heroes/<slug>.json`.

El fichero lo genera `tools/import_hero.py` a partir de unmatched-memory (solo lectura) y del overlay a mano
`data/heroes/overlay/<slug>.json` (hoja de CardID, restricciones de luchador, etiquetas, formas, contadores,
disparadores y pasivas). El motor solo lee el HeroDef generado: nunca depende de unmatched-memory en tiempo de
partida.

Formas y contadores: un contador cuenta las cartas con una etiqueta en una pila (hoy solo el descarte); la forma
es `below` mientras el contador no llega a `threshold` y `at_or_above` desde entonces (Hellboy: 6 destinos).
Disparadores y pasivas se cargan como datos (dicts) y los interpreta el motor por su `effect`; hasta el paso 8 del
plan solo la pasiva `attack_bonus` esta conectada."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .board import DATA_DIR
from .cards import Card

HEROES_DIR = DATA_DIR / "heroes"
CARD_TYPES = ("attack", "defense", "versatile", "scheme")
DECK_SIZE = 30


class HeroDataError(Exception):
    """El HeroDef no sirve para jugar (falta o esta mal); el mensaje dice que."""


@dataclass(frozen=True)
class SidekickDef:
    fid: str          # prefijo del id de luchador: con count > 1 se numera (harpy1, harpy2, harpy3)
    name: str
    count: int
    hp: int
    move: int
    ranged: bool


@dataclass(frozen=True)
class FighterSpec:
    fid: str
    name: str
    hero: bool
    hp: int
    move: int
    ranged: bool


@dataclass(frozen=True)
class CounterDef:
    name: str
    pile: str         # "discard": donde se cuentan las cartas
    tag: str          # etiqueta de carta que cuenta


@dataclass(frozen=True)
class FormDef:
    counter: str
    threshold: int
    below: str
    at_or_above: str

    def of(self, count: int) -> str:
        return self.at_or_above if count >= self.threshold else self.below


@dataclass(frozen=True)
class HeroDef:
    slug: str
    name: str
    fid: str
    hp: int
    move: int
    ranged: bool
    ability: str
    sidekicks: tuple[SidekickDef, ...]
    forms: FormDef | None
    counters: dict[str, CounterDef]
    triggers: tuple[dict, ...]
    passives: tuple[dict, ...]
    card_base: int | None
    cards: tuple[dict, ...]

    @property
    def fighter_names(self) -> set[str]:
        return {self.name, *(s.name for s in self.sidekicks)}

    def fighters(self) -> list[FighterSpec]:
        """Heroe y ayudantes en el orden de colocacion, con sus ids de luchador."""
        out = [FighterSpec(self.fid, self.name, True, self.hp, self.move, self.ranged)]
        for s in self.sidekicks:
            for i in range(1, s.count + 1):
                fid = f"{s.fid}{i}" if s.count > 1 else s.fid
                out.append(FighterSpec(fid, s.name, False, s.hp, s.move, s.ranged))
        return out

    def deck(self) -> list[Card]:
        if self.card_base is None:
            raise HeroDataError(f"{self.slug}: mazo sin hoja de CardID ni restricciones de luchador (pendiente de F08)")
        return [Card(self.card_base + c["idx"], c["title"], c["fighter"], c["type"], c["value"], c["boost"],
                     c.get("text", ""), frozenset(c.get("tags", ()))) for c in self.cards]

    def attack_bonus(self, form: str | None, fighter_is_hero: bool) -> int:
        """Pasivas `attack_bonus` activas en esa forma (Hellboy: +2 en ANUNG UN RAMA)."""
        total = 0
        for p in self.passives:
            if p.get("effect") != "attack_bonus" or p.get("form", form) != form:
                continue
            if p.get("fighter", "hero") == "hero" and not fighter_is_hero:
                continue
            total += int(p["n"])
        return total


def hero_path(slug: str, heroes_dir: Path = HEROES_DIR) -> Path:
    return heroes_dir / f"{slug}.json"


def _ranged(attack: str, where: str) -> bool:
    if attack not in ("melee", "range"):
        raise HeroDataError(f"{where}: ataque desconocido {attack!r} (melee o range)")
    return attack == "range"


def parse_hero(raw: dict, where: str = "hero") -> HeroDef:
    try:
        slug, name = raw["slug"], raw["name"]
        sidekicks = tuple(SidekickDef(s["fid"], s["name"], int(s["count"]), int(s["hp"]), int(s["move"]),
                                      _ranged(s["attack"], f"{where}: ayudante {s['name']}"))
                          for s in raw.get("sidekicks", ()))
        counters = {k: CounterDef(k, v["pile"], v["tag"]) for k, v in (raw.get("counters") or {}).items()}
        f = raw.get("forms")
        forms = None if f is None else FormDef(f["counter"], int(f["threshold"]), f["below"], f["at_or_above"])
        deck = raw.get("deck") or {}
        hero = HeroDef(slug, name, raw["fid"], int(raw["hp"]), int(raw["move"]), _ranged(raw["attack"], where),
                       raw.get("ability") or "", sidekicks, forms, counters,
                       tuple(raw.get("triggers") or ()), tuple(raw.get("passives") or ()),
                       deck.get("card_base"), tuple(deck.get("cards") or ()))
    except (KeyError, TypeError, ValueError) as e:
        raise HeroDataError(f"{where}: HeroDef no valido ({e!r})") from None
    _validate(hero, where)
    return hero


def _validate(h: HeroDef, where: str) -> None:
    if h.hp <= 0 or h.move < 0:
        raise HeroDataError(f"{where}: vida o movimiento no validos")
    if any(s.count <= 0 or s.hp <= 0 for s in h.sidekicks):
        raise HeroDataError(f"{where}: ayudante con cantidad o vida no validas")
    fids = [f.fid for f in h.fighters()]
    if len(set(fids)) != len(fids):
        raise HeroDataError(f"{where}: ids de luchador repetidos {fids}")
    if h.forms is not None:
        if h.forms.counter not in h.counters:
            raise HeroDataError(f"{where}: la forma usa el contador {h.forms.counter!r}, que no existe")
    for c in h.counters.values():
        if c.pile != "discard":
            raise HeroDataError(f"{where}: contador {c.name}: pila desconocida {c.pile!r}")
    if h.card_base is None:
        return
    if len(h.cards) != DECK_SIZE:
        raise HeroDataError(f"{where}: el mazo tiene {len(h.cards)} cartas, no {DECK_SIZE}")
    idxs = [c.get("idx") for c in h.cards]
    if sorted(idxs) != list(range(DECK_SIZE)):
        raise HeroDataError(f"{where}: los idx de la hoja deben ser 0..{DECK_SIZE - 1} sin repetir")
    allowed = h.fighter_names | {"any"}
    for c in h.cards:
        if c.get("type") not in CARD_TYPES:
            raise HeroDataError(f"{where}: {c.get('title')!r}: tipo {c.get('type')!r}")
        if c.get("fighter") not in allowed:
            raise HeroDataError(f"{where}: {c.get('title')!r}: restriccion {c.get('fighter')!r} no es un luchador")
        if (c["type"] == "scheme") != (c.get("value") is None):
            raise HeroDataError(f"{where}: {c.get('title')!r}: solo los planes van sin valor")


@lru_cache(maxsize=None)
def load_hero(slug: str, heroes_dir: Path = HEROES_DIR) -> HeroDef:
    path = hero_path(slug, heroes_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise HeroDataError(f"no hay HeroDef para {slug!r}: falta {path}") from None
    except ValueError as e:
        raise HeroDataError(f"{path}: JSON no valido ({e})") from None
    if raw.get("slug") != slug:
        raise HeroDataError(f"{path}: el slug del fichero es {raw.get('slug')!r}, no {slug!r}")
    return parse_hero(raw, str(path.name))


def available_heroes(heroes_dir: Path = HEROES_DIR) -> list[str]:
    return sorted(p.stem for p in heroes_dir.glob("*.json"))
