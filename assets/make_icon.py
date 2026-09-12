# DLSS 5 Neural Lens: the icon. Copyright (C) 2026 Leaps-Bounds. GPL-3.0-or-later,
# see the LICENSE file at the repository root.
"""Draw the lens icon: a round lens with the app's green ring over a dark
field, a highlight, and a small pass indicator. Writes neural-lens.ico with
every size Windows asks for, and a 256 px PNG of the same drawing.

    python assets/make_icon.py
"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
BG, RING, RING_DARK, GLASS, HIGHLIGHT = (27, 36, 48), (74, 222, 128), (34, 120, 72), (11, 18, 32), (203, 213, 225)


def draw(size):
    s = size * 4                                        # draw large, shrink for smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = s * 0.06
    d.rounded_rectangle((pad, pad, s - pad, s - pad), radius=s * 0.22, fill=BG + (255,))
    cx = cy = s / 2
    r = s * 0.31
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GLASS + (255,), outline=RING + (255,), width=int(s * 0.055))
    # a soft inner ring to read as glass
    d.ellipse((cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82), outline=RING_DARK + (255,), width=int(s * 0.018))
    # the see through content: a few crisp strokes, the way text under the lens looks
    for i, w in enumerate((0.42, 0.30, 0.36)):
        y = cy - r * 0.3 + i * r * 0.3
        d.rounded_rectangle((cx - r * w, y - s * 0.02, cx + r * w * 0.6, y + s * 0.02), radius=s * 0.02,
                            fill=HIGHLIGHT + (255,))
    # highlight
    hl = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    hd.ellipse((cx - r * 0.55, cy - r * 0.85, cx - r * 0.1, cy - r * 0.45), fill=(255, 255, 255, 90))
    hl = hl.filter(ImageFilter.GaussianBlur(s * 0.02))
    im = Image.alpha_composite(im, hl)
    return im.resize((size, size), Image.LANCZOS)


sizes = [16, 24, 32, 48, 64, 128, 256]
frames = [draw(n) for n in sizes]
frames[-1].save(os.path.join(HERE, "neural-lens.ico"), format="ICO", sizes=[(n, n) for n in sizes],
                append_images=frames[:-1])
frames[-1].save(os.path.join(HERE, "neural-lens.png"))
print("wrote neural-lens.ico with", sizes, "and neural-lens.png")
