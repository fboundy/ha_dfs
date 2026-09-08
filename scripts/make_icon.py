#!/usr/bin/env python3
"""Render the integration icon for the Home Assistant brands repository.

Draws at high resolution and downsamples with LANCZOS so the edges stay clean at
the small sizes Home Assistant actually renders.

    python scripts/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

SUPERSAMPLE = 2048
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "assets"

GRADIENT_TOP = (32, 201, 178)
GRADIENT_BOTTOM = (13, 71, 133)
CORNER_RADIUS = 0.22

# Lightning bolt in normalised coordinates, y running downwards.
BOLT = [
    (0.585, 0.085),
    (0.265, 0.545),
    (0.455, 0.545),
    (0.400, 0.915),
    (0.735, 0.440),
    (0.545, 0.440),
]

# Broken ring around the bolt, signalling flexibility in both directions.
RING_RADIUS = 0.412
RING_WIDTH = 0.052
ARC_SPANS = [(28, 152), (208, 332)]
ARROW_LENGTH = 0.105


def _lerp(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * t) for a, b in zip(start, end))


def _gradient_tile(size: int) -> Image.Image:
    column = Image.new("RGB", (1, size))
    for y in range(size):
        column.putpixel((0, y), _lerp(GRADIENT_TOP, GRADIENT_BOTTOM, y / (size - 1)))
    gradient = column.resize((size, size), Image.Resampling.BILINEAR)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * CORNER_RADIUS), fill=255
    )

    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(gradient, (0, 0), mask)
    return tile


def _arrow_head(draw: ImageDraw.ImageDraw, size: int, angle_deg: float) -> None:
    """Draw a triangular head sitting on the ring, pointing along the arc."""
    centre = size / 2
    radius = RING_RADIUS * size
    half_width = RING_WIDTH * size * 1.7
    length = ARROW_LENGTH * size

    angle = math.radians(angle_deg)
    point = (centre + radius * math.cos(angle), centre + radius * math.sin(angle))

    # PIL arc angles increase clockwise with y down, so the forward tangent is (-sin, cos).
    tangent = (-math.sin(angle), math.cos(angle))
    radial = (math.cos(angle), math.sin(angle))

    tip = (point[0] + length * tangent[0], point[1] + length * tangent[1])
    base_a = (point[0] + half_width * radial[0], point[1] + half_width * radial[1])
    base_b = (point[0] - half_width * radial[0], point[1] - half_width * radial[1])

    draw.polygon([tip, base_a, base_b], fill=(255, 255, 255, 255))


def render(size: int = SUPERSAMPLE) -> Image.Image:
    image = _gradient_tile(size)
    draw = ImageDraw.Draw(image)

    centre = size / 2
    radius = RING_RADIUS * size
    box = [centre - radius, centre - radius, centre + radius, centre + radius]
    for start, end in ARC_SPANS:
        draw.arc(box, start=start, end=end, fill=(255, 255, 255, 235), width=int(RING_WIDTH * size))

    for _, end in ARC_SPANS:
        _arrow_head(draw, size, end)

    draw.polygon([(x * size, y * size) for x, y in BOLT], fill=(255, 255, 255, 255))
    return image


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    master = render()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        resized = master.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(OUTPUT_DIR / name, format="PNG", optimize=True)
        print(f"wrote {OUTPUT_DIR / name} ({size}x{size})")


if __name__ == "__main__":
    main()
