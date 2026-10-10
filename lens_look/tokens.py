"""The looks' colours, type and sizes, as the drawings of the design canvas
give them in their inline styles, and the few sums made on colours: the ten
colours a look hands the parts of the lens it does not draw itself, the
colours a theme of the user's own does not give, and the contrast of two
colours.

A kind is the layout a look has. console, folio and industrial are the three
drawn looks, which the canvas names Slate Console, Folio and Industrial, and
classic is the lens as it looked up to 0.7.0, which the tests can still ask
for. Each built-in theme names its kind, see THEME_KIND. Sizes are CSS pixels
at 100 percent, which lens_look.scale turns into the screen's own.

Nothing here imports tkinter or the lens, so the checks read it with no Tk
root.
"""
import collections

KINDS = ("classic", "console", "folio", "industrial")
DRAWN = ("console", "folio", "industrial")          # the kinds the canvas draws

# The ten colours of a theme, as neural_lens.THEME_KEYS names them. Every part
# of the lens a look does not draw itself takes these, as BG to CLOSE.
THEME_KEYS = ("bg", "fg", "accent", "dim", "warn", "cap", "hover", "field", "tab", "close")

# Today's four themes, neural_lens.THEMES, which the classic kind keeps as they
# are. A value of a built-in theme that is not one of these came from the
# user's themes.json, see legacy.
CLASSIC = {
    "Slate": {"bg": "#1b2430", "fg": "#cbd5e1", "accent": "#4ade80", "dim": "#64748b", "warn": "#fbbf24",
              "cap": "#243040", "hover": "#334155", "field": "#0b1220", "tab": "#1e293b", "close": "#e11d48"},
    "Graphite": {"bg": "#232323", "fg": "#d6d6d6", "accent": "#f0b429", "dim": "#8a8a8a", "warn": "#f0b429",
                 "cap": "#2e2e2e", "hover": "#3d3d3d", "field": "#161616", "tab": "#2a2a2a", "close": "#d13c3c"},
    "Paper": {"bg": "#f3f4f6", "fg": "#1f2937", "accent": "#15803d", "dim": "#6b7280", "warn": "#b45309",
              "cap": "#e5e7eb", "hover": "#d1d5db", "field": "#ffffff", "tab": "#e5e7eb", "close": "#dc2626"},
    "Industrial": {"bg": "#2b2622", "fg": "#e7dcc8", "accent": "#f59e0b", "dim": "#8a7f70", "warn": "#fbbf24",
                   "cap": "#35302b", "hover": "#4a413a", "field": "#1f1b18", "tab": "#332d28", "close": "#b91c1c"},
}

# The kind each built-in theme takes in the drawn looks. Graphite has no
# drawing and takes Slate Console's layout in its own colours. A theme of the
# user's own takes the kind of the built-in theme it starts from, see
# theme_kind.
THEME_KIND = {"Slate": "console", "Graphite": "console", "Paper": "folio", "Industrial": "industrial"}


def looked(given):
    """The built-in theme a themes.json entry's look key names, Slate,
    Graphite, Paper or Industrial whatever the case of its letters, or None
    where it names none of them."""
    want = str((given or {}).get("look") or "").strip().lower()
    for name in CLASSIC:
        if name.lower() == want:
            return name
    return None


def theme_kind(name, given=None):
    """The kind a theme is drawn in, that of the built-in theme its
    themes.json entry's look key names, else that of the built-in theme of its
    name, else console."""
    return THEME_KIND.get(looked(given) or name, "console")


def base_of(name, given=None):
    """The built-in theme a theme's colours start from, the theme itself where
    it is one, else the one its themes.json entry's look key names, else
    Slate. neural_lens fills the colours an entry leaves out from this one."""
    if name in CLASSIC:
        return name
    return looked(given) or "Slate"

# ---- colours

# Each drawn kind's colours by the names its drawings use, every one of them
# taken from the drawings' inline styles.
OWN = {
    "console": {
        "surface": "#1b2430",       # page, menus, panel body, dialog body
        "deep": "#151c27",          # rail, pane, footers, bar, panel head, readout, menu header, tooltip
        "band": "#243040",          # lit row, chosen rail item, key cap fill, secondary buttons, hairlines
        "raised": "#334155",        # chosen segment or card, outer borders, cap borders, separators
        "well": "#0b1220",          # wells, fields, slider track
        "text": "#cbd5e1",
        "strong": "#e2e8f0",        # titles, chosen and lit labels, current values
        "muted": "#94a3b8",         # secondary text, beside words, hints, version
        "faint": "#64748b",         # pips, rings, greyed thumbs, tie borders, never text
        "accent": "#4ade80",        # lit bar, ring, Save, OK, lit slider fill, progress
        "on_accent": "#0b1220",
        "warn": "#fbbf24",
        "close": "#e11d48",
        "tab": "#1e293b",
    },
    "folio": {
        "paper": "#edebe6",         # the sheet
        "strip": "#e4e1da",         # chosen rail item, panel head, tab, menu header, caption tint
        "band": "#e2ded5",          # lit row
        "field": "#f7f6f2",         # fields, key caps, tooltip, corner screen
        "ink": "#1b1a17",           # text, chosen segment, primary button, switch on
        "muted": "#58544b",
        "rule": "#cdc8be",          # section rules, column borders
        "rule_faint": "#dad6cd",    # row separators
        "edge": "#7a746a",          # control borders, off knob, ticks
        "edge_off": "#b9b3a8",      # greyed borders and glyphs
        "greyed_line": "#a39d92",   # a tied slider's line and marker
        "greyed_track": "#c9c4ba",  # a tied slider's track and ticks
        "greyed_fill": "#dcd8cf",   # the chosen segment while greyed
        "accent": "#1f6b48",        # lit bar, margin rule, lit slider marker
        "warn": "#9a4e0c",
        "on_ink": "#f7f6f2",
        "cap_on_ink_edge": "#77726a",   # a key cap on a primary button, its border
        "cap_on_ink_text": "#e9e6df",   # and its text
        "close": "#dc2626",
    },
    "industrial": {
        "plate": "#2b2622",         # modules, panel body
        "deep": "#1f1b18",          # caption tint, tab band, wells, fields, strip, bar
        "band": "#241f1c",          # key strip, greyed wells
        "head": "#35302b",          # module headers, secondary buttons
        "tab": "#332d28",           # unselected tabs
        "lit": "#3a332d",           # lit row, tile or menu entry
        "hover": "#4a413a",
        "rule": "#433b34",          # row separators, tab tops
        "edge": "#544a41",          # module and control borders
        "text": "#e7dcc8",
        "muted": "#ab9f8d",
        "faint": "#8a7f70",         # ticks, seams, greyed fill, rings, never text
        "accent": "#f59e0b",
        "on_accent": "#1f1b18",
        "warn": "#fbbf24",          # the OFF word and outline, warnings
        "close": "#b91c1c",
    },
}

# The ten colours each drawn kind hands the rest of the lens, by the drawing's
# own names. console's and industrial's are today's Slate and Industrial but
# for dim, which was too faint to read as text, and folio's are the swatches
# the drawn Paper look shows for itself.
LEGACY_FROM = {
    "console": {"bg": "surface", "fg": "text", "accent": "accent", "dim": "muted", "warn": "warn", "cap": "band",
                "hover": "raised", "field": "well", "tab": "tab", "close": "close"},
    "folio": {"bg": "paper", "fg": "ink", "accent": "accent", "dim": "muted", "warn": "warn", "cap": "band",
              "hover": "strip", "field": "field", "tab": "strip", "close": "close"},
    "industrial": {"bg": "plate", "fg": "text", "accent": "accent", "dim": "muted", "warn": "warn", "cap": "head",
                   "hover": "hover", "field": "deep", "tab": "tab", "close": "close"},
}
LEGACY = {kind: {k: OWN[kind][name] for k, name in LEGACY_FROM[kind].items()} for kind in DRAWN}

# The roles every look's code draws with, the same names in every kind.
#   surface     the page, menus, the panel's body, a dialog's body
#   deep        a step from the surface: rail, pane, footers, bar, heads, readout, tooltip
#   lit         the row, entry or tile the pointer or the keys are on
#   chosen      the chosen rail item or tab
#   raised      the chosen segment or card, with on_raised on it
#   well        wells, fields and slider tracks
#   head        secondary buttons and the header plates of modules
#   hover       the colour under the pointer where a look has one
#   tab         a tab not chosen
#   rule        rules and separators
#   edge        the borders of controls and modules
#   frame       the line round the lens and round the panel
#   text, strong, muted     body text, titles and lit labels, secondary words
#   faint       the faint marks, never text, which are console's pips, rings
#               and greyed thumbs, industrial's ticks, seams and rings, and
#               folio's greyed borders and glyphs. Folio draws its ticks in edge
#   accent      the lit bar, rings, thumbs and fills, with on_accent on it
#   primary     Save and OK, with on_primary on it
#   warn, close the warnings and the close button's hover
#   cap, cap_edge, cap_text     a key cap
ROLES = ("surface", "deep", "lit", "chosen", "raised", "on_raised", "well", "head", "hover", "tab", "rule", "edge",
         "frame", "text", "strong", "muted", "faint", "accent", "on_accent", "primary", "on_primary", "warn", "close",
         "cap", "cap_edge", "cap_text")

# Each role of each drawn kind, by the name its drawings give the colour.
ROLE_FROM = {
    "console": {"surface": "surface", "deep": "deep", "lit": "band", "chosen": "band", "raised": "raised",
                "on_raised": "strong", "well": "well", "head": "band", "hover": "raised", "tab": "tab",
                "rule": "band", "edge": "raised", "frame": "raised", "text": "text", "strong": "strong",
                "muted": "muted", "faint": "faint", "accent": "accent", "on_accent": "on_accent", "primary": "accent",
                "on_primary": "on_accent", "warn": "warn", "close": "close", "cap": "band", "cap_edge": "raised",
                "cap_text": "text"},
    "folio": {"surface": "paper", "deep": "strip", "lit": "band", "chosen": "strip", "raised": "ink",
              "on_raised": "on_ink", "well": "field", "head": "paper", "hover": "strip", "tab": "strip",
              "rule": "rule", "edge": "edge", "frame": "edge", "text": "ink", "strong": "ink", "muted": "muted",
              "faint": "edge_off", "accent": "accent", "on_accent": "on_ink", "primary": "ink", "on_primary": "on_ink",
              "warn": "warn", "close": "close", "cap": "field", "cap_edge": "edge", "cap_text": "muted"},
    "industrial": {"surface": "plate", "deep": "deep", "lit": "lit", "chosen": "plate", "raised": "lit",
                   "on_raised": "text", "well": "deep", "head": "head", "hover": "hover", "tab": "tab",
                   "rule": "rule", "edge": "edge", "frame": "accent", "text": "text", "strong": "text",
                   "muted": "muted", "faint": "faint", "accent": "accent", "on_accent": "on_accent",
                   "primary": "accent", "on_primary": "on_accent", "warn": "warn", "close": "close", "cap": "plate",
                   "cap_edge": "edge", "cap_text": "text"},
}
DRAWN_ROLES = {kind: {role: OWN[kind][name] for role, name in ROLE_FROM[kind].items()} for kind in DRAWN}

# How each role follows from a theme's ten colours, for a theme the drawings do
# not give, such as Graphite or one of the user's own. A rule is a key of the
# ten, ("mix", a, b, t), a moved the part t of the way to b, ("dark", a, f), a
# with its light times f, or ("role", r), the colour of another role. In
# console deep is the surface darkened by about a fifth, strong the text a
# third of the way to white and faint the muted text partly toward the
# surface, lit is the cap colour, raised the hover colour, and well and
# on_accent the field colour. folio and industrial follow their own drawings
# in the same way. Each mix is chosen so that the drawn kind's own ten colours
# give back its drawn roles to within a few steps.
WHITE = "#ffffff"
RULES = {
    "console": {"surface": "bg", "deep": ("dark", "bg", 0.8), "lit": "cap", "chosen": "cap", "raised": "hover",
                "on_raised": ("role", "strong"), "well": "field", "head": "cap", "hover": "hover", "tab": "tab",
                "rule": "cap", "edge": "hover", "frame": "hover", "text": "fg", "strong": ("mix", "fg", WHITE, 1 / 3.0),
                "muted": "dim", "faint": ("mix", "dim", "bg", 0.37), "accent": "accent", "on_accent": "field",
                "primary": "accent", "on_primary": "field", "warn": "warn", "close": "close", "cap": "cap",
                "cap_edge": "hover", "cap_text": "fg"},
    "folio": {"surface": "bg", "deep": "hover", "lit": "cap", "chosen": "hover", "raised": "fg",
              "on_raised": "field", "well": "field", "head": "bg", "hover": "hover", "tab": "tab",
              "rule": ("mix", "bg", "fg", 0.17), "edge": ("mix", "bg", "fg", 0.57), "frame": ("role", "edge"),
              "text": "fg", "strong": "fg", "muted": "dim", "faint": ("mix", "dim", "bg", 0.63), "accent": "accent",
              "on_accent": "field", "primary": "fg", "on_primary": "field", "warn": "warn", "close": "close",
              "cap": "field", "cap_edge": ("role", "edge"), "cap_text": "dim"},
    "industrial": {"surface": "bg", "deep": "field", "lit": ("mix", "cap", "hover", 0.33), "chosen": "bg",
                   "raised": ("role", "lit"), "on_raised": "fg", "well": "field", "head": "cap", "hover": "hover",
                   "tab": "tab", "rule": ("mix", "bg", "fg", 0.12), "edge": ("mix", "bg", "fg", 0.2),
                   "frame": "accent", "text": "fg", "strong": "fg", "muted": "dim", "faint": ("mix", "dim", "bg", 0.26),
                   "accent": "accent", "on_accent": "field", "primary": "accent", "on_primary": "field",
                   "warn": "warn", "close": "close", "cap": "bg", "cap_edge": ("role", "edge"), "cap_text": "fg"},
}

# The roles drawn as text and the grounds they are drawn on, which need 4.5:1,
# and the pairs drawn one on the other beside those.
TEXT_ROLES = ("text", "strong", "muted", "accent", "warn")
GROUNDS = ("surface", "deep", "lit", "well", "chosen")
TEXT_ON = (("on_accent", "accent"), ("on_primary", "primary"), ("on_raised", "raised"), ("cap_text", "cap"),
           ("text", "head"), ("text", "hover"))
# The colours that show where a control is or what state it is in, which need
# 3:1 on their grounds: accent and warn in every look, folio's control
# outlines and ticks in edge, and console's and industrial's rings, pips and
# ticks in faint, which those two draw on the surface, the deep colour and the
# wells. The borders and state fills the drawings draw under 3:1 are in
# UNDER_MARK.
MARKS = {"console": ("faint", ("surface", "deep", "well")), "folio": ("edge", GROUNDS[:4]),
         "industrial": ("faint", ("surface", "deep", "well"))}
TEXT_MIN, MARK_MIN = 4.5, 3.0

# The borders and state fills the drawings draw under MARK_MIN, each as (role,
# the role it is drawn on or against, what it draws). They stay as drawn until
# it is decided whether they are drawn stronger, and the checks name each of
# them on every run. Folio has none.
UNDER_MARK = {
    "console": (("raised", "well", "the chosen segment of a switch or a choice strip in its well, and the chosen "
                                   "profile in the list"),
                ("muted", "strong", "the word of a segment not chosen against the chosen one's, which is also "
                                    "semibold"),
                ("raised", "surface", "a chosen card, a ticked tie box, and the borders of windows, dialogs, "
                                      "notices and key caps"),
                ("raised", "deep", "the borders of the bar, the menus, the tooltip and the readout")),
    "folio": (),
    "industrial": (("edge", "surface", "the borders of modules, menus, dialogs and controls on the plate, and "
                                       "the ticks of a slider not lit"),
                   ("edge", "deep", "the borders of wells, fields, key caps and the progress bar"),
                   ("edge", "head", "the borders of secondary buttons, steppers and reset buttons"),
                   ("edge", "tab", "the borders of the tabs not chosen")),
}


def text_pairs(kind):
    """The (text role, ground role) pairs of a kind that need TEXT_MIN."""
    return [(t, g) for t in TEXT_ROLES for g in GROUNDS] + list(TEXT_ON)


def mark_pairs(kind):
    """The (mark role, ground role) pairs of a kind that need MARK_MIN."""
    mark, grounds = MARKS.get(kind, MARKS["console"])
    return [(m, g) for m in ("accent", "warn") for g in GROUNDS] + [(mark, g) for g in grounds]


def is_colour(v):
    """Whether a value is a colour as #rrggbb."""
    v = str(v)
    return len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def rgb(colour):
    """#rrggbb as (r, g, b), each 0 to 255."""
    c = str(colour).lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def hexc(r, g, b):
    """(r, g, b) as #rrggbb, each rounded half up and kept within 0 to 255."""
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v + 0.5))) for v in (r, g, b))


def mix(a, b, t):
    """The colour the part t of the way from a to b."""
    ra, rb = rgb(a), rgb(b)
    return hexc(*(x + (y - x) * t for x, y in zip(ra, rb)))


def dark(a, f):
    """a with each of its channels times f."""
    return hexc(*(x * f for x in rgb(a)))


def luminance(colour):
    """The relative luminance of a colour, as WCAG 2 reckons it."""
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(colour)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    """The contrast ratio of two colours, 1 to 21, as WCAG 2 reckons it."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def is_dark(colour):
    """Whether a background is dark enough to want light text and a dark caption."""
    return luminance(colour) < 0.18


def _sources(kind, role):
    """The keys of the ten that a role's rule reads, through other roles."""
    rule = RULES[kind][role]
    if isinstance(rule, str):
        return {rule} if rule in THEME_KEYS else set()
    if rule[0] == "role":
        return _sources(kind, rule[1])
    return {x for x in rule[1:3] if isinstance(x, str) and x in THEME_KEYS}


def _reads(kind, role):
    """The roles a role's rule takes its colour from, as ("role", r), at any
    depth."""
    rule = RULES[kind][role]
    if isinstance(rule, tuple) and rule[0] == "role":
        return {rule[1]} | _reads(kind, rule[1])
    return set()


def derive(legacy, kind="console", given=None):
    """Every role of a kind from a theme's ten colours, by RULES, apart from
    the roles given, a themes.json entry's own, which stay as given and which
    the roles that take their colour from them follow. A kind without rules of
    its own, classic, takes console's for a dark theme and folio's for a light
    one."""
    if kind not in RULES:
        kind = "console" if is_dark(legacy.get("bg", "#000000")) else "folio"
    rules = RULES[kind]
    out = {r: str(v).lower() for r, v in (given or {}).items() if r in rules}

    def colour(x):
        return legacy[x] if x in THEME_KEYS else x

    def get(role):
        if role in out:
            return out[role]
        rule = rules[role]
        if isinstance(rule, str):
            v = legacy[rule]
        elif rule[0] == "mix":
            v = mix(colour(rule[1]), colour(rule[2]), rule[3])
        elif rule[0] == "dark":
            v = dark(colour(rule[1]), rule[2])
        else:
            v = get(rule[1])
        out[role] = str(v).lower()
        return out[role]

    for role in ROLES:
        get(role)
    return out


def same(a, b):
    """Whether two colours are the same, whatever the case of their letters."""
    return str(a).strip().lower() == str(b).strip().lower()


def legacy(kind, name, given):
    """The ten colours a look of this kind hands the rest of the lens, for the
    theme name whose colours, with the user's themes.json laid over them, are
    given. classic keeps them as given, the very same object, so the lens
    draws exactly as it did. In a drawn kind a theme starts from the built-in
    theme base_of names, which neural_lens also fills the colours a
    themes.json entry leaves out from. Where that theme is drawn in this kind,
    the theme takes that theme's ten of the drawn looks, OWN_TEN, apart from
    each colour that is not the built-in theme's own, which the user's
    themes.json gave and which it keeps. So an entry for Paper that gives only
    its accent is Paper's drawn colours with that accent. Otherwise, such as
    Paper's colours laid out as Industrial's, the theme keeps its colours."""
    if kind not in DRAWN:
        return given
    base = base_of(name, given)
    given = {k: str(v).lower() for k, v in dict(given).items() if k in THEME_KEYS}
    if THEME_KIND.get(base) == kind:
        out = dict(OWN_TEN[base])
        for k in THEME_KEYS:
            if k in given and not same(given[k], CLASSIC[base][k]):
                out[k] = given[k]
        return out
    out = dict(LEGACY.get(kind, LEGACY["console"]))
    out.update(given)
    return out


def given_roles(given):
    """The colours a themes.json entry gives the roles of the drawn looks
    itself, by the roles' names in ROLES that are not among the ten, each a
    colour #rrggbb, in lower case."""
    return {k: str(v).lower() for k, v in dict(given or {}).items()
            if k in ROLES and k not in THEME_KEYS and is_colour(v)}


def roles(kind, name, ten, given=None):
    """Every role of a look of this kind, for the theme name with the ten
    colours legacy gave and its themes.json entry given, if any. A role the
    entry gives is its own, see given_roles. Every other role whose colours,
    through its rule, are all the kind's own ten takes the drawn role, so a
    built-in theme with nothing of the user's draws exactly as its drawings
    do, and the rest are derived from the ten, see derive. None of Graphite's
    ten is console's, so its roles are all derived."""
    mine = given_roles(given)
    derived = derive(ten, kind, mine)
    if kind not in DRAWN:
        return derived
    own = LEGACY[kind]
    out = {}
    for role in ROLES:
        changed = (role in mine or any(r in mine for r in _reads(kind, role))
                   or any(not same(ten[k], own[k]) for k in _sources(kind, role)))
        out[role] = derived[role] if changed else DRAWN_ROLES[kind][role]
    return out


def weak_text(c, kind):
    """The text pairs of a set of roles under TEXT_MIN, as (text, ground, ratio)."""
    return [(t, g, contrast(c[t], c[g])) for t, g in text_pairs(kind) if contrast(c[t], c[g]) < TEXT_MIN]


def weak_marks(c, kind):
    """The mark pairs of a set of roles under MARK_MIN, as (mark, ground, ratio)."""
    return [(m, g, contrast(c[m], c[g])) for m, g in mark_pairs(kind) if contrast(c[m], c[g]) < MARK_MIN]


def lighter_dim(ten, kind):
    """A theme's ten colours with dim, its muted text, moved toward its text
    colour by the least part, in hundredths, at which the roles derived from
    them draw every text at TEXT_MIN and every mark at MARK_MIN on its ground,
    the faint marks following dim, or the ten as given where no part does."""
    for i in range(101):
        out = dict(ten, dim=mix(ten["dim"], ten["fg"], i / 100.0))
        c = derive(out, kind)
        if not weak_text(c, kind) and not weak_marks(c, kind):
            return out
    return dict(ten)


# The ten colours each built-in theme has in the drawn looks. Slate, Paper and
# Industrial take their drawings' own, see LEGACY. Graphite has no drawing, so
# it keeps its own colours in console's layout, all but dim, its muted text,
# which is made lighter as Slate's and Industrial's were for their drawings, by
# lighter_dim. That gives #989898 for #8a8a8a, its muted text 4.71:1 on its lit
# band and chosen rail item where it was 3.93:1, and the faint pips and rings
# that follow from it 3.04:1 on its surface where they were 2.66:1.
OWN_TEN = {"Slate": dict(LEGACY["console"]), "Graphite": lighter_dim(CLASSIC["Graphite"], THEME_KIND["Graphite"]),
           "Paper": dict(LEGACY["folio"]), "Industrial": dict(LEGACY["industrial"])}


# ---- type

# Each face's chain of families, the first present on the machine winning,
# each family named as its files name their typographic family. The fonts
# are resolved once a root is bound, see lens_look.fonts. Folio's 30 pixel
# page title takes Source Serif 4's Subhead cut, made for 32 pixels, the cut
# nearest the optical size the drawings' browser draws that title in, since
# Tk cannot choose an optical size.
FAMILIES = {
    "bahnschrift": ("Bahnschrift", "Barlow Semi Condensed", "Segoe UI"),
    "serif": ("Source Serif 4", "Georgia"),
    "subhead": ("Source Serif 4 Subhead", "Source Serif 4", "Georgia"),
    "sans": ("Source Sans 3", "Segoe UI"),
    "barlow": ("Barlow", "Bahnschrift", "Segoe UI"),
    "bsc": ("Barlow Semi Condensed", "Bahnschrift SemiCondensed", "Segoe UI"),
    "mono": ("IBM Plex Mono", "Cascadia Mono", "Consolas"),
}

# A role's type: its family chain in FAMILIES, its size in CSS pixels, its
# weight, its case (upper, lower or None for as written) and the weight it
# takes lit or chosen, None where that is the same.
Face = collections.namedtuple("Face", "family size weight case lit")


def _f(family, size, weight=400, case=None, lit=None):
    return Face(family, size, weight, case, lit)


# The roles of the type, the same names in every kind, each named for where it
# is used.
#   title           Settings' page title
#   rail            a page's name on Settings' rail or tab band
#   heading         a heading of a page, or the head of an industrial module
#   row, line       a setting's label on its row, and a line of text on a page
#   control, tile   the words on a segment or a switch, and on a card or a tile
#   value           a number or a value that a control shows
#   beside          the words beside a setting
#   explain_title, explain_section, explain_text, explain_option, explain_option_text
#                   the explanation's title, its section line on industrial's
#                   strip, its text, and an option's name and its text
#   cap             a key cap in Settings' footer or key strip
#   cap_button      a key cap on a button, in Settings, a dialog or the
#                   fullscreen note
#   cap_panel       a key cap in the NR panel's key footer
#   cap_menu        a key cap beside a menu entry or the panel's NR switch, or
#                   in the pick hint and the region sheet
#   cap_note        a key cap that starts a line of the fullscreen note, or one
#                   inside a sentence
#   hints           the words beside a footer's key caps
#   button          a button's words, Save's in the lit weight
#   version         the version in Settings
#   page_button     the words of a button on a page of Settings, such as Browse
#   facts_title, facts_name, facts_value
#                   what a profile holds on the Profiles page, its two headings,
#                   and each name and value
#   panel_title, panel_row, panel_words, panel_profile
#                   the panel's title, its rows' labels, the words beside them
#                   and the profile's name
#   menu, menu_hint, menu_profile
#                   a menu entry, the hint after it, and a profile's name in a
#                   list
#   bar_title, bar_readout, bar_picker
#                   the title bar's title, its readout and its pickers
#   note, notice, readout
#                   the fullscreen note, a notice and the readout
#   dialog_head, dialog_text, dialog_detail
#                   a dialog's head, its text and its detail
FONT_ROLES = ("title", "rail", "heading", "row", "line", "control", "tile", "value", "beside", "explain_title",
              "explain_section", "explain_text", "explain_option", "explain_option_text", "cap", "cap_button",
              "cap_panel", "cap_menu", "cap_note", "hints", "button", "version", "page_button", "facts_title",
              "facts_name", "facts_value", "panel_title", "panel_row",
              "panel_words", "panel_profile", "menu", "menu_hint", "menu_profile", "bar_title", "bar_readout",
              "bar_picker", "note", "notice", "readout", "dialog_head", "dialog_text", "dialog_detail")

# The type of every role, as the drawings set it. None is a role the kind does
# not draw, such as industrial's page title, whose tab band names the page.
# Industrial draws no key cap on a button, so its cap_button is its cap.
FONTS = {
    "console": {
        "title": _f("bahnschrift", 30, 600), "rail": _f("bahnschrift", 17, 500, lit=600),
        "heading": _f("bahnschrift", 12.5, 600, "upper"), "row": _f("bahnschrift", 16, lit=600),
        "line": _f("bahnschrift", 15), "control": _f("bahnschrift", 15, 500, lit=600),
        "tile": _f("bahnschrift", 15, 500, lit=600), "value": _f("bahnschrift", 15, lit=600),
        "beside": _f("bahnschrift", 13), "explain_title": _f("bahnschrift", 22, 600), "explain_section": None,
        "explain_text": _f("bahnschrift", 15), "explain_option": _f("bahnschrift", 15, 600),
        "explain_option_text": _f("bahnschrift", 14.5), "cap": _f("bahnschrift", 12, 600),
        "cap_button": _f("bahnschrift", 12, 600), "cap_panel": _f("bahnschrift", 11.5, 600),
        "cap_menu": _f("bahnschrift", 11.5, 600), "cap_note": _f("bahnschrift", 12.5, 600),
        "hints": _f("bahnschrift", 14),
        "button": _f("bahnschrift", 15, 500, lit=600), "version": _f("bahnschrift", 13),
        "page_button": _f("bahnschrift", 14, 500), "facts_title": _f("bahnschrift", 15, 600),
        "facts_name": _f("bahnschrift", 13), "facts_value": _f("bahnschrift", 13),
        "panel_title": _f("bahnschrift", 16, 600), "panel_row": _f("bahnschrift", 15, lit=600),
        "panel_words": _f("bahnschrift", 13), "panel_profile": _f("bahnschrift", 15, 600),
        "menu": _f("bahnschrift", 15, lit=600), "menu_hint": _f("bahnschrift", 13),
        "menu_profile": _f("bahnschrift", 15, lit=600), "bar_title": _f("bahnschrift", 15, 600),
        "bar_readout": _f("bahnschrift", 14), "bar_picker": _f("bahnschrift", 15, 600),
        "note": _f("bahnschrift", 15), "notice": _f("bahnschrift", 15), "readout": _f("bahnschrift", 15, 500),
        "dialog_head": _f("bahnschrift", 22, 600), "dialog_text": _f("bahnschrift", 15),
        "dialog_detail": _f("bahnschrift", 14.5),
    },
    "folio": {
        "title": _f("subhead", 30, 600), "rail": _f("serif", 16, lit=600), "heading": _f("serif", 18, 600),
        "row": _f("sans", 15.5, lit=600), "line": _f("sans", 14.5), "control": _f("sans", 14, lit=600),
        "tile": _f("sans", 14, lit=600), "value": _f("sans", 14, 600), "beside": _f("sans", 13),
        "explain_title": _f("serif", 19, 600), "explain_section": None, "explain_text": _f("serif", 15),
        "explain_option": _f("sans", 13.5, 600), "explain_option_text": _f("serif", 14.5),
        "cap": _f("sans", 11.5, 600), "cap_button": _f("sans", 11, 600), "cap_panel": _f("sans", 11.5, 600),
        "cap_menu": _f("sans", 11.5, 600), "cap_note": _f("sans", 11.5, 600), "hints": _f("sans", 13, case="lower"),
        "button": _f("sans", 15, 500, lit=600), "version": _f("sans", 12.5), "page_button": _f("sans", 13.5),
        "facts_title": _f("serif", 15, 600), "facts_name": _f("sans", 13), "facts_value": _f("sans", 13),
        "panel_title": _f("serif", 18, 600),
        "panel_row": _f("sans", 14.5, lit=600), "panel_words": _f("sans", 13), "panel_profile": _f("sans", 14.5),
        "menu": _f("sans", 14.5, lit=600), "menu_hint": _f("sans", 13), "menu_profile": _f("sans", 14.5, lit=600),
        "bar_title": _f("serif", 16, 600), "bar_readout": _f("sans", 13), "bar_picker": _f("sans", 14.5),
        "note": _f("serif", 15), "notice": _f("serif", 15), "readout": _f("sans", 14.5),
        "dialog_head": _f("serif", 18, 600), "dialog_text": _f("serif", 15), "dialog_detail": _f("sans", 14),
    },
    "industrial": {
        "title": None, "rail": _f("bsc", 13.5, 600, "upper"), "heading": _f("bsc", 13.5, 600, "upper"),
        "row": _f("barlow", 15.5, 500), "line": _f("barlow", 15), "control": _f("mono", 12, 500, lit=600),
        "tile": _f("barlow", 15.5, 500), "value": _f("mono", 13.5, 500), "beside": _f("barlow", 13),
        "explain_title": _f("bsc", 22, 600), "explain_section": _f("mono", 11.5, 500, "upper"),
        "explain_text": _f("barlow", 16), "explain_option": _f("bsc", 22, 600),
        "explain_option_text": _f("barlow", 16), "cap": _f("mono", 11.5, 500), "cap_button": _f("mono", 11.5, 500),
        "cap_panel": _f("mono", 11.5, 500), "cap_menu": _f("mono", 12, 500), "cap_note": _f("mono", 12, 500),
        "hints": _f("barlow", 13.5, 500), "button": _f("bsc", 14, 600, "upper"), "version": _f("mono", 12),
        "page_button": _f("bsc", 13, 600, "upper"), "facts_title": _f("bsc", 13.5, 600, "upper"),
        "facts_name": _f("barlow", 13.5, 500), "facts_value": _f("mono", 13, 500),
        "panel_title": _f("bsc", 14, 600, "upper"), "panel_row": _f("barlow", 15, 500),
        "panel_words": _f("barlow", 13),
        "panel_profile": _f("mono", 13.5, 600), "menu": _f("barlow", 15, 500), "menu_hint": _f("barlow", 13),
        "menu_profile": _f("mono", 13.5, 500), "bar_title": _f("bsc", 13, 600, "upper"), "bar_readout": _f("mono", 12),
        "bar_picker": _f("mono", 13.5), "note": _f("barlow", 16), "notice": _f("barlow", 16),
        "readout": _f("mono", 13.5, 500), "dialog_head": _f("bsc", 18, 600), "dialog_text": _f("barlow", 16),
        "dialog_detail": _f("mono", 13.5),
    },
}
# The roles a kind leaves out.
NO_FONT = {"console": ("explain_section",), "folio": ("explain_section",), "industrial": ("title",)}

# ---- sizes

# CSS pixels at 100 percent, from the drawings.
# settings is the client area of Settings, the drawing less its drawn title
# strip. The panel_ sizes model the panel's height for lens_look.fit, the
# rows being what is left of the drawn height after the head, the line under
# it, the explanation and the key footer. The sizes from title_line, rail_top
# or tab_pad on are those of Settings' frame, see lens_look.settings and
# fit.settings_parts, each from the Settings drawing of its kind. view_bottom
# is the room under the last row of a page that scrolls, which folio's and
# industrial's drawings do not draw, so folio takes its rail's room at the
# foot and industrial the gap between its modules. words_gap is the room
# between a footer's last key cap and its words, the drawings' gap and the
# words' own margin together.
METRICS = {
    "console": {
        "settings": (1120, 736), "rail_w": 216, "rail_pad": (18, 12), "rail_item_h": 44, "rail_gap": 2,
        "main_pad": (24, 30, 16), "heading_above": 22, "heading_below": 6, "section_gap": 22, "title": 30,
        "row_h": 44, "row_pad": (0, 8, 0, 18), "bar_w": 3, "bar_inset": 10, "well_pad": 3, "segment_h": 30,
        "segment_min_w": 52, "card_h": 44, "card_gap": 8, "carousel": (200, 36), "carousel_arrow": 34,
        "pip": (12, 2), "explain_w": 320, "explain_narrow_w": 260, "pane_pad": (28, 26, 22), "footer_h": 64,
        "button_h": 40, "cap_h": 24,
        "title_line": 36, "rail_item_pad": (16, 12), "chevron": 12, "version_in": 16, "footer_pad": (24, 18),
        "hint_gap": 22, "cap_gap": 4, "words_gap": 10, "button_gap": 10,
        "panel": (624, 830), "panel_head": 41, "panel_intro": 0, "panel_profile": 52, "panel_explain": 112,
        "panel_footer": 42, "panel_strength": 80, "panel_row_h": (38, 52),
        "panel_carousel": (184, 34), "panel_segment": (46, 28), "panel_tab_h": 40, "panel_tab_line": 2,
        "tie_col": 104, "slider": (172, 20), "slider_track": 6, "thumb": 16, "thumb_ring": 3, "number_w": 44,
        "reset": (28, 28), "tie_box": (20, 20),
        "menu_entry_h": 34, "menu_pad": (0, 12, 0, 16), "menu_head_pad": (9, 16, 9, 22), "menu_min_w": 520,
        "divider_handle": (24, 48),
    },
    "folio": {
        "settings": (1120, 744), "rail_w": 200, "rail_item_h": 38, "rail_text_inset": 25, "main_w": 600,
        "main_pad": (0, 24, 0, 32), "title_top": 28, "title_row_h": 40, "title": 30, "section_head_h": 30,
        "section_gap": 22, "row_h": 44, "row_tall_h": (64, 66), "label_w": 250, "explain_w": 320,
        "explain_narrow_w": 240, "note_pad": 14, "note_rule": 2, "footer_h": 60, "button_h": 36, "cap": (22, 20),
        "cap_bottom": 2, "switch": (38, 20), "knob": 13, "segment_h": 32, "panel_segment_h": 28, "ruler_w": 210,
        "ruler_line": 2, "ruler_marker": (6, 18), "ruler_ticks": (3, 6), "corner_screen": (72, 44),
        "corner_chosen": (20, 5), "corner_other": (14, 5),
        "rail_top": 26, "rail_bottom": 22, "rail_gap": 2, "rail_bar": 3, "version_in": 28, "view_bottom": 22,
        "footer_pad": (28, 24), "hint_gap": 24, "cap_gap": 4, "words_gap": 9, "button_gap": 10,
        "panel": (664, 844), "panel_head": 42, "panel_intro": 32, "panel_profile": 62, "panel_explain": 117,
        "panel_footer": 40, "panel_strength": 80, "panel_dropdown": (152, 30),
        "panel_label_w": 212, "panel_tab_h": 40, "tie_col": 64,
        "menu_w": 410, "menu_entry_h": 32,
    },
    "industrial": {
        "settings": (1120, 746), "tab_band_h": 44, "tab_band_pad": (0, 16), "tab_gap": 3, "tab_h": 36,
        "tab_chosen_h": 41, "page_pad": (26, 24, 0), "column_gap": 20, "one_column_below": 760,
        "module_head_h": 34, "section_gap": 20, "row_h": 56, "row_pad": (0, 16, 0, 13), "info": (24, 24),
        "switch": (104, 30), "switch_part": 52, "tile_h": 72, "tile_list_h": 56, "lamp": (10, 10),
        "corner_screen": (92, 54), "button_h": 34, "button_min_w": 100, "cap_h": 22, "strip_h": 148,
        "strip_col": 290, "strip_gap": 36, "key_strip_h": 52,
        "tab_pad": 10, "tab_top": (2, 3), "view_bottom": 20, "strip_bar": 3, "footer_pad": (27, 14),
        "hint_gap": 26, "cap_gap": 3, "words_gap": 8, "button_gap": 8, "version_gap": 16,
        "panel": (680, 868), "panel_border": 1, "panel_head": 40, "panel_intro": 0, "panel_profile": 50,
        "panel_explain": 136, "panel_footer": 40, "panel_strength": 80,
        "panel_label_w": 136, "panel_dropdown": (196, 34), "panel_switch": (100, 28), "panel_tab": (100, 32),
        "panel_tab_chosen": (100, 37), "slider": (255, 28), "slider_track": 8, "slider_fill": 6,
        "slider_ticks": (0, 25, 50, 75, 100), "thumb": (10, 18), "tie_col": 108, "ladder_block": (34, 16),
        "ladder_gap": 5,
        "menu_entry_h": 30, "menu_hint_x": 226,
    },
}
# Rows and gaps shrink to about this much in the compact sizes, see COMPACT.
COMPACT_RATIO = 0.82
# The sizes that change in the compact layout, which Settings and the panel
# take where the drawn sizes do not fit the screen, see lens_look.fit.
COMPACT = {
    "console": {"row_h": 36, "title": 24, "section_gap": 14, "footer_h": 52},
    "folio": {"row_h": 36, "title": 24, "section_gap": 14},
    "industrial": {"row_h": 46, "section_gap": 14, "strip_h": 112},
}

# ---- how each kind lays out and words its windows

# nav says how Settings turns its pages, by a rail or by tabs. explain says
# where a setting's explanation shows, in a pane, a margin note, a strip or
# the popup that comes up on the pointer's rest. dark_caption says whether a
# window's own caption is drawn dark, None going by the theme's background,
# which every kind does, so a theme of the user's own, light or dark, gets the
# caption that goes with its background. The built-in themes come out as
# drawn, dark for Slate, Graphite and Industrial and light for Paper. The cases are
# those of words the look draws, upper, lower or None for as written.
# menu_hints says how a menu entry's keys and hint are drawn, as caps, in
# brackets as the text has them, or as the text is.
FLAGS = {
    "classic": {"nav": "tabs", "explain": "popup", "dark_caption": None, "heading_case": None, "button_case": None,
                "hints_case": None, "menu_hints": "text"},
    "console": {"nav": "rail", "explain": "pane", "dark_caption": None, "heading_case": "upper", "button_case": None,
                "hints_case": None, "menu_hints": "caps"},
    "folio": {"nav": "rail", "explain": "margin", "dark_caption": None, "heading_case": None, "button_case": None,
              "hints_case": "lower", "menu_hints": "caps"},
    "industrial": {"nav": "tabs", "explain": "strip", "dark_caption": None, "heading_case": "upper",
                   "button_case": "upper", "hints_case": None, "menu_hints": "brackets"},
}

# The colours a window's own frame is drawn in, by role, the caption, its
# title and the window's border, as the dialog drawings draw their title
# strips. Console's title is its body text and the other two draw theirs in
# the muted colour. Slate's and Industrial's dialogs have a border in their
# edge colour. Paper's have none, so its frame's border takes the rule its
# title strip ends in. classic takes console's roles in its own derived
# colours, see lens_look.win.caption.
CAPTION = {"classic": ("deep", "text", "edge"), "console": ("deep", "text", "edge"),
           "folio": ("deep", "muted", "rule"), "industrial": ("deep", "muted", "edge")}

# The role each of the ten colours stands for when the code sets it on a
# widget of a drawn look that keeps the colour it was given and draws the
# look's own. A widget can have a table of its own for a state the drawings
# colour otherwise.
LOGICAL = {"bg": "surface", "fg": "text", "accent": "accent", "dim": "muted", "warn": "warn", "cap": "head",
           "hover": "lit", "field": "well", "tab": "tab", "close": "close"}
