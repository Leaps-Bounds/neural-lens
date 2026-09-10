"""
Resize helper for the DLSS 5 ScreenNR / PhoneNR windows.

The NR output window CANNOT be resized live: a resize recreates the swapchain,
which forces the NR add-on to release the DLSS feature -> 0xC0000005. So this
helper:

  1. strips the resize/maximize styles from the NR window (can't crash it), and
  2. offers Ctrl+Alt+R -> a translucent "virtual outline" you drag to any size.
     Let go, and it asks whether to restart at that size. Yes writes the new
     geometry and stops mpv; the launcher's loop relaunches at the new size.

  argv[1] = NR window title substring   argv[2] = state file path
"""
import ctypes, ctypes.wintypes as w, sys, os, threading, time
import tkinter as tk
from tkinter import messagebox

TITLE = sys.argv[1] if len(sys.argv) > 1 else "PhoneNR"
STATE = sys.argv[2] if len(sys.argv) > 2 else r"C:\Games\_screennr-state.txt"
RESTART = STATE + ".restart"

u = ctypes.windll.user32
u.SetProcessDPIAware()
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong
GWL_STYLE, WS_THICKFRAME, WS_MAXIMIZEBOX = -16, 0x00040000, 0x00010000
SWP_FRAMECHANGED = 0x0001 | 0x0002 | 0x0004 | 0x0020
MOD_CONTROL, MOD_ALT, VK_R, WM_HOTKEY = 0x0002, 0x0001, 0x52, 0x0312


def find_nr():
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


def lock(h):
    st = u.GetWindowLongPtrW(h, GWL_STYLE)
    u.SetWindowLongPtrW(h, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
    u.SetWindowPos(h, 0, 0, 0, 0, 0, SWP_FRAMECHANGED)


def rect_of(h):
    r = w.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


class Outline:
    """Translucent resizable ghost. Settle after a drag -> confirm -> restart."""
    SETTLE_MS = 400

    def __init__(self, root, hwnd):
        self.root, self.hwnd, self.after_id, self.done = root, hwnd, None, False
        x, y, wd, ht = rect_of(hwnd)
        self.start = (wd, ht)
        t = tk.Toplevel(root)
        self.t = t
        t.title("Resize NR output - drag the edges, let go to confirm")
        t.geometry("%dx%d+%d+%d" % (wd, ht, x, y))
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.45)
        t.configure(bg="#101820")
        self.c = tk.Canvas(t, highlightthickness=0, bg="#101820")
        self.c.pack(fill="both", expand=True)
        t.bind("<Configure>", self.on_conf)
        t.bind("<Escape>", lambda e: self.cancel())
        t.protocol("WM_DELETE_WINDOW", self.cancel)
        self.draw(wd, ht)

    def draw(self, wd, ht):
        c = self.c
        c.delete("all")
        c.create_rectangle(3, 3, wd - 3, ht - 3, outline="#4ade80", width=6)
        same = (wd, ht) == self.start
        c.create_text(wd // 2, ht // 2 - 26, text="%d x %d" % (wd, ht),
                      fill="#4ade80", font=("Consolas", 40, "bold"))
        c.create_text(wd // 2, ht // 2 + 30,
                      text=("drag any edge to resize" if same else "let go to confirm"),
                      fill="#94a3b8", font=("Segoe UI", 17))
        c.create_text(wd // 2, ht // 2 + 62, text="Esc to cancel",
                      fill="#64748b", font=("Segoe UI", 13))

    def on_conf(self, e):
        if self.done or e.widget is not self.t:
            return
        self.draw(self.t.winfo_width(), self.t.winfo_height())
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.after_id = self.root.after(self.SETTLE_MS, self.settled)

    def settled(self):
        if self.done:
            return
        wd, ht = self.t.winfo_width(), self.t.winfo_height()
        if (wd, ht) == self.start:
            return                                   # only moved, not resized
        self.done = True
        self.t.attributes("-topmost", False)
        self.t.withdraw()
        if messagebox.askyesno(
                "Restart at new size?",
                "Resize the NR output to %d x %d ?\n\n"
                "The window cannot resize while running - it has to restart.\n"
                "Your phone/scrcpy session is not affected." % (wd, ht)):
            x, y = self.t.winfo_x(), self.t.winfo_y()
            with open(STATE, "w") as f:
                f.write("%d %d %d %d\n" % (wd, ht, x, y))
            open(RESTART, "w").close()
            os.system('taskkill /F /IM mpv.exe /T >nul 2>&1')
            self.root.quit()
        else:
            self.t.destroy()
            self.root.after(100, arm)

    def cancel(self):
        self.done = True
        self.t.destroy()
        self.root.after(100, arm)


def arm():
    pass  # hotkey stays registered for the process lifetime


def main():
    h = None
    for _ in range(80):
        h = find_nr()
        if h:
            break
        time.sleep(0.5)
    if not h:
        return
    lock(h)

    root = tk.Tk()
    root.withdraw()

    def pump():
        # RegisterHotKey posts WM_HOTKEY to the REGISTERING THREAD's queue, so it
        # must be registered here, on the thread that pumps -- not on the main
        # thread, whose queue belongs to tkinter's mainloop.
        msg = w.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # force a queue
        ok = u.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, VK_R)
        prev = False
        while True:
            if ok:
                if u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == WM_HOTKEY:
                        cur = find_nr()
                        if cur:
                            root.after(0, lambda c=cur: Outline(root, c))
            else:
                # fallback: poll, edge-triggered
                down = all(u.GetAsyncKeyState(k) & 0x8000 for k in (0x11, 0x12, VK_R))
                if down and not prev:
                    cur = find_nr()
                    if cur:
                        root.after(0, lambda c=cur: Outline(root, c))
                prev = down
            if not u.IsWindow(h):
                root.after(0, root.quit)
                return
            time.sleep(0.05)

    threading.Thread(target=pump, daemon=True).start()
    root.mainloop()


main()
