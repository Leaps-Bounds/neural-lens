"""The NR settings panel in a drawn look: its head, its rows in the order of
the look's drawing, the tabs of the passes over the card of the pass shown,
the part that explains the row the keys or the pointer pick, and the footer
with the keys that work the panel, as Slate-Panel, Paper-Panel and
Industrial-Panel draw them.

The lens makes the panel's controls here row by row, in place of today's,
see Lens._open_panel_drawn, with the same words, variables, commands and
panel_ui keys. Each row's label is a State widget, see lens_look.widgets,
so the lens lights a row by its accent colour as it always did, see
Lens.panel_light, and the row's band, bar and weight follow. A switch's
label is its check button with the switch drawn beside it, a slider is a
LookScale with its face, and the pass count, the ties and the reset buttons
are the lens's own labels and check buttons drawn in the look's faces, see
lens_look.faces. So the lens's code and the tests read what they read in the
classic look.

Once the rows are made, finish lays them out in the look's order, the order
lens_look.walk gives the arrow keys, makes the explanation's part and the
key footer, and fits the panel to its monitor at the level
lens_look.fit.panel_fit picks from the panel's own heights. Level 0 is the
drawing, 1 has compact rows, 2 also has the profile row in the head, and 3
also has the pass card scroll to keep the lit row in view. The explanation's
part keeps its drawn height at every level, and a text that needs more grows
it by a line or two, see Region.

The explanation shows the row the arrow keys light, see lit, and the pointer
picks the row it moves onto, as F1 picks the one under it, see picked. The
panel is a window of the lens's own that never takes the keyboard, so
nothing here gives anything the keyboard or binds a key.

Imports tkinter and the package, and nothing of the lens.
"""
import tkinter as tk

from lens_look import faces, fit, settings, text, tokens, walk, widgets
from lens_look import scale as sc

# The value sliders, NR_SLIDERS' keys in neural_lens.py, each a row of its own
SLIDERS = walk.SLIDERS

# The panel's sizes in CSS pixels at 100 percent, from the drawings, by kind.
#   width       the panel's width with its border of 1 pixel
#   head        the head's height, title_in the room before the title,
#               head_gap the room before the words that say what closes the
#               panel, cross the close button's width and height, info_gap the
#               room before it of Industrial's i
#   band_pad    the room between a part's side and its rows' bands, and
#               card_pad that round Industrial's card
#   part_pad    the room above and under each part's rows
#   left, right the room before a row's first words, taking in the 3 pixel
#               bar a lit row has, and after its last control, and card_left
#               and card_right those of the card's rows where they differ
#   label       the width of the label column, 0 where each label takes its
#               own, and card_label the card's where it differs
#   gap         the room between a label and its control and between controls
#   tie         the width of the column of the ties
#   indent      how far the strength's label, and Slate's skin row, stand in
#   number      the width of a slider's number, number_gap the room before it
#               and reset_gap the room before the reset button
#   tab_pad, tab_gap, tab_line      the room beside a tab's words, between two
#               tabs and the line under the chosen one, and Industrial's tab,
#               tab_chosen and tab_top, the plates and the lines along their tops
#   picker      the profile picker's width and height, arrow Slate's arrows' width
#   button_gap  the room between the picker and its buttons
#   rows        each row's height, by its name, the value sliders' as slider
#   explain     the explanation's height as drawn, at every level, and
#               explain_pad the room round its words, see explain_room,
#               explain_top the room above it, context_gap, text_gap and
#               extra_gap the room before each of its lines
#   footer      the key footer's height, footer_pad its room at each side,
#               group_gap, cap_gap and words_gap the room between its groups,
#               between two caps and before the words, hints its words' size
PANEL = {
    "console": dict(width=624, head=41, title_in=16, head_gap=12, cross=(44, 40), info_gap=0, band_pad=12,
                    card_pad=0, part_pad={"top": (8, 2), "tabs": (4, 0), "card": (6, 8)}, left=14, right=10,
                    card_left=14, card_right=10, label=0, card_label=0, gap=12, tie=104, indent=30, number=44,
                    number_gap=10, reset_gap=4, tab_pad=12, tab_gap=2, tab_line=2, picker=(184, 34), arrow=30,
                    button_gap=10, own=(4, 6), own_w=380,
                    rows=dict(profile=52, auto=38, free=38, nr=38, quality=44, passes=46, scale_change=38, strength=38, tabs=40,
                              shared=38, style=38, slider=38, skin_auto=32, mask=38),
                    explain=112, explain_pad=(10, 16, 12), explain_top=0, context_gap=10, text_gap=4,
                    extra_gap=6, footer=42, footer_pad=(16, 16), group_gap=18, cap_gap=4, words_gap=5, hints=13),
    "folio": dict(width=664, head=42, title_in=20, head_gap=14, cross=(42, 41), info_gap=0, band_pad=0, card_pad=0,
                  part_pad={"top": (0, 0), "mid": (8, 0), "tabs": (8, 0), "card": (0, 0)}, left=24, right=24,
                  card_left=24, card_right=24, label=212, card_label=212, gap=12, tie=64, indent=16, number=40,
                  number_gap=8, reset_gap=4, tab_pad=2, tab_gap=20, tab_line=2, picker=(152, 30), arrow=0,
                  button_gap=8, intro=32, intro_pad=(10, 24, 4), own_pad=(6, 24),
                  rows=dict(profile=62, auto=50, free=36, nr=36, passes=36, scale_change=36, strength=36, quality=52, tabs=40,
                            shared=36, style=38, slider=36, skin_auto=28, mask=36, own=28),
                  explain=117, explain_pad=(12, 24, 10), explain_top=6, bar=2, bar_gap=12, text_gap=4,
                  extra_gap=2, footer=40, footer_pad=(24, 24), group_gap=24, cap_gap=4, words_gap=5, hints=13),
    "industrial": dict(width=680, head=40, title_in=18, head_gap=14, cross=(46, 39), info_gap=6, band_pad=20,
                       card_pad=20, part_pad={"top": (4, 0), "tabs": (0, 0), "card": (0, 0), "bottom": (0, 0)},
                       left=14, right=0, card_left=13, card_right=12, label=136, card_label=128, gap=12, tie=108,
                       indent=16, number=44, number_gap=12, reset_gap=12, tab=(100, 32), tab_chosen=(100, 37),
                       tab_top=(2, 3), tab_gap=3, picker=(196, 34), arrow=0, button_gap=8, own_pad=(6, 13),
                       rows=dict(profile=50, auto=44, free=44, nr=44, tabs=46, shared=48, tie_head=24, style=40, slider=40,
                                 skin_auto=38, mask=38, own=28, passes=50, scale_change=44, strength=40, quality=56),
                       explain=136, explain_pad=(16, 24, 23), explain_top=0, bar=3, context_gap=0,
                       text_gap=7, extra_gap=4, footer=40, footer_pad=(23, 18), group_gap=24, cap_gap=3,
                       words_gap=8, hints=13.5),
}

# The parts of the panel top to bottom and the rows in each, in the order of
# the look's drawing, which is the order the arrow keys walk, see
# lens_look.walk.ORDER. own is the line under the ties' column header that
# says what a tie does, and tie_head Industrial's row of that header.
LAYOUT = {
    "console": (("top", ("profile", "auto", "free", "nr", "quality", "passes", "scale_change", "strength")),
                ("tabs", ("tabs",)),
                ("card", ("shared", "own", "style") + SLIDERS + ("skin_auto", "mask"))),
    "folio": (("top", ("profile", "auto", "free")),
              ("mid", ("nr", "passes", "scale_change", "strength", "quality")),
              ("tabs", ("tabs",)),
              ("card", ("shared", "style") + SLIDERS + ("skin_auto", "mask", "own"))),
    "industrial": (("top", ("profile", "auto", "free", "nr")),
                   ("tabs", ("tabs",)),
                   ("card", ("shared", "tie_head", "style") + SLIDERS + ("skin_auto", "mask", "own")),
                   ("bottom", ("passes", "scale_change", "strength", "quality"))),
}

# The rows whose controls set the pass shown, whose explanation names that pass
PER_PASS = ("style", "shared", "skin_auto", "mask") + SLIDERS

# The panel_ui key of each switch the lens makes, by its row's name
SWITCHES = {"auto": "auto_box", "free": "free_box", "nr": "nr_box", "skin_auto": "skin_box", "mask": "mask_box",
            "scale_change": "scale_box"}

# The colours the panel's labels draw for the logical colours the code gives
# them, by the option and the key of the ten colours. A row's label is lit in
# the strong colour, as the drawings light it, and the words beside a setting
# and the numbers are muted where the code dims them
LABEL = widgets.LABEL_ROLES
BESIDE = {"fg": {"dim": "muted", "fg": "text", "accent": "strong", "warn": "warn"}}
NUMBER = {"fg": {"fg": "text", "dim": "muted", "accent": "strong"}}
# The tabs' words, the chosen one strong and lit, the others muted, and the
# words before them, muted until the keys light them
TAB = {"fg": {"accent": "strong", "fg": "muted"}}
TABS_WORD = {"fg": {"accent": "strong", "fg": "muted"}, "disabledforeground": {"accent": "muted", "dim": "muted"}}
# The profile's name in the picker, strong while the lens matches the profile,
# in the warning colour once it differs and muted with none in use, on the well
# or, under the pointer, the lit colour
PICKER = {"fg": {"accent": "strong", "warn": "warn", "dim": "muted", "fg": "text"},
          "bg": {"field": "well", "hover": "lit", "bg": "well"}}

# The chevron the code's picker text starts with, which the drawn picker draws
# apart from the name
CHEVRON = "\u25be "

# The least height in CSS pixels the pass card keeps where it scrolls
CARD_LEAST = 80


def explain_room(kind, s, height):
    """The height in screen pixels the explanation's lines have in a part
    height pixels high at the scale s: the part's height less the room above
    its lines and, in Slate and Paper, the room under them, as the drawings pad
    the part. explain_pad is (top, sides, foot) in those two, and (top, right,
    left) in Industrial, whose drawing has no room under the lines."""
    pad = PANEL[kind]["explain_pad"]
    foot = 0 if kind == "industrial" else pad[2]
    return height - sc.px(pad[0], s) - sc.px(foot, s)


def key_words(line):
    """A line that names keys, such as "F8 or Escape closes it", as its parts
    in order, each ("key", a key) or ("words", the words between), which
    join back to the line with a space between each two, see join_key_words."""
    parts = []
    for word in str(line).split(" "):
        if text.is_key(word):
            parts.append(("key", word))
        elif parts and parts[-1][0] == "words":
            parts[-1] = ("words", parts[-1][1] + " " + word)
        else:
            parts.append(("words", word))
    return parts


def join_key_words(parts):
    """The line key_words split."""
    return " ".join(words for _kind, words in parts)


def switch_words(label):
    """A switch's label as a drawn look shows it beside its switch, and the
    keys in the brackets at its end, which show as caps. The NR switch's
    "Neural Rendering on   (F9)" shows as "Neural Rendering" with the cap F9,
    since the switch itself shows On or Off. Any other label shows as it is."""
    mt = text.split_menu_text(label)
    words = mt.words[:-3] if mt.words.endswith(" on") else mt.words
    return words, mt.keys


def picker_words(label):
    """The profile picker's text without the chevron the code puts first,
    which the drawn picker draws apart, or as an arrow either side."""
    label = str(label)
    return label[len(CHEVRON):] if label.startswith(CHEVRON) else label


def sentences(words):
    """The first sentence of a text and the rest, as Paper's line under the
    head shows the first and its explanation the rest."""
    words = str(words or "")
    at = words.find(". ")
    if at < 0:
        return words, ""
    return words[:at + 1], words[at + 2:]


def content(title="", why="", context="", extra=""):
    """What the explanation shows: the row's title, the pass it is of where
    it sets the pass shown, its explanation and a line under it."""
    return {"title": title, "context": context, "text": why, "extra": extra}


def heights_of(kind, name):
    """A row's height in CSS pixels at the drawing, by its name."""
    rows = PANEL[kind]["rows"]
    return rows.get("slider" if name in SLIDERS else name, 0)


class Row(object):
    """A row of the panel: its name, the part it lies in, its band, the
    labels that light the band, its height at the drawing, and the cell of
    the tie column where it has one."""

    def __init__(self, name, part, band, height):
        self.name, self.part, self.band, self.height = name, part, band, height
        self.labels = []
        self.tie = None


class CheckFace(faces.Face):
    """Paper's box before the words of Leave skin structure to the model,
    which Paper-Panel draws as a check box and not as a switch, for the code's
    check button, the row's label beside it. It draws the box a tie has, see
    lens_look.faces.tie_items, and a click on it goes to the button's
    invoke()."""

    LIT_FROM_MODEL = True

    def __init__(self, master, look, model, ground=None):
        self.model = model
        faces.Face.__init__(self, master, look, ground)
        self.watch(str(model.cget("variable")))
        self.follow(widgets.observe(model))
        self.is_lit = bool(getattr(model, "is_lit", False))
        self.redraw_now()

    def enabled(self):
        return str(self.model.cget("state")) != "disabled"

    def state(self):
        return {"ticked": faces.selected(self.model), "greyed": not self.enabled()}

    def layout(self, ctx):
        box = ctx.px(faces.TIE[ctx.kind]["box"])
        st = self.state()
        return faces.tie_items(ctx, box, box, st["ticked"], st["greyed"], self.is_lit, self.ground())

    def act(self, action, x):
        self.model.invoke()


class Region(settings._Region):
    """The part of the panel that explains the row picked, as each drawing
    has it. Slate's lies under the rows on the deep colour, its title with the
    pass beside it, its explanation and the line under it. Paper's is a note
    with a bar of the accent colour, above the key line. Industrial's is the
    strip along the foot, the pass in capitals over the title. While no row
    is picked it shows the panel's own line. It has its drawn height at every
    level, and a text that needs more grows it by the lines it needs, a line
    or two and no more than the panel has left on its monitor, see fit_lines.
    No text is ever cut short or ends in three dots, and a check refuses
    before it ships a text that would need more. A fault leaves it blank, see
    lens_look.settings._Region."""

    def __init__(self, master, look, width, height):
        self.kind = widgets.kind_of(look)
        self.GROUND = "surface" if self.kind == "folio" else "deep"
        settings._Region.__init__(self, master, look, width, height)
        self.m = PANEL[self.kind]
        self.said = set()               # the texts lens.log was told did not fit, each once, see show
        c = look.c
        widgets.Rule(self, look, role="edge" if self.kind == "industrial" else "rule").place(x=0, y=0, relwidth=1.0)
        if self.kind == "industrial":
            tk.Frame(self, bg=c["accent"], width=self.px(self.m["bar"]), bd=0, highlightthickness=0).place(
                x=0, y=1, relheight=1.0, height=-1)

    def font(self, role, lit=False, size=None):
        family, _size, weight = self.look.font(role, lit, self)
        face = self.look.fonts[role]
        return (family, -self.px(face.size if size is None else size), weight)

    def line(self, master, words, font, colour, wrap, case=None):
        return tk.Label(master, text=text.display_case(words, case), bg=self.look.c[self.GROUND], fg=colour, font=font,
                        justify="left", anchor="w", wraplength=max(1, int(wrap)), bd=0, padx=0, pady=0)

    def show(self, what):
        c, m, kind = self.look.c, self.m, self.kind
        width = self.size[0]
        ground = c[self.GROUND]
        if kind == "industrial":
            top, right, left = (self.px(v) for v in m["explain_pad"])
        else:
            top, side, _foot = (self.px(v) for v in m["explain_pad"])
            left = right = side
        inner = max(1, width - left - right)
        holder = tk.Frame(self, bg=ground, bd=0, highlightthickness=0)
        self.parts.append(holder)
        body = holder
        if kind == "folio":
            tk.Frame(holder, bg=c["accent"], width=self.px(m["bar"]), bd=0, highlightthickness=0).pack(side="left",
                                                                                                   fill="y")
            body = tk.Frame(holder, bg=ground, bd=0, highlightthickness=0)
            body.pack(side="left", fill="both", expand=True, padx=(self.px(m["bar_gap"]), 0))
            inner -= self.px(m["bar"]) + self.px(m["bar_gap"])
        # the lines top to bottom, each (widget, the room above it), see
        # fit_lines
        lines = []
        first = True
        if kind == "industrial":
            if what["context"]:
                w = self.line(body, what["context"], self.font("explain_section", size=11), c["muted"], inner,
                              "upper")
                w.pack(anchor="w")
                lines.append((w, 0))
                first = False
            if what["title"]:
                above = 0 if first else self.px(5)
                w = self.line(body, what["title"], self.font("explain_title", size=18), c["text"], inner)
                w.pack(anchor="w", pady=(above, 0))
                lines.append((w, above))
                first = False
        elif what["title"]:
            row = tk.Frame(body, bg=ground, bd=0, highlightthickness=0)
            row.pack(anchor="w")
            if kind == "folio":
                tk.Label(row, text=what["title"], bg=ground, fg=c["text"], font=self.font("panel_title", size=17),
                         bd=0, padx=0, pady=0).pack(side="left")
            else:
                tk.Label(row, text=what["title"], bg=ground, fg=c["strong"], font=self.font("panel_title"), bd=0,
                         padx=0, pady=0).pack(side="left", anchor="s")
                if what["context"]:
                    tk.Label(row, text=what["context"], bg=ground, fg=c["muted"], font=self.font("panel_words"),
                             bd=0, padx=0, pady=0).pack(side="left", anchor="s", padx=(self.px(m["context_gap"]), 0))
            lines.append((row, 0))
            first = False
        role, size = {"console": ("explain_option_text", None), "folio": ("explain_text", None),
                      "industrial": ("line", None)}[kind]
        font = self.font(role, size=size)
        if what["text"]:
            above = 0 if first else self.px(m["text_gap"])
            w = self.line(body, what["text"], font, c["text"], inner)
            w.pack(anchor="w", pady=(above, 0))
            lines.append((w, above))
        if what["extra"]:
            role, size = {"console": ("panel_words", None), "folio": ("version", None),
                          "industrial": ("panel_words", None)}[kind]
            above = self.px(m["extra_gap"])
            w = self.line(body, what["extra"], self.font(role, size=size), c["muted"], inner)
            w.pack(anchor="w", pady=(above, 0))
            lines.append((w, above))
        holder.place(x=left, y=top, width=max(1, width - left - right))
        if self.fit_lines(lines, self.linespace(font)) and what["text"] not in self.said:
            self.said.add(what["text"])
            try:
                print("the NR settings panel's explanation of %s needs more room than its part has, so its last "
                      "lines are left out" % (what["title"] or "the panel"), flush=True)
            except Exception:
                pass            # an output that cannot take the words must not blank the part

    def fit_lines(self, lines, line):
        """The part as tall as its lines need, its drawn height where they fit
        and else taller by what lens_look.fit.grown gives, at most a line or
        two of line pixels and no more than the panel has left on its monitor,
        see Panel.spare, and of the lines only those that then fit whole, see
        whole_lines. resized hears of each change of the part's height.
        Returns how many lines were left out, none for a text a check let
        ship."""
        was = self.size[1]
        need = sum(above + self.tall(widget) for widget, above in lines)
        room = self.grow_to(need, explain_room(self.kind, self.s, self.base), line)
        shown = self.whole_lines(lines, room)
        if self.size[1] != was and self.resized is not None:
            self.resized(self.size[1] - self.base)
        return len(lines) - shown

    def whole_lines(self, lines, room):
        """Only whole lines in the part: the first line its foot would cut,
        and every line under it, left out, none cut short and none ending in
        three dots. lines are what show reads, room the height under the
        part's top padding. A label's height is its lines' as Tk lays them out
        at its wrap, which Tk works out as the words are set, so the window
        need not be shown. Returns how many lines show."""
        y = 0
        for at, (widget, above) in enumerate(lines):
            y += above + self.tall(widget)
            if y > room:
                for later in lines[at:]:
                    later[0].pack_forget()
                return at
        return len(lines)

    @staticmethod
    def tall(widget):
        """A line's height, a label's or that of the row the title and the
        pass lie in."""
        return max([widget.winfo_reqheight()] + [w.winfo_reqheight() for w in widget.winfo_children()])


class KeyFooter(tk.Frame):
    """The panel's key footer, the keys that work it with their words, each
    key a cap, see lens_look.widgets.KeyCap, and a word between two caps,
    such as or, in the words' type. keys are ((key, ...), words) pairs in
    their order. Where the panel is too narrow for them all the last ones are
    left out rather than cut."""

    def __init__(self, master, look, width, height, keys):
        kind = widgets.kind_of(look)
        c, m = look.c, PANEL[kind]
        s = look.scale_for(master)
        self.look = look
        self.ground = {"console": c["deep"], "folio": c["surface"]}.get(kind) or widgets.shade(look, "band")
        tk.Frame.__init__(self, master, bg=self.ground, width=width, height=height, bd=0, highlightthickness=0)
        self.pack_propagate(False)
        widgets.Rule(self, look).place(x=0, y=0, relwidth=1.0)
        family, _size, weight = look.font("hints", False, master)
        font = (family, -sc.px(m["hints"], s), weight)
        case = look.fonts["hints"].case
        left, right = (sc.px(v, s) for v in m["footer_pad"])
        self.groups = []
        row = tk.Frame(self, bg=self.ground, bd=0, highlightthickness=0)
        for caps, words in keys:
            group = tk.Frame(row, bg=self.ground, bd=0, highlightthickness=0)
            for j, key in enumerate(caps):
                if key in widgets.ARROWS or text.is_key(key):
                    part = widgets.KeyCap(group, look, key, "cap_panel", ground=self.ground)
                else:
                    part = tk.Label(group, text=text.display_case(key, case), bg=self.ground, fg=c["muted"], font=font,
                                    bd=0, padx=0, pady=0)
                part.pack(side="left", padx=(sc.px(m["cap_gap"], s) if j else 0, 0))
            tk.Label(group, text=text.display_case(words, case), bg=self.ground, fg=c["muted"], font=font, bd=0,
                     padx=0, pady=0).pack(side="left", padx=(sc.px(m["words_gap"], s), 0))
            group.pack(side="left", padx=(sc.px(m["group_gap"], s) if self.groups else 0, 0))
            self.groups.append(group)
        row.pack(side="left", padx=(left, 0))
        row.update_idletasks()
        room = width - left - right
        while self.groups and row.winfo_reqwidth() > room:
            self.groups.pop().destroy()
            row.update_idletasks()


class Panel(object):
    """The NR settings panel of a drawn look in the lens's own window t, which
    the lens made, as the module's docstring says. ui is the lens's panel_ui,
    which the rows fill, and hints the panel's Hints, which the rows give
    their explanations and which finish puts in its pane mode. monitor_h is
    the height of the monitor the panel opens on, rows a call that gives the
    lens's panel_rows, the rows of the arrow keys, and light the lens's
    panel_light, which lights one of them. The rows are made in the order the
    lens makes them, and laid out in the look's by finish."""

    def __init__(self, window, look, ui, hints, monitor_h, rows=None, light=None):
        self.t, self.look, self.ui, self.hints = window, look, ui, hints
        self.kind = widgets.kind_of(look)
        self.c, self.lg = look.c, look.legacy
        self.m = PANEL[self.kind]
        self.s = look.scale_for(window)
        self.monitor_h = int(monitor_h)
        self.rows_of = rows or (lambda: [])
        self.light_row = light
        self.rows = {}
        self.titles, self.lit_of, self.band_of = {}, {}, {}
        self.per_pass, self.sliders = set(), set()
        self.pass_shown, self.level, self.offset = 1, 0, 0
        self.idle = content()
        self.reset_line, self.context = "", "Pass %d"
        self.rest = None                # where the pointer was when it first came, see picked
        # where the pointer was when an arrow key last picked a row, see keyed:
        # until it has moved a few pixels from there it picks nothing itself
        self.key_at = None
        self.held = lambda: False       # the lens's reading of a held mouse, see Lens._watch_mouse
        # the lens's _panel_fit, which gives the window the size its contents
        # ask for, kept on its monitor, once the explanation's part has grown
        # for a text or come back to its drawn height, see Region.fit_lines
        self.fitted = None
        self.region = self.footer = self.intro = self.info = self.header = None
        self.head_frame = self.hint = self.extra = None
        self.profile_parts = None
        self.heights = []
        self.card_pack = {}
        window.configure(bg=self.c["frame"])
        self.box = tk.Frame(window, bg=self.c["surface"], bd=0, highlightthickness=0)
        self.box.pack(padx=1, pady=1)
        self.inner = sc.px(self.m["width"], self.s) - 2
        self.box.columnconfigure(0, minsize=self.inner)
        # the parts, made before the rows so the rows lie above them. The card
        # lies in a frame of its own, which clips it where it scrolls
        self.parts = {}
        self.clip = self.card = None
        for name, _rows in LAYOUT[self.kind]:
            if name == "card":
                self.clip = tk.Frame(self.box, bg=self.c["surface"], bd=0, highlightthickness=0)
                edge = sc.border(1, self.s) if self.kind == "industrial" else 0
                self.card = tk.Frame(self.clip, bg=self.c["surface"], bd=0, highlightthickness=edge,
                                     highlightbackground=self.c["edge"], highlightcolor=self.c["edge"])
                part = self.card
            else:
                part = tk.Frame(self.box, bg=self.c["surface"], bd=0, highlightthickness=0)
            part.columnconfigure(0, weight=1)
            self.parts[name] = part

    # sizes and type

    def px(self, n):
        return sc.px(n, self.s)

    def font(self, role, lit=False, size=None):
        """A role's font at the look's scale, at another size where one is given."""
        family, _size, weight = self.look.font(role, lit, self.t)
        face = self.look.fonts[role]
        return (family, -self.px(face.size if size is None else size), weight)

    def part_of(self, name):
        for part, names in LAYOUT[self.kind]:
            if name in names:
                return part
        raise KeyError(name)

    def card_row(self, row):
        return row.part == "card"

    # the widgets of the rows

    def label(self, master, words, role="panel_row", lit=True, roles=None, **kw):
        """A row's label, a State label the code lights by its accent colour,
        or with lit False words the code never lights. Paper's labels break
        onto a second line where its label column ends, see wrap."""
        lg = self.lg
        opts = dict(text=words, bg=lg["bg"], fg=lg["fg"], bd=0, padx=0, pady=0, anchor="w", justify="left")
        if lit:
            opts.update(self.wrap())
        opts.update(kw)
        return widgets.StateLabel(master, self.look, opts, roles=roles or LABEL, lit=("fg", "accent") if lit else None,
                                  font_role=role)

    def words(self, master, words, role="panel_words", **kw):
        """A few words beside a setting, muted as the code dims them."""
        return self.label(master, words, role, lit=False, roles=BESIDE, fg=self.lg["dim"], **kw)

    def number(self, master):
        """A slider's number, right-aligned in its column."""
        n = self.label(master, "", "value", lit=False, roles=NUMBER, anchor="e")
        widgets.exact(n, self.px(self.m["number"]), self.px(22))
        return n

    def check(self, master, words, var, command, role="panel_row", **kw):
        """A switch's label, the check button the code makes, see
        lens_look.faces.LookCheckbutton."""
        lg = self.lg
        opts = self.wrap()
        opts.update(kw)
        return faces.LookCheckbutton(master, self.look, text=words, variable=var, command=command, bg=lg["bg"],
                                     fg=lg["fg"], selectcolor=lg["field"], activebackground=lg["bg"],
                                     activeforeground=lg["fg"], disabledforeground=lg["dim"], justify="left",
                                     font_role=role, **opts)

    def wrap(self):
        """Where Paper's labels break onto a second line, the width of its
        label column, as Paper-Panel breaks Load the profile tied to the
        program in front. The other looks' labels take their own width."""
        if self.kind != "folio":
            return {}
        return {"wraplength": self.px(self.m["label"])}

    def frame(self, master, **kw):
        opts = dict(bg=self.c["surface"], bd=0, highlightthickness=0)
        opts.update(kw)
        return tk.Frame(master, **opts)

    def row(self, name):
        """A row's band in its part, its height kept to the row's, see level."""
        part = self.part_of(name)
        band = widgets.RowBand(self.parts[part], self.look)
        band.grid_propagate(False)
        row = Row(name, part, band, heights_of(self.kind, name))
        self.rows[name] = row
        return row

    def explained(self, row, lit, why, title, *more):
        """Give the widgets of a row their explanation and their row, whose
        label is lit, and give the label the row's title. The pointer on any
        of them picks the row, see picked."""
        self.titles[lit] = title
        for w in (lit,) + more:
            if w is None:
                continue
            self.hints.add(w, why)
            self.lit_of[w] = lit
        if row.name in PER_PASS:
            self.per_pass.add(lit)
        self.light_with(row, lit)

    def light_with(self, row, label):
        """The row's band lit while any of its labels is, the value's own or
        its tie's."""
        row.labels.append(label)
        self.band_of[label] = row.band

        def follow(widget, keys, changed):
            if changed:
                row.band.light(any(getattr(w, "is_lit", False) for w in row.labels))
        label.follow(follow)

    def lay(self, row, first, left=(), right=(), tie=False, label=None, start=None):
        """A row's widgets on its band: first at the left, after the room
        before a row's words, or at start where given, then the widgets of
        left, each (widget, the room before it in CSS pixels), the first of
        them after the label column where the look has one and label is not
        False, then a column that takes what room is left, the widgets of
        right, and the tie column where tie is set, then the room after."""
        m, band = self.m, row.band
        card = self.card_row(row)
        pad_left = m["card_left"] if card else m["left"]
        pad_right = m["card_right"] if card else m["right"]
        label_w = (m["card_label"] if card else m["label"]) if label is not False else 0
        x0 = self.px(pad_left if start is None else start)
        col = 0
        if first is not None:
            first.grid(in_=band, row=0, column=0, sticky="w", padx=(x0, 0))
            if label_w:
                band.columnconfigure(0, minsize=x0 + self.px(label_w) + self.px(m["gap"]))
            col = 1
        for i, (w, gap) in enumerate(left):
            w.grid(in_=band, row=0, column=col, sticky="w",
                   padx=(self.px(gap) if (i or not label_w or first is None) else 0, 0))
            col += 1
        band.columnconfigure(col, weight=1)
        col += 1
        for w, gap in right:
            w.grid(in_=band, row=0, column=col, sticky="e", padx=(self.px(gap), 0))
            col += 1
        if tie:
            height = self.px(row.height or 30)
            cell = row.tie = tk.Frame(band, bg=self.c["surface"], bd=0, highlightthickness=0, width=self.px(m["tie"]),
                                      height=height)
            cell.grid_propagate(False)
            cell.columnconfigure(0, weight=1)
            cell.rowconfigure(0, weight=1)
            cell.grid(in_=band, row=0, column=col, sticky="ns")
            band.add(cell)
            col += 1
        band.columnconfigure(col, minsize=self.px(pad_right))
        band.rowconfigure(0, weight=1)

    # the rows the lens makes, in the order it makes them

    def head(self, title, line, close, drag, glyph, glyph_font):
        """The head the panel is dragged by: its title, the line that says
        what closes it, drawn with caps in Paper and Industrial, Industrial's
        i, and the cross, which close is called for. drag is the lens's
        (press, move, release) for a drag. glyph and glyph_font are the
        cross's, as the lens's title bar draws it."""
        c, m = self.c, self.m
        ground = c["deep"]
        head = self.head_frame = self.frame(self.box, bg=ground, height=self.px(m["head"]))
        head.grid_propagate(False)
        head.rowconfigure(0, weight=1)
        widgets.Rule(head, self.look, role="edge" if self.kind == "industrial" else "rule").place(
            x=0, rely=1.0, y=-1, relwidth=1.0)
        face = self.look.fonts["panel_title"]
        name = tk.Label(head, text=text.display_case(title, face.case), bg=ground,
                        fg=c["strong"] if self.kind == "console" else c["text"], font=self.font("panel_title"), bd=0,
                        padx=0, pady=0)
        name.grid(row=0, column=0, sticky="w", padx=(self.px(m["title_in"]), 0))
        if self.kind == "console":
            hint = tk.Label(head, text=line, bg=ground, fg=c["muted"], font=self.font("panel_words"), bd=0, padx=0,
                            pady=0)
            dragged = [hint]
        else:
            hint = self.frame(head, bg=ground)
            dragged = [hint]
            for i, (kind, part) in enumerate(key_words(line)):
                if kind == "key":
                    w = widgets.KeyCap(hint, self.look, part, "cap_menu", ground=ground)
                else:
                    w = tk.Label(hint, text=part, bg=ground, fg=c["muted"], font=self.font("panel_words"), bd=0,
                                 padx=0, pady=0)
                w.pack(side="left", padx=(self.px(5) if i else 0, 0))
                dragged.append(w)
        hint.grid(row=0, column=1, sticky="w", padx=(self.px(m["head_gap"]), 0))
        self.hint = hint
        # the profile row's place at the compact level that folds it into the head
        self.extra = self.frame(head, bg=ground)
        self.extra.grid(row=0, column=2, sticky="w", padx=(self.px(m["head_gap"]), 0))
        self.extra.grid_remove()
        head.columnconfigure(3, weight=1)
        if self.kind == "industrial":
            self.info = settings.InfoMark(head, self.look)
            self.info.configure(bg=ground)
            self.info.grid(row=0, column=4, padx=(self.px(m["info_gap"]), 0))
        cross = tk.Label(head, text=glyph, font=glyph_font, bg=ground,
                         fg=c["muted"] if self.kind == "folio" else c["text"], bd=0, padx=0, pady=0)
        widgets.exact(cross, self.px(m["cross"][0]), self.px(m["cross"][1]))
        cross.grid(row=0, column=5, sticky="e")
        cross.bind("<Button-1>", lambda e: close())
        cross.bind("<Enter>", lambda e: cross.configure(bg=c["close"]))
        cross.bind("<Leave>", lambda e: cross.configure(bg=ground))
        down, move, up = drag
        for w in [head, name] + dragged:
            w.bind("<ButtonPress-1>", down)
            w.bind("<B1-Motion>", move)
            w.bind("<ButtonRelease-1>", up)
        return head

    def profile(self, words, name_text, colour, open_list, step, update, save_as, why):
        """The profile row: its label with the program the profile in use is
        tied to under it, ui's program, the picker, ui's profile, which open_list
        is called for, Slate's arrows either side of it, which call step with
        -1 or 1, and the Update and Save as buttons, each (words, command,
        explanation). Update is greyed while no profile is in use, which the
        picker's dim colour says. Its widgets lie in the panel's body, so the
        compact level can fold them into the head, see fold."""
        c, lg, m, box = self.c, self.lg, self.m, self.box
        row = self.row("profile")
        # the frames they lie in, made before them so they lie above them
        holders = {"words": self.frame(box), "controls": self.frame(box), "buttons": self.frame(box)}
        word = self.label(box, words)
        program = self.words(box, "")
        w, h = (self.px(v) for v in m["picker"])
        if self.kind == "console":
            picker = self.frame(box, bg=c["well"], width=w, height=h)
            picker.grid_propagate(False)
            picker.columnconfigure(1, weight=1)
            picker.rowconfigure(0, weight=1)
            arrows = []
            for col, (glyph, d) in ((0, ("left", -1)), (2, ("right", 1))):
                font, char = widgets.glyph(picker, glyph, self.px(12))
                a = tk.Label(picker, text=char, font=font, bg=c["well"], fg=c["text"], bd=0, padx=0, pady=0)
                widgets.exact(a, self.px(m["arrow"]), h)
                a.grid(row=0, column=col, sticky="ns")
                a.bind("<Button-1>", lambda e, d=d: step(d))
                arrows.append(a)
            name = widgets.StateLabel(picker, self.look, text=name_text, bg=lg["field"], fg=colour, bd=0, padx=0,
                                      pady=0, anchor="center", roles=PICKER, shown=picker_words,
                                      font_role="panel_profile")
            name.grid(row=0, column=1, sticky="nsew")
            parts = [picker, name] + arrows
        else:
            picker = self.frame(box, bg=c["well"], width=w, height=h, highlightthickness=sc.border(1, self.s),
                                highlightbackground=c["edge"], highlightcolor=c["edge"])
            picker.grid_propagate(False)
            picker.columnconfigure(0, weight=1)
            picker.rowconfigure(0, weight=1)
            name = widgets.StateLabel(picker, self.look, text=name_text, bg=lg["field"], fg=colour, bd=0, padx=0,
                                      pady=0, anchor="w", roles=PICKER, shown=picker_words, font_role="panel_profile")
            name.grid(row=0, column=0, sticky="nsew", padx=(self.px(10), 0))
            font, char = widgets.glyph(picker, "chevron_down", self.px(12))
            chevron = tk.Label(picker, text=char, font=font, bg=c["well"], fg=c["text"], bd=0, padx=0, pady=0)
            chevron.grid(row=0, column=1, padx=(self.px(6), self.px(8)))
            parts = [picker, name, chevron]

        def hover(on):
            name.configure(bg=lg["hover"] if on else lg["field"])
            colour_now = widgets.real(name, "bg")
            for p in parts:
                if p is not name:
                    p.configure(bg=colour_now)
        for p in parts:
            if p in (picker, name) or self.kind != "console":
                p.bind("<Button-1>", lambda e: open_list())
            p.bind("<Enter>", lambda e: hover(True), add="+")
            p.bind("<Leave>", lambda e: hover(False), add="+")
        buttons = []
        for words_, command, button_why in (update, save_as):
            b = settings.PageButton(box, self.look, text=words_, command=command)
            buttons.append((b, words_, button_why))

        def greyed(widget, keys, changed):
            if "fg" in keys:
                none = tokens.same(str(widget.cget("fg")), lg["dim"])
                buttons[0][0].configure(state="disabled" if none else "normal")
        name.follow(greyed)
        greyed(name, {"fg"}, False)
        self.ui["profile_word"], self.ui["program"], self.ui["profile"] = word, program, name
        self.profile_parts = {"row": row, "holders": holders, "word": word, "program": program, "picker": picker,
                              "buttons": [b for b, _w, _y in buttons], "folded": False}
        self.lay_profile()
        row.band.add(holders["words"], holders["controls"], holders["buttons"], word, program)
        self.explained(row, word, why, words, program, holders["words"], holders["controls"], *parts)
        for b, words_, button_why in buttons:
            self.hints.add(b, button_why)
            self.lit_of[b] = word
            self.titles[b] = words_
        return row

    def lay_profile(self):
        """The profile row's widgets in the row, as each drawing lays them."""
        p, m = self.profile_parts, self.m
        row, h = p["row"], p["holders"]
        gap = self.px(m["button_gap"])
        word, program, picker = p["word"], p["program"], p["picker"]
        upd, sav = p["buttons"]
        if self.kind == "folio":
            # the label alone in its column, and the picker and its buttons with
            # the program under them
            upd.pack(in_=h["buttons"], side="left", padx=(gap, 0))
            sav.pack(in_=h["buttons"], side="left", padx=(gap, 0))
            picker.pack(in_=h["controls"], side="left")
            h["buttons"].pack(in_=h["controls"], side="left")
            h["controls"].pack(in_=h["words"], anchor="w")
            program.pack(in_=h["words"], anchor="w", pady=(self.px(4), 0))
            self.lay(row, word, [(h["words"], 0)])
        else:
            word.pack(in_=h["words"], anchor="w")
            program.pack(in_=h["words"], anchor="w")
            upd.pack(in_=h["buttons"], side="left")
            sav.pack(in_=h["buttons"], side="left", padx=(gap, 0))
            if self.kind == "console":
                picker.pack(in_=h["controls"], side="left")
                self.lay(row, h["words"], right=[(h["controls"], 0), (h["buttons"], m["button_gap"])])
            else:
                self.lay(row, h["words"], [(picker, 0)], right=[(h["buttons"], 0)])

    def fold(self, on):
        """The profile row folded into the head, at the compact level 2, its
        label, picker and buttons after the title in place of the line that
        says what closes the panel, which the key footer says too, and the
        program left out, or laid out in its row again. While it is folded
        the label and the program are no members of the row's band, which is
        hidden then, so the row lit and unlit by the keys leaves the label on
        the head's colour, the label's own lit type saying it is lit."""
        p = self.profile_parts
        if p is None or bool(on) == p["folded"] or self.head_frame is None:
            return
        p["folded"] = bool(on)
        items = [p["word"], p["picker"]] + p["buttons"]
        for w in items + [p["program"]]:
            manager = w.winfo_manager()
            if manager == "pack":
                w.pack_forget()
            elif manager == "grid":
                w.grid_forget()
        for holder in p["holders"].values():
            if holder.winfo_manager() == "pack":
                holder.pack_forget()
            elif holder.winfo_manager() == "grid":
                holder.grid_forget()
        band = p["row"].band
        if on:
            mine = (p["word"], p["program"])
            p["away"] = [(w, plain) for w, plain in band.members if w in mine]
            band.members = [(w, plain) for w, plain in band.members if w not in mine]
            ground = self.c["deep"]
            p["word"].set_ground(ground)
            for i, w in enumerate(items):
                w.pack(in_=self.extra, side="left", padx=(self.px(self.m["button_gap"]) if i else 0, 0))
            self.hint.grid_remove()
            self.extra.grid()
            band.grid_remove()
        else:
            # back in the band, in its colour as it stands, lit or not
            away = p.pop("away", [])
            band.members.extend(away)
            colour = self.look.c["lit"] if band.lit_on else None
            for w, plain in away:
                if plain is None:
                    w.set_ground(colour)
                else:
                    w.configure(bg=colour or plain)
            if not away:
                p["word"].set_ground(None)
            self.extra.grid_remove()
            self.hint.grid()
            for col in range(8):
                p["row"].band.columnconfigure(col, minsize=0, weight=0)
            self.lay_profile()
            p["row"].band.grid()

    def switch(self, name, words, var, command, why):
        """A switch's row: its label, the check button, with the keys in its
        label's brackets as caps, and its switch, ui's auto_box, nr_box,
        skin_box, mask_box or scale_box. Paper's skin row is a box before its
        words, see CheckFace, and Slate's an indented row with a smaller
        switch."""
        row = self.row(name)
        band, m = row.band, self.m
        card = self.card_row(row)
        small = name == "skin_auto"
        role = "panel_words" if small and self.kind == "folio" else "panel_row"
        b = self.check(band, words, var, command, role)
        shown, keys = switch_words(words)
        if shown != words:
            b.shown_by = lambda t: switch_words(t)[0]
            tk.Misc.configure(b, b._drawn())
        caps = [widgets.KeyCap(band, self.look, k, "cap_menu", ground=self.c["surface"],
                               pad=5 if self.kind == "console" else None) for k in keys]
        if self.kind == "folio" and small:
            # Paper's box at the control column, its words after it
            face = CheckFace(band, self.look, b)
            self.lay(row, face, [(b, 8)], tie=card, label=False, start=m["left"] + m["label"] + m["gap"])
        else:
            size = "small" if small or (self.kind == "industrial" and name == "mask") else "panel"
            face = faces.SwitchFace(band, self.look, b, size)
            cap_gaps = [(cap, 8 if self.kind != "industrial" else 10) for cap in caps]
            if self.kind == "folio":
                self.lay(row, b, [(face, 0)] + [(cap, 16) for cap in caps], tie=card)
            elif small and self.kind == "console":
                self.lay(row, b, right=[(face, m["gap"])], tie=card, label=False, start=m["indent"])
            else:
                self.lay(row, b, cap_gaps, right=[(face, m["gap"])], tie=card, label=False)
        self.ui[SWITCHES[name]] = b
        band.add(b, face, *caps)
        self.explained(row, b, why, shown, face, *caps)
        return b

    def tabs(self, words, why):
        """The row of the tabs: its label, ui's tabs_word, ui's tabs, the
        frame the lens puts a tab for each pass in, see tab, and ui's
        tabs_words, which the lens shows in it at one pass. Paper's has the
        ties' column header at its right."""
        row = self.row("tabs")
        band = row.band
        if self.kind != "industrial":
            # Slate's tabs and Paper's stand on a line along the row's foot,
            # which the chosen tab's line lies over, so it is made first
            widgets.Rule(band, self.look, role="rule").place(x=0, rely=1.0, y=-1, relwidth=1.0)
        word = self.label(band, words, roles=TABS_WORD if self.kind != "industrial" else LABEL)
        holder = self.frame(band)
        self.ui["tabs_words"] = self.words(holder, "")
        self.ui["tabs_word"], self.ui["tabs"] = word, holder
        if self.kind == "industrial":
            self.lay(row, word, [(holder, 0)])
            holder.grid_configure(sticky="sw")
            word.grid_configure(sticky="w")
        else:
            self.lay(row, word, [(holder, 0 if self.kind == "folio" else 10)], tie=self.kind == "folio")
            holder.grid_configure(sticky="nsw", pady=(0, 1))
        band.add(word)
        self.explained(row, word, why, words, holder)
        return row

    def tab(self, parent, words, chosen):
        """A pass's tab, a State label whose text is the code's, " Pass n ",
        drawn as the look's tab, chosen or not, and packed in the row of tabs.
        The lens binds its click. Slate's and Paper's chosen tab has a line
        under it, and Industrial's tabs are plates with a line along the top,
        the chosen one taller and amber."""
        lg, c, m = self.lg, self.c, self.m
        if self.kind == "industrial":
            lbl = widgets.StateLabel(parent, self.look, text=words, bg=lg["bg"] if chosen else lg["tab"],
                                     fg=lg["accent"] if chosen else lg["fg"], bd=0, padx=0, pady=0,
                                     highlightthickness=sc.border(1, self.s) if chosen else 0,
                                     highlightbackground=c["edge"], highlightcolor=c["edge"],
                                     roles={"fg": {"accent": "text", "fg": "muted"}}, lit=("fg", "accent"),
                                     shown=lambda t: str(t).strip().upper(), font_role="rail")
            w, h = m["tab_chosen"] if chosen else m["tab"]
            widgets.exact(lbl, self.px(w), self.px(h))
            top = tk.Frame(lbl, bg=c["accent"] if chosen else c["rule"], bd=0, highlightthickness=0,
                           height=self.px(m["tab_top"][1 if chosen else 0]))
            top.place(x=0, y=0, relwidth=1.0)
            lbl.pack(side="left", anchor="s", padx=(0, self.px(m["tab_gap"])))
            return lbl
        lbl = widgets.StateLabel(parent, self.look, text=words, bg=lg["bg"], fg=lg["accent"] if chosen else lg["fg"],
                                 bd=0, padx=self.px(m["tab_pad"]), pady=0, roles=TAB, lit=("fg", "accent"),
                                 shown=lambda t: str(t).strip(),
                                 font_role="control" if self.kind == "console" else "panel_row")
        lbl.pack(side="left", fill="y", padx=(0, self.px(m["tab_gap"])))
        if chosen:
            line = tk.Frame(lbl, bg=c["text"], bd=0, highlightthickness=0, height=self.px(m["tab_line"]))
            line.place(x=0, rely=1.0, y=-self.px(m["tab_line"]), relwidth=1.0)
        return lbl

    def choice(self, name, words, var, names, command, why):
        """A choice's row, the style's: its label, ui's style_word, and its
        radio buttons, ui's style_btns, drawn as one strip, see
        lens_look.faces.ChoiceStrip. names are the choices' codes and names."""
        row = self.row(name)
        band, lg = row.band, self.lg
        word = self.label(band, words)
        strip = faces.ChoiceStrip(band, self.look, "panel")
        buttons = []
        for code, label_ in names.items():
            b = tk.Radiobutton(strip, text=label_, variable=var, value=code, command=command, bg=lg["bg"], fg=lg["fg"],
                               selectcolor=lg["field"], activebackground=lg["bg"], activeforeground=lg["fg"],
                               disabledforeground=lg["dim"])
            strip.add(b)
            buttons.append(b)
        self.ui[name + "_word"], self.ui[name + "_btns"] = word, buttons
        if self.kind == "console":
            self.lay(row, word, right=[(strip, self.m["gap"])], tie=True)
        else:
            self.lay(row, word, [(strip, 0)], tie=True)
        band.add(word, strip)
        self.explained(row, word, why, words, strip, *buttons)
        return row

    def tie(self, key, words, var, command, why):
        """A tie, Same as pass 1, in the tie column of the row of the value it
        ties, ui's tie_box of the key, a check button the lens shows on the
        tabs from pass 2 on, drawn as a box, see lens_look.faces.TieBox."""
        name = {"NRStyle": "style", "NRAutoMask": "mask"}.get(key, key)
        row = self.rows[name]
        lg = self.lg
        b = widgets.StateCheckbutton(row.tie, self.look, text=words, variable=var, command=command, bg=lg["bg"],
                                     fg=lg["fg"], selectcolor=lg["field"], activebackground=lg["bg"],
                                     activeforeground=lg["fg"], disabledforeground=lg["dim"], roles=LABEL,
                                     lit=("fg", "accent"))
        faces.TieBox(b, self.look)
        b.grid(row=0, column=0)
        self.ui["tie_box"][key] = b
        row.band.add(b)
        self.titles[b] = words
        self.hints.add(b, why)
        self.lit_of[b] = b
        self.per_pass.add(b)
        self.light_with(row, b)
        return b

    def slider(self, key, words, lo, hi, command, glyph, glyph_font, why):
        """A value's row: its label, ui's key word, its slider and number,
        ui's key, the button that puts the slider at 1.00, ui's key reset,
        whose click the lens binds, and the tie column."""
        row = self.row(key)
        band, lg, m = row.band, self.lg, self.m
        word = self.label(band, words)
        scale = faces.slider(band, self.look, mark=1.0, from_=lo, to=hi, resolution=0.01, orient="horizontal",
                             command=command)
        shown = self.number(band)
        reset = faces.ResetFace(band, self.look, text=glyph, bg=lg["bg"], fg=lg["fg"], disabledforeground=lg["dim"],
                                font=glyph_font, bd=0, padx=0, pady=0)
        if self.kind == "console":
            self.lay(row, word, right=[(scale, m["gap"]), (shown, m["number_gap"]), (reset, m["reset_gap"])], tie=True)
        else:
            self.lay(row, word, [(scale, 0), (shown, m["number_gap"]), (reset, m["reset_gap"])], tie=True)
        self.ui[key + " word"], self.ui[key], self.ui[key + " reset"] = word, (scale, shown), reset
        band.add(word, scale.face, shown, reset)
        self.explained(row, word, why, words, scale, scale.face, shown, reset)
        self.sliders.add(word)
        return row

    def shared(self, words, var, command, why):
        """The switch that runs a pass through pass 1's network, first on the
        pass card: ui's shared_row, the row the lens shows on the tabs of
        passes 2 to 4, ui's shared_box, and ui's shared_words, which the lens
        packs beside the label while there is a note."""
        row = self.row("shared")
        band = row.band
        col = self.frame(band)
        box = self.check(col, words, var, command)
        box.pack(side="left")
        note = self.words(col, "")
        size = "panel"
        face = faces.SwitchFace(band, self.look, box, size)
        if self.kind == "folio":
            self.lay(row, col, [(face, 0)], tie=True)
        else:
            self.lay(row, col, right=[(face, self.m["gap"])], tie=True, label=False)
        self.ui["shared_row"], self.ui["shared_box"], self.ui["shared_words"] = band, box, note
        band.add(col, box, note, face)
        self.explained(row, box, why, words, face, col)
        return box

    def own_words(self, words, header):
        """The line that says what a tie does, ui's own_words, which the lens
        shows on the tabs from pass 2 on, and the ties' column header, which
        shows with the ties: Slate's beside the line, Paper's in the row of
        the tabs and Industrial's in a row of its own under the switch."""
        c, m = self.c, self.m
        part = self.parts[self.part_of("own")]
        own = self.frame(part)
        line = tk.Label(own, text=words, bg=c["surface"], fg=c["muted"], font=self.font("panel_words"), justify="left",
                        anchor="w", bd=0, padx=0, pady=0)
        self.rows["own"] = Row("own", "card", own, 0)
        self.ui["own_words"] = line
        if self.kind == "console":
            line.configure(wraplength=self.px(m["own_w"]))
            line.grid(row=0, column=0, sticky="w", padx=(self.px(m["card_left"]), 0),
                      pady=(self.px(m["own"][0]), self.px(m["own"][1])))
            own.columnconfigure(1, weight=1)
            cell = self.frame(own, width=self.px(m["tie"]))
            cell.grid(row=0, column=2, sticky="nse", padx=(0, self.px(m["card_right"])))
            cell.columnconfigure(0, weight=1, minsize=self.px(m["tie"]))
            head = tk.Label(cell, text=header, bg=c["surface"], fg=c["text"], font=self.font("control", True, 13),
                            bd=0, padx=0, pady=0, justify="center")
            head.grid(row=0, column=0, sticky="s", pady=(0, self.px(m["own"][1])))
            cell.rowconfigure(0, weight=1)
            self.header = head
            return line
        top, side = m["own_pad"]
        width = self.inner - 2 * self.px(m["card_pad"]) - 2 * self.px(side)
        line.configure(wraplength=max(1, width))
        if self.kind == "folio":
            line.configure(font=self.font("panel_words", size=12.5))
            widgets.Rule(own, self.look, role="rule").place(x=0, y=0, relwidth=1.0)
            self.rows["own"].band.configure(bg=c["surface"])
        else:
            widgets.Rule(own, self.look, role="rule").place(x=0, y=0, relwidth=1.0)
        line.grid(row=0, column=0, sticky="w", padx=(self.px(side), self.px(side)), pady=(self.px(top), self.px(top)))
        if self.kind == "folio":
            tabs = self.rows.get("tabs")
            holder = tabs.tie if tabs is not None and tabs.tie is not None else None
            if holder is not None:
                head = tk.Label(holder, text=header, bg=c["surface"], fg=c["muted"], font=self.font("panel_words", size=12),
                                bd=0, padx=0, pady=0, justify="center", wraplength=self.px(m["tie"]) - 4)
                head.grid(row=0, column=0, sticky="s", pady=(0, self.px(5)))
                self.header = head
        else:
            row = Row("tie_head", "card", self.frame(self.parts["card"], height=self.px(m["rows"]["tie_head"])),
                      m["rows"]["tie_head"])
            row.band.grid_propagate(False)
            self.rows["tie_head"] = row
            widgets.Rule(row.band, self.look, role="rule").place(x=0, y=0, relwidth=1.0)
            row.band.columnconfigure(0, weight=1)
            row.band.rowconfigure(0, weight=1)
            cell = self.frame(row.band, width=self.px(m["tie"]), height=self.px(16))
            cell.grid(row=0, column=1, sticky="se", padx=(0, self.px(m["card_right"])), pady=(0, self.px(3)))
            head = tk.Label(cell, text=text.display_case(header, "upper"), bg=c["surface"], fg=c["muted"],
                            font=self.font("explain_section", size=10.5), bd=0, padx=0, pady=0)
            head.place(relx=0.5, rely=1.0, anchor="s")
            self.header = row.band
        return line

    def passes(self, words, beside, pick, limit, why):
        """The pass count's row: its label, ui's passes_word, and the code's
        minus, number and plus labels, ui's minus, passes and plus, whose
        clicks the lens binds. Slate counts the passes in segments 1 to 4,
        which pick is called for, the labels made and kept out of sight, and
        Paper and Industrial in a stepper, see lens_look.faces. limit gives
        the most passes the lens runs."""
        row = self.row("passes")
        band, lg, m = row.band, self.lg, self.m
        made = []
        if self.kind == "console":
            col = self.frame(band)
            word = self.label(col, words)
            small = self.words(col, beside)
            word.pack(anchor="w")
            small.pack(anchor="w")
            for t in (" \u2212 ", "1", " + "):
                made.append(widgets.StateLabel(band, self.look, text=t, bg=lg["bg"], fg=lg["fg"], bd=0))
            for w in made:
                w.winfo_id()            # made at once, so a click told to it reaches its binding unseen
            face = faces.PassSegments(band, self.look, made[1], pick, limit)
            self.lay(row, col, right=[(face, m["gap"])], label=False)
            band.add(col, word, small, face)
            more = (col, small, face)
        else:
            word = self.label(band, words)
            stepper = faces.Stepper(band, self.look)
            for t in (" \u2212 ", "1", " + "):
                made.append(widgets.StateLabel(band, self.look, text=t, bg=lg["bg"], fg=lg["fg"], bd=0))
            stepper.dress(*made)
            small = self.words(band, beside)
            self.lay(row, word, [(stepper, 0), (small, 14)])
            band.add(word, small)
            more = (stepper, small)
        self.ui["passes_word"] = word
        self.ui["minus"], self.ui["passes"], self.ui["plus"] = made
        self.explained(row, word, why, words, *(more + tuple(made)))
        return row

    def strength(self, words, lo, hi, command, why):
        """The strength's row under the switch that scales the change, its
        label indented, ui's strength_word, its slider and number, ui's
        strength. The lens shows and hides the three with the switch, and the
        row follows them, see refresh."""
        row = self.row("strength")
        band, m = row.band, self.m
        word = self.label(band, words)
        scale = faces.slider(band, self.look, mark=None, from_=lo, to=hi, resolution=0.01, orient="horizontal",
                             command=command)
        shown = self.number(band)
        if self.kind == "console":
            self.lay(row, word, right=[(scale, m["gap"]), (shown, m["number_gap"])], label=False,
                     start=m["left"] + m["indent"])
        else:
            self.lay(row, word, [(scale, 0), (shown, m["number_gap"])], start=m["left"] + m["indent"])
            band.columnconfigure(0, minsize=self.px(m["left"] + m["label"] + m["gap"]))
        self.ui["strength_word"], self.ui["strength"] = word, (scale, shown)
        band.add(word, scale.face, shown)
        self.explained(row, word, why, words, scale, scale.face, shown)
        return row

    def quality(self, words, make, why):
        """The quality step's row: its label, ui's quality_word, and the
        slider and its name that make gives, the lens's quality_control in
        the look, see quality_name and quality_scale, ui's quality and
        quality_name. Slate's carousel names the step itself, so its label
        is kept out of sight."""
        row = self.row("quality")
        band, m = row.band, self.m
        word = self.label(band, words)
        scale, name = make(band)
        if self.kind == "console":
            self.lay(row, word, right=[(scale, m["gap"])])
            more = (scale, scale.face)
        else:
            self.lay(row, word, [(scale, 0), (name, 14 if self.kind == "folio" else 8)])
            more = (scale, scale.face, name)
            band.add(name)
        self.ui["quality_word"], self.ui["quality"], self.ui["quality_name"] = word, scale, name
        band.add(word, scale.face)
        self.explained(row, word, why, words, *more)
        return row

    def quality_name(self, parent, words, font):
        """The label that names the quality step, the code's, in the look's
        type, Industrial's in its capitals."""
        lg = self.lg
        industrial = self.kind == "industrial"
        return widgets.StateLabel(parent, self.look, text=words, bg=lg["bg"], fg=lg["fg"], font=font, anchor="w", bd=0,
                                  padx=0, pady=0, case="upper" if industrial else None,
                                  font_role="value" if industrial else "panel_row")

    def quality_scale(self, parent, names, command):
        """The quality step's slider, a LookScale with its QualityFace in the
        panel's size, with the classic slider's range, steps and command."""
        return faces.quality(parent, self.look, names, "panel", from_=0, to=len(names) - 1, resolution=1,
                             command=command)

    def foot(self, lines):
        """The classic panel's foot lines, ui's foot, made and not shown,
        whose words the drawn panel shows in its own places, see finish."""
        out = []
        for words in lines:
            out.append(tk.Label(self.box, text=words, bg=self.c["surface"], fg=self.c["muted"]))
        self.ui["foot"] = out
        return out

    # laid out, fitted and shown

    def finish(self, keys, idle, reset_line, context):
        """Lay the rows out in the look's order, make the explanation's part
        and the key footer, and fit the panel to its monitor. keys are the key
        footer's ((key, ...), words) pairs, idle the panel's line that shows
        while no row is picked, Paper's first sentence of it under the head,
        reset_line the line under a slider's explanation, and context the
        words that name the pass shown, with %d for it. Then the rows the lens
        shows only on some tabs or with a switch are hidden, as the lens's
        own code has them before it shows the first tab."""
        c, m, box = self.c, self.m, self.box
        self.reset_line, self.context = reset_line, context
        first, rest = sentences(idle)
        self.idle = content("", rest if self.kind == "folio" else idle)
        if self.info is not None:
            self.hints.add(self.info, idle)
        at = 0
        self.head_frame.grid(row=at, column=0, sticky="we")
        at += 1
        if self.kind == "folio":
            top, side, bottom = (self.px(v) for v in m["intro_pad"])
            self.intro = tk.Label(box, text=first, bg=c["surface"], fg=c["muted"],
                                  font=self.font("panel_words", size=13.5), anchor="w", bd=0, padx=0, pady=0)
            self.intro.grid(row=at, column=0, sticky="w", padx=(side, side), pady=(top, bottom))
            at += 1
        for part, names in LAYOUT[self.kind]:
            frame = self.parts[part]
            above, below = (self.px(v) for v in m["part_pad"][part])
            r = 0
            if self.kind == "folio" and part in ("mid", "tabs"):
                widgets.Rule(frame, self.look, role="rule").grid(row=r, column=0, sticky="we")
                r += 1
            made = [n for n in names if n in self.rows]
            for i, name in enumerate(made):
                row = self.rows[name]
                # Slate's rows stand in from the panel's sides, Industrial's
                # outside the card too, its card's rows run the card's width
                pad = self.px(m["band_pad"]) if (self.kind == "console" or part != "card") else 0
                row.band.grid(in_=frame, row=r, column=0, sticky="we", padx=(pad, pad))
                if i and self.kind == "folio" and name not in ("own", "shared", "tabs", "skin_auto"):
                    self.rule(row.band, widgets.shade(self.look, "rule_faint"))
                if i and self.kind == "industrial" and name not in ("own", "tie_head", "style"):
                    self.rule(row.band, c["rule"])
                r += 1
            if part == "card":
                pad = self.px(m["card_pad"])
                self.card_pack = dict(fill="x", padx=(pad, pad), pady=(above, below))
                self.card.pack(**self.card_pack)
                self.clip.grid(row=at, column=0, sticky="we")
            else:
                frame.grid(row=at, column=0, sticky="we", pady=(above, below))
            if self.kind == "industrial" and part == "tabs":
                self.rule(self.rows["tabs"].band, c["rule"])
            at += 1
        width = self.inner
        self.region = Region(box, self.look, width, self.px(m["explain"]))
        self.region.grid(row=at, column=0, sticky="we", pady=(self.px(m["explain_top"]), 0))
        self.region.spare, self.region.resized = self.spare, self.explain_resized
        at += 1
        self.footer = KeyFooter(box, self.look, width, self.px(m["footer"]), keys)
        self.footer.grid(row=at, column=0, sticky="we")
        self.hints.mode = "pane"
        self.hints.select = self.picked
        # the panel's heights at levels 0 to 2 with every row it can show
        # shown, the most it can take, and the level that fits the monitor
        self.heights = []
        for level in (0, 1, 2):
            self.apply(level)
            self.t.update_idletasks()
            self.heights.append(self.t.winfo_reqheight())
        level = fit.panel_fit(self.look, self.s, self.monitor_h, heights=self.heights)
        self.apply(level)
        # hidden as the lens's own code has them, until the first tab shows them
        ui = self.ui
        ui["shared_row"].grid_remove()
        for b in ui["tie_box"].values():
            b.grid_remove()
        ui["own_words"].grid_remove()
        for w in (ui["strength_word"],) + tuple(ui["strength"]):
            w.grid_remove()
        self.refresh()
        self.region.present(self.idle)
        return level

    def rule(self, band, colour):
        line = tk.Frame(band, bg=colour, height=1, bd=0, highlightthickness=0)
        line.place(x=0, y=0, relwidth=1.0)
        return line

    def apply(self, level):
        """The panel at a level, see the module's docstring."""
        self.level = level
        ratio = tokens.COMPACT_RATIO if level >= 1 else 1.0
        for row in self.rows.values():
            if row.height:
                h = self.px(row.height * ratio)
                if level >= 1:
                    # a compact row no lower than what it holds asks for, as
                    # Paper's quality step with the words under its ruler
                    h = max([h] + [self.asks(w) for w in row.band.grid_slaves() if w is not row.tie])
                row.band.configure(height=h)
                if row.tie is not None:
                    row.tie.configure(height=h)
        # the explanation's part at its drawn height, at every level
        explain = self.px(self.m["explain"])
        self.region.base = explain
        self.region.configure(height=explain)
        self.region.size = (self.region.size[0], explain)
        # what the explanation shows, laid out again, as the room the panel
        # has left on its monitor differs from level to level, see spare
        shown, self.region.shown = self.region.shown, None
        if shown is not None:
            self.region.present(shown)
        self.fold(level >= 2)
        self.scroll(level >= 3)

    @staticmethod
    def asks(widget):
        """The height a widget gridded in a row asks for, with the room above
        and under it."""
        pad = widget.grid_info().get("pady", 0)
        try:
            pads = [int(p) for p in (pad if isinstance(pad, (tuple, list)) else str(pad).split())]
        except (TypeError, ValueError):
            pads = []
        return widget.winfo_reqheight() + (sum(pads) if len(pads) == 2 else 2 * sum(pads))

    def room(self):
        """The height the panel has on its monitor, see lens_look.fit.panel_fit."""
        return self.monitor_h - 2 * self.px(fit.PANEL_ROOM)

    def spare(self):
        """The room the panel has left on its monitor at its level, which its
        explanation's part may grow into for a text that needs it, see
        Region.fit_lines: the monitor's room less the panel's height at the
        level with every row it can show shown, so a row that comes later
        still fits. None at level 3, where the pass card scrolls to fit."""
        if self.level >= 3 or not self.heights:
            return 0
        return max(0, self.room() - self.heights[min(self.level, len(self.heights) - 1)])

    def explain_resized(self, extra):
        """The explanation's part grew by extra pixels for a text, or came
        back to its drawn height, so the lens gives the window the size its
        contents now ask for, see fitted."""
        if self.fitted is not None:
            self.fitted()

    def scroll(self, on):
        """The pass card clipped to what the monitor leaves of it, at level 3,
        and moved within its clip to keep the lit row in view, see keep."""
        clip, card = self.clip, self.card
        pad = self.px(self.m["card_pad"])
        placed = card.winfo_manager() == "place"
        if on:
            self.t.update_idletasks()
            over = (self.heights[2] - self.room()) if len(self.heights) > 2 else 0
            # the card's height with the room above and under it, as it was
            # packed in the clip until now
            high = card.winfo_reqheight() + sum(self.card_pack.get("pady", (0, 0)))
            clip.pack_propagate(False)
            clip.configure(width=self.inner, height=max(self.px(CARD_LEAST), high - max(0, over)))
            if not placed:
                card.pack_forget()
            self.offset = 0
            card.place(x=pad, y=0, relwidth=1.0, width=-2 * pad)
        elif placed:
            card.place_forget()
            clip.pack_propagate(True)
            card.pack(**self.card_pack)

    def keep(self, widget):
        """The pass card moved within its clip so the band of this row lies
        in view, at level 3."""
        band = self.band_of.get(widget)
        if band is None or self.level < 3 or band.master is not self.card:
            return
        self.t.update_idletasks()
        y, h = band.winfo_y(), band.winfo_height()
        room = self.clip.winfo_height()
        most = max(0, self.card.winfo_reqheight() - room)
        if y < self.offset:
            self.offset = y
        elif y + h > self.offset + room:
            self.offset = y + h - room
        self.offset = max(0, min(most, self.offset))
        self.card.place_configure(y=-self.offset)

    # what the lens tells the panel

    def show_pass(self, n):
        """The pass whose tab shows, which the explanation of its rows names."""
        self.pass_shown = int(n)

    def refresh(self):
        """The rows that follow what the lens shows: the strength's row with
        its slider, the ties' column header and the line about them with
        the ties, and the pass card's place at level 3. The lens calls it
        each time the panel's contents change, see Lens._panel_fit."""
        try:
            ui = self.ui
            row = self.rows.get("strength")
            if row is not None:
                self.shown(row.band, bool(ui["strength_word"].winfo_manager()))
            ties = any(bool(b.winfo_manager()) for b in ui.get("tie_box", {}).values())
            if self.header is not None:
                self.shown(self.header, ties)
            own = self.rows.get("own")
            if own is not None:
                self.shown(own.band, bool(ui["own_words"].winfo_manager()))
            if self.level >= 3:
                self.offset = max(0, min(self.offset, max(0, self.card.winfo_reqheight() - self.clip.winfo_height())))
                self.card.place_configure(y=-self.offset)
        except Exception as exc:
            widgets.fault(self, exc)

    @staticmethod
    def shown(widget, on):
        if on and not widget.winfo_manager():
            widget.grid()
        elif not on and widget.winfo_manager():
            widget.grid_remove()

    def explain_of(self, lit, own=None):
        """What the explanation shows for a row whose lit label is lit, or
        for a widget of the row with an explanation of its own, a button."""
        at = lit if own is None else own
        context = (self.context % self.pass_shown) if lit in self.per_pass else ""
        extra = self.reset_line if (lit in self.sliders and own is None) else ""
        return content(self.titles.get(at, ""), self.hints.texts.get(at, ""), context, extra)

    def lit(self, n):
        """The lens lit row n of its panel_rows, or none. The explanation
        shows that row, or the panel's own line where none is lit, and at
        level 3 the pass card keeps the row in view."""
        try:
            rows = self.rows_of()
            if n is None or not 0 <= n < len(rows):
                self.region.present(self.idle)
                return
            widget = rows[n][2]
            self.region.present(self.explain_of(widget))
            self.keep(widget)
        except Exception as exc:
            widgets.fault(self, exc)

    def keyed(self):
        """An arrow key picked a row: the pointer, wherever it is now, picks a
        row again only once it has moved a few pixels from here, so a pointer
        at rest on the panel, or one the program in front puts back, does not
        take the keys' row away."""
        try:
            self.key_at = tuple(self.t.winfo_pointerxy())
        except Exception:
            self.key_at = None

    def set_idle(self, words, show):
        """The panel's idle line, the lens's top line in a drawn look: shown in
        the explanation's part while no row is picked, and with show at once.
        Paper keeps its first sentence under the head."""
        first, rest = sentences(words)
        self.idle = content("", rest if self.kind == "folio" else words)
        if self.kind == "folio" and getattr(self, "intro", None) is not None:
            self.intro.configure(text=first)
        if self.info is not None:
            self.hints.add(self.info, words)
        if show and self.region is not None:
            self.region.present(self.idle)

    def picked(self, widget, how):
        """The pointer moved onto a widget of a row, or F1 asked for one, how
        being pointer or key, see the lens's Hints in its pane mode. The lens
        lights the row, which the explanation then shows, and a button with an
        explanation of its own shows that. The pointer counts once it has
        moved from where it first came, so a panel that opens under a resting
        pointer lights nothing by itself."""
        try:
            if how == "pointer":
                at = tuple(self.hints.at or ())
                # a pointer the program in front holds and keeps putting back
                # is no pointer of the person's, and after an arrow key the
                # pointer picks again only once it has really moved
                if self.held():
                    self.hints.over = None
                    return
                if self.key_at is not None:
                    if len(at) == 2 and abs(at[0] - self.key_at[0]) + abs(at[1] - self.key_at[1]) < self.px(8):
                        self.hints.over = None
                        return
                    self.key_at = None
                if self.rest is None or self.rest == at:
                    if self.rest is None:
                        self.rest = at
                    self.hints.over = None      # picked again once the pointer moves
                    return
                self.rest = ()
            lit = self.lit_of.get(widget)
            if lit is None:
                if widget is self.info:
                    self.region.present(self.idle)
                return
            n = next((i for i, r in enumerate(self.rows_of()) if r[2] is lit), None)
            if n is None or self.light_row is None:
                return
            self.light_row(n)
            if widget is not lit and widget in self.titles:
                self.region.present(self.explain_of(lit, widget))
        except Exception as exc:
            widgets.fault(self, exc)
