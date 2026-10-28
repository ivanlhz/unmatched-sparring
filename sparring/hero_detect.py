"""Que heroe juega cada bando, leido de los mazos que hay sobre la mesa (solo lectura).

Un heroe esta "en la mesa" si hay un Deck o Card suelto con CardID de su rango (`data/tts/<slug>.json`, `deck.card_ids`);
lo de dentro de las bolsas no cuenta. Cada pila se asigna al bando de cuyo sitio de mazo esta mas cerca; el bando de un
heroe es aquel donde tiene mas cartas. Las miniaturas sueltas solo sirven para explicar el error. Si algo no esta
claro no se adivina: `HeroDetectionError` lista lo visto y dice como forzarlo con --bot-hero / --human-hero."""
from __future__ import annotations

import math
from dataclasses import dataclass

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
    res = client.call_lua(lua.table_heroes([t.card_ids for t in tables], guids)) or {}
    pieces = res.get("pieces") if isinstance(res.get("pieces"), dict) else {}
    return TableReading(list(res.get("piles") or []), {g: (p["x"], p["z"]) for g, p in pieces.items()}, slugs)


def _side(pile: dict, spots: dict[str, tuple[float, float]]) -> str:
    return min(spots, key=lambda s: math.hypot(pile["x"] - spots[s][0], pile["z"] - spots[s][1]))


def _name(slug: str) -> str:
    return load_hero(slug).name


def _report(reading: TableReading, totals: dict[str, dict[str, int]]) -> str:
    lines = []
    for slug in reading.slugs:
        t = totals.get(slug)
        if t:
            lines.append(f"  {_name(slug)} ({slug}): {t[BOT]} cartas en el lado del bot, {t[HUMAN]} en el del humano")
        else:
            mins = {g for f in load_hero_table(slug).fighters.values() for g in f.pieces} & set(reading.pieces)
            if mins:
                lines.append(f"  {_name(slug)} ({slug}): solo {len(mins)} miniatura(s) sueltas, ningun mazo")
    return "\n".join(lines) or "  (ningun mazo de heroe suelto en la mesa)"


def detect_heroes(reading: TableReading, bot_spot, human_spot,
                  fixed: tuple[str | None, str | None] = (None, None)) -> tuple[str, str]:
    """(heroe del bot, heroe del humano). `fixed` son los ya decididos por opcion, configuracion o guardado."""
    spots = {BOT: tuple(bot_spot), HUMAN: tuple(human_spot)}
    totals: dict[str, dict[str, int]] = {}
    for pile in reading.piles:
        side = _side(pile, spots)
        for slug, n in zip(reading.slugs, pile["counts"]):
            if n:
                totals.setdefault(slug, {BOT: 0, HUMAN: 0})[side] += int(n)
    how = ("Fuerzalo con --bot-hero <slug> y --human-hero <slug> (o bot_hero / human_hero en la configuracion). "
           f"Slugs: {', '.join(reading.slugs)}.")
    for slug, t in totals.items():
        if min(t.values()) >= MIN_CARDS:
            raise HeroDetectionError(f"{_name(slug)} tiene un mazo en cada lado de la mesa (el mismo heroe en los dos "
                                     f"bandos).\nLo visto:\n{_report(reading, totals)}\n{how}")
    side_of = {slug: BOT if t[BOT] > t[HUMAN] else HUMAN for slug, t in totals.items()}
    chosen = list(fixed)
    for i, side in enumerate((BOT, HUMAN)):
        if chosen[i]:
            continue
        other = chosen[1 - i]
        cands = [s for s, sd in side_of.items() if sd == side and s != other]
        if len(cands) != 1:
            why = "no veo ningun mazo de heroe" if not cands else f"hay {len(cands)} heroes candidatos ({', '.join(cands)})"
            raise HeroDetectionError(f"No puedo saber el heroe del {'bot' if side == BOT else 'humano'}: {why} cerca de "
                                     f"su sitio de mazo {spots[side]}.\nLo visto:\n{_report(reading, totals)}\n{how}")
        chosen[i] = cands[0]
    if chosen[0] == chosen[1]:
        raise HeroDetectionError(f"El mismo heroe en los dos bandos ({chosen[0]}).\n{how}")
    return chosen[0], chosen[1]
