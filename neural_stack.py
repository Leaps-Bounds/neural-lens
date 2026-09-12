# DLSS 5 Neural Lens: the stack setup.
# Copyright (C) 2026 Leaps-Bounds
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details,
# and the LICENSE file beside this one for the text.
"""Fetch and assemble the DLSS Neural Rendering stack the lens drives.

Nothing is bundled. Every component is downloaded from the project that
publishes it, into a folder of the user's own, and registered for the current
user only, so no elevation is needed and nothing shared with other software is
touched. Licences force most of this: mpv is GPL and must come from upstream,
NVIDIA's runtimes are NVIDIA's, and a new install gets ReshadeMotionEstimation
(CC BY-NC 4.0) for motion vectors, chosen by measurement, with VORT (MIT) as
the alternative. LumeniteFX publishes no licence, so it is never fetched; a
copy the user already holds can be pointed at instead.

What ends up where. APP is the lens's own folder, and TARGET defaults to APP\\stack:

    TARGET\\mpv.exe and the rest of the mpv build      shinchiro's mpv-winbuild-cmake
    TARGET\\nvngx_dlss.dll                             NVIDIA, via the RHI manifest
    TARGET\\nvngx_dlssnr.dll                           NVIDIA, the 310.8.SF-v2 model
    TARGET\\dlss5-feed.addon64                         DLSS5-Feeder
    TARGET\\renodx-dlss5.addon64                       RenoDX, via the RHI repository
    TARGET\\reshade-shaders\\Shaders\\...               DLSS5_Feed.fx, DRME, VORT, ReShade headers
    TARGET\\portable_config\\mpv.conf, input.conf
    TARGET\\ReShade.ini, ReShadePreset.ini, dlss5-feed.cfg
    TARGET\\install-record.json                        everything above, for uninstall
    APP\\ReShade\\ReShade64.dll, ReShade64.json, ReShadeApps.ini
    APP\\downloads\\...                                  while installing; removed once the self test passes
    HKCU\\SOFTWARE\\Khronos\\Vulkan\\ImplicitLayers\\<APP\\ReShade\\ReShade64.json> = 0

A DLL the user points at is hash checked and copied into TARGET; the record
names the copy, so uninstalling never touches the original.

The layer is registered under a name of its own, VK_LAYER_reshade_neural_lens,
with its own allow list holding only this mpv. The Vulkan loader loads one
layer per name, so a copy named like a machine wide ReShade would be skipped
where one exists, and this way the two coexist and each hooks only what it
lists.

Command line, for testing and for people who prefer it:

    python neural_stack.py                  install into the default folder
    python neural_stack.py --target D:\\nr   install somewhere else
    python neural_stack.py --dlssnr X --dlss Y   use NVIDIA DLLs you already have (hash checked)
    python neural_stack.py --provider vort  estimate motion vectors with VORT instead of DRME
    python neural_stack.py --lumenite DIR   use a LumeniteFX copy you already have instead
    python neural_stack.py --verify         only run the self test on an existing stack
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
import threading
import time
import urllib.request
import winreg
import zipfile

__version__ = "0.1.0"

# Everything lives in the lens's own folder, the one the installer put it in or
# the one this script is in: the stack, the ReShade layer, the downloads while
# they are needed, and (in neural_lens.py) the state and logs. Uninstalling is
# then removing that one folder plus the registry value that names it.
APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
           else os.path.dirname(os.path.abspath(__file__)))
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW, for console children of a windowless lens
DEFAULT_TARGET = os.path.join(APP_DIR, "stack")
LAYER_DIR = os.path.join(APP_DIR, "ReShade")
CACHE_DIR = os.path.join(APP_DIR, "downloads")
LAYER_NAME = "VK_LAYER_reshade_neural_lens"
LAYER_KEY = r"SOFTWARE\Khronos\Vulkan\ImplicitLayers"

RESHADE_VERSION = "6.8.0"
SOURCES = {
    "mpv_api": "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest",
    "7zr": "https://www.7-zip.org/a/7zr.exe",
    "reshade": "https://reshade.me/downloads/ReShade_Setup_%s_Addon.exe" % RESHADE_VERSION,
    "manifest": "https://raw.githubusercontent.com/RankFTW/RHI/main/dlss_manifest.json",
    "feeder_api": "https://api.github.com/repos/jlrouzies-fr/DLSS5-Feeder/releases/latest",
    "renodx": "https://github.com/RankFTW/rhi-repo/releases/download/renodx-dlss5-4.70/renodx-dlss5_4.70.zip",
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
# a reading and a fast scroll: DRME 0.075, 0.096, 0.102; LumeniteFX 0.092,
# 0.097, 0.104; VORT 0.099, 0.109, 0.106; no provider 0.114, 0.123. DRME is
# CC BY-NC 4.0, so it may be fetched and used with credit in a free tool and
# is the default; VORT is MIT and stays as the alternative.
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
# that many people already hold.
DLSS_VERSION = "310.8.0"
HASHES = {
    "nvngx_dlss.dll": ["c85f971ce023c9f3492fc7455f0b01a24ba18ea39636407a846902c4360b0b7e"],
    "nvngx_dlssnr.dll": {
        "310.8.0": ["e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e"],
        "310.8.SF-v2": ["6eb209e764f39872625debd6abaf45e2bb6322f6f270f781f70c059ae30b3927",
                        "8270b350cd82de5ce89806872cdd6b6a9249b80836b91bbeb3573470744cc206"],
    },
}
# One Neural Rendering model serves every RTX card. The SF-v2 build was thought
# to be 40 series only until it was measured running on a 5090 on 2026-09-12:
# feature 18 created and evaluated, and the in-to-out difference matched the
# stock model to within 0.01 at two pinned rates. Its author states it covers
# RTX 20, 30 and 40 and runs identically on 50. The stock 310.8.0 hash stays in
# HASHES so installs made before this change still verify when repaired.
MODEL = "310.8.SF-v2"

MPV_CONF = """# written by the Neural Lens stack setup
gpu-api=vulkan
vo=gpu-next
profile=high-quality
keep-open=yes
"""
INPUT_CONF = """# written by the Neural Lens stack setup
# Home is ReShade's overlay key; keep mpv from swallowing it
HOME ignore
Shift+HOME seek 0 absolute
"""
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
EnableHooks=2
NeuralUplift=1
NRAutoMask=1
NRDepthMode=0
NRIntensity=1.58
NRLocalStructure=1
NRSkinStructure=-1
NRStyle=0
NRTransferStrength=1
NRUICorrection=0

[SCREENSHOT]
SavePath=.\\
FileFormat=1
"""
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


def gpu_supported():
    """(True, capability) when Neural Rendering can run here, else (False, why).

    One model now serves every generation, so the question is no longer which
    card this is but whether it is one at all. Compute capability 7.5 is Turing,
    the first RTX line and where Neural Rendering starts; a machine with no
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


# ---------------------------------------------------------------- steps
LUMENITE_FILES = ["Shaders/lumenite_Kernel.fx", "Shaders/include/lumenite_ColorManagement.fxh",
                  "Shaders/include/lumenite_Compute.fxh", "Shaders/include/lumenite_Helpers.fxh",
                  "Shaders/include/lumenite_Projections.fxh", "Textures/lumenite_bluenoise256.png"]


def find_lumenite(folder):
    """The reshade-shaders folder holding LumeniteFX, given it or its parent."""
    for root in (folder, os.path.join(folder, "reshade-shaders")):
        if all(os.path.isfile(os.path.join(root, f)) for f in LUMENITE_FILES):
            return root
    return None


class Install:
    def __init__(self, target=DEFAULT_TARGET, dlssnr=None, dlss=None, log=None, lumenite=None,
                 provider="drme"):
        self.target = os.path.abspath(target)
        self.given = {"nvngx_dlssnr.dll": dlssnr, "nvngx_dlss.dll": dlss}
        self.log = log
        self.provider = provider if provider in PROVIDERS else "drme"
        # LumeniteFX cannot be fetched or shipped, but a copy the user already
        # holds can be used in place of the fetched estimators
        self.lumenite = find_lumenite(lumenite) if lumenite else None
        if lumenite and not self.lumenite:
            raise StackError("no LumeniteFX under %s: it needs %s" % (lumenite, ", ".join(LUMENITE_FILES)))
        self.record = {"version": __version__, "target": self.target, "layer_dir": LAYER_DIR,
                       "files": [], "registry": [], "components": {}}

    def say(self, text):
        say(self.log, text)

    def add(self, path):
        self.record["files"].append(os.path.abspath(path))
        return path

    def run(self):
        os.makedirs(self.target, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.say("Installing the Neural Rendering stack into %s" % self.target)
        self.step_mpv()
        self.step_reshade()
        self.step_nvidia()
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
        if ok:
            # the downloads served their purpose; a failed run keeps them so a
            # retry does not fetch 230 MB again
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        return ok

    # mpv: the current build from shinchiro, which is the one mpv.io points at
    def step_mpv(self):
        if os.path.isfile(os.path.join(self.target, "mpv.exe")):
            self.say("mpv: already present, keeping it")
            return
        self.say("mpv: looking up the current build")
        rel = fetch_json(SOURCES["mpv_api"])
        asset = None
        for a in rel.get("assets", []):
            if re.match(r"^mpv-x86_64-\d{8}-git-[0-9a-f]+\.7z$", a["name"]):
                asset = a
                break
        if not asset:
            raise StackError("no mpv-x86_64 build in the latest release")
        self.record["components"]["mpv"] = asset["name"]
        archive = fetch(asset["browser_download_url"], os.path.join(CACHE_DIR, asset["name"]),
                        self.log, "mpv " + rel.get("tag_name", ""))
        sevenzr = fetch(SOURCES["7zr"], os.path.join(CACHE_DIR, "7zr.exe"), self.log, "7zr")
        self.say("mpv: unpacking")
        r = subprocess.run([sevenzr, "x", "-y", "-o" + self.target, archive], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(os.path.join(self.target, "mpv.exe")):
            raise StackError("unpacking mpv failed: %s" % (r.stderr or r.stdout)[-400:])
        for root, dirs, files in os.walk(self.target):
            for f in files:
                self.add(os.path.join(root, f))

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
                "description": "ReShade, installed for the Neural Lens's mpv only",
                "device_extensions": [{"name": "VK_EXT_tooling_info", "spec_version": "1",
                                       "entrypoints": ["vkGetPhysicalDeviceToolPropertiesEXT"]}],
                "disable_environment": {"DISABLE_VK_LAYER_reshade_neural_lens": "1"},
            },
        }
        with open(os.path.join(LAYER_DIR, "ReShade64.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
        self.add(os.path.join(LAYER_DIR, "ReShade64.json"))
        # the allow list is this layer's own, so it holds exactly one program
        self.add(write_text(os.path.join(LAYER_DIR, "ReShadeApps.ini"),
                            "Apps=%s\n" % os.path.join(self.target, "mpv.exe")))

    # NVIDIA: both runtimes, hash checked. One model serves every RTX card.
    def step_nvidia(self):
        ok, detail = gpu_supported()
        if not ok:
            raise StackError("Neural Rendering needs an NVIDIA RTX card: %s" % detail)
        model = MODEL
        self.record["components"]["gpu"] = detail
        self.record["components"]["dlssnr"] = model
        self.record["components"]["dlss"] = DLSS_VERSION
        self.say("NVIDIA: compute capability %s, Neural Rendering model %s" % (detail, model))
        manifest = fetch_json(SOURCES["manifest"])

        def url_for(key, version):
            for entry in manifest.get(key, []):
                if entry.get("version") == version:
                    return entry["url"]
            raise StackError("the manifest has no %s %s" % (key, version))

        wanted = {"nvngx_dlss.dll": (HASHES["nvngx_dlss.dll"], "dlss", DLSS_VERSION),
                  "nvngx_dlssnr.dll": (HASHES["nvngx_dlssnr.dll"][model], "dlssnr", model)}
        for name, (want, key, version) in wanted.items():
            dest = os.path.join(self.target, name)
            given = self.given.get(name)
            if given:
                got = sha256(given)
                if got not in want:
                    raise StackError("%s is not a %s build this stack knows\n"
                                     "  yours    %s\n  known    %s" % (given, version, got, ", ".join(want)))
                shutil.copy2(given, dest)
                self.say("%s: using your copy, hash verified" % name)
            elif os.path.isfile(dest) and sha256(dest) in want:
                self.say("%s: already present and verified" % name)
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
                self.say("%s: downloaded, hash verified" % name)
            self.add(dest)

    def step_feeder(self):
        rel = fetch_json(SOURCES["feeder_api"])
        asset = next((a for a in rel.get("assets", []) if re.match(r"^DLSS5-Feeder-.*\.zip$", a["name"])), None)
        if not asset:
            raise StackError("no DLSS5-Feeder zip in its latest release")
        self.record["components"]["feeder"] = rel.get("tag_name")
        z = fetch(asset["browser_download_url"], os.path.join(CACHE_DIR, asset["name"]), self.log,
                  "DLSS5-Feeder " + rel.get("tag_name", ""))
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            addon = next(n for n in names if n.lower().endswith("dlss5-feed.addon64"))
            fx = next(n for n in names if n.lower().endswith("dlss5_feed.fx"))
            self.add(self._extract(zf, addon, os.path.join(self.target, "dlss5-feed.addon64")))
            self.add(self._extract(zf, fx, os.path.join(self.target, "reshade-shaders", "Shaders", "DLSS5_Feed.fx")))
        self.say("DLSS5-Feeder: %s" % rel.get("tag_name"))

    def step_renodx(self):
        z = fetch(SOURCES["renodx"], os.path.join(CACHE_DIR, "renodx-dlss5.zip"), self.log, "RenoDX DLSS 5")
        with zipfile.ZipFile(z) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".addon64"))
            self.add(self._extract(zf, member, os.path.join(self.target, "renodx-dlss5.addon64")))
        self.record["components"]["renodx"] = SOURCES["renodx"].rsplit("/", 2)[-2]
        self.say("RenoDX DLSS 5 add-on: %s" % self.record["components"]["renodx"])

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
        self.say("shaders: VORT (MIT) fetched as the alternative estimator, %d includes and its texture, "
                 "and ReShade's headers" % len(includes))
        for name in DRME_FILES:
            self.add(fetch(SOURCES["drme"] + name, os.path.join(base, name), self.log, name))
        self.say("shaders: ReshadeMotionEstimation by Jakob Wapenhensch (CC BY-NC 4.0)")
        if self.lumenite:
            for rel_path in LUMENITE_FILES:
                dest = os.path.join(self.target, "reshade-shaders", rel_path.replace("/", os.sep))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(os.path.join(self.lumenite, rel_path), dest)
                self.add(dest)
            self.record["components"]["motion_vectors"] = "LumeniteFX, the user's own copy"
            self.say("shaders: your LumeniteFX copied in; it will provide the motion vectors")
        else:
            self.record["components"]["motion_vectors"] = {"drme": "ReshadeMotionEstimation", "vort": "VORT"}[self.provider]
            self.say("motion vectors: %s will provide them" % self.record["components"]["motion_vectors"])

    def step_config(self):
        self.add(write_text(os.path.join(self.target, "portable_config", "mpv.conf"), MPV_CONF))
        self.add(write_text(os.path.join(self.target, "portable_config", "input.conf"), INPUT_CONF))
        # the templates are written for VORT; the chosen provider is substituted
        ini, preset = RESHADE_INI, RESHADE_PRESET
        if self.lumenite:
            ini = ini.replace("DLSS5_MV_PROVIDER=2,V_MV_MODE=1", "DLSS5_MV_PROVIDER=3")
            preset = preset.replace("vort_MotionEffects@vort_Motion.fx", "Lumenite_Kernel@lumenite_Kernel.fx")
        elif self.provider == "drme":
            ini = ini.replace("DLSS5_MV_PROVIDER=2,V_MV_MODE=1", "DLSS5_MV_PROVIDER=0")
            preset = preset.replace("vort_MotionEffects@vort_Motion.fx", "DRME@MotionEstimation.fx")
        self.add(write_text(os.path.join(self.target, "ReShade.ini"), ini))
        self.add(write_text(os.path.join(self.target, "ReShadePreset.ini"), preset))
        self.add(write_text(os.path.join(self.target, "dlss5-feed.cfg"), FEED_CFG))
        self.say("config: mpv, ReShade, the preset and the feed written")

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


# ---------------------------------------------------------------- verify
def verify(target, log=None, seconds=9.0):
    """Run this mpv on a synthetic stream and read what ReShade says.

    The lens feeds mpv raw frames on stdin, so the self test does the same:
    a still with detail, long enough for the Feed's warm up and the first
    Neural Rendering evaluation. The verdict is read from ReShade.log.
    """
    import numpy as np
    mpv = os.path.join(target, "mpv.exe")
    if not os.path.isfile(mpv):
        return False, "FAIL: no mpv.exe in %s" % target
    logfile = os.path.join(target, "ReShade.log")
    try:
        os.remove(logfile)
    except OSError:
        pass
    w, h = 960, 540
    cmd = [mpv, "-", "--demuxer=rawvideo", "--demuxer-rawvideo-w=%d" % w, "--demuxer-rawvideo-h=%d" % h,
           "--demuxer-rawvideo-mp-format=bgra", "--demuxer-rawvideo-fps=60", "--no-audio",
           "--really-quiet", "--geometry=%dx%d+40+40" % (w, h), "--no-border", "--force-window=immediate",
           "--keep-open=yes", "--cache=no", "--title=NeuralLensSelfTest"]
    env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, cwd=target, env=env)
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 255, (h, w, 4), np.uint8)
    frame[::7, :, :] = 230
    stop = {"x": False}

    def feed():
        while not stop["x"]:
            try:
                proc.stdin.write(frame.tobytes())
            except Exception:
                return
            time.sleep(1 / 60)

    threading.Thread(target=feed, daemon=True).start()
    say(log, "    self test: mpv window for %.0f seconds" % seconds)
    time.sleep(seconds)
    stop["x"] = True
    try:
        proc.kill()
    except Exception:
        pass
    try:
        text = open(logfile, encoding="utf-8", errors="replace").read()
    except OSError:
        return False, ("FAIL: ReShade wrote no log, so it did not attach to mpv. Is the Vulkan layer "
                       "registered, and is %s on its Apps list?" % mpv)
    created = "feature=18" in text and "feature 18 created" in text
    evaluated = len(re.findall(r"feature 18 evaluation succeeded", text))
    failed = re.search(r"feature 18 create failed with (0x[0-9a-fA-F]+)", text)
    addons = ("DLSS 5 Neural Rendering" in text, "DLSS 5 Feed" in text)
    lines = ["    ReShade attached: yes",
             "    add-ons loaded: Neural Rendering %s, Feed %s" % tuple("yes" if a else "NO" for a in addons)]
    # A still needs no motion vectors, so Neural Rendering can run with the
    # provider missing and nobody would know until something moved. The Feed
    # says which provider it found; read that rather than trust the picture.
    try:
        feed = open(os.path.join(target, "dlss5-feed.log"), encoding="utf-8", errors="replace").read()
        prov = [l for l in feed.splitlines() if "DLSS5_MV_PROVIDER" in l]
        last = prov[-1].split("DLSS5_MV_PROVIDER=", 1)[-1] if prov else ""
        if not prov or "-> none" in last:
            lines.append("    motion vectors: NO PROVIDER, so anything that moves would smear. "
                         "The motion vector shader did not compile or was not found: %s" % (last[:90] or "no Feed log"))
            return False, "\n".join(lines)
        lines.append("    motion vectors: %s" % last.split(",", 1)[0][:90])
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
        lines.append("    Neural Rendering: running, %d evaluations" % evaluated)
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


def uninstall(target=DEFAULT_TARGET, log=None):
    path = os.path.join(target, "install-record.json")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except OSError:
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
    for f in record.get("files", []):
        try:
            os.remove(f)
        except OSError:
            pass
    # what running the stack wrote: the logs and their rotations, and mpv's
    # shader cache, none of which the record could know about
    for extra in ("ReShadePreset.ini", "ReShade.ini", "install-record.json") + tuple(
            f for f in os.listdir(target) if f.startswith(("ReShade.log", "dlss5-feed.log"))):
        try:
            os.remove(os.path.join(target, extra))
        except OSError:
            pass
    shutil.rmtree(os.path.join(target, "portable_config", "cache"), ignore_errors=True)
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
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
    responsive while 230 MB come down.
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
    intro = ("The lens needs an mpv with NVIDIA's DLSS Neural Rendering stack. Nothing is bundled: "
             "about 230 MB is downloaded from the projects that publish each part, into the lens's "
             "own folder, and registered for your user only. No administrator prompt.\n\n"
             + ("This card reports compute capability %s, which is supported. The %s model is used for every RTX card."
                % (detail, MODEL) if supported else
                "Neural Rendering cannot run on this machine: %s." % detail))
    tk.Label(root, text=intro, bg=BG, fg=FG, justify="left", wraplength=620,
             font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
    tk.Label(root, text="Goes into", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
        row=1, column=0, sticky="w", padx=14)
    tk.Label(root, text=target, bg=BG, fg=FG, font=("Consolas", 9), anchor="w").grid(
        row=1, column=1, columnspan=2, sticky="w", padx=(6, 14))
    # every variable is made on this window's own Tk. At the offer that follows
    # a found but bare mpv the lens's root already exists and is the default
    # root, so a variable without a master lived there while the entries lived
    # here: the fields showed empty and anything typed was never seen
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
        # at the first run offer the main thread is in wait_window, not mainloop,
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
                    help="the folder to install the stack into (default: stack, beside the lens)")
    ap.add_argument("--dlssnr", help="an nvngx_dlssnr.dll you already have; its hash is checked")
    ap.add_argument("--dlss", help="an nvngx_dlss.dll you already have; its hash is checked")
    ap.add_argument("--lumenite", help="a reshade-shaders folder holding LumeniteFX you already have; "
                                       "its motion vectors are used instead")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="drme",
                    help="which fetched shader estimates motion vectors (default drme)")
    ap.add_argument("--verify", action="store_true", help="only run the self test")
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
            return 0 if ok else 1
        ok = Install(a.target, a.dlssnr, a.dlss, lumenite=a.lumenite, provider=a.provider).run()
        print("")
        print("OK: the stack works in %s. The lens finds its default stack folder on its own; "
              "use --mpv-dir for any other." % a.target if ok else
              "The stack was installed but the self test did not pass; see above.")
        return 0 if ok else 1
    except StackError as exc:
        print("")
        print("FAILED: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
