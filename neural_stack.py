# DLSS 5 Neural Lens: the stack setup.
# Copyright (C) 2026 Leaps-Bounds
#
# Licensed under the PolyForm Strict License 1.0.0, whose text is in the LICENSE
# file beside this one.
"""Fetch and assemble the DLSS Neural Rendering stack the lens drives.

Nothing of the stack is bundled. Every component is downloaded from the
project that publishes it, into the lens's own folder, and registered for the
current user only, so no elevation is needed and nothing shared with other
software is touched. Licences force this: NVIDIA's runtimes are NVIDIA's, the
RenoDX add-on has no published licence, and a new install gets
ReshadeMotionEstimation (CC BY-NC 4.0) for motion vectors, chosen by
measurement, with VORT (MIT, its motion vector code CC BY-NC 4.0) as the
alternative.

What ends up where. APP is the lens's own folder. TARGET, the stack folder, is
APP itself for the installed program and APP\\stack when run from source:

    TARGET\\lens-presenter.exe                  installed, part of the program; from
                                               source, a copy of the Python running this
    TARGET\\pyvenv.cfg, Lib\\site-packages\\lens-presenter.pth   from source only
    TARGET\\nvngx_dlss.dll                      NVIDIA, via the RHI manifest
    TARGET\\nvngx_dlssnr_real.dll               NVIDIA, the 310.8.SF-v2 Neural Rendering model
    TARGET\\nvngx_dlssnr.dll, nvngx_dlssnr.ini  DLSSNR-Cost-Scaler, the proxy in front of it
    TARGET\\dlss5-feed.addon64                  DLSS5-Feeder
    TARGET\\renodx-dlss5.addon64                RenoDX, via the RHI repository
    TARGET\\reshade-shaders\\Shaders\\...        DLSS5_Feed.fx, DRME, VORT, ReShade headers
    TARGET\\ReShade.ini, ReShadePreset.ini, dlss5-feed.cfg
    TARGET\\install-record.json                 everything above, for uninstall
    TARGET\\fast\\lens-fast.exe                 the fast engine, installed with the program and
                                               never written here. From source the lens runs the
                                               one fast_engine\\build.cmd builds in fast_engine\\bin
    TARGET\\fast\\nvngx_dlssnr.ini              the fast engine's own copy of the proxy's ini,
                                               written beside its exe, in fast_engine\\bin from
                                               source. --uninstall removes it and the engine's logs
    APP\\ReShade\\ReShade64.dll, ReShade64.json, ReShadeApps.ini
    APP\\downloads\\...                           while installing; removed once the self test passes
    HKCU\\SOFTWARE\\Khronos\\Vulkan\\ImplicitLayers\\<APP\\ReShade\\ReShade64.json> = 0

The stack folder has to be the folder lens-presenter.exe is in. ReShade reads
its configuration from the executable's own folder: started from elsewhere with
the stack as its working directory, the layer did not attach, measured.

A DLL the user points at is hash checked and copied in; the record names the
copy, so uninstalling never touches the original.

The layer is registered under a name of its own, VK_LAYER_reshade_neural_lens,
and switches on only in a process that sets ENABLE_VK_LAYER_reshade_neural_lens=1,
which the presenter does for itself. The Vulkan loader loads one layer per name,
so a copy named like a machine wide ReShade would be skipped where one exists,
and this way the two coexist. ReShade itself starts in any program with a
ReShade.ini in its own folder, whatever ReShadeApps.ini says, so without that
switch the lens's copy could start in place of another program's own ReShade.
Releases up to 0.5.1 had no such switch. The lens checks the switch as it
starts, and --verify says whether it is there, see layer_ungated.

The add-on's section of ReShade.ini starts with nothing but its ConfigVersion,
so a new install runs the add-on's own defaults, apart from two that the lens
sets before its presenter starts, where the section holds no value for them:
chained temporal history on, and the Classic codec. A repair keeps that section,
and the lens's own section byte for byte, see step_config.

Command line, for testing and for people who prefer it:

    python neural_stack.py                  install into the default folder
    python neural_stack.py --target D:\\nr   install somewhere else, from source
    python neural_stack.py --dlssnr X --dlss Y   use NVIDIA DLLs you already have (hash checked)
    python neural_stack.py --provider vort  estimate motion vectors with VORT instead of DRME
    python neural_stack.py --verify         only run the self test on an existing stack, and
                                            check that the layer is limited to the lens
    python neural_stack.py --uninstall      remove what the record says was installed

The installer runs this during setup. The lens offers it again if it starts
without a stack, and the Start Menu's stack setup entry runs it on demand.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import winreg
import zipfile

__version__ = "0.7.0"

FROZEN = getattr(sys, "frozen", False)
# Everything lives in the lens's own folder, the one the installer put it in or
# the one this script is in: the stack, the ReShade layer, the downloads while
# they are needed, and (in neural_lens.py) the state and logs. Uninstalling is
# then removing that one folder plus the registry value that names it.
APP_DIR = (os.path.dirname(sys.executable) if FROZEN
           else os.path.dirname(os.path.abspath(__file__)))
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW, for console children of a windowless lens
DEFAULT_TARGET = APP_DIR if FROZEN else os.path.join(APP_DIR, "stack")
LAYER_DIR = os.path.join(APP_DIR, "ReShade")
CACHE_DIR = os.path.join(APP_DIR, "downloads")
LAYER_NAME = "VK_LAYER_reshade_neural_lens"
LAYER_GATE = "ENABLE_VK_LAYER_reshade_neural_lens"     # the switch the layer waits for, see layer_ungated
LAYER_KEY = r"SOFTWARE\Khronos\Vulkan\ImplicitLayers"

# What the download comes to, for the installer's page, the wizard and the
# lens's offer: ReShade's setup 4 MB, NVIDIA's two runtimes 29 and 111 MB as the
# manifest serves them zipped, and everything else under 2 MB together.
DOWNLOAD_MB = 150

RESHADE_VERSION = "6.8.0"
RENODX_VERSION = "5.2.1"
COST_SCALER_VERSION = "1.0.6"
SOURCES = {
    "reshade": "https://reshade.me/downloads/ReShade_Setup_%s_Addon.exe" % RESHADE_VERSION,
    "manifest": "https://raw.githubusercontent.com/RankFTW/RHI/main/dlss_manifest.json",
    "rhi_release": "https://github.com/RankFTW/rhi-repo/releases/download/%s/%s",
    "feeder_api": "https://api.github.com/repos/jlrouzies-fr/DLSS5-Feeder/releases/latest",
    "renodx": ("https://github.com/RankFTW/rhi-repo/releases/download/renodx-dlss5-%s/renodx-dlss5_%s.zip"
               % (RENODX_VERSION, RENODX_VERSION)),
    "cost_scaler": ("https://github.com/xenmods/DLSSNR-Cost-Scaler/releases/download/v%s/DLSSNR-Cost-Scaler-v%s.zip"
                    % (COST_SCALER_VERSION, COST_SCALER_VERSION)),
    "vort": "https://raw.githubusercontent.com/vortigern11/vort_Shaders/main/",
    "vort_api": "https://api.github.com/repos/vortigern11/vort_Shaders/contents/Shaders/Includes",
    # ReshadeMotionEstimation by Jakob Wapenhensch, CC BY-NC 4.0, pinned to its
    # last commit since the repository publishes no releases
    "drme": "https://raw.githubusercontent.com/JakobPCoder/ReshadeMotionEstimation/5fc3f434ba15/",
    "headers": "https://raw.githubusercontent.com/crosire/reshade-shaders/slim/Shaders/",
}
DRME_FILES = ["MotionEstimation.fx", "MotionEstimation.fxh", "MotionEstimationUI.fxh", "MotionVectors.fxh"]
# Which shader estimates motion vectors for the Feed. Measured on scrolling
# text as the partial ink fraction of the page, lower is crisper, at a slow,
# a reading and a fast scroll: DRME 0.075, 0.096, 0.102; VORT 0.099, 0.109,
# 0.106; no provider 0.114, 0.123. DRME is CC BY-NC 4.0, so it may be fetched
# and used with credit in a free tool and is the default. VORT is MIT apart
# from its motion vector code, which builds on DRME and is CC BY-NC 4.0 too,
# and stays as the alternative.
PROVIDERS = {"drme": 0, "vort": 2}
# vort_Motion.fx pulls in most of its Includes folder through nested includes
# (Depth, ColorTex, BlueNoise, Tonemap and more, four of which a hand picked
# list once missed, so the shader failed to compile and the Feed fell back to
# zero motion vectors). The whole folder is fetched, plus the blue noise
# texture the motion pass samples.
VORT_TEXTURES = ["vort_BlueNoise.png"]
HEADER_FILES = ["ReShade.fxh", "ReShadeUI.fxh"]

# The manifest carries no hashes, so these are held here. Every one was measured
# on a working install and its file ran Neural Rendering; a download that
# matches none is refused, not installed. The 310.8.SF-v2 entry accepts two
# known builds: the one the repository serves (version 310.8.SF.0, 165,830,144
# bytes) and an earlier community build (165,840,496 bytes, version 310.8.0.0)
# that many people already hold. The add-on and the Cost Scaler are pinned
# releases, so both their archives and the files taken out of them are checked.
DLSS_VERSION = "310.8.0"
HASHES = {
    "nvngx_dlss.dll": ["c85f971ce023c9f3492fc7455f0b01a24ba18ea39636407a846902c4360b0b7e"],
    "nvngx_dlssnr.dll": {
        "310.8.0": ["e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e"],
        "310.8.SF-v2": ["6eb209e764f39872625debd6abaf45e2bb6322f6f270f781f70c059ae30b3927",
                        "8270b350cd82de5ce89806872cdd6b6a9249b80836b91bbeb3573470744cc206"],
    },
    "renodx-dlss5.zip": ["125506b22edd8e0d6f8117579fe2a516288440fc068a5310680065db5d027129"],
    "renodx-dlss5.addon64": ["a1b78052b58fc285f018362ac8652df8a01d31be9f3ecbb9e31776866ead5887"],
    "cost-scaler.zip": ["525cc45b00dcb1ba03ce6c25905ff02c3ff3458b5e90ebf4138b307f46e13095"],
    # the Feed's zip is normally checked against the SHA-256 its release notes
    # print; these are the ones verified by hand, for a release whose notes
    # leave it out
    "dlss5-feeder.zip": ["0d1deebf531436a6d0914548e450a790aefa53cb4e9f6dfdcd48aff74831cb21"],
    "cost-scaler.dll": ["975b0a063b32463a8812209810f338f3025b47b97d7cb621330c11a7d13898e8"],
}
# One Neural Rendering model serves every RTX card. The SF-v2 build was thought
# to be 40 series only until it was measured running on an RTX 5090 on 2026-09-12:
# feature 18 created and evaluated, and the in-to-out difference matched the
# stock model to within 0.01 at two pinned rates. Its author states it covers
# RTX 20, 30 and 40 and runs identically on 50. The stock 310.8.0 hash is listed
# for identification only: step_nvidia accepts the MODEL's builds and nothing else.
MODEL = "310.8.SF-v2"

# The Cost Scaler is written with its own settings apart from these. The lens
# switches the proxy on for fullscreen and off when windowed, so it starts off.
# Its hotkeys are polled globally, and a desktop program must not answer
# Ctrl+Alt+PageUp in every window. Its depth aware resolve works from the depth
# the Feed synthesises for content that has none, and every measurement of the
# proxy in the lens was taken with it off.
COST_SCALER_SETTINGS = {"EnableProxy": "0", "EnableHotkeys": "0",
                        "EnableDepthAwareResolve": "0", "EnableGovernor": "0"}

RESHADE_INI = """[ADDON]
AddonPath=.\\

[GENERAL]
EffectSearchPaths=.\\reshade-shaders\\Shaders
TextureSearchPaths=.\\reshade-shaders\\Textures
PresetPath=.\\ReShadePreset.ini
NoDebugInfo=1
NoEffectCache=0
NoReloadOnInit=0
PerformanceMode=0
PreprocessorDefinitions=RESHADE_DEPTH_LINEARIZATION_FAR_PLANE=1000.0,RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN=0,RESHADE_DEPTH_INPUT_IS_REVERSED=0,RESHADE_DEPTH_INPUT_IS_LOGARITHMIC=0,DLSS5_MV_PROVIDER=2,V_MV_MODE=1

[INPUT]
ForceShortcutModifiers=1
InputProcessing=2
KeyOverlay=36,0,0,0
KeyScreenshot=44,0,0,0

[OVERLAY]
AutoSavePreset=1
ShowFPS=0
ShowFrameTime=0
TutorialProgress=4

[RenoDX.DLSS5]
ConfigVersion=2

[SCREENSHOT]
SavePath=.\\
FileFormat=1
"""
# The add-on resets its whole section to its built-in defaults when ConfigVersion
# is missing or older than its own, and otherwise fills any key that is absent
# with its default. Measured with 5.2.1 and this section alone: it ran at its
# defaults, wrote back EnableHooks=2, NeuralUplift=1 and NREnableUpscaling=0,
# and feature 18 created and evaluated.
ADDON_SECTION = "[RenoDX.DLSS5]"
# The lens's own section, which the add-on never reads. It holds the values a
# pass from the second on has of its own, which of passes 2 to 4 are ticked
# Same as pass 1, SharedNetwork, whether the passes after the first run through
# the first pass's network on the fast engine, and ScaleChange with Strength,
# whether and how much that engine scales the network's change. The name is
# PASS_SECTION in neural_lens.py and kPassSection in the fast engine. The
# template has no such section, and a new install starts without one, so each
# pass starts out on a network of its own and the change not scaled.
LENS_SECTION = "[NeuralLens.Passes]"
RESHADE_PRESET = """Techniques=vort_MotionEffects@vort_Motion.fx,DLSS5_Feed@DLSS5_Feed.fx
TechniqueSorting=vort_MotionEffects@vort_Motion.fx,DLSS5_Feed@DLSS5_Feed.fx
"""
FEED_CFG = """enabled=1
mode=2
hdr=-1
depth_inverted=-1
flags=-1
reset_every=0
warmup_rebuild=180
rebuild=0
log_frames=3
create_delay=60
preset=6
mv_scale_x=1.000
mv_scale_y=1.000
"""


class StackError(Exception):
    pass


# ---------------------------------------------------------------- helpers
def say(log, text):
    if log:
        log(text)
    else:
        print(text, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, log=None, label=None):
    """Download url to dest, resuming nothing, reporting progress in MB."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    label = label or os.path.basename(dest)
    req = urllib.request.Request(url, headers={"User-Agent": "neural-lens-stack/" + __version__})
    last = [0.0]
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if time.perf_counter() - last[0] > 1.0:
                        last[0] = time.perf_counter()
                        if total:
                            say(log, "    %s  %d of %d MB" % (label, done >> 20, total >> 20))
                        else:
                            say(log, "    %s  %d MB" % (label, done >> 20))
            os.replace(dest + ".part", dest)
            return dest
        except Exception as exc:
            if attempt == 2:
                raise StackError("could not download %s: %s" % (url, exc))
            say(log, "    retrying %s (%s)" % (label, exc))
            time.sleep(2)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "neural-lens-stack/" + __version__,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def feeder_hash_in_notes(notes, asset_name):
    """The SHA-256 the Feed's release notes print for this zip, or None."""
    m = re.search(r"SHA-256 of `?%s`?\s*:\s*`?([0-9A-Fa-f]{64})" % re.escape(asset_name), notes or "")
    return m.group(1).lower() if m else None


def verify_feeder_zip(path, asset_name, notes):
    """Refuse a Feed zip unless its hash is the one its release notes print, or
    one this file knows. Fake copies of the Feed are circulating, so a zip that
    matches neither is removed and named, not installed."""
    got = sha256(path).lower()
    want = feeder_hash_in_notes(notes, asset_name)
    if got == want or got in HASHES.get("dlss5-feeder.zip", []):
        return path
    try:
        os.remove(path)
    except OSError:
        pass
    if want is None:
        raise StackError("%s was not installed. Its release notes print no SHA-256 for it, and its hash "
                         "is not one this program knows.\n  got  %s\nThe lens's next release will carry the "
                         "hash once the zip is verified." % (asset_name, got))
    raise StackError("%s was not installed. It does not match the SHA-256 its release notes print.\n"
                     "  got    %s\n  notes  %s\nEither the download was tampered with or the release was "
                     "replaced. Nothing was changed." % (asset_name, got, want))


def check_hash(path, want, label):
    """Refuse a file whose hash is not one of the known ones, and remove it."""
    got = sha256(path)
    if got not in want:
        try:
            os.remove(path)
        except OSError:
            pass
        raise StackError("%s matches no known hash\n  got      %s\n  known    %s\nNot installed. The "
                         "project may have replaced the file; the lens's release notes will say when a "
                         "new one is verified." % (label, got, ", ".join(want)))
    return path


def set_ini_values(text, values):
    """Set each key = value line of an ini's text, wherever the key is, and keep
    everything else as it was, comments included."""
    for key, value in values.items():
        text, n = re.subn(r"(?im)^([ \t]*%s[ \t]*=)[^\r\n]*" % re.escape(key),
                          lambda m: m.group(1) + " " + value, text)
        if not n:
            raise StackError("the Cost Scaler's ini has no %s setting" % key)
    return text


def gpu_supported():
    """(True, capability) when Neural Rendering can run here, else (False, why).

    One model serves every generation, so the question is not which card this
    is but whether it is one at all. Compute capability 7.5 is Turing, the
    first RTX line and where Neural Rendering starts; a machine with no
    nvidia-smi has no NVIDIA driver. Capability is steadier than marketing
    names, which fragment into "RTX 4090 Laptop GPU" and "RTX 4000 Ada
    Generation".
    """
    smi = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    if not os.path.isfile(smi):
        smi = "nvidia-smi"
    try:
        # no console window for the child: without this the first console
        # program started while a shown topmost Tk window is up took 5 seconds
        # under pythonw and the frozen exe, which showed as a blank setup window
        out = subprocess.run([smi, "--query-gpu=compute_cap", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20,
                             stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).stdout
    except Exception:
        return False, "no NVIDIA driver here (nvidia-smi would not run)"
    caps = [c.strip() for c in out.splitlines() if c.strip()]
    if not caps:
        return False, "the driver reported no compute capability"
    try:
        cap = float(caps[0])
    except ValueError:
        return False, "the driver reported %r, which is not a capability" % caps[0]
    if cap < 7.5:
        return False, ("compute capability %s is older than the RTX 20 series, and "
                       "Neural Rendering needs the tensor cores an RTX card has" % caps[0])
    return True, caps[0]


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    return path


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def presenter_command(target):
    """How to start the presenter in a stack folder: the program itself when
    installed, and from source the interpreter's copy, which has a pyvenv.cfg
    beside it, with the script."""
    exe = os.path.join(target, "lens-presenter.exe")
    if FROZEN or not os.path.isfile(os.path.join(target, "pyvenv.cfg")):
        return [exe]
    return [exe, os.path.join(APP_DIR, "lens_presenter.py")]


def fast_engine_dirs(target):
    """The folders a lens with this stack folder looks in for the fast engine,
    lens-fast.exe, in the order neural_lens.py's _find_fast_exe looks: the
    stack's fast folder, where an install has it, then from source the folder
    fast_engine\\build.cmd builds it into. The engine writes its own copy of
    the proxy's ini beside its exe."""
    dirs = [os.path.join(target, "fast")]
    if not FROZEN:
        dirs.append(os.path.join(APP_DIR, "fast_engine", "bin"))
    return dirs


def fast_engine_line(target):
    """One line for the setup's summary and its check that says whether the
    fast engine is there. Without it a fullscreen lens runs on the presenter,
    the ReShade engine, as a windowed lens does."""
    for d in fast_engine_dirs(target):
        exe = os.path.join(d, "lens-fast.exe")
        if os.path.isfile(exe):
            return "    fast engine: found, %s" % exe
    if FROZEN:
        line = ("    fast engine: not found in %s, so a fullscreen lens uses the ReShade engine."
                % os.path.join(target, "fast"))
        # the installer puts it in the program's folder only, so a reinstall mends
        # only the stack that is that folder
        if same_path(target, APP_DIR):
            line += " Installing the lens again puts it back."
        return line
    return ("    fast engine: not built, so a fullscreen lens uses the ReShade engine, as a windowed "
            "lens does. fast_engine\\build.cmd builds it. It needs Visual Studio 2022 or later, or "
            "its Build Tools, with the workload \"Desktop development with C++\" and Windows SDK "
            "10.0.26100 or later.")


# ---------------------------------------------------------------- steps
class Install:
    def __init__(self, target=DEFAULT_TARGET, dlssnr=None, dlss=None, log=None, provider="drme"):
        self.target = os.path.abspath(target)
        self.given = {"nvngx_dlssnr.dll": dlssnr, "nvngx_dlss.dll": dlss}
        self.log = log
        self.provider = provider if provider in PROVIDERS else "drme"
        self.record = {"version": __version__, "target": self.target, "layer_dir": LAYER_DIR,
                       "files": [], "registry": [], "components": {}}

    def say(self, text):
        say(self.log, text)

    def add(self, path):
        path = os.path.abspath(path)
        if path not in self.record["files"]:
            self.record["files"].append(path)
        return path

    def run(self):
        if FROZEN and not same_path(self.target, APP_DIR):
            raise StackError("the installed lens keeps its stack in its own folder, %s, beside "
                             "lens-presenter.exe; --target is for running from source" % APP_DIR)
        self.retire_old_stack()
        os.makedirs(self.target, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.say("Installing the Neural Rendering stack into %s" % self.target)
        self.step_presenter()
        self.step_reshade()
        self.step_nvidia()
        self.step_cost_scaler()
        self.step_feeder()
        self.step_renodx()
        self.step_shaders()
        self.step_config()
        self.step_layer()
        self.write_record()
        self.say("")
        self.say("Installed. Running the self test.")
        ok, detail = verify(self.target, log=self.log)
        self.say(detail)
        self.say(layer_line(layer_ungated()))
        self.say(fast_engine_line(self.target))
        if ok:
            # the downloads served their purpose; a failed run keeps them so a
            # retry can be looked into with them still there
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        return ok

    def retire_old_stack(self):
        """Take out a stack that 0.1.0 assembled, which held mpv.

        Installed, 0.1.0 kept its stack in APP\\stack; from source it used the
        same stack folder this installs into. Its record lists what it wrote.
        NVIDIA's two runtimes and ReShade's DLL are kept where this install
        wants them when they check out, so they are not downloaded again, and
        the rest goes the way the record's uninstall takes it, the layer
        registration and the allow list that named mpv included. Installed,
        whatever is still in APP\\stack after that goes too: the folder
        belonged to the setup.
        """
        old = os.path.join(APP_DIR, "stack") if FROZEN else self.target
        try:
            with open(os.path.join(old, "install-record.json"), encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            return
        if "mpv" not in record.get("components", {}):
            return
        self.say("Removing the stack an earlier version assembled, which held mpv")
        os.makedirs(self.target, exist_ok=True)
        model = HASHES["nvngx_dlssnr.dll"][MODEL]
        moves = (("nvngx_dlss.dll", "nvngx_dlss.dll", HASHES["nvngx_dlss.dll"]),
                 ("nvngx_dlssnr_real.dll", "nvngx_dlssnr_real.dll", model),
                 ("nvngx_dlssnr.dll", "nvngx_dlssnr_real.dll", model))
        keep = []
        for name, dest_name, want in moves:
            src, dest = os.path.join(old, name), os.path.join(self.target, dest_name)
            try:
                if not os.path.isfile(src) or sha256(src) not in want:
                    continue
                if same_path(src, dest):
                    keep.append(dest)
                elif not os.path.isfile(dest):
                    os.replace(src, dest)
                    keep.append(dest)
                else:
                    continue
                self.say("    kept %s" % dest_name)
            except OSError:
                pass
        if record.get("components", {}).get("reshade") == RESHADE_VERSION:
            keep.append(os.path.join(LAYER_DIR, "ReShade64.dll"))
        uninstall(old, log=self.log, keep=keep)
        if FROZEN:
            shutil.rmtree(old, ignore_errors=True)

    # the presenter, in the stack folder beside the ReShade.ini that ReShade looks for
    def step_presenter(self):
        """Installed, lens-presenter.exe is part of the program and already in
        its folder, which is the stack folder. From source it is a copy of the
        Python running this, which runs lens_presenter.py beside this file: a
        pyvenv.cfg beside the copy points it at this Python's library, and a
        .pth file at the packages this Python sees, a virtual environment's
        included. Its packages are checked first, before anything is downloaded.
        """
        exe = os.path.join(self.target, "lens-presenter.exe")
        if FROZEN:
            if not os.path.isfile(exe):
                raise StackError("lens-presenter.exe is missing from %s; reinstall the lens" % self.target)
            self.say("presenter: lens-presenter.exe, part of the lens")
            return
        import importlib.util
        import site
        need = {"glfw": "glfw", "vulkan": "vulkan", "numpy": "numpy", "windows_capture": "windows-capture"}
        missing = [pip for mod, pip in need.items() if importlib.util.find_spec(mod) is None]
        if missing:
            raise StackError("the presenter needs %s for this Python first:\n  pip install %s"
                             % (", ".join(missing), " ".join(missing)))
        base = os.path.dirname(getattr(sys, "_base_executable", None) or sys.executable)
        python = os.path.join(base, "python.exe")
        if not os.path.isfile(python):
            raise StackError("there is no python.exe beside %s to copy as the presenter" % base)
        shutil.copy2(python, exe)
        self.add(exe)
        self.add(write_text(os.path.join(self.target, "pyvenv.cfg"),
                            "home = %s\ninclude-system-site-packages = true\nversion = %d.%d\n"
                            % (base, sys.version_info[0], sys.version_info[1])))
        paths = [p for p in site.getsitepackages() + [site.getusersitepackages()] if os.path.isdir(p)]
        self.add(write_text(os.path.join(self.target, "Lib", "site-packages", "lens-presenter.pth"),
                            "\n".join(paths) + "\n"))
        self.say("presenter: a copy of %s, running lens_presenter.py" % python)

    # ReShade: the DLL is read straight out of the setup exe, which is a zip, so
    # nothing of ReShade's is executed here. The layer manifest is written below.
    def step_reshade(self):
        dll = os.path.join(LAYER_DIR, "ReShade64.dll")
        if os.path.isfile(dll):
            self.say("ReShade: layer already present, keeping it")
        else:
            setup = fetch(SOURCES["reshade"], os.path.join(CACHE_DIR, "ReShade_Setup_%s_Addon.exe" % RESHADE_VERSION),
                          self.log, "ReShade " + RESHADE_VERSION)
            os.makedirs(LAYER_DIR, exist_ok=True)
            with zipfile.ZipFile(setup) as z:
                with open(dll, "wb") as f:
                    f.write(z.read("ReShade64.dll"))
            self.say("ReShade: %s extracted" % RESHADE_VERSION)
        self.add(dll)
        self.record["components"]["reshade"] = RESHADE_VERSION
        manifest = {
            "file_format_version": "1.0.0",
            "layer": {
                "name": LAYER_NAME,
                "type": "GLOBAL",
                "library_path": ".\\ReShade64.dll",
                "api_version": "1.3.268",
                "implementation_version": "1",
                "description": "ReShade, installed for the Neural Lens's presenter only",
                "device_extensions": [{"name": "VK_EXT_tooling_info", "spec_version": "1",
                                       "entrypoints": ["vkGetPhysicalDeviceToolPropertiesEXT"]}],
                "disable_environment": {"DISABLE_VK_LAYER_reshade_neural_lens": "1"},
                # on only where this is set, which the presenter does for itself, so no
                # other program gets the lens's ReShade, see layer_ungated
                "enable_environment": {LAYER_GATE: "1"},
            },
        }
        with open(os.path.join(LAYER_DIR, "ReShade64.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
        self.add(os.path.join(LAYER_DIR, "ReShade64.json"))
        # ReShade's own setup program keeps this list, and ReShade does not read it
        self.add(write_text(os.path.join(LAYER_DIR, "ReShadeApps.ini"),
                            "Apps=%s\n" % os.path.join(self.target, "lens-presenter.exe")))

    # NVIDIA: both runtimes, hash checked. One model serves every RTX card, and
    # it goes in as nvngx_dlssnr_real.dll, behind the Cost Scaler.
    def step_nvidia(self):
        ok, detail = gpu_supported()
        if not ok:
            raise StackError("Neural Rendering needs an NVIDIA RTX card: %s" % detail)
        model = MODEL
        self.record["components"]["gpu"] = detail
        self.record["components"]["dlssnr"] = model
        self.record["components"]["dlss"] = DLSS_VERSION
        self.say("NVIDIA: compute capability %s, Neural Rendering model %s" % (detail, model))
        manifest = {}

        # The manifest's version names are labels its maintainer renames: on
        # 2026-09-24 310.8.SF-v2 became "310.8.2 (20/30/40/50)" while the file
        # stayed where it was. So an entry is found by the release tag in its
        # link first and by its name second, and with neither, or no manifest
        # at all, the release is fetched straight from the repository. The
        # hash check below decides whether a download is installed.
        def url_for(key, version):
            tag = "%s-%s" % (key, version)
            if not manifest:
                try:
                    manifest.update(fetch_json(SOURCES["manifest"]))
                except Exception as exc:
                    self.say("manifest unreachable (%s), fetching %s from its release" % (exc, tag))
            entries = manifest.get(key, [])
            for entry in entries:
                if "/%s/" % tag in entry.get("url", ""):
                    return entry["url"]
            for entry in entries:
                if entry.get("version") == version:
                    return entry["url"]
            return SOURCES["rhi_release"] % (tag, "nvngx_%s_%s.zip" % (key, version))

        wanted = (("nvngx_dlss.dll", "nvngx_dlss.dll", HASHES["nvngx_dlss.dll"], "dlss", DLSS_VERSION),
                  ("nvngx_dlssnr.dll", "nvngx_dlssnr_real.dll", HASHES["nvngx_dlssnr.dll"][model],
                   "dlssnr", model))
        for name, dest_name, want, key, version in wanted:
            dest = os.path.join(self.target, dest_name)
            given = self.given.get(name)
            if given:
                got = sha256(given)
                if got not in want:
                    raise StackError("%s is not a %s build this stack knows\n"
                                     "  yours    %s\n  known    %s" % (given, version, got, ", ".join(want)))
                shutil.copy2(given, dest)
                self.say("%s: using your copy, hash verified" % name)
            elif os.path.isfile(dest) and sha256(dest) in want:
                self.say("%s: already present and verified" % dest_name)
            else:
                z = fetch(url_for(key, version), os.path.join(CACHE_DIR, "%s_%s.zip" % (key, version)),
                          self.log, "%s %s" % (name, version))
                with zipfile.ZipFile(z) as zf:
                    member = next(i for i in zf.infolist() if i.filename.lower().endswith(name))
                    with open(dest + ".part", "wb") as f:
                        f.write(zf.read(member))
                got = sha256(dest + ".part")
                if got not in want:
                    os.remove(dest + ".part")
                    raise StackError("%s downloaded from the manifest matches no known hash\n"
                                     "  got      %s\n  known    %s\nNot installed. The repository may "
                                     "have published a new build; the lens's release notes will say when "
                                     "one is verified." % (name, got, ", ".join(want)))
                os.replace(dest + ".part", dest)
                self.say("%s: downloaded, hash verified" % dest_name)
            self.add(dest)

    # DLSSNR-Cost-Scaler: the proxy as nvngx_dlssnr.dll, forwarding to the model
    def step_cost_scaler(self):
        name = "DLSSNR-Cost-Scaler-v%s.zip" % COST_SCALER_VERSION
        z = fetch(SOURCES["cost_scaler"], os.path.join(CACHE_DIR, name), self.log,
                  "DLSSNR Cost Scaler " + COST_SCALER_VERSION)
        check_hash(z, HASHES["cost-scaler.zip"], name)
        dest = os.path.join(self.target, "nvngx_dlssnr.dll")
        ini_path = os.path.join(self.target, "nvngx_dlssnr.ini")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            dll = next((n for n in names if n.lower().endswith("nvngx_dlssnr.dll")), None)
            ini = next((n for n in names if n.lower().endswith("nvngx_dlssnr.ini")), None)
            if not dll or not ini:
                raise StackError("the Cost Scaler's archive holds no nvngx_dlssnr.dll or nvngx_dlssnr.ini")
            self._extract(zf, dll, dest + ".part")
            check_hash(dest + ".part", HASHES["cost-scaler.dll"], "the Cost Scaler's nvngx_dlssnr.dll")
            os.replace(dest + ".part", dest)
            self.add(dest)
            if os.path.isfile(ini_path):
                kept = " Its settings were already there and are kept."
            else:
                # latin-1 both ways, so every byte of its comments survives
                text = set_ini_values(zf.read(ini).decode("latin-1"), COST_SCALER_SETTINGS)
                with open(ini_path, "wb") as f:
                    f.write(text.encode("latin-1"))
                kept = ""
            self.add(ini_path)
        self.record["components"]["cost_scaler"] = COST_SCALER_VERSION
        self.say("DLSSNR Cost Scaler %s: in front of the model, off until the lens asks for it.%s"
                 % (COST_SCALER_VERSION, kept))

    def step_feeder(self):
        rel = fetch_json(SOURCES["feeder_api"])
        asset = next((a for a in rel.get("assets", []) if re.match(r"^DLSS5-Feeder-.*\.zip$", a["name"])), None)
        if not asset:
            raise StackError("no DLSS5-Feeder zip in its latest release")
        self.record["components"]["feeder"] = rel.get("tag_name")
        z = fetch(asset["browser_download_url"], os.path.join(CACHE_DIR, asset["name"]), self.log,
                  "DLSS5-Feeder " + rel.get("tag_name", ""))
        # the maintainer prints each zip's SHA-256 in the release notes, and fake
        # copies of the Feed exist, so the zip must match that line or a hash
        # this file knows before anything is taken out of it
        verify_feeder_zip(z, asset["name"], rel.get("body"))
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            addon = next(n for n in names if n.lower().endswith("dlss5-feed.addon64"))
            fx = next(n for n in names if n.lower().endswith("dlss5_feed.fx"))
            self.add(self._extract(zf, addon, os.path.join(self.target, "dlss5-feed.addon64")))
            self.add(self._extract(zf, fx, os.path.join(self.target, "reshade-shaders", "Shaders", "DLSS5_Feed.fx")))
        self.say("DLSS5-Feeder: %s" % rel.get("tag_name"))

    def step_renodx(self):
        name = "renodx-dlss5_%s.zip" % RENODX_VERSION
        z = fetch(SOURCES["renodx"], os.path.join(CACHE_DIR, name), self.log, "RenoDX DLSS 5 " + RENODX_VERSION)
        check_hash(z, HASHES["renodx-dlss5.zip"], name)
        dest = os.path.join(self.target, "renodx-dlss5.addon64")
        with zipfile.ZipFile(z) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith(".addon64")), None)
            if not member:
                raise StackError("the RenoDX archive holds no add-on")
            self._extract(zf, member, dest + ".part")
        check_hash(dest + ".part", HASHES["renodx-dlss5.addon64"], "the RenoDX DLSS 5 add-on")
        os.replace(dest + ".part", dest)
        self.add(dest)
        self.record["components"]["renodx"] = RENODX_VERSION
        self.say("RenoDX DLSS 5 add-on: %s, hash verified" % RENODX_VERSION)

    def step_shaders(self):
        base = os.path.join(self.target, "reshade-shaders", "Shaders")
        textures = os.path.join(self.target, "reshade-shaders", "Textures")
        self.add(fetch(SOURCES["vort"] + "Shaders/vort_Motion.fx", os.path.join(base, "vort_Motion.fx"),
                       self.log, "vort_Motion.fx"))
        includes = [e["name"] for e in fetch_json(SOURCES["vort_api"])
                    if e.get("type") == "file" and e["name"].startswith("vort_") and e["name"].endswith(".fxh")]
        if len(includes) < 10:
            raise StackError("the VORT repository listed only %d include files" % len(includes))
        for name in includes:
            self.add(fetch(SOURCES["vort"] + "Shaders/Includes/" + name, os.path.join(base, "Includes", name),
                           self.log, name))
        for name in VORT_TEXTURES:
            self.add(fetch(SOURCES["vort"] + "Textures/" + name, os.path.join(textures, name), self.log, name))
        for name in HEADER_FILES:
            self.add(fetch(SOURCES["headers"] + name, os.path.join(base, name), self.log, name))
        self.say("shaders: VORT (MIT, its motion vector code CC BY-NC 4.0) fetched as the alternative "
                 "estimator, %d includes and its texture, and ReShade's headers" % len(includes))
        for name in DRME_FILES:
            self.add(fetch(SOURCES["drme"] + name, os.path.join(base, name), self.log, name))
        self.say("shaders: ReshadeMotionEstimation by Jakob Wapenhensch (CC BY-NC 4.0)")
        self.record["components"]["motion_vectors"] = {"drme": "ReshadeMotionEstimation", "vort": "VORT"}[self.provider]
        self.say("motion vectors: %s will provide them" % self.record["components"]["motion_vectors"])

    def step_config(self):
        # the templates are written for VORT; the chosen provider is substituted
        ini, preset = RESHADE_INI, RESHADE_PRESET
        if self.provider == "drme":
            ini = ini.replace("DLSS5_MV_PROVIDER=2,V_MV_MODE=1", "DLSS5_MV_PROVIDER=0")
            preset = preset.replace("vort_MotionEffects@vort_Motion.fx", "DRME@MotionEstimation.fx")
        path = os.path.join(self.target, "ReShade.ini")
        kept = self._addon_section(path)
        if kept:
            ini = ini.replace(ADDON_SECTION + "\nConfigVersion=2\n",
                              ADDON_SECTION + "\n" + "\n".join(kept) + "\n")
            self.say("config: the Neural Rendering add-on's settings in the existing ReShade.ini are kept")
        # the template goes in as write_text writes it, and the lens's own
        # section of the existing file after it, byte for byte, see _lens_section
        data = ini.replace("\n", "\r\n").encode("utf-8")
        own = self._lens_section(path)
        if own:
            data += b"\r\n" + own
            self.say("The lens's own section of the existing ReShade.ini, with the values the passes from the "
                     "second on have of their own, is kept as it was")
        self.add(write_bytes(path, data))
        self.add(write_text(os.path.join(self.target, "ReShadePreset.ini"), preset))
        self.add(write_text(os.path.join(self.target, "dlss5-feed.cfg"), FEED_CFG))
        self.say("config: ReShade, the preset and the feed written")

    @staticmethod
    def _addon_section(path):
        """The lines of the add-on's section in an existing ReShade.ini, or None."""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            return None
        out, inside = [], False
        for line in lines:
            bare = line.strip()
            if bare.startswith("["):
                if inside:
                    break
                inside = bare.lower() == ADDON_SECTION.lower()
                continue
            if inside and bare:
                out.append(bare)
        return out or None

    @staticmethod
    def _lens_section(path):
        """The lens's own section in an existing ReShade.ini as the file has it,
        or b"" where the file has none or cannot be read. That is each line from
        the line with the section's name to its last line that is not blank,
        with the line's own ending, so the values come back byte for byte. A
        line that starts with a bracket names a section, by what follows the
        bracket up to the first closing one, or to the line's end where there is
        none, without the spaces around it and whatever its case. Windows reads
        the name that way for the fast engine, and the lens finds the section
        that way when it writes to it, so a name line written by hand with a
        space or a comment in it is kept as well, and after a repair the engine
        and the lens read what they read before. A file that has the section
        more than once gives each, in the file's order, with a blank line
        between them."""
        try:
            with open(path, "rb") as f:
                lines = f.read().splitlines(True)
        except OSError:
            return b""
        name = LENS_SECTION.strip("[]").lower().encode("ascii")
        found, inside = [], None
        for line in lines:
            bare = line.strip()
            if bare.startswith(b"["):
                end = bare.find(b"]")
                title = bare[1:] if end < 0 else bare[1:end]
                inside = [line] if title.strip().lower() == name else None
                if inside is not None:
                    found.append(inside)
            elif inside is not None:
                inside.append(line)
        for section in found:
            while len(section) > 1 and not section[-1].strip():
                section.pop()       # the blank lines before the next section
        return b"\r\n".join(b"".join(section) for section in found)

    def step_layer(self):
        manifest = os.path.join(LAYER_DIR, "ReShade64.json")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, manifest, 0, winreg.REG_DWORD, 0)
        self.record["registry"].append(manifest)
        self.say("Vulkan layer: registered for this user as %s" % LAYER_NAME)

    def write_record(self):
        path = os.path.join(self.target, "install-record.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.record, f, indent=1)

    @staticmethod
    def _extract(zf, member, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(zf.read(member))
        return dest


# ---------------------------------------------------------------- the layer's limit
def layer_ungated():
    """The descriptions of the lens's layer, registered for this user, that
    would switch it on in every program: the paths of those that name the
    lens's layer and have no enable_environment for LAYER_GATE. Empty where
    every one waits for the presenter to ask, or none is registered.

    The layer is ReShade, and it belongs in the lens's own presenter alone. A
    description without the switch, which 0.5.1 wrote and an update with the
    stack setup left out keeps, has the Vulkan loader put ReShade into every
    program that uses Vulkan, games included. step_reshade writes the switch.
    The loader passes over a value that is not 0, and so does this. Only the
    registry and the descriptions are read. The lens asks this as it starts,
    and --verify says what it found."""
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    name, data, kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if kind != winreg.REG_DWORD or data != 0:
                    continue
                try:
                    with open(name, encoding="utf-8-sig") as f:
                        described = json.load(f)
                    layers = described.get("layers") or [described.get("layer") or {}]
                except (OSError, ValueError, AttributeError):
                    continue
                for layer in layers:
                    if isinstance(layer, dict) and layer.get("name") == LAYER_NAME and LAYER_GATE not in (
                            layer.get("enable_environment") or {}):
                        found.append(name)
                        break
    except OSError:
        pass
    return found


def layer_line(ungated):
    """The self test's line on the layer's limit, for layer_ungated's answer.
    The setup writes only this copy's own description, LAYER_DIR's, so a path
    of another copy of the lens is said to be that copy's, which this setup
    does not change, and where both are listed, the line names which one the
    setup writes."""
    if not ungated:
        return "    Vulkan layer: on only where the lens's presenter asks for it"
    own = os.path.normcase(os.path.abspath(os.path.join(LAYER_DIR, "ReShade64.json")))
    mine = [p for p in ungated if os.path.normcase(os.path.abspath(p)) == own]
    others = [p for p in ungated if p not in mine]
    line = ("    Vulkan layer: NOT LIMITED TO THE LENS. %s %s no enable_environment, so Vulkan loads the lens's "
            "ReShade into every program that uses Vulkan, games included."
            % (" and ".join(ungated), "has" if len(ungated) == 1 else "have"))
    if mine:
        line += (" Running the stack setup again writes the limit%s."
                 % (" into this copy's own description, %s" % mine[0] if others else ""))
    if others:
        line += (" %s %s to another copy of the lens, and the stack setup of this copy does not change %s."
                 % (" and ".join(others), "belongs" if len(others) == 1 else "belong",
                    "it" if len(others) == 1 else "them"))
    return line


def layer_unregister(path):
    """Delete this user's registration of a description of the lens's layer,
    the ImplicitLayers value named by its path, for one that another copy of
    the lens registered, which the lens asks about as it starts. Only a value
    whose description names LAYER_NAME is deleted, so nothing but the lens's
    own layer is touched. Returns whether it went."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            described = json.load(f)
        layers = described.get("layers") or [described.get("layer") or {}]
    except (OSError, ValueError, AttributeError):
        return False
    if not any(isinstance(layer, dict) and layer.get("name") == LAYER_NAME for layer in layers):
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, path)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- verify
def runs_elevated():
    """Whether this process runs at high integrity or above, as a program run as
    administrator does. The Vulkan loader makes the same test in the program it
    loads into, and there it reads no layer registered under HKEY_CURRENT_USER,
    the only place the setup registers the lens's, so a presenter this process
    starts gets no ReShade. IsUserAnAdmin, which agrees for an administrator run
    as administrator, answers when the token cannot be read."""
    import ctypes
    from ctypes import wintypes
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
        advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD))
        advapi32.GetSidSubAuthorityCount.argtypes = (ctypes.c_void_p,)
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        advapi32.GetSidSubAuthority.argtypes = (ctypes.c_void_p, wintypes.DWORD)
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))  # TokenIntegrityLevel
            label = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, 25, label, size, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            sid = ctypes.cast(label, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_MANDATORY_LABEL.Label.Sid
            if not sid:
                raise OSError("the token has no integrity label")
            last = advapi32.GetSidSubAuthorityCount(sid)[0] - 1
            return advapi32.GetSidSubAuthority(sid, last)[0] >= 0x3000  # SECURITY_MANDATORY_HIGH_RID
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False


def verify(target, log=None, seconds=9.0):
    """Run the presenter on a still and read what ReShade says.

    The presenter is what the lens runs, so the self test runs it too, on its
    pattern source rather than a capture: a still with detail in a 960x540
    window at the top left of the primary monitor, long enough for the Feed's
    warm up and the first Neural Rendering evaluations. The verdict is read
    from ReShade.log and the Feed's log.
    """
    cmd = presenter_command(target)
    if not os.path.isfile(cmd[0]):
        return False, "FAIL: no lens-presenter.exe in %s" % target
    logfile = os.path.join(target, "ReShade.log")
    proxy_log = os.path.join(target, "nvngx_dlssnr_proxy.log")
    for stale in (logfile, proxy_log):
        try:
            os.remove(stale)
        except OSError:
            pass
    env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
    err = tempfile.TemporaryFile()
    started = time.time()
    proc = subprocess.Popen(cmd + ["--source", "pattern", "--at", "40", "40", "--size", "960", "540",
                                   "--title", "NeuralLensSelfTest"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, cwd=target,
                            env=env, text=True, creationflags=NO_WINDOW)
    said = []

    def drain():
        for line in proc.stdout:
            said.append(line.rstrip())

    threading.Thread(target=drain, daemon=True).start()
    say(log, "    self test: a presenter window at the top left for %.0f seconds" % seconds)
    while time.time() - started < seconds and proc.poll() is None:
        time.sleep(0.2)
    early = proc.poll()
    try:
        proc.stdin.write("quit\n")
        proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    if early is not None:
        err.seek(0)
        tail = err.read().decode("utf-8", "replace").strip()[-900:]
        return False, ("FAIL: the presenter stopped after %.0f seconds with exit code %s.\n%s"
                       % (time.time() - started, early, tail or "\n".join(said[-5:]) or "It printed nothing."))
    try:
        text = open(logfile, encoding="utf-8", errors="replace").read()
    except OSError:
        if runs_elevated():
            # the presenter runs with this process's rights, so the layer this user has
            # registered never loads in it, and the checks below would all hold
            return False, ("FAIL: ReShade wrote no log at %s, so it did not start in the presenter. This setup "
                           "runs as administrator, and in a program that runs as administrator Vulkan reads no "
                           "layer registered for one user. Run the stack setup again without administrator "
                           "rights. In an account where every program runs as administrator, as with User "
                           "Account Control fully off, ReShade cannot start in the lens." % logfile)
        # ReShade 6.8 never reads ReShadeApps.ini. The layer loads where the variable its
        # description's enable_environment names is set, and ReShade then starts only
        # beside a ReShade.ini, see layer_ungated
        return False, ("FAIL: ReShade wrote no log at %s, so it did not start in the presenter. Check that the "
                       "layer's description %s is registered for this user under HKEY_CURRENT_USER\\%s with the "
                       "value 0 and carries enable_environment with %s, the switch the presenter sets for itself. "
                       "Check too that ReShade.ini is beside %s, since ReShade starts only where it finds one."
                       % (logfile, os.path.join(LAYER_DIR, "ReShade64.json"), LAYER_KEY, LAYER_GATE, cmd[0]))
    created = "feature=18" in text and "feature 18 created" in text
    # the add-on logs the 1st, 60th and 600th evaluation and none after them,
    # counting its pre-SR and inline evaluations apart, so a session that went
    # from pre-SR to inline can log up to six, and the highest count it logged is
    # how many there were at least
    counts = [int(c) for c in re.findall(r"feature 18 evaluation succeeded \(count=(\d+)", text)]
    evaluated = max(counts) if counts else len(re.findall(r"feature 18 evaluation succeeded", text))
    failed = re.search(r"feature 18 create failed with (0x[0-9a-fA-F]+)", text)
    addons = ("DLSS 5 Neural Rendering" in text, "DLSS 5 Feed" in text)
    lines = ["    ReShade attached: yes",
             "    add-ons loaded: Neural Rendering %s, Feed %s" % tuple("yes" if a else "NO" for a in addons)]
    # the Cost Scaler logs as it loads, whether it is switched on or off
    try:
        proxy = open(proxy_log, encoding="utf-8", errors="replace").read()
        lines.append("    Cost Scaler: %s" % ("loaded, in front of the model" if "Loaded real module successfully"
                                                 in proxy else "its log says it did not load the model"))
    except OSError:
        if os.path.isfile(os.path.join(target, "nvngx_dlssnr_real.dll")):
            lines.append("    Cost Scaler: it wrote no log")
    # A still needs no motion vectors, so Neural Rendering can run with the
    # provider missing and nobody would know until something moved. The Feed
    # says which provider it found; read that rather than trust the picture.
    try:
        feed = open(os.path.join(target, "dlss5-feed.log"), encoding="utf-8", errors="replace").read()
        # the Feed's "effects:" line names the provider it found; its warnings
        # mention the setting too, "use another provider (VORT:
        # DLSS5_MV_PROVIDER=2)", so they are not the line to read
        prov = [l for l in feed.splitlines() if "effects:" in l and "DLSS5_MV_PROVIDER=" in l]
        last = prov[-1].split("DLSS5_MV_PROVIDER=", 1)[-1] if prov else ""
        if not prov or "-> none" in last:
            lines.append("    motion vectors: NO PROVIDER, so anything that moves would smear. "
                         "The motion vector shader did not compile or was not found: %s" % (last[:90] or "no Feed log"))
            return False, "\n".join(lines)
        name = re.search(r"->\s*([^(,]+)", last)
        name = name.group(1).strip() if name else last.split(",", 1)[0][:60]
        if "FAILED TO COMPILE" in last:
            # measured in the lens: DRME's frame save pass fails on ReShade 6.8 and
            # the Feed says it then writes nothing, yet the Feed's own motion vector
            # probe reads real vectors whenever the picture moves
            lines.append("    motion vectors: %s. The Feed's log reports one of its passes failing to "
                         "compile on this ReShade, which is expected, and the rest still deliver "
                         "vectors once something moves." % name)
        else:
            lines.append("    motion vectors: %s" % name)
    except OSError:
        lines.append("    motion vectors: the Feed wrote no log")
        return False, "\n".join(lines)
    if failed:
        lines.append("    Neural Rendering: FAILED to start, %s" % failed.group(1))
        if failed.group(1).lower() == "0xbad00001":
            lines.append("    that code means the model refused to run on this card. The 310.8.SF-v2 "
                         "build in use is meant to cover RTX 20 through 50.")
        return False, "\n".join(lines)
    if created and evaluated:
        lines.append("    Neural Rendering: running, at least %d evaluations" % evaluated)
        return True, "\n".join(lines)
    lines.append("    Neural Rendering: never started (no feature 18 in the log). Log: %s" % logfile)
    return False, "\n".join(lines)


# ---------------------------------------------------------------- uninstall
def _unregister_stray(log=None):
    """Delete any layer value that points inside this install's layer folder,
    whether or not a record names it. The value name is the manifest path, so
    everything under LAYER_DIR is ours and nothing else is touched."""
    removed = []
    prefix = os.path.normcase(LAYER_DIR) + os.sep
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            names = []
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
            for name in names:
                if os.path.normcase(name).startswith(prefix):
                    try:
                        winreg.DeleteValue(k, name)
                        removed.append(name)
                        say(log, "unregistered %s" % name)
                    except OSError:
                        pass
    except OSError:
        pass
    return removed


def uninstall(target=DEFAULT_TARGET, log=None, keep=()):
    """Remove what the install record in target lists, the layer registration,
    and what running the stack and the fast engine wrote. Paths in keep are
    left in place."""
    path = os.path.join(target, "install-record.json")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        # No record, so no files are known. The layer value can still be there:
        # an install stopped after step_layer and before write_record registered
        # it and never recorded it, and left alone it would point the Vulkan
        # loader at a manifest the uninstaller is about to delete.
        stray = _unregister_stray(log)
        raise StackError("no install record in %s, nothing known to remove%s" % (
            target, "; removed %d layer value(s) it left behind" % len(stray) if stray else ""))
    for value in record.get("registry", []):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, value)
            say(log, "unregistered %s" % value)
        except OSError:
            pass
    _unregister_stray(log)
    kept = {os.path.normcase(os.path.abspath(k)) for k in keep}
    for f in record.get("files", []):
        if os.path.normcase(os.path.abspath(f)) in kept:
            continue
        try:
            os.remove(f)
        except OSError:
            pass
    # what running the stack wrote: the logs and their rotations, the Cost
    # Scaler's log, and the shader cache of the mpv that 0.1.0 ran
    for extra in ("ReShadePreset.ini", "ReShade.ini", "install-record.json") + tuple(
            f for f in os.listdir(target)
            if f.startswith(("ReShade.log", "dlss5-feed.log", "nvngx_dlssnr_proxy.log"))):
        try:
            os.remove(os.path.join(target, extra))
        except OSError:
            pass
    shutil.rmtree(os.path.join(target, "portable_config", "cache"), ignore_errors=True)
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    # what the fast engine wrote: its copy of the proxy's ini beside lens-fast.exe,
    # made from the stack's, and the runtime's logs in the lens's data folder. A
    # data_dir moved out of the lens's folder is left alone, like the rest of it.
    for d in fast_engine_dirs(target):
        try:
            os.remove(os.path.join(d, "nvngx_dlssnr.ini"))
        except OSError:
            pass
    shutil.rmtree(os.path.join(APP_DIR, "data", "logs", "fast"), ignore_errors=True)
    for d in (target, record.get("layer_dir", LAYER_DIR)):
        for root, dirs, files in os.walk(d, topdown=False):
            for sub in dirs:
                try:
                    os.rmdir(os.path.join(root, sub))
                except OSError:
                    pass
        try:
            os.rmdir(d)
        except OSError:
            pass
    say(log, "removed what the record listed from %s" % target)


# ---------------------------------------------------------------- wizard
def wizard(parent=None, target=DEFAULT_TARGET):
    """A window that runs the install and shows what it is doing.

    Returns the folder the stack was installed into when it installed and
    passed the self test, otherwise False. The install runs on a thread; the
    window only ever appends to its log from the mainloop, so it stays
    responsive while the download comes down.
    """
    import queue
    import tkinter as tk
    from tkinter import filedialog

    BG, FG, DIM, ACCENT, WARN = "#1b2430", "#cbd5e1", "#64748b", "#4ade80", "#fbbf24"
    supported, detail = gpu_supported()
    root = tk.Toplevel(parent) if parent else tk.Tk()
    root.title("Neural Lens: set up the neural stack")
    try:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        root.iconbitmap(os.path.join(base, "assets", "neural-lens.ico"))
    except Exception:
        pass
    root.configure(bg=BG)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    intro = ("The lens needs NVIDIA's DLSS Neural Rendering stack. Nothing of it is bundled: about "
             "%d MB is downloaded from the projects that publish each part, into the lens's own "
             "folder, and registered for your user only. No administrator prompt.\n\n" % DOWNLOAD_MB
             + ("This card reports compute capability %s, which is supported. The %s model is used for every RTX card."
                % (detail, MODEL) if supported else
                "Neural Rendering cannot run on this machine: %s." % detail))
    tk.Label(root, text=intro, bg=BG, fg=FG, justify="left", wraplength=620,
             font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
    tk.Label(root, text="Goes into", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
        row=1, column=0, sticky="w", padx=14)
    tk.Label(root, text=target, bg=BG, fg=FG, font=("Consolas", 9), anchor="w").grid(
        row=1, column=1, columnspan=2, sticky="w", padx=(6, 14))
    # every variable is made on this window's own Tk. At the offer the lens
    # makes when its stack is incomplete, the lens's root already exists and is
    # the default root, so a variable without a master lived there while the
    # entries lived here: the fields showed empty and anything typed was never seen
    have = {"nvngx_dlssnr.dll": tk.StringVar(master=root), "nvngx_dlss.dll": tk.StringVar(master=root)}
    tk.Label(root, text="If you already have NVIDIA's DLLs, point at them and copies are used instead "
                        "of downloaded, once their hashes check out. Otherwise leave these empty.",
             bg=BG, fg=DIM, justify="left", wraplength=620, font=("Segoe UI", 9)).grid(
        row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 2))
    for i, name in enumerate(have):
        tk.Label(root, text=name, bg=BG, fg=FG, font=("Consolas", 9)).grid(row=3 + i, column=0, sticky="w", padx=14)
        tk.Entry(root, textvariable=have[name], width=64, bg="#0b1220", fg=FG, insertbackground=FG,
                 relief="flat").grid(row=3 + i, column=1, sticky="we", padx=(6, 6), pady=2)

        def pick(var=have[name], n=name):
            p = filedialog.askopenfilename(title="Where is %s?" % n, filetypes=[(n, n), ("DLL", "*.dll")])
            if p:
                var.set(os.path.normpath(p))

        tk.Button(root, text="Browse", command=pick, relief="flat", bg="#334155", fg=FG).grid(
            row=3 + i, column=2, padx=(0, 14))
    tk.Label(root, text="Motion vectors come from ReshadeMotionEstimation by Jakob Wapenhensch (CC BY-NC "
                        "4.0), fetched with the rest.",
             bg=BG, fg=DIM, justify="left", wraplength=620, font=("Segoe UI", 9)).grid(
        row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 2))
    log = tk.Text(root, width=88, height=14, bg="#0b1220", fg=FG, relief="flat", font=("Consolas", 9),
                  state="disabled", wrap="word")
    log.grid(row=7, column=0, columnspan=3, padx=14, pady=(10, 6), sticky="we")
    status = tk.Label(root, text="", bg=BG, fg=DIM, font=("Segoe UI", 9))
    status.grid(row=8, column=0, columnspan=2, sticky="w", padx=14)
    result = {"ok": False, "done": False}
    q = queue.Queue()

    def append(text):
        log.config(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.config(state="disabled")

    def pump():
        try:
            while True:
                item = q.get_nowait()
                if item is None:
                    result["done"] = True
                    go.config(state="normal", text="Close" if result["ok"] else "Try again")
                    status.config(text="The stack works." if result["ok"] else "Not working yet; see above.",
                                  fg=ACCENT if result["ok"] else WARN)
                    return
                append(item)
        except queue.Empty:
            pass
        root.after(100, pump)

    def work(target, dlssnr, dlss):
        # plain strings only: Tk may be touched from the main thread alone, and
        # at the lens's offer the main thread is in wait_window, not mainloop,
        # so a .get() here raised "main thread is not in main loop"
        try:
            ok = Install(target, dlssnr or None, dlss or None, log=q.put).run()
            result["ok"] = ok
        except StackError as exc:
            q.put("")
            q.put("FAILED: %s" % exc)
        except Exception as exc:
            q.put("")
            q.put("FAILED: %r" % exc)
        q.put(None)

    def start():
        if result["done"] and result["ok"]:
            root.destroy()
            return
        result["done"] = False
        go.config(state="disabled", text="Installing...")
        status.config(text="", fg=DIM)
        threading.Thread(target=work, daemon=True,
                         args=(target, have["nvngx_dlssnr.dll"].get(), have["nvngx_dlss.dll"].get())).start()
        root.after(100, pump)

    go = tk.Button(root, text="Set it up", command=start, relief="flat", bg=ACCENT, fg="#0b1220",
                   font=("Segoe UI", 10, "bold"), state="normal" if supported else "disabled")
    go.grid(row=8, column=2, sticky="e", padx=14, pady=(4, 14))
    tk.Button(root, text="Not now", command=root.destroy, relief="flat", bg="#334155", fg=FG).grid(
        row=9, column=2, sticky="e", padx=14, pady=(0, 14))
    root.grab_set() if parent else None
    if parent:
        parent.wait_window(root)
    else:
        root.mainloop()
    # the folder it installed into, so a caller can point the lens straight at
    # it; a string is truthy, so callers that only ask whether it worked are fine
    return os.path.abspath(target) if result["ok"] else False


# ---------------------------------------------------------------- entry
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="fetch and assemble the Neural Rendering stack for the lens")
    ap.add_argument("--target", default=DEFAULT_TARGET,
                    help="the folder to install the stack into; installed, the lens's own folder is the "
                         "only one that works, and from source the default is stack, beside the script")
    ap.add_argument("--dlssnr", help="an nvngx_dlssnr.dll you already have; its hash is checked")
    ap.add_argument("--dlss", help="an nvngx_dlss.dll you already have; its hash is checked")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="drme",
                    help="which fetched shader estimates motion vectors (default drme)")
    ap.add_argument("--verify", action="store_true",
                    help="only run the self test, and check that the layer is limited to the lens")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove what the install record lists, and the layer registration")
    a = ap.parse_args(argv)
    try:
        if a.uninstall:
            uninstall(a.target)
            return 0
        if a.verify:
            ok, detail = verify(a.target)
            print(detail)
            ungated = layer_ungated()
            print(layer_line(ungated))
            print(fast_engine_line(a.target))
            return 0 if ok and not ungated else 1
        ok = Install(a.target, a.dlssnr, a.dlss, provider=a.provider).run()
        print("")
        if not ok:
            print("The stack was installed but the self test did not pass; see above.")
        elif FROZEN or same_path(a.target, DEFAULT_TARGET):
            print("OK: the stack works in %s." % a.target)
        else:
            print("OK: the stack works in %s. Point the lens at it with --stack-dir." % a.target)
        return 0 if ok else 1
    except StackError as exc:
        print("")
        print("FAILED: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
