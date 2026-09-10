# Print "X Y W H" (physical px) for a window's CLIENT area, so ddagrab grabs the
# phone screen only -- no title bar, no borders.
#   arg1: substring to match, or a window class (scrcpy uses class "SDL_app")
import ctypes, ctypes.wintypes as w, sys
u = ctypes.windll.user32
u.SetProcessDPIAware()
want = (sys.argv[1] if len(sys.argv) > 1 else "SDL_app").lower()
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
    if want in c.value.lower() or (b.value and want in b.value.lower()):
        r = w.RECT()
        u.GetClientRect(h, ctypes.byref(r))
        pt = w.POINT(0, 0)
        u.ClientToScreen(h, ctypes.byref(pt))
        cw, ch = r.right - r.left, r.bottom - r.top
        if cw > 100 and ch > 100:
            hits.append((pt.x, pt.y, cw, ch))
    return True

u.EnumWindows(cb, 0)
if not hits:
    sys.exit(1)
x, y, cw, ch = hits[0]
# h264 / yuv420p needs even dimensions
print("%d %d %d %d" % (x, y, cw - (cw % 2), ch - (ch % 2)))
