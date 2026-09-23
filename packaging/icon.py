"""The application icon, drawn rather than shipped as a binary.

Same three faders as the tray icon, on a rounded plate so it reads at Dock
size. Run it to (re)generate the platform icon files:

    python packaging/icon.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ACCENT = (223, 162, 68, 255)
PLATE = (24, 27, 31, 255)


def draw(size):
    """The icon at one size, as a square RGBA image."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s * 0.06
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=s * 0.22, fill=PLATE)
    # Three faders: two thirds of the plate, centred, caps at different heights.
    span = s * 0.52
    x0 = (s - span) / 2
    top, bottom = s * 0.28, s * 0.72
    width = max(2, int(s * 0.035))
    for i, frac in enumerate((0.45, 0.72, 0.30)):
        x = x0 + span * i / 2
        d.line([(x, top), (x, bottom)], fill=ACCENT, width=width)
        cap = bottom - (bottom - top) * frac
        half_w, half_h = s * 0.055, s * 0.028
        d.rounded_rectangle([x - half_w, cap - half_h, x + half_w, cap + half_h],
                            radius=s * 0.012, fill=ACCENT)
    return img


def write_icns(out):
    """macOS wants an .icns, which iconutil builds from an .iconset folder."""
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Kite.iconset"
        iconset.mkdir()
        for size in (16, 32, 64, 128, 256, 512, 1024):
            draw(size).save(iconset / f"icon_{size}x{size}.png")
            if size <= 512:                      # the @2x of the size below it
                draw(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)


def write_ico(out):
    """Windows takes every size in one .ico."""
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    draw(256).save(out, format="ICO", sizes=sizes)


if __name__ == "__main__":
    png = HERE / "icon.png"
    draw(1024).save(png)
    write_ico(HERE / "icon.ico")
    print(f"wrote {png.name}, icon.ico")
    if sys.platform == "darwin":
        write_icns(HERE / "icon.icns")
        print("wrote icon.icns")
