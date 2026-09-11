"""
DLSS 5 Neural Lens: a floating see-through window that neural-renders whatever
is behind it. Drag it by the title bar. The viewport is click-through, so the
mouse reaches the desktop underneath, like the Windows Magnifier lens.

How it works. Every piece below was measured before it was built:

  1. A Windows Magnification API host window sits UNDER the lens, on the exact
     same rect, with our own windows on its EXCLUDE filter list. It asks DWM to
     render the true desktop content for that rect. This is what Windows
     Magnifier does; it does not capture the screen.

  2. Windows.Graphics.Capture captures that host window BY HWND. Window capture
     reads a window's own DWM buffer, so it does not matter that the lens sits
     on top of it. Verified: with the host fully covered by an opaque window,
     WGC still returns the source content at about 52 fps, while Desktop
     Duplication of the same rect returns the occluder instead.

  3. Frames go straight into mpv's stdin as raw BGRA. No ffmpeg, no encode, no
     decode. mpv's NR stack (ReShade + dlss5-feed + renodx-dlss5) does the
     neural rendering.

  4. MULTI-PASS by chaining. The add-on that mpv can use has no pass count, so
     extra passes are made by running the whole thing again: stage N captures
     stage N-1's mpv window with WGC and neural-renders it a second time. All
     stages stack on the lens rect and only the last one is visible. Measured
     cumulative change from the raw source: 7.71, 14.06, 19.52 for one, two and
     three passes, against a round-trip cost of only 0.24 with NR disabled.

     EVERY stage must be on the magnifier's exclude list. Miss one and the
     magnifier renders it back into stage 1's input, which is a feedback loop
     that collapses the picture into a dark blob within seconds.

  5. Moving the lens just moves the windows and re-aims the magnifier, and never
     restarts anything. Changing the pass count DOES respawn every stage, because
     the frame rate declared to mpv depends on how many stages there are and is
     fixed when the process spawns. Declaring a higher rate than the chain can
     deliver makes mpv present without a new frame, and NR then re-runs over its
     own output until the picture collapses to black and recovers, over and over.
     See _fps_for for the measurements.

  6. RESIZING is the one thing that cannot be done live: it recreates mpv's
     swapchain, which forces the NR add-on to release the DLSS feature and crash
     with 0xC0000005. So the menu's resize saves the new geometry and relaunches
     the process at that size instead. That handover must not use os.execv: on
     Windows it does not quote arguments containing spaces, and this project's
     own path has one in "DLSS 5".

Configuration: see neural-lens.ini.example. State and logs live in
%LOCALAPPDATA%/NeuralLens by default.
"""
import collections
import ctypes
import ctypes.wintypes as w
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import zlib
from tkinter import filedialog, messagebox

import numpy as np
from windows_capture import WindowsCapture, Frame, InternalCaptureControl


def _script_dir():
    return os.path.dirname(os.path.abspath(__file__))


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


def _find_mpv_dir():
    """Locate the mpv install carrying the DLSS 5 Neural Rendering stack.

    Checked in order: --mpv-dir on the command line, the NEURAL_LENS_MPV_DIR
    environment variable, mpv_dir in neural-lens.ini, an "mpv" folder beside
    this script, and finally C:/Games/_mpv.
    """
    cands = []
    for i, a in enumerate(sys.argv):
        if a == "--mpv-dir" and i + 1 < len(sys.argv):
            cands.append(sys.argv[i + 1])
    cands += [os.environ.get("NEURAL_LENS_MPV_DIR"), _INI.get("mpv_dir"),
              os.path.join(_script_dir(), "mpv"), r"C:\Games\_mpv"]
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "mpv.exe")):
            return os.path.abspath(d)
    return None


MPV_DIR = _find_mpv_dir()
MPV = os.path.join(MPV_DIR, "mpv.exe") if MPV_DIR else None

# Finding the folder only proves mpv.exe is in it, so an ordinary mpv install
# passes, the lens starts, and it shows the screen back unchanged with nothing
# said. That reads as the app doing nothing rather than as a misconfiguration.
NEURAL_STACK = (
    ("dlss5-feed.addon64", "the DLSS 5 feed add-on"),
    ("renodx-dlss5.addon64", "the RenoDX DLSS 5 add-on"),
    ("nvngx_dlssnr.dll", "NVIDIA's Neural Rendering model"),
    # the super resolution DLL is required even though the lens never upscales:
    # with it renamed aside the lens started, held 100 fps and rendered nothing
    # at all, feature=18 never created and the output within 0.01 of the input
    ("nvngx_dlss.dll", "NVIDIA's DLSS runtime, which the model loads through"),
)


def _missing_stack():
    """Which parts of the Neural Rendering stack are not in MPV_DIR.

    This warns rather than refuses. The names are matched exactly against a
    known good install, so a variant layout that works should not be blocked on
    a guess about filenames.
    """
    if not MPV_DIR:
        return []
    return [(n, d) for n, d in NEURAL_STACK
            if not os.path.isfile(os.path.join(MPV_DIR, n))]


def _read_nr_enabled():
    """Whether the add-on will start with Neural Rendering on, from ReShade.ini.

    The add-on persists its F6 toggle there as NeuralUplift and reads it at
    start: measured, a session begun with NeuralUplift=0 ran as a passthrough,
    an in-to-out difference of 1.2 against 2.2 with it on, same image. It is
    written only at exit, so this is the starting state and nothing more. The
    running state is tracked from the key itself, see Lens.watch_f6.
    """
    if not MPV_DIR:
        return True
    try:
        with open(os.path.join(MPV_DIR, "ReShade.ini"), encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                bare = line.strip()
                if bare.lower().startswith("neuraluplift="):
                    return bare.split("=", 1)[1].strip().lower() not in ("0", "no", "off", "false")
    except OSError:
        pass
    return True


# The stage windows are found by exact title, so the title carries the process
# id: two lenses at once, one per monitor say, must not pick up each other's
# stages while waiting for their own to appear.
TITLE = "LensNR %d" % os.getpid()
__version__ = "0.1.0"        # beta; see CHANGELOG.md

DATA_DIR = (os.environ.get("NEURAL_LENS_DATA") or _INI.get("data_dir")
            or os.path.join(os.environ.get("LOCALAPPDATA") or _script_dir(), "NeuralLens"))
STATE = os.path.join(DATA_DIR, "lens-state.txt")
LOGDIR = os.path.join(DATA_DIR, "logs")

# Started by pythonw there is no console. Everything the lens prints goes to
# lens.log in the log folder instead, and anything that used to stop and wait
# for Enter is shown as a dialog, since there is nothing left to read it in.
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

try:
    MAX_PASSES = max(1, min(8, int(_INI.get("max_passes", 4))))
except ValueError:
    MAX_PASSES = 4

BAR, EDGE = 34, 2
DIVIDER = 14                 # grab width of the A/B divider; the line drawn is 4
KEY_HOLD = 350               # ms a posted key stays down, longer than any stage's frame
KEY, BG, FG, ACCENT = "#010203", "#1b2430", "#cbd5e1", "#4ade80"
DIM, WARN = "#64748b", "#fbbf24"
def _display_hz():
    """Refresh rate of the primary display, so nothing is hardcoded to 60 or 120.

    mpv presents according to the frame rate it is told the stream has, so
    declaring 60 caps what you actually see at 60 no matter how fast frames
    arrive. The repaint pump is paced to the same rate: there is no point
    producing frames faster than the display can show them.
    """
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
        dm = DEVMODEW(); dm.dmSize = ctypes.sizeof(DEVMODEW)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
            hz = int(dm.dmDisplayFrequency)
            if 24 <= hz <= 1000:
                return hz
    except Exception:
        pass
    return 60


def _rate(key, default):
    try:
        v = int(_INI.get(key, default))
        return v if 24 <= v <= 1000 else default
    except (TypeError, ValueError):
        return default


DISPLAY_HZ = _display_hz()
BASE_FPS = _rate("fps", DISPLAY_HZ)     # ceiling, before dividing by stage count
PUMP_HZ = _rate("pump_hz", DISPLAY_HZ)  # magnifier repaint pacing

# The rate is adapted to what the chain measurably presents unless the ini says
# adaptive = 0, in which case the fixed rule in _fps_for is declared and kept.
ADAPTIVE = str(_INI.get("adaptive", "1")).strip().lower() not in ("0", "no", "off", "false")
try:
    MIN_FPS = max(5, min(60, int(_INI.get("min_fps", 12))))
except (TypeError, ValueError):
    MIN_FPS = 12

# Fullscreen covers the whole monitor the lens is on. It is an ini flag rather
# than a window state because the lens has to restart to change size, and the
# windowed geometry in the state file must survive the round trip, so the
# fullscreen chain keeps its pass count and best held rate in a file of its own.
FULLSCREEN = str(_INI.get("fullscreen", "0")).strip().lower() in ("1", "yes", "on", "true")
FULL_STATE = os.path.join(DATA_DIR, "lens-state-fullscreen.txt")

# What the title bar shows beside the size. fps is what the visible pass
# actually presents, averaged over the last few seconds, which is the number a
# person means by it. detail is the capture rate in and the rate asked of the
# visible pass, which is what the governor works from. size is just the size.
READOUT = str(_INI.get("readout", "fps")).strip().lower()
if READOUT not in ("fps", "detail", "size"):
    READOUT = "fps"


def _fps_for(stages):
    """The fixed rule: the rate for this many stages on this display.

    With the adaptive rate (the default) this is only where the visible stage
    starts, and the governor in Lens.start_governor takes it from there. With
    adaptive = 0 it is declared to mpv and kept, and everything below applies
    unchanged.

    The rate must never exceed what the chain delivers.

    Every pass is another full capture and present stage, so throughput divides
    roughly by the number of stages. Declaring more than actually arrives makes
    mpv present without a new frame to draw, and Neural Rendering then re-runs
    over its own previous output until the picture crushes toward black, until
    something forces a fresh frame and it recovers. It looks like the image
    blobbing and resetting every few seconds.

    Measured on a 120 Hz display, as samples out of 14 that collapsed:

        120 fps   1 stage 0/14    2 stages 8/14    3 stages 4/14
         90 fps                   2 stages 0/14
         60 fps                   2 stages 0/14    3 stages 0/14   4 stages 4/14
         30 fps                   2 stages 0/14

    Dividing by the stage count is necessary but not sufficient. Declaring exactly
    what the chain delivers is already broken, because ordinary jitter then lands
    some presents with no new frame to draw. That does not collapse the picture,
    it shimmers: measured as frame to frame change on a static source, where the
    floor is 0.146 out of 255:

        one stage, with about 119 frames a second arriving
            120 declared   1.637       0 percent headroom
            110 declared   0.220       5 percent
            100 declared   0.150      16 percent
             90 declared   0.148      24 percent

    So the rate is also held to five sixths of the ceiling, giving 100, 50, 33 and
    25 on a 120 Hz display.

    Stages after the first are fed by the stage before them, which presents at
    this same rate, so they sit at parity by construction and dividing cannot fix
    that. What makes parity safe is a longer frame interval, which is why two
    stages at 60 measured 0.225 while three at 40 and four at 30 measured at the
    floor: 16.7 ms leaves room for jitter to slip past a present, 25 ms and 33 ms
    do not.

    Known limit: this assumes the chain delivers close to the display rate, which
    holds at 120 Hz but is untested on a faster panel. On hardware that cannot
    keep up, the declared rate would still be too high.
    """
    return max(24, (BASE_FPS * 5 // 6) // max(1, stages))

u = ctypes.windll.user32
mag = ctypes.windll.magnification
k32 = ctypes.windll.kernel32
u.SetProcessDPIAware()
try:
    ctypes.windll.winmm.timeBeginPeriod(1)   # default granularity is 15.6 ms
except Exception:
    pass
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_POPUP = 0x40000000, 0x10000000, 0x80000000
WS_THICKFRAME, WS_MAXIMIZEBOX = 0x00040000, 0x00010000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x08000000
HWND_TOPMOST = ctypes.c_void_p(-1)          # pointer sized, NOT int -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_FRAMECHANGED = 0x0020
MW_FILTERMODE_EXCLUDE = 0
LWA_ALPHA = 0x2


def _write_png(path, rgb):
    """Minimal PNG encoder, so the only dependencies stay numpy and
    windows-capture. rgb is an HxWx3 uint8 array."""
    h, wd = rgb.shape[:2]
    raw = np.empty((h, wd * 3 + 1), np.uint8)
    raw[:, 0] = 0                                  # per row filter: none
    raw[:, 1:] = rgb.reshape(h, wd * 3)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", wd, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw.tobytes(), 6)))
        f.write(chunk(b"IEND", b""))


def _bgra_to_rgb(a):
    return np.ascontiguousarray(a[:, :, 2::-1])


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
    """Keep the PREVIOUS session's logs before mpv overwrites them. Without this,
    launching again destroys the only evidence of a failure.

    ReShade rotates to ReShade.log1, ReShade.log2 and so on when the first file is
    already locked, which is exactly what happens with more than one stage. So a
    multi-pass run leaves one log per stage, and copying only ReShade.log threw
    every stage but one away.
    """
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        names = [n for n in os.listdir(MPV_DIR)
                 if n.startswith("ReShade.log") or n == "dlss5-feed.log"]
        for name in sorted(names):
            src = os.path.join(MPV_DIR, name)
            if os.path.isfile(src) and os.path.getsize(src) > 0:
                shutil.copy2(src, os.path.join(LOGDIR, "%s-%s" % (stamp, name)))
        # mpv's stderr is appended to once per stage for the life of a session,
        # and the pruning below sorts by name, so a file not carrying a stamp is
        # never reached and would grow without bound. Roll it into the archive.
        prev = os.path.join(LOGDIR, "mpv-stderr.log")
        if os.path.isfile(prev):
            if os.path.getsize(prev) > 0:
                os.replace(prev, os.path.join(LOGDIR, "%s-mpv-stderr.log" % stamp))
            else:
                os.remove(prev)
        files = sorted(os.listdir(LOGDIR))
        while len(files) > 80:
            os.remove(os.path.join(LOGDIR, files.pop(0)))
    except Exception:
        pass


def _own_windows():
    """Every visible top-level window owned by this process.

    The magnifier must not see any of them. Listing them by name cannot work,
    because the popup menu, the resize outline, the settings dialog and any
    message box are created and destroyed on demand. Anything missed is rendered
    into stage 1's input and neural rendered along with the desktop.
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


def find_mpv(title):
    """Exact title match. Stage titles share a prefix, so substring matching
    would return the wrong window."""
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        c = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, c, 256)
        if c.value == "mpv" and b.value == title:
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


class MpvIPC:
    """mpv's JSON IPC over a named pipe, just enough to set a property.

    The pipe is opened on first use, because mpv creates it a moment after the
    process starts. A dead mpv makes readline return nothing, which comes back
    as None rather than an exception, so a stage that is being torn down cannot
    take the caller with it.
    """

    def __init__(self, pipe):
        self.pipe = pipe
        self.f = None
        self.lock = threading.Lock()
        self.rid = 0

    def command(self, *args):
        with self.lock:
            if self.f is None:
                self.f = open(self.pipe, "r+b", buffering=0)
            self.rid += 1
            rid = self.rid
            self.f.write((json.dumps({"command": list(args), "request_id": rid}) + "\n")
                         .encode("utf-8"))
            for _ in range(200):
                line = self.f.readline()
                if not line:
                    return None
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("request_id") == rid:
                    return m
            return None

    def set(self, prop, value):
        return self.command("set_property", prop, value)

    def close(self):
        try:
            if self.f is not None:
                self.f.close()
        except OSError:
            pass
        self.f = None


class Lens:
    def __init__(self, root, x, y, cw, ch, passes, rate=None, fullscreen=False):
        self.root, self.cw, self.ch = root, cw, ch
        self.fullscreen = fullscreen    # the title bar overlays the picture, no drag
        self.split = None           # A/B divider as a fraction of the width, or off
        self.divider = None         # the draggable divider window while split is on
        self.settle_until = 0.0     # the governor ignores its counters until then
        self.drag = None
        self.closing = False
        self.rebuilding = False     # True while set_passes is replacing the chain
        self.tweak = False          # True while the viewport is interactive
        self.frames = 0
        self.t_first = None
        self.out_frames = 0         # frames the visible stage has presented
        self.out_ctl = None
        self.out_alive = None
        self.in_lum = None          # mean luminance entering stage 1, sampled
        self.out_lum = None         # mean luminance the visible stage shows
        self.in_mad = None          # how much the source moves, sampled
        self.in_lums = collections.deque(maxlen=64)      # (t, luminance) entering stage 1
        self.out_mads = collections.deque(maxlen=1200)   # (t, change) per output frame
        self._in_prev = None
        self._out_prev = None
        self.rate_note = ""         # last governor decision, for the title bar
        self.readout = READOUT      # what the title bar shows beside the size
        self._shown = None          # (time, out_frames) behind the fps readout
        self._fps_hist = collections.deque(maxlen=3)
        self.saved_rate = rate      # best held rate from the state file, if any
        # the state file's rate is a level this size and pass count held before,
        # so it counts as proven ground the governor may retake quickly
        self.best_rate = rate or 0  # highest rate this chain has actually held
        self.restart = False        # set by the resize flow, read by main()
        self.shot_want = False      # ask the capture thread for one source frame
        self.shot_ready = False
        self.shot_busy = False
        self.shot_buf = np.empty((ch, cw, 4), np.uint8)
        self.stages = []            # [{title, proc, hwnd, ctl}], last one is visible
        self.pending = passes       # the pass count chosen on the bar, applied by Set
        self.nr_on = _read_nr_enabled()   # Neural Rendering on, as far as the lens knows

        # ---- chrome (tk): title bar + subtle border + transparent hole
        t = tk.Toplevel(root)
        self.t = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=ACCENT)
        t.attributes("-transparentcolor", KEY)
        # windowed, the bar sits above the picture inside a frame that also draws
        # the border. Fullscreen there is no room above the monitor, so the
        # chrome is just the bar, laid over the top edge of the picture. It must
        # not be larger than the screen: a layered window that is comes up
        # blank, with nothing drawn at all.
        if fullscreen:
            t.geometry("%dx%d+%d+%d" % (cw, BAR, x, y))
        else:
            t.geometry("%dx%d+%d+%d" % (cw + EDGE * 2, ch + BAR + EDGE, x - EDGE, y - BAR))
        bar = tk.Frame(t, bg=BG, height=BAR)
        bar.place(x=0 if fullscreen else EDGE, y=0, width=cw, height=BAR)

        self.menu_btn = tk.Label(bar, text=" \u2630 ", bg=BG, fg=FG, font=("Segoe UI", 12))
        self.menu_btn.pack(side="left", padx=(6, 0))
        self.menu_btn.bind("<Button-1>", self.menu)
        tk.Label(bar, text="  DLSS 5 Neural Lens", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.info = tk.Label(bar, text="%d x %d" % (cw, ch), bg=BG, fg=DIM,
                             font=("Consolas", 9))
        self.info.pack(side="left", padx=10)

        self.x_btn = tk.Label(bar, text="  \u2715  ", bg=BG, fg=FG, font=("Segoe UI", 12))
        self.x_btn.pack(side="right")
        self.x_btn.bind("<Button-1>", lambda e: self.quit())
        self.x_btn.bind("<Enter>", lambda e: self.x_btn.config(bg="#e11d48"))
        self.x_btn.bind("<Leave>", lambda e: self.x_btn.config(bg=BG))

        # plus and minus only choose a number; Set rebuilds the chain at it, so
        # going from one pass to four is one rebuild rather than three
        self.set_btn = tk.Label(bar, text=" Set ", bg=BG, fg=DIM, font=("Segoe UI", 10, "bold"))
        self.set_btn.pack(side="right", padx=(2, 6))
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
            b.bind("<Enter>", lambda e, b=b: b.config(bg="#334155"))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=BG))

        tk.Frame(t, bg=KEY).place(x=EDGE, y=BAR, width=cw, height=ch)
        nodrag = (self.x_btn, self.menu_btn, self.plus, self.minus, self.set_btn)
        for wdg in (bar,) + tuple(bar.winfo_children()):
            if wdg not in nodrag:
                wdg.bind("<ButtonPress-1>", self.down)
                wdg.bind("<B1-Motion>", self.move)
                wdg.bind("<ButtonRelease-1>", self.up)
        t.update()
        self.chrome = u.GetParent(t.winfo_id()) or t.winfo_id()
        # never take foreground: the lens is a tool window floating over whatever
        # you are actually using, and stealing focus costs the user their next click
        _ex = u.GetWindowLongPtrW(self.chrome, GWL_EXSTYLE)
        u.SetWindowLongPtrW(self.chrome, GWL_EXSTYLE, _ex | WS_EX_NOACTIVATE)

        # ---- magnifier host UNDER the lens (same rect). Must NOT be a tool
        #      window, or WGC cannot find it. Not topmost: it lives below mpv.
        hInst = k32.GetModuleHandleW(None)
        self.host = u.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
            "Static", "LensMagHost", WS_POPUP,
            x, y, cw, ch, None, None, hInst, None)
        u.SetLayeredWindowAttributes(self.host, 0, 255, LWA_ALPHA)
        u.ShowWindow(self.host, 8)                       # SW_SHOWNA
        if not mag.MagInitialize():
            raise SystemExit("MagInitialize failed")
        self.hmag = u.CreateWindowExW(
            0, "Magnifier", "LensMag", WS_CHILD | WS_VISIBLE,
            0, 0, cw, ch, self.host, None, hInst, None)
        if not self.hmag:
            raise SystemExit("magnifier control failed")

        # ---- stage 1: the magnifier host feeds the first mpv. The rate declared
        # to mpv depends on how many stages there will be, so it is settled first.
        self.fps = _fps_for(passes)
        self.rate = self.start_rate(passes) if ADAPTIVE else self.fps
        if ADAPTIVE and self.saved_rate:
            # the state file remembers the best rate this size and pass count held,
            # so the chain does not have to shimmer its way down again
            self.rate = max(MIN_FPS, min(self.rate, self.saved_rate))
        self._build_first(x, y)
        self.raise_chrome()
        self.aim()

        for _ in range(max(0, passes - 1)):
            self._append_stage()
        self.update_info()
        self.start_counter()

        self.start_pump()
        self.start_governor()
        self.watch_f6()
        self.root.after(1000, self.stats)
        self.root.after(200, self.watch_filter)

    # ---- stage plumbing
    def spawn_mpv(self, title, x, y):
        """Start one mpv reading raw BGRA on stdin, and return (proc, hwnd, ipc).

        The stream's frame rate is fixed for the life of the process, so with
        the adaptive rate every stage is declared at the display rate and the
        rate it actually presents is its playback speed, which the governor can
        change at any time over IPC. In fixed mode the rule's rate is declared
        outright and the speed is 1.
        """
        env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
        pipe = r"\\.\pipe\lensnr-%d-%s" % (os.getpid(), title)
        declared = BASE_FPS if ADAPTIVE else self.fps
        cmd = [MPV, "-",
               "--demuxer=rawvideo", "--demuxer-rawvideo-w=%d" % self.cw,
               "--demuxer-rawvideo-h=%d" % self.ch, "--demuxer-rawvideo-mp-format=bgra",
               "--demuxer-rawvideo-fps=%d" % declared,
               "--speed=%.4f" % (self.rate / float(declared)),
               "--input-ipc-server=%s" % pipe,
               "--geometry=%dx%d+%d+%d" % (self.cw, self.ch, x, y),
               "--hidpi-window-scale=no", "--no-border", "--no-osc",
               "--no-window-dragging", "--ontop", "--force-window=immediate",
               "--keep-open=yes", "--cache=no",
               # Two frames of readahead rather than eight, plus mpv's own low
               # latency mode. The lens plays slower than frames arrive, so this
               # buffer is always full and every frame in it is pure delay.
               # Measured at one pass and 99 fps with a black and white flipper
               # under the lens, from the change on screen to the change in the
               # output: eight frames 136 ms, two frames 78 ms, two frames with
               # the latency hacks 68 ms, with 99 fps presented throughout. One
               # frame measured 63 ms but leaves no slack for a late frame, which
               # is what makes the picture shimmer, so two is the floor.
               "--demuxer-max-bytes=%d" % (self.cw * self.ch * 4 * 2),
               "--video-latency-hacks=yes",
               "--title=%s" % title]
        # mpv's stderr used to go to DEVNULL, so when it could not start, the
        # reason was destroyed and only the symptom below survived. stdout stays
        # discarded: mpv's status line is continuous and would bloat the file.
        errlog = os.path.join(LOGDIR, "mpv-stderr.log")
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            errf = open(errlog, "a", encoding="utf-8", errors="replace")
            errf.write("\n--- %s  %s ---\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), title))
            errf.flush()
        except OSError:
            errf, errlog = subprocess.DEVNULL, None
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=errf, cwd=MPV_DIR, env=env)
        if errf is not subprocess.DEVNULL:
            try:
                errf.close()          # the child holds its own handle
            except OSError:
                pass
        hwnd = None
        for i in range(140):
            hwnd = find_mpv(title)
            if hwnd:
                break
            if i == 20:
                # thirty five seconds of nothing reads as a hang, so say what
                # is being waited for rather than leaving it silent
                print("waiting for mpv to open its window ...", flush=True)
            time.sleep(0.25)
        if not hwnd:
            try:
                proc.kill()
            except Exception:
                pass
            raise SystemExit("\n".join([
                "mpv never opened a window for stage %s." % title,
                "",
                "The usual cause is that this mpv install cannot start with the",
                "Neural Rendering stack loaded, so check that ReShade is registered",
                "as the Vulkan layer for it.",
                "",
                ("What mpv printed is in:\n  %s" % errlog) if errlog
                else "mpv's own output could not be captured.",
            ]))
        st = u.GetWindowLongPtrW(hwnd, GWL_STYLE)
        u.SetWindowLongPtrW(hwnd, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
        self.set_interactive(hwnd, False)
        u.SetWindowPos(hwnd, HWND_TOPMOST, x, y, self.cw, self.ch, SWP_NOACTIVATE)
        return proc, hwnd, MpvIPC(pipe)

    def start_capture(self, src_hwnd, dst_proc, count=False, alive=None):
        """WGC on src_hwnd, frames written to dst_proc's stdin.

        alive is a one key dict the owning stage can clear. Without it the writer
        thread only ever exits on lens.closing or a failed write, so rebuilding
        the chain would strand one thread per stage waiting on a condition that
        nothing will ever signal again.
        """
        if alive is None:
            alive = {"ok": True}
        # minimum_update_interval defaults to a value that throttles delivery to about
        # 60 fps. Setting it to 0 more than doubles it: 59.4 -> 124.6 on the same source.
        cap = WindowsCapture(cursor_capture=False, draw_border=False,
                             minimum_update_interval=0, window_hwnd=src_hwnd)
        lens = self
        # WGC hands back a row padded, non contiguous view. Copying it with
        # ascontiguousarray().tobytes() costs two full copies, measured at 2.93 ms
        # per 1400x1000 frame. Copying into one reused buffer and writing its
        # memoryview costs 0.18 ms, and this runs on the capture thread, which has
        # to keep up with delivery.
        # Two buffers and a one slot handoff. Writing 5.6 MB into mpv's stdin is
        # synchronous and blocks whenever mpv has not drained the previous frame,
        # which stalls the thread WGC delivers on: measured 58.7 fps with the write
        # removed against 50.5 with it. The writer thread absorbs that, and a full
        # slot is overwritten rather than queued, because for a live view the newest
        # frame is the only one worth having.
        bufs = [np.empty((self.ch, self.cw, 4), np.uint8) for _ in range(2)]
        mvs = [memoryview(b).cast("B") for b in bufs]
        slot = {"i": 0, "ready": None}
        cv = threading.Condition()

        def writer():
            while alive["ok"] and not lens.closing:
                with cv:
                    while slot["ready"] is None and alive["ok"] and not lens.closing:
                        cv.wait(0.2)
                    idx = slot["ready"]
                    slot["ready"] = None
                if idx is None:
                    continue
                try:
                    dst_proc.stdin.write(mvs[idx])
                except (BrokenPipeError, OSError, ValueError):
                    return

        threading.Thread(target=writer, daemon=True).start()

        def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
            if lens.closing or not alive["ok"]:
                control.stop()
                return
            try:
                if frame.height < lens.ch or frame.width < lens.cw:
                    return
                i = slot["i"]
                np.copyto(bufs[i], frame.frame_buffer[:lens.ch, :lens.cw, :])
                with cv:
                    slot["ready"] = i
                    cv.notify()
                slot["i"] = 1 - i
                if count:
                    if lens.shot_want:
                        # copy here rather than holding a reference: the two
                        # buffers rotate every frame, so a reference would race
                        try:
                            np.copyto(lens.shot_buf,
                                      frame.frame_buffer[:lens.ch, :lens.cw, :])
                            lens.shot_ready = True
                        except Exception:
                            pass
                        lens.shot_want = False
                    if lens.t_first is None:
                        lens.t_first = time.perf_counter()
                    lens.frames += 1
                    if lens.frames % 8 == 0:
                        # one frame in eight, one pixel in sixteen: the governor
                        # compares the luminance with what the visible stage
                        # shows, and the change since the previous sample says
                        # whether the source is still enough to judge shimmer
                        sub = bufs[i][::4, ::4, :3].astype(np.int16)
                        lens.in_lum = float(sub.mean())
                        lens.in_lums.append((time.perf_counter(), lens.in_lum))
                        if lens._in_prev is not None and lens._in_prev.shape == sub.shape:
                            lens.in_mad = float(np.abs(sub - lens._in_prev).mean())
                        lens._in_prev = sub
            except (BrokenPipeError, OSError, ValueError):
                control.stop()

        def on_closed():
            pass

        cap.event(on_frame_arrived)
        cap.event(on_closed)
        return cap.start_free_threaded()

    def refresh_filter(self):
        """The magnifier must never see any of our own windows.

        Missing a stage creates a feedback loop that collapses the image to a dark
        blob. Missing a transient window, such as the popup menu, is quieter but
        just as wrong: it gets neural rendered into the lens content and turns up
        in saved screenshots. The stages are separate processes, so they are added
        explicitly; everything else is found by enumeration.
        """
        hs = list(dict.fromkeys(_own_windows() + [self.host, self.chrome]
                                + [s["hwnd"] for s in self.stages]))
        arr = (w.HWND * len(hs))(*hs)
        mag.MagSetWindowFilterList(self.hmag, MW_FILTERMODE_EXCLUDE, len(hs), arr)

    def watch_filter(self):
        """Re-apply the exclude list on a timer.

        A popup menu or a dialog appears and vanishes with no hook to refresh
        from, so the list is rebuilt periodically instead. This runs on the
        mainloop because the Mag call has to happen on the thread that owns the
        magnifier.
        """
        if self.closing:
            return
        try:
            self.refresh_filter()
            self.keep_chrome_on_top()
        except Exception:
            pass
        self.root.after(200, self.watch_filter)

    def keep_chrome_on_top(self):
        """Raise the chrome again if a stage has climbed above it.

        mpv re-asserts its own topmost position on some window events, and a
        stage that covers the whole monitor ends up above the title bar, which
        then cannot be seen or clicked. Only the stages count: menus and dialogs
        are meant to be above the chrome.
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

    def bring_back(self):
        """Put every stage and the title bar back on top, in chain order.

        A fullscreen application, or another window that asks to be on top,
        can leave the lens underneath and demoted from topmost, with no way
        back short of restarting it. raise_chrome only re-asserts the title
        bar, so on its own it would put a bar back on top of nothing.
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
    # _taskbar_click: the lens comes back to the top and the root is minimised
    # again before it can be noticed. Tk toplevels on Windows are not owned by
    # the root, so minimising it does not take the title bar with it; measured
    # rather than assumed.
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
        self.bring_back()
        self.root.after(80, self.root.iconify)

    # ---- live A/B split
    # The lens is see-through, so the raw source is already on screen under the
    # stages. Clipping every stage window to the left of a divider reveals it on
    # the right, live and pixel aligned, at no cost. Every stage has to be
    # clipped, not just the visible one: the stages stack, so clipping only the
    # last would reveal the stage below it rather than the desktop.
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
        else:
            self.split = None
            try:
                self.divider.destroy()
            except Exception:
                pass
            self.divider = None
        self.apply_split()
        self.place_divider()
        # clipping and unclipping are big frame to frame changes on the output
        # capture; give the governor a fresh window rather than a false shimmer
        self.out_mads.clear()
        self.settle_until = time.perf_counter() + 3.0

    def apply_split(self):
        """Clip every stage to the left of the divider, or unclip them all."""
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

    def visible(self):
        return self.stages[-1]["hwnd"]

    def _build_first(self, x, y):
        """Stage 1, fed by the magnifier host rather than by another stage."""
        alive = {"ok": True}
        proc, hwnd, ipc = self.spawn_mpv(TITLE, x, y)
        ctl = self.start_capture(self.host, proc, count=True, alive=alive)
        self.stages.append({"title": TITLE, "proc": proc, "hwnd": hwnd,
                            "ctl": ctl, "alive": alive, "ipc": ipc})
        self.refresh_filter()

    def _append_stage(self):
        """One more mpv on the end, neural rendering the stage before it."""
        x, y = self.inner()
        n = len(self.stages) + 1
        title = "%sp%d" % (TITLE, n)
        alive = {"ok": True}
        proc, hwnd, ipc = self.spawn_mpv(title, x, y)
        ctl = self.start_capture(self.stages[-1]["hwnd"], proc, alive=alive)
        self.stages.append({"title": title, "proc": proc, "hwnd": hwnd,
                            "ctl": ctl, "alive": alive, "ipc": ipc})
        self.refresh_filter()

    def _kill_stage(self, s):
        s.get("alive", {})["ok"] = False
        for step in (lambda: s["ipc"].close(),
                     lambda: s["ctl"].stop(),
                     lambda: s["proc"].stdin.close(),
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

    def set_passes(self, n, save=True):
        """Rebuild the whole chain at n passes.

        Appending a single stage is not enough. In fixed mode the frame rate
        declared to mpv depends on how many stages there are and is fixed when
        the process spawns, so every stage has to be respawned at the new rate.
        Leaving the earlier ones alone is what made two and three passes
        collapse. The adaptive rate could change the speed in place, but the
        rebuild is kept for both modes: the starting rate, the governor's search
        and the output counter all belong to one chain.
        """
        n = max(1, min(MAX_PASSES, n))
        self.pending = n
        if self.closing or n == len(self.stages):
            self.update_info()
            return
        self.info.config(text="rebuilding at %d pass%s ..."
                              % (n, "" if n == 1 else "es"), fg=WARN)
        self.root.update_idletasks()
        # Every stage tweak mode applied to is about to be destroyed, and the
        # replacements are built click-through, so the flag has to come back down
        # or the lens believes it is interactive while behaving otherwise. The
        # ReShade overlay itself dies with the mpv process that was hosting it.
        self.tweak = False
        self.rebuilding = True
        self.stop_counter()
        for s in reversed(self.stages):
            self._kill_stage(s)
        self.stages = []
        self.fps = _fps_for(n)
        self.rate = self.start_rate(n) if ADAPTIVE else self.fps
        self.rate_note = ""
        self.frames, self.t_first = 0, None
        x, y = self.inner()
        try:
            self._build_first(x, y)
            for _ in range(n - 1):
                self._append_stage()
        except SystemExit:
            self.info.config(text="a stage failed to start", fg=WARN)
        if self.stages:
            self.start_counter()
            self.apply_split()
        self.rebuilding = False
        if not self.stages:
            # nothing left to show. visible() is stages[-1], so carrying on would
            # raise on the next menu action rather than here, where it is clear.
            messagebox.showerror("Neural Lens",
                                 "No stage could be started, so the lens has to close.\n"
                                 "The most recent logs are in:\n%s" % LOGDIR)
            self.quit()
            return
        self.raise_chrome()
        self.aim()
        self.update_info()
        if save:
            self.save_state()

    def add_pass(self, save=True):
        self.set_passes(len(self.stages) + 1, save)

    def drop_pass(self, save=True):
        self.set_passes(len(self.stages) - 1, save)

    # ---- geometry
    def inner(self):
        if self.fullscreen:
            return self.t.winfo_x(), self.t.winfo_y()
        return self.t.winfo_x() + EDGE, self.t.winfo_y() + BAR

    def aim(self):
        x, y = self.inner()
        r = w.RECT(x, y, x + self.cw, y + self.ch)
        mag.MagSetWindowSource(self.hmag, r)

    def place(self):
        x, y = self.inner()
        flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        u.SetWindowPos(self.host, 0, x, y, 0, 0, flags)
        for s in self.stages:
            u.SetWindowPos(s["hwnd"], 0, x, y, 0, 0, flags)
        self.place_divider()

    def start_pump(self):
        """Drive magnifier repaints from a precisely paced thread.

        tkinter's after() has coarse granularity and event loop overhead, so an
        after(16) tick actually lands nearer 20 ms, which capped the lens at
        47 to 52 fps. This paces at PUMP_HZ, which comes from the display's own
        refresh rate. The magnifier was never the limit: it matches an ordinary
        window and is indifferent to how large the magnified region is.

        InvalidateRect from another thread just posts WM_PAINT; tkinter's mainloop
        dispatches it, because the host window belongs to that thread.
        """
        def loop():
            period = 1.0 / PUMP_HZ
            nxt = time.perf_counter()
            while not self.closing:
                u.InvalidateRect(self.hmag, None, True)
                nxt += period
                d = nxt - time.perf_counter()
                if d < -0.05:
                    nxt = time.perf_counter()
                elif d > 0:
                    time.sleep(d)
        threading.Thread(target=loop, daemon=True).start()

    def update_info(self):
        n = len(self.stages)
        p = max(1, min(MAX_PASSES, self.pending))
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
        self.plus.config(fg=DIM if p >= MAX_PASSES else FG)
        self.minus.config(fg=DIM if p <= 1 else FG)

    def bump_passes(self, step):
        """Choose a pass count on the bar without rebuilding anything yet."""
        if not self.nr_on:
            return
        self.pending = max(1, min(MAX_PASSES, self.pending + step))
        self.update_info()

    def apply_passes(self):
        if self.nr_on and self.pending != len(self.stages):
            self.set_passes(self.pending)

    def stats(self):
        if self.closing:
            return
        # What the visible pass actually presented over the last few seconds,
        # which is the number a person means by fps. Its counter restarts with
        # the chain, so a step backwards starts the average over.
        now, n = time.perf_counter(), self.out_frames
        if self._shown is not None and n >= self._shown[1] and now > self._shown[0]:
            self._fps_hist.append((n - self._shown[1]) / (now - self._shown[0]))
        elif self._shown is not None and n < self._shown[1]:
            self._fps_hist.clear()
        self._shown = (now, n)
        shown = sum(self._fps_hist) / len(self._fps_hist) if self._fps_hist else None
        if self.t_first and self.frames > 30 and not self.tweak:
            size = "%d x %d" % (self.cw, self.ch)
            if self.readout == "size":
                txt = size
            elif self.readout == "detail" and ADAPTIVE:
                fps = self.frames / max(now - self.t_first, 1e-6)
                txt = "%s   %.0f in  %.0f out%s" % (size, fps, self.out_rate(), self.rate_note)
            elif shown is not None:
                txt = "%s   %.0f fps%s" % (size, shown, self.rate_note)
            else:
                txt = size
            self.info.config(text=txt, fg=DIM)
        self.root.after(1000, self.stats)

    # ---- adaptive rate
    def start_counter(self):
        """Count the frames the visible stage presents.

        Stage 1's counter says how fast frames enter the chain, and that number
        stays at the display rate while the output collapses, so it cannot be
        the signal. What the viewer sees is the visible stage's window, and a
        capture of it delivers exactly once per presented frame. The callback
        only increments, so it never throttles anything.
        """
        self.stop_counter()
        alive = {"ok": True}
        self.out_alive = alive
        self.out_frames = 0
        self.out_mads.clear()
        self._out_prev = None
        lens = self
        cap = WindowsCapture(cursor_capture=False, draw_border=False,
                             minimum_update_interval=0, window_hwnd=self.visible())

        def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
            if lens.closing or not alive["ok"]:
                control.stop()
                return
            lens.out_frames += 1
            try:
                # one pixel in sixteen, every frame: the change from the previous
                # frame is what shimmer and collapse look like, and it costs well
                # under a millisecond at this size
                sub = frame.frame_buffer[:frame.height:4, :frame.width:4, :3].astype(np.int16)
                if lens._out_prev is not None and lens._out_prev.shape == sub.shape:
                    lens.out_mads.append((time.perf_counter(),
                                          float(np.abs(sub - lens._out_prev).mean())))
                lens._out_prev = sub
                if lens.out_frames % 8 == 0:
                    lens.out_lum = float(sub.mean())
            except Exception:
                pass

        def on_closed():
            pass

        cap.event(on_frame_arrived)
        cap.event(on_closed)
        try:
            self.out_ctl = cap.start_free_threaded()
        except Exception:
            self.out_ctl = None

    def stop_counter(self):
        if self.out_alive is not None:
            self.out_alive["ok"] = False
        try:
            if self.out_ctl is not None:
                self.out_ctl.stop()
        except Exception:
            pass
        self.out_ctl = None

    @staticmethod
    def stage_rate(rate, idx):
        """What stage idx (0 based) presents when stage 1 presents at rate.

        Each stage is fed by the one before it, and a stage that consumes exactly
        what arrives shimmers: measured at two passes on the 4070, equal rates of
        35 were clean and 37 were not, and on the 5090 two stages at 60 measured
        0.225 against a floor of 0.146. So every stage after the first runs at
        five sixths of the stage feeding it, the same headroom stage 1 keeps over
        capture.
        """
        return rate * (5.0 / 6.0) ** idx

    def out_rate(self):
        """The rate the visible stage is asked to present."""
        return self.stage_rate(self.rate, len(self.stages) - 1)

    @staticmethod
    def start_rate(passes):
        """Stage 1's starting rate: the fixed rule's rate for this pass count,
        arriving at the visible stage after each later stage's headroom."""
        return min(_fps_for(1), int(round(_fps_for(passes) / (5.0 / 6.0) ** (passes - 1))))

    def apply_rate(self, new, why):
        """Set every stage's playback speed for a stage 1 rate of new fps."""
        self.rate = new
        for i, s in enumerate(list(self.stages)):
            try:
                s["ipc"].set("speed", self.stage_rate(new, i) / float(BASE_FPS))
            except Exception:
                pass
        # the console gets the measurement, the title bar a word
        word = ""
        for key, short in (("shimmer", "shimmer"), ("runaway", "collapse"),
                           ("presented", "short"), ("arriving", "input"), ("probing", "probing")):
            if key in why:
                word = short
                break
        self.rate_note = "  (%s)" % word if word else ""
        print("rate %d fps, visible %.0f, %s" % (new, self.out_rate(), why or "start"),
              flush=True)
        self.root.after(0, self.save_state)

    def start_governor(self):
        """Keep the presented rate under what the chain can actually deliver.

        The fixed rule in _fps_for was calibrated on one GPU at one size. On a
        slower card, or a larger lens, or more passes, the chain cannot present
        the rate it is asked for. mpv then presents frames that are not there yet,
        Neural Rendering re-runs over its own output, and the picture shimmers,
        then collapses. Measured on an RTX 4070 SUPER at 1400x1000, out of 255
        frame to frame on a static source: two passes at the rule's 50 presented
        40 with spikes to 3.3, three passes at 33 presented 29 with spikes, and a
        2000x1400 lens at 100 presented 27 and collapsed to a mean of 14. Every
        one of those was clean at 24.

        So the rate is governed, once a second, from four measurements:

        - the mean luminance entering stage 1 against the mean luminance the
          visible stage shows. Neural Rendering moves it by two or three percent;
          a collapse moves it by half or more, and it can do that while every
          frame is still presented on time (measured: one pass at 90 presented 90
          and sat at a mean of 250 out of 255). Two seconds of that and the rate
          halves. The output is judged against the range the input has occupied
          over the last second and a half, not its latest value, because on a
          video the two are sampled at different moments and disagree while
          nothing is wrong: that false alarm alone took a chain from 100 to 12.
        - what the visible stage presents. If that falls short of the rate by
          more than measurement noise, the chain is over capacity: the rate drops
          to two thirds of what was presented, and the next probe upward waits
          twice as long.
        - what enters stage 1. The rate is also held to five sixths of that,
          because declaring even exactly what arrives shimmers (0.220 at 5
          percent headroom against a floor of 0.146 on the 5090).
        - the frame to frame change of the output, while the source is still.
          Short of collapse, a rate just over the knee presents every frame on
          time and shimmers anyway: one pass at 78 on a loaded 4070 had 47
          percent of frames jump by more than 1.5 out of 255, at 45 none did.
          On a still source, more than 3 percent of frames jumping like that
          marks the level as failed, but only when it survives a second reading
          a second later: another process taking the GPU spikes the floor to
          1.51 and 1.77 for four seconds and then settles to 0.12 while it is
          still running. On a moving source the change is motion, so it is
          ignored, and the rate does not probe upward either, because the
          result could not be checked.

        When nothing has bitten for a while the rate probes upward, never above
        the fixed rule's rate, which is the ceiling. A probe lands halfway
        between the last rate that held and the lowest that failed, and a failed
        probe falls straight back to the rate that held, so the search closes in
        a few steps and stops once the two are within a couple of frames.

        A level that failed is recorded, but not for ever. It is questioned again
        once the chain has carried clean output for twenty seconds and the limit
        is at least half a minute old, on an interval that doubles each time the
        limit turns out to be real. So a passing load costs under a minute rather
        than the rest of the session, while a chain that genuinely cannot go
        faster is left alone for longer and longer.

        Telling contention apart from incapacity by watching the rate frames
        arrive at was tried and dropped. It holds at the pump's rate while the
        chain alone collapses, which is promising, and at one pass it separated
        the two cleanly. At four passes the lens depressed its own input enough
        to look like another process: arriving averaged 98 against a line of 114,
        no limit was ever recorded, and the rate hunted over a 19 fps range
        instead of settling.

        Changes take effect over IPC as mpv's playback speed, so the chain is
        never rebuilt for a rate change, and the best rate that actually held is
        saved with the window state so the next launch starts there.
        """
        def loop():
            hist = []
            hold = 5.0
            good = None                           # highest stage 1 rate seen to hold
            bad = None                            # lowest stage 1 rate seen to fall short
            bad_at = 0.0                          # when bad was last recorded
            retest = 30.0                         # seconds before bad is questioned
            spell = 0                             # consecutive seconds of shimmer
            clean = 0.0                           # when this rate last fell short
            chain = None                          # the search is per chain
            dark = 0                              # consecutive seconds of runaway
            settle = 1.5                          # seconds to ignore after a change
            t0 = last = clean = time.perf_counter()
            while not self.closing:
                time.sleep(1.0)
                if self.closing or not ADAPTIVE or self.rebuilding or not self.stages:
                    hist = []
                    continue
                if chain is not self.stages:
                    chain, good, bad, hold, hist = self.stages, None, None, 5.0, []
                    dark, settle = 0, 1.5
                    bad_at, retest, spell = 0.0, 30.0, 0
                    self.best_rate = 0
                    last = clean = time.perf_counter()
                now = time.perf_counter()
                if now < self.settle_until:
                    hist = []
                    continue
                if now - last < settle:
                    continue                      # the speed change is still settling
                settle = 1.5
                lin, lout = self.in_lum, self.out_lum
                # with the A/B split on, the visible stage is clipped and its
                # capture carries the clipped part as black, so neither the
                # brightness nor the frame to frame change means anything
                split = self.split is not None
                # The output lags the input by the pipeline delay plus up to a
                # few frames of sampling, so on content whose brightness moves,
                # any video with a scene change, the two describe different
                # moments and disagree while nothing is wrong. Measured: a
                # brightness-swinging scrolling source took a healthy one pass
                # chain, which had just held 100 fps pinned, from 100 to 12 in
                # 27 seconds on false runaways and held it there, which is what
                # the user's own log showed over a video. So the output is
                # judged against the range the input has occupied over the last
                # second and a half rather than its latest value. On a still
                # that range is a point and nothing changes; on a video it is
                # wide and the lag is tolerated; a real collapse still crushes
                # the output to a brightness the input never had.
                recent = [l for t, l in list(self.in_lums) if now - t <= 1.5]
                if split or lout is None or not recent:
                    runaway = False
                else:
                    lo, hi = min(recent), max(recent)
                    margin = max(12.0, 0.2 * (sum(recent) / len(recent)))
                    runaway = lout < lo - margin or lout > hi + margin
                dark = dark + 1 if runaway else 0
                rate = self.rate
                last_idx = len(self.stages) - 1
                if dark >= 2:
                    bad = rate if bad is None else min(bad, rate)
                    bad_at = now
                    hold = min(hold * 2, 60.0)
                    if good is not None and good < rate:
                        new = good
                    else:
                        good = None
                        new = max(MIN_FPS, rate // 2)
                    self.apply_rate(new, "t=%.0fs runaway, showing %.0f for %.0f"
                                    % (now - t0, lout, lin))
                    last = clean = time.perf_counter()
                    hist, dark, spell = [], 0, 0
                    settle = 6.0                  # a collapse takes seconds to clear
                    continue
                hist.append((now, self.out_frames, self.frames))
                hist = [h for h in hist if now - h[0] <= 3.2]
                if len(hist) < 4:
                    continue                      # three full seconds of samples
                dt = now - hist[0][0]
                presented = (self.out_frames - hist[0][1]) / dt
                arriving = (self.frames - hist[0][2]) / dt
                target = self.out_rate()
                cap = _fps_for(1)
                if arriving > 0:
                    cap = min(cap, int(arriving * 5 // 6))
                if bad is not None:
                    cap = min(cap, bad - 1)
                still = not split and self.in_mad is not None and self.in_mad < 0.5
                spiky = False
                if still:
                    try:
                        mads = [m for t, m in list(self.out_mads) if now - t <= dt]
                    except Exception:
                        mads = []
                    if len(mads) >= 20:
                        # two shapes of shimmer: a few frames jumping well above
                        # the rest, or every frame changing when the source does
                        # not. Clean floors on still content measured 0.15 to
                        # 0.95 on this source set; a floor above 1.5 is shimmer.
                        floor = float(np.median(mads))
                        # How much a frame may differ from the one before it
                        # scales with the time between them: at 12 fps they sit
                        # 83 ms apart, at 90 fps only 11, and ordinary drift over
                        # the longer gap is not shimmer. Judging it against a
                        # fixed 1.5 made this fire more readily the lower the
                        # rate already was, which is backwards, and trapped a
                        # user's lens at 12 on a chain that went on to hold 90.
                        # The 1.5 was measured at 78 fps, so it is carried as a
                        # change per second of gap and is unchanged at that point.
                        gap = 1.0 / max(presented, 1.0)
                        limit = max(1.5 * gap * 78.0, 3.0 * floor)
                        jumps = sum(1 for m in mads if m > limit)
                        # the calibration was 47 percent of frames jumping while
                        # the picture was genuinely breaking and none at all when
                        # it was clean, so a quarter sits well inside that margin.
                        # Three percent sat close enough to nothing that ordinary
                        # content crossed it: 9 frames out of 275 was enough.
                        spiky = (jumps >= 3 and jumps > 0.25 * len(mads)) or floor > 1.5
                # The floor jumps for a few seconds when another process takes the
                # GPU, then settles while that load is still running: measured 1.51
                # and 1.77 at the onset, then 0.12 to 0.46 for the thirty seconds
                # after. One sample is an event, not a level, so shimmer has to
                # survive a second look before it costs anything.
                spell = spell + 1 if spiky else 0
                spiky = spell >= 2
                new, why = rate, ""
                deficit = target - presented
                # Presenting 87 of 90 is not a failure. Three percent was tight
                # enough that near perfect delivery dropped a user's lens from 90
                # to 58, and neither mpv's pacing nor a three second count is
                # that exact.
                if deficit > max(0.08 * target, 1.5) or spiky:
                    clean = now
                    bad = rate if bad is None else min(bad, rate)
                    # the interval keeps doubling across failures rather than
                    # resetting, or a chain that genuinely cannot go faster would
                    # probe and wobble once a minute for ever
                    bad_at = now
                    hold = min(hold * 2, 60.0)
                    if good is not None and good < rate:
                        new = good                # a probe that failed: back to what held
                    elif spiky:
                        good = None
                        new = max(MIN_FPS, int(rate * 5 // 6))
                    else:
                        good = None               # what held no longer does
                        # A mild shortfall means the chain is a little over
                        # capacity, and what it just presented is by definition
                        # achievable, so back off to just under that rather than
                        # to two thirds. Two thirds is kept for a severe one,
                        # where the presented figure is not to be trusted either.
                        share = 2.0 / 3.0 if deficit > 0.25 * target else 0.95
                        new = int(presented * share / self.stage_rate(1.0, last_idx))
                        new = max(MIN_FPS, min(new, rate - 1))
                    why = ("shimmer, %d of %d frames jumped, floor %.2f"
                           % (jumps, len(mads), floor) if spiky
                           else "presented %.0f, asked %.0f" % (presented, target))
                else:
                    # A level that has carried clean output for a while is evidence
                    # the chain can hold it, and makes an older bad worth doubting.
                    # A bad that was really a passing load clears for good; a real
                    # ceiling costs one failed probe and is then left alone for
                    # twice as long, so the cost of asking falls away over time.
                    if (bad is not None and now - clean >= 20.0
                            and now - bad_at >= retest):
                        bad, bad_at = None, now
                        retest = min(retest * 2, 600.0)
                        # an expiry is a deliberate decision to re-test, so the
                        # wait between probes drops sharply rather than creeping
                        # down, or the decision is spent waiting to act on it
                        hold = max(5.0, hold / 4)
                        cap = _fps_for(1)
                        if arriving > 0:
                            cap = min(cap, int(arriving * 5 // 6))
                    # Returning to a level this chain has already held needs no
                    # verification and no still source, because it is known to
                    # work. That matters most over a video: probing requires a
                    # still source, so without this one false knock down leaves
                    # the rate on the floor for the whole film. So proven ground
                    # is retaken in a few halving steps two seconds apart, moving
                    # content included, where creeping back at plus two every
                    # fifteen seconds cost four minutes of a user's session.
                    # Climbing above anything it has held is the cautious case
                    # and still waits for a still source and a full hold period.
                    known = self.best_rate - 2 > rate
                    wait = 2.0 if known else hold
                    if rate > cap + 2:
                        new = max(MIN_FPS, cap)
                        why = "arriving %.0f" % arriving
                    elif (known or still) and now - last >= wait:
                        # Shimmer near the knee can take fifteen seconds to show,
                        # so a level only counts as held once a whole hold period
                        # has passed at it, which is now. It is recorded even when
                        # there is no headroom left to probe into, or the rate the
                        # lens actually settles at is never the one written to the
                        # state file: two runs that both held 99 for well over two
                        # minutes saved 97 and 91.
                        good = rate
                        self.best_rate = max(self.best_rate, rate)
                        if rate < cap - 1:
                            if known:
                                # halfway back to the proven level each time,
                                # and never more than half again in one go
                                step = max(2, (self.best_rate - rate + 1) // 2)
                                step = min(step, max(4, rate // 2))
                            else:
                                step = ((bad - rate) // 2 if bad is not None
                                        else max(2, rate // 8))
                                step = min(step, max(2, rate // 4))  # a big jump collapses
                            # The convergence guard belongs to the search between
                            # what held and what failed. Retaking proven ground is
                            # not a search, and within a few frames of the target
                            # the halving step falls under the guard, which would
                            # park the lens just short of its own best rate for
                            # ever: from 12 with 90 proven it stopped dead at 87.
                            if known or step >= max(1, rate // 20):
                                new = min(cap, rate + step)
                                why = "probing"
                if new != rate:
                    self.apply_rate(new, "t=%.0fs %s" % (now - t0, why))
                    last = clean = time.perf_counter()
                    hist, spell = [], 0

        def guarded():
            # This runs on a daemon thread, so an exception would kill it silently
            # and the rate would simply stop moving, which looks exactly like a
            # chain that has settled. The rate holds at its last working value,
            # which is safe, but say what happened rather than leaving it to be
            # inferred from a number that never changes again.
            try:
                loop()
            except Exception as exc:
                print("rate governor stopped: %r, rate held at %d"
                      % (exc, self.rate), flush=True)

        threading.Thread(target=guarded, daemon=True).start()

    def save_state(self):
        x, y = self.inner()
        # The rate worth remembering is the best one this chain actually held, not
        # whatever it happens to sit at now. Saving the instantaneous rate meant a
        # lens closed while something else had the GPU reopened at the depressed
        # rate and had to climb back from there.
        keep = self.best_rate if self.best_rate else self.rate
        try:
            if self.fullscreen:
                # the windowed geometry stays untouched for the way back
                with open(FULL_STATE, "w") as f:
                    f.write("%d %d\n" % (len(self.stages), keep))
                return
            with open(STATE, "w") as f:
                f.write("%d %d %d %d %d %d\n" % (self.cw, self.ch, x, y, len(self.stages),
                                                keep))
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
            self.save_state()

    # ---- menu / tweak mode
    # The ReShade overlay lives INSIDE mpv's swapchain, so it cannot be moved to
    # a separate window. Tweak mode makes the viewport interactive (drops
    # WS_EX_TRANSPARENT / WS_EX_NOACTIVATE), focuses it and presses Home so the
    # overlay opens in place; leaving tweak mode presses Home again and restores
    # click-through. mpv's input.conf has "HOME ignore", so the key reaches
    # ReShade rather than mpv. With several passes the overlay belongs to the
    # visible stage, while F6 and F5 are sent to every stage in turn.
    def menu(self, e):
        m = tk.Menu(self.t, tearoff=0)
        # a bug report is much easier to act on when the reporter can read the
        # version off the app rather than having to work out which build they have
        m.add_command(label="Neural Lens %s  (beta)" % __version__, state="disabled")
        m.add_separator()
        m.add_command(label=("Done tweaking  (back to click-through)" if self.tweak
                             else "Tweak NR settings  (ReShade overlay, Home)"),
                      command=self.toggle_tweak)
        m.add_command(label=("Turn NR back on   (F6, all passes)" if not self.nr_on
                             else "Turn NR off   (F6, all passes)"),
                      command=self.toggle_nr)
        m.add_separator()
        off = "disabled" if not self.nr_on else "normal"
        m.add_command(label="Add a pass now", command=self.add_pass, state=off)
        m.add_command(label="Remove a pass now", command=self.drop_pass, state=off)
        m.add_separator()
        m.add_command(label="Save before and after      (both images, plus a join)",
                      command=self.take_screenshot)
        m.add_command(label="Save the result only       (F5, ReShade's own)",
                      command=lambda: self.send_key(0x74))
        m.add_command(label="Open screenshot folder", command=self.open_shots)
        m.add_separator()
        m.add_command(label=("End the A/B split" if self.split is not None
                             else "Live A/B split      (neural left, raw right)"),
                      command=self.toggle_split)
        m.add_separator()
        m.add_command(label="Resize the lens...", command=self.resize_dialog,
                      state="disabled" if self.fullscreen else "normal")
        m.add_command(label="Settings...", command=self.settings_dialog)
        m.add_separator()
        m.add_command(label="Close", command=self.quit)
        m.tk_popup(self.t.winfo_x() + 6, self.t.winfo_y() + BAR)

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
        """Deliver one key press straight to a stage's message queue.

        ReShade reads its hotkeys from the window's own messages, so a posted
        WM_KEYDOWN and WM_KEYUP reach it whether or not the window has focus.
        But it only notices a press when it polls, once per presented frame,
        and a stage presents anywhere from 12 to 100 frames a second. A key that
        goes down and up inside one frame is never seen. The earlier approach,
        focusing the window and synthesising a 30 ms press, dropped presses for
        exactly that reason, more often with more passes, which left the overlay
        and the lens's idea of it out of step: Done tweaking would not close it,
        and the next Tweak would not open it. So the key is held for a quarter
        of a second, longer than the slowest frame, before it is released.
        """
        scan = u.MapVirtualKeyW(vk, 0)
        ext = 0x1000000 if vk in (0x24, 0x21, 0x22, 0x23, 0x2D, 0x2E) else 0
        lp = (scan << 16) | 1 | ext
        u.PostMessageW(hwnd, 0x100, vk, lp)
        self.root.after(KEY_HOLD, lambda: u.PostMessageW(hwnd, 0x101, vk, lp | 0xC0000000))

    def toggle_tweak(self):
        h = self.visible()
        self.tweak = not self.tweak
        if self.tweak:
            # interactive first, so the overlay that opens can be used with the
            # mouse; the key itself does not need the focus
            self.set_interactive(h, True)
            self.info.config(text="TWEAK MODE: Home hides/shows the ReShade menu", fg=WARN)
            self.post_key(h, 0x24)
            self.root.after(150, lambda: self.focus(h))
        else:
            # the key first, and the window made click-through only after it
            # has been released: taking the styles back drops the focus, and
            # ReShade forgets every key it is holding when that happens
            self.post_key(h, 0x24)
            self.root.after(KEY_HOLD + 200, lambda: self.set_interactive(h, False))
            self.info.config(text="%d x %d" % (self.cw, self.ch), fg=DIM)

    def send_key(self, vk, idx=0):
        """Every stage gets the key, so a toggle applies to every pass."""
        if self.closing:
            return
        for s in list(self.stages):
            self.post_key(s["hwnd"], vk)

    # ---- Neural Rendering on or off
    # The add-on reads its F6 from the physical keyboard, through
    # GetAsyncKeyState, not from window messages. Measured with a still image
    # under the lens and the in-to-out difference as the witness: F6 posted to
    # the stage did nothing in three runs, with or without focus, while one
    # real keystroke with no focus at all took it from 1.20 to 2.22. So F6
    # anywhere on the system toggles Neural Rendering in every stage, and the
    # lens watches the same key the same way to keep its own idea in step.
    def watch_f6(self):
        def loop():
            down = False
            while not self.closing:
                now = bool(u.GetAsyncKeyState(0x75) & 0x8000)
                if now and not down:
                    self.root.after(0, self._nr_toggled)
                down = now
                time.sleep(0.05)      # a human press lasts longer than this

        threading.Thread(target=loop, daemon=True).start()

    def _nr_toggled(self):
        if self.closing:
            return
        self.nr_on = not self.nr_on
        print("Neural Rendering %s" % ("on" if self.nr_on else "off"), flush=True)
        self.update_info()

    def press_key(self, vk):
        """A genuine keystroke, since that is what the add-on reads.

        Unlike a posted message it reaches the whole system, so the stage takes
        the focus for the press and hands it back afterwards; without that the
        key also lands in whatever is under the lens, and F6 in a browser moves
        the cursor to the address bar. The key is held longer than the slowest
        frame, and the click-through styles come back only after it is released:
        dropping the focus makes ReShade forget every key it is holding.
        """
        if self.closing or not self.stages:
            return
        h = self.visible()
        prev = u.GetForegroundWindow()
        self.set_interactive(h, True)
        self.focus(h)

        def back():
            if not self.tweak:
                self.set_interactive(h, False)
            if prev and prev != h:
                try:
                    me = k32.GetCurrentThreadId()
                    tid = u.GetWindowThreadProcessId(prev, None)
                    u.AttachThreadInput(me, tid, True)
                    u.SetForegroundWindow(prev)
                    u.AttachThreadInput(me, tid, False)
                except Exception:
                    pass

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
    # The lens cannot resize in place: that recreates mpv's swapchain, which makes
    # the NR add-on release its DLSS feature and crash. So drag a ghost to the size
    # you want, confirm, and the lens restarts itself at that size.
    def confirm(self, title, text):
        """A yes or no dialog that stays above the lens.

        tkinter's messagebox is not topmost and every stage window is, so the
        stock dialog is drawn underneath the lens and half the question cannot be
        read. This also places itself clear of the lens rather than over it.
        """
        t = tk.Toplevel(self.root)
        t.title(title)
        t.configure(bg=BG)
        t.resizable(False, False)
        t.attributes("-topmost", True)
        out = {"v": False}
        tk.Label(t, text=text, bg=BG, fg=FG, justify="left", wraplength=430,
                 font=("Segoe UI", 10)).pack(padx=18, pady=(16, 12))
        row = tk.Frame(t, bg=BG)
        row.pack(padx=18, pady=(0, 14), anchor="e")

        def done(v):
            out["v"] = v
            try:
                t.grab_release()
            except Exception:
                pass
            t.destroy()

        tk.Button(row, text="Yes", width=10, relief="flat", bg=ACCENT,
                  fg="#0b1220", command=lambda: done(True)).pack(side="left",
                                                                 padx=(0, 10))
        tk.Button(row, text="No", width=10, relief="flat", bg="#334155", fg=FG,
                  command=lambda: done(False)).pack(side="left")
        t.bind("<Escape>", lambda e: done(False))
        t.bind("<Return>", lambda e: done(True))
        t.protocol("WM_DELETE_WINDOW", lambda: done(False))
        t.update_idletasks()

        # Sit below the lens if there is room, otherwise above it, otherwise in
        # the middle of the screen. Anywhere but underneath the thing it is
        # asking about.
        dw, dh = t.winfo_width(), t.winfo_height()
        lx, ly = self.inner()
        sw, sh = t.winfo_screenwidth(), t.winfo_screenheight()
        x = min(max(0, lx + (self.cw - dw) // 2), max(0, sw - dw))
        if ly + self.ch + 12 + dh <= sh:
            y = ly + self.ch + 12
        elif ly - 12 - dh >= 0:
            y = ly - 12 - dh
        else:
            x, y = max(0, (sw - dw) // 2), max(0, (sh - dh) // 2)
        t.geometry("+%d+%d" % (x, y))
        t.grab_set()
        t.focus_force()
        self.root.wait_window(t)
        return out["v"]

    def resize_dialog(self):
        if self.closing:
            return
        x, y = self.inner()
        t = tk.Toplevel(self.root)
        t.title("Resize the lens: drag the edges, then let go")
        t.geometry("%dx%d+%d+%d" % (self.cw, self.ch, x, y))
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.55)
        t.configure(bg="#101820")
        c = tk.Canvas(t, highlightthickness=0, bg="#101820")
        c.pack(fill="both", expand=True)
        st = {"after": None, "done": False, "start": (self.cw, self.ch)}

        def draw():
            wd, ht = t.winfo_width(), t.winfo_height()
            c.delete("all")
            c.create_rectangle(3, 3, wd - 3, ht - 3, outline=ACCENT, width=6)
            c.create_text(wd // 2, ht // 2 - 26, text="%d x %d" % (wd, ht),
                          fill=ACCENT, font=("Consolas", 34, "bold"))
            c.create_text(wd // 2, ht // 2 + 24,
                          text=("drag any edge, then let go"
                                if (wd, ht) == st["start"] else "let go to confirm"),
                          fill=FG, font=("Segoe UI", 14))
            c.create_text(wd // 2, ht // 2 + 54, text="Esc to cancel",
                          fill=DIM, font=("Segoe UI", 11))

        def settled():
            if st["done"]:
                return
            wd, ht = t.winfo_width(), t.winfo_height()
            if (wd, ht) == st["start"]:
                return
            # Pausing in the middle of a drag looks exactly like finishing one, so
            # never confirm while the button is still held. Tk cannot see these
            # events during a window manager resize, because the window manager
            # holds the mouse capture for the duration, so ask Windows directly.
            if u.GetAsyncKeyState(0x01) & 0x8000:      # 0x01 is VK_LBUTTON
                st["after"] = self.root.after(120, settled)
                return
            st["done"] = True
            # rootx/rooty, not x/y: save_state stores the viewport origin
            nx, ny = t.winfo_rootx(), t.winfo_rooty()
            t.attributes("-topmost", False)
            t.withdraw()
            if self.confirm(
                    "Resize the lens",
                    "Resize to %d x %d ?\n\n"
                    "The lens has to restart. Resizing in place recreates mpv's "
                    "swapchain, which makes the Neural Rendering add-on release "
                    "its DLSS feature and crash, so restarting is the safe way.\n\n"
                    "It reopens at the new size with the same number of passes."
                    % (wd, ht)):
                try:
                    with open(STATE, "w") as f:
                        f.write("%d %d %d %d %d\n" % (wd - wd % 2, ht - ht % 2,
                                                      nx, ny, len(self.stages)))
                except OSError:
                    pass
                t.destroy()
                self.quit(restart=True)
            else:
                t.destroy()

        def on_conf(e):
            if st["done"] or e.widget is not t:
                return
            draw()
            if st["after"]:
                self.root.after_cancel(st["after"])
            st["after"] = self.root.after(450, settled)

        def align():
            # geometry() places the decorated frame, but the client area is the
            # part that has to sit on the viewport. The decoration thickness is
            # only knowable once the window manager has mapped the window, so
            # this runs after that rather than immediately.
            try:
                dx = t.winfo_rootx() - t.winfo_x()
                dy = t.winfo_rooty() - t.winfo_y()
            except tk.TclError:
                return
            if (dx, dy) != (0, 0):
                t.geometry("%dx%d+%d+%d" % (self.cw, self.ch, x - dx, y - dy))
            st["start"] = (t.winfo_width(), t.winfo_height())

        t.after(150, align)
        t.bind("<Configure>", on_conf)
        t.bind("<Escape>", lambda e: t.destroy())
        draw()

    # ---- screenshots
    # ReShade's own key can only give the processed image. The lens holds the exact
    # frame it handed to mpv, so it can save a genuinely aligned before and after
    # from the same moment, plus a composite, which is the shot worth posting.
    def _capture_once(self, hwnd, timeout=2.0, skip=1):
        """One frame from a window, for screenshots and for measurement.

        The opening frame of a freshly started capture session is sometimes
        handed over uninitialised and comes back black. Measured at roughly one
        sample in 14, and since the before and after screenshot takes its "after"
        image through here, that was a black PNG with no explanation. So skip the
        first frames and refuse a buffer that is entirely empty.
        """
        out = {"a": None, "n": 0}

        def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
            out["n"] += 1
            if out["n"] <= skip:
                return
            try:
                a = np.array(
                    frame.frame_buffer[:frame.height, :frame.width, :], copy=True)
            except Exception:
                out["a"] = False
                control.stop()
                return
            # an uninitialised buffer is all zeros; a real frame never is. Give up
            # rejecting after a few tries so a genuinely black window still returns.
            if out["n"] < skip + 6 and not a[:, :, :3].any():
                return
            out["a"] = a
            control.stop()

        def on_closed():
            pass

        cap = WindowsCapture(cursor_capture=False, draw_border=False,
                             minimum_update_interval=0, window_hwnd=hwnd)
        cap.event(on_frame_arrived)
        cap.event(on_closed)
        try:
            ctl = cap.start_free_threaded()
        except Exception:
            return None
        t0 = time.perf_counter()
        while out["a"] is None and time.perf_counter() - t0 < timeout:
            time.sleep(0.01)
        try:
            ctl.stop()
        except Exception:
            pass
        return out["a"] if isinstance(out["a"], np.ndarray) else None

    def take_screenshot(self):
        if self.closing or self.shot_busy:
            return
        self.shot_busy = True
        self.info.config(text="saving screenshot ...", fg=WARN)
        # This has to run off the mainloop. The mainloop is what dispatches
        # WM_PAINT for the magnifier host, so blocking it here would stop the
        # source repainting, window capture would stop delivering, and the frame
        # being waited for would never arrive.
        threading.Thread(target=self._shot_worker, daemon=True).start()

    def _shot_worker(self):
        text, colour = "screenshot captured nothing", WARN
        try:
            # The menu that started this has closed, but frames containing it are
            # still moving through the chain, and the visible stage lags the source
            # by the pipeline latency. Let both settle, or the saved pair shows the
            # menu that was on screen a moment ago.
            time.sleep(0.25 + 0.15 * len(self.stages))
            self.shot_ready = False
            self.shot_want = True
            t0 = time.perf_counter()
            while not self.shot_ready and time.perf_counter() - t0 < 2.0:
                time.sleep(0.005)
            before = self.shot_buf.copy() if self.shot_ready else None
            after = self._capture_once(self.visible())
            stamp = time.strftime("%Y%m%d-%H%M%S")
            saved = []
            os.makedirs(SHOT_DIR, exist_ok=True)
            base = os.path.join(SHOT_DIR, "lens-%s-%dpass" % (stamp, len(self.stages)))
            if before is not None:
                _write_png(base + "-before.png", _bgra_to_rgb(before))
                saved.append("before")
            if after is not None:
                _write_png(base + "-after.png", _bgra_to_rgb(after))
                saved.append("after")
            if before is not None and after is not None:
                hh = min(before.shape[0], after.shape[0])
                ww = min(before.shape[1], after.shape[1])
                _write_png(base + "-side-by-side.png",
                           np.hstack([_bgra_to_rgb(before[:hh, :ww]),
                                      np.full((hh, 8, 3), 90, np.uint8),
                                      _bgra_to_rgb(after[:hh, :ww])]))
                saved.append("side by side")
            if saved:
                text, colour = "saved " + ", ".join(saved), ACCENT
        except Exception as exc:
            text, colour = "screenshot failed: %s" % exc, WARN
        finally:
            self.shot_want = False
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
        default on the next machine rather than pinning this one's number.
        Settings that change how the chain is built restart the lens, the same
        way a resize does.
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
            tk.Checkbutton(t, text=text, variable=var, bg=BG, fg=FG, selectcolor="#0b1220",
                           activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).grid(row=row[0], column=0, columnspan=3,
                                                       sticky="w", padx=8, pady=(4, 0))
            row[0] += 1

        def radio(text, var, value):
            tk.Radiobutton(t, text=text, variable=var, value=value, bg=BG, fg=FG,
                           selectcolor="#0b1220", activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).grid(row=row[0], column=0, columnspan=3,
                                                       sticky="w", padx=8, pady=(2, 0))
            row[0] += 1

        def slider(text, var, lo, hi):
            tk.Label(t, text=text, bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
                row=row[0], column=0, sticky="w", padx=12, pady=(4, 0))
            tk.Scale(t, from_=lo, to=hi, orient="horizontal", variable=var, length=300,
                     bg=BG, fg=FG, troughcolor="#0b1220", highlightthickness=0,
                     activebackground=ACCENT, font=("Consolas", 9)).grid(
                row=row[0], column=1, columnspan=2, sticky="w", padx=(6, 12))
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

        # ---- fullscreen
        section("Fullscreen (experimental)")
        full = tk.BooleanVar(value=self.fullscreen)
        switch("Cover the whole monitor the lens is on", full)
        explain("Experimental, and the least tested part of the lens: try it rather than rely "
                "on it, and please report what happens. Changing it restarts the lens. "
                "Windowed, it comes back at its last position and size; fullscreen, the title "
                "bar sits over the top edge of the picture and the lens cannot be dragged. A "
                "whole monitor is many times the pixels of a window, so expect a much lower "
                "frame rate.")

        # ---- frame rate
        section("Frame rate")
        adaptive = tk.BooleanVar(value=ADAPTIVE)
        switch("Adjust the frame rate automatically (recommended)", adaptive)
        explain("The lens watches what it actually shows and lowers the rate whenever the "
                "picture falls behind, runs away in brightness or shimmers, then probes back "
                "up while the content under it is still. Switched off, it asks for a fixed "
                "rate instead: five sixths of the ceiling below, divided by the number of "
                "passes. Changing this restarts the lens. Right now the visible stage is "
                "asked for %.0f frames a second." % self.out_rate())
        min_fps = tk.IntVar(value=MIN_FPS)
        slider("Lowest rate it may go to", min_fps, 5, 60)
        explain("The automatic adjustment never goes below this. A very large lens on a "
                "modest GPU can need the bottom of the range. Applies straight away.")
        ceiling = tk.IntVar(value=BASE_FPS)
        slider("Frame rate ceiling", ceiling, 24, max(240, DISPLAY_HZ))
        explain("Your display reports %d Hz, which is the default. The lens never asks for "
                "more than five sixths of this. Lower it to spend less GPU on the lens. "
                "Changing it restarts the lens." % DISPLAY_HZ)
        pump = tk.IntVar(value=PUMP_HZ)
        slider("Capture refresh", pump, 24, max(240, DISPLAY_HZ))
        explain("How often the picture under the lens is captured, per second. The display's "
                "own rate is the default and there is nothing to gain above it. Changing it "
                "restarts the lens.")
        most = tk.IntVar(value=MAX_PASSES)
        slider("Most neural passes the plus button allows", most, 1, 8)
        explain("Each pass renders the previous pass again. Two is usually the sweet spot, "
                "three is visibly heavy, and every pass costs a share of the frame rate. "
                "Applies straight away.")

        # ---- title bar
        section("Title bar")
        readout = tk.StringVar(value=self.readout)
        radio("The frame rate the lens is showing", readout, "fps")
        radio("Capture rate in, and the rate asked of the visible pass", readout, "detail")
        radio("Only the size", readout, "size")
        explain("What sits beside the size on the title bar. The frame rate is what the "
                "visible pass actually presents, averaged over the last few seconds. Applies "
                "straight away.")

        # ---- folders
        section("Folders")
        mpv = tk.StringVar(value=MPV_DIR or "")
        explain("The mpv install that carries the DLSS Neural Rendering stack.")
        folder(mpv, "Where is the mpv with the neural rendering stack?")
        data = tk.StringVar(value=DATA_DIR)
        explain("Where the lens keeps its window state, remembered frame rates and archived logs.")
        folder(data, "Where should the lens keep its state and logs?")
        explain("Both take effect at the next launch. Changing either restarts the lens.")

        def save():
            global SHOT_DIR, MIN_FPS, MAX_PASSES
            restart = False
            d = shots.get().strip()
            if d and d != SHOT_DIR:
                SHOT_DIR = d
                _save_ini("screenshot_dir", d)
            if bool(adaptive.get()) != ADAPTIVE:
                _save_ini("adaptive", None if adaptive.get() else "0")
                restart = True
            if int(min_fps.get()) != MIN_FPS:
                MIN_FPS = int(min_fps.get())
                _save_ini("min_fps", None if MIN_FPS == 12 else MIN_FPS)
            if int(ceiling.get()) != BASE_FPS:
                v = int(ceiling.get())
                _save_ini("fps", None if v == DISPLAY_HZ else v)
                restart = True
            if int(pump.get()) != PUMP_HZ:
                v = int(pump.get())
                _save_ini("pump_hz", None if v == DISPLAY_HZ else v)
                restart = True
            if int(most.get()) != MAX_PASSES:
                MAX_PASSES = int(most.get())
                _save_ini("max_passes", None if MAX_PASSES == 4 else MAX_PASSES)
                self.update_info()
                if len(self.stages) > MAX_PASSES:
                    self.set_passes(MAX_PASSES)
            m = mpv.get().strip()
            if m and m != (MPV_DIR or ""):
                _save_ini("mpv_dir", m)
                restart = True
            dd = data.get().strip()
            if dd and dd != DATA_DIR:
                _save_ini("data_dir", dd)
                restart = True
            want = bool(full.get())
            if want != self.fullscreen:
                _save_ini("fullscreen", "1" if want else None)
                restart = True
            r = readout.get()
            if r != self.readout:
                self.readout = r
                _save_ini("readout", None if r == "fps" else r)
            t.destroy()
            if restart:
                # the windowed geometry is what a fullscreen launch derives its
                # monitor from, and what the way back restores, so keep it current
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
        self.stop_counter()
        for s in reversed(self.stages):
            for step in (lambda s=s: s["ipc"].close(),
                         lambda s=s: s["ctl"].stop(),
                         lambda s=s: s["proc"].stdin.close(),
                         lambda s=s: (s["proc"].terminate(), s["proc"].wait(timeout=3))):
                try:
                    step()
                except Exception:
                    pass
            try:
                if s["proc"].poll() is None:
                    s["proc"].kill()
            except Exception:
                pass
        try:
            mag.MagUninitialize()
        except Exception:
            pass
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self.root.quit()


def _pause():
    """Hold the console open so a message on the way out can be read.

    stdin is not always a console. With input redirected, input() raises
    EOFError, and under pythonw it raises RuntimeError; either would bury the
    message this exists to let you read under a traceback about the attempt
    to wait for you. With no console at all there is nothing to hold open.
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


def main():
    if not MPV_DIR:
        _fatal("\n".join([
            "Could not find mpv.exe.",
            "",
            "Point the lens at your mpv install (the one carrying the DLSS 5",
            "Neural Rendering stack) in any of these ways:",
            "",
            '  Launch-LensNR.cmd --mpv-dir "D:\\path\\to\\mpv"',
            "  set NEURAL_LENS_MPV_DIR=D:\\path\\to\\mpv",
            "  copy neural-lens.ini.example to neural-lens.ini and set mpv_dir",
            "  or put an 'mpv' folder beside neural_lens.py",
        ]))
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as exc:
        # data_dir is taken from the ini or the environment verbatim and is the
        # one setting nothing validates, so a path on a drive that does not
        # exist used to arrive here as a raw traceback
        _fatal("\n".join([
            "Could not use the folder the lens keeps its state in:",
            "",
            "  %s" % DATA_DIR,
            "",
            "  %s" % exc,
            "",
            "Set data_dir in neural-lens.ini to a folder that exists, or delete",
            "that line to use the default under LOCALAPPDATA.",
        ]))
        return
    cw, ch, x, y, passes, rate = 1400, 1000, 500, 400, 1, None
    if os.path.exists(STATE):
        try:
            v = [int(n) for n in open(STATE).read().split()]
            cw, ch, x, y = v[:4]
            if len(v) > 4:
                passes = v[4]
            if len(v) > 5:
                rate = v[5]
        except Exception:
            pass
    if FULLSCREEN:
        # the monitor the windowed lens sits on, whole. Pass count and best held
        # rate come from the fullscreen chain's own file, since a rate that
        # suits a 1400x1000 lens is far too high for a whole monitor.
        x, y, cw, ch = monitor_rect(x + cw // 2, y + ch // 2)
        # two pixels short of the monitor: a borderless window that covers a
        # monitor exactly is taken over by the compositor's fullscreen path,
        # and the title bar on top of it stops being drawn
        ch -= 2
        rate = None
        if os.path.exists(FULL_STATE):
            try:
                v = [int(n) for n in open(FULL_STATE).read().split()]
                passes = v[0]
                if len(v) > 1:
                    rate = v[1]
            except Exception:
                pass
    cw -= cw % 2
    ch -= ch % 2
    passes = max(1, min(MAX_PASSES, passes))
    archive_logs()
    root = tk.Tk()
    root.withdraw()
    missing = _missing_stack()
    if missing:
        # This has to run before the first stage exists. Stage windows are
        # topmost and a stock messagebox is not, so once the chain is up this
        # dialog would be drawn underneath the lens: see Lens.confirm.
        note = "\n".join(
            ["Neural Rendering will probably not run.",
             "",
             "These are not in the mpv folder:",
             "  %s" % MPV_DIR,
             ""]
            + ["  %s   (%s)" % (n, d) for n, d in missing]
            + ["",
               "The lens will still open, but it will most likely show the screen",
               "back to you unchanged. The README says what the mpv install needs",
               "to carry; none of it is included here."])
        print("\n" + note + "\n", flush=True)
        messagebox.showwarning("Neural Lens", note)
    try:
        lens = Lens(root, x, y, cw, ch, passes, rate, FULLSCREEN)
    except SystemExit as exc:
        # a stage that never opened its window. Under pythonw the message
        # would go to the log and the lens would simply fail to appear.
        _fatal(str(exc))
        return
    lens.show_in_taskbar()
    print("Neural Lens %s (beta)" % __version__, flush=True)
    print("lens ready %dx%d at (%d,%d), %d pass%s%s"
          % (cw, ch, x, y, len(lens.stages), "" if len(lens.stages) == 1 else "es",
             ", fullscreen" if FULLSCREEN else ""),
          flush=True)

    def watch():
        # the stage list is empty for a moment during a rebuild, and reading
        # stages[0] then used to kill this thread, after which a dead stage
        # went unnoticed for the rest of the session
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
        # Resizing has to go through a restart, so hand the process over to a
        # fresh copy of itself once every mpv child is really gone.
        #
        # Not os.execv. On Windows that goes through the CRT, which does not quote
        # arguments containing spaces, so a script path such as
        # "...\\Coding\\DLSS 5\\neural-lens\\neural_lens.py" reaches the replacement
        # process split at the space. It does not raise either: it starts something
        # broken while this process is already gone, so the lens never comes back
        # and nothing is reported. subprocess quotes correctly through list2cmdline.
        try:
            root.destroy()
        except Exception:
            pass
        time.sleep(1.0)
        cmd = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
        note = os.path.join(LOGDIR, "restart.log")
        try:
            # the new size lives in the state file; lens.cw and lens.ch are the old one
            v = [int(n) for n in open(STATE).read().split()]
            print("restarting at %d x %d" % (v[0], v[1]), flush=True)
        except Exception:
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
            print("start it again yourself, the new size is already saved", flush=True)
            return
        # A restart that fails should say so rather than vanishing without a word.
        time.sleep(3.0)
        if child.poll() is not None:
            print("the restart exited straight away (code %s)" % child.poll(), flush=True)
            print("what it printed is in %s" % note, flush=True)
            print("start it again yourself, the new size is already saved", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # under pythonw a traceback goes to lens.log and the lens simply never
        # appears, which is the silence the log and the dialogs exist to end
        import traceback
        _fatal("The lens stopped with an error.\n\n" + traceback.format_exc())
        sys.exit(1)
