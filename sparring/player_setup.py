"""The player sets the table: "Clean table" empties it and the player drags the map and the two heroes from the roster of the
official tournament table (infinite bags: dragging gives a COPY); "Prepare" reads what is there.

What dragging a hero gives is a copy of the hero's inner bag (a closed `Bag` holding the deck, miniatures and dials); the player
may also open it and spread its contents. Which hero a side plays is read from either: a closed bag by the GUIDs it holds, a loose
deck by its CardID range AND deck image (docs/card-identity.md). The halves of the table split at x = 0: the bot's is +x, the
player's is -x. A map is recognised by its board image (`board_detect`). Anything the bot cannot play (a hero without data, a
hero missing or twice, two heroes on a half, no map) comes back as chat lines and nothing is started.

`scan` reads the table (one message), `decide` turns the reading into a `Setup` or the problems; `clear_table` is the cleaning."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import hero_detect, map_setup, table_prep
from .board import MapEntry, catalog as board_catalog
from .board_detect import TABLE_PAD_IMAGES, BoardError, choose_board, image_key_of
from .heroes import load_hero
from .i18n import t
from .session import TOKEN_NICKNAMES
from .tts import lua
from .tts.hero_table import load_hero_table, variants_of

BOT, HUMAN = "bot", "human"
MIN_BAG_ITEMS = 3          # a loose bag with fewer objects is not a hero's


def side_of(x: float) -> str:
    """The half of the table an object lies on: the bot's is +x, the player's -x."""
    return BOT if x > 0 else HUMAN


@dataclass(frozen=True)
class Sighting:
    """A hero (or something that claims to be one) seen on a half of the table."""
    side: str
    kind: str                  # "bag" (closed copy of the hero's bag) or "deck"
    guid: str
    slug: str | None           # the hero, when the bot can play it
    name: str = ""             # what to call it when it cannot (catalog name or the object's own)
    items: int = 0
    variants: tuple[str, ...] = ()   # slug None and these set: the box of several heroes (Yennefer & Triss); who leads is still to be chosen


@dataclass
class Scan:
    boards: list = field(default_factory=list)
    sightings: list[Sighting] = field(default_factory=list)


@dataclass(frozen=True)
class Setup:
    bot: str
    human: str
    entry: MapEntry
    board_guid: str
    bags: dict[str, str]                       # hero slug -> GUID of the closed bag the player dropped (absent: opened)
    calibration: map_setup.MapSetup | None     # None: the map is not calibrated


def _bag_hero(guids: list[str], tables: dict) -> str | None:
    """The hero a closed bag holds: the one whose objects include every GUID in it (the save repeats some GUIDs between
    heroes, so a bag with only those is nobody's)."""
    held = set(guids)
    fits = [slug for slug, table in tables.items() if held <= {*table.all_guids(), *table.ignored_tokens}]
    if len(fits) > 1:
        fits = [slug for slug in fits if tables[slug].deck_guid in held]
    return fits[0] if len(fits) == 1 else None


def _bag_family(guids: list[str], tables: dict) -> tuple[str, ...]:
    """The variants of a box (Yennefer & Triss) when the bag holds pieces of more than one of them, so that no single variant fits it:
    every GUID in it is one of the box's and the variants' own pieces (the shared deck apart) are mixed. Empty otherwise."""
    held = set(guids)
    for slug in tables:
        family = variants_of(slug)
        if len(family) == 1 or slug != family[0]:
            continue
        objects = {g for s in family for g in tables[s].all_guids()}
        shared = set.intersection(*(set(tables[s].all_guids()) for s in family))
        touched = [s for s in family if held & (set(tables[s].all_guids()) - shared)]
        if held <= objects and len(touched) > 1:
            return family
    return ()


def _sightings(bags, reading: hero_detect.TableReading, tables: dict, ignore: set[str]) -> list[Sighting]:
    out = []
    for bag in bags if isinstance(bags, list) else []:
        guids = [g for g in bag.get("guids") or [] if isinstance(g, str)]
        if not guids or not isinstance(bag.get("x"), (int, float)):
            continue
        slug = _bag_hero(guids, tables)
        if slug is None and len(guids) < MIN_BAG_ITEMS:
            continue
        family = () if slug else _bag_family(guids, tables)
        out.append(Sighting(side_of(bag["x"]), "bag", bag["guid"], slug, bag.get("name") or "", len(guids), family))
    for pile in reading.piles:
        if pile.get("guid") in ignore:
            continue
        side = side_of(pile["x"])
        mine = [slug for slug, n in zip(reading.slugs, pile["counts"]) if n >= hero_detect.MIN_CARDS]
        if len(mine) > 1 and set(mine) == set(variants_of(mine[0])):          # one deck, several heroes: the box
            out.append(Sighting(side, "deck", pile["guid"], None, items=pile.get("size", 0), variants=variants_of(mine[0])))
        elif mine:
            out += [Sighting(side, "deck", pile["guid"], slug, items=pile.get("size", 0)) for slug in mine]
        elif pile.get("catalog"):
            out.append(Sighting(side, "deck", pile["guid"], None, hero_detect._name(pile["catalog"]), pile.get("size", 0)))
        elif not any(pile["counts"]):
            out.append(Sighting(side, "deck", pile["guid"], None, pile.get("name") or "", pile.get("size", 0)))
    return _settle_boxes(out, reading)


def _hero_piece(slug: str) -> set[str]:
    return set(load_hero_table(slug).fighters[load_hero(slug).fid].pieces)


def _settle_boxes(seen: list[Sighting], reading: hero_detect.TableReading) -> list[Sighting]:
    """On each half, what already says which heroine of a box leads is used before anything is asked: the hero miniature of one
    variant lying out on that half (as `hero_detect._by_hero_piece` does), else a bag or deck of the same half that fits only one
    variant. A bag of the box and its shared deck, both loose, are one box (like any hero's bag and its deck), not two."""
    out = list(seen)
    for side in (BOT, HUMAN):
        boxes = [s for s in out if s.side == side and s.variants]
        if not boxes:
            continue
        variants = boxes[0].variants
        lying = {g for g, (x, _) in reading.pieces.items() if side_of(x) == side}
        led = [v for v in variants if _hero_piece(v) & lying]
        known = {s.slug for s in out if s.side == side and s.slug in variants}
        pick = led[0] if len(led) == 1 else next(iter(known)) if len(known) == 1 else None
        if pick:
            out = [replace(s, slug=pick, variants=()) if s in boxes else s for s in out]
        elif len({s.kind for s in boxes}) == 2:
            deck = next(s for s in boxes if s.kind == "deck")
            out.remove(deck)
    return out


def scan(client, raw: dict, batch) -> Scan:
    """Reads the boards, the loose bags and the loose decks in ONE message (`batch` is `table_reset.batch`). The two decks
    of the official save's centre (`remove_table`) are the table's own and do not count."""
    got = batch(client, [("boards", lua.list_boards()), ("bags", lua.list_bags()), ("heroes", hero_detect.table_script())])
    tables = {slug: load_hero_table(slug) for slug in hero_detect.hero_slugs()}
    ignore = {guid for guid, _ in table_prep.removal_plan(raw)}
    reading = hero_detect.parse_table(got["heroes"])
    return Scan(got["boards"] if isinstance(got["boards"], list) else [], _sightings(got["bags"], reading, tables, ignore))


def _side_name(side: str) -> str:
    return t(f"setup.side.{side}")


def _family_names(variants: tuple[str, ...]) -> str:
    return t("common.and").join(load_hero(s).name for s in variants)


def question(found: Scan, human_hero: str | None = None) -> tuple[str, ...] | None:
    """The variants the player must choose between when their half holds a box of several heroes (Yennefer & Triss: the player
    picks which heroine leads) and nothing else, or None. The bot's half is never asked (`decide` picks), and a box on both
    halves is refused, not asked. A hero the configuration fixes for the player (`human_hero`) that belongs to the box answers it."""
    mine = [s for s in found.sightings if s.side == HUMAN]
    bots = [s for s in found.sightings if s.side == BOT]
    if len(mine) == 1 and mine[0].variants and human_hero not in mine[0].variants and not any(s.variants for s in bots):
        return mine[0].variants
    return None


def _resolve(seen: list[Sighting], picks: dict[str, str], bot_hero: str | None, human_hero: str | None) -> list[Sighting]:
    """The sightings with each box turned into the variant that leads: on the player's half the hero the configuration fixes
    for them if it is one of the box, else their answer; on the bot's the configured `bot_hero` (else the box's first variant).
    A box without a valid answer stays unresolved."""
    out = []
    for s in seen:
        if s.variants:
            wanted = ((human_hero if human_hero in s.variants else picks.get(s.side)) if s.side == HUMAN
                      else (bot_hero if bot_hero in s.variants else s.variants[0]))
            if wanted in s.variants:
                s = replace(s, slug=wanted, variants=())
        out.append(s)
    return out


def _hero_problems(seen: list[Sighting], console: bool = False) -> tuple[dict[str, str], list[str]]:
    """({side: slug} of the sides with exactly one playable hero, the problems of the others)."""
    problems, chosen = [], {}
    playable = ", ".join(load_hero(s).name for s in hero_detect.hero_slugs())
    for side in (BOT, HUMAN):
        here = [s for s in seen if s.side == side]
        for s in (s for s in here if s.slug is None and not s.variants):
            if s.kind == "bag" and not s.name:
                problems.append(t("setup.bag_unknown", side=_side_name(side), n=s.items, playable=playable))
            else:
                problems.append(t("setup.hero_unplayable", side=_side_name(side), name=s.name or t("setup.unknown_object"),
                                  playable=playable))
        boxes = [s for s in here if s.variants]
        if boxes:
            others = [s for s in here if s.variants != boxes[0].variants]
            if others:                             # a box and something else on one half: the same refusal as two heroes
                names = [_family_names(boxes[0].variants), *(load_hero(s.slug).name for s in others if s.slug)]
                problems.append(t("setup.two_on_side", side=_side_name(side), names=t("common.and").join(names)))
            elif len(boxes) > 1:
                problems.append(t("setup.duplicated", name=_family_names(boxes[0].variants), side=_side_name(side)))
            else:
                problems.append(t("setup.family_unchosen_console" if console else "setup.family_unchosen",
                                  names=_family_names(boxes[0].variants)))
            continue
        mine = [s for s in here if s.slug is not None]
        slugs = sorted({s.slug for s in mine})
        if len(slugs) > 1:
            problems.append(t("setup.two_on_side", side=_side_name(side),
                              names=t("common.and").join(load_hero(s).name for s in slugs)))
        elif slugs and (len({s.guid for s in mine if s.kind == "bag"}) > 1 or len({s.guid for s in mine if s.kind == "deck"}) > 1):
            problems.append(t("setup.duplicated", name=load_hero(slugs[0]).name, side=_side_name(side)))
        elif slugs:
            chosen[side] = slugs[0]
        elif len(here) == len(mine):
            problems.append(t("setup.no_hero", side=_side_name(side)))
    return chosen, problems


def decide(found: Scan, path=None, picks: dict[str, str] | None = None,
           bot_hero: str | None = None, human_hero: str | None = None, console: bool = False) -> tuple[Setup | None, list[str]]:
    """The `Setup` the table shows, or None and the lines that say what to fix. `picks` ({side: slug}) answers the question of
    `question`; `bot_hero` / `human_hero` are the heroes the configuration fixes, used only to choose among the variants of a
    box. `console`: nobody can answer on a panel (the calibration tool), so an unanswered box is worded for the command line."""
    problems = []
    entry = guid = None
    try:
        entry, guid = choose_board(found.boards, board_catalog())
    except BoardError as e:
        if all(image_key_of(b.get("image")) in TABLE_PAD_IMAGES for b in found.boards if isinstance(b, dict)):
            problems.append(t("setup.no_map"))
        else:
            problems.append(t("setup.map_unplayable", error=e))
    seen = _resolve(found.sightings, picks or {}, bot_hero, human_hero)
    boxes = {s.side: s.variants for s in found.sightings if s.variants}
    shared = [v for side, v in boxes.items() if len(boxes) == 2 or any(o.slug in v for o in found.sightings if o.side != side)]
    if shared:                      # the same box on both halves: one deck cannot be on two sides
        return None, [*problems, t("setup.same_family", names=_family_names(shared[0]))]
    chosen, hero_problems = _hero_problems(seen, console)
    problems += hero_problems
    if len(chosen) == 2 and chosen[BOT] == chosen[HUMAN]:
        problems.append(t("setup.same_hero", name=load_hero(chosen[BOT]).name))
    elif len(chosen) == 2 and chosen[HUMAN] in variants_of(chosen[BOT]):
        problems.append(t("setup.same_family", names=_family_names(variants_of(chosen[BOT]))))
    if problems:
        return None, problems
    bags = {s.slug: s.guid for s in seen if s.kind == "bag" and s.slug}
    return Setup(chosen[BOT], chosen[HUMAN], entry, guid, bags, map_setup.setup_for(entry.key, path)), []


def describe(setup: Setup) -> str:
    return t("setup.detected", bot=load_hero(setup.bot).name, human=load_hero(setup.human).name, map=setup.entry.name)


def not_calibrated(setup: Setup) -> str:
    return t("setup.not_calibrated", map=setup.entry.name, slug=setup.entry.key)


# ---------- the cleaning ----------
def _safe(name: str) -> bool:
    try:
        lua.lua_str(name)
    except ValueError:
        return False
    return True


def clear_script(raw: dict) -> str:
    """`lua.clear_setup` for every hero the bot can play and every map of the catalog."""
    tables = [load_hero_table(slug) for slug in hero_detect.hero_slugs()]
    names: set[str] = set()
    for table in tables:
        hero = load_hero(table.slug)
        names |= {" ".join(spec.name.lower().split()) for spec in hero.fighters()}
        names |= {f.nickname.lower() for f in table.fighters.values() if f.nickname}
        names |= {nick.lower() for name, nick in TOKEN_NICKNAMES.items() if name in table.tokens}   # the one split off a stack has a new GUID
    return lua.clear_setup([(table.card_ids, table.identity, table.character_card_id) for table in tables],
                           sorted({g for table in tables for g in table.all_guids()}),
                           sorted(n for n in names if _safe(n)), [e.image_key for e in board_catalog()],
                           table_prep.removal_limits(raw))


def cleared_summary(res) -> tuple[int, list[str]]:
    """(objects destroyed in all, GUIDs of the mixed piles left alone) out of the answer of `clear_setup`."""
    res = res if isinstance(res, dict) else {}
    total = sum(int(res.get(k) or 0) for k in ("cards", "boards", "bags", "objects") if isinstance(res.get(k), (int, float)))
    mixed = [g for g in res.get("mixed") or [] if isinstance(g, str)]
    return total, mixed
