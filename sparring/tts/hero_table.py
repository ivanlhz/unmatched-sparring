"""Lo que el puente necesita del guardado real para cada heroe: `data/tts/<slug>.json`.

El fichero lleva los GUID de la bolsa del heroe, de su mazo, de la miniatura (o ficha) y el dial de vida de cada luchador,
las fichas especiales (habilidad de Hellboy, intuicion de Abe) y los diales de contador (destinos), mas el rango de CardID
y la imagen (FaceURL, BackURL) de su hoja de cartas. Todo sale de la bolsa del heroe en
`saves/Unmatched Official Tournament Table October 2026 (Hellboy).json` (solo lectura); `tests/test_tts_data.py` lo
comprueba contra ese guardado.

`config/partida.json` solo dice QUE heroes juegan y como es la MESA (asientos, zonas, puntos); `table_defaults` saca de
estos ficheros lo propio de cada heroe y lo deja en la forma que ya esperaba la configuracion (`pieces`, `dials`,
`nicknames`, GUID de mazos, rangos de CardID, identidades de mazo)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..board import DATA_DIR
from ..heroes import DECK_SIZE, HeroDef, load_hero

TTS_DIR = DATA_DIR / "tts"


class HeroTableError(Exception):
    """El fichero de TTS de un heroe no sirve (falta o no concuerda con su HeroDef); el mensaje dice que."""


@dataclass(frozen=True)
class FighterTable:
    fid: str
    pieces: tuple[str, ...]        # GUID de la miniatura; varios si cambia de GUID al cambiar de estado
    dial: str | None               # dial de vida (None: pieza de 1 PV)
    dial_max: int | None
    nickname: str | None           # nombre propio de la ficha (los agentes de Abe); si no, el del HeroDef


@dataclass(frozen=True)
class HeroTable:
    slug: str
    bag: str                       # bolsa infinita del heroe
    inner_bag: str                 # bolsa interior: de ella salen todos los objetos conservando su GUID
    deck_guid: str
    card_ids: tuple[int, int]
    character_card_id: int
    identity: tuple[tuple[str, str], ...]
    fighters: dict[str, FighterTable]
    tokens: dict[str, str] = field(default_factory=dict)          # fichas especiales por nombre
    counter_dials: dict[str, str] = field(default_factory=dict)   # dial de cada contador del heroe (destinos)

    def unpack_items(self) -> list[tuple[str, str]]:
        """(clase, GUID) de todo lo que hay que sacar de la bolsa interior para jugar con el heroe."""
        items = [("deck", self.deck_guid)]
        for f in self.fighters.values():
            items.append(("piece", f.pieces[0]))                # la otra cara es un estado del mismo objeto
            if f.dial:
                items.append(("dial", f.dial))
        items += [("token", g) for g in self.tokens.values()]
        items += [("dial", g) for g in self.counter_dials.values()]
        return items

    def all_guids(self) -> list[str]:
        out = [self.deck_guid]
        for f in self.fighters.values():
            out += [*f.pieces, *([f.dial] if f.dial else [])]
        return out + [*self.tokens.values(), *self.counter_dials.values()]


def _guid_list(value, where: str) -> tuple[str, ...]:
    guids = (value,) if isinstance(value, str) else tuple(value)
    if not guids or not all(isinstance(g, str) and g for g in guids):
        raise HeroTableError(f"{where}: GUID no valido {value!r}")
    return guids


def parse_hero_table(raw: dict, hero: HeroDef, where: str = "tts") -> HeroTable:
    try:
        deck = raw["deck"]
        ids = deck["card_ids"]
        fighters = {fid: FighterTable(fid, _guid_list(v["piece"], f"{where}: {fid}"), v.get("dial"),
                                      None if v.get("dial") is None else int(v["dial_max"]), v.get("nickname"))
                    for fid, v in raw["fighters"].items()}
        table = HeroTable(raw["slug"], raw["bag"]["guid"], raw["bag"]["inner"], deck["guid"], (int(ids[0]), int(ids[1])),
                          int(deck["character_card_id"]),
                          tuple((i["face"], i["back"]) for i in deck["identity"]), fighters,
                          dict(raw.get("tokens") or {}), dict(raw.get("counter_dials") or {}))
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise HeroTableError(f"{where}: datos de TTS no validos ({e!r})") from None
    _validate(table, hero, where)
    return table


def _validate(t: HeroTable, hero: HeroDef, where: str) -> None:
    if t.slug != hero.slug:
        raise HeroTableError(f"{where}: el slug es {t.slug!r}, no {hero.slug!r}")
    specs = {f.fid: f for f in hero.fighters()}
    if set(t.fighters) != set(specs):
        raise HeroTableError(f"{where}: luchadores {sorted(t.fighters)} distintos de los del HeroDef {sorted(specs)}")
    for fid, f in t.fighters.items():
        if f.dial and f.dial_max != specs[fid].hp:
            raise HeroTableError(f"{where}: {fid}: el dial llega a {f.dial_max} y el HeroDef dice {specs[fid].hp} PV")
        if f.dial is None and specs[fid].hp > 1:
            raise HeroTableError(f"{where}: {fid}: tiene {specs[fid].hp} PV y no hay dial")
    if hero.card_base is not None and t.card_ids != (hero.card_base, hero.card_base + DECK_SIZE - 1):
        raise HeroTableError(f"{where}: rango de CardID {t.card_ids} distinto de la hoja del HeroDef")
    if not t.identity:
        raise HeroTableError(f"{where}: sin identidad (FaceURL, BackURL) del mazo")
    missing = sorted({"destiny"} & set(hero.counters) - set(t.counter_dials))
    if missing:
        raise HeroTableError(f"{where}: falta el dial del contador {', '.join(missing)}")
    guids = t.all_guids()
    if len(set(guids)) != len(guids):
        raise HeroTableError(f"{where}: GUID repetidos")


@lru_cache(maxsize=None)
def load_hero_table(slug: str, tts_dir: Path = TTS_DIR) -> HeroTable:
    hero = load_hero(slug)
    path = tts_dir / f"{slug}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise HeroTableError(f"no hay datos de TTS para {slug!r}: falta {path}") from None
    except ValueError as e:
        raise HeroTableError(f"{path}: JSON no valido ({e})") from None
    return parse_hero_table(raw, hero, path.name)


def nicknames_for(hero: HeroDef, table: HeroTable) -> dict[str, str]:
    """Nombre de cada luchador en los mensajes y botones: el de su ficha si la tiene; si no, el del HeroDef con su
    numero cuando hay varios iguales (Harpy 1, Harpy 2...)."""
    counts = {s.fid: s.count for s in hero.sidekicks}
    out = {}
    for spec in hero.fighters():
        base = spec.fid.rstrip("0123456789")
        own = table.fighters[spec.fid].nickname
        if own:
            out[spec.fid] = own
        elif spec.hero or counts.get(base, 1) == 1:
            out[spec.fid] = spec.name
        else:
            out[spec.fid] = f"{spec.name} {spec.fid[len(base):]}"
    return out


def table_defaults(bot_slug: str, human_slug: str) -> dict:
    """Lo propio de los dos heroes, con las claves de `config/partida.json` (que manda si las repite)."""
    if bot_slug == human_slug:
        raise HeroTableError(f"los dos bandos juegan {bot_slug!r}: no hay piezas ni mazo para dos")
    bot, human = load_hero(bot_slug), load_hero(human_slug)
    tb, th = load_hero_table(bot_slug), load_hero_table(human_slug)
    first, second = sorted((tb.card_ids, th.card_ids))
    if first[1] >= second[0]:
        raise HeroTableError(f"los rangos de CardID de {bot_slug} y {human_slug} se solapan")
    pieces, dials, nicknames = {}, {}, {}
    for hero, table in ((bot, tb), (human, th)):
        nicknames.update(nicknames_for(hero, table))
        for fid, f in table.fighters.items():
            pieces[fid] = f.pieces[0] if len(f.pieces) == 1 else list(f.pieces)
            if f.dial:
                dials[fid] = f.dial
    if len(set(nicknames.values())) != len(nicknames):
        raise HeroTableError("dos luchadores con el mismo nombre: " + ", ".join(sorted(nicknames.values())))
    out = {"nicknames": nicknames, "pieces": pieces, "dials": dials,
           "bot_deck_guid": tb.deck_guid, "human_deck_guid": th.deck_guid,
           "bot_card_ids": list(tb.card_ids), "human_card_ids": list(th.card_ids),
           "bot_identity": [list(p) for p in tb.identity], "human_identity": [list(p) for p in th.identity]}
    if human.forms is not None and human.forms.counter in th.counter_dials:
        out["destiny_dial"] = th.counter_dials[human.forms.counter]
    return out
