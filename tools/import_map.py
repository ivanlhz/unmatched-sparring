r"""Builds `data/maps/<key>.json` and `data/maps/catalog.json` for the maps of a TTS save, from each board's snap
points and image.

    .venv\Scripts\python tools\import_map.py --save <save.json> --images <dir> --out data\maps --check-dir docs\maps-check ^
        --expected ..\unmatched-memory\data\maps.json

The save is read only. For each `Custom_Board` inside a `Custom_Model_Infinite_Bag` it downloads the image into
`--images` (untrusted data: only decoded by OpenCV) and extracts:

* spaces: the board's snap points; the pixel of a snap is `W/2 - x*W/L, H/2 + z*H/L` (L = 16.75 units, the same for
  every map of the save: the image is stretched over a square board); a snap with no circle outline around it is not a
  space (battlefield-item spots);
* adjacency: the connectors (strokes of the map's ink outside the circles) thinned to a pixel graph; two circles are
  adjacent when the shortest path between them, without touching a third circle, is not much longer than the straight
  line; circles that nearly touch are judged by the stubs of ink leaving their rims;
* zones: the colours inside each circle (k-means), one palette per map, named after the nearest of COLOR_NAMES;
* starts: the numbered diamonds (1-4) on the rim of the circles, read by template matching (start_digits.json).

Maps that need tokens or doors (a "<map> Battlefield Items" bag beside the map, or a Doors bag next to its own bag) are
only listed in the catalog as excluded. Every other map is checked (spaces = the published count, symmetric and
connected, no space with a single neighbour, a zone on every space, the published zone
count, start markers 1 and 2); a map that fails is written with `"playable": false` and the reasons; every extracted map is written `"verified": false`
and is only played after a person confirms it in tools/map_checker.py. A verification
picture of every non-excluded map goes to `--check-dir`. Data files that already exist are kept (`--overwrite`)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

BOARD_UNITS = 16.75          # side of the square the board image is stretched over, in snap-point units
WORK_PX = 1600               # long side the image is scaled to before analysis
ICON_ORANGE = np.array([12, 102, 251])   # BGR of the orange icons printed on some connectors
PURE_BLACK = 30              # max(B, G, R) below this is black ink whatever the outlines' colour
INK_TOLERANCE = 32           # colour distance (BGR) from the map's ink that still counts as ink
DIGIT_MIN_IOU = 0.66         # how much a numeral must overlap a template to be read as that digit
NEAR_GAP = 0.7               # circles whose outlines are closer than this (in radii) are judged by their connector stubs
RING_MIN = 0.5               # share of the outline of a circle that must be dark for the snap to be a space
IMAGE_KEY = re.compile(r"[0-9A-Fa-f]{40}")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def image_key(url: str) -> str:
    """The identifier TTS-hosted images end with (the SHA-1 in the last path segment)."""
    last = url.rstrip("/").rsplit("/", 1)[-1]
    if not IMAGE_KEY.fullmatch(last):
        raise ValueError(f"no image key in {url!r}")
    return last.upper()


@dataclass
class SaveMap:
    name: str
    key: str
    url: str
    snaps: list[tuple[float, float]]


def read_save_maps(save: dict) -> list[SaveMap]:
    """Every Custom_Board that sits inside a Custom_Model_Infinite_Bag of the save (one per official map)."""
    out = []
    for obj in save["ObjectStates"]:
        if obj.get("Name") != "Custom_Model_Infinite_Bag":
            continue
        for inner in obj.get("ContainedObjects", []):
            if inner.get("Name") == "Custom_Board":
                snaps = [(s["Position"]["x"], s["Position"]["z"]) for s in inner.get("AttachedSnapPoints", [])]
                out.append(SaveMap(obj["Nickname"], slugify(obj["Nickname"]), inner["CustomImage"]["ImageURL"], snaps))
    return out


def load_work_image(path) -> np.ndarray:
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"{path}: not an image")
    h, w = img.shape[:2]
    s = WORK_PX / max(h, w)
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def snap_pixels(snaps: list[tuple[float, float]], shape: tuple[int, int]) -> np.ndarray:
    h, w = shape[:2]
    return np.array([(w / 2 - x * w / BOARD_UNITS, h / 2 + z * h / BOARD_UNITS) for x, z in snaps])


def ring_darkness(gray: np.ndarray, x: float, y: float, r: float, tolerance: int = 3) -> float:
    """Share of the points of the circle outline (radius r +- tolerance px) that are dark."""
    h, w = gray.shape
    ang = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    dark = np.zeros(len(ang), bool)
    for rr in (r - tolerance, r, r + tolerance):
        xs = np.clip((x + rr * np.cos(ang)).astype(int), 0, w - 1)
        ys = np.clip((y + rr * np.sin(ang)).astype(int), 0, h - 1)
        dark |= gray[ys, xs] < 70
    return float(dark.mean())


def refine_centers(img: np.ndarray, centers: np.ndarray, r: float) -> tuple[np.ndarray, np.ndarray]:
    """Moves each snap pixel (up to 8 px) to where the outline of a circle is darkest; returns the centres and, for
    each, the share of its outline that is ink (a snap with no circle around it, such as an item spot, scores low)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    refined, score = [], []
    for x, y in centers:
        coarse = max(((ring_darkness(gray, x + dx, y + dy, r), -abs(dx) - abs(dy), dx, dy)
                      for dx in range(-8, 9, 2) for dy in range(-8, 9, 2)))
        fine = max(((ring_darkness(gray, x + coarse[2] + dx, y + coarse[3] + dy, r, 1), -abs(dx) - abs(dy), dx, dy)
                    for dx in range(-2, 3) for dy in range(-2, 3)))
        refined.append((x + coarse[2] + fine[2], y + coarse[3] + fine[3]))
        score.append(coarse[0])
    return np.array(refined), np.array(score)


def circle_radius(img: np.ndarray) -> float:
    """Radius of the spaces: median of the Hough circles that have a dark outline (they are all the same size)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    long_side = max(img.shape[:2])
    found = cv2.HoughCircles(cv2.medianBlur(gray, 7), cv2.HOUGH_GRADIENT, dp=1.5, minDist=long_side * 0.03, param1=120,
                             param2=50, minRadius=int(long_side * .02), maxRadius=int(long_side * .06))
    if found is None:
        raise ValueError("no circles found in the image")
    good = [c for c in found[0] if ring_darkness(gray, *c) > 0.6]
    if not good:
        raise ValueError("no circle with a dark outline")
    return float(np.median([c[2] for c in good]))


def ink_pixels(img: np.ndarray, color: np.ndarray) -> np.ndarray:
    """Pixels drawn with the map's pen: the colour of the outlines, or plain black (some maps print the connectors
    blacker than the outlines)."""
    return (np.linalg.norm(img.astype(int) - color, axis=2) < INK_TOLERANCE) | (img.max(axis=2) < PURE_BLACK)


def ink(img: np.ndarray, centers: np.ndarray, r: float) -> tuple[np.ndarray, int]:
    """(colour, width) of this map's ink, read off the circles: the outlines and the connectors are the same pen.
    The colour is the median of the dark pixels on the outlines; the width is how thick the connectors are where
    they leave the circles."""
    h, w = img.shape[:2]
    ang = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    dark = []
    for x, y in centers:
        for rr in (r - 1, r, r + 1):
            px = img[np.clip((y + rr * np.sin(ang)).astype(int), 0, h - 1), np.clip((x + rr * np.cos(ang)).astype(int), 0, w - 1)]
            dark.append(px[px.max(axis=1) < 90])
    color = np.median(np.concatenate(dark), axis=0)
    near = ink_pixels(img, color)
    runs = []
    steps = 720
    th = np.linspace(0, 2 * np.pi, steps, endpoint=False)
    for x, y in centers:
        on = near[np.clip((y + (r + 9) * np.sin(th)).astype(int), 0, h - 1), np.clip((x + (r + 9) * np.cos(th)).astype(int), 0, w - 1)]
        bounds = np.flatnonzero(np.diff(np.r_[False, on, False].astype(int)))
        lengths = [(e1 - e0) * 2 * np.pi * (r + 9) / steps for e0, e1 in zip(bounds[::2], bounds[1::2])]
        lengths = [v for v in lengths if v >= 3]
        runs += [float(np.median(lengths))] if lengths else []
    return color, int(np.clip(np.median(runs), 3, 12)) if runs else 4


def line_mask(img: np.ndarray, color: np.ndarray, width: int) -> np.ndarray:
    """Pixels that can belong to a connector: the colour of the map's ink, and the orange icons that sit on some of
    them (they interrupt the line). Specks and anything much wider than the pen (walls, shadows) are dropped."""
    near = ink_pixels(img, color).astype(np.uint8)
    orange = np.linalg.norm(img.astype(int) - ICON_ORANGE, axis=2) < 45
    k = int(2.4 * width) | 1
    thick = cv2.dilate(cv2.morphologyEx(near, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))),
                       np.ones((5, 5), np.uint8))
    thin_k = max(3, int(0.55 * width)) | 1
    strokes = cv2.dilate(cv2.morphologyEx(near, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thin_k, thin_k))),
                         np.ones((3, 3), np.uint8))          # wood grain, window frames and other hairlines are thinner than the pen
    mask = (((near & strokes) | orange.astype(np.uint8)) & (1 - thick)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    small = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] < 60)
    return mask & (1 - np.isin(labels, small[small > 0]).astype(np.uint8))


def thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning of a 0/1 image: strokes become one-pixel-wide paths."""
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p2, p3, p4, p5 = img[:-2, 1:-1], img[:-2, 2:], img[1:-1, 2:], img[2:, 2:]
            p6, p7, p8, p9 = img[2:, 1:-1], img[2:, :-2], img[1:-1, :-2], img[:-2, :-2]
            c = img[1:-1, 1:-1]
            nb = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            trans = sum(((seq[k] == 0) & (seq[k + 1] == 1)).astype(np.uint8) for k in range(8))
            if step == 0:
                cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            kill = (c == 1) & (nb >= 2) & (nb <= 6) & (trans == 1) & cond
            if kill.any():
                img[1:-1, 1:-1][kill] = 0
                changed = True
        if not changed:
            return img[1:-1, 1:-1]


def find_adjacency(img: np.ndarray, centers: np.ndarray, r: float) -> set[tuple[int, int]]:
    """Edges between circles. The connectors (dark thin strokes outside the circles) are thinned to a pixel graph;
    each circle is a node joined to the graph pixels around its rim; two circles are adjacent when the shortest path
    between them, without going through a third circle, is not much longer than the straight line (that rejects
    hairpins at a Y junction and detours along walls). Circles that nearly touch are judged apart (`find_touching`)."""
    h, w = img.shape[:2]
    mask = line_mask(img, *ink(img, centers, r))
    disk = r + 5
    discs = np.zeros_like(mask)
    for x, y in centers:
        cv2.circle(discs, (round(x), round(y)), round(disk), 1, -1)
    skel = thin(mask & (1 - discs))
    ys, xs = np.nonzero(skel)
    n_pix, n_circ = len(xs), len(centers)
    index = -np.ones(skel.shape, int)
    index[ys, xs] = np.arange(n_pix)
    src, dst, wgt = [], [], []
    for dy, dx, cost in ((0, 1, 1.0), (1, 0, 1.0), (1, 1, 1.414), (1, -1, 1.414)):
        ok = (ys + dy < h) & (xs + dx >= 0) & (xs + dx < w)
        a = np.flatnonzero(ok)
        b = index[ys[a] + dy, xs[a] + dx]
        keep = b >= 0
        for u, v in zip(a[keep], b[keep]):
            src += [u, v]; dst += [v, u]; wgt += [cost, cost]
    attach = []
    owner = -np.ones(n_pix, int)                  # the circle whose rim a pixel is next to (a path ends there, never goes on)
    nearest = np.full(n_pix, np.inf)
    to_node_src, to_node_dst, to_node_w = [], [], []
    for i, (x, y) in enumerate(centers):
        d = np.hypot(xs - x, ys - y)
        near = np.flatnonzero(d < disk + 14)
        attach.append(near)
        closer = near[d[near] < nearest[near]]
        owner[closer], nearest[closer] = i, d[closer]
        to_node_src += list(near)
        to_node_dst += [n_pix + i] * len(near)
        to_node_w += [max(float(d[u]) - disk, 0.0) for u in near]
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra
    src, dst, wgt = np.array(src), np.array(dst), np.array(wgt)
    edges = set()
    for i in range(n_circ):
        walk = (owner[src] < 0) | (owner[src] == i)        # from a third circle's rim a path cannot carry on
        s2 = np.r_[src[walk], to_node_src, np.full(len(attach[i]), n_pix + i)]
        d2 = np.r_[dst[walk], to_node_dst, attach[i]]
        w2 = np.r_[wgt[walk], to_node_w, np.zeros(len(attach[i]))]
        graph = csr_matrix((w2 + 1e-9, (s2, d2)), shape=(n_pix + n_circ,) * 2)
        dist = dijkstra(graph, indices=n_pix + i, limit=9 * r)
        for j in range(i + 1, n_circ):
            chord = float(np.hypot(*(centers[i] - centers[j])))
            gap = chord - 2 * disk
            if dist[n_pix + j] <= 1.4 * max(gap, 0) + 30 and not _crosses_circle(centers, i, j, r):
                edges.add((i, j))
    return edges | find_touching(img, centers, r)


def stub_level(inked: np.ndarray, c: np.ndarray, toward: np.ndarray, r: float, spread: float) -> float:
    """How much ink leaves the rim of the circle at `c` in the direction of `toward` (within +-`spread` degrees):
    the best share of ink along a short ray just outside the outline."""
    h, w = inked.shape
    base = np.arctan2(*(toward - c)[::-1])
    radii = np.linspace(r + 5, r + 14, 10)
    best = 0.0
    for delta in np.radians(np.arange(-spread, spread + 1, 4)):
        xs = np.clip((c[0] + radii * np.cos(base + delta)).astype(int), 0, w - 1)
        ys = np.clip((c[1] + radii * np.sin(base + delta)).astype(int), 0, h - 1)
        best = max(best, float(inked[ys, xs].mean()))
    return best


def find_touching(img: np.ndarray, centers: np.ndarray, r: float) -> set[tuple[int, int]]:
    """Edges between circles that nearly touch (outlines closer than NEAR_GAP radii): both circles show a stub of
    ink leaving the rim towards the other one. Some maps chain their circles with tiny connectors and draw no long
    lines, so the path search has nothing to follow there."""
    inked = ink_pixels(img, ink(img, centers, r)[0])
    return {(i, j) for i in range(len(centers)) for j in range(i + 1, len(centers))
            if np.hypot(*(centers[i] - centers[j])) - 2 * r <= NEAR_GAP * r and not _crosses_circle(centers, i, j, r)
            and min(stub_level(inked, centers[i], centers[j], r, 8), stub_level(inked, centers[j], centers[i], r, 8)) >= 0.9}


def _crosses_circle(centers: np.ndarray, i: int, j: int, r: float) -> bool:
    """True when the straight line between circles i and j goes through another circle: a connector never does."""
    a, b = centers[i], centers[j]
    ab = b - a
    t = np.clip(((centers - a) @ ab) / (ab @ ab), 0, 1)
    d = np.hypot(*(centers - (a + t[:, None] * ab)).T)
    d[[i, j]] = np.inf
    return bool((d < 0.95 * r).any())


def find_start_markers(img: np.ndarray, centers: np.ndarray, r: float, color: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """The numbered diamonds on the rim of the circles: (circle index, 16x16 binary picture of the numeral).
    A diamond is a filled ink diamond sitting on a rim: it scores high where the ink inside a diamond-shaped window
    exceeds the ink in the band around it (a plain outline or connector does not)."""
    ink = ink_pixels(img, color).astype(np.float32)
    half = max(6, round(r * 0.165))
    size = 2 * (half + 6) + 1
    yy, xx = np.mgrid[-(half + 6):half + 7, -(half + 6):half + 7]
    manhattan = np.abs(yy) + np.abs(xx)
    inner = (manhattan <= half).astype(np.float32)
    band = ((manhattan > half + 1) & (manhattan <= half + 6)).astype(np.float32)
    score = cv2.filter2D(ink, -1, inner / inner.sum()) - cv2.filter2D(ink, -1, band / band.sum())
    peaks = (score == cv2.dilate(score, np.ones((half, half), np.uint8))) & (score > 0.38)
    found = []
    for y, x in zip(*np.nonzero(peaks)):
        d = np.hypot(centers[:, 0] - x, centers[:, 1] - y)
        i = int(d.argmin())
        if not r - 0.22 * r <= d[i] <= r + 0.22 * r:
            continue
        window = (manhattan <= half - 3)
        y0, x0 = y - half - 6, x - half - 6
        if y0 < 0 or x0 < 0 or y0 + size > img.shape[0] or x0 + size > img.shape[1]:
            continue
        numeral = (ink[y0:y0 + size, x0:x0 + size] < 0.5) & window
        n_parts, parts, part_stats, _ = cv2.connectedComponentsWithStats(numeral.astype(np.uint8), connectivity=8)
        numeral = np.isin(parts, [q for q in range(1, n_parts) if part_stats[q, cv2.CC_STAT_AREA] >= 4])
        ys, xs = np.nonzero(numeral)
        if len(xs) < 6:
            continue
        glyph = numeral[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
        found.append((i, cv2.resize(glyph, (16, 16), interpolation=cv2.INTER_AREA) > 100))
    return found


# ---------------------------------------------------------------- starts

DIGITS_FILE = Path(__file__).with_name("start_digits.json")


def load_digit_templates() -> dict[str, list[np.ndarray]]:
    """16x16 pictures of the numerals 1-4 as they are printed on the maps (read off confirmed markers)."""
    raw = json.loads(DIGITS_FILE.read_text(encoding="utf-8"))
    return {d: [np.array([[c == "1" for c in row] for row in rows]) for rows in variants] for d, variants in raw.items()}


def digit_scores(glyph: np.ndarray, templates: dict[str, list[np.ndarray]]) -> dict[str, float]:
    """Intersection over union of the glyph with the best template of each digit."""
    return {d: max(float((glyph & t).sum() / max((glyph | t).sum(), 1)) for t in variants) for d, variants in templates.items()}


def find_starts(img: np.ndarray, centers: np.ndarray, r: float, color: np.ndarray) -> dict[str, int]:
    """Start markers by number: {"1": space index, ...}. Each numeral is taken once, from the diamond that looks most
    like it, and only when it looks enough like it."""
    templates = load_digit_templates()
    best: dict[str, tuple[float, int]] = {}
    for i, glyph in find_start_markers(img, centers, r, color):
        scores = digit_scores(glyph, templates)
        digit = max(scores, key=scores.get)
        if scores[digit] >= DIGIT_MIN_IOU and scores[digit] > best.get(digit, (0.0, -1))[0]:
            best[digit] = (scores[digit], i)
    for a, b in [(a, b) for a in best for b in best if a < b and best[a][1] == best[b][1]]:      # one diamond, one number
        best.pop(a if best[a][0] < best[b][0] else b, None)
    return {d: i for d, (_, i) in sorted(best.items())}


# ---------------------------------------------------------------- zones

L_WEIGHT = 0.45              # lightness counts less than hue: the patterns on a zone are darker strokes of the same hue
MIN_SHARE = 0.08             # a colour covering less than this of a circle is a border or an icon, not a zone
COLOR_NAMES = {
    "red": (200, 70, 70), "brick": (150, 72, 62), "maroon": (110, 45, 62), "orange": (225, 130, 50),
    "peach": (240, 190, 160), "yellow": (240, 205, 80), "gold": (210, 165, 45), "cream": (250, 236, 214),
    "beige": (240, 207, 164), "sand": (222, 198, 150), "tan": (196, 160, 120), "brown": (135, 98, 70),
    "olive": (150, 158, 72), "lime": (176, 196, 84), "green": (96, 168, 100), "forest": (52, 100, 64),
    "mint": (168, 214, 184), "turquoise": (80, 180, 160), "teal": (48, 118, 126), "sky": (168, 204, 230),
    "blue": (84, 130, 188), "navy": (52, 62, 108), "lilac": (196, 180, 214), "purple": (128, 92, 160),
    "magenta": (168, 62, 130), "pink": (230, 150, 172), "gray": (150, 150, 156), "white": (236, 236, 238),
}


def weighted_lab(img: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 0] *= 100 / 255 * L_WEIGHT
    lab[..., 1:] -= 128
    return lab


def _lab_of_rgb(rgb: tuple[int, int, int]) -> np.ndarray:
    pixel = np.array([[[rgb[2], rgb[1], rgb[0]]]], np.uint8)
    return weighted_lab(pixel)[0, 0]


def _merge(entries: list[tuple[np.ndarray, float]], threshold: float) -> list[tuple[np.ndarray, float]]:
    """Greedy agglomeration of (colour, weight) entries: merge the closest pair while it is closer than `threshold`."""
    items = [(np.asarray(c, np.float32), w) for c, w in entries]
    while len(items) > 1:
        best = min(((float(np.linalg.norm(items[a][0] - items[b][0])), a, b)
                    for a in range(len(items)) for b in range(a + 1, len(items))))
        if best[0] >= threshold:
            break
        _, a, b = best
        (ca, wa), (cb, wb) = items[a], items[b]
        items[a] = ((ca * wa + cb * wb) / (wa + wb), wa + wb)
        del items[b]
    return items


def space_colors(lab: np.ndarray, img: np.ndarray, center: tuple[float, float], r: float,
                 ink: np.ndarray) -> list[tuple[np.ndarray, float]]:
    """The colours inside one circle with their share of its area: k-means (4 clusters) on the inner 80 %."""
    h, w = lab.shape[:2]
    x, y = center
    y0, y1, x0, x1 = max(int(y - r), 0), min(int(y + r) + 1, h), max(int(x - r), 0), min(int(x + r) + 1, w)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    inside = np.hypot(xx - x, yy - y) < 0.8 * r
    inside &= ~ink_pixels(img[y0:y1, x0:x1], ink)
    pixels = lab[y0:y1, x0:x1][inside][::2]
    if len(pixels) < 100:
        return []
    cv2.setRNGSeed(7)
    _, labels, centers_ = cv2.kmeans(pixels, 4, None, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 2,
                                     cv2.KMEANS_PP_CENTERS)
    shares = np.bincount(labels.ravel(), minlength=4) / len(labels)
    return list(zip(centers_, shares))


def settle(colors: list[tuple[np.ndarray, float]], threshold: float) -> list[tuple[np.ndarray, float]]:
    """Close colours of one circle are one zone (patterns are darker strokes of the same hue); borders and icons
    (small shares) are not zones."""
    merged = _merge(colors, threshold)
    return [(c, wt) for c, wt in merged if wt >= MIN_SHARE] or ([max(merged, key=lambda e: e[1])] if merged else [])


def build_palette(per_space: list[list[tuple[np.ndarray, float]]], threshold: float) -> tuple[list[np.ndarray], list[list[int]]]:
    """One palette for the whole map; each circle gets the indices of the palette colours it contains."""
    flat = [(c, wt) for colors in per_space for c, wt in colors]
    palette = [c for c, _ in _merge(flat, threshold)]
    members = [sorted({int(np.argmin([np.linalg.norm(c - p) for p in palette])) for c, _ in colors}) for colors in per_space]
    return palette, members


def name_palette(palette: list[np.ndarray]) -> list[str]:
    """A distinct colour name for each palette colour (the nearest names, each used once)."""
    from scipy.optimize import linear_sum_assignment
    names = list(COLOR_NAMES)
    refs = [_lab_of_rgb(COLOR_NAMES[n]) for n in names]
    cost = np.array([[np.linalg.norm(p - ref) for ref in refs] for p in palette])
    rows, cols = linear_sum_assignment(cost)
    return [names[c] for c in cols[np.argsort(rows)]]


def palette_rgb(palette: list[np.ndarray]) -> list[tuple[int, int, int]]:
    out = []
    for p in palette:
        lab = np.array([[[p[0] / (100 / 255 * L_WEIGHT), p[1] + 128, p[2] + 128]]], np.float32).clip(0, 255).astype(np.uint8)
        b, g, rr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)[0, 0]
        out.append((int(rr), int(g), int(b)))
    return out


# ---------------------------------------------------------------- one map

THRESHOLDS = (8, 10, 12, 14, 16, 18, 20, 23, 26)     # colour-merge distances tried when the published zone count is known


@dataclass
class Extracted:
    key: str
    name: str
    image_key: str
    img: np.ndarray
    snap_index: list[int]               # snap point behind each space (space id = position in this list)
    local: list[tuple[float, float]]
    centers: np.ndarray                 # pixel of each space in `img`
    edges: set[tuple[int, int]]
    zones: list[list[str]]
    palette: dict[str, tuple[int, int, int]]
    starts: dict[str, int]
    non_space_snaps: int
    problems: list[str] = field(default_factory=list)

    @property
    def playable(self) -> bool:
        return not self.problems


def extract_map(save_map: SaveMap, img: np.ndarray, expected: dict | None = None) -> Extracted:
    """Runs the whole extraction on one map and checks it. `expected` is the published {spacesCount, zonesCount}."""
    pixels = snap_pixels(save_map.snaps, img.shape)
    r = circle_radius(img)
    refined, ring = refine_centers(img, pixels, r)
    keep = [i for i in range(len(pixels)) if ring[i] >= RING_MIN]
    centers = refined[keep]
    color, _ = ink(img, centers, r)
    edges = find_adjacency(img, centers, r)
    starts = find_starts(img, centers, r, color)
    lab = weighted_lab(img)
    raw = [space_colors(lab, img, tuple(c), r, color) for c in centers]
    exp_zones = (expected or {}).get("zonesCount")
    best = None
    for thr in THRESHOLDS:
        palette, members = build_palette([settle(c, thr) for c in raw], thr)
        gap = abs(len(palette) - exp_zones) if exp_zones else abs(thr - 14)
        if best is None or gap < best[0]:
            best = (gap, palette, members)
    _, palette, members = best
    names = name_palette(palette)
    out = Extracted(save_map.key, save_map.name, image_key(save_map.url), img, keep,
                    [save_map.snaps[i] for i in keep], centers, edges,
                    [[names[k] for k in m] for m in members], dict(zip(names, palette_rgb(palette))), starts,
                    len(pixels) - len(keep))
    out.problems += check_map(out, expected)
    return out


def adjacency_lists(n: int, edges: set[tuple[int, int]]) -> list[list[int]]:
    adj: list[set[int]] = [set() for _ in range(n)]
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    return [sorted(s) for s in adj]


def check_map(m: Extracted, expected: dict | None) -> list[str]:
    """Why the extraction cannot be trusted (empty list: every check passed)."""
    problems = []
    n = len(m.centers)
    if expected and expected.get("spacesCount") not in (None, n):
        problems.append(f"{n} spaces found, the map has {expected['spacesCount']}")
    adj = adjacency_lists(n, m.edges)
    isolated = [i for i, a in enumerate(adj) if not a]
    if isolated:
        problems.append(f"spaces without a neighbour: {isolated}")
    dead_ends = [i for i, a in enumerate(adj) if len(a) == 1]
    if dead_ends:
        problems.append(f"spaces with a single neighbour, so a connector is probably missing: {dead_ends}")
    seen, queue = {0}, [0]
    while queue:
        for v in adj[queue.pop()]:
            if v not in seen:
                seen.add(v)
                queue.append(v)
    if len(seen) != n:
        problems.append(f"the board is not connected ({len(seen)} of {n} spaces reachable from space 0)")
    bare = [i for i, z in enumerate(m.zones) if not z]
    if bare:
        problems.append(f"spaces without a zone: {bare}")
    if expected and expected.get("zonesCount") not in (None, len(m.palette)):
        problems.append(f"{len(m.palette)} zone colours found, the map has {expected['zonesCount']}")
    for digit in ("1", "2"):
        if digit not in m.starts:
            problems.append(f"start marker {digit} not found")
    if len(set(m.starts.values())) != len(m.starts):
        problems.append("two start markers on the same space")
    return problems


def map_data(m: Extracted, source: str) -> dict:
    adj = adjacency_lists(len(m.centers), m.edges)
    data = {"key": m.key, "name": m.name, "source": source, "imageKey": m.image_key, "playable": m.playable,
            "verified": False}           # extracted from a picture: a person confirms it in tools/map_checker.py
    if m.problems:
        data["problems"] = m.problems
    data["starts"] = dict(sorted(m.starts.items()))
    data["spaces"] = [{"id": i, "local": [round(x, 3), round(z, 3)], "zones": sorted(m.zones[i]), "adj": adj[i]}
                      for i, (x, z) in enumerate(m.local)]
    return data


# ---------------------------------------------------------------- the save: exclusions, download

KEY_ALIASES = {"b-p-r-d-hq": "bprd-hq"}
EXPECTED_ALIASES = {"thrilla-in-manilla": "thrilla-in-manila"}
DOOR_RANGE = 5.0             # a Doors bag this close (table units) to a map bag belongs to that map
MAX_IMAGE_BYTES = 80_000_000


def exclusions(save: dict, maps: list[SaveMap]) -> dict[str, str]:
    """Maps that need tokens or doors, read off the save: an Infinite_Bag "<map> Battlefield Items" beside the map, or
    a Doors bag next to the map's own bag. Returns {key: "tokens" | "doors"}."""
    bags = {o["Nickname"]: o for o in save["ObjectStates"] if o.get("Name") == "Custom_Model_Infinite_Bag"}
    out: dict[str, str] = {}
    for obj in save["ObjectStates"]:
        nick = obj.get("Nickname", "")
        if obj.get("Name") == "Infinite_Bag" and nick.endswith(" Battlefield Items") and nick[:-18] in bags:
            out[slugify(nick[:-18])] = "tokens"
        elif obj.get("Name") == "Infinite_Bag" and nick == "Doors":
            here = obj["Transform"]
            near = [(((o["Transform"]["posX"] - here["posX"]) ** 2 + (o["Transform"]["posZ"] - here["posZ"]) ** 2) ** 0.5, n)
                    for n, o in bags.items() if any(m.name == n for m in maps)]
            dist, name = min(near)
            if dist <= DOOR_RANGE:
                out.setdefault(slugify(name), "doors")
    return {KEY_ALIASES.get(k, k): v for k, v in out.items()}


def fetch_image(url: str, dest: Path) -> Path:
    """Downloads a map image once. Only https, with a size cap; the file is untrusted and only ever decoded by OpenCV."""
    import urllib.request
    if dest.exists():
        return dest
    if not url.startswith("https://"):
        raise ValueError(f"not an https URL: {url!r}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"{url}: image too large")
    dest.write_bytes(data)
    return dest


# ---------------------------------------------------------------- verification picture

def render_check(m: Extracted, path: Path, width: int = 1280) -> None:
    """Writes the picture Iván eyeballs: the map with every space id, its zones, the adjacency edges and the starts."""
    from PIL import Image
    scale = width / m.img.shape[1]
    canvas = cv2.resize(m.img, (width, round(m.img.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    pts = (m.centers * scale).astype(int)
    for a, b in sorted(m.edges):
        cv2.line(canvas, tuple(pts[a]), tuple(pts[b]), (0, 255, 255), 3, cv2.LINE_AA)
    font = cv2.FONT_HERSHEY_SIMPLEX
    for i, (x, y) in enumerate(pts):
        cv2.circle(canvas, (x, y), 15, (0, 0, 0), -1, cv2.LINE_AA)
        cv2.putText(canvas, str(i), (x - 6 * len(str(i)) - 1, y + 6), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        for k, name in enumerate(sorted(m.zones[i])):
            cv2.putText(canvas, name[:9], (x - 28, y + 28 + 12 * k), font, 0.38, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, name[:9], (x - 28, y + 28 + 12 * k), font, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    for digit, space in m.starts.items():
        x, y = pts[space]
        cv2.rectangle(canvas, (x + 18, y - 26), (x + 50, y - 6), (0, 0, 200), -1)
        cv2.putText(canvas, f"S{digit}", (x + 21, y - 11), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    header = np.full((44, width, 3), 30, np.uint8)
    status = "CHECKS PASSED (unconfirmed)" if m.playable else "CHECKS FAILED: " + "; ".join(m.problems)
    cv2.putText(header, f"{m.name} - {len(m.centers)} spaces, {len(m.edges)} edges - {status}"[:150], (8, 28), font, 0.55,
                (80, 220, 80) if m.playable else (60, 60, 255), 1, cv2.LINE_AA)
    names = sorted({n for z in m.zones for n in z})
    legend = np.full((38, width, 3), 30, np.uint8)
    x = 8
    for n in names:
        rgb = m.palette.get(n)
        if rgb:
            cv2.rectangle(legend, (x, 8), (x + 22, 28), (rgb[2], rgb[1], rgb[0]), -1)
            x += 28
        cv2.putText(legend, n, (x, 25), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        x += 12 + 9 * len(n)
    stacked = np.vstack([header, canvas, legend])
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cv2.cvtColor(stacked, cv2.COLOR_BGR2RGB)).quantize(colors=256).save(path, optimize=True)


def extracted_from_data(data: dict, img: np.ndarray) -> Extracted:
    """An already verified data/maps file, as an Extracted, so its picture is drawn like the others."""
    spaces = data["spaces"]
    centers = snap_pixels([tuple(s["local"]) for s in spaces], img.shape)
    edges = {(min(s["id"], n), max(s["id"], n)) for s in spaces for n in s["adj"]}
    starts = {d: v for d, v in data["starts"].items()}
    return Extracted(data["key"], data["name"], data["imageKey"], img, list(range(len(spaces))),
                     [tuple(s["local"]) for s in spaces], centers, edges, [list(s["zones"]) for s in spaces], {}, starts, 0)


# ---------------------------------------------------------------- command line

def load_expected(path: Path | None) -> dict[str, dict]:
    """The published space and zone counts (unmatched-memory's maps.json), by map key; optional cross-check."""
    if path is None:
        return {}
    out = {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        key = EXPECTED_ALIASES.get(slugify(entry["name"]), slugify(entry["name"]))
        out[KEY_ALIASES.get(key, key)] = {"spacesCount": entry["spacesCount"], "zonesCount": entry["zonesCount"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--images", type=Path, required=True, help="empty or cache directory for the downloaded images")
    ap.add_argument("--out", type=Path, default=Path("data/maps"))
    ap.add_argument("--check-dir", type=Path, default=Path("docs/maps-check"))
    ap.add_argument("--expected", type=Path, help="unmatched-memory data/maps.json, for the published space/zone counts")
    ap.add_argument("--only", action="append", help="only this map key (repeatable)")
    ap.add_argument("--overwrite", action="store_true", help="also regenerate data files that already exist")
    args = ap.parse_args(argv)
    save = json.loads(args.save.read_text(encoding="utf-8"))
    maps = read_save_maps(save)
    for sm in maps:
        sm.key = KEY_ALIASES.get(sm.key, sm.key)
    excluded = exclusions(save, maps)
    expected = load_expected(args.expected)
    args.images.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    catalog = []
    for sm in sorted(maps, key=lambda m: m.name):
        entry = {"key": sm.key, "name": sm.name, "imageKey": image_key(sm.url)}
        if sm.key in excluded:
            catalog.append({**entry, "status": "excluded", "reason": excluded[sm.key]})
            print(f"{sm.key}: excluded ({excluded[sm.key]})")
            continue
        if args.only and sm.key not in args.only:
            continue
        img = load_work_image(fetch_image(sm.url, args.images / f"{entry['imageKey']}.img"))
        target = args.out / f"{sm.key}.json"
        if target.exists() and not args.overwrite:
            m = extracted_from_data(json.loads(target.read_text(encoding="utf-8")), img)
            entry["name"] = m.name
        else:
            m = extract_map(sm, img, expected.get(sm.key))
            data = map_data(m, f"{save.get('SaveName', 'save')}, Custom_Board of the {sm.name} bag")
            target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        render_check(m, args.check_dir / f"{sm.key}.png")
        verified = json.loads(target.read_text(encoding="utf-8")).get("verified") is True
        status = "supported" if m.playable and verified else "unverified" if m.playable else "unavailable"
        catalog.append({**entry, "status": status, **({"why": m.problems} if m.problems else {})})
        print(f"{sm.key}: {status} {len(m.centers)} spaces {len(m.edges)} edges starts {m.starts} {'; '.join(m.problems)}", flush=True)
    if not args.only:
        (args.out / "catalog.json").write_text(json.dumps(sorted(catalog, key=lambda e: e["key"]), indent=1,
                                                         ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
