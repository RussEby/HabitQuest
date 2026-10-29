#!/usr/bin/env python3
"""Draw the Habit Quest app icon (512x512 PNG), with no image libraries.

The packager turns this PNG into the Windows icon for the executable, the
installer and the desktop shortcut. Run it again only if you want to change the
artwork:

    python scripts/make-icon.py

It is kept in the repo so the icon is reproducible instead of being an opaque
binary nobody can edit.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 512
OUT = Path(__file__).resolve().parent.parent / "desktop" / "build" / "icon.png"

BG_TOP = (28, 21, 54)
BG_BOTTOM = (10, 9, 20)
GOLD_LIGHT = (255, 232, 163)
GOLD_DARK = (186, 134, 38)
INK = (24, 18, 42)
RIM = (245, 196, 81)


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rounded_rect_distance(x, y, half, radius):
    """Signed distance from (x, y) to a rounded square centred on the origin."""
    dx = abs(x) - (half - radius)
    dy = abs(y) - (half - radius)
    ax, ay = max(dx, 0.0), max(dy, 0.0)
    outside = math.hypot(ax, ay)
    inside = min(max(dx, dy), 0.0)
    return outside + inside - radius


def _segment_distance(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length = vx * vx + vy * vy
    t = 0.0 if length == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def _coverage(distance):
    """Antialias a signed distance (in pixels) into 0..1 coverage."""
    return max(0.0, min(1.0, 0.5 - distance))


def build_pixels() -> bytearray:
    c = SIZE / 2.0
    body = SIZE * 0.461  # inset from the edge, leaves room for the rim
    radius = SIZE * 0.175
    disc = SIZE * 0.258
    stroke = SIZE * 0.058
    check = [
        (SIZE * 0.383, SIZE * 0.498),
        (SIZE * 0.462, SIZE * 0.579),
        (SIZE * 0.624, SIZE * 0.414),
    ]

    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)  # PNG filter type: none
        py = y + 0.5
        shade = py / SIZE
        base = _mix(BG_TOP, BG_BOTTOM, shade ** 0.9)
        for x in range(SIZE):
            px = x + 0.5

            body_d = _rounded_rect_distance(px - c, py - c, body, radius)
            alpha = _coverage(body_d)
            if alpha <= 0:
                raw.extend((0, 0, 0, 0))
                continue

            color = base

            # A thin gold rim just inside the silhouette.
            rim_d = abs(body_d + SIZE * 0.012) - SIZE * 0.0035
            rim = _coverage(rim_d) * 0.55
            if rim > 0:
                color = _mix(color, RIM, rim)

            # The badge: a gold disc with a little sheen toward the top.
            disc_d = math.hypot(px - c, py - c * 0.995) - disc
            if disc_d < 1:
                sheen = 1.0 - min(1.0, math.hypot(px - c * 0.82, py - c * 0.78) / (disc * 1.55))
                gold = _mix(GOLD_DARK, GOLD_LIGHT, 0.35 + 0.65 * sheen)
                color = _mix(color, gold, _coverage(disc_d))

            # A dark check mark, drawn as two round-capped strokes.
            if disc_d < 0:
                d = min(
                    _segment_distance(px, py, *check[0], *check[1]),
                    _segment_distance(px, py, *check[1], *check[2]),
                ) - stroke / 2.0
                ink = _coverage(d)
                if ink > 0:
                    color = _mix(color, INK, ink)

            raw.extend((*color, round(alpha * 255)))
    return raw


def write_png(path: Path, pixels: bytes) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
           + chunk(b"IDAT", zlib.compress(pixels, 9)) + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


if __name__ == "__main__":
    write_png(OUT, bytes(build_pixels()))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
