"""The control kit of the drawn looks.

A State widget is the tk.Label, tk.Checkbutton, tk.Radiobutton or tk.Button
the lens's code makes in a drawn look. It keeps the text, the colours and,
where the look sets the type, the font the code gives it, the logical ones,
and draws the look's own version of them. cget and w["text"] give back
exactly what the code set, so the code and the tests, which read states and
not pixels, read the same in every look. A widget the code lights, as
panel_light lights a row by its accent colour or the lens menu an entry by
its hover colour, draws itself lit and tells whoever follows it, such as the
band behind its row, see RowBand. Every change made through its configure is
told to its followers, the faces that draw it, see lens_look.faces.

The rest are the small pieces every look draws with, a key cap, a button
with a key cap in it, a rule, the band behind a row, the options of a field,
a list and a plain button, and the colours of a drawing that are none of the
roles.

Classic never makes any of these. Its widgets stay plain Tk, as they always
were.

Imports tkinter and the package, and nothing of the lens.
"""
import tkinter as tk

from lens_look import scale as sc
from lens_look import text, tokens

# The options whose colour a State widget keeps as the code gave it, the long
# names taken as the short ones
COLOURS = {"fg": "fg", "foreground": "fg", "bg": "bg", "background": "bg",
           "disabledforeground": "disabledforeground"}
LOGICAL_COLOURS = ("fg", "bg", "disabledforeground")

# The table of a row's label, which the code lights by its accent colour and
# greys by its dim colour. Lit it is drawn in the strong text colour, greyed in
# the muted one
LABEL_ROLES = {"fg": {"accent": "strong", "dim": "muted", "fg": "text"},
               "disabledforeground": {"accent": "muted", "dim": "muted"}}

# The icon fonts of Windows, as lens_look.dialogs looks for them, and the
# glyphs the kit draws from them, each as (its place in the icon font, the
# character drawn in Segoe UI Symbol where neither font is there)
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
PLAIN_FONT = "Segoe UI Symbol"
GLYPHS = {"left": (0xE76B, 0x2039), "right": (0xE76C, 0x203A), "check": (0xE73E, 0x2713),
          "chevron_down": (0xE70D, 0x25BE), "up": (0xE74A, 0x2191), "down": (0xE74B, 0x2193),
          "back": (0xE72B, 0x2190), "forward": (0xE72A, 0x2192), "warn": (0xE7BA, 0x26A0)}

# The colours of a drawing that are none of the roles, by the drawing's own
# names, each with the mix of two roles that stands in for it in a theme the
# drawings do not draw, as (a role, another, the part of the way from the
# first to the second). Each mix gives the drawn colour back to within a few
# steps from the kind's own roles
SHADES = {
    "console": {},
    "folio": {"greyed_line": ("muted", "surface", 0.48), "greyed_track": ("edge", "surface", 0.67),
              "greyed_fill": ("surface", "edge", 0.16), "rule_faint": ("surface", "rule", 0.6),
              "cap_on_ink_edge": ("raised", "on_raised", 0.4), "cap_on_ink_text": ("on_raised", "raised", 0.07)},
    "industrial": {"band": ("deep", "surface", 0.4)},
}

_NONE = object()

# The faults the kit met as it drew, each as (the class of what could not
# draw, the fault's words), for the checks and the probe. The first of each is
# said in one line of the lens's log, see fault
FAULTS = []


def fault(widget, exc, aside=False):
    """A face, a key cap or a button of the kit that could not draw. It goes
    on working, shown as Tk draws its model where it stepped aside, or blank.
    Kept in FAULTS, and said in one line of the lens's log the first time each
    such fault is met. Never raises, so a window goes on being built whatever
    a face meets in it."""
    try:
        key = (type(widget).__name__, str(exc) or type(exc).__name__)
        first = key not in FAULTS
        FAULTS.append(key)
        if first:
            print('a %s of the look could not be drawn ("%s"), so it shows %s'
                  % (key[0], key[1], "as Tk draws it" if aside else "blank"), flush=True)
    except Exception:
        pass                            # an output that cannot take the words must not stop the window


def model_of(widget):
    """The widget a click on this one stands for, the model of a face or a
    key cap that has one, such as the radio button under a cover or the button
    a cap is in, and else the widget itself. A click in a drawn look lands on
    the cover, so whatever gives the clicked control the keyboard, as
    Hints.pressed does, asks this first."""
    model = getattr(widget, "model", None)
    return widget if model is None else model


def kind_of(look):
    """The drawn kind a look's controls are drawn as, console for any other."""
    return look.kind if look.kind in tokens.DRAWN else "console"


def real(widget, key):
    """An option as Tk has it, the drawn value, past a State widget's logical one."""
    return tk.Misc.cget(widget, key)


def kept(widget, name, make):
    """A thing made once for the Tk interpreter a widget belongs to and kept on
    its root, such as the blank image or the icon font found."""
    root = widget._root()
    got = getattr(root, name, _NONE)
    if got is _NONE:
        got = make(root)
        setattr(root, name, got)
    return got


def blank(widget):
    """An image one pixel wide with nothing in it. A label or a button that
    shows it beside its words takes its width and height in pixels rather
    than in characters, see exact."""
    return kept(widget, "_lens_look_blank", lambda root: tk.PhotoImage(master=root, width=1, height=1))


def inset_of(widget):
    """What Tk adds round a label's or a button's content on Windows, its
    border and its highlight, and one more for a check or radio button, which
    keeps room for its focus ring (tkWinButton.c, TkpComputeButtonGeometry)."""
    inset = widget.winfo_pixels(widget.cget("bd")) + widget.winfo_pixels(widget.cget("highlightthickness"))
    if widget.winfo_class() in ("Checkbutton", "Radiobutton"):
        inset += 1
    return inset


def exact(widget, width, height, padx=0):
    """A label or a button exactly width by height pixels, whatever its words,
    by the blank image, with padx pixels before its words where they lie at
    its left or right. Tk adds the inset and the padding round the size it is
    given, see inset_of."""
    inset = inset_of(widget)
    widget.configure(image=blank(widget), compound="center", padx=padx, pady=0,
                     width=max(1, width - 2 * inset - 2 * padx), height=max(1, height - 2 * inset))


def icon_family(widget):
    """The first of ICON_FONTS this machine has, or None where it has neither."""
    def find(root):
        try:
            have = set(root.tk.splitlist(root.tk.call("font", "families")))
        except tk.TclError:
            have = set()
        return next((f for f in ICON_FONTS if f in have), None)
    return kept(widget, "_lens_look_icons", find)


def glyph(widget, name, size):
    """The font and the character of a glyph of GLYPHS, size pixels high."""
    icon, plain = GLYPHS[name]
    family = icon_family(widget)
    if family:
        return (family, -int(size), "normal"), chr(icon)
    return (PLAIN_FONT, -int(size), "normal"), chr(plain)


def observe(widget):
    """A plain widget made to tell followers of the changes made through its
    configure, as a State widget does, so a face sees the code grey it. A
    widget that tells them already is left as it is. Returns the widget."""
    if hasattr(widget, "followers"):
        return widget
    widget.followers = []
    own = widget.configure

    def configure(cnf=None, **kw):
        got = own(cnf, **kw)
        if not ((cnf is None and not kw) or isinstance(cnf, str)):
            keys = set(kw) | (set(cnf) if isinstance(cnf, dict) else set())
            for follower in list(widget.followers):
                try:
                    follower(widget, keys, False)
                except tk.TclError:
                    pass
        return got

    widget.configure = widget.config = configure
    return widget


def keys_of(look, colour):
    """The keys of the theme's ten colours that are this colour, in
    THEME_KEYS' order. A colour can be two of them, as Graphite's accent is
    its warning colour."""
    return [k for k in tokens.THEME_KEYS if tokens.same(look.legacy.get(k, ""), colour)]


def drawn_colour(look, option, colour, roles=None):
    """The colour a State widget draws for a colour the code gave one of its
    options, option being fg, bg or disabledforeground. roles is the widget's
    own table, {option: {a key of the ten: a role}}, whose keys come first, in
    its order, where a colour is more than one of the ten, and tokens.LOGICAL
    holds for the rest. A colour that is none of the ten is drawn as it is."""
    keys = keys_of(look, colour)
    if not keys:
        return colour
    for key, role in (roles or {}).get(option, {}).items():
        if key in keys:
            return look.c.get(role, colour)
    return look.c.get(tokens.LOGICAL[keys[0]], colour)


def shown_text(logical, case=None, shown=None):
    """The words a State widget draws for the text the code gave it, shown's
    own words where the widget has a way of its own, such as a picker that
    draws its chevron apart from its name, and else the text in the look's
    case."""
    if shown is not None:
        return shown(logical)
    return text.display_case(logical, case)


def own_theme(look):
    """Whether a look draws its kind's own built-in theme as the drawings have
    it, Slate, Paper or Industrial with no colour of the user's own, whose
    shades are then the drawings' very colours."""
    kind = look.kind
    return (kind in tokens.DRAWN and tokens.THEME_KIND.get(look.theme) == kind and look.theme != "Graphite"
            and all(tokens.same(look.legacy.get(k, ""), v) for k, v in tokens.LEGACY[kind].items()))


def shade(look, name):
    """A colour of a drawing that is none of the roles, by its name in SHADES,
    the drawing's own for the kind's own theme and the mix of roles SHADES
    gives for any other theme."""
    kind = kind_of(look)
    own = look.own.get(name)
    if own and own_theme(look):
        return own
    a, b, part = SHADES[kind][name]
    return tokens.mix(look.c[a], look.c[b], part)


class _State(object):
    """What the State widgets share, see the module's docstring. The widget's
    own class comes second in each State class, so super() reaches Tk's own
    methods. GROUNDS are the options that take the widget's background as
    well, so a check or radio button with no indicator looks the same chosen,
    pressed or not."""

    GROUNDS = ()

    def _begin(self, master, look, opts, roles, lit, case, shown, font_role):
        """The options Tk is given as the widget is made, the drawn ones, with
        the logical ones kept. lit is (an option, a key of the ten) whose
        logical colour shows the widget lit, such as ("fg", "accent")."""
        self.look = look
        self.roles = roles or {}
        self.lit_by = lit
        self.font_role = font_role
        face = look.fonts.get(font_role) if font_role else None
        self.case = case if case is not None else (face.case if face is not None else None)
        self.shown_by = shown
        self.logical = {}
        self.followers = []
        self.is_lit = False
        self.lit_font = False           # the lit weight always, as a Save button has it
        self.shown_lit = False          # drawn as the label of a row the pointer or the keys picked, see picked
        self.ground_colour = None       # the background a band gives the widget, which wins over its own
        self.state_now = "normal"
        self._kit_master = master
        return self._take(opts, made=False)

    def _take(self, opts, made=True):
        """Keep the logical text, colours and font of these options and give
        back the options Tk is to be given, the drawn ones in their place.
        made is False while the widget is not made yet."""
        out = {}
        for key, value in opts.items():
            name = COLOURS.get(key, key)
            if name in LOGICAL_COLOURS:
                self.logical[name] = value
            elif key == "text":
                self.logical["text"] = value
            elif key == "font" and self.font_role:
                self.logical["font"] = value
            else:
                if key == "state":
                    self.state_now = str(value)
                out[key] = value
        self.is_lit = self._lit_now()
        out.update(self._drawn(made))
        return out

    def _lit_now(self):
        if not self.lit_by:
            return False
        option, key = self.lit_by
        value = self.logical.get(option)
        return value is not None and tokens.same(value, self.look.legacy.get(key, ""))

    def _drawn(self, made=True):
        """The drawn options of the logical ones, the widget's state and the
        band it is on."""
        out = {}
        if "text" in self.logical:
            out["text"] = shown_text(self.logical["text"], self.case, self.shown_by)
        for name in ("fg", "disabledforeground"):
            if name in self.logical:
                out[name] = drawn_colour(self.look, name, self.logical[name], self.roles)
        if self.shown_lit and "fg" in out and tokens.same(out["fg"], self.look.c["text"]):
            out["fg"] = self.look.c["strong"]
        bg = self.ground_colour
        if bg is None and "bg" in self.logical:
            bg = drawn_colour(self.look, "bg", self.logical["bg"], self.roles)
        if bg is not None:
            out["bg"] = bg
            for name in self.GROUNDS:
                out[name] = bg
        if self.font_role:
            out["font"] = self.look.font(self.font_role, self.is_lit or self.lit_font or self.shown_lit,
                                         self if made else self._kit_master)
        self.more(out)
        return out

    def more(self, out):
        """Options of a State widget's own, added to the drawn ones."""

    def drawn_text(self):
        """The words the widget draws."""
        return shown_text(self.logical.get("text", ""), self.case, self.shown_by)

    def configure(self, cnf=None, **kw):
        if (cnf is None and not kw) or isinstance(cnf, str):
            return self._query(super(_State, self).configure(cnf))
        opts = {}
        if cnf:
            opts.update(cnf)
        opts.update(kw)
        was = self.is_lit
        drawn = self._take(opts)
        got = super(_State, self).configure(drawn) if drawn else None
        self._tell(set(COLOURS.get(k, k) for k in opts), was != self.is_lit)
        return got

    config = configure

    def cget(self, key):
        name = COLOURS.get(key, key)
        if name in self.logical:
            return self.logical[name]
        return super(_State, self).cget(key)

    __getitem__ = cget

    def _query(self, got):
        """configure's answer to a question, with the logical values in place
        of the drawn ones."""
        if isinstance(got, dict):
            for key, entry in list(got.items()):
                name = COLOURS.get(key, key)
                if name in self.logical and isinstance(entry, tuple) and len(entry) == 5:
                    got[key] = entry[:4] + (self.logical[name],)
        elif isinstance(got, tuple) and len(got) == 5:
            name = COLOURS.get(str(got[0]), str(got[0]))
            if name in self.logical:
                got = got[:4] + (self.logical[name],)
        return got

    def _tell(self, keys, lit_changed):
        for follower in list(self.followers):
            try:
                follower(self, keys, lit_changed)
            except tk.TclError:
                pass

    def follow(self, follower):
        """follower(widget, the options changed, whether it was lit or unlit)
        is called after each change made through configure."""
        self.followers.append(follower)

    def set_ground(self, colour):
        """The background of the band the widget is on, or None for its own."""
        self.ground_colour = colour
        super(_State, self).configure(self._drawn())
        self._tell({"bg"}, False)

    def picked(self, on):
        """Drawn as the label of a row the pointer or the keys picked in
        Settings, in its role's lit weight and in the strong colour where it
        is drawn in the text colour, as the page drawings draw a lit row's
        label. The words, the colours and the lit state the code gave it stay
        as they are, see lens_look.settings.SettingsFrame.select."""
        on = bool(on)
        if on == self.shown_lit:
            return
        self.shown_lit = on
        super(_State, self).configure(self._drawn())
        self._tell({"fg", "font"}, False)


class StateLabel(_State, tk.Label):
    """A tk.Label of a drawn look, see the module's docstring. roles, lit,
    case, shown and font_role are as _State._begin takes them."""

    def __init__(self, master=None, look=None, cnf=None, roles=None, lit=None, case=None, shown=None,
                 font_role=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        tk.Label.__init__(self, master, self._begin(master, look, opts, roles, lit, case, shown, font_role))


class StateCheckbutton(_State, tk.Checkbutton):
    """A tk.Checkbutton of a drawn look, see StateLabel."""

    GROUNDS = ("activebackground", "selectcolor")

    def __init__(self, master=None, look=None, cnf=None, roles=None, lit=None, case=None, shown=None,
                 font_role=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        tk.Checkbutton.__init__(self, master, self._begin(master, look, opts, roles, lit, case, shown, font_role))


class StateRadiobutton(_State, tk.Radiobutton):
    """A tk.Radiobutton of a drawn look, see StateLabel."""

    GROUNDS = ("activebackground", "selectcolor")

    def __init__(self, master=None, look=None, cnf=None, roles=None, lit=None, case=None, shown=None,
                 font_role=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        tk.Radiobutton.__init__(self, master, self._begin(master, look, opts, roles, lit, case, shown, font_role))


class StateButton(_State, tk.Button):
    """A tk.Button of a drawn look, see StateLabel."""

    def __init__(self, master=None, look=None, cnf=None, roles=None, lit=None, case=None, shown=None,
                 font_role=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        tk.Button.__init__(self, master, self._begin(master, look, opts, roles, lit, case, shown, font_role))


# ---- the pieces every look draws with

# A key cap's sizes in CSS pixels, by kind and by its font role, as (its
# least width, its height, the space beside its words, its border at the
# foot), which is 2 pixels in Folio and Industrial, as a key's front edge
CAPS = {
    "console": {"cap": (24, 24, 7, 1), "cap_button": (24, 24, 7, 1), "cap_panel": (22, 22, 6, 1),
                "cap_menu": (22, 22, 6, 1), "cap_note": (24, 22, 6, 1)},
    "folio": {"cap": (22, 21, 6, 2), "cap_button": (22, 20, 6, 2), "cap_panel": (22, 21, 6, 2),
              "cap_menu": (22, 20, 6, 2), "cap_note": (22, 20, 6, 2)},
    "industrial": {"cap": (24, 22, 6, 2), "cap_button": (24, 22, 6, 2), "cap_panel": (24, 22, 6, 2),
                   "cap_menu": (26, 22, 6, 2), "cap_note": (26, 22, 6, 2)},
}
# The colours the drawings give some roles' caps apart from the look's cap
# colours, by kind and role, as (the fill's role, the words' role), None
# keeping the look's own. Industrial fills its caps beside a menu entry or the
# panel's NR switch and those of the fullscreen note in its deep colour, and
# Slate draws the words of the note's caps in its strong colour
CAP_COLOURS = {"console": {"cap_note": (None, "strong")},
               "industrial": {"cap_menu": ("deep", None), "cap_note": ("deep", None)}}
# The keys a cap draws as an arrow, by the glyph of GLYPHS, and an arrow's size
# and the space beside it in CSS pixels, by kind and by role where a role's
# differ, as the drawings draw Up, Down, Left and Right
ARROWS = {"Up": "up", "Down": "down", "Left": "back", "Right": "forward"}
ARROW_CAPS = {"console": (12, 6), "folio": (10, 5), "industrial": (10, 6)}
ARROW_ROLES = {"console": {"cap_panel": (11, 5)}}


def arrow_cap(look, role):
    """An arrow cap's glyph size and the space beside it, in CSS pixels."""
    kind = kind_of(look)
    return ARROW_ROLES.get(kind, {}).get(role) or ARROW_CAPS[kind]


def cap_size(look, role, s, words_width, pad=None):
    """A key cap's width and height in pixels at the scale s, for words
    words_width pixels wide with pad CSS pixels beside them, the role's own
    where none is given, see CAPS. Its side edges are inside its width, as the
    drawings' caps have them."""
    least, height, own, _foot = CAPS[kind_of(look)][role]
    pad = own if pad is None else pad
    return max(sc.px(least, s), words_width + 2 * sc.px(pad, s) + 2 * sc.border(1, s)), sc.px(height, s)


def cap_colours(look, role, fill=None, edge=None, ink=None):
    """A key cap's fill, edge and words, those given, else the look's cap
    colours with the roles of CAP_COLOURS."""
    c = look.c
    fill_role, ink_role = CAP_COLOURS.get(kind_of(look), {}).get(role, (None, None))
    return fill or c[fill_role or "cap"], edge or c["cap_edge"], ink or c[ink_role or "cap_text"]


def cap_items(look, s, width, height, role, fill, edge):
    """The two boxes of a key cap, its edge and its face, as (x0, y0, x1, y1,
    colour), and the middle of its face, where its words go."""
    b = sc.border(1, s)
    foot = sc.border(CAPS[kind_of(look)][role][3], s)
    return [(0, 0, width, height, edge), (b, b, width - b, height - foot, fill)], (width // 2, (b + height - foot) // 2)


class KeyCap(tk.Canvas):
    """A key cap of a drawn look, the key's name in the look's cap type in a
    box with an edge, Folio's and Industrial's thicker at its foot, or an
    arrow for Up, Down, Left and Right. role is the cap's font role, cap,
    cap_button, cap_panel, cap_menu or cap_note, see tokens.FONT_ROLES, whose
    colours CAP_COLOURS and sizes CAPS give. fill, edge and ink stand in for
    those colours, as on a button. pad is the space beside the words in CSS
    pixels where a cap's differs from its role's, as for Slate's F9 beside the
    panel's NR switch, 5 where the panel's other caps have 6. model is the
    widget a click on the cap stands for, a button's cap its button, see
    model_of. cget and configure take text, the key's name, as a label's do.
    It takes no click of its own and never the keyboard. A cap that cannot
    draw stays blank, see fault."""

    def __init__(self, master, look, key, role="cap", ground=None, fill=None, edge=None, ink=None, pad=None,
                 model=None):
        self.look, self.role, self.key, self.pad = look, role, str(key), pad
        self.colours = (fill, edge, ink)
        self.fault = None
        if model is not None:
            self.model = model
        tk.Canvas.__init__(self, master, width=1, height=1, bd=0, highlightthickness=0, takefocus=0,
                           bg=ground or look.c["surface"])
        self._draw()

    def _words(self, widget):
        s = self.look.scale_for(widget)
        if self.key in ARROWS:
            return glyph(widget, ARROWS[self.key], sc.px(arrow_cap(self.look, self.role)[0], s))
        return self.look.font(self.role, False, widget), self.key

    def _size(self, widget):
        s = self.look.scale_for(widget)
        font, words = self._words(widget)
        pad = self.pad
        if pad is None and self.key in ARROWS:
            pad = arrow_cap(self.look, self.role)[1]
        return cap_size(self.look, self.role, s, int(widget.tk.call("font", "measure", font, words)), pad)

    def _draw(self):
        """The cap drawn at its size. One that could not draw is cleared and
        draws no more, see fault."""
        if self.fault is not None:
            return
        try:
            self._paint()
        except Exception as exc:
            self.fault = str(exc) or type(exc).__name__
            try:
                self.delete("all")
            except tk.TclError:
                pass
            fault(self, exc)

    def _paint(self):
        self.delete("all")
        s = self.look.scale_for(self)
        width, height = self._size(self)
        if (self.winfo_pixels(tk.Canvas.cget(self, "width")), self.winfo_pixels(tk.Canvas.cget(self, "height"))) \
                != (width, height):
            tk.Canvas.configure(self, width=width, height=height)
        fill, edge, ink = cap_colours(self.look, self.role, *self.colours)
        boxes, (cx, cy) = cap_items(self.look, s, width, height, self.role, fill, edge)
        for x0, y0, x1, y1, colour in boxes:
            self.create_rectangle(x0, y0, x1, y1, fill=colour, outline="", width=0)
        font, words = self._words(self)
        self.create_text(cx, cy, text=words, font=font, fill=ink, anchor="center")

    def cget(self, key):
        if key == "text":
            return self.key
        return tk.Canvas.cget(self, key)

    __getitem__ = cget

    def configure(self, cnf=None, **kw):
        if cnf == "text" and not kw:
            return ("text", "text", "Text", "", self.key)
        if (cnf is None and not kw) or isinstance(cnf, str):
            return tk.Canvas.configure(self, cnf)
        opts = dict(cnf or {})
        opts.update(kw)
        if "text" in opts:
            self.key = str(opts.pop("text"))
        got = tk.Canvas.configure(self, opts) if opts else None
        self._draw()
        return got

    config = configure


# A button's sizes in CSS pixels by kind, its height, the space before and
# after its words with no cap, the same with a cap, its least width, the gap
# between its words and its cap, and where the cap goes. Industrial draws no
# cap on a button
BUTTONS = {"console": dict(h=40, pad=(26, 26), cap_pad=(10, 16), least=0, gap=10, cap="left"),
           "folio": dict(h=36, pad=(18, 18), cap_pad=(18, 10), least=0, gap=10, cap="right"),
           "industrial": dict(h=34, pad=(20, 20), cap_pad=(20, 20), least=100, gap=0, cap=None)}


def button_colours(look, primary):
    """A button's face, its words, its edge or None for none, and its colour
    pressed. Save and OK are primary."""
    c, kind = look.c, kind_of(look)
    if primary:
        return c["primary"], c["on_primary"], None, tokens.mix(c["primary"], c["on_primary"], 0.15)
    if kind == "folio":
        return c["surface"], c["text"], c["edge"], c["hover"]
    if kind == "industrial":
        return c["head"], c["text"], c["edge"], c["hover"]
    return c["head"], c["text"], None, c["raised"]


# The events after which Tk draws a button again by itself at its next idle
# moment, over the cap inside it: the button come into view, moved or sized
# anew, and the keyboard come or gone, which draws an edged button's ring
# (tkButton.c, ButtonEventProc), and the pointer's coming, going, press and
# release, on which Tk's own bindings for a button configure it (button.tcl,
# tk::ButtonEnter, tk::ButtonLeave, tk::ButtonDown and tk::ButtonUp)
DRAWN_AGAIN = ("<Expose>", "<Configure>", "<FocusIn>", "<FocusOut>", "<Enter>", "<Leave>", "<ButtonPress-1>",
               "<ButtonRelease-1>")


class CapButton(StateButton):
    """A button of a drawn look, Save, Cancel or OK, with its key's cap in it
    where the look draws one, Slate's Esc before Cancel and Folio's Esc after
    Cancel. Save has no cap, since it is pressed by a click and Enter
    switches a switch (plan question 5). The words are the code's, cget
    gives them back, and the look's case draws them, Industrial's in
    capitals. A click on the
    cap presses the button, and the cap's model is the button, see model_of.
    primary draws Save or OK in the look's primary colour, the words in the lit
    weight. A button that cannot be fitted to its cap shows as Tk draws it,
    with no cap, see fault.

    Plan 1.7 marks a button that has the keyboard with a ring in the accent.
    Tk on Windows draws a button's ring only as its default ring, with
    default active and always in its highlightcolor, and marks the keyboard
    with its own dotted rectangle (tkWinButton.c, TkpDisplayButton), so the
    edged buttons draw their edge as that ring and the keyboard shows as on
    today's buttons. The cap is a KeyCap, since a label's ring cannot be
    thicker at its foot.

    Tk draws a button again at its next idle moment after each change made
    through its configure, whatever the change, and after each of
    DRAWN_AGAIN, and draws it over the cap inside it, which does not draw
    itself again then. So the cap is drawn again each time, once the button
    has drawn itself, see _again, as a menu's entry draws the parts inside
    it again, see lens_look.menus.Menu._again.

    sizes gives some of BUTTONS' sizes anew for this button, as a dialog's
    buttons other than its primary one are drawn narrower in Slate."""

    def __init__(self, master=None, look=None, cnf=None, key=None, primary=False, sizes=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        kind = kind_of(look)
        m = self.sizes = dict(BUTTONS[kind], **(sizes or {}))
        self.cap_key = key if m["cap"] else None
        face, ink, edge, pressed = button_colours(look, primary)
        opts.update(relief="flat", overrelief="", bd=0, activebackground=pressed, activeforeground=ink,
                    highlightthickness=1 if edge else 0)
        if edge:
            opts.update(default="active", highlightcolor=edge, highlightbackground=edge)
        self._face_ink = (face, ink)
        StateButton.__init__(self, master, look, opts, font_role="button")
        self.lit_font = bool(primary)
        tk.Misc.configure(self, self._drawn())
        self.cap = None
        self.fault = None
        self.again = False
        self._fit_safely()
        if self.cap is not None:
            self._keep_cap()

    def _fit_safely(self):
        """_fit, or where it fails the button as Tk draws it, its cap taken
        away, see fault."""
        if self.fault is not None:
            return
        try:
            self._fit()
        except Exception as exc:
            self.fault = str(exc) or type(exc).__name__
            try:
                if self.cap is not None:
                    self.cap.place_forget()
                tk.Misc.configure(self, image="", compound="none", width=0, height=0, anchor="center")
            except tk.TclError:
                pass
            fault(self, exc, aside=True)

    def more(self, out):
        """The button's own face and words, whatever colours the code gave it,
        which cget gives back."""
        face, ink = self._face_ink
        if self.ground_colour is None:
            out["bg"] = face
        out["fg"] = ink

    def _fit(self):
        """The button's size and the place of its cap. The edge a button has
        is inside its size, as the drawings' boxes have it, and the words and
        the cap stand in from it."""
        kind, s = kind_of(self.look), self.look.scale_for(self)
        m = self.sizes
        font = real(self, "font")
        words = int(self.tk.call("font", "measure", font, real(self, "text")))
        height = sc.px(m["h"], s)
        edge = self.winfo_pixels(self.cget("highlightthickness"))
        if self.cap_key:
            face, _ink = self._face_ink
            fill, cap_edge, ink = (None, None, None)
            if kind == "console":
                fill = self.look.c["surface"]
            elif kind == "folio" and self.lit_font:
                fill, cap_edge, ink = face, shade(self.look, "cap_on_ink_edge"), shade(self.look, "cap_on_ink_text")
            if self.cap is None:
                self.cap = KeyCap(self, self.look, self.cap_key, "cap_button", ground=face, fill=fill, edge=cap_edge,
                                  ink=ink, model=self)
                self.cap.bind("<ButtonRelease-1>", self._cap_released)
            cap_w, cap_h = self.cap.winfo_reqwidth(), self.cap.winfo_reqheight()
            before, after = sc.px(m["cap_pad"][0], s), sc.px(m["cap_pad"][1], s)
            gap = sc.px(m["gap"], s)
            width = max(sc.px(m["least"], s), 2 * edge + before + cap_w + gap + words + after)
            if m["cap"] == "left":
                exact(self, width, height, padx=after)
                tk.Misc.configure(self, anchor="e")
                self.cap.place(x=edge + before, y=(height - cap_h) // 2, bordermode="ignore")
            else:
                exact(self, width, height, padx=before)
                tk.Misc.configure(self, anchor="w")
                self.cap.place(x=edge + before + words + gap, y=(height - cap_h) // 2, bordermode="ignore")
        else:
            pad = sc.px(m["pad"][0], s) + sc.px(m["pad"][1], s)
            exact(self, max(sc.px(m["least"], s), 2 * edge + words + pad), height)
            tk.Misc.configure(self, anchor="center")

    def _cap_released(self, event):
        if 0 <= event.x < event.widget.winfo_width() and 0 <= event.y < event.widget.winfo_height():
            if str(self.cget("state")) != "disabled":
                self.invoke()

    def _keep_cap(self):
        """The cap drawn again after each change made through configure,
        which the button's followers are told of, and after each of
        DRAWN_AGAIN, see _again."""
        self.follow(lambda widget, keys, lit_changed: self._again())
        for sequence in DRAWN_AGAIN:
            self.bind(sequence, lambda event: self._again(), add="+")

    def _again(self):
        """The cap drawn again, once the button has drawn itself. Asked for
        more than once before then, it is drawn once. The root keeps the
        call, so a button gone before then leaves no call behind that Tk
        could not make."""
        if self.cap is None or self.again:
            return
        self.again = True

        def draw():
            self.again = False
            try:
                if self.cap.winfo_ismapped():
                    self.cap.configure(bg=real(self.cap, "bg"))
            except tk.TclError:
                pass            # the button went before its first idle moment

        try:
            self._root().after_idle(draw)
        except tk.TclError:
            self.again = False

    def configure(self, cnf=None, **kw):
        got = StateButton.configure(self, cnf, **kw)
        opts = cnf if isinstance(cnf, dict) else {}
        if "text" in kw or "text" in opts:
            self._fit_safely()
        return got

    config = configure


class Rule(tk.Frame):
    """A rule one pixel thick at every scale, in a role's colour, the look's
    rule colour unless another is named, across or, with vertical, down."""

    def __init__(self, master, look, role="rule", vertical=False, **kw):
        size = {"width": 1} if vertical else {"height": 1}
        size.update(kw)
        tk.Frame.__init__(self, master, bg=look.c[role], bd=0, highlightthickness=0, **size)


# How far a lit row's bar stands in from the row's top and foot, in CSS
# pixels, by kind. Slate's bar is short of the row, Folio's and Industrial's
# run its whole height
BAR_INSET = {"console": 10, "folio": 0, "industrial": 0}
BAR_WIDTH = 3


class RowBand(tk.Frame):
    """The band behind a row of a drawn look, made before the row's widgets so
    they lie above it, and gridded behind them across the row. Lit, it takes
    the look's lit colour with a bar of the accent colour at its left, and
    gives its members the lit colour as their background. follow makes it
    light and unlight with a State widget, the row's label. A Frame with no
    label, field or button of its own, so a test that groups a page's
    settings by grid row still finds one setting a row."""

    def __init__(self, master, look, ground=None, inset=None, **kw):
        self.look = look
        self.plain = ground or look.c["surface"]
        self.lit_on = False
        self.members = []
        kind = kind_of(look)
        s = look.scale_for(master)
        self.inset = sc.px(BAR_INSET[kind] if inset is None else inset, s)
        tk.Frame.__init__(self, master, bg=self.plain, bd=0, highlightthickness=0, **kw)
        self.bar = tk.Frame(self, bg=look.c["accent"], bd=0, highlightthickness=0, width=sc.px(BAR_WIDTH, s))

    def add(self, *widgets):
        """Widgets of the row, which take the band's colour while it is lit.
        A plain widget gets its own background back after."""
        for widget in widgets:
            plain = None if hasattr(widget, "set_ground") else widget.cget("bg")
            self.members.append((widget, plain))

    def follow(self, widget):
        """Light and unlight the band with a State widget, the row's label, as
        the code lights and unlights it. Its other changes, such as being
        drawn picked, leave the band as it is."""
        widget.follow(lambda w, keys, lit_changed: self.light(w.is_lit) if lit_changed else None)

    def light(self, on):
        on = bool(on)
        if on == self.lit_on:
            return
        self.lit_on = on
        colour = self.look.c["lit"] if on else self.plain
        self.configure(bg=colour)
        if on:
            self.bar.place(x=0, y=self.inset, relheight=1, height=-2 * self.inset, bordermode="ignore")
        else:
            self.bar.place_forget()
        for widget, plain in self.members:
            try:
                if plain is None:
                    widget.set_ground(colour if on else None)
                    if hasattr(widget, "light"):
                        widget.light(on)
                else:
                    widget.configure(bg=colour if on else plain)
            except tk.TclError:
                pass


def field_options(look):
    """The options of a field, a tk.Entry, in a drawn look, a well with the
    look's text and selection, and a line in the accent colour while it has
    the keyboard."""
    c = look.c
    return dict(bg=c["well"], fg=c["text"], insertbackground=c["text"], selectbackground=c["lit"],
                selectforeground=c["strong"], relief="flat", bd=0, highlightthickness=1,
                highlightbackground=c["edge"], highlightcolor=c["accent"], font=look.font("line"))


def list_options(look):
    """The options of a list, the profile list's tk.Listbox, in a drawn look.
    Industrial draws the profiles' names in its mono type."""
    c = look.c
    return dict(bg=c["well"], fg=c["text"], selectbackground=c["lit"], selectforeground=c["strong"],
                activestyle="none", relief="flat", bd=0, highlightthickness=1, highlightbackground=c["edge"],
                highlightcolor=c["accent"], font=look.font("menu_profile"))


def button_options(look, primary=False):
    """The options of a plain tk.Button in a drawn look, such as Browse, with
    the look's faces and its colour pressed. A button with an edge draws it
    with -default active, as Tk on Windows draws a button's ring then alone."""
    face, ink, edge, pressed = button_colours(look, primary)
    out = dict(bg=face, fg=ink, activebackground=pressed, activeforeground=ink, relief="flat", bd=0,
               highlightthickness=1 if edge else 0, font=look.font("button", primary))
    if edge:
        out.update(default="active", highlightcolor=edge, highlightbackground=edge)
    return out
