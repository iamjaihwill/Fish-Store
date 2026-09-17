"""Generated stand-in photography.

The demo store needs images that look like reef photography without shipping
binary assets in the repository. These are procedural: a dark water gradient,
a bloom of colour where the colony sits, and polyp-like speckle on top.
"""

import hashlib
import math
import random
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFilter

PALETTES = {
    "acan": ((255, 96, 84), (255, 206, 92), (28, 12, 38)),
    "torch": ((86, 230, 190), (140, 255, 120), (6, 30, 40)),
    "acro": ((120, 180, 255), (180, 120, 255), (4, 18, 34)),
    "zoa": ((255, 120, 220), (110, 255, 200), (18, 6, 34)),
    "chalice": ((255, 140, 60), (120, 255, 190), (12, 20, 30)),
    "fish": ((255, 176, 59), (96, 200, 255), (5, 22, 36)),
    "invert": ((200, 160, 255), (90, 220, 210), (8, 16, 30)),
    "gear": ((150, 190, 210), (90, 130, 160), (10, 22, 32)),
    "scene": ((33, 230, 193), (157, 123, 255), (4, 20, 29)),
}


def _rng(seed):
    return random.Random(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16))


def generate_image(seed, palette="acan", size=(900, 900), style="colony"):
    """Return a ContentFile holding a JPEG stand-in image."""
    rng = _rng(seed)
    warm, cool, deep = PALETTES.get(palette, PALETTES["acan"])
    width, height = size

    base = Image.new("RGB", size, deep)
    draw = ImageDraw.Draw(base, "RGBA")

    # Water column gradient
    for y in range(height):
        ratio = y / height
        draw.line(
            [(0, y), (width, y)],
            fill=(
                int(deep[0] + 18 * ratio),
                int(deep[1] + 26 * ratio),
                int(deep[2] + 34 * ratio),
            ),
        )

    if style == "scene":
        # Wide banner: light shafts plus a silhouetted rock line.
        for i in range(9):
            x = rng.randint(-width // 4, width)
            draw.polygon(
                [(x, 0), (x + 70, 0), (x + 170, height), (x + 40, height)],
                fill=(cool[0], cool[1], cool[2], 16),
            )
        for i in range(7):
            cx = rng.randint(0, width)
            cy = height - rng.randint(0, height // 3)
            r = rng.randint(width // 8, width // 4)
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                fill=(warm[0] // 3, warm[1] // 3, warm[2] // 3, 180),
            )
    else:
        # Colony bloom: concentric polyp rings radiating from a centre.
        cx, cy = width // 2, int(height * 0.52)
        radius = int(min(width, height) * rng.uniform(0.28, 0.38))
        draw.ellipse(
            [cx - radius * 1.5, cy - radius * 1.5, cx + radius * 1.5, cy + radius * 1.5],
            fill=(warm[0], warm[1], warm[2], 40),
        )
        polyps = rng.randint(50, 110)
        for i in range(polyps):
            angle = rng.uniform(0, math.tau)
            dist = radius * math.sqrt(rng.random())
            px = cx + math.cos(angle) * dist
            py = cy + math.sin(angle) * dist * 0.86
            pr = rng.uniform(radius * 0.05, radius * 0.16)
            blend = dist / max(radius, 1)
            color = (
                int(warm[0] * (1 - blend) + cool[0] * blend),
                int(warm[1] * (1 - blend) + cool[1] * blend),
                int(warm[2] * (1 - blend) + cool[2] * blend),
                rng.randint(150, 235),
            )
            draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=color)
            draw.ellipse(
                [px - pr * 0.35, py - pr * 0.35, px + pr * 0.35, py + pr * 0.35],
                fill=(cool[0], cool[1], cool[2], 200),
            )

    # Suspended particles, then a soft-focus pass so it reads as a photograph.
    for _ in range(90):
        x, y = rng.randint(0, width), rng.randint(0, height)
        r = rng.uniform(0.6, 2.4)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 240, 255, rng.randint(20, 70)))

    base = base.filter(ImageFilter.GaussianBlur(radius=1.1))
    vignette = Image.new("L", size, 0)
    ImageDraw.Draw(vignette).ellipse(
        [-width * 0.2, -height * 0.2, width * 1.2, height * 1.2], fill=255
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=width // 8))
    base = Image.composite(base, Image.new("RGB", size, deep), vignette)

    buffer = BytesIO()
    base.save(buffer, format="JPEG", quality=82, optimize=True)
    return ContentFile(buffer.getvalue())
