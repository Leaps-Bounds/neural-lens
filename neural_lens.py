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
import ctypes
import ctypes.wintypes as w
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
TITLE = "LensNR"

DATA_DIR = (os.environ.get("NEURAL_LENS_DATA") or _INI.get("data_dir")
            or os.path.join(os.environ.get("LOCALAPPDATA") or _script_dir(), "NeuralLens"))
STATE = os.path.join(DATA_DIR, "lens-state.txt")
LOGDIR = os.path.join(DATA_DIR, "logs")
SHOT_DIR = (os.environ.get("NEURAL_LENS_SHOTS") or _INI.get("screenshot_dir")
            or os.path.join(DATA_DIR, "screenshots"))

try:
    MAX_PASSES = max(1, min(8, int(_INI.get("max_passes", 4))))
except ValueError:
    MAX_PASSES = 4

BAR, EDGE = 34, 2
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


def _fps_for(stages):
    """The rate declared to mpv, which must never exceed what the chain delivers.

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

    Dividing by the stage count gives 120, 60, 40, 30, each at or below every
    clean measurement. It is deliberately conservative at three stages, where 60
    is known to work, because a cliff is worse than a few lost frames.
    """
    return max(24, BASE_FPS // max(1, stages))

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
    """Write one key into neural-lens.ini beside the script, keeping the rest."""
    path = os.path.join(_script_dir(), "neural-lens.ini")
    lines, done = [], False
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                bare = line.strip()
                if bare and bare[0] not in "#;[" and "=" in bare \
                        and bare.split("=", 1)[0].strip().lower() == key:
                    lines.append("%s = %s\n" % (key, value)); done = True
                else:
                    lines.append(line)
    except OSError:
        pass
    if not done:
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
        files = sorted(os.listdir(LOGDIR))
        while len(files) > 80:
            os.remove(os.path.join(LOGDIR, files.pop(0)))
    except Exception:
        pass


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


class Lens:
    def __init__(self, root, x, y, cw, ch, passes):
        self.root, self.cw, self.ch = root, cw, ch
        self.drag = None
        self.closing = False
        self.tweak = False          # True while the viewport is interactive
        self.frames = 0
        self.t_first = None
        self.restart = False        # set by the resize flow, read by main()
        self.shot_want = False      # ask the capture thread for one source frame
        self.shot_ready = False
        self.shot_busy = False
        self.shot_buf = np.empty((ch, cw, 4), np.uint8)
        self.stages = []            # [{title, proc, hwnd, ctl}], last one is visible

        # ---- chrome (tk): title bar + subtle border + transparent hole
        t = tk.Toplevel(root)
        self.t = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=ACCENT)
        t.attributes("-transparentcolor", KEY)
        t.geometry("%dx%d+%d+%d" % (cw + EDGE * 2, ch + BAR + EDGE, x - EDGE, y - BAR))
        bar = tk.Frame(t, bg=BG, height=BAR)
        bar.place(x=EDGE, y=0, width=cw, height=BAR)

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

        self.plus = tk.Label(bar, text=" + ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.plus.pack(side="right")
        self.plus.bind("<Button-1>", lambda e: self.add_pass())
        self.pass_lbl = tk.Label(bar, text="1 pass", bg=BG, fg=ACCENT, font=("Consolas", 9))
        self.pass_lbl.pack(side="right", padx=2)
        self.minus = tk.Label(bar, text=" \u2212 ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.minus.pack(side="right")
        self.minus.bind("<Button-1>", lambda e: self.drop_pass())
        for b in (self.plus, self.minus):
            b.bind("<Enter>", lambda e, b=b: b.config(bg="#334155"))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=BG))

        tk.Frame(t, bg=KEY).place(x=EDGE, y=BAR, width=cw, height=ch)
        nodrag = (self.x_btn, self.menu_btn, self.plus, self.minus)
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
        self._build_first(x, y)
        self.raise_chrome()
        self.aim()

        for _ in range(max(0, passes - 1)):
            self._append_stage()
        self.update_info()

        self.start_pump()
        self.root.after(1000, self.stats)

    # ---- stage plumbing
    def spawn_mpv(self, title, x, y):
        """Start one mpv reading raw BGRA on stdin, and return (proc, hwnd)."""
        env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
        cmd = [MPV, "-",
               "--demuxer=rawvideo", "--demuxer-rawvideo-w=%d" % self.cw,
               "--demuxer-rawvideo-h=%d" % self.ch, "--demuxer-rawvideo-mp-format=bgra",
               "--demuxer-rawvideo-fps=%d" % self.fps,
               "--geometry=%dx%d+%d+%d" % (self.cw, self.ch, x, y),
               "--hidpi-window-scale=no", "--no-border", "--no-osc",
               "--no-window-dragging", "--ontop", "--force-window=immediate",
               "--keep-open=yes", "--cache=no",
               "--demuxer-max-bytes=%d" % (self.cw * self.ch * 4 * 8),
               "--title=%s" % title]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, cwd=MPV_DIR, env=env)
        hwnd = None
        for _ in range(140):
            hwnd = find_mpv(title)
            if hwnd:
                break
            time.sleep(0.25)
        if not hwnd:
            try:
                proc.kill()
            except Exception:
                pass
            raise SystemExit("mpv window %r never appeared" % title)
        st = u.GetWindowLongPtrW(hwnd, GWL_STYLE)
        u.SetWindowLongPtrW(hwnd, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
        self.set_interactive(hwnd, False)
        u.SetWindowPos(hwnd, HWND_TOPMOST, x, y, self.cw, self.ch, SWP_NOACTIVATE)
        return proc, hwnd

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
            except (BrokenPipeError, OSError, ValueError):
                control.stop()

        def on_closed():
            pass

        cap.event(on_frame_arrived)
        cap.event(on_closed)
        return cap.start_free_threaded()

    def refresh_filter(self):
        """The magnifier must never see any of our windows. Missing even one
        stage creates a feedback loop that collapses the image to a dark blob."""
        hs = [self.host, self.chrome] + [s["hwnd"] for s in self.stages]
        arr = (w.HWND * len(hs))(*hs)
        mag.MagSetWindowFilterList(self.hmag, MW_FILTERMODE_EXCLUDE, len(hs), arr)

    def raise_chrome(self):
        u.SetWindowPos(self.chrome, HWND_TOPMOST, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def visible(self):
        return self.stages[-1]["hwnd"]

    def _build_first(self, x, y):
        """Stage 1, fed by the magnifier host rather than by another stage."""
        alive = {"ok": True}
        proc, hwnd = self.spawn_mpv(TITLE, x, y)
        ctl = self.start_capture(self.host, proc, count=True, alive=alive)
        self.stages.append({"title": TITLE, "proc": proc, "hwnd": hwnd,
                            "ctl": ctl, "alive": alive})
        self.refresh_filter()

    def _append_stage(self):
        """One more mpv on the end, neural rendering the stage before it."""
        x, y = self.inner()
        n = len(self.stages) + 1
        title = "%sp%d" % (TITLE, n)
        alive = {"ok": True}
        proc, hwnd = self.spawn_mpv(title, x, y)
        ctl = self.start_capture(self.stages[-1]["hwnd"], proc, alive=alive)
        self.stages.append({"title": title, "proc": proc, "hwnd": hwnd,
                            "ctl": ctl, "alive": alive})
        self.refresh_filter()

    def _kill_stage(self, s):
        s.get("alive", {})["ok"] = False
        for step in (lambda: s["ctl"].stop(),
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

        Appending a single stage is not enough. The frame rate declared to mpv
        depends on how many stages there are and is fixed when the process
        spawns, so every stage has to be respawned at the new rate. Leaving the
        earlier ones alone is what made two and three passes collapse.
        """
        n = max(1, min(MAX_PASSES, n))
        if self.closing or n == len(self.stages):
            return
        self.info.config(text="rebuilding at %d pass%s ..."
                              % (n, "" if n == 1 else "es"), fg=WARN)
        self.root.update_idletasks()
        # Every stage tweak mode applied to is about to be destroyed, and the
        # replacements are built click-through, so the flag has to come back down
        # or the lens believes it is interactive while behaving otherwise. The
        # ReShade overlay itself dies with the mpv process that was hosting it.
        self.tweak = False
        for s in reversed(self.stages):
            self._kill_stage(s)
        self.stages = []
        self.fps = _fps_for(n)
        self.frames, self.t_first = 0, None
        x, y = self.inner()
        try:
            self._build_first(x, y)
            for _ in range(n - 1):
                self._append_stage()
        except SystemExit:
            self.info.config(text="a stage failed to start", fg=WARN)
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
        self.pass_lbl.config(text="%d pass%s" % (n, "" if n == 1 else "es"),
                             fg=ACCENT if n == 1 else WARN)
        self.plus.config(fg=DIM if n >= MAX_PASSES else FG)
        self.minus.config(fg=DIM if n <= 1 else FG)

    def stats(self):
        if self.closing:
            return
        if self.t_first and self.frames > 30 and not self.tweak:
            fps = self.frames / max(time.perf_counter() - self.t_first, 1e-6)
            self.info.config(text="%d x %d   %.0f fps" % (self.cw, self.ch, fps), fg=DIM)
        self.root.after(1000, self.stats)

    def save_state(self):
        x, y = self.inner()
        try:
            with open(STATE, "w") as f:
                f.write("%d %d %d %d %d\n" % (self.cw, self.ch, x, y, len(self.stages)))
        except OSError:
            pass

    # ---- drag (title bar only; a move never resizes)
    def down(self, e):
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
        m.add_command(label=("Done tweaking  (back to click-through)" if self.tweak
                             else "Tweak NR settings  (ReShade overlay, Home)"),
                      command=self.toggle_tweak)
        m.add_command(label="Toggle NR on/off   (F6, all passes)",
                      command=lambda: self.send_key(0x75))
        m.add_separator()
        m.add_command(label="Add a pass      (+)", command=self.add_pass)
        m.add_command(label="Remove a pass   (\u2212)", command=self.drop_pass)
        m.add_separator()
        m.add_command(label="Save before and after      (both images, plus a join)",
                      command=self.take_screenshot)
        m.add_command(label="Save the result only       (F5, ReShade's own)",
                      command=lambda: self.send_key(0x74))
        m.add_command(label="Open screenshot folder", command=self.open_shots)
        m.add_separator()
        m.add_command(label="Resize the lens...", command=self.resize_dialog)
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

    @staticmethod
    def press(vk):
        u.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        u.keybd_event(vk, 0, 2, 0)

    def toggle_tweak(self):
        h = self.visible()
        self.tweak = not self.tweak
        if self.tweak:
            self.set_interactive(h, True)
            self.info.config(text="TWEAK MODE: Home hides/shows the ReShade menu", fg=WARN)
            self.root.after(150, lambda: self.focus(h))
            self.root.after(320, lambda: self.press(0x24))
        else:
            self.focus(h)
            self.press(0x24)
            self.root.after(250, lambda: self.set_interactive(h, False))
            self.info.config(text="%d x %d" % (self.cw, self.ch), fg=DIM)

    def send_key(self, vk, idx=0):
        """Walk the stages one at a time so every pass gets the key."""
        if self.closing or idx >= len(self.stages):
            return
        h = self.stages[idx]["hwnd"]
        if self.tweak and idx == len(self.stages) - 1:
            self.focus(h)
            self.press(vk)
            return
        self.set_interactive(h, True)
        self.root.after(120, lambda: self.focus(h))
        self.root.after(260, lambda: self.press(vk))
        self.root.after(420, lambda: self.set_interactive(h, False))
        self.root.after(540, lambda: self.send_key(vk, idx + 1))

    # ---- resize
    # The lens cannot resize in place: that recreates mpv's swapchain, which makes
    # the NR add-on release its DLSS feature and crash. So drag a ghost to the size
    # you want, confirm, and the lens restarts itself at that size.
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
            if messagebox.askyesno(
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
        t = tk.Toplevel(self.root)
        t.title("Neural Lens settings")
        t.attributes("-topmost", True)
        t.configure(bg=BG)
        t.resizable(False, False)
        tk.Label(t, text="Where to save screenshots", bg=BG, fg=FG,
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                     sticky="w", padx=12, pady=(12, 4))
        var = tk.StringVar(value=SHOT_DIR)
        tk.Entry(t, textvariable=var, width=58, bg="#0b1220", fg=FG,
                 insertbackground=FG, relief="flat").grid(row=1, column=0, columnspan=2,
                                                          padx=(12, 6), pady=4, sticky="we")

        def browse():
            d = filedialog.askdirectory(initialdir=var.get() or DATA_DIR,
                                        title="Where should screenshots go?")
            if d:
                var.set(os.path.normpath(d))

        tk.Button(t, text="Browse", command=browse, relief="flat",
                  bg="#334155", fg=FG).grid(row=1, column=2, padx=(0, 12), pady=4)
        tk.Label(t, text="Display %d Hz. Repaints are paced at %d, and mpv is told %d,\n"
                         "which is %d divided by the %d stage(s) now running.\n"
                         "Override with fps and pump_hz in neural-lens.ini."
                         % (DISPLAY_HZ, PUMP_HZ, self.fps, BASE_FPS, len(self.stages)),
                 bg=BG, fg=DIM, justify="left",
                 font=("Segoe UI", 9)).grid(row=2, column=0, columnspan=3,
                                            sticky="w", padx=12, pady=(10, 4))

        def save():
            global SHOT_DIR
            d = var.get().strip()
            if d:
                SHOT_DIR = d
                _save_ini("screenshot_dir", d)
            t.destroy()

        tk.Button(t, text="Save", command=save, relief="flat", bg=ACCENT,
                  fg="#0b1220").grid(row=3, column=1, sticky="e", pady=(6, 12))
        tk.Button(t, text="Cancel", command=t.destroy, relief="flat",
                  bg="#334155", fg=FG).grid(row=3, column=2, sticky="w",
                                            padx=(6, 12), pady=(6, 12))

    def quit(self, restart=False):
        if self.closing:
            return
        self.restart = restart
        self.closing = True
        for s in reversed(self.stages):
            for step in (lambda s=s: s["ctl"].stop(),
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


def main():
    if not MPV_DIR:
        print("\n".join([
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
        input("\nPress Enter to close.")
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    cw, ch, x, y, passes = 1400, 1000, 500, 400, 1
    if os.path.exists(STATE):
        try:
            v = [int(n) for n in open(STATE).read().split()]
            cw, ch, x, y = v[:4]
            if len(v) > 4:
                passes = v[4]
        except Exception:
            pass
    cw -= cw % 2
    ch -= ch % 2
    passes = max(1, min(MAX_PASSES, passes))
    archive_logs()
    root = tk.Tk()
    root.withdraw()
    lens = Lens(root, x, y, cw, ch, passes)
    print("lens ready %dx%d at (%d,%d), %d pass%s"
          % (cw, ch, x, y, len(lens.stages), "" if len(lens.stages) == 1 else "es"),
          flush=True)

    def watch():
        while not lens.closing and lens.stages[0]["proc"].poll() is None:
            time.sleep(0.4)
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
    main()
