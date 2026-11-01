"""Generates `data/heroes/<slug>.json` (HeroDef) from unmatched-memory + the hand-written overlay.

    .venv\\Scripts\\python tools\\import_hero.py medusa hellboy
    .venv\\Scripts\\python tools\\import_hero.py --all          # every overlay in data/heroes/overlay
    .venv\\Scripts\\python tools\\import_hero.py --check --all  # fails if any generated HeroDef differs from the versioned one

unmatched-memory (`../unmatched-memory/data/heroes/<slug>.json`, or UNMATCHED_MEMORY) is read only and provides
life, movement, reach, sidekicks, ability and the cards (title, type, value, boost, copies, texts).
The overlay `data/heroes/overlay/<slug>.json` provides what unmatched-memory lacks: the fighter id (`fid`),
the corrected sidekicks (sparring name, fid, count), the CardID sheet (`deck.card_base` + `deck.sheet`:
idx, title, fighter restriction, tags and, if the real card says something else, `text` and `memory_title`), and forms, counters,
triggers and passives.
With the DSL effects (`data/heroes/effects/<slug>.json`) and the cards it computes `ai_profile`: the static profile of each
fighter for the AI (sparring/ai_profile.py); the overlay can fix `ai_role: {fid: striker|keep_away}`.
Without a sheet, the HeroDef carries the unmatched-memory cards with no CardID or restriction and the engine cannot play with it."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sparring.ai_profile import compute_ai_profile  # noqa: E402
from sparring.cards import memory_dir  # noqa: E402
from sparring.heroes import HEROES_DIR, parse_hero  # noqa: E402

OVERLAY_DIR = HEROES_DIR / "overlay"
EFFECTS_DIR = HEROES_DIR / "effects"
TEXT_PARTS = (("effect", ""), ("effectImmediately", "IMMEDIATELY: "), ("effectDuring", "DURING COMBAT: "),
              ("effectAfter", "AFTER COMBAT: "))


def card_text(src: dict) -> str:
    """Text of a card as the bot announces it: each moment with its label, on one line."""
    return " ".join(label + src[key].strip() for key, label in TEXT_PARTS if src.get(key))


def sidekick_groups(um: dict) -> list[dict]:
    """unmatched-memory repeats a sidekick per miniature: identical ones (name and figures) are grouped with their count."""
    groups: list[dict] = []
    for s in um.get("sidekicks") or ():
        if not s.get("name"):
            continue                        # empty entry (Liz Sherman has no sidekicks)
        key = {"name": s["name"], "hp": int(s["startHealth"]), "move": int(s["move"]), "attack": s["attack"]}
        for g in groups:
            if all(g[k] == v for k, v in key.items()):
                g["count"] += 1
                break
        else:
            groups.append({**key, "count": 1})
    return groups


def build(slug: str, memory: Path, overlay_dir: Path = OVERLAY_DIR, effects_dir: Path = EFFECTS_DIR) -> dict:
    um = json.loads((memory / "data" / "heroes" / f"{slug}.json").read_text(encoding="utf-8"))
    ov = json.loads((overlay_dir / f"{slug}.json").read_text(encoding="utf-8"))
    groups = sidekick_groups(um)
    if "sidekicks" in ov:
        sidekicks = [{**(groups[i] if i < len(groups) else {}), **s} for i, s in enumerate(ov["sidekicks"])]
    else:
        sidekicks = groups
    for s in sidekicks:
        if "fid" not in s:
            raise SystemExit(f"{slug}: sidekick {s.get('name')!r} needs a fid in the overlay")
    by_title = {c["title"]: c for c in um["cards"]}
    deck_ov = ov.get("deck") or {}
    if "sheet" in deck_ov:
        cards = []
        for entry in deck_ov["sheet"]:
            src = by_title.get(entry.get("memory_title", entry["title"]))     # memory_title: unmatched-memory misspells it
            if src is None:
                raise SystemExit(f"{slug}: the overlay sheet cites {entry['title']!r} (idx {entry.get('idx')}), which does not "
                                 f"exist in unmatched-memory; known titles: {', '.join(sorted(by_title))}")
            cards.append({"idx": entry["idx"], "title": entry["title"], "fighter": entry["fighter"], "type": src["type"],
                          "value": src["value"], "boost": src["boostValue"],
                          "text": entry.get("text") or card_text(src),     # the real card wins over unmatched-memory
                          "tags": list(entry.get("tags", ()))})
        for title, src in by_title.items():
            n = sum(1 for e in deck_ov["sheet"] if e.get("memory_title", e["title"]) == title)
            if n != src["copies"]:
                raise SystemExit(f"{slug}: {title!r} appears {n} times in the sheet and unmatched-memory says {src['copies']}")
        deck = {"card_base": deck_ov["card_base"], "sheet": deck_ov.get("sheet_id"), "cards": cards}
    else:
        deck = {"card_base": None, "sheet": None,
                "cards": [{"title": c["title"], "fighter": None, "type": c["type"], "value": c["value"],
                           "boost": c["boostValue"], "copies": c["copies"], "text": card_text(c)} for c in um["cards"]]}
    out = {
        "_source": {"memory": f"unmatched-memory/data/heroes/{slug}.json",
                    "overlay": f"data/heroes/overlay/{slug}.json", "generator": "tools/import_hero.py"},
        "slug": slug, "name": um["name"], "fid": ov["fid"], "hp": int(um["hp"]), "move": int(um["move"]),
        "attack": um["attackType"], "set": (um.get("set") or {}).get("key"),
        "ability": ov.get("ability", (um.get("specialAbility") or "").strip()),
        "sidekicks": sidekicks, "forms": ov.get("forms"), "counters": ov.get("counters") or {},
        "triggers": ov.get("triggers") or [], "passives": ov.get("passives") or [], "deck": deck,
    }
    effects_path = effects_dir / f"{slug}.json"
    effects = json.loads(effects_path.read_text(encoding="utf-8")) if effects_path.exists() else None
    out["ai_profile"] = compute_ai_profile(out, effects, ov.get("ai_role"))
    if ov.get("_notes"):
        out["_notes"] = ov["_notes"]
    parse_hero(out, f"{slug} (generated)")       # what does not validate is not written
    return out


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/import_hero.py")
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true", help="every overlay in data/heroes/overlay")
    ap.add_argument("--check", action="store_true", help="does not write: fails if the versioned HeroDef differs")
    ap.add_argument("--memory", type=Path, default=None, help="unmatched-memory folder (searched for by default)")
    args = ap.parse_args(argv)
    slugs = sorted(p.stem for p in OVERLAY_DIR.glob("*.json")) if args.all else args.slugs
    if not slugs:
        ap.error("give some slug or --all")
    memory = args.memory or memory_dir()
    stale = []
    for slug in slugs:
        text = render(build(slug, memory))
        path = HEROES_DIR / f"{slug}.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(slug)
            continue
        path.write_text(text, encoding="utf-8")
        print(f"{path}: written")
    if stale:
        print("Outdated HeroDefs (regenerate with tools/import_hero.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
