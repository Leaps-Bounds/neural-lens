"""The title bar of the lens and the frame round its picture in a drawn look,
as the bars of Slate-Menus, Paper-Menus and Industrial-Menus draw them.

The lens makes the bar's widgets here in place of today's, see
Lens._bar_drawn, under the names it always gave them and with the same
words, colours and clicks, so its code and its tests read what they read in
the classic look. The menu button, the title, the two pickers, the pass
count, its two buttons, Set and the caption buttons are State labels, see
lens_look.widgets, each drawn in the colours PAINT gives it for the logical
colours the code gives it. A picker draws its name without the chevron the
code writes first, and a chevron of its own at its right. The pass count and
its buttons lie in a well, with Set beside it. The readout and the intensity
are plain labels in the look's type, since the lens measures the readout's
words in its own font.

The bar keeps the lens's height for it, BAR, which stays in screen pixels,
and so do the heights inside it. A well is BAR less 8 pixels, see
WELL_INSET. Its widths and its type follow the scale, see lens_look.scale.
The frame keeps its sizes too, its line in the look's frame colour and its
grips in the bar's.

Nothing here gives anything the keyboard, takes a grab, makes an event,
raises or places a window or makes one. A part that lies inside another
widget passes that widget's bindings on, see passes_on, and is drawn again
after it, since Tk can draw a widget again over what lies inside it, see
kept_inside and lens_look.menus.Menu._again.

Imports tkinter and the package, and nothing of the lens.
"""
import tkinter as tk

from lens_look import panel, text, tokens, widgets
from lens_look import scale as sc

# ---- sizes

# The bar's sizes by kind in CSS pixels at 100 percent, from the bars of
# Slate-Menus, Paper-Menus and Industrial-Menus, which the scale turns into the
# screen's own. Its heights are not among them, see WELL_INSET and SEP_INSET.
#   lead        the room before the menu button, menu its width and
#               menu_glyph the size of its glyph
#   title_pad   the room before the title's words and after them, and
#               title_rule Slate's line after the title, as the room before
#               the line and after it, None for none
#   readout_gap the room from the title's words to the readout's
#   picker_gap  the room before the profile picker, picker_between the room
#               after it, before the style picker, picker_pad the room before
#               a picker's name and after its chevron, chevron_gap the room
#               between the two and chevron the chevron's size
#   step        the width of the pass count's buttons and step_glyph the
#               size of their glyphs, count_pad the room either side of the
#               count, which gives 1 pass about the width the drawing gives it
#   set_gap     the room before Set and set_pad the room either side of its
#               word
#   sep         the room before the line before the caption buttons and the
#               room after it, and caption the caption buttons' width
#   intensity_pad   the room either side of the intensity, which no drawing
#               draws, as wide as the room between the two pickers
SIZES = {
    "console": dict(lead=0, menu=44, menu_glyph=16, title_pad=12, title_rule=(12, 12), readout_gap=25,
                    picker_gap=14, picker_between=8, picker_pad=(12, 10), chevron_gap=8, chevron=12, step=28,
                    step_glyph=12, count_pad=8, set_gap=6, set_pad=12, sep=(12, 6), caption=46, intensity_pad=8),
    "folio": dict(lead=5, menu=40, menu_glyph=14, title_pad=12, title_rule=None, readout_gap=20, picker_gap=16,
                  picker_between=8, picker_pad=(9, 6), chevron_gap=8, chevron=12, step=26, step_glyph=10,
                  count_pad=14, set_gap=8, set_pad=10, sep=(12, 6), caption=46, intensity_pad=8),
    "industrial": dict(lead=0, menu=46, menu_glyph=14, title_pad=12, title_rule=None, readout_gap=20,
                       picker_gap=16, picker_between=8, picker_pad=(10, 9), chevron_gap=8, chevron=10, step=30,
                       step_glyph=10, count_pad=8, set_gap=8, set_pad=12, sep=(9, 9), caption=46, intensity_pad=8),
}

# The heights inside the bar are in screen pixels, as BAR is. A well, the
# pickers, the pass count and Set are BAR less twice WELL_INSET high, and a
# line on the bar is BAR less twice SEP_INSET, by kind, 16, 18 and 16 pixels
# as drawn
WELL_INSET = 4
SEP_INSET = {"console": 9, "folio": 8, "industrial": 9}

# The glyphs of the menu button and the pass count's buttons, each as (its
# place in Windows' icon fonts, the character drawn in Segoe UI Symbol where
# neither font is there), as widgets.GLYPHS gives the kit's
MENU = (0xE700, 0x2630)
REMOVE = (0xE738, 0x2212)
ADD = (0xE710, 0x2B)

# ---- colours

# The colours of the bar's parts by kind, each a role of the look, see
# lens_look.tokens.ROLES:
#   ground      the part's colour, or (live, greyed), a part being greyed
#               while the code gives its words the dim colour, as it gives a
#               button that does nothing now
#   hover       its colour where the code gives it the hover colour, which it
#               does under the pointer, None where it has none
#   close, close_ink    the close button's colour where the code gives it the
#               close colour, and its glyph's then
#   ink         the colour of its words for each of the ten colours the code
#               gives them, {a key of the ten: a role}, see
#               widgets.drawn_colour
#   border      the line round it, or (live, greyed), None for none
# The drawings draw no part under the pointer, so the hover colours are the
# looks' own. Folio's hover colour is its strip, which is the bar's own, so its
# bar's buttons take its field colour under the pointer, on which the words
# keep 4.5:1, and its pickers their lit one.
_PICKER = {"accent": "strong", "warn": "warn", "dim": "muted", "fg": "text"}
_COUNT = {"accent": "strong", "warn": "warn", "dim": "muted", "fg": "text"}
_STEP = {"fg": "text", "dim": "faint"}
_SET = {"accent": "accent", "dim": "muted", "fg": "text"}
PAINT = {
    "console": {
        "menu": dict(ground="deep", ink={"fg": "text"}),
        "title": dict(ground="deep", ink={"accent": "text"}),
        "picker": dict(ground="well", hover="lit", ink=_PICKER),
        "count": dict(ground="well", ink=_COUNT),
        "step": dict(ground="well", hover="hover", ink=_STEP),
        "set": dict(ground="head", hover="hover", ink=_SET, border="edge"),
        "caption": dict(ground="deep", hover="hover", ink={"fg": "text"}),
        "close": dict(ground="deep", close="close", close_ink="strong", ink={"fg": "text"}),
    },
    "folio": {
        "menu": dict(ground="deep", ink={"fg": "text"}),
        "title": dict(ground="deep", ink={"accent": "text"}),
        "picker": dict(ground="well", hover="lit", ink=_PICKER, border="edge"),
        "count": dict(ground="deep", ink=_COUNT),
        "step": dict(ground="deep", hover="well", ink=_STEP, border=("edge", "faint")),
        "set": dict(ground="deep", hover="well", ink=_SET, border=("edge", "faint")),
        "caption": dict(ground="deep", hover="well", ink={"fg": "muted"}),
        "close": dict(ground="deep", close="close", close_ink="on_raised", ink={"fg": "muted"}),
    },
    "industrial": {
        "menu": dict(ground="deep", ink={"fg": "text"}),
        "title": dict(ground="deep", ink={"accent": "muted"}),
        "picker": dict(ground="well", hover="lit", ink=_PICKER, border="edge"),
        "count": dict(ground="deep", ink=_COUNT),
        "step": dict(ground=("head", "deep"), hover="hover", ink=_STEP),
        "set": dict(ground="deep", hover="hover", ink=_SET, border=("accent", "rule")),
        "caption": dict(ground="deep", hover="hover", ink={"fg": "text"}),
        "close": dict(ground="deep", close="close", close_ink="text", ink={"fg": "text"}),
    },
}

# The lines and the well by kind, each a role, None for none:
#   frame       the line round the lens, which the chrome's own colour draws
#   under       the line along the foot of the bar
#   title_rule  Slate's line after the title
#   sep         the line before the caption buttons
#   chevron     the pickers' chevrons
#   well, well_edge, seam   the well's colour, the line round it and the lines
#               between the pass count and its buttons
LINES = {
    "console": dict(frame="frame", under="rule", title_rule="edge", sep="edge", chevron="muted", well="well",
                    well_edge=None, seam=None),
    "folio": dict(frame="frame", under="rule", title_rule=None, sep="rule", chevron="text", well="deep",
                  well_edge=None, seam=None),
    "industrial": dict(frame="frame", under=None, title_rule=None, sep="edge", chevron="text", well="deep",
                       well_edge="edge", seam="edge"),
}


def pick(spec, live):
    """A role of PAINT, given alone or as (live, greyed)."""
    return spec if isinstance(spec, str) else spec[0 if live else 1]


def paint_options(look, paint, logical):
    """The colours a part of the bar draws, as options for Tk, for the logical
    colours the code gave it, logical being {"fg": ..., "bg": ...}: its
    ground, or its hover or close colour where the code gives it that, its
    words' colour and its border's, each by its paint, see PAINT. The bar's
    own colour and the cap colour the code gives a caption button are its
    ground, whatever else a theme of the user's own makes them. Pure."""
    c, lg = look.c, look.legacy
    fg, bg = logical.get("fg"), logical.get("bg")
    live = fg is None or not tokens.same(fg, lg["dim"])
    keys = widgets.keys_of(look, bg) if bg is not None else []
    plain = "bg" in keys or "cap" in keys
    ink = None
    if paint.get("close") and "close" in keys and not plain:
        ground, ink = c[paint["close"]], c[paint["close_ink"]]
    elif paint.get("hover") and "hover" in keys and not plain:
        ground = c[paint["hover"]]
    else:
        ground = c[pick(paint["ground"], live)]
    out = {"bg": ground}
    if fg is not None:
        out["fg"] = ink or widgets.drawn_colour(look, "fg", fg, {"fg": paint["ink"]})
    if paint.get("border"):
        out["highlightbackground"] = out["highlightcolor"] = c[pick(paint["border"], live)]
    return out


def icon_glyph(widget, codes, size):
    """The font and the character of a glyph of Windows' icon fonts, codes
    being as MENU gives them, size pixels high, as widgets.glyph gives the
    kit's."""
    icon, plain = codes
    family = widgets.icon_family(widget)
    if family:
        return (family, -int(size), "normal"), chr(icon)
    return (widgets.PLAIN_FONT, -int(size), "normal"), chr(plain)


def passes_on(widget, holder):
    """widget, which lies inside holder or inside a part of it, takes holder's
    bindings after its own, so a click on it is a click on holder and a drag
    on it a drag of whatever holder drags. Tk runs the bindings of a widget's
    tags in their order."""
    tags = [tag for tag in widget.bindtags() if tag != str(holder)]
    widget.bindtags((tags[0], str(holder)) + tuple(tags[1:]))


def kept_inside(holder, part, colour):
    """part, which lies inside holder, a State widget, drawn again in the
    colour colour() gives at the next idle moment after holder changes
    through its configure or is drawn again, however often before then. Tk
    can draw a widget again over what lies inside it, see
    lens_look.menus.Menu._again. The root keeps the call, so a bar gone
    before then leaves no call behind that Tk could not make."""
    asked = []

    def again():
        del asked[:]
        try:
            part.configure(bg=colour())
        except tk.TclError:
            pass                        # the bar went before its idle moment

    def ask():
        if not asked:
            try:
                asked.append(holder._root().after_idle(again))
            except tk.TclError:
                pass

    holder.follow(lambda widget, keys, lit_changed: ask())
    holder.bind("<Expose>", lambda event: ask() if event.widget is holder else None, add="+")


class Part(widgets.StateLabel):
    """A part of the bar in a drawn look, a State label whose colours follow
    its paint, see PAINT and paint_options, for the logical colours the code
    gives it. fit, as (the room before its words, the room after them, its
    height or 0 for its words' own) in pixels, sizes it to the words it
    draws each time they change, so the lens measures what it shows, see
    fitted."""

    def __init__(self, master, look, paint, fit=None, **kw):
        self.paint = paint
        self.fit = fit
        self.fit_font = kw.get("font")
        self.fit_inset = int(kw.get("highlightthickness", 0)) + int(kw.get("bd", 0))
        widgets.StateLabel.__init__(self, master, look, **kw)

    def more(self, out):
        out.update(paint_options(self.look, self.paint, self.logical))
        if self.fit is not None:
            out.update(self.fitted(out))

    def fitted(self, out):
        """The options that make the part exactly as wide as its words and
        the room fit gives either side, its words at the left of it, and as
        high as fit gives, by the blank image, see widgets.exact."""
        before, after, high = self.fit
        words = out["text"] if "text" in out else self.drawn_text()
        master = self._kit_master
        wide = int(master.tk.call("font", "measure", out.get("font") or self.fit_font, words))
        got = dict(image=widgets.blank(master), compound="center", anchor="w", padx=before, pady=0,
                   width=max(1, wide + after - before))
        if high:
            got["height"] = max(1, high - 2 * self.fit_inset)
        return got


class Bar(object):
    """The title bar of a drawn look, built in bar, the lens's own Frame for
    it, inside t, the chrome's window, whose colour is the frame's line round
    the lens. words are the code's words for each part and clicks what a
    click on each does, both by the names the lens gives its widgets, see
    Lens._bar_drawn, glyph_font the caption buttons' font and height the
    lens's BAR. parts are the widgets by those names, and ground the bar's
    colour, which the frame's grips take, see grips.

    The parts go onto the bar in the order the lens puts its own there: the
    menu button, the caption buttons, the line before them, Set and the well
    of the pass count, then the words, which are the title, the readout and
    the profile picker, so a narrow lens cuts its words short and never a
    control. The style picker and the intensity are made and left for the
    lens to put on the bar, see Lens.show_bar_mirrors. The well's children
    and the parts drawn inside the title and the pickers pass their clicks
    on, the pass count and the lines a drag of the bar, which the lens binds
    on the bar itself, see Lens.__init__."""

    def __init__(self, t, bar, look, words, clicks, glyph_font, height):
        kind = widgets.kind_of(look)
        self.look, self.kind, self.bar, self.words = look, kind, bar, words
        self.paint, self.lines, m = PAINT[kind], LINES[kind], SIZES[kind]
        self.s = look.scale_for(bar)
        self.parts = {}
        c, lg, px = look.c, look.legacy, self.px
        edge = sc.border(1, self.s)
        self.ground = c["deep"]
        t.configure(bg=c[self.lines["frame"]])
        bar.configure(bg=self.ground)
        room = height                   # the height the parts have, above the line along the bar's foot
        if self.lines["under"]:
            widgets.Rule(bar, look, self.lines["under"]).pack(side="bottom", fill="x")
            room -= 1
        well = height - 2 * WELL_INSET
        line = height - 2 * SEP_INSET[kind]

        # the controls, which go onto the bar first
        font, menu_char = icon_glyph(bar, MENU, px(m["menu_glyph"]))
        menu = self.part(bar, "menu_btn", "menu", font=font, shown=lambda logical: menu_char, bg=lg["bg"],
                         fg=lg["fg"])
        widgets.exact(menu, px(m["menu"]), room)
        menu.pack(side="left", padx=(px(m["lead"]), 0))
        menu.bind("<Button-1>", clicks["menu_btn"])
        for name, paint, hover in (("x_btn", "close", lg["close"]), ("max_btn", "caption", lg["hover"]),
                                   ("min_btn", "caption", lg["hover"])):
            b = self.part(bar, name, paint, font=glyph_font, bg=lg["cap"], fg=lg["fg"])
            widgets.exact(b, px(m["caption"]), room)
            b.pack(side="right")
            b.bind("<Button-1>", clicks[name])
            self.hover(b, hover, lg["cap"])
        tk.Frame(bar, bg=c[self.lines["sep"]], width=1, height=line, bd=0, highlightthickness=0).pack(
            side="right", padx=(px(m["sep"][0]), px(m["sep"][1])))
        case = look.fonts["page_button"].case
        set_btn = self.part(bar, "set_btn", "set", font_role="page_button", bg=lg["bg"], fg=lg["dim"],
                            shown=lambda logical: text.display_case(logical.strip(), case),
                            fit=(px(m["set_pad"]), px(m["set_pad"]), well),
                            highlightthickness=edge if self.paint["set"].get("border") else 0)
        set_btn.pack(side="right", padx=(px(m["set_gap"]), 0))
        set_btn.bind("<Button-1>", clicks["set_btn"])
        self.hover(set_btn, lg["hover"], lg["bg"])
        self.stepper(clicks, well).pack(side="right")

        # the words, which go on last
        title_case = look.fonts["bar_title"].case
        rule = m["title_rule"]
        after = px(m["title_pad"]) if rule is None else px(rule[0]) + 1 + px(rule[1])
        title = self.part(bar, "bar_title", "title", font_role="bar_title", bg=lg["bg"], fg=lg["accent"],
                          shown=lambda logical: text.display_case(logical.strip(), title_case),
                          fit=(px(m["title_pad"]), after, 0))
        title.pack(side="left")
        if rule is not None:
            ink = c[self.lines["title_rule"]]
            mark = tk.Frame(title, bg=ink, width=1, height=line, bd=0, highlightthickness=0)
            mark.place(relx=1.0, x=-px(rule[1]), rely=0.5, anchor="e")
            passes_on(mark, bar)
            kept_inside(title, mark, lambda: ink)
        type_ = look.font("bar_readout", False, bar)
        info = self.parts["info"] = tk.Label(bar, text=words["info"], bg=self.ground, fg=lg["dim"], font=type_,
                                             anchor="w", bd=0, padx=0, pady=0, highlightthickness=0)
        info.pack(side="left", padx=(max(0, px(m["readout_gap"]) - after), 0))
        profile = self.picker("prof_btn", clicks, well)
        profile.pack(side="left", padx=(px(m["picker_gap"]), px(m["picker_between"])))
        self.picker("style_btn", clicks, well)
        self.parts["intensity_lbl"] = tk.Label(bar, text=words["intensity_lbl"], bg=self.ground, fg=lg["dim"],
                                               font=type_, bd=0, padx=px(m["intensity_pad"]), pady=0,
                                               highlightthickness=0)

    def px(self, n):
        """n CSS pixels in screen pixels at the bar's scale."""
        return sc.px(n, self.s)

    def part(self, master, name, paint, fit=None, **kw):
        """A Part of the bar with the code's words for name, kept in parts."""
        widget = Part(master, self.look, self.paint[paint], fit=fit, text=self.words[name], bd=0, **kw)
        self.parts[name] = widget
        return widget

    @staticmethod
    def hover(widget, on, off):
        """The code's colours for a part under the pointer and away from it,
        as the lens gives its own bar's buttons, which the part draws in its
        paint."""
        widget.bind("<Enter>", lambda event: widget.configure(bg=on))
        widget.bind("<Leave>", lambda event: widget.configure(bg=off))

    def stepper(self, clicks, height):
        """The well with the pass count between its two buttons, height
        pixels high, Industrial's with a line round it and between the three.
        The count and the lines pass a drag on to the bar."""
        m, c, lg, px = SIZES[self.kind], self.look.c, self.look.legacy, self.px
        edge = sc.border(1, self.s)
        rim = edge if self.lines["well_edge"] else 0
        well = tk.Frame(self.bar, bg=c[self.lines["well"]], bd=0, highlightthickness=rim)
        if rim:
            well.configure(highlightbackground=c[self.lines["well_edge"]], highlightcolor=c[self.lines["well_edge"]])
        inner = height - 2 * rim
        boxed = edge if self.paint["step"].get("border") else 0
        font, minus_char = icon_glyph(well, REMOVE, px(m["step_glyph"]))
        minus = self.part(well, "minus", "step", font=font, shown=lambda logical: minus_char, bg=lg["bg"],
                          fg=lg["fg"], highlightthickness=boxed)
        widgets.exact(minus, px(m["step"]), inner)
        count = self.part(well, "pass_lbl", "count", font=self.look.font("value", True, well), bg=lg["bg"],
                          fg=lg["accent"], fit=(px(m["count_pad"]), px(m["count_pad"]), inner))
        passes_on(count, self.bar)
        font, plus_char = icon_glyph(well, ADD, px(m["step_glyph"]))
        plus = self.part(well, "plus", "step", font=font, shown=lambda logical: plus_char, bg=lg["bg"], fg=lg["fg"],
                         highlightthickness=boxed)
        widgets.exact(plus, px(m["step"]), inner)
        row = [minus, count, plus]
        if self.lines["seam"]:
            seams = [tk.Frame(well, bg=c[self.lines["seam"]], width=1, bd=0, highlightthickness=0) for _ in (0, 1)]
            for seam in seams:
                passes_on(seam, self.bar)
            row = [minus, seams[0], count, seams[1], plus]
        for widget in row:
            widget.pack(side="left", fill="y")
        for name, widget in (("minus", minus), ("plus", plus)):
            widget.bind("<Button-1>", clicks[name])
            self.hover(widget, lg["hover"], lg["bg"])
        # its size as its parts ask for it, which the packer gives it only
        # at the next idle moment, so the lens can measure the bar at once
        well.configure(width=sum(w.winfo_reqwidth() for w in row) + 2 * rim, height=height)
        return well

    def picker(self, name, clicks, height):
        """A picker, the profile's or the style's, height pixels high, its name
        on the well's colour and its chevron at its right, which passes its
        click and the pointer on to the picker."""
        m, c, lg, px = SIZES[self.kind], self.look.c, self.look.legacy, self.px
        before, right = m["picker_pad"]
        boxed = sc.border(1, self.s) if self.paint["picker"].get("border") else 0
        widget = self.part(self.bar, name, "picker", font_role="bar_picker", shown=panel.picker_words,
                           bg=lg["bg"], fg=lg["dim"], fit=(px(before), px(m["chevron_gap"] + m["chevron"] + right),
                                                           height), highlightthickness=boxed)
        font, char = widgets.glyph(widget, "chevron_down", px(m["chevron"]))
        chevron = tk.Label(widget, text=char, font=font, bg=widgets.real(widget, "bg"),
                           fg=c[self.lines["chevron"]], bd=0, padx=0, pady=0, highlightthickness=0)
        chevron.place(relx=1.0, x=-px(right), rely=0.5, anchor="e")
        passes_on(chevron, widget)
        kept_inside(widget, chevron, lambda: widgets.real(widget, "bg"))
        widget.bind("<Button-1>", clicks[name])
        self.hover(widget, lg["hover"], lg["bg"])
        return widget

    def grips(self, grips):
        """The frame's grips, the lens's strips down its sides and along its
        foot, in the bar's colour, as the drawings draw the frame round the
        picture. A grip it cannot colour keeps the lens's colour, and the
        kit's fault line says so, see widgets.fault."""
        for grip in grips:
            try:
                grip.configure(bg=self.ground)
            except tk.TclError as e:
                widgets.fault(grip, e, aside=True)
