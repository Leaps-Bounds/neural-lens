"""Makes the engine's table of work sizes: src\\work_table.h from tools\\work_table.json.

    python make_work_table.py [--study TABLE.JSON] [--check]

The engine's five quality steps below Full each have a work size, the size the network runs
at, for each picture size (Full is the picture's own size and needs no table). The sizes
come from a study that measured them on an RTX 5090: for every
candidate size the network's GPU time over 300 runs after 120 to warm up, and how much of the
network's change four pictures keep against the reference size, which is the picture fitted
into 2560x1440. The study's files are not part of the repository. What the engine needs of
them is kept here as tools\\work_table.json, and src\\work_table.h is generated from that
file, so the header can be made again from the repository alone.

Without --study the tool reads tools\\work_table.json and writes src\\work_table.h.
With --study it first makes tools\\work_table.json again from the study's table.json. The
default place for that file, used when it exists and --study is given without a path, is
_harnesses\\work_sizes\\table.json beside fast_engine.
With --check nothing is written, and the exit code is 1 when the header on disk is not what
the tool would write.

The rule for a picture size that is not in the table is steps() below. The same rule is
written in C++ in src\\common.cpp (quality_rule), which checks at compile time that it gives
every entry of the header that this tool marked as given by the rule.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAST = os.path.dirname(HERE)
REPO = os.path.dirname(FAST)
TABLE = os.path.join(HERE, "work_table.json")
HEADER = os.path.join(FAST, "src", "work_table.h")
STUDY = os.path.join(REPO, "_harnesses", "work_sizes", "table.json")

NAMES = ["Lowest power", "Low power", "Performance", "Balanced", "Quality"]   # by step, 0 to 4
KINDS = ["native", "downscaled", "short"]                                    # as the header numbers them
PICTURES = ["text", "lines", "ui", "blender"]
MOST_W, MOST_H = 2560, 1440     # the reference size is the picture fitted into this


# ---------------------------------------------------------------- the rule

def reference(W, H):
    """The picture fitted into 2560x1440, each side rounded to nearest, a half going up."""
    num, den = 1, 1
    if MOST_W * den < num * W:
        num, den = MOST_W, W
    if MOST_H * den < num * H:
        num, den = MOST_H, H
    return min(W, (2 * W * num + den) // (2 * den)), min(H, (2 * H * num + den) // (2 * den))


def floor128(x):
    """The largest multiple of 128 not above x, 128 at least."""
    return max(128, (x // 128) * 128)


def near128(x, percent):
    """The multiple of 128 nearest to that share of x, a half going up, 128 at least."""
    return max(128, ((percent * x + 6400) // 12800) * 128)


def below(h, above):
    """h, and at least 128 under `above`, and 128 at least."""
    return max(128, min(h, above - 128))


def steps(W, H):
    """The five work sizes of a W x H picture by the rule, with its kind and reference size.

    R is the reference size. f is floor128, r is near128.
    native       the picture fits 2560x1440, so R is the picture itself. Any resampling takes
                 away the network's finest texture, and a narrower width takes it away both
                 ways, so the width stays and only the height steps down:
                 4 R, 3 (Rw, r(82% Rh)), 2 (Rw, r(70% Rh)), 1 (Rw, r(60% Rh)), 0 (r(60% Rw), height of 1)
    downscaled   R has 900 rows or more:
                 4 (f(Rw), f(Rh)), 3 (f(Rw), r(82% Rh)), 2 (r(85% Rw), height of 3),
                 1 (f(Rw), r(60% Rh)), 0 (r(60% Rw), height of 1)
    short        R has fewer than 900 rows, as 2560x720 for a 32:9 screen:
                 4 (f(Rw), f(Rh)), 3 (r(85% Rw), height of 4), 2 (width of 3, height of 4 - 128),
                 1 (r(60% Rw), height of 2), 0 (width of 1, height of 2 - 128)
                 and with 768 rows or more in R, step 3 is (f(Rw), f(Rh) - 128). Measured on
                 3840x1200, that size costs the same as the recipe's and is nearer the reference.
    A step's height is at least 128 rows under the height above it where both have the same
    width. A native picture of 128 rows or fewer has no such height, and its steps 3 to 1 are
    the picture itself, since one row fewer would resample every row and save nothing.
    A downscaled step 0 that lands on 1280 wide takes 1408, since 1280 was a weak width.
    At the end no side is larger than the picture's, and no step is larger than the one above.
    """
    rw, rh = reference(W, H)
    if (rw, rh) == (W, H):
        kind = "native"
        h3 = below(near128(rh, 82), floor128(rh) + (128 if rh % 128 else 0))
        if h3 >= rh:
            h3 = rh         # with 128 rows or fewer there is no multiple of 128 under the picture
        h2 = below(near128(rh, 70), h3)
        h1 = below(near128(rh, 60), h2)
        s = {4: (rw, rh), 3: (rw, h3), 2: (rw, h2), 1: (rw, h1), 0: (min(near128(rw, 60), rw), h1)}
    elif rh >= 900:
        kind = "downscaled"
        w4, h4 = floor128(rw), floor128(rh)
        h3 = below(near128(rh, 82), h4 + 128) if near128(rh, 82) < h4 else h4 - 128
        w2 = min(near128(rw, 85), w4 - 128)
        h1 = below(near128(rh, 60), h3)
        w0 = min(near128(rw, 60), w4)
        if w0 == 1280 and w2 - 128 >= 1408:
            w0 = 1408
        s = {4: (w4, h4), 3: (w4, h3), 2: (w2, h3), 1: (w4, h1), 0: (w0, h1)}
    else:
        kind = "short"
        w4, h4 = floor128(rw), floor128(rh)
        w3 = min(near128(rw, 85), w4 - 128)
        h2 = below(h4 - 128, h4)
        w1 = min(near128(rw, 60), w3 - 128)
        h0 = below(h2 - 128, h2)
        s = {4: (w4, h4), 3: (w3, h4), 2: (w3, h2), 1: (w1, h2), 0: (w1, h0)}
        if rh >= 768:
            s[3] = (w4, h4 - 128)
    for k in (4, 3, 2, 1, 0):
        w, h = max(1, min(s[k][0], W)), max(1, min(s[k][1], H))
        if k < 4 and w * h > s[k + 1][0] * s[k + 1][1]:
            w, h = s[k + 1]
        s[k] = (w, h)
    return {"kind": kind, "reference": (rw, rh), "work": [s[k] for k in range(5)]}


# ---------------------------------------------------------------- the study's table, trimmed

def from_study(path):
    """tools\\work_table.json's content from the study's table.json."""
    with open(path, encoding="utf-8") as f:
        study = json.load(f)
    pictures = []
    for group in ("screens", "tests", "check_tests"):
        for name, e in study.get(group, {}).items():
            W, H = (int(v) for v in name.lower().split("x"))
            by_step = {s["step"]: s for s in e["steps"] if "step" in s}
            also = {tuple(s["work"]): s for s in e.get("also", [])}
            if "default_work" in e:
                # a measured size took the place of the recipe's at the default step
                by_step[3] = dict(also[tuple(e["default_work"])], step=3)
            if sorted(by_step) != [0, 1, 2, 3, 4]:
                sys.exit("%s in %s does not have the five steps" % (name, group))
            entry = {"size": [W, H], "kind": e["kind"], "reference": e["reference"],
                     "reference_ms": e["reference_ms"], "steps": []}
            for k in range(5):
                s = by_step[k]
                row = {"work": s["work"], "ms": s["ms"]}
                kept = {p: s[p]["kept"] for p in PICTURES if p in s and "kept" in s[p]}
                if kept:
                    row["kept"] = kept
                elif tuple(s["work"]) == tuple(e["reference"]):
                    row["kept"] = {p: 1.0 for p in PICTURES}   # the reference against itself
                entry["steps"].append(row)
            pictures.append(entry)
    default = study["default"]
    return {
        "about": "The work sizes of the fast engine's five quality steps for each picture size that was "
                 "measured. tools\\make_work_table.py makes src\\work_table.h from this file. ms is the network's "
                 "GPU time at the work size on an RTX 5090, the median of 300 runs after 120 to warm up. kept "
                 "is the share of the network's change that a picture keeps against the reference size, which "
                 "is the picture fitted into 2560x1440. steps are listed from 0 to 4.",
        "names": NAMES,
        "default": {k: default[k] for k in KINDS},
        "pictures": pictures,
    }


# ---------------------------------------------------------------- the header

def header_text(table):
    rows = []
    for e in sorted(table["pictures"], key=lambda e: (-e["size"][0] * e["size"][1], -e["size"][0])):
        W, H = e["size"]
        ruled = steps(W, H)
        given = (ruled["kind"] == e["kind"] and list(ruled["reference"]) == list(e["reference"])
                 and [list(w) for w in ruled["work"]] == [s["work"] for s in e["steps"]])
        cells = []
        for s in e["steps"]:
            kept = s.get("kept", {}).get("blender")
            cells.append("{%d, %d, %.3ff, %.4ff}" % (s["work"][0], s["work"][1], s["ms"],
                                                    kept if kept is not None else 0.0))
        rows.append("    {%d, %d, %d, %s, {%s}}," % (W, H, KINDS.index(e["kind"]), "true" if given else "false",
                                                     ", ".join(cells)))
    d = table["default"]
    lines = [
        "// work_table.h: the work sizes of the five quality steps below Full, for every picture size",
        "// that was measured.",
        "//",
        "// GENERATED by tools\\make_work_table.py from tools\\work_table.json. Do not edit it by hand.",
        "// Change the table and run the tool again.",
        "//",
        "// The work size is the size the network runs at. For each picture size in the table, five",
        "// work sizes were measured on an RTX 5090, one for each step from 4 (Quality) down to 0",
        "// (Lowest power). A picture size that is not here gets its sizes from the rule in",
        "// common.cpp, quality_rule(), which gives every entry below that is marked as the rule's.",
        "// The step above these, 5 (Full), is the picture's own size and needs no table, see",
        "// common.h.",
        "//",
        "// ms is the network's GPU time at that work size, the median of 300 runs after 120 to warm",
        "// up. kept is the share of the network's change that the Blender test picture keeps against",
        "// the reference size, which is the picture fitted into 2560x1440. It is 0 where it was not",
        "// measured.",
        "#pragma once",
        "",
        "namespace work_table {",
        "",
        "struct Step {",
        "  unsigned short w, h;  // the work size",
        "  float ms;             // the network's GPU milliseconds there",
        "  float kept;           // the share of the network's change that is kept",
        "};",
        "",
        "struct Entry {",
        "  unsigned short width, height;  // the picture",
        "  unsigned char kind;            // 0 native, 1 downscaled, 2 short, see quality_rule()",
        "  bool by_rule;                  // the rule gives these five sizes too",
        "  Step step[5];                  // by step, 0 Lowest power to 4 Quality",
        "};",
        "",
        "// The step in use when none is asked for, by kind. It is the highest step at which no loss",
        "// was seen in the pictures.",
        "inline constexpr int kDefaultStep[3] = {%d, %d, %d};" % (d["native"], d["downscaled"], d["short"]),
        "",
        "inline constexpr Entry kEntries[] = {",
    ] + rows + [
        "};",
        "",
        "inline constexpr int kEntryCount = (int)(sizeof(kEntries) / sizeof(kEntries[0]));",
        "",
        "}  // namespace work_table",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Makes src\\work_table.h from tools\\work_table.json.")
    ap.add_argument("--study", nargs="?", const=STUDY, default=None,
                    help="make tools\\work_table.json again from the study's table.json first")
    ap.add_argument("--check", action="store_true", help="write nothing, exit 1 when the header is out of date")
    args = ap.parse_args()

    if args.study:
        if not os.path.isfile(args.study):
            sys.exit("no study table at %s" % args.study)
        table = from_study(args.study)
        if not args.check:
            with open(TABLE, "w", encoding="utf-8", newline="\n") as f:
                json.dump(table, f, indent=1)
                f.write("\n")
            print("wrote %s, %d picture sizes" % (TABLE, len(table["pictures"])))
    else:
        with open(TABLE, encoding="utf-8") as f:
            table = json.load(f)

    text = header_text(table)
    off_rule = [e["size"] for e in table["pictures"]
                if [list(w) for w in steps(*e["size"])["work"]] != [s["work"] for s in e["steps"]]]
    if args.check:
        try:
            with open(HEADER, encoding="utf-8", newline="") as f:
                same = f.read() == text
        except OSError:
            same = False
        print("%s is %s" % (HEADER, "what the table gives" if same else "NOT what the table gives"))
        sys.exit(0 if same else 1)
    with open(HEADER, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote %s, %d picture sizes, %d of them not as the rule gives them%s"
          % (HEADER, len(table["pictures"]), len(off_rule),
             ": " + ", ".join("%dx%d" % tuple(s) for s in off_rule) if off_rule else ""))


if __name__ == "__main__":
    main()
