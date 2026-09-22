# DLSS 5 Neural Lens
# Copyright (C) 2026 Leaps-Bounds
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details,
# and the LICENSE file beside this one for the text.
"""
DLSS 5 Neural Lens: a floating see-through window that neural-renders whatever
is behind it. Drag it by the title bar. The viewport is click-through, so the
mouse reaches the desktop underneath, like the Windows Magnifier lens.

How it works. Every piece below was measured before it was built:

  1. The picture is drawn by the presenter, lens_presenter.py, a Vulkan window
     placed exactly on the lens rect, click-through and on top. It captures the
     monitor with Windows.Graphics.Capture, cropped to the rect, and presents
     each frame the moment it arrives, copying the original in afresh each
     time, so Neural Rendering never works on its own output. A captured
     frame the same as the last is not presented at all, so over content that
     is not changing nothing runs, and a present every quarter second keeps
     ReShade's keys and the capture alive.

  2. Every window of the lens's own, the presenter included, is excluded from
     capture (WDA_EXCLUDEFROMCAPTURE). Monitor capture then composes the
     desktop underneath them, which Desktop Duplication does not: measured, a
     region under an excluded window matched the bare desktop exactly.

  3. ReShade's Vulkan layer, the DLSS 5 Feed and the RenoDX DLSS 5 add-on attach
     to the presenter's swapchain and do the neural rendering. The presenter
     runs as lens-presenter.exe in the stack folder, which the layer's allow
     list names. ReShade reads its configuration from the executable's own
     folder: started from elsewhere with the stack as its working directory,
     the layer did not attach, measured. So the installed program's folder is
     the stack folder, and from source the stack folder beside the script holds
     a copy of the interpreter under that name.

  4. MULTI-PASS runs inside the add-on: the title bar's count is written to
     NRPasses in ReShade.ini before the presenter starts, and a count chosen in
     the add-on's own overlay reaches the bar while the overlay is open.

  5. Nothing buffers, so there is no frame rate to govern: a frame the neural
     pass cannot keep up with is replaced by the next. Measured from a change on
     screen to the change in the output, both read through the compositor:
     8 ms windowed at 120 Hz, one refresh.

  6. RESIZING restarts the picture. The presenter's size is fixed when it
     starts, and the add-on crashes when a swapchain is recreated under it, so
     a new size, fullscreen and back, or a lens that has to shrink to fit its
     monitor replaces the presenter, the way a new pass count does, and the
     chrome is laid out again around the new one. Only the folder settings
     restart the process, and that handover must not use os.execv: on Windows
     it does not quote arguments containing spaces.

  7. MINIMISED to the taskbar, the lens hides its windows and tells the
     presenter to pause. It stops its capture and presents nothing, so no
     neural pass runs and the GPU is free, and the taskbar button brings
     everything back as it was.

Configuration: see neural-lens.ini.example. State, logs and screenshots live
in a data folder beside the program by default, so an install is one folder.
"""
import collections
import ctypes
import ctypes.wintypes as w
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox
from tkinter import ttk


def _script_dir():
    """The folder the ini lives in: beside the script, or beside the exe when
    frozen, where __file__ would point inside the bundle's internals."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _asset(name):
    """A file from the assets folder: beside the script, or inside the frozen
    bundle's data folder."""
    base = getattr(sys, "_MEIPASS", None) or _script_dir()
    return os.path.join(base, "assets", name)


def _set_icon(window):
    """Give a Tk window the lens icon, which the taskbar button shows."""
    try:
        window.iconbitmap(_asset("neural-lens.ico"))
    except Exception:
        pass


def _relaunch_cmd():
    """How to start another copy of this program with the same arguments.

    Frozen, the executable is the program and sys.argv[0] is the executable
    too, so passing it again as the first argument would be wrong.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable] + sys.argv[1:]
    return [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]


def _ini_path():
    """neural-lens.ini beside this script, or the file NEURAL_LENS_INI names,
    which is how a test keeps its settings out of the real one."""
    return os.environ.get("NEURAL_LENS_INI") or os.path.join(_script_dir(), "neural-lens.ini")


def _read_ini():
    """Optional neural-lens.ini beside this script. Plain key = value lines."""
    cfg = {}
    try:
        with open(_ini_path(), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line[0] in "#;[":
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip().lower()] = v.strip().strip('"')
    except OSError:
        pass
    return cfg


_INI = _read_ini()


def _find_stack_dir():
    """The folder holding the Neural Rendering stack and the presenter.

    Checked in order: --stack-dir on the command line, the NEURAL_LENS_STACK
    environment variable, stack_dir in neural-lens.ini, then the program's own
    folder when installed, which is where the setup assembles the stack, and a
    "stack" folder beside the script when run from source. The names 0.1.0
    used, --mpv-dir, NEURAL_LENS_MPV_DIR and mpv_dir, are read too, in the same
    places. A folder counts when lens-presenter.exe is in it; the stack's other
    parts are checked separately, see _missing_stack, so an incomplete stack is
    named rather than silently passed over.
    """
    cands = []
    for i, a in enumerate(sys.argv):
        if a in ("--stack-dir", "--mpv-dir") and i + 1 < len(sys.argv):
            cands.append(sys.argv[i + 1])
    cands += [os.environ.get("NEURAL_LENS_STACK"), os.environ.get("NEURAL_LENS_MPV_DIR"),
              _INI.get("stack_dir"), _INI.get("mpv_dir")]
    if getattr(sys, "frozen", False):
        cands.append(_script_dir())
    cands.append(os.path.join(_script_dir(), "stack"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "lens-presenter.exe")):
            return os.path.abspath(c)
    return None


STACK_DIR = _find_stack_dir()
PRESENTER_EXE = os.path.join(STACK_DIR, "lens-presenter.exe") if STACK_DIR else None
# Installed, lens-presenter.exe is the presenter itself. The one the setup puts in
# a stack from source is a copy of the interpreter, with a pyvenv.cfg beside it,
# and is handed the script; a lens run from source against an installed stack
# runs that stack's own presenter.
PRESENTER_SCRIPT = (os.path.join(_script_dir(), "lens_presenter.py")
                    if STACK_DIR and not getattr(sys, "frozen", False)
                    and os.path.isfile(os.path.join(STACK_DIR, "pyvenv.cfg")) else None)
CREATE_NO_WINDOW = 0x08000000

# Finding the folder only proves the presenter is in it, so the lens would start
# and show the screen back unchanged with nothing said. That reads as the app
# doing nothing rather than as a stack that is incomplete.
NEURAL_STACK = (
    ("ReShade.ini", "ReShade's configuration, which loads the add-ons"),
    ("dlss5-feed.addon64", "the DLSS 5 feed add-on"),
    ("renodx-dlss5.addon64", "the RenoDX DLSS 5 add-on"),
    ("nvngx_dlssnr.dll", "NVIDIA's Neural Rendering model, or the Cost Scaler in front of it"),
    # the super resolution DLL is required even though the lens never upscales:
    # with it renamed aside the lens started and rendered nothing at all,
    # feature=18 never created and the output within 0.01 of the input
    ("nvngx_dlss.dll", "NVIDIA's DLSS runtime, which the model loads through"),
)


def _missing_stack():
    """Which parts of the Neural Rendering stack are not in STACK_DIR.

    This warns rather than refuses. The names are matched exactly against a
    known good install, so a variant layout that works should not be blocked on
    a guess about filenames.
    """
    if not STACK_DIR:
        return []
    return [(n, d) for n, d in NEURAL_STACK
            if not os.path.isfile(os.path.join(STACK_DIR, n))]


def _read_nr_enabled():
    """Whether the add-on will start with Neural Rendering on, from ReShade.ini.

    The add-on persists its F6 toggle there as NeuralUplift and reads it at
    start: measured, a session begun with NeuralUplift=0 ran as a passthrough,
    an in-to-out difference of 1.2 against 2.2 with it on, same image. It is
    written back within about a second of the toggle (measured: 1.3 s), but
    the running state is tracked from the key itself, see Lens.watch_f6.
    """
    if not STACK_DIR:
        return True
    try:
        with open(os.path.join(STACK_DIR, "ReShade.ini"), encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                bare = line.strip()
                if bare.lower().startswith("neuraluplift="):
                    return bare.split("=", 1)[1].strip().lower() not in ("0", "no", "off", "false")
    except OSError:
        pass
    return True


def _addon_stack_passes():
    """Whether the add-on in the stack runs several passes itself.

    From its v5 line the RenoDX DLSS 5 add-on applies several neural passes
    inside one process, the count set by NRPasses in its section of
    ReShade.ini and read when the process starts. The setup fetches such a
    build. An older add-on has no pass count, and the presenter cannot make a
    second pass by capturing its own window, which it excludes from capture,
    so with one the lens runs one pass. The key's name is looked for in the
    add-on file itself.
    """
    if not STACK_DIR:
        return False
    try:
        with open(os.path.join(STACK_DIR, "renodx-dlss5.addon64"), "rb") as fh:
            return b"NRPasses" in fh.read()
    except OSError:
        return False


ADDON_PASSES = _addon_stack_passes()
ADDON_MAX_PASSES = 4        # the add-on's own choice stops at four


def _pass_limit():
    """The most passes the bar allows: the add-on's own four, or one with an
    add-on that cannot run the passes itself."""
    return ADDON_MAX_PASSES if ADDON_PASSES else 1


def _write_addon_settings(n):
    """Write the add-on's section of ReShade.ini for a presenter about to start,
    keeping the rest: NRPasses as n, and chained temporal history and the codec
    where the section holds no value for them.

    The add-on reads its settings only when its process starts: measured, an
    edit while it ran had changed nothing twelve seconds later, and a process
    that is terminated does not write the file back. So this runs after the old
    presenter is gone and before the new one spawns. Returns whether the file
    was written.

    Chained temporal history goes on, NRChainedHistory=1: without it the add-on
    resets its passes beyond the first every frame, and the picture pulses at
    two passes and up. The codec goes to Classic, NRCodecMode=0, which the
    add-on's developer asks for on the v5 line: with the add-on's default,
    Anchored, a model in Blender showed ghosting around it. A value the section
    already holds stays, so a choice made in the add-on's overlay, which the
    add-on writes back, is kept. The measurements are in docs/NOTES.md.
    """
    if not STACK_DIR:
        return False
    path = os.path.join(STACK_DIR, "ReShade.ini")
    keys = {"NRPasses": str(n), "NRChainedHistory": "1", "NRCodecMode": "0"}
    keep = {"NRChainedHistory", "NRCodecMode"}      # a value already there wins
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, done = [], False, set()

    def rest():
        for k, v in keys.items():
            if k not in done:
                out.append("%s=%s\n" % (k, v))
                done.add(k)

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                rest()
            inside = bare.lower() == "[renodx.dlss5]"
        elif inside and "=" in bare:
            name = bare.split("=", 1)[0].strip().lower()
            for k, v in keys.items():
                if name == k.lower():
                    if k not in done:
                        out.append(line if k in keep else "%s=%s\n" % (k, v))
                        done.add(k)
                    break
            else:
                out.append(line)
            continue
        out.append(line)
    if len(done) < len(keys):
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if not inside:
            out.append("\n[RenoDX.DLSS5]\n")
        rest()
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.writelines(out)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def _read_nr_passes():
    """NRPasses as the add-on's section of ReShade.ini holds it now, or None.

    The add-on writes its settings back within about a second of a change in
    its overlay (measured with F6: NeuralUplift was on disk 1.3 s after the
    press), so while the overlay is open this is how a pass count chosen there
    reaches the title bar. See Lens.follow_overlay.
    """
    if not STACK_DIR:
        return None
    try:
        with open(os.path.join(STACK_DIR, "ReShade.ini"), encoding="utf-8",
                  errors="replace") as fh:
            inside = False
            for line in fh:
                bare = line.strip()
                if bare.startswith("["):
                    inside = bare.lower() == "[renodx.dlss5]"
                elif inside and bare.lower().startswith("nrpasses="):
                    return int(bare.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return None


def _read_addon_section():
    """The add-on's section of ReShade.ini as it stands, key by key, in order.

    This is every setting the Home menu holds, as the add-on last wrote it
    back, which it does within about a second of a change there.
    """
    values = {}
    if not STACK_DIR:
        return values
    try:
        with open(os.path.join(STACK_DIR, "ReShade.ini"), encoding="utf-8", errors="replace") as fh:
            inside = False
            for line in fh:
                bare = line.strip()
                if bare.startswith("["):
                    inside = bare.lower() == "[renodx.dlss5]"
                elif inside and "=" in bare:
                    k, v = bare.split("=", 1)
                    values[k.strip()] = v.strip()
    except OSError:
        pass
    return values


# the add-on's section holds these for the install, not for a look: they are
# kept as they are when a profile replaces the rest
ADDON_KEEP = ("ConfigVersion", "EnableHooks")


def _replace_addon_section(values):
    """Make the add-on's section of ReShade.ini hold these values and nothing
    else, apart from ADDON_KEEP, which stay as they are. For a presenter about
    to start, since the add-on reads its settings only then."""
    if not STACK_DIR:
        return False
    path = os.path.join(STACK_DIR, "ReShade.ini")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, found = [], False, False
    kept = []

    def section():
        for line in kept:
            out.append(line)
        for k, v in values.items():
            if k not in ADDON_KEEP:
                out.append("%s=%s\n" % (k, v))
        out.append("\n")

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                section()
            inside = bare.lower() == "[renodx.dlss5]"
            if inside:
                found = True
            out.append(line)
        elif inside:
            if "=" in bare and bare.split("=", 1)[0].strip() in ADDON_KEEP:
                kept.append(line)
        else:
            out.append(line)
    if inside:
        section()
    if not found:
        out.append("\n[RenoDX.DLSS5]\n")
        section()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(out)
    except OSError:
        return False
    return True


# ---- profiles: named sets of everything that makes the picture, see Lens.capture_profile
def _load_profiles():
    try:
        with open(PROFILES, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("profiles"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"profiles": {}, "current": None}


def _save_profiles(d):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PROFILES, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
    except OSError:
        pass


# ---- the Cost Scaler proxy
# DLSSNR-Cost-Scaler is a proxy nvngx_dlssnr.dll that runs the neural model at
# a fraction of the frame's resolution and composites the result back onto the
# full frame. The setup puts it in front of the model, which becomes
# nvngx_dlssnr_real.dll, with the proxy's ini beside it. The proxy reads that
# ini when it starts and again within a second of any change. Neural Rendering
# in the lens runs as a D3D12 NGX session behind the Feed's Vulkan transport,
# which is the API the proxy hooks, so it works here as it does in a game.
#
# It pays where the neural pass is what limits the frame rate, which is a
# whole monitor or several passes, and costs a little where it is not. The
# change it makes to the picture is smaller the lower the scale, since the
# model sees fewer pixels of what, under a lens, is all detail. So it is on for
# fullscreen and off when windowed, unless cost_scaler in the ini says always,
# off, or manual, which leaves its ini alone. docs/NOTES.md has the numbers.
COST_SCALER = str(_INI.get("cost_scaler", "fullscreen")).strip().lower()
if COST_SCALER not in ("fullscreen", "always", "off", "manual"):
    COST_SCALER = "fullscreen"
try:
    # the neural working area over all the passes, in megapixels. 8 is
    # 6144x2560 at 0.70 for one pass and 0.50 for two, 3840x2160 at native for
    # one pass and 0.65 for two, and 2560x1440 at native up to two passes,
    # where the proxy would only add its own cost. A slower card can want less.
    COST_SCALER_MPX = max(0.5, min(80.0, float(_INI.get("cost_scaler_mpx", 8))))
except (TypeError, ValueError):
    COST_SCALER_MPX = 8.0


def _set_cost_scaler(mode):
    """Change the Cost Scaler rule in force, from Settings, and record it in
    the ini, where the default is left unwritten. The caller applies it."""
    global COST_SCALER
    COST_SCALER = mode
    _save_ini("cost_scaler", None if mode == "fullscreen" else mode)


def _proxy_installed():
    return bool(STACK_DIR) and all(os.path.isfile(os.path.join(STACK_DIR, n))
                                   for n in ("nvngx_dlssnr_real.dll", "nvngx_dlssnr.ini"))


def _proxy_scale(cw, ch, passes=1):
    """The proxy's resolution scale for a lens this size and pass count, or
    None for off.

    Scaled so the model's work over all the passes comes to about
    COST_SCALER_MPX megapixels, in the 5% steps the proxy uses, never below
    0.35, where the picture has lost too much detail, and off rather than on
    from 0.90 up, where too little is saved to pay for the proxy's own cost.
    """
    if cw <= 0 or ch <= 0:
        return None
    s = (COST_SCALER_MPX * 1e6 / float(cw * ch * max(1, passes))) ** 0.5
    if s >= 0.90:
        return None
    return max(0.35, int(s * 20 + 1e-9) / 20.0)


def _write_proxy(enabled, scale):
    """Set EnableProxy, and when enabling also ResolutionScale, in the proxy's
    ini, keeping the rest.

    Anamorphic scaling is switched off with the scale, so the uniform scale is
    what applies. Switching off touches nothing but the flag, so a scale of
    the user's own survives. Returns whether the file was written.
    """
    if not _proxy_installed():
        return False
    path = os.path.join(STACK_DIR, "nvngx_dlssnr.ini")
    keys = {"EnableProxy": "1" if enabled else "0"}
    if enabled:
        keys["ResolutionScale"] = "%.2f" % scale
        keys["EnableAnamorphic"] = "0"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, done = [], False, set()

    def rest():
        for k, v in keys.items():
            if k not in done:
                out.append("%s = %s\n" % (k, v))
                done.add(k)

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                rest()
            inside = bare.lower() == "[dlssnr_proxy]"
        elif inside and "=" in bare and not bare.startswith(";"):
            name = bare.split("=", 1)[0].strip().lower()
            for k, v in keys.items():
                if name == k.lower():
                    if k not in done:
                        out.append("%s = %s\n" % (k, v))
                        done.add(k)
                    break
            else:
                out.append(line)
            continue
        out.append(line)
    if len(done) < len(keys):
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if not inside:
            out.append("\n[DLSSNR_Proxy]\n")
        rest()
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.writelines(out)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


# The presenter's window is found by its process, and its title carries this
# process's id, so two lenses at once, one per monitor say, never pick up each
# other's presenter.
TITLE = "LensNR %d" % os.getpid()
__version__ = "0.5.0"        # beta; see CHANGELOG.md

DATA_DIR = (os.environ.get("NEURAL_LENS_DATA") or _INI.get("data_dir")
            or os.path.join(_script_dir(), "data"))
STATE = os.path.join(DATA_DIR, "lens-state.txt")
LOGDIR = os.path.join(DATA_DIR, "logs")
PROFILES = os.path.join(DATA_DIR, "profiles.json")     # named settings, see Lens.capture_profile

# Started without a console, as the installed program and the launcher are,
# everything the lens prints goes to lens.log in the log folder instead, and
# anything that used to stop and wait for Enter is shown as a dialog, since
# there is nothing left to read it in.
HEADLESS = ctypes.windll.kernel32.GetConsoleWindow() == 0


def _redirect_output():
    """Send stdout and stderr to lens.log, rolling the previous one into the
    archive first so it is pruned with the rest. Returns the path, or None."""
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        cur = os.path.join(LOGDIR, "lens.log")
        if os.path.isfile(cur):
            if os.path.getsize(cur) > 0:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                os.replace(cur, os.path.join(LOGDIR, "%s-lens.log" % stamp))
            else:
                os.remove(cur)
        f = open(cur, "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = sys.stderr = f
        return cur
    except OSError:
        return None


if sys.stdout is None:
    _redirect_output()
SHOT_DIR = (os.environ.get("NEURAL_LENS_SHOTS") or _INI.get("screenshot_dir")
            or os.path.join(DATA_DIR, "screenshots"))

BAR = 34
# The frame around the picture, which the lens is resized by: EDGE pixels down
# each side and along the bottom, the outer LINE of them the border's line and
# the rest a strip the mouse can catch. The top edge is the bar.
LINE, EDGE = 2, 8
CORNER = 16                  # how far from a grip's end still counts as the corner
MIN_W, MIN_H = 240, 120      # the smallest lens a drag can make
# Attached to a window, the chrome is a two pixel line around the region and
# this tab on its top edge, the only part of the lens that takes the mouse
TAB_W, TAB_H = 28, 14
ATTACH_SETTLE = 0.5          # seconds a target's new size must hold before the picture restarts
DIVIDER = 14                 # grab width of the A/B divider; the line drawn is 4
KEY_HOLD = 350               # ms a posted key stays down, longer than any frame
# Themes. Every colour the lens draws comes from one of these, chosen by
# theme = Name in the ini; Slate is the lens as it always looked. A themes.json
# in the data folder adds or replaces themes, one object per name with the same
# keys, so a theme can be made without touching the program.
THEMES = {
    "Slate": {"bg": "#1b2430", "fg": "#cbd5e1", "accent": "#4ade80", "dim": "#64748b", "warn": "#fbbf24",
              "cap": "#243040", "hover": "#334155", "field": "#0b1220", "tab": "#1e293b", "close": "#e11d48"},
    "Graphite": {"bg": "#232323", "fg": "#d6d6d6", "accent": "#f0b429", "dim": "#8a8a8a", "warn": "#f0b429",
                 "cap": "#2e2e2e", "hover": "#3d3d3d", "field": "#161616", "tab": "#2a2a2a", "close": "#d13c3c"},
    "Paper": {"bg": "#f3f4f6", "fg": "#1f2937", "accent": "#15803d", "dim": "#6b7280", "warn": "#b45309",
              "cap": "#e5e7eb", "hover": "#d1d5db", "field": "#ffffff", "tab": "#e5e7eb", "close": "#dc2626"},
    "Industrial": {"bg": "#2b2622", "fg": "#e7dcc8", "accent": "#f59e0b", "dim": "#8a7f70", "warn": "#fbbf24",
                   "cap": "#35302b", "hover": "#4a413a", "field": "#1f1b18", "tab": "#332d28", "close": "#b91c1c"},
}
THEME_KEYS = ("bg", "fg", "accent", "dim", "warn", "cap", "hover", "field", "tab", "close")


def _is_colour(v):
    v = str(v)
    return len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def _load_themes():
    """The built-in themes, with the data folder's themes.json laid over them:
    a theme there with a built-in name replaces it, a new name is added, and a
    theme missing keys takes them from Slate. A file that cannot be read is
    ignored, since a bad file must not stop the lens."""
    themes = {k: dict(v) for k, v in THEMES.items()}
    try:
        with open(os.path.join(DATA_DIR, "themes.json"), encoding="utf-8") as f:
            extra = json.load(f)
        for name, vals in (extra or {}).items():
            if isinstance(vals, dict) and str(name).strip():
                merged = dict(THEMES["Slate"])
                merged.update({k: str(v) for k, v in vals.items() if k in THEME_KEYS and _is_colour(v)})
                themes[str(name).strip()] = merged
    except Exception:
        pass
    return themes


ALL_THEMES = _load_themes()
THEME_NAME = str(_INI.get("theme", "Slate")).strip() or "Slate"
if THEME_NAME not in ALL_THEMES:
    THEME_NAME = "Slate"
_T = ALL_THEMES[THEME_NAME]
KEY = "#010203"                     # the colour keyed out of the chrome, never drawn
BG, FG, ACCENT, DIM, WARN = _T["bg"], _T["fg"], _T["accent"], _T["dim"], _T["warn"]
CAP = _T["cap"]                     # the window buttons' own shade on the title bar
HOVER, FIELD, TAB_BG, CLOSE = _T["hover"], _T["field"], _T["tab"], _T["close"]

# The title bar's minimise, maximise, restore and close buttons use Windows'
# own caption glyphs, from whichever Segoe icon font the machine has, so they
# read as the buttons every window has. Without either they fall back to plain
# characters Segoe UI draws.
CAPTION_FONTS = (("Segoe Fluent Icons", {"min": "", "max": "", "restore": "",
                                         "close": ""}),
                 ("Segoe MDL2 Assets", {"min": "", "max": "", "restore": "",
                                        "close": ""}))
CAPTION_PLAIN = {"min": "─", "max": "□", "restore": "❐", "close": "✕"}


def _caption_glyphs(families):
    """The font and the glyphs for the caption buttons, given the font families
    the machine has."""
    for fam, glyphs in CAPTION_FONTS:
        if fam in families:
            return (fam, 9), glyphs
    return ("Segoe UI", 12), CAPTION_PLAIN


def _display_hz():
    """Refresh rate of the primary display, for the delay meter's allowance."""
    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
                    ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
                    ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
                    ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                    ("dmDisplayOrientation", ctypes.c_ulong), ("dmDisplayFixedOutput", ctypes.c_ulong),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
                    ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
                    ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
                    ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
                    ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
                    ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
                    ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong)]
    try:
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
            hz = int(dm.dmDisplayFrequency)
            if 24 <= hz <= 1000:
                return hz
    except Exception:
        pass
    return 60


DISPLAY_HZ = _display_hz()

# Fullscreen fills the monitor the lens is on. It is an ini flag rather
# than a window state because the lens has to restart to change size, and the
# windowed geometry in the state file must survive the round trip, so the
# fullscreen lens keeps its pass count in a file of its own.
FULLSCREEN = str(_INI.get("fullscreen", "0")).strip().lower() in ("1", "yes", "on", "true")
FULL_STATE = os.path.join(DATA_DIR, "lens-state-fullscreen.txt")

# What the title bar shows beside the size. size, the default, is the size
# alone. fps is the rate of new pictures the presenter shows, averaged over the
# last few seconds, which is the rate the content under the lens hands it and
# never a limit of the lens's own: off by default, since read as the lens's
# own rate it misleads. detail is the frames captured and the new pictures
# shown, each per second.
READOUT = str(_INI.get("readout", "size")).strip().lower()
if READOUT not in ("fps", "detail", "both", "size"):
    READOUT = "size"
# The delay meter on the title bar, on unless the ini says latency = 0. See
# Lens._read_presenter for what it measures and what it adds.
LATENCY = str(_INI.get("latency", "1")).strip().lower() in ("1", "yes", "on", "true")
TITLE_SIZE = str(_INI.get("title_size", "1")).strip().lower() in ("1", "yes", "on", "true")
TITLE_STYLE = str(_INI.get("title_style", "0")).strip().lower() in ("1", "yes", "on", "true")
TITLE_INTENSITY = str(_INI.get("title_intensity", "0")).strip().lower() in ("1", "yes", "on", "true")
STYLE_NAMES = {"0": "Default", "1": "Natural", "2": "Cinematic"}     # the add-on's NRStyle
# Keep the picture ready while nothing changes: the presenter presents thirty
# times a second over a still instead of falling to four after ten seconds, so
# the first frame after any pause is on time. Off unless the ini says ready = 1.
# What it costs, and what the pause costs without it, is in lens_presenter.py.
READY = str(_INI.get("ready", "0")).strip().lower() in ("1", "yes", "on", "true")
# Copy the joined before and after to the clipboard when a screenshot is saved.
CLIP_SHOTS = str(_INI.get("clipboard_shots", "0")).strip().lower() in ("1", "yes", "on", "true")
# Check GitHub for a newer release when the lens starts, at most once a day.
# Off unless the ini says check_updates = 1, since it is a request to a server.
CHECK_UPDATES = str(_INI.get("check_updates", "0")).strip().lower() in ("1", "yes", "on", "true")
AUTO_UPDATE = str(_INI.get("auto_update", "0")).strip().lower() in ("1", "yes", "on", "true")
RELEASES_API = "https://api.github.com/repos/Leaps-Bounds/neural-lens/releases"
RELEASES_PAGE = "https://github.com/Leaps-Bounds/neural-lens/releases"


def _version_tuple(text):
    out = []
    for part in str(text).lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _latest_release():
    """(version, page url) of the newest release on GitHub, prereleases
    included since every release so far is one, or None when it cannot be read."""
    import urllib.request
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "neural-lens/" + __version__,
                                                        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        releases = json.loads(r.read().decode("utf-8"))
    for rel in releases:
        if not rel.get("draft") and rel.get("tag_name"):
            # the installer among the release's files, by its name and by its
            # home on GitHub, so nothing else is ever downloaded
            asset_url = asset_size = None
            for a in rel.get("assets") or []:
                name, link = str(a.get("name", "")), str(a.get("browser_download_url", ""))
                if (name.startswith("NeuralLens-Setup-") and name.endswith(".exe")
                        and link.startswith(RELEASES_PAGE + "/download/")):
                    asset_url, asset_size = link, int(a.get("size") or 0)
                    break
            return rel["tag_name"].lstrip("vV"), rel.get("html_url") or RELEASES_PAGE, asset_url, asset_size
    return None


# ---- global hotkeys
# Each action can have a key combination that works from anywhere, registered
# with RegisterHotKey on a thread of its own, since Tk's loop never hands
# WM_HOTKEY out. A registered combination is taken from every other program
# while the lens runs, which is why none is set until the user sets it, and why
# Home, F5 and F6 on their own are refused: ReShade reads Home and F5 from the
# presenter's own messages and the add-on reads F6 from the keyboard, so
# taking them would silence the overlay, its screenshot and the NR toggle.
HOTKEY_ACTIONS = (
    ("screenshot", "Save before and after"),
    ("add_pass", "Add a pass"),
    ("drop_pass", "Remove a pass"),
    ("split", "Live A/B split, on or off"),
    ("minimize", "Minimise, or bring back"),
    ("fullscreen", "Fullscreen, and back"),
    ("hide_bar", "Hide the title bar, and show it again"),
    ("profile", "Next profile"),
    ("ready", "Keep the picture ready, on or off"),
    ("detach", "Detach from the window"),
)
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
WM_HOTKEY, QS_ALLINPUT = 0x0312, 0x04FF
VK_BY_NAME = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "backspace": 0x08,
              "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
              "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "pause": 0x13, "scrolllock": 0x91,
              "printscreen": 0x2C, "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE,
              "slash": 0xBF, "backslash": 0xDC, "semicolon": 0xBA, "quote": 0xDE, "backquote": 0xC0,
              "bracketleft": 0xDB, "bracketright": 0xDD, "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D,
              "divide": 0x6F, "decimal": 0x6E}
for _i in range(1, 25):
    VK_BY_NAME["f%d" % _i] = 0x6F + _i
for _i in range(10):
    VK_BY_NAME["numpad%d" % _i] = 0x60 + _i
NAME_BY_VK = {v: k for k, v in VK_BY_NAME.items()}
RESERVED_KEYS = {0x24: "Home opens ReShade's overlay", 0x74: "F5 is ReShade's screenshot", 0x75: "F6 toggles Neural Rendering"}


def _parse_hotkey(text):
    """'Ctrl+Alt+S' to (modifiers, virtual key), or None when it is not a key."""
    if not text:
        return None
    parts = [p.strip().lower() for p in str(text).replace("-", "+").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "windows", "super"):
            mods |= MOD_WIN
        else:
            return None
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    elif key in VK_BY_NAME:
        vk = VK_BY_NAME[key]
    else:
        return None
    return mods, vk


def _hotkey_text(mods, vk):
    parts = [n for f, n in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win")) if mods & f]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        name = chr(vk)
    else:
        name = NAME_BY_VK.get(vk, "0x%02X" % vk)
        name = name.upper() if name.startswith("f") and name[1:].isdigit() else name.capitalize()
    return "+".join(parts + [name])


def _hotkey_problem(text):
    """Why this combination cannot be used, or None."""
    parsed = _parse_hotkey(text)
    if parsed is None:
        return "not a key"
    mods, vk = parsed
    if not mods and vk in RESERVED_KEYS:
        return RESERVED_KEYS[vk]
    if not mods and not (0x70 <= vk <= 0x87):
        return "needs Ctrl, Alt, Shift or Win, or a function key"
    return None


HOTKEYS = {a: str(_INI.get("hotkey_" + a, "")).strip() for a, _ in HOTKEY_ACTIONS}


class Hotkeys:
    """The listener: a thread with a message queue of its own, where the
    combinations are registered and WM_HOTKEY arrives. Actions go into a queue
    the lens drains on its timer; a combination another program already holds
    is reported in failed."""

    def __init__(self):
        import queue
        self.fired = queue.Queue()
        self.wanted = queue.Queue()
        self.failed = {}
        self.stopping = False
        self.tid = 0
        threading.Thread(target=self._run, daemon=True).start()

    def set(self, mapping):
        self.wanted.put(dict(mapping))
        if self.tid:
            u.PostThreadMessageW(self.tid, 0, 0, 0)     # WM_NULL, to end the wait

    def stop(self):
        self.stopping = True
        if self.tid:
            u.PostThreadMessageW(self.tid, 0, 0, 0)

    def _run(self):
        self.tid = k32.GetCurrentThreadId()
        registered = {}
        msg = w.MSG()
        while not self.stopping:
            while not self.wanted.empty():
                mapping = self.wanted.get()
                for i in registered:
                    u.UnregisterHotKey(None, i)
                registered, failed = {}, {}
                for n, (action, text) in enumerate(mapping.items()):
                    parsed = _parse_hotkey(text) if text and not _hotkey_problem(text) else None
                    if parsed is None:
                        continue
                    mods, vk = parsed
                    if u.RegisterHotKey(None, n + 1, mods | MOD_NOREPEAT, vk):
                        registered[n + 1] = action
                    else:
                        failed[action] = text
                self.failed = failed
            while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY and msg.wParam in registered:
                    self.fired.put(registered[msg.wParam])
            u.MsgWaitForMultipleObjectsEx(0, None, 100, QS_ALLINPUT, 0)
        for i in registered:
            u.UnregisterHotKey(None, i)

u = ctypes.windll.user32
k32 = ctypes.windll.kernel32
# Per monitor DPI aware, version 2, so every coordinate the lens uses is a
# physical pixel on whichever monitor it is on. System DPI awareness keeps the
# DPI the session logged on with and lives in a virtualized coordinate space:
# a 1400x760 lens on a monitor whose scaling differed from that produced a
# 1680x912 picture, exactly the ratio of the two scalings, while the lens
# believed its window was 1400x760.
try:
    u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    u.SetProcessDPIAware()
try:
    ctypes.windll.winmm.timeBeginPeriod(1)   # default granularity is 15.6 ms
except Exception:
    pass
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_THICKFRAME, WS_MAXIMIZEBOX = 0x00040000, 0x00010000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x08000000
WS_EX_TOPMOST = 0x00000008
WDA_EXCLUDEFROMCAPTURE = 0x00000011
HWND_TOPMOST = ctypes.c_void_p(-1)          # pointer sized, NOT int -1
HWND_NOTOPMOST = ctypes.c_void_p(-2)
HWND_TOP = 0
GW_HWNDPREV, GA_ROOT = 3, 2
u.WindowFromPoint.argtypes = [w.POINT]      # a POINT by value, not a pointer to one
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_FRAMECHANGED = 0x0020
SW_HIDE, SW_SHOWNA = 0, 8


def _save_ini(key, value):
    """Write one key into neural-lens.ini beside the script, keeping the rest.

    A value of None removes the key, so a setting put back to its default
    follows the default again rather than pinning today's value.
    """
    path = _ini_path()
    lines, done = [], False
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                bare = line.strip()
                if bare and bare[0] not in "#;[" and "=" in bare \
                        and bare.split("=", 1)[0].strip().lower() == key:
                    if value is not None:
                        lines.append("%s = %s\n" % (key, value))
                    done = True
                else:
                    lines.append(line)
    except OSError:
        pass
    if not done and value is not None:
        lines.append("%s = %s\n" % (key, value))
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


def archive_logs():
    """Keep the PREVIOUS session's logs before the presenter overwrites them.
    Without this, launching again destroys the only evidence of a failure.

    ReShade rotates to ReShade.log1, ReShade.log2 and so on when the first file
    is already locked, so every one of them is kept, along with the Feed's and
    the Cost Scaler's logs.
    """
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        names = [n for n in os.listdir(STACK_DIR)
                 if n.startswith("ReShade.log") or n in ("dlss5-feed.log", "nvngx_dlssnr_proxy.log")]
        for name in sorted(names):
            src = os.path.join(STACK_DIR, name)
            if os.path.isfile(src) and os.path.getsize(src) > 0:
                shutil.copy2(src, os.path.join(LOGDIR, "%s-%s" % (stamp, name)))
        # the presenter's stderr is appended to for the life of a session, and
        # the pruning below sorts by name, so a file not carrying a stamp is
        # never reached and would grow without bound. Roll it into the archive.
        prev = os.path.join(LOGDIR, "presenter-stderr.log")
        if os.path.isfile(prev):
            if os.path.getsize(prev) > 0:
                os.replace(prev, os.path.join(LOGDIR, "%s-presenter-stderr.log" % stamp))
            else:
                os.remove(prev)
        files = sorted(os.listdir(LOGDIR))
        while len(files) > 80:
            os.remove(os.path.join(LOGDIR, files.pop(0)))
    except Exception:
        pass


def _own_windows():
    """Every visible top-level window owned by this process.

    Nothing of ours may be in the picture the presenter captures. Listing them
    by name cannot work, because the menu, the settings dialog and any message
    box are created and destroyed on demand.
    """
    pid = k32.GetCurrentProcessId()
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if u.IsWindowVisible(h):
            p = w.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid:
                hits.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hits


def find_window(pid, cls="GLFW30"):
    """The visible window of the class that belongs to the process, the moment
    it is visible, whatever its title. The presenter's window class is glfw's."""
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        c = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, c, 256)
        if c.value != cls:
            return True
        p = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            hits.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


def monitor_rect(x, y):
    """The full rectangle of the monitor containing the point, in pixels."""
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", ctypes.c_ulong)]
    u.MonitorFromPoint.restype = ctypes.c_void_p
    u.MonitorFromPoint.argtypes = [w.POINT, ctypes.c_ulong]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    h = u.MonitorFromPoint(w.POINT(int(x), int(y)), 2)     # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if h and u.GetMonitorInfoW(h, ctypes.byref(mi)):
        r = mi.rcMonitor
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def monitor_of(x, y):
    """The monitor containing the point, as (index from 1 in enumeration order,
    left, top). Windows Graphics Capture numbers monitors the same way."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.RECT),
                        ctypes.c_void_p)
    def cb(hmon, hdc, prc, lp):
        r = prc.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return True

    u.EnumDisplayMonitors(None, None, cb, 0)
    for i, (l, t, r, b) in enumerate(found, 1):
        if l <= x < r and t <= y < b:
            return i, l, t
    return 1, 0, 0


def monitor_layout():
    """The monitors as rectangles in enumeration order, the order Windows Graphics
    Capture numbers them in. Compared on a timer to notice displays being added,
    removed or rearranged."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.RECT),
                        ctypes.c_void_p)
    def cb(hmon, hdc, prc, lp):
        r = prc.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return True

    u.EnumDisplayMonitors(None, None, cb, 0)
    return tuple(found)


def work_area(x, y):
    """The work area, the monitor less the taskbar, of the monitor containing the
    point or else the one nearest to it, in pixels."""
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", ctypes.c_ulong)]
    u.MonitorFromPoint.restype = ctypes.c_void_p
    u.MonitorFromPoint.argtypes = [w.POINT, ctypes.c_ulong]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    h = u.MonitorFromPoint(w.POINT(int(x), int(y)), 2)     # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if h and u.GetMonitorInfoW(h, ctypes.byref(mi)):
        r = mi.rcWork
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def fit_rect(x, y, cw, ch, area=None):
    """The lens moved, and shrunk if it has to be, so that the picture, its title
    bar and its border lie inside one monitor's work area.

    The presenter captures one monitor, so a lens hanging over that monitor's
    edge shows a picture that no longer lines up with what is under it, and a
    lens larger than the monitor gets no frames at all. The monitor is the one
    under the lens's centre, or the nearest when that point is on none. A lens
    that has to shrink keeps its proportions. area stands in for the monitor's
    work area when given.
    """
    mx, my, mw, mh = area or work_area(x + cw // 2, y + ch // 2)
    room_w, room_h = mw - 2 * EDGE, mh - BAR - EDGE
    scale = min(1.0, room_w / float(cw), room_h / float(ch))
    if scale < 1.0:
        cw, ch = int(cw * scale), int(ch * scale)
    cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
    x = max(mx + EDGE, min(x, mx + mw - EDGE - cw))
    y = max(my + BAR, min(y, my + mh - EDGE - ch))
    return x, y, cw, ch


class PopupMenu:
    """The title bar menu, drawn by the lens itself.

    A native popup only dismisses on an outside click or Escape while its
    owner is the foreground window, and the title bar never activates so that
    the application under the lens keeps the focus. Taking the foreground for
    the menu's lifetime worked when it worked, but the click that dismissed
    the menu was consumed, so the menu button looked dead on that click, and
    when the foreground could not be taken the button posted a second menu on
    top of the first, which read as a menu that cannot close. This is a plain
    window of ours instead: the button opens it and closes it, a click
    anywhere else closes it, so does Escape, nothing is consumed, and the
    focus stays where it was.
    """

    def __init__(self, lens):
        self.lens = lens
        self.win = None
        self.pressed = False

    def toggle(self, items):
        if self.win is not None:
            self.close()
        else:
            self.open(items)

    def open(self, items):
        lens = self.lens
        t = tk.Toplevel(lens.root)
        self.win = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=ACCENT)
        box = tk.Frame(t, bg=BG)
        box.pack(padx=1, pady=1)
        for item in items:
            if item is None:
                tk.Frame(box, bg=HOVER, height=1).pack(fill="x", padx=6, pady=3)
                continue
            text, command, enabled = item
            lbl = tk.Label(box, text=text, bg=BG, fg=FG if enabled else DIM, anchor="w",
                           padx=14, pady=4, font=("Segoe UI", 10))
            lbl.pack(fill="x")
            if enabled and command is not None:
                lbl.bind("<Enter>", lambda e, l=lbl: l.config(bg=HOVER))
                lbl.bind("<Leave>", lambda e, l=lbl: l.config(bg=BG))
                lbl.bind("<Button-1>", lambda e, c=command: self.choose(c))
        t.update_idletasks()
        wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
        bx, top, bottom = lens.menu_anchor()
        mx, my, mw, mh = monitor_rect(bx + 10, top + 10)
        x = max(mx, min(bx + 6, mx + mw - wd))
        y = bottom
        if y + ht > my + mh:
            y = top - ht                  # no room below the bar or the tab
        t.geometry("%dx%d+%d+%d" % (wd, ht, x, max(my, y)))
        t.update()
        h = u.GetParent(t.winfo_id()) or t.winfo_id()
        u.SetWindowLongPtrW(h, GWL_EXSTYLE, u.GetWindowLongPtrW(h, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
        u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)     # never in the picture
        self.pressed = bool(u.GetAsyncKeyState(0x01) & 0x8000)
        lens.root.after(30, self.watch)

    def choose(self, command):
        self.close()
        try:
            command()
        except Exception:
            pass

    def inside(self, widget, px, py):
        try:
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            return x <= px < x + widget.winfo_width() and y <= py < y + widget.winfo_height()
        except Exception:
            return False

    def watch(self):
        """Close on a click anywhere but the menu or the button, or on Escape.

        The button's own handler toggles, and the menu's labels take their own
        clicks, so those two are left alone. The state is polled rather than
        bound, since neither the menu nor the bar ever has the keyboard focus."""
        if self.win is None or self.lens.closing:
            return
        if u.GetAsyncKeyState(0x1B) & 0x8000:
            self.close()
            return
        down = any(u.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))
        if down and not self.pressed:
            pt = w.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            if not self.inside(self.win, pt.x, pt.y) and not any(
                    self.inside(wdg, pt.x, pt.y) for wdg in self.lens.menu_widgets()):
                self.close()
                return
        self.pressed = down
        self.lens.root.after(30, self.watch)

    def close(self):
        t, self.win = self.win, None
        if t is not None:
            try:
                t.destroy()
            except Exception:
                pass


class Lens:
    def __init__(self, root, x, y, cw, ch, passes, fullscreen=False):
        self.root, self.cw, self.ch = root, cw, ch
        self.fullscreen = fullscreen    # the title bar overlays the picture, no drag
        self.split = None           # A/B divider as a fraction of the width, or off
        self.divider = None         # the draggable divider window while split is on
        self.drag = None
        self.closing = False
        self.rebuilding = False     # True while set_passes is replacing the presenter
        self.tweak = False          # True while the viewport is interactive
        self.tweak_until = 0.0      # the overlay is followed until then after Done
        self.tweak_prev = None      # the window that had the keyboard before tweak mode
        self.proxy_scale = None     # the Cost Scaler's scale this session, or off
        self.fs_origin = (x, y)     # fullscreen: where the picture is, for good
        self.frames = 0             # frames the presenter has captured
        self.t_first = None
        self.out_frames = 0         # new pictures the presenter has shown
        self.pres_in = self.pres_out = 0.0   # the last second's captures and new pictures
        self.mon_x = self.mon_y = 0          # the captured monitor's origin
        self.readout = READOUT      # what the title bar shows beside the size
        self.show_size = TITLE_SIZE  # the size itself on the title bar
        self.latency_on = LATENCY   # the latency meter on the title bar
        self.auto_update_on = AUTO_UPDATE   # offer to install a newer release, after asking
        self.show_style = TITLE_STYLE       # the Home menu's NR style on the title bar
        self.show_intensity = TITLE_INTENSITY   # its overall intensity, shown only
        self.addon_seen = {}                # the add-on's section as the bar last read it
        self.ready = READY          # thirty presents a second over a still, always
        self.clip_shots = CLIP_SHOTS   # the joined before and after to the clipboard too
        self.check_updates_on = CHECK_UPDATES
        self.latency_ms = None      # its latest reading, the whole delay, estimated
        self.latency_raw = None     # the measured part alone, capture to present
        self._shown = None          # (time, out_frames) behind the fps readout
        self._fps_hist = collections.deque(maxlen=3)
        self.restart = False        # set by the folder settings, read by main()
        self.minimized = False      # hidden, with the presenter paused, until the taskbar button
        self.profiles = _load_profiles()
        self.profile = self.profiles.get("current")      # the name on the bar, or None
        if self.profile not in self.profiles["profiles"]:
            self.profile = None
        self.anchor_widget = None   # what the menu opens under, when not the bar
        self.attach = None          # the window the lens is attached to, see attach_to
        self.tab = None             # the tab on the top edge while attached or folded
        self.folded = False         # the title bar and frame folded away, see fold
        self.tab_x = 12             # where along the top edge the tab sits
        self.tab_drag = None
        self.picking = None         # a pick of a window or region in progress
        self.rs = None              # a resize by the frame in progress, see _grip_down
        self.shot_busy = False
        self.shot_event = threading.Event()
        self.shot_reply = None
        self.probe_event = threading.Event()
        self.probe_reply = None
        self.stages = []            # [{title, proc, hwnd}]: the presenter, one entry
        self.popup = PopupMenu(self)
        self.hotkeys = Hotkeys()
        self.hotkeys.set(HOTKEYS)
        self.root.after(50, self.poll_hotkeys)
        self.root.after(15000, self.check_updates_at_start)     # once the picture is up
        self.passes = passes        # neural passes, run inside the add-on
        self.pending = passes       # the pass count chosen on the bar, applied by Set
        self.nr_on = _read_nr_enabled()   # Neural Rendering on, as far as the lens knows
        self.last_arrival = time.perf_counter()   # the presenter's last report of a captured frame
        self.healthy_since = time.perf_counter()  # when the current presenter started
        self.recover_wait = 1.0     # seconds before the next start after a lost capture
        self.recover_after = None   # that start, while it is pending
        self.layout = monitor_layout()            # the monitors the presenter started under
        self.layout_seen = (self.layout, time.perf_counter())   # the last layout read, and since when

        # ---- chrome (tk): title bar + subtle border + transparent hole
        t = tk.Toplevel(root)
        self.t = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=ACCENT)
        t.attributes("-transparentcolor", KEY)
        # windowed, the bar sits above the picture inside a frame that also draws
        # the border. Fullscreen the bar sits above the picture too, but the
        # chrome is the bar alone: a frame around a picture that fills the
        # monitor would be larger than the screen, and a layered window that is
        # comes up blank, with nothing drawn at all. layout_chrome places it all.
        bar = tk.Frame(t, bg=BG, height=BAR)
        self.bar = bar
        self.hole = tk.Frame(t, bg=KEY)         # the picture shows through this

        self.menu_btn = tk.Label(bar, text=" \u2630 ", bg=BG, fg=FG, font=("Segoe UI", 12))
        self.menu_btn.pack(side="left", padx=(6, 0))
        self.menu_btn.bind("<Button-1>", self.menu)
        tk.Label(bar, text="  DLSS 5 Neural Lens", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.info = tk.Label(bar, text="%d x %d" % (cw, ch), bg=BG, fg=DIM,
                             font=("Consolas", 9))
        self.info.pack(side="left", padx=10)
        # the profile selector: the name of the profile in use, or Profile
        self.prof_btn = tk.Label(bar, text="▾ Profile", bg=BG, fg=DIM, font=("Segoe UI", 9), padx=4)
        self.prof_btn.pack(side="left")
        self.prof_btn.bind("<Button-1>", lambda e: self.profile_menu())
        self.prof_btn.bind("<Enter>", lambda e: self.prof_btn.config(bg=HOVER))
        self.prof_btn.bind("<Leave>", lambda e: self.prof_btn.config(bg=BG))

        # the Home menu's NR style and overall intensity, on the bar when Settings
        # asks for them. Both follow the add-on's section, which it writes within a
        # second of a change in its overlay. The style is picked here and restarts
        # the picture, since the add-on reads its section only when it starts; the
        # intensity is shown only, the Home menu being the live way to move it
        self.style_btn = tk.Label(bar, text="▾ Default", bg=BG, fg=DIM, font=("Segoe UI", 9), padx=4)
        self.style_btn.bind("<Button-1>", lambda e: self.style_menu())
        self.style_btn.bind("<Enter>", lambda e: self.style_btn.config(bg=HOVER))
        self.style_btn.bind("<Leave>", lambda e: self.style_btn.config(bg=BG))
        self.intensity_lbl = tk.Label(bar, text="intensity 1.00", bg=BG, fg=DIM, font=("Consolas", 9), padx=4)
        self.show_bar_mirrors()

        # the caption buttons, right to left as on every window: close,
        # maximise or restore, minimise. They sit on a shade of their own, so
        # they read as the window's buttons rather than as more pass controls
        try:
            capfont, self.glyphs = _caption_glyphs(set(tkfont.families(root)))
        except Exception:
            capfont, self.glyphs = ("Segoe UI", 12), CAPTION_PLAIN
        self.x_btn = tk.Label(bar, text=self.glyphs["close"], bg=CAP, fg=FG, font=capfont, padx=11)
        self.x_btn.pack(side="right", fill="y")
        self.x_btn.bind("<Button-1>", lambda e: self.quit())
        self.x_btn.bind("<Enter>", lambda e: self.x_btn.config(bg=CLOSE))
        self.x_btn.bind("<Leave>", lambda e: self.x_btn.config(bg=CAP))
        self.max_btn = tk.Label(bar, text=self.glyphs["restore" if fullscreen else "max"], bg=CAP,
                                fg=FG, font=capfont, padx=11)
        self.max_btn.pack(side="right", fill="y")
        self.max_btn.bind("<Button-1>", lambda e: self.toggle_fullscreen())
        self.min_btn = tk.Label(bar, text=self.glyphs["min"], bg=CAP, fg=FG, font=capfont, padx=11)
        self.min_btn.pack(side="right", fill="y")
        self.min_btn.bind("<Button-1>", lambda e: self.minimize())
        for b in (self.max_btn, self.min_btn):
            b.bind("<Enter>", lambda e, b=b: b.config(bg=HOVER))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=CAP))
        # a line between the caption buttons and the pass controls: without it
        # the minimise glyph reads as the minus of the pass count
        tk.Frame(bar, bg=HOVER, width=1).pack(side="right", fill="y", padx=(4, 6), pady=9)

        # plus and minus only choose a number; Set restarts the presenter at it,
        # so going from one pass to three is one restart rather than two
        self.set_btn = tk.Label(bar, text=" Set ", bg=BG, fg=DIM, font=("Segoe UI", 10, "bold"))
        self.set_btn.pack(side="right", padx=(2, 4))
        self.set_btn.bind("<Button-1>", lambda e: self.apply_passes())
        self.plus = tk.Label(bar, text=" + ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.plus.pack(side="right")
        self.plus.bind("<Button-1>", lambda e: self.bump_passes(1))
        self.pass_lbl = tk.Label(bar, text="1 pass", bg=BG, fg=ACCENT, font=("Consolas", 9))
        self.pass_lbl.pack(side="right", padx=2)
        self.minus = tk.Label(bar, text=" \u2212 ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.minus.pack(side="right")
        self.minus.bind("<Button-1>", lambda e: self.bump_passes(-1))
        for b in (self.plus, self.minus, self.set_btn):
            b.bind("<Enter>", lambda e, b=b: b.config(bg=HOVER))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=BG))

        # the frame the lens is resized by: a strip down each side and one along
        # the bottom, inside the border's line. Which way a drag on one resizes
        # depends on where it starts, see _grip_zone.
        self.grips = {}
        for side in ("w", "e", "s"):
            g = tk.Frame(t, bg=BG)
            g.bind("<Motion>", lambda e, s=side: self._grip_hover(s, e))
            g.bind("<ButtonPress-1>", lambda e, s=side: self._grip_down(s, e))
            g.bind("<B1-Motion>", self._grip_move)
            g.bind("<ButtonRelease-1>", self._grip_up)
            self.grips[side] = g

        # everything that answers a click of its own keeps that click; the rest of
        # the bar, the intensity readout included, drags the lens
        nodrag = (self.x_btn, self.max_btn, self.min_btn, self.menu_btn, self.plus, self.minus,
                  self.set_btn, self.prof_btn, self.style_btn)
        for wdg in (bar,) + tuple(bar.winfo_children()):
            if wdg not in nodrag:               # the separator drags the lens like the bar
                wdg.bind("<ButtonPress-1>", self.down)
                wdg.bind("<B1-Motion>", self.move)
                wdg.bind("<ButtonRelease-1>", self.up)
        self.layout_chrome(x, y)
        self.chrome = u.GetParent(t.winfo_id()) or t.winfo_id()
        # never take foreground: the lens is a tool window floating over whatever
        # you are actually using, and stealing focus costs the user their next
        # click. And never in the picture: the presenter captures the monitor, so
        # the chrome is excluded from capture for good, and every other window of
        # ours by watch_filter as it appears.
        _ex = u.GetWindowLongPtrW(self.chrome, GWL_EXSTYLE)
        u.SetWindowLongPtrW(self.chrome, GWL_EXSTYLE, _ex | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(self.chrome, WDA_EXCLUDEFROMCAPTURE)

        # ---- the presenter. The add-on's settings go into ReShade.ini before
        # it starts, see _write_addon_settings, and the Cost Scaler's ini is set
        # for this size and count.
        if ADDON_PASSES:
            _write_addon_settings(passes)
        self.apply_proxy()
        self._build_presenter(x, y)
        self.raise_chrome()
        self.aim()
        self.update_info()
        self.watch_f6()
        self.root.after(1000, self.stats)
        self.root.after(200, self.watch_filter)

    # ---- the presenter
    def visible(self):
        return self.stages[-1]["hwnd"]

    def _build_presenter(self, x, y):
        """Start the presenter on the lens rect: it captures the monitor the lens
        is on, cropped to the lens, and presents each frame as it arrives."""
        idx, mx, my = monitor_of(x + self.cw // 2, y + self.ch // 2)
        self.mon_x, self.mon_y = mx, my
        proc, hwnd = self.spawn_presenter(TITLE, x, y, "monitor:%d" % idx, x - mx, y - my)
        self.stages.append({"title": TITLE, "proc": proc, "hwnd": hwnd})

    def spawn_presenter(self, title, x, y, source, cx, cy):
        """Start the presenter and return (proc, hwnd). See lens_presenter.py for
        what it does, what it reads on stdin and what it prints."""
        env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
        cmd = [PRESENTER_EXE] + ([PRESENTER_SCRIPT] if PRESENTER_SCRIPT else []) + [
            "--source", source, "--at", str(x), str(y), "--size", str(self.cw), str(self.ch),
            "--crop", str(cx), str(cy), "--title", title, "--exclude"] + (["--ready"] if self.ready else [])
        errlog = os.path.join(LOGDIR, "presenter-stderr.log")
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            errf = open(errlog, "a", encoding="utf-8", errors="replace")
            errf.write("\n--- %s  %s ---\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), title))
            errf.flush()
        except OSError:
            errf, errlog = subprocess.DEVNULL, None
        # no console window: from source the presenter is a copy of python.exe,
        # which would open one when the lens itself has none
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errf,
                                cwd=STACK_DIR, env=env, text=True, bufsize=1,
                                creationflags=CREATE_NO_WINDOW)
        if errf is not subprocess.DEVNULL:
            try:
                errf.close()          # the child holds its own handle
            except OSError:
                pass
        threading.Thread(target=self._read_presenter, args=(proc,), daemon=True).start()
        hwnd = None
        for i in range(700):
            hwnd = find_window(proc.pid)
            if hwnd or proc.poll() is not None:
                break
            if i == 100:
                # five seconds of nothing reads as a hang, so say what is being
                # waited for rather than leaving it silent
                print("waiting for the presenter to open its window ...", flush=True)
            time.sleep(0.05)
        if not hwnd:
            try:
                proc.kill()
            except Exception:
                pass
            raise SystemExit("\n".join([
                "The presenter never opened a window.",
                "",
                "It runs as lens-presenter.exe in the stack folder:",
                "  %s" % STACK_DIR,
                "",
                ("What it printed is in:\n  %s" % errlog) if errlog
                else "Its own output could not be captured.",
            ]))
        st = u.GetWindowLongPtrW(hwnd, GWL_STYLE)
        u.SetWindowLongPtrW(hwnd, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
        self.set_interactive(hwnd, False)
        if self.attach is not None:
            # not above everything: one step above the target, see stack_above_target
            u.SetWindowPos(hwnd, HWND_NOTOPMOST, x, y, self.cw, self.ch, SWP_NOACTIVATE)
        else:
            u.SetWindowPos(hwnd, HWND_TOPMOST, x, y, self.cw, self.ch, SWP_NOACTIVATE)
        return proc, hwnd

    def _read_presenter(self, proc):
        """The presenter's stdout: a stats line a second, and replies.

        The delay meter: the presenter reports the median, over each second,
        of its present call against the capture's own timestamp, which names
        the composition the frame belongs to. The composition and scanout after
        the present come to about a refresh and a half: measured with a window
        flipping black and white, the flip took 8 ms to reach the presenter's
        output where the meter read -5 at 120 Hz. So that much is added and
        the bar shows the whole delay.
        """
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("stats "):
                try:
                    kv = dict(p.split("=", 1) for p in line[6:].split())
                    new, arrived = int(kv["new"]), int(kv["arrived"])
                    meter = float(kv["meter"])
                except (ValueError, KeyError):
                    continue
                if self.t_first is None:
                    self.t_first = time.perf_counter()
                self.frames += arrived
                self.out_frames += new
                self.pres_in, self.pres_out = float(arrived), float(new)
                if arrived > 0:
                    self.last_arrival = time.perf_counter()
                if meter == meter:
                    self.latency_raw = meter
                    self.latency_ms = meter + 1.5 * 1000.0 / float(DISPLAY_HZ)
            elif line.startswith("shot "):
                self.shot_reply = line[5:]
                self.shot_event.set()
            elif line.startswith("probe "):
                self.probe_reply = line[6:]
                self.probe_event.set()
            elif line.startswith("capture lost"):
                print(line, flush=True)
                try:
                    self.root.after(0, self.capture_lost, line[13:])
                except Exception:
                    pass
            elif line.startswith("presenter ready") or line in ("paused", "resumed"):
                print(line, flush=True)

    def tell_presenter(self, text):
        for s in list(self.stages):
            try:
                s["proc"].stdin.write(text + "\n")
                s["proc"].stdin.flush()
            except (OSError, ValueError, AttributeError):
                pass

    def _kill_stage(self, s):
        for step in (lambda: s["proc"].stdin.close(),
                     lambda: (s["proc"].terminate(), s["proc"].wait(timeout=3))):
            try:
                step()
            except Exception:
                pass
        try:
            if s["proc"].poll() is None:
                s["proc"].kill()
        except Exception:
            pass

    # ---- keeping the picture clean and the lens on top
    def watch_filter(self):
        """Every window of ours out of the picture, and the lens on top.

        The menu or a dialog appears and vanishes with no hook to act on, so
        the exclusion from capture is re-applied on a timer, and the stacking
        is checked on the same one.
        """
        if self.closing:
            return
        for hx in _own_windows():
            try:
                u.SetWindowDisplayAffinity(hx, WDA_EXCLUDEFROMCAPTURE)
            except Exception:
                pass
        if not self.minimized and self.attach is None:
            try:
                self.keep_chrome_on_top()
                self.keep_stage_on_top()
            except Exception:
                pass
        try:
            self.watch_layout()
        except Exception:
            pass
        if not self.closing:
            self.root.after(200, self.watch_filter)

    def keep_stage_on_top(self):
        """Raise the lens again when an ordinary window has been stacked over it.

        Windows puts a maximised or full screen window that becomes the
        foreground above every topmost window: measured with the Photos app,
        maximised over a windowed lens it sat above the presenter and stayed
        there, and only a fresh HWND_TOPMOST brought the lens back. So
        whenever a visible window that is neither ours nor itself topmost
        sits above the presenter and overlaps the lens, the whole lens is
        raised, the same as the taskbar button does. Windows that are
        themselves topmost are left alone, so a tool the user keeps on top is
        not fought over.
        """
        if not self.stages or self.rebuilding:
            return
        stage = self.visible()
        lx, ly = self.inner()
        own = set(_own_windows()) | {s["hwnd"] for s in self.stages} | {self.chrome}
        h = u.GetWindow(stage, 3)                    # GW_HWNDPREV: the window above
        while h:
            if (h not in own and u.IsWindowVisible(h)
                    and not u.GetWindowLongPtrW(h, GWL_EXSTYLE) & WS_EX_TOPMOST):
                r = w.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                if r.right > lx and r.left < lx + self.cw and r.bottom > ly and r.top < ly + self.ch:
                    self.bring_back()
                    return
            h = u.GetWindow(h, 3)

    def keep_chrome_on_top(self):
        """Raise the chrome again if the presenter has climbed above it.

        The A/B divider lies over the picture, so a presenter above the chrome
        hides it. Only the presenter counts: menus and dialogs are meant to be
        above the chrome.
        """
        stages = {s["hwnd"] for s in self.stages}
        tops = [self.chrome]
        if self.divider is not None:
            try:
                tops.append(u.GetParent(self.divider.winfo_id()) or self.divider.winfo_id())
            except Exception:
                pass
        for top in tops:
            h = u.GetWindow(top, 3)                  # GW_HWNDPREV, the window above
            while h:
                if h in stages:
                    self.raise_chrome()
                    return
                h = u.GetWindow(h, 3)

    def raise_chrome(self):
        u.SetWindowPos(self.chrome, HWND_TOPMOST, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        if self.tab is not None and self.attach is None:
            # folded: the tab is the only thing that takes the mouse, and it has
            # to stay above the picture, which is re-raised the same way
            try:
                th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
                u.SetWindowPos(th, HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        if self.divider is not None:
            try:
                h = u.GetParent(self.divider.winfo_id()) or self.divider.winfo_id()
                u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        if getattr(self, "popup", None) is not None and self.popup.win is not None:
            try:
                hm = u.GetParent(self.popup.win.winfo_id()) or self.popup.win.winfo_id()
                u.SetWindowPos(hm, HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass

    def bring_back(self):
        """Put the presenter and the title bar back on top.

        A window that is itself set to stay on top can leave the lens
        underneath it and demoted from topmost, with no way back short of
        restarting it. raise_chrome only re-asserts the title bar, so on its
        own it would put a bar back on top of nothing. Attached, the lens
        belongs one step above its target, so the target comes forward and
        the lens with it.
        """
        if self.attach is not None:
            try:
                u.SetForegroundWindow(self.attach["hwnd"])
            except Exception:
                pass
            self.stack_above_target()
            return
        for s in list(self.stages):
            try:
                u.SetWindowPos(s["hwnd"], HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        self.raise_chrome()

    # ---- taskbar
    # The title bar cannot have a taskbar button: it is an override redirect
    # window that never activates, so the mouse can reach the application
    # under the lens. The hidden tk root stands in for it. It is fully
    # transparent and parked minimised, so it is never seen, but its button is
    # on the taskbar. Clicking that restores the root, which lands in
    # _taskbar_click: a minimised lens comes back, any other comes back to the
    # top, and the root is minimised again before it can be noticed. Tk
    # toplevels on Windows are not owned by the root, so minimising it does
    # not take the title bar with it; measured rather than assumed.
    def show_in_taskbar(self):
        r = self.root
        r.title("DLSS 5 Neural Lens")
        r.geometry("1x1+0+0")
        try:
            r.attributes("-alpha", 0.0)
        except Exception:
            pass
        r.protocol("WM_DELETE_WINDOW", self.quit)   # Close window on the button
        r.iconify()
        r.update_idletasks()
        r.bind("<Map>", self._taskbar_click)

    def _taskbar_click(self, _event=None):
        if self.closing:
            return
        if self.minimized:
            self.restore()
        else:
            self.bring_back()
        self.root.after(80, self.root.iconify)

    def minimize(self):
        """Hide the lens, leaving its taskbar button, and pause the presenter.

        Paused, the presenter stops its capture and presents nothing, so no
        neural pass runs and nothing of the lens costs the GPU or the CPU
        anything until the taskbar button brings it back. Neural Rendering is
        not switched off for it: the add-on only runs on a present, and with
        none it keeps whatever state it had for the way back.
        """
        if self.closing or self.minimized or self.rebuilding or not self.stages or self.rs:
            return
        self.popup.close()
        if self.tweak:
            # the overlay closes on a Home the presenter has to present a frame
            # to notice, so it gets that frame before the pause
            self.end_tweak()
            self.root.after(KEY_HOLD + 400, self.minimize)
            return
        self.minimized = True
        self.tell_presenter("pause")
        for s in self.stages:
            u.ShowWindow(s["hwnd"], SW_HIDE)
        if self.divider is not None:
            try:
                self.divider.withdraw()
            except Exception:
                pass
        if self.tab is not None:
            try:
                self.tab.withdraw()
            except Exception:
                pass
        self.t.withdraw()
        print("minimised to the taskbar", flush=True)

    def restore(self):
        """Bring a minimised lens back as it was, from the taskbar button.

        The presenter is shown again where it was and told to capture and
        present again. Had the monitors changed meanwhile, it is replaced
        instead, as it would have been had the lens been in view.
        """
        if self.closing or not self.minimized:
            return
        self.minimized = False
        self.t.deiconify()
        self.t.update()
        # the styles the chrome was given at birth, in case showing it again
        # cost any of them, and never in the picture
        ex = u.GetWindowLongPtrW(self.chrome, GWL_EXSTYLE)
        u.SetWindowLongPtrW(self.chrome, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(self.chrome, WDA_EXCLUDEFROMCAPTURE)
        if self.divider is not None:
            try:
                self.divider.deiconify()
            except Exception:
                pass
        if self.tab is not None:
            try:
                self.tab.deiconify()
            except Exception:
                pass
        self._fps_hist.clear()
        self._shown = None
        self.last_arrival = self.healthy_since = time.perf_counter()
        now = monitor_layout()
        if now != self.layout:
            print("the monitors changed while minimised: %s" % (now,), flush=True)
            self.layout = now
            self.layout_seen = (now, time.perf_counter())
            if self.fullscreen:
                self.set_fullscreen(True)
            elif not self.refit():
                self.restart_presenter("the monitors changed, starting again ...")
            return
        for s in self.stages:
            u.ShowWindow(s["hwnd"], SW_SHOWNA)
        self.tell_presenter("resume")
        self.bring_back()
        self.place()
        self.aim()
        print("back from the taskbar", flush=True)

    # ---- live A/B split
    # The lens is see-through, so the raw source is already on screen under the
    # presenter. Clipping the presenter's window to the left of a divider
    # reveals it on the right, live and pixel aligned, at no cost.
    # ---- attached to a window
    # The lens can be attached to another window, or to a region inside it.
    # It then follows that window: moves with it, restarts its picture when the
    # window's size has settled, minimises and restores with it, and closes when
    # it closes. The chrome shrinks to a two pixel line around the region, all
    # of it click-through so the target's own edges and controls stay usable,
    # and a tab on the top edge that opens the menu and slides along the edge
    # when it is in the way. And the lens is not on top of everything: it sits
    # one step above its target in the stacking order, so a window put over the
    # target covers the lens too, and bringing the target forward brings the
    # lens with it.
    def pick_target(self, region):
        """Start a pick: the next click names the window, then for a region a
        drag over it draws the rectangle. Escape cancels either."""
        if self.picking is not None or self.attach is not None or self.fullscreen or self.closing:
            return
        self.popup.close()
        hint = tk.Toplevel(self.root)
        hint.overrideredirect(True)
        hint.attributes("-topmost", True)
        hint.configure(bg=ACCENT)
        lbl = tk.Label(hint, text=("Click the window to attach the lens to.  Escape cancels."
                                   if not region else
                                   "Click the window, then drag the region inside it.  Escape cancels."),
                       bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=8)
        lbl.pack(padx=1, pady=1)
        hint.update_idletasks()
        x, y = self.inner()
        mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
        hint.geometry("+%d+%d" % (mx + (mw - hint.winfo_reqwidth()) // 2, my + 24))
        hint.update()
        hh = u.GetParent(hint.winfo_id()) or hint.winfo_id()
        u.SetWindowLongPtrW(hh, GWL_EXSTYLE, u.GetWindowLongPtrW(hh, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(hh, WDA_EXCLUDEFROMCAPTURE)
        self.picking = {"region": region, "hint": hint, "label": lbl, "down": bool(u.GetAsyncKeyState(0x01) & 0x8000),
                        "target": None, "overlay": None, "canvas": None, "start": None, "box": None}
        self.root.after(30, self._pick_tick)

    def _pick_end(self):
        p, self.picking = self.picking, None
        if p is None:
            return
        for k in ("overlay", "hint"):
            try:
                if p[k] is not None:
                    p[k].destroy()
            except Exception:
                pass

    def _pick_tick(self):
        p = self.picking
        if p is None or self.closing:
            return
        if u.GetAsyncKeyState(0x1B) & 0x8000:
            self._pick_end()
            return
        down = bool(u.GetAsyncKeyState(0x01) & 0x8000)
        if p["target"] is None and down and not p["down"]:
            pt = w.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            h = u.WindowFromPoint(pt)
            h = u.GetAncestor(h, GA_ROOT) or h
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, cls, 64)
            own = set(_own_windows()) | {s["hwnd"] for s in self.stages} | {self.chrome}
            if not h or h in own or cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                p["label"].config(text="That is the desktop, the taskbar or the lens itself. Click a window.  Escape cancels.")
            else:
                p["target"] = h
        p["down"] = down
        if p["target"] is not None and not down:
            # the click has been released, so the target keeps it; now the
            # region, or the attachment itself
            if p["region"]:
                if p["overlay"] is None:
                    self._region_start()
            else:
                h = p["target"]
                self._pick_end()
                self.attach_to(h, None)
                return
        self.root.after(30, self._pick_tick)

    def _region_start(self):
        """A translucent sheet over the target's client area to drag the region on."""
        p = self.picking
        rect = self.target_client(p["target"])
        if rect is None:
            self._pick_end()
            return
        cx, cy, cw, ch = rect
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.35)
        ov.configure(bg=FIELD)
        ov.geometry("%dx%d+%d+%d" % (cw, ch, cx, cy))
        cv = tk.Canvas(ov, bg=FIELD, highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        p["overlay"], p["canvas"] = ov, cv
        p["label"].config(text="Drag the region the lens should cover.  Escape cancels.")

        def down(e):
            p["start"] = (e.x, e.y)
            p["box"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT, width=2)

        def move(e):
            if p["start"] is not None:
                cv.coords(p["box"], p["start"][0], p["start"][1], e.x, e.y)

        def up(e):
            if p["start"] is None:
                return
            x0, y0 = p["start"]
            x1, y1 = e.x, e.y
            left, top = min(x0, x1), min(y0, y1)
            wd, ht = abs(x1 - x0), abs(y1 - y0)
            h = p["target"]
            if wd < MIN_W or ht < MIN_H:
                p["start"], p["box"] = None, None
                cv.delete("all")
                p["label"].config(text="Too small: the region needs at least %d by %d. Drag again.  Escape cancels."
                                  % (MIN_W, MIN_H))
                return
            frac = (left / float(cw), top / float(ch), wd / float(cw), ht / float(ch))
            self._pick_end()
            self.attach_to(h, frac)

        cv.bind("<ButtonPress-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)
        ov.update()

    @staticmethod
    def target_client(h):
        """The target's client area in screen pixels, or None if it has none."""
        r = w.RECT()
        if not u.IsWindow(h) or not u.GetClientRect(h, ctypes.byref(r)) or r.right <= 0 or r.bottom <= 0:
            return None
        pt = w.POINT(0, 0)
        u.ClientToScreen(h, ctypes.byref(pt))
        return pt.x, pt.y, r.right, r.bottom

    def target_rect(self):
        """Where the picture goes now: the target's client area, or the region's
        share of it, clipped to the monitor it is mostly on, since the
        presenter captures one monitor. None while it is too small to show."""
        a = self.attach
        c = self.target_client(a["hwnd"])
        if c is None:
            return None
        cx, cy, cw, ch = c
        if a["frac"] is not None:
            fx, fy, fw, fh = a["frac"]
            x, y, wd, ht = cx + int(round(fx * cw)), cy + int(round(fy * ch)), int(round(fw * cw)), int(round(fh * ch))
        else:
            x, y, wd, ht = cx, cy, cw, ch
        mx, my, mw, mh = monitor_rect(x + wd // 2, y + ht // 2)
        x0, y0 = max(x, mx), max(y, my)
        x1, y1 = min(x + wd, mx + mw), min(y + ht, my + mh)
        wd, ht = x1 - x0, y1 - y0
        wd, ht = wd - wd % 2, ht - ht % 2
        if wd < MIN_W or ht < MIN_H:
            return None
        return x0, y0, wd, ht

    def attach_to(self, h, frac):
        if self.attach is not None or self.closing or self.fullscreen:
            return
        if self.folded:
            self.unfold()
        x, y = self.inner()
        self.attach = {"hwnd": h, "frac": frac, "rect": (x, y, self.cw, self.ch),
                       "saved": (self.cw, self.ch, x, y), "size_seen": None, "since": 0.0,
                       "by_target": False}
        rect = self.target_rect()
        if rect is None:
            self.attach = None
            print("attach: the window is too small to attach to", flush=True)
            return
        title = ctypes.create_unicode_buffer(128)
        u.GetWindowTextW(h, title, 128)
        print("attached to %r%s at %dx%d" % (title.value, " (a region)" if frac else "", rect[2], rect[3]), flush=True)
        self.popup.close()
        # the chrome becomes the line and the tab, click-through and no longer
        # above everything
        self.t.attributes("-topmost", False)
        self._chrome_passthrough(True)
        self.make_tab()
        u.SetWindowPos(self.chrome, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.attach["rect"] = rect
        self.resize_to(*rect)               # lays the chrome out attached, restarts the picture
        self.stack_above_target()
        self.root.after(50, self.follow_target)

    def detach(self):
        a, self.attach = self.attach, None
        if a is None:
            return
        cw, ch, x, y = a["saved"]
        print("detached", flush=True)
        if self.tab is not None:
            try:
                self.tab.destroy()
            except Exception:
                pass
            self.tab = None
        self._chrome_passthrough(False)
        self.t.attributes("-topmost", True)
        if self.closing:
            return
        if self.minimized:
            self.restore()
        self.resize_to(x, y, cw, ch)
        self.bring_back()
        self.save_state()

    def toggle_fold(self):
        if self.folded:
            self.unfold()
        else:
            self.fold()

    def fold(self):
        """Fold the title bar and frame away, leaving the tab on the picture's
        top edge, which drags the lens and opens the menu, where Unfold is. The
        picture stays exactly where it is, so nothing restarts."""
        if self.folded or self.attach is not None or self.closing or self.rs is not None:
            return
        self.popup.close()
        x, y = self.inner()
        self.folded = True
        self._chrome_passthrough(True)
        self.make_tab()
        self.layout_chrome(x, y)
        self.raise_chrome()
        print("title bar hidden", flush=True)

    def unfold(self):
        if not self.folded:
            return
        x, y = self.inner()
        self.folded = False
        if self.tab is not None:
            try:
                self.tab.destroy()
            except Exception:
                pass
            self.tab = None
        self._chrome_passthrough(False)
        self.layout_chrome(x, y)
        print("title bar shown", flush=True)

    def _chrome_passthrough(self, on):
        ex = u.GetWindowLongPtrW(self.chrome, GWL_EXSTYLE)
        ex = (ex | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
        u.SetWindowLongPtrW(self.chrome, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        u.SetWindowPos(self.chrome, 0, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

    def follow_target(self):
        """Every 50 ms while attached: gone, minimised, moved, resized, or covered."""
        a = self.attach
        if a is None or self.closing:
            return
        h = a["hwnd"]
        if not u.IsWindow(h):
            print("the attached window closed; closing the lens", flush=True)
            self.attach = None
            self.quit()
            return
        if u.IsIconic(h):
            if not self.minimized and not self.rebuilding:
                a["by_target"] = True
                self.minimize()
        elif self.minimized and a["by_target"] and not self.rebuilding:
            a["by_target"] = False
            self.restore()
        if not self.minimized and not self.rebuilding:
            rect = self.target_rect()
            if rect is not None:
                x, y, wd, ht = rect
                now = time.perf_counter()
                if (wd, ht) != (self.cw, self.ch):
                    # a new size restarts the picture, once it has held still
                    if a["size_seen"] != (wd, ht):
                        a["size_seen"], a["since"] = (wd, ht), now
                    elif now - a["since"] >= ATTACH_SETTLE:
                        a["size_seen"] = None
                        a["rect"] = rect
                        self.resize_to(x, y, wd, ht)
                elif (x, y) != a["rect"][:2]:
                    a["rect"] = rect
                    self.layout_chrome(x, y, settle=False)
                    self.place()
                    self.aim()
                    self.follow_monitor()
            if self.stages and not self.rebuilding:
                stage = self.visible()
                if (u.GetWindow(h, GW_HWNDPREV) != stage
                        or u.GetWindow(stage, GW_HWNDPREV) != self.chrome):
                    self.stack_above_target()
        self.root.after(50, self.follow_target)

    def stack_above_target(self):
        """Put the picture directly above the target, the line above the
        picture and the tab above the line, none of them topmost."""
        a = self.attach
        if a is None or not self.stages:
            return

        def above(hwnd, ref):
            p = u.GetWindow(ref, GW_HWNDPREV)
            # inserting after a topmost window would make this one topmost;
            # a target with nothing but topmost windows above it is the top
            # of the ordinary band, which is HWND_TOP
            if p and u.GetWindowLongPtrW(p, GWL_EXSTYLE) & WS_EX_TOPMOST:
                p = 0
            u.SetWindowPos(hwnd, p if p else HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        try:
            stage = self.visible()
            above(stage, a["hwnd"])
            above(self.chrome, stage)
            if self.tab is not None:
                th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
                above(th, self.chrome)
        except Exception:
            pass

    def make_tab(self):
        tab = tk.Toplevel(self.root)
        self.tab = tab
        tab.overrideredirect(True)
        tab.configure(bg=ACCENT)
        lbl = tk.Label(tab, text="☰", bg=ACCENT, fg=FIELD, font=("Segoe UI", 8))
        lbl.place(x=0, y=0, width=TAB_W, height=TAB_H)
        for wdg in (tab, lbl):
            wdg.bind("<ButtonPress-1>", self._tab_down)
            wdg.bind("<B1-Motion>", self._tab_move)
            wdg.bind("<ButtonRelease-1>", self._tab_up)
            # the right button slides the tab along the edge, whatever the left
            # one does, so a hidden title bar's tab can be moved out of the way
            wdg.bind("<ButtonPress-3>", self._tab_slide_down)
            wdg.bind("<B3-Motion>", self._tab_slide_move)
            wdg.bind("<ButtonRelease-3>", self._tab_slide_up)
        x, y = self.inner()
        tab.geometry("%dx%d+%d+%d" % (TAB_W, TAB_H, x + self.tab_x, y))
        tab.update()
        th = u.GetParent(tab.winfo_id()) or tab.winfo_id()
        u.SetWindowLongPtrW(th, GWL_EXSTYLE, u.GetWindowLongPtrW(th, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(th, WDA_EXCLUDEFROMCAPTURE)

    def place_tab(self, x, y, cw):
        if self.tab is None:
            return
        self.tab_x = max(0, min(self.tab_x, cw - TAB_W))
        try:
            th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
            u.SetWindowPos(th, 0, x + self.tab_x, y, TAB_W, TAB_H, SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass

    def _tab_slide_down(self, e):
        self.tab_slide = (e.x_root, self.tab_x)

    def _tab_slide_move(self, e):
        if getattr(self, "tab_slide", None) is None:
            return
        x0, tx0 = self.tab_slide
        self.tab_x = tx0 + (e.x_root - x0)
        x, y = self.inner()
        self.place_tab(x, y, self.cw)

    def _tab_slide_up(self, e):
        self.tab_slide = None

    def _tab_down(self, e):
        self.tab_drag = (e.x_root, self.tab_x)
        if self.attach is None and not self.fullscreen:
            self.down(e)                 # folded and free: the tab drags the whole lens

    def _tab_move(self, e):
        if self.tab_drag is None:
            return
        if self.attach is None:
            if not self.fullscreen:
                self.move(e)
                x, y = self.inner()
                self.place_tab(x, y, self.cw)
            return
        x0, tx0 = self.tab_drag
        self.tab_x = tx0 + (e.x_root - x0)
        x, y = self.inner()
        self.place_tab(x, y, self.cw)

    def _tab_up(self, e):
        if self.tab_drag is None:
            return
        x0, _ = self.tab_drag
        self.tab_drag = None
        moved = abs(e.x_root - x0) >= 3
        if self.attach is None and self.drag:
            self.up(e)                   # settles the picture where the drag ended
            x, y = self.inner()
            self.place_tab(x, y, self.cw)
        if not moved:
            self.menu(e)

    def menu_anchor(self):
        """Where the menu opens from: (x, top, bottom) of the bar, the tab, or
        the control that asked for it."""
        wdg = self.anchor_widget
        if wdg is not None:
            try:
                return wdg.winfo_rootx() - 6, wdg.winfo_rooty(), wdg.winfo_rooty() + wdg.winfo_height()
            except Exception:
                pass
        if (self.attach is not None or self.folded) and self.tab is not None:
            try:
                tx, ty = self.tab.winfo_rootx(), self.tab.winfo_rooty()
                return tx - 6, ty, ty + TAB_H
            except Exception:
                pass
        return self.t.winfo_x(), self.t.winfo_y(), self.t.winfo_y() + BAR

    def menu_widgets(self):
        """The controls whose clicks the menu leaves alone: they toggle it themselves."""
        return [self.menu_btn, self.prof_btn] + ([self.tab] if self.tab is not None else [])

    # ---- updates
    def check_updates(self, quiet):
        """Ask GitHub for the newest release on a thread, and say what it found
        on the Tk thread: quiet says nothing unless there is something newer."""
        def work():
            try:
                found = _latest_release()
            except Exception as exc:
                found = exc
            try:
                self.root.after(0, lambda: self._updates_reply(found, quiet))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _updates_reply(self, found, quiet):
        if self.closing:
            return
        if isinstance(found, Exception) or found is None:
            if not quiet:
                messagebox.showinfo("Neural Lens", "Could not read the releases page.\n\n%s"
                                    % (found if found is not None else "no release listed"))
            return
        version, url = found[0], found[1]
        asset = tuple(found[2:4]) if len(found) >= 4 else (None, None)
        try:
            with open(os.path.join(DATA_DIR, "update-check.txt"), "w") as f:
                f.write("%d %s\n" % (int(time.time()), version))
        except OSError:
            pass
        if _version_tuple(version) > _version_tuple(__version__):
            self._offer_update(version, url, asset)
        elif not quiet:
            messagebox.showinfo("Neural Lens", "This is the latest version, %s." % __version__)

    def _offer_update(self, version, url, asset):
        """Say a newer version exists and ask what to do. Nothing happens on its
        own, whichever switches are on."""
        asset_url, asset_size = asset
        text = "Neural Lens %s is available. This is %s.\n\n" % (version, __version__)
        if self.auto_update_on and asset_url:
            text += ("It can be downloaded and installed over this one now. The lens closes while "
                     "the installer runs, and comes back on the new version.")
            choices = ["Install it now", "Open the release page", "Not now"]
        else:
            text += "The release page has the installer, which runs over this install."
            choices = ["Open the release page", "Not now"]
        pick = self._ask("Neural Lens update", text, choices)
        if pick == "Open the release page":
            import webbrowser
            webbrowser.open(url)
        elif pick == "Install it now":
            self._install_update(version, asset_url, asset_size)

    def _install_update(self, version, asset_url, asset_size):
        """Download the release's installer to the temp folder, check its size
        against what the release lists, run it silently over this install, and
        quit so it can replace the files. The lens is started again after."""
        import tempfile
        import urllib.request
        dest = os.path.join(tempfile.gettempdir(), "NeuralLens-Setup-%s.exe" % version)
        box = tk.Toplevel(self.root)
        box.title("Neural Lens update")
        box.attributes("-topmost", True)
        box.configure(bg=BG)
        box.resizable(False, False)
        note = tk.Label(box, text="Downloading Neural Lens %s ..." % version, bg=BG, fg=FG,
                        font=("Segoe UI", 10), width=48, anchor="w")
        note.grid(row=0, column=0, padx=14, pady=14)
        self._place_over_lens(box)
        state = {"done": 0, "total": int(asset_size or 0), "error": None, "finished": False}

        def work():
            try:
                req = urllib.request.Request(asset_url, headers={"User-Agent": "neural-lens/" + __version__})
                with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
                    if not state["total"]:
                        state["total"] = int(r.headers.get("Content-Length") or 0)
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        state["done"] += len(chunk)
                got = os.path.getsize(dest)
                if state["total"] and got != state["total"]:
                    raise IOError("the download is %d bytes where the release lists %d" % (got, state["total"]))
            except Exception as exc:
                state["error"] = exc
            state["finished"] = True

        threading.Thread(target=work, daemon=True).start()

        def tick():
            if self.closing:
                return
            if not state["finished"]:
                if state["total"]:
                    note.config(text="Downloading Neural Lens %s ... %d%%"
                                % (version, min(100, 100 * state["done"] // state["total"])))
                self.root.after(200, tick)
                return
            box.destroy()
            if state["error"] is not None:
                messagebox.showinfo("Neural Lens", "The download did not finish, so nothing was changed.\n\n%s"
                                    % state["error"])
                return
            # the installer replaces the files once the lens is gone, and starts
            # the new lens when it is done; its own start entry skips a silent run
            exe = sys.executable if getattr(sys, "frozen", False) else None
            again = (' && start "" "%s"' % exe) if exe else ""
            subprocess.Popen('cmd /c ""%s" /SILENT /NORESTART /CLOSEAPPLICATIONS%s"' % (dest, again),
                             creationflags=CREATE_NO_WINDOW)
            self.quit()

        tick()

    def check_updates_at_start(self):
        """Once a day at most, when the ini asks for it."""
        if not self.check_updates_on:
            return
        try:
            with open(os.path.join(DATA_DIR, "update-check.txt")) as f:
                last = int(f.read().split()[0])
            if time.time() - last < 86400:
                return
        except Exception:
            pass
        self.check_updates(quiet=True)

    # ---- global hotkeys
    def poll_hotkeys(self):
        if self.closing:
            return
        try:
            while not self.hotkeys.fired.empty():
                self.hotkey_action(self.hotkeys.fired.get_nowait())
        except Exception:
            pass
        self.root.after(50, self.poll_hotkeys)

    def hotkey_action(self, action):
        if self.closing or self.rebuilding:
            return
        if action == "screenshot":
            self.take_screenshot()
        elif action == "add_pass":
            self.add_pass()
        elif action == "drop_pass":
            self.drop_pass()
        elif action == "split":
            self.toggle_split()
        elif action == "minimize":
            if self.minimized:
                self.restore()
            else:
                self.minimize()
        elif action == "fullscreen":
            if self.attach is None:
                self.toggle_fullscreen()
        elif action == "profile":
            names = sorted(self.profiles["profiles"], key=str.lower)
            if names:
                i = names.index(self.profile) + 1 if self.profile in names else 0
                self.apply_profile(names[i % len(names)])
        elif action == "hide_bar":
            if self.attach is None:
                self.toggle_fold()
        elif action == "ready":
            self.ready = not self.ready
            _save_ini("ready", "1" if self.ready else None)
            self.tell_presenter("ready %d" % (1 if self.ready else 0))
            self.update_info()
        elif action == "detach":
            self.detach()

    def set_hotkeys(self, mapping):
        """From Settings: record each combination in the ini and register them."""
        for action, text in mapping.items():
            text = (text or "").strip()
            if text != HOTKEYS.get(action, ""):
                HOTKEYS[action] = text
                _save_ini("hotkey_" + action, text or None)
        self.hotkeys.set(HOTKEYS)

    # ---- profiles
    # A profile is everything that makes the picture, under a name: the windowed
    # place and size, fullscreen, the pass count, the Cost Scaler rule, ready,
    # what the title bar shows, and the add-on's whole section of ReShade.ini,
    # which is every setting the Home menu holds. Applying one writes all of
    # that and restarts the picture, since the add-on reads its settings only
    # when its process starts. The selector on the bar switches; Settings
    # renames and deletes.
    def capture_profile(self):
        if self.attach is not None:
            cw, ch, x, y = self.attach["saved"]
        elif self.fullscreen:
            cw, ch, x, y = 1400, 1000, 100, 100
            try:
                v = [int(n) for n in open(STATE).read().split()]
                cw, ch, x, y = v[:4]
            except Exception:
                pass
        else:
            x, y = self.inner()
            cw, ch = self.cw, self.ch
        addon = {k: v for k, v in _read_addon_section().items() if k not in ADDON_KEEP}
        return {"width": cw, "height": ch, "x": x, "y": y, "fullscreen": bool(self.fullscreen),
                "passes": self.passes, "cost_scaler": COST_SCALER, "ready": bool(self.ready),
                "readout": self.readout, "latency": bool(self.latency_on),
                "title_size": bool(self.show_size), "title_style": bool(self.show_style),
                "title_intensity": bool(self.show_intensity), "addon": addon}

    def show_bar_mirrors(self):
        """Put the Home menu's style and intensity on the bar, or take them off,
        as Settings says, and read them once."""
        for widget, on in ((self.style_btn, self.show_style), (self.intensity_lbl, self.show_intensity)):
            if on:
                widget.pack(side="left")
            else:
                widget.pack_forget()
        self.mirror_addon()

    def mirror_addon(self):
        """The bar's copy of the Home menu's style and intensity, from the add-on's
        section. Called once a second while either is shown."""
        if not (self.show_style or self.show_intensity):
            return
        try:
            a = _read_addon_section()
        except Exception:
            return
        self.addon_seen = a
        self.style_btn.config(text="▾ " + STYLE_NAMES.get(str(a.get("NRStyle", "0")).strip(), "Default"))
        try:
            self.intensity_lbl.config(text="intensity %.2f" % float(a.get("NRIntensity", "1")))
        except ValueError:
            self.intensity_lbl.config(text="intensity ?")

    def style_menu(self):
        cur = str(self.addon_seen.get("NRStyle", "0")).strip()
        items = [("%s%s" % (name, "   ✓" if code == cur else ""), lambda c=code: self.set_style(c), True)
                 for code, name in STYLE_NAMES.items()]
        self.anchor_widget = self.style_btn
        try:
            self.popup.toggle(items)
        finally:
            self.anchor_widget = None

    def set_style(self, code):
        """Write the style into the add-on's section and restart the picture, which
        is when the add-on reads it."""
        if self.closing or self.rebuilding or self.rs is not None:
            return
        vals = _read_addon_section()
        if str(vals.get("NRStyle", "0")).strip() == str(code):
            return
        vals["NRStyle"] = str(code)
        _replace_addon_section(vals)
        self.mirror_addon()
        self.update_profile_label()
        self.restart_presenter("NR style %s, restarting ..." % STYLE_NAMES.get(str(code), code))

    def profile_menu(self):
        names = sorted(self.profiles["profiles"], key=str.lower)
        items = []
        for n in names:
            items.append(("%s%s" % (n, "   ✓" if n == self.profile else ""),
                          lambda n=n: self.apply_profile(n), n != self.profile or True))
        if names:
            items.append(None)
        items.append(("Save the current settings as a new profile...", self.profile_save_as, True))
        if self.profile in self.profiles["profiles"]:
            items.append(("Update '%s' with the current settings" % self.profile,
                          lambda: self.profile_store(self.profile), True))
        items.append(("Manage profiles in Settings...", self.settings_dialog, True))
        self.anchor_widget = self.prof_btn
        try:
            self.popup.toggle(items)
        finally:
            self.anchor_widget = None

    def profile_store(self, name):
        """Save what the lens is now under this name, and make it the one in use."""
        name = (name or "").strip()
        if not name:
            return
        self.profiles["profiles"][name] = self.capture_profile()
        self.profiles["current"] = self.profile = name
        _save_profiles(self.profiles)
        print("profile %r saved" % name, flush=True)
        self.update_profile_label()

    def profile_save_as(self):
        """Ask for a name, then store the current settings under it."""
        d = tk.Toplevel(self.root)
        d.title("New profile")
        d.attributes("-topmost", True)
        d.configure(bg=BG)
        tk.Label(d, text="A name for these settings, such as Video, Text or Photo:", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 4))
        var = tk.StringVar(master=d, value="")
        n = 1
        while "Profile %d" % n in self.profiles["profiles"]:
            n += 1
        var.set("Profile %d" % n)
        ent = tk.Entry(d, textvariable=var, width=32, bg=FIELD, fg=FG, insertbackground=FG, relief="flat")
        ent.grid(row=1, column=0, columnspan=2, sticky="we", padx=12)
        ent.selection_range(0, "end")

        def save(*_):
            name = var.get().strip()
            d.destroy()
            if name:
                self.profile_store(name)

        tk.Button(d, text="Save", command=save, relief="flat", bg=ACCENT, fg=FIELD).grid(
            row=2, column=0, sticky="e", padx=(12, 4), pady=12)
        tk.Button(d, text="Cancel", command=d.destroy, relief="flat", bg=HOVER, fg=FG).grid(
            row=2, column=1, sticky="w", padx=(4, 12), pady=12)
        ent.bind("<Return>", save)
        d.update_idletasks()
        x, y = self.inner()
        d.geometry("+%d+%d" % (x + 40, y + 40))
        ent.focus_force()

    def profile_delete(self, name):
        if name in self.profiles["profiles"]:
            del self.profiles["profiles"][name]
            if self.profile == name:
                self.profile = self.profiles["current"] = None
            _save_profiles(self.profiles)
            self.update_profile_label()

    def profile_rename(self, old, new):
        new = (new or "").strip()
        if old not in self.profiles["profiles"] or not new or new == old:
            return
        self.profiles["profiles"][new] = self.profiles["profiles"].pop(old)
        if self.profile == old:
            self.profile = self.profiles["current"] = new
        _save_profiles(self.profiles)
        self.update_profile_label()

    def apply_profile(self, name):
        """Make the lens what this profile says: the settings, the add-on's
        section, and the picture restarted at the profile's place, size and
        pass count. Attached, the target keeps the place and size."""
        p = self.profiles["profiles"].get(name)
        if p is None or self.closing or self.rebuilding or self.rs is not None:
            return
        if self.minimized:
            self.restore()
        self.popup.close()
        self.profiles["current"] = self.profile = name
        _save_profiles(self.profiles)
        print("profile %r applied" % name, flush=True)
        # the settings the bar and Settings hold, each written to the ini as
        # Settings would write it
        self.readout = p.get("readout", self.readout)
        _save_ini("readout", None if self.readout == "size" else self.readout)
        self.latency_on = bool(p.get("latency", self.latency_on))
        self.latency_ms = None
        _save_ini("latency", None if self.latency_on else "0")
        self.show_size = bool(p.get("title_size", self.show_size))
        _save_ini("title_size", None if self.show_size else "0")
        self.show_style = bool(p.get("title_style", self.show_style))
        _save_ini("title_style", "1" if self.show_style else None)
        self.show_intensity = bool(p.get("title_intensity", self.show_intensity))
        _save_ini("title_intensity", "1" if self.show_intensity else None)
        self.show_bar_mirrors()
        self.ready = bool(p.get("ready", self.ready))
        _save_ini("ready", "1" if self.ready else None)
        mode = p.get("cost_scaler", COST_SCALER)
        if COST_SCALER != "manual" and mode in ("off", "fullscreen", "always") and mode != COST_SCALER:
            _set_cost_scaler(mode)
        # the Home menu, whole, for the presenter about to start
        if isinstance(p.get("addon"), dict):
            _replace_addon_section(p["addon"])
        self.passes = self.pending = max(1, min(_pass_limit(), int(p.get("passes", self.passes))))
        cw, ch = int(p.get("width", self.cw)), int(p.get("height", self.ch))
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        full = bool(p.get("fullscreen"))
        if self.attach is not None:
            self.resize_to(*self.attach["rect"])
        elif full:
            # a fullscreen lens keeps its own pass count, read from this file
            try:
                with open(FULL_STATE, "w") as f:
                    f.write("%d\n" % self.passes)
            except OSError:
                pass
            self.set_fullscreen(True)
        elif self.fullscreen:
            # the way back reads the windowed geometry and count from this file
            try:
                with open(STATE, "w") as f:
                    f.write("%d %d %d %d %d\n" % (cw, ch, x, y, self.passes))
            except OSError:
                pass
            self.set_fullscreen(False)
        else:
            x, y, cw, ch = fit_rect(x, y, cw, ch)
            self.resize_to(x, y, cw, ch)
        self.save_state()
        self.update_info()

    def toggle_split(self):
        if self.closing:
            return
        if self.split is None:
            self.split = 0.5
            d = tk.Toplevel(self.root)
            d.overrideredirect(True)
            d.attributes("-topmost", True)
            d.configure(bg=BG, cursor="sb_h_double_arrow")
            # a wider grab area than the line itself, so it is easy to catch
            tk.Frame(d, bg=ACCENT).place(x=DIVIDER // 2 - 2, y=0, width=4, relheight=1.0)
            d.bind("<ButtonPress-1>", self._split_down)
            x, y = self.inner()
            d.geometry("%dx%d+%d+%d" % (DIVIDER, self.ch, x + self.cw // 2 - DIVIDER // 2, y))
            self.divider = d
            # idle tasks only: a full update() here runs the lens's own timers
            # in the middle of building the window
            d.update_idletasks()
            h = u.GetParent(d.winfo_id()) or d.winfo_id()
            u.SetWindowLongPtrW(h, GWL_EXSTYLE,
                                u.GetWindowLongPtrW(h, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
            u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)
        else:
            self.split = None
            try:
                self.divider.destroy()
            except Exception:
                pass
            self.divider = None
        self.apply_split()
        self.place_divider()

    def apply_split(self):
        """Clip the presenter to the left of the divider, or unclip it."""
        for s in list(self.stages):
            try:
                if self.split is None:
                    u.SetWindowRgn(s["hwnd"], None, True)
                else:
                    px = max(0, min(self.cw, int(self.cw * self.split)))
                    # the system owns the region once it is set
                    u.SetWindowRgn(s["hwnd"], ctypes.windll.gdi32.CreateRectRgn(0, 0, px, self.ch),
                                   True)
            except Exception:
                pass

    def place_divider(self):
        if self.divider is None or self.split is None:
            return
        x, y = self.inner()
        px = int(self.cw * self.split)
        # not tk's geometry(): while the mouse button is held on this window
        # Tk ignores it, and the line the user is dragging never moves
        try:
            h = u.GetParent(self.divider.winfo_id()) or self.divider.winfo_id()
            u.SetWindowPos(h, 0, x + px - DIVIDER // 2, y, DIVIDER, self.ch,
                           SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            self.divider.geometry("%dx%d+%d+%d" % (DIVIDER, self.ch, x + px - DIVIDER // 2, y))
        self.raise_chrome()

    def _split_down(self, e):
        """Follow the mouse until the button is released.

        Not tk's motion events: the divider is a thin window under a click
        through neighbour, and a drag that starts on it has to keep working
        after the pointer has left it. A thread polls the button and the cursor
        instead and hands each position to the mainloop.
        """
        self.drag = None            # never a lens drag while on the divider
        if getattr(self, "_split_dragging", False):
            return
        self._split_dragging = True

        def follow():
            try:
                while not self.closing and u.GetAsyncKeyState(0x01) & 0x8000:
                    p = w.POINT()
                    u.GetCursorPos(ctypes.byref(p))
                    self.root.after(0, self.split_to, p.x)
                    time.sleep(0.01)
            finally:
                self._split_dragging = False

        threading.Thread(target=follow, daemon=True).start()

    def split_to(self, x_root):
        if self.split is None:
            return
        x, _ = self.inner()
        split = max(0.0, min(1.0, (x_root - x) / float(self.cw)))
        if split != self.split:
            self.split = split
            self.apply_split()
            self.place_divider()

    # ---- passes
    def set_passes(self, n, save=True):
        """Restart the presenter at n passes.

        The add-on reads its pass count when its process starts, so the count
        is written to ReShade.ini once the old presenter is gone and before
        the new one spawns. The Cost Scaler's scale follows the count.
        """
        n = max(1, min(_pass_limit(), n))
        self.pending = n
        if self.closing or n == self.passes:
            self.update_info()
            return
        self.passes = n
        self.restart_presenter("restarting at %d pass%s ..." % (n, "" if n == 1 else "es"), save)

    def follow_monitor(self):
        """Restart the presenter when the lens has been dragged onto another monitor.

        The presenter captures the monitor the lens was on when it started, so
        over another monitor it crops the wrong picture. It does while the drag
        lasts; once the lens is let go there, it starts again on that monitor.
        """
        if self.closing or self.fullscreen or not self.stages:
            return
        x, y = self.inner()
        _, mx, my = monitor_of(x + self.cw // 2, y + self.ch // 2)
        if (mx, my) != (self.mon_x, self.mon_y):
            print("the lens moved to the monitor at (%d,%d)" % (mx, my), flush=True)
            self.restart_presenter("moving to this monitor ...")

    def restart_presenter(self, note, save=True):
        """Replace the presenter with a new one at the lens's place, pass count and
        monitor, since all three are fixed when a presenter starts."""
        if self.recover_after is not None:
            try:
                self.root.after_cancel(self.recover_after)
            except Exception:
                pass
            self.recover_after = None
        self.healthy_since = self.last_arrival = time.perf_counter()
        self.info.config(text=note, fg=WARN)
        self.root.update_idletasks()
        # Tweak mode applied to the presenter about to be replaced, and its
        # successor is built click-through, so the flag has to come back down
        # or the lens believes it is interactive while behaving otherwise. The
        # ReShade overlay itself goes with the process that was hosting it, and
        # the keyboard goes back as it would on Done.
        if self.tweak:
            prev = self.tweak_prev
            self.root.after(0, lambda: self.hand_focus_back(prev, None))
        self.tweak = False
        self.rebuilding = True
        for s in reversed(self.stages):
            self._kill_stage(s)
        self.stages = []
        self.apply_proxy()
        if ADDON_PASSES:
            _write_addon_settings(self.passes)
        self.latency_ms = None
        self.frames, self.t_first = 0, None
        x, y = self.inner()
        try:
            self._build_presenter(x, y)
        except SystemExit:
            self.info.config(text="the presenter failed to start", fg=WARN)
        if self.stages:
            self.apply_split()
        self.rebuilding = False
        if not self.stages:
            # nothing left to show. visible() is stages[-1], so carrying on would
            # raise on the next menu action rather than here, where it is clear.
            messagebox.showerror("Neural Lens",
                                 "The presenter could not be started, so the lens has to close.\n"
                                 "The most recent logs are in:\n%s" % LOGDIR)
            self.quit()
            return
        self.raise_chrome()
        self.aim()
        self.update_info()
        if save:
            self.save_state()

    def capture_lost(self, reason):
        """Start the presenter again when its capture has ended.

        Windows ends a monitor capture when the displays change: measured, with a
        second monitor switched on while the lens ran, the presenter went on
        presenting its last frame, and switching that monitor off again did not
        bring its capture back. A new presenter captures afresh, on the monitor
        under the lens as the displays are now. A screen that is off or locked
        stops frames as well, so the wait before each new start doubles, up to a
        minute, until a presenter has run for half a minute.
        """
        if self.closing or self.minimized or self.recover_after is not None:
            return
        if time.perf_counter() - self.healthy_since > 30.0:
            self.recover_wait = 1.0
        delay, self.recover_wait = self.recover_wait, min(60.0, self.recover_wait * 2)
        print("capture lost (%s); starting the presenter again in %.0f s" % (reason, delay), flush=True)
        self.recover_after = self.root.after(int(delay * 1000), self._recover)

    def _recover(self):
        self.recover_after = None
        if self.closing or self.rebuilding or self.minimized:
            return
        if time.perf_counter() - self.last_arrival < 1.5:
            return                          # frames came back by themselves
        self.layout = monitor_layout()
        self.layout_seen = (self.layout, time.perf_counter())
        if self.refit():
            return
        self.restart_presenter("capture ended, starting again ...")

    def watch_layout(self):
        """Start the presenter again once the monitor layout has changed and settled.

        A display being added, removed or rearranged renumbers the monitors and
        ends the presenter's capture, so there is no point waiting for the loss to
        be reported. The layout is read on the 200 ms timer and acted on once it
        has held still for a second, since one change arrives as several.
        Fullscreen covers its monitor again as it is now. A minimised lens
        waits: restore compares the layout and starts again if it must.
        """
        now = monitor_layout()
        if now != self.layout_seen[0]:
            self.layout_seen = (now, time.perf_counter())
            return
        if (now == self.layout or self.closing or self.rebuilding or self.minimized
                or time.perf_counter() - self.layout_seen[1] < 1.0):
            return
        print("the monitors changed: %s" % (now,), flush=True)
        self.layout = now
        if self.fullscreen:
            self.set_fullscreen(True)
            return
        if self.refit():
            return
        self.restart_presenter("the monitors changed, starting again ...")

    def refit(self):
        """Keep the windowed lens on one monitor as the displays are now.

        A lens that only needs moving is moved. One that has to shrink gets a
        new picture at the smaller size, the same way a resize does, and this
        returns True. Fullscreen already covers exactly its monitor.
        """
        if self.fullscreen or self.closing or self.attach is not None:
            return False
        x, y = self.inner()
        nx, ny, ncw, nch = fit_rect(x, y, self.cw, self.ch)
        if (ncw, nch) != (self.cw, self.ch):
            print("the lens no longer fits its monitor; resizing to %d x %d" % (ncw, nch), flush=True)
            self.resize_to(nx, ny, ncw, nch)
            return True
        if (nx, ny) != (x, y):
            self.t.geometry("+%d+%d" % (nx - EDGE, ny - BAR))
            self.t.update()                 # so inner() reads the new place
            self.place()
            self.aim()
            self.save_state()
        return False

    def apply_proxy(self):
        """Set the Cost Scaler for this lens: on for fullscreen at the scale the
        monitor and the pass count call for, off when windowed, or as the ini
        says. The proxy reads its ini when it starts and again within a second
        of a change, so this is right both before the presenter spawns and live."""
        if not _proxy_installed() or COST_SCALER == "manual":
            return
        want = COST_SCALER == "always" or (COST_SCALER == "fullscreen" and self.fullscreen)
        scale = _proxy_scale(self.cw, self.ch, self.passes) if want else None
        if _write_proxy(scale is not None, scale) and scale != self.proxy_scale:
            self.proxy_scale = scale
            print("cost scaler %s" % ("on at %.2f" % scale if scale else "off"), flush=True)

    def add_pass(self, save=True):
        self.set_passes(self.passes + 1, save)

    def drop_pass(self, save=True):
        self.set_passes(self.passes - 1, save)

    # ---- geometry
    def inner(self):
        if self.fullscreen:
            # fullscreen cannot be dragged, and its chrome is the bar alone, with
            # no border to count from
            return self.fs_origin
        if self.attach is not None:
            return self.attach["rect"][:2]
        if self.folded:
            return self.t.winfo_x() + LINE, self.t.winfo_y() + LINE
        return self.t.winfo_x() + EDGE, self.t.winfo_y() + BAR

    def layout_chrome(self, x, y, cw=None, ch=None, settle=True):
        """Lay the chrome out around a picture of this size at this place.

        Windowed, the bar sits above the picture inside the frame, which draws
        the border and carries the grips. Fullscreen the chrome is the bar
        alone, since a layered window larger than the screen comes up blank.
        The size is the lens's own unless one is given, which is how a drag
        previews its outcome; settle waits for the window to be where it was
        put, so inner() reads the new place, which a preview has no need of.
        """
        cw = self.cw if cw is None else cw
        ch = self.ch if ch is None else ch
        t = self.t
        if self.fullscreen and self.folded:
            # folded fullscreen: the chrome is as good as gone, two pixels in the
            # corner, and the tab alone stays on the picture's top edge; a layered
            # window the size of the screen would come up blank
            t.geometry("2x2+%d+%d" % (x, y - BAR))
            self.bar.place_forget()
            self.hole.place_forget()
            for g in self.grips.values():
                g.place_forget()
            self.place_tab(x, y, cw)
        elif self.fullscreen:
            t.geometry("%dx%d+%d+%d" % (cw, BAR, x, y - BAR))
            self.bar.place(x=0, y=0, width=cw, height=BAR)
            self.hole.place_forget()
            for g in self.grips.values():
                g.place_forget()
        elif self.attach is not None or self.folded:
            # attached or folded, the chrome is the line around the picture and
            # the tab on its top edge; no bar and no grips. Attached, the target
            # decides the size; folded, the tab drags the lens and opens the menu
            t.geometry("%dx%d+%d+%d" % (cw + 2 * LINE, ch + 2 * LINE, x - LINE, y - LINE))
            self.bar.place_forget()
            self.hole.place(x=LINE, y=LINE, width=cw, height=ch)
            for g in self.grips.values():
                g.place_forget()
            self.place_tab(x, y, cw)
        else:
            t.geometry("%dx%d+%d+%d" % (cw + 2 * EDGE, ch + BAR + EDGE, x - EDGE, y - BAR))
            self.bar.place(x=EDGE, y=0, width=cw, height=BAR)
            self.hole.place(x=EDGE, y=BAR, width=cw, height=ch)
            grab = EDGE - LINE
            self.grips["w"].place(x=LINE, y=0, width=grab, height=BAR + ch + grab)
            self.grips["e"].place(x=EDGE + cw, y=0, width=grab, height=BAR + ch + grab)
            self.grips["s"].place(x=LINE, y=BAR + ch, width=cw + 2 * grab, height=grab)
        if settle:
            t.update()

    def aim(self):
        """Tell the presenter where the lens is on its monitor."""
        x, y = self.inner()
        self.tell_presenter("crop %d %d" % (x - self.mon_x, y - self.mon_y))

    def place(self):
        x, y = self.inner()
        flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        for s in self.stages:
            u.SetWindowPos(s["hwnd"], 0, x, y, 0, 0, flags)
        self.place_divider()

    def update_info(self):
        n = self.passes
        p = max(1, min(_pass_limit(), self.pending))
        self.pending = p
        chosen = p != n
        if not self.nr_on:
            # every pass is a neural pass, so with Neural Rendering off each one
            # is a copy of the last; the controls wait until it is back
            self.pass_lbl.config(text="NR off", fg=DIM)
            for b in (self.set_btn, self.plus, self.minus):
                b.config(fg=DIM)
            return
        self.pass_lbl.config(text="%d pass%s" % (p, "" if p == 1 else "es"),
                             fg=WARN if chosen else ACCENT)
        self.set_btn.config(fg=ACCENT if chosen else DIM)
        self.plus.config(fg=DIM if p >= _pass_limit() else FG)
        self.minus.config(fg=DIM if p <= 1 else FG)
        self.update_profile_label()

    def update_profile_label(self):
        """The profile's name on the bar, amber with a star once the lens no
        longer matches it in what the bar and Settings hold."""
        name = self.profile
        if not name or name not in self.profiles["profiles"]:
            self.prof_btn.config(text="▾ Profile", fg=DIM)
            return
        p = self.profiles["profiles"][name]
        same = (p.get("passes") == self.passes and p.get("cost_scaler") == COST_SCALER
                and bool(p.get("ready")) == self.ready and p.get("readout") == self.readout
                and bool(p.get("latency")) == self.latency_on and bool(p.get("fullscreen")) == self.fullscreen
                and bool(p.get("title_size", True)) == bool(self.show_size)
                and bool(p.get("title_style", False)) == bool(self.show_style)
                and bool(p.get("title_intensity", False)) == bool(self.show_intensity))
        self.prof_btn.config(text="▾ %s%s" % (name, "" if same else "*"), fg=ACCENT if same else WARN)

    def bump_passes(self, step):
        """Choose a pass count on the bar without restarting anything yet."""
        if not self.nr_on:
            return
        self.pending = max(1, min(_pass_limit(), self.pending + step))
        self.update_info()

    def apply_passes(self):
        if self.nr_on and self.pending != self.passes:
            self.set_passes(self.pending)

    def stats(self):
        if self.closing:
            return
        # The new pictures the presenter actually showed over the last few
        # seconds, which is the number a person means by fps. Its counter
        # restarts with the presenter, so a step backwards starts the average over.
        now, n = time.perf_counter(), self.out_frames
        if self._shown is not None and n >= self._shown[1] and now > self._shown[0]:
            self._fps_hist.append((n - self._shown[1]) / (now - self._shown[0]))
        elif self._shown is not None and n < self._shown[1]:
            self._fps_hist.clear()
        self._shown = (now, n)
        shown = sum(self._fps_hist) / len(self._fps_hist) if self._fps_hist else None
        # not during a drag on the frame, which shows the size it is making
        if self.t_first and self.frames > 0 and not self.tweak and self.rs is None:
            # nothing under the lens has changed for a few seconds: the presenter
            # shows nothing new, the neural pass rests, and the delay of the last
            # new picture is history
            idle = shown is not None and shown < 0.5
            parts = ["%d x %d" % (self.cw, self.ch)] if self.show_size else []
            if self.readout in ("detail", "both"):
                parts.append("%.0f in  %.0f out" % (self.pres_in, self.pres_out))
            if idle and self.readout != "detail":
                parts.append("idle")
            elif not idle and self.readout in ("fps", "both") and shown is not None:
                parts.append("%.0f fps" % shown)
            if self.latency_on and self.latency_ms is not None and not idle:
                parts.append("latency ~%.0f ms" % self.latency_ms)
            self.info.config(text="   ".join(parts), fg=DIM)
        self.mirror_addon()
        self.root.after(1000, self.stats)

    def save_state(self):
        x, y = self.inner()
        if self.attach is not None:
            # the attached place and size belong to the target; the windowed
            # geometry is what comes back on detach and on the next launch
            cw, ch, x, y = self.attach["saved"]
        else:
            cw, ch = self.cw, self.ch
        try:
            if self.fullscreen:
                # the windowed geometry stays untouched for the way back
                with open(FULL_STATE, "w") as f:
                    f.write("%d\n" % self.passes)
                return
            with open(STATE, "w") as f:
                f.write("%d %d %d %d %d\n" % (cw, ch, x, y, self.passes))
        except OSError:
            pass

    # ---- drag (title bar only; a move never resizes)
    def down(self, e):
        if self.fullscreen:
            return
        self.drag = (e.x_root - self.t.winfo_x(), e.y_root - self.t.winfo_y())

    def move(self, e):
        if self.drag:
            self.t.geometry("+%d+%d" % (e.x_root - self.drag[0], e.y_root - self.drag[1]))
            self.place()
            self.aim()

    def up(self, e):
        if self.drag:
            self.drag = None
            self.place()
            self.aim()
            if self.refit():
                return
            self.save_state()
            self.follow_monitor()

    # ---- menu / tweak mode
    # The ReShade overlay lives INSIDE the presenter's swapchain, so it cannot
    # be moved to a separate window. Tweak mode makes the viewport interactive
    # (drops WS_EX_TRANSPARENT / WS_EX_NOACTIVATE), focuses it and presses Home
    # so the overlay opens in place. It ends with Done, which presses Home again,
    # or with a Home the user presses, which has closed the overlay already;
    # either way the viewport goes back to click-through and the keyboard to the
    # window that had it.
    def menu(self, e):
        off = self.nr_on
        # a bug report is much easier to act on when the reporter can read the
        # version off the app rather than having to work out which build they have
        items = [
            ("Neural Lens %s  (beta)" % __version__, None, False),
            None,
            (("Done tweaking  (back to click-through)" if self.tweak
              else "Tweak NR settings  (ReShade overlay, Home)"), self.toggle_tweak, True),
            (("Turn NR back on   (F6)" if not self.nr_on
              else "Turn NR off   (F6)"), self.toggle_nr, True),
            None,
            ("Add a pass now", self.add_pass, off and self.passes < _pass_limit()),
            ("Remove a pass now", self.drop_pass, off and self.passes > 1),
            None,
            ("Save before and after      (both images, plus a join)", self.take_screenshot, True),
            ("Save the result only       (F5, ReShade's own)", lambda: self.send_key(0x74), True),
            ("Open screenshot folder", self.open_shots, True),
            None,
            (("End the A/B split" if self.split is not None
              else "Live A/B split      (neural left, raw right)"), self.toggle_split, True),
            None,
        ] + ([
            ("Detach from the window", self.detach, True),
        ] if self.attach is not None else [
            ("Attach to a window...       (then click the window)", lambda: self.pick_target(False),
             not self.fullscreen),
            ("Attach to a region in a window...   (click it, then drag the region)",
             lambda: self.pick_target(True), not self.fullscreen),
        ]) + [
            None,
            (("Show the title bar" if self.folded else "Hide the title bar   (only the tab stays)"),
             self.toggle_fold, self.attach is None),
            ("Settings...", self.settings_dialog, True),
            None,
            ("Close", self.quit, True),
        ]
        self.popup.toggle(items)

    def set_interactive(self, hwnd, on):
        ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if on:
            ex &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        else:
            ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)

    def focus(self, hwnd):
        me = k32.GetCurrentThreadId()
        tid = u.GetWindowThreadProcessId(hwnd, None)
        u.AttachThreadInput(me, tid, True)
        u.SetForegroundWindow(hwnd)
        u.SetFocus(hwnd)
        u.AttachThreadInput(me, tid, False)

    def post_key(self, hwnd, vk):
        """Deliver one key press straight to the presenter's message queue.

        ReShade reads its hotkeys from the window's own messages, so a posted
        WM_KEYDOWN and WM_KEYUP reach it whether or not the window has focus.
        But it only notices a press when it polls, once per presented frame,
        and a key that goes down and up inside one frame is never seen. So the
        key is held for a third of a second, longer than the slowest frame,
        before it is released.
        """
        scan = u.MapVirtualKeyW(vk, 0)
        ext = 0x1000000 if vk in (0x24, 0x21, 0x22, 0x23, 0x2D, 0x2E) else 0
        lp = (scan << 16) | 1 | ext
        u.PostMessageW(hwnd, 0x100, vk, lp)
        self.root.after(KEY_HOLD, lambda: u.PostMessageW(hwnd, 0x101, vk, lp | 0xC0000000))

    def toggle_tweak(self):
        if self.tweak:
            self.end_tweak()
        else:
            self.start_tweak()

    def start_tweak(self):
        h = self.visible()
        self.tweak = True
        self.tweak_prev = u.GetForegroundWindow()
        # interactive first, so the overlay that opens can be used with the
        # mouse; the key itself does not need the focus. The overlay is drawn
        # and read on every present, so the presenter presents at full rate
        # for as long as it is open
        self.set_interactive(h, True)
        self.tell_presenter("live 1")
        self.info.config(text="TWEAK MODE: press Home when done", fg=WARN)
        self.post_key(h, 0x24)
        self.root.after(150, lambda: self.focus(h))
        self.tweak_until = float("inf")
        self.root.after(700, self.follow_overlay)
        u.GetAsyncKeyState(0x24)            # forget a press from before, see watch_home
        self.root.after(KEY_HOLD, lambda: self.watch_home(h))

    def end_tweak(self, press_home=True):
        """Leave tweak mode: from Done, which closes the overlay with Home, or
        with press_home False once the user's own Home has closed it."""
        h = self.visible()
        self.tweak = False
        prev = self.tweak_prev
        if press_home:
            # the key first, and the window made click-through only after it
            # has been released: taking the styles back drops the focus, and
            # ReShade forgets every key it is holding when that happens
            self.post_key(h, 0x24)
        self.root.after(KEY_HOLD + 200 if press_home else 200,
                        lambda: (self.set_interactive(h, False), self.hand_focus_back(prev, h),
                                 self.tell_presenter("live 0")))
        self.info.config(text="%d x %d" % (self.cw, self.ch), fg=DIM)
        # the add-on's write of a change made just before Done can still be
        # on its way, so the file is followed a few seconds longer
        self.tweak_until = time.perf_counter() + 4.0

    def watch_home(self, h, pressing=False):
        """End tweak mode when the user's Home closes the overlay.

        A Home press reaches the presenter, and so ReShade, only while the
        presenter is the foreground window, and ReShade closes the overlay on
        it. The key is read from the physical keyboard, the way F6 is, so the
        presses the lens posts itself are not counted, and tweak mode ends once
        the key is back up: dropping the focus while it is down makes ReShade
        forget it. The low bit catches a press that came and went between two
        looks.
        """
        if self.closing or not self.tweak or not self.stages or h != self.visible():
            return
        state = u.GetAsyncKeyState(0x24)
        down = bool(state & 0x8000)
        if not pressing and (down or state & 1) and u.GetForegroundWindow() == h:
            pressing = True
        if pressing and not down:
            self.end_tweak(press_home=False)
            return
        self.root.after(30, lambda: self.watch_home(h, pressing))

    def hand_focus_back(self, prev, h):
        """Give the keyboard back to the window that had it before the presenter
        took it, so the next key goes where the user expects rather than to
        ReShade. A window of the lens's own, or one that has gone, is left be."""
        if not prev or prev == h or not u.IsWindow(prev):
            return
        pid = w.DWORD()
        u.GetWindowThreadProcessId(prev, ctypes.byref(pid))
        if pid.value == os.getpid():
            return
        try:
            me = k32.GetCurrentThreadId()
            tid = u.GetWindowThreadProcessId(prev, None)
            u.AttachThreadInput(me, tid, True)
            u.SetForegroundWindow(prev)
            u.AttachThreadInput(me, tid, False)
        except Exception:
            pass

    def follow_overlay(self):
        """Keep the title bar in step with a pass count chosen in the overlay.

        The overlay's own control changes the add-on's count live, inside its
        process, and the add-on writes it to ReShade.ini within about a second.
        While the overlay is open, and for a few seconds after it closes, the
        file is read back and a changed count becomes the bar's own, with
        nothing restarted: the add-on is already running it.
        """
        if self.closing or not (self.tweak or time.perf_counter() < self.tweak_until):
            return
        if ADDON_PASSES and not self.rebuilding:
            n = _read_nr_passes()
            if n is not None and 1 <= n <= ADDON_MAX_PASSES and n != self.passes:
                print("passes set to %d in the overlay" % n, flush=True)
                self.passes = self.pending = n
                self.update_info()
                self.apply_proxy()
                self.save_state()
        self.root.after(700, self.follow_overlay)

    def send_key(self, vk):
        """Post a key to the presenter, for ReShade's own hotkeys."""
        if self.closing:
            return
        for s in list(self.stages):
            self.post_key(s["hwnd"], vk)

    # ---- Neural Rendering on or off
    # The add-on reads its F6 from the physical keyboard, through
    # GetAsyncKeyState, not from window messages. Measured with a still image
    # under the lens and the in-to-out difference as the witness: F6 posted to
    # the window did nothing in three runs, with or without focus, while one
    # real keystroke with no focus at all took it from 1.20 to 2.22. So F6
    # anywhere on the system toggles Neural Rendering, and the lens watches
    # the same key the same way to keep its own idea in step.
    def watch_f6(self):
        def loop():
            down = False
            while not self.closing:
                now = bool(u.GetAsyncKeyState(0x75) & 0x8000)
                # a paused presenter presents no frame for the add-on to read
                # the key on, so a press while minimised changes nothing there
                if now and not down and not self.minimized:
                    self.root.after(0, self._nr_toggled)
                down = now
                time.sleep(0.05)      # a human press lasts longer than this

        threading.Thread(target=loop, daemon=True).start()

    def _nr_toggled(self):
        if self.closing:
            return
        # the add-on reads the key on a present, and an idle presenter presents
        # four times a second, so it presents at full rate for a moment; and the
        # add-on's own answer, written to ReShade.ini within about a second and a
        # half, is read back to keep the two in step should it have missed the key
        self.tell_presenter("wake")
        self.nr_on = not self.nr_on
        print("Neural Rendering %s" % ("on" if self.nr_on else "off"), flush=True)
        self.update_info()
        self.root.after(2500, self._check_nr)

    def _check_nr(self):
        if self.closing or self.rebuilding:
            return
        on = _read_nr_enabled()
        if on != self.nr_on:
            self.nr_on = on
            print("Neural Rendering %s, as the add-on has it" % ("on" if on else "off"), flush=True)
            self.update_info()

    def press_key(self, vk):
        """A genuine keystroke, since that is what the add-on reads.

        Unlike a posted message it reaches the whole system, so the presenter
        takes the focus for the press and hands it back afterwards; without
        that the key also lands in whatever is under the lens, and F6 in a
        browser moves the cursor to the address bar. The key is held longer
        than the slowest frame, and the click-through styles come back only
        after it is released: dropping the focus makes ReShade forget every
        key it is holding.
        """
        if self.closing or not self.stages:
            return
        h = self.visible()
        prev = u.GetForegroundWindow()
        self.tell_presenter("wake")         # the add-on reads the key on a present
        self.set_interactive(h, True)
        self.focus(h)

        def back():
            if not self.tweak:
                self.set_interactive(h, False)
            self.hand_focus_back(prev, h)

        def up():
            u.keybd_event(vk, 0, 2, 0)
            self.root.after(150, back)

        def down():
            u.keybd_event(vk, 0, 0, 0)
            self.root.after(KEY_HOLD, up)

        self.root.after(120, down)

    def toggle_nr(self):
        """The menu's toggle. watch_f6 sees the press and flips the state."""
        if not self.closing:
            self.press_key(0x75)

    # ---- resize
    # The picture cannot change size in place: the presenter's swapchain is
    # made at its size, and the add-on crashes when a swapchain is recreated
    # under it. So a new size replaces the presenter, the way a new pass count
    # does, and the chrome is laid out again around the new one. The size
    # comes from the frame around the lens, dragged the way any window is.
    def resize_to(self, x, y, cw, ch):
        """Give the lens this size at this place: the chrome is laid out again
        and the presenter replaced, since its size is fixed when it starts."""
        if self.closing:
            return
        cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
        self.cw, self.ch = cw, ch
        self.layout_chrome(x, y)
        self.restart_presenter("resizing to %d x %d ..." % (cw, ch))

    # The frame: a drag on a side moves that side, a drag on a bottom corner
    # moves both of its sides. The chrome follows the mouse as a preview, the
    # picture stays as it is, and letting go replaces the picture at the new
    # size, kept within the monitor like any other.
    def _grip_zone(self, side, e):
        if side == "s":
            wd = e.widget.winfo_width()
            return "sw" if e.x < CORNER else "se" if e.x > wd - CORNER else "s"
        ht = e.widget.winfo_height()
        if e.y < ht - CORNER:
            return side
        return "sw" if side == "w" else "se"

    def _grip_hover(self, side, e):
        if self.rs is None:
            e.widget.config(cursor={"w": "size_we", "e": "size_we", "s": "size_ns",
                                    "sw": "size_ne_sw", "se": "size_nw_se"}[self._grip_zone(side, e)])

    def _grip_down(self, side, e):
        if self.fullscreen or self.closing or self.rebuilding or self.rs is not None:
            return
        self.popup.close()
        x, y = self.inner()
        self.rs = {"zone": self._grip_zone(side, e), "x0": e.x_root, "y0": e.y_root,
                   "start": (x, y, self.cw, self.ch), "rect": (x, y, self.cw, self.ch)}

    def _grip_rect(self, e):
        zone = self.rs["zone"]
        x, y, cw, ch = self.rs["start"]
        dx, dy = e.x_root - self.rs["x0"], e.y_root - self.rs["y0"]
        if "e" in zone:
            cw = max(MIN_W, cw + dx)
        if "w" in zone:
            nw = max(MIN_W, cw - dx)
            x, cw = x + cw - nw, nw
        if "s" in zone:
            ch = max(MIN_H, ch + dy)
        return x, y, cw - cw % 2, ch - ch % 2

    def _grip_move(self, e):
        if self.rs is None:
            return
        rect = self._grip_rect(e)
        if rect != self.rs["rect"]:
            self.rs["rect"] = rect
            self.layout_chrome(*rect, settle=False)
            self.info.config(text="%d x %d" % rect[2:], fg=WARN)

    def _grip_up(self, e):
        if self.rs is None:
            return
        x, y, cw, ch = self._grip_rect(e)          # while the drag's record is still there
        sx, sy, scw, sch = self.rs["start"]
        self.rs = None
        if (cw, ch) != (scw, sch):
            self.resize_to(*fit_rect(x, y, cw, ch))
            return
        self.layout_chrome(sx, sy)
        self.info.config(text="%d x %d" % (scw, sch), fg=DIM)

    # ---- fullscreen and back
    def toggle_fullscreen(self):
        """The maximise button: fullscreen, or back to the window the lens was."""
        if not self.closing and not self.rebuilding:
            self.set_fullscreen(not self.fullscreen)

    def set_fullscreen(self, on):
        """Fill the monitor the lens is on, or come back to the window it was.

        Either way the picture is replaced, since the presenter's size is fixed
        when it starts, and the chrome laid out again around it. The windowed
        geometry is saved on the way in and read back on the way out, and the
        fullscreen lens keeps its own pass count, as it does across a launch.
        The ini follows, so the next launch opens the same way. Already
        fullscreen, going fullscreen again covers the monitor as it is now.
        """
        if self.closing or self.rebuilding:
            return
        if self.minimized:
            self.restore()
        self.popup.close()
        if self.rs is not None:
            return
        passes = self.passes
        if on:
            if not self.fullscreen:
                self.save_state()           # the windowed geometry, for the way back
                if os.path.exists(FULL_STATE):
                    try:
                        passes = int(open(FULL_STATE).read().split()[0])
                    except Exception:
                        pass
            x, y = self.inner()
            mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
            x, y, cw, ch = mx, my + BAR, mw, mh - BAR
            note = "going fullscreen ..."
        else:
            if not self.fullscreen:
                return
            cw, ch, x, y = 1400, 1000, None, None
            try:
                v = [int(n) for n in open(STATE).read().split()]
                cw, ch, x, y = v[:4]
                if len(v) > 4:
                    passes = v[4]
            except Exception:
                cw, ch, x, y = 1400, 1000, None, None
            if x is None:
                mx, my, mw, mh = work_area(0, 0)
                x, y, cw, ch = fit_rect(mx + EDGE, my + BAR, cw, ch, (mx, my, mw, mh))
                x = mx + (mw - cw) // 2
                y = my + BAR + (mh - BAR - EDGE - ch) // 2
            x, y, cw, ch = fit_rect(x, y, cw, ch)
            note = "back to a window ..."
        cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
        self.fullscreen = on
        self.fs_origin = (x, y)
        self.cw, self.ch = cw, ch
        self.passes = self.pending = max(1, min(_pass_limit(), passes))
        _save_ini("fullscreen", "1" if on else None)
        self.max_btn.config(text=self.glyphs["restore" if on else "max"])
        self.layout_chrome(x, y)
        print("%s %dx%d at (%d,%d)" % ("fullscreen" if on else "windowed", cw, ch, x, y), flush=True)
        self.restart_presenter(note)

    # ---- screenshots
    # ReShade's own key can only give the processed image. The presenter holds
    # the exact frame it captured and reads back the picture it presented last,
    # so it saves a genuinely aligned before and after from the same moment,
    # plus a composite, which is the shot worth posting.
    def take_screenshot(self):
        if self.closing or self.shot_busy:
            return
        self.shot_busy = True
        self.info.config(text="saving screenshot ...", fg=WARN)
        threading.Thread(target=self._shot_worker, daemon=True).start()

    def _shot_worker(self):
        text, colour = "screenshot captured nothing", WARN
        try:
            time.sleep(0.1)                     # let the menu finish closing
            os.makedirs(SHOT_DIR, exist_ok=True)
            base = os.path.join(SHOT_DIR, "lens-%s-%dpass" % (time.strftime("%Y%m%d-%H%M%S"),
                                                               self.passes))
            self.shot_event.clear()
            self.shot_reply = None
            self.tell_presenter("clip %d" % (1 if self.clip_shots else 0))
            self.tell_presenter("shot " + base)
            if self.shot_event.wait(5.0) and self.shot_reply and self.shot_reply.startswith("done"):
                text, colour = "saved " + self.shot_reply[5:], ACCENT
            elif self.shot_reply:
                text = "screenshot failed: " + self.shot_reply
        except Exception as exc:
            text = "screenshot failed: %s" % exc
        finally:
            self.shot_busy = False
        try:
            self.root.after(0, lambda: self._shot_done(text, colour))
        except Exception:
            pass

    def _shot_done(self, text, colour):
        if self.closing:
            return
        self.info.config(text=text, fg=colour)
        self.root.after(4000, lambda: self.info.config(fg=DIM))

    def open_shots(self):
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            os.startfile(SHOT_DIR)
        except Exception:
            messagebox.showinfo("Screenshots", "Screenshots are saved to:\n%s" % SHOT_DIR)

    # ---- settings
    def settings_dialog(self):
        """Every setting the lens has, as a control with a plain explanation,
        on six pages rather than one column: the picture, the title bar,
        profiles, hotkeys, screenshots, and the program itself.

        Each section explains itself before its controls. Nothing here
        requires editing the ini; the dialog writes it. A value put back to its
        default is removed from the ini, so it follows the default on the next
        machine rather than pinning this one's value. The folders take effect
        at the next launch, so changing them restarts the lens.
        """
        t = tk.Toplevel(self.root)
        t.title("Neural Lens settings")
        t.attributes("-topmost", True)
        t.configure(bg=BG)
        t.resizable(False, False)

        # ttk draws the tabs, in the lens's colours; the pages are plain frames,
        # so every control is the widget it was when the dialog was one column
        style = ttk.Style(t)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Lens.TNotebook", background=BG, borderwidth=0, tabmargins=(8, 8, 8, 0))
        style.configure("Lens.TNotebook.Tab", background=TAB_BG, foreground=DIM, borderwidth=0,
                        padding=(14, 6), font=("Segoe UI", 10))
        style.map("Lens.TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)],
                  expand=[("selected", (0, 0, 0, 0))])
        nb = ttk.Notebook(t, style="Lens.TNotebook")
        nb.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 0))

        def page(name):
            p = tk.Frame(nb, bg=BG)
            p.row = 0
            p.columnconfigure(0, weight=1)
            nb.add(p, text=name)
            return p

        def heading(p, text):
            tk.Label(p, text=text, bg=BG, fg=FG, font=("Segoe UI", 10, "bold")).grid(
                row=p.row, column=0, columnspan=3, sticky="w", padx=12, pady=(14, 2))
            p.row += 1

        def explain(p, text):
            tk.Label(p, text=text, bg=BG, fg=DIM, justify="left", wraplength=560,
                     font=("Segoe UI", 9)).grid(row=p.row, column=0, columnspan=3,
                                                sticky="w", padx=12, pady=(0, 4))
            p.row += 1

        def note(p, text):
            """A short description under the switch it belongs to."""
            tk.Label(p, text=text, bg=BG, fg=DIM, justify="left", wraplength=530,
                     font=("Segoe UI", 9)).grid(row=p.row, column=0, columnspan=3,
                                                sticky="w", padx=(34, 12), pady=(0, 8))
            p.row += 1

        def switch(p, text, var):
            b = tk.Checkbutton(p, text=text, variable=var, bg=BG, fg=FG, selectcolor=FIELD,
                               activebackground=BG, activeforeground=FG, disabledforeground=DIM,
                               font=("Segoe UI", 10))
            b.grid(row=p.row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 0))
            p.row += 1
            return b

        def radio(p, text, var, value):
            tk.Radiobutton(p, text=text, variable=var, value=value, bg=BG, fg=FG,
                           selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).grid(row=p.row, column=0, columnspan=3,
                                                       sticky="w", padx=8, pady=(2, 0))
            p.row += 1

        def folder(p, var, prompt):
            tk.Entry(p, textvariable=var, width=58, bg=FIELD, fg=FG,
                     insertbackground=FG, relief="flat").grid(
                row=p.row, column=0, columnspan=2, padx=(12, 6), pady=4, sticky="we")

            def browse():
                d = filedialog.askdirectory(initialdir=var.get() or DATA_DIR, title=prompt)
                if d:
                    var.set(os.path.normpath(d))

            tk.Button(p, text="Browse", command=browse, relief="flat", bg=HOVER,
                      fg=FG).grid(row=p.row, column=2, padx=(0, 12), pady=4)
            p.row += 1

        def button(p, text, command):
            tk.Button(p, text=text, command=command, relief="flat", bg=HOVER,
                      fg=FG).grid(row=p.row, column=0, sticky="w", padx=12, pady=(2, 2))
            p.row += 1

        # ================================================================ picture
        pic = page("Picture")

        heading(pic, "Ready mode")
        explain(pic, "Over a non-moving background the lens rests, which lets the card run cooler and "
                     "draw less power. The picture stays neurally rendered while it rests, so nothing "
                     "is lost. Resting starts ten seconds after the last change and drops the lens to "
                     "four presents a second. Waking from a rest can make the first frame after a "
                     "pause arrive late, up to 150 ms on some cards. Ready mode never rests, holding "
                     "thirty presents a second, at about 18 W more over a still. Leave it off unless "
                     "the first frame after a pause looks like a stutter and you don't mind the card "
                     "running hotter and drawing more power all the time.")
        ready = tk.BooleanVar(value=self.ready)
        switch(pic, "Ready mode, thirty presents a second while nothing changes", ready)

        heading(pic, "The Cost Scaler")
        explain(pic, "DLSSNR-Cost-Scaler runs the neural model at a fraction of the picture's "
                     "resolution and puts the result back at full size, which means fewer pixels for "
                     "the model, a higher frame rate, and a slightly smaller change to the picture. "
                     "Fullscreen at 6144x2560 it took one pass from 42 frames a second to 58 frames "
                     "a second, and two passes from 26 to 54. The lens uses it only where the model's work would pass "
                     "about 8 megapixels over all the passes, which a window reaches at 2560x1440 "
                     "with three passes or 3840x2160 with two. Below that it would only add its own "
                     "cost. Applies straight away.")
        if COST_SCALER == "manual":
            explain(pic, "cost_scaler = manual in neural-lens.ini leaves the Cost Scaler's own ini "
                         "alone, so these two do nothing until that line goes.")
        cs_full = tk.BooleanVar(value=COST_SCALER in ("fullscreen", "always"))
        cs_always = tk.BooleanVar(value=COST_SCALER == "always")
        cs_full_btn = switch(pic, "Use the Cost Scaler for a fullscreen lens", cs_full)
        cs_always_btn = switch(pic, "Use the Cost Scaler for a windowed lens too", cs_always)
        if COST_SCALER == "manual":
            cs_full_btn.config(state="disabled")
            cs_always_btn.config(state="disabled")

        def follow_always(*_):
            if cs_always.get():
                cs_full.set(True)
                cs_full_btn.config(state="disabled")
            elif COST_SCALER != "manual":
                cs_full_btn.config(state="normal")

        cs_always.trace_add("write", follow_always)
        follow_always()

        # ================================================================ title bar
        bar = page("Title bar")

        heading(bar, "What to show on the title bar")
        size_on = tk.BooleanVar(value=self.show_size)
        switch(bar, "Current lens size", size_on)
        note(bar, "The picture's width and height in pixels.")
        fps_on = tk.BooleanVar(value=self.readout in ("fps", "both"))
        switch(bar, "Frame rate", fps_on)
        note(bar, "How many new pictures a second (fps) the content under the lens hands it, averaged "
                  "over the last few seconds. A 30 frame a second video gives 30 fps, and the lens "
                  "never limits it. When nothing is moving the bar says idle instead. The picture "
                  "stays the neural rendering of the last frame, so idle means nothing new arrived, "
                  "not that the rendering stopped.")
        latency = tk.BooleanVar(value=self.latency_on)
        switch(bar, "Latency", latency)
        note(bar, "How far the lens runs behind what is under it, from the moment Windows composed a "
                  "frame to the moment the lens showed it, plus a refresh and a half for the display. "
                  "On a 120 Hz screen the floor is about 8 to 11 ms, so a reading near that is as low "
                  "as it goes.")
        style_on = tk.BooleanVar(value=self.show_style)
        switch(bar, "NR style", style_on)
        note(bar, "The Home menu's style, Default, Natural or Cinematic, as a picker. Picking one "
                  "restarts the picture, because the add-on reads its settings only when it starts. "
                  "A change made in the Home menu shows here within a second.")
        inten_on = tk.BooleanVar(value=self.show_intensity)
        switch(bar, "Overall intensity", inten_on)
        note(bar, "The Home menu's intensity, shown only. A change made in the Home menu shows here "
                  "within a second. Moving it lives in the Home menu, where the picture follows it "
                  "live.")
        explain(bar, "All of these apply straight away.")

        # ================================================================ profiles
        prof = page("Profiles")

        heading(prof, "Profiles")
        explain(prof, "A profile is everything that makes the picture, saved under a name. That is "
                      "the window's place and size, fullscreen, the pass count, the Cost Scaler, the "
                      "ready switch, what the title bar shows, and every setting in the Home menu. "
                      "The selector on the title bar saves and switches them, and the picture "
                      "restarts when one is applied. Here a profile is renamed or deleted, and the "
                      "current settings can be saved under a name.")
        names = sorted(self.profiles["profiles"], key=str.lower)
        plist = tk.Listbox(prof, height=max(3, min(8, len(names))), bg=FIELD, fg=FG, relief="flat",
                           selectbackground=HOVER, selectforeground=FG, exportselection=False,
                           font=("Segoe UI", 10), highlightthickness=0)
        for n in names:
            plist.insert("end", n)
        plist.grid(row=prof.row, column=0, columnspan=2, sticky="we", padx=12, pady=(2, 2))
        pname = tk.StringVar(master=t, value="")
        tk.Entry(prof, textvariable=pname, width=24, bg=FIELD, fg=FG, insertbackground=FG,
                 relief="flat").grid(row=prof.row, column=2, sticky="new", padx=(6, 12), pady=(2, 2))
        prof.row += 1

        def chosen():
            sel = plist.curselection()
            return plist.get(sel[0]) if sel else None

        # what the chosen profile holds, the lens's own settings on the left and
        # the Home menu's on the right, grouped the way the menu groups them
        facts = tk.Frame(prof, bg=BG)
        facts.grid(row=prof.row + 1, column=0, columnspan=3, sticky="we", padx=12, pady=(10, 4))

        def fact_rows(p):
            a = p.get("addon", {}) or {}

            def val(key, names=None):
                v = a.get(key)
                if v is None:
                    return "default"
                if names is not None:
                    return names.get(str(v).strip(), str(v))
                return str(v)

            onoff = {"0": "off", "1": "on"}
            bar_parts = [x for x in (("size" if p.get("title_size", True) else ""),
                                     {"fps": "frame rate", "detail": "in and out",
                                      "both": "frame rate, in and out"}.get(p.get("readout"), ""),
                                     ("latency" if p.get("latency") else ""),
                                     ("NR style" if p.get("title_style") else ""),
                                     ("intensity" if p.get("title_intensity") else "")) if x]
            lens_rows = [("Passes", str(p.get("passes", ""))),
                         ("Size", "%s x %s" % (p.get("width", "?"), p.get("height", "?"))),
                         ("Place", "%s, %s" % (p.get("x", "?"), p.get("y", "?"))),
                         ("Fullscreen", "yes" if p.get("fullscreen") else "no"),
                         ("Ready mode", "on" if p.get("ready") else "off"),
                         ("Cost Scaler", str(p.get("cost_scaler", ""))),
                         ("Title bar", ", ".join(bar_parts) or "nothing")]
            nr_rows = [("Neural Rendering", val("NeuralUplift", onoff)),
                       ("NR style", val("NRStyle", {"0": "Default", "1": "Natural", "2": "Cinematic"})),
                       ("Overall intensity", val("NRIntensity")),
                       ("NR passes", val("NRPasses")),
                       ("Chained temporal history", val("NRChainedHistory", onoff)),
                       ("Codec", val("NRCodecMode", {"0": "Classic", "1": "Anchored"})),
                       ("Global tone", val("NRGlobalTone")),
                       ("Local tone", val("NRLocalTone")),
                       ("Auto mask", val("NRAutoMask", onoff)),
                       ("Upscaling", val("NREnableUpscaling", onoff))]
            return lens_rows, nr_rows

        def show_facts(name):
            for c in facts.winfo_children():
                c.destroy()
            p = self.profiles["profiles"].get(name) if name else None
            if p is None:
                return
            for col, (title, rows) in enumerate((("The lens", fact_rows(p)[0]),
                                                 ("Neural Rendering, the Home menu", fact_rows(p)[1]))):
                tk.Label(facts, text=title, bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(
                    row=0, column=col * 2, columnspan=2, sticky="w", padx=(0, 24), pady=(0, 2))
                for i, (k, v) in enumerate(rows):
                    tk.Label(facts, text=k, bg=BG, fg=DIM, font=("Segoe UI", 9)).grid(
                        row=i + 1, column=col * 2, sticky="w", padx=(0, 10))
                    tk.Label(facts, text=v, bg=BG, fg=FG, font=("Segoe UI", 9), justify="left",
                             wraplength=170).grid(row=i + 1, column=col * 2 + 1, sticky="w", padx=(0, 24))

        def on_pick(*_):
            n = chosen()
            if n:
                pname.set(n)
                show_facts(n)

        plist.bind("<<ListboxSelect>>", on_pick)

        def refresh():
            plist.delete(0, "end")
            for n in sorted(self.profiles["profiles"], key=str.lower):
                plist.insert("end", n)
            show_facts(None)

        def rename():
            n = chosen()
            if n:
                self.profile_rename(n, pname.get())
                refresh()

        def delete():
            n = chosen()
            if n:
                self.profile_delete(n)
                refresh()
                pname.set("")

        def save_current():
            n = pname.get().strip()
            if n:
                self.profile_store(n)
                refresh()

        btns = tk.Frame(prof, bg=BG)
        btns.grid(row=prof.row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 4))
        for text, cmd in (("Rename to the name typed", rename), ("Delete", delete),
                          ("Save the current settings under the name typed", save_current)):
            tk.Button(btns, text=text, command=cmd, relief="flat", bg=HOVER, fg=FG).pack(side="left", padx=(0, 6))
        prof.row += 2
        # the profile in use starts chosen, with its facts shown
        if self.profile in self.profiles["profiles"]:
            plist.selection_set(names.index(self.profile))
            pname.set(self.profile)
            show_facts(self.profile)

        # ================================================================ hotkeys
        hk = page("Hotkeys")

        heading(hk, "Global hotkeys")
        explain(hk, "A key combination that works from anywhere, whichever window has the keyboard. "
                    "Click a field and press the combination, and Clear takes it away. A combination "
                    "set here is taken from every other program while the lens runs, so none is set "
                    "until you set it. Home, F5 and F6 on their own cannot be used because ReShade "
                    "reads Home and F5 and the add-on reads F6 from the keyboard, and taking them "
                    "would silence the overlay, its screenshot and the Neural Rendering toggle.")
        hk_vars, hk_note = {}, {}
        failed = dict(self.hotkeys.failed)

        def capture(action, var, ent):
            def on_key(e):
                sym = e.keysym
                if sym in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                           "Win_L", "Win_R", "Meta_L", "Meta_R"):
                    return "break"
                mods = 0
                if e.state & 0x4:
                    mods |= MOD_CONTROL
                if e.state & 0x20000:
                    mods |= MOD_ALT
                if e.state & 0x1:
                    mods |= MOD_SHIFT
                low = sym.lower()
                names = {"prior": "pageup", "next": "pagedown", "return": "enter", "print": "printscreen",
                         "scroll_lock": "scrolllock", "apostrophe": "quote", "grave": "backquote",
                         "kp_multiply": "multiply", "kp_add": "add", "kp_subtract": "subtract",
                         "kp_divide": "divide", "kp_decimal": "decimal"}
                low = names.get(low, low)
                if low.startswith("kp_") and low[3:].isdigit():
                    low = "numpad" + low[3:]
                if len(low) == 1 and (low.isalpha() or low.isdigit()):
                    vk = ord(low.upper())
                elif low in VK_BY_NAME:
                    vk = VK_BY_NAME[low]
                else:
                    return "break"
                text = _hotkey_text(mods, vk)
                problem = _hotkey_problem(text)
                if problem:
                    hk_note[action].config(text=problem, fg=WARN)
                else:
                    var.set(text)
                    hk_note[action].config(text="", fg=DIM)
                return "break"
            ent.bind("<KeyPress>", on_key)

        for action, label in HOTKEY_ACTIONS:
            var = tk.StringVar(master=t, value=HOTKEYS.get(action, ""))
            hk_vars[action] = var
            tk.Label(hk, text=label, bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
                row=hk.row, column=0, sticky="w", padx=12, pady=(3, 0))
            ent = tk.Entry(hk, textvariable=var, width=18, bg=FIELD, fg=FG, insertbackground=BG,
                           relief="flat", justify="center")
            ent.grid(row=hk.row, column=1, sticky="w", padx=(6, 6), pady=(3, 0))
            capture(action, var, ent)
            fr = tk.Frame(hk, bg=BG)
            fr.grid(row=hk.row, column=2, sticky="w", padx=(0, 12), pady=(3, 0))
            tk.Button(fr, text="Clear", command=lambda v=var, a=action: (v.set(""), hk_note[a].config(text="")),
                      relief="flat", bg=HOVER, fg=FG).pack(side="left")
            hk_note[action] = tk.Label(fr, text=("in use by another program" if action in failed else ""),
                                       bg=BG, fg=WARN, font=("Segoe UI", 9))
            hk_note[action].pack(side="left", padx=(8, 0))
            hk.row += 1

        # ================================================================ screenshots
        sh = page("Screenshots")

        heading(sh, "Where to save screenshots")
        explain(sh, "Each screenshot saves the picture under the lens, the lens's picture, and the "
                    "two joined side by side, into this folder.")
        shots = tk.StringVar(value=SHOT_DIR)
        folder(sh, shots, "Where should screenshots go?")

        heading(sh, "The clipboard")
        explain(sh, "The side by side image goes onto the clipboard as well as into the folder, ready "
                    "to paste into a message or a document. Applies to the next screenshot.")
        clip = tk.BooleanVar(value=self.clip_shots)
        switch(sh, "Also copy the joined before and after to the clipboard", clip)

        # ================================================================ look
        look = page("Look")

        heading(look, "Theme")
        explain(look, "The colours of the title bar, the menus and this dialog. The picture is never "
                      "touched. A themes.json in the data folder adds themes of your own, one per "
                      "name, with the keys the built-in ones use. Takes effect at the next launch, "
                      "so choosing one restarts the lens.")
        theme_var = tk.StringVar(value=THEME_NAME)
        for name in sorted(ALL_THEMES, key=lambda n: (n != "Slate", n.lower())):
            t_ = ALL_THEMES[name]
            row_ = tk.Frame(look, bg=BG)
            row_.grid(row=look.row, column=0, columnspan=3, sticky="w", padx=8, pady=(3, 0))
            tk.Radiobutton(row_, text=name, variable=theme_var, value=name, bg=BG, fg=FG,
                           selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10), width=12, anchor="w").pack(side="left")
            for key in ("bg", "field", "hover", "cap", "fg", "dim", "accent", "warn", "close"):
                tk.Frame(row_, bg=t_[key], width=22, height=16, highlightthickness=1,
                         highlightbackground=t_["dim"]).pack(side="left", padx=1)
            look.row += 1
        note(look, "Each swatch row is the theme's background, field, hover, window buttons, text, "
                   "dim text, accent, warning and close, in that order.")

        # ================================================================ program
        prog = page("Program")

        heading(prog, "Updates")
        explain(prog, "With the first switch on, the lens asks GitHub for the newest release when it "
                      "starts, at most once a day, and says nothing unless there is one newer than "
                      "this, %s. Then it asks, and opens the release page only if you say so. With "
                      "the second switch on it offers to download that release's installer and run "
                      "it over this install instead, again only if you say yes, and the lens comes "
                      "back on the new version. Off, the lens never contacts anything. Check now "
                      "asks once, straight away." % __version__)
        upd = tk.BooleanVar(value=self.check_updates_on)
        auto = tk.BooleanVar(value=self.auto_update_on)
        upd_btn = switch(prog, "Check for a new version when the lens starts", upd)
        switch(prog, "Offer to download and install it, after asking", auto)
        button(prog, "Check now", lambda: self.check_updates(quiet=False))

        def follow_auto(*_):
            if auto.get():
                upd.set(True)
                upd_btn.config(state="disabled")
            else:
                upd_btn.config(state="normal")

        auto.trace_add("write", follow_auto)
        follow_auto()

        heading(prog, "Folders")
        explain(prog, "Both take effect at the next launch. Changing either restarts the lens.")
        explain(prog, "The folder that holds the Neural Rendering stack and lens-presenter.exe.")
        stack = tk.StringVar(value=STACK_DIR or "")
        folder(prog, stack, "Where is the Neural Rendering stack?")
        explain(prog, "Where the lens keeps its window state and archived logs.")
        data = tk.StringVar(value=DATA_DIR)
        folder(prog, data, "Where should the lens keep its state and logs?")

        # ================================================================ footer
        def save():
            global SHOT_DIR
            restart = False
            d = shots.get().strip()
            if d and d != SHOT_DIR:
                SHOT_DIR = d
                _save_ini("screenshot_dir", d)
            m = stack.get().strip()
            if m and m != (STACK_DIR or ""):
                _save_ini("stack_dir", m)
                restart = True
            dd = data.get().strip()
            if dd and dd != DATA_DIR:
                _save_ini("data_dir", dd)
                restart = True
            if theme_var.get() != THEME_NAME:
                _save_ini("theme", None if theme_var.get() == "Slate" else theme_var.get())
                restart = True
            # the in-and-out readout is the ini's alone, readout = detail, so a save
            # here keeps it if it was set
            detail = self.readout in ("detail", "both")
            r = ("both" if detail and fps_on.get() else "detail" if detail
                 else "fps" if fps_on.get() else "size")
            if r != self.readout:
                self.readout = r
                _save_ini("readout", None if r == "size" else r)
            mirrors_changed = False
            if bool(style_on.get()) != self.show_style:
                self.show_style = bool(style_on.get())
                _save_ini("title_style", "1" if self.show_style else None)
                mirrors_changed = True
            if bool(inten_on.get()) != self.show_intensity:
                self.show_intensity = bool(inten_on.get())
                _save_ini("title_intensity", "1" if self.show_intensity else None)
                mirrors_changed = True
            if mirrors_changed:
                self.show_bar_mirrors()
            if bool(latency.get()) != self.latency_on:
                self.latency_on = bool(latency.get())
                self.latency_ms = None
                _save_ini("latency", None if self.latency_on else "0")
            if bool(size_on.get()) != self.show_size:
                self.show_size = bool(size_on.get())
                _save_ini("title_size", None if self.show_size else "0")
            if bool(ready.get()) != self.ready:
                self.ready = bool(ready.get())
                _save_ini("ready", "1" if self.ready else None)
                self.tell_presenter("ready %d" % (1 if self.ready else 0))
            mode = "always" if cs_always.get() else "fullscreen" if cs_full.get() else "off"
            if COST_SCALER != "manual" and mode != COST_SCALER:
                _set_cost_scaler(mode)
                # the proxy reads its ini within a second of a change, so this is live
                self.apply_proxy()
            self.set_hotkeys({a: v.get() for a, v in hk_vars.items()})
            if bool(clip.get()) != self.clip_shots:
                self.clip_shots = bool(clip.get())
                _save_ini("clipboard_shots", "1" if self.clip_shots else None)
            if bool(upd.get()) != self.check_updates_on:
                self.check_updates_on = bool(upd.get())
                _save_ini("check_updates", "1" if self.check_updates_on else None)
            if bool(auto.get()) != self.auto_update_on:
                self.auto_update_on = bool(auto.get())
                _save_ini("auto_update", "1" if self.auto_update_on else None)
            self.update_info()              # the profile's name on the bar follows the settings
            t.destroy()
            if restart:
                # the folders take effect at the next launch, so the lens restarts.
                # The windowed geometry is what a fullscreen launch derives its
                # monitor from, and what the way back restores, so keep it current.
                if not self.fullscreen:
                    self.save_state()
                self.quit(restart=True)

        # the version sits beside Save on every page: a bug report is far more
        # likely to be written with this dialog open than with the console
        foot = tk.Frame(t, bg=BG)
        foot.grid(row=1, column=0, sticky="we", padx=8, pady=(6, 10))
        foot.columnconfigure(0, weight=1)
        tk.Label(foot, text="Neural Lens %s (beta)" % __version__, bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=12)
        tk.Button(foot, text="Save", command=save, relief="flat", bg=ACCENT,
                  fg=FIELD).grid(row=0, column=1, sticky="e", padx=(0, 6))
        tk.Button(foot, text="Cancel", command=t.destroy, relief="flat",
                  bg=HOVER, fg=FG).grid(row=0, column=2, sticky="w", padx=(0, 12))
        self._place_over_lens(t)

    def _place_over_lens(self, win):
        """Put a dialog over the middle of the lens, kept inside that monitor's
        work area, rather than wherever Tk would put it."""
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        try:
            x, y = self.inner()
            cx, cy = x + self.cw // 2, y + self.ch // 2
        except Exception:
            cx, cy = win.winfo_screenwidth() // 2, win.winfo_screenheight() // 2
        left, top = cx - w // 2, cy - h // 2
        try:
            l, t, ww, hh = tuple(work_area(cx, cy))[:4]
            left = max(l, min(left, l + ww - w))
            top = max(t, min(top, t + hh - h))
        except Exception:
            pass
        win.geometry("+%d+%d" % (left, top))

    def _ask(self, title, text, choices):
        """A question with these buttons, the first one the accent. Returns the
        one chosen, or None when the window is closed instead."""
        d = tk.Toplevel(self.root)
        d.title(title)
        d.attributes("-topmost", True)
        d.configure(bg=BG)
        d.resizable(False, False)
        tk.Label(d, text=text, bg=BG, fg=FG, justify="left", wraplength=460, font=("Segoe UI", 10)).grid(
            row=0, column=0, columnspan=len(choices), sticky="w", padx=14, pady=(14, 12))
        picked = []
        for i, c in enumerate(choices):
            tk.Button(d, text=c, command=lambda c=c: (picked.append(c), d.destroy()), relief="flat",
                      bg=ACCENT if i == 0 else HOVER, fg=FIELD if i == 0 else FG).grid(
                row=1, column=i, sticky="w", padx=(14 if i == 0 else 6, 14 if i == len(choices) - 1 else 0),
                pady=(0, 14))
        self._place_over_lens(d)
        d.grab_set()
        self.root.wait_window(d)
        return picked[0] if picked else None
    def quit(self, restart=False):
        if self.closing:
            return
        self.restart = restart
        self.closing = True
        self.popup.close()
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        for s in reversed(self.stages):
            self._kill_stage(s)
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self.root.quit()


def _pause():
    """Hold the console open so a message on the way out can be read.

    stdin is not always a console. With input redirected, input() raises
    EOFError, and without a console it raises RuntimeError; either would bury
    the message this exists to let you read under a traceback about the
    attempt to wait for you. With no console at all there is nothing to hold
    open.
    """
    if HEADLESS:
        return
    try:
        input("\nPress Enter to close.")
    except (EOFError, OSError, RuntimeError):
        print("")            # the prompt carries no newline of its own


def _fatal(text):
    """Say why the lens cannot start, somewhere it will actually be seen.

    With a console, print and wait for Enter. Without one, the print goes to
    lens.log and a dialog carries the message: a line in a log file is not
    something a person who just double clicked a launcher is going to find.
    """
    print(text, flush=True)
    if not HEADLESS:
        _pause()
        return
    try:
        made = None
        if tk._default_root is None:
            made = tk.Tk()          # or messagebox makes a visible one itself
            made.withdraw()
        messagebox.showerror("Neural Lens", text)
        if made is not None:
            made.destroy()
    except Exception:
        pass


def _offer_setup(reason):
    """Offer to fetch and assemble the neural stack, and relaunch if it worked.

    Returns True when the lens has been relaunched and this process should
    simply return. The stack setup lives in neural_stack.py; the relaunch is
    told the folder it installed into, so no ini change is needed and nothing
    that pointed elsewhere gets in the way.
    """
    try:
        import neural_stack
    except ImportError:
        return False
    root = tk.Tk()
    _set_icon(root)
    root.withdraw()
    root.attributes("-topmost", True)
    want = messagebox.askyesno(
        "Neural Lens",
        reason + "\n\nSet up the Neural Rendering stack now? About %d MB is downloaded from "
        "the projects that publish each part, into the lens's own folder, and registered for "
        "your user only, with no administrator prompt. It takes a few minutes."
        % neural_stack.DOWNLOAD_MB)
    where = False
    if want:
        where = neural_stack.wizard(root)
    try:
        root.destroy()
    except Exception:
        pass
    if not where:
        return False
    # name the new stack first, ahead of whatever led here: a --stack-dir or an
    # ini stack_dir that pointed at an incomplete folder would otherwise be
    # found again by the relaunch, which would offer the setup all over again
    cmd = _relaunch_cmd()
    subprocess.Popen(cmd[:1] + ["--stack-dir", where] + cmd[1:], cwd=_script_dir())
    return True


def main():
    # Three entry points the installer uses. This one runs DURING setup, so it
    # must never open a window of its own: the whole point is that the user
    # meets one installer and not a second surprise afterwards. Everything goes
    # to its own log, which the installer reads line by line to show progress
    # on its own page, and the last line is a sentinel carrying the exit code.
    # The fourth flag the lens accepts, --stack-dir, is read by _find_stack_dir
    # at import time; the lens passes it to itself when it relaunches after a
    # setup.
    if "--install-stack" in sys.argv:
        import neural_stack
        argv = [a for a in sys.argv[1:] if a != "--install-stack"]

        class _Tee:
            """Write to every stream that exists, ignoring the ones that do not.

            The installer reads this process's stdout to show progress on its
            own page, and the log file has to survive for a post mortem.
            Replacing stdout with the file would leave the installer reading
            nothing for the whole download while the log filled up where
            nobody could see it.
            """

            def __init__(self, *streams):
                self.streams = [s for s in streams if s is not None]

            def write(self, text):
                for s in self.streams:
                    try:
                        s.write(text)
                        s.flush()
                    except Exception:
                        pass
                return len(text)

            def flush(self):
                for s in self.streams:
                    try:
                        s.flush()
                    except Exception:
                        pass

        handle = None
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            handle = open(os.path.join(LOGDIR, "stack-setup.log"), "w",
                          encoding="utf-8", errors="replace", buffering=1)
        except OSError:
            pass
        # __stdout__ is None in a windowed build launched with no pipe; when the
        # installer runs us it supplies one, and that is what it reads back
        sys.stdout = sys.stderr = _Tee(handle, getattr(sys, "__stdout__", None))
        try:
            rc = neural_stack.main(argv)
        except Exception as exc:                  # never die silently mid-setup
            print("FAILED: %r" % (exc,), flush=True)
            rc = 3
        print("__STACK_SETUP_EXIT__ %d" % rc, flush=True)
        try:
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(rc)
    # the Start Menu's stack setup, which is the repair path and may show its
    # own window, and the uninstaller's removal of what the setup wrote
    if "--setup-stack" in sys.argv:
        import neural_stack
        neural_stack.wizard()
        return
    if "--uninstall-stack" in sys.argv:
        import neural_stack
        try:
            neural_stack.uninstall()
        except neural_stack.StackError as exc:
            print(exc, flush=True)
        return
    if not STACK_DIR:
        if _offer_setup("The lens could not find its Neural Rendering stack."):
            return
        _fatal("\n".join([
            "Could not find the Neural Rendering stack.",
            "",
            "The lens looks for lens-presenter.exe in its own folder when installed,",
            "in the 'stack' folder beside the script when run from source, and in a",
            "folder pointed at in any of these ways:",
            "",
            '  --stack-dir "D:\\path\\to\\stack" on the command line',
            "  set NEURAL_LENS_STACK=D:\\path\\to\\stack",
            "  copy neural-lens.ini.example to neural-lens.ini and set stack_dir",
            "",
            "The Start Menu's stack setup entry, or python neural_stack.py from",
            "source, fetches and assembles the stack.",
        ]))
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as exc:
        # data_dir is taken from the ini or the environment verbatim and is the
        # one setting nothing validates, so a path on a drive that does not
        # exist would otherwise arrive here as a raw traceback
        _fatal("\n".join([
            "Could not use the folder the lens keeps its state in:",
            "",
            "  %s" % DATA_DIR,
            "",
            "  %s" % exc,
            "",
            "Set data_dir in neural-lens.ini to a folder that exists, or delete",
            "that line to use the data folder beside the program.",
        ]))
        return
    cw, ch, x, y, passes = 1400, 1000, None, None, 1
    if os.path.exists(STATE):
        try:
            v = [int(n) for n in open(STATE).read().split()]
            cw, ch, x, y = v[:4]
            if len(v) > 4:
                passes = v[4]
        except Exception:
            cw, ch, x, y = 1400, 1000, None, None
    if x is None:
        # nothing saved: the preferred size, centred on the main monitor, whose
        # top left corner is always the desktop's origin
        mx, my, mw, mh = work_area(0, 0)
        x, y, cw, ch = fit_rect(mx + EDGE, my + BAR, cw, ch, (mx, my, mw, mh))
        x = mx + (mw - cw) // 2
        y = my + BAR + (mh - BAR - EDGE - ch) // 2
    # kept on one monitor: a saved place can be on a monitor that has since gone,
    # or larger than a lowered resolution leaves room for
    x, y, cw, ch = fit_rect(x, y, cw, ch)
    if FULLSCREEN:
        # the whole of the monitor the windowed lens sits on, the taskbar's place
        # included, with the bar across its top and the picture filling the rest,
        # so a fullscreen video behind the lens is covered to the bottom edge.
        # The ReShade overlay opens at the picture's top left with its tabs along
        # its top edge, so a picture that starts below the bar keeps them clear of
        # it without the bar ever moving. Starting below the bar, the picture
        # never covers a monitor exactly, which would hand it to the compositor's
        # fullscreen path and stop the bar being drawn. The pass count comes from
        # the fullscreen lens's own file.
        mx, my, mw, mh = monitor_rect(x + cw // 2, y + ch // 2)
        x, y, cw, ch = mx, my + BAR, mw, mh - BAR
        if os.path.exists(FULL_STATE):
            try:
                passes = int(open(FULL_STATE).read().split()[0])
            except Exception:
                pass
    cw -= cw % 2
    ch -= ch % 2
    passes = max(1, min(_pass_limit(), passes))
    archive_logs()
    root = tk.Tk()
    _set_icon(root)
    root.withdraw()
    missing = _missing_stack()
    if missing:
        # This has to run before the presenter exists. Its window is topmost
        # and a stock messagebox is not, so once the lens is up this dialog
        # would be drawn underneath it: see Lens.confirm.
        note = "\n".join(
            ["Neural Rendering will probably not run.",
             "",
             "These are not in the stack folder:",
             "  %s" % STACK_DIR,
             ""]
            + ["  %s   (%s)" % (n, d) for n, d in missing]
            + ["",
               "The lens will still open, but it will most likely show the screen",
               "back to you unchanged. The stack setup fetches every one of them."])
        print("\n" + note + "\n", flush=True)
        if _offer_setup(note):
            return
    try:
        lens = Lens(root, x, y, cw, ch, passes, FULLSCREEN)
    except SystemExit as exc:
        # a presenter that never opened its window. Without a console the
        # message would go to the log and the lens would simply fail to appear.
        _fatal(str(exc))
        return
    lens.show_in_taskbar()
    print("Neural Lens %s (beta)" % __version__, flush=True)
    print("lens ready %dx%d at (%d,%d), %d pass%s%s, stack %s"
          % (cw, ch, x, y, lens.passes, "" if lens.passes == 1 else "es",
             ", fullscreen" if FULLSCREEN else "", STACK_DIR),
          flush=True)
    if not ADDON_PASSES:
        print("the add-on in the stack cannot run several passes itself, so the lens runs one",
              flush=True)

    def watch():
        # the stage list is empty for a moment during a restart, and reading
        # stages[0] then would kill this thread, after which a presenter that
        # died would go unnoticed for the rest of the session
        while not lens.closing:
            time.sleep(0.4)
            if lens.rebuilding or not lens.stages:
                continue
            if lens.stages[0]["proc"].poll() is not None:
                break
        root.after(0, lens.quit)

    threading.Thread(target=watch, daemon=True).start()
    root.mainloop()

    if lens.restart:
        # The folder settings take effect at the next launch, so hand the process
        # over to a fresh copy of itself once the presenter is really gone.
        #
        # Not os.execv. On Windows that goes through the CRT, which does not quote
        # arguments containing spaces, so a script path such as
        # "C:\\Some Folder\\neural-lens\\neural_lens.py" reaches the replacement
        # process split at the space. It does not raise either: it starts something
        # broken while this process is already gone, so the lens never comes back
        # and nothing is reported. subprocess quotes correctly through list2cmdline.
        try:
            root.destroy()
        except Exception:
            pass
        time.sleep(1.0)
        cmd = _relaunch_cmd()
        note = os.path.join(LOGDIR, "restart.log")
        print("restarting", flush=True)
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            # The console this was started from may go away with this process, so
            # give the replacement its own destination for anything it prints.
            out = open(note, "w", encoding="utf-8", errors="replace")
            child = subprocess.Popen(cmd, cwd=_script_dir(),
                                     stdout=out, stderr=subprocess.STDOUT)
        except Exception as exc:
            print("could not restart: %s" % exc, flush=True)
            print("start it again yourself, the settings are already saved", flush=True)
            return
        # A restart that fails should say so rather than vanishing without a word.
        time.sleep(3.0)
        if child.poll() is not None:
            print("the restart exited straight away (code %s)" % child.poll(), flush=True)
            print("what it printed is in %s" % note, flush=True)
            print("start it again yourself, the settings are already saved", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # without a console a traceback goes to lens.log and the lens simply
        # never appears, which is the silence the log and the dialogs exist to end
        import traceback
        _fatal("The lens stopped with an error.\n\n" + traceback.format_exc())
        sys.exit(1)
