"""The frame of Settings in a drawn look, the rail or the tab band that turns
its pages, the page's title, the part a page scrolls in, the column or the
strip its explanation shows in, and the footer with Save and Cancel.

The pages stay the frames of ttk's notebook that the lens makes them in, its
tabs drawn by nothing, so the lens builds them and the tests turn and read
them as in the classic look. The notebook stays a child of the dialog, held
as one window item in the canvas of ScrollHost, which lies lowest of the
dialog's widgets with the notebook just above it. The frame's other parts lie
above both, so a page taller than its part scrolls under the title and the
footer, and a walk through the dialog's widgets, which Tk lists in that
order, meets a page's own widgets before any of the frame's.

SettingsFrame makes the notebook as the dialog is made. Once the lens has
built the pages, finish fits the window to the screen, see
lens_look.fit.settings_fit, and lays the frame out round them, see
fit.settings_parts. A page that asks for more width than its drawn part has
widens the window rather than being cut.

Every word the frame shows is given to it by the lens, the pages' names on
the notebook, the version, the line that says how an explanation comes up,
the keys' words, Save and Cancel, and the explanations, the settings' labels
and the headings the lens gives its Hints.

Where the fit leaves room for it, the explanation of the setting picked shows
in the frame's own part for it, console's pane, folio's margin note or
industrial's strip, and the footer shows the keys that walk the rows, see
SettingsFrame.select, explained and RowWalker. The pointer picks the setting
it is on at once, as F1 does the one that has the keyboard. Where the fit
leaves no room, the explanation comes up by the pointer as in the classic
look, and the footer shows the line that says so.

The rows of the pages are made by Rows, which the lens's helpers ask for each
row in place of making today's, with the same widgets, words and variables,
see Rows. Rows keeps each row the keys and the pointer can pick as a Stop.

Imports tkinter and the package, and nothing of the lens.
"""
import tkinter as tk
from tkinter import ttk

from lens_look import faces, fit
from lens_look import scale as sc
from lens_look import text, tokens, widgets, win

# The ttk style of a drawn look's notebook, whose tabs nothing draws
STYLE = "LensLook.TNotebook"

# Windows 11's taskbar along the foot of a screen in CSS pixels at 100
# percent, for the screen of a given size the tests fit Settings to, see
# screen_room
TASKBAR = 48

# A dialog's caption in CSS pixels, about what Windows 11 draws, where the
# dialog's own frame cannot be read, see caption_of
CAPTION = 31

# How far a notch of the wheel scrolls a page, in CSS pixels
WHEEL = 48

# The least height in CSS pixels the part a page scrolls in keeps where
# Industrial's strip grows into it, see SettingsFrame.grow_strip
VIEW_LEAST = 160

# What the clam notebook keeps round a page on each side, in pixels at every
# scale, see SettingsFrame.finish and Rows
NOTEBOOK_INSET = 2


def screen_room(screen, s):
    """The work area of a screen of this (width, height) in pixels at the
    scale s, its taskbar along the foot, for the tests, which fit Settings to
    a screen of 1920x1080 on any monitor."""
    return int(screen[0]), int(screen[1]) - sc.px(TASKBAR, s)


def caption_of(dialog, s):
    """The caption and the border of the dialog's frame in pixels, as
    (caption, border), read from the frame Windows draws round it, or what
    Windows 11 draws at the scale s where that cannot be read."""
    try:
        got = win.frame_insets(dialog)
    except Exception:
        got = None
    if not got:
        return sc.px(CAPTION, s), 1
    left, top, right, bottom = got
    return top, max(left, right, bottom)


class SettingsFrame(object):
    """The frame of Settings in a drawn look, see the module's docstring. nb
    is the notebook the lens adds its pages to. Once finish has laid the
    frame out, fit is the fit with the frame's parts, compact and columns say
    how the rows are to be laid out, and host, nav, head, region and footer
    are the frame's parts, nav being the rail or the tab band and region the
    explanation's column or strip, each None where the fit has none."""

    def __init__(self, dialog, look):
        self.dialog, self.look = dialog, look
        self.kind = widgets.kind_of(look)
        # the explanation in the frame's own part, see finish and select
        self.hints = self.walker = self.lit = None
        self.picked = (None, None)
        self._refresh = None
        self._lit_labels = []
        surface = look.c["surface"]
        style = ttk.Style(dialog)
        try:
            style.theme_use("clam")     # whose notebook takes the colours it is given, as in the classic look
        except tk.TclError:
            pass
        style.configure(STYLE, background=surface, borderwidth=0, tabmargins=0, padding=0, lightcolor=surface,
                        darkcolor=surface, bordercolor=surface)
        style.layout(STYLE, [("Notebook.client", {"sticky": "nswe"})])
        style.layout(STYLE + ".Tab", [])    # no tab is drawn, the rail or the tab band turns the pages
        self.nb = ttk.Notebook(dialog, style=STYLE, takefocus=0)
        self.fit, self.compact, self.columns = None, False, 1
        self.host = self.nav = self.head = self.region = self.footer = None
        self.rows = Rows(self)

    def finish(self, room, save, cancel, version, help_line, keys=(), hints=None):
        """Lay the frame out round the pages the lens built. room is the
        (width, height) of the work area the window is fitted to, save and
        cancel are (words, command) for Save and Cancel, version and help_line
        the words of the version and of the line that says how an explanation
        comes up, and keys the footer's key caps with their words, as ((key,
        ...), words) pairs, the keys of RowWalker. hints are the dialog's
        Hints. Where the fit leaves room for the explanation's part and hints
        are given, the explanation shows there, the keys walk the rows and the
        footer shows them, see _explain. Else the explanation comes up by the
        pointer and the footer shows help_line. The window takes its fitted
        size here, and the lens places and shows it. Returns the fit, see
        fit.settings_fit, with the frame's parts, see fit.settings_parts, the
        caption and the border it was fitted with, the width the pages needed
        beyond the drawn width, and the room."""
        look, t, nb = self.look, self.dialog, self.nb
        s = look.scale_for(t)
        # the rows' choices still open drawn, and industrial's modules in
        # their drawn columns, before the pages are measured, see Rows.close
        self.rows.close()
        t.update_idletasks()
        caption, border = caption_of(t, s)
        # the width the notebook asks for its widest page, which takes in
        # what its client keeps round a page, in clam two pixels a side
        need = nb.winfo_reqwidth() if nb.tabs() else 0
        fitted = fit.settings_fit(look, s, room[0], room[1], caption, border)
        extra = max(0, need - fit.settings_parts(look, s, fitted)["room"])
        if extra:
            fitted = fit.settings_fit(look, s, room[0], room[1], caption, border, extra_w=extra)
        # the compact rows, and one column of modules, where the fit asks
        self.rows.fitted(fitted)
        parts = fit.settings_parts(look, s, fitted)
        self.fit = dict(fitted, parts=parts, caption=caption, border=border, extra=extra, room=tuple(room))
        self.compact, self.columns = fitted["compact"], fitted["columns"]
        # the keys in the footer only where they work, with the explanation in
        # the frame's own part, see _explain
        explain = hints is not None and fitted["explain"] != "popup"
        if self.kind == "industrial":
            self._band_layout(parts, save, cancel, version, help_line, keys if explain else ())
        else:
            self._rail_layout(parts, save, cancel, version, help_line, keys if explain else ())
        # the canvas lowest and the notebook it holds just above it, the
        # frame's other parts above both, see the module's docstring
        tk.Misc.lower(self.host)
        nb.bind("<<NotebookTabChanged>>", self.turned, add="+")
        t.bind("<MouseWheel>", self.host.wheel, add="+")
        t.geometry("%dx%d" % fitted["client"])
        if explain and self.region is not None:
            self._explain(hints, cancel[1])
        self.turned()
        return self.fit

    # the explanation in the frame's own part

    def _explain(self, hints, cancel):
        """The explanation of a setting in the frame's own part from now on,
        not by the pointer, hints.mode being pane and hints.select select. The
        keys walk the rows, see RowWalker, cancel being what Esc does. The
        part follows a choice that changes, by a click or a key, and the
        margin note its row as the page scrolls."""
        t = self.dialog
        self.hints = hints
        hints.mode, hints.select = "pane", self.select
        self.walker = RowWalker(self, cancel)
        for seq in ("<ButtonRelease-1>", "<KeyRelease>"):
            t.bind(seq, lambda event: self.refresh_soon(), add="+")
        self.host.scrolled.append(self._scrolled)

    def page_name(self):
        """The name of the page that shows, or None."""
        try:
            return str(self.nb.tab(self.nb.select(), "text"))
        except tk.TclError:
            return None

    def select(self, widget, how="pointer"):
        """Hints.select in a drawn look. The setting the widget is part of is
        picked, by the pointer, F1, the keys or a control that got the
        keyboard. Its row is lit, and the frame's part for the explanation
        shows it, see explained. how says which of those picked it. None
        shows the page's own, see idle."""
        if widget is None:
            return self.idle()
        stop = self.rows.stop_of(widget)
        self._light(stop)
        if self.walker is not None:
            self.walker.current = stop
        self.picked = (widget, stop)
        self._show()

    def idle(self):
        """The page's own explanation, as a page is turned to, with no row
        lit and none picked, see idle_explained. The keyboard leaves a control
        of a page that no longer shows."""
        self._light(None)
        if self.walker is not None:
            self.walker.current = None
        if self.hints is not None:
            self.hints.over = None
        self.picked = (None, None)
        try:
            focus = self.dialog.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        if focus is not None and focus is not self.dialog and self.host.holds(focus) \
                and not _inside(focus, self.host.page()):
            self.dialog.focus_set()
        self._show()

    def refresh_soon(self):
        """Show the setting picked again once Tk is idle, as a choice of it
        may have changed by a click or a key."""
        if self._refresh is None and self.region is not None:
            try:
                self._refresh = self.dialog.after_idle(self._refreshed)
            except tk.TclError:
                self._refresh = None

    def _refreshed(self):
        self._refresh = None
        try:
            if self.dialog.winfo_exists():
                self._show()
        except tk.TclError:
            pass

    def _show(self):
        """The part for the explanation shows what is picked, or the page's
        own, where that differs from what it shows."""
        region = self.region
        if region is None or self.hints is None:
            return
        widget, stop = self.picked
        if widget is None:
            name = self.page_name() or ""
            sections = [s for s in self.hints.sections if s["page"] == name]
            content = idle_explained(name, [(s["title"], s["why"], s["beside"]) for s in sections])
            anchor = sections[0]["row"] if sections else None
        else:
            content = self._content(widget, stop)
            anchor = stop.anchor if stop is not None else widget
        region.present(content, anchor)

    def _content(self, widget, stop):
        """What the explanation of the setting picked is made of, from the
        dialog's Hints, see explained."""
        h = self.hints
        own = list(stop.widgets) if stop is not None else [widget]
        options = list(stop.options) if stop is not None else []
        index = next((h.section_of[w] for w in own + options if w in h.section_of), None)
        sec = h.sections[index] if index is not None else None
        section = (sec["title"], sec["why"], sec["beside"]) if sec is not None else None
        heading = stop is None and sec is not None and sec["row"] is widget
        label = next((h.titles[w] for w in own if h.titles.get(w)), None)
        why = next((h.texts[w] for w in own if h.texts.get(w)), "")
        chosen = [(str(b.cget("text")), h.texts.get(b, ""), faces.selected(b)) for b in options]
        if heading:
            label, why = sec["title"], sec["why"]
        elif stop is None:
            label = None                # a sentence of a page, under its heading's title
        return explained(label, why, section, chosen, self.page_name() or "", heading)

    def _light(self, stop):
        """The row of the stop picked lit, its label drawn picked, and the
        row lit before unlit."""
        band = stop.band if stop is not None else None
        labels = list(stop.labels) if stop is not None else []
        for w in self._lit_labels:
            if w not in labels:
                _pick_label(w, self.look, False)
        if band is not self.lit:
            if self.lit is not None:
                try:
                    self.lit.light(False)
                except tk.TclError:
                    pass
            self.lit = band
            if band is not None:
                band.light(True)
        for w in labels:
            _pick_label(w, self.look, True)
        self._lit_labels = labels

    def _scrolled(self):
        if isinstance(self.region, MarginNote):
            self.region.follow()

    def _rail_layout(self, parts, save, cancel, version, help_line, keys):
        """Console's and folio's frame, the rail down the left, the title and
        the page beside it, the explanation's column down the right, and the
        footer along the foot."""
        t, look, nb = self.dialog, self.look, self.nb
        for i, size in enumerate((parts["rail"], parts["main"], parts["column"])):
            t.columnconfigure(i, minsize=size, weight=0)
        for i, size in enumerate((parts["head"], parts["view"], parts["footer"])):
            t.rowconfigure(i, minsize=size, weight=0)
        body = parts["head"] + parts["view"]
        self.host = ScrollHost(t, look, nb, parts["main"], parts["view"], parts["pad"])
        self.host.grid(row=1, column=1, sticky="nsew")
        self.nav = Rail(t, look, nb, parts["rail"], body, version)
        self.nav.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.head = Head(t, look, parts["main"], parts["head"], parts["title"])
        self.head.grid(row=0, column=1, sticky="nsew")
        if parts["column"]:
            region = Pane if self.kind == "console" else MarginNote
            self.region = region(t, look, parts["column"], body)
            self.region.grid(row=0, column=2, rowspan=2, sticky="nsew")
        width = parts["rail"] + parts["main"] + parts["column"]
        self.footer = Footer(t, look, width, parts["footer"], save, cancel, help_line, keys=keys)
        self.footer.grid(row=2, column=0, columnspan=3, sticky="nsew")

    def _band_layout(self, parts, save, cancel, version, help_line, keys):
        """Industrial's frame, the tab band along the top, the page under it,
        the strip of the explanation under the page, and the key strip with
        the version along the foot."""
        t, look, nb = self.dialog, self.look, self.nb
        t.columnconfigure(0, minsize=parts["main"], weight=0)
        for i, size in enumerate((parts["band"], parts["view"], parts["strip"], parts["footer"])):
            t.rowconfigure(i, minsize=size, weight=0)
        self.host = ScrollHost(t, look, nb, parts["main"], parts["view"], parts["pad"])
        self.host.grid(row=1, column=0, sticky="nsew")
        self.nav = TabBand(t, look, nb, parts["main"], parts["band"])
        self.nav.grid(row=0, column=0, sticky="nsew")
        self.region = Strip(t, look, parts["main"], parts["strip"])
        self.region.grid(row=2, column=0, sticky="nsew")
        # a text taller than the strip grows it into the page above it, which
        # keeps at least VIEW_LEAST, see grow_strip
        least = sc.px(VIEW_LEAST, look.scale_for(t))
        self.region.spare = lambda: max(0, parts["view"] - least)
        self.region.resized = self.grow_strip
        self.footer = Footer(t, look, parts["main"], parts["footer"], save, cancel, help_line, version, keys)
        self.footer.grid(row=3, column=0, sticky="nsew")

    def grow_strip(self, extra):
        """Industrial's strip extra pixels taller than the fit made it, for a
        text that needs more room than its drawn height, see _Region.grow_to,
        and the part the page scrolls in as much shorter, so the window keeps
        its size and the page scrolls a little further. 0 gives both their
        fitted heights back."""
        parts = self.fit["parts"]
        self.dialog.rowconfigure(1, minsize=parts["view"] - extra)
        self.dialog.rowconfigure(2, minsize=parts["strip"] + extra)
        self.host.resize(parts["view"] - extra)

    def turned(self, event=None):
        """The page turned, by the rail, the tab band, the keys, the code or
        a test, which all turn it through the notebook. Its item is lit, its
        name is the title, it shows from its top, and the explanation's part
        shows the page's own, see idle."""
        try:
            index = self.nb.index(self.nb.select())
        except tk.TclError:
            return                      # no page yet
        if self.nav is not None:
            self.nav.show(index)
        if self.head is not None:
            self.head.show(self.nb.tab(index, "text"))
        if self.host is not None:
            self.host.to_top()
        if self.hints is not None:
            self.idle()


class ScrollHost(tk.Canvas):
    """The part a page scrolls in, a canvas holding the whole notebook as one
    window item, the pages staying the notebook's own. The notebook is as
    tall as its tallest page and the canvas scrolls as far as the page shown
    reaches, so a page whose rows grow while it shows is never cut. The wheel
    scrolls it where the pointer is on the page, and keep scrolls a widget on
    the page into view. pad is the room round the page, as (top, right,
    bottom, left), and every size is in pixels. scrolled are called after
    each scroll, as the margin note follows its row."""

    def __init__(self, master, look, nb, width, height, pad):
        s = look.scale_for(master)
        tk.Canvas.__init__(self, master, width=width, height=height, bd=0, highlightthickness=0, takefocus=0,
                           bg=look.c["surface"], yscrollincrement=max(1, sc.px(WHEEL, s) // 3))
        self.nb, self.view, self.pad = nb, (width, height), tuple(pad)
        self.tall = height
        self.scrolled = []
        top, right, _bottom, left = self.pad
        self.create_window(left, top, window=nb, anchor="nw", width=max(1, width - left - right))
        nb.bind("<Configure>", lambda event: self.reach(), add="+")

    def page(self):
        """The page that shows, or None while the notebook has none."""
        try:
            name = str(self.nb.select())
            return self.nb.nametowidget(name) if name else None
        except (tk.TclError, KeyError):
            return None

    def reach(self):
        """Scroll as far as the page shown reaches, and no further. Whether
        it is taller than the part it shows in."""
        page = self.page()
        top, _right, bottom, _left = self.pad
        tall = top + (page.winfo_reqheight() if page is not None else 0) + bottom
        self.tall = max(tall, self.view[1])
        self.configure(scrollregion=(0, 0, self.view[0], self.tall))
        return tall > self.view[1]

    def to_top(self):
        """The page shown from its top, as on a turn of the page."""
        self.reach()
        self.yview_moveto(0.0)
        self._moved()

    def _moved(self):
        for follow in list(self.scrolled):
            try:
                follow()
            except tk.TclError:
                pass

    def holds(self, widget):
        """Whether the widget is this part or is on the page in it."""
        while widget is not None:
            if widget is self or widget is self.nb:
                return True
            widget = widget.master
        return False

    def wheel(self, event):
        """The wheel turned over the dialog. The page scrolls where the
        pointer is on it and it is taller than its part, but not where the
        pointer is on a list, which scrolls itself."""
        if not getattr(event, "delta", 0) or not self.reach():
            return
        try:
            under = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            return
        if under is None or not self.holds(under) or under.winfo_class() in ("Listbox", "Text"):
            return
        self.yview_scroll(-3 if event.delta > 0 else 3, "units")
        self._moved()

    def resize(self, height):
        """The part height pixels high, as Industrial's strip grows into it or
        gives the room back, see SettingsFrame.grow_strip, the page as far as
        it scrolled and the part scrolling as far as the page now reaches."""
        self.view = (self.view[0], height)
        self.configure(height=height)
        self.reach()
        self._moved()

    def keep(self, widget, margin=0):
        """Scroll so a widget on the page is in view, margin pixels clear of
        the part's top and foot, as a row the keys pick is kept in view."""
        if not self.reach():
            return
        y0 = widget.winfo_rooty() - self.nb.winfo_rooty() + self.pad[0] - margin
        y1 = y0 + widget.winfo_height() + 2 * margin
        seen = self.canvasy(0)
        if y0 < seen:
            self.yview_moveto(max(0.0, y0) / float(self.tall))
        elif y1 > seen + self.view[1]:
            self.yview_moveto(max(0.0, y1 - self.view[1]) / float(self.tall))
        self._moved()


class RailItem(tk.Frame):
    """An item of the rail, a page's name on a band that is lit while its
    page shows, console's with a chevron at its right and folio's with a bar
    of ink down its left. words is the name in the look's case, inset where
    it starts, and fonts the type of the name and of the lit name."""

    def __init__(self, master, look, words, width, height, inset, fonts, ground):
        kind = widgets.kind_of(look)
        c, m = look.c, look.m
        s = look.scale_for(master)
        self.look, self.ground, self.fonts = look, ground, fonts
        tk.Frame.__init__(self, master, bg=ground, width=width, height=height, bd=0, highlightthickness=0)
        self.words = tk.Label(self, text=words, bg=ground, fg=c["muted"], font=fonts[0], bd=0, padx=0, pady=0)
        self.words.place(x=inset, rely=0.5, anchor="w")
        if kind == "console":
            font, mark = widgets.glyph(self, "right", sc.px(m["chevron"], s))
            self.mark = tk.Label(self, text=mark, bg=c["chosen"], fg=c["muted"], font=font, bd=0, padx=0, pady=0)
            self.mark_at = dict(relx=1.0, x=-sc.px(m["rail_item_pad"][1], s), rely=0.5, anchor="e")
        else:
            self.mark = tk.Frame(self, bg=c["strong"], width=sc.px(m["rail_bar"], s), bd=0, highlightthickness=0)
            self.mark_at = dict(x=0, y=0, relheight=1.0)

    def clicked(self, command):
        for widget in (self, self.words, self.mark):
            widget.bind("<Button-1>", command)

    def light(self, on):
        c = self.look.c
        ground = c["chosen"] if on else self.ground
        tk.Frame.configure(self, bg=ground)
        self.words.configure(bg=ground, fg=c["strong"] if on else c["muted"], font=self.fonts[1 if on else 0])
        if on:
            self.mark.place(**self.mark_at)
        else:
            self.mark.place_forget()


class Rail(tk.Frame):
    """The rail down the left of console's and folio's Settings, an item for
    each page with the chosen one lit, and the version at its foot. A click
    on an item turns to its page through the notebook, and the rail follows
    the notebook, so it shows a page turned by the code or a test too."""

    def __init__(self, master, look, nb, width, height, version):
        kind = widgets.kind_of(look)
        c, m = look.c, look.m
        s = look.scale_for(master)
        self.nb = nb
        ground = c["deep"] if kind == "console" else c["surface"]
        tk.Frame.__init__(self, master, bg=ground, width=width, height=height, bd=0, highlightthickness=0)
        if kind == "console":
            top, side = sc.px(m["rail_pad"][0], s), sc.px(m["rail_pad"][1], s)
            foot, x, item_w = top, side, width - 2 * side
            inset = sc.px(m["rail_item_pad"][0], s)
            version_x = side + sc.px(m["version_in"], s)
        else:
            # the rule down its right, inside its width
            widgets.Rule(self, look, vertical=True).place(relx=1.0, x=-1, y=0, relheight=1.0)
            top, foot, x, item_w = sc.px(m["rail_top"], s), sc.px(m["rail_bottom"], s), 0, width - 1
            inset = sc.px(m["rail_bar"], s) + sc.px(m["rail_text_inset"], s)
            version_x = sc.px(m["version_in"], s)
        item_h, gap = sc.px(m["rail_item_h"], s), sc.px(m["rail_gap"], s)
        fonts, case = (look.font("rail", False, self), look.font("rail", True, self)), look.fonts["rail"].case
        self.items = []
        for i, tab in enumerate(nb.tabs()):
            item = RailItem(self, look, text.display_case(nb.tab(tab, "text"), case), item_w, item_h, inset, fonts,
                            ground)
            item.place(x=x, y=top + i * (item_h + gap))
            item.clicked(lambda event, i=i: self.nb.select(i))
            self.items.append(item)
        self.version = tk.Label(self, text=version, bg=ground, fg=c["muted"], font=look.font("version", False, self),
                                bd=0, padx=0, pady=0)
        self.version.place(x=version_x, rely=1.0, y=-foot, anchor="sw")

    def show(self, index):
        for i, item in enumerate(self.items):
            item.light(i == index)


class Tab(tk.Frame):
    """A tab of industrial's band, its page's name in capitals, a rule along
    its top and a line along its foot, and while its page shows on the page's
    plate with an amber top and no line at its foot, so it stands on the
    page."""

    def __init__(self, master, look, words, width, font):
        c, m = look.c, look.m
        s = look.scale_for(master)
        self.look, self.wide = look, width
        self.tops = tuple(sc.px(v, s) for v in m["tab_top"])
        tk.Frame.__init__(self, master, bg=c["tab"], bd=0, highlightthickness=0)
        self.rule_top = tk.Frame(self, bg=c["rule"], height=self.tops[0], bd=0, highlightthickness=0)
        self.rule_top.place(x=0, y=0, relwidth=1.0)
        self.rule_foot = tk.Frame(self, bg=c["edge"], height=1, bd=0, highlightthickness=0)
        self.rule_foot.place(x=0, rely=1.0, y=-1, relwidth=1.0)
        self.words = tk.Label(self, text=words, bg=c["tab"], fg=c["muted"], font=font, bd=0, padx=0, pady=0)
        self.words.place(relx=0.5, rely=0.5, y=self.tops[0] // 2, anchor="center")

    def clicked(self, command):
        for widget in (self, self.rule_top, self.rule_foot, self.words):
            widget.bind("<Button-1>", command)

    def light(self, on):
        c = self.look.c
        ground = c["surface"] if on else c["tab"]
        tk.Frame.configure(self, bg=ground)
        self.rule_top.configure(bg=c["accent"] if on else c["rule"], height=self.tops[1 if on else 0])
        self.rule_foot.configure(bg=ground if on else c["edge"])
        self.words.configure(bg=ground, fg=c["text"] if on else c["muted"])
        self.words.place_configure(y=self.tops[1 if on else 0] // 2)


class TabBand(tk.Frame):
    """Industrial's band of tabs along the top of Settings, a tab for each
    page, the chosen one taller. A click on a tab turns to its page through
    the notebook, and the band follows the notebook, so it shows a page
    turned by the code or a test too. The tabs share the band's width, see
    fit.tab_widths."""

    def __init__(self, master, look, nb, width, height):
        c, m = look.c, look.m
        s = look.scale_for(master)
        tk.Frame.__init__(self, master, bg=c["deep"], width=width, height=height, bd=0, highlightthickness=0)
        # the line along its foot, which the chosen tab stands over
        widgets.Rule(self, look, role="edge").place(x=0, rely=1.0, y=-1, relwidth=1.0)
        side, gap, pad = sc.px(m["tab_band_pad"][1], s), sc.px(m["tab_gap"], s), sc.px(m["tab_pad"], s)
        font, case = look.font("rail", False, self), look.fonts["rail"].case
        names = [text.display_case(nb.tab(tab, "text"), case) for tab in nb.tabs()]
        natural = [int(self.tk.call("font", "measure", font, name)) + 2 * pad for name in names]
        widths = fit.tab_widths(natural, width - 2 * side - gap * max(0, len(names) - 1))
        self.heights = (sc.px(m["tab_h"], s), sc.px(m["tab_chosen_h"], s))
        self.items, self.at, x = [], [], side
        for i, (name, w) in enumerate(zip(names, widths)):
            tab = Tab(self, look, name, w, font)
            tab.clicked(lambda event, i=i: nb.select(i))
            self.items.append(tab)
            self.at.append(x)
            x += w + gap

    def show(self, index):
        for i, tab in enumerate(self.items):
            tab.light(i == index)
            tab.place(x=self.at[i], rely=1.0, y=0, anchor="sw", width=tab.wide,
                      height=self.heights[1 if i == index else 0])


class Head(tk.Frame):
    """The page's name as its title over the part it scrolls in, console's
    and folio's, in the look's title type, smaller in the compact layout.
    size is the title's size in CSS pixels."""

    def __init__(self, master, look, width, height, size):
        kind = widgets.kind_of(look)
        c, m = look.c, look.m
        s = look.scale_for(master)
        tk.Frame.__init__(self, master, bg=c["surface"], width=width, height=height, bd=0, highlightthickness=0)
        family, _size, weight = look.font("title", False, self)
        if kind == "console":
            x, top = sc.px(m["main_pad"][1], s), sc.px(m["main_pad"][0], s)
        else:
            x, top = sc.px(m["main_pad"][3], s), sc.px(m["title_top"], s)
        self.case = look.fonts["title"].case
        self.words = tk.Label(self, text="", bg=c["surface"], fg=c["strong"], font=(family, -sc.px(size, s), weight),
                              bd=0, padx=0, pady=0)
        self.words.place(x=x, y=top + (height - top) // 2, anchor="w")

    def show(self, name):
        self.words.configure(text=text.display_case(name, self.case))


class _Region(tk.Frame):
    """The part of Settings an explanation shows in, its words placed in it
    so it never asks for more room than it has. The pane and the margin note
    have the column's whole height. Industrial's strip, and the NR settings
    panel's part, which is one of these too, have their drawn height, and a
    text that needs more grows them by a line or two, see grow_to, where
    there is room for that. A check refuses before it ships a text that
    would not fit. shown is the content it shows, see explained, for the
    checks. present shows a content, and where drawing it fails the part
    stays blank and the lens's log says so once, see widgets.fault, while
    Settings goes on working."""

    GROUND = "deep"

    def __init__(self, master, look, width, height):
        tk.Frame.__init__(self, master, bg=look.c[self.GROUND], width=width, height=height, bd=0,
                          highlightthickness=0)
        self.look, self.size = look, (width, height)
        self.s = look.scale_for(master)
        self.shown, self.parts, self.fault = None, [], None
        # the height the part has where its text fits, which it grows from,
        # how far it may grow, see grow_to, and what hears that it did, called
        # with the pixels it has above that height
        self.base = height
        self.spare = lambda: 0
        self.resized = None

    def px(self, n):
        return sc.px(n, self.s)

    def grow_to(self, need, room, line):
        """The part as tall as lines that need need pixels where its own
        height gives them room pixels: that height where they fit, else
        taller by what fit.grown gives, at most a line or two of line pixels
        and no more than spare has left. Returns the room the lines have
        now."""
        extra = fit.grown(need, room, line, self.spare())
        height = self.base + extra
        if height != self.size[1]:
            self.size = (self.size[0], height)
            self.configure(height=height)
        return room + extra

    def linespace(self, font):
        """The height of a line of a font, as Tk sets lines of it."""
        return int(self.tk.call("font", "metrics", font, "-linespace"))

    def present(self, content, anchor=None):
        """Show this content where it differs from what shows, else only
        follow the row it is about, anchor."""
        if self.fault is not None:
            return
        try:
            if content != self.shown:
                for part in self.parts:
                    part.destroy()
                self.parts = []
                self.shown = content
                self.show(content)
            self.anchored(anchor)
        except Exception as exc:
            self.fault = str(exc) or type(exc).__name__
            for part in self.parts:
                try:
                    part.destroy()
                except tk.TclError:
                    pass
            self.parts = []
            widgets.fault(self, exc)

    def show(self, content):
        raise NotImplementedError

    def anchored(self, anchor):
        """The row the content is about, which the margin note stands level with."""

    def words(self, master, words, role, colour, wrap, ground=None, case=None, lit=False):
        """A label of the explanation in a role's type, its words broken at
        wrap pixels."""
        font = self.look.font(role, lit, self)
        if case is None:
            case = self.look.fonts[role].case
        return tk.Label(master, text=text.display_case(words, case), bg=ground or self.look.c[self.GROUND],
                        fg=colour, font=font, justify="left", anchor="w", wraplength=max(1, int(wrap)), bd=0,
                        padx=0, pady=0)


class Pane(_Region):
    """Console's pane down the right of Settings, the explanation of the
    setting picked, as Main draws it: its title, its explanation, for a
    choice whose choices have explanations of their own each with its own,
    the chosen one marked, and at its foot the words beside the setting's
    heading as a sentence. Before a setting is picked it lists the page's
    sections, each with its explanation, as many as it holds whole and at
    least the first, as on a short screen the narrow pane holds fewer, see
    fit.whole."""

    def show(self, content):
        c, r = self.look.c, REGION["console"]
        top, side, foot = (self.px(v) for v in r["pad"])
        width, height = self.size
        inner = max(1, width - 2 * side)
        body = tk.Frame(self, bg=c["deep"], bd=0, highlightthickness=0)
        self.parts.append(body)
        if content["idle"]:
            made = []
            for i, (title, why) in enumerate(content["sections"]):
                section = [(self.words(body, title, "explain_option", c["strong"], inner),
                            self.px(r["sections_gap"]) if i else 0)]
                if why:
                    section.append((self.words(body, why, "explain_option_text", c["text"], inner),
                                    self.px(r["option_text"])))
                made.append(section)
            keep = fit.whole([sum(gap + w.winfo_reqheight() for w, gap in s) for s in made], height - top - foot)
            for n, section in enumerate(made):
                for w, gap in section:
                    if n < keep:
                        w.pack(anchor="w", pady=(gap, 0))
                    else:
                        w.destroy()
        else:
            self.words(body, content["title"], "explain_title", c["strong"], inner).pack(anchor="w")
            if content["why"]:
                self.words(body, content["why"], "explain_text", c["text"], inner).pack(
                    anchor="w", pady=(self.px(r["title_gap"]), 0))
            if content["options"]:
                above, below = (self.px(v) for v in r["rule"])
                widgets.Rule(body, self.look, role="lit").pack(fill="x", pady=(above, below))
                into = self.px(r["mark"]) + self.px(r["mark_gap"])
                for i, (name, why, chosen) in enumerate(content["options"]):
                    row = tk.Frame(body, bg=c["deep"], bd=0, highlightthickness=0)
                    row.pack(anchor="w", fill="x", pady=(self.px(r["option_gap"]) if i else 0, 0))
                    OptionMark(row, self.look, chosen, c["deep"]).pack(side="left")
                    self.words(row, name, "explain_option", c["strong"] if chosen else c["text"],
                               inner - into).pack(side="left", padx=(self.px(r["mark_gap"]), 0))
                    if why:
                        self.words(body, why, "explain_option_text", c["text"] if chosen else c["muted"],
                                   inner - into).pack(anchor="w", padx=(into, 0), pady=(self.px(r["option_text"]), 0))
        body.place(x=side, y=top, width=inner)
        if content["footnote"]:
            note = tk.Frame(self, bg=c["deep"], bd=0, highlightthickness=0)
            self.parts.append(note)
            widgets.Rule(note, self.look, role="lit").pack(fill="x")
            self.words(note, content["footnote"], "hints", c["muted"], inner).pack(
                anchor="w", pady=(self.px(r["foot"]), 0))
            note.place(x=side, rely=1.0, y=-foot, anchor="sw", width=inner)


class MarginNote(_Region):
    """Folio's column down the right of Settings, ruled off from the page,
    and in it the explanation of the setting picked as a note level with its
    row, as Paper-Settings draws it, a bar of the accent colour down its left,
    its title and its explanation, and for a choice whose choices have
    explanations of their own each with its own, the chosen one marked. The
    note stays inside the column as the page scrolls, see follow. Before a
    setting is picked it is the page's first section's, level with its
    heading."""

    GROUND = "surface"

    def __init__(self, master, look, width, height):
        _Region.__init__(self, master, look, width, height)
        widgets.Rule(self, look, vertical=True).place(x=0, y=0, relheight=1.0)
        self.note, self.anchor = None, None
        self.bind("<Configure>", lambda event: self.follow(), add="+")

    def show(self, content):
        c, r = self.look.c, REGION["folio"]
        width = self.size[0]
        note = self.note = tk.Frame(self, bg=c["surface"], bd=0, highlightthickness=0)
        self.parts.append(note)
        tk.Frame(note, bg=c["accent"], width=self.px(r["bar"]), bd=0, highlightthickness=0).pack(side="left", fill="y")
        body = tk.Frame(note, bg=c["surface"], bd=0, highlightthickness=0)
        body.pack(side="left", fill="both", expand=True, padx=(self.px(r["bar_gap"]), 0))
        inner = max(1, width - 1 - self.px(r["left"]) - self.px(r["right"]) - self.px(r["bar"]) - self.px(r["bar_gap"]))
        gap = self.px(r["gap"])
        self.words(body, content["title"], "explain_title", c["text"], inner).pack(anchor="w")
        if content["why"]:
            self.words(body, content["why"], "explain_text", c["text"], inner).pack(anchor="w", pady=(gap, 0))
        if content["options"]:
            widgets.Rule(body, self.look).pack(fill="x", pady=(gap, 0))
            for name, why, chosen in content["options"]:
                ink = c["text"] if chosen else c["muted"]
                row = tk.Frame(body, bg=c["surface"], bd=0, highlightthickness=0)
                row.pack(anchor="w", fill="x", pady=(gap, 0))
                OptionMark(row, self.look, chosen, c["surface"]).pack(side="left")
                self.words(row, name, "explain_option", ink, inner - self.px(r["mark"]) - self.px(r["mark_gap"])).pack(
                    side="left", padx=(self.px(r["mark_gap"]), 0))
                if why:
                    self.words(body, why, "explain_option_text", ink, inner).pack(
                        anchor="w", pady=(self.px(r["option_gap"]), 0))

    def anchored(self, anchor):
        self.anchor = anchor
        self.follow()

    def follow(self):
        """The note level with its row, and kept inside the column, as the
        page scrolls under it or the window first shows."""
        note = self.note
        if note is None or self.fault is not None:
            return
        try:
            r = REGION["folio"]
            width, height = self.size
            note.update_idletasks()
            tall = note.winfo_reqheight()
            y = 0
            if self.anchor is not None and self.anchor.winfo_ismapped():
                y = self.anchor.winfo_rooty() - self.winfo_rooty()
            y = max(0, min(y, height - tall))
            left = 1 + self.px(r["left"])
            note.place(x=left, y=y, width=max(1, width - left - self.px(r["right"])))
        except tk.TclError:
            pass


class Strip(_Region):
    """Industrial's strip under the page, a line along its top and an amber
    bar down its left, and in it the explanation of the setting picked, as
    Industrial-Settings draws it: the section in capitals, under it the name
    of the setting or of the choice chosen, and beside them the
    explanation. Before a setting is picked it is the page's first
    section's, the page's name over its title. A text that needs more than
    the strip's height grows it into the page above it, see
    SettingsFrame.grow_strip."""

    def __init__(self, master, look, width, height):
        _Region.__init__(self, master, look, width, height)
        c, m = look.c, look.m
        widgets.Rule(self, look, role="edge").place(x=0, y=0, relwidth=1.0)
        tk.Frame(self, bg=c["accent"], width=sc.px(m["strip_bar"], self.s), bd=0, highlightthickness=0).place(
            x=0, y=1, relheight=1.0, height=-1)

    def show(self, content):
        c, r = self.look.c, REGION["industrial"]
        width = self.size[0]
        top, right, left = (self.px(v) for v in r["pad"])
        column = self.px(r["column"])
        head = tk.Frame(self, bg=c["deep"], bd=0, highlightthickness=0)
        self.parts.append(head)
        section = self.words(head, content["section"], "explain_section", c["muted"], column)
        section.pack(anchor="w")
        name = self.words(head, content["name"], "explain_option", c["text"], column)
        name.pack(anchor="w", pady=(self.px(r["name_gap"]), 0))
        head.place(x=left, y=top, width=column)
        need = top + section.winfo_reqheight() + self.px(r["name_gap"]) + name.winfo_reqheight()
        x = left + column + self.px(r["column_gap"])
        wide = max(1, min(self.px(r["text_w"]), width - x - right))
        if content["text"]:
            words = self.words(self, content["text"], "explain_text", c["text"], wide)
            self.parts.append(words)
            words.place(x=x, y=top + self.px(r["text_top"]))
            need = max(need, top + self.px(r["text_top"]) + words.winfo_reqheight())
        # as tall as its lines need, the strip's drawn height where they fit,
        # its drawing having no room under them, see grow_to
        was = self.size[1]
        self.grow_to(need, self.base, self.linespace(self.look.font("explain_text", False, self)))
        if self.size[1] != was and self.resized is not None:
            self.resized(self.size[1] - self.base)


class OptionMark(faces.Face):
    """The mark before a choice's name in the explanation: Slate's ring, as
    its cards have, with a dot in it for the chosen choice, and Folio's
    square, filled in ink for the chosen one and outlined for the others. It
    has no words and takes no click."""

    def __init__(self, master, look, chosen, ground):
        self.chosen = bool(chosen)
        faces.Face.__init__(self, master, look, ground)
        self.redraw_now()

    def state(self):
        return {"chosen": self.chosen}

    def layout(self, ctx):
        items, ground = [], self.ground()
        if ctx.kind == "folio":
            d = ctx.px(REGION["folio"]["mark"])
            if self.chosen:
                faces.rect(items, 0, 0, d, d, ctx.c("text"))
            else:
                faces.frame(items, 0, 0, d, d, ctx.c("edge"), ctx.border(1.5))
            return items, [], (d, d)
        t = faces.TILES["console"]
        d = ctx.px(REGION["console"]["mark"])
        ring = ctx.c("strong") if self.chosen else ctx.c("faint")
        faces.disc(items, 0, 0, d, ground, ground, ring, ctx.px(t["ring"]))
        if self.chosen:
            dot = ctx.px(t["dot"])
            faces.disc(items, (d - dot) // 2, (d - dot) // 2, dot, ring, ground)
        return items, [], (d, d)


class Footer(tk.Frame):
    """The footer along the foot of Settings, industrial's key strip. At its
    left the line that says how an explanation comes up, or the key caps of
    the keys that move through the rows with their words, then industrial's
    version, and Save and Cancel in the look's order with their keys' caps
    where the look draws them. The line, the version and the buttons are its
    own children, as in the classic footer, so a test finds them as there.
    Save is pressed by a click and has no cap, since Enter switches a switch.
    save and cancel are (words, command), keys ((key, ...), words) pairs,
    and the sizes are in pixels."""

    def __init__(self, master, look, width, height, save, cancel, help_line, version=None, keys=()):
        kind = widgets.kind_of(look)
        c, m = look.c, look.m
        s = look.scale_for(master)
        self.look, self.kind = look, kind
        self.ground = {"console": c["deep"], "folio": c["surface"]}.get(kind) or widgets.shade(look, "band")
        tk.Frame.__init__(self, master, bg=self.ground, width=width, height=height, bd=0, highlightthickness=0)
        self.grid_propagate(False)
        widgets.Rule(self, look).place(x=0, y=0, relwidth=1.0)
        left, right = (sc.px(v, s) for v in m["footer_pad"])
        gap = sc.px(m["button_gap"], s)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.help_line = self.key_row = self.version = self.esc_group = None
        self.groups = []
        self.hint_gap, self.version_pads = sc.px(m["hint_gap"], s), 0
        if keys:
            self.key_row = self._keys(keys, s)
            self.key_row.grid(row=0, column=0, sticky="w", padx=(left, 0))
        else:
            self.help_line = tk.Label(self, text=help_line, bg=self.ground, fg=c["text"],
                                      font=look.font("hints", False, self), bd=0, padx=0, pady=0)
            self.help_line.grid(row=0, column=0, sticky="w", padx=(left, 0))
        column, taken = 1, left + right
        if version is not None:
            self.version = tk.Label(self, text=version, bg=self.ground, fg=c["muted"],
                                    font=look.font("version", False, self), bd=0, padx=0, pady=0)
            self.version.grid(row=0, column=column, padx=(gap, sc.px(m["version_gap"], s)))
            column += 1
            self.version_pads = gap + sc.px(m["version_gap"], s)
            taken += self.version_pads
        made = {"save": dict(text=save[0], command=save[1], primary=True),
                "cancel": dict(text=cancel[0], command=cancel[1], key="Esc")}
        order = ("cancel", "save") if kind == "console" else ("save", "cancel")
        self.buttons = {}
        for i, name in enumerate(order):
            self.buttons[name] = widgets.CapButton(self, look, **made[name])
            self.buttons[name].grid(row=0, column=column + i, padx=(gap, right if i == len(order) - 1 else 0))
            taken += gap
        if self.key_row is not None:
            self._fit_keys(width - taken)

    def _keys(self, keys, s):
        """The key caps and their words in a row of their own. Esc is left out
        where Cancel carries its cap."""
        look, m = self.look, self.look.m
        row = tk.Frame(self, bg=self.ground, bd=0, highlightthickness=0)
        cap_gap, words_gap, hint_gap = (sc.px(m[k], s) for k in ("cap_gap", "words_gap", "hint_gap"))
        font, case = look.font("hints", False, self), look.fonts["hints"].case
        for caps, words in keys:
            if widgets.BUTTONS[self.kind]["cap"] and tuple(caps) == ("Esc",):
                continue
            group = tk.Frame(row, bg=self.ground, bd=0, highlightthickness=0)
            for j, key in enumerate(caps):
                cap = widgets.KeyCap(group, look, key, "cap", ground=self.ground)
                cap.pack(side="left", padx=(cap_gap if j else 0, 0))
            tk.Label(group, text=text.display_case(words, case), bg=self.ground, fg=look.c["muted"], font=font, bd=0,
                     padx=0, pady=0).pack(side="left", padx=(words_gap, 0))
            group.pack(side="left", padx=(hint_gap if self.groups else 0, 0))
            self.groups.append(group)
            if tuple(caps) == ("Esc",):
                self.esc_group = group
        return row

    def _fit_keys(self, room):
        """The key caps and their words fitted beside the version and the
        buttons, room pixels less the buttons' own widths, rather than cut a
        button, see fit.key_strip. Where they have no room as drawn, the gaps
        between the groups close up to half the drawn gap, then the version
        leaves the footer, being at the head of the lens menu too, then the
        groups leave, the last first, all but Esc Cancel, which stays at every
        width where it is here, Industrial's, since no button of the look
        carries Esc's cap."""
        self.update_idletasks()
        room -= sum(b.winfo_reqwidth() for b in self.buttons.values())
        version = 0
        if self.version is not None:
            room += self.version_pads
            version = self.version.winfo_reqwidth() + self.version_pads
        keep = self.groups.index(self.esc_group) if self.esc_group in self.groups else None
        floor = int(self.hint_gap * fit.KEY_GAP_FLOOR + 0.5)
        gap, shown, kept = fit.key_strip(room, [g.winfo_reqwidth() for g in self.groups], self.hint_gap, floor,
                                         version, keep)
        for i, group in enumerate(self.groups):
            if i not in kept:
                group.destroy()
        self.groups = [group for i, group in enumerate(self.groups) if i in kept]
        for i, group in enumerate(self.groups):
            group.pack_configure(padx=(gap if i else 0, 0))
        if self.version is not None and not shown:
            self.version.grid_remove()
        self.key_row.update_idletasks()


# ---- the rows of the pages

# The sizes of the rows of Settings' pages, CSS pixels at 100 percent, from
# the page drawings, Slate-Page-*, Paper-Page-* and Industrial-Page-*, and for
# the Fullscreen page Main, Paper-Settings and Industrial-Settings. A pad is
# (top, right, bottom, left) round a row's words and controls, the left one
# taking in the 3 pixel bar a lit row has. row is a row's least height, gap
# the room between its words and its control, head the room above and under
# a heading, line a sentence's pad, glyph the warning sign before a warning
# and its gap, cards Slate's cards' pad, tiles Industrial's, stack Folio's
# stacked strip's, field a field's height, hotkey a hotkey field's width,
# button a page button's height and the room beside its words, folder the pad
# of a folder under its own label, corner the corner's row, list_w the profile
# list's width, side the room between it and what is done with it, facts the
# box of what a profile holds, and swatch_at or swatch_after where a theme's
# first colour stands after its name on the Look page and swatch_right the
# room after its last, see faces.SWATCH.
ROWS = {
    "console": dict(row=44, pad=(0, 8, 0, 18), gap=16, beside_gap=12, head=(22, 6), head_gap=12,
                    line=(8, 8, 8, 18), glyph=16, glyph_gap=10, glyph_top=3, cards=(8, 8, 8, 18),
                    field=36, hotkey=150, field_gap=8, button=(32, 12), folder=(6, 8, 8, 18), folder_gap=6,
                    list_w=196, side=16, facts_above=14, facts=(14, 18, 16, 18), swatch_after=10,
                    swatch_right=14),
    "folio": dict(row=44, pad=(0, 24, 0, 32), label=250, label_gap=16, wrap_pad=10, gap=10, beside_gap=12,
                  head=(22, 0), head_first=16, head_h=30, head_gap=14, strip=52, stack=(12, 24, 12, 32),
                  line=(6, 24, 8, 32), glyph=14, glyph_gap=10, glyph_top=3, quality=64, quality_top=10,
                  name_gap=14, corner=64, field=30, hotkey=152,
                  field_gap=8, button=(30, 12), folder=(10, 24, 12, 32), folder_gap=6, folder_row=52,
                  list_w=226, side=24, profile=(14, 24, 14, 32), facts=(14, 24, 16, 32),
                  swatch_at=116, swatch_right=14),
    "industrial": dict(row=56, pad=(0, 16, 0, 16), gap=16, beside_gap=12, head_h=34, head_pad=(16, 5), info=24,
                       module_gap=20, column_gap=20, tiles=(22, 16, 22, 16), line=(10, 16, 10, 16),
                       warn=(14, 16, 14, 16), field=34, hotkey=150, field_gap=8, button=(34, 14),
                       folder_label=220, quality_gap=8, corner=80, list_w=400, list=(16, 16, 16, 16), side=16,
                       facts=(16, 16, 16, 16), swatch_at=96, swatch_after=16, swatch_right=16),
}

# The order of a theme's colours on the Look page, as the classic look shows them
SWATCHES = ("bg", "field", "hover", "cap", "fg", "dim", "accent", "warn", "close")


# Slate draws the choices of a variable as cards where one of them has more
# letters than this, a phrase such as the motion detail's, and as segments
# where each is a short label, such as the frame rate limit's
PHRASE = 20


def choice_layout(kind, count, themes, fits, longest=0):
    """How the choices of one variable are drawn, as (tiles or strip, the
    tiles' columns, whether the tiles are a list's lower ones). Slate draws two
    side by side as cards, and more as segments in a well where they are short
    labels that fit the row, else as cards one under another, see PHRASE.
    Folio draws its ink strip, or a stacked strip where the strip does not
    fit. Industrial draws two side by side as tiles and more as a list of
    lower tiles. The Look page's themes are cards, a stacked strip or listed
    tiles in every look. longest is the most letters a choice has."""
    two = count == 2 and not themes
    cards = kind == "console" and (two or not fits or longest > PHRASE)
    if themes or kind == "industrial" or cards or (kind == "folio" and not fits):
        return "tiles", (2 if two and kind != "folio" else 1), not two
    return "strip", 1, True


def page_button_colours(look):
    """A page's button's face, words, edge and colour pressed, Browse, Clear,
    Check now and the Profiles page's buttons. Slate's lie on the band with a
    raised edge, Folio's on the paper and Industrial's on the head, each with
    its edge."""
    face, ink, edge, pressed = widgets.button_colours(look, False)
    if widgets.kind_of(look) == "console":
        edge = look.c["raised"]
    return face, ink, edge, pressed


class PageButton(widgets.StateButton):
    """A button on a page of Settings in a drawn look, smaller than Save and
    Cancel, in the look's face, edge and colour pressed, its words in the
    look's case. The code's words, colours and font are kept and cget gives
    them back, see widgets.StateButton. A button that cannot be sized shows
    as Tk draws it, see widgets.fault."""

    def __init__(self, master=None, look=None, cnf=None, **kw):
        opts = dict(cnf or {})
        opts.update(kw)
        face, ink, edge, pressed = page_button_colours(look)
        opts.setdefault("disabledforeground", look.legacy["dim"])
        opts.update(relief="flat", overrelief="", bd=0, activebackground=pressed, activeforeground=ink,
                    highlightthickness=1, default="active", highlightcolor=edge, highlightbackground=edge)
        self._face_ink = (face, ink)
        widgets.StateButton.__init__(self, master, look, opts, font_role="page_button")
        tk.Misc.configure(self, self._drawn())
        self.fault = None
        self._fit_safely()

    def more(self, out):
        face, ink = self._face_ink
        if self.ground_colour is None:
            out["bg"] = face
        out["fg"] = ink

    def _fit_safely(self):
        if self.fault is not None:
            return
        try:
            kind, s = widgets.kind_of(self.look), self.look.scale_for(self)
            height, pad = ROWS[kind]["button"]
            words = int(self.tk.call("font", "measure", widgets.real(self, "font"), widgets.real(self, "text")))
            edge = self.winfo_pixels(self.cget("highlightthickness"))
            widgets.exact(self, 2 * edge + words + 2 * sc.px(pad, s), sc.px(height, s))
        except Exception as exc:
            self.fault = str(exc) or type(exc).__name__
            try:
                tk.Misc.configure(self, image="", compound="none", width=0, height=0)
            except tk.TclError:
                pass
            widgets.fault(self, exc, aside=True)

    def configure(self, cnf=None, **kw):
        got = widgets.StateButton.configure(self, cnf, **kw)
        opts = cnf if isinstance(cnf, dict) else {}
        if "text" in kw or "text" in opts:
            self._fit_safely()
        return got

    config = configure


class WarnMark(tk.Canvas):
    """The warning sign before a warning on a page, as Slate's and Folio's
    drawings set it, the icon font's triangle in the warning colour, see
    widgets.GLYPHS. It has no words."""

    def __init__(self, master, look, size, ground):
        d = sc.px(size, look.scale_for(master))
        tk.Canvas.__init__(self, master, width=d, height=d, bg=ground, bd=0, highlightthickness=0, takefocus=0)
        font, char = widgets.glyph(self, "warn", d)
        self.create_text(d // 2, d // 2, text=char, font=font, fill=look.c["warn"], anchor="center")


class InfoMark(tk.Canvas):
    """Industrial's i at the right of a module's head, a framed square with
    the drawing's i in the muted colour, a dot over a stem. It has no words,
    and the pointer on it brings up the section's explanation as anywhere on
    the head."""

    def __init__(self, master, look):
        s = look.scale_for(master)
        c = look.c
        d, b = sc.px(ROWS["industrial"]["info"], s), sc.border(1, s)
        tk.Canvas.__init__(self, master, width=d, height=d, bg=c["surface"], bd=0, highlightthickness=0, takefocus=0)
        self.create_rectangle(0, 0, d, d, fill=c["edge"], outline="", width=0)
        self.create_rectangle(b, b, d - b, d - b, fill=c["surface"], outline="", width=0)
        stroke = sc.px(1.6, s)
        x0 = (d - stroke) // 2
        top = (d - sc.px(12, s)) // 2
        for y0, y1 in ((0.6, 2.6), (4.6, 11.4)):
            self.create_rectangle(x0, top + sc.px(y0, s), x0 + stroke, top + sc.px(y1, s), fill=c["muted"], outline="",
                                  width=0)


class _Group(object):
    """The choices of one variable on a page, made one by one by the lens's
    radio(), and drawn together once the last is made, see Rows.close. A
    strip and tiles are both made first, so the choices made after them lie
    above whichever is kept."""

    def __init__(self, var, band, strip, tiles):
        self.var, self.band, self.strip, self.tiles = var, band, strip, tiles
        self.buttons = []
        self.themes = False


class _Page(object):
    """What Rows keeps of one page as its rows are made."""

    def __init__(self, page):
        self.page = page
        self.sections = 0       # the headings made, folio's first lies closer under the title
        self.last = None        # the last row of a section, folio's rule goes under it
        self.module = None      # industrial's module the rows go into, and its head
        self.plate = None
        self.count = 0          # the rows in that module, the first has no rule above it
        self.modules = []       # industrial's modules, each [frame, wide]
        self.columns = None     # industrial's two columns of modules
        self.group = None       # the open choices, see _Group
        self.inner = None       # industrial's two columns of hotkey rows in their module
        self.hotkeys = []       # the hotkey rows there, each (band, label, frame)


class Rows(object):
    """The rows of Settings' pages in a drawn look. The lens's helpers ask
    for each row here in place of making today's, see Lens.settings_dialog,
    and get the same widgets back: a check button for a switch, a radio
    button for a choice, a label for a heading or a sentence, a field and a
    button for a folder. Each keeps the words, variable, command, logical
    colours and font the code gives it, and its .beside, so the code, its log
    lines and the tests read what they read in the classic look, and the face
    of the look is drawn over it or beside it, see lens_look.faces. Rows the
    lens makes itself, the readout's switches, its corner, the hotkeys and the
    profiles, are made as today and laid out again here, in the look's sizes,
    and the Look page's themes are drawn as the look's cards or tiles with
    their colours.

    A row lies on the page's grid row the code counts, p.row, in a band of its
    own, see widgets.RowBand, so a test that groups a page's controls by grid
    row finds them as in the classic look. Industrial's modules and its two
    columns are frames of the page at grid rows from 1000 up, and a row lies
    in them by in_=, see the plan's 1.8. The choices of one variable are drawn
    as one strip, cards or tiles once the last of them is made, and the sizes
    that depend on the screen, the compact rows and Industrial's columns, are
    given once the window is fitted, see close and fitted. Every size is in
    pixels at the look's scale."""

    def __init__(self, frame):
        self.frame, self.look, self.kind = frame, frame.look, frame.kind
        self.dialog = frame.dialog
        self.s = self.look.scale_for(self.dialog)
        self.m = ROWS[self.kind]
        self.legacy = self.look.legacy
        self.pages = {}
        self.sized = []                 # what the compact layout changes, see fitted
        self.compact = False
        self.stops = []                 # the rows the keys and the pointer pick, in the order made, see Stop
        self._by_widget = None          # each stop by the path of a widget of it, see stop_of
        # what a chosen profile's facts lie on and their width, see profiles
        self.facts_ground, self.facts_width = self.look.c["surface"], 0
        # the room a page has in the drawn layout, which the compact one keeps,
        # less what the notebook keeps round a page
        drawn = fit.settings_fit(self.look, self.s, 10 ** 6, 10 ** 6, sc.px(CAPTION, self.s))
        self.room = fit.settings_parts(self.look, self.s, drawn)["room"] - 2 * NOTEBOOK_INSET

    # sizes

    def px(self, n):
        return sc.px(n, self.s)

    def pad(self, name):
        """A pad of ROWS in pixels, as (top, right, bottom, left)."""
        return tuple(self.px(v) for v in self.m[name])

    def width(self, st):
        """The width a row has where it lies, the page's room, or in
        Industrial the inside of a module in one of the two columns, or across
        both where the module is wide."""
        if self.kind != "industrial" or st.module is None:
            return self.room
        gap = self.px(self.m["column_gap"])
        whole = self.room if st.modules[-1][1] else (self.room - gap) // 2
        return whole - 2 * sc.border(1, self.s)

    def _size(self, widget, how, full, more=0):
        """A height or a room the compact layout makes smaller, given now at
        its full size. how is rows, the least height of the grid row of widget
        whose number is more, or above, the room above a heading, with more
        the room under it."""
        self.sized.append((widget, how, full, more))
        self._apply(widget, how, full, more, False)

    def _apply(self, widget, how, full, more, compact):
        n = self._smaller(how, full) if compact else full
        if how == "rows":
            widget.rowconfigure(more, minsize=self.px(n))
        else:
            widget.grid_configure(pady=(self.px(n), more))

    def _smaller(self, how, full):
        """A size in the compact layout, the kind's own where tokens.COMPACT
        names one, else the size times tokens.COMPACT_RATIO."""
        small = tokens.COMPACT.get(self.kind, {})
        if how == "rows" and full == self.m["row"] and "row_h" in small:
            return small["row_h"]
        if how == "above" and "section_gap" in small and full in (self.m.get("head", (None,))[0],
                                                                  self.m.get("module_gap")):
            return small["section_gap"]
        return full * tokens.COMPACT_RATIO

    # the rows the keys and the pointer pick

    def _stop(self, p, kind, band, control=None, options=None, anchor=None, labels=(), *more):
        """A row of page p the keys and the pointer pick, see Stop."""
        stop = Stop(p, kind, band, control, options, anchor, labels, (band,) + more)
        self.stops.append(stop)
        self._by_widget = None
        return stop

    def stop_of(self, widget):
        """The stop a widget is part of, it or the nearest of its masters
        that a stop names, or None for a heading, a sentence or a widget of no
        row."""
        if self._by_widget is None:
            self._by_widget = {}
            for stop in self.stops:
                for w in stop.widgets:
                    self._by_widget.setdefault(str(w), stop)
        while widget is not None:
            stop = self._by_widget.get(str(widget))
            if stop is not None:
                return stop
            widget = getattr(widget, "master", None)
        return None

    # the page and where its rows lie

    def _state(self, p):
        st = self.pages.get(str(p))
        if st is None:
            st = self.pages[str(p)] = _Page(p)
            if self.kind == "industrial":
                ground = self.look.c["surface"]
                st.columns = (tk.Frame(p, bg=ground, bd=0, highlightthickness=0),
                              tk.Frame(p, bg=ground, bd=0, highlightthickness=0))
        return st

    def _open(self, p, var=None):
        """The page's state, with its open choices drawn unless the row to
        come is another choice of the same variable."""
        st = self._state(p)
        if st.group is not None and (var is None or st.group.var != var):
            self._draw_group(st)
        return st

    def _put(self, st, widget, sticky="we", padx=0, pady=0, row=None):
        """Grid a row on the page's row p.row, which it then counts, or on the
        row given, in Industrial in the module it belongs to."""
        p = st.page
        r = p.row if row is None else row
        if self.kind == "industrial" and st.module is not None:
            widget.grid(in_=st.module, row=r, column=0, columnspan=1, sticky=sticky, padx=padx, pady=pady)
        else:
            widget.grid(in_=p, row=r, column=0, columnspan=3, sticky=sticky, padx=padx, pady=pady)
        if row is None:
            p.row += 1

    def _regrid(self, st, widget):
        """A row the lens gridded itself, across the page as a band is, in
        Industrial in its module, on the row it has."""
        if self.kind == "industrial" and st.module is not None:
            widget.grid_configure(in_=st.module, column=0, columnspan=1, sticky="we", padx=0, pady=0)
        else:
            widget.grid_configure(sticky="we", padx=0, pady=0)

    def _rule(self, band, colour, top=True):
        line = tk.Frame(band, bg=colour, height=1, bd=0, highlightthickness=0)
        if top:
            line.place(x=0, y=0, relwidth=1.0)
        else:
            line.place(x=0, rely=1.0, y=-1, relwidth=1.0)
        return line

    def _rule_over(self, widget, colour):
        """A rule along the top of widget, made as a child of the widget's
        parent and placed in it, so that it stays when the lens clears the
        widget's children, as show_facts does each time it lists a profile."""
        line = tk.Frame(widget.master, bg=colour, height=1, bd=0, highlightthickness=0)
        line.place(in_=widget, x=0, y=0, relwidth=1.0)
        return line

    def _rules(self, st, band):
        """The rules a row has, Folio's above each row, with one under the
        last of a section, see _end_section, and Industrial's above each row
        of a module but its first."""
        if self.kind == "folio":
            self._rule(band, widgets.shade(self.look, "rule_faint"))
            st.last = band
        elif self.kind == "industrial" and st.module is not None:
            if st.count:
                self._rule(band, self.look.c["rule"])
            st.count += 1

    def _end_section(self, st):
        if self.kind == "folio" and st.last is not None:
            self._rule(st.last, widgets.shade(self.look, "rule_faint"), top=False)
        st.last = None

    def _band(self, st, least=None):
        """A row's band on the page's row, ruled, its least height kept for the
        compact layout."""
        band = widgets.RowBand(st.page, self.look)
        self._put(st, band)
        self._rules(st, band)
        self._size(band, "rows", self.m["row"] if least is None else least)
        return band

    def _words(self, master, words, small, bg=None, wrap=0):
        """A few words beside a setting, as the classic look's words(), in the
        look's type and the muted colour."""
        lg = self.legacy
        return widgets.StateLabel(master, self.look, text=words, bg=bg or lg["bg"], fg=lg["dim"], font=small, bd=0,
                                  padx=0, pady=0, justify="left", anchor="w", wraplength=max(0, wrap),
                                  font_role="beside")

    def _shown_with_words(self, label, **pack):
        """A label packed while it has words, and out of the way while it has
        none, as a switch's .beside comes and goes."""
        def show():
            have = bool(str(label.cget("text")))
            if have and not label.winfo_manager():
                label.pack(side="top", anchor="w", **pack)
            elif not have and label.winfo_manager():
                label.pack_forget()
        label.follow(lambda widget, keys, lit: show() if "text" in keys else None)
        show()

    # the rows the lens's helpers make

    def heading(self, p, words, beside, font, small):
        """A heading, Slate's capitals with a hairline and the beside words at
        the right, Folio's serif heading with the words and a hairline after
        it, or Industrial's module with its head, see _module. Returns the
        row, which the lens gives the section's explanation."""
        st = self._open(p)
        self._end_section(st)
        if self.kind == "industrial":
            return self._module(st, words, beside, font, small)
        c, lg, m = self.look.c, self.legacy, self.m
        first = st.sections == 0
        st.sections += 1
        row = tk.Frame(p, bg=c["surface"], bd=0, highlightthickness=0)
        roles = {"fg": {"fg": "muted"}} if self.kind == "console" else None
        label = widgets.StateLabel(row, self.look, text=words, bg=lg["bg"], fg=lg["fg"], font=font, bd=0, padx=0,
                                   pady=0, roles=roles, font_role="heading")
        gap = self.px(m["head_gap"])
        if self.kind == "console":
            above, below = m["head"]
            self._put(st, row, pady=(self.px(above), self.px(below)))
            self._size(row, "above", above, self.px(below))
            label.grid(row=0, column=0, sticky="w")
            widgets.Rule(row, self.look).grid(row=0, column=1, sticky="we", padx=(gap, 0))
            row.columnconfigure(1, weight=1)
            if beside:
                self._words(row, beside, small).grid(row=0, column=2, sticky="e", padx=(gap, 0))
            return row
        above = m["head_first"] if first else m["head"][0]
        _top, right, _bottom, left = self.pad("pad")
        self._put(st, row, pady=(self.px(above), 0))
        self._size(row, "above", above, 0)
        row.rowconfigure(0, minsize=self.px(m["head_h"]))
        label.grid(row=0, column=0, sticky="w", padx=(left, 0))
        col = 1
        if beside:
            self._words(row, beside, small).grid(row=0, column=1, sticky="w", padx=(gap, 0))
            col = 2
        widgets.Rule(row, self.look).grid(row=0, column=col, sticky="we", padx=(gap, right))
        row.columnconfigure(col, weight=1)
        return row

    def _module(self, st, words, beside, font, small):
        """Industrial's module, framed in its edge colour, with its head, the
        heading in capitals on the head plate, the beside words and the i at
        its right. Its rows lie in it, and the modules of a page lie in two
        columns once the page is made, see _arrange. Returns the head."""
        p, c, lg, m = st.page, self.look.c, self.legacy, self.m
        b = sc.border(1, self.s)
        module = tk.Frame(p, bg=c["surface"], bd=0, highlightthickness=b, highlightbackground=c["edge"],
                          highlightcolor=c["edge"])
        module.columnconfigure(0, weight=1)
        st.modules.append([module, False])
        st.module, st.count, st.inner, st.hotkeys = module, 0, None, []
        plate = st.plate = tk.Frame(p, bg=c["head"], bd=0, highlightthickness=0)
        self._put(st, plate)
        plate.rowconfigure(0, minsize=self.px(m["head_h"]))
        plate.columnconfigure(1, weight=1)
        left, right = (self.px(v) for v in m["head_pad"])
        widgets.StateLabel(plate, self.look, text=words, bg=lg["cap"], fg=lg["fg"], font=font, bd=0, padx=0, pady=0,
                           font_role="heading").grid(row=0, column=0, sticky="w", padx=(left, 0))
        col = 2
        if beside:
            self._words(plate, beside, small, bg=lg["cap"]).grid(row=0, column=2, sticky="e",
                                                                  padx=(self.px(m["beside_gap"]), 0))
            col = 3
        InfoMark(plate, self.look).grid(row=0, column=col, sticky="e", padx=(self.px(m["beside_gap"]), right))
        self._rule(plate, c["edge"], top=False)
        return plate

    def line(self, p, words, colour, small):
        """A sentence on a row of its own, one label with the whole text, in
        the colour the code gives it, a warning with Slate's and Folio's sign
        before it. Returns the label, then the sign where there is one."""
        st = self._open(p)
        c, lg, m = self.look.c, self.legacy, self.m
        warn = tokens.same(str(colour), lg["warn"])
        top, right, bottom, left = self.pad("warn" if warn and self.kind == "industrial" else "line")
        made = []
        if warn and self.kind != "industrial":
            sign = WarnMark(p, self.look, m["glyph"], c["surface"])
            self._put(st, sign, sticky="nw", padx=(left, 0), pady=(top + self.px(m["glyph_top"]), 0), row=p.row)
            left += sign.winfo_reqwidth() + self.px(m["glyph_gap"])
            made.append(sign)
        label = widgets.StateLabel(p, self.look, text=words, bg=lg["bg"], fg=colour, font=small, justify="left",
                                   anchor="w", bd=0, padx=0, pady=0,
                                   wraplength=max(1, self.width(st) - left - right), font_role="line")
        self._put(st, label, sticky="w", padx=(left, right), pady=(top, bottom))
        if self.kind == "industrial" and st.module is not None:
            st.count += 1
        return (label,) + tuple(made)

    def option(self, kind, p, words, beside, font, small, **kw):
        """A switch or a choice, as the classic look's option() makes them.
        Returns the check or radio button, then the widgets the lens gives the
        setting's explanation."""
        if kind is tk.Radiobutton:
            return self._choice(p, words, beside, font, small, **kw)
        return self._switch(p, words, beside, font, small, **kw)

    def _switch_width(self, widget):
        ctx = faces._ctx_of(widget, self.look)
        return faces.switch_items(ctx, False, False, False, "settings")[2][0]

    def _switch(self, p, words, beside, font, small, **kw):
        """A switch's row, its label the check button, see
        faces.LookCheckbutton, the words beside it under the label while it
        has any, and the switch at the row's right, or after Folio's label
        column, see faces.SwitchFace."""
        st = self._open(p)
        c, lg, m = self.look.c, self.legacy, self.m
        band = self._band(st)
        _top, right, _bottom, left = self.pad("pad")
        # the label's words break where its row has no more room, less the
        # few pixels a check button keeps round its words
        if self.kind == "folio":
            wrap = self.px(m["label"]) - self.px(m["label_gap"]) - 4
        else:
            wrap = self.width(st) - left - right - self.px(m["gap"]) - self._switch_width(band) - 4
        words_col = tk.Frame(band, bg=c["surface"], bd=0, highlightthickness=0)
        b = faces.LookCheckbutton(words_col, self.look, text=words, bg=lg["bg"], fg=lg["fg"], selectcolor=lg["field"],
                                  activebackground=lg["bg"], activeforeground=lg["fg"], disabledforeground=lg["dim"],
                                  font=font, justify="left", wraplength=max(1, wrap), **kw)
        b.pack(side="top", anchor="w")
        b.beside = self._words(words_col, beside or "", small, wrap=wrap)
        self._shown_with_words(b.beside)
        face = faces.SwitchFace(band, self.look, b, "settings")
        self._lay(band, words_col, face, left, right)
        band.add(words_col, b, b.beside, face)
        band.follow(b)
        self._stop(p, "switch", band, b, None, None, (b,), words_col, b, b.beside, face)
        return b, band, words_col, b

    def _lay(self, band, words_col, control, left, right):
        """A row's words at its left and its control at its right, or in Folio
        after the label column, the words taking two lines there where they
        have to."""
        m = self.m
        if self.kind == "folio":
            band.columnconfigure(0, minsize=left + self.px(m["label"]))
            words_col.grid(row=0, column=0, sticky="w", padx=(left, self.px(m["label_gap"])),
                           pady=self.px(m["wrap_pad"]))
            control.grid(row=0, column=1, sticky="w")
            band.columnconfigure(2, weight=1)
        else:
            words_col.grid(row=0, column=0, sticky="w", padx=(left, 0))
            control.grid(row=0, column=2, sticky="e", padx=(self.px(m["gap"]), right))
            band.columnconfigure(1, weight=1)

    def _choice(self, p, words, beside, font, small, **kw):
        """A choice of a variable. Its band is made with the first choice,
        and the choices are drawn together once the last is made, see
        _draw_group."""
        var = str(kw.get("variable"))
        st = self._open(p, var)
        g = st.group
        if g is None:
            band = self._band(st, self.m.get("strip"))
            g = st.group = _Group(var, band, faces.ChoiceStrip(band, self.look, "settings"),
                                  faces.Tiles(band, self.look))
            self._stop(p, "choice", band, None, g.buttons)
        lg = self.legacy
        b = tk.Radiobutton(g.band, text=words, bg=lg["bg"], fg=lg["fg"], selectcolor=lg["field"],
                           activebackground=lg["bg"], activeforeground=lg["fg"], disabledforeground=lg["dim"], font=font,
                           **kw)
        b.beside = self._words(g.band, beside or "", small)
        g.buttons.append(b)
        return b, b

    def theme(self, p, name, var, colours, font):
        """A theme of the Look page, the choice of its name as the classic
        look makes it, drawn with the theme's colours on the look's card,
        stacked strip or tile once the last theme is made, see _draw_group.
        Returns the radio button, which the lens gives the explanation."""
        st = self._open(p, str(var))
        g = st.group
        if g is None:
            band = self._band(st, self.m.get("strip"))
            g = st.group = _Group(str(var), band, faces.ChoiceStrip(band, self.look, "settings"),
                                  faces.Tiles(band, self.look))
            self._stop(p, "choice", band, None, g.buttons)
        g.themes = True
        lg = self.legacy
        b = tk.Radiobutton(g.band, text=name, variable=var, value=name, bg=lg["bg"], fg=lg["fg"],
                           selectcolor=lg["field"], activebackground=lg["bg"], activeforeground=lg["fg"], font=font,
                           width=12, anchor="w")
        # the colours the theme has in the drawn looks, those choosing it
        # gives, as lens_look.choose takes them, see tokens.legacy
        ten = tokens.legacy(tokens.theme_kind(name, colours), name, colours)
        b.swatches = [(ten[k], ten["dim"]) for k in SWATCHES]
        g.buttons.append(b)
        return b

    def _draw_group(self, st):
        """The choices of one variable drawn together, as choice_layout says,
        the Look page's themes each with its colours, and the words beside a
        choice under them."""
        g, st.group = st.group, None
        if g is None or not g.buttons:
            return
        k = self.kind
        n = len(g.buttons)
        _top, right, _bottom, left = self.pad("pad")
        ctx = faces._ctx_of(g.band, self.look)
        sizes = faces.strip_sizes(widgets.kind_of(self.look), "settings")
        need = (sum(faces.segment_width(ctx, text.display_case(str(b.cget("text")), g.strip.case), sizes)
                    for b in g.buttons) + (n - 1) * g.strip.gap + 2 * g.strip.pad)
        use, columns, listed = choice_layout(k, n, g.themes, need <= self.width(st) - left - right,
                                             max(len(str(b.cget("text"))) for b in g.buttons))
        if use == "tiles":
            tiles, other = g.tiles, g.strip
            tiles.columns, tiles.listed = columns, listed
            if g.themes:
                tiles.swatch_x = self._swatch_x(ctx, g.buttons)
            for b in g.buttons:
                tiles.add(b)
                if g.themes:
                    self._widen(ctx, b, tiles.swatch_x)
            key = {"console": "cards", "industrial": "tiles"}.get(k, "stack")
            top, right_, bottom, left_ = self.pad(key)
            tiles.grid(row=0, column=0, sticky="we", padx=(left_, right_), pady=(top, bottom))
            g.band.columnconfigure(0, weight=1)
            kept = tiles
        else:
            strip, other = g.strip, g.tiles
            for b in g.buttons:
                strip.add(b)
            strip.grid(row=0, column=0, sticky="w", padx=(left, right))
            kept = strip
        other.destroy()
        r = 1
        for b in g.buttons:
            words = getattr(b, "beside", None)
            if words is not None and str(words.cget("text")):
                words.grid(row=r, column=0, sticky="w", padx=(left, right), pady=(0, self.px(6)))
                r += 1
        g.band.add(kept, *[b.beside for b in g.buttons if getattr(b, "beside", None) is not None])

    def _swatch_x(self, ctx, buttons):
        """Where a theme's colours start on its card or tile, after the
        longest name in Slate, after the drawn name's column in the others."""
        m, t = self.m, faces.TILES[ctx.kind]
        if ctx.kind == "console":
            font = ctx.font("tile", True, t["size"])
            name = max(ctx.measure(font, str(b.cget("text"))) for b in buttons)
            return ctx.px(t["pad"]) + ctx.px(t["mark"]) + ctx.px(t["mark_gap"]) + name + ctx.px(m["swatch_after"])
        if ctx.kind == "folio":
            return ctx.px(t["pad"]) + ctx.px(m["swatch_at"])
        return (ctx.px(t["pad"]) + ctx.px(t["lamp"]) + ctx.px(t["lamp_gap"]) + ctx.px(m["swatch_at"])
                + ctx.px(m["swatch_after"]))

    def _widen(self, ctx, button, at):
        """A theme's card or tile wide enough for its colours."""
        sw = faces.SWATCH[ctx.kind]
        w, gap = ctx.px(sw["w"]), ctx.px(sw["gap"])
        count = len(button.swatches)
        width = at + count * w + (count - 1) * gap + ctx.px(self.m["swatch_right"])
        widgets.exact(button, max(width, button.winfo_reqwidth()), button.winfo_reqheight())

    def press(self, holder, words, command, font, bg, fg):
        """A button of a page, see PageButton."""
        return PageButton(holder, self.look, text=words, command=command, font=font, bg=bg, fg=fg)

    def _field(self, entry, role, lit=False):
        """A field in the look's well and type, as widgets.field_options
        gives them."""
        opts = widgets.field_options(self.look)
        opts["font"] = self.look.font(role, lit, entry)
        entry.configure(**opts)
        return entry

    def _ipady(self, entry, height):
        return max(0, (self.px(height) - entry.winfo_reqheight()) // 2)

    def folder(self, p, label, var, browse, font, ctl):
        """A folder as a field with a Browse button, under its label where it
        has one of its own, beside it in Industrial. Returns every widget of
        the row, which the lens gives the explanation."""
        st = self._open(p)
        lg, m, k = self.legacy, self.m, self.kind
        band = self._band(st, (m.get("folder_row") if not label else None))
        made = []
        if label:
            made.append(widgets.StateLabel(band, self.look, text=label, bg=lg["bg"], fg=lg["fg"], font=font, bd=0,
                                           padx=0, pady=0, font_role="row"))
        field = self._field(tk.Entry(band, textvariable=var, width=1), "value" if k == "industrial" else "line")
        go = self.press(band, "Browse", browse, ctl, lg["hover"], lg["fg"])
        gap = self.px(m["field_gap"])
        ipady = self._ipady(field, m["field"])
        if label and k != "industrial":
            top, right, bottom, left = self.pad("folder")
            made[0].grid(row=0, column=0, columnspan=2, sticky="w", padx=(left, right), pady=(top, 0))
            field.grid(row=1, column=0, sticky="we", padx=(left, 0), pady=(self.px(m["folder_gap"]), bottom),
                       ipady=ipady)
            go.grid(row=1, column=1, sticky="w", padx=(gap, right), pady=(self.px(m["folder_gap"]), bottom))
        else:
            _top, right, _bottom, left = self.pad("pad")
            col = 0
            if label:
                band.columnconfigure(0, minsize=left + self.px(m["folder_label"]))
                made[0].grid(row=0, column=0, sticky="w", padx=(left, self.px(m["gap"])))
                col, left = 1, 0
            field.grid(row=0, column=col, sticky="we", padx=(left, 0), ipady=ipady)
            go.grid(row=0, column=col + 1, sticky="w", padx=(gap, right))
        band.columnconfigure(1 if label and k == "industrial" else 0, weight=1)
        band.add(*made)                 # the label alone, the field and the button keep their own faces
        self._stop(p, "field", band, field, None, None, tuple(made), field, go, *made)
        made += [field, go, band]
        return made

    def button(self, p, words, command, ctl):
        """A button on a row of its own. Returns it and its row."""
        st = self._open(p)
        lg = self.legacy
        band = self._band(st, self.m.get("folder_row"))
        b = self.press(band, words, command, ctl, lg["hover"], lg["fg"])
        _top, right, _bottom, left = self.pad("pad")
        b.grid(row=0, column=0, sticky="w", padx=(left, right))
        self._stop(p, "button", band, b, None, None, (), b)
        return b, band

    # the rows the lens makes itself, laid out again in the look

    def quality(self, p, control, font):
        """The Power page's quality step, its slider and its name made by the
        lens's quality_control in the look, see quality_name and
        quality_scale, on a row of their own. Slate's carousel names the step
        itself, so its label is kept out of sight. Returns the row, the slider
        and the label."""
        st = self._open(p)
        m = self.m
        band = self._band(st, m.get("quality"))
        scale, name = control(band, font=font, drawn=self)
        _top, right, _bottom, left = self.pad("pad")
        if self.kind == "console":
            scale.grid(row=0, column=0, sticky="w", padx=(left, right))
        elif self.kind == "folio":
            q = self.px(m["quality_top"])
            scale.grid(row=0, column=0, sticky="nw", padx=(left, 0), pady=(q, 0))
            name.grid(row=0, column=1, sticky="nw", padx=(self.px(m["name_gap"]), right), pady=(q, 0))
        else:
            scale.grid(row=0, column=0, sticky="w", padx=(left, 0))
            name.grid(row=0, column=1, sticky="w", padx=(self.px(m["quality_gap"]), right))
        band.add(scale.face, name)
        self._stop(p, "quality", band, scale, None, None, (), scale, scale.face, name)
        return band, scale, name

    def quality_name(self, parent, words, font):
        """The label that names the quality step, the code's, in the look's
        type, Industrial's in its capitals."""
        lg = self.legacy
        industrial = self.kind == "industrial"
        return widgets.StateLabel(parent, self.look, text=words, bg=lg["bg"], fg=lg["fg"], font=font, width=12,
                                  anchor="w", bd=0, padx=0, pady=0, case="upper" if industrial else None,
                                  font_role="value" if industrial else "line")

    def quality_scale(self, parent, names, command):
        """The quality step's slider, a LookScale with its QualityFace, see
        faces.quality, with the classic slider's range, steps and command."""
        return faces.quality(parent, self.look, names, "settings", from_=0, to=len(names) - 1, resolution=1,
                             command=command)

    def _dress_switch(self, b, wrap=0):
        """A check button the lens made as in the classic look, drawn as a
        switch's label, see faces.LookCheckbutton."""
        c = self.look.c
        b.configure(indicatoron=0, relief="flat", offrelief="flat", overrelief="", bd=0, highlightthickness=0,
                    anchor="w", justify="left", bg=c["surface"], activebackground=c["surface"], selectcolor=c["surface"],
                    fg=c["text"], activeforeground=c["text"], disabledforeground=c["muted"],
                    font=self.look.font("row", False, b), wraplength=max(0, wrap))
        faces.LabelCover(b, self.look)

    def readout(self, p, row, hints):
        """The readout's five switches, which the lens makes side by side, a
        row each as every drawing has them, each with its switch. The lens's
        explanations of each are given to its row and its switch too."""
        st = self._open(p)
        _top, right, _bottom, left = self.pad("pad")
        self._regrid(st, row)
        row.columnconfigure(0, weight=1)
        buttons = [w for w in row.winfo_children() if w.winfo_class() == "Checkbutton"]
        for b in buttons:
            b.pack_forget()             # every one, before the row lays out by grid
        for i, b in enumerate(buttons):
            band = widgets.RowBand(row, self.look)
            tk.Misc.lower(band, b)
            band.grid(row=i, column=0, sticky="we")
            self._rules(st, band)
            self._size(band, "rows", self.m["row"])
            self._dress_switch(b)
            face = faces.SwitchFace(row, self.look, b, "settings")
            if self.kind == "folio":
                band.columnconfigure(0, minsize=left + self.px(self.m["label"]))
                b.grid(in_=band, row=0, column=0, sticky="w", padx=(left, self.px(self.m["label_gap"])))
                face.grid(in_=band, row=0, column=1, sticky="w")
                band.columnconfigure(2, weight=1)
            else:
                b.grid(in_=band, row=0, column=0, sticky="w", padx=(left, 0))
                face.grid(in_=band, row=0, column=2, sticky="e", padx=(self.px(self.m["gap"]), right))
                band.columnconfigure(1, weight=1)
            band.add(b, face)
            self._stop(p, "switch", band, b, None, None, (b,), b, face)
            why = hints.texts.get(b)
            if why:
                hints.add(band, why)
                hints.add(face, why)

    def corner(self, p, row, made):
        """The readout's corner, which the lens makes as a label and four
        radio buttons, as the corner's face, see faces.CornerFace, the radio
        buttons kept and out of sight. Returns the row's band and the face,
        which the lens gives the explanation too."""
        st = self._open(p)
        _top, right, _bottom, left = self.pad("pad")
        label, buttons = made[0], list(made[1:])
        self._regrid(st, row)
        row.columnconfigure(0, weight=1)
        for w in made:
            w.pack_forget()
        band = widgets.RowBand(row, self.look)
        tk.Misc.lower(band, label)
        band.grid(row=0, column=0, sticky="we")
        self._rules(st, band)
        self._size(band, "rows", self.m.get("corner", self.m["row"]))
        c = self.look.c
        label.configure(bg=c["surface"], fg=c["text"], font=self.look.font("row", False, label), bd=0, padx=0, pady=0)
        face = faces.CornerFace(row, self.look, buttons)
        if self.kind == "folio":
            band.columnconfigure(0, minsize=left + self.px(self.m["label"]))
            label.grid(in_=band, row=0, column=0, sticky="w", padx=(left, self.px(self.m["label_gap"])))
            face.grid(in_=band, row=0, column=1, sticky="w")
            band.columnconfigure(2, weight=1)
        else:
            label.grid(in_=band, row=0, column=0, sticky="w", padx=(left, 0))
            face.grid(in_=band, row=0, column=2, sticky="e", padx=(self.px(self.m["gap"]), right))
            band.columnconfigure(1, weight=1)
        band.add(label, face)
        self._stop(p, "corner", band, None, buttons, None, (label,), label, face)
        return [band, face]

    def _inner(self, st, before):
        """Industrial's two columns of hotkey rows in their module, made with
        the first row and lying under it."""
        if st.inner is None:
            p, ground = st.page, self.look.c["surface"]
            st.inner = (tk.Frame(p, bg=ground, bd=0, highlightthickness=0),
                        tk.Frame(p, bg=ground, bd=0, highlightthickness=0))
            for i, col in enumerate(st.inner):
                tk.Misc.lower(col, before)
                col.grid(in_=st.module, row=1000, column=i, sticky="new")
                col.columnconfigure(0, weight=1)
                st.module.columnconfigure(i, weight=1, uniform="lens_look_hotkeys")
            if st.plate is not None:
                st.plate.grid_configure(columnspan=2)
            st.modules[-1][1] = True
        return st.inner

    def hotkey(self, p, name, ent, fr, note, hints):
        """A hotkey's row, which the lens makes as a label, a field and a frame
        with Clear and the note, laid out in the look with the same widgets on
        the same grid row, the note under the field while it has words. The
        row's band has the row's explanation too."""
        st = self._open(p)
        c, m = self.look.c, self.m
        r = int(name.grid_info()["row"])
        _top, right, _bottom, left = self.pad("pad")
        master = self._inner(st, name)[0] if self.kind == "industrial" else p
        band = widgets.RowBand(p, self.look)
        tk.Misc.lower(band, name)
        band.grid(in_=master, row=r, column=0, columnspan=3, sticky="nsew")
        if self.kind == "folio":
            self._rules(st, band)
        # the band lies behind the row and holds nothing, so the grid row it
        # shares with the label and the field keeps the row's height, in
        # Industrial in the column the row ends in, see _hotkey_columns
        if self.kind != "industrial":
            self._size(master, "rows", m["row"], r)
        field_w, gap = self.px(m["hotkey"]), self.px(m["field_gap"])
        clear = next((w for w in fr.winfo_children() if w.winfo_class() == "Button"), None)
        clear_w = clear.winfo_reqwidth() if clear is not None else 0
        width = self.width(st) // (2 if self.kind == "industrial" else 1)
        wrap = (self.px(m["label"]) - self.px(m["label_gap"]) if self.kind == "folio"
                else width - left - right - self.px(m["gap"]) - field_w - gap - clear_w)
        name.configure(bg=c["surface"], fg=c["text"], font=self.look.font("row", False, name), anchor="w",
                       justify="left", wraplength=max(1, wrap), bd=0, padx=0, pady=0)
        if self.kind == "folio":
            master.columnconfigure(0, minsize=left + self.px(m["label"]))
            name.grid_configure(in_=master, row=r, column=0, sticky="w", padx=(left, self.px(m["label_gap"])), pady=0)
            fr.grid_configure(in_=master, row=r, column=1, columnspan=2, sticky="w", padx=(0, right), pady=self.px(4))
        else:
            master.columnconfigure(0, weight=1)
            name.grid_configure(in_=master, row=r, column=0, sticky="w", padx=(left, self.px(m["gap"])), pady=0)
            fr.grid_configure(in_=master, row=r, column=1, columnspan=2, sticky="e", padx=(0, right), pady=self.px(4))
        fr.configure(bg=c["surface"])
        # Clear and the note out of the frame's packing first, as the frame
        # lays them out by grid with the field
        if clear is not None:
            clear.pack_forget()
        note.pack_forget()
        tk.Misc.lower(fr, ent)          # the field above the frame it lies in
        self._field(ent, "value", self.kind == "console")
        zero = max(1, int(ent.tk.call("font", "measure", widgets.real(ent, "font"), "0")))
        ent.configure(insertbackground=c["well"], justify="center", width=max(1, (field_w - 4) // zero))
        # the field keeps its grid row's number in the frame, so the label and
        # the field still share one row number, as a test groups them by it
        ent.grid_configure(in_=fr, row=r, column=0, sticky="w", padx=0, pady=0, ipady=self._ipady(ent, m["field"]))
        if clear is not None:
            clear.grid(row=r, column=1, sticky="w", padx=(gap, 0))
        note.configure(bg=c["surface"], font=self.look.font("beside", False, note), justify="left", anchor="w",
                       wraplength=field_w + gap + clear_w, padx=0, pady=0)
        widgets.observe(note)

        def show():
            if str(note.cget("text")):
                note.grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(self.px(2), 0))
            else:
                note.grid_remove()
        note.followers.append(lambda widget, keys, lit: show() if "text" in keys else None)
        show()
        band.add(name, fr, note)
        self._stop(p, "field", band, ent, None, None, (name,), name, fr, ent, note)
        why = hints.texts.get(name)
        if why:
            hints.add(band, why)
        if self.kind == "industrial":
            st.hotkeys.append((band, name, fr))

    def _hotkey_columns(self, st):
        """Industrial's hotkey rows shared between the two columns of their
        module, the first half in the left one, each ruled above but the
        first of a column."""
        if not st.hotkeys or st.inner is None:
            return
        half = (len(st.hotkeys) + 1) // 2
        for i, (band, name, fr) in enumerate(st.hotkeys):
            col = st.inner[0 if i < half else 1]
            if i >= half:
                for w in (band, name, fr):
                    w.grid_configure(in_=col)
            # the row's height kept in its own column alone, as a grid keeps
            # the least height of an empty row too
            self._size(col, "rows", self.m["row"], int(name.grid_info()["row"]))
            if i not in (0, half):
                self._rule(band, self.look.c["rule"])
        st.inner[1].columnconfigure(0, weight=1)
        st.hotkeys = []

    def profiles(self, p, plist, side, named, facts, last):
        """The Profiles page, which the lens makes as today, laid out in the
        look: the list in the look's well and type, what is done with it beside
        it, and what the chosen profile holds under them, or in Industrial in
        one module with the list and its buttons in a column of their own and
        what the profile holds beside them. Returns the band of the list's
        row."""
        st = self._open(p)
        c, m, k = self.look.c, self.m, self.kind
        r = int(plist.grid_info()["row"])
        _top, right, _bottom, left = self.pad("pad")
        holder = widgets.RowBand(p, self.look)
        tk.Misc.lower(holder, plist)
        if k == "industrial":
            st.modules[-1][1] = True
            self._put(st, holder, row=r)
        else:
            holder.grid(in_=p, row=r, column=0, columnspan=3, sticky="we")
        self._rules(st, holder)
        plist.configure(**widgets.list_options(self.look))
        zero = max(1, int(plist.tk.call("font", "measure", widgets.real(plist, "font"), "0")))
        plist.configure(width=max(1, (self.px(m["list_w"]) - 2) // zero))
        top, gap = self.px(8), self.px(m["side"])
        if k == "folio":
            top, right, bottom, left = self.pad("profile")
        if k == "industrial":
            _t, _r, _b, left = self.pad("list")
            plist.grid_configure(in_=holder, row=0, column=0, columnspan=1, sticky="nw", padx=(left, gap),
                                 pady=(gap, 0))
            side.grid_configure(in_=holder, row=1, column=0, columnspan=1, sticky="nw", padx=(left, gap),
                                pady=(gap, gap))
            facts.grid_configure(in_=holder, row=0, column=1, columnspan=1, rowspan=2, sticky="nwe",
                                 padx=(gap, right), pady=gap)
            holder.columnconfigure(0, minsize=self.px(m["list_w"]))
            holder.columnconfigure(1, weight=1)
            # the facts' column ruled down its left side, the drawing's column
            # border, a child of the page so that show_facts leaves it
            line = tk.Frame(p, bg=c["rule"], width=1, bd=0, highlightthickness=0)
            line.grid(in_=holder, row=0, column=1, rowspan=2, sticky="nsw")
            self.facts_width = self.width(st) - self.px(m["list_w"]) - 2 * gap - right
        else:
            plist.grid_configure(in_=holder, row=0, column=0, columnspan=1, sticky="nw", padx=(left, 0),
                                 pady=(top, top))
            side.grid_configure(in_=holder, row=0, column=1, columnspan=1, sticky="nw", padx=(gap, right),
                                pady=(top, top))
            holder.columnconfigure(2, weight=1)
            fpad = self.pad("facts")
            if k == "console":
                rows_pad = self.pad("pad")
                facts.configure(bg=c["deep"], padx=fpad[3], pady=fpad[0])
                facts.grid_configure(sticky="we", padx=(rows_pad[3], rows_pad[1]), pady=(self.px(m["facts_above"]), 0))
                self.facts_width = self.room - rows_pad[3] - rows_pad[1] - 2 * fpad[3]
            else:
                facts.configure(padx=fpad[3], pady=fpad[0])
                facts.grid_configure(sticky="we", padx=0, pady=0)
                self._rule_over(facts, widgets.shade(self.look, "rule_faint"))
                self.facts_width = self.room - 2 * fpad[3]
        for w in named.winfo_children():
            if w.winfo_class() == "Label":
                w.configure(font=self.look.font("row", False, w), fg=c["text"], bd=0, padx=0, pady=0)
            elif w.winfo_class() == "Entry":
                self._field(w, "value" if k == "industrial" else "line")
                w.pack_configure(ipady=self._ipady(w, m["field"]))
        last.configure(font=self.look.font("beside", False, last), fg=c["muted"])
        self.facts_ground = c["deep"] if k == "console" else c["surface"]
        # the list, the name and each button beside them are rows the keys
        # pick, which share the list's band, lit with what lies beside the list
        self._stop(p, "list", holder, plist, None, plist, (), plist)
        inside = list(_walk(side))
        entry = next((w for w in named.winfo_children() if w.winfo_class() == "Entry"), None)
        if entry is not None:
            self._stop(p, "field", holder, entry, None, named, (), named, entry)
        for b in inside:
            if b.winfo_class() == "Button":
                self._stop(p, "button", holder, b, None, b, (), b)
        holder.add(side, *[w for w in inside if w.winfo_class() in ("Frame", "Label")])
        return [holder]

    def facts(self, facts):
        """What the chosen profile holds, as the lens's show_facts makes it,
        in the look's type and colours, the two headings, the names in the
        muted colour and the values in the text colour. Never raises, so a
        profile chosen in the list always shows, see widgets.fault."""
        try:
            c, lg = self.look.c, self.legacy
            ground = self.facts_ground
            # each of the two columns of names and values in half the box, less
            # the room the lens keeps after a name and after a value, the names
            # a little wider than the values, as the drawings share them
            both = max(2, self.facts_width // 2 - self.px(10) - self.px(24))
            wraps = {"facts_name": both * 11 // 20, "facts_value": both - both * 11 // 20, "facts_title": 0}
            for w in facts.winfo_children():
                if w.winfo_class() != "Label":
                    continue
                if "bold" in str(w.cget("font")):
                    role, fg = "facts_title", c["strong"]
                elif tokens.same(str(w.cget("fg")), lg["dim"]):
                    role, fg = "facts_name", c["muted"]
                else:
                    role, fg = "facts_value", c["text"]
                w.configure(font=self.look.font(role, False, w), fg=fg, bg=ground, justify="left",
                            wraplength=wraps[role])
        except Exception as exc:
            widgets.fault(facts, exc)

    # once the pages are made

    def close(self):
        """Every page's open choices drawn, Folio's last section ruled under,
        and Industrial's hotkeys and modules laid in their columns, before the
        window is measured."""
        for st in list(self.pages.values()):
            if st.group is not None:
                self._draw_group(st)
            self._end_section(st)
            if self.kind == "industrial":
                self._hotkey_columns(st)
        if self.kind == "industrial":
            self.dialog.update_idletasks()
            for st in self.pages.values():
                self._arrange(st, 2)

    def fitted(self, fitted):
        """The window's fit, see fit.settings_fit, given to the rows. They take
        their compact sizes where it is compact, and Industrial's modules lie
        in one column where its page is too narrow for two."""
        compact = bool(fitted.get("compact"))
        if compact != self.compact:
            self.compact = compact
            for widget, how, full, more in self.sized:
                try:
                    self._apply(widget, how, full, more, compact)
                except tk.TclError:
                    pass            # a widget the page no longer has, such as a fact shown before
        if self.kind == "industrial":
            for st in self.pages.values():
                self._arrange(st, fitted.get("columns", 2))

    def _arrange(self, st, columns):
        """Industrial's modules of a page in its two columns, as
        fit.split_columns shares them, a wide module across both, or all in
        one column. What the lens grids on the page itself, the room under a
        page's last row, goes under the modules."""
        if not st.modules:
            return
        p = st.page
        gap = self.m["module_gap"]
        gap, col_gap = self.px(self._smaller("above", gap) if self.compact else gap), self.px(self.m["column_gap"])
        left, right = st.columns
        frames = [f for f, _wide in st.modules]
        wide = any(w for _f, w in st.modules)
        for w in p.grid_slaves():
            info = w.grid_info()
            if w not in st.columns and int(info.get("row", 0)) < 1000 and not w.winfo_children():
                w.grid_configure(row=3000)
        if columns == 2 and not wide:
            heights = [f.winfo_reqheight() for f in frames]
            parts = fit.split_columns(heights, gap)
            for i in (0, 1):
                p.columnconfigure(i, weight=1, uniform="lens_look_columns")
            left.grid(in_=p, row=1000, column=0, columnspan=1, sticky="new", padx=(0, col_gap // 2))
            right.grid(in_=p, row=1000, column=1, columnspan=1, sticky="new", padx=(col_gap - col_gap // 2, 0))
        else:
            parts = (list(range(len(frames))), [])
            for i in (0, 1):
                p.columnconfigure(i, weight=1 if i == 0 else 0, uniform="")
            left.grid(in_=p, row=1000, column=0, columnspan=2, sticky="new", padx=0)
            right.grid_remove()
        for col, indices in zip((left, right), parts):
            col.columnconfigure(0, weight=1)
            for j, i in enumerate(indices):
                frames[i].grid(in_=col, row=1001 + j, column=0, sticky="we", pady=(gap if j else 0, 0))


# ---- the explanation and the keys

# The explanation's part of Settings in CSS pixels at 100 percent, from the
# Settings drawings, Main, Paper-Settings and Industrial-Settings.
# console, the pane: pad (top, sides, foot), title_gap the room under the
# title, rule the room above and under the rule before the choices,
# option_gap the room between two choices, option_text the room above a
# choice's words, which stand in by the mark and the gap after it, mark
# and mark_gap, and foot the room above the footnote's words.
# sections_gap is the room between two sections where the pane lists a
# page's sections, which no drawing draws, the drawn room between choices.
# folio, the margin note: left and right the column's room inside its rule
# and at its right, gap the room between the note's parts, bar and bar_gap
# the bar down its left and the room after it, option_gap the room between
# a choice's name and its words, mark and mark_gap the square before the name
# and the room after it.
# industrial, the strip: pad (top, right, left with its bar), column the
# width of the section and the name and column_gap the room after it,
# name_gap the room above the name, text_w the widest the text runs and
# text_top the room above it, its paragraph's own margin in the drawing.
REGION = {
    "console": dict(pad=(28, 26, 22), title_gap=10, rule=(22, 18), option_gap=18, option_text=6, mark=14,
                    mark_gap=8, foot=14, sections_gap=18),
    "folio": dict(left=26, right=28, gap=10, bar=2, bar_gap=14, option_gap=4, mark=8, mark_gap=8),
    "industrial": dict(pad=(24, 40, 27), column=290, column_gap=36, name_gap=8, text_w=680, text_top=16),
}


def sentence(words):
    """The words beside a heading as a sentence of their own, as the pane's
    footnote shows them, with a capital first and a full stop last. The
    words stay the lens's own."""
    words = " ".join(str(words or "").split())
    if not words:
        return ""
    words = words[0].upper() + words[1:]
    return words if words[-1] in ".!?" else words + "."


def explained(label, why, section=None, options=(), page="", heading=False):
    """What a drawn look's explanation shows for one setting, from its words
    alone. label is the setting's own label, None for one with none of its
    own, a choice of buttons that each have a label or a sentence of a page,
    which then go by their heading's title. why is its explanation, section
    the (title, why, beside) of the heading it is under, or None, options the
    (name, why, chosen) of a choice's buttons in their order, page the page's
    name and heading whether the setting is the heading itself. A choice whose
    buttons share one explanation has it as its own, and one whose buttons
    each have their own has its heading's. Returns a dict:
      title     what the pane and the margin note show first
      why       their explanation under it
      options   (name, why, chosen) of each choice, where the choices have
                explanations of their own, else none
      section   the strip's line above the name, the heading's title, or the
                page's name for the heading itself
      name      the strip's name, the chosen choice's or the setting's title
      text      the strip's explanation, the chosen choice's own where the
                choices have their own
      footnote  the heading's beside words as a sentence, see sentence, unless
                the explanation says them already
      idle      False, and sections, none, see idle_explained."""
    s_title, s_why, s_beside = section or ("", "", "")
    whys = [w or "" for _n, w, _c in options]
    own = len(set(whys)) > 1
    if options and not own:
        why = whys[0] or why
    elif own:
        why = s_why or why
    why = why or ""
    title = label or s_title
    chosen = next(((n, w or "") for n, w, c in options if c), None)
    foot = sentence(s_beside)
    if foot and foot.rstrip(".").lower() in why.lower():
        foot = ""
    return {"title": title, "why": why, "options": [(n, w or "", bool(c)) for n, w, c in options] if own else [],
            "section": page if heading else s_title, "name": chosen[0] if chosen else title,
            "text": (chosen[1] or why) if (own and chosen) else why, "footnote": foot, "idle": False,
            "sections": []}


def idle_explained(page, sections):
    """What the explanation shows on a page before a setting is picked, from
    the page's sections as (title, why, beside) in their order. The pane
    lists them, each with its explanation, and the margin note and the strip
    show the first, the strip with the page's name over it."""
    title, why = (sections[0][0], sections[0][1] or "") if sections else ("", "")
    return {"title": title, "why": why, "options": [], "section": page, "name": title, "text": why,
            "footnote": "", "idle": True, "sections": [(t, w or "") for t, w, _b in sections]}


def walk_order(places, middle):
    """The order the keys walk a page's rows in, as indices into places, the
    rows' (x, y) on the page. They go down the page, and where the page has
    two columns, Industrial's, down the left one, then down the right one,
    middle being the x where the right one begins. Rows level with each
    other go from left to right."""
    return sorted(range(len(places)), key=lambda i: (places[i][0] >= middle, places[i][1], places[i][0]))


def stepped(count, at, step, wrap=True):
    """The index step places on from at among count, round from the last
    to the first and back where wrap is set, else held at either end. From
    None a step forward is the first and a step back the last. None where
    there are none."""
    if count <= 0:
        return None
    if at is None:
        return 0 if step > 0 else count - 1
    if wrap:
        return (at + step) % count
    return max(0, min(count - 1, at + step))


def _walk(widget):
    """A widget's widgets, each before its own, as Tk lists them."""
    for child in widget.winfo_children():
        yield child
        for grandchild in _walk(child):
            yield grandchild


def _inside(widget, holder):
    """Whether a widget is holder or lies inside it."""
    while widget is not None:
        if widget is holder:
            return True
        widget = getattr(widget, "master", None)
    return False


def _pick_label(widget, look, on):
    """A row's label drawn as picked or not, see widgets._State.picked. A
    label the lens made and the look dressed, the readout's switches, the
    corner's and a hotkey's, takes the row's lit type and the strong colour
    itself."""
    try:
        if hasattr(widget, "picked"):
            widget.picked(on)
        else:
            widget.configure(font=look.font("row", on, widget), fg=look.c["strong"] if on else look.c["text"])
    except tk.TclError:
        pass


class Stop(object):
    """A row of a page that the keys and the pointer pick, see RowWalker and
    SettingsFrame.select. kind says how the keys work it: switch, choice,
    corner, quality, field, list or button. control is the check button, the
    slider, the field, the list or the button the keys work, and options a
    choice's or the corner's radio buttons in their order. band is the band
    lit while it is picked, anchor the widget its place on the page is read
    from, the band or, where several share one band, its own widget, labels
    the labels drawn picked with it, and widgets every widget of the row the
    pointer can be on, which name it."""

    def __init__(self, page, kind, band, control=None, options=None, anchor=None, labels=(), widgets=()):
        self.page, self.kind, self.band, self.control = page, kind, band, control
        self.options = options if options is not None else []
        self.anchor = anchor if anchor is not None else band
        self.labels = [w for w in labels if w is not None]
        self.widgets = [w for w in widgets if w is not None]


# The classes of the widgets that keep their own keys while they have the
# keyboard, see RowWalker
OWN_KEYS = ("Entry", "Listbox", "Text", "Spinbox", "TEntry", "TCombobox")

# The keys RowWalker takes on the dialog, as Tk names them, each with what it
# does and which way
WALK_KEYS = (("<Up>", "step", -1), ("<Down>", "step", 1), ("<Left>", "change", -1), ("<Right>", "change", 1),
             ("<Return>", "enter", 0), ("<KP_Enter>", "enter", 0), ("<Escape>", "escape", 0),
             ("<Control-Tab>", "turn", 1), ("<Control-Shift-Tab>", "turn", -1), ("<Next>", "turn", 1),
             ("<Prior>", "turn", -1))

# The keys a slider also takes in Tk's own bindings for a scale, which would
# move a slider that has the keyboard as well as the walker does
SCALE_KEYS = ("<Up>", "<Down>", "<Left>", "<Right>")


class RowWalker(object):
    """The keys of Settings in a drawn look, as plan 3.1 has them, bound on
    the dialog. Up and Down pick the row before or after in the order the
    page is read, see walk_order, round from the last to the first. Left and
    Right change a choice, the quality step or the corner and do nothing on a
    switch. Enter switches a switch, presses a button, and gives a field or
    the profile list the keyboard. Esc cancels. Ctrl+Tab and PgDn turn to the
    next page, Ctrl+Shift+Tab and PgUp to the one before. None of them acts
    while a field, a list or a text has the keyboard, which keeps its own
    keys, apart from Esc, which gives the keyboard back to the rows, so a
    second Esc cancels. A hotkey field takes every key it is given, Esc too,
    see the lens's settings_dialog. Tab and Shift+Tab stay Tk's own, and a
    control that gets the keyboard picks its row.

    A row the keys pick is lit and explained, kept in view, and its switch,
    chosen choice or button given the keyboard, so Space works it as Tk's
    own keys do, or the dialog itself where it has none of those. The
    keyboard moves only inside the dialog, which has it already where these
    keys come to it, so no window of the lens takes the foreground.
    current is the row picked, or None."""

    def __init__(self, frame, cancel):
        self.frame, self.dialog, self.cancel = frame, frame.dialog, cancel
        self.current = None
        for seq, what, step in WALK_KEYS:
            self.dialog.bind(seq, lambda event, w=what, d=step: self.key(event, w, d), add="+")
        self.dialog.bind("<FocusIn>", self.focused, add="+")
        # a slider given the keyboard by a click takes the arrows here
        # first, ahead of Tk's own bindings for a scale, see SCALE_KEYS
        keys = {seq: (what, step) for seq, what, step in WALK_KEYS}
        for stop in frame.rows.stops:
            if stop.kind == "quality" and stop.control is not None:
                for seq in SCALE_KEYS:
                    what, step = keys[seq]
                    stop.control.bind(seq, lambda event, w=what, d=step: self.key(event, w, d), add="+")

    def key(self, event, what, step):
        """A key of WALK_KEYS. Returns break where it acted, so no binding
        after the dialog's acts on it too, such as Tk's own for Tab."""
        try:
            focus = self.dialog.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        own = focus is not None and focus.winfo_class() in OWN_KEYS
        if own and what != "escape":
            return None
        try:
            return getattr(self, what)(step, focus if own else None)
        except tk.TclError:
            return "break"

    def order(self):
        """The rows of the page that shows that the keys pick, in the order
        they are walked, see walk_order."""
        page = self.frame.host.page()
        if page is None:
            return []
        stops = [s for s in self.frame.rows.stops if str(s.page) == str(page) and s.anchor.winfo_ismapped()]
        x0, y0 = page.winfo_rootx(), page.winfo_rooty()
        places = [(s.anchor.winfo_rootx() - x0, s.anchor.winfo_rooty() - y0) for s in stops]
        middle = page.winfo_width() // 2 if self.frame.kind == "industrial" else 10 ** 9
        return [stops[i] for i in walk_order(places, middle)]

    def step(self, d, _focus):
        stops = self.order()
        if stops:
            at = stops.index(self.current) if self.current in stops else None
            self.pick(stops[stepped(len(stops), at, d)])
        return "break"

    def change(self, d, _focus):
        stop = self.current
        if stop is None or stop not in self.order():
            return "break"
        if stop.kind in ("choice", "corner"):
            buttons = list(stop.options)
            at = next((i for i, b in enumerate(buttons) if faces.selected(b)), None)
            i = stepped(len(buttons), at, d, wrap=stop.kind == "corner")
            if i is not None and i != at and str(buttons[i].cget("state")) != "disabled":
                buttons[i].invoke()
                if stop.kind == "choice":
                    self._give(buttons[i])
        elif stop.kind == "quality" and str(stop.control.cget("state")) != "disabled":
            scale = stop.control
            low, high = sorted((float(scale.cget("from")), float(scale.cget("to"))))
            now = int(round(float(scale.get())))
            scale.set(max(low, min(high, now + d)))
        self.frame.refresh_soon()
        return "break"

    def enter(self, _d, _focus):
        stop = self.current
        if stop is None or stop not in self.order():
            return "break"
        if stop.kind in ("switch", "button") and str(stop.control.cget("state")) != "disabled":
            stop.control.invoke()
        elif stop.kind in ("field", "list"):
            stop.control.focus_set()
        self.frame.refresh_soon()
        return "break"

    def escape(self, _d, focus):
        if focus is not None:
            # a field, a list or a text had the keyboard, which goes back to the rows
            self._give(self._control(self.current))
            return "break"
        self.cancel()
        return "break"

    def turn(self, d, _focus):
        nb = self.frame.nb
        count = len(nb.tabs())
        if count:
            nb.select(stepped(count, nb.index(nb.select()), d))
        return "break"

    def focused(self, event):
        """A control got the keyboard, by Tab, a click or the keys, and its
        row is picked, where it is one."""
        widget = getattr(event, "widget", None)
        if widget is None or isinstance(widget, str) or widget is self.dialog:
            return
        stop = self.frame.rows.stop_of(widget)
        if stop is not None and stop is not self.current:
            self.frame.select(widget, "focus")

    def pick(self, stop):
        """A row picked by the keys: lit and explained, kept in view, and its
        control given the keyboard, see the class's docstring."""
        self.frame.select(stop.anchor, "keys")
        try:
            self.frame.host.keep(stop.anchor, sc.px(8, self.frame.look.scale_for(self.dialog)))
        except tk.TclError:
            pass
        self._give(self._control(stop))

    @staticmethod
    def _control(stop):
        """What takes the keyboard while a row is picked: its switch or button,
        its chosen choice, or None, the dialog itself."""
        if stop is None:
            return None
        if stop.kind in ("switch", "button"):
            return stop.control
        if stop.kind == "choice":
            return next((b for b in stop.options if faces.selected(b)), stop.options[0] if stop.options else None)
        return None

    def _give(self, widget):
        (self.dialog if widget is None else widget).focus_set()
