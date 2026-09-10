"""
Floating see-through DLSS 5 Neural Rendering lens.

A bold-bordered window you drag anywhere on screen. Whatever is BEHIND it is
captured, neural-rendered, and drawn inside it -- so it reads as a see-through
pane that makes the desktop underneath it look neural-rendered.

How it avoids eating itself: both the frame and the mpv output window get
SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE), so Desktop Duplication looks
straight through them to the desktop below. Verified: an excluded magenta window
reads as plain desktop (UAVG 125) instead of magenta (UAVG 188).

Transport is UDP, not a pipe, because re-aiming the capture means restarting
ffmpeg -- mpv survives that on UDP (verified) but would hit EOF on a pipe.

MOVING the window is safe. RESIZING is not: it recreates the swapchain, forcing
the NR add-on to release the DLSS feature -> 0xC0000005. Resize goes through the
restart flow (Ctrl+Alt+R) instead.

  argv[1] mpv window title   argv[2] udp url   argv[3] state file
"""
import ctypes, ctypes.wintypes as w, sys, os, subprocess, threading, time
import tkinter as tk

TITLE = sys.argv[1] if len(sys.argv) > 1 else "FloatNR"
UDP   = sys.argv[2] if len(sys.argv) > 2 else "udp://127.0.0.1:9711?pkt_size=1316"
STATE = sys.argv[3] if len(sys.argv) > 3 else r"C:\Games\_screennr-float-state.txt"

FF = (r"C:\Users\jx\AppData\Local\Microsoft\WinGet\Packages"
      r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
      r"\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe")
BORDER   = 14                 # px of visible frame around the lens
KEY      = "#010203"          # transparent-colour key for the middle
ACCENT   = "#4ade80"
FPS      = 60

u = ctypes.windll.user32
u.SetProcessDPIAware()
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010


def find_mpv():
    hits = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, b, n + 1)
        c = ctypes.create_unicode_buffer(256);   u.GetClassNameW(h, c, 256)
        if c.value == "mpv" and TITLE.lower() in b.value.lower():
            hits.append(h)
        return True
    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


def exclude(h):
    return bool(u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE))


class Lens:
    def __init__(self, root, x, y, cw, ch):
        self.root, self.cw, self.ch = root, cw, ch
        self.proc = None
        self.drag = None
        self.pending = None

        t = tk.Toplevel(root)
        self.t = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.geometry("%dx%d+%d+%d" % (cw + BORDER * 2, ch + BORDER * 2,
                                    x - BORDER, y - BORDER))
        t.configure(bg=ACCENT)
        t.attributes("-transparentcolor", KEY)

        # hollow middle: the key colour is fully transparent AND click-through,
        # which is fine because the mpv output window sits exactly there.
        self.mid = tk.Frame(t, bg=KEY, width=cw, height=ch)
        self.mid.place(x=BORDER, y=BORDER)

        for seq, fn in (("<ButtonPress-1>", self.down),
                        ("<B1-Motion>", self.move),
                        ("<ButtonRelease-1>", self.up)):
            t.bind(seq, fn)
        t.update()
        self.hwnd = u.GetParent(t.winfo_id()) or t.winfo_id()
        exclude(self.hwnd)

    # ---- dragging: move only, never resize (a resize would crash the add-on)
    def down(self, e):
        self.drag = (e.x_root - self.t.winfo_x(), e.y_root - self.t.winfo_y())

    def move(self, e):
        if not self.drag:
            return
        self.t.geometry("+%d+%d" % (e.x_root - self.drag[0], e.y_root - self.drag[1]))
        self.place_mpv()

    def up(self, e):
        self.drag = None
        self.place_mpv()
        self.reaim()                       # re-capture what is now underneath

    def inner(self):
        return self.t.winfo_x() + BORDER, self.t.winfo_y() + BORDER

    def place_mpv(self):
        h = find_mpv()
        if h:
            x, y = self.inner()
            u.SetWindowPos(h, 0, x, y, 0, 0,
                           SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def reaim(self):
        x, y = self.inner()
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
        cmd = [FF, "-hide_banner", "-loglevel", "error",
               "-init_hw_device", "d3d11va",
               "-filter_complex",
               "ddagrab=output_idx=0:framerate=%d:video_size=%dx%d:offset_x=%d:offset_y=%d"
               % (FPS, self.cw, self.ch, x, y),
               "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull",
               "-bf", "0", "-g", "30", "-forced-idr", "1",
               "-rc", "constqp", "-qp", "12",
               "-f", "mpegts", UDP]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        with open(STATE, "w") as f:
            f.write("%d %d %d %d\n" % (self.cw, self.ch, x, y))

    def stop(self):
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass


def main():
    cw, ch, x, y = 1400, 1100, 400, 400
    if os.path.exists(STATE):
        try:
            cw, ch, x, y = [int(v) for v in open(STATE).read().split()[:4]]
        except Exception:
            pass

    h = None
    for _ in range(80):
        h = find_mpv()
        if h:
            break
        time.sleep(0.5)
    if not h:
        print("mpv window '%s' never appeared" % TITLE)
        return
    print("mpv excluded from capture:", exclude(h))

    # lock it against live resize (see module docstring)
    st = u.GetWindowLongPtrW(h, -16)
    u.SetWindowLongPtrW(h, -16, st & ~0x00040000 & ~0x00010000)

    root = tk.Tk(); root.withdraw()
    lens = Lens(root, x, y, cw, ch)
    lens.place_mpv()
    lens.reaim()
    print("lens ready: %dx%d at (%d,%d) - drag the border" % (cw, ch, x, y))

    def watch():
        while u.IsWindow(h):
            time.sleep(0.4)
        lens.stop()
        root.after(0, root.quit)
    threading.Thread(target=watch, daemon=True).start()

    try:
        root.mainloop()
    finally:
        lens.stop()


main()
