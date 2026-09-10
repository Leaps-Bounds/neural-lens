"""
DLSS 5 Neural Lens v3: a floating see-through window that neural-renders
whatever is behind it. Drag it by the title bar. The viewport is click-through,
so the mouse reaches the desktop underneath, like the Windows Magnifier lens.

How it works. Every piece below was measured before it was built:

  1. A Windows Magnification API host window sits UNDER the lens, on the exact
     same rect, with our own windows (host, chrome, mpv) on its EXCLUDE filter
     list. It asks DWM to render the true desktop content for that rect. This is
     what Windows Magnifier does; it does not capture the screen.

  2. Windows.Graphics.Capture captures that host window BY HWND. Window capture
     reads a window's own DWM buffer, so it does not matter that the lens sits
     on top of it. Verified: host fully covered by an opaque window, WGC still
     returns the source content at ~52 fps, while Desktop Duplication of the
     same rect returns the occluder. (ddagrab could never work here; Desktop
     Duplication cannot see under an occluding window, excluded or not.)

  3. Frames go straight into mpv's stdin as raw BGRA. No ffmpeg, no encode, no
     decode. mpv's existing NR stack (ReShade + dlss5-feed + renodx-dlss5) does
     the neural rendering. Verified: feature 18 attaches, 60 fps present rate.

  4. Moving the lens just moves the three windows and updates the magnifier's
     source rect every tick. Nothing restarts. RESIZING is different: it
     recreates mpv's swapchain, which forces the NR add-on to release the DLSS
     feature -> 0xC0000005. So the size is fixed per run; change it in the
     state file and relaunch.

  argv[1] state file   (W H X Y of the viewport)
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

STATE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Games\_screennr-lens-state.txt"
MPV = r"C:\Games\_mpv\mpv.exe"
MPV_DIR = r"C:\Games\_mpv"
TITLE = "LensNR"
LOGDIR = r"C:\Games\_lens-logs"

BAR, EDGE = 34, 2
KEY, BG, FG, ACCENT = "#010203", "#1b2430", "#cbd5e1", "#4ade80"
FPS = 60                     # declared to mpv; WGC delivers ~52, mpv presents on arrival

u = ctypes.windll.user32
mag = ctypes.windll.magnification
k32 = ctypes.windll.kernel32
u.SetProcessDPIAware()
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_POPUP = 0x40000000, 0x10000000, 0x80000000
WS_THICKFRAME, WS_MAXIMIZEBOX = 0x00040000, 0x00010000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x08000000
HWND_TOPMOST, HWND_NOTOPMOST = ctypes.c_void_p(-1), ctypes.c_void_p(-2)   # pointer-sized, NOT int -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
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


def find_mpv():
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
        if c.value == "mpv" and TITLE.lower() in b.value.lower():
            hits.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


class Lens:
    def __init__(self, root, x, y, cw, ch):
        self.root, self.cw, self.ch = root, cw, ch
        self.drag = None
        self.closing = False
        self.tweak = False          # True while the viewport is interactive for the ReShade overlay
        self.frames = 0
        self.t_first = None

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
        self.info = tk.Label(bar, text="%d x %d" % (cw, ch), bg=BG, fg="#64748b",
                             font=("Consolas", 9))
        self.info.pack(side="left", padx=10)
        self.x_btn = tk.Label(bar, text="  \u2715  ", bg=BG, fg=FG, font=("Segoe UI", 12))
        self.x_btn.pack(side="right")
        self.x_btn.bind("<Button-1>", lambda e: self.quit())
        self.x_btn.bind("<Enter>", lambda e: self.x_btn.config(bg="#e11d48"))
        self.x_btn.bind("<Leave>", lambda e: self.x_btn.config(bg=BG))
        tk.Frame(t, bg=KEY).place(x=EDGE, y=BAR, width=cw, height=ch)
        for wdg in (bar,) + tuple(bar.winfo_children()):
            if wdg not in (self.x_btn, self.menu_btn):
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

        # ---- mpv: raw BGRA on stdin, NR via ReShade. Spawned from its own dir.
        env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
        cmd = [MPV, "-",
               "--demuxer=rawvideo", "--demuxer-rawvideo-w=%d" % cw,
               "--demuxer-rawvideo-h=%d" % ch, "--demuxer-rawvideo-mp-format=bgra",
               "--demuxer-rawvideo-fps=%d" % FPS,
               "--geometry=%dx%d+%d+%d" % (cw, ch, x, y), "--hidpi-window-scale=no",
               "--no-border", "--no-osc", "--no-window-dragging", "--ontop",
               "--force-window=immediate", "--keep-open=yes", "--cache=no",
               "--demuxer-max-bytes=%d" % (cw * ch * 4 * 3), "--title=%s" % TITLE]
        self.mpv = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, cwd=MPV_DIR, env=env)
        self.mpv_hwnd = None
        for _ in range(120):
            self.mpv_hwnd = find_mpv()
            if self.mpv_hwnd:
                break
            time.sleep(0.25)
        if not self.mpv_hwnd:
            raise SystemExit("mpv window never appeared")
        h = self.mpv_hwnd
        st = u.GetWindowLongPtrW(h, GWL_STYLE)
        u.SetWindowLongPtrW(h, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
        ex = u.GetWindowLongPtrW(h, GWL_EXSTYLE)
        u.SetWindowLongPtrW(h, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        u.SetWindowPos(h, HWND_TOPMOST, x, y, cw, ch, SWP_NOACTIVATE)
        u.SetWindowPos(self.chrome, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        # ---- the magnifier must never see us
        arr = (w.HWND * 3)(self.host, self.chrome, h)
        mag.MagSetWindowFilterList(self.hmag, MW_FILTERMODE_EXCLUDE, 3, arr)
        self.aim()

        # ---- WGC: capture the host by HWND, push frames to mpv
        self.cap = WindowsCapture(cursor_capture=False, draw_border=False,
                                  window_hwnd=self.host)
        self.cap.event(self.on_frame_arrived)
        self.cap.event(self.on_closed)
        self.ctl = self.cap.start_free_threaded()

        self.root.after(16, self.tick)
        self.root.after(1000, self.stats)

    # ---- geometry
    def inner(self):
        return self.t.winfo_x() + EDGE, self.t.winfo_y() + BAR

    def aim(self):
        x, y = self.inner()
        r = w.RECT(x, y, x + self.cw, y + self.ch)
        mag.MagSetWindowSource(self.hmag, r)

    def place(self):
        x, y = self.inner()
        u.SetWindowPos(self.host, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        u.SetWindowPos(self.mpv_hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def tick(self):
        if self.closing:
            return
        self.aim()
        u.InvalidateRect(self.hmag, None, True)
        self.root.after(16, self.tick)

    def stats(self):
        if self.closing:
            return
        if self.t_first and self.frames > 30 and not self.tweak:
            fps = self.frames / max(time.perf_counter() - self.t_first, 1e-6)
            self.info.config(text="%d x %d   %.0f fps" % (self.cw, self.ch, fps))
        self.root.after(1000, self.stats)

    # ---- WGC callbacks (capture thread)
    def on_frame_arrived(self, frame: Frame, control: InternalCaptureControl):
        if self.closing:
            return
        try:
            b = frame.frame_buffer[:frame.height, :frame.width, :]
            self.mpv.stdin.write(np.ascontiguousarray(b).tobytes())
            if self.t_first is None:
                self.t_first = time.perf_counter()
            self.frames += 1
        except (BrokenPipeError, OSError, ValueError):
            self.root.after(0, self.quit)

    def on_closed(self):
        pass

    # ---- drag (title bar only; move never resizes)
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
            x, y = self.inner()
            with open(STATE, "w") as f:
                f.write("%d %d %d %d\n" % (self.cw, self.ch, x, y))

    # ---- menu / tweak mode
    # The ReShade overlay lives INSIDE mpv's swapchain, so it cannot be moved to a
    # separate window. Tweak mode makes the viewport interactive (drops
    # WS_EX_TRANSPARENT / WS_EX_NOACTIVATE), focuses it and presses Home so the
    # overlay opens in place; leaving tweak mode presses Home again and restores
    # click-through. Single keys (F6 NR toggle, F5 screenshot) do the same dance
    # for a fraction of a second. mpv's input.conf has "HOME ignore", so the key
    # reaches ReShade, not mpv.
    def menu(self, e):
        m = tk.Menu(self.t, tearoff=0)
        m.add_command(label=("Done tweaking  (back to click-through)" if self.tweak
                             else "Tweak NR settings  (ReShade overlay, Home)"),
                      command=self.toggle_tweak)
        m.add_command(label="Toggle NR on/off   (F6)", command=lambda: self.send_key(0x75))
        m.add_command(label="NR screenshot        (F5)", command=lambda: self.send_key(0x74))
        m.add_separator()
        m.add_command(label="Why can't I resize?", command=self.resize_hint)
        m.add_separator()
        m.add_command(label="Close", command=self.quit)
        m.tk_popup(self.t.winfo_x() + 6, self.t.winfo_y() + BAR)

    def set_interactive(self, on):
        h = self.mpv_hwnd
        ex = u.GetWindowLongPtrW(h, GWL_EXSTYLE)
        ex = (ex & ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)) if on             else (ex | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        u.SetWindowLongPtrW(h, GWL_EXSTYLE, ex)
        u.SetWindowPos(h, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | 0x0020)

    def focus_mpv(self):
        me = k32.GetCurrentThreadId()
        tid = u.GetWindowThreadProcessId(self.mpv_hwnd, None)
        u.AttachThreadInput(me, tid, True)
        u.SetForegroundWindow(self.mpv_hwnd)
        u.SetFocus(self.mpv_hwnd)
        u.AttachThreadInput(me, tid, False)

    @staticmethod
    def press(vk):
        u.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        u.keybd_event(vk, 0, 2, 0)

    def toggle_tweak(self):
        self.tweak = not self.tweak
        if self.tweak:
            self.set_interactive(True)
            self.info.config(text="TWEAK MODE: Home hides/shows the ReShade menu", fg="#fbbf24")
            self.root.after(150, self.focus_mpv)
            self.root.after(320, lambda: self.press(0x24))
        else:
            self.focus_mpv()
            self.press(0x24)
            self.root.after(250, lambda: self.set_interactive(False))
            self.info.config(text="%d x %d" % (self.cw, self.ch), fg="#64748b")

    def send_key(self, vk):
        if self.tweak:
            self.focus_mpv()
            self.press(vk)
            return
        self.set_interactive(True)
        self.root.after(150, self.focus_mpv)
        self.root.after(320, lambda: self.press(vk))
        self.root.after(600, lambda: self.set_interactive(False))

    def resize_hint(self):
        messagebox.showinfo(
            "Resize",
            "The lens cannot resize while running. A resize recreates mpv's "
            "swapchain, which forces the NR add-on to release the DLSS feature "
            "and crash (0xC0000005).\n\nClose it, edit width/height on the first "
            "line of:\n%s\nand relaunch." % STATE)

    def quit(self):
        if self.closing:
            return
        self.closing = True
        try:
            self.ctl.stop()
        except Exception:
            pass
        try:
            self.mpv.stdin.close()
        except Exception:
            pass
        os.system("taskkill /F /IM mpv.exe /T >nul 2>&1")
        try:
            mag.MagUninitialize()
        except Exception:
            pass
        self.root.quit()


def main():
    cw, ch, x, y = 1400, 1000, 500, 400
    if os.path.exists(STATE):
        try:
            cw, ch, x, y = [int(v) for v in open(STATE).read().split()[:4]]
        except Exception:
            pass
    cw -= cw % 2
    ch -= ch % 2
    archive_logs()
    root = tk.Tk()
    root.withdraw()
    lens = Lens(root, x, y, cw, ch)
    print("lens ready %dx%d at (%d,%d)" % (cw, ch, x, y), flush=True)

    def watch():
        while not lens.closing and lens.mpv.poll() is None:
            time.sleep(0.4)
        root.after(0, lens.quit)

    threading.Thread(target=watch, daemon=True).start()
    root.mainloop()


main()
