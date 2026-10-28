"""Genera `data/heroes/<slug>.json` (HeroDef) desde unmatched-memory + el overlay a mano.

    .venv\\Scripts\\python tools\\import_hero.py medusa hellboy
    .venv\\Scripts\\python tools\\import_hero.py --all          # todos los overlays de data/heroes/overlay
    .venv\\Scripts\\python tools\\import_hero.py --check --all  # falla si algun HeroDef generado difiere del versionado

unmatched-memory (`../unmatched-memory/data/heroes/<slug>.json`, o UNMATCHED_MEMORY) es solo lectura y aporta
vida, movimiento, alcance, ayudantes, habilidad y las cartas (titulo, tipo, valor, impulso, copias, textos).
El overlay `data/heroes/overlay/<slug>.json` aporta lo que unmatched-memory no tiene: el id de luchador (`fid`),
los ayudantes corregidos (nombre del sparring, fid, cantidad), la hoja de CardID (`deck.card_base` + `deck.sheet`:
idx, titulo, restriccion de luchador y etiquetas), y formas, contadores, disparadores y pasivas.
Sin hoja, el HeroDef lleva las cartas de unmatched-memory sin CardID ni restriccion y el motor no puede jugar con el."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sparring.cards import memory_dir  # noqa: E402
from sparring.heroes import HEROES_DIR, parse_hero  # noqa: E402

OVERLAY_DIR = HEROES_DIR / "overlay"
TEXT_PARTS = (("effect", ""), ("effectImmediately", "IMMEDIATELY: "), ("effectDuring", "DURING COMBAT: "),
              ("effectAfter", "AFTER COMBAT: "))


def card_text(src: dict) -> str:
    """Texto de una carta tal y como lo anuncia el bot: cada momento con su etiqueta, en una linea."""
    return " ".join(label + src[key].strip() for key, label in TEXT_PARTS if src.get(key))


def sidekick_groups(um: dict) -> list[dict]:
    """unmatched-memory repite un ayudante por miniatura: se agrupan los iguales (nombre y cifras) con su cantidad."""
    groups: list[dict] = []
    for s in um.get("sidekicks") or ():
        if not s.get("name"):
            continue                        # entrada vacia (Liz Sherman no tiene ayudantes)
        key = {"name": s["name"], "hp": int(s["startHealth"]), "move": int(s["move"]), "attack": s["attack"]}
        for g in groups:
            if all(g[k] == v for k, v in key.items()):
                g["count"] += 1
                break
        else:
            groups.append({**key, "count": 1})
    return groups


def build(slug: str, memory: Path, overlay_dir: Path = OVERLAY_DIR) -> dict:
    um = json.loads((memory / "data" / "heroes" / f"{slug}.json").read_text(encoding="utf-8"))
    ov = json.loads((overlay_dir / f"{slug}.json").read_text(encoding="utf-8"))
    groups = sidekick_groups(um)
    if "sidekicks" in ov:
        sidekicks = [{**(groups[i] if i < len(groups) else {}), **s} for i, s in enumerate(ov["sidekicks"])]
    else:
        sidekicks = groups
    for s in sidekicks:
        if "fid" not in s:
            raise SystemExit(f"{slug}: el ayudante {s.get('name')!r} necesita un fid en el overlay")
    by_title = {c["title"]: c for c in um["cards"]}
    deck_ov = ov.get("deck") or {}
    if "sheet" in deck_ov:
        cards = []
        for entry in deck_ov["sheet"]:
            src = by_title[entry["title"]]
            cards.append({"idx": entry["idx"], "title": entry["title"], "fighter": entry["fighter"], "type": src["type"],
                          "value": src["value"], "boost": src["boostValue"], "text": card_text(src),
                          "tags": list(entry.get("tags", ()))})
        for title, src in by_title.items():
            n = sum(1 for c in cards if c["title"] == title)
            if n != src["copies"]:
                raise SystemExit(f"{slug}: {title!r} aparece {n} veces en la hoja y unmatched-memory dice {src['copies']}")
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
    if ov.get("_notes"):
        out["_notes"] = ov["_notes"]
    parse_hero(out, f"{slug} (generado)")       # lo que no valida no se escribe
    return out


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/import_hero.py")
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true", help="todos los overlays de data/heroes/overlay")
    ap.add_argument("--check", action="store_true", help="no escribe: falla si el HeroDef versionado difiere")
    ap.add_argument("--memory", type=Path, default=None, help="carpeta unmatched-memory (por defecto se busca)")
    args = ap.parse_args(argv)
    slugs = sorted(p.stem for p in OVERLAY_DIR.glob("*.json")) if args.all else args.slugs
    if not slugs:
        ap.error("di algun slug o --all")
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
        print(f"{path}: escrito")
    if stale:
        print("HeroDef desactualizados (regenera con tools/import_hero.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
