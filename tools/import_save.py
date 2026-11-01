"""Generate `data/tts/<slug>.json` from a Tabletop Simulator savegame (read-only).

    .venv\\Scripts\\python tools\\import_save.py saves\\table.json                 # every hero with a HeroDef
    .venv\\Scripts\\python tools\\import_save.py saves\\table.json --hero medusa   # only some heroes
    .venv\\Scripts\\python tools\\import_save.py saves\\table.json --check        # write nothing; fail if a file would change

The save is never modified. For each hero the tool finds its bag (an infinite bag named after the hero, or any bag
that holds a deck with the hero's CardID sheet), takes the inner bag out of it and reads everything the bridge needs
(`sparring/tts/hero_table.py`): bag and deck GUIDs, CardID range and character card, deck identity (FaceURL, BackURL),
one piece per fighter (several GUIDs when the miniature changes GUID with its state), health dials with their
MAX_VALUE, special tokens and counter dials.

What the save cannot tell is kept from the existing file: `_notes`, `token_faces` (rotations, verify-live notes) and
`token_sources`. Anything that could not be derived, or that differs from the versioned file, is reported; a hero
with any PROBLEM line is not written (exit 1) unless `--force` says so explicitly, and a derived field that failed is
left out rather than copied from the old file."""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sparring.heroes import DECK_SIZE, HeroDef, available_heroes, hero_path, load_hero  # noqa: E402
from sparring.tts.hero_table import TTS_DIR, HeroTableError, parse_hero_table  # noqa: E402

MAX_VALUE_RE = re.compile(r"MAX_VALUE\s*=\s*(\d+)")
KEPT_FIELDS = ("_notes", "token_faces", "token_sources")


class SaveImportError(Exception):
    """A hero could not be extracted from the save; the message says why."""


@dataclass
class Report:
    slug: str
    derived: list[str] = field(default_factory=list)     # fields read from the save
    kept: list[str] = field(default_factory=list)        # fields copied from the existing file
    changed: list[str] = field(default_factory=list)     # derived fields whose value differs from the existing file
    problems: list[str] = field(default_factory=list)    # what could not be derived or matched
    unused: list[str] = field(default_factory=list)      # objects of the inner bag nobody claimed

    def lines(self) -> list[str]:
        out = [f"{self.slug}: derived {', '.join(self.derived) or 'nothing'}"]
        if self.kept:
            out.append(f"  kept from existing file: {', '.join(self.kept)}")
        out += [f"  CHANGED {c}" for c in self.changed]
        out += [f"  PROBLEM {p}" for p in self.problems]
        if self.unused:
            out.append(f"  unused objects in the inner bag: {', '.join(self.unused)}")
        return out


# --- save walking -----------------------------------------------------------------------------------------------

def load_save(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["ObjectStates"]


def walk(obj: dict):
    """The object, then everything inside it: bag and deck contents and the other states of a multi-state object."""
    yield obj
    for child in obj.get("ContainedObjects") or ():
        yield from walk(child)
    for state in (obj.get("States") or {}).values():
        yield from walk(state)


def walk_all(objects: list[dict]):
    for obj in objects:
        yield from walk(obj)


def is_bag(obj: dict) -> bool:
    return "Bag" in obj.get("Name", "")


def is_deck(obj: dict) -> bool:
    return bool(obj.get("DeckIDs"))


def dial_max(obj: dict) -> int | None:
    m = MAX_VALUE_RE.search(obj.get("LuaScript") or "")
    return int(m.group(1)) if m else None


COLOR_TAG_RE = re.compile(r"\[[0-9A-Fa-f]{6}\]")       # TTS markup in a nickname: "[E77204]Michelangelo"
NAME_NOISE_RE = re.compile(r"[^a-z0-9]")


def _nick(obj: dict) -> str:
    return COLOR_TAG_RE.sub("", obj.get("Nickname") or "").strip()


def _plain(name: str) -> str:
    """A name as the save spells it or not: case, spaces and punctuation aside ("April O' Neil" is "April O'Neil")."""
    return NAME_NOISE_RE.sub("", name.casefold())


def _same(a: str, b: str) -> bool:
    return _plain(a) == _plain(b)


def deck_sheet(deck: dict) -> tuple[tuple[int, int], int] | None:
    """(CardID range of the 30 playing cards, character CardID) of a physical hero deck, or None if it is not one.
    The 30 cards share a sheet (CardID // 100); the character card is the single card from another sheet."""
    by_sheet: dict[int, list[int]] = {}
    for cid in deck["DeckIDs"]:
        by_sheet.setdefault(cid // 100, []).append(cid)
    main = [ids for ids in by_sheet.values() if len(ids) == DECK_SIZE]
    rest = [ids for ids in by_sheet.values() if len(ids) != DECK_SIZE]
    if len(main) != 1 or len(rest) != 1 or len(rest[0]) != 1:
        return None
    lo, hi = min(main[0]), max(main[0])
    if hi - lo != DECK_SIZE - 1:
        return None
    return (lo, hi), rest[0][0]


# --- locating the hero bag --------------------------------------------------------------------------------------

def parents(objects: list[dict]) -> dict[int, dict]:
    """id(object) -> the bag or deck that directly contains it (states hang from their first state)."""
    out: dict[int, dict] = {}
    for obj in walk_all(objects):
        for child in obj.get("ContainedObjects") or ():
            out[id(child)] = obj
        for state in (obj.get("States") or {}).values():
            out[id(state)] = obj
    return out


def find_hero_bag(objects: list[dict], hero: HeroDef) -> tuple[dict, dict]:
    """(outer bag, inner bag) of a hero: the outer bag is the one named after the hero (its inner bag is the only
    bag directly inside it) or, failing that, the bag around the bag that directly holds a deck with the hero's
    CardID sheet."""
    named = [o for o in walk_all(objects) if is_bag(o) and _same(_nick(o), hero.name)]
    if len(named) > 1:
        raise SaveImportError(f"{len(named)} bags named {hero.name!r}: " + ", ".join(o["GUID"] for o in named))
    if named:
        outer = named[0]
        inner_bags = [c for c in outer.get("ContainedObjects") or () if is_bag(c)]
        if len(inner_bags) != 1:
            raise SaveImportError(f"bag {outer['GUID']} ({_nick(outer)!r}) holds {len(inner_bags)} bags, expected "
                               f"exactly one inner bag")
        return outer, inner_bags[0]
    if hero.card_base is None:
        raise SaveImportError(f"no bag named {hero.name!r} (and the HeroDef has no CardID sheet to search by)")
    wanted = (hero.card_base, hero.card_base + DECK_SIZE - 1)
    decks = [d for d in walk_all(objects) if is_deck(d) and (deck_sheet(d) or (None,))[0] == wanted]
    if not decks:
        raise SaveImportError(f"no bag named {hero.name!r} and no deck of CardIDs {wanted[0]}..{wanted[1]}")
    if len(decks) > 1:
        raise SaveImportError(f"no bag named {hero.name!r} and {len(decks)} decks of CardIDs {wanted[0]}.."
                              f"{wanted[1]}: " + ", ".join(d["GUID"] for d in decks))
    up = parents(objects)
    inner = up.get(id(decks[0]))
    outer = up.get(id(inner)) if inner is not None else None
    if inner is None or outer is None or not is_bag(inner) or not is_bag(outer):
        raise SaveImportError(f"deck {decks[0]['GUID']} has the hero's CardIDs but is not inside two nested bags")
    return outer, inner


# --- extracting one hero ----------------------------------------------------------------------------------------

def _tts_tokens(raw_hero: dict) -> dict[str, str]:
    """fighter id -> nickname of its token when the overlay names each copy (Abe's agents: Victor, Carla, Kate)."""
    out = {}
    for s in raw_hero.get("sidekicks") or ():
        names = s.get("tts_tokens") or ()
        for i, name in enumerate(names, start=1):
            out[f"{s['fid']}{i}" if int(s["count"]) > 1 else s["fid"]] = name
    return out


def _dial_matches(nick: str, name: str) -> bool:
    a, b = _plain(nick), _plain(name)
    return bool(a) and (a == b or a.startswith(b) or b.startswith(a))


def extract_hero(objects: list[dict], hero: HeroDef, raw_hero: dict, report: Report,
                 expected_tokens: set[str] = frozenset()) -> dict:
    outer, inner = find_hero_bag(objects, hero)
    out: dict = {"slug": hero.slug, "bag": {"guid": outer["GUID"], "inner": inner["GUID"]}}
    report.derived.append("bag")
    contents = list(inner.get("ContainedObjects") or ())
    claimed: set[str] = set()

    decks = [(o, deck_sheet(o)) for o in contents if is_deck(o)]
    decks = [(o, s) for o, s in decks if s is not None]
    if hero.card_base is not None:
        decks = [(o, s) for o, s in decks if s[0][0] == hero.card_base] or decks
    if len(decks) != 1:
        report.problems.append(f"deck: {len(decks)} physical hero decks in the inner bag, expected one")
    else:
        deck, ((lo, hi), char_id) = decks[0]
        sheet = (deck.get("CustomDeck") or {}).get(str(lo // 100)) or {}
        out["deck"] = {"guid": deck["GUID"], "card_ids": [lo, hi], "character_card_id": char_id,
                       "identity": [{"face": sheet.get("FaceURL", ""), "back": sheet.get("BackURL", "")}]}
        claimed.add(deck["GUID"])
        report.derived.append("deck")
        if hero.card_base is not None and lo != hero.card_base:
            report.problems.append(f"deck {deck['GUID']}: CardIDs {lo}..{hi} but the HeroDef sheet starts at "
                                   f"{hero.card_base} (identity by image is phase G2)")
        if not sheet:
            report.problems.append(f"deck {deck['GUID']}: CustomDeck has no sheet {lo // 100} (identity empty)")

    dials = [o for o in contents if dial_max(o) is not None]
    counter_dials: dict[str, str] = {}
    for counter in hero.counters:
        hits = [d for d in dials if d["GUID"] not in claimed and counter.casefold() in _nick(d).casefold()]
        if len(hits) == 1:
            counter_dials[counter] = hits[0]["GUID"]
            claimed.add(hits[0]["GUID"])
        else:
            report.problems.append(f"counter {counter!r}: {len(hits)} dials named after it")

    token_names = _tts_tokens(raw_hero)
    pieces = [o for o in contents if dial_max(o) is None and not is_deck(o) and not is_bag(o)]
    fighters: dict[str, dict] = {}
    for spec in hero.fighters():
        wanted = token_names.get(spec.fid, spec.name)
        # a bag hands out its last object first: duplicates (harpies) are numbered in that order
        hits = [p for p in reversed(pieces) if p["GUID"] not in claimed and _same(_nick(p), wanted)]
        if not hits:
            report.problems.append(f"fighter {spec.fid!r}: no piece named {wanted!r}")
            continue
        piece = hits[0]
        guids = [piece["GUID"], *(s["GUID"] for s in (piece.get("States") or {}).values())]
        claimed.add(piece["GUID"])
        entry: dict = {"piece": guids[0] if len(guids) == 1 else guids}
        dial_hits = [d for d in dials if d["GUID"] not in claimed and _dial_matches(_nick(d), spec.name)]
        if len(dial_hits) > 1:
            dial_hits = [d for d in dial_hits if dial_max(d) == spec.hp] or dial_hits
        if dial_hits:
            entry["dial"] = dial_hits[0]["GUID"]
            entry["dial_max"] = dial_max(dial_hits[0])
            claimed.add(dial_hits[0]["GUID"])
            if len(dial_hits) > 1:
                report.problems.append(f"fighter {spec.fid!r}: several dials match, took {dial_hits[0]['GUID']}")
        elif spec.hp > 1:
            report.problems.append(f"fighter {spec.fid!r}: {spec.hp} HP and no dial named {spec.name!r}")
        if not _same(_nick(piece), spec.name):
            entry["nickname"] = _nick(piece)
        fighters[spec.fid] = entry
    out["fighters"] = fighters
    report.derived.append("fighters")

    tokens: dict[str, str] = {}
    token_children: dict[str, str] = {}
    for o in pieces:
        if o["GUID"] in claimed or not o.get("Name", "").startswith("Custom_Token"):
            continue
        key = _token_key(_nick(o))
        if key not in expected_tokens:
            report.problems.append(f"token {key!r} ({o['GUID']}, nickname {_nick(o)!r}): {hero.name} uses no such "
                                   f"token (expected: {', '.join(sorted(expected_tokens)) or 'none'})")
            continue
        if key in tokens:
            report.problems.append(f"token {key!r}: more than one object ({tokens[key]}, {o['GUID']})")
            continue
        tokens[key] = o["GUID"]
        claimed.add(o["GUID"])
        children = o.get("ChildObjects") or ()
        if len(children) == 1:
            token_children[key] = children[0]["GUID"]
    for key in sorted(expected_tokens - set(tokens)):
        report.problems.append(f"token {key!r}: {hero.name} uses it and the inner bag has no such token")
    out["tokens"] = tokens
    out["counter_dials"] = counter_dials
    report.derived += ["tokens", "counter_dials"]
    report.unused = [f"{o['GUID']} {o.get('Name')} {_nick(o)!r}".rstrip() for o in contents if o["GUID"] not in claimed]
    out["_token_children"] = token_children      # consumed by merge(); never written
    return out


def _token_key(nickname: str) -> str:
    """'Intuition Token' -> 'intuition'; a token without a nickname is the hero's special ability token."""
    words = [w for w in re.split(r"[^a-z0-9]+", nickname.casefold()) if w and w != "token"]
    return "_".join(words) or "ability"


def expected_token_keys(raw_hero: dict) -> set[str]:
    """Token names the hero's data actually uses: `token` of its triggers and passives (Abe: intuition) and the
    special ability token when the hero has forms (Hellboy flips it). Only the HeroDef counts, never the existing
    file: an old key would let a stray token of a new save through. The bridge looks tokens up by these keys
    (`effects_bridge.token_source`), so a stray token must not invent one."""
    keys = {t["token"] for t in [*(raw_hero.get("triggers") or ()), *(raw_hero.get("passives") or ())]
            if t.get("token")}
    if raw_hero.get("forms"):
        keys.add("ability")
    return keys


# --- merging with the versioned file ------------------------------------------------------------------------------

def merge(derived: dict, existing: dict | None, report: Report) -> dict:
    """The derived fields in the order of today's files, plus the hand-written blocks of the existing file.
    A derived field that could not be read from the save is left out, never copied from the existing file: old
    GUIDs next to new ones would be a silent lie."""
    token_children = derived.pop("_token_children", {})
    existing = existing or {}
    out: dict = {"slug": derived["slug"]}
    if existing.get("_notes"):
        out["_notes"] = existing["_notes"]
    for key in ("bag", "deck", "fighters", "tokens"):
        if key in derived:
            out[key] = derived[key]
    for key in ("token_faces", "token_sources"):
        if key in existing:
            out[key] = json.loads(json.dumps(existing[key]))
    for key, child in token_children.items():
        face = out.get("token_faces", {}).get(key)
        if face is not None and face.get("child") != child:
            report.changed.append(f"token_faces.{key}.child: {face.get('child')!r} -> {child!r}")
            face["child"] = child
    out["counter_dials"] = derived["counter_dials"]
    report.kept += [k for k in KEPT_FIELDS if k in out and k in existing]
    for key in ("bag", "deck", "fighters", "tokens", "counter_dials"):
        if key in existing and key in derived and existing[key] != derived[key]:
            report.changed.append(f"{key}: {json.dumps(existing[key])} -> {json.dumps(derived[key])}")
    return out


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def import_hero(objects: list[dict], slug: str, out_dir: Path) -> tuple[dict | None, Report]:
    """The merged file content for a hero (None when its bag is missing) and the report of how it was built.
    A report with problems means the content must not be written without an explicit override."""
    report = Report(slug)
    hero = load_hero(slug)
    raw_hero = json.loads(hero_path(slug).read_text(encoding="utf-8"))
    path = out_dir / f"{slug}.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    try:
        derived = extract_hero(objects, hero, raw_hero, report, expected_token_keys(raw_hero))
    except SaveImportError as e:
        report.problems.append(f"hero not found in the save: {e}")
        return None, report
    data = merge(derived, existing, report)
    try:
        parse_hero_table(data, hero, f"{slug} (generated)")
    except HeroTableError as e:
        report.problems.append(f"the generated file does not validate: {e}")
    return data, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/import_save.py")
    ap.add_argument("save", type=Path, help="TTS savegame (read-only)")
    ap.add_argument("--hero", action="append", default=None, metavar="SLUG",
                    help="only this hero (repeatable); default: every slug in data/heroes")
    ap.add_argument("--out", type=Path, default=TTS_DIR, help="where data/tts/<slug>.json go")
    ap.add_argument("--check", action="store_true", help="write nothing: fail and show a diff if a file would change")
    ap.add_argument("--force", action="store_true",
                    help="write a hero's file even if its report has PROBLEM lines (never with --check)")
    args = ap.parse_args(argv)
    if not args.save.is_file():
        ap.error(f"{args.save} is not a file")
    save, out = args.save.resolve(), args.out.resolve()
    if out == save or out == save.parent or out in save.parents:
        ap.error(f"--out {args.out} would write next to or over the save {args.save}; the save is read-only")
    if args.check and args.force:
        ap.error("--check writes nothing: --force makes no sense with it")
    objects = load_save(args.save)
    slugs = args.hero or available_heroes()
    failed, forced, stale = [], [], []
    for slug in slugs:
        data, report = import_hero(objects, slug, args.out)
        print("\n".join(report.lines()))
        if data is None or (report.problems and not args.force):
            failed.append(slug)
            continue
        if report.problems:
            forced.append(slug)
        path = args.out / f"{slug}.json"
        text = render(data)
        if args.check:
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            if old != text:
                stale.append(slug)
                sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), text.splitlines(True),
                                                           str(path), f"{path} (from {args.save.name})"))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"  written {path}")
    if failed:
        print("not imported (PROBLEM lines above; --force overrides): " + ", ".join(failed), file=sys.stderr)
    if forced:
        print("written despite PROBLEM lines (--force): " + ", ".join(forced), file=sys.stderr)
    if stale:
        print("files that would change (regenerate with tools/import_save.py): " + ", ".join(stale), file=sys.stderr)
    return 1 if failed or stale else 0


if __name__ == "__main__":
    sys.exit(main())
