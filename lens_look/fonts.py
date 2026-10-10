"""The fonts the drawn looks are drawn in, which come with the lens in the
fonts folder of its assets, and the face each role of a look finds on this
machine.

load_private adds the files of that folder for this process alone, before Tk
makes any font. Nothing is installed, no administrator is asked, no other
program sees them, and they go when the process ends. Windows lists a static
weight other than regular and bold as a family of its own, such as Source
Sans 3 Semibold, and some files shorten that name, such as IBM Plex Mono
SmBld, so read_names reads the names from each file rather than guessing
them. resolve gives a face of a look, a chain of families of
tokens.FAMILIES and a weight, the first family of the chain this machine
has, in the weight it has nearest the one asked, as a browser chooses a
weight.

Imports collections, ctypes, os, struct and the package's tokens, and
neither tkinter nor the lens.
"""
import collections
import ctypes
import os
import struct

from lens_look import tokens

FR_PRIVATE = 0x10               # a font of this process alone, which goes when it ends
FACE_CHARS = 31                 # the longest family name Windows keeps, LF_FACESIZE less its null
SUFFIXES = (".ttf", ".otf")
ENGLISH = 0x409                 # US English, whose names Windows falls back on
SFNT = (b"\x00\x01\x00\x00", b"OTTO", b"true")

# What a font file is listed as, see read_names
Names = collections.namedtuple("Names", "family style typographic subfamily full weight bold italic")
# The face a chain of families and a weight resolve to. family and weight are
# what Tk is given, the weight normal or bold. chain is the family of the
# chain that won, got the weight it has that was taken and want the weight
# asked. found is False where nothing of the chain is on the machine, and Tk
# is then given the chain's last family and finds a face for it itself
Resolved = collections.namedtuple("Resolved", "family weight chain got want found")

# The faces of the families of the chains that come with Windows, by weight,
# each as the family name Windows lists it by and the weight Tk is given for
# it. Windows lists a weight other than regular and bold, such as
# Bahnschrift's semibold, as a family of its own, and cuts a name to
# FACE_CHARS characters, so the semibold of Bahnschrift SemiCondensed is
# listed as Bahnschrift SemiBold SemiConden. As this machine's list had them
# on 2026-10-07, Windows 11 build 26200.
SYSTEM = {
    "Bahnschrift": ((300, "Bahnschrift Light", "normal"), (350, "Bahnschrift SemiLight", "normal"),
                    (400, "Bahnschrift", "normal"), (600, "Bahnschrift SemiBold", "normal"),
                    (700, "Bahnschrift", "bold")),
    "Bahnschrift SemiCondensed": ((300, "Bahnschrift Light SemiCondensed", "normal"),
                                  (350, "Bahnschrift SemiLight SemiCondensed", "normal"),
                                  (400, "Bahnschrift SemiCondensed", "normal"),
                                  (600, "Bahnschrift SemiBold SemiCondensed", "normal"),
                                  (700, "Bahnschrift SemiCondensed", "bold")),
    "Segoe UI": ((300, "Segoe UI Light", "normal"), (350, "Segoe UI Semilight", "normal"),
                 (400, "Segoe UI", "normal"), (600, "Segoe UI Semibold", "normal"), (700, "Segoe UI", "bold"),
                 (900, "Segoe UI Black", "normal")),
    "Georgia": ((400, "Georgia", "normal"), (700, "Georgia", "bold")),
    "Cascadia Mono": ((200, "Cascadia Mono ExtraLight", "normal"), (300, "Cascadia Mono Light", "normal"),
                      (350, "Cascadia Mono SemiLight", "normal"), (400, "Cascadia Mono", "normal"),
                      (600, "Cascadia Mono SemiBold", "normal"), (700, "Cascadia Mono", "bold")),
    "Consolas": ((400, "Consolas", "normal"), (700, "Consolas", "bold")),
}
# The families of SYSTEM that every Windows the lens runs on has, 10 from
# build 19041 on and 11, see assumed. Cascadia Mono is not one of them, since
# Windows 10 has it only where a program brought it.
ALWAYS = ("Bahnschrift", "Bahnschrift SemiCondensed", "Segoe UI", "Georgia", "Consolas")

# What load_private added in this process, each file's path and its Names,
# which the faces of a look are resolved with. A file is added once, however
# often it is asked for
LOADED = collections.OrderedDict()
_gdi = []                       # gdi32 once it is first wanted, an instance of this module's own


def listed(name):
    """A family name as Windows lists it, cut to FACE_CHARS characters, and
    folded for a comparison that ignores case, as Windows matches a name."""
    return str(name)[:FACE_CHARS].casefold()


def names_of(data):
    """Names from the bytes of a font file, see read_names."""
    if len(data) < 12 or data[:4] not in SFNT:
        raise ValueError("it is not a font file the lens can read")
    tables = {}
    for i in range(struct.unpack_from(">H", data, 4)[0]):
        at = 12 + 16 * i
        if at + 16 > len(data):
            raise ValueError("its table directory is cut short")
        tag, _sum, off, length = struct.unpack_from(">4sIII", data, at)
        if off + length > len(data):
            raise ValueError("its %s table runs past its end" % tag.decode("latin-1").strip())
        tables[tag] = (off, length)
    if b"name" not in tables:
        raise ValueError("it has no name table")
    off, length = tables[b"name"]
    if length < 6:
        raise ValueError("its name table is cut short")
    count, strings = struct.unpack_from(">HH", data, off + 2)
    found = {}
    for i in range(count):
        at = off + 6 + 12 * i
        if at + 12 > off + length:
            raise ValueError("its name records are cut short")
        platform, encoding, language, nid, size, where = struct.unpack_from(">HHHHHH", data, at)
        if platform != 3 or encoding not in (0, 1, 10) or nid not in (1, 2, 4, 16, 17):
            continue
        start = off + strings + where
        if start + size > len(data):
            raise ValueError("its name %d runs past its end" % nid)
        text = data[start:start + size].decode("utf-16-be", "replace").strip()
        found.setdefault(nid, []).append((language != ENGLISH, language, text))

    def name(nid):
        got = sorted(found.get(nid, []))
        return got[0][2] if got and got[0][2] else None

    family = name(1)
    if not family:
        raise ValueError("it has no family name for Windows")
    style = name(2) or "Regular"
    weight, bold, italic = None, False, False
    if b"OS/2" in tables and tables[b"OS/2"][1] >= 64:
        o = tables[b"OS/2"][0]
        weight = struct.unpack_from(">H", data, o + 4)[0]
        selection = struct.unpack_from(">H", data, o + 62)[0]
        bold, italic = bool(selection & 0x20), bool(selection & 0x01)
    if b"head" in tables and tables[b"head"][1] >= 46:
        mac = struct.unpack_from(">H", data, tables[b"head"][0] + 44)[0]
        bold, italic = bold or bool(mac & 1), italic or bool(mac & 2)
    if not weight:
        weight = 700 if bold else 400
    return Names(family[:FACE_CHARS], style, name(16) or family, name(17) or style, name(4) or family, weight,
                 bold, italic)


def read_names(path):
    """What a font file is listed as, from its name table and its weight, as
    Names. family is name 1, the family Windows lists the file by, cut to
    FACE_CHARS as Windows cuts it, and style name 2. typographic and
    subfamily are names 16 and 17, the family the file belongs to whatever
    its weight and its weight's name, or names 1 and 2 where it has none,
    full is name 4. The names are those for Windows in US English, else the
    first for Windows the file has. weight is the OS/2 table's weight class,
    and bold and italic whether the file says it is bold or italic. Raises
    OSError where the file cannot be read and ValueError where it is not a
    font this can read."""
    with open(path, "rb") as f:
        return names_of(f.read())


def _add(path):
    """gdi32's AddFontResourceExW for one file, for this process alone, giving
    the number of fonts Windows added, 0 where it took none."""
    if not _gdi:
        dll = ctypes.WinDLL("gdi32", use_last_error=True)
        dll.AddFontResourceExW.restype = ctypes.c_int
        dll.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
        _gdi.append(dll)
    return _gdi[0].AddFontResourceExW(path, FR_PRIVATE, None)


class Load(object):
    """What load_private did, the files it added, those it did not and why,
    and the line the lens's log gets, see line."""

    def __init__(self, folder):
        self.folder = folder
        self.added = []             # (path, Names) of each file added
        self.failed = []            # (file name, why) of each file not added
        self.unread = None          # why the folder could not be read, "is not there" where it is not

    def line(self):
        """One line for the log, how many files were added and which were not."""
        total = len(self.added) + len(self.failed)
        if not total:
            return ("the fonts of the looks were not added, since %s %s, so each face takes the next font of "
                    "its chain" % (self.folder, self.unread or "holds none"))
        said = "the fonts of the looks, %d of %d files, were added for this process alone from %s" % (
            len(self.added), total, self.folder)
        if self.failed:
            said += ", and these were not: %s" % ", ".join("%s (%s)" % (n, why) for n, why in self.failed)
        return said


def load_private(folder, add=None):
    """Add every font file of folder for this process alone, see FR_PRIVATE,
    and keep each file's Names in LOADED, which resolve takes the faces from.
    A file that cannot be read as a font is not handed to Windows. add stands
    in for AddFontResourceExW, for the checks, taking a path and giving the
    number of fonts Windows added. Never raises for a file or for the folder,
    and returns a Load."""
    done = Load(folder)
    try:
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(SUFFIXES))
    except Exception as e:
        try:
            there = os.path.isdir(folder)
        except Exception:
            there = False
        done.unread = ("could not be read (%s)" % (str(e) or type(e).__name__)) if there else "is not there"
        return done
    for f in files:
        path = os.path.join(folder, f)
        try:
            names = read_names(path)
        except Exception as e:
            done.failed.append((f, str(e) or type(e).__name__))
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key not in LOADED:
            try:
                taken = (add or _add)(path)
            except Exception as e:
                done.failed.append((f, "Windows could not be asked for it, %s" % (str(e) or type(e).__name__)))
                continue
            if not taken:
                done.failed.append((f, "Windows did not take it"))
                continue
            LOADED[key] = names
        done.added.append((path, names))
    return done


def nearest(want, have):
    """The weight of have to draw want in, as CSS matches a weight. Asked 400
    to 500, the weights from want up to 500 going up, then those under want
    going down, then those over 500 going up. Asked under 400, those under
    want going down, then those over going up. Asked over 500, those over
    want going up, then those under going down. None where have is empty."""
    ws = sorted(have)
    if want in have or not ws:
        return want if want in have else None
    if 400 <= want <= 500:
        order = [w for w in ws if want < w <= 500] + [w for w in reversed(ws) if w < want] + [w for w in ws if w > 500]
    elif want < 400:
        order = [w for w in reversed(ws) if w < want] + [w for w in ws if w > want]
    else:
        order = [w for w in ws if w > want] + [w for w in reversed(ws) if w < want]
    return order[0]


def weights_of(family, present, loaded=None):
    """The faces this machine has of a family of a chain, as {weight: (family
    name as listed, Tk's weight)}. present is the families Tk lists, and
    loaded the Names of the files load_private added, LOADED's by default,
    whose faces count as present. A file's own names come first, then
    SYSTEM's names that present lists. A family present that neither
    describes has its regular and its bold, as Tk asks Windows for them."""
    shown = {listed(n): n for n in present}
    out = {}
    for n in (LOADED.values() if loaded is None else loaded):
        if not n.italic and listed(n.typographic) == listed(family):
            out.setdefault(n.weight, (n.family, "bold" if n.bold else "normal"))
    for weight, name, tk_weight in SYSTEM.get(family, ()):
        if listed(name) in shown and weight not in out:
            out[weight] = (shown[listed(name)], tk_weight)
    if not out and listed(family) in shown:
        out = {400: (shown[listed(family)], "normal"), 700: (shown[listed(family)], "bold")}
    return out


def resolve(chain, want, present, loaded=None):
    """The face for a chain of families and a weight asked, as Resolved. The
    first family of the chain that this machine has wins, in the weight it
    has nearest the one asked, see weights_of and nearest. Where it has none
    of the chain, Tk is given the chain's last family as it is, bold from 600
    up, and finds a face for it itself."""
    for family in chain:
        have = weights_of(family, present, loaded)
        if have:
            got = nearest(want, have)
            return Resolved(have[got][0], have[got][1], family, got, want, True)
    return Resolved(chain[-1], "bold" if want >= 600 else "normal", chain[-1], None, want, False)


def assumed():
    """The families Windows lists for the faces of ALWAYS, cut to FACE_CHARS
    as it cuts them, which a look gives resolve as present where it has read
    no families from Tk, see Look.font. The fonts load_private added count as
    there besides, so a role then takes the first font of its chain that the
    lens added or that every Windows has, and Tk is never given a family that
    neither has, such as Barlow Semi Condensed, whose files are listed as
    Barlow Semi Condensed Medium and Barlow Semi Condensed SemiBold."""
    return [name[:FACE_CHARS] for family in ALWAYS for _weight, name, _tk in SYSTEM[family]]


def resolve_look(fonts, present, loaded=None):
    """The faces of a look's roles, fonts being its tokens.Face by role, as
    {(chain, weight): Resolved} for every chain and weight a role takes,
    plain or lit."""
    out = {}
    for face in fonts.values():
        if face is None:
            continue
        for weight in (face.weight, face.lit):
            if weight and (face.family, weight) not in out:
                out[(face.family, weight)] = resolve(tokens.FAMILIES[face.family], weight, present, loaded)
    return out


def said(name, fonts, faces):
    """One line for the log that names the face of every role of a look,
    plain and, where it differs, lit, in the order of tokens.FONT_ROLES. name
    is the look's name, its theme's."""
    items = []

    def item(label, got):
        items.append("%s %s%s%s" % (label, got.family, " bold" if got.weight == "bold" else "",
                                    "" if got.found else " (none of its chain is on this machine)"))

    for role in tokens.FONT_ROLES:
        face = fonts.get(role)
        if face is None:
            continue
        item(role, faces[(face.family, face.weight)])
        if face.lit and face.lit != face.weight:
            item(role + " lit", faces[(face.family, face.lit)])
    return "the fonts of the %s look: %s" % (name, ", ".join(items))
