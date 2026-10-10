"""The lens's own dialog, in which the lens asks its questions and says what
it has to say, and Messages, which stands in for tkinter.messagebox in the
lens, so that no message of the lens is one of Windows' own boxes, which no
theme reaches.

A dialog is made withdrawn, dressed while it is still unseen (see
lens_look.win.dress), placed, and then shown on top of every window without
being made active, as Tk shows a window it maps for the first time. The
keyboard comes to it only where the lens has the keyboard already, so a
dialog never takes the foreground from the program in front. It is modal, and
once it closes the keyboard and Tk's grab go back where they were, as Tk's own
dialogs give them back.

It keeps what Windows' own boxes do. The sign of the message's kind, info,
question, warning or error, is drawn from Windows' own icon font, and Windows'
own sound for that kind plays as it shows. A button answers with its words,
Enter presses the button that has the keyboard, the default one to begin with,
Y and N press Yes and No, and Ctrl+C or Ctrl+Insert copies the whole message
as Windows' own boxes copy theirs. Escape and the close button give the answer
the dialog has for them, OK on a message. A Yes and No question has none, so
there Escape does nothing and the close button is greyed, as on Windows' own
box, and the person picks Yes or No.

Its text wraps at a width that grows with the display's scaling, as the text
of Windows' own boxes does, and a line the lens broke on purpose shows whole
up to a limit.

The classic look shows it as the lens has always drawn its questions, a text
and a row of buttons in the theme's colours with the default one in the
accent, see Lens._ask in neural_lens.py. A drawn look draws it as the look's
dialog drawings do, see Dialog.build_drawn: the text split into its head, its
paragraphs, its detail and the paths it names, see text.split_message, the
look's sign, and the buttons in a footer of their own in the look's order,
some with a key cap. The same footer, field and type make New profile, see
name_box, the download box's bar, see Progress, and the stack setup's window,
see SetupShell. Where a drawn look cannot draw one of them, it is drawn as in
the classic look and lens.log says so once.
"""
import tkinter as tk
import tkinter.font as tkfont

from lens_look import scale, text, tokens, widgets, win

# The words on the buttons, as Windows' own boxes have them
YES, NO, OK = "Yes", "No", "OK"
# The key that presses a button, as on Windows' own boxes, where Y and N
# answer a Yes and No question. OK has none
KEYS = {YES: "y", NO: "n"}
# The text in the font of the lens's questions, wrapped at WRAP pixels at 100
# percent and at more on a display scaled up. A line the lens broke on purpose
# that is wider widens the wrap, up to WRAP_MOST, so it shows whole
FONT = ("Segoe UI", 10)
WRAP, WRAP_MOST = 460, 600
# Pixels at 100 percent kept free above and below a dialog on its monitor, for
# its caption and a margin. A text that would make the dialog taller than the
# rest scrolls in a box of its own, so its buttons stay in view
MARGIN = 48
# The sign of each kind of message, as Windows' own icon font has it, Segoe
# Fluent Icons or else Segoe MDL2 Assets, which hold it at the same place, the
# outlined signs the dialog drawings draw. An info sign and a question are in
# the dim colour, a warning in the warning colour and an error in the close
# button's red. SIGN_SIZE is the sign's size in pixels at 100 percent
SIGN_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
SIGNS = {"info": ("\ue946", "dim"), "question": ("\ue9ce", "dim"), "warning": ("\ue7ba", "warn"),
         "error": ("\uea39", "close")}
SIGN_SIZE = 24
# The options of tkinter.messagebox's functions the stand-in takes. A call
# with any other, such as type, shows the fallback's box, which knows them all
OPTIONS = ("icon", "parent", "default", "detail")
# The line Windows' own boxes copy between the title, the text and the buttons
RULE = "-" * 27

_family = []                    # the icon font this machine has, once looked for, None where it has neither

# ---- the drawn looks, see Dialog.build_drawn

# The forms of the lens's dialog: ask, a question with buttons of its own that
# Lens._ask asks, such as the update offer, message, a message with OK alone,
# and question, a question of Yes and No. name is New profile, see name_box
FORMS = ("ask", "message", "question")

# What heads the text in each drawn kind and form, see text.split_message.
# A question Lens._ask asks is headed by its first paragraph, and in Folio a
# message by its first line. Slate and Industrial draw a message's first line
# as its text, and no drawing heads a question of Yes and No
HEAD = {"console": {"ask": "paragraph", "message": None, "question": None},
        "folio": {"ask": "paragraph", "message": "line", "question": None},
        "industrial": {"ask": "paragraph", "message": None, "question": None}}

# A drawn dialog's sizes in CSS pixels at 100 percent, from the dialog
# drawings. pad is the room round a message, as (above it, either side, below
# it), ask_pad that round a question Lens._ask asks and round New profile, and
# progress_pad that round the download box. sign is the room after Slate's
# sign and Industrial's box, which is box pixels square, and rule the width of
# Folio's line beside a warning, with rule_gap the room after it. head_gap,
# para_gap, detail_gap and path_gap are the room above a part after the head,
# above a paragraph, a detail and a path, and top the room above Industrial's
# text beside its box. path_pad is the room round a path in its field, as
# (above and below, either side). field is New profile's field, as (its
# height, the room before its words, the room above it), with field_ring the
# width of its edge. footer is the footer's height, the room at its left and at
# its right, and the room between its buttons. progress is the download box's
# bar, as (its height, the room above it), which Folio does not draw. wrap is
# the width a text wraps at, as wide as the widest text the drawings draw
SIZES = {
    "console": dict(pad=(20, 22, 22), ask_pad=(18, 22, 20), progress_pad=(16, 22, 18), sign=14, box=None,
                    rule=None, rule_gap=None, head_gap=10, para_gap=12, detail_gap=10, path_gap=10, top=0,
                    path_pad=(8, 12), field=(40, 14, 10), field_ring=2, footer=(64, 24, 18, 10), progress=(6, 10),
                    wrap=600),
    "folio": dict(pad=(24, 24, 24), ask_pad=(24, 24, 24), progress_pad=(24, 24, 24), sign=None, box=None,
                  rule=2, rule_gap=14, head_gap=8, para_gap=14, detail_gap=8, path_gap=8, top=0, path_pad=(0, 0),
                  field=(36, 10, 8), field_ring=1, footer=(60, 24, 24, 10), progress=None, wrap=384),
    "industrial": dict(pad=(22, 24, 24), ask_pad=(22, 24, 24), progress_pad=(22, 24, 26), sign=16, box=34,
                       rule=None, rule_gap=None, head_gap=10, para_gap=12, detail_gap=12, path_gap=10, top=4,
                       path_pad=(7, 12), field=(34, 12, 12), field_ring=1, footer=(52, 24, 14, 8), progress=(8, 12),
                       wrap=600),
}

# The type and the colour of each part of a drawn dialog, by kind, as (its
# font role, its colour role): a message's head, text, detail and path, New
# profile's words and field, and the download box's words, each the role
# whose face the dialog drawings draw that part in. Folio draws a detail and
# a path in its text's serif and ink, and Industrial a detail and a path in
# the mono at 500 that its values take
TYPE = {
    "console": {"head": ("dialog_head", "strong"), "text": ("dialog_text", "text"),
                "detail": ("dialog_detail", "muted"), "path": ("hints", "strong"), "label": ("dialog_text", "text"),
                "field": ("dialog_text", "strong"), "status": ("dialog_text", "text")},
    "folio": {"head": ("dialog_head", "text"), "text": ("dialog_text", "text"), "detail": ("dialog_text", "text"),
              "path": ("dialog_text", "text"), "label": ("line", "text"), "field": ("line", "text"),
              "status": ("line", "text")},
    "industrial": {"head": ("dialog_head", "text"), "text": ("dialog_text", "text"), "detail": ("value", "muted"),
                   "path": ("value", "text"), "label": ("row", "text"), "field": ("value", "text"),
                   "status": ("dialog_text", "text")},
}

# The grounds of a drawn dialog, by colour role or by a name of
# widgets.SHADES: a path's field, as (its ground, its edge or None), New
# profile's field, as (its ground, its edge, its edge while it has the
# keyboard), the footer, as (its ground, the rule along its top), and the
# download box's bar, as (its ground, its edge or None, its fill)
GROUNDS = {
    "console": dict(path=("well", None), field=("well", "well", "accent"), footer=("deep", "rule"),
                    progress=("well", None, "accent")),
    "folio": dict(path=("surface", None), field=("well", "edge", "text"), footer=("surface", "rule"),
                  progress=None),
    "industrial": dict(path=("deep", "edge"), field=("deep", "edge", "accent"), footer=("band", "rule"),
                       progress=("deep", "edge", "accent")),
}

# The colour role of the classic sign's colours, see SIGNS, in a drawn look
SIGN_ROLES = {"dim": "muted", "warn": "warn", "close": "close"}
# Folio draws no sign. The text of a warning has a line at its left in the
# warning colour, and an error's in the close button's red
RULE_ROLES = {"warning": "warn", "error": "close"}
# Industrial draws the sign in a box of its own, an i or a question mark in
# LETTER's type in its text colour, and Windows' signs of a warning and of an
# error, GLYPH_SIZE pixels at 100 percent, both in its warning colour, since
# its red is too dark to tell on the box. Each sign is (the letter or the
# glyph's place in the icon font, the letter where neither icon font is there,
# its colour role)
INDUSTRIAL_SIGNS = {"info": ("i", "i", "text"), "question": ("?", "?", "text"), "warning": (0xE7BA, "!", "warn"),
                    "error": (0xEA39, "x", "warn")}
LETTER = tokens.Face("bsc", 20, 600, None, None)
GLYPH_SIZE = 18

# The key cap a drawn dialog's button carries, by kind and form, as (the
# key, the button, the last or the primary). Slate draws Esc on the button
# Escape stands for, the last of a question Lens._ask asks and New profile's
# Cancel, and Folio draws Enter on the primary button of a message, of a
# question and of New profile. Industrial draws none
CAPS = {"console": {"ask": ("Esc", "last"), "name": ("Esc", "last")},
        "folio": {"message": ("Enter", "primary"), "question": ("Enter", "primary"), "name": ("Enter", "primary")},
        "industrial": {}}
# Slate puts the first button, the primary, at the right, and Folio and
# Industrial keep the order the lens gives them
REVERSED = {"console": True, "folio": False, "industrial": False}
# Slate draws the buttons other than the primary narrower, see
# widgets.BUTTONS, which CapButton takes for the rest
SECONDARY = {"console": dict(pad=(16, 16), least=76)}

# The mono type of the stack setup's log, of the folder it installs into and
# of the names of NVIDIA's files, by kind. Industrial's is its detail's, and
# Slate and Folio take the mono of the lens's fonts
MONO = {"console": tokens.Face("mono", 13, 400, None, None), "folio": tokens.Face("mono", 13, 400, None, None),
        "industrial": tokens.Face("mono", 13.5, 400, None, None)}

# The fault the dialog met where a drawn look could not draw it, which
# lens.log says once. From then on it is drawn as in the classic look for
# the rest of the run. SETUP_FAULT is the stack setup's window's
FAULT = []
SETUP_FAULT = []


def drawn(look):
    """Whether the dialog is drawn in its look's layout, which it is in a
    drawn look until it has met a fault there, see FAULT."""
    return (look is not None and not getattr(look, "classic", True) and getattr(look, "kind", None) in tokens.DRAWN
            and not FAULT)


def form_of(buttons, form=None):
    """The dialog's form, see FORMS, the one given or else message for one
    button alone and question for more."""
    if form in FORMS or form == "name":
        return form
    return "message" if len(buttons) == 1 else "question"


def screen_order(kind, count):
    """The buttons' places in the code's order, as the screen shows them from
    the left, see REVERSED."""
    order = list(range(count))
    return order[::-1] if REVERSED.get(kind) else order


def caps_of(kind, form, count, default):
    """The key each button's cap shows, by the button's place in the code's
    order, see CAPS. A question Lens._ask asks with one button has no button
    for Escape."""
    key, which = CAPS.get(kind, {}).get(form, (None, None))
    if not key or not count:
        return {}
    if which == "last":
        return {count - 1: key} if count > 1 else {}
    return {default: key}


def gap_before(sizes, part, before):
    """The room above a part of the text in CSS pixels, see SIZES, none above
    the first."""
    if before is None:
        return 0
    if part.kind == "path":
        return sizes["path_gap"]
    if before.kind == "head":
        return sizes["head_gap"]
    if part.kind == "detail":
        return sizes["detail_gap"]
    return sizes["para_gap"] if part.new else 0


def wrap_of(lines, measure, s, base=WRAP, most=WRAP_MOST):
    """The width in pixels lines wrap at at the scale s, base scaled, or the
    width of the widest line that is no wider than most scaled, so a line the
    lens broke on purpose shows whole and a long paragraph wraps at base.
    measure gives a line's width in pixels in the lines' font."""
    base, most = scale.px(base, s), scale.px(max(base, most), s)
    fits = [width for width in (measure(line) for line in lines) if width <= most]
    return max([base] + [width + 2 for width in fits])


def percent_of(words):
    """The percentage a text ends in, such as 42 for "Downloading ... 42%",
    or 0 where it ends in none."""
    words = str(words).rstrip()
    if not words.endswith("%"):
        return 0
    digits = ""
    for ch in reversed(words[:-1]):
        if not ch.isdigit():
            break
        digits = ch + digits
    return min(100, int(digits)) if digits else 0


def pair(value):
    """A grid padding as Tk gives it back, a number or two, as [before, after]."""
    if isinstance(value, (tuple, list)):
        got = [int(str(v)) for v in value]
    else:
        got = [int(v) for v in str(value).split()]
    return ((got or [0]) * 2)[:2]


def colour_of(look, name):
    """A colour of the look by its role, or by its name in widgets.SHADES."""
    got = look.c.get(name)
    return got if got else widgets.shade(look, name)


def measuring(widget, font):
    """A function that gives a line's width in pixels in a font, as Tk measures
    it for a label in that font."""
    return lambda line: int(widget.tk.call("font", "measure", font, line))


def say_fault(said, where, look, exc):
    """One line in lens.log the first time a drawn look could not draw where,
    see FAULT. Never raises."""
    first = not said
    said.append(str(exc) or type(exc).__name__)
    if first:
        try:
            print('the %s could not be drawn in the %s look ("%s"), so it is drawn as in the classic look'
                  % (where, getattr(look, "theme", "drawn"), said[0]), flush=True)
        except Exception:
            pass                    # an output that cannot take the error's words must not stop the dialog


def colours(look):
    """The ten colours of a look's theme, Slate's where no look is given."""
    ten = getattr(look, "legacy", None)
    return ten if ten else tokens.CLASSIC["Slate"]


def sign_family(widget):
    """The first of SIGN_FONTS the machine has, or None where it has neither."""
    if not _family:
        try:
            have = set(tkfont.families(widget))
        except tk.TclError:
            have = set()
        _family.append(next((f for f in SIGN_FONTS if f in have), None))
    return _family[0]


class Dialog(object):
    """One showing of the lens's dialog, see ask."""

    def __init__(self, title, text, buttons, parent=None, look=None, default=0, cancel=None, icon=None,
                 detail=None, escape=True, form=None, place=None):
        self.title, self.text = str(title or ""), str(text or "")
        self.said, self.detail = self.text, (str(detail) if detail else None)
        if detail:
            self.text = "%s\n\n%s" % (self.text, detail) if self.text else str(detail)
        self.buttons = [str(b) for b in buttons] or [OK]
        self.parent, self.look, self.icon, self.cancel, self.escape = parent, look, icon, cancel, escape
        self.default = default if 0 <= default < len(self.buttons) else 0
        self.form = form_of(self.buttons, form)
        self.placer = place             # what places the window, see place
        self.answer, self.answered, self.closed = None, False, False
        self.win, self.top, self.body, self.made = None, None, None, []
        self.parts = []                 # the parts of the text a drawn look draws, see build_drawn
        self.wrap = WRAP
        self.before = None              # what hold took and close gives back

    def run(self):
        """Show the dialog and wait for its answer. A fault before it is
        answered closes what was made of it and is raised, so the caller can
        show a box of its own instead. One after the answer is passed over."""
        try:
            self.build()
            self.show()
            self.win.wait_window()
        except Exception:
            if not self.answered:
                raise
        finally:
            self.close()
        return self.answer

    def build(self):
        """The window, withdrawn as it is made, with the sign, the text, the
        buttons and the keys Windows' own boxes take. A drawn look draws it as
        its dialog drawings do, see build_drawn, and the classic look as the
        lens has always drawn its questions, see build_classic. Where a drawn
        look cannot draw it, it is drawn as in the classic look, and from then
        on for the rest of the run, and lens.log says so once, see FAULT."""
        if drawn(self.look):
            try:
                return self.build_drawn()
            except Exception as exc:
                self.drawn_fault(exc)
        return self.build_classic()

    def drawn_fault(self, exc):
        """What a drawn look made of the dialog taken away, and the line in
        lens.log, see say_fault."""
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
        self.win, self.top, self.body, self.made, self.parts = None, None, None, [], []
        say_fault(FAULT, "lens's dialog", self.look, exc)

    def bind_keys(self, d):
        """The keys Windows' own boxes take, on the dialog's window d."""
        for key in ("<Return>", "<KP_Enter>"):
            d.bind(key, self.enter)
        d.bind("<Escape>", lambda event: self.quit())
        for key, i in self.keys().items():
            for k in (key, key.upper()):
                d.bind("<Key-%s>" % k, lambda event, b=self.made[i]: self.press(b))
        d.bind("<<Copy>>", self.copy)   # Ctrl+C and Ctrl+Insert, as Tk names them on Windows

    def build_drawn(self):
        """The window as the look's dialog drawings draw it. Its text split
        into a head, paragraphs, a detail and paths, see text.split_message
        and HEAD, each in its own type and colour, see TYPE, at the right of
        the look's sign, see drawn_sign, a path in a field it can be selected
        in, see path_field, and under them the buttons in the look's footer,
        see footer. The text wraps as wide as the widest text the drawings
        draw, and a line the lens broke on purpose shows whole up to a limit,
        see wrap_of. A text too tall for the screen scrolls, see fit_drawn."""
        root = self.parent if self.parent is not None else tk._default_root
        if root is None:
            raise RuntimeError("no Tk root to show the dialog over")
        look = self.look
        kind, c = look.kind, look.c
        m = SIZES[kind]
        d = self.win = tk.Toplevel(root)
        d.withdraw()                    # first seen dressed and placed, see show
        d.title(self.title)
        d.attributes("-topmost", True)
        d.configure(bg=c["surface"])
        d.resizable(False, False)
        d.protocol("WM_DELETE_WINDOW", self.quit)
        d.columnconfigure(0, weight=1)
        s = look.scale_for(d)
        above, side, below = m["ask_pad" if self.form == "ask" else "pad"]
        body = self.top = tk.Frame(d, bg=c["surface"], bd=0, highlightthickness=0)
        body.grid(row=0, column=0, sticky="nsew")
        sign = self.drawn_sign(body, look, s, above, side, below)
        column = self.body = tk.Frame(body, bg=c["surface"], bd=0, highlightthickness=0)
        column.grid(row=0, column=1, sticky="nw",
                    padx=(0 if sign is not None else scale.px(side, s), scale.px(side, s)),
                    pady=(scale.px(above + (m["top"] if sign is not None else 0), s), scale.px(below, s)))
        self.parts = text.split_message(self.said, self.detail, HEAD[kind][self.form]).parts
        before = None
        for row, part in enumerate(self.parts):
            made = self.drawn_part(column, part, look, s)
            made.grid(row=row, column=0, sticky="we" if part.kind == "path" else "w",
                      pady=(scale.px(gap_before(m, part, before), s), 0))
            before = part
        commands = [lambda word=word: self.pick(word) for word in self.buttons]
        _foot, self.made = footer(d, look, self.buttons, commands, self.default, self.form)
        self.bind_keys(d)
        self.fit_drawn(look, s)

    def drawn_part(self, column, part, look, s):
        """A part of the text, a label in the part's type and colour that
        wraps, see wrap_of, or a path's field."""
        if part.kind == "path":
            return path_field(column, look, part.words, s, self.copy)
        c, kind = look.c, look.kind
        role, colour = TYPE[kind][part.kind]
        font = look.font(role, widget=column)
        wrap = wrap_of(part.words.split("\n"), measuring(column, font), s, SIZES[kind]["wrap"])
        return tk.Label(column, text=part.words, bg=c["surface"], fg=c[colour], font=font, justify="left",
                        anchor="w", wraplength=wrap, bd=0, padx=0, pady=0)

    def drawn_sign(self, body, look, s, above, side, below):
        """The sign of the message's kind at the left of its text, as the
        look's drawings draw it: Windows' outlined sign in Slate, see SIGNS, a
        line in the warning colour beside a warning in Folio, see RULE_ROLES,
        and a box with the sign in it in Industrial, see INDUSTRIAL_SIGNS. A
        dialog asked with no kind, and one whose sign this machine has no font
        for, has none."""
        kind, c, m = look.kind, look.c, SIZES[look.kind]
        icon = str(self.icon or "")
        if kind == "folio":
            role = RULE_ROLES.get(icon)
            if role is None:
                return None
            rule = tk.Frame(body, bg=c[role], width=scale.border(m["rule"], s), bd=0, highlightthickness=0)
            rule.grid(row=0, column=0, sticky="ns", padx=(scale.px(side, s), scale.px(m["rule_gap"], s)),
                      pady=(scale.px(above, s), scale.px(below, s)))
            return rule
        if kind == "industrial":
            sign = INDUSTRIAL_SIGNS.get(icon)
            if sign is None:
                return None
            glyph, letter, role = sign
            family = sign_family(body) if isinstance(glyph, int) else None
            if family is not None:
                words, font = chr(glyph), (family, -scale.px(GLYPH_SIZE, s), "normal")
            else:
                words, font = letter, look.face_font(LETTER, widget=body)
            box = tk.Label(body, text=words, font=font, bg=c["deep"], fg=c[role], bd=0, highlightthickness=1,
                           highlightbackground=c["edge"], highlightcolor=c["edge"])
            widgets.exact(box, scale.px(m["box"], s), scale.px(m["box"], s))
            box.grid(row=0, column=0, sticky="n", padx=(scale.px(side, s), scale.px(m["sign"], s)),
                     pady=(scale.px(above, s), 0))
            return box
        glyph, role = SIGNS.get(icon, (None, None))
        family = sign_family(body) if glyph else None
        if family is None:
            return None
        label = tk.Label(body, text=glyph, bg=c["surface"], fg=c[SIGN_ROLES[role]],
                         font=(family, -scale.px(SIGN_SIZE, s)), bd=0, padx=0, pady=0)
        label.grid(row=0, column=0, sticky="n", padx=(scale.px(side, s), scale.px(m["sign"], s)),
                   pady=(scale.px(above, s), 0))
        return label

    def fit_drawn(self, look, s):
        """A text too tall for the screen, such as a long error, shows in a
        box of its own that scrolls, its parts in their own type and colour,
        as many lines tall as the monitor has room for, so the buttons stay
        in view, as build_classic's fit does. Any other shows whole."""
        d = self.win
        d.update_idletasks()
        room = win.work_area(*self.anchor())[3] - 2 * scale.px(MARGIN, s)
        if d.winfo_reqheight() <= room:
            return
        kind, c = look.kind, look.c
        rest = d.winfo_reqheight() - self.body.winfo_reqheight()
        font = look.font(TYPE[kind]["text"][0], widget=d)
        line = int(d.tk.call("font", "metrics", font, "-linespace"))
        zero = int(d.tk.call("font", "measure", font, "0"))
        for child in self.body.winfo_children():
            child.destroy()
        box = tk.Text(self.body, width=max(40, scale.px(SIZES[kind]["wrap"], s) // max(1, zero)),
                      height=max(4, (room - rest) // max(1, line)), wrap="word", bg=c["surface"], fg=c["text"],
                      font=font, relief="flat", bd=0, highlightthickness=0, selectbackground=c["lit"],
                      selectforeground=c["strong"], insertwidth=0, padx=0, pady=0)
        for name in ("head", "detail", "path"):
            role, colour = TYPE[kind][name]
            box.tag_configure(name, font=look.font(role, widget=d), foreground=c[colour])
        for i, part in enumerate(self.parts):
            box.insert("end", ("" if i == 0 else "\n\n" if part.new else "\n") + part.words, (part.kind,))
        bar = tk.Scrollbar(self.body, command=box.yview)
        box.configure(yscrollcommand=bar.set, state="disabled")
        box.bind("<<Copy>>", self.copy)     # ahead of the Text's own copy, which would copy for Tk alone
        box.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")

    def build_classic(self):
        """The window as the lens has always drawn its questions, withdrawn as
        it is made, with the sign, the text and the buttons."""
        root = self.parent if self.parent is not None else tk._default_root
        if root is None:
            raise RuntimeError("no Tk root to show the dialog over")
        c = colours(self.look)
        d = self.win = tk.Toplevel(root)
        d.withdraw()                    # first seen dressed and placed, see show
        d.title(self.title)
        d.attributes("-topmost", True)
        d.configure(bg=c["bg"])
        d.resizable(False, False)
        d.protocol("WM_DELETE_WINDOW", self.quit)
        s = scale.scale_of(d)
        font = tkfont.Font(root=d, font=FONT)
        self.wrap = self.wrap_width(font.measure, s)
        top = self.top = tk.Frame(d, bg=c["bg"])
        top.grid(row=0, column=0, columnspan=len(self.buttons), sticky="we", padx=14, pady=(14, 12))
        self.sign(top, c, s)
        self.body = tk.Label(top, text=self.text, bg=c["bg"], fg=c["fg"], justify="left", wraplength=self.wrap,
                             font=FONT)
        self.body.pack(side="left", anchor="nw")
        last = len(self.buttons) - 1
        for i, word in enumerate(self.buttons):
            lead = i == self.default
            b = tk.Button(d, text=word, command=lambda word=word: self.pick(word), relief="flat",
                          bg=c["accent"] if lead else c["hover"], fg=c["field"] if lead else c["fg"],
                          activebackground=c["cap"], activeforeground=c["fg"])
            b.grid(row=1, column=i, sticky="w", padx=(14 if i == 0 else 6, 14 if i == last else 0), pady=(0, 14))
            self.made.append(b)
        self.bind_keys(d)
        self.fit(c, font, s)

    def wrap_width(self, measure, s):
        """The width in pixels the text wraps at at the scale s, WRAP scaled,
        or the width of the text's widest line that is no wider than
        WRAP_MOST scaled, so a line the lens broke on purpose shows whole and
        a long paragraph wraps as before. measure gives a line's width in
        pixels in the dialog's font. See wrap_of."""
        return wrap_of(self.text.split("\n"), measure, s)

    def sign(self, top, c, s):
        """The sign of the message's kind at the left of its text, see SIGNS,
        where the machine has Windows' icon font. A dialog asked with no kind,
        or on a machine without the font, has none."""
        glyph, role = SIGNS.get(str(self.icon or ""), (None, None))
        family = sign_family(top) if glyph else None
        if family is None:
            return None
        label = tk.Label(top, text=glyph, bg=c["bg"], fg=c[role], font=(family, -scale.px(SIGN_SIZE, s)))
        label.pack(side="left", anchor="n", padx=(0, 12))
        return label

    def fit(self, c, font, s):
        """A text too tall for the screen, such as a long error, shows in a box
        of its own that scrolls, as many lines tall as the monitor has room
        for, so the buttons stay in view. Any other shows whole."""
        d = self.win
        d.update_idletasks()
        room = win.work_area(*self.anchor())[3] - 2 * scale.px(MARGIN, s)
        if d.winfo_reqheight() <= room:
            return
        rest = d.winfo_reqheight() - self.body.winfo_reqheight()
        lines = max(4, (room - rest) // max(1, font.metrics("linespace")))
        self.body.destroy()
        box = self.body = tk.Frame(self.top, bg=c["bg"])
        box.pack(side="left", fill="both", expand=True)
        text = tk.Text(box, width=max(40, self.wrap // max(1, font.measure("0"))), height=lines, wrap="word",
                       bg=c["bg"], fg=c["fg"], font=FONT, relief="flat", bd=0, highlightthickness=0,
                       selectbackground=c["hover"], selectforeground=c["fg"], insertwidth=0)
        bar = tk.Scrollbar(box, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.insert("1.0", self.text)
        text.configure(state="disabled")
        text.bind("<<Copy>>", self.copy)    # ahead of the Text's own copy, which would copy for Tk alone
        text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

    def anchor(self):
        """The point the dialog goes over the middle of. That is its parent's
        middle where the parent is in view, as Settings is when it asks, and
        else the middle of the work area of the monitor the pointer is on."""
        try:
            top = self.parent.winfo_toplevel() if self.parent is not None else None
            if top is not None and top.winfo_viewable() and top.state() == "normal":
                return (top.winfo_rootx() + top.winfo_width() // 2, top.winfo_rooty() + top.winfo_height() // 2)
        except (tk.TclError, AttributeError):
            pass
        x, y = self.win.winfo_pointerxy()
        left, top_, width, height = win.work_area(x, y)
        return left + width // 2, top_ + height // 2

    def place(self):
        """Over the middle of anchor, kept inside that monitor's work area, as
        Lens._place_over_lens places a dialog over the lens, or where the
        dialog was given what places it, as Lens._ask gives that very
        function, by that."""
        if self.placer is not None:
            self.placer(self.win)
            return
        d = self.win
        d.update_idletasks()
        wd, ht = d.winfo_reqwidth(), d.winfo_reqheight()
        cx, cy = self.anchor()
        left, top, width, height = win.work_area(cx, cy)
        x = max(left, min(cx - wd // 2, left + width - wd))
        y = max(top, min(cy - ht // 2, top + height - ht))
        d.geometry("+%d+%d" % (x, y))

    def show(self):
        """Dress the dialog while it is unseen, place it, and show it. wm state
        normal shows a window as Tk shows one it maps for the first time, on
        top and not made active, where wm deiconify would also ask Windows for
        the foreground. Then hold takes the grab, which keeps clicks off the
        rest of the lens while the dialog is up, the keyboard goes to the
        default button only where the lens has it already, and Windows' own
        sound for the message's kind plays."""
        d = self.win
        d.update_idletasks()            # Tk makes the window with the frame now, hidden while withdrawn
        win.dress(d, self.look)
        if not self.escape:
            try:
                win.no_close(d)         # a question with no answer for it, see quit
            except Exception:
                pass
        self.place()
        d.update_idletasks()            # its place, given while it was withdrawn, before it is seen
        d.state("normal")
        self.hold()
        self.made[self.default].focus_set()
        try:
            win.beep(self.icon)
        except Exception:
            pass

    def hold(self):
        """Take Tk's grab, and keep which window had the keyboard in the lens
        and which held the grab before, which close gives back, as Tk's own
        dialogs keep them (tk::SetFocusGrab). Tk does not stack grabs, so a
        message over the update offer would otherwise leave the offer without
        its grab once the message closes."""
        d = self.win
        try:
            focus = str(d.tk.call("focus"))
            held = str(d.tk.call("grab", "current", d._w))
            self.before = (focus, held, str(d.tk.call("grab", "status", held)) if held else "")
        except tk.TclError:
            self.before = None
        try:
            d.grab_set()
        except tk.TclError:
            pass

    def pick(self, word):
        """The answer, the words of the button pressed or cancel, and the
        dialog closed."""
        if self.answered:
            return
        self.answer, self.answered = word, True
        self.close()

    def quit(self):
        """Escape or the close button, which give cancel, the answer that
        stands for no. A question with no such answer, a Yes and No question,
        does nothing, as Windows' own box does nothing, so the person picks."""
        if self.escape:
            self.pick(self.cancel)

    def keys(self):
        """The keys that press a button, as KEYS gives them, by the button's
        place in the row."""
        return {KEYS[word]: i for i, word in enumerate(self.buttons) if word in KEYS}

    def press(self, button):
        button.invoke()
        return "break"

    def enter(self, event=None):
        """Enter presses the button that has the keyboard, else the default one."""
        try:
            got = self.win.focus_get()
        except (KeyError, tk.TclError):
            got = None
        (got if any(got is b for b in self.made) else self.made[self.default]).invoke()
        return "break"

    def words(self):
        """The message as Windows' own boxes copy theirs, the title, the text
        and the buttons' words between rules, with Windows' line ends."""
        lines = [RULE, self.title, RULE, self.text, RULE, "".join("%s   " % b for b in self.buttons), RULE, ""]
        return "\n".join(lines).replace("\r\n", "\n").replace("\n", "\r\n")

    def copy(self, event=None):
        """Ctrl+C or Ctrl+Insert. The words selected in the box a long text
        scrolls in or in a path's field, where some are, and else the whole
        message as words gives it, go on the clipboard at once, so they are
        still there after the lens has quit, as after _fatal. Where that cannot
        be done they go on Tk's own clipboard, which holds them while the lens
        runs."""
        what = None
        widget = getattr(event, "widget", None)
        if isinstance(widget, tk.Text):
            try:
                what = widget.get("sel.first", "sel.last")
            except tk.TclError:
                what = None
        elif isinstance(widget, tk.Entry):
            try:
                if widget.selection_present():
                    what = widget.get()[int(widget.index("sel.first")):int(widget.index("sel.last"))]
            except tk.TclError:
                what = None
        what = (what or self.words()).replace("\r\n", "\n")
        try:
            done = win.copy_text(win.wrapper(self.win), what.replace("\n", "\r\n"))
        except Exception:
            done = False
        if not done:
            try:
                self.win.clipboard_clear()
                self.win.clipboard_append(what)
            except tk.TclError:
                pass
        return "break"

    def close(self):
        """The dialog closed, once, with the keyboard and the grab given back
        as hold kept them. The keyboard goes back only where the lens has it,
        as Tk moves it, and the grab only to a window still there and in
        view."""
        d = self.win
        if d is None or self.closed:
            return
        self.closed = True
        before, self.before = self.before, None
        if before is not None:
            focus, held, status = before
            if focus:
                try:
                    d.tk.call("focus", focus)
                except tk.TclError:
                    pass
            try:
                d.tk.call("grab", "release", d._w)
            except tk.TclError:
                pass
        try:
            if d.winfo_exists():
                d.destroy()
        except tk.TclError:
            pass
        if before is not None and before[1]:
            focus, held, status = before
            try:
                if int(d.tk.call("winfo", "exists", held)) and int(d.tk.call("winfo", "ismapped", held)):
                    if status == "global":
                        d.tk.call("grab", "-global", held)
                    else:
                        d.tk.call("grab", held)
            except (tk.TclError, ValueError):
                pass


def ask(title, text, buttons, parent=None, look=None, default=0, cancel=None, icon=None, detail=None,
        escape=True, form=None, place=None):
    """The lens's dialog with this title, text and buttons, see Dialog, and the
    words of the button pressed, or cancel where Escape is pressed or the
    window is closed. default is the index of the button Enter presses to
    begin with, drawn in the accent. icon is the kind of message, info,
    warning, question or error, whose sign and sound it takes. parent is the
    window it belongs to, the lens's root where none is given. escape False
    makes Escape and the close button do nothing, for a question that has no
    answer for them. form is ask for a question Lens._ask asks, whose first
    paragraph a drawn look draws as its head, see FORMS, and place is what
    places the window where it is not to be placed over its parent, as
    Lens._place_over_lens places Lens._ask's over the lens."""
    return Dialog(title, text, buttons, parent, look, default, cancel, icon, detail, escape, form, place).run()


class Messages(object):
    """Stands in for tkinter.messagebox in the lens. askyesno, showinfo,
    showwarning and showerror take its arguments and give its answers, and
    show the lens's own dialog in the look. Where that dialog cannot be shown
    the fallback, tkinter.messagebox itself, shows Windows' own box instead,
    and the lens's log says why in one line. A call with an option the
    stand-in does not know goes to the fallback too, and so does anything
    else of tkinter.messagebox. dialog is the function that shows the dialog,
    ask unless a check gives a stand-in of its own. A test may set any of the
    four on the stand-in, as on the module it stands in for."""

    def __init__(self, fallback, look=None, dialog=None):
        self.fallback, self.look, self.dialog = fallback, look, dialog or ask

    def __getattr__(self, name):
        fallback = self.__dict__.get("fallback")
        if fallback is None or name.startswith("__"):
            raise AttributeError(name)
        return getattr(fallback, name)

    def askyesno(self, title=None, message=None, **options):
        """True for Yes and False for No. Escape and the close button do
        nothing, as on Windows' own Yes and No box, so the person picks one. A
        dialog gone with no answer gives False."""
        done, word = self._show(title, message, options, (YES, NO), None, "question", False)
        if not done:
            return self.fallback.askyesno(title, message, **options)
        return word == YES

    def showinfo(self, title=None, message=None, **options):
        return self._tell("showinfo", title, message, options, "info")

    def showwarning(self, title=None, message=None, **options):
        return self._tell("showwarning", title, message, options, "warning")

    def showerror(self, title=None, message=None, **options):
        return self._tell("showerror", title, message, options, "error")

    def _tell(self, name, title, message, options, icon):
        done, _word = self._show(title, message, options, (OK,), OK, icon, True)
        if not done:
            return getattr(self.fallback, name)(title, message, **options)
        return "ok"

    def _show(self, title, message, options, buttons, cancel, icon, escape):
        """(True, the answer) once the lens's dialog has answered, or (False,
        None) where the fallback is to show its box instead."""
        if any(k not in OPTIONS for k in options):
            return False, None
        want = str(options.get("default") or "").lower()
        default = next((i for i, b in enumerate(buttons) if b.lower() == want), 0)
        try:
            return True, self.dialog(title, message, buttons, parent=options.get("parent"), look=self.look,
                                     default=default, cancel=cancel, escape=escape,
                                     icon=options.get("icon") or icon, detail=options.get("detail"))
        except Exception as exc:
            try:
                print("the lens's own dialog could not be shown (\"%s\"), so Windows' own box shows instead"
                      % (str(exc) or type(exc).__name__), flush=True)
            except Exception:
                pass                # an output that cannot take the error's words must not stop the message
            return False, None


# ---- the parts of a drawn dialog, and the windows the lens makes like it

def footer(window, look, words, commands, default, form, row=1):
    """The footer of a drawn dialog on its window's grid row row, as the
    look's dialog drawings draw it, in its ground with a rule along its top,
    see GROUNDS, and the buttons with these words and commands at its right,
    in the look's order, see screen_order, the default one the primary, and
    on one of them the key cap the look draws, see caps_of. Returns the
    footer and the buttons in the order of words."""
    kind = look.kind
    s = look.scale_for(window)
    height, left, right, gap = SIZES[kind]["footer"]
    ground, rule = GROUNDS[kind]["footer"]
    foot = tk.Frame(window, bg=colour_of(look, ground), bd=0, highlightthickness=0)
    foot.grid(row=row, column=0, sticky="we")
    foot.columnconfigure(0, weight=1, minsize=scale.px(left, s))
    widgets.Rule(foot, look, rule).grid(row=0, column=0, columnspan=len(words) + 1, sticky="we")
    caps = caps_of(kind, form, len(words), default)
    made = []
    for i, word in enumerate(words):
        primary = i == default
        made.append(widgets.CapButton(foot, look, text=word, command=commands[i], key=caps.get(i), primary=primary,
                                      sizes=None if primary else SECONDARY.get(kind)))
    room = scale.px(height, s) - 1 - max(b.winfo_reqheight() for b in made)
    order = screen_order(kind, len(words))
    for col, i in enumerate(order, start=1):
        made[i].grid(row=1, column=col, padx=(0 if col == 1 else scale.px(gap, s),
                                             scale.px(right, s) if col == len(order) else 0),
                     pady=(room // 2, room - room // 2))
    return foot, made


def path_field(master, look, path, s, copy=None):
    """A path in a field of its own, in which it can be selected and copied,
    in the look's type, ground and edge, see TYPE and GROUNDS, as wide as the
    path up to the width a text wraps at. copy is what Ctrl+C does in it, the
    dialog's own copy."""
    kind, c = look.kind, look.c
    role, colour = TYPE[kind]["path"]
    ground_role, edge_role = GROUNDS[kind]["path"]
    ground = colour_of(look, ground_role)
    edge = c[edge_role] if edge_role else ground
    ypad, xpad = SIZES[kind]["path_pad"]
    box = tk.Frame(master, bg=ground, bd=0, highlightthickness=1 if edge_role else 0, highlightbackground=edge,
                   highlightcolor=edge)
    font = look.font(role, widget=master)
    measure = measuring(master, font)
    most = scale.px(SIZES[kind]["wrap"], s) - 2 * scale.px(xpad, s)
    field = tk.Entry(box, bg=ground, readonlybackground=ground, fg=c[colour], font=font, relief="flat", bd=0,
                     highlightthickness=0, selectbackground=c["lit"], selectforeground=c["strong"],
                     insertbackground=c[colour], width=max(4, min(measure(path), most) // max(1, measure("0")) + 1))
    field.insert(0, path)
    field.configure(state="readonly")
    if copy is not None:
        field.bind("<<Copy>>", copy)
    field.pack(fill="x", padx=scale.px(xpad, s), pady=scale.px(ypad, s))
    return box


def name_box(d, look, words, var, buttons):
    """New profile in a drawn look, built in its window d, which the lens has
    made withdrawn: its words over the field, which holds var, each in the
    look's type, see TYPE, the field in the look's well with its edge, which
    lights while the field has the keyboard, see GROUNDS, and the buttons in
    the look's footer, buttons being ((words, command), ...), Save first,
    which is the primary. Return in the field does what the first does, as in
    the classic look, which takes the event as its sign that Enter saved,
    and Escape does what the last does, Cancel, as the drawings show.
    Returns the field."""
    kind, c, m = look.kind, look.c, SIZES[look.kind]
    s = look.scale_for(d)
    above, side, below = m["ask_pad"]
    height, inset, gap = m["field"]
    ground, edge, lit = GROUNDS[kind]["field"]
    d.configure(bg=c["surface"])
    d.columnconfigure(0, weight=1)
    body = tk.Frame(d, bg=c["surface"], bd=0, highlightthickness=0)
    body.grid(row=0, column=0, sticky="nsew")
    body.columnconfigure(0, weight=1)
    role, colour = TYPE[kind]["label"]
    tk.Label(body, text=words, bg=c["surface"], fg=c[colour], font=look.font(role, widget=d), justify="left",
             anchor="w", bd=0, padx=0, pady=0).grid(row=0, column=0, sticky="w", padx=scale.px(side, s),
                                                    pady=(scale.px(above, s), 0))
    ring = scale.border(m["field_ring"], s)
    well = tk.Frame(body, bg=c[ground], height=scale.px(height, s), bd=0, highlightthickness=ring,
                    highlightbackground=c[edge], highlightcolor=c[edge])
    role, colour = TYPE[kind]["field"]
    field = tk.Entry(well, textvariable=var, width=32, bg=c[ground], fg=c[colour], insertbackground=c[colour],
                     relief="flat", bd=0, highlightthickness=0, selectbackground=c["lit"],
                     selectforeground=c["strong"], font=look.font(role, widget=d))
    well.configure(width=field.winfo_reqwidth() + 2 * scale.px(inset, s) + 2 * ring)
    well.pack_propagate(False)
    field.pack(fill="x", expand=True, padx=scale.px(inset, s))
    well.grid(row=1, column=0, sticky="we", padx=scale.px(side, s), pady=(scale.px(gap, s), scale.px(below, s)))
    field.bind("<FocusIn>", lambda event: well.configure(highlightbackground=c[lit]), add="+")
    field.bind("<FocusOut>", lambda event: well.configure(highlightbackground=c[edge]), add="+")
    commands = [command for _words, command in buttons]
    footer(d, look, [said for said, _command in buttons], commands, 0, "name")
    field.bind("<Return>", commands[0])
    d.bind("<Escape>", lambda event: commands[-1]())
    return field


class Progress(object):
    """The download box in a drawn look: its words in the look's type, see
    TYPE, with the room round them that the drawings give, and in Slate and
    Industrial a bar under them whose fill follows the percentage the words
    end in as the lens writes them, see percent_of. The lens's own label keeps
    its words and is told to the bar by widgets.observe. Where it cannot be
    drawn, the box and the label are put back as the lens made them and the
    fault is raised, for the lens to say once and leave the box as in the
    classic look."""

    def __init__(self, box, look, note):
        self.fill, self.made = None, []
        kind, c, m = look.kind, look.c, SIZES[look.kind]
        s = look.scale_for(box)
        role, colour = TYPE[kind]["status"]
        above, side, below = m["progress_pad"]
        info = note.grid_info()
        kept = (box.cget("bg"), {k: note.cget(k) for k in ("bg", "fg", "font")},
                {k: info[k] for k in ("padx", "pady") if k in info})
        try:
            font = look.font(role, widget=box)
            bar, spec = m["progress"], GROUNDS[kind]["progress"]
            box.configure(bg=c["surface"])
            note.configure(bg=c["surface"], fg=c[colour], font=font)
            note.grid_configure(padx=scale.px(side, s),
                                pady=(scale.px(above, s), 0 if bar and spec else scale.px(below, s)))
            if bar and spec:
                height, gap = bar
                ground, edge, fill = spec
                trough = tk.Frame(box, bg=c[edge or ground], height=scale.px(height, s), bd=0, highlightthickness=0)
                self.made.append(trough)
                inner = trough
                if edge:
                    inner = tk.Frame(trough, bg=c[ground], bd=0, highlightthickness=0)
                    inner.place(x=1, y=1, relwidth=1, relheight=1, width=-2, height=-2)
                self.fill = tk.Frame(inner, bg=c[fill], bd=0, highlightthickness=0)
                trough.grid(row=1, column=0, sticky="we", padx=scale.px(side, s),
                            pady=(scale.px(gap, s), scale.px(below, s)))
            widgets.observe(note).followers.append(self.follow)
            self.show(percent_of(note.cget("text")))
        except Exception:
            self.undo(box, note, kept)
            raise

    def undo(self, box, note, kept):
        """The box and the label as the lens made them, before the fault."""
        ground, opts, pads = kept
        for made in self.made:
            try:
                made.destroy()
            except tk.TclError:
                pass
        self.fill, self.made = None, []
        for name in ("configure", "config", "followers"):
            note.__dict__.pop(name, None)
        try:
            box.configure(bg=ground)
            note.configure(**opts)
            note.grid_configure(**pads)
        except tk.TclError:
            pass

    def follow(self, widget, keys, lit_changed):
        """The bar again, where the code gave the label new words."""
        if "text" in keys:
            self.show(percent_of(widget.cget("text")))

    def show(self, percent):
        """The bar's fill as long as the percentage of its width."""
        if self.fill is None:
            return
        try:
            if percent > 0:
                self.fill.place(x=0, y=0, relheight=1, relwidth=min(100, percent) / 100.0)
            else:
                self.fill.place_forget()
        except tk.TclError:
            pass


class SetupShell(object):
    """The stack setup's window in a drawn look, laid out as the look's
    dialogs, since no drawing draws it: its words in the dialogs' type, the
    folder it installs into, the names of NVIDIA's files and the log in a
    mono type, see MONO, the fields as Settings' fields and the log in the
    look's well, Browse as a button of a page of Settings, and Set it up and
    Not now in the dialogs' footer in the look's order, Set it up the
    primary, with the status at its left. The stack setup makes it before its
    window's parts, so the footer made then lies under the parts it takes,
    and finishes it once they are made. Every word stays the stack setup's
    own, Industrial's buttons drawn in its capitals, and the buttons keep
    their commands and states. Where it cannot be finished the window stays
    as the stack setup made it, in the theme's colours, and lens.log says so
    once, see SETUP_FAULT."""

    # the fonts the stack setup gives its labels, as Tk gives them back, and
    # the type each takes, see finish
    FONTS = {("Segoe UI", "10"): "text", ("Consolas", "9"): "mono", ("Segoe UI", "9"): "detail"}
    # the room the stack setup puts at the window's sides and at its top
    EDGE = 14

    def __init__(self, window, look):
        self.window, self.look = window, look
        # the scale and the faces of the look, taken from this window's Tk
        # where the stack setup made its own root, from the Start Menu, as
        # the lens binds the look to each root it makes, see Look.bind
        look.bind(window)
        ground, rule = GROUNDS[look.kind]["footer"]
        self.foot = tk.Frame(window, bg=colour_of(look, ground), bd=0, highlightthickness=0)
        self.rule = widgets.Rule(self.foot, look, rule)

    def finish(self, go, status, log):
        """The window's parts dressed and laid out, see the class, go being
        Set it up, status the status and log the log. Returns whether it
        was. Never raises."""
        if SETUP_FAULT:
            return False
        try:
            steps = self.steps(go, status, log)
        except Exception as exc:
            say_fault(SETUP_FAULT, "stack setup's window", self.look, exc)
            return False
        for step in steps:
            try:
                step()
            except tk.TclError:
                pass
        return True

    def steps(self, go, status, log):
        """What finish does, each a call made once all of them are worked
        out, so a fault in working them out leaves the window as it was."""
        from lens_look import settings     # Browse as the pages of Settings draw it
        look, w = self.look, self.window
        kind, c, m = look.kind, look.c, SIZES[look.kind]
        s = look.scale_for(w)
        above = SIZES[kind]["pad"][0]
        side = SIZES[kind]["pad"][1]
        fonts = {"text": look.font("dialog_text", widget=w), "mono": look.face_font(MONO[kind], widget=w),
                 "detail": look.font("dialog_detail", widget=w)}
        steps, browse, later = [], [], None
        for child in w.winfo_children():
            if child is self.foot or child is status:
                continue
            made = child.winfo_class()
            if made == "Label":
                font = fonts.get(self.FONTS.get(tuple(str(v) for v in child.tk.splitlist(child.cget("font")))))
                if font is not None:
                    opts = {"font": font}
                    wrap = child.winfo_pixels(child.cget("wraplength"))
                    if wrap:
                        opts["wraplength"] = scale.px(wrap, s)
                    steps.append(lambda child=child, opts=opts: child.configure(**opts))
            elif made == "Entry":
                steps.append(lambda child=child, opts=widgets.field_options(look): child.configure(**opts))
            elif child is log:
                opts = dict(bg=c["well"], fg=c["text"], insertbackground=c["text"], selectbackground=c["lit"],
                            selectforeground=c["strong"], font=fonts["mono"], relief="flat", bd=0,
                            padx=scale.px(10, s), pady=scale.px(8, s),
                            highlightthickness=0 if kind == "console" else 1, highlightbackground=c["edge"],
                            highlightcolor=c["edge"])
                steps.append(lambda child=child, opts=opts: child.configure(**opts))
            elif made == "Button" and child is not go:
                if str(child.cget("text")) == "Browse":
                    browse.append(child)
                else:
                    later = child
        # the room round the parts, the stack setup's sides and top the dialogs'
        for slave in w.grid_slaves():
            if slave in (status, go, later):
                continue
            info = slave.grid_info()
            row = int(info.get("row", 0))
            padx, pady = pair(info.get("padx", 0)), pair(info.get("pady", 0))
            new_x = tuple(scale.px(side, s) if v == self.EDGE else scale.px(v, s) for v in padx)
            new_y = (scale.px(above, s) if row == 0 and pady[0] == self.EDGE else scale.px(pady[0], s),
                     scale.px(pady[1], s))
            steps.append(lambda slave=slave, x=new_x, y=new_y: slave.grid_configure(padx=x, pady=y))
        for button in browse:
            steps += self.button(button, "page", settings)
        if go is not None:
            steps += self.button(go, "primary", settings)
        if later is not None:
            steps += self.button(later, "secondary", settings)
        # the footer, with the status at its left and the buttons at its right
        height, left, right, gap = m["footer"]
        ground = colour_of(look, GROUNDS[kind]["footer"][0])
        ordered = [b for b in (go, later) if b is not None]
        ordered = [ordered[i] for i in screen_order(kind, len(ordered))]
        tall = scale.px(widgets.BUTTONS[kind]["h"], s)
        room = scale.px(height, s) - 1 - tall
        steps.append(lambda: self.foot.grid(row=10, column=0, columnspan=3, sticky="we",
                                            pady=(scale.px(self.EDGE, s), 0)))
        steps.append(lambda: self.foot.columnconfigure(1, weight=1))
        steps.append(lambda: self.rule.grid(row=0, column=0, columnspan=len(ordered) + 2, sticky="we"))
        steps.append(lambda: status.configure(bg=ground, font=fonts["detail"]))
        steps.append(lambda: status.grid(in_=self.foot, row=1, column=0, sticky="w",
                                         padx=(scale.px(left, s), scale.px(gap, s))))
        for col, button in enumerate(ordered, start=2):
            pad = (0 if col == 2 else scale.px(gap, s), scale.px(right, s) if col == len(ordered) + 1 else 0)
            steps.append(lambda button=button, col=col, pad=pad: button.grid(
                in_=self.foot, row=1, column=col, padx=pad, pady=(room // 2, room - room // 2)))
        return steps

    def button(self, button, which, settings):
        """The steps that dress one of the stack setup's buttons: primary Set
        it up, secondary Not now, page Browse. Each is sized to its words, as
        CapButton and settings.PageButton size theirs, and the words the stack
        setup gives it later, such as Installing..., are drawn in the look's
        case and sized again."""
        look, kind = self.look, self.look.kind
        s = look.scale_for(button)
        role = "page_button" if which == "page" else "button"
        primary = which == "primary"
        if which == "page":
            face, ink, edge, pressed = settings.page_button_colours(look)
            height, pad = settings.ROWS[kind]["button"]
            least, pads = 0, (pad, pad)
        else:
            face, ink, edge, pressed = widgets.button_colours(look, primary)
            sizes = dict(widgets.BUTTONS[kind], **({} if primary else SECONDARY.get(kind, {})))
            height, least, pads = sizes["h"], sizes["least"], sizes["pad"]
        font = look.font(role, primary, widget=button)
        case = look.fonts[role].case
        opts = dict(bg=face, fg=ink, activebackground=pressed, activeforeground=ink, relief="flat", overrelief="",
                    bd=0, highlightthickness=1 if edge else 0, font=font,
                    disabledforeground=tokens.mix(face, ink, 0.5))
        if edge:
            opts.update(default="active", highlightcolor=edge, highlightbackground=edge)
        own = button.configure

        def fit():
            words = int(button.tk.call("font", "measure", font, tk.Misc.cget(button, "text")))
            ring = 1 if edge else 0
            widgets.exact(button, max(scale.px(least, s), 2 * ring + words + scale.px(pads[0], s)
                                      + scale.px(pads[1], s)), scale.px(height, s))

        def configure(cnf=None, **kw):
            if (cnf is None and not kw) or isinstance(cnf, str):
                return own(cnf)
            given = dict(cnf or {})
            given.update(kw)
            if "text" in given:
                given["text"] = text.display_case(given["text"], case)
            got = own(given)
            if "text" in given:
                fit()
            return got

        def cased():
            button.configure = button.config = configure

        return [lambda: own(opts), lambda: own(text=text.display_case(tk.Misc.cget(button, "text"), case)), fit,
                cased]
