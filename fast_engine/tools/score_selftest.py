"""Scores what the fast engine's self test wrote.

    python score_selftest.py OUTDIR [--original PNG] [--reference DIR] [--kept-against DIR]
                             [--nr-ms-max MS] [--check]

OUTDIR is the folder given to  lens-fast-selftest.exe --stack DIR --selftest IMAGE OUTDIR.
It holds composite.png, nr_in.png, nr_out.png, timings.json and nr-reads.txt.

The two figures the project scores pictures with:
    change  the mean absolute difference of grey from the original, out of 255
    edge    the variance of a 4-neighbour Laplacian on grey: how much fine detail there is
The probe's reference picture has change 3.21 and edge 270, the original has edge 273. The
probe is the test program the engine's GPU work was first proven with, see src\\common.h.

And against the probe's own files in --reference, where that folder exists:
    the composite against full-composite.png
    nr_in.png against work-input.png, which checks the area downscale
    nr_out.png against work-nr-output.png, which checks the network was fed and set the same
    nr-reads.txt against route-b-reads.txt: every value the runtime asked for, and through
        which getter. The same list means the engine's parameter object sits in the runtime's
        slots as the SDK's own does.
each as the mean absolute difference over all bytes, the largest one, and the share of
bytes that differ. The probe's files are not part of the repository. The default folder is
where a checkout that has them keeps them. Without them these comparisons are skipped,
which is said and written to scores.json under "skipped".

And for a run at a quality step, with --kept-against DIR, the folder of a run of the same
picture at the reference size (the picture fitted into 2560x1440, which --work-max 2560 1440
gives):
    kept    the share of the network's change that this run keeps. With r the grey change
            of this run's composite from the original and R that of the run in DIR, it is
            the sum of r * R over the sum of R * R. 1 is all of it.
The engine's table of work sizes holds the kept it measured for each step of the picture
sizes in it, on the Blender test picture, and the network's time there. The self test
writes both into timings.json, and the scorer holds this run's figures against them.

--check makes the exit code 1 unless change is 3.21 +- 0.15, edge is 270 +- 12, the
network's median is within its limit, the self test's own checks held, the runtime's reads
are the probe's where the probe's list is there, and ingest and composite are each under
1 ms. Change, edge and the network's limit belong to the 6144x2526 picture at a 2560x1053
work size with one pass, which is how the reference was made, and are not applied to a run
with more passes or another work size. The network's limit, 3.6 ms, was measured on an RTX
5090 and is applied on that card only. On another card the median is printed with no limit,
unless --nr-ms-max gives one.
For a run at a quality step of a picture size in the table it also asks that kept, where
--kept-against gave one, is within 0.03 of the table's, and on an RTX 5090 that the
network's median is within 0.15 ms of the table's.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None   # the pictures are large on purpose

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ORIGINAL = os.path.join(REPO, "docs", "images", "blender-before.png")
# the probe's files, which are not in the repository: without the folder the comparisons
# with them are skipped, see main()
REFERENCE = os.path.join(REPO, "_harnesses", "nr_direct_probe", "out", "B-rgba8")

CHANGE, CHANGE_TOL = 3.21, 0.15
EDGE, EDGE_TOL = 270.0, 12.0
WORK = [2560, 1053]             # the work size the reference was made at, with one pass
NR_MS_MAX = 3.6                 # the network's median on the card below, with some room
REFERENCE_ADAPTER = "NVIDIA GeForce RTX 5090"   # as timings.json names the card
STAGE_MS_MAX = 1.0
KEPT_TOL = 0.03                 # how far kept may be from the table's
TABLE_MS_TOL = 0.15             # and the network's median, on the card above


def gray(path):  # as the probe's scorer did
    return np.asarray(Image.open(path).convert("L"), np.float32)


def edge(a):  # as the probe's scorer did
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(lap.var())


def rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), np.uint8)


def against(path, ref_path):
    """How far one picture is from another, byte by byte."""
    if not (os.path.exists(path) and os.path.exists(ref_path)):
        return None
    a, b = rgb(path), rgb(ref_path)
    if a.shape != b.shape:
        return {"sizes_differ": [list(a.shape[1::-1]), list(b.shape[1::-1])]}
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return {"mean_abs": round(float(d.mean()), 4), "max_abs": int(d.max()),
            "differing_share": round(float((d > 0).mean()), 6),
            "over_one_share": round(float((d > 1).mean()), 6)}


def reads(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return dict(line.split(None, 1) for line in f.read().splitlines() if line.strip())


def main():
    ap = argparse.ArgumentParser(description="Scores the fast engine's self test.")
    ap.add_argument("outdir")
    ap.add_argument("--original", default=ORIGINAL)
    ap.add_argument("--reference", default=REFERENCE)
    ap.add_argument("--kept-against", default=None)
    ap.add_argument("--nr-ms-max", type=float, default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    out = {}
    problems = []
    skipped = []
    if not os.path.isdir(args.reference):
        skipped.append("the comparisons with the probe's pictures and its list of reads, since there is "
                       "no folder %s" % args.reference)
    composite = os.path.join(args.outdir, "composite.png")
    if not os.path.exists(composite):
        sys.exit("no composite.png in %s" % args.outdir)

    orig = gray(args.original)
    comp = gray(composite)
    if comp.shape != orig.shape:
        sys.exit("the composite is %dx%d and the original %dx%d" % (comp.shape[1], comp.shape[0],
                                                                    orig.shape[1], orig.shape[0]))
    timings = None
    timings_path = os.path.join(args.outdir, "timings.json")
    if os.path.exists(timings_path):
        with open(timings_path, encoding="utf-8") as f:
            timings = json.load(f)
    # the targets belong to one pass at the work size the reference was made at
    as_reference = timings is None or (timings["passes"] == 1 and timings["work"] == WORK)

    out["original"] = {"edge": round(edge(orig), 1)}
    out["composite"] = {"change": round(float(np.abs(comp - orig).mean()), 3), "edge": round(edge(comp), 1)}
    if as_reference and abs(out["composite"]["change"] - CHANGE) > CHANGE_TOL:
        problems.append("change %.3f is outside %.2f +- %.2f" % (out["composite"]["change"], CHANGE, CHANGE_TOL))
    if as_reference and abs(out["composite"]["edge"] - EDGE) > EDGE_TOL:
        problems.append("edge %.1f is outside %.0f +- %.0f" % (out["composite"]["edge"], EDGE, EDGE_TOL))

    ref_composite = os.path.join(args.reference, "full-composite.png")
    if os.path.exists(ref_composite):
        ref = gray(ref_composite)
        if ref.shape == orig.shape:
            out["reference"] = {"change": round(float(np.abs(ref - orig).mean()), 3), "edge": round(edge(ref), 1)}
            out["composite"]["grey_mean_abs_from_reference"] = round(float(np.abs(comp - ref).mean()), 4)
        del ref

    # kept: how much of the network's change at the reference size this run keeps
    kept = None
    if args.kept_against:
        against_path = os.path.join(args.kept_against, "composite.png")
        if not os.path.exists(against_path):
            sys.exit("no composite.png in %s" % args.kept_against)
        full = gray(against_path)
        if full.shape != orig.shape:
            sys.exit("the composite in %s is not the picture's size" % args.kept_against)
        r, big = comp - orig, full - orig
        kept = float((r.astype(np.float64) * big).sum() / (big.astype(np.float64) * big).sum())
        out["kept"] = {"kept": round(kept, 4),
                       "grey_mean_abs_from_reference_size": round(float(np.abs(comp - full).mean()), 4)}
        del full, r, big
    del orig, comp

    for name, mine, theirs in (("composite_vs_reference", "composite.png", "full-composite.png"),
                               ("nr_in_vs_reference", "nr_in.png", "work-input.png"),
                               ("nr_out_vs_reference", "nr_out.png", "work-nr-output.png")):
        r = against(os.path.join(args.outdir, mine), os.path.join(args.reference, theirs))
        if r is not None:
            out[name] = r

    mine, theirs = reads(os.path.join(args.outdir, "nr-reads.txt")), reads(os.path.join(args.reference, "route-b-reads.txt"))
    if mine is not None and theirs is not None:
        differing = sorted(k for k in set(mine) | set(theirs) if mine.get(k) != theirs.get(k))
        out["reads"] = {"names": len(mine), "reference_names": len(theirs), "same": not differing,
                        "differing": {k: [mine.get(k), theirs.get(k)] for k in differing}}
        if differing:
            problems.append("the runtime's reads differ from the probe's: " + ", ".join(differing))

    if timings is not None:
        t = timings
        g = t["gpu_ms"]
        out["timings"] = {
            "passes": t["passes"], "work": t["work"],
            "gpu_ms_median": {k: g[k]["median"] for k in ("ingest", "nr", "composite", "frame")},
            "gpu_ms_p95": {k: g[k]["p95"] for k in ("ingest", "nr", "composite", "frame")},
            "cpu_ms_median": {k: v["median"] for k, v in t["cpu_ms"].items()},
            "unchanged_frame_ms_median": {k: v["median"] for k, v in t["unchanged_frame"].items()},
            "create_ms": t["create_ms"], "vram_mib": t["vram_mib"]["after_timed_frames"], "checks_ok": t["ok"]}
        if not t["ok"]:
            problems.append("the self test's own checks did not all hold: %s" % t["checks"])
        # The quality step, and what the engine's table has for it. kept and the network's
        # time were measured for the table on the Blender picture at this picture size.
        q = t.get("quality")
        if q:
            out["quality"] = q
            if kept is not None and q.get("table_kept"):
                out["kept"]["table"] = q["table_kept"]
                if abs(kept - q["table_kept"]) > KEPT_TOL:
                    problems.append("kept %.4f is not within %.2f of the table's %.4f"
                                    % (kept, KEPT_TOL, q["table_kept"]))
            if q.get("table_ms") and t.get("adapter") == REFERENCE_ADAPTER and t["passes"] == 1:
                if abs(g["nr"]["median"] - q["table_ms"]) > TABLE_MS_TOL:
                    problems.append("the network's median %.3f ms is not within %.2f of the table's %.3f"
                                    % (g["nr"]["median"], TABLE_MS_TOL, q["table_ms"]))
        if "zero_strength" in t:
            out["zero_strength"] = t["zero_strength"]
        if "switches" in t:
            out["switches"] = [{"quality": s["quality"], "work": s["work"], "prepare_ms": s["prepare_ms"],
                                "create_ms": s["create_ms"], "commit_ms": s["commit_ms"],
                                "first_frame_ms": s["first_frame_ms"], "nr_ms": s["nr_ms"]["median"],
                                "vram_mib": s["vram_mib"], "same": s["same"]} for s in t["switches"]]
        # The settle: how far the first still picture after ten scrolled frames is from the
        # network's settled one, then after each of four more runs of the network. It has to
        # come nearer, or the settle does nothing for the picture.
        if "settle" in t:
            far = t["settle"]["mean_abs_from_settled"]
            out["settle"] = {"mean_abs_from_settled": far, "gain": round(far[0] - far[-1], 4)}
            if not far[-1] < far[0]:
                problems.append("the settle does not bring the picture nearer its settled state: %s" % far)
        # the limit is one card's figure: on another card the time is shown and not judged
        limit = args.nr_ms_max
        if limit is None and t.get("adapter") == REFERENCE_ADAPTER:
            limit = NR_MS_MAX
        if as_reference and limit is None:
            skipped.append("the network's limit of %.1f ms, which was measured on an %s, since this card "
                           "is %s" % (NR_MS_MAX, REFERENCE_ADAPTER.replace("NVIDIA GeForce ", ""),
                                      t.get("adapter") or "not named"))
        elif as_reference and g["nr"]["median"] > limit:
            problems.append("the network's median %.3f ms is over %.1f" % (g["nr"]["median"], limit))
        for stage in ("ingest", "composite"):
            if g[stage]["median"] >= STAGE_MS_MAX:
                problems.append("%s median %.3f ms is not under %.1f" % (stage, g[stage]["median"], STAGE_MS_MAX))

    if skipped:
        out["skipped"] = skipped
    out["problems"] = problems
    for key, value in out.items():
        print("%-24s %s" % (key, json.dumps(value)))
    with open(os.path.join(args.outdir, "scores.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    if args.check and problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
