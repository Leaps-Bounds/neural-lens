"""The words of the lens as the drawn looks show them, split out of the whole
texts the code builds. A widget keeps the whole text as its own and draws the
parts, so what the code and the tests read never changes. Each split joins
back to the very string it came from, see join_menu_text, join_key_line and
join_message.

Pure.
"""
import collections
import re

# The tick after the chosen name in a list, three spaces and a check mark.
TICK = "   \u2713"

# A key as the lens writes one, the modifiers and then the key joined by +, as
# _hotkey_text in neural_lens.py writes them, or one of the keys the lens
# names itself, such as Home or Escape. Alone, without a modifier, a function
# key or a key of BARE counts as a key, and a letter or a digit does not, since
# it reads as a word.
BARE = ("Home", "End", "Insert", "Delete", "Pageup", "Pagedown", "PgUp", "PgDn", "Escape", "Esc", "Enter",
        "Return", "Tab", "Space", "Backspace", "Pause", "Scrolllock", "Printscreen", "Up", "Down", "Left", "Right")
NAMED = BARE + ("Plus", "Minus", "Comma", "Period", "Slash", "Backslash", "Semicolon", "Quote", "Backquote",
                "Bracketleft", "Bracketright", "Multiply", "Add", "Subtract", "Divide", "Decimal")
_FN = r"F(?:[1-9]|1[0-9]|2[0-4])"
_MODS = r"(?:(?:Ctrl|Alt|Shift|Win)\+)"
KEY = re.compile(r"^(?:%s+(?:%s|%s|Numpad[0-9]|[A-Z0-9]|0x[0-9A-F]{2})|%s|%s)$"
                 % (_MODS, _FN, "|".join(NAMED), _FN, "|".join(BARE)))

# A menu entry's hint is two spaces or more and then words in brackets at its
# end, which the code puts after the entry's own words.
_HINT = re.compile(r"^(.*?\S)( {2,})\(([^()]*)\)$")
_SEPS = re.compile(r"(, | or )")

# A menu entry as the drawn looks show it. words are the entry's own words, gap
# the spaces the code put before the brackets, inner what the brackets hold,
# None where there are none, items the keys and the hint in it in their order,
# each (kind, text, separator before it), and tick the tick after a chosen
# name. keys and hint are the items' keys and the hint's words, for drawing.
MenuText = collections.namedtuple("MenuText", "words gap inner items tick keys hint")


def is_key(text):
    """Whether a word is a key as the lens names keys."""
    return bool(KEY.match(text))


def split_menu_text(text, hints=True):
    """The parts of a menu entry the code built, such as "Save the result only
    (F5, ReShade's own)" with seven spaces, into its words, the key F5 and the
    hint "ReShade's own". The keys and the hint keep their order, and a run of
    words that are not keys stays one hint with its commas, as in "(click it,
    then drag the region)". hints=False takes the whole entry as words, for an
    entry made of a name, such as a profile's, which could hold brackets of its
    own."""
    text = str(text)
    tick = TICK if text.endswith(TICK) else ""
    body = text[:len(text) - len(tick)]
    m = _HINT.match(body) if hints else None
    if not m:
        return MenuText(body, "", None, (), tick, (), "")
    words, gap, inner = m.groups()
    parts = _SEPS.split(inner)
    items = []
    for i in range(0, len(parts), 2):
        part, sep = parts[i], parts[i - 1] if i else ""
        kind = "key" if is_key(part) else "hint"
        if kind == "hint" and items and items[-1][0] == "hint":
            items[-1] = ("hint", items[-1][1] + sep + part, items[-1][2])
        else:
            items.append((kind, part, sep))
    keys = tuple(t for k, t, _s in items if k == "key")
    hint = ", ".join(t for k, t, _s in items if k == "hint")
    return MenuText(words, gap, inner, tuple(items), tick, keys, hint)


def join_menu_text(mt):
    """The whole entry a MenuText was split from."""
    if mt.inner is None:
        return mt.words + mt.tick
    return "%s%s(%s)%s" % (mt.words, mt.gap, "".join(sep + t for _k, t, sep in mt.items), mt.tick)


def split_key_line(line, key=None):
    """A line of the fullscreen note's keys as (the key it starts with, the
    rest), such as ("F7", "opens the lens menu, where Leave fullscreen is.").
    key is the key the code knows the line starts with, which wins where it
    is given. A line that starts with no key, such as the line of the arrow
    keys, gives ("", the line)."""
    line = str(line)
    if key:
        if line.startswith(key + " "):
            return key, line[len(key) + 1:]
        return "", line
    first, _sp, rest = line.partition(" ")
    if rest and is_key(first):
        return first, rest
    return "", line


def join_key_line(cap, rest):
    """The whole line split_key_line split."""
    return "%s %s" % (cap, rest) if cap else rest


def display_case(text, case):
    """A text in a look's case: upper, lower, or as written for None. The
    widget keeps the text as written."""
    if case == "upper":
        return str(text).upper()
    if case == "lower":
        return str(text).lower()
    return text


# ---- a message as a drawn look's dialog lays it out

# A line that is a path alone, a folder or a file on a drive or a share, such
# as the logs folder a message names. A drawn look shows it in a field of its
# own, where it can be selected.
_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\\s])")
# The first line of the traceback the lens quotes after it says it stopped
# with an error. It and everything after it are the message's detail.
TRACEBACK = "Traceback (most recent call last):"

# A part of a message. kind is head, text, path or detail, words what the
# dialog shows, raw the very text it was taken from, before what came between
# it and the part before it, and new whether it begins a paragraph.
MessagePart = collections.namedtuple("MessagePart", "kind words raw before new")
# A message split into its parts, and what came after the last of them.
Message = collections.namedtuple("Message", "parts tail")


def is_path(line):
    """Whether a line of a message is a path alone, see _PATH."""
    return bool(_PATH.match(str(line).strip()))


def _prose(lines):
    """Whether lines read as the lens's own sentences, which begin with a
    capital letter and end as a sentence or a lead-in ends, where an error
    quoted from elsewhere often does neither."""
    first, last = lines[0].strip(), lines[-1].strip()
    return first[:1].isupper() and last[-1:] in ".:?!"


def _dedent(lines):
    """The lines without the spaces they all begin with or end with."""
    cut = min(len(line) - len(line.lstrip()) for line in lines)
    return [line[cut:].rstrip() for line in lines]


def split_message(text, detail=None, head=None):
    """The parts of a message the lens shows, as a drawn look's dialog lays
    them out. Paragraphs are parted by a blank line. A line that is a path
    alone is a path. A paragraph after the first is the detail where it is
    words quoted from elsewhere, which do not read as the lens's sentences or
    have a line set in by spaces that is not a path, such as an error, the
    files a stack lacks or the lines to type, and from a traceback on every
    paragraph is. Every other line is text. head says what heads the message,
    the first line of its first paragraph for line, the whole first
    paragraph for paragraph, and nothing for None. detail is a detail given
    apart, which comes last after a blank line, as the dialog adds it to the
    text. The words of a head and a text keep the lines the lens broke on
    purpose, a path is the path alone, and a detail's lines lose the spaces
    they all begin with. join_message gives back the very text, with the
    detail after it as the dialog has it."""
    text = str(text or "")
    lines = text.split("\n")
    spans, at = [], 0
    for line in lines:
        spans.append((at, at + len(line)))
        at += len(line) + 1
    paragraphs, run = [], []
    for i, line in enumerate(lines):
        if line.strip():
            run.append(i)
        elif run:
            paragraphs.append(run)
            run = []
    if run:
        paragraphs.append(run)
    parts, end = [], [0]

    def add(kind, first, last, words, new):
        start, stop = spans[first][0], spans[last][1]
        parts.append(MessagePart(kind, words, text[start:stop], text[end[0]:start], new))
        end[0] = stop

    quoted = False
    for p, para in enumerate(paragraphs):
        rows = [lines[i] for i in para]
        k, new = 0, True
        if p == 0 and head:
            take = len(rows) if head == "paragraph" else 1
            add("head", para[0], para[take - 1], "\n".join(r.strip() for r in rows[:take]), True)
            k, new = take, False
        if p > 0:
            quoted = quoted or rows[0].strip() == TRACEBACK
            said = [r for r in rows if not is_path(r)]
            if quoted or (said and (not _prose(said) or any(r[:1].isspace() for r in said))):
                add("detail", para[0], para[-1], "\n".join(_dedent(rows)), True)
                continue
        while k < len(rows):
            if is_path(rows[k]):
                add("path", para[k], para[k], rows[k].strip(), new)
                k += 1
            else:
                j = k
                while j < len(rows) and not is_path(rows[j]):
                    j += 1
                add("text", para[k], para[j - 1], "\n".join(r.rstrip() for r in rows[k:j]), new)
                k = j
            new = False
    tail = text[end[0]:]
    if detail:
        more = str(detail)
        rows = more.split("\n")
        words = "\n".join(_dedent([r for r in rows if r.strip()] or [""]))
        parts.append(MessagePart("detail", words, more, tail + ("\n\n" if text else ""), True))
        tail = ""
    return Message(parts, tail)


def join_message(message):
    """The whole text a Message was split from, with its detail after it."""
    return "".join(part.before + part.raw for part in message.parts) + message.tail
