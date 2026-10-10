"""The faces of the drawn looks' controls, and the two models that come with
faces, LookCheckbutton and LookScale.

A face is a Canvas that draws what Tk's options cannot draw. Slate's Off and
On segments, Folio's block switch, Industrial's ON and OFF plates, a slider's
track, ruler or trough, the quality step's carousel, ruler or ladder, the
corner's carousel or miniature screen, a tie's box, the segments, cards and
tiles of a choice. It reads its model, the real widget the lens's code made,
through the model's variable and state, and a click on it goes to the
model's own invoke() or set(), so the lens's code, its log lines and the
tests see what they always saw.

A cover is a face that is a child of its model, placed over the whole of it.
The model stays mapped and keeps its place in its row, Hints finds the
model's explanation from the cover, and Tk still calls a Scale's command at
idle as it does for a drag. Where a Scale with a cover should misbehave,
ROUTE "hidden" keeps the Scale made and never shown and puts its face in its
place, see LookScale.

What a face draws is worked out by the functions of this module's first
part from the look, the scale and a way of measuring words, with no Tk at
all, so the checks can read it, as a list of items, boxes, words, glyphs and
round marks, and of hits, the places a click acts on. The classes of the
second part draw them.

Imports tkinter and the package, and nothing of the lens.
"""
import math
import tkinter as tk

from lens_look import scale as sc
from lens_look import text, tokens, widgets

# How a slider's face sits on its Scale. inside, the face a cover of the
# Scale, as plan 1.7 has it, or hidden, the fallback stage 3's probe falls
# back to where the cover fails it, the Scale made and never shown with the
# face in its place
ROUTE = "inside"
ROUTES = ("inside", "hidden")

# ---- sizes, CSS pixels at 100 percent, from the drawings

# Segments in a well, Slate's switches, choices and pass counts, Folio's ink
# strip and Industrial's strip of capitals, by kind and by where they are. h
# a segment's height, least its least width, pad the space beside its words,
# size the words' size, well the well's padding round the segments or the
# strip's border, gap the space between two of them, and width a strip whose
# segments share a fixed width
SEGMENTS = {
    "console": {"settings": dict(h=30, least=52, pad=12, size=15, well=3, gap=2),
                "panel": dict(h=28, least=46, pad=10, size=14, well=3, gap=2),
                "small": dict(h=22, least=42, pad=9, size=13, well=3, gap=2),
                "choice": dict(h=28, least=0, pad=12, size=14, well=3, gap=2),
                "passes": dict(h=28, least=40, pad=10, size=14, well=3, gap=2)},
    "folio": {"settings": dict(h=30, least=0, pad=14, size=14, well=1, gap=1),
              "panel": dict(h=26, least=0, pad=12, size=13.5, well=1, gap=1)},
    "industrial": {"panel": dict(h=26, least=0, pad=8, size=11.5, well=1, gap=0, width=255)},
}
# Folio's block switch, w by h with a knob, its word gap beside it, and
# Industrial's ON and OFF plates, part wide each and h high
SWITCH = {
    "folio": dict(w=38, h=20, knob=13, inner=2, border=1.5, gap=10, size=14.5),
    "industrial": {"settings": dict(part=52, h=30, size=12), "panel": dict(part=50, h=28, size=12),
                   "small": dict(part=50, h=26, size=12)},
}
# Slate's carousel, w by h with arrows arrow wide, pips pip wide, and the
# name's size
CAROUSEL = {"settings": dict(w=200, h=36, arrow=34, pip=12, size=15),
            "panel": dict(w=184, h=36, arrow=30, pip=10, size=15),
            "profile": dict(w=184, h=34, arrow=30, pip=0, size=15)}
# Sliders. Slate's track and round thumb with its ring, Folio's ruler and
# Industrial's trough with its plate of a thumb
SLIDER = {
    "console": dict(w=172, h=20, track=6, thumb=16, ring=3),
    "folio": dict(w=210, row=20, line=2, marker=(6, 18), tick_gap=1, ticks=6, border=1.5),
    "industrial": dict(w=255, h=28, trough=(9, 8), ticks=(20, 5, 8), thumb=(10, 18, 4)),
}
# where a slider's ticks stand, as parts of its range, the long one at 1.00
MARKS = (0.0, 0.25, 0.5, 0.75, 1.0)
# Industrial's ladder of blocks, the ring round the chosen one as (its gap,
# its line), the gap down to the end words and their size, and Folio's end
# words' size
LADDER = dict(block=(34, 16), gap=5, ring=(2, 1), words_gap=5, size=12)
RULER_WORDS = 11.5
# Folio's and Industrial's miniature screen of the corner
CORNER = {"folio": dict(screen=(72, 44), border=1.5, pad=5, chosen=(20, 5), other=(14, 5), gap=14, size=14.5),
          "industrial": dict(screen=(92, 54), border=1, pad=5, block=(30, 10), gap=16, size=12)}
# A tie's box, its border and its check mark
TIE = {"console": dict(box=20, border=1, check=12), "folio": dict(box=16, border=1.5, check=10),
       "industrial": dict(box=22, border=1, check=12)}
# Slate's cards, Folio's stacked strip and Industrial's tiles
TILES = {"console": dict(h=44, pad=14, mark=14, ring=2, dot=6, mark_gap=10, size=16, gap=8),
         "folio": dict(h=40, pad=14, size=14, gap=1),
         "industrial": dict(h=72, list_h=56, pad=21, lamp=10, lamp_gap=16, right=16, size=15.5, gap=12, bar=3)}
# A theme's colour on its card or tile of the Look page, each a box w by h in
# the theme's own muted colour, gap apart (Slate-, Paper- and
# Industrial-Page-Look)
SWATCH = {"console": dict(w=26, h=18, gap=4), "folio": dict(w=26, h=18, gap=2),
          "industrial": dict(w=26, h=18, gap=5)}
# Folio's and Industrial's pass stepper
STEPPER = {"folio": dict(button=(26, 26), number=34, size=15),
           "industrial": dict(button=(34, 30), number=46, size=15)}
# The reset button beside a slider's number, and Industrial's frame round it
RESET = {"console": dict(box=28), "folio": dict(box=24), "industrial": dict(box=28)}


def strip_sizes(kind, size):
    """A strip's sizes, see SEGMENTS, the kind's first where it has none of
    that name."""
    table = SEGMENTS[kind]
    if kind == "console" and size == "panel":
        size = "choice"
    return table.get(size) or table[next(iter(table))]


# ---- what a face draws, worked out with no Tk

class Ctx(object):
    """What a face's drawing is worked out with, the look, the scale s, and a
    way of measuring words, measure(font, words) giving their width and
    linespace(font) a line's height in pixels, so the drawing needs no Tk.
    widget is the face, whose interpreter finds the look's faces of type
    where no root was bound, or None."""

    def __init__(self, look, s, measure, linespace, widget=None):
        self.look, self.s, self.widget = look, s, widget
        self.kind = widgets.kind_of(look)
        self._measure, self._linespace = measure, linespace

    def px(self, n):
        return sc.px(n, self.s)

    def border(self, n):
        return sc.border(n, self.s)

    def c(self, role):
        return self.look.c[role]

    def shade(self, name):
        return widgets.shade(self.look, name)

    def font(self, role, lit=False, size=None):
        """A role's font at this scale, at another size where one is given."""
        family, _size, weight = self.look.font(role, lit, self.widget)
        face = self.look.fonts[role]
        return (family, -sc.px(face.size if size is None else size, self.s), weight)

    def measure(self, font, words):
        return int(self._measure(font, words))

    def linespace(self, font):
        return int(self._linespace(font))


def rect(items, x0, y0, x1, y1, fill):
    """A box filled with a colour, from x0 up to x1 and y0 up to y1."""
    if x1 > x0 and y1 > y0:
        items.append(("rect", int(x0), int(y0), int(x1), int(y1), fill))


def frame(items, x0, y0, x1, y1, colour, width, foot=None):
    """A border width pixels wide inside a box, foot pixels at its foot."""
    foot = width if foot is None else foot
    rect(items, x0, y0, x1, y0 + width, colour)
    rect(items, x0, y1 - foot, x1, y1, colour)
    rect(items, x0, y0 + width, x0 + width, y1 - foot, colour)
    rect(items, x1 - width, y0 + width, x1, y1 - foot, colour)


def words(items, x, y, string, font, fill, anchor="center"):
    items.append(("text", int(x), int(y), string, font, fill, anchor))


def lines(items, x, y, string, font, fill, anchor, width, justify="left"):
    """Words that break onto further lines at width pixels, as a label with
    that wraplength breaks them."""
    items.append(("lines", int(x), int(y), string, font, fill, anchor, int(width), justify))


def mark(items, x, y, name, size, fill):
    """A glyph of widgets.GLYPHS centred on (x, y), size pixels high."""
    items.append(("glyph", int(x), int(y), name, int(size), fill))


def disc(items, x, y, d, fill, ground, ring=None, ring_w=0):
    """A round mark d pixels across with its top left at (x, y), in fill, in a
    ring ring_w pixels wide in ring where ring is given. It is drawn as an
    image with a soft edge over the boxes already drawn under it, or over
    ground where there are none, see disc_rows. Plan 1.8 draws round marks as
    glyphs. An image lands on the very pixel and is as soft, where a glyph's
    ink lies where its font puts it. The boxes under a mark are kept cut to
    its square, and those a later box covers whole are left out, which leaves
    its pixels as they are and makes one look of a mark one image wherever it
    stands, as a slider's thumb along its track."""
    under = []
    for item in items:
        if item[0] == "rect":
            _k, x0, y0, x1, y1, colour = item
            if x0 < x + d and x < x1 and y0 < y + d and y < y1:
                box = (max(0, x0 - x), max(0, y0 - y), min(d, x1 - x), min(d, y1 - y), colour)
                if box[:4] == (0, 0, d, d):
                    under = []
                under.append(box)
    items.append(("disc", int(x), int(y), int(d), fill, ground, ring, int(ring_w), tuple(under)))


def colour_under(under, x, y, ground):
    """The colour under a point of a round mark, of the last box there."""
    got = ground
    for x0, y0, x1, y1, colour in under:
        if x0 <= x < x1 and y0 <= y < y1:
            got = colour
    return got


def disc_rows(d, fill, ground, ring=None, ring_w=0, under=(), samples=4):
    """The pixels of a round mark, see disc, as rows of #rrggbb, each pixel
    the mean of samples by samples points in it, so its edge is soft as text
    is. Tk's Canvas draws its own circles with a hard edge."""
    r = d / 2.0
    inner = r - ring_w if ring is not None else r
    rgb = {}

    def of(colour):
        if colour not in rgb:
            rgb[colour] = tokens.rgb(colour)
        return rgb[colour]

    rows = []
    n = samples
    for j in range(d):
        row = []
        for i in range(d):
            total = [0.0, 0.0, 0.0]
            for sj in range(n):
                for si in range(n):
                    x, y = i + (si + 0.5) / n, j + (sj + 0.5) / n
                    dd = (x - r) ** 2 + (y - r) ** 2
                    if dd <= inner * inner:
                        colour = fill
                    elif dd <= r * r:
                        colour = ring
                    else:
                        colour = colour_under(under, x, y, ground)
                    for k, v in enumerate(of(colour)):
                        total[k] += v
            row.append(tokens.hexc(*(v / float(n * n) for v in total)))
        rows.append(row)
    return rows


def tk_format(lo, hi, resolution, digits=0, length=0):
    """The format Tk writes a Scale's value in when it calls the Scale's
    command, as tkScale.c's ComputeFormat works it out, such as %.2f for a
    scale from 0 to 2 in hundredths and %.0f for one in whole steps."""
    most = max(abs(float(lo)), abs(float(hi))) or 1.0
    most_sig = int(math.floor(math.log10(most)))
    num = int(digits or 0)
    if num <= 0:
        if resolution > 0:
            least = int(math.floor(math.log10(resolution)))
        else:
            step = abs(float(lo) - float(hi)) / (length if length > 0 else 1)
            least = int(math.floor(math.log10(step))) if step > 0 else 0
        num = max(1, most_sig - least + 1)
    e_digits = num + 4 + (1 if num > 1 else 0)
    after = max(0, num - most_sig - 1)
    f_digits = (most_sig + after if most_sig >= 0 else after) + (1 if after > 0 else 0) + (1 if most_sig < 0 else 0)
    if f_digits <= e_digits:
        return "%%.%df" % after
    return "%%.%de" % (num - 1)


def corner_spot(value):
    """Where a corner of the readout lies by its name, such as top right, as
    (row, column), 0 for the top or the left."""
    v = str(value).lower()
    return (1 if "bottom" in v else 0, 1 if "right" in v else 0)


def frac_of(value, lo, hi):
    """Where a value lies in a range, 0 to 1."""
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (float(value) - lo) / (float(hi) - lo)))


def value_at(x, x0, x1, lo, hi):
    """The value of a range at x, x0 being its low end and x1 its high end."""
    f = 0.0 if x1 <= x0 else max(0.0, min(1.0, (x - x0) / float(x1 - x0)))
    return lo + f * (hi - lo)


def segment_width(ctx, word, m):
    """A segment's width for its words, whichever weight they are in."""
    plain, bold = ctx.font("control", False, m["size"]), ctx.font("control", True, m["size"])
    return max(ctx.px(m["least"]), max(ctx.measure(plain, word), ctx.measure(bold, word)) + 2 * ctx.px(m["pad"]))


def switch_items(ctx, on, greyed, lit, size="settings", ground=None):
    """What a switch draws for a check button on or off, greyed or lit, as
    (items, hits, (width, height)). Slate draws Off and On segments in a well,
    the chosen one raised and, lit, ringed in the accent. Folio draws a block
    switch, filled in ink while on, with the word On or Off beside it.
    Industrial draws ON and OFF plates, ON lit amber while on and OFF outlined
    in the warning colour while off. A hit is (x0, y0, x1, y1, action), and
    ("set", True) asks for the switch on, ("set", False) for it off and
    ("toggle",) for the other way."""
    ground = ground or ctx.c("surface")
    items, hits = [], []
    if ctx.kind == "folio":
        m = SWITCH["folio"]
        bw, sw, sh = ctx.border(m["border"]), ctx.px(m["w"]), ctx.px(m["h"])
        knob, inner, gap = ctx.px(m["knob"]), ctx.px(m["inner"]), ctx.px(m["gap"])
        font = ctx.font("line", False, m["size"])
        width = sw + gap + max(ctx.measure(font, "On"), ctx.measure(font, "Off"))
        height = max(sh, ctx.linespace(font))
        y0 = (height - sh) // 2
        if on:
            edge = fill = ctx.c("faint") if greyed else ctx.c("raised")
            knob_colour = ctx.c("surface") if greyed else ctx.c("on_raised")
        else:
            edge = ctx.c("faint") if greyed else ctx.c("edge")
            fill, knob_colour = ground, edge
        rect(items, 0, y0, sw, y0 + sh, edge)
        rect(items, bw, y0 + bw, sw - bw, y0 + sh - bw, fill)
        kx = sw - bw - inner - knob if on else bw + inner
        ky = y0 + (sh - knob) // 2
        rect(items, kx, ky, kx + knob, ky + knob, knob_colour)
        words(items, sw + gap, height // 2, "On" if on else "Off", font,
              ctx.c("text") if on and not greyed else ctx.c("muted"), "w")
        hits.append((0, 0, width, height, ("toggle",)))
        return items, hits, (width, height)
    if ctx.kind == "industrial":
        m = SWITCH["industrial"].get(size) or SWITCH["industrial"]["settings"]
        part, height, b = ctx.px(m["part"]), ctx.px(m["h"]), ctx.border(1)
        width = 2 * part + 2 * b
        plain, bold = ctx.font("control", False, m["size"]), ctx.font("control", True, m["size"])
        edge = ctx.c("rule") if greyed else (ctx.c("accent") if lit else ctx.c("edge"))
        rect(items, 0, 0, width, height, edge)
        rect(items, b, b, width - b, height - b, ctx.shade("band") if greyed else ctx.c("well"))
        mid = b + part
        if on:
            rect(items, b, b, mid, height - b, ctx.c("faint") if greyed else ctx.c("accent"))
            words(items, (b + mid) // 2, height // 2, "ON", bold, ctx.c("well") if greyed else ctx.c("on_accent"))
            words(items, (mid + width - b) // 2, height // 2, "OFF", plain, ctx.c("muted"))
        else:
            words(items, (b + mid) // 2, height // 2, "ON", plain, ctx.c("muted"))
            frame(items, mid, b, width - b, height - b, ctx.c("faint") if greyed else ctx.c("warn"), b)
            words(items, (mid + width - b) // 2, height // 2, "OFF", bold, ctx.c("muted") if greyed else ctx.c("warn"))
        hits += [(0, 0, mid, height, ("set", True)), (mid, 0, width, height, ("set", False))]
        return items, hits, (width, height)
    m = SEGMENTS["console"].get(size) or SEGMENTS["console"]["settings"]
    plain, bold = ctx.font("control", False, m["size"]), ctx.font("control", True, m["size"])
    pad, gap, h = ctx.px(m["well"]), ctx.px(m["gap"]), ctx.px(m["h"])
    labels = ("Off", "On")
    widths = [segment_width(ctx, w, m) for w in labels]
    width, height = 2 * pad + widths[0] + gap + widths[1], 2 * pad + h
    rect(items, 0, 0, width, height, ctx.c("well"))
    x = pad
    for i, label in enumerate(labels):
        x1 = x + widths[i]
        if i == (1 if on else 0):
            rect(items, x, pad, x1, pad + h, ctx.c("lit") if greyed else ctx.c("raised"))
            if lit and not greyed:
                frame(items, x, pad, x1, pad + h, ctx.c("accent"), ctx.px(2))
            words(items, (x + x1) // 2, pad + h // 2, label, plain if greyed else bold,
                  ctx.c("muted") if greyed else ctx.c("strong"))
        else:
            words(items, (x + x1) // 2, pad + h // 2, label, plain, ctx.c("muted"))
        x = x1 + gap
    mid = pad + widths[0] + gap // 2
    hits += [(0, 0, mid, height, ("set", False)), (mid, 0, width, height, ("set", True))]
    return items, hits, (width, height)


def segment_items(ctx, width, height, word, chosen, greyed, lit, size="settings", ground=None):
    """One choice of a strip, width by height, its words in the look's case
    already. Slate's chosen segment is raised in the well and ringed in the
    accent while its row is lit, Folio's is ink with the paper's colour on it,
    and Industrial's is amber. Greyed, the chosen one keeps a quieter mark."""
    m = strip_sizes(ctx.kind, size)
    plain, bold = ctx.font("control", False, m["size"]), ctx.font("control", True, m["size"])
    items = []
    middle = (width // 2, height // 2)
    if ctx.kind == "folio":
        if chosen:
            rect(items, 0, 0, width, height, ctx.shade("greyed_fill") if greyed else ctx.c("raised"))
            words(items, middle[0], middle[1], word, bold, ctx.c("muted") if greyed else ctx.c("on_raised"))
        else:
            rect(items, 0, 0, width, height, ground or ctx.c("surface"))
            words(items, middle[0], middle[1], word, plain, ctx.c("muted") if greyed else ctx.c("text"))
    elif ctx.kind == "industrial":
        if chosen and not greyed:
            rect(items, 0, 0, width, height, ctx.c("accent"))
            words(items, middle[0], middle[1], word, bold, ctx.c("on_accent"))
        elif chosen:
            rect(items, 0, 0, width, height, ctx.shade("band"))
            frame(items, 0, 0, width, height, ctx.c("faint"), ctx.border(1))
            words(items, middle[0], middle[1], word, bold, ctx.c("muted"))
        else:
            rect(items, 0, 0, width, height, ctx.shade("band") if greyed else ctx.c("well"))
            words(items, middle[0], middle[1], word, plain, ctx.c("muted"))
    else:
        if chosen:
            rect(items, 0, 0, width, height, ctx.c("lit") if greyed else ctx.c("raised"))
            if lit and not greyed:
                frame(items, 0, 0, width, height, ctx.c("accent"), ctx.px(2))
            words(items, middle[0], middle[1], word, plain if greyed else bold,
                  ctx.c("muted") if greyed else ctx.c("strong"))
        else:
            rect(items, 0, 0, width, height, ctx.c("well"))
            words(items, middle[0], middle[1], word, plain, ctx.c("muted"))
    return items, [(0, 0, width, height, ("invoke",))], (width, height)


def tile_size(ctx, word, listed=False):
    """A card's or a tile's width for its words, and its height. listed is a
    tile in a list, which Industrial draws lower than one of two side by side."""
    m = TILES[ctx.kind]
    if ctx.kind == "console":
        font = ctx.font("tile", True, m["size"])
        width = 2 * ctx.px(m["pad"]) + ctx.px(m["mark"]) + ctx.px(m["mark_gap"]) + ctx.measure(font, word)
        return width, ctx.px(m["h"])
    if ctx.kind == "folio":
        font = ctx.font("control", True, m["size"])
        return 2 * ctx.px(m["pad"]) + ctx.measure(font, word), ctx.px(m["h"])
    font = ctx.font("tile", False, m["size"])
    width = ctx.px(m["pad"]) + ctx.px(m["lamp"]) + ctx.px(m["lamp_gap"]) + ctx.measure(font, word) + ctx.px(m["right"])
    return width, ctx.px(m["list_h"] if listed else m["h"])


def tile_items(ctx, width, height, word, chosen, greyed, lit, ground=None, swatches=None, swatch_x=None):
    """One choice drawn large. Slate's card, raised with a filled round mark
    while chosen and ringed in the accent while its row is lit, Folio's row of
    a stacked strip, in ink while chosen, and Industrial's tile with its
    square lamp, amber while chosen, and lit with an amber edge and bar.
    swatches are a theme's colours on the Look page, each as (its colour, its
    edge), drawn in a row from swatch_x, see SWATCH."""
    items, hits, size = _tile_items(ctx, width, height, word, chosen, greyed, lit, ground)
    if swatches and swatch_x is not None:
        m = SWATCH[ctx.kind]
        w, h, gap, b = ctx.px(m["w"]), ctx.px(m["h"]), ctx.px(m["gap"]), ctx.border(1)
        x, y = int(swatch_x), (height - h) // 2
        for fill, edge in swatches:
            rect(items, x, y, x + w, y + h, edge)
            rect(items, x + b, y + b, x + w - b, y + h - b, fill)
            x += w + gap
    return items, hits, size


def _tile_items(ctx, width, height, word, chosen, greyed, lit, ground=None):
    m = TILES[ctx.kind]
    items = []
    if ctx.kind == "console":
        fill = (ctx.c("lit") if greyed else ctx.c("raised")) if chosen else ctx.c("well")
        rect(items, 0, 0, width, height, fill)
        if chosen and lit and not greyed:
            frame(items, 0, 0, width, height, ctx.c("accent"), ctx.px(2))
        d, x = ctx.px(m["mark"]), ctx.px(m["pad"])
        y = (height - d) // 2
        ring = (ctx.c("muted") if greyed else ctx.c("strong")) if chosen else ctx.c("faint")
        disc(items, x, y, d, fill, fill, ring, ctx.px(m["ring"]))
        if chosen:
            dot = ctx.px(m["dot"])
            disc(items, x + (d - dot) // 2, y + (d - dot) // 2, dot, ring, fill)
        font = ctx.font("tile", chosen and not greyed, m["size"])
        colour = ctx.c("muted") if greyed else (ctx.c("strong") if chosen else ctx.c("text"))
        words(items, x + d + ctx.px(m["mark_gap"]), height // 2, word, font, colour, "w")
    elif ctx.kind == "folio":
        fill = (ctx.shade("greyed_fill") if greyed else ctx.c("raised")) if chosen else (ground or ctx.c("surface"))
        rect(items, 0, 0, width, height, fill)
        colour = ctx.c("muted") if greyed else (ctx.c("on_raised") if chosen else ctx.c("text"))
        words(items, ctx.px(m["pad"]), height // 2, word, ctx.font("control", chosen, m["size"]), colour, "w")
    else:
        b = ctx.border(1)
        on = chosen and lit and not greyed
        rect(items, 0, 0, width, height, ctx.c("accent") if on else ctx.c("edge"))
        rect(items, b, b, width - b, height - b, ctx.c("lit") if on else ctx.c("surface"))
        if on:
            rect(items, b, b, b + ctx.px(m["bar"]), height - b, ctx.c("accent"))
        lamp, x = ctx.px(m["lamp"]), ctx.px(m["pad"])
        y = (height - lamp) // 2
        gap = ctx.px(3)
        rect(items, x - gap - b, y - gap - b, x + lamp + gap + b, y + lamp + gap + b,
             ctx.c("accent") if chosen and not greyed else ctx.c("faint"))
        rect(items, x - gap, y - gap, x + lamp + gap, y + lamp + gap, ctx.c("well"))
        rect(items, x, y, x + lamp, y + lamp,
             (ctx.c("faint") if greyed else ctx.c("accent")) if chosen else ctx.c("well"))
        words(items, x + lamp + ctx.px(m["lamp_gap"]), height // 2, word, ctx.font("tile", False, m["size"]),
              ctx.c("muted") if greyed else ctx.c("text"), "w")
    return items, [(0, 0, width, height, ("invoke",))], (width, height)


def carousel_items(ctx, name, index, count, greyed, size="settings", colour=None, bold=False, ground=None):
    """Slate's carousel, a name between two arrows in a well, with a pip for
    each of count choices under it, the chosen one bright. An arrow's hit is
    ("step", -1) or ("step", 1)."""
    m = CAROUSEL.get(size) or CAROUSEL["settings"]
    width, height, arrow = ctx.px(m["w"]), ctx.px(m["h"]), ctx.px(m["arrow"])
    items = []
    rect(items, 0, 0, width, height, ctx.c("well"))
    arrow_colour = ctx.c("faint") if greyed else ctx.c("text")
    mark(items, arrow // 2, height // 2, "left", ctx.px(12), arrow_colour)
    mark(items, width - arrow // 2, height // 2, "right", ctx.px(12), arrow_colour)
    pips = bool(m["pip"]) and count > 0
    name_y = (height - ctx.px(5)) // 2 if pips else height // 2
    words(items, width // 2, name_y, name, ctx.font("control", bold, m["size"]),
          colour or (ctx.c("muted") if greyed else ctx.c("strong")))
    if pips:
        pw, ph, pg = ctx.px(m["pip"]), ctx.px(2), ctx.px(4)
        x = (width - (count * pw + (count - 1) * pg)) // 2
        y1 = height - ctx.px(5)
        for i in range(count):
            bright = ctx.c("muted") if greyed else ctx.c("strong")
            rect(items, x, y1 - ph, x + pw, y1, bright if i == index else ctx.c("faint"))
            x += pw + pg
    return items, [(0, 0, arrow, height, ("step", -1)), (width - arrow, 0, width, height, ("step", 1))], \
        (width, height)


def track_items(ctx, frac, greyed, lit, ground=None):
    """Slate's slider, a track filled up to a round thumb, which a ring of the
    row's colour sets off from the track. The fill and the thumb are in the
    accent while the row is lit, in the text colour while not, and faint
    while greyed."""
    m = SLIDER["console"]
    ground = ground or ctx.c("surface")
    width, height = ctx.px(m["w"]), ctx.px(m["h"])
    th, d = ctx.px(m["track"]), ctx.px(m["thumb"])
    ty = (height - th) // 2
    cx = d // 2 + int(round(frac * (width - d)))
    colour = ctx.c("faint") if greyed else (ctx.c("accent") if lit else ctx.c("text"))
    items = []
    rect(items, 0, ty, width, ty + th, ctx.c("well"))
    rect(items, 0, ty, cx, ty + th, colour)
    disc(items, cx - d // 2, (height - d) // 2, d, colour, ground, ground, ctx.px(m["ring"]))
    return items, [(0, 0, width, height, ("drag", d // 2, width - d + d // 2))], (width, height)


def ruler_items(ctx, frac, greyed, lit, marks=MARKS, long_at=None, heights=(3, 6), ends=None, ground=None, top=7):
    """Folio's ruler, a 2 pixel line in ink up to a 6 by 18 marker and in the
    edge colour after it, with ticks under it, the long one at long_at, and
    ends, the words at its two ends, where given. The marker is in the accent
    while the row is lit. Greyed, the line and the ticks go pale and the
    marker is an outline."""
    m = SLIDER["folio"]
    ground = ground or ctx.c("surface")
    width, row, t = ctx.px(m["w"]), ctx.px(m["row"]), ctx.px(top)
    lw = ctx.px(m["line"])
    mw, mh = ctx.px(m["marker"][0]), ctx.px(m["marker"][1])
    ly0 = t + (row - lw) // 2
    mx = int(round(frac * (width - mw)))
    my = t + (row - mh) // 2
    items = []
    rect(items, 0, ly0, mx, ly0 + lw, ctx.shade("greyed_line") if greyed else ctx.c("text"))
    rect(items, mx + mw, ly0, width, ly0 + lw, ctx.shade("greyed_track") if greyed else ctx.c("edge"))
    if greyed:
        b = ctx.border(m["border"])
        rect(items, mx, my, mx + mw, my + mh, ctx.shade("greyed_line"))
        rect(items, mx + b, my + b, mx + mw - b, my + mh - b, ground)
    else:
        rect(items, mx, my, mx + mw, my + mh, ctx.c("accent") if lit else ctx.c("text"))
    ty = t + row + ctx.px(m["tick_gap"])
    tick = ctx.shade("greyed_track") if greyed else ctx.c("edge")
    for f in marks:
        x = int(round(f * (width - mw))) + mw // 2
        h = heights[1] if long_at is not None and abs(f - long_at) < 1e-9 else heights[0]
        rect(items, x, ty, x + 1, ty + ctx.px(h), tick)
    height = ty + ctx.px(m["ticks"])
    if ends:
        font = ctx.font("beside", False, RULER_WORDS)
        wy = height + ctx.px(1)
        words(items, 0, wy, ends[0], font, ctx.c("muted"), "nw")
        words(items, width, wy, ends[1], font, ctx.c("muted"), "ne")
        height = wy + ctx.linespace(font)
    return items, [(0, 0, width, height, ("drag", mw // 2, width - mw + mw // 2))], (width, height)


def trough_items(ctx, frac, greyed, lit, marks=MARKS, long_at=None, ground=None):
    """Industrial's slider, an amber fill in a framed trough, ticks under it,
    the long one at long_at, and a plate of a thumb in the text colour. The
    trough's frame is amber while the row is lit. Greyed, the fill and the
    thumb are faint and the trough dark."""
    m = SLIDER["industrial"]
    width, height = ctx.px(m["w"]), ctx.px(m["h"])
    ty, th = ctx.px(m["trough"][0]), ctx.px(m["trough"][1])
    b = ctx.border(1)
    tw, thh, tt = ctx.px(m["thumb"][0]), ctx.px(m["thumb"][1]), ctx.px(m["thumb"][2])
    cx = tw // 2 + int(round(frac * (width - tw)))
    items = []
    rect(items, 0, ty, width, ty + th, ctx.c("rule") if greyed else (ctx.c("accent") if lit else ctx.c("edge")))
    rect(items, b, ty + b, width - b, ty + th - b, ctx.shade("band") if greyed else ctx.c("well"))
    rect(items, b, ty + b, cx, ty + th - b, ctx.c("faint") if greyed else ctx.c("accent"))
    y0 = ctx.px(m["ticks"][0])
    for f in marks:
        x = int(round(f * (width - 1)))
        is_long = long_at is not None and abs(f - long_at) < 1e-9
        colour = (ctx.c("faint") if greyed else ctx.c("muted")) if is_long else (
            ctx.c("edge") if greyed else ctx.c("faint"))
        rect(items, x, y0, x + 1, y0 + ctx.px(m["ticks"][2] if is_long else m["ticks"][1]), colour)
    x0 = cx - tw // 2
    rect(items, x0, tt, x0 + tw, tt + thh, ctx.c("well"))
    rect(items, x0 + b, tt + b, x0 + tw - b, tt + thh - b, ctx.c("faint") if greyed else ctx.c("text"))
    return items, [(0, 0, width, height, ("drag", tw // 2, width - tw + tw // 2))], (width, height)


def slider_items(ctx, frac, greyed, lit, long_at=None, ground=None):
    """A value's slider in the look, see track_items, ruler_items and
    trough_items."""
    if ctx.kind == "folio":
        return ruler_items(ctx, frac, greyed, lit, MARKS, long_at, (3, 6), None, ground, 7)
    if ctx.kind == "industrial":
        return trough_items(ctx, frac, greyed, lit, MARKS, long_at, ground)
    return track_items(ctx, frac, greyed, lit, ground)


def ladder_items(ctx, index, count, greyed, ends=("", ""), ground=None):
    """Industrial's quality step, a ladder of count blocks, amber up to the
    chosen one, which a ring in the text colour marks, dark after it, with
    the words of the two ends under it. A block's hit is ("set", its step)."""
    ground = ground or ctx.c("surface")
    bw, bh, gap = ctx.px(LADDER["block"][0]), ctx.px(LADDER["block"][1]), ctx.px(LADDER["gap"])
    ring_gap, ring_line = ctx.px(LADDER["ring"][0]), ctx.border(LADDER["ring"][1])
    edge = ring_gap + ring_line
    width = 2 * edge + count * bw + (count - 1) * gap
    lit = ctx.c("faint") if greyed else ctx.c("accent")
    items, hits = [], []
    for i in range(count):
        x, y = edge + i * (bw + gap), edge
        if i == index:
            rect(items, x - edge, y - edge, x + bw + edge, y + bh + edge, ctx.c("muted") if greyed else ctx.c("text"))
            rect(items, x - ring_gap, y - ring_gap, x + bw + ring_gap, y + bh + ring_gap, ground)
        if i <= index:
            rect(items, x, y, x + bw, y + bh, lit)
        else:
            rect(items, x, y, x + bw, y + bh, ctx.c("faint"))
            rect(items, x + ring_line, y + ring_line, x + bw - ring_line, y + bh - ring_line, ctx.c("well"))
        hits.append((x - gap // 2, 0, x + bw + gap - gap // 2, edge + bh + edge, ("set", i)))
    font = ctx.font("beside", False, LADDER["size"])
    wy = edge + bh + ctx.px(LADDER["words_gap"])
    words(items, edge, wy, ends[0], font, ctx.c("muted"), "nw")
    words(items, width - edge, wy, ends[1], font, ctx.c("muted"), "ne")
    return items, hits, (width, wy + ctx.linespace(font))


def quality_items(ctx, index, count, names, greyed, lit, size="settings", ground=None):
    """The quality step in the look, Slate's carousel with the step's name and
    a pip for each step, Folio's ruler with a tick for each step and the end
    steps' names under it, and Industrial's ladder, see carousel_items,
    ruler_items and ladder_items. Folio and Industrial name the step beside
    the face, in the lens's own label."""
    index = max(0, min(count - 1, index))
    ends = (names[0], names[-1]) if names else ("", "")
    if ctx.kind == "folio":
        marks = [i / float(count - 1) for i in range(count)] if count > 1 else [0.0]
        return ruler_items(ctx, marks[index], greyed, lit, marks, None, (5, 5), ends, ground, 3)
    if ctx.kind == "industrial":
        return ladder_items(ctx, index, count, greyed, ends, ground)
    name = names[index] if 0 <= index < len(names) else ""
    return carousel_items(ctx, name, index, count, greyed, size, ground=ground)


def corner_items(ctx, spots, names, index, greyed=False, ground=None):
    """Folio's and Industrial's corner, a miniature screen with a block in
    each corner, the chosen one filled, Folio's in ink with the corner's name
    after the screen and Industrial's in amber with the name in capitals
    before it. spots are each choice's (row, column), and a hit on a quarter
    of the screen is ("pick", that choice)."""
    m = CORNER[ctx.kind]
    sw, sh = ctx.px(m["screen"][0]), ctx.px(m["screen"][1])
    b, pad, gap = ctx.border(m["border"]), ctx.px(m["pad"]), ctx.px(m["gap"])
    name = names[index] if 0 <= index < len(names) else ""
    items, hits = [], []
    if ctx.kind == "folio":
        font = ctx.font("line", False, m["size"])
        width = sw + gap + max([ctx.measure(font, n) for n in names] or [0])
        height = max(sh, ctx.linespace(font))
        sx, y0 = 0, (height - sh) // 2
        words(items, sw + gap, height // 2, name, font, ctx.c("muted") if greyed else ctx.c("text"), "w")
        edge, inside, chosen_colour, other = (ctx.c("faint") if greyed else ctx.c("edge")), ctx.c("well"), (
            ctx.c("muted") if greyed else ctx.c("text")), (ctx.c("faint") if greyed else ctx.c("edge"))
    else:
        font = ctx.font("control", True, m["size"])
        caps = [text.display_case(n, "upper") for n in names]
        nw = max([ctx.measure(font, n) for n in caps] or [0])
        width, height = nw + gap + sw, sh
        sx, y0 = nw + gap, 0
        words(items, nw, height // 2, text.display_case(name, "upper"), font,
              ctx.c("muted") if greyed else ctx.c("text"), "e")
        edge, inside, chosen_colour, other = ctx.c("faint"), ctx.c("well"), (
            ctx.c("faint") if greyed else ctx.c("accent")), ctx.c("faint")
    rect(items, sx, y0, sx + sw, y0 + sh, edge)
    rect(items, sx + b, y0 + b, sx + sw - b, y0 + sh - b, inside)
    for i, (row, col) in enumerate(spots):
        if ctx.kind == "folio":
            bw_, bh_ = (ctx.px(m["chosen"][0]), ctx.px(m["chosen"][1])) if i == index else (
                ctx.px(m["other"][0]), ctx.px(m["other"][1]))
        else:
            bw_, bh_ = ctx.px(m["block"][0]), ctx.px(m["block"][1])
        x = sx + b + pad if col == 0 else sx + sw - b - pad - bw_
        y = y0 + b + pad if row == 0 else y0 + sh - b - pad - bh_
        if i == index:
            rect(items, x, y, x + bw_, y + bh_, chosen_colour)
        else:
            frame(items, x, y, x + bw_, y + bh_, other, ctx.border(1))
        hits.append((sx + col * (sw // 2), y0 + row * (sh // 2), sx + (col + 1) * (sw // 2) + col * (sw % 2),
                     y0 + (row + 1) * (sh // 2) + row * (sh % 2), ("pick", i)))
    return items, hits, (width, height)


def tie_items(ctx, width, height, ticked, greyed, lit, ground=None):
    """A tie's box, Same as pass 1, in the middle of width by height, with a
    check mark while ticked, its edge in the accent while it is lit."""
    m = TIE[ctx.kind]
    box, b = ctx.px(m["box"]), ctx.border(m["border"])
    x0, y0 = (width - box) // 2, (height - box) // 2
    check = ctx.c("muted") if greyed else ctx.c("strong")
    if ctx.kind == "folio" and ticked:
        edge = fill = ctx.shade("greyed_line") if greyed else ctx.c("raised")
        check = ctx.c("on_raised")
    elif ctx.kind == "folio":
        edge, fill = (ctx.c("faint") if greyed else ctx.c("edge")), ctx.c("well")
    elif ctx.kind == "industrial":
        edge, fill = ctx.c("faint"), ctx.c("well")
        check = ctx.c("muted") if greyed else ctx.c("text")
    else:
        edge, fill = ctx.c("faint"), (ctx.c("raised") if ticked else ctx.c("well"))
    if lit and not greyed:
        edge, b = ctx.c("accent"), max(b, ctx.px(2))
    items = []
    rect(items, 0, 0, width, height, ground or ctx.c("surface"))
    rect(items, x0, y0, x0 + box, y0 + box, edge)
    rect(items, x0 + b, y0 + b, x0 + box - b, y0 + box - b, fill)
    if ticked:
        mark(items, x0 + box // 2, y0 + box // 2, "check", ctx.px(m["check"]), check)
    return items, [(0, 0, width, height, ("invoke",))], (width, height)


def passes_items(ctx, count, greyed, limit=4, ground=None):
    """Slate's pass count on the panel, segments 1 to 4 in a well, the count's
    raised. A segment past limit, the most passes the lens runs, takes no
    click, and greyed, while Neural Rendering is off, none does. A hit is
    ("pick", a count)."""
    m = SEGMENTS["console"]["passes"]
    plain, bold = ctx.font("control", False, m["size"]), ctx.font("control", True, m["size"])
    pad, gap, h = ctx.px(m["well"]), ctx.px(m["gap"]), ctx.px(m["h"])
    labels = ("1", "2", "3", "4")
    widths = [segment_width(ctx, w, m) for w in labels]
    width, height = 2 * pad + sum(widths) + gap * (len(labels) - 1), 2 * pad + h
    items, hits = [], []
    rect(items, 0, 0, width, height, ctx.c("well"))
    x = pad
    for i, label in enumerate(labels):
        k, x1 = i + 1, x + widths[i]
        if k == count:
            rect(items, x, pad, x1, pad + h, ctx.c("lit") if greyed else ctx.c("raised"))
            words(items, (x + x1) // 2, pad + h // 2, label, plain if greyed else bold,
                  ctx.c("muted") if greyed else ctx.c("on_raised"))
        else:
            words(items, (x + x1) // 2, pad + h // 2, label, plain, ctx.c("muted"))
        if not greyed and k <= limit:
            hits.append((x, 0, x1, height, ("pick", k)))
        x = x1 + gap
    return items, hits, (width, height)


# ---- the faces

def selected(widget):
    """Whether a check or radio button is chosen as Tk has it, its variable
    holding its onvalue or its value, compared as text, as Tk compares them."""
    try:
        name = str(widget.cget("variable"))
        want = widget.cget("onvalue") if widget.winfo_class() == "Checkbutton" else widget.cget("value")
        have = widget.tk.call("set", name)
        return str(widget.tk.call("string", "cat", have)) == str(widget.tk.call("string", "cat", want))
    except tk.TclError:
        return False


def _above(widget, holder):
    """Whether widget lies above holder, so holder does not hide it, being in
    holder or made after the branch of its parent that holds holder."""
    parent = widget.master
    if holder is parent:
        return True
    at = holder
    while at is not None and at.master is not parent:
        at = at.master
    if at is None:
        return True
    kids = list(parent.children.values())
    return kids.index(widget) > kids.index(at)


def _ctx_of(widget, look):
    """A Ctx for a widget that is not a face, measuring in its interpreter."""
    return Ctx(look, look.scale_for(widget), lambda f, w: widget.tk.call("font", "measure", f, w),
               lambda f: widget.tk.call("font", "metrics", f, "-linespace"), widget)


class Face(tk.Canvas):
    """A face, a Canvas that draws what layout gives, at once with
    redraw_now or at the next idle moment with redraw_soon, once however
    often it is asked. A face follows the variables it watches, the model it
    follows, which a State widget or a LookScale tells of its changes, and
    a band that lights it. A click acts on its model through act, a press and
    a move do for a drag, and a face that is greyed, see enabled, does
    nothing. drawn says what it drew last, for the checks. It takes no
    keyboard, so a window that never takes the keyboard keeps it so. A face
    that cannot draw is cleared and draws no more, and steps aside where it
    covers its model, so the model shows and works as Tk draws it, see
    step_aside and widgets.fault. A window with such a face is still built."""

    LIT_FROM_MODEL = False              # whether the face is lit while its model is

    def __init__(self, master, look, ground=None, width=1, height=1):
        self.look = look
        self.fault = None
        self.ground_colour = ground
        self.is_lit = False
        self.items, self.hits, self.drawn = [], [], {}
        self.down = None
        self._idle = None
        self._traces = []
        self._followed = []
        tk.Canvas.__init__(self, master, width=width, height=height, bd=0, highlightthickness=0, takefocus=0,
                           bg=ground or look.c["surface"])
        self.bind("<Configure>", lambda e: self.redraw_soon(), add="+")
        self.bind("<Destroy>", self._gone, add="+")
        self.bind("<ButtonPress-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._motion, add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")

    # what the face shows and does, which each face has its own of

    def layout(self, ctx):
        """(items, hits, (width, height) or None for a cover, which takes its
        model's size)."""
        raise NotImplementedError

    def state(self):
        """What the face shows, for drawn."""
        return {}

    def act(self, action, x):
        """A click on a hit, or a press or a move on a drag at x."""

    def enabled(self):
        return True

    def resized(self, width, height):
        """The face has taken a new size."""

    def step_aside(self):
        """A face that could not draw takes itself off its model where it
        covers it, and says whether it did. One beside its model stays,
        blank."""
        return False

    # the rest is the same for every face

    def ground(self):
        return self.ground_colour or self.look.c["surface"]

    def set_ground(self, colour):
        """The background of the band the face is on, or None for its own."""
        self.ground_colour = colour
        self.configure(bg=self.ground())
        self.redraw_soon()

    def light(self, on):
        self.is_lit = bool(on)
        self.redraw_soon()

    def ctx(self):
        return Ctx(self.look, self.look.scale_for(self), self._measure, self._linespace, self)

    def _measure(self, font, string):
        return int(self.tk.call("font", "measure", font, string))

    def _linespace(self, font):
        return int(self.tk.call("font", "metrics", font, "-linespace"))

    def watch(self, name):
        """Draw again whenever the Tcl variable of this name is written."""
        if not name:
            return
        cmd = self.register(self._written)
        try:
            self.tk.call("trace", "add", "variable", name, "write", cmd)
            self._traces.append((name, cmd))
        except tk.TclError:
            pass

    def _written(self, *args):
        self.redraw_soon()

    def follow(self, model):
        """Draw again after every change of a model that tells of them."""
        followers = getattr(model, "followers", None)
        if followers is not None:
            followers.append(self._model_changed)
            self._followed.append(model)

    def _model_changed(self, model, keys, lit_changed):
        # lit while the code lights the model, or while its row is picked in
        # Settings, see widgets._State.picked
        if self.LIT_FROM_MODEL and hasattr(model, "is_lit"):
            self.is_lit = bool(model.is_lit or getattr(model, "shown_lit", False))
        self.redraw_soon()

    def redraw_soon(self):
        if self._idle is None and self.fault is None:
            try:
                self._idle = self.after_idle(self._redraw)
            except tk.TclError:
                self._idle = None

    def redraw_now(self):
        if self._idle is not None:
            try:
                self.after_cancel(self._idle)
            except tk.TclError:
                pass
            self._idle = None
        self._redraw()

    def _redraw(self):
        self._idle = None
        if self.fault is not None:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            self._paint()
        except Exception as exc:
            self._failed(exc)

    def _paint(self):
        items, hits, size = self.layout(self.ctx())
        self.delete("all")
        for item in items:
            self._draw(item)
        self.items, self.hits = items, hits
        if size is not None:
            width, height = size
            if (self.winfo_pixels(self.cget("width")), self.winfo_pixels(self.cget("height"))) != (width, height):
                self.configure(width=width, height=height)
                self.resized(width, height)
        self.drawn = dict(self.state(), lit=self.is_lit, size=size)

    def _failed(self, exc):
        """The face could not draw. It is cleared, takes no click and draws no
        more, and steps aside where it covers its model, see step_aside."""
        self.fault = str(exc) or type(exc).__name__
        self.items, self.hits, self.down = [], [], None
        self.drawn = {"fault": self.fault}
        aside = False
        try:
            self.delete("all")
            aside = bool(self.step_aside())
        except tk.TclError:
            pass
        widgets.fault(self, exc, aside)

    def _draw(self, item):
        kind = item[0]
        if kind == "rect":
            _k, x0, y0, x1, y1, fill = item
            self.create_rectangle(x0, y0, x1, y1, fill=fill, outline="", width=0)
        elif kind == "text":
            _k, x, y, string, font, fill, anchor = item
            self.create_text(x, y, text=string, font=font, fill=fill, anchor=anchor)
        elif kind == "lines":
            _k, x, y, string, font, fill, anchor, width, justify = item
            self.create_text(x, y, text=string, font=font, fill=fill, anchor=anchor, width=width, justify=justify)
        elif kind == "glyph":
            _k, x, y, name, size, fill = item
            font, char = widgets.glyph(self, name, size)
            self.create_text(x, y, text=char, font=font, fill=fill, anchor="center")
        elif kind == "disc":
            self.create_image(item[1], item[2], image=self._disc(item), anchor="nw")

    def _disc(self, item):
        """The image of a round mark, made once for each look of it and kept
        for the interpreter."""
        _k, _x, _y, d, fill, ground, ring, ring_w, under = item
        key = (d, fill, ground, ring, ring_w, under)
        cache = widgets.kept(self, "_lens_look_discs", lambda root: {})
        image = cache.get(key)
        if image is None:
            image = tk.PhotoImage(master=self._root(), width=d, height=d)
            rows = disc_rows(d, fill, ground, ring, ring_w, under)
            image.put(" ".join("{%s}" % " ".join(row) for row in rows))
            cache[key] = image
        return image

    def hit(self, x, y):
        for x0, y0, x1, y1, action in self.hits:
            if x0 <= x < x1 and y0 <= y < y1:
                return action
        return None

    def _press(self, event):
        self.down = self.hit(event.x, event.y)
        if self.down is not None and self.down[0] == "drag" and self.enabled():
            self.act(self.down, event.x)

    def _motion(self, event):
        if self.down is not None and self.down[0] == "drag" and self.enabled():
            self.act(self.down, event.x)

    def _release(self, event):
        down, self.down = self.down, None
        if down is None or down[0] == "drag" or not self.enabled():
            return
        if self.hit(event.x, event.y) == down:
            self.act(down, event.x)

    def _gone(self, event):
        if str(event.widget) != str(self):
            return
        if self._idle is not None:
            try:
                self.after_cancel(self._idle)
            except tk.TclError:
                pass
            self._idle = None
        for name, cmd in self._traces:
            try:
                self.tk.call("trace", "remove", "variable", name, "write", cmd)
            except tk.TclError:
                pass
        self._traces = []
        for model in self._followed:
            try:
                model.followers.remove(self._model_changed)
            except (AttributeError, ValueError):
                pass
        self._followed = []


class Cover(Face):
    """A face over the whole of its model, a child of the model placed with
    bordermode ignore, so it covers the inset Tk keeps round a check or radio
    button too. It takes its model's size and its model's background."""

    def __init__(self, model, look, ground=None):
        self.model = model
        Face.__init__(self, model, look, ground)
        self.place(x=0, y=0, relwidth=1, relheight=1, bordermode="ignore")
        self.follow(widgets.observe(model))

    def ground(self):
        if self.ground_colour:
            return self.ground_colour
        try:
            return widgets.real(self.model, "bg")
        except tk.TclError:
            return self.look.c["surface"]

    def enabled(self):
        return str(self.model.cget("state")) != "disabled"

    def act(self, action, x):
        self.model.invoke()

    def step_aside(self):
        self.place_forget()
        return True

    def extent(self):
        return max(1, self.winfo_width()), max(1, self.winfo_height())


class LabelCover(Cover):
    """The words of a check or radio button drawn over it as the button draws
    them, its words, font and colour as Tk has them, at the same place, but
    never moved a pixel while it is chosen, as Tk moves a chosen button's
    words that has no indicator (tkWinButton.c, TkpDisplayButton). Words the
    button breaks onto further lines at its wraplength break here at the
    same width, as a Folio label of two lines does."""

    LIT_FROM_MODEL = True

    def layout(self, ctx):
        m = self.model
        width, height = self.extent()
        greyed = not self.enabled()
        fill = widgets.real(m, "disabledforeground" if greyed else "fg")
        anchor = str(m.cget("anchor"))
        inset = widgets.inset_of(m) + m.winfo_pixels(m.cget("padx"))
        items = []
        rect(items, 0, 0, width, height, self.ground())
        if "w" in anchor:
            x, anchor = inset, "w"
        elif "e" in anchor:
            x, anchor = width - inset, "e"
        else:
            x, anchor = width // 2, "center"
        wrap = m.winfo_pixels(m.cget("wraplength"))
        if wrap > 0:
            lines(items, x, height // 2, widgets.real(m, "text"), widgets.real(m, "font"), fill, anchor, wrap,
                  str(m.cget("justify")))
        else:
            words(items, x, height // 2, widgets.real(m, "text"), widgets.real(m, "font"), fill, anchor)
        return items, [(0, 0, width, height, ("invoke",))], None

    def state(self):
        return {"words": str(widgets.real(self.model, "text")), "greyed": not self.enabled()}


class LookCheckbutton(widgets.StateCheckbutton):
    """A switch of a drawn look, the row's label, as plan 1.7 has it. It is
    the tk.Checkbutton the code makes, with its text, variable, command and
    .beside, drawn with no indicator, the row's background chosen or not, its
    label's type, and its words on a cover, see LabelCover. The code lights it
    by its accent colour and greys it by its state, as today. The switch
    itself is a SwitchFace at the row's right."""

    def __init__(self, master=None, look=None, cnf=None, font_role="row", **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        opts.update(indicatoron=0, relief="flat", offrelief="flat", overrelief="", bd=0, highlightthickness=0)
        opts.setdefault("anchor", "w")
        opts.setdefault("bg", look.legacy["bg"])
        widgets.StateCheckbutton.__init__(self, master, look, opts, roles=widgets.LABEL_ROLES,
                                          lit=("fg", "accent"), font_role=font_role)
        self.cover = LabelCover(self, look)


class SwitchFace(Face):
    """A switch at its row's right, for a check button, the row's label, see
    switch_items. size is settings, panel or small, the panel's indented
    rows."""

    LIT_FROM_MODEL = True

    def __init__(self, master, look, model, size="settings", ground=None):
        self.model, self.where = model, size
        Face.__init__(self, master, look, ground)
        self.watch(str(model.cget("variable")))
        self.follow(widgets.observe(model))
        self.is_lit = bool(getattr(model, "is_lit", False))
        self.redraw_now()

    def enabled(self):
        return str(self.model.cget("state")) != "disabled"

    def state(self):
        return {"on": selected(self.model), "greyed": not self.enabled()}

    def layout(self, ctx):
        st = self.state()
        return switch_items(ctx, st["on"], st["greyed"], self.is_lit, self.where, self.ground())

    def act(self, action, x):
        if action[0] == "toggle" or action[1] != selected(self.model):
            self.model.invoke()


class SegmentCover(Cover):
    """One choice of a ChoiceStrip drawn over its radio button."""

    def __init__(self, model, look, strip):
        self.strip = strip
        Cover.__init__(self, model, look)
        self.watch(str(model.cget("variable")))

    def ground(self):
        return self.strip.ground()

    def _model_changed(self, model, keys, lit_changed):
        Cover._model_changed(self, model, keys, lit_changed)
        if "state" in keys:
            self.strip.refresh()

    def state(self):
        return {"chosen": selected(self.model), "greyed": not self.enabled()}

    def layout(self, ctx):
        width, height = self.extent()
        word = text.display_case(str(self.model.cget("text")), self.strip.case)
        st = self.state()
        return segment_items(ctx, width, height, word, st["chosen"], st["greyed"], self.strip.is_lit, self.strip.where,
                             self.ground())


class ChoiceStrip(tk.Frame):
    """A row of choices drawn as one strip, the radio buttons of one variable,
    Slate's segments in a well, Folio's ink strip, Industrial's strip of
    capitals. Each button keeps its text, variable, value and command, and is
    packed into the strip with a cover, see SegmentCover. It keeps its place
    in Tab's traversal too, as plan 3.1 asks, the cover taking no keyboard. A
    button is made after the strip or in it, so the strip does not hide it,
    and add refuses one that would lie under it. size is settings or panel."""

    def __init__(self, master, look, size="settings", ground=None):
        self.look, self.where = look, size
        self.kind = widgets.kind_of(look)
        self.case = "upper" if self.kind == "industrial" else None
        self.ground_colour = ground
        self.is_lit = False
        self.buttons, self.covers = [], []
        m = strip_sizes(self.kind, size)
        s = look.scale_for(master)
        self.pad = sc.px(m["well"], s) if self.kind == "console" else sc.border(m["well"], s)
        self.gap = sc.px(m["gap"], s) if self.kind == "console" else sc.border(m["gap"], s)
        tk.Frame.__init__(self, master, bg=self._edge(), bd=0, highlightthickness=0, padx=self.pad, pady=self.pad)

    def _edge(self, greyed=False):
        c = self.look.c
        if self.kind == "console":
            return c["well"]
        if self.kind == "industrial":
            return c["rule"] if greyed else c["edge"]
        return c["faint"] if greyed else c["edge"]

    def ground(self):
        return self.ground_colour or self.look.c["surface"]

    def set_ground(self, colour):
        self.ground_colour = colour
        for cover in self.covers:
            cover.redraw_soon()

    def light(self, on):
        self.is_lit = bool(on)
        for cover in self.covers:
            cover.redraw_soon()

    def add(self, button):
        """Draw a radio button as the strip's next choice. Returns its cover."""
        if not _above(button, self):
            raise ValueError("a strip's choices are made after the strip, or they lie under it")
        ctx = _ctx_of(self, self.look)
        m = strip_sizes(self.kind, self.where)
        height = ctx.px(m["h"])
        button.configure(indicatoron=0, bd=0, highlightthickness=0, relief="flat", offrelief="flat", overrelief="")
        self.buttons.append(button)
        if m.get("width"):
            total = ctx.px(m["width"]) - 2 * self.pad
            n = len(self.buttons)
            for i, b in enumerate(self.buttons):
                widgets.exact(b, total // n + (1 if i < total % n else 0), height)
        else:
            word = text.display_case(str(button.cget("text")), self.case)
            widgets.exact(button, segment_width(ctx, word, m), height)
        button.pack(in_=self, side="left", padx=(self.gap if len(self.buttons) > 1 else 0, 0))
        cover = SegmentCover(widgets.observe(button), self.look, self)
        self.covers.append(cover)
        self.refresh()
        return cover

    def refresh(self):
        """The strip's edge as its choices are greyed or not."""
        greyed = bool(self.buttons) and all(str(b.cget("state")) == "disabled" for b in self.buttons)
        self.configure(bg=self._edge(greyed))


class TileCover(Cover):
    """One choice of Tiles drawn over its radio button."""

    def __init__(self, model, look, tiles):
        self.tiles = tiles
        Cover.__init__(self, model, look)
        self.watch(str(model.cget("variable")))

    def ground(self):
        return self.tiles.ground()

    def state(self):
        return {"chosen": selected(self.model), "greyed": not self.enabled()}

    def layout(self, ctx):
        width, height = self.extent()
        st = self.state()
        return tile_items(ctx, width, height, str(self.model.cget("text")), st["chosen"], st["greyed"],
                          self.tiles.is_lit, self.ground(), getattr(self.model, "swatches", None),
                          getattr(self.tiles, "swatch_x", None))


class Tiles(tk.Frame):
    """Choices drawn large, the radio buttons of one variable, Slate's cards,
    Folio's stacked strip and Industrial's tiles, in columns of equal width,
    one or two. Each button keeps its text, variable, value and command and
    its place in Tab's traversal, see TileCover, and is made after the tiles or
    in them, as for ChoiceStrip. listed draws Industrial's lower tiles of a
    list."""

    def __init__(self, master, look, columns=1, listed=True, ground=None):
        self.look, self.columns, self.listed = look, max(1, int(columns)), listed
        self.kind = widgets.kind_of(look)
        self.ground_colour = ground
        self.is_lit = False
        self.buttons, self.covers = [], []
        s = look.scale_for(master)
        if self.kind == "folio":
            self.gap = sc.border(TILES["folio"]["gap"], s)
            bg, pad = look.c["edge"], self.gap
        else:
            self.gap = sc.px(TILES[self.kind]["gap"], s)
            bg, pad = ground or look.c["surface"], 0
        tk.Frame.__init__(self, master, bg=bg, bd=0, highlightthickness=0, padx=pad, pady=pad)

    def ground(self):
        return self.ground_colour or self.look.c["surface"]

    def set_ground(self, colour):
        self.ground_colour = colour
        if self.kind != "folio":
            self.configure(bg=self.ground())
        for cover in self.covers:
            cover.redraw_soon()

    def light(self, on):
        self.is_lit = bool(on)
        for cover in self.covers:
            cover.redraw_soon()

    def add(self, button):
        """Draw a radio button as the next choice. Returns its cover."""
        if not _above(button, self):
            raise ValueError("the choices of tiles are made after the tiles, or they lie under them")
        width, height = tile_size(_ctx_of(self, self.look), str(button.cget("text")), self.listed)
        button.configure(indicatoron=0, bd=0, highlightthickness=0, relief="flat", offrelief="flat", overrelief="")
        widgets.exact(button, width, height)
        i = len(self.buttons)
        row, col = divmod(i, self.columns)
        self.columnconfigure(col, weight=1, uniform="tiles")
        button.grid(in_=self, row=row, column=col, sticky="we", padx=(self.gap if col else 0, 0),
                    pady=(self.gap if row else 0, 0))
        self.buttons.append(button)
        cover = TileCover(widgets.observe(button), self.look, self)
        self.covers.append(cover)
        return cover


class Carousel(Face):
    """Slate's carousel, see carousel_items, for choices the code keeps
    itself, the panel's profile picker among them. names() gives the names,
    index() the one chosen, step(d) is called for an arrow, greyed() says
    whether it is greyed and colour() the name's colour, or None for the
    look's. size is settings, panel or profile. It follows no variable or
    model of its own, so the caller calls redraw_soon after the names, the
    chosen one or the greyed state change, or watch(name) for a Tcl variable
    that holds them."""

    def __init__(self, master, look, names, index, step, size="settings", greyed=None, colour=None, bold=False,
                 ground=None):
        self._names, self._index, self._step = names, index, step
        self._greyed, self._colour, self.where, self.bold = greyed, colour, size, bold
        Face.__init__(self, master, look, ground)
        self.redraw_now()

    def enabled(self):
        return not (self._greyed and self._greyed())

    def state(self):
        names, i = list(self._names()), self._index()
        return {"index": i, "name": names[i] if 0 <= i < len(names) else "", "greyed": not self.enabled()}

    def layout(self, ctx):
        st = self.state()
        return carousel_items(ctx, st["name"], st["index"], len(list(self._names())), st["greyed"], self.where,
                              self._colour() if self._colour else None, self.bold, self.ground())

    def act(self, action, x):
        if action[0] == "step":
            self._step(action[1])


class LookScale(tk.Scale):
    """The lens's slider in a drawn look, the tk.Scale the code makes with its
    calls, command and variable, and a face over it, see SliderFace and
    QualityFace. Its width and length are the face's size, and its border,
    highlight and shown value none.

    With ROUTE inside the face covers the Scale, which stays where the code
    put it, so Tk calls the command at idle after set() or a drag, as for
    any Scale, and calls it not at all while the Scale is not shown, until it
    is. With hidden, the fallback, the Scale is made and never shown, its face
    stands where the code puts the Scale, which the geometry calls and
    winfo_ismapped pass on to, and the Scale's own set() calls the command
    once at the next idle moment with the value, as Tk writes it, after a
    change, as Tk would for a Scale shown, and once the face is shown where
    it was not. There the face goes when the Scale goes, as a face inside its
    Scale does.

    Its variable, a DoubleVar unless the code gives one, tells the face of
    every change of its value, and its configure tells the face of every other
    change, as its state."""

    def __init__(self, master=None, look=None, route=None, cnf=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        self.look = look
        self.route = route or ROUTE
        if self.route not in ROUTES:
            raise ValueError("a LookScale's route is inside or hidden, not %r" % (self.route,))
        self.face = None
        self.followers = []
        self.command = opts.pop("command", None) if self.route == "hidden" else None
        self._fire_id, self._fire_waiting = None, False
        if opts.get("variable") is None:
            opts["variable"] = tk.DoubleVar(master=master)
        self.variable = opts["variable"]
        opts.update(bd=0, highlightthickness=0, showvalue=0, takefocus=0)
        opts.setdefault("orient", "horizontal")
        tk.Scale.__init__(self, master, opts)
        name, cmd = str(tk.Scale.cget(self, "variable")), self.register(self._moved)
        self.tk.call("trace", "add", "variable", name, "write", cmd)
        self._trace = (name, cmd)
        self.bind("<Destroy>", self._gone, add="+")
        if self.command is not None:
            self._fire_soon()           # Tk calls a new Scale's command once it is first shown

    def _value(self):
        return float(self.tk.call(self._w, "get"))

    def _moved(self, *args):
        self._tell({"value"})

    def _tell(self, keys):
        for follower in list(self.followers):
            try:
                follower(self, keys, False)
            except tk.TclError:
                pass

    def attach(self, face):
        """Give the Scale its face, over it or, hidden, in its place."""
        self.face = face
        self.followers.append(face._model_changed)
        if self.route == "inside":
            face.place(x=0, y=0, relwidth=1, relheight=1, bordermode="ignore")
        else:
            face.bind("<Map>", self._face_shown, add="+")

    def configure(self, cnf=None, **kw):
        if (cnf is None and not kw) or isinstance(cnf, str):
            return tk.Scale.configure(self, cnf, **kw)
        opts = dict(cnf or {})
        opts.update(kw)
        if self.route == "hidden" and "command" in opts:
            self.command = opts.pop("command")
        before = self._value()
        got = tk.Scale.configure(self, opts) if opts else None
        if self.route == "hidden" and self._value() != before:
            self._fire_soon()
        self._tell(set(opts))
        return got

    config = configure

    def set(self, value):
        before = self._value()
        tk.Scale.set(self, value)
        if self.route == "hidden" and self._value() != before:
            self._fire_soon()

    def _fire_soon(self):
        if self.command is None or self._fire_id is not None:
            return
        try:
            self._fire_id = self.after_idle(self._fire)
        except tk.TclError:
            self._fire_id = None

    def _fire(self):
        self._fire_id = None
        face = self.face
        try:
            shown = face is not None and bool(face.winfo_ismapped())
        except tk.TclError:
            return
        if not shown:
            self._fire_waiting = True   # as Tk waits to call a Scale's command until the Scale is shown
            return
        self._fire_waiting = False
        fmt = tk_format(float(self.cget("from")), float(self.cget("to")), float(self.cget("resolution")),
                        int(float(self.cget("digits"))), self.winfo_pixels(self.cget("length")))
        if self.command is not None:
            self.command(fmt % self._value())

    def _face_shown(self, event=None):
        if self._fire_waiting:
            self._fire_soon()

    def _gone(self, event):
        if str(event.widget) != str(self):
            return
        if self._fire_id is not None:
            try:
                self.after_cancel(self._fire_id)
            except tk.TclError:
                pass
            self._fire_id = None
        try:
            self.tk.call("trace", "remove", "variable", self._trace[0], "write", self._trace[1])
        except tk.TclError:
            pass
        face = self.face
        if self.route == "hidden" and face is not None:
            try:
                if face.winfo_exists():
                    face.destroy()      # it stands beside the Scale, not in it, so Tk would leave it
            except tk.TclError:
                pass


# the calls a hidden Scale passes on to its face, which stands in its place
FORWARDED = ("grid", "grid_configure", "grid_remove", "grid_forget", "grid_info", "pack", "pack_configure",
             "pack_forget", "pack_info", "place", "place_configure", "place_forget", "place_info", "forget",
             "winfo_ismapped", "winfo_viewable", "winfo_rootx", "winfo_rooty", "winfo_x", "winfo_y",
             "winfo_width", "winfo_height", "winfo_reqwidth", "winfo_reqheight")


def _forward(name):
    own = getattr(tk.Scale, name)

    def call(self, *args, **kw):
        if self.route == "hidden" and self.face is not None:
            return getattr(self.face, name)(*args, **kw)
        return own(self, *args, **kw)
    call.__name__ = name
    call.__doc__ = "%s of the Scale, or of its face where the Scale is hidden, see LookScale." % name
    return call


for _name in FORWARDED:
    setattr(LookScale, _name, _forward(_name))


class ScaleFace(Face):
    """A face of a LookScale, over it or, hidden, in its place."""

    def __init__(self, model, look, ground=None):
        self.model = model
        Face.__init__(self, model if model.route == "inside" else model.master, look, ground)
        model.attach(self)
        self.redraw_now()

    def enabled(self):
        return str(self.model.cget("state")) != "disabled"

    def step_aside(self):
        if self.model.route == "inside":
            self.place_forget()
            return True
        return False

    def range(self):
        return float(self.model.cget("from")), float(self.model.cget("to"))

    def resized(self, width, height):
        if self.model.route == "inside":
            self.model.configure(length=width, width=height)


class SliderFace(ScaleFace):
    """A value's slider, see slider_items, its ticks' long one at mark, the
    value a button puts the slider at, 1.00 on the panel."""

    def __init__(self, model, look, mark=1.0, ground=None):
        self.mark = mark
        ScaleFace.__init__(self, model, look, ground)

    def state(self):
        lo, hi = self.range()
        value = float(self.model.get())
        return {"value": value, "frac": frac_of(value, lo, hi), "greyed": not self.enabled()}

    def layout(self, ctx):
        lo, hi = self.range()
        st = self.state()
        long_at = frac_of(self.mark, lo, hi) if self.mark is not None and lo <= self.mark <= hi else None
        return slider_items(ctx, st["frac"], st["greyed"], self.is_lit, long_at, self.ground())

    def act(self, action, x):
        if action[0] == "drag":
            lo, hi = self.range()
            self.model.set(value_at(x, action[1], action[2], lo, hi))


class QualityFace(ScaleFace):
    """The quality step, see quality_items, for a LookScale of whole steps,
    names the steps' names, the lens's FAST_QUALITY_NAMES. size is settings
    or panel, which only Slate's carousel tells apart."""

    def __init__(self, model, look, names, size="settings", ground=None):
        self.names, self.where = list(names), size
        ScaleFace.__init__(self, model, look, ground)

    def steps(self):
        lo, hi = self.range()
        return int(round(lo)), int(round(hi))

    def state(self):
        lo, hi = self.steps()
        return {"index": int(round(float(self.model.get()))) - lo, "count": hi - lo + 1, "greyed": not self.enabled()}

    def layout(self, ctx):
        st = self.state()
        return quality_items(ctx, st["index"], st["count"], self.names, st["greyed"], self.is_lit, self.where,
                             self.ground())

    def act(self, action, x):
        lo, hi = self.steps()
        now = int(round(float(self.model.get())))
        if action[0] == "step":
            self.model.set(max(lo, min(hi, now + action[1])))
        elif action[0] == "set":
            self.model.set(lo + action[1])
        elif action[0] == "drag":
            self.model.set(int(round(value_at(x, action[1], action[2], lo, hi))))


class CornerFace(Face):
    """The readout's corner, for the four radio buttons the code makes, which
    stay made and are left out of sight, as a radio button is chosen by its
    invoke() wherever it is. Slate's carousel steps round them, see
    carousel_items, and Folio's and Industrial's miniature screen chooses the
    corner clicked, see corner_items. Add the face to the dialog's hints, as
    the buttons are not under it."""

    def __init__(self, master, look, buttons, ground=None):
        self.buttons = list(buttons)
        Face.__init__(self, master, look, ground)
        if self.buttons:
            self.watch(str(self.buttons[0].cget("variable")))
        self.redraw_now()

    def chosen_index(self):
        return next((i for i, b in enumerate(self.buttons) if selected(b)), -1)

    def state(self):
        return {"index": self.chosen_index()}

    def layout(self, ctx):
        names = [str(b.cget("text")) for b in self.buttons]
        i = self.chosen_index()
        if ctx.kind == "console":
            return carousel_items(ctx, names[i] if i >= 0 else "", i, len(names), False, "settings", ground=self.ground())
        spots = [corner_spot(b.cget("value")) for b in self.buttons]
        return corner_items(ctx, spots, names, i, False, self.ground())

    def act(self, action, x):
        n = len(self.buttons)
        if not n:
            return
        if action[0] == "step":
            i = self.chosen_index()
            self.buttons[(i + action[1]) % n if i >= 0 else 0].invoke()
        elif action[0] == "pick":
            self.buttons[action[1]].invoke()


class TieBox(Cover):
    """A tie's box, Same as pass 1, drawn over the code's check button, which
    keeps its text, variable and command, and its grid place. The button is
    made the box's size, see tie_items."""

    LIT_FROM_MODEL = True

    def __init__(self, model, look, ground=None):
        kind = widgets.kind_of(look)
        box = sc.px(TIE[kind]["box"], look.scale_for(model))
        model.configure(indicatoron=0, bd=0, highlightthickness=0, relief="flat", offrelief="flat", overrelief="",
                        takefocus=0)
        widgets.exact(model, box, box)
        Cover.__init__(self, model, look, ground)
        self.watch(str(model.cget("variable")))
        self.is_lit = bool(getattr(model, "is_lit", False))

    def state(self):
        return {"ticked": selected(self.model), "greyed": not self.enabled()}

    def layout(self, ctx):
        width, height = self.extent()
        st = self.state()
        return tie_items(ctx, width, height, st["ticked"], st["greyed"], self.is_lit, self.ground())


class Stepper(tk.Frame):
    """Folio's and Industrial's pass stepper, the panel's minus, number and
    plus labels, which the code makes in the stepper and keeps setting as
    today, in boxes, see dress. Slate counts the passes in segments
    instead, see PassSegments."""

    def __init__(self, master, look, ground=None):
        self.look = look
        self.kind = widgets.kind_of(look)
        self.ground_colour = ground
        s = look.scale_for(master)
        self.b = sc.border(1, s)
        if self.kind == "industrial":
            tk.Frame.__init__(self, master, bg=look.c["edge"], bd=0, highlightthickness=0, padx=self.b, pady=self.b)
        else:
            tk.Frame.__init__(self, master, bg=ground or look.c["surface"], bd=0, highlightthickness=0)

    def dress(self, minus, number, plus):
        """The three labels in the stepper's boxes, packed in it."""
        look, s = self.look, self.look.scale_for(self)
        c = look.c
        m = STEPPER.get(self.kind, STEPPER["folio"])
        bw, bh = sc.px(m["button"][0], s), sc.px(m["button"][1], s)
        ctx = _ctx_of(self, look)
        plain = ctx.font("line", False, m["size"])
        heavy = ctx.font("value" if self.kind == "folio" else "panel_profile", False, m["size"])
        for label in (minus, plus):
            if self.kind == "industrial":
                opts = dict(bg=c["head"], fg=c["text"], highlightthickness=0)
                roles = {"bg": {"bg": "head", "hover": "hover"}}
            else:
                opts = dict(bg=self.ground_colour or c["surface"], fg=c["text"], highlightthickness=self.b,
                            highlightbackground=c["edge"])
                roles = {"bg": {"bg": "surface", "hover": "hover"}}
            self._dress(label, opts, roles, plain)
            # Industrial's minus and plus hold the line between them and the
            # number inside their width, as the drawing's buttons do
            widgets.exact(label, bw - (self.b if self.kind == "industrial" else 0), bh)
        roles = {"bg": {"bg": "well"}} if self.kind == "industrial" else {}
        self._dress(number, dict(bg=c["well"] if self.kind == "industrial" else (self.ground_colour or c["surface"]),
                                 fg=c["text"], highlightthickness=0), roles, heavy)
        widgets.exact(number, sc.px(m["number"], s), bh)
        gap = self.b if self.kind == "industrial" else 0
        for i, label in enumerate((minus, number, plus)):
            label.pack(in_=self, side="left", padx=(gap if i else 0, 0))

    def _dress(self, label, opts, roles, font):
        if isinstance(label, widgets._State):
            label.roles = dict(label.roles, **roles)
            label.shown_by = label.shown_by or (lambda t: str(t).strip())
            tk.Misc.configure(label, font=font, highlightthickness=opts.get("highlightthickness", 0),
                              highlightbackground=opts.get("highlightbackground", opts["bg"]))
            label.set_ground(None)
        else:
            tk.Misc.configure(label, font=font, **opts)


class PassSegments(Face):
    """Slate's pass count on the panel, segments 1 to 4, see passes_items, for
    the panel's number label, a State label the code keeps setting as today,
    which stays made and out of sight. pick(count) is called for a segment,
    which is greyed while the label's colour is the dim one, Neural Rendering
    off. limit() gives the most passes the lens runs."""

    def __init__(self, master, look, number, pick, limit=None, ground=None):
        self.number, self.pick, self.limit = number, pick, limit
        Face.__init__(self, master, look, ground)
        self.follow(number)
        self.redraw_now()

    def state(self):
        try:
            count = int(str(self.number.cget("text")).strip() or "1")
        except ValueError:
            count = 1
        greyed = tokens.same(str(self.number.cget("fg")), self.look.legacy["dim"])
        return {"count": count, "greyed": greyed, "limit": self.limit() if self.limit else 4}

    def enabled(self):
        return not self.state()["greyed"]

    def layout(self, ctx):
        st = self.state()
        return passes_items(ctx, st["count"], st["greyed"], st["limit"], self.ground())

    def act(self, action, x):
        if action[0] == "pick":
            self.pick(action[1])


class ResetFace(widgets.StateLabel):
    """The button beside a slider's number that puts the slider at 1.00, the
    code's label with its glyph, font, colours, state and click as today, see
    Lens._panel_reset, drawn in the look, framed in Industrial, plain in the
    others, and in the look's greyed colour while greyed. cget gives back the
    code's font and colours, which a test reads."""

    def __init__(self, master=None, look=None, cnf=None, ground=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        kind = widgets.kind_of(look)
        every = list(tokens.THEME_KEYS)
        self._plain = ground or look.c["surface"]
        roles = {"fg": {k: ("muted" if kind == "folio" else "text") for k in every},
                 "disabledforeground": {k: "faint" for k in every},
                 "bg": {"hover": "hover"}}
        opts.setdefault("bg", look.legacy["bg"])
        widgets.StateLabel.__init__(self, master, look, opts, roles=roles)
        self.box = sc.px(RESET[kind]["box"], look.scale_for(self))
        tk.Misc.configure(self, self._drawn())
        widgets.exact(self, self.box, self.box)

    def more(self, out):
        """Industrial's frame, in the edge colour, in the rule colour while
        greyed, and the button's face, the module's head colour while live,
        the row's while greyed. The others' face is the row's."""
        kind = widgets.kind_of(self.look)
        greyed = self.state_now == "disabled"
        hover = tokens.same(self.logical.get("bg", ""), self.look.legacy.get("hover", ""))
        if kind == "industrial":
            out["highlightthickness"] = 1
            out["highlightbackground"] = self.look.c["rule"] if greyed else self.look.c["edge"]
            if not hover and self.ground_colour is None:
                out["bg"] = self._plain if greyed else self.look.c["head"]
        elif not hover and self.ground_colour is None:
            out["bg"] = self._plain


def slider(master, look, route=None, mark=1.0, ground=None, **opts):
    """A LookScale with its SliderFace, made as the code makes a tk.Scale.
    Returns the LookScale, whose face is its face."""
    model = LookScale(master, look, route, **opts)
    SliderFace(model, look, mark, ground)
    return model


def quality(master, look, names, size="settings", route=None, ground=None, **opts):
    """A LookScale of whole steps with its QualityFace. Returns the LookScale."""
    model = LookScale(master, look, route, **opts)
    QualityFace(model, look, names, size, ground)
    return model
