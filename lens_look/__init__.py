"""The looks of the lens: the layout, colours, type and sizes its windows are
drawn in, chosen once as the lens starts.

neural_lens.LOOK is the Look the lens draws in, which choose makes from the
theme. The drawn looks draw the layouts of the design canvas over the lens's
controls, which keep their words, settings and keys. classic is the lens as it
looked up to 0.7.0, its code the lens's own, which the tests can still ask for
and which the lens falls back to where this package cannot be loaded or its
look chosen.

The modules this file imports, tokens, scale, text, fit and walk, import
neither tkinter nor the lens. dialogs, fonts, settings and win, which use
tkinter or ctypes, are imported by the lens itself, and settings imports the
widgets it draws with.
"""
from lens_look import fit, scale, text, tokens, walk

# The look is the one the theme names, its drawn layout. NEURAL_LENS_LOOK, or
# the ini's look key, can say classic instead, the lens as it looked up to
# 0.7.0, which the tests use and no setting offers.
DEFAULT = "themed"
CHOICES = ("classic", "themed")


class Look(object):
    """A look, and what its windows are drawn with.

    kind        classic, console, folio or industrial
    classic     True for classic, whose code paths are the lens's own
    theme       the theme's name
    legacy      the theme's ten colours by THEME_KEYS, which every part of the
                lens the look does not draw itself takes, BG to CLOSE
    c           the colours by role, see tokens.ROLES
    own         the drawing's own names for its colours, for one kind's faces
    fonts       the type by role, see tokens.FONT_ROLES, empty for classic,
                whose fonts stay in the code
    faces       the face each family chain and weight of fonts found on this
                machine, see lens_look.fonts.resolve_look, found at the first
                bind and empty until then and for classic
    m           sizes in CSS pixels at 100 percent, and compact the smaller
                ones, see tokens.METRICS and tokens.COMPACT
    nav, explain, dark_caption, heading_case, button_case, hints_case,
    menu_hints  how the kind lays out Settings, explains a setting, tints a
                window's caption and writes its own words, see tokens.FLAGS
    logical     the role each of the ten colours stands for, see tokens.LOGICAL
    s           screen pixels to a CSS pixel, once bound to a root
    """

    def __init__(self, kind, theme, legacy, c=None, own=None, fonts=None, m=None, compact=None):
        self.kind = kind
        self.classic = kind == "classic"
        self.theme = theme
        self.legacy = legacy
        self.c = c if c is not None else {}
        self.own = own if own is not None else {}
        self.fonts = fonts if fonts is not None else {}
        self.m = m if m is not None else {}
        self.compact = compact if compact is not None else {}
        flags = tokens.FLAGS[kind]
        for name, value in flags.items():
            setattr(self, name, value)
        if self.dark_caption is None:
            self.dark_caption = tokens.is_dark(legacy["bg"])
        self.logical = dict(tokens.LOGICAL)
        self.s = None
        self.faces = {}
        self._looked = False            # whether the faces were looked for, which is done once

    def __repr__(self):
        return "Look(%s, %s)" % (self.kind, self.theme)

    def bind(self, root):
        """Take the scale from a root as it is made, once Tk's scaling is set,
        and the first time the faces of the look's type on this machine, see
        _find_faces. Tk keeps one scaling for the process, so the first root's
        holds for every window. Never raises, so the lens's start and its
        last message go on whatever happens here. A scale that cannot be read
        leaves the look unbound, and scale_for then asks a widget."""
        if self.s is None:
            try:
                self.s = scale.scale_of(root)
            except Exception:
                pass
        if self.fonts and not self._looked:
            self._find_faces(root)
        return self.s

    def _find_faces(self, widget):
        """The faces of the look's roles, from the families Tk lists in the
        widget's interpreter and the fonts lens_look.fonts.load_private
        added, looked for once, and one line in the log that names them. A
        fault leaves faces empty, so each role takes the first font of its
        chain that the lens added or that every Windows has, see _face, and
        the log says so instead."""
        self._looked = True
        try:
            from lens_look import fonts
            present = widget.tk.splitlist(widget.tk.call("font", "families"))
            self.faces = fonts.resolve_look(self.fonts, present)
            line = fonts.said(self.theme, self.fonts, self.faces)
        except Exception as e:
            self.faces = {}
            line = ('the fonts of the %s look could not be looked for ("%s"), so each role takes the first font '
                    'of its chain that the lens added or that every Windows has'
                    % (self.theme, str(e) or type(e).__name__))
        try:
            print(line, flush=True)
        except Exception:
            pass                        # an output that cannot take the words must not stop the lens

    def font(self, role, lit=False, widget=None):
        """A role's Tk font as (family, size, weight), the size in pixels at
        the look's scale and the family the face the role found on this
        machine, see scale.font and _face. The faces are found at the first
        bind, or else here from the widget's interpreter, as the scale is.
        lit takes the weight the role has lit or chosen. A role the look does
        not draw raises KeyError."""
        face = self.fonts.get(role)
        if face is None:
            raise KeyError(role)
        if not self._looked and widget is not None:
            self._find_faces(widget)
        family, weight = self._face(face.family, face.lit if lit and face.lit else face.weight)
        return scale.font(face, self.scale_for(widget), family, lit, weight)

    def face_font(self, face, lit=False, widget=None):
        """The Tk font of a face that no role names, a tokens.Face, as font
        gives a role's, such as the mono type of the stack setup's log in a
        look whose roles have no mono, see lens_look.dialogs.MONO."""
        if not self._looked and widget is not None and self.fonts:
            self._find_faces(widget)
        family, weight = self._face(face.family, face.lit if lit and face.lit else face.weight)
        return scale.font(face, self.scale_for(widget), family, lit, weight)

    def _face(self, chain, weight):
        """The family Tk is given for a chain of tokens.FAMILIES and a weight,
        and Tk's weight for it. That is the face found at the first bind, or
        where no families were read from Tk the first font of the chain that
        the lens added or that every Windows has, see lens_look.fonts.assumed,
        which is not kept, so a later bind still looks. Where even that fails
        it is the chain's last family, which every Windows has, bold from 600.
        So Tk is never given a family that no file and no Windows has."""
        got = self.faces.get((chain, weight))
        if got is None:
            try:
                from lens_look import fonts
                got = fonts.resolve(tokens.FAMILIES[chain], weight, fonts.assumed())
            except Exception:
                return tokens.FAMILIES[chain][-1], "bold" if weight >= 600 else "normal"
        return got.family, got.weight

    def scale_for(self, widget=None):
        """S, from the root the look was bound to, or else from the
        interpreter of the widget given, for a window built before any root
        was bound, or 1.0 with neither."""
        if self.s is not None:
            return self.s
        if widget is not None:
            return scale.scale_of(widget)
        return 1.0

    def px(self, n, widget=None):
        """n CSS pixels in screen pixels, see scale.px and scale_for."""
        return scale.px(n, self.scale_for(widget))

    def dress(self, window):
        """A window with a frame dressed in this look before it is first seen,
        kept out of the picture and its frame in the look's colours, see
        lens_look.win.dress. It is here for a window made outside the lens,
        the stack setup's, which imports nothing of the package and is handed
        the look. Only this call reaches lens_look.win, which uses ctypes."""
        from lens_look import win
        return win.dress(window, self)

    def setup_shell(self, window):
        """The stack setup's window laid out as this look's dialogs, see
        lens_look.dialogs.SetupShell, which the stack setup makes before the
        window's parts and finishes after them. It is here, as dress is, for
        the stack setup, which imports nothing of the package."""
        from lens_look import dialogs
        return dialogs.SetupShell(window, self)


def choose(theme_name, all_themes, ini=None, environ=None):
    """The Look for the theme of this name among all_themes, the built-in themes
    with the data folder's themes.json laid over them. NEURAL_LENS_LOOK in
    environ, else the ini's look key, says classic or themed, DEFAULT where
    neither says one of those. themed draws the kind tokens.theme_kind gives,
    the built-in theme's own, or for a theme of the user's own that of the
    built-in theme its look key names, console where it names none, in the
    colours of tokens.legacy and tokens.roles. classic keeps the theme's
    colours exactly as given."""
    ini = ini or {}
    environ = environ or {}
    want = str(environ.get("NEURAL_LENS_LOOK") or ini.get("look") or DEFAULT).strip().lower()
    if want not in CHOICES:
        want = DEFAULT
    themes = all_themes or {}
    name = theme_name if theme_name in themes else "Slate" if "Slate" in themes else None
    given = themes[name] if name is not None else dict(tokens.CLASSIC["Slate"])
    name = name or "Slate"
    if want == "classic":
        return Look("classic", name, given, c=tokens.derive(given, "classic"))
    kind = tokens.theme_kind(name, given)
    ten = tokens.legacy(kind, name, given)
    return Look(kind, name, ten, c=tokens.roles(kind, name, ten, given), own=dict(tokens.OWN[kind]),
                fonts=dict(tokens.FONTS[kind]), m=dict(tokens.METRICS[kind]), compact=dict(tokens.COMPACT[kind]))


def weak_line(look):
    """The line lens.log gets where a drawn look draws text under
    tokens.TEXT_MIN on a ground it draws that text on, which only colours of
    the user's own in themes.json can make, naming each pair of roles and its
    contrast, or None. The look still draws as chosen."""
    if look.classic:
        return None
    weak = tokens.weak_text(look.c, look.kind)
    if not weak:
        return None
    return ("the %s theme has text under a contrast of 4.5 in these pairs of its colours: %s"
            % (look.theme, ", ".join("%s on %s %.2f" % (t, g, r) for t, g, r in weak)))
