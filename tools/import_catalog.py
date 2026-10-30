"""Generate `data/catalog/heroes.json`, the catalog of every hero deck in a TTS savegame (read-only).

    .venv\\Scripts\\python tools\\import_catalog.py "saves\\Unmatched Official Tournament Table October 2026 (Hellboy).json"
    .venv\\Scripts\\python tools\\import_catalog.py saves\\table.json --check     # write nothing; fail if the file would change

The catalog lets the hero detector RECOGNISE a deck by its image even when the bot cannot play that hero yet
(`sparring/hero_detect.py`). Only the five heroes with `data/tts/<slug>.json` are playable; the rest are just named.

A CardID does not identify a deck (almost every hero uses DeckID 176), so the identity of a hero is the set of
(FaceURL, BackURL) pairs of its cards, resolved like the bridge does (`imagesOf` in `sparring/tts/lua.py`: the card's own
CustomDeck, then the containing deck's). Pairs other than a deck's main sheet that several heroes' decks
use (the generic character-card sheet) identify nobody: they go to `shared_pairs` and are left out of each `identity`.
Two heroes with the same main sheet cannot be told apart: they are listed under `collisions`.

A hero is the nickname of a bag (minus colour tags like `[A32135]`) that holds a deck of 20-40 cards; its main deck is the
largest one in the bag (smaller decks in a bag are leftover cards and are ignored). Loose decks of that size outside bags
are read the same way under their own nickname. The save is never modified."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.import_save import is_bag, load_save, walk  # noqa: E402

CATALOG_PATH = ROOT / "data" / "catalog" / "heroes.json"
MIN_DECK, MAX_DECK = 20, 40          # a hero deck is ~30 cards; the 78-card pick/ban decks and 2-card decks are not heroes
DECK_NAMES = ("Deck", "DeckCustom")
MINIATURE_NAMES = ("Custom_Model", "Custom_Assetbundle", "Figurine")
COLOUR_TAG = re.compile(r"\[[0-9A-Fa-f]{6}\]|\[-\]")


def clean_name(nickname: str) -> str:
    return COLOUR_TAG.sub("", nickname or "").strip()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", " ")).strip("-")


def card_pairs(card: dict, fallback: dict | None) -> list[tuple[str, str]]:
    """(FaceURL, BackURL) of a card, as `imagesOf` does it: the entry of its own sheet (CardID // 100) in the card's
    CustomDeck, then in the deck's; with neither, every image the card carries."""
    cid = card.get("CardID")
    if not isinstance(cid, int):
        return []
    for custom in (card.get("CustomDeck"), fallback):
        info = custom.get(str(cid // 100)) if isinstance(custom, dict) else None
        if isinstance(info, dict):
            return [(info["FaceURL"], info["BackURL"])] if info.get("FaceURL") and info.get("BackURL") else []
    own = card.get("CustomDeck")
    infos = own.values() if isinstance(own, dict) else ()
    return [(i["FaceURL"], i["BackURL"]) for i in infos if isinstance(i, dict) and i.get("FaceURL") and i.get("BackURL")]


def is_hero_deck(obj: dict) -> bool:
    return obj.get("Name") in DECK_NAMES and MIN_DECK <= len(obj.get("ContainedObjects") or ()) <= MAX_DECK


def _decks_in(bag: dict) -> list[dict]:
    """Hero-sized decks inside a bag, at any depth, without looking inside decks."""
    found = []
    for child in bag.get("ContainedObjects") or ():
        if is_hero_deck(child):
            found.append(child)
        elif child.get("Name") not in DECK_NAMES:
            found += _decks_in(child)
    return found


def _miniatures(bag: dict) -> list[dict]:
    out = {(clean_name(o.get("Nickname", "")), o["GUID"]) for o in walk(bag)
           if o.get("Name") in MINIATURE_NAMES and o.get("GUID")}
    return [{"name": n, "guid": g} for n, g in sorted(out)]


def _read_deck(deck: dict) -> dict:
    cards = deck["ContainedObjects"]
    ids = [c["CardID"] for c in cards if isinstance(c.get("CardID"), int)]
    pairs = Counter(p for c in cards for p in card_pairs(c, deck.get("CustomDeck")))
    return {"deck_guid": deck.get("GUID", ""), "card_count": len(cards),
            "card_ids": [min(ids), max(ids)] if ids else [0, 0], "pairs": pairs}


def find_decks(objects: list[dict]) -> list[dict]:
    """One raw record per hero found: name, bag/deck GUIDs, miniatures and every pair of the main deck."""
    records = []

    def visit(obj: dict) -> None:
        name = clean_name(obj.get("Nickname", ""))
        if is_bag(obj):
            decks = _decks_in(obj)
            if decks and name:
                main = max(decks, key=lambda d: len(d["ContainedObjects"]))
                records.append({"name": name, "bag_guid": obj.get("GUID", ""), "miniatures": _miniatures(obj),
                                **_read_deck(main)})
                return
        elif is_hero_deck(obj):
            records.append({"name": name, "bag_guid": "", "miniatures": [], **_read_deck(obj)})
            return
        for child in obj.get("ContainedObjects") or ():
            visit(child)

    for obj in objects:
        visit(obj)
    return records


def _pair_rows(pairs) -> list[dict]:
    return [{"face": f, "back": b} for f, b in sorted(pairs)]


def _main_pair(record: dict) -> tuple[str, str]:
    """The sheet of the deck's playing cards: the pair most of its cards use (ties: the smallest)."""
    return min(record["pairs"], key=lambda p: (-record["pairs"][p], p))


def build_catalog(objects: list[dict], source: str) -> dict:
    """The catalog dict, sorted and deterministic. `unnamed` lists decks without a nickname; `collisions` lists groups
    of heroes whose identity is exactly the same (they cannot be told apart by image)."""
    records = find_decks(objects)
    named = [r for r in records if r["name"]]
    users = Counter(p for r in named for p in r["pairs"])
    shared = {p for r in named for p in r["pairs"] if users[p] > 1 and p != _main_pair(r)}
    heroes, slugs = [], Counter()
    for r in sorted(named, key=lambda r: (slugify(r["name"]), r["bag_guid"], r["deck_guid"])):
        slug = slugify(r["name"])
        slugs[slug] += 1
        if slugs[slug] > 1:
            slug = f"{slug}-{slugs[slug]}"
        heroes.append({"name": r["name"], "slug": slug, "card_count": r["card_count"], "card_ids": r["card_ids"],
                       "identity": _pair_rows(set(r["pairs"]) - shared), "bag_guid": r["bag_guid"],
                       "deck_guid": r["deck_guid"], "miniatures": r["miniatures"]})
    by_identity: dict[tuple, list[str]] = {}
    for h in heroes:
        by_identity.setdefault(tuple((p["face"], p["back"]) for p in h["identity"]), []).append(h["slug"])
    return {
        "_notes": "Generated by tools/import_catalog.py from the tournament save; do not edit by hand. identity = the "
                  "(face, back) image pairs that only this hero's deck uses; shared_pairs belong to several decks.",
        "source": source,
        "shared_pairs": _pair_rows(shared),
        "heroes": heroes,
        "unnamed": [{"bag_guid": r["bag_guid"], "deck_guid": r["deck_guid"], "card_count": r["card_count"]}
                    for r in sorted(records, key=lambda r: r["deck_guid"]) if not r["name"]],
        "collisions": sorted(sorted(g) for ident, g in by_identity.items() if ident and len(g) > 1),
    }


def render(catalog: dict) -> str:
    return json.dumps(catalog, indent=1, ensure_ascii=False) + "\n"


def summary(catalog: dict) -> list[str]:
    heroes = catalog["heroes"]
    lines = [f"{len(heroes)} heroes, {len(catalog['shared_pairs'])} shared image pair(s)"]
    odd = [h["slug"] for h in heroes if not h["identity"]]
    if odd:
        lines.append(f"  NO IDENTITY (every image is shared): {', '.join(odd)}")
    lines += [f"  COLLISION {', '.join(g)}" for g in catalog["collisions"]]
    lines += [f"  UNNAMED deck {u['deck_guid']} ({u['card_count']} cards)" for u in catalog["unnamed"]]
    short = [f"{h['slug']} ({h['card_count']})" for h in heroes if h["card_count"] not in (30, 31, 32)]
    if short:
        lines.append(f"  unusual card count: {', '.join(short)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/import_catalog.py")
    ap.add_argument("save", type=Path, help="TTS savegame (read-only)")
    ap.add_argument("--out", type=Path, default=CATALOG_PATH, help="catalog file to write")
    ap.add_argument("--check", action="store_true", help="write nothing: exit 1 if the file would change")
    args = ap.parse_args(argv)
    if not args.save.is_file():
        ap.error(f"{args.save} is not a file")
    if args.out.resolve() == args.save.resolve():
        ap.error("--out is the save itself; the save is read-only")
    text = render(build_catalog(load_save(args.save), args.save.name))
    print("\n".join(summary(json.loads(text))))
    if args.check:
        old = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        print("up to date" if old == text else f"{args.out} would change")
        return 0 if old == text else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
