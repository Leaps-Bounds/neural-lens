"""The fast engine's self test and its scoring in one go. run_selftest.cmd starts it.

    python run_selftest.py [OUTDIR] [--image PNG] [--kept-against DIR] [--against DIR|none]
                           [--against-shared DIR|none] [--shared | --both] [ENGINE ARGUMENTS...]

It runs  bin\\lens-fast.exe --stack test-stack --selftest docs\\images\\blender-before.png OUTDIR
--data OUTDIR\\ngx-data --work-size 2560 1053  and then  tools\\score_selftest.py OUTDIR --check.
OUTDIR defaults to a new folder under fast_engine\\build\\selftest named after the time.

2560x1053 is the work size the reference pictures were made at, so that run is the one the
scorer holds against them byte for byte. Any engine argument that chooses the work size takes
the place of --work-size 2560 1053: --quality N, --work-size W H, --work-scale S or --work-max
W H. Other engine arguments are added as they are (--passes 2, --switches 4,3,2,1,0,4, ...).

--image PNG runs another picture in place of blender-before.png. No work size is added then,
and the engine takes the default quality step for the picture's size, unless an argument says
otherwise.
--kept-against DIR is handed to the scorer. It is the folder of a run of the same picture at
the reference size, against which the scorer measures how much of the network's change this
run keeps.
--against DIR holds the run's composite.png, nr_in.png, nr_out.png and nr-reads.txt against
DIR's byte for byte, and the run fails when one differs. Not given, a reference run is held
against its baseline where the folder exists: the normal reference run (no --image, no work
size argument, no --passes) against the baseline of 2026-10-03, and the shared reference run
(--shared with none of those either) against the shared baseline of 2026-10-06. They are
kept under _harnesses, beside the measuring tools, not in the repository. Any other run,
another picture, size or pass count, is held against nothing unless --against names a
folder. --against none skips it.
--shared is the shared mode's run: --passes 2 with SharedNetwork=1 and Pass2IntensityTied=1
in the test stack's [NeuralLens.Passes], so every pass runs the first pass's feature and the
second at the first's values. The two keys are written into test-stack\\ReShade.ini for the
run and the file is put back byte for byte after it, whatever happened. --both runs the
normal run and then the shared one, in OUTDIR and OUTDIR-shared, and fails when either does.
With --both, --against goes with the normal run and --against-shared with the shared one,
each taking its own default where it is not given, so the two are never held against one
folder.

The self test runs the network on the GPU, so it keeps the project's rules for measuring:
- the card must be under 25 percent busy, looked at again a minute later, given up after five
  minutes: a game or another load would make the timings mean nothing
- where the project's other measuring tools are, in a folder _harnesses beside fast_engine
  that is not part of the repository, it shares their lock. It waits while
  _harnesses\\measuring.lock or the trial tools' measuring.lock exists, looking every 10 s, and
  gives up after 15 minutes: another measurement is running, and two at once would spoil both.
  It then creates _harnesses\\measuring.lock with its name in it, runs the engine with no
  window, and removes the lock straight after, whatever happened in between
- without that folder there is nobody to share a lock with, and none is made

The engine's own output goes to OUTDIR\\engine-stdout.txt and engine-stderr.txt, and only its
last lines are printed. LENS_FAST_NR_READS=1 is set, so the runtime's reads are written and
the scoring compares them with the probe's where it has the probe's list.

Exit code: 0 the test ran and the scores are within the targets, 1 a score is not or a file
differs from the baseline's, 2 the engine failed, 3 the lock never went or could not be made,
4 the card stayed busy.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FAST = os.path.dirname(HERE)
REPO = os.path.dirname(FAST)
EXE = os.path.join(FAST, "bin", "lens-fast.exe")
STACK = os.path.join(FAST, "test-stack")
STACK_INI = os.path.join(STACK, "ReShade.ini")
IMAGE = os.path.join(REPO, "docs", "images", "blender-before.png")
SCORE = os.path.join(HERE, "score_selftest.py")
LOCK = os.path.join(REPO, "_harnesses", "measuring.lock")
# The baselines the two reference runs are held against byte for byte: the pictures and the
# runtime's reads of a run made when the engine's picture was last judged right. Not in the
# repository: where a folder is missing the comparison is skipped and said.
RESEARCH = os.path.join(REPO, "_harnesses", "wip-060", "research")
BASELINE = os.path.join(RESEARCH, "2026-10-03", "selftest-baseline-1827")
BASELINE_SHARED = os.path.join(RESEARCH, "2026-10-06", "selftest-baseline-shared")
BASELINE_FILES = ("composite.png", "nr_in.png", "nr_out.png", "nr-reads.txt")
# What the shared run writes into the test stack's [NeuralLens.Passes] for its run
SHARED_KEYS = (("SharedNetwork", "1"), ("Pass2IntensityTied", "1"))
PASS_SECTION = "[NeuralLens.Passes]"
# The stack trial and upstream check tools keep theirs here, and this one is only waited
# for. Neither those tools nor the _harnesses folder are in the repository: where they are
# missing no lock is waited for or made.
OTHER_LOCKS = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "NeuralLens-trial", "measuring.lock")]
NO_WINDOW = 0x08000000
TAIL = 12


def gpu_busy():
    out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    return int(out.strip().splitlines()[0])


def take_lock():
    """Waits for every lock to be gone and the card to be free, then takes the lock.
    Returns how busy the card is and whether a lock was made: where the folder of the
    project's measuring tools is missing there is no one to share a lock with."""
    # FAST_RUN_LOCK_HELD=1: the caller holds the lock for a series of runs of which this is
    # one, so none is waited for, made or removed here
    shared = os.path.isdir(os.path.dirname(LOCK)) and os.environ.get("FAST_RUN_LOCK_HELD") != "1"
    t0 = time.time()
    busy_looks = 0
    while True:
        held = [p for p in [LOCK] + OTHER_LOCKS if os.path.exists(p)] if shared else []
        if held:
            if time.time() - t0 > 15 * 60:
                print("run_selftest: %s still there after 15 minutes, no run" % held[0])
                sys.exit(3)
            time.sleep(10)
            continue
        busy = gpu_busy()
        if busy >= 25:
            busy_looks += 1
            print("run_selftest: the card is %d percent busy (look %d of 5)" % (busy, busy_looks), flush=True)
            if busy_looks >= 5:
                print("run_selftest: the card stayed busy for five minutes, no run")
                sys.exit(4)
            time.sleep(60)
            continue
        if not shared:
            return busy, False
        try:
            with open(LOCK, "x") as f:
                f.write("selftest\n")
            return busy, True
        except FileExistsError:
            continue
        except OSError as e:
            print("run_selftest: cannot create %s: %s" % (LOCK, e))
            sys.exit(3)


def tail(path, n):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()[-n:]


SIZE_OPTIONS = ("--quality", "--work-size", "--work-scale", "--work-max")
REFERENCE_SIZE = ["--work-size", "2560", "1053"]


def taken(args, name):
    """Takes `name VALUE` out of args and returns VALUE, or None when it is not there."""
    if name not in args:
        return None
    i = args.index(name)
    if i + 1 >= len(args):
        sys.exit("run_selftest: %s needs a value" % name)
    value = args[i + 1]
    del args[i:i + 2]
    return value


def with_shared_keys(text):
    """The test stack's ReShade.ini text with SHARED_KEYS in its [NeuralLens.Passes], the
    section added at the end when the file has none. The file's own line ending is kept."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    names = [k.lower() for k, _ in SHARED_KEYS]
    out, in_section, placed = [], False, False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if in_section and not placed:
                out += ["%s=%s" % kv for kv in SHARED_KEYS]
                placed = True
            in_section = s.lower() == PASS_SECTION.lower()
            out.append(line)
            if in_section:
                out += ["%s=%s" % kv for kv in SHARED_KEYS]
                placed = True
            continue
        if in_section and s.split("=", 1)[0].strip().lower() in names:
            continue  # the file's own line for a key written above
        out.append(line)
    if not placed:
        while out and out[-1].strip() == "":
            out.pop()
        out += ["", PASS_SECTION] + ["%s=%s" % kv for kv in SHARED_KEYS] + [""]
    return nl.join(out)


def compare_baseline(outdir, baseline):
    """The run's four files against the baseline's, byte for byte. Returns the names that
    differ or are missing, and prints a line for each file."""
    differing = []
    for name in BASELINE_FILES:
        mine, theirs = os.path.join(outdir, name), os.path.join(baseline, name)
        if not (os.path.exists(mine) and os.path.exists(theirs)):
            print("  %s: missing in %s" % (name, "the run" if not os.path.exists(mine) else "the baseline"))
            differing.append(name)
            continue
        with open(mine, "rb") as a, open(theirs, "rb") as b:
            same = a.read() == b.read()
        print("  %s: %s the baseline's" % (name, "identical to" if same else "DIFFERS FROM"))
        if not same:
            differing.append(name)
    return differing


def run_one(outdir, args, image, kept_against, against, shared):
    """One run of the engine and its scoring. Returns the exit code of this program."""
    os.makedirs(outdir, exist_ok=True)
    command = [EXE, "--stack", STACK, "--selftest", os.path.abspath(image) if image else IMAGE, outdir,
               "--data", os.path.join(outdir, "ngx-data")]
    # a reference run, normal or shared: the reference picture at the reference size and the
    # pass count the mode's baseline was made at, so it is the one held against that baseline
    reference = not image and not any(a in SIZE_OPTIONS for a in args) and "--passes" not in args
    if not image and not any(a in SIZE_OPTIONS for a in args):
        command += REFERENCE_SIZE
    if shared:
        command += ["--passes", "2"]
    command += args
    if against is None:
        baseline = BASELINE_SHARED if shared else BASELINE
        against = baseline if reference and os.path.isdir(baseline) else "none"
        # a run that makes a baseline is not held against itself (the folder may be reached
        # through a junction, so the two paths are compared as folders, not as text)
        if against != "none" and os.path.isdir(outdir) and os.path.samefile(against, outdir):
            against = "none"
        if against == "none" and reference:
            print("run_selftest: no baseline folder to hold the run against, the byte for byte comparison is skipped")
    env = dict(os.environ, LENS_FAST_NR_READS="1")
    out_path = os.path.join(outdir, "engine-stdout.txt")
    err_path = os.path.join(outdir, "engine-stderr.txt")

    # outside the try: a run that never got the lock must not remove another run's
    busy, locked = take_lock()
    t0 = time.time()
    code = None
    ini_before = None
    try:
        if shared:
            # the two keys for this run, the file put back below whatever happens
            with open(STACK_INI, "rb") as f:
                ini_before = f.read()
            with open(STACK_INI, "wb") as f:
                f.write(with_shared_keys(ini_before.decode("utf-8")).encode("utf-8"))
        print("run_selftest: card %d percent busy, %s, running%s"
              % (busy, "lock taken" if locked else "no lock to share",
                 " the shared mode's run, the test stack's ini holds its two keys meanwhile" if shared else ""),
              flush=True)
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            code = subprocess.run(command, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env,
                                  creationflags=NO_WINDOW, timeout=600).returncode
    except subprocess.TimeoutExpired:
        print("run_selftest: the engine did not finish in 600 s and was ended")
        code = None
    finally:
        if ini_before is not None:
            with open(STACK_INI, "wb") as f:
                f.write(ini_before)
            with open(STACK_INI, "rb") as f:
                put_back = f.read() == ini_before
            print("run_selftest: the test stack's ini is put back: %s" % ("yes" if put_back else "NO, LOOK AT IT"))
        if locked:
            try:
                os.remove(LOCK)
            except OSError:
                pass
    print("run_selftest: engine exit code %s after %.1f s%s"
          % (code, time.time() - t0, ", lock removed" if locked else ""))
    for line in tail(out_path, TAIL):
        print("  " + line)
    if code != 0:
        for line in tail(err_path, TAIL):
            print("  stderr: " + line)
        return 2

    # Captured and printed here: a console program started without a window and without
    # handles of its own writes into nothing.
    score = [sys.executable, SCORE, outdir, "--check"]
    if image:
        score += ["--original", os.path.abspath(image)]
    if kept_against:
        score += ["--kept-against", os.path.abspath(kept_against)]
    scored = subprocess.run(score, capture_output=True, text=True, creationflags=NO_WINDOW)
    for line in (scored.stdout + scored.stderr).splitlines():
        print("  " + line)
    differing = []
    if against != "none":
        print("run_selftest: against %s" % against)
        differing = compare_baseline(outdir, os.path.abspath(against))
    print("run_selftest: %s%s, the pictures and scores.json are in %s" %
          ("scores within the targets" if scored.returncode == 0 else "A SCORE IS OFF TARGET",
           "" if against == "none" else (", the baseline's files byte for byte" if not differing
                                         else ", NOT THE BASELINE'S: " + ", ".join(differing)),
           outdir))
    return 0 if scored.returncode == 0 and not differing else 1


def main():
    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        outdir = os.path.abspath(args.pop(0))
    else:
        outdir = os.path.join(FAST, "build", "selftest", time.strftime("%Y%m%d-%H%M%S"))
    image = taken(args, "--image")
    kept_against = taken(args, "--kept-against")
    against = taken(args, "--against")
    against_shared = taken(args, "--against-shared")
    shared = "--shared" in args
    both = "--both" in args
    args = [a for a in args if a not in ("--shared", "--both")]
    if both:
        code = run_one(outdir, list(args), image, kept_against, against, False)
        print("")
        code_shared = run_one(outdir + "-shared", list(args), image, kept_against, against_shared, True)
        print("run_selftest: the normal run %s, the shared run %s"
              % ("held" if code == 0 else "FAILED", "held" if code_shared == 0 else "FAILED"))
        sys.exit(max(code, code_shared))
    if shared and against_shared is not None and against is None:
        against = against_shared
    sys.exit(run_one(outdir, args, image, kept_against, against, shared))


if __name__ == "__main__":
    main()
