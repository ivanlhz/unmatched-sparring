"""What the bridge needs from the real save for each hero: `data/tts/<slug>.json`.

The file carries the GUIDs of the hero's bag, its deck, the miniature (or token) and the life dial of each fighter,
the special tokens (Hellboy's ability, Abe's intuition) and the counter dials (destinies), plus the CardID range
and the image (FaceURL, BackURL) of its card sheet. Everything comes from the hero's bag in
`saves/Unmatched Official Tournament Table October 2026 (Hellboy).json` (read only); `tests/test_tts_data.py` checks it
against that save.

`config/table.json` only says WHICH heroes play and what the TABLE is like (seats, zones, spots); `table_defaults` takes from
these files what is specific to each hero and leaves it in the shape the configuration already expected (`pieces`, `dials`,
`nicknames`, deck GUIDs, CardID ranges, deck identities)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..board import DATA_DIR
from ..heroes import HeroDef, load_hero

TTS_DIR = DATA_DIR / "tts"


class HeroTableError(Exception):
    """A hero's TTS file is unusable (missing or does not agree with its HeroDef); the message says what."""


@dataclass(frozen=True)
class FighterTable:
    fid: str
    pieces: tuple[str, ...]        # GUID of the miniature; several if the GUID changes when the state changes
    dial: str | None               # life dial (None: 1 HP piece)
    dial_max: int | None
    nickname: str | None           # own name of the token (Abe's agents); otherwise the HeroDef's


@dataclass(frozen=True)
class HeroTable:
    slug: str
    bag: str                       # the hero's infinite bag
    inner_bag: str                 # inner bag: all the objects come out of it keeping their GUID
    deck_guid: str
    card_ids: tuple[int, int]
    character_card_id: int
    identity: tuple[tuple[str, str], ...]
    fighters: dict[str, FighterTable]
    tokens: dict[str, str] = field(default_factory=dict)          # special tokens by name
    counter_dials: dict[str, str] = field(default_factory=dict)   # dial of each of the hero's counters (destinies)
    token_faces: dict[str, dict] = field(default_factory=dict)    # Z rotation of each face of a two-faced token (verify live)
    token_sources: dict[str, dict] = field(default_factory=dict)  # how to get another copy of a token (verify live)
    token_slots: dict[str, dict] = field(default_factory=dict)     # own resting places of a token by side, ((x, y, z), (rx, ry, rz)) each, measured on the table: win over the layout's `tokens`

    def unpack_items(self) -> list[tuple[str, tuple[str, ...]]]:
        """(kind, GUID of each state) of everything that has to be taken out of the inner bag to play with the hero.
        A piece with several states (Hellboy) is on the table if ANY of its GUIDs answers."""
        items = [("deck", (self.deck_guid,))]
        for f in self.fighters.values():
            items.append(("piece", f.pieces))
            if f.dial:
                items.append(("dial", (f.dial,)))
        items += [("token", (g,)) for g in self.tokens.values()]
        items += [("dial", (g,)) for g in self.counter_dials.values()]
        return items

    def all_guids(self) -> list[str]:
        out = [self.deck_guid]
        for f in self.fighters.values():
            out += [*f.pieces, *([f.dial] if f.dial else [])]
        return out + [*self.tokens.values(), *self.counter_dials.values()]


def card_shift(table: HeroTable, deck_id: int) -> int:
    """How far the hero's CardIDs moved when TTS renumbered the DeckID of its deck from the data's to `deck_id`
    (0 if it did not). The image identity is the deck's real key; the DeckID is only where TTS put it."""
    return (deck_id - table.card_ids[0] // 100) * 100 if deck_id > 0 else 0


def shifted(ids: tuple[int, int], shift: int) -> tuple[int, int]:
    return ids[0] + shift, ids[1] + shift


def _guid_list(value, where: str) -> tuple[str, ...]:
    guids = (value,) if isinstance(value, str) else tuple(value)
    if not guids or not all(isinstance(g, str) and g for g in guids):
        raise HeroTableError(f"{where}: invalid GUID {value!r}")
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
                          dict(raw.get("tokens") or {}), dict(raw.get("counter_dials") or {}),
                          {k: dict(v) for k, v in (raw.get("token_faces") or {}).items()},
                          {k: dict(v) for k, v in (raw.get("token_sources") or {}).items()},
                          {k: {side: tuple((tuple(float(v) for v in s["pos"]), tuple(float(v) for v in s["rot"])) for s in rows)
                               for side, rows in v.items()}
                           for k, v in (raw.get("token_slots") or {}).items()})
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise HeroTableError(f"{where}: invalid TTS data ({e!r})") from None
    _validate(table, hero, where)
    return table


def _validate(t: HeroTable, hero: HeroDef, where: str) -> None:
    if t.slug != hero.slug:
        raise HeroTableError(f"{where}: the slug is {t.slug!r}, not {hero.slug!r}")
    specs = {f.fid: f for f in hero.fighters()}
    if set(t.fighters) != set(specs):
        raise HeroTableError(f"{where}: fighters {sorted(t.fighters)} differ from the HeroDef's {sorted(specs)}")
    for fid, f in t.fighters.items():
        if f.dial and f.dial_max != specs[fid].hp:
            raise HeroTableError(f"{where}: {fid}: the dial goes up to {f.dial_max} and the HeroDef says {specs[fid].hp} HP")
        if f.dial is None and specs[fid].hp > 1:
            raise HeroTableError(f"{where}: {fid}: has {specs[fid].hp} HP and there is no dial")
    if hero.card_base is not None and t.card_ids != (hero.card_base, hero.card_base + hero.deck_size - 1):
        raise HeroTableError(f"{where}: CardID range {t.card_ids} differs from the HeroDef's sheet")
    if not t.identity:
        raise HeroTableError(f"{where}: no deck identity (FaceURL, BackURL)")
    missing = sorted({"destiny"} & set(hero.counters) - set(t.counter_dials))
    if missing:
        raise HeroTableError(f"{where}: the dial of counter {', '.join(missing)} is missing")
    guids = t.all_guids()
    if len(set(guids)) != len(guids):
        raise HeroTableError(f"{where}: repeated GUIDs")


@lru_cache(maxsize=None)
def load_hero_table(slug: str, tts_dir: Path = TTS_DIR) -> HeroTable:
    hero = load_hero(slug)
    path = tts_dir / f"{slug}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise HeroTableError(f"no TTS data for {slug!r}: {path} is missing") from None
    except ValueError as e:
        raise HeroTableError(f"{path}: invalid JSON ({e})") from None
    return parse_hero_table(raw, hero, path.name)


def nicknames_for(hero: HeroDef, table: HeroTable) -> dict[str, str]:
    """Name of each fighter in messages and buttons: its token's if it has one; otherwise the HeroDef's with its
    number when there are several alike (Harpy 1, Harpy 2...)."""
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


def table_defaults(bot_slug: str, human_slug: str, shifts: tuple[int, int] = (0, 0)) -> dict:
    """What is specific to the two heroes, with the keys of `config/table.json` (which wins if it repeats them). `shifts`:
    CardID shift of each one's deck when TTS renumbered its DeckID (`card_shift`); the CardID ranges come out shifted."""
    if bot_slug == human_slug:
        raise HeroTableError(f"both sides play {bot_slug!r}: there are no pieces or deck for two")
    bot, human = load_hero(bot_slug), load_hero(human_slug)
    tb, th = load_hero_table(bot_slug), load_hero_table(human_slug)
    first, second = sorted((tb.card_ids, th.card_ids))
    # Overlapping CardID ranges are fine when the two decks have different images: Medusa and every TMNT turtle share
    # 17600-17629 (DeckID 176) and the table tells their cards apart by image identity (docs/card-identity.md). Only two
    # decks that overlap in range AND in image could not be told apart.
    if first[1] >= second[0] and set(tb.identity) & set(th.identity):
        raise HeroTableError(f"the CardID ranges of {bot_slug} and {human_slug} overlap")
    pieces, dials, nicknames = {}, {}, {}
    for hero, table in ((bot, tb), (human, th)):
        nicknames.update(nicknames_for(hero, table))
        for fid, f in table.fighters.items():
            pieces[fid] = f.pieces[0] if len(f.pieces) == 1 else list(f.pieces)
            if f.dial:
                dials[fid] = f.dial
    if len(set(nicknames.values())) != len(nicknames):
        raise HeroTableError("two fighters with the same name: " + ", ".join(sorted(nicknames.values())))
    out = {"nicknames": nicknames, "pieces": pieces, "dials": dials,
           "bot_deck_guid": tb.deck_guid, "human_deck_guid": th.deck_guid,
           "bot_card_ids": list(shifted(tb.card_ids, shifts[0])), "human_card_ids": list(shifted(th.card_ids, shifts[1])),
           "bot_identity": [list(p) for p in tb.identity], "human_identity": [list(p) for p in th.identity]}
    for hero, table in ((human, th), (bot, tb)):     # one Hellboy per game, on either side
        if hero.forms is not None and hero.forms.counter in table.counter_dials:
            out["destiny_dial"] = table.counter_dials[hero.forms.counter]
    return out
