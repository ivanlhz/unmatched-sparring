"""Which hero each side plays, read from the decks lying on the table (read only).

A hero is "on the table" if there is a loose Deck or Card with a CardID of its range (`data/tts/<slug>.json`,
`deck.card_ids`) AND the image of its deck (`deck.identity`): the CardID alone is not enough, in the tournament save
almost every deck (Raphael, Alice, Ciri...) uses Medusa's DeckID 176. What is inside the bags does not count. Each pile
is assigned to the side whose deck spot is closest; a hero's side is the one where it has the most cards (and at least
MIN_CARDS); among several candidates only one with >=2x the second wins. Loose miniatures only serve to explain the
error. Nothing is guessed: a deck that belongs to no playable hero is looked up by its images in the catalog
(`data/catalog/heroes.json`, `sparring/hero_catalog.py`); if it is a known but not playable hero it is counted like any
other and, if its side wins, the bot refuses to start and says which one it is. When it is unclear,
`HeroDetectionError` lists what was seen and says how to force it with --bot-hero / --human-hero.

The error texts are catalog tags (`hero.*`): the player reads them on the console."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import i18n
from .hero_catalog import load_catalog
from .heroes import load_hero
from .tts import lua
from .tts.hero_table import TTS_DIR, load_hero_table

MIN_CARDS = 5          # fewer cards of a hero on a side is a stray card, not its deck
BOT, HUMAN = "bot", "human"


class HeroDetectionError(Exception):
    pass


@dataclass
class TableReading:
    piles: list[dict]                              # {type, guid, x, z, counts}; counts follows the order of `slugs`
    pieces: dict[str, tuple[float, float]]         # loose miniatures on the table by GUID
    slugs: list[str]


def hero_slugs() -> list[str]:
    return sorted(p.stem for p in TTS_DIR.glob("*.json"))


def read_table(client) -> TableReading:
    """One read (`table_heroes`) with the CardID ranges and the miniatures of every hero that has TTS data."""
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
    """Decks on the table that belong to no hero with data (e.g. Raphael), on `side` or on both."""
    return [p for p in reading.piles if not any(p["counts"]) and not p.get("catalog")
            and (side is None or _side(p, spots) == side)]


def _deck_name(pile: dict) -> str:
    return i18n.t("hero.deck_name", name=pile.get("name") or i18n.t("hero.unnamed"), n=pile.get("size", "?"))


def _report(reading: TableReading, totals: dict[str, dict[str, int]],
            spots: dict[str, tuple[float, float]] | None = None) -> str:
    lines = []
    for slug in [*reading.slugs, *sorted(set(totals) - set(reading.slugs))]:
        counts = totals.get(slug)
        if counts:
            todo = "" if slug in reading.slugs else i18n.t("hero.report.not_playable")
            lines.append(i18n.t("hero.report.line", name=_name(slug), slug=slug, todo=todo, bot=counts[BOT],
                                human=counts[HUMAN]))
        else:
            mins = {g for f in load_hero_table(slug).fighters.values() for g in f.pieces} & set(reading.pieces)
            if mins:
                lines.append(i18n.t("hero.report.pieces_only", name=_name(slug), slug=slug, n=len(mins)))
    for pile in _unknown(reading, spots) if spots else []:
        lines.append(i18n.t("hero.report.unknown_deck", deck=_deck_name(pile),
                            who=i18n.t("hero.who.bot" if _side(pile, spots) == BOT else "hero.who.human")))
    return "\n".join(lines) or i18n.t("hero.report.none")


def detect_heroes(reading: TableReading, bot_spot, human_spot,
                  fixed: tuple[str | None, str | None] = (None, None)) -> tuple[str, str]:
    """(bot hero, human hero). `fixed` are the ones already decided by option, configuration or saved game."""
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
    how = i18n.t("hero.how", slugs=", ".join(reading.slugs))
    for slug, counts in totals.items():
        if min(counts.values()) >= MIN_CARDS:
            raise HeroDetectionError(i18n.t("hero.both_sides", name=_name(slug), bot=counts[BOT], human=counts[HUMAN],
                                            seen=_report(reading, totals, spots), how=how))
    chosen = list(fixed)
    for i, side in enumerate((BOT, HUMAN)):
        if chosen[i]:
            continue
        other = chosen[1 - i]
        # candidate: at least MIN_CARDS on this side; a hero with MIN_CARDS on both already failed above, and one with
        # stray cards on the opposite side (< MIN_CARDS) or tied below the minimum is not dealt out
        cands = {s: counts[side] for s, counts in totals.items() if s != other and counts[side] >= MIN_CARDS}
        ranked = sorted(cands, key=cands.get, reverse=True)
        who = i18n.t("hero.who.bot" if side == BOT else "hero.who.human")
        seen = _report(reading, totals, spots)
        if ranked and (len(ranked) == 1 or cands[ranked[0]] >= 2 * cands[ranked[1]]):
            if ranked[0] not in reading.slugs:
                raise HeroDetectionError(i18n.t("hero.unplayable", who=who, name=_name(ranked[0]),
                                                playable=_playable_names(reading), seen=seen, how=how))
            chosen[i] = ranked[0]
            continue
        unknown = _unknown(reading, spots, side)
        if not ranked and unknown:
            raise HeroDetectionError(i18n.t("hero.unknown_deck", who=who, decks=", ".join(_deck_name(p) for p in unknown),
                                            playable=_playable_names(reading), seen=seen, how=how))
        why = i18n.t("hero.why.none") if not ranked else i18n.t("hero.why.many", n=len(ranked), names=", ".join(ranked))
        raise HeroDetectionError(i18n.t("hero.cant_tell", who=who, why=why, spot=spots[side], seen=seen, how=how))
    if chosen[0] == chosen[1]:
        raise HeroDetectionError(i18n.t("hero.same", slug=chosen[0], how=how))
    return chosen[0], chosen[1]
