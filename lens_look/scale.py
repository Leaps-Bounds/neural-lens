"""Sizes on the screen. A size in the drawings is in CSS pixels at 100
percent, and on the screen it is that times S, Tk's scaling in pixels to the
point over the 96 pixels an inch of 100 percent. Tk 8.6 keeps one scaling for
the whole process, so one S serves every window.

Pure apart from scale_of, which asks a widget's interpreter for its scaling.
"""
from lens_look import tokens

# The allowance that keeps a scale such as 1.2499999, which a sum on Tk's own
# scaling can give, from rounding a half the other way.
EPS = 1e-6


def px(n, s):
    """n CSS pixels at the scale s, in whole screen pixels, rounded half up
    and never under 1 for a size that is not 0. Python's round() is not used,
    since it rounds 4.5 down, and a 3 pixel bar has to come out 3, 4 and 5
    pixels at 100, 125 and 150 percent."""
    if not n:
        return 0
    if n < 0:
        return -px(-n, s)
    return max(1, int(n * s + 0.5 + EPS))


def hair(s=None):
    """A hairline, one screen pixel at every scale, so it stays crisp."""
    return 1


def border(n, s):
    """A border n CSS pixels wide, rounded down as a browser draws one and
    never under 1, so Folio's 1.5 pixel borders come out 1, 1 and 2 pixels at
    100, 125 and 150 percent."""
    if not n:
        return 0
    return max(1, int(n * s + EPS))


def font(face, s, family=None, lit=False, weight=None):
    """A Tk font for a tokens.Face at the scale s, as (family, size, weight).
    The size is negative, which Tk reads as pixels rather than points, and
    whole, since Tk takes whole sizes only, so 15.5 pixels comes out 16 at 100
    percent and 19 at 125. family is the face the fonts resolve to on this
    machine, the first of the face's chain until they are resolved, and
    weight the weight Tk is given for it, normal or bold, see
    lens_look.fonts.resolve. Tk has no weight between normal and bold, so
    unresolved 600 and above is bold and a weight below that normal, where a
    resolved family such as Bahnschrift SemiBold is that weight itself and is
    given as normal. lit takes the weight the role has lit or chosen."""
    if weight is None:
        css = face.lit if lit and face.lit else face.weight
        weight = "bold" if css >= 600 else "normal"
    name = family or tokens.FAMILIES[face.family][0]
    return (name, -px(face.size, s), weight)


def scale_of(widget):
    """S for the interpreter a widget belongs to, from Tk's own scaling."""
    return round(float(widget.tk.call("tk", "scaling")) * 72.0 / 96.0, 6)
