"""How Settings and the NR settings panel of a drawn look fit the screen, and
how Industrial shares a page's sections between its two columns.

Settings is drawn 1120 pixels wide and 736 to 746 high, which a 1080 row
screen at 150 percent has no room for, nor a 1366x768 one. settings_fit takes
the drawn size where it fits, then the compact sizes with the height held to
the screen, then, where the width does not fit, the narrow explanation column,
and below that the explanation in a popup. Fonts never shrink, only spacing
and layout. settings_parts gives the parts of the frame for a fit, the rail,
the title, the part a page scrolls in, the explanation's column and the
footer. panel_fit picks the panel's level in the same way. grown says how
far an explanation's part grows for a text that does not fit it.

Pure. Sizes in are screen pixels, and the drawn sizes come from
tokens.METRICS in CSS pixels.
"""
from lens_look import tokens
from lens_look.scale import px

# CSS pixels kept free at each side of the screen's work area for Settings,
# and above and below the panel on its monitor.
SETTINGS_ROOM = 8
PANEL_ROOM = 24


def _kind(look):
    kind = getattr(look, "kind", look)
    return kind if kind in tokens.DRAWN else "console"


def settings_fit(look, s, work_w, work_h, caption_h, border=1, extra_w=0):
    """Settings' size and layout for a look at the scale s on a work area of
    work_w by work_h screen pixels, its window having caption_h pixels of
    caption and border pixels of frame at each side and at the bottom.
    extra_w is the width in screen pixels the window takes beyond the drawn
    width, for a page that asks for more room than its drawn column has, see
    settings_parts. Returns a dict:
      client      (width, height) of the client area, which Tk's geometry sets
      outer       (width, height) of the whole window
      compact     the compact sizes apply, and a page taller than its column scrolls
      narrow      the drawn width did not fit
      explain     pane, margin, strip or popup, where a setting's explanation shows
      column      the width of the pane or the margin note's column, 0 for none
      columns     how many columns industrial's modules take, 1 or 2
    """
    kind = _kind(look)
    m = tokens.METRICS[kind]
    flags = tokens.FLAGS[kind]
    room = 2 * px(SETTINGS_ROOM, s)
    avail_w, avail_h = work_w - room, work_h - room
    cw, ch = px(m["settings"][0], s) + max(0, int(extra_w)), px(m["settings"][1], s)
    explain = flags["explain"]
    column = px(m.get("explain_w", 0), s)
    columns = 2 if kind == "industrial" else 1

    def outer(w, h):
        return w + 2 * border, h + caption_h + border

    fits_w = outer(cw, ch)[0] <= avail_w
    fits_h = outer(cw, ch)[1] <= avail_h
    compact = not (fits_w and fits_h)
    narrow = not fits_w
    if narrow:
        if kind == "industrial":
            # the strip runs under the page at any width, and the modules
            # take one column where the page is narrower than drawn for two
            cw = avail_w - 2 * border
            pad = tokens.METRICS[kind]["page_pad"][1]
            if cw - 2 * px(pad, s) < px(m["one_column_below"], s):
                columns = 1
        else:
            # the explanation's column narrows, and below that it goes,
            # leaving the explanation to a popup on the pointer's rest
            slim = cw - (column - px(m["explain_narrow_w"], s))
            if outer(slim, ch)[0] <= avail_w:
                cw, column = slim, px(m["explain_narrow_w"], s)
            else:
                cw, column, explain = cw - column, 0, "popup"
                cw = min(cw, avail_w - 2 * border)
    if compact:
        ch = min(ch, avail_h - caption_h - border)
    return {"client": (cw, ch), "outer": outer(cw, ch), "compact": compact, "narrow": narrow,
            "explain": explain, "column": column, "columns": columns}


def settings_parts(look, s, fitted):
    """The parts of Settings' frame at the scale s for a fit settings_fit
    gave, in screen pixels, which tile its client area exactly. Returns a
    dict:
      rail, main, column  the widths of the rail, of the part the page shows
                          in and of the explanation's column, each 0 where
                          there is none. Industrial has no rail, and its
                          strip runs along the foot
      band, head          the heights of industrial's tab band and of the
                          page's title, each 0 where a kind has none
      view                the height of the part the page scrolls in
      strip, footer       the heights of industrial's strip, 0 elsewhere, and
                          of the footer or the key strip
      pad                 the room round the page where it scrolls, as (top,
                          right, bottom, left)
      room                the width the page has there
      title               the title's size in CSS pixels, 0 for none
    """
    kind = _kind(look)
    m = tokens.METRICS[kind]
    small = tokens.COMPACT[kind] if fitted["compact"] else {}
    cw, ch = fitted["client"]
    if kind == "industrial":
        band, head, rail, column, title = px(m["tab_band_h"], s), 0, 0, 0, 0
        strip = px(small.get("strip_h", m["strip_h"]), s)
        footer = px(m["key_strip_h"], s)
        top, side = m["page_pad"][0], m["page_pad"][1]
        pad = (px(top, s), px(side, s), px(m["view_bottom"], s), px(side, s))
    else:
        band, strip = 0, 0
        rail, column = px(m["rail_w"], s), fitted["column"]
        title = small.get("title", m["title"])
        footer = px(small.get("footer_h", m["footer_h"]), s)
        if kind == "console":
            # the title's line is as much taller than its words as drawn
            head = px(m["main_pad"][0], s) + px(m["title_line"] * float(title) / m["title"], s)
            pad = (0, px(m["main_pad"][1], s), px(m["main_pad"][2], s), px(m["main_pad"][1], s))
        else:
            # folio's rows run the column's whole width, their rules and lit
            # band too, and keep main_pad inside them, see
            # lens_look.settings.ROWS, so the page itself has none at its sides
            head = px(m["title_top"], s) + px(m["title_row_h"] * float(title) / m["title"], s)
            pad = (0, 0, px(m["view_bottom"], s), 0)
    main = cw - rail - column
    return {"rail": rail, "main": main, "column": column, "band": band, "head": head,
            "view": ch - band - head - strip - footer, "strip": strip, "footer": footer, "pad": pad,
            "room": main - pad[1] - pad[3], "title": title}


def tab_widths(natural, room):
    """The widths of industrial's tabs in a band with room pixels for them,
    each its natural width and an even share of what is left, the first ones
    a pixel more where it does not share out evenly, as the drawing's flex
    shares it. Where the band is narrower than the tabs, each gives up room in
    proportion to its width, so the tabs still fill the band."""
    n = len(natural)
    if not n:
        return []
    room, total = max(n, int(room)), sum(natural)
    if total <= room:
        each, more = divmod(room - total, n)
        return [w + each + (1 if i < more else 0) for i, w in enumerate(natural)]
    out = [max(1, int(w * room / float(total))) for w in natural]
    for i in range(max(0, room - sum(out))):
        out[i % n] += 1
    return out


# The least part of the drawn gap between two groups of key caps that a
# footer's groups close up to before anything leaves it, see key_strip.
KEY_GAP_FLOOR = 0.5


def key_strip(room, groups, gap, floor, version=0, keep=None):
    """How a footer's key groups fit room pixels beside its buttons, as (the
    gap between two groups, whether the version stays, the indexes of the
    groups that stay). groups are the groups' widths in their order, gap the
    drawn gap between two, floor the least gap, version the room the version
    takes with its own gaps, 0 where the footer has none, and keep the index
    of a group that stays at every width, Industrial's Esc Cancel, which no
    button of its look carries. The gaps close up first, down to floor, then
    the version leaves the footer, then the other groups leave, the last
    first, each time with the gaps as drawn again where they fit. Without a
    group to keep every group can leave, so no button is ever cut."""
    kept = list(range(len(groups)))
    shown = version > 0
    while True:
        have = room - (version if shown else 0)
        words, n = sum(groups[i] for i in kept), max(0, len(kept) - 1)
        if words + n * gap <= have:
            return gap, shown, kept
        if n > 0:
            closer = gap - -(-(words + n * gap - have) // n)
            if closer >= floor:
                return closer, shown, kept
        if shown:
            shown = False
            continue
        others = [i for i in kept if i != keep]
        if not others:
            return gap, shown, kept
        kept.remove(others[-1])


def panel_heights(look, strength=False):
    """The panel's height at each of the levels 0, 1 and 2 in CSS pixels, from
    the drawn sizes. Level 0 is the drawing. Level 1 has the compact rows.
    Level 2 also has the profile row folded into the head. The explanation's
    part keeps its drawn height at every level, so a text that fits it shows
    whole. strength adds the Strength row, which no drawing has. These model
    the drawings, and the panel can give its own measured heights to
    panel_fit instead."""
    m = tokens.METRICS[_kind(look)]
    total = m["panel"][1] + (m["panel_strength"] if strength else 0)
    rows = total - m["panel_head"] - m["panel_intro"] - m["panel_explain"] - m["panel_footer"]
    one = total - rows * (1 - tokens.COMPACT_RATIO)
    two = one - m["panel_profile"] * tokens.COMPACT_RATIO
    return total, one, two


def panel_fit(look, s, monitor_h, strength=False, heights=None):
    """The panel's level for a look at the scale s on a monitor monitor_h
    screen pixels high, keeping PANEL_ROOM free above and below: 0, the
    drawing, 1, compact rows, 2, the profile row in the head as well, or 3,
    where the pass card scrolls to keep the lit row in view. heights are the
    panel's own heights at levels 0 to 2 in screen pixels, measured, or None
    for the drawn model's."""
    avail = monitor_h - 2 * px(PANEL_ROOM, s)
    if heights is None:
        heights = [px(h, s) for h in panel_heights(look, strength)]
    for level, h in enumerate(heights):
        if h <= avail:
            return level
    return 3


# The most lines an explanation's part grows by for a text that needs more
# room than its drawn height gives, see grown.
GROW_LINES = 2


def grown(need, room, line, spare):
    """How many pixels an explanation's part grows by for lines that need need
    pixels where it has room: none where they fit, else what they need, at
    most GROW_LINES lines of line pixels, and never more than spare, the room
    the window has left on its monitor's work area, or the page above
    Industrial's strip in Settings. A text that needs more is one a check
    refuses before it ships, and the lines that do not fit then stay out
    whole, never cut and never ending in three dots."""
    if need <= room:
        return 0
    return max(0, min(int(need - room), GROW_LINES * int(line), int(spare)))


def whole(heights, room):
    """How many parts of these heights, one under another, show whole in room
    pixels, from the first, which always shows, as Slate's pane lists the
    sections of a page before a setting is picked: on a short screen its
    narrow pane holds fewer, and none is cut."""
    n, y = 0, 0
    for h in heights:
        if n and y + h > room:
            break
        y += h
        n += 1
    return n


def split_columns(heights, gap=0):
    """Industrial's two columns for sections of these heights in their order.
    The left column takes the fewest sections from the start that are at
    least as tall as the rest, so it is the fuller one, and the right column
    always keeps at least the last. Returns (the left's indices, the right's).
    One section stays in the left column alone."""
    n = len(heights)
    if n < 2:
        return list(range(n)), []

    def tall(part):
        return sum(part) + gap * max(0, len(part) - 1)

    for k in range(1, n):
        if tall(heights[:k]) >= tall(heights[k:]):
            return list(range(k)), list(range(k, n))
    return list(range(n - 1)), [n - 1]
