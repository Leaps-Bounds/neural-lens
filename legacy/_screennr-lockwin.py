# Strip the resize/maximize styles from the NR output window.
# Resizing recreates the swapchain -> the NR add-on must release the DLSS
# feature -> 0xC0000005 "releasing the DLSS feature". Cheaper to make the
# resize impossible than to survive it.
#   arg1: window title substring (default "PhoneNR")
import ctypes, ctypes.wintypes as w, sys, time
u = ctypes.windll.user32
u.SetProcessDPIAware()
GWL_STYLE = -16
WS_THICKFRAME, WS_MAXIMIZEBOX = 0x00040000, 0x00010000
SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020   # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
want = (sys.argv[1] if len(sys.argv) > 1 else "PhoneNR").lower()

u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong

def find():
    hits = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h): return True
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, b, n + 1)
        c = ctypes.create_unicode_buffer(256);   u.GetClassNameW(h, c, 256)
        if c.value == "mpv" and want in b.value.lower():
            hits.append(h)
        return True
    u.EnumWindows(cb, 0)
    return hits[0] if hits else None

for _ in range(60):                      # wait up to 30s for the window
    h = find()
    if h:
        st = u.GetWindowLongPtrW(h, GWL_STYLE)
        u.SetWindowLongPtrW(h, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
        u.SetWindowPos(h, 0, 0, 0, 0, 0, SWP)
        print("locked hwnd=%s  style %#x -> %#x" % (hex(h), st, u.GetWindowLongPtrW(h, GWL_STYLE)))
        sys.exit(0)
    time.sleep(0.5)
print("window not found")
sys.exit(1)
