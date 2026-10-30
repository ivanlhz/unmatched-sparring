"""Que heroe juega cada bando, leido de los mazos que hay sobre la mesa (solo lectura).

Un heroe esta "en la mesa" si hay un Deck o Card suelto con CardID de su rango (`data/tts/<slug>.json`, `deck.card_ids`)
Y la imagen de su mazo (`deck.identity`): el CardID solo no basta, en el guardado del torneo casi todos los mazos
(Raphael, Alice, Ciri...) usan el DeckID 176 de Medusa. Lo de dentro de las bolsas no cuenta. Cada pila se asigna al bando de cuyo sitio de mazo esta mas cerca; el bando de un
heroe es aquel donde tiene mas cartas (y al menos MIN_CARDS); entre varios candidatos solo gana uno con >=2x el segundo. Las miniaturas sueltas solo sirven para explicar el error. Si algo no esta
claro no se adivina: un mazo que no es de ningun heroe jugable se busca por sus imagenes en el catalogo
(`data/catalog/heroes.json`, `sparring/hero_catalog.py`); si es de un heroe conocido pero no jugable, se cuenta como
cualquier otro y, si gana su bando, se niega a empezar diciendo cual es. Si algo no esta claro no se adivina: `HeroDetectionError` lista lo visto y dice como forzarlo con --bot-hero / --human-hero."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .hero_catalog import load_catalog
from .heroes import load_hero
from .tts import lua
from .tts.hero_table import TTS_DIR, load_hero_table

MIN_CARDS = 5          # menos cartas de un heroe en un bando es una carta perdida, no su mazo
BOT, HUMAN = "bot", "human"


class HeroDetectionError(Exception):
    pass


@dataclass
class TableReading:
    piles: list[dict]                              # {type, guid, x, z, counts}; counts va en el orden de `slugs`
    pieces: dict[str, tuple[float, float]]         # miniaturas sueltas en la mesa por GUID
    slugs: list[str]


def hero_slugs() -> list[str]:
    return sorted(p.stem for p in TTS_DIR.glob("*.json"))


def read_table(client) -> TableReading:
    """Una lectura (`table_heroes`) con los rangos de CardID y las miniaturas de todos los heroes con datos de TTS."""
    slugs = hero_slugs()
    tables = [load_hero_table(s) for s in slugs]
    guids = sorted({g for t in tables for f in t.fighters.values() for g in f.pieces})
    res = client.call_lua(lua.table_heroes([t.card_ids for t in tables], guids, [t.identity for t in tables],
                                           MIN_CARDS)) or {}
    pieces = res.get("pieces") if isinstance(res.get("pieces"), dict) else {}
    piles = [_with_catalog(p, slugs) for p in res.get("piles") or []]
    return TableReading(piles, {g: (p["x"], p["z"]) for g, p in pieces.items()}, slugs)


def _with_catalog(pile: dict, playable: list[str]) -> dict:
    """A deck that is nobody's playable hero gets `catalog` (slug) when its images are a catalog hero's."""
    images = pile.get("pairs")
    if any(pile["counts"]) or not isinstance(images, list):
        return pile
    hero = load_catalog().identify(images)
    return {**pile, "catalog": hero.slug} if hero and hero.slug not in playable else pile


def _side(pile: dict, spots: dict[str, tuple[float, float]]) -> str:
    return min(spots, key=lambda s: math.hypot(pile["x"] - spots[s][0], pile["z"] - spots[s][1]))


def _name(slug: str) -> str:
    if slug in hero_slugs():
        return load_hero(slug).name
    return load_catalog().name_of(slug) or slug


def _playable_names(reading: TableReading) -> str:
    return ", ".join(_name(s) for s in reading.slugs)


def _unknown(reading: TableReading, spots: dict[str, tuple[float, float]], side: str | None = None) -> list[dict]:
    """Mazos de la mesa que no son de ningun heroe con datos (p. ej. Raphael), del lado `side` o de los dos."""
    return [p for p in reading.piles if not any(p["counts"]) and not p.get("catalog")
            and (side is None or _side(p, spots) == side)]


def _deck_name(pile: dict) -> str:
    return f"«{pile.get('name') or 'sin nombre'}» ({pile.get('size', '?')} cartas)"


def _report(reading: TableReading, totals: dict[str, dict[str, int]],
            spots: dict[str, tuple[float, float]] | None = None) -> str:
    lines = []
    for slug in [*reading.slugs, *sorted(set(totals) - set(reading.slugs))]:
        t = totals.get(slug)
        if t:
            todo = "" if slug in reading.slugs else " [no jugable todavia]"
            lines.append(f"  {_name(slug)} ({slug}){todo}: {t[BOT]} cartas en el lado del bot, "
                         f"{t[HUMAN]} en el del humano")
        else:
            mins = {g for f in load_hero_table(slug).fighters.values() for g in f.pieces} & set(reading.pieces)
            if mins:
                lines.append(f"  {_name(slug)} ({slug}): solo {len(mins)} miniatura(s) sueltas, ningun mazo")
    for pile in _unknown(reading, spots) if spots else []:
        side = "bot" if _side(pile, spots) == BOT else "humano"
        lines.append(f"  Mazo {_deck_name(pile)} en el lado del {side}: no es de ningun heroe que el bot conozca")
    return "\n".join(lines) or "  (ningun mazo de heroe suelto en la mesa)"


def detect_heroes(reading: TableReading, bot_spot, human_spot,
                  fixed: tuple[str | None, str | None] = (None, None)) -> tuple[str, str]:
    """(heroe del bot, heroe del humano). `fixed` son los ya decididos por opcion, configuracion o guardado."""
    spots = {BOT: tuple(bot_spot), HUMAN: tuple(human_spot)}
    totals: dict[str, dict[str, int]] = {}
    for pile in reading.piles:
        side = _side(pile, spots)
        owned = list(zip(reading.slugs, pile["counts"]))
        if pile.get("catalog"):
            owned.append((pile["catalog"], pile.get("size", 0)))
        for slug, n in owned:
            if n:
                totals.setdefault(slug, {BOT: 0, HUMAN: 0})[side] += int(n)
    how = ("Fuerzalo con --bot-hero <slug> y --human-hero <slug> (o bot_hero / human_hero en la configuracion). "
           f"Slugs: {', '.join(reading.slugs)}.")
    for slug, t in totals.items():
        if min(t.values()) >= MIN_CARDS:
            raise HeroDetectionError(f"{_name(slug)} tiene cartas en los dos lados de la mesa "
                                     f"({t[BOT]} y {t[HUMAN]}).\nLo visto:\n{_report(reading, totals, spots)}\n{how}")
    chosen = list(fixed)
    for i, side in enumerate((BOT, HUMAN)):
        if chosen[i]:
            continue
        other = chosen[1 - i]
        # candidato: al menos MIN_CARDS en este lado; un heroe con MIN_CARDS en los dos ya fallo arriba, y uno
        # con cartas sueltas en el lado contrario (< MIN_CARDS) o empatado por debajo del minimo no se reparte
        cands = {s: t[side] for s, t in totals.items() if s != other and t[side] >= MIN_CARDS}
        ranked = sorted(cands, key=cands.get, reverse=True)
        who = "bot" if side == BOT else "humano"
        if ranked and (len(ranked) == 1 or cands[ranked[0]] >= 2 * cands[ranked[1]]):
            if ranked[0] not in reading.slugs:
                raise HeroDetectionError(
                    f"El {who} juega {_name(ranked[0])}, que el bot todavia no sabe jugar. "
                    f"Heroes jugables: {_playable_names(reading)}.\nLo visto:\n{_report(reading, totals, spots)}\n{how}")
            chosen[i] = ranked[0]
            continue
        unknown = _unknown(reading, spots, side)
        if not ranked and unknown:
            raise HeroDetectionError(
                f"El mazo del {who} {', '.join(_deck_name(p) for p in unknown)} no es de ningun heroe que el bot sepa "
                f"jugar. Heroes con datos: {_playable_names(reading)}.\n"
                f"Lo visto:\n{_report(reading, totals, spots)}\n{how}")
        why = "no veo ningun mazo de heroe" if not ranked else f"hay {len(ranked)} heroes candidatos ({', '.join(ranked)})"
        raise HeroDetectionError(f"No puedo saber el heroe del {who}: {why} cerca de "
                                 f"su sitio de mazo {spots[side]}.\nLo visto:\n{_report(reading, totals, spots)}\n{how}")
    if chosen[0] == chosen[1]:
        raise HeroDetectionError(f"El mismo heroe en los dos bandos ({chosen[0]}).\n{how}")
    return chosen[0], chosen[1]
