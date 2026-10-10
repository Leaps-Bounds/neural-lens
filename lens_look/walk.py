"""The order the NR settings panel's rows stand in, top to bottom, in each
look, which is also the order the arrow keys walk them in.

classic is the panel as it always was, whose own code in neural_lens.py
keeps building its walk, and the table here only matches it. Each drawn look
has the order of its drawing. Scale the change and Strength, which no drawing
has, follow Passes in every look.

Pure.
"""
# The panel's sliders, NR_SLIDERS' keys in neural_lens.py, in their order.
SLIDERS = ("NRIntensity", "NRLocalTone", "NRLocalStructure", "NRSkinStructure")

# The rows top to bottom by name, see _rows for what each name brings.
ORDER = {
    "classic": ("profile", "auto", "free", "nr", "tabs", "style", "sliders", "skin_auto", "mask", "shared", "passes",
                "scale_change", "strength", "quality"),
    "console": ("profile", "auto", "free", "nr", "quality", "passes", "scale_change", "strength", "tabs", "shared",
                "style", "sliders", "skin_auto", "mask"),
    "folio": ("profile", "auto", "free", "nr", "passes", "scale_change", "strength", "quality", "tabs", "shared",
              "style", "sliders", "skin_auto", "mask"),
    "industrial": ("profile", "auto", "free", "nr", "tabs", "shared", "style", "sliders", "skin_auto", "mask",
                   "passes", "scale_change", "strength", "quality"),
}


def _rows(name, n, scale, sliders):
    """The walk's entries a row of this name brings on the tab of pass n, each
    (kind, what, the panel_ui key of the label that lights), the key being a
    pair for a tie's box, ("tie_box", the pass's key). A tie follows the value
    it ties, from the second pass on."""
    tie = n >= 2
    if name == "profile":
        return [("profile", "profile", "profile_word")]
    if name == "auto":
        return [("switch", "auto", "auto_box")]
    if name == "free":
        return [("switch", "free", "free_box")]
    if name == "nr":
        return [("switch", "nr", "nr_box")]
    if name == "tabs":
        return [("tabs", "pass", "tabs_word")]
    if name == "style":
        return [("choice", "style", "style_word")] + ([("tie", "NRStyle", ("tie_box", "NRStyle"))] if tie else [])
    if name == "sliders":
        out = []
        for key in sliders:
            out.append(("slider", key, key + " word"))
            if tie:
                out.append(("tie", key, ("tie_box", key)))
        return out
    if name == "skin_auto":
        return [("switch", "skin_auto", "skin_box")]
    if name == "mask":
        return [("switch", "mask", "mask_box")] + ([("tie", "NRAutoMask", ("tie_box", "NRAutoMask"))] if tie else [])
    if name == "shared":
        # the switch that runs the pass through pass 1's network, on the tabs of
        # passes 2 to 4
        return [("switch", "shared", "shared_box")] if tie else []
    if name == "passes":
        return [("passes", "passes", "passes_word")]
    if name == "scale_change":
        return [("switch", "scale_change", "scale_box")]
    if name == "strength":
        # the strength's slider, while the switch above has it show
        return [("strength", "strength", "strength_word")] if scale else []
    if name == "quality":
        return [("quality", "quality", "quality_word")]
    raise KeyError(name)


def panel_walk(look, n, scale, sliders=SLIDERS):
    """The panel's rows on the tab of pass n, top to bottom, in the look's
    order, as [(kind, what, panel_ui key)], with the ties after their values,
    the switch of pass 1's network on the tabs of passes 2 to 4 and the
    strength while scale, the switch Scale the change, is on. look is a Look
    or a kind's name."""
    kind = getattr(look, "kind", look)
    out = []
    for name in ORDER.get(kind, ORDER["console"]):
        out += _rows(name, int(n), bool(scale), sliders)
    return out


def lit_widget(ui, key):
    """The panel_ui entry a walk's key names, the pair of a tie's box included."""
    return ui[key[0]][key[1]] if isinstance(key, tuple) else ui[key]


def follow_on(was, before, now):
    """The row the arrow keys stay on when the row they were on, was, goes
    from the walk, as the switch of pass 1's network goes with the tab of
    pass 1. That is the first of the rows after it in the walk before that
    is still there, else the last one before it that is, else None. Rows are
    (kind, what) pairs, before and now the walk before and after."""
    before, now = list(before), list(now)
    if was in now:
        return was
    at = before.index(was) if was in before else len(before)
    for row in before[at + 1:]:
        if row in now:
            return row
    for row in reversed(before[:at]):
        if row in now:
            return row
    return None
