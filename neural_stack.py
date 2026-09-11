"""Fetch and assemble the DLSS Neural Rendering stack the lens drives.

Nothing is bundled. Every component is downloaded from the project that
publishes it, into a folder of the user's own, and registered for the current
user only, so no elevation is needed and nothing shared with other software is
touched. Licences force most of this: mpv is GPL and must come from upstream,
NVIDIA's runtimes are NVIDIA's, and the motion vector shader the lens's own
author uses cannot be redistributed at all, so a new install gets VORT (MIT).

What ends up where, with TARGET defaulting to %LOCALAPPDATA%\\NeuralLens\\stack:

    TARGET\\mpv.exe and the rest of the mpv build      shinchiro's mpv-winbuild-cmake
    TARGET\\nvngx_dlss.dll                             NVIDIA, via the RHI manifest
    TARGET\\nvngx_dlssnr.dll                           NVIDIA, the build for this card
    TARGET\\dlss5-feed.addon64                         DLSS5-Feeder
    TARGET\\renodx-dlss5.addon64                       RenoDX, via the RHI repository
    TARGET\\reshade-shaders\\Shaders\\...               DLSS5_Feed.fx, VORT, ReShade headers
    TARGET\\portable_config\\mpv.conf, input.conf
    TARGET\\ReShade.ini, ReShadePreset.ini, dlss5-feed.cfg
    TARGET\\install-record.json                        everything above, for uninstall
    LAYER\\ReShade64.dll, ReShade64.json, ReShadeApps.ini   LAYER = %LOCALAPPDATA%\\NeuralLens\\ReShade
    HKCU\\SOFTWARE\\Khronos\\Vulkan\\ImplicitLayers\\<LAYER\\ReShade64.json> = 0

The layer is registered under a name of its own, VK_LAYER_reshade_neural_lens,
with its own allow list holding only this mpv. The Vulkan loader loads one
layer per name, so a copy named like a machine wide ReShade would be skipped
where one exists, and this way the two coexist and each hooks only what it
lists.

Command line, for testing and for people who prefer it:

    python neural_stack.py                  install into the default folder
    python neural_stack.py --target D:\\nr   install somewhere else
    python neural_stack.py --dlssnr X --dlss Y   use NVIDIA DLLs you already have (hash checked)
    python neural_stack.py --gpu ada        override the card generation (ada or blackwell)
    python neural_stack.py --verify         only run the self test on an existing install
    python neural_stack.py --uninstall      remove what the record says was installed

The lens itself offers the same setup when it starts without a stack.
"""
import ctypes
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

LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
DEFAULT_TARGET = os.path.join(LOCAL, "NeuralLens", "stack")
LAYER_DIR = os.path.join(LOCAL, "NeuralLens", "ReShade")
CACHE_DIR = os.path.join(LOCAL, "NeuralLens", "downloads")
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
# matches none is refused, not installed. The 40 series model has two known
# builds: the one the repository serves (version 310.8.SF.0, 165,830,144 bytes)
# and an earlier community build (165,840,496 bytes) many people already hold.
DLSS_VERSION = "310.8.0"
HASHES = {
    "nvngx_dlss.dll": ["c85f971ce023c9f3492fc7455f0b01a24ba18ea39636407a846902c4360b0b7e"],
    "nvngx_dlssnr.dll": {
        "310.8.0": ["e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e"],
        "310.8.SF-v2": ["6eb209e764f39872625debd6abaf45e2bb6322f6f270f781f70c059ae30b3927",
                        "8270b350cd82de5ce89806872cdd6b6a9249b80836b91bbeb3573470744cc206"],
    },
}
# which Neural Rendering model each card generation needs, by compute capability
GENERATIONS = {"blackwell": "310.8.0", "ada": "310.8.SF-v2"}

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


def gpu_generation():
    """'blackwell', 'ada', or None, from the driver's own nvidia-smi.

    Compute capability is steadier than marketing names, which fragment into
    "RTX 4090 Laptop GPU" and "RTX 4000 Ada Generation": 8.9 is Ada, the RTX 40
    series; 12.0 is Blackwell, the RTX 50 series.
    """
    smi = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    if not os.path.isfile(smi):
        smi = "nvidia-smi"
    try:
        out = subprocess.run([smi, "--query-gpu=compute_cap", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    caps = [c.strip() for c in out.splitlines() if c.strip()]
    if not caps:
        return None
    major = int(float(caps[0]))
    if major >= 12:
        return "blackwell"
    if caps[0].startswith("8.9"):
        return "ada"
    return None


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
    def __init__(self, target=DEFAULT_TARGET, gpu=None, dlssnr=None, dlss=None, log=None, lumenite=None,
                 provider="drme"):
        self.target = os.path.abspath(target)
        self.gpu = gpu
        self.given = {"nvngx_dlssnr.dll": dlssnr, "nvngx_dlss.dll": dlss}
        self.log = log
        self.provider = provider if provider in PROVIDERS else "drme"
        # LumeniteFX cannot be fetched or shipped, but a copy the user already
        # holds can be used: its motion vectors ghost less on scrolling text
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
        r = subprocess.run([sevenzr, "x", "-y", "-o" + self.target, archive], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(os.path.join(self.target, "mpv.exe")):
            raise StackError("unpacking mpv failed: %s" % (r.stderr or r.stdout)[-400:])
        for root, dirs, files in os.walk(self.target):
            for f in files:
                self.add(os.path.join(root, f))

    # ReShade: the DLL and its layer manifest come straight out of the setup
    # exe, which is a zip, so nothing of ReShade's is executed here
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

    # NVIDIA: both runtimes, hash checked, the model chosen for this card
    def step_nvidia(self):
        gen = self.gpu or gpu_generation()
        if not gen:
            raise StackError("could not tell which card this is. nvidia-smi reported no compute "
                             "capability of 8.9 (RTX 40 series) or 12 (RTX 50 series). Pass --gpu.")
        model = GENERATIONS[gen]
        self.record["components"]["gpu"] = gen
        self.record["components"]["dlssnr"] = model
        self.record["components"]["dlss"] = DLSS_VERSION
        self.say("NVIDIA: %s card, Neural Rendering model %s" % (
            {"ada": "RTX 40 series", "blackwell": "RTX 50 series"}[gen], model))
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
        self.say("shaders: VORT motion vectors (MIT), %d includes and its texture, and ReShade's headers"
                 % len(includes))
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
                         "The VORT shader did not compile or was not found: %s" % (last[:90] or "no Feed log"))
            return False, "\n".join(lines)
        lines.append("    motion vectors: %s" % last.split(",", 1)[0][:90])
    except OSError:
        lines.append("    motion vectors: the Feed wrote no log")
        return False, "\n".join(lines)
    if failed:
        lines.append("    Neural Rendering: FAILED to start, %s" % failed.group(1))
        if failed.group(1).lower() == "0xbad00001":
            lines.append("    that code means the model does not support this card; the stock model "
                         "runs only on RTX 50, the 40 series needs the community build")
        return False, "\n".join(lines)
    if created and evaluated:
        lines.append("    Neural Rendering: running, %d evaluations" % evaluated)
        return True, "\n".join(lines)
    lines.append("    Neural Rendering: never started (no feature 18 in the log). Log: %s" % logfile)
    return False, "\n".join(lines)


# ---------------------------------------------------------------- uninstall
def uninstall(target=DEFAULT_TARGET, log=None):
    path = os.path.join(target, "install-record.json")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except OSError:
        raise StackError("no install record in %s, nothing known to remove" % target)
    for value in record.get("registry", []):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYER_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, value)
            say(log, "unregistered %s" % value)
        except OSError:
            pass
    for f in record.get("files", []):
        try:
            os.remove(f)
        except OSError:
            pass
    for extra in ("ReShade.log", "dlss5-feed.log", "ReShadePreset.ini", "ReShade.ini", "install-record.json"):
        try:
            os.remove(os.path.join(target, extra))
        except OSError:
            pass
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

    Returns True when the stack installed and passed the self test. The
    install runs on a thread; the window only ever appends to its log from the
    mainloop, so it stays responsive while 230 MB come down.
    """
    import queue
    import tkinter as tk
    from tkinter import filedialog

    BG, FG, DIM, ACCENT, WARN = "#1b2430", "#cbd5e1", "#64748b", "#4ade80", "#fbbf24"
    root = tk.Toplevel(parent) if parent else tk.Tk()
    root.title("Neural Lens: set up the neural stack")
    root.configure(bg=BG)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    gen = gpu_generation()
    card = {"ada": "an RTX 40 series card", "blackwell": "an RTX 50 series card"}.get(gen)
    intro = ("The lens needs an mpv with NVIDIA's DLSS Neural Rendering stack. Nothing is bundled: "
             "about 230 MB is downloaded from the projects that publish each part, into a folder "
             "of your own, and registered for your user only. No administrator prompt.\n\n"
             + ("This is %s, so it gets the %s Neural Rendering model." % (card, GENERATIONS[gen])
                if gen else
                "The card could not be identified as RTX 40 or 50 series. Neural Rendering runs "
                "only on those, so the setup cannot choose a model here."))
    tk.Label(root, text=intro, bg=BG, fg=FG, justify="left", wraplength=620,
             font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
    tk.Label(root, text="Install into", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
        row=1, column=0, sticky="w", padx=14)
    where = tk.StringVar(value=target)
    tk.Entry(root, textvariable=where, width=64, bg="#0b1220", fg=FG, insertbackground=FG,
             relief="flat").grid(row=1, column=1, sticky="we", padx=(6, 6))

    def browse():
        d = filedialog.askdirectory(initialdir=where.get(), title="Where should the stack go?")
        if d:
            where.set(os.path.normpath(d))

    tk.Button(root, text="Browse", command=browse, relief="flat", bg="#334155", fg=FG).grid(
        row=1, column=2, padx=(0, 14))
    have = {"nvngx_dlssnr.dll": tk.StringVar(), "nvngx_dlss.dll": tk.StringVar()}
    tk.Label(root, text="If you already have NVIDIA's DLLs, point at them and they are used instead "
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
    lum = tk.StringVar()
    tk.Label(root, text="Motion vectors come from ReshadeMotionEstimation by Jakob Wapenhensch (CC BY-NC "
                        "4.0). If you already have LumeniteFX and prefer it, point at its reshade-shaders "
                        "folder and your copy is used instead. It cannot be downloaded for you.",
             bg=BG, fg=DIM, justify="left", wraplength=620, font=("Segoe UI", 9)).grid(
        row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 2))
    tk.Label(root, text="LumeniteFX", bg=BG, fg=FG, font=("Consolas", 9)).grid(row=6, column=0, sticky="w", padx=14)
    tk.Entry(root, textvariable=lum, width=64, bg="#0b1220", fg=FG, insertbackground=FG,
             relief="flat").grid(row=6, column=1, sticky="we", padx=(6, 6), pady=2)

    def pick_lum():
        d = filedialog.askdirectory(title="Where is the reshade-shaders folder holding LumeniteFX?")
        if d:
            lum.set(os.path.normpath(d))

    tk.Button(root, text="Browse", command=pick_lum, relief="flat", bg="#334155", fg=FG).grid(
        row=6, column=2, padx=(0, 14))
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

    def work():
        try:
            ok = Install(where.get(), gen, have["nvngx_dlssnr.dll"].get() or None,
                         have["nvngx_dlss.dll"].get() or None, log=q.put,
                         lumenite=lum.get() or None).run()
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
        threading.Thread(target=work, daemon=True).start()
        root.after(100, pump)

    go = tk.Button(root, text="Set it up", command=start, relief="flat", bg=ACCENT, fg="#0b1220",
                   font=("Segoe UI", 10, "bold"), state="normal" if gen else "disabled")
    go.grid(row=8, column=2, sticky="e", padx=14, pady=(4, 14))
    tk.Button(root, text="Not now", command=root.destroy, relief="flat", bg="#334155", fg=FG).grid(
        row=9, column=2, sticky="e", padx=14, pady=(0, 14))
    root.grab_set() if parent else None
    if parent:
        parent.wait_window(root)
    else:
        root.mainloop()
    return result["ok"]


# ---------------------------------------------------------------- entry
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="fetch and assemble the Neural Rendering stack for the lens")
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--gpu", choices=sorted(GENERATIONS))
    ap.add_argument("--dlssnr", help="an nvngx_dlssnr.dll you already have; its hash is checked")
    ap.add_argument("--dlss", help="an nvngx_dlss.dll you already have; its hash is checked")
    ap.add_argument("--lumenite", help="a reshade-shaders folder holding LumeniteFX you already have; "
                                       "its motion vectors are used instead")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="drme",
                    help="which fetched shader estimates motion vectors (default drme)")
    ap.add_argument("--verify", action="store_true", help="only run the self test")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.uninstall:
            uninstall(a.target)
            return 0
        if a.verify:
            ok, detail = verify(a.target)
            print(detail)
            return 0 if ok else 1
        ok = Install(a.target, a.gpu, a.dlssnr, a.dlss, lumenite=a.lumenite, provider=a.provider).run()
        print("")
        print("OK: the stack works. Point the lens at %s" % a.target if ok else
              "The stack was installed but the self test did not pass; see above.")
        return 0 if ok else 1
    except StackError as exc:
        print("")
        print("FAILED: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
