"""The small windows of the lens in a drawn look, as the Fullscreen, Menus and
Dialogs boards of Slate, Paper and Industrial draw them: the note a lens
shows as it goes fullscreen, the notice at the top of its monitor, the
on-screen readout, the window an explanation shows in by the pointer, the
tab of a hidden title bar, the divider of the A/B split, the hint of an
attach pick and the sheet a region is dragged on.

The lens makes each of these windows as it always did, with its flags, its
place, its alpha and its timing, and what is built here goes inside it in
place of the few widgets the classic look puts there. What the lens and its
tests read of them is kept. The note's head is its first Label and its first
line the next, its lines of keys are a grid of two columns, the key a line
starts with as a cap in the first and the whole line, drawn without its key,
in the second, and its Don't show this again is a check button and its OK a
button. The notice's lines are the only Labels of its box, the window's
first child. The readout's words and an explanation's words are the window's
first child. The tab's Label and the pick hint's Label, whose words the lens
changes, keep the lens's whole words. Every word is the lens's own, given by
the lens, and only the names of keys are the look's.

Nothing here makes a window of its own, gives anything the keyboard, takes a
grab, raises a window or binds a key. A part drawn inside another widget is
drawn again after that widget, since Tk draws a widget again over what lies
inside it in a window that has an alpha, see kept_over.

Imports tkinter and the package, and nothing of the lens.
"""
import tkinter as tk

from lens_look import faces, text, tokens, widgets
from lens_look import scale as sc

# ---- sizes, in CSS pixels at 100 percent, from the drawings

# The note's sizes by kind, from Slate-Fullscreen, Paper-Fullscreen and
# Industrial-Fullscreen.
#   width       the note's width, its border taken in
#   strip       the height of the strip its head is on, 0 where the head is
#               the body's first row, as in Paper, strip_pad the room before
#               the head's words and strip_rule the role of the line under it
#   title_row   Paper's head row, title_gap the room between its words and
#               the rule after them, and title_rule that rule's role
#   title_ink   the role of the head's words
#   pad         the room above the body, at its sides and under it
#   first_top   the room above the first line, under Paper's head row
#   list_top    the room above the lines of keys
#   cap_col     the least width of the caps' column, col_gap the room after it
#   row_gap     the room between two lines of keys where no rule divides them
#   row_pad     the room above and under a line of keys where rules divide
#               them, and row_rule their colour, a role or a shade
#   line_role   the type of a line of keys
#   taskbar_top the room above the taskbar's line, and taskbar_rule the role
#               of a rule there and the room under that rule, None for none
#   taskbar_role the type of the taskbar's line
#   warn_top    the room above a line in the warning colour
#   footer      the footer's height, footer_ground its colour, a role or a
#               shade, footer_rule the role of the line at its top, and
#               footer_pad the room at its left and at its right
#   box_gap, box_role   the room between the box of Don't show this again
#               and its words, and the type of the words
#   ok_key      the key whose cap OK carries, None for none
NOTE = {
    "console": dict(width=560, strip=41, strip_pad=16, strip_rule="rule", title_row=0, title_gap=0,
                    title_rule=None, title_ink="strong", pad=(16, 20, 18), first_top=0, list_top=14, cap_col=40,
                    col_gap=12, row_gap=8, row_pad=0, row_rule=None, line_role="note", taskbar_top=14,
                    taskbar_rule=("rule", 12), taskbar_role="dialog_detail", warn_top=8, footer=64,
                    footer_ground="deep", footer_rule="rule", footer_pad=(20, 18), box_gap=10,
                    box_role="panel_row", ok_key=None),
    "folio": dict(width=520, strip=0, strip_pad=0, strip_rule=None, title_row=30, title_gap=14, title_rule="rule",
                  title_ink="text", pad=(22, 24, 20), first_top=10, list_top=16, cap_col=40, col_gap=12,
                  row_gap=0, row_pad=7, row_rule="rule_faint", line_role="line", taskbar_top=14, taskbar_rule=None,
                  taskbar_role="note", warn_top=8, footer=60, footer_ground="surface", footer_rule="rule",
                  footer_pad=(24, 24), box_gap=10, box_role="panel_row", ok_key="Enter"),
    "industrial": dict(width=600, strip=40, strip_pad=18, strip_rule="edge", title_row=0, title_gap=0,
                       title_rule=None, title_ink="text", pad=(20, 24, 22), first_top=0, list_top=16, cap_col=0,
                       col_gap=6, row_gap=0, row_pad=8, row_rule="rule", line_role="line", taskbar_top=16,
                       taskbar_rule=None, taskbar_role="line", warn_top=8, footer=52, footer_ground="band",
                       footer_rule="rule", footer_pad=(24, 14), box_gap=12, box_role="panel_row", ok_key=None),
}

# The note's levels, each as (the part of its rooms, and of the heights of its
# strip and its footer, that it keeps, the part of its width it takes), tried
# in turn until the note takes no more of the room it is fitted to than
# NOTE_ROOM gives, as the part of the room's width and of its height: the
# drawing's sizes, the compact sizes, those a quarter wider so fewer lines
# break, and last its rooms halved. The last is taken where none fits.
NOTE_LEVELS = ((1.0, 1.0), (tokens.COMPACT_RATIO, 1.0), (tokens.COMPACT_RATIO, 1.25), (0.5, 1.25))
NOTE_ROOM = (0.5, 0.6)

# The notice's sizes by kind, from the notices of Slate-Fullscreen,
# Paper-Fullscreen, Industrial-Fullscreen and their second boards. ground is
# the role of its box, pad the room above its lines, under them, at their
# left and at their right, line_pad the room above and under each line of
# Slate's, gap the room between two lines, glyph Slate's warning sign before
# a line in the warning colour, its size, its room from the line's top and
# the room after it, rule Paper's rule at a line's left, its width and the
# room after it, and bar the width of Industrial's bar at the box's left.
NOTICE = {
    "console": dict(ground="surface", pad=(4, 4, 16, 16), line_pad=6, gap=2, glyph=(16, 3, 10), rule=None, bar=0),
    "folio": dict(ground="surface", pad=(12, 12, 16, 16), line_pad=0, gap=6, glyph=None, rule=(2, 12), bar=0),
    "industrial": dict(ground="deep", pad=(12, 12, 23, 22), line_pad=0, gap=4, glyph=None, rule=None, bar=3),
}

# The readout by kind, from Slate-Fullscreen, Paper-Fullscreen and
# Industrial-Fullscreen: the roles of its ground and its words, the room at
# the sides of its words, and the height inside its border that its words
# are centred in.
READOUT = {"console": dict(ground="deep", ink="strong", pad=10, inner=30),
           "folio": dict(ground="surface", ink="text", pad=10, inner=26),
           "industrial": dict(ground="deep", ink="text", pad=10, inner=28)}

# An explanation's window by kind, from the hover windows of Slate-Menus,
# Paper-Menus and Industrial-Menus: the role of its ground, the type and the
# role of its title, the setting's label, title None where the kind draws
# none, the type of its words, the room above them, at their sides and under
# them, the room between the title and the words, and the width of the bar
# Industrial draws at its left.
TIP = {"console": dict(ground="deep", title="panel_title", title_ink="strong", words="explain_option_text",
                       pad=(12, 16, 14), gap=4, bar=0),
       "folio": dict(ground="well", title="panel_title", title_ink="text", words="explain_text", pad=(10, 14, 10),
                     gap=4, bar=0),
       "industrial": dict(ground="deep", title=None, title_ink="text", words="line", pad=(12, 16, 12), gap=0,
                          bar=3)}

# The tab of a hidden title bar by kind, from Slate-Menus, Paper-Menus and
# Industrial-Menus: the role of the line at its sides and its foot, None for
# none, and the roles of its ground and its glyph. Its size stays the lens's.
TAB = {"console": dict(edge="edge", ground="deep", ink="text"),
       "folio": dict(edge="edge", ground="deep", ink="text"),
       "industrial": dict(edge=None, ground="accent", ink="on_accent")}

# The divider of the A/B split by kind, from Slate-Dialogs, Paper-Dialogs-2 and
# Industrial-Dialogs-2, in the lens's window of DIVIDER pixels: the role of its
# ground, the role and the width in pixels of the line down its middle, the
# role of a line at each side, None for none, and Slate's handle, its height
# and the roles of its fill, its edge and its arrows. The window and its lines
# stay in screen pixels, as the lens's are.
DIVIDER = {"console": dict(ground="deep", line=("faint", 2), sides=None, handle=(48, "head", "edge", "text")),
           "folio": dict(ground="surface", line=("text", 4), sides=None, handle=None),
           "industrial": dict(ground="surface", line=("accent", 4), sides="edge", handle=None)}
# The arrows on Slate's handle, their size and how far each stands from its
# middle, in screen pixels, as the window they are in is
HANDLE_ARROWS = (8, 3)

# The hint of an attach pick by kind, from Slate-Dialogs, Paper-Dialogs and
# Industrial-Dialogs-2: the role of its ground, the room above its words,
# under them, before them and after the last, the room between the sentence
# and the key's cap and between the cap and the words after it, the type and
# the role of those words, and the width of Industrial's bar at its left. Its
# sentence is in the note's type, and its cap a menu's.
PICK = {"console": dict(ground="surface", pad=(8, 8, 16, 12), gap=18, after_gap=9, after_role="menu_hint",
                        after_ink="muted", bar=0),
        "folio": dict(ground="surface", pad=(8, 8, 16, 16), gap=5, after_gap=5, after_role="note", after_ink="text",
                      bar=0),
        "industrial": dict(ground="deep", pad=(10, 10, 23, 20), gap=16, after_gap=6, after_role="note",
                           after_ink="text", bar=3)}

# The sheet a region is dragged on by kind, from Slate-Dialogs, Paper-Dialogs
# and Industrial-Dialogs-2: the roles of the sheet, which the lens shows at its
# own alpha, and of the rectangle dragged on it, which is SHEET_LINE wide
SHEET = {"console": ("well", "accent"), "folio": ("well", "text"), "industrial": ("well", "accent")}
SHEET_LINE = 2


# ---- the words, split as the looks draw them (pure)

def note_rows(lines, keys):
    """The note's lines of keys, as keys_list gives them, each as (the key it
    starts with, the words after that key), keys being the keys key_for
    gives, None for one that is not held. A line that starts with none of
    them, as the arrow keys' line and the taskbar's line do, gives ("", the
    line), see text.split_key_line."""
    out = []
    for line in lines:
        got = ("", str(line))
        for key in keys:
            if key:
                cap, rest = text.split_key_line(line, key)
                if cap:
                    got = (cap, rest)
                    break
        out.append(got)
    return out


def pick_parts(words):
    """The words of an attach pick's hint, as the lens gives them, ending in
    two spaces, the key that cancels and what it does, as (the sentence
    before them, the key, the words after it), such as ("Click the window to
    attach the lens to.", "Escape", "cancels."). Words that do not end so give
    (the words, "", "")."""
    words = str(words)
    head, sep, tail = words.rpartition("  ")
    key, _sp, rest = tail.partition(" ")
    if sep and head.strip() and rest and text.is_key(key):
        return head, key, rest
    return words, "", ""


# ---- the pieces

def colour(look, name):
    """A colour of the look by its role, or by its name in widgets.SHADES for
    one that is none of the roles, such as Paper's faint rule."""
    return look.c[name] if name in look.c else widgets.shade(look, name)


def linespace(widget, font):
    """The height of a line of a font in pixels, in widget's interpreter."""
    return int(widget.tk.call("font", "metrics", font, "-linespace"))


def kept_over(holder, part):
    """part, which lies inside holder, drawn again once holder has drawn
    itself, at the next idle moment after holder comes into view or is drawn
    again, however often before then. In a window of the lens's own, which
    has an alpha, Tk draws a widget again over what lies inside it, see
    lens_look.menus.Menu._again. The root keeps the call, so a window closed
    before then leaves no call behind that Tk could not make."""
    asked = []

    def again():
        del asked[:]
        try:
            if part.winfo_ismapped():
                part.configure(bg=widgets.real(part, "bg"))
        except tk.TclError:
            pass                        # the window closed before its idle moment

    def drawn(event):
        if not asked:
            try:
                asked.append(holder._root().after_idle(again))
            except tk.TclError:
                pass

    holder.bind("<Expose>", drawn, add="+")


class BoxFace(faces.Face):
    """The note's Don't show this again, a box as the NR panel's ties draw
    theirs, see faces.tie_items, and the words beside it, for a check button
    that is made and never shown, which keeps the words, the variable and the
    command. The box follows the variable, and a click on the box or on the
    words invokes the button, as a click on the button would. It takes no
    keyboard."""

    def __init__(self, master, look, model, role, gap, ground):
        self.model, self.role, self.gap = model, role, gap
        faces.Face.__init__(self, master, look, ground)
        self.watch(str(model.cget("variable")))
        self.redraw_now()

    def state(self):
        return {"ticked": faces.selected(self.model), "words": str(self.model.cget("text"))}

    def layout(self, ctx):
        box = ctx.px(faces.TIE[ctx.kind]["box"])
        font = ctx.font(self.role)
        words = str(self.model.cget("text"))
        gap = ctx.px(self.gap)
        width = box + gap + ctx.measure(font, words)
        height = max(box, ctx.linespace(font))
        items = []
        faces.rect(items, 0, 0, width, height, self.ground())
        drawn, _hits, _size = faces.tie_items(ctx, box, height, faces.selected(self.model), False, False,
                                              self.ground())
        items += drawn
        faces.words(items, box + gap, height // 2, words, font, ctx.c("text"), "w")
        return items, [(0, 0, width, height, ("invoke",))], (width, height)

    def act(self, action, x):
        self.model.invoke()


def _cap(master, look, key, ground):
    """The cap a line of the note's keys starts with, a Label whose words
    are the key, with the key's cap drawn over the whole of it, see
    widgets.KeyCap, or an empty Label for a line that starts with no key."""
    _fill, _edge, ink = widgets.cap_colours(look, "cap_note")
    label = tk.Label(master, text=key, bg=ground, fg=ink, font=look.font("cap_note", False, master), bd=0,
                     highlightthickness=0, padx=0, pady=0)
    if not key:
        widgets.exact(label, 1, 1)
        return label
    cap = widgets.KeyCap(label, look, key, "cap_note", ground=ground)
    widgets.exact(label, cap.winfo_reqwidth(), cap.winfo_reqheight())
    cap.place(x=0, y=0, relwidth=1.0, relheight=1.0, bordermode="ignore")
    kept_over(label, cap)
    return label


# ---- the note on going fullscreen

def note(t, look, head, first, lines, keys, taskbar, warns, quiet_words, quiet, ok_words, ok, room):
    """The note on going fullscreen in t, a window of the lens's own, as the
    look's design draws it. head is its head and first its first line. lines
    are the lines of keys keys_list gives and keys the keys key_for gives,
    each line drawn after the cap of the key it starts with, see note_rows.
    taskbar is the taskbar's line and warns the lines in the warning colour,
    None for one not said. quiet_words are the words of Don't show this
    again, None where the note has none, and quiet(ticked) is called the
    moment it is ticked or unticked. ok_words are OK's, and ok() is called
    when it is pressed. room is the (width, height) of the work area the
    note is fitted to. It is built at the first of NOTE_LEVELS at which it
    takes no more of that than NOTE_ROOM gives, or else at the last. Returns
    the Label of its first line, whose words the lens changes in place."""
    kind = widgets.kind_of(look)
    t.configure(bg=look.c["frame"])
    most_w, most_h = int(room[0] * NOTE_ROOM[0]), int(room[1] * NOTE_ROOM[1])
    rows = note_rows(lines, keys)
    for i, (part, wider) in enumerate(NOTE_LEVELS):
        box, first_label = _note(t, look, kind, part, wider, most_w, head, first, lines, rows, taskbar, warns,
                                 quiet_words, quiet, ok_words, ok)
        t.update_idletasks()
        if i == len(NOTE_LEVELS) - 1 or (t.winfo_reqwidth() <= most_w and t.winfo_reqheight() <= most_h):
            return first_label
        box.destroy()


def _note(t, look, kind, part, wider, most_w, head, first, lines, rows, taskbar, warns, quiet_words, quiet, ok_words,
          ok):
    """One build of the note at a level of NOTE_LEVELS, see note, as (its box,
    the Label of its first line). part is the part of its rooms it keeps and
    wider the part of its width it takes, no wider than most_w."""
    k, c, legacy = NOTE[kind], look.c, look.legacy
    s = look.scale_for(t)
    hair = sc.hair()

    def px(n):
        return sc.px(n, s)

    def room(n):
        return sc.px(n * part, s)

    def font(role):
        return look.font(role, False, t)

    width = px(k["width"])
    if wider > 1:
        width = max(width, min(px(k["width"] * wider), most_w))
    inner = width - 2 * hair - 2 * px(k["pad"][1])
    ground = c["surface"]
    box = tk.Frame(t, bg=ground, bd=0, highlightthickness=0)
    box.pack(padx=hair, pady=hair)
    title_tall = linespace(t, font("panel_title"))

    def title(master, under):
        label = widgets.StateLabel(master, look, text=head, fg=legacy["fg"], bg=legacy["bg"],
                                   roles={"fg": {"fg": k["title_ink"]}}, font_role="panel_title", bd=0,
                                   highlightthickness=0, padx=0, pady=0)
        label.set_ground(under)
        return label

    if k["strip"]:
        strip = tk.Frame(box, bg=c["deep"], width=width - 2 * hair, height=max(room(k["strip"]), title_tall + 2 * hair),
                         bd=0, highlightthickness=0)
        strip.pack_propagate(False)
        strip.pack(fill="x")
        title(strip, c["deep"]).pack(side="left", padx=(px(k["strip_pad"]), 0))
        widgets.Rule(box, look, k["strip_rule"]).pack(fill="x")
    body = tk.Frame(box, bg=ground, bd=0, highlightthickness=0)
    body.pack(fill="x", padx=px(k["pad"][1]), pady=(room(k["pad"][0]), room(k["pad"][2])))
    if k["title_row"]:
        row = tk.Frame(body, bg=ground, width=inner, height=max(room(k["title_row"]), title_tall), bd=0,
                       highlightthickness=0)
        row.pack_propagate(False)
        row.pack(fill="x")
        title(row, ground).pack(side="left")
        widgets.Rule(row, look, k["title_rule"]).pack(side="left", fill="x", expand=True,
                                                      padx=(px(k["title_gap"]), 0))
    first_label = tk.Label(body, text=first, bg=ground, fg=legacy["fg"], font=font("note"), justify="left",
                           wraplength=inner, anchor="w", bd=0, highlightthickness=0, padx=0, pady=0)
    first_label.pack(anchor="w", pady=(room(k["first_top"]), 0))

    # the lines of keys, the cap in the first column and the line in the second,
    # in a row each, rows 0 on, its first line level with the middle of the cap
    listed = tk.Frame(body, bg=ground, bd=0, highlightthickness=0)
    listed.pack(fill="x", pady=(room(k["list_top"]), 0))
    listed.columnconfigure(0, minsize=px(k["cap_col"]))
    cap_tall = px(widgets.CAPS[kind]["cap_note"][1])
    lift = max(0, min(3, (cap_tall - linespace(t, font(k["line_role"]))) // 2))
    rule = colour(look, k["row_rule"]) if k["row_rule"] else None
    pad, last, widest, said = room(k["row_pad"]), len(rows) - 1, 0, []
    for i, (whole, (key, _rest)) in enumerate(zip(lines, rows)):
        if rule:
            above, below = hair + pad, pad + (hair if i == last else 0)
        else:
            above, below = (room(k["row_gap"]) if i else 0), 0
        cap = _cap(listed, look, key, ground)
        cap.grid(row=i, column=0, sticky="nw", pady=(above, below))
        widest = max(widest, cap.winfo_reqwidth())
        line = widgets.StateLabel(listed, look, text=whole, fg=legacy["fg"], bg=legacy["bg"], font_role=k["line_role"],
                                  shown=lambda words, key=key: text.split_key_line(words, key)[1] if key else words,
                                  justify="left", anchor="w", bd=0, highlightthickness=0, padx=0, pady=0)
        line.grid(row=i, column=1, sticky="nw", padx=(px(k["col_gap"]), 0), pady=(above + lift, below))
        said.append(line)
        if rule:
            tk.Frame(listed, bg=rule, height=hair, bd=0, highlightthickness=0).grid(
                row=i, column=0, columnspan=2, sticky="new")
    if rule and rows:
        tk.Frame(listed, bg=rule, height=hair, bd=0, highlightthickness=0).grid(
            row=last, column=0, columnspan=2, sticky="sew")
    wrap = max(1, inner - max(widest, px(k["cap_col"])) - px(k["col_gap"]))
    for line in said:
        line.configure(wraplength=wrap)

    # the taskbar's line, and the lines in the warning colour under it
    top = room(k["taskbar_top"])
    if k["taskbar_rule"]:
        role, under = k["taskbar_rule"]
        widgets.Rule(body, look, role).pack(fill="x", pady=(top, 0))
        top = room(under)
    tk.Label(body, text=taskbar, bg=ground, fg=legacy["fg"], font=font(k["taskbar_role"]), justify="left",
             wraplength=inner, anchor="w", bd=0, highlightthickness=0, padx=0, pady=0).pack(anchor="w", pady=(top, 0))
    for words in warns:
        if words:
            tk.Label(body, text=words, bg=ground, fg=legacy["warn"], font=font("note"), justify="left",
                     wraplength=inner, anchor="w", bd=0, highlightthickness=0, padx=0, pady=0).pack(
                anchor="w", pady=(room(k["warn_top"]), 0))

    # the footer, Don't show this again at the left where the note has it and OK at the right
    under = colour(look, k["footer_ground"])
    tall = sc.px(widgets.BUTTONS[kind]["h"], s)
    footer = tk.Frame(box, bg=under, height=max(room(k["footer"]), tall + 2 * px(6)), bd=0, highlightthickness=0)
    footer.pack_propagate(False)
    footer.pack(fill="x")
    widgets.Rule(footer, look, k["footer_rule"]).place(x=0, y=0, relwidth=1.0)
    left, right = px(k["footer_pad"][0]), px(k["footer_pad"][1])
    if quiet_words is not None:
        ticked = tk.BooleanVar(master=footer, value=False)
        model = tk.Checkbutton(footer, text=quiet_words, variable=ticked, takefocus=0,
                               command=lambda: quiet(bool(ticked.get())))
        BoxFace(footer, look, model, k["box_role"], k["box_gap"], under).pack(side="left", padx=(left, 0))
    button = widgets.CapButton(footer, look, text=ok_words, command=ok, primary=True, key=k["ok_key"])
    button.pack(side="right", padx=(0, right))
    if getattr(button, "cap", None) is not None:
        kept_over(button, button.cap)
    return box, first_label


# ---- the notice

def notice_box(t, look):
    """The notice's box in t, a window of the lens's own, its first child,
    in the look's colours, the window's own colour being its border."""
    k = NOTICE[widgets.kind_of(look)]
    t.configure(bg=look.c["frame"])
    box = tk.Frame(t, bg=look.c[k["ground"]], bd=0, highlightthickness=0)
    box.pack(padx=sc.hair(), pady=sc.hair())
    return box


def notice_lines(box, look, lines, wrap):
    """The notice's lines in its box, made anew, each (its words, its colour)
    as the lens says them, top to bottom, broken at wrap pixels. Each line is
    a Label of the box, its only Labels, and what the look draws beside them
    is no Label. Slate's warning sign before a line in the warning colour is
    drawn on a Canvas, and Paper's rule at a line's left and Industrial's bar
    at the box's left are Frames."""
    kind = widgets.kind_of(look)
    k, c = NOTICE[kind], look.c
    s = look.scale_for(box)

    def px(n):
        return sc.px(n, s)

    for child in box.winfo_children():
        child.destroy()
    ground = c[k["ground"]]
    font = look.font("notice", False, box)
    top, bottom, left, right = (px(n) for n in k["pad"])
    if k["bar"]:
        tk.Frame(box, bg=c["accent"], width=sc.border(k["bar"], s), bd=0, highlightthickness=0).place(
            x=0, y=0, relheight=1.0)
    box.columnconfigure(0, minsize=left)
    last = len(lines) - 1
    for i, (words, ink) in enumerate(lines):
        above = (top if i == 0 else px(k["gap"])) + px(k["line_pad"])
        below = (bottom if i == last else 0) + px(k["line_pad"])
        tk.Label(box, text=words, bg=ground, fg=ink, font=font, justify="left", wraplength=wrap, anchor="w", bd=0,
                 highlightthickness=0, padx=0, pady=0).grid(row=i, column=1, sticky="w", padx=(0, right),
                                                            pady=(above, below))
        if k["glyph"]:
            size, down, after = (px(n) for n in k["glyph"])
            box.columnconfigure(0, minsize=left + size + after)
            if tokens.same(ink, look.legacy["warn"]):
                sign = tk.Canvas(box, width=size, height=size, bg=ground, bd=0, highlightthickness=0, takefocus=0)
                glyph_font, char = widgets.glyph(sign, "warn", size)
                sign.create_text(size // 2, size // 2, text=char, font=glyph_font, fill=ink, anchor="center")
                sign.grid(row=i, column=0, sticky="nw", padx=(left, after), pady=(above + down, below))
        elif k["rule"]:
            line, after = sc.border(k["rule"][0], s), px(k["rule"][1])
            box.columnconfigure(0, minsize=left + line + after)
            tk.Frame(box, bg=ink, width=line, bd=0, highlightthickness=0).grid(
                row=i, column=0, sticky="nsw", padx=(left, after), pady=(above, below))


# ---- the readout and an explanation's window

def readout(t, look):
    """The readout's Label in t, a window of the lens's own, its first and
    only child, in the look's colours and type, the window's own colour being
    its border. The lens gives it its words."""
    k, c = READOUT[widgets.kind_of(look)], look.c
    s = look.scale_for(t)
    t.configure(bg=c["frame"])
    font = look.font("readout", False, t)
    label = tk.Label(t, bg=c[k["ground"]], fg=c[k["ink"]], font=font, padx=sc.px(k["pad"], s),
                     pady=max(0, (sc.px(k["inner"], s) - linespace(t, font)) // 2), bd=0, highlightthickness=0)
    label.pack(padx=sc.hair(), pady=sc.hair())
    return label


def tip(t, look, words, title, wrap):
    """An explanation's window in t, a window the lens made, as the look draws
    it: words, the explanation, in a Label that is t's first child, and above
    them title, the setting's label, where the look draws one and the
    setting has one. wrap is the width the lines break at, as a Label's
    wraplength. The window's own colour is its border, and Industrial's bar
    at its left. Returns the Label of the words."""
    k, c = TIP[widgets.kind_of(look)], look.c
    s = look.scale_for(t)
    hair = sc.hair()
    t.configure(bg=c["frame"])
    ground = c[k["ground"]]
    top, side, bottom = (sc.px(n, s) for n in k["pad"])
    label = tk.Label(t, text=words, bg=ground, fg=c["text"], font=look.font(k["words"], False, t), justify="left",
                     wraplength=wrap, anchor="w", padx=side, pady=0, bd=0, highlightthickness=0)
    if k["title"] and title:
        head = tk.Label(t, text=title, bg=ground, fg=c[k["title_ink"]], font=look.font(k["title"], False, t),
                        justify="left", wraplength=wrap, anchor="w", padx=side, pady=0, bd=0, highlightthickness=0)
        rooms = [tk.Frame(t, bg=ground, height=n, bd=0, highlightthickness=0)
                 for n in (top, sc.px(k["gap"], s), bottom)]
        rooms[0].pack(fill="x", padx=hair, pady=(hair, 0))
        head.pack(fill="x", padx=hair)
        rooms[1].pack(fill="x", padx=hair)
        label.pack(fill="x", padx=hair)
        rooms[2].pack(fill="x", padx=hair, pady=(0, hair))
        return label
    bar = sc.border(k["bar"], s) if k["bar"] else 0
    label.configure(pady=top)
    label.pack(fill="x", padx=(hair + bar, hair), pady=(hair, hair if bottom <= top else 0))
    if bottom > top:
        tk.Frame(t, bg=ground, height=bottom - top, bd=0, highlightthickness=0).pack(
            fill="x", padx=(hair + bar, hair), pady=(0, hair))
    return label


# ---- the tab, the divider, the pick hint and the region sheet

def tab(t, look, glyph, font, width, height):
    """The tab's Label in t, the tab's window, which stays width by height
    pixels: glyph, the lens's own, in the font the lens gives it, on the
    look's ground, and the look's line at its sides and its foot where it
    draws one, the window's own colour. The lens binds the window and the
    Label alike."""
    k, c = TAB[widgets.kind_of(look)], look.c
    edge = sc.hair() if k["edge"] else 0
    t.configure(bg=c[k["edge"] or k["ground"]])
    label = tk.Label(t, text=glyph, bg=c[k["ground"]], fg=c[k["ink"]], font=font, bd=0, highlightthickness=0)
    label.place(x=edge, y=0, width=width - 2 * edge, height=height - edge)
    return label


def divider(d, look, width):
    """The divider of the A/B split in d, its window, width pixels wide, in
    the look's colours: its ground, the line down its middle, Industrial's
    lines at its sides and Slate's handle in the middle of its height, which
    follows the window's height. Nothing in it takes a click of its own, so a
    press anywhere on it reaches the window's binding."""
    k, c = DIVIDER[widgets.kind_of(look)], look.c
    s = look.scale_for(d)
    d.configure(bg=c[k["ground"]])
    if k["sides"]:
        for x in (0, width - 1):
            tk.Frame(d, bg=c[k["sides"]], bd=0, highlightthickness=0).place(x=x, y=0, width=1, relheight=1.0)
    role, line = k["line"]
    tk.Frame(d, bg=c[role], bd=0, highlightthickness=0).place(x=(width - line) // 2, y=0, width=line, relheight=1.0)
    if k["handle"]:
        tall, fill, edge, ink = k["handle"]
        tall = sc.px(tall, s)
        handle = tk.Canvas(d, width=width, height=tall, bg=c[fill], bd=0, highlightthickness=0, takefocus=0)
        handle.create_rectangle(0, 0, width, tall, fill=c[edge], outline="", width=0)
        handle.create_rectangle(1, 1, width - 1, tall - 1, fill=c[fill], outline="", width=0)
        size, off = HANDLE_ARROWS
        for name, x in (("left", width // 2 - off), ("right", width // 2 + off)):
            glyph_font, char = widgets.glyph(handle, name, size)
            handle.create_text(x, tall // 2, text=char, font=glyph_font, fill=c[ink], anchor="center")
        handle.place(relx=0.5, rely=0.5, anchor="center")


def pick_hint(hint, look, words):
    """The hint of an attach pick in hint, its window, as the look draws it:
    the sentence of words, the lens's whole words, in a State Label that
    keeps them, see widgets.StateLabel, then the key that cancels as a cap
    and the words after it, see pick_parts. Returns the Label, whose words
    the lens changes as the pick goes on, and the cap and the words after it
    follow them. The window's own colour is its border, and Industrial's bar
    at its left."""
    k, c, legacy = PICK[widgets.kind_of(look)], look.c, look.legacy
    s = look.scale_for(hint)

    def px(n):
        return sc.px(n, s)

    hint.configure(bg=c["frame"])
    ground = c[k["ground"]]
    box = tk.Frame(hint, bg=ground, bd=0, highlightthickness=0)
    box.pack(padx=sc.hair(), pady=sc.hair())
    if k["bar"]:
        tk.Frame(box, bg=c["accent"], width=sc.border(k["bar"], s), bd=0, highlightthickness=0).place(
            x=0, y=0, relheight=1.0)
    top, bottom, left, right = (px(n) for n in k["pad"])
    label = widgets.StateLabel(box, look, text=words, fg=legacy["fg"], bg=legacy["bg"], font_role="note",
                               shown=lambda said: pick_parts(said)[0], bd=0, highlightthickness=0, padx=0, pady=0)
    label.set_ground(ground)
    label.pack(side="left", padx=(left, 0), pady=(top, bottom))
    _sentence, key, after = pick_parts(words)
    cap = widgets.KeyCap(box, look, key or "Esc", "cap_menu", ground=ground)
    tail = tk.Label(box, text=after, bg=ground, fg=c[k["after_ink"]], font=look.font(k["after_role"], False, box),
                    bd=0, highlightthickness=0, padx=0, pady=0)

    def follow(widget=None, keys=(), lit_changed=False):
        _sentence, key_, after_ = pick_parts(label.cget("text"))
        cap.pack_forget()
        tail.pack_forget()
        if key_:
            cap.configure(text=key_)
            tail.configure(text=after_)
            cap.pack(side="left", padx=(px(k["gap"]), 0))
            tail.pack(side="left", padx=(px(k["after_gap"]), right))
        label.pack_configure(padx=(left, 0 if key_ else right))

    label.follow(follow)
    follow()
    return label


def sheet_colours(look, widget=None):
    """The sheet a region is dragged on, the rectangle dragged on it and that
    rectangle's width in pixels, as (sheet, rectangle, width), in the look's
    colours. The lens draws them as it always did."""
    sheet, edge = SHEET[widgets.kind_of(look)]
    return look.c[sheet], look.c[edge], sc.border(SHEET_LINE, look.scale_for(widget))
