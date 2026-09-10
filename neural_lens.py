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

  5. Moving the lens just moves the windows and re-aims the magnifier,
     and adding or removing a pass only spawns or kills a stage. Nothing
     restarts and nothing resizes. RESIZING is the one thing that cannot be done
     live: it recreates mpv's swapchain, which forces the NR add-on to release
     the DLSS feature and crash with 0xC0000005.

Configuration: see neural-lens.ini.example. State and logs live in
%LOCALAPPDATA%/NeuralLens by default.
"""
import ctypes
import ctypes.wintypes as w
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

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

try:
    MAX_PASSES = max(1, min(8, int(_INI.get("max_passes", 4))))
except ValueError:
    MAX_PASSES = 4

BAR, EDGE = 34, 2
KEY, BG, FG, ACCENT = "#010203", "#1b2430", "#cbd5e1", "#4ade80"
DIM, WARN = "#64748b", "#fbbf24"
FPS = 60                     # declared to mpv; WGC delivers ~52, mpv presents on arrival

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


def archive_logs():
    """Keep the PREVIOUS session's logs before mpv overwrites them. Without this,
    launching again destroys the only evidence of a failure."""
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name in ("ReShade.log", "dlss5-feed.log"):
            src = os.path.join(MPV_DIR, name)
            if os.path.exists(src) and os.path.getsize(src) > 0:
                shutil.copy2(src, os.path.join(LOGDIR, "%s-%s" % (stamp, name)))
        files = sorted(os.listdir(LOGDIR))
        while len(files) > 40:
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

        # ---- magnifier host UNDER the lens (same rect). Must NOT be a tool
        #      window, or WGC cannot find it. Not topmost: it lives below mpv.
        hInst = k32.GetModuleHandleW(None)
        self.host = u.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_NOACTIVATE, "Static", "LensMagHost", WS_POPUP,
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

        # ---- stage 1: the magnifier host feeds the first mpv
        proc, hwnd = self.spawn_mpv(TITLE, x, y)
        ctl = self.start_capture(self.host, proc, count=True)
        self.stages.append({"title": TITLE, "proc": proc, "hwnd": hwnd, "ctl": ctl})
        self.refresh_filter()
        self.raise_chrome()
        self.aim()

        for _ in range(max(0, passes - 1)):
            self.add_pass(save=False)
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
               "--demuxer-rawvideo-fps=%d" % FPS,
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

    def start_capture(self, src_hwnd, dst_proc, count=False):
        """WGC on src_hwnd, frames written to dst_proc's stdin."""
        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=src_hwnd)
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
            while not lens.closing:
                with cv:
                    while slot["ready"] is None and not lens.closing:
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
            if lens.closing:
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

    def add_pass(self, save=True):
        if self.closing or len(self.stages) >= MAX_PASSES:
            return
        x, y = self.inner()
        n = len(self.stages) + 1
        title = "%sp%d" % (TITLE, n)
        try:
            proc, hwnd = self.spawn_mpv(title, x, y)
        except SystemExit:
            return
        ctl = self.start_capture(self.stages[-1]["hwnd"], proc)
        self.stages.append({"title": title, "proc": proc, "hwnd": hwnd, "ctl": ctl})
        self.refresh_filter()
        self.raise_chrome()
        self.update_info()
        if save:
            self.save_state()

    def drop_pass(self, save=True):
        if self.closing or len(self.stages) <= 1:
            return
        s = self.stages.pop()
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
        self.refresh_filter()
        self.raise_chrome()
        self.update_info()
        if save:
            self.save_state()

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
        47 to 52 fps. A paced thread invalidating at 120 Hz reaches the display
        cadence: the magnifier itself measures 59 fps at full lens size, the same
        as capturing an ordinary window, so it was never the limit.

        InvalidateRect from another thread just posts WM_PAINT; tkinter's mainloop
        dispatches it, because the host window belongs to that thread.
        """
        def loop():
            period = 1.0 / 120.0
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
            print("FPS %.2f" % fps, flush=True)
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
        m.add_command(label="NR screenshot        (F5)", command=lambda: self.send_key(0x74))
        m.add_separator()
        m.add_command(label="Add a pass      (+)", command=self.add_pass)
        m.add_command(label="Remove a pass   (\u2212)", command=self.drop_pass)
        m.add_separator()
        m.add_command(label="Why can't I resize?", command=self.resize_hint)
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

    def resize_hint(self):
        messagebox.showinfo(
            "Resize",
            "The lens cannot resize while running. A resize recreates mpv's "
            "swapchain, which forces the NR add-on to release the DLSS feature "
            "and crash (0xC0000005). Passes can be changed live because adding "
            "one never resizes anything.\n\nTo resize: close the lens, edit the "
            "width and height on the first line of:\n%s\nand relaunch." % STATE)

    def quit(self):
        if self.closing:
            return
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


main()
