"""The fast engine's five quality steps below Full, tried with no window: each by itself, then switched
through in one run, then switched back and forth to watch the video memory.

    python quality_test.py [OUTDIR] [--image PNG] [--loop N] [--math] [--keep]

It runs bin\\lens-fast.exe --selftest on one picture, docs\\images\\blender-before.png unless
--image names another, against the stack copy in fast_engine\\test-stack:

  reference   at the reference size, the picture fitted into 2560x1440 (--work-max 2560 1440)
  steps       --quality 4 down to 0, each a run of its own. Scored by score_selftest.py with
              kept measured against the reference run, and held against the engine's table
              where the picture size is in it: kept within 0.03, and on an RTX 5090 the
              network's time within 0.15 ms
  switches    one run that starts at the default step and switches through 4, 3, 2, 1, 0 and
              back to the default. Each step draws as many frames as a run of its own has
              drawn when it keeps its picture, so the picture after a switch must be the
              picture of that step's own run, byte for byte
  loop        one run that switches between step 4 and step 0, N times each (12), with 99
              frames at each, then goes back to the default step and draws there for about
              20 s more. The runtime gives the memory of a network that was replaced back
              some seconds after the switch, so the video memory in use at the end must be
              what it was before the first switch, within 16 MiB
  math        with --math, tools\\verify_math.py on the default step's run and on step 1's,
              the downscale and the composite done again on the CPU for a squeezed size

OUTDIR defaults to a new folder under fast_engine\\build\\quality-test named after the time.
It gets one folder for each run and quality-test.json with every figure. The switch run's
pictures, 25 MB each at 6144x2526, are deleted once they are compared, unless --keep is
given.

The runs use the GPU, so the whole series holds the measuring lock, as run_selftest.py does
for one run (see there). Exit code: 0 everything held, 1 something did not, 2 the engine
failed, 3 the lock never went, 4 the card stayed busy.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

import run_selftest as rs

Image.MAX_IMAGE_PIXELS = None   # the pictures are large on purpose
HERE = os.path.dirname(os.path.abspath(__file__))
FAST = os.path.dirname(HERE)
VERIFY = os.path.join(HERE, "verify_math.py")
NO_WINDOW = 0x08000000
VRAM_TOL_MIB = 16.0
LOOP_FRAMES = 99        # under 100, so the run keeps no pictures
REST_ENTRIES = 70       # so many times the frames again at the last step, about 20 s


def engine(outdir, image, args):
    """One self test run. Returns the exit code, None when it did not finish."""
    os.makedirs(outdir, exist_ok=True)
    command = [rs.EXE, "--stack", rs.STACK, "--selftest", image, outdir, "--data", os.path.join(outdir, "ngx-data")]
    command += args
    with open(os.path.join(outdir, "engine-stdout.txt"), "wb") as out, \
            open(os.path.join(outdir, "engine-stderr.txt"), "wb") as err:
        try:
            return subprocess.run(command, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                  env=dict(os.environ, LENS_FAST_NR_READS="1"), creationflags=NO_WINDOW,
                                  timeout=900).returncode
        except subprocess.TimeoutExpired:
            return None


def scored(outdir, image, extra):
    """score_selftest.py --check on a run. Returns its exit code and what it wrote."""
    done = subprocess.run([sys.executable, rs.SCORE, outdir, "--original", image, "--check"] + extra,
                          capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        with open(os.path.join(outdir, "scores.json"), encoding="utf-8") as f:
            return done.returncode, json.load(f)
    except (OSError, ValueError):
        return done.returncode, {"problems": [(done.stdout + done.stderr).strip()[-400:]]}


def timings(outdir):
    with open(os.path.join(outdir, "timings.json"), encoding="utf-8") as f:
        return json.load(f)


def steps_of(width, height):
    """The engine's own word on the picture size: the work sizes of the five steps below Full
    and the default step. The Full step, the picture's own size, is not part of this test's
    runs and its entry is left out."""
    out = subprocess.run([rs.EXE, "--steps", str(width), str(height)], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout.strip()
    sizes = {}
    default = None
    for part in out.split(":", 1)[-1].split(","):
        words = part.split()
        if words and words[0].isdigit() and int(words[0]) <= 4:
            sizes[int(words[0])] = words[-1]
        elif len(words) == 2 and words[0] == "default":
            default = int(words[1])
    if len(sizes) != 5 or default is None:
        sys.exit("quality_test: lens-fast.exe --steps said '%s'" % out)
    return sizes, default, out


def same_picture(a, b):
    x = np.asarray(Image.open(a).convert("RGB"))
    y = np.asarray(Image.open(b).convert("RGB"))
    return x.shape == y.shape and bool((x == y).all())


def fail_run(what, outdir, code):
    print("quality_test: %s: the engine's exit code is %s" % (what, code))
    for line in rs.tail(os.path.join(outdir, "engine-stdout.txt"), 6) + rs.tail(os.path.join(outdir, "engine-stderr.txt"), 6):
        print("    " + line)


def main():
    ap = argparse.ArgumentParser(description="Tries the fast engine's quality steps with no window.")
    ap.add_argument("outdir", nargs="?")
    ap.add_argument("--image", default=rs.IMAGE)
    ap.add_argument("--loop", type=int, default=12)
    ap.add_argument("--math", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    image = os.path.abspath(args.image)
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.join(
        FAST, "build", "quality-test", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(outdir, exist_ok=True)
    with Image.open(image) as picture:
        width, height = picture.size
    sizes, default, said = steps_of(width, height)
    print("quality_test: %s, %dx%d" % (image, width, height))
    print("quality_test: %s" % said)

    result = {"image": image, "size": [width, height], "default": default, "steps": {}, "problems": []}
    problems = result["problems"]
    busy, locked = rs.take_lock()
    code_out = 0
    try:
        print("quality_test: card %d percent busy, %s" % (busy, "lock taken" if locked else "no lock to share"),
              flush=True)
        # ---- the reference size
        ref_dir = os.path.join(outdir, "reference")
        code = engine(ref_dir, image, ["--work-max", "2560", "1440"])
        if code != 0:
            fail_run("the reference run", ref_dir, code)
            return 2
        _, ref_scores = scored(ref_dir, image, [])
        ref_t = timings(ref_dir)
        result["reference"] = {"work": ref_t["work"], "nr_ms": ref_t["gpu_ms"]["nr"]["median"],
                               "change": ref_scores["composite"]["change"], "edge": ref_scores["composite"]["edge"],
                               "vram_mib": ref_t["vram_mib"]["after_timed_frames"]}
        print("reference   work %dx%d  nr %.3f ms  change %.3f  edge %.1f  %0.f MiB"
              % (ref_t["work"][0], ref_t["work"][1], result["reference"]["nr_ms"], result["reference"]["change"],
                 result["reference"]["edge"], result["reference"]["vram_mib"]), flush=True)

        # ---- each step by itself
        for step in (4, 3, 2, 1, 0):
            run_dir = os.path.join(outdir, "q%d" % step)
            code = engine(run_dir, image, ["--quality", str(step)])
            if code != 0:
                fail_run("step %d" % step, run_dir, code)
                return 2
            rc, s = scored(run_dir, image, ["--kept-against", ref_dir])
            t = timings(run_dir)
            q = t.get("quality") or {}
            row = {"work": t["work"], "nr_ms": t["gpu_ms"]["nr"]["median"], "ingest_ms": t["gpu_ms"]["ingest"]["median"],
                   "composite_ms": t["gpu_ms"]["composite"]["median"], "frame_ms": t["gpu_ms"]["frame"]["median"],
                   "change": s["composite"]["change"], "edge": s["composite"]["edge"],
                   "kept": s.get("kept", {}).get("kept"), "table_kept": q.get("table_kept"),
                   "table_ms": q.get("table_ms"), "vram_mib": t["vram_mib"]["after_timed_frames"],
                   "create_ms": t["create_ms"], "settle": t["settle"]["mean_abs_from_settled"],
                   "checks_ok": t["ok"], "problems": s.get("problems", [])}
            result["steps"][str(step)] = row
            for p in row["problems"]:
                problems.append("step %d: %s" % (step, p))
            if rc != 0 and not row["problems"]:
                problems.append("step %d: the scorer's exit code is %d" % (step, rc))
            print("step %d      work %dx%d  nr %.3f ms%s  kept %.4f%s  change %.3f  edge %.1f  %.0f MiB  %s"
                  % (step, t["work"][0], t["work"][1], row["nr_ms"],
                     " (table %.3f)" % row["table_ms"] if row["table_ms"] else "",
                     row["kept"], " (table %.4f)" % row["table_kept"] if row["table_kept"] else "",
                     row["change"], row["edge"], row["vram_mib"],
                     "ok" if not row["problems"] else "OFF: " + "; ".join(row["problems"])), flush=True)

        # ---- switched through in one run
        order = [4, 3, 2, 1, 0, default]
        sw_dir = os.path.join(outdir, "switches")
        code = engine(sw_dir, image, ["--quality", str(default), "--switches", ",".join(str(s) for s in order)])
        if code != 0:
            fail_run("the switch run", sw_dir, code)
            problems.append("the switch run failed with exit code %s" % code)
        else:
            t = timings(sw_dir)
            result["switches"] = []
            for k, s in enumerate(t["switches"]):
                picture = os.path.join(sw_dir, s["file"])
                own = os.path.join(outdir, "q%d" % s["quality"], "composite.png")
                same = same_picture(picture, own)
                if not same:
                    problems.append("switch %d to step %d: the picture is not the one of the step's own run"
                                    % (k, s["quality"]))
                if s["same"] is False:
                    problems.append("switch %d to step %d: not the picture of the first time at this step"
                                    % (k, s["quality"]))
                if s["resized"] and s.get("held_same") is False:
                    problems.append("switch %d to step %d: a frame drawn while the network was being made is not "
                                    "the picture from before the switch" % (k, s["quality"]))
                result["switches"].append({"quality": s["quality"], "work": s["work"], "resized": s["resized"],
                                           "prepare_ms": s["prepare_ms"], "create_ms": s["create_ms"],
                                           "commit_ms": s["commit_ms"], "first_frame_ms": s["first_frame_ms"],
                                           "nr_ms": s["nr_ms"]["median"], "vram_mib": s["vram_mib"],
                                           "held_frames": s.get("held_frames"), "held_gap_ms": s.get("held_gap_ms"),
                                           "held_same": s.get("held_same"),
                                           "first_from_before": s.get("first_from_before"),
                                           "first_from_plain": s.get("first_from_plain"),
                                           "rest_from_first": s.get("rest_from_first"),
                                           "same_as_own_run": same})
                print("switch %d    to step %d  work %dx%d  made in %.0f ms (creation %.0f)  %s frames drawn meanwhile, "
                      "the longest gap %.1f ms  put in use %.1f ms  first frame %.1f ms  nr %.3f ms  %.0f MiB  the "
                      "first picture %.3f from the one before and %.3f from the plain one  %s"
                      % (k, s["quality"], s["work"][0], s["work"][1], s["prepare_ms"], s["create_ms"],
                         s.get("held_frames", "-"), s.get("held_gap_ms", 0.0),
                         s["commit_ms"], s["first_frame_ms"], s["nr_ms"]["median"], s["vram_mib"],
                         s.get("first_from_before", -1.0), s.get("first_from_plain", -1.0),
                         "the picture of the step's own run" if same else "NOT the picture of the step's own run"),
                      flush=True)
                if not args.keep:
                    os.remove(picture)

        # ---- back and forth, for the memory, then back at the default step and a rest there
        if args.loop > 0:
            loop_dir = os.path.join(outdir, "loop")
            order = [4, 0] * args.loop + [default] * (1 + REST_ENTRIES)
            code = engine(loop_dir, image, ["--quality", str(default), "--switches", ",".join(str(s) for s in order),
                                            "--switch-frames", str(LOOP_FRAMES)])
            if code != 0:
                fail_run("the loop run", loop_dir, code)
                problems.append("the loop run failed with exit code %s" % code)
            else:
                t = timings(loop_dir)
                sw = t["switches"]
                start = t["vram_mib"]["after_timed_frames"]     # at the default step, before any switch
                resized = [k for k, s in enumerate(sw) if s["resized"]]
                last = resized[-1] if resized else 0
                made = [sw[k]["prepare_ms"] for k in resized]
                peak = max(s["vram_mib"] for s in sw)
                end = sw[-1]["vram_mib"]
                # from when on it is back at the level it began with, in seconds after the last switch
                back = None
                for k in range(len(sw) - 1, last - 1, -1):
                    if abs(sw[k]["vram_mib"] - start) > VRAM_TOL_MIB:
                        break
                    back = sw[k]["at_s"] - sw[last]["at_s"]
                held = abs(end - start) <= VRAM_TOL_MIB
                result["loop"] = {"switches": len(resized), "frames": LOOP_FRAMES, "start_mib": start,
                                  "peak_mib": peak, "end_mib": end, "back_after_s": back,
                                  "rest_s": sw[-1]["at_s"] - sw[last]["at_s"],
                                  "vram_mib": [s["vram_mib"] for s in sw], "at_s": [s["at_s"] for s in sw],
                                  "prepare_ms": made}
                if not held:
                    problems.append("the loop: video memory began at %.0f MiB and is at %.0f MiB %.0f s after the "
                                    "last switch" % (start, end, result["loop"]["rest_s"]))
                print("loop        %d switches between step 4 and step 0, then back at step %d: video memory %.0f MiB "
                      "before the first, %.0f at the most, %.0f at the end  %s"
                      % (len(resized) - 1, default, start, peak, end,
                         "it is back at its level %.1f s after the last switch" % back if held and back is not None
                         else "IT DOES NOT RETURN within %.0f s" % result["loop"]["rest_s"]), flush=True)
                if made:
                    print("loop        a switch made its network in %.0f to %.0f ms, median %.0f"
                          % (min(made), max(made), sorted(made)[len(made) // 2]), flush=True)
    finally:
        if locked:
            try:
                os.remove(rs.LOCK)
            except OSError:
                pass

    # ---- the arithmetic, on the CPU, which needs no lock
    if args.math:
        for step in sorted({default, 1}, reverse=True):
            done = subprocess.run([sys.executable, VERIFY, os.path.join(outdir, "q%d" % step), "--original", image],
                                  capture_output=True, text=True, creationflags=NO_WINDOW)
            lines = (done.stdout + done.stderr).strip().splitlines()
            result.setdefault("math", {})[str(step)] = {"equal": done.returncode == 0, "lines": lines}
            for line in lines:
                print("math q%d     %s" % (step, line))
            if done.returncode != 0:
                problems.append("step %d: the shaders' arithmetic is not what the CPU gives" % step)

    with open(os.path.join(outdir, "quality-test.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    if problems:
        code_out = 1
        for p in problems:
            print("quality_test: PROBLEM: %s" % p)
    print("quality_test: %s, the runs and quality-test.json are in %s"
          % ("everything held" if not problems else "SOMETHING DID NOT HOLD", outdir))
    return code_out


if __name__ == "__main__":
    sys.exit(main())
