"""The lens menu and its lists in a drawn look, the style list and the two
profile lists, as Slate-Menus, Paper-Menus and Industrial-Menus draw them.

PopupMenu.open makes the entries here in place of today's, in the same
window of the lens's own, see PopupMenu._open_drawn. Each entry is a State
Label, see lens_look.widgets, a child of the menu's box as today's entries
are, with the whole text the code built as its own. So the lens's log, its
keys and the tests read the texts, the colours and the clicks they always
read. The entry draws its words alone, and its other parts lie inside it:
the bar a lit entry has at its left, the keys as caps with the hint's words
in Slate and Paper or the hint in its brackets in Industrial, and the check
mark after the chosen name in a list. PopupMenu.light lights an entry by the
hover colour as it always did, and the entry then paints its row in the
look's lit colour with its bar, see Menu._paint. Tk draws an entry again
over the parts inside it, so they are drawn again after it, see Menu._again.

The lens menu's version, and over a fullscreen lens its readout, are a band
at its head in Slate and Industrial and its first lines in Paper. They stay
the first Labels of the box, so the readout is still the second, which the
lens keeps current while the menu is open.

The pointer moving from an entry onto one of its parts does not leave the
entry, so a lit entry does not flicker as the pointer crosses it. The menu
is a window of the lens's own that never takes the keyboard, so nothing here
gives anything the keyboard or binds a key.

Imports tkinter and the package, and nothing of the lens.
"""
import tkinter as tk

from lens_look import scale as sc
from lens_look import text, widgets

# The menus' sizes in CSS pixels at 100 percent, from the drawings, by kind.
#   entry_h     an entry's height
#   left, right the room before an entry's words, taking in the 3 pixel bar a
#               lit entry has, and after its last part
#   bar_inset   how far the bar stands in from the entry's top and foot
#   body        the room above and under the entries, and at their sides
#   sep         the room at a separator's sides and above and under it, and
#               sep_role the role of its colour
#   band        whether the lens menu's version and readout are a band at its
#               head, band_pad the room before and after their words, band_line
#               a line's height, band_pad_y the room over the first line and
#               under the last, band_one a band of one line's height where it is
#               not those added, band_rule the role of the line under the band
#   head_role   the type of the version and the readout
#   collapse    whether the version shows with one space before its brackets,
#               as Slate and Paper write it, where Industrial keeps the code's
#   words_w     the least width of the words of an entry with a hint in a
#               column, Paper's and Industrial's, 0 for none
#   hint_gap    the room before a hint, at the least before Slate's, which
#               stands at the right
#   part_gap    the room between the parts of Slate's and Paper's hints
#   caps_gap    the room before Paper's caps, which stand at the right
#   lit_cap     the role of a cap's fill on a lit entry, None for its own
#   tick        the check mark's size, where it stands, at the right or after
#               the name, the room before it, and the role of its colour
#   least       the lens menu's least width, its border taken in, 0 for none
MENU = {
    "console": dict(entry_h=34, left=16, right=12, bar_inset=8, body=(6, 6), sep=(10, 4), sep_role="rule",
                    band=True, band_pad=(22, 16), band_line=18, band_pad_y=9, band_one=0, band_rule="rule",
                    head_role="menu_hint", collapse=True, words_w=0, hint_gap=24, part_gap=6, caps_gap=0,
                    lit_cap="surface", tick=(12, "right", 16, "strong"), least=520),
    "folio": dict(entry_h=32, left=14, right=14, bar_inset=0, body=(6, 0), sep=(14, 4), sep_role="rule",
                  band=False, band_pad=(14, 14), band_line=0, band_pad_y=0, band_one=0, band_rule="rule",
                  head_role="menu_hint", collapse=True, words_w=214, hint_gap=0, part_gap=6, caps_gap=12,
                  lit_cap=None, tick=(10, "after", 10, "text"), least=410),
    "industrial": dict(entry_h=30, left=16, right=16, bar_inset=0, body=(4, 0), sep=(0, 4), sep_role="edge",
                       band=True, band_pad=(16, 16), band_line=26, band_pad_y=2, band_one=30, band_rule="edge",
                       head_role="version", collapse=False, words_w=226, hint_gap=12, part_gap=6, caps_gap=0,
                       lit_cap=None, tick=(12, "after", 12, "accent"), least=0),
}

# The colour a menu entry draws for the hover colour PopupMenu.light gives the
# entry it lights, the look's lit colour, whatever else of the theme's ten
# colours the hover colour is too
ROLES = {"bg": {"hover": "lit"}}


def takes_hints(name):
    """Whether the entries of a menu of this name have hints, which only the
    lens menu's have. The lists' entries are names and what can be done with
    them, whose words can hold a name with brackets of its own."""
    return name == "menu"


def rows_of(name, items, band):
    """The rows of a menu or a list as a drawn look lays them out, from the
    items the code gives PopupMenu.open, each (text, command, enabled), or
    None for a separator. Each row is (what, n, item), what being head for a
    line of the lens menu's head, name for a name in a list, entry for any
    other entry, or sep for a separator, and n the entry's place among the
    entries as PopupMenu numbers them, None for a separator. The head is the lens
    menu's first entries that do nothing, its version and over a fullscreen
    lens its readout. band leaves out the separators right after the head,
    for the band's line stands for them. The style list's entries are all
    names, and a profile list's those before its first separator, where it
    has one."""
    items = list(items)
    head = 0
    if name == "menu":
        while head < len(items) and items[head] is not None and items[head][1] is None and not items[head][2]:
            head += 1
    naming = name == "style list" or (name == "profile list" and None in items)
    rows, n = [], 0
    for i, item in enumerate(items):
        if item is None:
            if name == "profile list":
                naming = False
            if not (band and 0 < head <= i and all(x is None for x in items[head:i + 1])):
                rows.append(("sep", None, None))
            continue
        rows.append(("head" if i < head else "name" if naming else "entry", n, item))
        n += 1
    return rows


def entry_parts(label, hints, menu_hints):
    """What a drawn look draws of an entry the code built, as (its words, the
    parts after them in their order, whether a tick follows the name). Each
    part is (key, or, or hint, its words). menu_hints is the look's way with
    them, see tokens.FLAGS. caps draws each key as a cap with the hint's words
    beside the caps, and the word or between two of them where the text has
    it. brackets, and text, show the brackets as the text has them. hints
    False takes the entry as a name, see text.split_menu_text."""
    mt = text.split_menu_text(label, hints)
    tick = bool(mt.tick)
    if mt.inner is None:
        return mt.words, (), tick
    if menu_hints != "caps":
        return mt.words, (("hint", "(%s)" % mt.inner),), tick
    parts = []
    for kind, words, sep in mt.items:
        if parts and sep.strip() == "or":
            parts.append(("or", "or"))
        parts.append((kind, words))
    return mt.words, tuple(parts), tick


def column_and_caps(parts):
    """Paper's way with an entry's parts, as (the hint's words, which stand in
    the column, the keys, which stand at the right with the word or between
    two of them where the text has it)."""
    words, caps = [], []
    for i, (kind, part) in enumerate(parts):
        if kind == "hint":
            words.append(part)
        elif kind == "key":
            if caps and parts[i - 1][0] == "or":
                caps.append(("or", "or"))
            caps.append((kind, part))
    return ", ".join(words), tuple(caps)


def head_words(label, collapse=True):
    """The version as the head shows it, with one space between its words
    where the look writes it so, as "Neural Lens 0.6.1 (beta)"."""
    return " ".join(str(label).split()) if collapse else label


def _inside(widget):
    """Every widget inside this one, its children and theirs."""
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out += _inside(child)
    return out


class _Row(object):
    """An entry as Menu draws it. label is its State Label and n its place
    among the entries, live whether it does something. bar is the bar a lit
    entry has, grounded the parts that take the row's colour, caps its key
    caps, column the hint's words in the column, group the parts at its
    right, which gap stands clear of and which group_w wide, tick the check
    mark after its name, ticked whether it has one, words_w the width of
    its words, lit or not, and again whether its parts are to be drawn again,
    see Menu._again."""

    def __init__(self, label, n, live):
        self.label, self.n, self.live = label, n, live
        self.bar = None
        self.grounded, self.caps = [], []
        self.column = self.group = self.tick = None
        self.gap = self.group_w = self.words_w = 0
        self.ticked = False
        self.again = False


class Menu(object):
    """A menu or a list in a drawn look, built in t, the window of the lens's
    own PopupMenu.open made for it, from the name and the items open was
    given. labels are the entries' Labels in PopupMenu's order, the head's
    lines first. enter(n), leave(n) and click(n) are called as the pointer
    comes onto entry n, leaves it and clicks it, for each entry that does
    something, on the entry and on each of its parts alike."""

    def __init__(self, t, look, name, items, enter=None, leave=None, click=None):
        self.look, self.name = look, name
        self.kind = widgets.kind_of(look)
        self.k, self.c = MENU[self.kind], look.c
        self.s = look.scale_for(t)
        self.enter, self.leave, self.click = enter, leave, click
        self.labels, self.rows = [], []
        k, c = self.k, self.c
        t.configure(bg=c["frame"])
        box = self.box = tk.Frame(t, bg=c["surface"], bd=0, highlightthickness=0)
        box.pack(padx=sc.hair(), pady=sc.hair())
        rows = rows_of(name, items, k["band"])
        heads = [row for row in rows if row[0] == "head"]
        if k["band"] and heads:
            self._band(heads)
        # the room above the entries, as wide as the lens menu is at the least
        least = self.px(k["least"]) - 2 * sc.hair() if name == "menu" and k["least"] else 0
        tk.Frame(box, width=max(0, least), height=self.px(k["body"][0]), bg=c["surface"], bd=0,
                 highlightthickness=0).pack(fill="x")
        for what, n, item in rows:
            if what == "sep":
                self._separator()
            elif what != "head" or not k["band"]:
                self._entry(what, n, item)
        tk.Frame(box, height=self.px(k["body"][0]), bg=c["surface"], bd=0, highlightthickness=0).pack(fill="x")
        self._lay_out()
        for row in self.rows:
            if row.live:
                self._bind(row)

    def px(self, n):
        return sc.px(n, self.s)

    def measure(self, font, words):
        """The width of words in a font, in pixels."""
        return int(self.box.tk.call("font", "measure", font, words))

    def _label(self, item, role, shown):
        """An entry's Label, a child of the box with the whole text the code
        built and the colours the classic menu gives it, which it draws as the
        look draws them, lit by the hover colour, see widgets.StateLabel."""
        words, _command, enabled = item
        legacy = self.look.legacy
        label = widgets.StateLabel(self.box, self.look, text=words, bg=legacy["bg"],
                                   fg=legacy["fg"] if enabled else legacy["dim"], roles=ROLES, lit=("bg", "hover"),
                                   shown=shown, font_role=role, anchor="w", bd=0, highlightthickness=0, padx=0,
                                   pady=0)
        self.labels.append(label)
        return label

    def _band(self, heads):
        """The lens menu's version and readout as the band at its head, Slate's
        and Industrial's, still the first Labels of the box, and the line under
        the band."""
        k, c = self.k, self.c
        left, right = self.px(k["band_pad"][0]), self.px(k["band_pad"][1])
        line, pad_y, last = k["band_line"], k["band_pad_y"], len(heads) - 1
        for i, (_what, _n, item) in enumerate(heads):
            shown = (lambda words: head_words(words)) if i == 0 and k["collapse"] else None
            label = self._label(item, k["head_role"], shown)
            label.set_ground(c["deep"])
            if not last:
                height, anchor = k["band_one"] or line + 2 * pad_y, "w"
            else:
                height = line + (pad_y if i in (0, last) else 0)
                anchor = "sw" if i == 0 else "nw" if i == last else "w"
            words = self.measure(widgets.real(label, "font"), label.drawn_text())
            label.configure(anchor=anchor)
            widgets.exact(label, left + words + max(left, right), self.px(height), padx=left)
            label.pack(fill="x")
        tk.Frame(self.box, bg=c[k["band_rule"]], height=sc.hair(), bd=0, highlightthickness=0).pack(fill="x")

    def _separator(self):
        k = self.k
        side, between = k["sep"]
        tk.Frame(self.box, bg=self.c[k["sep_role"]], height=sc.hair(), bd=0, highlightthickness=0).pack(
            fill="x", padx=self.px(k["body"][1] + side), pady=self.px(between))

    def _words(self, parent, words, row):
        """A hint's words, in the look's hint type and its muted colour."""
        label = tk.Label(parent, text=words, bg=self.c["surface"], fg=self.c["muted"],
                         font=self.look.font("menu_hint", False, parent), bd=0, highlightthickness=0, padx=0,
                         pady=0)
        row.grounded.append(label)
        return label

    def _group(self, label, parts, row, tick=None):
        """The parts that stand at an entry's right in their order, the hint's
        words and the keys as caps, and Slate's tick last."""
        c, gap = self.c, self.px(self.k["part_gap"])
        group = tk.Frame(label, bg=c["surface"], bd=0, highlightthickness=0)
        row.grounded.append(group)
        made = []
        for kind, part in parts:
            if kind == "key":
                widget = widgets.KeyCap(group, self.look, part, "cap_menu", ground=c["surface"])
                row.caps.append(widget)
            else:
                widget = self._words(group, part, row)
            made.append((widget, gap))
        if tick is not None:
            made.append((self._tick(group, row), self.px(self.k["tick"][2])))
        for i, (widget, before) in enumerate(made):
            widget.pack(side="left", padx=(before if i else 0, 0))
        row.group_w = sum(w.winfo_reqwidth() for w, _b in made) + sum(b for _w, b in made[1:])
        return group

    def _tick(self, parent, row):
        """The check mark of the chosen name in a list."""
        size, _where, _gap, role = self.k["tick"]
        font, char = widgets.glyph(parent, "check", self.px(size))
        tick = tk.Label(parent, text=char, font=font, fg=self.c[role], bg=self.c["surface"], bd=0,
                        highlightthickness=0, padx=0, pady=0)
        row.grounded.append(tick)
        return tick

    def _entry(self, what, n, item):
        """An entry as the look draws it: its Label with its words, and the
        parts inside it, the bar, the hint, the caps and the tick."""
        k, look = self.k, self.look
        words, command, enabled = item
        if what == "head":
            role, parts, ticked = k["head_role"], (), False
            shown = (lambda w: head_words(w)) if n == 0 and k["collapse"] else None
        else:
            role = "menu_profile" if what == "name" else "menu"
            hints = takes_hints(self.name)
            _shown, parts, ticked = entry_parts(words, hints, look.menu_hints)
            shown = (lambda w, hints=hints: entry_parts(w, hints, look.menu_hints)[0])
        label = self._label(item, role, shown)
        label.pack(fill="x", padx=self.px(k["body"][1]))
        row = _Row(label, n, bool(enabled and command is not None))
        row.ticked = ticked
        row.bar = tk.Frame(label, bg=self.c["accent"], width=self.px(widgets.BAR_WIDTH), bd=0,
                           highlightthickness=0)
        right = ticked and k["tick"][1] == "right"
        if parts and self.kind == "folio":
            column, caps = column_and_caps(parts)
            if column:
                row.column = self._words(label, column, row)
            if caps:
                row.group, row.gap = self._group(label, caps, row), self.px(k["caps_gap"])
        elif parts and self.kind == "console":
            row.group, row.gap = self._group(label, parts, row, tick=True if right else None), self.px(
                k["hint_gap"])
        elif parts:
            row.column = self._words(label, parts[0][1], row)
        if right and row.group is None:
            row.group, row.gap = self._group(label, (), row, tick=True), self.px(k["tick"][2])
        elif ticked and not right:
            row.tick = self._tick(label, row)
        shown_now = label.drawn_text()
        row.words_w = max(self.measure(look.font(role, lit, label), shown_now) for lit in (False, True))
        label.follow(lambda widget, keys, lit_changed, row=row: self._changed(row, lit_changed))
        label.bind("<Expose>", lambda event, row=row: self._again(row))
        if self.kind == "console" and ticked:
            label.picked(True)          # Slate draws the chosen name in its strong colour and semibold
        self.rows.append(row)

    def _lay_out(self):
        """Each entry's width and its parts' places: the hints of Paper and
        Industrial in a column clear of the widest words, the parts at the
        right where the look has them there, and the tick after the name."""
        k = self.k
        left, right, height = self.px(k["left"]), self.px(k["right"]), self.px(k["entry_h"])
        widest = max([self.px(k["words_w"])] + [row.words_w for row in self.rows if row.column is not None])
        hint_x = left + widest + self.px(k["hint_gap"])
        for row in self.rows:
            width = left + row.words_w
            if row.column is not None:
                width = hint_x + row.column.winfo_reqwidth()
                row.column.place(x=hint_x, rely=0.5, anchor="w")
            if row.group is not None:
                width += row.gap + row.group_w
                row.group.place(relx=1.0, x=-right, rely=0.5, anchor="e")
            if row.tick is not None:
                width += self.px(k["tick"][2]) + row.tick.winfo_reqwidth()
                self._place_tick(row)
            widgets.exact(row.label, max(width + right, 2 * left + row.words_w), height, padx=left)

    def _place_tick(self, row):
        """The tick right after the name, as wide as the name is drawn now."""
        if row.tick is None:
            return
        words = self.measure(widgets.real(row.label, "font"), row.label.drawn_text())
        row.tick.place(x=self.px(self.k["left"]) + words + self.px(self.k["tick"][2]), rely=0.5, anchor="w")

    def _paint(self, row):
        """An entry lit or unlit, as PopupMenu.light lights it by the hover
        colour: its parts on the look's lit colour or back on the surface, the
        bar, Slate's caps filled in its surface colour and its words in its
        strong colour, and the tick after the words in their weight now."""
        k, c = self.k, self.c
        on = row.label.is_lit
        ground = c["lit"] if on else c["surface"]
        if on:
            inset = self.px(k["bar_inset"])
            row.bar.place(x=0, y=inset, relheight=1, height=-2 * inset, bordermode="ignore")
        else:
            row.bar.place_forget()
        for part in row.grounded:
            part.configure(bg=ground)
        for cap in row.caps:
            fill = c[k["lit_cap"]] if on and k["lit_cap"] else None
            cap.colours = (fill,) + tuple(cap.colours[1:])
            cap.configure(bg=ground)
        if self.kind == "console":
            row.label.picked(on or row.ticked)
        self._place_tick(row)

    def _changed(self, row, lit_changed):
        """An entry changed through its configure, as PopupMenu.light changes
        each entry that does something: lit or unlit, its parts painted to
        match, see _paint, and drawn again once the entry has drawn itself."""
        if lit_changed:
            self._paint(row)
        self._again(row)

    def _again(self, row):
        """The parts inside an entry drawn again, once the entry has drawn
        itself. Tk draws an entry again after each change to it and as it
        comes into view, at its first idle moment, and draws it over the
        parts inside it, which do not draw themselves again then. Asked for
        more than once before then, they are drawn once. The root keeps the
        call, so a menu closed before then leaves no call behind that Tk
        could not make."""
        if row.again:
            return
        row.again = True

        def draw():
            row.again = False
            try:
                for part in _inside(row.label):
                    if part.winfo_ismapped():
                        part.configure(bg=part.cget("bg"))
            except tk.TclError:
                pass            # the menu closed before its first idle moment

        try:
            row.label._root().after_idle(draw)
        except tk.TclError:
            row.again = False

    def _bind(self, row):
        """The pointer and the click of an entry that does something, on the
        entry and on each of its parts. The entry does not take the pointer's
        move onto one of its parts as leaving it, which Tk tells by the detail
        NotifyInferior."""
        n, label = row.n, row.label

        def leave(detail):
            if detail != "NotifyInferior" and self.leave is not None:
                self.leave(n)

        def enter(event):
            if self.enter is not None:
                self.enter(n)

        def click(event):
            if self.click is not None:
                self.click(n)

        label.bind("<Enter>", enter)
        label.bind("<Leave>", "%s %%d" % label.register(leave))
        label.bind("<Button-1>", click)
        for part in _inside(label):
            part.bind("<Enter>", enter)
            part.bind("<Button-1>", click)
