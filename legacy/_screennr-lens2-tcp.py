"""
Floating see-through DLSS 5 Neural Rendering lens (v2).

A real little app: title bar with a menu button and an X, a subtle border, and a
click-through viewport. Whatever is BEHIND it is captured, neural-rendered and
drawn inside it, and the mouse passes straight through the viewport to the
desktop underneath, like the Windows Magnifier lens.

Design notes, each one load-bearing:

  * Both the chrome and the mpv window get WDA_EXCLUDEFROMCAPTURE, so Desktop
    Duplication looks THROUGH them to the desktop below. That is what makes the
    lens see-through, and what stops it from capturing its own output.

  * The viewport is WS_EX_TRANSPARENT | WS_EX_LAYERED, so clicks pass through.
    Consequence: mpv can never take keyboard focus, so the q key cannot quit it.
    The X button is the only way out. That is why it exists.

  * Transport is TCP, not a pipe and not UDP. Re-aiming means restarting ffmpeg;
    a pipe would EOF and kill mpv, and UDP measured slower and resyncs badly
    after a restart. mpv listens, ffmpeg connects. Measured 60.4 fps and it
    survives re-aims.

  * MOVING is safe. RESIZING recreates the swapchain, which forces the NR add-on
    to release the DLSS feature -> 0xC0000005. Size changes need a restart.

  argv[1] mpv window title   argv[2] tcp url   argv[3] state file
"""
import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import threading
import time
import tkinter as tk

TITLE = sys.argv[1] if len(sys.argv) > 1 else "LensNR"
URL = sys.argv[2] if len(sys.argv) > 2 else "tcp://127.0.0.1:9744"
STATE = sys.argv[3] if len(sys.argv) > 3 else r"C:\Games\_screennr-lens-state.txt"

FF = (r"C:\Users\jx\AppData\Local\Microsoft\WinGet\Packages"
      r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
      r"\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe")

BAR = 34             # title bar height
EDGE = 2             # subtle border thickness
KEY = "#010203"      # transparent-colour key for the viewport hole
BG = "#1b2430"
FG = "#cbd5e1"
ACCENT = "#4ade80"
FPS = 60

u = ctypes.windll.user32
u.SetProcessDPIAware()
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_THICKFRAME, WS_MAXIMIZEBOX = 0x00040000, 0x00010000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010


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
    def __init__(self, root, mpv_hwnd, x, y, cw, ch):
        self.root, self.mpv, self.cw, self.ch = root, mpv_hwnd, cw, ch
        self.proc = None
        self.drag = None

        t = tk.Toplevel(root)
        self.t = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=ACCENT)
        t.attributes("-transparentcolor", KEY)
        t.geometry("%dx%d+%d+%d" % (cw + EDGE * 2, ch + BAR + EDGE,
                                    x - EDGE, y - BAR))

        bar = tk.Frame(t, bg=BG, height=BAR)
        bar.place(x=EDGE, y=0, width=cw, height=BAR)
        self.bar = bar

        self.menu_btn = tk.Label(bar, text=" \u2630 ", bg=BG, fg=FG,
                                 font=("Segoe UI", 12))
        self.menu_btn.pack(side="left", padx=(6, 0))
        self.menu_btn.bind("<Button-1>", self.menu)

        tk.Label(bar, text="  DLSS 5 Neural Lens", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.size_lbl = tk.Label(bar, text="%d x %d" % (cw, ch), bg=BG,
                                 fg="#64748b", font=("Consolas", 9))
        self.size_lbl.pack(side="left", padx=10)

        self.x_btn = tk.Label(bar, text="  \u2715  ", bg=BG, fg=FG,
                              font=("Segoe UI", 12))
        self.x_btn.pack(side="right")
        self.x_btn.bind("<Button-1>", lambda e: self.quit())
        self.x_btn.bind("<Enter>", lambda e: self.x_btn.config(bg="#e11d48"))
        self.x_btn.bind("<Leave>", lambda e: self.x_btn.config(bg=BG))

        # viewport hole: the key colour is transparent AND click-through,
        # which is exactly where the mpv output window sits.
        tk.Frame(t, bg=KEY).place(x=EDGE, y=BAR, width=cw, height=ch)

        for wdg in (bar,) + tuple(bar.winfo_children()):
            if wdg not in (self.x_btn, self.menu_btn):
                wdg.bind("<ButtonPress-1>", self.down)
                wdg.bind("<B1-Motion>", self.move)
                wdg.bind("<ButtonRelease-1>", self.up)

        t.update()
        self.hwnd = u.GetParent(t.winfo_id()) or t.winfo_id()
        u.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)

    def inner(self):
        return self.t.winfo_x() + EDGE, self.t.winfo_y() + BAR

    def place_mpv(self):
        x, y = self.inner()
        u.SetWindowPos(self.mpv, 0, x, y, 0, 0,
                       SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    # ---- dragging: title bar only, and a move never resizes
    def down(self, e):
        self.drag = (e.x_root - self.t.winfo_x(), e.y_root - self.t.winfo_y())

    def move(self, e):
        if self.drag:
            self.t.geometry("+%d+%d" % (e.x_root - self.drag[0],
                                        e.y_root - self.drag[1]))
            self.place_mpv()

    def up(self, e):
        if self.drag:
            self.drag = None
            self.place_mpv()
            self.reaim()

    def reaim(self):
        x, y = self.inner()
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
        cmd = [FF, "-hide_banner", "-loglevel", "error",
               "-init_hw_device", "d3d11va", "-filter_complex",
               "ddagrab=output_idx=0:framerate=%d:video_size=%dx%d"
               ":offset_x=%d:offset_y=%d" % (FPS, self.cw, self.ch, x, y),
               "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull",
               "-bf", "0", "-g", "30", "-forced-idr", "1",
               "-rc", "constqp", "-qp", "12",
               "-f", "mpegts", URL]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        with open(STATE, "w") as f:
            f.write("%d %d %d %d\n" % (self.cw, self.ch, x, y))

    def menu(self, e):
        m = tk.Menu(self.t, tearoff=0)
        m.add_command(label="Re-capture now", command=self.reaim)
        m.add_separator()
        m.add_command(label="Why can't I resize?", command=self.resize_hint)
        m.add_separator()
        m.add_command(label="Close", command=self.quit)
        m.tk_popup(self.t.winfo_x() + 6, self.t.winfo_y() + BAR)

    def resize_hint(self):
        from tkinter import messagebox
        messagebox.showinfo(
            "Resize",
            "The lens cannot resize while running. A resize recreates the "
            "swapchain, which forces the NR add-on to release the DLSS feature "
            "and crash (0xC0000005).\n\nClose it, then edit the width/height "
            "on the first line of:\n%s" % STATE)

    def quit(self):
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass
        os.system("taskkill /F /IM mpv.exe /T >nul 2>&1")
        self.root.quit()


def main():
    cw, ch, x, y = 1400, 1000, 500, 400
    if os.path.exists(STATE):
        try:
            cw, ch, x, y = [int(v) for v in open(STATE).read().split()[:4]]
        except Exception:
            pass

    h = None
    for _ in range(90):
        h = find_mpv()
        if h:
            break
        time.sleep(0.5)
    if not h:
        print("mpv window '%s' never appeared" % TITLE)
        return

    u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)
    st = u.GetWindowLongPtrW(h, GWL_STYLE)
    u.SetWindowLongPtrW(h, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
    ex = u.GetWindowLongPtrW(h, GWL_EXSTYLE)
    u.SetWindowLongPtrW(h, GWL_EXSTYLE,
                        ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
    print("viewport: click-through + excluded from capture")

    root = tk.Tk()
    root.withdraw()
    lens = Lens(root, h, x, y, cw, ch)
    lens.place_mpv()
    lens.reaim()
    print("lens ready %dx%d at (%d,%d) - drag the title bar" % (cw, ch, x, y))

    def watch():
        while u.IsWindow(h):
            time.sleep(0.4)
        try:
            if lens.proc:
                lens.proc.kill()
        except Exception:
            pass
        root.after(0, root.quit)

    threading.Thread(target=watch, daemon=True).start()

    try:
        root.mainloop()
    finally:
        try:
            if lens.proc:
                lens.proc.kill()
        except Exception:
            pass


main()
