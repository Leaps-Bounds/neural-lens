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
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox


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


def _read_ini():
    """Optional neural-lens.ini beside this script. Plain key = value lines."""
    cfg = {}
    try:
        with open(os.path.join(_script_dir(), "neural-lens.ini"), encoding="utf-8") as fh:
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
__version__ = "0.3.0"        # beta; see CHANGELOG.md

DATA_DIR = (os.environ.get("NEURAL_LENS_DATA") or _INI.get("data_dir")
            or os.path.join(_script_dir(), "data"))
STATE = os.path.join(DATA_DIR, "lens-state.txt")
LOGDIR = os.path.join(DATA_DIR, "logs")

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
DIVIDER = 14                 # grab width of the A/B divider; the line drawn is 4
KEY_HOLD = 350               # ms a posted key stays down, longer than any frame
KEY, BG, FG, ACCENT = "#010203", "#1b2430", "#cbd5e1", "#4ade80"
DIM, WARN = "#64748b", "#fbbf24"

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
if READOUT not in ("fps", "detail", "size"):
    READOUT = "size"
# The delay meter on the title bar, on unless the ini says latency = 0. See
# Lens._read_presenter for what it measures and what it adds.
LATENCY = str(_INI.get("latency", "1")).strip().lower() in ("1", "yes", "on", "true")

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
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_FRAMECHANGED = 0x0020
SW_HIDE, SW_SHOWNA = 0, 8


def _save_ini(key, value):
    """Write one key into neural-lens.ini beside the script, keeping the rest.

    A value of None removes the key, so a setting put back to its default
    follows the default again rather than pinning today's value.
    """
    path = os.path.join(_script_dir(), "neural-lens.ini")
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
                tk.Frame(box, bg="#334155", height=1).pack(fill="x", padx=6, pady=3)
                continue
            text, command, enabled = item
            lbl = tk.Label(box, text=text, bg=BG, fg=FG if enabled else DIM, anchor="w",
                           padx=14, pady=4, font=("Segoe UI", 10))
            lbl.pack(fill="x")
            if enabled and command is not None:
                lbl.bind("<Enter>", lambda e, l=lbl: l.config(bg="#334155"))
                lbl.bind("<Leave>", lambda e, l=lbl: l.config(bg=BG))
                lbl.bind("<Button-1>", lambda e, c=command: self.choose(c))
        t.update_idletasks()
        wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
        bx, by = lens.t.winfo_x(), lens.t.winfo_y()
        mx, my, mw, mh = monitor_rect(bx + 10, by + 10)
        x = max(mx, min(bx + 6, mx + mw - wd))
        y = by + BAR
        if y + ht > my + mh:
            y = by - ht                   # no room below the bar
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
            if not self.inside(self.win, pt.x, pt.y) and not self.inside(self.lens.menu_btn, pt.x, pt.y):
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
        self.latency_on = LATENCY   # the delay meter on the title bar
        self.latency_ms = None      # its latest reading, the whole delay, estimated
        self.latency_raw = None     # the measured part alone, capture to present
        self._shown = None          # (time, out_frames) behind the fps readout
        self._fps_hist = collections.deque(maxlen=3)
        self.restart = False        # set by the folder settings, read by main()
        self.minimized = False      # hidden, with the presenter paused, until the taskbar button
        self.rs = None              # a resize by the frame in progress, see _grip_down
        self.shot_busy = False
        self.shot_event = threading.Event()
        self.shot_reply = None
        self.probe_event = threading.Event()
        self.probe_reply = None
        self.stages = []            # [{title, proc, hwnd}]: the presenter, one entry
        self.popup = PopupMenu(self)
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

        # the caption buttons, right to left as on every window: close,
        # maximise or restore, minimise
        try:
            capfont, self.glyphs = _caption_glyphs(set(tkfont.families(root)))
        except Exception:
            capfont, self.glyphs = ("Segoe UI", 12), CAPTION_PLAIN
        self.x_btn = tk.Label(bar, text=self.glyphs["close"], bg=BG, fg=FG, font=capfont, padx=11)
        self.x_btn.pack(side="right", fill="y")
        self.x_btn.bind("<Button-1>", lambda e: self.quit())
        self.x_btn.bind("<Enter>", lambda e: self.x_btn.config(bg="#e11d48"))
        self.x_btn.bind("<Leave>", lambda e: self.x_btn.config(bg=BG))
        self.max_btn = tk.Label(bar, text=self.glyphs["restore" if fullscreen else "max"], bg=BG,
                                fg=FG, font=capfont, padx=11)
        self.max_btn.pack(side="right", fill="y")
        self.max_btn.bind("<Button-1>", lambda e: self.toggle_fullscreen())
        self.min_btn = tk.Label(bar, text=self.glyphs["min"], bg=BG, fg=FG, font=capfont, padx=11)
        self.min_btn.pack(side="right", fill="y")
        self.min_btn.bind("<Button-1>", lambda e: self.minimize())

        # plus and minus only choose a number; Set restarts the presenter at it,
        # so going from one pass to three is one restart rather than two
        self.set_btn = tk.Label(bar, text=" Set ", bg=BG, fg=DIM, font=("Segoe UI", 10, "bold"))
        self.set_btn.pack(side="right", padx=(2, 10))
        self.set_btn.bind("<Button-1>", lambda e: self.apply_passes())
        self.plus = tk.Label(bar, text=" + ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.plus.pack(side="right")
        self.plus.bind("<Button-1>", lambda e: self.bump_passes(1))
        self.pass_lbl = tk.Label(bar, text="1 pass", bg=BG, fg=ACCENT, font=("Consolas", 9))
        self.pass_lbl.pack(side="right", padx=2)
        self.minus = tk.Label(bar, text=" \u2212 ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.minus.pack(side="right")
        self.minus.bind("<Button-1>", lambda e: self.bump_passes(-1))
        for b in (self.plus, self.minus, self.set_btn, self.max_btn, self.min_btn):
            b.bind("<Enter>", lambda e, b=b: b.config(bg="#334155"))
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

        nodrag = (self.x_btn, self.max_btn, self.min_btn, self.menu_btn, self.plus, self.minus,
                  self.set_btn)
        for wdg in (bar,) + tuple(bar.winfo_children()):
            if wdg not in nodrag:
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
            "--crop", str(cx), str(cy), "--title", title, "--exclude"]
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
        if not self.minimized:
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
        own it would put a bar back on top of nothing.
        """
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
        if self.fullscreen or self.closing:
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
        if self.fullscreen:
            t.geometry("%dx%d+%d+%d" % (cw, BAR, x, y - BAR))
            self.bar.place(x=0, y=0, width=cw, height=BAR)
            self.hole.place_forget()
            for g in self.grips.values():
                g.place_forget()
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
            parts = ["%d x %d" % (self.cw, self.ch)]
            if self.readout == "detail":
                parts.append("%.0f in  %.0f out" % (self.pres_in, self.pres_out))
            elif idle:
                parts.append("idle")
            elif self.readout == "fps" and shown is not None:
                parts.append("%.0f fps" % shown)
            if self.latency_on and self.latency_ms is not None and not idle:
                parts.append("delay ~%.0f ms" % self.latency_ms)
            self.info.config(text="   ".join(parts), fg=DIM)
        self.root.after(1000, self.stats)

    def save_state(self):
        x, y = self.inner()
        try:
            if self.fullscreen:
                # the windowed geometry stays untouched for the way back
                with open(FULL_STATE, "w") as f:
                    f.write("%d\n" % self.passes)
                return
            with open(STATE, "w") as f:
                f.write("%d %d %d %d %d\n" % (self.cw, self.ch, x, y, self.passes))
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
            mx, my, mw, mh = work_area(x + self.cw // 2, y + self.ch // 2)
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
        """Every setting the lens has, as a control with a plain explanation.

        Nothing here requires editing the ini; the dialog writes it. A value
        put back to its default is removed from the ini, so it follows the
        default on the next machine rather than pinning this one's value.
        The folders take effect at the next launch, so changing them restarts
        the lens.
        """
        t = tk.Toplevel(self.root)
        t.title("Neural Lens settings")
        t.attributes("-topmost", True)
        t.configure(bg=BG)
        t.resizable(False, False)
        row = [0]

        def section(text):
            tk.Label(t, text=text, bg=BG, fg=FG, font=("Segoe UI", 10, "bold")).grid(
                row=row[0], column=0, columnspan=3, sticky="w", padx=12, pady=(14, 2))
            row[0] += 1

        def explain(text):
            tk.Label(t, text=text, bg=BG, fg=DIM, justify="left", wraplength=560,
                     font=("Segoe UI", 9)).grid(row=row[0], column=0, columnspan=3,
                                                sticky="w", padx=12, pady=(0, 2))
            row[0] += 1

        def switch(text, var):
            b = tk.Checkbutton(t, text=text, variable=var, bg=BG, fg=FG, selectcolor="#0b1220",
                               activebackground=BG, activeforeground=FG, disabledforeground=DIM,
                               font=("Segoe UI", 10))
            b.grid(row=row[0], column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))
            row[0] += 1
            return b

        def radio(text, var, value):
            tk.Radiobutton(t, text=text, variable=var, value=value, bg=BG, fg=FG,
                           selectcolor="#0b1220", activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).grid(row=row[0], column=0, columnspan=3,
                                                       sticky="w", padx=8, pady=(2, 0))
            row[0] += 1

        def folder(var, prompt):
            tk.Entry(t, textvariable=var, width=58, bg="#0b1220", fg=FG,
                     insertbackground=FG, relief="flat").grid(
                row=row[0], column=0, columnspan=2, padx=(12, 6), pady=4, sticky="we")

            def browse():
                d = filedialog.askdirectory(initialdir=var.get() or DATA_DIR, title=prompt)
                if d:
                    var.set(os.path.normpath(d))

            tk.Button(t, text="Browse", command=browse, relief="flat", bg="#334155",
                      fg=FG).grid(row=row[0], column=2, padx=(0, 12), pady=4)
            row[0] += 1

        # the console and the menu already name the version; a bug report is
        # far more likely to be written with this dialog open than either
        tk.Label(t, text="Neural Lens %s (beta)" % __version__, bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).grid(row=row[0], column=0, columnspan=3,
                                            sticky="w", padx=12, pady=(10, 0))
        row[0] += 1

        # ---- screenshots
        section("Where to save screenshots")
        shots = tk.StringVar(value=SHOT_DIR)
        folder(shots, "Where should screenshots go?")

        # ---- the Cost Scaler: fullscreen, always, or off, as two switches, the
        # second of which keeps the first on
        section("The Cost Scaler")
        cs_full = tk.BooleanVar(value=COST_SCALER in ("fullscreen", "always"))
        cs_always = tk.BooleanVar(value=COST_SCALER == "always")
        cs_full_btn = switch("Use the Cost Scaler for a fullscreen lens", cs_full)
        cs_always_btn = switch("Use the Cost Scaler for a windowed lens too", cs_always)
        explain("DLSSNR-Cost-Scaler runs the neural model at a fraction of the picture's "
                "resolution and puts the result back at full size: fewer pixels for the model, "
                "a higher frame rate, and a slightly smaller change to the picture. Fullscreen at "
                "6144x2560 it took one pass from 42 frames a second to 58 and two passes from 26 "
                "to 54. The lens uses it only where the model's work would pass about 8 "
                "megapixels over all the passes, which a window reaches at 2560x1440 with three "
                "passes or 3840x2160 with two; below that it would only add its own cost. "
                "Applies straight away.")
        if COST_SCALER == "manual":
            explain("cost_scaler = manual in neural-lens.ini leaves the Cost Scaler's own ini "
                    "alone, so these two do nothing until that line goes.")
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

        # ---- title bar
        section("Title bar")
        readout = tk.StringVar(value=self.readout)
        radio("Only the size", readout, "size")
        radio("The frame rate the content under the lens gives it", readout, "fps")
        radio("Frames captured and new pictures shown, each per second", readout, "detail")
        explain("What sits beside the size on the title bar. The frame rate counts the new "
                "pictures a second the content under the lens hands it, averaged over the last "
                "few seconds: a 30 frame a second video gives 30, and the lens never limits it. "
                "Over content that is not changing the bar says idle whichever is chosen, since "
                "the neural pass then rests. Applies straight away.")
        latency = tk.BooleanVar(value=self.latency_on)
        switch("Show the delay from capture to display", latency)
        explain("How far the picture in the lens runs behind what is under it: from the moment "
                "Windows composed a captured frame to the moment the lens presented it, plus a "
                "refresh and a half for the composition and scanout after. Checked against a "
                "window flipping black and white, it read 8 ms where the flip measured 8 at "
                "120 Hz. Applies straight away.")

        # ---- folders
        section("Folders")
        stack = tk.StringVar(value=STACK_DIR or "")
        explain("The folder that holds the Neural Rendering stack and lens-presenter.exe.")
        folder(stack, "Where is the Neural Rendering stack?")
        data = tk.StringVar(value=DATA_DIR)
        explain("Where the lens keeps its window state and archived logs.")
        folder(data, "Where should the lens keep its state and logs?")
        explain("Both take effect at the next launch. Changing either restarts the lens.")

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
            r = readout.get()
            if r != self.readout:
                self.readout = r
                _save_ini("readout", None if r == "size" else r)
            if bool(latency.get()) != self.latency_on:
                self.latency_on = bool(latency.get())
                self.latency_ms = None
                _save_ini("latency", None if self.latency_on else "0")
            mode = "always" if cs_always.get() else "fullscreen" if cs_full.get() else "off"
            if COST_SCALER != "manual" and mode != COST_SCALER:
                _set_cost_scaler(mode)
                # the proxy reads its ini within a second of a change, so this is live
                self.apply_proxy()
            t.destroy()
            if restart:
                # the folders take effect at the next launch, so the lens restarts.
                # The windowed geometry is what a fullscreen launch derives its
                # monitor from, and what the way back restores, so keep it current.
                if not self.fullscreen:
                    self.save_state()
                self.quit(restart=True)

        tk.Button(t, text="Save", command=save, relief="flat", bg=ACCENT,
                  fg="#0b1220").grid(row=row[0], column=1, sticky="e", pady=(12, 12))
        tk.Button(t, text="Cancel", command=t.destroy, relief="flat",
                  bg="#334155", fg=FG).grid(row=row[0], column=2, sticky="w",
                                            padx=(6, 12), pady=(12, 12))

    def quit(self, restart=False):
        if self.closing:
            return
        self.restart = restart
        self.closing = True
        self.popup.close()
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
        # the work area of the monitor the windowed lens sits on, with the bar
        # across its top and the picture filling the rest. The ReShade overlay
        # opens at the picture's top left with its tabs along its top edge, so a
        # picture that starts below the bar keeps them clear of it without the
        # bar ever moving, and nothing of the lens shares its place with the
        # taskbar, which is always on top as well. Starting below the bar, the
        # picture never covers a monitor exactly, which would hand it to the
        # compositor's fullscreen path and stop the bar being drawn. The pass
        # count comes from the fullscreen lens's own file.
        mx, my, mw, mh = work_area(x + cw // 2, y + ch // 2)
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
