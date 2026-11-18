"""Draw the disk image's window background: background.tiff (1x and 2x).

    uv run python app/packaging/dmg/make_background.py

The output is committed, like the app icon, so the release build needs no
Pillow. Rerun after changing the layout here or in settings.py; the icon
positions in both files must agree.

Finder writes the icon labels in black in light mode and white in dark mode,
over this picture, so it stays a mid blue where both read (roughly 4:1 or
better for each at the label line), never light or dark.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
# Taller than the content: Finder may add a tab bar and path bar (the user's
# preferences), which take height from the window, so everything that matters
# sits in the top 330 points and the rest is just more water.
WIDTH, HEIGHT = 660, 440
APP_AT, APPLICATIONS_AT = (165, 140), (495, 140)  # icon centres, as in settings.py
TOP, BOTTOM = (0x4F, 0x9C, 0xE6), (0x23, 0x5A, 0xA6)
FONT = "/System/Library/Fonts/SFNS.ttf"


def _draw(scale: int) -> Image.Image:
    w, h = WIDTH * scale, HEIGHT * scale
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        px.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))

    # Sonar rings spreading from behind the app, fading outwards.
    rings = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    cx, cy = APP_AT[0] * scale, APP_AT[1] * scale
    for i, r in enumerate((110, 170, 235, 305)):
        alpha = round(34 * (1 - i / 4))
        rr = r * scale
        rd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(255, 255, 255, alpha), width=3 * scale)
    img.paste(rings, (0, 0), rings)

    # The arrow from the app to Applications.
    arrow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arrow)
    y = APP_AT[1] * scale
    x0, x1 = (APP_AT[0] + 92) * scale, (APPLICATIONS_AT[0] - 92) * scale
    white = (255, 255, 255, 225)
    ad.line([(x0, y), (x1 - 6 * scale, y)], fill=white, width=6 * scale)
    head = 18 * scale
    ad.line([(x1 - head, y - head), (x1, y), (x1 - head, y + head)], fill=white, width=6 * scale, joint="curve")
    for end in ((x0, y), (x1 - head, y - head), (x1 - head, y + head)):
        r = 3 * scale
        ad.ellipse([end[0] - r, end[1] - r, end[0] + r, end[1] + r], fill=white)
    shadow = arrow.filter(ImageFilter.GaussianBlur(4 * scale))
    img.paste((0, 40, 90), (0, 0), shadow.getchannel("A").point(lambda a: a // 4))
    img.paste(arrow, (0, 0), arrow)

    # The caption, below the icon labels.
    font = ImageFont.truetype(FONT, 15 * scale)
    try:
        font.set_variation_by_name("Semibold")
    except (OSError, ValueError):
        pass  # not a variable font here; regular weight is fine
    text = "Drag ReefScanner to Applications"
    tw = px.textlength(text, font=font)
    px.text(((w - tw) / 2, 284 * scale), text, font=font, fill=(255, 255, 255))
    return img


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        one, two = Path(tmp) / "background.png", Path(tmp) / "background@2x.png"
        _draw(1).save(one)
        _draw(2).save(two)
        # One TIFF holding both, so Finder picks the sharp one on Retina.
        subprocess.run(
            ["tiffutil", "-cathidpicheck", str(one), str(two), "-out", str(HERE / "background.tiff")],
            check=True, capture_output=True,
        )
    print(f"Wrote {HERE / 'background.tiff'}")


if __name__ == "__main__":
    main()
