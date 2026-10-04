"""A source for the fast engine's tests on screen: one picture of dense detail in a borderless
window at an exact rectangle, with a small part of it changing in a way a test names.

    python test_source.py X Y W H MODE [VALUE] [VALUE]

    still             nothing changes
    jump SECONDS      a white square of 120 px jumps to another place every SECONDS: one changed
                      frame, then rest. For the delay of the first picture after a rest
    caret MS          a bar of 4 by 46 px goes on and off every MS, as a text caret blinks
                      (530 is the Windows default)
    move SECONDS HZ   the square moves 8 px a step, HZ steps a second (120), for SECONDS, and
                      then stands still for good
    stops SECONDS REST HZ  the square moves as in move for SECONDS (1.2), stands still for
                      REST seconds (6), and so on: does the picture it stops on reach the
                      engine every time
    scroll SECONDS HZ the whole picture scrolls sideways 8 px a step, HZ steps a second (30),
                      for SECONDS, and then stands still for good. For the picture after a
                      stop: every part of it has moved
    lines MS          a band of 200 px across the whole picture is redrawn every MS, as a
                      terminal that prints: a large change, then rest
    sync BW BH        a part of BW x BH (1536x640) in the middle scrolls 8 px for each frame
                      the desktop's compositor makes, so the screen changes at every refresh
                      and misses none, and the rest stands still. For what the engine does
                      with a frame at every refresh. A source that steps by a timer misses a
                      refresh a few times a second

It prints "ready" once the window is up, and one line for each event with the clock's time:
"jumped T", "caret T", "stopped T" (20 ms after the square's last step and 60 ms after the
picture's, when that frame is on screen), "lines T", and "steps N" with a stop: how many
steps were drawn. In sync it prints "steps N" every second, the steps of that second. It
runs until it is killed, or for SOURCE_LIFETIME seconds (240), whichever comes
first. It must be a process of its own: a window of the harness's own process could not sit
beneath the engine's.

The picture is the one the project's other on-screen tests use, made once for each size and
kept beside this file's caller as backdrop-WxH.png when the folder named in BACKDROP_DIR is
given, else in the temporary folder. It is noise, which the network changes a great deal.
SOURCE_PICTURE=FILE shows that picture file in its place, as it is when it has the window's
size and stretched to it otherwise. It is for a picture of a scene, where a test needs the
network to behave as it does over one.
"""
import ctypes
import os
import sys
import tempfile
import time
import tkinter as tk

try:
    ctypes.windll.winmm.timeBeginPeriod(1)      # so an 8 ms step is not a 16 ms one
except Exception:
    pass
ctypes.windll.user32.SetProcessDPIAware()       # the rectangle is in physical pixels

X, Y, W, H = (int(a) for a in sys.argv[1:5])
MODE = sys.argv[5] if len(sys.argv) > 5 else "still"
VALUES = [float(a) for a in sys.argv[6:]]
FOLDER = os.environ.get("BACKDROP_DIR") or tempfile.gettempdir()
PICTURE = os.path.join(FOLDER, "backdrop-%dx%d.png" % (W, H))


def picture():
    """Dense detail, the same every time: the network acts on detail, and a flat picture would
    show little of what it does."""
    given = os.environ.get("SOURCE_PICTURE")
    if given and os.path.exists(given):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(given) as im:
            if im.size == (W, H) and given.lower().endswith(".png"):
                return given
            fitted = os.path.join(tempfile.gettempdir(), "source-picture-%dx%d.png" % (W, H))
            im.convert("RGB").resize((W, H), Image.LANCZOS).save(fitted)
            return fitted
    if os.path.exists(PICTURE):
        return PICTURE
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(11)
    a = rng.integers(0, 256, (H // 4 + 1, W // 4 + 1, 3), dtype="uint8")
    Image.fromarray(a).resize((W, H), Image.BICUBIC).save(PICTURE)
    return PICTURE


def said(what):
    print("%s %.4f" % (what, time.time()), flush=True)


root = tk.Tk()
root.overrideredirect(True)
root.geometry("%dx%d+%d+%d" % (W, H, X, Y))
root.attributes("-topmost", True)
image = tk.PhotoImage(file=picture())
canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, borderwidth=0)
canvas.pack(fill="both", expand=True)
canvas.create_image(0, 0, image=image, anchor="nw")

if MODE == "jump":
    every = int(1000 * (VALUES[0] if VALUES else 12.0))
    box = canvas.create_rectangle(20, 20, 140, 140, fill="#ffffff", outline="")
    places = [(20, 20), (W // 2, H // 2), (W - 300, 60), (200, H - 300), (W // 3, H // 4)]
    state = {"n": 0}

    def jump():
        state["n"] += 1
        x, y = places[state["n"] % len(places)]
        canvas.coords(box, x, y, x + 120, y + 120)
        said("jumped")
        root.after(every, jump)

    root.after(every, jump)
elif MODE == "caret":
    every = int(VALUES[0] if VALUES else 530)
    bar = canvas.create_rectangle(W // 3, H // 2, W // 3 + 4, H // 2 + 46, fill="#000000", outline="")
    state = {"on": True}

    def blink():
        state["on"] = not state["on"]
        canvas.itemconfigure(bar, state="normal" if state["on"] else "hidden")
        said("caret")
        root.after(every, blink)

    root.after(every, blink)
elif MODE == "move":
    seconds = VALUES[0] if VALUES else 6.0
    hz = VALUES[1] if len(VALUES) > 1 else 120.0
    box = canvas.create_rectangle(20, 20, 140, 140, fill="#ffffff", outline="")
    pos = {"x": 20, "y": 20, "dx": 8, "dy": 8, "end": 0.0}

    def step():
        if time.time() >= pos["end"]:
            # the last step is on screen a refresh or two later: said then, so whoever acts on
            # the line acts on the picture that stays
            root.after(20, lambda: said("stopped"))
            return
        for axis, limit in (("x", W - 120), ("y", H - 120)):
            pos[axis] += pos["d" + axis]
            if pos[axis] < 0 or pos[axis] > limit:
                pos["d" + axis] = -pos["d" + axis]
                pos[axis] = max(0, min(limit, pos[axis]))
        canvas.coords(box, pos["x"], pos["y"], pos["x"] + 120, pos["y"] + 120)
        root.after(max(1, int(round(1000.0 / hz))), step)

    def begin():
        pos["end"] = time.time() + seconds
        said("moving")
        step()

    root.after(1500, begin)
elif MODE == "stops":
    seconds = VALUES[0] if VALUES else 1.2
    rest = VALUES[1] if len(VALUES) > 1 else 6.0
    hz = VALUES[2] if len(VALUES) > 2 else 120.0
    box = canvas.create_rectangle(20, 20, 140, 140, fill="#ffffff", outline="")
    pos = {"x": 20, "y": 20, "dx": 8, "dy": 8, "end": 0.0}

    def step_on():
        if time.time() >= pos["end"]:
            root.after(20, lambda: said("stopped"))
            root.after(int(1000 * rest), begin_again)
            return
        for axis, limit in (("x", W - 120), ("y", H - 120)):
            pos[axis] += pos["d" + axis]
            if pos[axis] < 0 or pos[axis] > limit:
                pos["d" + axis] = -pos["d" + axis]
                pos[axis] = max(0, min(limit, pos[axis]))
        canvas.coords(box, pos["x"], pos["y"], pos["x"] + 120, pos["y"] + 120)
        root.after(max(1, int(round(1000.0 / hz))), step_on)

    def begin_again():
        pos["end"] = time.time() + seconds
        said("moving")
        step_on()

    root.after(1500, begin_again)
elif MODE == "scroll":
    seconds = VALUES[0] if VALUES else 5.0
    hz = VALUES[1] if len(VALUES) > 1 else 30.0
    # the picture twice, side by side, so it scrolls round without a gap
    second = canvas.create_image(W, 0, image=image, anchor="nw")
    first = canvas.find_all()[0]
    pos = {"x": 0, "end": 0.0, "steps": 0}

    def scroll():
        if time.time() >= pos["end"]:
            print("steps %d" % pos["steps"], flush=True)
            root.after(60, lambda: said("stopped"))
            return
        pos["x"] = (pos["x"] + 8) % W
        pos["steps"] += 1
        canvas.coords(first, -pos["x"], 0)
        canvas.coords(second, W - pos["x"], 0)
        root.update_idletasks()     # drawn now, so a step is a frame
        root.after(max(1, int(round(1000.0 / hz))), scroll)

    def begin_scroll():
        pos["end"] = time.time() + seconds
        said("moving")
        scroll()

    root.after(1500, begin_scroll)
elif MODE == "lines":
    every = int(VALUES[0] if VALUES else 300)
    band = canvas.create_rectangle(0, H // 2 - 100, W, H // 2 + 100, fill="#202020", outline="")
    state = {"n": 0}

    def line():
        state["n"] += 1
        canvas.itemconfigure(band, fill="#%02x%02x%02x" % ((37 * state["n"]) % 256, (91 * state["n"]) % 256, 64))
        said("lines")
        root.after(every, line)

    root.after(every, line)
elif MODE == "sync":
    import ctypes.wintypes as wt
    from PIL import Image
    BW = min(W, int(VALUES[0]) if VALUES else 1536)
    BH = min(H, int(VALUES[1]) if len(VALUES) > 1 else 640)
    BX, BY = (W - BW) // 2, (H - BH) // 2
    # That part of the picture as a bitmap GDI can copy from. It is copied onto the window in
    # two pieces, so it scrolls round without a gap.
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(picture()) as whole:
        raw = whole.convert("RGB").crop((BX, BY, BX + BW, BY + BH)).tobytes("raw", "BGRX")
    g, u, dwm = ctypes.windll.gdi32, ctypes.windll.user32, ctypes.windll.dwmapi

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    g.CreateCompatibleDC.restype = wt.HDC
    g.CreateCompatibleDC.argtypes = [wt.HDC]
    g.CreateDIBSection.restype = wt.HBITMAP
    g.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                   wt.DWORD]
    g.SelectObject.restype = wt.HGDIOBJ
    g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    g.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC, ctypes.c_int,
                         ctypes.c_int, wt.DWORD]
    u.GetDC.restype = wt.HDC
    u.GetDC.argtypes = [wt.HWND]
    u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), BW, -BH, 1, 32, 0, 0, 0, 0, 0, 0)   # top row first
    bits = ctypes.c_void_p()
    memory = g.CreateCompatibleDC(None)
    bitmap = g.CreateDIBSection(memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, raw, len(raw))
    del raw
    g.SelectObject(memory, bitmap)
    at = {"x": 0, "steps": 0, "said": time.perf_counter()}

    def tick():
        # DwmFlush returns when the compositor has finished a frame. The step drawn right
        # after it is in the compositor's next frame, so each of its frames has one step.
        dwm.DwmFlush()
        x = at["x"] = (at["x"] + 8) % BW
        window = canvas.winfo_id()
        dc = u.GetDC(window)
        g.BitBlt(dc, BX, BY, BW - x, BH, memory, x, 0, 0x00CC0020)      # SRCCOPY
        g.BitBlt(dc, BX + BW - x, BY, x, BH, memory, 0, 0, 0x00CC0020)
        u.ReleaseDC(window, dc)
        g.GdiFlush()
        at["steps"] += 1
        now = time.perf_counter()
        if now - at["said"] >= 1.0:
            print("steps %d" % at["steps"], flush=True)
            at["steps"], at["said"] = 0, now
        root.after(0, tick)

    root.after(1000, tick)

# It covers the screen, topmost: should the test that started it be gone without closing it,
# it closes itself, after SOURCE_LIFETIME seconds (240).
root.after(int(float(os.environ.get("SOURCE_LIFETIME", "240")) * 1000), root.destroy)
root.update()
root.lift()
print("ready", flush=True)
root.mainloop()
