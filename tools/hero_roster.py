"""Build `assets/heroes-roster.jpg`, the README picture of every hero deck in the catalog (card backs).

    .venv\\Scripts\\python tools\\hero_roster.py --cache C:\\path\\card-backs

Every hero of `data/catalog/heroes.json` is drawn with the back of its deck, with its name underneath, in the order of
`data/catalog/sets.json` (sets by release date, the heroes of each set together); a hero missing from it goes last,
alphabetically, with a warning. A hero the bot can play (it has `data/tts/<slug>.json`, matched to the catalog by the deck images) is
drawn as is; the others get a semi-transparent grey overlay. The backs are downloaded once into `--cache`
(outside the repo); the picture is the only file written in the repo.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "heroes-roster.jpg"
SETS = ROOT / "data" / "catalog" / "sets.json"

COLS = 13
CARD_W, CARD_H = 180, 251
GAP = 10
LABEL_H = 34
MARGIN = 16
BG = (24, 24, 28)
TEXT = (235, 235, 235)
TEXT_OFF = (105, 105, 105)
OVERLAY = (22, 22, 26, 205)


def release_order(catalog: list[dict]) -> list[dict]:
    """The catalog heroes in release order: sets by date, each set's heroes as listed."""
    by_name = {h["name"]: h for h in catalog}
    by_name.update({h["name"].split(",")[0]: h for h in catalog})    # "Dr. Jill Trent, Science Sleuth" as "Dr. Jill Trent"
    sets = sorted(json.loads(SETS.read_text(encoding="utf-8"))["sets"], key=lambda s: s["released"])
    ordered = []
    for s in sets:
        for name in s["heroes"]:
            if name not in by_name:
                raise SystemExit(f"{SETS.name}: {name!r} ({s['name']}) is not a catalog hero")
            if by_name[name] in ordered:
                raise SystemExit(f"{SETS.name}: {name!r} is listed twice")
            ordered.append(by_name[name])
    rest = sorted((h for h in catalog if h not in ordered), key=lambda h: h["name"].lower())
    for h in rest:
        print(f"warning: {h['name']} is in no set of {SETS.name}; drawn last", file=sys.stderr)
    return ordered + rest


def playable_slugs(catalog: list[dict]) -> set[str]:
    """Catalog slugs of the heroes that have table data, matched by a shared deck image."""
    faces: dict[str, str] = {}
    for hero in catalog:
        for pair in hero["identity"]:
            faces[pair["face"]] = hero["slug"]
    found = set()
    for path in (ROOT / "data" / "tts").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for pair in data.get("deck", {}).get("identity", []):
            if pair["face"] in faces:
                found.add(faces[pair["face"]])
                break
        else:
            print(f"warning: {path.stem} matches no catalog deck", file=sys.stderr)
    return found


def back_url(hero: dict, shared_backs: set[str]) -> str:
    """The hero's own back: the generic back of the shared sheets only when it has nothing else."""
    if not hero["identity"]:
        raise SystemExit(f"{hero['name']}: no deck images in the catalog")
    # a pair whose face is its own back is a single loose image, not the deck's back (Blackbeard has one)
    own = [p["back"] for p in hero["identity"] if p["back"] not in shared_backs and p["back"] != p["face"]]
    return (own or [hero["identity"][0]["back"]])[0]


def fetch(url: str, cache: Path, hero: str) -> Path:
    path = cache / (url.rstrip("/").split("/")[-1] + ".png")
    if not path.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
            Image.open(io.BytesIO(data)).verify()       # never cache an error page as a card back
        except Exception as exc:
            raise SystemExit(f"{hero}: cannot download its card back {url}: {exc}") from exc
        path.write_bytes(data)
    return path


def font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit_label(draw: ImageDraw.ImageDraw, text: str, width: int) -> tuple[str, ImageFont.ImageFont]:
    for size in (20, 18, 16, 14):
        f = font(size)
        if draw.textlength(text, font=f) <= width:
            return text, f
    f = font(14)
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text.rstrip(" ,") + "…", f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, required=True, help="folder for the downloaded card backs (outside the repo)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    cat = json.loads((ROOT / "data" / "catalog" / "heroes.json").read_text(encoding="utf-8"))
    heroes = release_order(cat["heroes"])
    shared_backs = {p["back"] for p in cat["shared_pairs"]}
    playable = playable_slugs(heroes)

    rows = -(-len(heroes) // COLS)
    width = MARGIN * 2 + COLS * CARD_W + (COLS - 1) * GAP
    height = MARGIN * 2 + rows * (CARD_H + LABEL_H) + (rows - 1) * GAP
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    for i, hero in enumerate(heroes):
        x = MARGIN + (i % COLS) * (CARD_W + GAP)
        y = MARGIN + (i // COLS) * (CARD_H + LABEL_H + GAP)
        card = Image.open(fetch(back_url(hero, shared_backs), args.cache, hero["name"])).convert("RGBA")
        card = card.resize((CARD_W, CARD_H), Image.LANCZOS)
        on = hero["slug"] in playable
        if not on:
            card = Image.alpha_composite(card, Image.new("RGBA", card.size, OVERLAY))
        sheet.paste(card.convert("RGB"), (x, y))
        name = hero["name"].split(",")[0]
        label, f = fit_label(draw, name, CARD_W)
        tw = draw.textlength(label, font=f)
        draw.text((x + (CARD_W - tw) / 2, y + CARD_H + 6), label, font=f, fill=TEXT if on else TEXT_OFF)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out, quality=85, optimize=True)
    print(f"{args.out}: {len(heroes)} heroes, {len(playable)} playable, {width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
