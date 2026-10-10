"""The frame Windows draws round a window of the lens's own that has one, the
dialogs and the stack setup, in the look's colours, how far it stands out
round the window, which Settings is fitted to the screen with, and such a
window kept out of the picture the presenter captures from the moment it is
made. And
what the lens's own dialog keeps of Windows' own boxes, the greyed close
button of a Yes and No question, the sound of each kind of message and the
copy of a message on the clipboard.

Windows 11 (build 22000 and later) takes the three colours of a frame, its
caption, its title and its border. Windows 10 takes none of them and keeps
its own, in its dark mode for a dark look where it knows the dark mode, as
attribute 20 from version 2004 on and as 19 before. Each call is tried and
one that Windows refuses is passed over, so a dialog never fails on its
frame.

The calls go through instances of user32 and dwmapi of this module's own, so
the argument types set here change nothing for the calls the rest of the
lens makes through ctypes.windll.
"""
import ctypes
import ctypes.wintypes as w

from lens_look import tokens

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_2004 = 19     # Windows 10 1809 to 1909
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_EXTENDED_FRAME_BOUNDS = 9
WDA_EXCLUDEFROMCAPTURE = 0x11
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0001, 0x0002, 0x0004, 0x0010, 0x0020
MONITOR_DEFAULTTONEAREST = 2
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SC_CLOSE, MF_BYCOMMAND, MF_GRAYED = 0xF060, 0x0000, 0x0001
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
# Windows' own sound for each kind of message, as MessageBeep takes it and as
# Windows' own boxes play it, MB_ICONHAND, MB_ICONQUESTION,
# MB_ICONEXCLAMATION and MB_ICONASTERISK
SOUNDS = {"error": 0x10, "question": 0x20, "warning": 0x30, "info": 0x40}


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


_user = ctypes.WinDLL("user32", use_last_error=True)
for _name, _res, _args in (
        ("GetParent", w.HWND, [w.HWND]),
        ("IsWindowVisible", w.BOOL, [w.HWND]),
        ("SetWindowDisplayAffinity", w.BOOL, [w.HWND, w.DWORD]),
        ("GetWindowDisplayAffinity", w.BOOL, [w.HWND, ctypes.POINTER(w.DWORD)]),
        ("SetWindowPos", w.BOOL, [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint]),
        ("MonitorFromPoint", w.HMONITOR, [w.POINT, w.DWORD]),
        ("GetMonitorInfoW", w.BOOL, [w.HMONITOR, ctypes.POINTER(_MonitorInfo)]),
        ("GetSystemMetrics", ctypes.c_int, [ctypes.c_int]),
        ("GetSystemMenu", w.HMENU, [w.HWND, w.BOOL]),
        ("EnableMenuItem", w.BOOL, [w.HMENU, w.UINT, w.UINT]),
        ("MessageBeep", w.BOOL, [w.UINT]),
        ("OpenClipboard", w.BOOL, [w.HWND]),
        ("EmptyClipboard", w.BOOL, []),
        ("SetClipboardData", w.HANDLE, [w.UINT, w.HANDLE]),
        ("CloseClipboard", w.BOOL, []),
        ("GetWindowRect", w.BOOL, [w.HWND, ctypes.POINTER(w.RECT)]),
        ("GetClientRect", w.BOOL, [w.HWND, ctypes.POINTER(w.RECT)]),
        ("ClientToScreen", w.BOOL, [w.HWND, ctypes.POINTER(w.POINT)])):
    getattr(_user, _name).restype, getattr(_user, _name).argtypes = _res, _args
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
for _name, _res, _args in (
        ("GlobalAlloc", w.HGLOBAL, [w.UINT, ctypes.c_size_t]),
        ("GlobalLock", w.LPVOID, [w.HGLOBAL]),
        ("GlobalUnlock", w.BOOL, [w.HGLOBAL]),
        ("GlobalFree", w.HGLOBAL, [w.HGLOBAL]),
        ("Sleep", None, [w.DWORD])):
    getattr(_kernel, _name).restype, getattr(_kernel, _name).argtypes = _res, _args
_dwm = []                       # dwmapi once it is first wanted, None where it cannot be had


def _set_attribute(hwnd, attribute, value):
    """DwmSetWindowAttribute with a DWORD value. Its HRESULT, which is 0 where
    the attribute took, or -1 where dwmapi cannot be had."""
    if not _dwm:
        try:
            dll = ctypes.WinDLL("dwmapi")
            dll.DwmSetWindowAttribute.restype = ctypes.c_long
            dll.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.POINTER(w.DWORD), w.DWORD]
            _dwm.append(dll)
        except (OSError, AttributeError):
            _dwm.append(None)
    if _dwm[0] is None:
        return -1
    v = w.DWORD(value)
    return _dwm[0].DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(v), ctypes.sizeof(v))


def colorref(colour):
    """A colour as #rrggbb in Windows' COLORREF, 0x00bbggrr."""
    r, g, b = tokens.rgb(colour)
    return r | (g << 8) | (b << 16)


def caption_colours(look):
    """The caption, the title and the border of a window's frame in a look,
    taken from its colours by role as tokens.CAPTION names them."""
    return tuple(look.c[role] for role in tokens.CAPTION.get(look.kind, tokens.CAPTION["console"]))


def dark(hwnd, on, setter=None):
    """The window's frame in Windows' dark mode, or in its light one. The
    attribute that took, 20 or 19, or None where neither did. setter is
    DwmSetWindowAttribute unless a check gives a stand-in."""
    setter = setter or _set_attribute
    for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_2004):
        if setter(hwnd, attribute, 1 if on else 0) == 0:
            return attribute
    return None


def tint(hwnd, dark_mode, colours, setter=None):
    """The frame of the window hwnd in the dark or the light mode and in
    colours, its caption, title and border, as caption_colours gives them.
    Returns the attributes that took. A colour Windows refuses is passed
    over, as Windows 10 refuses all three."""
    setter = setter or _set_attribute
    took = []
    mode = dark(hwnd, dark_mode, setter)
    if mode is not None:
        took.append(mode)
    for attribute, colour in zip((DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR, DWMWA_BORDER_COLOR), colours):
        if setter(hwnd, attribute, colorref(colour)) == 0:
            took.append(attribute)
    return took


def wrapper(window):
    """The window whose frame Windows draws for a Tk window, the parent of the
    one Tk draws in. Tk makes it at the first idle moment after the window,
    hidden while the window is withdrawn."""
    inner = window.winfo_id()
    return _user.GetParent(inner) or inner


def visible(hwnd):
    return bool(_user.IsWindowVisible(hwnd))


def frame_changed(hwnd):
    """Have Windows draw the frame of a window that is shown already once more,
    in the colours just set, without moving it, sizing it, raising it or
    making it active."""
    return bool(_user.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                                   | SWP_FRAMECHANGED))


def _shown_bounds(hwnd, rect):
    """The window's rectangle as it shows, without the part of its frame that
    Windows keeps invisible round it, where dwmapi can say. Whether it could."""
    try:
        get = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
        get.restype = ctypes.c_long
        get.argtypes = [w.HWND, w.DWORD, ctypes.POINTER(w.RECT), w.DWORD]
        return get(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) == 0
    except (OSError, AttributeError):
        return False


def frame_insets(window):
    """How far the frame Windows draws round a Tk window stands out from the
    window's own area, at its left, top, right and foot, in pixels, the
    caption being in the top one. Read from the window that carries the
    frame, which Tk makes at the first idle moment, so it works on a dialog
    still withdrawn. Where dwmapi cannot say what of the frame shows, the
    invisible part counts too. None where it cannot be read."""
    hwnd = wrapper(window)
    outer, inner, origin = w.RECT(), w.RECT(), w.POINT(0, 0)
    if not _shown_bounds(hwnd, outer) and not _user.GetWindowRect(hwnd, ctypes.byref(outer)):
        return None
    if not _user.GetClientRect(hwnd, ctypes.byref(inner)) or not _user.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    got = (origin.x - outer.left, origin.y - outer.top, outer.right - origin.x - inner.right,
           outer.bottom - origin.y - inner.bottom)
    if min(got) < 0 or got[1] == 0:
        return None                 # no frame round it, a window Tk has not given one yet
    return got


def caption(window, look):
    """The frame of a Tk window in the look's colours and its dark or light
    mode, see tint. A window that is shown already has its frame drawn again
    at once, see frame_changed. Returns the attributes that took."""
    hwnd = wrapper(window)
    took = tint(hwnd, look.dark_caption, caption_colours(look))
    if visible(hwnd):
        frame_changed(hwnd)
    return took


def exclude(window):
    """A Tk window kept out of the picture the presenter captures, as every
    window of the lens is, from the moment it is made rather than from the
    next time the lens's timer finds it. Whether Windows took it."""
    return bool(_user.SetWindowDisplayAffinity(wrapper(window), WDA_EXCLUDEFROMCAPTURE))


def affinity(hwnd):
    """The display affinity of a window, 0x11 for one kept out of the picture,
    or None where it cannot be read."""
    got = w.DWORD(0)
    return got.value if _user.GetWindowDisplayAffinity(hwnd, ctypes.byref(got)) else None


def dress(window, look=None):
    """A window with a frame dressed before it is first seen. It is kept out
    of the picture, and where a look is given its frame takes the look's
    colours. A fault in either is passed over, so a dialog never fails on its
    frame, and such a dialog keeps Windows' own caption while the lens's
    timer keeps it out of the picture, as it always did. Returns what took,
    for the checks."""
    took = {"excluded": False, "caption": []}
    try:
        took["excluded"] = exclude(window)
    except Exception:
        pass
    if look is not None:
        try:
            took["caption"] = caption(window, look)
        except Exception:
            pass
    return took


def no_close(window):
    """The close button of a window's frame greyed, as Windows' own box greys
    it on a Yes and No question, which has no answer for it. Whether Windows
    took it."""
    menu = _user.GetSystemMenu(wrapper(window), False)
    return bool(menu) and _user.EnableMenuItem(menu, SC_CLOSE, MF_BYCOMMAND | MF_GRAYED) != -1


def beep(kind):
    """Windows' own sound for a message of this kind, info, question, warning
    or error, as its own boxes play it as they show. Whether one was asked
    for. A kind it does not know plays nothing."""
    sound = SOUNDS.get(kind)
    return sound is not None and bool(_user.MessageBeep(sound))


def copy_text(hwnd, text):
    """text on the clipboard as Unicode text, given at once rather than when
    a program asks for it, as Tk gives it, so it is still there after the
    lens has quit. hwnd is the window of the lens's own that owns the
    clipboard, and without one nothing is touched. Whether it took."""
    if not hwnd:
        return False
    data = text.encode("utf-16-le") + b"\0\0"
    for _ in range(10):         # another program may hold the clipboard open for a moment
        if _user.OpenClipboard(hwnd):
            break
        _kernel.Sleep(20)
    else:
        return False
    try:
        if not _user.EmptyClipboard():
            return False
        handle = _kernel.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        at = _kernel.GlobalLock(handle)
        if not at:
            _kernel.GlobalFree(handle)
            return False
        ctypes.memmove(at, data, len(data))
        _kernel.GlobalUnlock(handle)
        if not _user.SetClipboardData(CF_UNICODETEXT, handle):
            _kernel.GlobalFree(handle)
            return False
        return True             # the clipboard owns the memory from here on
    finally:
        _user.CloseClipboard()


def work_area(x, y):
    """The work area, the monitor less the taskbar, of the monitor containing
    the point or else of the one nearest to it, as (left, top, width, height)
    in pixels."""
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    monitor = _user.MonitorFromPoint(w.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
    if monitor and _user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        r = info.rcWork
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return 0, 0, _user.GetSystemMetrics(SM_CXSCREEN), _user.GetSystemMetrics(SM_CYSCREEN)
