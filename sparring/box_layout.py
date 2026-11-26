"""Pandora's Box beside her deck, and the side of the table her pile of revealed Miseries lies on.

Iván (26/11/2026): the Misery deck goes to the LEFT of her own deck as seen from her seat, face down, and the Miseries she reveals lie face up in a
cascade (the human's below the Box, the bot's below its deck, from her player's point of view), so the effects of the turn are seen at a glance. This module is the part of that which is known before the
game is on the table: where the unpack lays the Box (`box_place`, from the deck spot, the discard zones, the hand zones and the slots of her
layout, all read from config/table.json) and which way her seat faces (`SeatGeo`: `down` is the way to her seat, `up_yaw` the yaw her cards
lie at upright for her). The pile itself is planned on the live table by `lua.BoxPile` (it reads the real hand zones)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .tts import lua

HAND_EDGE = 25.1                    # |x| from which the hand zones lie (config/table.json: hand_edge)
SEAT_X = {"Green": 1, "White": -1}  # the side of the table each seat is on, as the sign of x (config/table.json: seat_x)
DIAL_HALF, PIECE_HALF = 1.3, 1.0    # half the side of a life dial / a miniature as the layout lays them: what her pile must not cover
TABLE_LIMITS = (26.0, 36.0)         # |x|, |z| the Box may lie in (remove_table_limits)

Rect = tuple[float, float, float, float]       # (cx, cz, half x, half z)


@dataclass(frozen=True)
class SeatGeo:
    """One player's seat: `sign` is +1 when it is on the +x side of the table (cards read upright from there have their bottom edge toward +x)."""
    sign: int
    up_yaw: float
    keep: tuple[Rect, ...] = ()        # what her layout lays around her deck (character card, dial, pieces)

    @property
    def down(self) -> tuple[float, float]:
        return (float(self.sign), 0.0)

    @property
    def left(self) -> tuple[float, float]:
        """The unit step to the LEFT of her deck as she sees it from her seat (she looks toward the table's centre: White at -x looks +x, so her left is +z)."""
        return (0.0, -float(self.sign))


def _sign(raw: dict, side: str) -> int:
    seats = {**SEAT_X, **(raw.get("seat_x") or {})}
    value = seats.get(raw.get(f"{side}_seat"))
    return value if value in (1, -1) else (1 if side == "bot" else -1)


def _card_half(yaw: float) -> tuple[float, float]:
    """Half x and half z of a card lying at `yaw`."""
    c, s = abs(math.cos(math.radians(yaw))), abs(math.sin(math.radians(yaw)))
    return (lua.BOX_CARD_SHORT * c + lua.BOX_CARD_LONG * s) / 2, (lua.BOX_CARD_SHORT * s + lua.BOX_CARD_LONG * c) / 2


def _slot(spec) -> tuple[float, float, float] | None:
    """(x, z, yaw) of one layout slot, None if it is not one."""
    try:
        pos, rot = spec["pos"], spec.get("rot") or (0, 0, 0)
        return float(pos[0]), float(pos[2]), float(rot[1])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return None


def seat_geo(raw: dict, side: str, pieces: int = 0) -> SeatGeo:
    """The geometry of `side`'s seat. `pieces` is how many miniatures its hero lays on the layout's piece slots."""
    sign = _sign(raw, side)
    layout = (raw.get("layout") or {}).get(side) or {}
    deck = _slot(layout.get("deck") or {})
    up = deck[2] % 360 if deck is not None and deck[2] % 90 == 0 else (90.0 if sign > 0 else 270.0)
    keep: list[Rect] = []
    card = _slot(layout.get("character_card") or {})
    if card is not None:
        keep.append((card[0], card[1], *_card_half(card[2])))
    dial = _slot(layout.get("dial") or {})
    if dial is not None:
        keep.append((dial[0], dial[1], DIAL_HALF, DIAL_HALF))
    for spec in (layout.get("pieces") or [])[:pieces]:
        piece = _slot(spec)
        if piece is not None:
            keep.append((piece[0], piece[1], PIECE_HALF, PIECE_HALF))
    return SeatGeo(sign, up, tuple(keep))


def _discard_rect(raw: dict, side: str) -> Rect | None:
    """The discard zone of `side` as it lies on the table: the configured (cx, cz, size x, size z, rotY), the sizes swapped when turned 90 or 270."""
    b = raw.get(f"{side}_discard_bounds")
    if not isinstance(b, (list, tuple)) or len(b) < 5:
        return None
    cx, cz, sx, sz, rot = (float(v) for v in b[:5])
    if round(rot) % 180 == 90:
        sx, sz = sz, sx
    return cx, cz, sx / 2, sz / 2


def _overlap(a: Rect, b: Rect) -> float:
    dx = min(a[0] + a[2], b[0] + b[2]) - max(a[0] - a[2], b[0] - b[2]) - lua.BOX_OVERLAP_TOLERANCE
    dz = min(a[1] + a[3], b[1] + b[3]) - max(a[1] - a[3], b[1] - b[3]) - lua.BOX_OVERLAP_TOLERANCE
    return dx * dz if dx > 0 and dz > 0 else 0.0


def _crowd(rect: Rect, obstacles: list[Rect], limits: tuple[float, float]) -> float:
    off = (max(0.0, rect[0] + rect[2] - limits[0]) + max(0.0, -limits[0] - (rect[0] - rect[2]))
           + max(0.0, rect[1] + rect[3] - limits[1]) + max(0.0, -limits[1] - (rect[1] - rect[3])))
    return sum(_overlap(rect, o) for o in obstacles) + off * 10


def _away(deck: tuple[float, float], zone: Rect | None, fallback: float) -> tuple[float, float]:
    """The unit step along x or z that leads from the nearest point of `zone` to the deck (`fallback` x if the deck lies inside it)."""
    if zone is None:
        return (fallback, 0.0)
    nx = min(max(deck[0], zone[0] - zone[2]), zone[0] + zone[2])
    nz = min(max(deck[1], zone[1] - zone[3]), zone[1] + zone[3])
    vx, vz = deck[0] - nx, deck[1] - nz
    if abs(vx) < 1e-9 and abs(vz) < 1e-9:
        return (fallback, 0.0)
    return (math.copysign(1.0, vx), 0.0) if abs(vx) >= abs(vz) else (0.0, math.copysign(1.0, vz))


def box_place(raw: dict, side: str, geo: SeatGeo) -> tuple[float, float, float] | None:
    """(x, z, yaw) where the unpack lays `side`'s Misery deck, face down: to the LEFT of her own deck as she sees it from her seat (Ivan
    26/11/2026), in the yaw of her deck.

    Free means no hand zone, no discard zone, nothing of her layout and the table's edge in the way. If the left is not free it falls back to
    the other sides as before (first the side away from her discard zone, then the two others along the discard, then the discard's own) and
    takes the first free one; with none free, the least crowded. None when her deck spot is not known: the unpack then keeps its row."""
    deck = raw.get(f"{side}_deck_spot")
    if not deck:
        return None
    dx, dz = float(deck[0]), float(deck[1])
    discard = _discard_rect(raw, side)
    away = _away((dx, dz), discard, -float(geo.sign))
    outward = (0.0, math.copysign(1.0, dz)) if away[1] == 0 else (math.copysign(1.0, dx), 0.0)         # of the two sides across `away`, the one toward the table's edge first
    left = geo.left
    sides = [left, *(v for v in (away, outward, (-outward[0], -outward[1]), (-away[0], -away[1])) if v != left)]
    hx, hz = _card_half(geo.up_yaw)
    edge = float(raw.get("hand_edge", HAND_EDGE))
    obstacles: list[Rect] = [(edge + 40, 0.0, 40.0, 80.0), (-edge - 40, 0.0, 40.0, 80.0), *geo.keep]
    for other in ("bot", "human"):
        rect = _discard_rect(raw, other)
        if rect is not None:
            obstacles.append(rect)
    limits = tuple(float(v) for v in raw.get("remove_table_limits") or TABLE_LIMITS)
    best: tuple[float, tuple[float, float]] | None = None
    for ux, uz in sides:
        reach = abs(ux) * (hx + hx) + abs(uz) * (hz + hz) + lua.BOX_GAP
        at = (dx + ux * reach, dz + uz * reach)
        area = _crowd((at[0], at[1], hx, hz), obstacles, limits)       # type: ignore[arg-type]
        if best is None or area < best[0]:
            best = (area, at)
        if area == 0:
            break
    return best[1][0], best[1][1], geo.up_yaw
