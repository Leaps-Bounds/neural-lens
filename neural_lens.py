# DLSS 5 Neural Lens
# Copyright (C) 2026 Leaps-Bounds
#
# Licensed under the PolyForm Strict License 1.0.0, whose text is in the LICENSE
# file beside this one.
"""
DLSS 5 Neural Lens: a floating see-through window that neural-renders whatever
is behind it. Drag it by the title bar. The viewport is click-through, so the
mouse reaches the desktop underneath, like the Windows Magnifier lens.

How it works. Every piece below was measured before it was built:

  1. The picture is drawn by the presenter, lens_presenter.py, a Vulkan window
     placed exactly on the lens rect, click-through and on top. It captures the
     monitor with Windows.Graphics.Capture, cropped to the rect, and presents
     each frame the moment it arrives, copying the original in afresh each
     time, so Neural Rendering never works on its own output. A captured
     frame the same as the last is not presented at all, so over content that
     is not changing nothing runs, and a present every quarter second keeps
     ReShade's keys and the capture alive.

  2. Every window of the lens's own, the presenter included, is excluded from
     capture (WDA_EXCLUDEFROMCAPTURE). Monitor capture then composes the
     desktop underneath them, which Desktop Duplication does not: measured, a
     region under an excluded window matched the bare desktop exactly.

  3. ReShade's Vulkan layer, the DLSS 5 Feed and the RenoDX DLSS 5 add-on attach
     to the presenter's swapchain and do the neural rendering. The presenter
     runs as lens-presenter.exe in the stack folder. ReShade reads its
     configuration from the executable's own folder: started from elsewhere with the stack as its working directory,
     the layer did not attach, measured. So the installed program's folder is
     the stack folder, and from source the stack folder beside the script holds
     a copy of the interpreter under that name.

  4. MULTI-PASS runs inside the add-on: the title bar's count is written to
     NRPasses in ReShade.ini before the presenter starts, and a count chosen in
     the add-on's own overlay reaches the bar while the overlay is open.

  5. Nothing buffers, so there is no frame rate to govern: a frame the neural
     pass cannot keep up with is replaced by the next. Measured from a change on
     screen to the change in the output, both read through the compositor:
     8 ms windowed at 120 Hz, one refresh.

  6. RESIZING restarts the picture. The presenter's size is fixed when it
     starts, and the add-on crashes when a swapchain is recreated under it, so
     a new size, fullscreen and back, or a lens that has to shrink to fit its
     monitor replaces the presenter, the way a new pass count does, and the
     chrome is laid out again around the new one. Only the folder settings
     restart the process, and that handover must not use os.execv: on Windows
     it does not quote arguments containing spaces.

  7. MINIMISED to the taskbar, the lens hides its windows and tells the
     presenter to pause. It stops its capture and presents nothing, so no
     neural pass runs and the GPU is free, and the taskbar button brings
     everything back as it was.

  8. FULLSCREEN has a presenter of its own, the fast engine, lens-fast.exe:
     a D3D12 program that captures on the GPU and calls the neural model
     directly, through the Cost Scaler's proxy, with no ReShade in it. It
     takes the presenter's command line and speaks its protocol, so the lens
     drives either the same way, and it starts in the presenter's place for
     a fullscreen lens. Where it is missing, or fails, the presenter of
     points 1 to 3 draws fullscreen as it draws a window, and it stands in
     while a screen that is asleep gives the engine no picture. What needs
     ReShade, tweak mode and ReShade's own screenshot, is offered only under
     that one. See Lens.engine_wanted, Lens.fast_out and Lens._recover.

  9. A FULLSCREEN lens is the picture alone, with no title bar, no frame and
     no tab. It covers its monitor from the top edge, less two rows at the
     bottom: a window that covers a monitor exactly makes Windows treat its
     program as a fullscreen one. Four single keys that are held only while
     the lens is fullscreen bring up the lens menu and the NR settings, turn
     Neural Rendering off and on, and show or hide the readout, a line of
     figures in a corner that Settings sets up. While the menu, the NR
     settings panel or the note is up, the arrow keys, Enter and Escape work
     it, so nothing needs the mouse or the taskbar while a game has the
     keyboard. Under the fast engine the NR settings are a panel of the
     lens's own, which writes the add-on's section of ReShade.ini and has
     the engine read it again, so the picture follows a value as it moves.
     What the bar would have said goes onto a notice at the top of the
     monitor for a few seconds. See fullscreen_rect, Lens.show_chrome,
     Lens.say, Lens.open_panel, Lens.nav_key and Lens.show_readout.

 10. THE TASKBAR BUTTON has a list of the lens's own on a right click, with
     three entries: the lens menu, the NR settings, and fullscreen and back.
     It is the button's jump list, which Windows keeps under the program's
     AppUserModelID, and each entry starts this program again with --do and
     a word. When a lens is running, that second process opens no window. It
     finds the lens by a window of the lens's that is never seen, hands it
     the word as a window message and ends, and the lens does what its own
     hotkey or menu entry for it does. With none running, it goes on as the
     lens itself. See _send_command, Commands and _taskbar_list.

 11. SETTINGS shows each setting as one short label. What a setting does is
     said in a small window by the pointer, once the pointer has rested on
     the setting for a second and a half. That window is one of the lens's
     own: out of the picture, never taking the keyboard or a click. See
     Hints and Lens.settings_dialog.

 12. NOTHING OF THE LENS GOES INTO ANOTHER PROGRAM, so it can get nobody
     banned from a game. It reads the screen through Windows Graphics
     Capture, and keys through RegisterHotKey and their state. It never
     hooks into another program, never sends one a key or any other input,
     never attaches to another program's input, never opens another
     program's process and never writes into another program's folder. The
     keys it posts go only to its own presenter's window, whose process is
     checked on each handle, and under the ReShade engine it switches Neural
     Rendering through ReShade.ini and a restart of the picture, not a key.
     Its ReShade is a Vulkan layer that switches on only in its own
     presenter, which the lens checks as it starts. Its own windows are made
     so they never take the foreground from the program in front. See
     Lens.toggle_nr, Lens.post_key, Lens.hand_focus_back, _layer_ungated
     and Lens._own_window.

Configuration: see neural-lens.ini.example. State, logs and screenshots live
in a data folder beside the program by default, so an install is one folder.
"""
import collections
import ctypes
import ctypes.wintypes as w
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox
from tkinter import ttk


def _script_dir():
    """The folder the ini lives in: beside the script, or beside the exe when
    frozen, where __file__ would point inside the bundle's internals."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _asset(name):
    """A file from the assets folder: beside the script, or inside the frozen
    bundle's data folder."""
    base = getattr(sys, "_MEIPASS", None) or _script_dir()
    return os.path.join(base, "assets", name)


def _set_icon(window):
    """Give a Tk window the lens icon, which the taskbar button shows."""
    try:
        window.iconbitmap(_asset("neural-lens.ico"))
    except Exception:
        pass


def _relaunch_cmd():
    """How to start another copy of this program with the same arguments.

    Frozen, the executable is the program and sys.argv[0] is the executable
    too, so passing it again as the first argument would be wrong.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable] + sys.argv[1:]
    return [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]


# ---- a word for the lens that is running
# The taskbar button's list, see _taskbar_list, starts this program a second
# time, with --do and one of the words below. When a lens is running, that
# process opens no window. It finds the lens, hands it the word and ends, see
# _send_command. With none running it goes on as the lens, unless one is
# starting or closing, see _hold_alive. A lens listens with a window that is
# never seen, see Commands, and the word travels as a registered window
# message, which needs nothing Windows does not have and works alike for the
# installed program and from source.
#
# The taskbar button, a shortcut pinned to the taskbar and the button's list
# belong together by an id, the AppUserModelID. Installed, the lens goes by
# the id Windows itself gives its exe, which a shortcut to that exe has too, so
# a lens that is pinned to the taskbar runs under its own pin and the pin shows
# the list: APP_ID is None there and nothing is set. A process that sets an id
# no longer belongs to a pin made without one. From source the program is
# Python, whose id every Python program has, so there the lens takes an id of
# its own. A test names one in NEURAL_LENS_APPID, which keeps its list and its
# words apart from those of a lens in real use. DO_NAME is the listening
# window's title, the same text whether or not the process carries it as its id.
DO_NAME = os.environ.get("NEURAL_LENS_APPID") or "LeapsBounds.NeuralLens"
APP_ID = None if getattr(sys, "frozen", False) and not os.environ.get("NEURAL_LENS_APPID") else DO_NAME
DO_ENTRIES = (                      # each word, and its entry's text in the taskbar button's list
    ("menu", "Open the lens menu"),
    ("nr", "Open or close the NR settings"),
    ("fullscreen", "Enter or leave fullscreen"),
)
DO_WORDS = tuple(word for word, _ in DO_ENTRIES)
DO_CLASS = "NeuralLensDo"           # the class of the listening window
HWND_MESSAGE = w.HWND(-3)           # the parent of a window that only takes messages
LRESULT = ctypes.c_ssize_t
# user32 through an instance of its own, so the argument types set on it change
# nothing for the calls the rest of the lens makes through ctypes.windll, and
# kernel32 the same way
_u32 = ctypes.WinDLL("user32", use_last_error=True)
for _name, _res, _args in (
        ("RegisterWindowMessageW", ctypes.c_uint, [w.LPCWSTR]),
        ("FindWindowExW", w.HWND, [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]),
        ("SendMessageTimeoutW", LRESULT, [w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM, ctypes.c_uint,
                                          ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]),
        ("GetWindowThreadProcessId", w.DWORD, [w.HWND, ctypes.POINTER(w.DWORD)]),
        ("AllowSetForegroundWindow", w.BOOL, [w.DWORD])):
    getattr(_u32, _name).restype, getattr(_u32, _name).argtypes = _res, _args
DO_MESSAGE = _u32.RegisterWindowMessageW(DO_CLASS)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
for _name, _res, _args in (
        ("CreateMutexW", w.HANDLE, [ctypes.c_void_p, w.BOOL, w.LPCWSTR]),
        ("CloseHandle", w.BOOL, [w.HANDLE])):
    getattr(_k32, _name).restype, getattr(_k32, _name).argtypes = _res, _args


def _lens_windows():
    """The listening window of every lens that is running, this one's too."""
    found, h = [], None
    while len(found) < 64:
        h = _u32.FindWindowExW(HWND_MESSAGE, h, DO_CLASS, DO_NAME)
        if not h:
            break
        found.append(h)
    return found


def _window_pid(hwnd):
    pid = w.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _ask_lens(hwnd, number):
    """Send a lens's listening window a number and return its answer, or None
    when it gave none within two seconds."""
    answer = ctypes.c_size_t(0)
    if not _u32.SendMessageTimeoutW(hwnd, DO_MESSAGE, number, 0, 0x0002, 2000,     # SMTO_ABORTIFHUNG
                                    ctypes.byref(answer)):
        return None
    return answer.value


def _say(line):
    """One line on stderr, for a process started with --do."""
    try:
        sys.stderr.write(line + "\n")
    except Exception:
        pass                        # started without a console or a pipe, there is no stderr


def _send_command(word):
    """What a process started with --do does first. Returns its exit code: 0
    when a lens took the word, 1 when no lens did, and the caller then goes on
    as the lens, 2 when the word is not one of DO_WORDS, and 3 when the lens
    gave no answer. 2 and 3 are said in one line on stderr, where the process
    has one. The block below that calls this says the line for 1 itself, once
    it knows that this process starts, and ends with 4 where a lens is
    starting or closing, see _hold_alive.

    With several lenses running, one takes the word: a lens in view before a
    minimised one, then a fullscreen lens before a windowed one, since it has
    no bar to click, then the lens on the monitor the pointer is on, then the
    one started last. Each lens says where it stands in that order as a
    number, see Commands.rank, and the highest takes the word."""
    if word not in DO_WORDS:
        _say("--do takes menu, nr or fullscreen.")
        return 2
    ranked = [(rank, h) for rank, h in ((_ask_lens(h, 0), h) for h in _lens_windows()) if rank]
    if not ranked:
        return 1
    hwnd = max(ranked)[1]
    # Windows lets a process that a click started give the keyboard to a
    # window, and lets it pass that on. The lens needs it for tweak mode, which
    # hands the keyboard to the ReShade overlay
    _u32.AllowSetForegroundWindow(_window_pid(hwnd))
    if _ask_lens(hwnd, 1 + DO_WORDS.index(word)) != 1:
        _say("The lens gave no answer.")
        return 3
    return 0


_ALIVE = None                       # this process's handle on the mutex of a lens that is alive, see _hold_alive


def _hold_alive():
    """Make the named mutex that marks this process as a lens that is alive,
    starting or closing, once per process, and keep its handle until main
    lets it go. Returns whether it was there already, which means another
    lens holds it. A lens listens for a word only once its picture is up, and
    no longer once it is closing, so a process started with --do that finds
    no lens to take its word asks this before it goes on as the lens, see
    below. An ordinary start makes it too and goes on all the same, so
    several lenses can still run."""
    global _ALIVE
    if _ALIVE is not None:
        return False
    ctypes.set_last_error(0)
    _ALIVE = _k32.CreateMutexW(None, False, "Local\\NeuralLens.alive." + DO_NAME)
    # ERROR_ALREADY_EXISTS, or ERROR_ACCESS_DENIED where a lens started as
    # administrator holds it, which a process that was not cannot open
    return ctypes.get_last_error() in (183, 5)


_DO_START = None                    # the word of a --do that found no lens to take it, see below
if __name__ == "__main__" and "--do" in sys.argv:
    # here, before anything below reads the stack or takes over the log, since
    # when a lens is running this process only passes a word on, and the files
    # are that lens's
    _at = sys.argv.index("--do") + 1
    _DO_START = sys.argv[_at] if _at < len(sys.argv) else ""
    _rc = _send_command(_DO_START)
    if _rc == 1 and _hold_alive():
        # a lens on its way up or out, which takes no word yet or any more
        _say("A Neural Lens is starting or closing, so this one does not start.")
        _rc = 4
    if _rc != 1:
        sys.exit(_rc)
    # No lens is running to take the word. The list outlives a lens only when
    # that lens was ended by force, and an entry of it then starts the lens, as
    # starting the program does, fullscreen for "fullscreen", see FULLSCREEN
    _say("No Neural Lens is running, so this one starts.")
    del sys.argv[_at - 1:_at + 1]


def _ini_path():
    """neural-lens.ini beside this script, or the file NEURAL_LENS_INI names,
    which is how a test keeps its settings out of the real one."""
    return os.environ.get("NEURAL_LENS_INI") or os.path.join(_script_dir(), "neural-lens.ini")


def _read_ini():
    """Optional neural-lens.ini beside this script. Plain key = value lines."""
    cfg = {}
    try:
        with open(_ini_path(), encoding="utf-8") as fh:
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


def _find_stack_dir():
    """The folder holding the Neural Rendering stack and the presenter.

    Checked in order: --stack-dir on the command line, the NEURAL_LENS_STACK
    environment variable, stack_dir in neural-lens.ini, then the program's own
    folder when installed, which is where the setup assembles the stack, and a
    "stack" folder beside the script when run from source. The names 0.1.0
    used, --mpv-dir, NEURAL_LENS_MPV_DIR and mpv_dir, are read too, in the same
    places. A folder counts when lens-presenter.exe is in it; the stack's other
    parts are checked separately, see _missing_stack, so an incomplete stack is
    named rather than silently passed over.
    """
    cands = []
    for i, a in enumerate(sys.argv):
        if a in ("--stack-dir", "--mpv-dir") and i + 1 < len(sys.argv):
            cands.append(sys.argv[i + 1])
    cands += [os.environ.get("NEURAL_LENS_STACK"), os.environ.get("NEURAL_LENS_MPV_DIR"),
              _INI.get("stack_dir"), _INI.get("mpv_dir")]
    if getattr(sys, "frozen", False):
        cands.append(_script_dir())
    cands.append(os.path.join(_script_dir(), "stack"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "lens-presenter.exe")):
            return os.path.abspath(c)
    return None


STACK_DIR = _find_stack_dir()
PRESENTER_EXE = os.path.join(STACK_DIR, "lens-presenter.exe") if STACK_DIR else None
# Installed, lens-presenter.exe is the presenter itself. The one the setup puts in
# a stack from source is a copy of the interpreter, with a pyvenv.cfg beside it,
# and is handed the script; a lens run from source against an installed stack
# runs that stack's own presenter.
PRESENTER_SCRIPT = (os.path.join(_script_dir(), "lens_presenter.py")
                    if STACK_DIR and not getattr(sys, "frozen", False)
                    and os.path.isfile(os.path.join(STACK_DIR, "pyvenv.cfg")) else None)


def _find_fast_exe():
    """The fast engine, lens-fast.exe, or None when it is not there.

    Checked in order: the stack's own, in its fast folder, then installed the
    fast folder beside the lens's own exe, which is where the installer puts
    it, and from source the one built under fast_engine beside the script.
    Installed, the two fast folders are one and the same unless the lens was
    pointed at another stack folder, which has no engine in it. Without the
    engine a fullscreen lens runs on the presenter like any other.
    """
    cands = []
    if STACK_DIR:
        cands.append(os.path.join(STACK_DIR, "fast", "lens-fast.exe"))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(_script_dir(), "fast", "lens-fast.exe"))
    else:
        cands.append(os.path.join(_script_dir(), "fast_engine", "bin", "lens-fast.exe"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


FAST_EXE = _find_fast_exe()
FAST_CLASS = "NeuralLensFast"       # its window's class, where the presenter's is glfw's
CREATE_NO_WINDOW = 0x08000000

# Finding the folder only proves the presenter is in it, so the lens would start
# and show the screen back unchanged with nothing said. That reads as the app
# doing nothing rather than as a stack that is incomplete.
NEURAL_STACK = (
    ("ReShade.ini", "ReShade's configuration, which loads the add-ons"),
    ("dlss5-feed.addon64", "the DLSS 5 feed add-on"),
    ("renodx-dlss5.addon64", "the RenoDX DLSS 5 add-on"),
    ("nvngx_dlssnr.dll", "NVIDIA's Neural Rendering model, or the Cost Scaler in front of it"),
    # the super resolution DLL is required even though the lens never upscales:
    # with it renamed aside the lens started and rendered nothing at all,
    # feature=18 never created and the output within 0.01 of the input
    ("nvngx_dlss.dll", "NVIDIA's DLSS runtime, which the model loads through"),
)


def _missing_stack():
    """Which parts of the Neural Rendering stack are not in STACK_DIR.

    This warns rather than refuses. The names are matched exactly against a
    known good install, so a variant layout that works should not be blocked on
    a guess about filenames.
    """
    if not STACK_DIR:
        return []
    return [(n, d) for n, d in NEURAL_STACK
            if not os.path.isfile(os.path.join(STACK_DIR, n))]


# Said at the start, ahead of the offer of the stack setup, when the layer that
# loads the lens's ReShade would switch on in every program, see _layer_ungated
LAYER_WORDS = ("The lens's ReShade is registered so that Vulkan loads it into every program that uses Vulkan, "
               "games included, and not only into the lens. An update that left out the stack setup leaves it "
               "that way, and the stack setup limits it to the lens again.")


def _layer_ungated():
    """The descriptions of the lens's Vulkan layer that would switch it on in
    every program, as paths, or none.

    The layer is ReShade, and it belongs in the lens's own presenter alone,
    which asks for it with ENABLE_VK_LAYER_reshade_neural_lens=1. A layer
    switched on in every program would load ReShade into every game that
    uses Vulkan, and nothing of the lens may go into another program, see
    point 12 at the top. 0.5.1 wrote a description without that switch, and
    an update with the stack setup left out keeps it. neural_stack's
    layer_ungated reads what is registered for this user, and it is asked
    here so the setup and the lens judge alike."""
    try:
        import neural_stack
        return neural_stack.layer_ungated()
    except Exception:
        return []


def _layer_own():
    """This copy's own description of the layer, the one its stack setup
    writes, normcase and abspath as _layer_key makes every path, or None."""
    try:
        import neural_stack
        return _layer_key(os.path.join(neural_stack.LAYER_DIR, "ReShade64.json"))
    except Exception:
        return None


def _layer_key(path):
    return os.path.normcase(os.path.abspath(path))


# Asked at the start about a registration of the lens's layer that would switch
# it on in every program and belongs to another copy of the lens, see
# _layer_stray. The stack setup of this copy writes only its own description.
LAYER_STRAY_WORDS = ("Another copy of the lens has its ReShade registered so that Vulkan loads it into every "
                     "program that uses Vulkan, games included. The registration names the file %s, and the "
                     "stack setup of this copy does not change it.\n\nRemove that registration? That copy's "
                     "ReShade then loads nowhere, its presenter included, until its own stack setup registers "
                     "it again. No keeps the registration, and the lens does not ask about it again.")
# The registrations the person kept when asked, by their descriptions' paths,
# which layer_stray_kept in the ini lists with | between them, a sign no path holds
LAYER_STRAY_KEPT = [p.strip() for p in str(_INI.get("layer_stray_kept", "")).split("|") if p.strip()]


def _layer_stray(path, parent=None):
    """Ask about a registration of the lens's layer that belongs to another
    copy of the lens, path being the description it names, and remove it or
    keep it as the answer says. Removing it deletes the value this user's
    ImplicitLayers holds under that path, which names the lens's own layer,
    see neural_stack.layer_unregister. A registration that is kept goes into
    the ini, so the lens does not ask about it again. Where the ini cannot be
    written, it is kept for this session alone and the lens starts all the
    same, and asks again at its next start."""
    import neural_stack
    if messagebox.askyesno("Neural Lens", LAYER_STRAY_WORDS % path, icon="warning", parent=parent):
        if neural_stack.layer_unregister(path):
            print("the registration of %s, which belongs to another copy of the lens, is removed" % path,
                  flush=True)
        else:
            print("the registration of %s could not be removed, so the lens asks again at its next start"
                  % path, flush=True)
        return
    LAYER_STRAY_KEPT.append(path)
    try:
        _save_ini("layer_stray_kept", "|".join(LAYER_STRAY_KEPT))
    except OSError as exc:
        print("the registration of %s, which belongs to another copy of the lens, is kept for this session, and "
              "as neural-lens.ini could not be written (%s), the lens asks about it again at its next start"
              % (path, exc.strerror or exc), flush=True)
        return
    print("the registration of %s, which belongs to another copy of the lens, is kept, and the lens does not "
          "ask about it again" % path, flush=True)


def _read_nr_enabled():
    """Whether the add-on will start with Neural Rendering on, from ReShade.ini.

    The add-on persists its F6 toggle there as NeuralUplift and reads it at
    start: measured, a session begun with NeuralUplift=0 ran as a passthrough,
    an in-to-out difference of 1.2 against 2.2 with it on, same image. It is
    written back within about a second of the toggle (measured: 1.3 s), but
    the running state is tracked from the key itself, see Lens.watch_f6.
    """
    if not STACK_DIR:
        return True
    try:
        with open(os.path.join(STACK_DIR, "ReShade.ini"), encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                bare = line.strip()
                if bare.lower().startswith("neuraluplift="):
                    return bare.split("=", 1)[1].strip().lower() not in ("0", "no", "off", "false")
    except OSError:
        pass
    return True


def _addon_stack_passes():
    """Whether the add-on in the stack runs several passes itself.

    From its v5 line the RenoDX DLSS 5 add-on applies several neural passes
    inside one process, the count set by NRPasses in its section of
    ReShade.ini and read when the process starts. The setup fetches such a
    build. An older add-on has no pass count, and the presenter cannot make a
    second pass by capturing its own window, which it excludes from capture,
    so with one the lens runs one pass. The key's name is looked for in the
    add-on file itself.
    """
    if not STACK_DIR:
        return False
    try:
        with open(os.path.join(STACK_DIR, "renodx-dlss5.addon64"), "rb") as fh:
            return b"NRPasses" in fh.read()
    except OSError:
        return False


ADDON_PASSES = _addon_stack_passes()
ADDON_MAX_PASSES = 4        # the add-on's own choice stops at four


def _pass_limit():
    """The most passes the bar allows: the add-on's own four, or one with an
    add-on that cannot run the passes itself."""
    return ADDON_MAX_PASSES if ADDON_PASSES else 1


def _write_addon_settings(n, nr=None):
    """Write the add-on's section of ReShade.ini for a presenter about to start,
    keeping the rest: NRPasses as n, and chained temporal history and the codec
    where the section holds no value for them.

    The add-on reads its settings only when its process starts: measured, an
    edit while it ran had changed nothing twelve seconds later, and a process
    that is terminated does not write the file back. So this runs after the old
    presenter is gone and before the new one spawns. Returns whether the file
    was written.

    Chained temporal history goes on, NRChainedHistory=1: without it the add-on
    resets its passes beyond the first every frame, and the picture pulses at
    two passes and up. The codec goes to Classic, NRCodecMode=0, which the
    add-on's developer asks for on the v5 line: with the add-on's default,
    Anchored, a model in Blender showed ghosting around it. A value the section
    already holds stays, so a choice made in the add-on's overlay, which the
    add-on writes back, is kept. The measurements are in docs/NOTES.md.

    nr, when given, is written as well, as NeuralUplift, the add-on's own record
    of its F6 toggle. The fast engine has no add-on in it to write that back, so
    the lens does when Neural Rendering is switched there, see Lens._nr_toggled,
    and the presenter that starts next, of either kind, finds it as it was left.
    """
    if not STACK_DIR:
        return False
    path = os.path.join(STACK_DIR, "ReShade.ini")
    keys = {"NRPasses": str(n), "NRChainedHistory": "1", "NRCodecMode": "0"}
    if nr is not None:
        keys["NeuralUplift"] = "1" if nr else "0"
    keep = {"NRChainedHistory", "NRCodecMode"}      # a value already there wins
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, done = [], False, set()

    def rest():
        for k, v in keys.items():
            if k not in done:
                out.append("%s=%s\n" % (k, v))
                done.add(k)

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                rest()
            inside = bare.lower() == "[renodx.dlss5]"
        elif inside and "=" in bare:
            name = bare.split("=", 1)[0].strip().lower()
            for k, v in keys.items():
                if name == k.lower():
                    if k not in done:
                        out.append(line if k in keep else "%s=%s\n" % (k, v))
                        done.add(k)
                    break
            else:
                out.append(line)
            continue
        out.append(line)
    if len(done) < len(keys):
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if not inside:
            out.append("\n[RenoDX.DLSS5]\n")
        rest()
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.writelines(out)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def _drme_in_use():
    """Whether the stack's preset runs ReshadeMotionEstimation, the estimator
    whose detail _write_motion_detail sets."""
    if not STACK_DIR:
        return False
    try:
        with open(os.path.join(STACK_DIR, "ReShadePreset.ini"), encoding="utf-8-sig", errors="replace") as fh:
            head = [l for l in fh.read().splitlines() if l.strip().lower().startswith("techniques=")]
    except OSError:
        return False
    return bool(head) and "motionestimation.fx" in head[0].lower()


def _read_motion_detail():
    """The detail ReShadePreset.ini holds for ReshadeMotionEstimation, full, half or
    quarter, full where the preset has no value, or None where the estimator is not
    in use or the file cannot be read."""
    if not _drme_in_use():
        return None
    inside, level = False, "0"
    try:
        with open(os.path.join(STACK_DIR, "ReShadePreset.ini"), encoding="utf-8-sig", errors="replace") as fh:
            for line in fh.read().splitlines():
                bare = line.strip()
                if bare.startswith("["):
                    inside = bare.lower() == "[motionestimation.fx]"
                elif inside and bare.split("=", 1)[0].strip().lower() == "ui_me_layer_max":
                    level = bare.split("=", 1)[-1].strip()
    except OSError:
        return None
    return {"0": "full", "1": "half", "2": "quarter"}.get(level, "full")


def _write_motion_detail(detail):
    """Set ReshadeMotionEstimation's Motion Estimation Detail in ReShadePreset.ini
    for a presenter about to start: 0 for full, 1 for half, 2 for quarter, as
    UI_ME_LAYER_MAX in the preset's [MotionEstimation.fx] section, keeping the
    rest of the file.

    ReShade reads the preset when its process starts, so like the add-on's
    settings this runs before the presenter spawns. The lens's choice wins over
    one made in the ReShade overlay, since Settings is where it is offered. At
    full with no section in the preset nothing is written, since full is the
    estimator's own default. Returns whether the file was written.
    """
    if not _drme_in_use():
        return False
    path = os.path.join(STACK_DIR, "ReShadePreset.ini")
    level = {"full": "0", "half": "1", "quarter": "2"}.get(detail, "0")
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, found, section = [], False, False, False
    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside and not found:
                # at the end of the section, ahead of the blank lines before the next
                blanks = []
                while out and not out[-1].strip():
                    blanks.insert(0, out.pop())
                out.append("UI_ME_LAYER_MAX=%s\n" % level)
                out.extend(blanks)
                found = True
            inside = bare.lower() == "[motionestimation.fx]"
            section = section or inside
        elif inside and bare.split("=", 1)[0].strip().lower() == "ui_me_layer_max":
            if found:
                continue
            if bare.split("=", 1)[-1].strip() == level:
                return False
            out.append("UI_ME_LAYER_MAX=%s\n" % level)
            found = True
            continue
        out.append(line)
    if not found:
        if not section and level == "0":
            return False
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if not inside:
            out.append("\n[MotionEstimation.fx]\n")
        out.append("UI_ME_LAYER_MAX=%s\n" % level)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.writelines(out)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def _read_nr_passes():
    """NRPasses as the add-on's section of ReShade.ini holds it now, or None.

    The add-on writes its settings back within about a second of a change in
    its overlay (measured with F6: NeuralUplift was on disk 1.3 s after the
    press), so while the overlay is open this is how a pass count chosen there
    reaches the title bar. See Lens.follow_overlay.
    """
    if not STACK_DIR:
        return None
    try:
        with open(os.path.join(STACK_DIR, "ReShade.ini"), encoding="utf-8",
                  errors="replace") as fh:
            inside = False
            for line in fh:
                bare = line.strip()
                if bare.startswith("["):
                    inside = bare.lower() == "[renodx.dlss5]"
                elif inside and bare.lower().startswith("nrpasses="):
                    return int(bare.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return None


def _read_addon_section():
    """The add-on's section of ReShade.ini as it stands, key by key, in order.

    This is every setting the Home menu holds, as the add-on last wrote it
    back, which it does within about a second of a change there.
    """
    values = {}
    if not STACK_DIR:
        return values
    try:
        with open(os.path.join(STACK_DIR, "ReShade.ini"), encoding="utf-8", errors="replace") as fh:
            inside = False
            for line in fh:
                bare = line.strip()
                if bare.startswith("["):
                    inside = bare.lower() == "[renodx.dlss5]"
                elif inside and "=" in bare:
                    k, v = bare.split("=", 1)
                    values[k.strip()] = v.strip()
    except OSError:
        pass
    return values


def _set_addon_values(values):
    """Set these keys in the add-on's section of ReShade.ini and leave every
    other byte of the file as it is: the other lines, their order and their
    line endings. A key the section holds keeps its line and gets the new
    value, one it does not hold is added at the section's end, and a file
    without the section gets one at its end.

    This is the write behind the lens's own NR settings panel. The fast engine
    reads the section again when it is told reload, so the file has to be whole
    at every moment: it is written beside the real one and put in its place in
    one step. Returns whether the file now holds the values.
    """
    if not STACK_DIR or not values:
        return False
    path = os.path.join(STACK_DIR, "ReShade.ini")
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    eol = "\r\n" if any(l.endswith("\r\n") for l in lines) or not lines else "\n"
    want = {str(k).lower(): (str(k), str(v)) for k, v in values.items()}
    out, inside, found, done = [], False, False, set()

    def rest():
        # the keys the section does not hold, after its last line and ahead of
        # the blank lines that part it from the next section
        missing = [(k, v) for low, (k, v) in want.items() if low not in done]
        if not missing:
            return
        blanks = []
        while out and not out[-1].strip():
            blanks.insert(0, out.pop())
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += eol
        out.extend("%s=%s%s" % (k, v, eol) for k, v in missing)
        done.update(want)
        out.extend(blanks)

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                rest()
            inside = bare.lower() == "[renodx.dlss5]"
            found = found or inside
        elif inside and "=" in bare:
            name = bare.split("=", 1)[0].strip().lower()
            if name in want:
                # the key as the file spells it, the space it leaves after the
                # sign, and the line's own ending
                body = line.rstrip("\r\n")
                key, _, old = body.partition("=")
                out.append("%s=%s%s%s" % (key, old[:len(old) - len(old.lstrip())], want[name][1],
                                          line[len(body):]))
                done.add(name)
                continue
        out.append(line)
    if inside:
        rest()
    elif not found:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += eol
        out.append("%s[RenoDX.DLSS5]%s" % (eol if out else "", eol))
        rest()
    if out == lines:
        return True
    try:
        with open(path + ".tmp", "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.writelines(out)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def _nr_text(value):
    """A number as the add-on writes it into its section: two decimals at most
    and no zeros at the end."""
    text = ("%.2f" % float(value)).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _nr_number(values, key, default):
    """A number out of the add-on's section as _read_addon_section gives it, or
    the default where the key is missing or is not a number."""
    try:
        v = float(values.get(key, default))
    except (TypeError, ValueError):
        return default
    return v if v == v and abs(v) != float("inf") else default


# the add-on's section holds these for the install, not for a look: they are
# kept as they are when a profile replaces the rest
ADDON_KEEP = ("ConfigVersion", "EnableHooks")


def _replace_addon_section(values):
    """Make the add-on's section of ReShade.ini hold these values and nothing
    else, apart from ADDON_KEEP, which stay as they are. For a presenter about
    to start, since the add-on reads its settings only then."""
    if not STACK_DIR:
        return False
    path = os.path.join(STACK_DIR, "ReShade.ini")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, found = [], False, False
    kept = []

    def section():
        for line in kept:
            out.append(line)
        for k, v in values.items():
            if k not in ADDON_KEEP:
                out.append("%s=%s\n" % (k, v))
        out.append("\n")

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                section()
            inside = bare.lower() == "[renodx.dlss5]"
            if inside:
                found = True
            out.append(line)
        elif inside:
            if "=" in bare and bare.split("=", 1)[0].strip() in ADDON_KEEP:
                kept.append(line)
        else:
            out.append(line)
    if inside:
        section()
    if not found:
        out.append("\n[RenoDX.DLSS5]\n")
        section()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(out)
    except OSError:
        return False
    return True


# ---- profiles: named sets of everything that makes the picture, see Lens.capture_profile
def _load_profiles():
    try:
        with open(PROFILES, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("profiles"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"profiles": {}, "current": None}


def _save_profiles(d):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PROFILES, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
    except OSError:
        pass


# ---- the Cost Scaler proxy
# DLSSNR-Cost-Scaler is a proxy nvngx_dlssnr.dll that runs the neural model at
# a fraction of the frame's resolution and composites the result back onto the
# full frame. The setup puts it in front of the model, which becomes
# nvngx_dlssnr_real.dll, with the proxy's ini beside it. The proxy reads that
# ini when it starts and again within a second of any change. Neural Rendering
# in the lens runs as a D3D12 NGX session behind the Feed's Vulkan transport,
# which is the API the proxy hooks, so it works here as it does in a game.
#
# It pays where the neural pass is what limits the frame rate, which is a
# whole monitor or several passes, and costs a little where it is not. Its
# Matched Residual blend puts the model's change onto the full-size original,
# so a lower scale loses none of the model's detail, and its light sharpening
# adds some: over a Blender still fullscreen at 6144x2526, one pass, 0.50 made
# as large a change as the model at full size, with edge detail 152 against
# 113. So it is on for fullscreen and off when windowed, unless cost_scaler in
# the ini says always, off, or manual, which leaves its ini alone.
# docs/NOTES.md has the numbers.
COST_SCALER = str(_INI.get("cost_scaler", "fullscreen")).strip().lower()
if COST_SCALER not in ("fullscreen", "always", "off", "manual"):
    COST_SCALER = "fullscreen"
try:
    # the neural working area over all the passes, in megapixels. 4 is
    # 6144x2526 at 0.50 for one pass and the floor of 0.35 from two, 3840x2160
    # at 0.65 for one pass and 0.45 for two, and 2560x1440 at native for one
    # pass and 0.70 for two. Fullscreen at one pass, 0.50 ran 10 frames a
    # second faster than 0.70 on about 55 W less, and made the model's full
    # change where 0.70 made about half of it, measured over the Blender still.
    # docs/NOTES.md has the numbers.
    COST_SCALER_MPX = max(0.5, min(80.0, float(_INI.get("cost_scaler_mpx", 4))))
except (TypeError, ValueError):
    COST_SCALER_MPX = 4.0


def _set_cost_scaler(mode):
    """Change the Cost Scaler rule in force, from Settings, and record it in
    the ini, where the default is left unwritten. The caller applies it."""
    global COST_SCALER
    COST_SCALER = mode
    _save_ini("cost_scaler", None if mode == "fullscreen" else mode)


def _proxy_installed():
    return bool(STACK_DIR) and all(os.path.isfile(os.path.join(STACK_DIR, n))
                                   for n in ("nvngx_dlssnr_real.dll", "nvngx_dlssnr.ini"))


def _proxy_scale(cw, ch, passes=1):
    """The proxy's resolution scale for a lens this size and pass count, or
    None for off.

    Scaled so the model's work over all the passes comes to about
    COST_SCALER_MPX megapixels, in the 5% steps the proxy uses, never below
    0.35, where the picture has lost too much detail, and off rather than on
    from 0.90 up, where too little is saved to pay for the proxy's own cost.
    """
    if cw <= 0 or ch <= 0:
        return None
    s = (COST_SCALER_MPX * 1e6 / float(cw * ch * max(1, passes))) ** 0.5
    if s >= 0.90:
        return None
    return max(0.35, int(s * 20 + 1e-9) / 20.0)


def _write_proxy(enabled, scale):
    """Set EnableProxy, and when enabling also ResolutionScale, in the proxy's
    ini, keeping the rest.

    Anamorphic scaling is switched off with the scale, so the uniform scale is
    what applies. Switching off touches nothing but the flag, so a scale of
    the user's own survives. Returns whether the file was written.
    """
    if not _proxy_installed():
        return False
    path = os.path.join(STACK_DIR, "nvngx_dlssnr.ini")
    keys = {"EnableProxy": "1" if enabled else "0"}
    if enabled:
        keys["ResolutionScale"] = "%.2f" % scale
        keys["EnableAnamorphic"] = "0"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines(True)
    except OSError:
        return False
    out, inside, done = [], False, set()

    def rest():
        for k, v in keys.items():
            if k not in done:
                out.append("%s = %s\n" % (k, v))
                done.add(k)

    for line in lines:
        bare = line.strip()
        if bare.startswith("["):
            if inside:
                rest()
            inside = bare.lower() == "[dlssnr_proxy]"
        elif inside and "=" in bare and not bare.startswith(";"):
            name = bare.split("=", 1)[0].strip().lower()
            for k, v in keys.items():
                if name == k.lower():
                    if k not in done:
                        out.append("%s = %s\n" % (k, v))
                        done.add(k)
                    break
            else:
                out.append(line)
            continue
        out.append(line)
    if len(done) < len(keys):
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if not inside:
            out.append("\n[DLSSNR_Proxy]\n")
        rest()
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.writelines(out)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


# The presenter's window is found by its process, and its title carries this
# process's id, so two lenses at once, one per monitor say, never pick up each
# other's presenter.
TITLE = "LensNR %d" % os.getpid()
__version__ = "0.6.0"        # beta; see CHANGELOG.md

DATA_DIR = (os.environ.get("NEURAL_LENS_DATA") or _INI.get("data_dir")
            or os.path.join(_script_dir(), "data"))
STATE = os.path.join(DATA_DIR, "lens-state.txt")
LOGDIR = os.path.join(DATA_DIR, "logs")
PROFILES = os.path.join(DATA_DIR, "profiles.json")     # named settings, see Lens.capture_profile

# Started without a console, as the installed program and the launcher are,
# everything the lens prints goes to lens.log in the log folder instead, and
# anything that used to stop and wait for Enter is shown as a dialog, since
# there is nothing left to read it in.
HEADLESS = ctypes.windll.kernel32.GetConsoleWindow() == 0


def _clock():
    """The local time as lens.log's lines start with it, HH:MM:SS.mmm."""
    t = time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + ".%03d" % (int(t * 1000) % 1000)


class _StampedLines:
    """lens.log as the lens writes it: every line starts with the local time,
    HH:MM:SS.mmm, and a space, so a line can be put beside what happened on
    screen and beside the engine's own notes.

    print hands a line over in pieces, its text and then its newline, and the
    threads that read the presenters print too, so each thread's pieces are
    gathered apart from the others' until a line is whole. A whole line goes
    into the file in one write, under one lock, with the time its first piece
    came."""

    def __init__(self, f):
        self.f = f
        self.lock = threading.Lock()
        self.parts = {}             # {thread: (stamp, text)}: a line begun and not ended yet

    def write(self, text):
        text = str(text)
        if not text:
            return 0
        me = threading.get_ident()
        with self.lock:
            stamp, part = self.parts.pop(me, (None, ""))
            lines = (part + text).split("\n")
            for line in lines[:-1]:
                self.f.write("%s %s\n" % (stamp or _clock(), line))
                stamp = None
            if lines[-1]:
                self.parts[me] = (stamp or _clock(), lines[-1])
        return len(text)

    def flush(self):
        with self.lock:
            self.f.flush()

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self.f, name)        # encoding, fileno and the rest, as the file has them


def _redirect_output(append=False):
    """Send stdout and stderr to lens.log, rolling the previous one into the
    archive first so it is pruned with the rest. With append the lens.log
    that is there goes on instead, unrolled, which is how a lens that
    Settings restarted carries on in the log of the one before it, where
    the two have the same data folder, see _main. Every line it gets starts
    with the time, see _StampedLines. Returns the path, or None."""
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        cur = os.path.join(LOGDIR, "lens.log")
        if os.path.isfile(cur) and not append:
            if os.path.getsize(cur) > 0:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                os.replace(cur, os.path.join(LOGDIR, "%s-lens.log" % stamp))
            else:
                os.remove(cur)
        f = open(cur, "a" if append else "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = sys.stderr = _StampedLines(f)
        return cur
    except OSError:
        return None


# A lens that Settings restarted has its stdout in restart.log, and is told by
# this which lens.log the lens before it wrote, see _main. It goes on in that
# file only where that is its own lens.log too. A new data folder gives it
# another, which it starts as any start does, rolling the one there into the
# archive. The marker is taken out of the environment, so nothing this lens
# starts in turn inherits it.
_LOG_HANDED = os.environ.pop("NEURAL_LENS_LOG_APPEND", None)
_LOG_APPEND = bool(_LOG_HANDED) and (os.path.normcase(os.path.abspath(_LOG_HANDED))
                                     == os.path.normcase(os.path.abspath(os.path.join(LOGDIR, "lens.log"))))
if sys.stdout is None or _LOG_HANDED:
    _redirect_output(append=_LOG_APPEND)
SHOT_DIR = (os.environ.get("NEURAL_LENS_SHOTS") or _INI.get("screenshot_dir")
            or os.path.join(DATA_DIR, "screenshots"))

BAR = 34
# The frame around the picture, which the lens is resized by: EDGE pixels down
# each side and along the bottom, the outer LINE of them the border's line and
# the rest a strip the mouse can catch. The top edge is the bar.
LINE, EDGE = 2, 8
CORNER = 16                  # how far from a grip's end still counts as the corner
MIN_W, MIN_H = 240, 120      # the smallest lens a drag can make
# Attached to a window, the chrome is a two pixel line around the region and
# this tab on its top edge, the only part of the lens that takes the mouse
TAB_W, TAB_H = 28, 14
ATTACH_SETTLE = 0.5          # seconds a target's new size must hold before the picture restarts
DIVIDER = 14                 # grab width of the A/B divider; the line drawn is 4
KEY_HOLD = 350               # ms a posted key stays down, longer than any frame
# A fullscreen lens covers its monitor less this many rows at the bottom. A
# window that covers a monitor exactly makes Windows treat its program as a
# fullscreen one: notifications are held back and the taskbar loses its place
# on top, so one that hides itself no longer comes up. Measured, one row short
# does none of that, and the lens keeps its sizes even, so it is two.
FULL_SHORT = 2
# Themes. Every colour the lens draws comes from one of these, chosen by
# theme = Name in the ini; Slate is the lens as it always looked. A themes.json
# in the data folder adds or replaces themes, one object per name with the same
# keys, so a theme can be made without touching the program.
THEMES = {
    "Slate": {"bg": "#1b2430", "fg": "#cbd5e1", "accent": "#4ade80", "dim": "#64748b", "warn": "#fbbf24",
              "cap": "#243040", "hover": "#334155", "field": "#0b1220", "tab": "#1e293b", "close": "#e11d48"},
    "Graphite": {"bg": "#232323", "fg": "#d6d6d6", "accent": "#f0b429", "dim": "#8a8a8a", "warn": "#f0b429",
                 "cap": "#2e2e2e", "hover": "#3d3d3d", "field": "#161616", "tab": "#2a2a2a", "close": "#d13c3c"},
    "Paper": {"bg": "#f3f4f6", "fg": "#1f2937", "accent": "#15803d", "dim": "#6b7280", "warn": "#b45309",
              "cap": "#e5e7eb", "hover": "#d1d5db", "field": "#ffffff", "tab": "#e5e7eb", "close": "#dc2626"},
    "Industrial": {"bg": "#2b2622", "fg": "#e7dcc8", "accent": "#f59e0b", "dim": "#8a7f70", "warn": "#fbbf24",
                   "cap": "#35302b", "hover": "#4a413a", "field": "#1f1b18", "tab": "#332d28", "close": "#b91c1c"},
}
THEME_KEYS = ("bg", "fg", "accent", "dim", "warn", "cap", "hover", "field", "tab", "close")


def _is_colour(v):
    v = str(v)
    return len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def _load_themes():
    """The built-in themes, with the data folder's themes.json laid over them:
    a theme there with a built-in name replaces it, a new name is added, and a
    theme missing keys takes them from Slate. A file that cannot be read is
    ignored, since a bad file must not stop the lens."""
    themes = {k: dict(v) for k, v in THEMES.items()}
    try:
        with open(os.path.join(DATA_DIR, "themes.json"), encoding="utf-8") as f:
            extra = json.load(f)
        for name, vals in (extra or {}).items():
            if isinstance(vals, dict) and str(name).strip():
                merged = dict(THEMES["Slate"])
                merged.update({k: str(v) for k, v in vals.items() if k in THEME_KEYS and _is_colour(v)})
                themes[str(name).strip()] = merged
    except Exception:
        pass
    return themes


ALL_THEMES = _load_themes()
THEME_NAME = str(_INI.get("theme", "Slate")).strip() or "Slate"
if THEME_NAME not in ALL_THEMES:
    THEME_NAME = "Slate"
_T = ALL_THEMES[THEME_NAME]
KEY = "#010203"                     # the colour keyed out of the chrome, never drawn
BG, FG, ACCENT, DIM, WARN = _T["bg"], _T["fg"], _T["accent"], _T["dim"], _T["warn"]
CAP = _T["cap"]                     # the window buttons' own shade on the title bar
HOVER, FIELD, TAB_BG, CLOSE = _T["hover"], _T["field"], _T["tab"], _T["close"]

# The title bar's minimise, maximise, restore and close buttons use Windows'
# own caption glyphs, from whichever Segoe icon font the machine has, so they
# read as the buttons every window has. Without either they fall back to plain
# characters Segoe UI draws.
CAPTION_FONTS = (("Segoe Fluent Icons", {"min": "", "max": "", "restore": "",
                                         "close": ""}),
                 ("Segoe MDL2 Assets", {"min": "", "max": "", "restore": "",
                                        "close": ""}))
CAPTION_PLAIN = {"min": "─", "max": "□", "restore": "❐", "close": "✕"}


def _caption_glyphs(families):
    """The font and the glyphs for the caption buttons, given the font families
    the machine has."""
    for fam, glyphs in CAPTION_FONTS:
        if fam in families:
            return (fam, 9), glyphs
    return ("Segoe UI", 12), CAPTION_PLAIN


def _display_hz(device=None, unknown=60):
    """Refresh rate of the primary display, for the delay meter's allowance,
    or with a device name, such as GetMonitorInfoW gives, of that display,
    for monitor_hz. As Windows has it now, and unknown where it cannot be
    read."""
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
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if ctypes.windll.user32.EnumDisplaySettingsW(device, -1, ctypes.byref(dm)):
            hz = int(dm.dmDisplayFrequency)
            if 24 <= hz <= 1000:
                return hz
    except Exception:
        pass
    return unknown


DISPLAY_HZ = _display_hz()


def _whole_delay(meter, shown=None):
    """The delay the lens shows, in milliseconds, never below zero. This is the
    one place it is worked out, for both presenters.

    The stack presenter reports its meter alone, and the composition and
    scanout after its present come to about a refresh and a half, see
    Lens._read_presenter, so that much is added. The fast engine reports shown
    as well, the time from a captured frame's timestamp to the refresh that
    showed its picture, which is the whole delay as measured, so nothing is
    added to it. No sum on its meter can stand in for that: for the same
    picture on screen the meter read -15.0 with a second monitor at 60 Hz
    beside the 120 Hz one and -6.6 with one monitor. The timestamp names a
    refresh still to come, so shown reads a refresh below zero where the
    picture is on screen before it, and a delay cannot be negative."""
    if shown is not None:
        return max(0.0, shown)
    return max(0.0, meter + 1.5 * 1000.0 / float(DISPLAY_HZ))


# Fullscreen fills the monitor the lens is on, see fullscreen_rect, and shows
# the picture alone, with no title bar. It is an ini flag rather than a window
# state because the lens has to restart to change size, and the windowed
# geometry in the state file must survive the round trip, so the fullscreen
# lens keeps its pass count in a file of its own. The taskbar list's entry for
# fullscreen, with no lens running to take it, starts this one fullscreen too.
FULLSCREEN = (str(_INI.get("fullscreen", "0")).strip().lower() in ("1", "yes", "on", "true")
              or _DO_START == "fullscreen")
FULL_STATE = os.path.join(DATA_DIR, "lens-state-fullscreen.txt")

# Which presenter draws a fullscreen lens. fast, the default, asks for the fast
# engine, lens-fast.exe: a D3D12 program of the lens's own that captures on the
# GPU and calls the neural model directly, through the Cost Scaler's proxy, with
# no ReShade in it. It speaks the presenter's protocol, so the lens drives
# either the same way. stack is the presenter every windowed lens has. This is
# the wish only: Lens.engine_wanted decides at each start, since the fast engine
# also needs its exe, the proxy's files, and a run in which it has not failed.
FULLSCREEN_ENGINE = str(_INI.get("fullscreen_engine", "fast")).strip().lower()
if FULLSCREEN_ENGINE not in ("fast", "stack"):
    FULLSCREEN_ENGINE = "fast"


def _set_fullscreen_engine(mode):
    """Change the engine a fullscreen lens asks for, from Settings, and record
    it in the ini, where the default is left unwritten. The caller restarts the
    picture."""
    global FULLSCREEN_ENGINE
    FULLSCREEN_ENGINE = mode
    _save_ini("fullscreen_engine", None if mode == "fast" else mode)


# The fast engine's quality steps, from 0 to 4. Toward the lower steps the
# network works on a smaller copy of the picture, which costs less power and
# loses some of the fine detail the network adds. The original's own detail is
# kept at every step, since the engine puts the network's change onto the
# full-size original. It is fast_quality in the ini. With that set, the step
# goes to the engine as --quality N when it starts. With none set the engine is
# given no --quality and takes its own default, _default_quality, which it
# names in its ready line. A step chosen while it runs is said as "quality N".
FAST_QUALITY_NAMES = ("Lowest power", "Low power", "Performance", "Balanced", "Quality")
# What the step does, for Settings and the NR settings panel. Like every text in
# Settings it says what the setting does and no more: the watts of each step and
# the pictures it was measured over are in docs/NOTES.md, Frames a second and
# power at each step.
FAST_QUALITY_WORDS = ("A lower step has the network work on a smaller copy of the picture, which saves power and "
                      "gives up some of the fine detail it adds. Until you choose a step, a picture larger than "
                      "2560x1440 starts at Balanced and a smaller one at Quality.")


def _default_quality(cw, ch):
    """The quality step of a fullscreen picture this size where the ini names
    none, in this one place. Balanced for a picture larger than 2560x1440 in
    width or in height: the network works on a downscaled copy of such a picture
    at every step, and no loss was seen at Balanced. Quality for a picture that
    fits within 2560x1440: there the network runs at the picture's own size, and
    any step down takes away some of the fine texture it adds. The engine
    applies the same rule by itself when it is given no --quality."""
    return 3 if cw > 2560 or ch > 1440 else 4


try:
    FAST_QUALITY = int(float(str(_INI["fast_quality"])))
    FAST_QUALITY = max(0, min(len(FAST_QUALITY_NAMES) - 1, FAST_QUALITY))
except (KeyError, ValueError, OverflowError):
    FAST_QUALITY = None         # none set: the default for the picture's size


def _set_fast_quality(step):
    """Change the fast engine's quality step, from Settings or the NR settings
    panel, and record it in the ini. None is the default for the picture's
    size, which is left unwritten. The caller tells the engine."""
    global FAST_QUALITY
    FAST_QUALITY = step
    _save_ini("fast_quality", None if step is None else str(step))


# What the title bar shows beside the size. size, the default, is the size
# alone. fps is the rate of new pictures the presenter shows, averaged over the
# last few seconds, which follows the rate the content under the lens hands it
# up to the frame rate limit. It is off by default, since read as the lens's own
# rate it misleads. detail is the frames captured and the new pictures shown,
# each per second.
READOUT = str(_INI.get("readout", "size")).strip().lower()
if READOUT not in ("fps", "detail", "both", "size"):
    READOUT = "size"
# The delay meter on the title bar, on unless the ini says latency = 0. See
# Lens._read_presenter for what it measures and what it adds.
LATENCY = str(_INI.get("latency", "1")).strip().lower() in ("1", "yes", "on", "true")
TITLE_SIZE = str(_INI.get("title_size", "1")).strip().lower() in ("1", "yes", "on", "true")
TITLE_STYLE = str(_INI.get("title_style", "0")).strip().lower() in ("1", "yes", "on", "true")
TITLE_INTENSITY = str(_INI.get("title_intensity", "0")).strip().lower() in ("1", "yes", "on", "true")
STYLE_NAMES = {"0": "Default", "1": "Natural", "2": "Cinematic"}     # the add-on's NRStyle
# What the lens's own NR settings panel holds beside the style, each a key of
# the add-on's section of ReShade.ini, where both engines read them: the name on
# the panel, the lowest and the highest value, and the model's own default, which
# stands where the section has no value. The ranges are the ones the Cost
# Scaler's ini gives for the model's settings. Skin structure also takes -1,
# its default, which leaves it to the model.
NR_SLIDERS = (
    ("NRIntensity", "Intensity", 0.0, 2.0, 1.0),
    ("NRLocalTone", "Local tone", 0.0, 2.0, 1.0),
    ("NRLocalStructure", "Local structure", 0.0, 2.0, 1.0),
    ("NRSkinStructure", "Skin structure", 0.0, 2.0, -1.0),
)

# Keep the picture ready while nothing changes: the presenter presents thirty
# times a second over a still instead of falling to four after ten seconds, so
# the first frame after any pause is on time. Off unless the ini says ready = 1.
# What it costs, and what the pause costs without it, is in lens_presenter.py.
READY = str(_INI.get("ready", "0")).strip().lower() in ("1", "yes", "on", "true")
# At most this many new pictures a second, 0 for no limit. The presenter shows the
# newest frame when its turn comes and asks the capture for fewer, so the neural
# pass runs proportionally less often. Settings offers 60 and 30; the ini takes
# any rate from 10 to 240 as max_fps.
try:
    MAX_FPS = int(float(str(_INI.get("max_fps", "0") or "0")))
except (ValueError, OverflowError):
    MAX_FPS = 0
MAX_FPS = 0 if MAX_FPS <= 0 else max(10, min(240, MAX_FPS))
# How finely the motion estimator works out movement between frames: on the
# full picture, or on a half or a quarter of it on each side, which costs the
# card less and leaves text that moves fast with a faint double. Full unless the
# ini says motion_detail = half or quarter. See _write_motion_detail.
MOTION_DETAIL = str(_INI.get("motion_detail", "full")).strip().lower()
if MOTION_DETAIL not in ("full", "half", "quarter"):
    MOTION_DETAIL = "full"
# Copy the joined before and after to the clipboard when a screenshot is saved.
CLIP_SHOTS = str(_INI.get("clipboard_shots", "0")).strip().lower() in ("1", "yes", "on", "true")
# The note a lens shows as it goes fullscreen, see Lens.show_note. Its Don't
# show this again writes fullscreen_note = 0 the moment it is ticked, and
# Settings, Fullscreen switches it on again.
FULLSCREEN_NOTE = str(_INI.get("fullscreen_note", "1")).strip().lower() not in ("0", "no", "off", "false")
NOTE_WORDS = "In fullscreen the lens itself is invisible, but it goes on applying DLSS 5 to the screen."
# its first line in place of that one while Neural Rendering is off, with the
# keys that bring it back as they are set, see Lens.note_first
NOTE_OFF_WORDS = "In fullscreen the lens itself is invisible. Neural Rendering is off now, and %s brings it back."
NOTE_TASKBAR = ("A right click on the lens's taskbar button lists the lens menu, the NR settings and fullscreen "
                "as well.")
# Said on the notice while a program has the screen in exclusive fullscreen,
# which no window of another program is drawn over, see Lens.check_exclusive
EXCLUSIVE_WORDS = ("A program is in exclusive fullscreen, and the lens cannot draw over that. Set the program to "
                   "borderless windowed and the lens can.")
# Said on the notice when a fullscreen lens keeps running well behind the
# program in front, with its delay in whole ms, see Lens.check_behind. A
# program that keeps the card fully busy while it has the focus gets the card
# first, and the lens's work waits for each of its frames. Under a frame rate
# limit of its own with room to spare it pauses after each frame, and the lens
# has its turn then. Settings, Fullscreen switches it off, fs_behind_warn = 0,
# and on again, the default, which is left unwritten.
BEHIND_WORDS = ("The lens is running about %.0f ms behind the program in front, most likely because that program "
                "keeps the graphics card fully busy. A frame rate limit in that program, set a little below the "
                "rate it reaches, lets the lens keep up. This warning can be switched off in Settings, Fullscreen.")
FS_BEHIND_WARN = str(_INI.get("fs_behind_warn", "1")).strip().lower() not in ("0", "no", "off", "false")


def _set_fs_behind_warn(on):
    """Switch the warning that a fullscreen lens runs behind on or off, from
    Settings, and record it in the ini, where on is the default and is left
    unwritten. It applies from the next summary, see Lens.check_behind."""
    global FS_BEHIND_WARN
    FS_BEHIND_WARN = bool(on)
    _save_ini("fs_behind_warn", None if FS_BEHIND_WARN else "0")


def _either(words):
    """Alternatives as a person lists them: A, A or B, A, B or C."""
    words = [wd for wd in words if wd]
    return ", ".join(words[:-1]) + " or " + words[-1] if len(words) > 1 else "".join(words)


# The on-screen readout of a fullscreen lens, see Lens.show_readout: what it
# shows, as fs_readout lists it in the ini, nothing by default, and the corner
# of the lens's monitor it shows in, fs_readout_at, the top right by default.
# Its key shows and hides it, see Lens.toggle_readout. What it showed when it
# was last put out, by the key or in Settings, is kept as fs_readout_last, and
# the key brings that back, or FS_READOUT_BACK, the frame rate and the latency,
# where nothing is kept.
FS_READOUT_ITEMS = ("fps", "latency", "step", "passes", "style")
FS_READOUT_CORNERS = ("top right", "top left", "bottom right", "bottom left")
FS_READOUT_BACK = ("fps", "latency")


def _readout_items(text):
    """The readout's items a comma list names, in their own order."""
    named = {wd.strip().lower() for wd in str(text or "").split(",")}
    return tuple(i for i in FS_READOUT_ITEMS if i in named)


FS_READOUT = _readout_items(_INI.get("fs_readout", ""))
FS_READOUT_LAST = _readout_items(_INI.get("fs_readout_last", "")) or FS_READOUT_BACK
FS_READOUT_AT = " ".join(str(_INI.get("fs_readout_at", "top right")).lower().replace("_", " ").replace("-", " ")
                         .split())
if FS_READOUT_AT not in FS_READOUT_CORNERS:
    FS_READOUT_AT = "top right"


def _set_fs_readout(items, at):
    """The readout's items and corner, from Settings or the readout's key,
    recorded in the ini, where the defaults, nothing, the top right and
    FS_READOUT_BACK, are left unwritten. A readout that goes out keeps what
    it showed, for its key to bring back. The caller shows the readout anew."""
    global FS_READOUT, FS_READOUT_AT, FS_READOUT_LAST
    items = _readout_items(",".join(items))
    if FS_READOUT and not items:
        FS_READOUT_LAST = FS_READOUT
    FS_READOUT = items
    FS_READOUT_AT = at if at in FS_READOUT_CORNERS else "top right"
    _save_ini("fs_readout", ",".join(FS_READOUT) or None)
    _save_ini("fs_readout_at", None if FS_READOUT_AT == "top right" else FS_READOUT_AT)
    _save_ini("fs_readout_last", None if FS_READOUT_LAST == FS_READOUT_BACK else ",".join(FS_READOUT_LAST))


# Check GitHub for a newer release when the lens starts, at most once a day.
# Off unless the ini says check_updates = 1, since it is a request to a server.
CHECK_UPDATES = str(_INI.get("check_updates", "0")).strip().lower() in ("1", "yes", "on", "true")
AUTO_UPDATE = str(_INI.get("auto_update", "0")).strip().lower() in ("1", "yes", "on", "true")
RELEASES_API = "https://api.github.com/repos/Leaps-Bounds/neural-lens/releases"
RELEASES_PAGE = "https://github.com/Leaps-Bounds/neural-lens/releases"


def _version_tuple(text):
    out = []
    for part in str(text).lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _latest_release():
    """(version, page url) of the newest release on GitHub, prereleases
    included since every release so far is one, or None when it cannot be read."""
    import urllib.request
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "neural-lens/" + __version__,
                                                        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        releases = json.loads(r.read().decode("utf-8"))
    for rel in releases:
        if not rel.get("draft") and rel.get("tag_name"):
            # the installer among the release's files, by its name and by its
            # home on GitHub, so nothing else is ever downloaded
            asset_url = asset_size = None
            for a in rel.get("assets") or []:
                name, link = str(a.get("name", "")), str(a.get("browser_download_url", ""))
                if (name.startswith("NeuralLens-Setup-") and name.endswith(".exe")
                        and link.startswith(RELEASES_PAGE + "/download/")):
                    asset_url, asset_size = link, int(a.get("size") or 0)
                    break
            return rel["tag_name"].lstrip("vV"), rel.get("html_url") or RELEASES_PAGE, asset_url, asset_size
    return None


# ---- global hotkeys
# Each action can have a key combination that works from anywhere, registered
# with RegisterHotKey on a thread of its own, since Tk's loop never hands
# WM_HOTKEY out. A registered combination is taken from every other program
# while the lens runs, which is why none is set until the user sets it, and why
# Home, F5 and F6 on their own are refused: ReShade reads Home and F5 from the
# presenter's own messages and the add-on reads F6 from the keyboard, so
# taking them would silence the overlay, its screenshot and the NR toggle.
#
# The last four actions are for a fullscreen lens, which has no title bar to
# click: they bring up the lens menu and the NR settings, turn Neural Rendering
# off and on, and show or hide the on-screen readout. They have keys from the
# start, HOTKEY_DEFAULTS, and are held only while the lens is fullscreen and in
# view, see Lens.hotkeys_wanted, so a windowed or minimised lens takes none of
# them from any other program.
# Those keys are single keys that every keyboard has, with no modifier:
# RegisterHotKey takes only the last key of a combination from other programs,
# so with Ctrl+Home the game would still get the Ctrl, which many games act on.
# A value the ini holds is kept, so only the defaults are these, and a default
# goes only to an action whose key no other action has, see _hotkeys_from_ini.
HOTKEY_ACTIONS = (
    ("screenshot", "Save before and after"),
    ("add_pass", "Add a pass"),
    ("drop_pass", "Remove a pass"),
    ("quality_up", "Raise the quality step"),
    ("quality_down", "Lower the quality step"),
    ("split", "Live A/B split, on or off"),
    ("minimize", "Minimise, or bring back"),
    ("fullscreen", "Fullscreen, and back"),
    ("hide_bar", "Hide the title bar, and show it again"),
    ("profile", "Next profile"),
    ("ready", "Keep the picture ready, on or off"),
    ("detach", "Detach from the window"),
    ("lens_menu", "The lens menu, while fullscreen"),
    ("nr_panel", "NR settings, while fullscreen"),
    ("nr_toggle", "NR on or off, while fullscreen"),
    ("readout_toggle", "On-screen readout on or off, while fullscreen"),
)
HOTKEY_DEFAULTS = {"lens_menu": "F7", "nr_panel": "F8", "nr_toggle": "F9", "readout_toggle": "F10"}
FULL_HOTKEYS = ("lens_menu", "nr_panel", "nr_toggle", "readout_toggle")     # held only while the lens is fullscreen
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
WM_HOTKEY, QS_ALLINPUT = 0x0312, 0x04FF
VK_BY_NAME = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "backspace": 0x08,
              "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
              "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "pause": 0x13, "scrolllock": 0x91,
              "printscreen": 0x2C, "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE,
              "slash": 0xBF, "backslash": 0xDC, "semicolon": 0xBA, "quote": 0xDE, "backquote": 0xC0,
              "bracketleft": 0xDB, "bracketright": 0xDD, "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D,
              "divide": 0x6F, "decimal": 0x6E}
for _i in range(1, 25):
    VK_BY_NAME["f%d" % _i] = 0x6F + _i
for _i in range(10):
    VK_BY_NAME["numpad%d" % _i] = 0x60 + _i
NAME_BY_VK = {v: k for k, v in VK_BY_NAME.items()}
RESERVED_KEYS = {0x24: "Home opens ReShade's overlay", 0x74: "F5 is ReShade's screenshot",
                 0x75: "F6 toggles Neural Rendering on the ReShade engine"}


def _parse_hotkey(text):
    """'Ctrl+Alt+S' to (modifiers, virtual key), or None when it is not a key."""
    if not text:
        return None
    parts = [p.strip().lower() for p in str(text).replace("-", "+").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "windows", "super"):
            mods |= MOD_WIN
        else:
            return None
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    elif key in VK_BY_NAME:
        vk = VK_BY_NAME[key]
    else:
        return None
    return mods, vk


def _hotkey_text(mods, vk):
    parts = [n for f, n in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win")) if mods & f]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        name = chr(vk)
    else:
        name = NAME_BY_VK.get(vk, "0x%02X" % vk)
        name = name.upper() if name.startswith("f") and name[1:].isdigit() else name.capitalize()
    return "+".join(parts + [name])


def _hotkey_problem(text):
    """Why this combination cannot be used, or None."""
    parsed = _parse_hotkey(text)
    if parsed is None:
        return "not a key"
    mods, vk = parsed
    if not mods and vk in RESERVED_KEYS:
        return RESERVED_KEYS[vk]
    if not mods and not (0x70 <= vk <= 0x87):
        return "needs Ctrl, Alt, Shift or Win, or a function key"
    return None


def _hotkey_from_ini(action, ini=None):
    """The combination the ini holds for an action, or the action's default
    where the ini has no line for it. none, off or nothing after the sign is no
    combination, which is how an action with a default is left without one.
    ini is neural-lens.ini as read, the one read at the start where not given."""
    text = (_INI if ini is None else ini).get("hotkey_" + action)
    if text is None:
        return HOTKEY_DEFAULTS.get(action, "")
    text = str(text).strip()
    return "" if text.lower() in ("none", "off") else text


# The defaults left out, see _hotkeys_from_ini, each under the action that has
# its combination, which the Hotkeys page names on the row left empty
HOTKEY_LEFT_OUT = {}


def _hotkeys_from_ini(ini=None):
    """Every action's combination, as _hotkey_from_ini gives it, except that a
    default goes only to an action no other action has the same combination
    for. 0.5.1 let any action have a function key alone, so an ini of then can
    hold hotkey_split = F9, and the action the ini names keeps the key. A
    default left out goes into HOTKEY_LEFT_OUT, which this fills afresh. ini
    is neural-lens.ini as read, the one read at the start where not given."""
    ini = _INI if ini is None else ini
    keys = {a: _hotkey_from_ini(a, ini) for a, _ in HOTKEY_ACTIONS}
    HOTKEY_LEFT_OUT.clear()
    for a, default in HOTKEY_DEFAULTS.items():
        if ini.get("hotkey_" + a) is not None:
            continue                    # the ini's own value, kept as it is
        holder = next((b for b, text in keys.items() if b != a and text and not _hotkey_problem(text)
                       and _parse_hotkey(text) == _parse_hotkey(default)), None)
        if holder is not None:
            keys[a] = ""
            HOTKEY_LEFT_OUT[a] = holder
    return keys


def _left_out_line(action):
    return ("hotkey_%s is left without its default %s, which hotkey_%s has in neural-lens.ini"
            % (action, HOTKEY_DEFAULTS[action], HOTKEY_LEFT_OUT[action]))


def _hotkey_defaults_again():
    """After Settings has written the hotkeys into neural-lens.ini, the rule of
    _hotkeys_from_ini again, as the next start will apply it, for each action
    with a default that the ini has no line for, so this session holds what
    the next one will. Such an action has its default where no other action
    has that combination now, and none where one does. Returns the actions
    whose combination this changed, each of which the log names."""
    ini = _read_ini()
    keys = _hotkeys_from_ini(ini)
    changed = []
    for a in HOTKEY_DEFAULTS:
        if ini.get("hotkey_" + a) is not None or keys[a] == HOTKEYS.get(a, ""):
            continue
        HOTKEYS[a] = keys[a]
        changed.append(a)
        print(_left_out_line(a) if a in HOTKEY_LEFT_OUT
              else "hotkey_%s has its default %s again, which no other action has now" % (a, keys[a]), flush=True)
    return changed


def _hotkey_holder(action, keys=None):
    """The action ahead of this one in HOTKEY_ACTIONS that has the same
    combination, of HOTKEYS or of keys where given, or None. Hotkeys takes
    the actions in that order and skips a combination it holds already, so
    the lens holds such a key for that action, see Hotkeys.dup."""
    keys = HOTKEYS if keys is None else keys
    mine = _parse_hotkey(keys.get(action, ""))
    if mine is None:
        return None
    for b, _label in HOTKEY_ACTIONS:
        if b == action:
            return None
        text = keys.get(b, "")
        if text and not _hotkey_problem(text) and _parse_hotkey(text) == mine:
            return b
    return None


HOTKEYS = _hotkeys_from_ini()
for _a in HOTKEY_LEFT_OUT:
    print(_left_out_line(_a), flush=True)
HOTKEY_LABELS = dict(HOTKEY_ACTIONS)
# The keys that work the lens menu, the NR settings panel and the note while one
# of them is up over a fullscreen lens, held only then, see Lens.nav_wanted. They
# are the lens's own, never set in Settings, so they are the one place a key
# with no modifier that is not a function key is registered.
NAV_KEYS = {"nav_up": "Up", "nav_down": "Down", "nav_left": "Left", "nav_right": "Right", "nav_enter": "Enter",
            "nav_escape": "Escape"}
NAV_VK = {a: _parse_hotkey(text)[1] for a, text in NAV_KEYS.items()}
NAV_REPEAT = ("nav_up", "nav_down", "nav_left", "nav_right")     # these repeat while held, see Hotkeys


class Hotkeys:
    """The listener: a thread with a message queue of its own, where the
    combinations are registered and WM_HOTKEY arrives. Actions go into a queue
    the lens drains on its timer; a combination another program already holds
    is reported in failed, one the lens holds already for an action ahead of
    it in the mapping is reported in dup, under that action, and registered
    has the ones that are held, each under the number its WM_HOTKEY carries.

    An action a mapping leaves out, such as a key of a fullscreen lens while
    the lens is in a window, keeps what failed and dup knew of it, so that
    another program's hold on its key, or the lens's own for another action,
    is still known while the key is let go. Its record changes only when a
    mapping has the action again, or when its combination changes, which
    set names in forget."""

    def __init__(self):
        import queue
        self.fired = queue.Queue()
        self.wanted = queue.Queue()
        self.failed = {}
        self.dup = {}               # {action: the action the lens holds the same combination for}
        self.registered = {}
        self.last = (None, 0.0)     # the action that fired last, and when
        self.stopping = False
        self.tid = 0
        threading.Thread(target=self._run, daemon=True).start()

    def set(self, mapping, forget=()):
        """Hold the combinations of mapping, {action: text}, and no others.
        forget names the actions whose combination has changed since, whose
        records go even where mapping leaves them out."""
        self.wanted.put((dict(mapping), frozenset(forget)))
        if self.tid:
            u.PostThreadMessageW(self.tid, 0, 0, 0)     # WM_NULL, to end the wait

    def stop(self):
        self.stopping = True
        if self.tid:
            u.PostThreadMessageW(self.tid, 0, 0, 0)

    def _run(self):
        self.tid = k32.GetCurrentThreadId()
        registered = {}
        msg = w.MSG()
        while not self.stopping:
            while not self.wanted.empty():
                mapping, forget = self.wanted.get()
                for i in registered:
                    u.UnregisterHotKey(None, i)
                # the records of an action the mapping leaves out stay, see above
                failed = {a: text for a, text in self.failed.items() if a not in mapping and a not in forget}
                dup = {a: b for a, b in self.dup.items() if a not in mapping and a not in forget and b not in forget}
                registered, held = {}, {}
                for n, (action, text) in enumerate(mapping.items()):
                    parsed = (_parse_hotkey(text) if text and (action in NAV_KEYS or not _hotkey_problem(text))
                              else None)
                    if parsed is None:
                        continue
                    mods, vk = parsed
                    if parsed in held:
                        # the lens holds it already, for an action ahead of
                        # this one, which is not another program holding it
                        dup[action] = held[parsed]
                        continue
                    # an arrow key held down repeats, so a slider on the NR
                    # settings panel moves on while it is held. Every other
                    # key acts once a press
                    once = 0 if action in NAV_REPEAT else MOD_NOREPEAT
                    if u.RegisterHotKey(None, n + 1, mods | once, vk):
                        registered[n + 1] = action
                        held[parsed] = action
                    else:
                        failed[action] = text
                self.failed, self.dup, self.registered = failed, dup, dict(registered)
            while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY and msg.wParam in registered:
                    self.last = (registered[msg.wParam], time.perf_counter())
                    self.fired.put(registered[msg.wParam])
            u.MsgWaitForMultipleObjectsEx(0, None, 100, QS_ALLINPUT, 0)
        for i in registered:
            u.UnregisterHotKey(None, i)


# ---- the listener for --do
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                ("lpszClassName", w.LPCWSTR)]


for _name, _res, _args in (
        ("RegisterClassW", w.ATOM, [ctypes.POINTER(WNDCLASSW)]),
        ("UnregisterClassW", w.BOOL, [w.LPCWSTR, w.HINSTANCE]),
        ("CreateWindowExW", w.HWND, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]),
        ("DestroyWindow", w.BOOL, [w.HWND]),
        ("DefWindowProcW", LRESULT, [w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM]),
        ("ChangeWindowMessageFilterEx", w.BOOL, [w.HWND, ctypes.c_uint, w.DWORD, ctypes.c_void_p]),
        ("GetMessageW", ctypes.c_int, [ctypes.POINTER(w.MSG), w.HWND, ctypes.c_uint, ctypes.c_uint]),
        ("TranslateMessage", w.BOOL, [ctypes.POINTER(w.MSG)]),
        ("DispatchMessageW", LRESULT, [ctypes.POINTER(w.MSG)]),
        ("PostThreadMessageW", w.BOOL, [w.DWORD, ctypes.c_uint, w.WPARAM, w.LPARAM]),
        ("GetCursorPos", w.BOOL, [ctypes.POINTER(w.POINT)]),
        ("MonitorFromWindow", ctypes.c_void_p, [w.HWND, w.DWORD]),
        ("MonitorFromPoint", ctypes.c_void_p, [w.POINT, w.DWORD])):
    getattr(_u32, _name).restype, getattr(_u32, _name).argtypes = _res, _args
_k32.GetModuleHandleW.restype, _k32.GetModuleHandleW.argtypes = w.HMODULE, [w.LPCWSTR]


class Commands:
    """The lens's ear for --do: a thread with a window of its own that is never
    seen and only takes messages, which a process started with --do finds by
    its class and its title, DO_NAME. A word that arrives goes into a queue
    the lens drains on its timer, see Lens.poll_commands, so the sender has
    its answer at once, also while the lens is busy with a presenter's start."""

    def __init__(self, lens):
        import queue
        self.lens = lens
        self.asked = queue.Queue()
        self.started = int(time.time() * 1000)
        self.hwnd = None
        self.error = None           # Windows' error number, had the window not been made
        self.stopping = False
        self.tid = 0
        self.proc = WNDPROC(self._message)      # kept, since Windows calls it for as long as the window lives
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stopping = True
        if self.tid:
            _u32.PostThreadMessageW(self.tid, 0x0012, 0, 0)        # WM_QUIT, to end the wait

    def rank(self):
        """Where this lens stands when several are running and a word names
        none, as one number: in view, fullscreen, on the monitor the pointer is
        on, and the time of its start, in that order of weight, see
        _send_command. It is worked out on the listener's own thread, from the
        lens's plain attributes and what Windows says, with no call into Tk."""
        lens = self.lens
        stages = lens.stages
        near = False
        if stages:
            pt = w.POINT()
            _u32.GetCursorPos(ctypes.byref(pt))
            mon = _u32.MonitorFromWindow(stages[0]["hwnd"], 0)     # none where the picture is on no monitor
            near = bool(mon) and mon == _u32.MonitorFromPoint(pt, 0)
        return ((0 if lens.minimized else 1) << 62 | (1 if lens.fullscreen else 0) << 61
                | (1 if near else 0) << 60 | self.started)

    def _message(self, hwnd, msg, wp, lp):
        if msg != DO_MESSAGE:
            return _u32.DefWindowProcW(hwnd, msg, wp, lp)
        try:
            if self.lens.closing:
                return 0                    # a lens on its way out is no lens to the sender
            if wp == 0:
                return self.rank()
            if 1 <= wp <= len(DO_WORDS):
                self.asked.put(DO_WORDS[wp - 1])
                return 1
        except Exception:
            pass
        return 0

    def _run(self):
        self.tid = k32.GetCurrentThreadId()
        wc = WNDCLASSW()
        wc.lpfnWndProc = self.proc
        wc.hInstance = _k32.GetModuleHandleW(None)
        wc.lpszClassName = DO_CLASS
        _u32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = _u32.CreateWindowExW(0, DO_CLASS, DO_NAME, 0, 0, 0, 0, 0, HWND_MESSAGE, None,
                                         wc.hInstance, None)
        if not self.hwnd:
            self.error = ctypes.get_last_error()
            _u32.UnregisterClassW(DO_CLASS, wc.hInstance)
            return
        # a lens started as administrator still hears a process that was not:
        # Windows drops a message from below unless the window lets it through
        _u32.ChangeWindowMessageFilterEx(self.hwnd, DO_MESSAGE, 1, None)       # MSGFLT_ALLOW
        msg = w.MSG()
        while not self.stopping and _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _u32.TranslateMessage(ctypes.byref(msg))
            _u32.DispatchMessageW(ctypes.byref(msg))
        _u32.DestroyWindow(self.hwnd)
        self.hwnd = None
        _u32.UnregisterClassW(DO_CLASS, wc.hInstance)


# ---- the taskbar button's list
# A right click on the lens's taskbar button shows the button's jump list,
# which Windows keeps for the program's id, see APP_ID, in a file of its own in
# the user's Recent\CustomDestinations folder. The lens puts the three entries
# of DO_ENTRIES there as tasks, which Windows lists under a heading of its own.
# A category under a heading of the lens's own is refused where Windows is set
# not to show recently opened items, and tasks show there all the same:
# measured, AppendCategory gave E_ACCESSDENIED and AddUserTasks went through.
# The shell's objects are called through ctypes, each method by its place in
# the object's table.
class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


class PROPVARIANT(ctypes.Structure):        # as far as a text needs it
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("text", ctypes.c_wchar_p), ("rest", ctypes.c_void_p)]


_ole = ctypes.WinDLL("ole32")
for _name, _res, _args in (
        ("CoInitializeEx", ctypes.c_long, [ctypes.c_void_p, w.DWORD]),
        ("CoUninitialize", None, []),
        ("CLSIDFromString", ctypes.c_long, [w.LPCWSTR, ctypes.POINTER(GUID)]),
        ("CoCreateInstance", ctypes.c_long, [ctypes.POINTER(GUID), ctypes.c_void_p, w.DWORD, ctypes.POINTER(GUID),
                                             ctypes.POINTER(ctypes.c_void_p)])):
    getattr(_ole, _name).restype, getattr(_ole, _name).argtypes = _res, _args


def _guid(text):
    g = GUID()
    _ole.CLSIDFromString(text, ctypes.byref(g))
    return g


def _com(obj, n, types, *args):
    """Call the method at place n of a COM object's table. Returns what it
    returned, and raises OSError with the number where that says it failed."""
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    hr = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[n])(obj, *args)
    if hr < 0:
        raise OSError("0x%08X" % (hr & 0xFFFFFFFF))
    return hr


def _com_object(clsid, iid):
    obj = ctypes.c_void_p()
    hr = _ole.CoCreateInstance(ctypes.byref(_guid(clsid)), None, 1, ctypes.byref(_guid(iid)), ctypes.byref(obj))
    if hr < 0:
        raise OSError("0x%08X" % (hr & 0xFFFFFFFF))
    return obj


def _do_command_line(word):
    """How an entry of the taskbar list starts this program with its word:
    (program, arguments). Installed, the program is the lens's own exe. From
    source it is the Python that runs the lens, as pythonw where there is one,
    which opens no console, with this script. Where this lens's stack came
    from its command line or from NEURAL_LENS_STACK, the entry names it with
    --stack-dir, since an entry that finds no lens running starts the lens
    itself. A stack found in the ini or beside the program is found again
    without it, and a --stack-dir would outrank a later change in Settings."""
    args = ["--do", word]
    if STACK_DIR and (any(a in ("--stack-dir", "--mpv-dir") for a in sys.argv)
                      or os.environ.get("NEURAL_LENS_STACK")):
        args += ["--stack-dir", STACK_DIR]
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(args)
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(exe):
        exe = sys.executable
    return exe, subprocess.list2cmdline([os.path.abspath(__file__)] + args)


def _task_link(word, text):
    """An entry for the list, which is a shell link: this program with --do and
    the word, under the entry's text, with the lens's icon."""
    exe, args = _do_command_line(word)
    icon = exe if getattr(sys, "frozen", False) else _asset("neural-lens.ico")
    link = _com_object("{00021401-0000-0000-C000-000000000046}",        # a shell link,
                       "{000214F9-0000-0000-C000-000000000046}")        # as IShellLinkW
    _com(link, 20, [w.LPCWSTR], exe)                                    # SetPath
    _com(link, 11, [w.LPCWSTR], args)                                   # SetArguments
    _com(link, 9, [w.LPCWSTR], _script_dir())                           # SetWorkingDirectory
    _com(link, 17, [w.LPCWSTR, ctypes.c_int], icon, 0)                  # SetIconLocation
    _com(link, 7, [w.LPCWSTR], text)                                    # SetDescription, shown on a hover
    # the text the list shows is the link's title, which is a property of it
    store = ctypes.c_void_p()
    _com(link, 0, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],                      # QueryInterface
         ctypes.byref(_guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")), ctypes.byref(store))    # for IPropertyStore
    key = PROPERTYKEY(_guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 2)       # PKEY_Title
    value = PROPVARIANT(31, 0, 0, 0, text, None)                                # VT_LPWSTR
    _com(store, 6, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)],
         ctypes.byref(key), ctypes.byref(value))                        # SetValue
    _com(store, 7, [])                                                  # Commit
    _com(store, 2, [])                                                  # Release
    return link


def _taskbar_list(on=True):
    """Put the three entries of DO_ENTRIES on the taskbar button's list, or
    with on False take the list away. Returns None when Windows took it, else
    what went wrong, as text. Setting a list that is there and taking away one
    that is not are both harmless, measured.

    The shell's objects want a thread that COM was started on, so this runs on
    a thread of its own, which is waited for, five seconds at most: nothing
    here may hold the lens up."""
    result = []

    def work():
        started = _ole.CoInitializeEx(None, 2) >= 0         # COINIT_APARTMENTTHREADED
        try:
            dest = _com_object("{77F10CF0-3DB5-4966-B520-B7C54FD35ED6}",        # the list,
                               "{6332DEBF-87B5-4670-90C0-5E57B408A49E}")        # as ICustomDestinationList
            if APP_ID:                      # with none it is the list of the id Windows gives this exe
                _com(dest, 3, [w.LPCWSTR], APP_ID)                              # SetAppID
            if on:
                slots, removed = ctypes.c_uint(), ctypes.c_void_p()
                _com(dest, 4, [ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                     ctypes.byref(slots), ctypes.byref(_guid("{92CA9DCD-5622-4BBA-A805-5E9F541BD8C9}")),
                     ctypes.byref(removed))                                     # BeginList
                tasks = _com_object("{2D3468C1-36A7-43B6-AC24-D3F02FD9607A}",   # a collection of objects,
                                    "{5632B1A4-E38A-400A-928A-D4CD63230295}")   # as IObjectCollection
                for word, text in DO_ENTRIES:
                    link = _task_link(word, text)
                    _com(tasks, 5, [ctypes.c_void_p], link)                     # AddObject
                    _com(link, 2, [])                                           # Release
                _com(dest, 7, [ctypes.c_void_p], tasks)                         # AddUserTasks
                _com(dest, 8, [])                                               # CommitList
                for obj in (tasks, removed):
                    if obj:
                        _com(obj, 2, [])
            else:
                _com(dest, 10, [w.LPCWSTR], APP_ID)                             # DeleteList
            _com(dest, 2, [])
            result.append(None)
        except Exception as exc:
            result.append(str(exc) or type(exc).__name__)
        finally:
            if started:
                _ole.CoUninitialize()

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(5.0)
    return result[0] if result else "Windows gave no answer within five seconds"


def _other_lens():
    """Whether another lens is running beside this one, by its listening window."""
    return any(_window_pid(h) != os.getpid() for h in _lens_windows())


u = ctypes.windll.user32
k32 = ctypes.windll.kernel32
# Per monitor DPI aware, version 2, so every coordinate the lens uses is a
# physical pixel on whichever monitor it is on. System DPI awareness keeps the
# DPI the session logged on with and lives in a virtualized coordinate space:
# a 1400x760 lens on a monitor whose scaling differed from that produced a
# 1680x912 picture, exactly the ratio of the two scalings, while the lens
# believed its window was 1400x760.
try:
    u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    u.SetProcessDPIAware()
try:
    ctypes.windll.winmm.timeBeginPeriod(1)   # default granularity is 15.6 ms
except Exception:
    pass
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.SetWindowLongPtrW.restype = ctypes.c_longlong

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_THICKFRAME, WS_MAXIMIZEBOX = 0x00040000, 0x00010000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x08000000
WS_EX_TOPMOST = 0x00000008
WDA_EXCLUDEFROMCAPTURE = 0x00000011
HWND_TOPMOST = ctypes.c_void_p(-1)          # pointer sized, NOT int -1
HWND_NOTOPMOST = ctypes.c_void_p(-2)
HWND_TOP = 0
GW_HWNDPREV, GA_ROOT = 3, 2
u.WindowFromPoint.argtypes = [w.POINT]      # a POINT by value, not a pointer to one
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_FRAMECHANGED = 0x0020
SW_HIDE, SW_SHOWNA = 0, 8


def _save_ini(key, value):
    """Write one key into neural-lens.ini beside the script, keeping the rest.

    A value of None removes the key, so a setting put back to its default
    follows the default again rather than pinning today's value.
    """
    path = _ini_path()
    lines, done = [], False
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                bare = line.strip()
                if bare and bare[0] not in "#;[" and "=" in bare \
                        and bare.split("=", 1)[0].strip().lower() == key:
                    if value is not None:
                        lines.append("%s = %s\n" % (key, value))
                    done = True
                else:
                    lines.append(line)
    except OSError:
        pass
    if not done and value is not None:
        lines.append("%s = %s\n" % (key, value))
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


def archive_logs():
    """Keep the PREVIOUS session's logs before the presenter overwrites them.
    Without this, launching again destroys the only evidence of a failure.

    ReShade rotates to ReShade.log1, ReShade.log2 and so on when the first file
    is already locked, so every one of them is kept, along with the Feed's and
    the Cost Scaler's logs.
    """
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        names = [n for n in os.listdir(STACK_DIR)
                 if n.startswith("ReShade.log") or n in ("dlss5-feed.log", "nvngx_dlssnr_proxy.log")]
        for name in sorted(names):
            src = os.path.join(STACK_DIR, name)
            if os.path.isfile(src) and os.path.getsize(src) > 0:
                shutil.copy2(src, os.path.join(LOGDIR, "%s-%s" % (stamp, name)))
        # the presenter's stderr is appended to for the life of a session, and
        # the pruning below sorts by name, so a file not carrying a stamp is
        # never reached and would grow without bound. Roll it into the archive.
        prev = os.path.join(LOGDIR, "presenter-stderr.log")
        if os.path.isfile(prev):
            if os.path.getsize(prev) > 0:
                os.replace(prev, os.path.join(LOGDIR, "%s-presenter-stderr.log" % stamp))
            else:
                os.remove(prev)
        files = sorted(os.listdir(LOGDIR))
        while len(files) > 80:
            os.remove(os.path.join(LOGDIR, files.pop(0)))
    except Exception:
        pass


def _own_windows():
    """Every visible top-level window owned by this process.

    Nothing of ours may be in the picture the presenter captures. Listing them
    by name cannot work, because the menu, the settings dialog and any message
    box are created and destroyed on demand.
    """
    pid = k32.GetCurrentProcessId()
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if u.IsWindowVisible(h):
            p = w.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid:
                hits.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hits


def find_window(pid, cls="GLFW30"):
    """The visible window of the class that belongs to the process, the moment
    it is visible, whatever its title. The presenter's window class is glfw's,
    and the fast engine's is its own, FAST_CLASS."""
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        c = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, c, 256)
        if c.value != cls:
            return True
        p = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            hits.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


u.OpenInputDesktop.restype = w.HANDLE       # pointer sized, as every handle
u.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD,
                                        ctypes.POINTER(w.DWORD)]
u.CloseDesktop.argtypes = [w.HANDLE]


def desktop_is_the_users():
    """Whether the desktop that takes the keyboard and mouse is the one programs
    draw on. With the computer locked, or while Windows shows a prompt on its
    secure desktop, it is not, and a screen capture then brings no frames:
    measured, every presenter started under a locked screen reported its capture
    lost four seconds later. A name that cannot be read counts as the user's own,
    so a fault in here never holds a recovery back."""
    try:
        h = u.OpenInputDesktop(0, False, 0x0001)        # DESKTOP_READOBJECTS
        if not h:
            return False            # the secure desktop is not ours to open
        name = ctypes.create_unicode_buffer(64)
        need = w.DWORD()
        got = u.GetUserObjectInformationW(h, 2, name, ctypes.sizeof(name) - 2,     # UOI_NAME
                                          ctypes.byref(need))
        u.CloseDesktop(h)
        return not got or name.value.lower() == "default"
    except Exception:
        return True


def _exclusive_fullscreen():
    """Whether a program has the screen in exclusive fullscreen, which no window
    of another program is drawn over, so a lens over it shows nothing. The
    shell says so, QUNS_RUNNING_D3D_FULL_SCREEN: nothing is asked of the
    program itself and no process is opened. False where it cannot say."""
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value == 3
    except Exception:
        pass
    return False


def monitor_rect(x, y):
    """The full rectangle of the monitor containing the point, in pixels."""
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", ctypes.c_ulong)]
    u.MonitorFromPoint.restype = ctypes.c_void_p
    u.MonitorFromPoint.argtypes = [w.POINT, ctypes.c_ulong]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    h = u.MonitorFromPoint(w.POINT(int(x), int(y)), 2)     # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if h and u.GetMonitorInfoW(h, ctypes.byref(mi)):
        r = mi.rcMonitor
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def monitor_hz(hwnd):
    """The refresh rate of the monitor a window is on, or else the one nearest
    to it, as Windows has it now, or None where it cannot be read. It asks
    through _u32, since monitor_rect and work_area set argument types on u's
    GetMonitorInfoW that take their own structure and no other."""
    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", w.RECT), ("rcWork", w.RECT),
                    ("dwFlags", ctypes.c_ulong), ("szDevice", ctypes.c_wchar * 32)]
    try:
        mon = _u32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if mon and _u32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
            return _display_hz(mi.szDevice, None)
    except Exception:
        pass
    return None


def monitor_of(x, y):
    """The monitor containing the point, as (index from 1 in enumeration order,
    left, top). Windows Graphics Capture numbers monitors the same way."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.RECT),
                        ctypes.c_void_p)
    def cb(hmon, hdc, prc, lp):
        r = prc.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return True

    u.EnumDisplayMonitors(None, None, cb, 0)
    for i, (l, t, r, b) in enumerate(found, 1):
        if l <= x < r and t <= y < b:
            return i, l, t
    return 1, 0, 0


def monitor_layout():
    """The monitors as rectangles in enumeration order, the order Windows Graphics
    Capture numbers them in. Compared on a timer to notice displays being added,
    removed or rearranged."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.RECT),
                        ctypes.c_void_p)
    def cb(hmon, hdc, prc, lp):
        r = prc.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return True

    u.EnumDisplayMonitors(None, None, cb, 0)
    return tuple(found)


def work_area(x, y):
    """The work area, the monitor less the taskbar, of the monitor containing the
    point or else the one nearest to it, in pixels."""
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", ctypes.c_ulong)]
    u.MonitorFromPoint.restype = ctypes.c_void_p
    u.MonitorFromPoint.argtypes = [w.POINT, ctypes.c_ulong]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    h = u.MonitorFromPoint(w.POINT(int(x), int(y)), 2)     # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if h and u.GetMonitorInfoW(h, ctypes.byref(mi)):
        r = mi.rcWork
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def fit_rect(x, y, cw, ch, area=None):
    """The lens moved, and shrunk if it has to be, so that the picture, its title
    bar and its border lie inside one monitor's work area.

    The presenter captures one monitor, so a lens hanging over that monitor's
    edge shows a picture that no longer lines up with what is under it, and a
    lens larger than the monitor gets no frames at all. The monitor is the one
    under the lens's centre, or the nearest when that point is on none. A lens
    that has to shrink keeps its proportions. area stands in for the monitor's
    work area when given.
    """
    mx, my, mw, mh = area or work_area(x + cw // 2, y + ch // 2)
    room_w, room_h = mw - 2 * EDGE, mh - BAR - EDGE
    scale = min(1.0, room_w / float(cw), room_h / float(ch))
    if scale < 1.0:
        cw, ch = int(cw * scale), int(ch * scale)
    cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
    x = max(mx + EDGE, min(x, mx + mw - EDGE - cw))
    y = max(my + BAR, min(y, my + mh - EDGE - ch))
    return x, y, cw, ch


def fullscreen_rect(x, y, cw, ch):
    """Where a fullscreen lens puts its picture, given the lens as it is now:
    the whole of the monitor under its middle, from the monitor's top edge,
    less FULL_SHORT rows at the bottom, in even sizes. The taskbar's place is
    covered too, so a fullscreen video behind the lens is covered down to those
    rows."""
    mx, my, mw, mh = monitor_rect(x + cw // 2, y + ch // 2)
    cw, ch = mw - mw % 2, mh - FULL_SHORT
    return mx, my, max(2, cw), max(2, ch - ch % 2)


class PopupMenu:
    """The title bar menu, drawn by the lens itself.

    A native popup only dismisses on an outside click or Escape while its
    owner is the foreground window, and the title bar never activates so that
    the application under the lens keeps the focus. Taking the foreground for
    the menu's lifetime worked when it worked, but the click that dismissed
    the menu was consumed, so the menu button looked dead on that click, and
    when the foreground could not be taken the button posted a second menu on
    top of the first, which read as a menu that cannot close. This is a plain
    window of ours instead: the button opens it and closes it, a click
    anywhere else closes it, so does Escape, nothing is consumed, and the
    focus stays where it was. It is made so it never takes the foreground,
    see Lens._own_window.

    Over a fullscreen lens the arrow keys, Enter and Escape work it as well,
    see Lens.nav_key: Up and Down light an entry, the way the pointer does,
    and Enter chooses the one that is lit.

    The same window shows the NR style list and the profile list of the
    title bar, so it carries the name of the list it shows, which the log
    gives its lines: menu for the lens menu, style list or profile list.
    """

    def __init__(self, lens):
        self.lens = lens
        self.win = None
        self.name = "menu"          # the list it shows, or showed last, for the log
        self.pressed = False
        self.labels = []            # the entries of the menu that is open, in order
        self.cmds = []              # what each of them does, None for one that does nothing
        self.lit = None             # the entry the pointer or the arrow keys lit, by its place in labels
        self.live = None            # the one that shows the readout, see Lens.menu

    def toggle(self, items, name="menu"):
        if self.win is not None:
            self.close()
        else:
            self.open(items, name)

    def open(self, items, name="menu"):
        lens = self.lens
        t = lens._own_window()
        self.win, self.name = t, name
        self.labels, self.cmds, self.lit, self.live = [], [], None, None
        t.configure(bg=ACCENT)
        box = tk.Frame(t, bg=BG)
        box.pack(padx=1, pady=1)
        for item in items:
            if item is None:
                tk.Frame(box, bg=HOVER, height=1).pack(fill="x", padx=6, pady=3)
                continue
            text, command, enabled = item
            lbl = tk.Label(box, text=text, bg=BG, fg=FG if enabled else DIM, anchor="w",
                           padx=14, pady=4, font=("Segoe UI", 10))
            lbl.pack(fill="x")
            n = len(self.labels)
            self.labels.append(lbl)
            self.cmds.append(command if enabled else None)
            if enabled and command is not None:
                lbl.bind("<Enter>", lambda e, n=n: self.light(n))
                lbl.bind("<Leave>", lambda e, n=n: self.light(None) if self.lit == n else None)
                lbl.bind("<Button-1>", lambda e, n=n: self.choose(n, "click"))
        t.update_idletasks()
        wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
        bx, top, bottom = lens.menu_anchor()
        # the monitor the anchor itself is on: with a fullscreen lens that is the
        # pointer, which can be at the very edge of its monitor
        mx, my, mw, mh = monitor_rect(bx + 6, top)
        x = max(mx, min(bx + 6, mx + mw - wd))
        y = bottom
        if y + ht > my + mh:
            y = top - ht                  # no room below the bar, the tab or the pointer
        t.geometry("%dx%d+%d+%d" % (wd, ht, x, max(my, y)))
        lens._show_own(t)
        if self.win is not t:
            return                  # closed again while it was being shown
        self.pressed = bool(u.GetAsyncKeyState(0x01) & 0x8000)
        lens.root.after(30, self.watch)
        lens.sync_hotkeys()         # the arrow keys, Enter and Escape, over a fullscreen lens

    def light(self, n):
        """Light this entry and no other, for the pointer or the arrow keys
        alike, so the two never show two entries lit. None lights none."""
        self.lit = n
        for i, lbl in enumerate(self.labels):
            if self.cmds[i] is not None:
                try:
                    lbl.config(bg=HOVER if i == n else BG)
                except Exception:
                    pass

    def step(self, d):
        """Light the next entry that does something, down for 1 and up for -1,
        round from the end to the start. With none lit, Down lights the first
        and Up the last."""
        live = [i for i, c in enumerate(self.cmds) if c is not None]
        if not live:
            return
        if self.lit not in live:
            self.light(live[0] if d > 0 else live[-1])
        else:
            self.light(live[(live.index(self.lit) + d) % len(live)])

    def key(self, name):
        """An arrow key, Enter or Escape while this menu is open over a
        fullscreen lens, see Lens.nav_key. Left and Right do nothing here."""
        if name in ("up", "down"):
            self.step(-1 if name == "up" else 1)
        elif name == "enter" and self.lit is not None:
            self.choose(self.lit, "Enter")
        elif name == "escape":
            self.close()
            self.lens.act("%s closed (Escape)" % self.name)

    def choose(self, n, how="click"):
        """Do what entry n does, chosen by a click or by Enter, once the menu
        has closed. The log says which list, which entry, and how."""
        command = self.cmds[n] if 0 <= n < len(self.cmds) else None
        if command is None:
            return
        try:
            text = " ".join(str(self.labels[n].cget("text")).split())
        except Exception:
            text = "?"
        self.lens.act('%s item "%s" (%s)' % (self.name, text, how))
        self.close()
        try:
            command()
        except Exception:
            import traceback
            traceback.print_exc()

    def inside(self, widget, px, py):
        try:
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            return x <= px < x + widget.winfo_width() and y <= py < y + widget.winfo_height()
        except Exception:
            return False

    def watch(self):
        """Close on a click anywhere but the menu or the button, or on Escape.

        The button's own handler toggles, and the menu's labels take their own
        clicks, so those two are left alone. The state is polled rather than
        bound, since neither the menu nor the bar ever has the keyboard focus.
        While the lens holds Escape as a key of its own, over a fullscreen lens,
        Escape comes as that key instead, see key, and is not looked for here,
        or one press would close the menu and then the panel or the note."""
        if self.win is None or self.lens.closing:
            return
        held = "nav_escape" in self.lens.hotkeys.registered.values()
        if not held and u.GetAsyncKeyState(0x1B) & 0x8000:
            self.close()
            self.lens.act("%s closed (Escape)" % self.name)
            return
        down = any(u.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))
        if down and not self.pressed:
            pt = w.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            if not self.inside(self.win, pt.x, pt.y) and not any(
                    self.inside(wdg, pt.x, pt.y) for wdg in self.lens.menu_widgets()):
                self.close()
                self.lens.act("%s closed (a click elsewhere)" % self.name)
                return
        self.pressed = down
        self.lens.root.after(30, self.watch)

    def close(self):
        t, self.win = self.win, None
        self.labels, self.cmds, self.lit, self.live = [], [], None, None
        if t is not None:
            try:
                t.destroy()
            except Exception:
                pass
            self.lens.sync_hotkeys()    # the keys that worked it go back once they are up


# Settings shows each setting as one short label. What the setting does is said
# in a small window by the pointer, once the pointer has rested on the setting
# for this many seconds without moving.
HINT_REST = 1.5
# The width an explanation is wrapped to, in points and not in pixels, so that
# a line holds about as many letters at every display scaling: 427 pixels at
# 100 percent, 533 at 125 and 640 at 150.
HINT_WRAP = "320p"


def _kept_together(text):
    """An explanation as its window shows it. The space between a number and
    its unit, and the one after RTX, is a space that does not break, so no line
    ends with "10" while the next begins with "ms"."""
    text = re.sub(r"(\d) (?=(?:ms|W|Hz|fps|s|megapixels|frames|percent|px)\b)", "\\1\u00a0", text)
    return re.sub(r"\bRTX (?=\d)", "RTX\u00a0", text)


class Hints:
    """The explanations of a dialog's settings, one at a time in a small window
    by the pointer.

    add gives a widget its text. Once the pointer has rested on that widget, or
    on anything inside it, for HINT_REST seconds without moving, the text shows
    beside the pointer. It stays while the pointer is on the widget, and goes
    when the pointer moves off it, a button or a key is pressed, the wheel
    turns, or the dialog loses the keyboard. F1 shows the text of the setting
    that has the keyboard, beside that setting, or where none has it, of the
    setting under the pointer, and it goes the same ways. The window is one of
    the lens's own: out of the picture, never taking the keyboard or a click,
    and kept on the pointer's monitor.
    """

    def __init__(self, lens, dialog):
        self.lens, self.dialog = lens, dialog
        self.texts = {}             # {widget: its explanation}
        self.listed = []            # (page, label, explanation) in the dialog's order, see settings_dialog
        self.at = None              # where the pointer was at its last move, on the screen
        self.over = None            # the widget with a text that the pointer is on
        self.timer = None           # the rest that is being timed
        self.win = None             # the window, while an explanation shows
        # bound on the dialog, which every widget in it passes its events on to
        for seq in ("<Motion>", "<Enter>", "<Leave>"):
            dialog.bind(seq, self.moved, add="+")
        for seq in ("<ButtonPress>", "<MouseWheel>", "<KeyPress>", "<FocusOut>", "<Unmap>", "<Destroy>"):
            dialog.bind(seq, self.pressed, add="+")
        # the one key that brings an explanation up rather than taking it away.
        # A hotkey field passes F1 alone on to it, see settings_dialog
        dialog.bind("<F1>", self.key)

    def add(self, widget, text):
        """Give this widget, and everything inside it, an explanation."""
        self.texts[widget] = text

    def under(self):
        """The widget with an explanation that the pointer is on, or None."""
        try:
            at = self.dialog.winfo_containing(*self.at)
        except Exception:
            return None             # no place known yet, or a window Tk has no name for
        while at is not None and at not in self.texts:
            at = None if at is self.dialog else at.master
        return at

    def moved(self, event=None):
        """The pointer moved, came or went. A text that shows stays while the
        pointer is on its widget. With none showing, the rest is timed again
        from this move. The place is the event's own, so a test can tell the
        dialog of a pointer without moving one."""
        x, y = getattr(event, "x_root", None), getattr(event, "y_root", None)
        self.at = (x, y) if isinstance(x, int) and isinstance(y, int) else self.dialog.winfo_pointerxy()
        at = self.under()
        if at is not self.over:
            self.hide()
            self.over = at
        if at is not None and self.win is None:
            self.cancel()
            self.timer = self.lens.root.after(int(HINT_REST * 1000), self.rested)

    def rested(self):
        self.timer = None
        try:
            if self.dialog.winfo_exists() and self.over is not None and self.under() is self.over:
                self.show(self.over)
        except Exception:
            pass

    def pressed(self, event=None):
        """A button or a key went down, the wheel turned, a page was turned, or
        the dialog lost the keyboard or went: nothing shows, and a rest counts
        again from the pointer's next move. A left click on a switch, a choice,
        a button or the slider also gives it the keyboard, which on Windows Tk
        does not, so F1 then explains what was clicked. It is done here and not
        in a binding of its own, which would outrank this one and keep a text
        up."""
        self.hide()
        if getattr(event, "num", None) == 1 and isinstance(event.widget, (tk.Checkbutton, tk.Radiobutton,
                                                                          tk.Button, tk.Scale)):
            event.widget.focus_set()

    def key(self, _event=None):
        """F1: the explanation of the setting that has the keyboard, below it,
        for a person who goes through the dialog with Tab. Where nothing with an
        explanation has the keyboard, a page's tab say, it is the setting under
        the pointer, beside the pointer, as a rest shows it."""
        try:
            at = self.dialog.focus_get()
        except Exception:
            at = None
        while at is not None and at not in self.texts:
            at = None if at is self.dialog else at.master
        self.hide()
        if at is not None:
            self.over = at
            self.show(at, at=(at.winfo_rootx() + 8, at.winfo_rooty() + at.winfo_height()), top=at.winfo_rooty())
        else:
            self.at = self.dialog.winfo_pointerxy()
            at = self.under()
            if at is not None:
                self.over = at
                self.show(at)
        return "break"

    def cancel(self):
        if self.timer is not None:
            try:
                self.lens.root.after_cancel(self.timer)
            except Exception:
                pass
            self.timer = None

    def hide(self):
        self.cancel()
        t, self.win = self.win, None
        if t is not None:
            try:
                t.destroy()
            except Exception:
                pass

    def show(self, widget, at=None, top=None):
        """Show this widget's explanation at once, beside the pointer's last
        place, or beside the point given, which is how a test asks for one.
        top is the top edge of a setting that the point lies below, which the
        window goes above where the monitor ends below. Returns the window, or
        None for a widget that has no text."""
        self.hide()
        text = self.texts.get(widget)
        if not text:
            return None
        px, py = at or self.at or self.dialog.winfo_pointerxy()
        t = self.win = tk.Toplevel(self.dialog)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.0)         # unseen until it is out of the picture, see below
        t.configure(bg=ACCENT)
        tk.Label(t, text=_kept_together(text), bg=FIELD, fg=FG, font=("Segoe UI", 11), justify="left",
                 wraplength=HINT_WRAP, padx=14, pady=10).pack(padx=1, pady=1)
        t.update_idletasks()
        wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
        mx, my, mw, mh = monitor_rect(px, py)
        # below the pointer and to its right, where a tooltip lies. Where the
        # monitor ends first it goes above the pointer, or above the setting F1
        # named, and as far left as it has to
        x, y = px + 16, py + 22
        if y + ht > my + mh:
            y = (py if top is None else top) - 12 - ht
        t.geometry("%dx%d+%d+%d" % (wd, ht, max(mx, min(x, mx + mw - wd)), max(my, min(y, my + mh - ht))))
        t.update_idletasks()
        self.lens._own_styles(t, through=True)
        t.attributes("-alpha", 1.0)
        t.update_idletasks()
        self.lens._own_styles(t, through=True)      # again, should the change have cost the window its styles
        return t


class Lens:
    def __init__(self, root, x, y, cw, ch, passes, fullscreen=False):
        self.root, self.cw, self.ch = root, cw, ch
        self.fullscreen = fullscreen    # the picture alone on its monitor: no chrome, no drag
        self.split = None           # A/B divider as a fraction of the width, or off
        self.divider = None         # the draggable divider window while split is on
        self.drag = None
        self.closing = False
        self.rebuilding = False     # True while set_passes is replacing the presenter
        self.tweak = False          # True while the viewport is interactive
        self.tweak_until = 0.0      # the overlay is followed until then after Done
        self.tweak_prev = None      # the window that had the keyboard before tweak mode
        self.nr_wait = None         # an NR switch that waits for the overlay's last write, see nr_by_restart
        self.proxy_scale = None     # the Cost Scaler's scale this session, or off
        self.engine = "stack"       # which presenter runs, fast or stack, see pick_engine
        self.fast_failed = None     # how the fast engine failed in this run, which rules it out
        self.engine_words = {}      # {pid: reason}: what a fast engine said as it failed
        self.engine_stage = {}      # {pid: stage}: the part of the engine that reason named
        self.engine_blind = {}      # {pid: reason}: what a presenter said as its capture was lost
        self.f6_said = False        # the log has said that F6 does nothing under this engine, see _nr_toggled
        self.stand_in = None        # since when the stack presenter stands in for a fast engine
                                    # that got no picture from the screen, see spawn_presenter
        self.fast_retry = False     # the fast engine about to start follows a stand-in that had pictures
        self.fed_at = 0.0           # when a presenter last reported frames it had captured
        self.held = None            # (text, until): a sentence held on the bar, see hold_note
        self.notes = {}             # {slot: (text, colour, until)}: what the notice shows, see say
        self.notice = None          # the notice's window, while a fullscreen lens has something to say
        self.notice_lines = []      # what it showed when last drawn, top line first
        self.readout_now = None     # the readout as last worked out, see stats
        self.readout_win = None     # the on-screen readout of a fullscreen lens, see show_readout
        self.readout_drawn = None   # what it shows and where, as last drawn
        self.fps_now = None         # new pictures a second, as stats last worked it out
        self.idle_now = False       # and whether nothing under the lens has changed for a while
        self.exclusive = False      # a program in exclusive fullscreen, as last seen, see check_exclusive
        self.quality_set = FAST_QUALITY     # the quality step the ini names, or None for the default
        self.engine_quality = None      # the step the fast engine that runs is at, by its own word
        self.engine_default = None      # (width, height, step): the step a fast engine took by itself
        self.engine_asked = None        # whether the fast engine that runs was given a step
        self.panel = None           # the NR settings panel's window while it is open, see open_panel
        self.panel_ui = {}          # its controls, by name
        self.panel_vals = {}        # what ReShade.ini holds for each of its keys, as the panel knows it
        self.panel_pos = {}         # where the panel itself put each slider, see _panel_slider
        self.panel_pending = {}     # changes made on it that are not written yet
        self.panel_sent = 0.0       # when its last write went out
        self.panel_timer = None     # the write that waits for its turn
        self.panel_tries = 0        # writes in a row that failed
        self.panel_live = False     # False while its controls are being set from the file
        self.panel_at = None        # where it was last put, for the next time it opens
        self.panel_drag = None
        self.panel_rows = []        # its settings in order, for the arrow keys, see panel_key
        self.panel_row = None       # the one the arrow keys are on
        self.panel_said = {}        # {key: (value, how, timer)}: a change on it still to be logged
        self.panel_pass_at = 0.0    # when the arrow keys last changed the pass count on it
        self.key_wait = False       # a hotkey's keys are waited for, see tweak_by_key
        self.fs_origin = (x, y)     # fullscreen: where the picture is, for good
        self.frames = 0             # frames the presenter has captured
        self.t_first = None
        self.out_frames = 0         # new pictures the presenter has shown
        self.pres_in = self.pres_out = 0.0   # the last second's captures and new pictures
        self.mon_x = self.mon_y = 0          # the captured monitor's origin
        self.readout = READOUT      # what the title bar shows beside the size
        self.show_size = TITLE_SIZE  # the size itself on the title bar
        self.latency_on = LATENCY   # the latency meter on the title bar
        self.auto_update_on = AUTO_UPDATE   # offer to install a newer release, after asking
        self.show_style = TITLE_STYLE       # the Home menu's NR style on the title bar
        self.show_intensity = TITLE_INTENSITY   # its overall intensity, shown only
        self.addon_seen = {}                # the add-on's section as the bar last read it
        self.ready = READY          # thirty presents a second over a still, always
        self.max_fps = MAX_FPS      # new pictures a second at most, 0 for no limit
        self.motion_detail = MOTION_DETAIL     # full, half or quarter, see _write_motion_detail
        self.md_written = None                 # the detail last written to the preset, see sync_motion_detail
        self.clip_shots = CLIP_SHOTS   # the joined before and after to the clipboard too
        self.fs_note = FULLSCREEN_NOTE  # the note on going fullscreen, see show_note
        self.note_win = None            # its window, while it is up
        self.check_updates_on = CHECK_UPDATES
        self.latency_ms = None      # its latest reading, the whole delay, see _whole_delay
        self.latency_raw = None     # the measured part alone, capture to present
        self._shown = None          # (time, out_frames) behind the fps readout
        self._fps_hist = collections.deque(maxlen=3)
        self.restart = False        # set by the folder settings, read by main()
        self.minimized = False      # hidden, with the presenter paused, until the taskbar button
        self.profiles = _load_profiles()
        self.profile = self.profiles.get("current")      # the name on the bar, or None
        if self.profile not in self.profiles["profiles"]:
            self.profile = None
        self.anchor_widget = None   # what the menu opens under, when not the bar
        self.attach = None          # the window the lens is attached to, see attach_to
        self.tab = None             # the tab on the top edge while attached or folded
        self.folded = False         # the title bar and frame folded away, see fold
        self.tab_x = 12             # where along the top edge the tab sits
        self.tab_drag = None
        self.picking = None         # a pick of a window or region in progress
        self.rs = None              # a resize by the frame in progress, see _grip_down
        self.shot_busy = False
        self.shot_event = threading.Event()
        self.shot_reply = None
        self.probe_event = threading.Event()
        self.probe_reply = None
        self.stages = []            # [{title, proc, hwnd}]: the presenter, one entry
        self.popup = PopupMenu(self)
        self.nav_held = set()       # the keys that work the menu, the panel and the note, as held now
        self.nav_wait = False       # one of them is still down after its window went, see sync_hotkeys
        self.hk_sent = None         # the combinations last handed to the listener
        self.fg_seen = None         # the window in front as last logged, see log_foreground
        self.fg_since = 0.0         # when log_foreground saw another window come to the front, see check_behind
        # the presenters' stats since the last summary, each with its process's
        # id, of which summarise keeps the fast engine's that runs now
        self.fast_seconds = collections.deque(maxlen=120)
        self.summary_at = time.perf_counter()               # when that summary was, see summarise
        self.behind_run = 0         # summaries in a row with the lens behind, see check_behind
        self.behind_next = 0.0      # when its warning may come again
        self.commands = None        # the listener for --do, from when the picture is up, see Commands
        self.hotkeys = Hotkeys()
        self.sync_hotkeys()
        self.root.after(50, self.poll_hotkeys)
        self.root.after(15000, self.check_updates_at_start)     # once the picture is up
        self.passes = passes        # neural passes, run inside the add-on
        self.pending = passes       # the pass count chosen on the bar, applied by Set
        self.nr_on = _read_nr_enabled()   # Neural Rendering on, as far as the lens knows
        self.last_arrival = time.perf_counter()   # the presenter's last report of a captured frame
        self.healthy_since = time.perf_counter()  # when the current presenter started
        self.recover_wait = 1.0     # seconds before the next start after a lost capture
        self.recover_after = None   # that start, while it is pending
        self.recover_held = False   # that start waits for a locked screen to come back
        self.lost_at = 0.0          # when a presenter last said its capture was lost
        self.layout = monitor_layout()            # the monitors the presenter started under
        self.layout_seen = (self.layout, time.perf_counter())   # the last layout read, and since when

        # ---- chrome (tk): title bar + subtle border + transparent hole
        t = tk.Toplevel(root)
        self.t = t
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=ACCENT)
        t.attributes("-transparentcolor", KEY)
        # windowed, the bar sits above the picture inside a frame that also draws
        # the border. Fullscreen there is no chrome at all: this window stays
        # withdrawn until the lens is a window again. layout_chrome places it all.
        bar = tk.Frame(t, bg=BG, height=BAR)
        self.bar = bar
        self.hole = tk.Frame(t, bg=KEY)         # the picture shows through this

        self.menu_btn = tk.Label(bar, text=" \u2630 ", bg=BG, fg=FG, font=("Segoe UI", 12))
        self.menu_btn.pack(side="left", padx=(6, 0))
        self.menu_btn.bind("<Button-1>", self.menu)
        tk.Label(bar, text="  DLSS 5 Neural Lens", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.info = tk.Label(bar, text="%d x %d" % (cw, ch), bg=BG, fg=DIM,
                             font=("Consolas", 9))
        self.info.pack(side="left", padx=10)
        # the profile selector: the name of the profile in use, or Profile
        self.prof_btn = tk.Label(bar, text="▾ Profile", bg=BG, fg=DIM, font=("Segoe UI", 9), padx=4)
        self.prof_btn.pack(side="left")
        self.prof_btn.bind("<Button-1>", lambda e: self.profile_menu())
        self.prof_btn.bind("<Enter>", lambda e: self.prof_btn.config(bg=HOVER))
        self.prof_btn.bind("<Leave>", lambda e: self.prof_btn.config(bg=BG))

        # the Home menu's NR style and overall intensity, on the bar when Settings
        # asks for them. Both follow the add-on's section, which it writes within a
        # second of a change in its overlay. The style is picked here and restarts
        # the picture, since the add-on reads its section only when it starts; the
        # intensity is shown only, the Home menu being the live way to move it
        self.style_btn = tk.Label(bar, text="▾ Default", bg=BG, fg=DIM, font=("Segoe UI", 9), padx=4)
        self.style_btn.bind("<Button-1>", lambda e: self.style_menu())
        self.style_btn.bind("<Enter>", lambda e: self.style_btn.config(bg=HOVER))
        self.style_btn.bind("<Leave>", lambda e: self.style_btn.config(bg=BG))
        self.intensity_lbl = tk.Label(bar, text="intensity 1.00", bg=BG, fg=DIM, font=("Consolas", 9), padx=4)
        self.show_bar_mirrors()

        # the caption buttons, right to left as on every window: close,
        # maximise or restore, minimise. They sit on a shade of their own, so
        # they read as the window's buttons rather than as more pass controls
        try:
            capfont, self.glyphs = _caption_glyphs(set(tkfont.families(root)))
        except Exception:
            capfont, self.glyphs = ("Segoe UI", 12), CAPTION_PLAIN
        self.capfont = capfont
        self.x_btn = tk.Label(bar, text=self.glyphs["close"], bg=CAP, fg=FG, font=capfont, padx=11)
        self.x_btn.pack(side="right", fill="y")
        self.x_btn.bind("<Button-1>", lambda e: self.quit(how="close button"))
        self.x_btn.bind("<Enter>", lambda e: self.x_btn.config(bg=CLOSE))
        self.x_btn.bind("<Leave>", lambda e: self.x_btn.config(bg=CAP))
        self.max_btn = tk.Label(bar, text=self.glyphs["restore" if fullscreen else "max"], bg=CAP,
                                fg=FG, font=capfont, padx=11)
        self.max_btn.pack(side="right", fill="y")
        self.max_btn.bind("<Button-1>", lambda e: self.toggle_fullscreen("button"))
        self.min_btn = tk.Label(bar, text=self.glyphs["min"], bg=CAP, fg=FG, font=capfont, padx=11)
        self.min_btn.pack(side="right", fill="y")
        self.min_btn.bind("<Button-1>", lambda e: self.minimize("button"))
        for b in (self.max_btn, self.min_btn):
            b.bind("<Enter>", lambda e, b=b: b.config(bg=HOVER))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=CAP))
        # a line between the caption buttons and the pass controls: without it
        # the minimise glyph reads as the minus of the pass count
        tk.Frame(bar, bg=HOVER, width=1).pack(side="right", fill="y", padx=(4, 6), pady=9)

        # plus and minus only choose a number; Set restarts the presenter at it,
        # so going from one pass to three is one restart rather than two
        self.set_btn = tk.Label(bar, text=" Set ", bg=BG, fg=DIM, font=("Segoe UI", 10, "bold"))
        self.set_btn.pack(side="right", padx=(2, 4))
        self.set_btn.bind("<Button-1>", lambda e: self.apply_passes())
        self.plus = tk.Label(bar, text=" + ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.plus.pack(side="right")
        self.plus.bind("<Button-1>", lambda e: self.bump_passes(1))
        self.pass_lbl = tk.Label(bar, text="1 pass", bg=BG, fg=ACCENT, font=("Consolas", 9))
        self.pass_lbl.pack(side="right", padx=2)
        self.minus = tk.Label(bar, text=" \u2212 ", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"))
        self.minus.pack(side="right")
        self.minus.bind("<Button-1>", lambda e: self.bump_passes(-1))
        for b in (self.plus, self.minus, self.set_btn):
            b.bind("<Enter>", lambda e, b=b: b.config(bg=HOVER))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=BG))

        # the frame the lens is resized by: a strip down each side and one along
        # the bottom, inside the border's line. Which way a drag on one resizes
        # depends on where it starts, see _grip_zone.
        self.grips = {}
        for side in ("w", "e", "s"):
            g = tk.Frame(t, bg=BG)
            g.bind("<Motion>", lambda e, s=side: self._grip_hover(s, e))
            g.bind("<ButtonPress-1>", lambda e, s=side: self._grip_down(s, e))
            g.bind("<B1-Motion>", self._grip_move)
            g.bind("<ButtonRelease-1>", self._grip_up)
            self.grips[side] = g

        # everything that answers a click of its own keeps that click; the rest of
        # the bar, the intensity readout included, drags the lens
        nodrag = (self.x_btn, self.max_btn, self.min_btn, self.menu_btn, self.plus, self.minus,
                  self.set_btn, self.prof_btn, self.style_btn)
        for wdg in (bar,) + tuple(bar.winfo_children()):
            if wdg not in nodrag:               # the separator drags the lens like the bar
                wdg.bind("<ButtonPress-1>", self.down)
                wdg.bind("<B1-Motion>", self.move)
                wdg.bind("<ButtonRelease-1>", self.up)
        self.layout_chrome(x, y)
        self.chrome = u.GetParent(t.winfo_id()) or t.winfo_id()
        # never take foreground: the lens is a tool window floating over whatever
        # you are actually using, and stealing focus costs the user their next
        # click. And never in the picture: the presenter captures the monitor, so
        # the chrome is excluded from capture for good, and every other window of
        # ours by watch_filter as it appears.
        _ex = u.GetWindowLongPtrW(self.chrome, GWL_EXSTYLE)
        u.SetWindowLongPtrW(self.chrome, GWL_EXSTYLE, _ex | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(self.chrome, WDA_EXCLUDEFROMCAPTURE)

        # ---- the presenter. The add-on's settings go into ReShade.ini before
        # it starts, see _write_addon_settings, and the Cost Scaler's ini is set
        # for this size and count. Which presenter it is comes first, since
        # apply_proxy leaves that ini alone for the fast engine.
        self.pick_engine()
        if ADDON_PASSES:
            _write_addon_settings(passes)
        self.sync_motion_detail()
        self.apply_proxy()
        self.check_exclusive()          # a lens starting fullscreen over one says so at once
        self.show_notice()
        self._build_presenter(x, y)
        self.raise_chrome()
        self.aim()
        self.update_info()
        self.watch_f6()
        self.root.after(1000, self.stats)
        self.root.after(200, self.watch_filter)
        if self.fullscreen:
            self.root.after(600, self.show_note)    # no bar to click, so the note names the keys
        self.commands = Commands(self)

    # ---- the presenter
    def visible(self):
        return self.stages[-1]["hwnd"]

    def engine_wanted(self):
        """Which presenter a start right now would get, fast or stack.

        The fast engine is for a fullscreen lens, when the ini asks for it, its
        exe is there, the Cost Scaler's files are in the stack, since it calls
        the model through that proxy, the lens is not attached to a window, and
        it has not failed in this run of the lens. Everything else gets the
        stack presenter.
        """
        fast = (self.fullscreen and FULLSCREEN_ENGINE == "fast" and FAST_EXE is not None
                and _proxy_installed() and self.attach is None and self.fast_failed is None)
        return "fast" if fast else "stack"

    def pick_engine(self, stand_in=False):
        """Decide the engine for the presenter about to start and keep it in
        self.engine, which is what the rest of the lens goes by. It comes before
        the Cost Scaler's ini and the add-on's settings are written.

        stand_in gives the stack presenter to a lens that wants the fast engine,
        for as long as the screen gives no picture, see spawn_presenter. Every
        other start ends a stand-in."""
        self.stand_in = time.perf_counter() if stand_in else None
        self.engine = "stack" if stand_in else self.engine_wanted()
        self.f6_said = False            # each engine says it once, see _nr_toggled

    def standing_in(self):
        """Whether the stack presenter is standing in for the fast engine, which
        the lens still wants and has not ruled out."""
        if self.stand_in is not None and (self.engine != "stack" or self.engine_wanted() != "fast"):
            self.stand_in = None
        return self.stand_in is not None

    def _build_presenter(self, x, y):
        """Start the presenter on the lens rect: it captures the monitor the lens
        is on, cropped to the lens, and presents each frame as it arrives."""
        idx, mx, my = monitor_of(x + self.cw // 2, y + self.ch // 2)
        self.mon_x, self.mon_y = mx, my
        proc, hwnd = self.spawn_presenter(TITLE, x, y, "monitor:%d" % idx, x - mx, y - my)
        self.stages.append({"title": TITLE, "proc": proc, "hwnd": hwnd})
        if self.engine == "fast" and not self.nr_on:
            # said once already, before its first picture, see spawn_presenter,
            # and once more now that it is up, should that have come too early
            self.tell_presenter("nr 0")

    def spawn_presenter(self, title, x, y, source, cx, cy):
        """Start the presenter and return (proc, hwnd). See lens_presenter.py for
        what it does, what it reads on stdin and what it prints.

        With self.engine at fast it is the fast engine that starts. It takes the
        presenter's command line and up to four options of its own, speaks the
        presenter's protocol, and its window is found by a class of its own. The
        window shows once the first picture is on it, a second or two in, since
        the model is created first. Should the engine leave before that, or show
        no window within twenty seconds, the lens does not stop: the fast engine
        is out for this run, see fast_out, and the stack presenter is started in
        its place.

        An engine that says the screen gave it no picture has not failed. A
        locked screen or one that is asleep gives no presenter a picture, and the
        lens's own recovery starts a presenter under exactly such a screen. The
        stack presenter then stands in, and the fast engine is started again once
        the stand-in gets pictures, see _recover and stats. Only a fast engine
        that gets none where the stand-in just had them is ruled out.
        """
        fast = self.engine == "fast"
        retry, self.fast_retry = self.fast_retry, False
        env = dict(os.environ, DISABLE_DLSS5_VK_BRIDGE="1")
        args = ["--source", source, "--at", str(x), str(y), "--size", str(self.cw), str(self.ch),
                "--crop", str(cx), str(cy), "--title", title, "--exclude"] + (["--ready"] if self.ready else []) + (
            ["--max-fps", str(self.max_fps)] if self.max_fps else [])
        if fast:
            # the engine's own four: where the model and ReShade.ini are, a
            # folder the runtime may write its logs into, the pass count, which
            # no add-on is there to read from ReShade.ini, and the quality step
            # where the ini names one. Given none, the engine takes its own
            # default for the picture's size and names it in its ready line
            data = os.path.join(LOGDIR, "fast")
            try:
                os.makedirs(data, exist_ok=True)
            except OSError:
                pass
            cmd = [FAST_EXE] + args + ["--stack", STACK_DIR, "--data", data, "--passes", str(self.passes)] + (
                ["--quality", str(self.quality_set)] if self.quality_set is not None else [])
            self.engine_quality, self.engine_asked = None, self.quality_set is not None
        else:
            cmd = [PRESENTER_EXE] + ([PRESENTER_SCRIPT] if PRESENTER_SCRIPT else []) + args
        errlog = os.path.join(LOGDIR, "presenter-stderr.log")
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            errf = open(errlog, "a", encoding="utf-8", errors="replace")
            errf.write("\n--- %s  %s%s ---\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), title,
                                               "  fast engine" if fast else ""))
            errf.flush()
        except OSError:
            errf, errlog = subprocess.DEVNULL, None
        # no console window: from source the presenter is a copy of python.exe,
        # which would open one when the lens itself has none
        proc, hwnd, how = None, None, None
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errf,
                                    cwd=STACK_DIR, env=env, text=True, bufsize=1,
                                    creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            if not fast:
                raise
            # Windows would not start the exe at all, which a virus scanner
            # holding a new program back is one way to get
            how = 'could not be started. Windows said "%s"' % (exc.strerror or exc)
        if errf is not subprocess.DEVNULL:
            try:
                errf.close()          # the child holds its own handle
            except OSError:
                pass
        if proc is not None:
            for said in (self.engine_words, self.engine_stage, self.engine_blind):
                said.pop(proc.pid, None)                # a process id comes round again
            reader = threading.Thread(target=self._read_presenter, args=(proc,), daemon=True)
            reader.start()
            if fast:
                # the fast engine starts with the network on, where the add-on
                # starts as its F6 toggle was left, NeuralUplift in ReShade.ini.
                # So the lens reads that as the add-on would have, and tells the
                # engine at once, so that its first picture is already right
                self.nr_on = _read_nr_enabled()
                if not self.nr_on:
                    try:
                        proc.stdin.write("nr 0\n")
                        proc.stdin.flush()
                    except (OSError, ValueError):
                        pass
            for i in range(400 if fast else 700):
                hwnd = find_window(proc.pid, FAST_CLASS if fast else "GLFW30")
                # an engine that has said its capture is lost shows no window before
                # a frame comes, so there is nothing more to wait for
                if hwnd or proc.poll() is not None or (fast and (proc.pid in self.engine_words
                                                                 or proc.pid in self.engine_blind)):
                    break
                if i == 100:
                    # five seconds of nothing reads as a hang, so say what is being
                    # waited for rather than leaving it silent
                    print("waiting for the %s to open its window ..."
                          % ("fast engine" if fast else "presenter"), flush=True)
                time.sleep(0.05)
        if fast and not hwnd:
            blind = None        # what it said of a screen that gave it no picture
            if proc is not None:
                # its reason is the last line it printed, "engine failed ...",
                # which the reader has once the process and its pipe are gone
                code = proc.poll()
                self._kill_stage({"proc": proc})
                if proc.pid in self.engine_blind:
                    # its reader is in a call into Tk, which waits for this thread,
                    # so it is not waited for
                    if proc.pid not in self.engine_words:
                        blind = self.engine_blind[proc.pid]
                else:
                    reader.join(2.0)
                if self.engine_stage.get(proc.pid) == "capture":
                    blind = self.engine_words.get(proc.pid) or "the capture did not start"
                how = self._engine_end(proc, code, False)
            # The add-on's settings and the motion detail are written before every
            # start, whichever the engine, so for the stack presenter that now
            # starts only the Cost Scaler is still to set, which apply_proxy left
            # alone while the engine was to be the fast one
            if blind is not None and not (retry and desktop_is_the_users()):
                print('the fast engine got no picture from the screen, saying "%s". The ReShade engine '
                      "stands in until the screen gives pictures again." % blind, flush=True)
                self.hold_note("The fast engine got no picture from the screen. The ReShade engine "
                               "stands in until the screen gives pictures again.")
                self.pick_engine(stand_in=True)
            else:
                if blind is not None:
                    # the stand-in had pictures a moment ago, on a desktop that is
                    # the user's: the screen gives them, and this engine gets none
                    how = 'got no picture from the screen while the ReShade engine did, saying "%s"' % blind
                self.fast_out(how, "got no picture from the screen" if blind is not None else "did not start")
                self.pick_engine()
            self.apply_proxy()
            return self.spawn_presenter(title, x, y, source, cx, cy)
        if not hwnd:
            try:
                proc.kill()
            except Exception:
                pass
            raise SystemExit("\n".join([
                "The presenter never opened a window.",
                "",
                "It runs as lens-presenter.exe in the stack folder:",
                "  %s" % STACK_DIR,
                "",
                ("What it printed is in:\n  %s" % errlog) if errlog
                else "Its own output could not be captured.",
            ]))
        st = u.GetWindowLongPtrW(hwnd, GWL_STYLE)
        u.SetWindowLongPtrW(hwnd, GWL_STYLE, st & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX)
        self.set_interactive(hwnd, False)
        if self.attach is not None:
            # not above everything: one step above the target, see stack_above_target
            u.SetWindowPos(hwnd, HWND_NOTOPMOST, x, y, self.cw, self.ch, SWP_NOACTIVATE)
        else:
            u.SetWindowPos(hwnd, HWND_TOPMOST, x, y, self.cw, self.ch, SWP_NOACTIVATE)
        return proc, hwnd

    def _read_presenter(self, proc):
        """The presenter's stdout: a stats line a second, and replies.

        The delay meter: the presenter reports the median, over each second,
        of its present call against the capture's own timestamp, which names
        the composition the frame belongs to. The composition and scanout after
        the present come to about a refresh and a half: measured with a window
        flipping black and white, the flip took 8 ms to reach the presenter's
        output where the meter read -5 at 120 Hz. So that much is added and
        the bar shows the whole delay.

        The fast engine's line has delay as well, measured up to the refresh
        that showed the picture, and that is what the lens shows for it, see
        _whole_delay. It reads nan while the engine has learned of no refresh,
        and the last reading stays until it has.
        """
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("stats "):
                try:
                    kv = dict(p.split("=", 1) for p in line[6:].split())
                    new, arrived = int(kv["new"]), int(kv["arrived"])
                    meter = float(kv["meter"])
                except (ValueError, KeyError):
                    continue
                shown = None            # the fast engine's delay, which the stack presenter does not report
                if "delay" in kv:
                    try:
                        shown = float(kv["delay"])
                    except ValueError:
                        shown = float("nan")
                try:
                    # the fast engine's second, for the summary in the log, under the
                    # process's id, so the summary keeps to the engine that runs, see summarise
                    self.fast_seconds.append((proc.pid, new, arrived, int(kv.get("repeated", 0)),
                                              int(kv.get("dropped", 0)), int(kv.get("skipped", 0)), shown))
                except ValueError:
                    pass
                if self.t_first is None:
                    self.t_first = time.perf_counter()
                self.frames += arrived
                self.out_frames += new
                self.pres_in, self.pres_out = float(arrived), float(new)
                if arrived > 0:
                    # fed_at is only ever set here, by frames a presenter really had,
                    # where last_arrival is also set to now by a restart and a restore
                    self.last_arrival = self.fed_at = time.perf_counter()
                if meter == meter:
                    self.latency_raw = meter
                if shown is not None:
                    if shown == shown:
                        self.latency_ms = _whole_delay(meter, shown)
                elif meter == meter:
                    self.latency_ms = _whole_delay(meter)
            elif line.startswith("shot "):
                self.shot_reply = line[5:]
                self.shot_event.set()
            elif line.startswith("probe "):
                self.probe_reply = line[6:]
                self.probe_event.set()
            elif line.startswith("capture lost"):
                # Kept first, since the call into Tk below waits for the Tk thread,
                # which may be in spawn_presenter waiting for this very engine, and
                # reads the reason there. The time is what _recover compares the
                # frames with: lines come in order, so the stats line a presenter
                # prints just before this one is already in last_arrival, and only
                # a later one says that frames came back.
                self.lost_at = time.perf_counter()
                self.engine_blind[proc.pid] = line[13:].strip()
                print(line, flush=True)
                try:
                    self.root.after(0, self.capture_lost, line[13:], proc)
                except Exception:
                    pass
            elif line.startswith("engine "):
                # the fast engine's own lines, for the log. "engine failed REASON"
                # is its last before it leaves. The reason is kept, and that it
                # is there is how spawn_presenter and main's watch learn of the
                # failure, as they learn of the process ending, and go to
                # fast_out. Nothing is called from here: a call into Tk waits
                # for the Tk thread, which may itself be in spawn_presenter
                # waiting for this thread to finish
                print(line, flush=True)
                if line.startswith("engine failed"):
                    # "engine failed pipeline: REASON": the part of the engine that
                    # failed comes first, for whoever reads the log. Settings and
                    # the lens's own sentences quote the reason without it. Only
                    # the engine's own stage names are taken off, so a reason that
                    # happens to hold a colon stays whole
                    said = line[13:].strip()
                    stage, sep, rest = said.partition(": ")
                    if sep and rest and stage in ("gpu", "window", "pipeline", "commands", "capture", "quality",
                                                  "back buffer", "repaint", "present", "render", "ingest"):
                        self.engine_stage[proc.pid] = stage
                        said = rest
                    self.engine_words[proc.pid] = said
            elif line.startswith("presenter ready") or line in ("paused", "resumed"):
                if line.startswith("presenter ready"):
                    # the fast engine ends its ready line with the quality step it
                    # runs at, which is its own default where the lens gave it none
                    for part in line.split(", "):
                        if part.startswith("quality ") and part[8:].strip().isdigit():
                            self.engine_quality = int(part[8:])
                            if self.engine_asked is False:
                                # with the picture's size, which the default goes by
                                self.engine_default = (self.cw, self.ch, self.engine_quality)
                print(line, flush=True)

    def tell_presenter(self, text):
        for s in list(self.stages):
            try:
                s["proc"].stdin.write(text + "\n")
                s["proc"].stdin.flush()
            except (OSError, ValueError, AttributeError):
                pass

    def _kill_stage(self, s):
        # A screenshot the presenter is writing gets its time first: it writes
        # straight into the files' final names, and ended in the middle it would
        # leave them cut short. Its reply comes once all three are written, and
        # the reader sets the event without a call into Tk, so waiting here cannot
        # lock. Five seconds is as long as the screenshot itself waits. Only the
        # presenter that is showing the picture can be writing one.
        try:
            if self.shot_busy and s in self.stages and s["proc"].poll() is None:
                self.shot_event.wait(5.0)
        except Exception:
            pass
        for step in (lambda: s["proc"].stdin.close(),
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

    # ---- the fast engine failing
    # A stack presenter that fails ends the lens, since there is nothing else to
    # show the picture with. The fast engine failing does not: the stack
    # presenter takes over, and the fast engine is left out for the rest of the
    # run, so one that fails every time is started once and not over and over.
    def _engine_end(self, proc, code, started):
        """How a fast engine that is gone went, as words to follow "the fast
        engine": the reason it printed when it printed one, else its exit code,
        else that no window came. started says whether its picture was up."""
        verb = "stopped" if started else "did not start"
        said = self.engine_words.get(proc.pid)
        if said:
            return '%s, saying "%s"' % (verb, said)
        if code is not None:
            return "%s and gave no reason, exit code %d" % (verb, code)
        if said is not None:
            return "%s and gave no reason" % verb       # it said it failed and no more
        return "showed no window within twenty seconds"

    def fast_out(self, how, what):
        """Rule the fast engine out for the rest of this run of the lens, and say
        so in the log and on the bar. engine_wanted gives the stack presenter
        from here on. how is the whole of what happened, for the log and for
        Settings, and what is the short of it, for the bar. Returns the bar's
        sentence, which also serves as the note of a restart."""
        self.fast_failed = how
        print("the fast engine %s. Fullscreen runs on the ReShade engine until the lens is started again."
              % how, flush=True)
        text = ("The fast engine %s, so the ReShade engine took over. The Fullscreen page in Settings "
                "says why." % what)
        self.hold_note(text)
        return text

    def engine_gone(self, proc):
        """Whether a fast engine has ended, or has said that it failed, which it
        says just before it ends."""
        return proc.poll() is not None or proc.pid in self.engine_words

    def engine_lost(self, proc):
        """The fast engine went while its picture was up, which main's watch saw.
        The stack presenter takes over. A minimised lens is left as it is and
        restore does this when it comes back, so that a lens put away never
        comes back by itself."""
        if (self.closing or self.rebuilding or self.minimized or self.engine != "fast"
                or not self.stages or self.stages[0]["proc"] is not proc):
            return
        self.restart_presenter(self.fast_out(self._engine_end(proc, proc.poll(), True), "stopped"))

    # ---- keeping the picture clean and the lens on top
    def watch_filter(self):
        """Every window of ours out of the picture, and the lens on top.

        The menu or a dialog appears and vanishes with no hook to act on, so
        the exclusion from capture is re-applied on a timer, and the stacking
        is checked on the same one.
        """
        if self.closing:
            return
        own = _own_windows()
        for hx in own:
            try:
                u.SetWindowDisplayAffinity(hx, WDA_EXCLUDEFROMCAPTURE)
            except Exception:
                pass
        try:
            self.log_foreground(own)
            if self.fullscreen and not self.minimized:
                self.sync_hotkeys()     # a dialog of the lens's own that came in front takes the keys, see nav_wanted
        except Exception:
            pass
        if not self.minimized and self.attach is None:
            try:
                self.keep_chrome_on_top()
                self.keep_stage_on_top()
            except Exception:
                pass
        try:
            self.watch_layout()
        except Exception:
            pass
        if not self.closing:
            self.root.after(200, self.watch_filter)

    def keep_stage_on_top(self):
        """Raise the lens again when an ordinary window has been stacked over it.

        Windows puts a maximised or full screen window that becomes the
        foreground above every topmost window: measured with the Photos app,
        maximised over a windowed lens it sat above the presenter and stayed
        there, and only a fresh HWND_TOPMOST brought the lens back. So
        whenever a visible window that is neither ours nor itself topmost
        sits above the presenter and overlaps the lens, the whole lens is
        raised, the same as the taskbar button does. Windows that are
        themselves topmost are left alone, so a tool the user keeps on top is
        not fought over.
        """
        if not self.stages or self.rebuilding:
            return
        stage = self.visible()
        lx, ly = self.inner()
        own = set(_own_windows()) | {s["hwnd"] for s in self.stages} | {self.chrome}
        h = u.GetWindow(stage, 3)                    # GW_HWNDPREV: the window above
        while h:
            if (h not in own and u.IsWindowVisible(h)
                    and not u.GetWindowLongPtrW(h, GWL_EXSTYLE) & WS_EX_TOPMOST):
                r = w.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                if r.right > lx and r.left < lx + self.cw and r.bottom > ly and r.top < ly + self.ch:
                    self.bring_back()
                    return
            h = u.GetWindow(h, 3)

    def keep_chrome_on_top(self):
        """Raise the chrome again if the presenter has climbed above it.

        The A/B divider lies over the picture, so a presenter above the chrome
        hides it. Only the presenter counts: menus and dialogs are meant to be
        above the chrome.
        """
        stages = {s["hwnd"] for s in self.stages}
        # a fullscreen lens has no chrome in view, but its notice, its note, its
        # NR settings panel and its readout lie over the picture the same way
        tops = [] if self.fullscreen else [self.chrome]
        for win in (self.divider, self.panel, self.notice, self.note_win, self.readout_win):
            if win is not None:
                try:
                    tops.append(u.GetParent(win.winfo_id()) or win.winfo_id())
                except Exception:
                    pass
        for top in tops:
            h = u.GetWindow(top, 3)                  # GW_HWNDPREV, the window above
            while h:
                if h in stages:
                    self.raise_chrome()
                    return
                h = u.GetWindow(h, 3)

    def raise_chrome(self):
        u.SetWindowPos(self.chrome, HWND_TOPMOST, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        if self.tab is not None and self.attach is None:
            # folded: the tab is the only thing that takes the mouse, and it has
            # to stay above the picture, which is re-raised the same way
            try:
                th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
                u.SetWindowPos(th, HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        # the readout, the divider, the NR settings panel, the notice and the
        # note lie over the picture, each raised over the one before it, so the
        # readout is under the rest, see raise_over_readout, and the menu is on top
        for win in (self.readout_win, self.divider, self.panel, self.notice, self.note_win):
            if win is not None:
                try:
                    h = u.GetParent(win.winfo_id()) or win.winfo_id()
                    u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0,
                                   SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                except Exception:
                    pass
        if getattr(self, "popup", None) is not None and self.popup.win is not None:
            try:
                hm = u.GetParent(self.popup.win.winfo_id()) or self.popup.win.winfo_id()
                u.SetWindowPos(hm, HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass

    def raise_over_readout(self):
        """Put the NR settings panel, the note and the menu back over the
        readout, which a new readout window comes up over, see show_readout."""
        for win in (self.panel, self.note_win, self.popup.win):
            if win is not None:
                try:
                    h = u.GetParent(win.winfo_id()) or win.winfo_id()
                    u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0,
                                   SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                except Exception:
                    pass

    def bring_back(self):
        """Put the presenter and the title bar back on top.

        A window that is itself set to stay on top can leave the lens
        underneath it and demoted from topmost, with no way back short of
        restarting it. raise_chrome only re-asserts the title bar, so on its
        own it would put a bar back on top of nothing. Attached, the lens
        belongs one step above its target, so the target comes forward and
        the lens with it.
        """
        if self.attach is not None:
            try:
                u.SetForegroundWindow(self.attach["hwnd"])
            except Exception:
                pass
            self.stack_above_target()
            return
        for s in list(self.stages):
            try:
                u.SetWindowPos(s["hwnd"], HWND_TOPMOST, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        self.raise_chrome()

    # ---- taskbar
    # The title bar cannot have a taskbar button: it is an override redirect
    # window that never activates, so the mouse can reach the application
    # under the lens. The hidden tk root stands in for it. It is fully
    # transparent and parked minimised, so it is never seen, but its button is
    # on the taskbar. Clicking that restores the root, which lands in
    # _taskbar_click: a minimised lens comes back, any other comes back to the
    # top, and the root is minimised again before it can be noticed. Tk
    # toplevels on Windows are not owned by the root, so minimising it does
    # not take the title bar with it; measured rather than assumed.
    #
    # A fullscreen lens has no bar, and its menu comes up by a hotkey. Whenever
    # the lens does not hold that key, since none is set, another program or
    # another of the lens's actions holds the combination, or the lens has let
    # it go for the moment, while a dialog of its own is in front say, the
    # click on the button opens the menu as well, so there is always a way to
    # it, and with it a way out of fullscreen.
    def show_in_taskbar(self):
        r = self.root
        r.title("DLSS 5 Neural Lens")
        r.geometry("1x1+0+0")
        try:
            r.attributes("-alpha", 0.0)
        except Exception:
            pass
        r.protocol("WM_DELETE_WINDOW", lambda: self.quit(how="taskbar"))   # Close window on the button
        r.iconify()
        r.update_idletasks()
        r.bind("<Map>", self._taskbar_click)

    def _taskbar_click(self, _event=None):
        if self.closing:
            return
        if self.minimized:
            self.restore("taskbar button")
        else:
            self.bring_back()
            if (self.fullscreen and "lens_menu" not in self.hotkeys.registered.values()
                    and not self.rebuilding):
                self.root.after(120, lambda: self.menu(None, "taskbar button"))
        self.root.after(80, self.root.iconify)

    def minimize(self, how=None):
        """Hide the lens, leaving its taskbar button, and pause the presenter.

        Paused, the presenter stops its capture and presents nothing, so no
        neural pass runs and nothing of the lens costs the GPU or the CPU
        anything until the taskbar button brings it back. Neural Rendering is
        not switched off for it: the add-on only runs on a present, and with
        none it keeps whatever state it had for the way back. how is the way
        the person at the lens asked, for the log.
        """
        if self.closing or self.minimized or self.rebuilding or not self.stages or self.rs:
            return
        if how:
            self.act("minimised (%s)" % how)
        self.summarise(now=True)        # what the fast engine did up to here, see summarise
        self.popup.close()
        if self.tweak:
            # the overlay closes on a Home the presenter has to present a frame
            # to notice, so it gets that frame before the pause
            self.end_tweak()
            self.root.after(KEY_HOLD + 400, self.minimize)
            return
        self.close_panel()
        self.close_note()
        self.minimized = True
        self.show_notice()              # a lens put away says nothing on screen
        self.show_readout()             # and shows no figures
        self.sync_hotkeys()             # and gives the fullscreen lens's keys back
        self.tell_presenter("pause")
        for s in self.stages:
            u.ShowWindow(s["hwnd"], SW_HIDE)
        if self.divider is not None:
            try:
                self.divider.withdraw()
            except Exception:
                pass
        if self.tab is not None:
            try:
                self.tab.withdraw()
            except Exception:
                pass
        self.t.withdraw()
        print("minimised to the taskbar", flush=True)

    def restore(self, how=None):
        """Bring a minimised lens back as it was, from the taskbar button.

        The presenter is shown again where it was and told to capture and
        present again. Had the monitors changed meanwhile, it is replaced
        instead, as it would have been had the lens been in view, and so is a
        fast engine that ended meanwhile, by the stack presenter. how is the
        way the person at the lens asked, for the log.
        """
        if self.closing or not self.minimized:
            return
        if how:
            self.act("brought back (%s)" % how)
        self.minimized = False
        # a paused engine's stats line from just before is no part of the next summary
        self.fast_seconds.clear()
        self.summary_at = time.perf_counter()
        self.sync_hotkeys()             # a fullscreen lens holds its keys again
        self.show_chrome(not self.fullscreen)       # a fullscreen lens has none to bring back
        if self.divider is not None:
            try:
                self.divider.deiconify()
            except Exception:
                pass
        self._fps_hist.clear()
        self._shown = None
        self.last_arrival = self.healthy_since = time.perf_counter()
        # a fast engine that went while the lens was minimised was left until
        # now, see engine_lost
        gone = None
        if self.engine == "fast" and self.stages and self.engine_gone(self.stages[0]["proc"]):
            proc = self.stages[0]["proc"]
            gone = self.fast_out(self._engine_end(proc, proc.poll(), True), "stopped")
        now = monitor_layout()
        if now != self.layout:
            print("the monitors changed while minimised: %s" % (now,), flush=True)
            self.layout = now
            self.layout_seen = (now, time.perf_counter())
            if self.fullscreen:
                self.set_fullscreen(True, "the monitors changed, starting again ...")
            elif not self.refit():
                self.restart_presenter("the monitors changed, starting again ...")
            return
        if gone:
            self.restart_presenter(gone)
            return
        for s in self.stages:
            u.ShowWindow(s["hwnd"], SW_SHOWNA)
        self.tell_presenter("resume")
        self.bring_back()
        self.place()
        self.aim()
        print("back from the taskbar", flush=True)

    # ---- live A/B split
    # The lens is see-through, so the raw source is already on screen under the
    # presenter. Clipping the presenter's window to the left of a divider
    # reveals it on the right, live and pixel aligned, at no cost.
    # ---- attached to a window
    # The lens can be attached to another window, or to a region inside it.
    # It then follows that window: moves with it, restarts its picture when the
    # window's size has settled, minimises and restores with it, and closes when
    # it closes. The chrome shrinks to a two pixel line around the region, all
    # of it click-through so the target's own edges and controls stay usable,
    # and a tab on the top edge that opens the menu and slides along the edge
    # when it is in the way. And the lens is not on top of everything: it sits
    # one step above its target in the stacking order, so a window put over the
    # target covers the lens too, and bringing the target forward brings the
    # lens with it.
    def pick_target(self, region):
        """Start a pick: the next click names the window, then for a region a
        drag over it draws the rectangle. Escape cancels either."""
        if self.picking is not None or self.attach is not None or self.fullscreen or self.closing:
            return
        self.popup.close()
        hint = tk.Toplevel(self.root)
        hint.overrideredirect(True)
        hint.attributes("-topmost", True)
        hint.configure(bg=ACCENT)
        lbl = tk.Label(hint, text=("Click the window to attach the lens to.  Escape cancels."
                                   if not region else
                                   "Click the window, then drag the region inside it.  Escape cancels."),
                       bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=8)
        lbl.pack(padx=1, pady=1)
        hint.update_idletasks()
        x, y = self.inner()
        mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
        hint.geometry("+%d+%d" % (mx + (mw - hint.winfo_reqwidth()) // 2, my + 24))
        hint.update()
        hh = u.GetParent(hint.winfo_id()) or hint.winfo_id()
        u.SetWindowLongPtrW(hh, GWL_EXSTYLE, u.GetWindowLongPtrW(hh, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(hh, WDA_EXCLUDEFROMCAPTURE)
        self.picking = {"region": region, "hint": hint, "label": lbl, "down": bool(u.GetAsyncKeyState(0x01) & 0x8000),
                        "target": None, "overlay": None, "canvas": None, "start": None, "box": None}
        self.root.after(30, self._pick_tick)

    def _pick_end(self):
        p, self.picking = self.picking, None
        if p is None:
            return
        for k in ("overlay", "hint"):
            try:
                if p[k] is not None:
                    p[k].destroy()
            except Exception:
                pass

    def _pick_tick(self):
        p = self.picking
        if p is None or self.closing:
            return
        if u.GetAsyncKeyState(0x1B) & 0x8000:
            self._pick_end()
            return
        down = bool(u.GetAsyncKeyState(0x01) & 0x8000)
        if p["target"] is None and down and not p["down"]:
            pt = w.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            h = u.WindowFromPoint(pt)
            h = u.GetAncestor(h, GA_ROOT) or h
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, cls, 64)
            own = set(_own_windows()) | {s["hwnd"] for s in self.stages} | {self.chrome}
            if not h or h in own or cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                p["label"].config(text="That is the desktop, the taskbar or the lens itself. Click a window.  Escape cancels.")
            else:
                p["target"] = h
        p["down"] = down
        if p["target"] is not None and not down:
            # the click has been released, so the target keeps it; now the
            # region, or the attachment itself
            if p["region"]:
                if p["overlay"] is None:
                    self._region_start()
            else:
                h = p["target"]
                self._pick_end()
                self.attach_to(h, None)
                return
        self.root.after(30, self._pick_tick)

    def _region_start(self):
        """A translucent sheet over the target's client area to drag the region on."""
        p = self.picking
        rect = self.target_client(p["target"])
        if rect is None:
            self._pick_end()
            return
        cx, cy, cw, ch = rect
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.35)
        ov.configure(bg=FIELD)
        ov.geometry("%dx%d+%d+%d" % (cw, ch, cx, cy))
        cv = tk.Canvas(ov, bg=FIELD, highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        p["overlay"], p["canvas"] = ov, cv
        p["label"].config(text="Drag the region the lens should cover.  Escape cancels.")

        def down(e):
            p["start"] = (e.x, e.y)
            p["box"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT, width=2)

        def move(e):
            if p["start"] is not None:
                cv.coords(p["box"], p["start"][0], p["start"][1], e.x, e.y)

        def up(e):
            if p["start"] is None:
                return
            x0, y0 = p["start"]
            x1, y1 = e.x, e.y
            left, top = min(x0, x1), min(y0, y1)
            wd, ht = abs(x1 - x0), abs(y1 - y0)
            h = p["target"]
            if wd < MIN_W or ht < MIN_H:
                p["start"], p["box"] = None, None
                cv.delete("all")
                p["label"].config(text="Too small. The region needs at least %d by %d pixels. Drag again.  "
                                       "Escape cancels." % (MIN_W, MIN_H))
                return
            frac = (left / float(cw), top / float(ch), wd / float(cw), ht / float(ch))
            self._pick_end()
            self.attach_to(h, frac)

        cv.bind("<ButtonPress-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)
        ov.update()

    @staticmethod
    def target_client(h):
        """The target's client area in screen pixels, or None if it has none."""
        r = w.RECT()
        if not u.IsWindow(h) or not u.GetClientRect(h, ctypes.byref(r)) or r.right <= 0 or r.bottom <= 0:
            return None
        pt = w.POINT(0, 0)
        u.ClientToScreen(h, ctypes.byref(pt))
        return pt.x, pt.y, r.right, r.bottom

    def target_rect(self):
        """Where the picture goes now: the target's client area, or the region's
        share of it, clipped to the monitor it is mostly on, since the
        presenter captures one monitor. None while it is too small to show."""
        a = self.attach
        c = self.target_client(a["hwnd"])
        if c is None:
            return None
        cx, cy, cw, ch = c
        if a["frac"] is not None:
            fx, fy, fw, fh = a["frac"]
            x, y, wd, ht = cx + int(round(fx * cw)), cy + int(round(fy * ch)), int(round(fw * cw)), int(round(fh * ch))
        else:
            x, y, wd, ht = cx, cy, cw, ch
        mx, my, mw, mh = monitor_rect(x + wd // 2, y + ht // 2)
        x0, y0 = max(x, mx), max(y, my)
        x1, y1 = min(x + wd, mx + mw), min(y + ht, my + mh)
        wd, ht = x1 - x0, y1 - y0
        wd, ht = wd - wd % 2, ht - ht % 2
        if wd < MIN_W or ht < MIN_H:
            return None
        return x0, y0, wd, ht

    def attach_to(self, h, frac):
        if self.attach is not None or self.closing or self.fullscreen:
            return
        if self.folded:
            self.unfold()
        x, y = self.inner()
        self.attach = {"hwnd": h, "frac": frac, "rect": (x, y, self.cw, self.ch),
                       "saved": (self.cw, self.ch, x, y), "size_seen": None, "since": 0.0,
                       "by_target": False}
        rect = self.target_rect()
        if rect is None:
            self.attach = None
            print("attach: the window is too small to attach to", flush=True)
            return
        # the window's class and not its title, which can hold private text
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, cls, 256)
        print("attached to a window of class %s%s at %dx%d" % (cls.value or "unknown", " (a region)" if frac else "",
                                                              rect[2], rect[3]), flush=True)
        self.popup.close()
        # the chrome becomes the line and the tab, click-through and no longer
        # above everything
        self.t.attributes("-topmost", False)
        self._chrome_passthrough(True)
        self.make_tab()
        u.SetWindowPos(self.chrome, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.attach["rect"] = rect
        self.resize_to(*rect)               # lays the chrome out attached, restarts the picture
        self.stack_above_target()
        self.root.after(50, self.follow_target)

    def detach(self, how=None):
        """Let go of the window the lens is attached to. how is the way the
        person at the lens asked, for the log."""
        a, self.attach = self.attach, None
        if a is None:
            if how:
                self.act("nothing to detach from (%s)" % how)
            return
        if how:
            self.act("detached (%s)" % how)
        cw, ch, x, y = a["saved"]
        print("detached", flush=True)
        if self.tab is not None:
            try:
                self.tab.destroy()
            except Exception:
                pass
            self.tab = None
        self._chrome_passthrough(False)
        self.t.attributes("-topmost", True)
        if self.closing:
            return
        if self.minimized:
            self.restore()
        self.resize_to(x, y, cw, ch)
        self.bring_back()
        self.save_state()

    def toggle_fold(self, how=None):
        """The title bar hidden or shown again. how is the way the person at
        the lens asked, for the log."""
        if self.folded:
            self.unfold(how)
        else:
            self.fold(how)

    def fold(self, how=None):
        """Fold the title bar and frame away, leaving the tab on the picture's
        top edge, which drags the lens and opens the menu, where Unfold is. The
        picture stays exactly where it is, so nothing restarts. A fullscreen
        lens has no bar to fold, and comes back to a window folded or not as it
        was before."""
        if (self.folded or self.attach is not None or self.closing or self.rs is not None
                or self.fullscreen):
            if how:
                self.act("title bar left as it is (%s)" % how)
            return
        if how:
            self.act("title bar hidden (%s)" % how)
        self.popup.close()
        x, y = self.inner()
        self.folded = True
        self._chrome_passthrough(True)
        self.make_tab()
        self.layout_chrome(x, y)
        self.raise_chrome()
        print("title bar hidden", flush=True)

    def unfold(self, how=None):
        if not self.folded or self.fullscreen:
            if how:
                self.act("title bar left as it is (%s)" % how)
            return
        if how:
            self.act("title bar shown (%s)" % how)
        x, y = self.inner()
        self.folded = False
        if self.tab is not None:
            try:
                self.tab.destroy()
            except Exception:
                pass
            self.tab = None
        self._chrome_passthrough(False)
        self.layout_chrome(x, y)
        print("title bar shown", flush=True)

    def _chrome_passthrough(self, on):
        ex = u.GetWindowLongPtrW(self.chrome, GWL_EXSTYLE)
        ex = (ex | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
        u.SetWindowLongPtrW(self.chrome, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        u.SetWindowPos(self.chrome, 0, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

    def show_chrome(self, on):
        """Bring the chrome's two windows, the bar with its frame and the tab,
        into view, or take them out of it. A fullscreen lens shows neither, and
        a minimised one nothing at all, whatever is asked.

        Brought back, each gets the styles it was given at birth again, in case
        showing it cost any of them, and is kept out of the picture. The
        chrome's window handle is read afresh: a lens that started fullscreen
        has never shown its chrome, and Tk makes the window that carries the
        styles when it first shows one. Returns whether anything came back."""
        on = on and not self.minimized
        back = False
        for win in (self.t, self.tab):
            if win is None:
                continue
            try:
                hidden = win.state() == "withdrawn"
                if on and hidden:
                    win.deiconify()
                    back = True
                elif not on and not hidden:
                    win.withdraw()
            except Exception:
                pass
        if not back:
            return False
        self.t.update()
        self.chrome = u.GetParent(self.t.winfo_id()) or self.t.winfo_id()
        self._chrome_passthrough(self.attach is not None or self.folded)
        u.SetWindowDisplayAffinity(self.chrome, WDA_EXCLUDEFROMCAPTURE)
        if self.tab is not None:
            try:
                th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
                u.SetWindowLongPtrW(th, GWL_EXSTYLE, u.GetWindowLongPtrW(th, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
                u.SetWindowDisplayAffinity(th, WDA_EXCLUDEFROMCAPTURE)
            except Exception:
                pass
        return True

    def follow_target(self):
        """Every 50 ms while attached: gone, minimised, moved, resized, or covered."""
        a = self.attach
        if a is None or self.closing:
            return
        h = a["hwnd"]
        if not u.IsWindow(h):
            print("the attached window closed; closing the lens", flush=True)
            self.attach = None
            self.quit()
            return
        if u.IsIconic(h):
            if not self.minimized and not self.rebuilding:
                a["by_target"] = True
                self.minimize()
        elif self.minimized and a["by_target"] and not self.rebuilding:
            a["by_target"] = False
            self.restore()
        if not self.minimized and not self.rebuilding:
            rect = self.target_rect()
            if rect is not None:
                x, y, wd, ht = rect
                now = time.perf_counter()
                if (wd, ht) != (self.cw, self.ch):
                    # a new size restarts the picture, once it has held still
                    if a["size_seen"] != (wd, ht):
                        a["size_seen"], a["since"] = (wd, ht), now
                    elif now - a["since"] >= ATTACH_SETTLE:
                        a["size_seen"] = None
                        a["rect"] = rect
                        self.resize_to(x, y, wd, ht)
                elif (x, y) != a["rect"][:2]:
                    a["rect"] = rect
                    self.layout_chrome(x, y, settle=False)
                    self.place()
                    self.aim()
                    self.follow_monitor()
            if self.stages and not self.rebuilding:
                stage = self.visible()
                if (u.GetWindow(h, GW_HWNDPREV) != stage
                        or u.GetWindow(stage, GW_HWNDPREV) != self.chrome):
                    self.stack_above_target()
        self.root.after(50, self.follow_target)

    def stack_above_target(self):
        """Put the picture directly above the target, the line above the
        picture and the tab above the line, none of them topmost."""
        a = self.attach
        if a is None or not self.stages:
            return

        def above(hwnd, ref):
            p = u.GetWindow(ref, GW_HWNDPREV)
            # inserting after a topmost window would make this one topmost;
            # a target with nothing but topmost windows above it is the top
            # of the ordinary band, which is HWND_TOP
            if p and u.GetWindowLongPtrW(p, GWL_EXSTYLE) & WS_EX_TOPMOST:
                p = 0
            u.SetWindowPos(hwnd, p if p else HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        try:
            stage = self.visible()
            above(stage, a["hwnd"])
            above(self.chrome, stage)
            if self.tab is not None:
                th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
                above(th, self.chrome)
        except Exception:
            pass

    def make_tab(self):
        tab = tk.Toplevel(self.root)
        self.tab = tab
        tab.overrideredirect(True)
        tab.configure(bg=ACCENT)
        lbl = tk.Label(tab, text="☰", bg=ACCENT, fg=FIELD, font=("Segoe UI", 8))
        lbl.place(x=0, y=0, width=TAB_W, height=TAB_H)
        for wdg in (tab, lbl):
            wdg.bind("<ButtonPress-1>", self._tab_down)
            wdg.bind("<B1-Motion>", self._tab_move)
            wdg.bind("<ButtonRelease-1>", self._tab_up)
            # the right button slides the tab along the edge, whatever the left
            # one does, so a hidden title bar's tab can be moved out of the way
            wdg.bind("<ButtonPress-3>", self._tab_slide_down)
            wdg.bind("<B3-Motion>", self._tab_slide_move)
            wdg.bind("<ButtonRelease-3>", self._tab_slide_up)
        x, y = self.inner()
        tab.geometry("%dx%d+%d+%d" % (TAB_W, TAB_H, x + self.tab_x, y))
        tab.update()
        th = u.GetParent(tab.winfo_id()) or tab.winfo_id()
        u.SetWindowLongPtrW(th, GWL_EXSTYLE, u.GetWindowLongPtrW(th, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
        u.SetWindowDisplayAffinity(th, WDA_EXCLUDEFROMCAPTURE)

    def place_tab(self, x, y, cw):
        if self.tab is None:
            return
        self.tab_x = max(0, min(self.tab_x, cw - TAB_W))
        try:
            th = u.GetParent(self.tab.winfo_id()) or self.tab.winfo_id()
            u.SetWindowPos(th, 0, x + self.tab_x, y, TAB_W, TAB_H, SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass

    def _tab_slide_down(self, e):
        self.tab_slide = (e.x_root, self.tab_x)

    def _tab_slide_move(self, e):
        if getattr(self, "tab_slide", None) is None:
            return
        x0, tx0 = self.tab_slide
        self.tab_x = tx0 + (e.x_root - x0)
        x, y = self.inner()
        self.place_tab(x, y, self.cw)

    def _tab_slide_up(self, e):
        self.tab_slide = None

    def _tab_down(self, e):
        self.tab_drag = (e.x_root, self.tab_x)
        if self.attach is None and not self.fullscreen:
            self.down(e)                 # folded and free: the tab drags the whole lens

    def _tab_move(self, e):
        if self.tab_drag is None:
            return
        if self.attach is None:
            if not self.fullscreen:
                self.move(e)
                x, y = self.inner()
                self.place_tab(x, y, self.cw)
            return
        x0, tx0 = self.tab_drag
        self.tab_x = tx0 + (e.x_root - x0)
        x, y = self.inner()
        self.place_tab(x, y, self.cw)

    def _tab_up(self, e):
        if self.tab_drag is None:
            return
        x0, _ = self.tab_drag
        self.tab_drag = None
        moved = abs(e.x_root - x0) >= 3
        if self.attach is None and self.drag:
            self.up(e)                   # settles the picture where the drag ended
            x, y = self.inner()
            self.place_tab(x, y, self.cw)
        if not moved:
            self.menu(e, "tab")

    def pointer(self):
        """Where the mouse pointer is, in screen pixels."""
        pt = w.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def menu_anchor(self):
        """Where the menu opens from: (x, top, bottom) of the bar, the tab, or
        the control that asked for it. A fullscreen lens has none of them in
        view, so its menu opens at the pointer when that is on the lens's
        monitor, and else at that monitor's top left corner."""
        if self.fullscreen:
            x, y = self.inner()
            mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
            px, py = self.pointer()
            if mx <= px < mx + mw and my <= py < my + mh:
                return px - 6, py, py
            return mx - 6, my, my
        wdg = self.anchor_widget
        if wdg is not None:
            try:
                return wdg.winfo_rootx() - 6, wdg.winfo_rooty(), wdg.winfo_rooty() + wdg.winfo_height()
            except Exception:
                pass
        if (self.attach is not None or self.folded) and self.tab is not None:
            try:
                tx, ty = self.tab.winfo_rootx(), self.tab.winfo_rooty()
                return tx - 6, ty, ty + TAB_H
            except Exception:
                pass
        return self.t.winfo_x(), self.t.winfo_y(), self.t.winfo_y() + BAR

    def menu_widgets(self):
        """The controls whose clicks the menu leaves alone: they toggle it themselves.
        A fullscreen lens has none of them in view."""
        if self.fullscreen:
            return []
        return [self.menu_btn, self.prof_btn] + ([self.tab] if self.tab is not None else [])

    # ---- updates
    def check_updates(self, quiet, how=None):
        """Ask GitHub for the newest release on a thread, and say what it found
        on the Tk thread: quiet says nothing unless there is something newer.
        how is the way the person at the lens asked, for the log, and none
        for the check at the start."""
        if how:
            self.act("check for a new version (%s)" % how)

        def work():
            try:
                found = _latest_release()
            except Exception as exc:
                found = exc
            try:
                self.root.after(0, lambda: self._updates_reply(found, quiet))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _updates_reply(self, found, quiet):
        if self.closing:
            return
        if isinstance(found, Exception) or found is None:
            if not quiet:
                messagebox.showinfo("Neural Lens", "Could not read the releases page.\n\n%s"
                                    % (found if found is not None else "no release listed"))
            return
        version, url = found[0], found[1]
        asset = tuple(found[2:4]) if len(found) >= 4 else (None, None)
        try:
            with open(os.path.join(DATA_DIR, "update-check.txt"), "w") as f:
                f.write("%d %s\n" % (int(time.time()), version))
        except OSError:
            pass
        if _version_tuple(version) > _version_tuple(__version__):
            self._offer_update(version, url, asset)
        elif not quiet:
            messagebox.showinfo("Neural Lens", "This is the latest version, %s." % __version__)

    def _offer_update(self, version, url, asset):
        """Say a newer version exists and ask what to do. Nothing happens on its
        own, whichever switches are on."""
        asset_url, asset_size = asset
        text = "Neural Lens %s is available. This is %s.\n\n" % (version, __version__)
        if self.auto_update_on and asset_url:
            text += ("It can be downloaded and installed over this one now. Neural Lens quits while "
                     "the installer runs, and comes back on the new version.")
            choices = ["Install it now", "Open the release page", "Not now"]
        else:
            text += "The release page has the installer, which runs over this install."
            choices = ["Open the release page", "Not now"]
        pick = self._ask("Neural Lens update", text, choices)
        if pick == "Open the release page":
            import webbrowser
            webbrowser.open(url)
        elif pick == "Install it now":
            self._install_update(version, asset_url, asset_size)

    def _install_update(self, version, asset_url, asset_size):
        """Download the release's installer to the temp folder, check its size
        against what the release lists, run it silently over this install, and
        quit so it can replace the files. The lens is started again after."""
        import tempfile
        import urllib.request
        dest = os.path.join(tempfile.gettempdir(), "NeuralLens-Setup-%s.exe" % version)
        box = tk.Toplevel(self.root)
        box.title("Neural Lens update")
        box.attributes("-topmost", True)
        box.configure(bg=BG)
        box.resizable(False, False)
        note = tk.Label(box, text="Downloading Neural Lens %s ..." % version, bg=BG, fg=FG,
                        font=("Segoe UI", 10), width=48, anchor="w")
        note.grid(row=0, column=0, padx=14, pady=14)
        self._place_over_lens(box)
        state = {"done": 0, "total": int(asset_size or 0), "error": None, "finished": False}

        def work():
            try:
                req = urllib.request.Request(asset_url, headers={"User-Agent": "neural-lens/" + __version__})
                with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
                    if not state["total"]:
                        state["total"] = int(r.headers.get("Content-Length") or 0)
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        state["done"] += len(chunk)
                got = os.path.getsize(dest)
                if state["total"] and got != state["total"]:
                    raise IOError("the download is %d bytes where the release lists %d" % (got, state["total"]))
            except Exception as exc:
                state["error"] = exc
            state["finished"] = True

        threading.Thread(target=work, daemon=True).start()

        def tick():
            if self.closing:
                return
            if not state["finished"]:
                if state["total"]:
                    note.config(text="Downloading Neural Lens %s ... %d%%"
                                % (version, min(100, 100 * state["done"] // state["total"])))
                self.root.after(200, tick)
                return
            box.destroy()
            if state["error"] is not None:
                messagebox.showinfo("Neural Lens", "The download did not finish, so nothing was changed.\n\n%s"
                                    % state["error"])
                return
            # the installer replaces the files once the lens is gone, and starts
            # the new lens when it is done; its own start entry skips a silent run
            exe = sys.executable if getattr(sys, "frozen", False) else None
            again = (' && start "" "%s"' % exe) if exe else ""
            subprocess.Popen('cmd /c ""%s" /SILENT /NORESTART /CLOSEAPPLICATIONS%s"' % (dest, again),
                             creationflags=CREATE_NO_WINDOW)
            self.quit(how="update")

        tick()

    def check_updates_at_start(self):
        """Once a day at most, when the ini asks for it."""
        if not self.check_updates_on:
            return
        try:
            with open(os.path.join(DATA_DIR, "update-check.txt")) as f:
                last = int(f.read().split()[0])
            if time.time() - last < 86400:
                return
        except Exception:
            pass
        self.check_updates(quiet=True)

    # ---- global hotkeys
    def poll_hotkeys(self):
        if self.closing:
            return
        try:
            # while an NR switch waits for its restart, see nr_by_restart, keys
            # and words wait too, so none of them acts on the presenter that the
            # restart is about to end, as none does during a rebuild
            while self.nr_wait is None and not self.hotkeys.fired.empty():
                self.hotkey_action(self.hotkeys.fired.get_nowait())
            self.poll_commands()
        except Exception:
            pass
        self.root.after(50, self.poll_hotkeys)

    def poll_commands(self):
        """Act on the words that came in with --do, see Commands. A word that
        arrives while the picture is being replaced waits for the new one."""
        heard = self.commands
        while (heard is not None and not (self.closing or self.rebuilding or self.nr_wait is not None)
               and not heard.asked.empty()):
            self.do_command(heard.asked.get_nowait())

    def do_command(self, word):
        """What a word from the taskbar button's list, or from any process
        started with --do, does: what the lens's own hotkey or menu entry for
        it does, in a window as well as fullscreen. A minimised lens comes back
        first, as it does by a click on its taskbar button, and acts then."""
        if self.minimized:
            print("--do %s, which brings the lens back first" % word, flush=True)
            self.restore("taskbar list")
            if not self.minimized:
                self.commands.asked.put(word)       # which poll_commands takes up now that the lens is back
            return
        print("--do %s" % word, flush=True)
        if word == "menu":
            self.menu(None, "taskbar list")         # opens it, or closes the one that is open
        elif word == "nr":
            if self.stages:
                self.toggle_tweak("taskbar list")   # the panel under the fast engine, else ReShade's overlay
        elif word == "fullscreen":
            if self.attach is None:
                self.toggle_fullscreen("taskbar list")
            else:
                self.act("fullscreen left as it is (taskbar list)")
                print("a lens attached to a window stays as it is", flush=True)
                # an attached lens has no bar, so the notice says why, see show_notice
                self.notes["attached"] = ("No fullscreen while attached to a window. Detach it in the lens menu "
                                          "first.", WARN, time.perf_counter() + 6.0)
                self.show_notice()

    def hotkey_action(self, action):
        if self.closing or self.rebuilding:
            return
        if action in NAV_KEYS:
            self.nav_key(action[4:])
            return
        how = "key %s" % HOTKEYS.get(action, action)        # the route the log gives the action
        if action == "screenshot":
            self.take_screenshot(how)
        elif action == "add_pass":
            self.add_pass(how=how)
        elif action == "drop_pass":
            self.drop_pass(how=how)
        elif action in ("quality_up", "quality_down"):
            self.step_quality(1 if action == "quality_up" else -1, how)
        elif action == "split":
            self.toggle_split(how)
        elif action == "minimize":
            if self.minimized:
                self.restore(how)
            else:
                self.minimize(how)
        elif action == "fullscreen":
            if self.attach is None:
                self.toggle_fullscreen(how)
            else:
                self.act("fullscreen left as it is (%s)" % how)     # attached, see do_command
        elif action == "profile":
            names = sorted(self.profiles["profiles"], key=str.lower)
            if names:
                i = names.index(self.profile) + 1 if self.profile in names else 0
                self.apply_profile(names[i % len(names)], how)
            else:
                self.act("no profile to apply (%s)" % how)
        elif action == "hide_bar":
            if self.fullscreen:
                self.act("title bar left as it is (%s)" % how)
                self.say("A fullscreen lens has no title bar.", FG, 4.0, bar=False)
            else:
                self.toggle_fold(how)       # which leaves an attached lens's line and tab as they are
        elif action == "ready":
            self.act("Ready mode %s (%s)" % ("off" if self.ready else "on", how))
            self.summarise(now=True)        # under the mode it had, see summarise
            self.ready = not self.ready
            _save_ini("ready", "1" if self.ready else None)
            self.tell_presenter("ready %d" % (1 if self.ready else 0))
            self.update_info()
        elif action == "detach":
            self.detach(how)
        elif action == "lens_menu":
            if self.fullscreen:
                self.menu(None, how)        # a second press closes it
        elif action == "nr_panel":
            if self.fullscreen and self.engine == "fast":
                self.toggle_panel(how)
            elif self.fullscreen:
                self.tweak_by_key(how)
        elif action == "nr_toggle":
            if self.fullscreen:
                self.toggle_nr(how)
        elif action == "readout_toggle":
            if self.fullscreen:
                self.toggle_readout(how)

    def act(self, text):
        """One line in the log for something the person at the lens did, and
        the way it came: "action menu opened (key F7)". Every such line starts
        with "action ", so a session can be read back step by step."""
        print("action " + text, flush=True)

    def dialog_in_front(self):
        """Whether a dialog of the lens's own is in front, Settings or a
        message box say, which takes the keys itself. Only a real dialog
        counts. The windows made never to take the foreground do not, should
        one be in front all the same: the bar, the tab, the divider, the menu,
        the NR settings panel, the note, the notice and the readout. Nor does
        the hidden window that stands in for the taskbar button, which a click
        on the button brings to the front and which then lies minimised and
        unseen, see show_in_taskbar, nor any window that is minimised."""
        fg = u.GetForegroundWindow()
        if not fg or _window_pid(fg) != os.getpid() or u.IsIconic(fg):
            return False
        return fg not in self.quiet_windows()

    def quiet_windows(self):
        """The handles of the lens's own windows that are no dialog: the
        hidden root, see show_in_taskbar, and the ones that never take the
        foreground, see dialog_in_front."""
        found = set()
        # each looked up as it may be, since the lens asks this from its very
        # start, before its title bar is made, see __init__
        wins = [getattr(self, name, None) for name in ("root", "t", "tab", "divider", "panel", "note_win", "notice",
                                                       "readout_win")]
        for win in wins + [getattr(getattr(self, "popup", None), "win", None)]:
            if win is not None:
                try:
                    found.add(u.GetParent(win.winfo_id()) or win.winfo_id())
                except Exception:
                    pass
        return found

    def nav_wanted(self):
        """Which of NAV_KEYS the lens holds right now. While the lens menu or
        the NR settings panel is open over a fullscreen lens in view, all six,
        so both can be worked from the keyboard while the game keeps the
        foreground and gets none of those keys. While only the note on going
        fullscreen is up, Enter and Escape, which close it. Else none, and a
        windowed lens never holds them. Nor does a lens with a dialog of its
        own in front, Settings say, which takes those keys itself, see
        dialog_in_front, and watch_filter looks at that five times a second.
        Nor does a lens over a program in exclusive fullscreen, where nothing
        of the lens can be seen, see check_exclusive."""
        if not self.fullscreen or self.minimized or self.closing or self.exclusive:
            return ()
        if self.dialog_in_front():
            return ()
        if self.popup.win is not None or self.panel is not None:
            return tuple(NAV_KEYS)
        if self.note_win is not None:
            return ("nav_enter", "nav_escape")
        return ()

    def nav_key(self, name):
        """up, down, left, right, enter or escape, from NAV_KEYS. The menu takes
        them first, then the NR settings panel, then the note, which only
        Enter and Escape close."""
        if self.popup.win is not None:
            self.popup.key(name)
        elif self.panel is not None:
            self.panel_key(name)
        elif self.note_win is not None and name in ("enter", "escape"):
            self.close_note("Enter" if name == "enter" else "Escape")

    def step_quality(self, d, how):
        """The quality step one up or one down, from its hotkey, and the notice
        or the bar says where it is now."""
        now = self.quality_now()
        step = now + d
        if not 0 <= step < len(FAST_QUALITY_NAMES):
            self.say("The quality step is at %s, the %s one." % (FAST_QUALITY_NAMES[now],
                                                                  "highest" if d > 0 else "lowest"), FG, 3.0)
            self.act("quality step stays at %d %s (%s)" % (now, FAST_QUALITY_NAMES[now], how))
            return
        self.set_quality(step, how)
        self.say("Quality step set to %s." % FAST_QUALITY_NAMES[step], FG, 3.0)

    def set_hotkeys(self, mapping):
        """From Settings: record each combination in the ini and register them.
        An action's default is left unwritten, and an action that has a default
        and is to have no key is written as none. A default that the ini then
        has no line for goes where the next start would put it, see
        _hotkey_defaults_again."""
        changed = []
        for action, text in mapping.items():
            text = (text or "").strip()
            if text != HOTKEYS.get(action, ""):
                HOTKEYS[action] = text
                changed.append(action)
                default = HOTKEY_DEFAULTS.get(action, "")
                _save_ini("hotkey_" + action, None if text == default else text or "none")
        changed += _hotkey_defaults_again()
        self.hk_sent = None             # registered afresh, so a key another program let go of is taken now
        self.sync_hotkeys(forget=changed)

    def hotkeys_wanted(self):
        """The combinations to hold right now: every one that is set, the four
        for a fullscreen lens only while the lens is fullscreen and in view, and
        the keys that work its menu, its panel and its note while one is up, see
        nav_wanted. In a window, or minimised, the lens gives the fullscreen
        keys back, so F7 to F10 reach whatever program has the keyboard.
        It gives them back too while a dialog of its own is in front, whose
        fields take them, see dialog_in_front, and while a program is in
        exclusive fullscreen over it, see check_exclusive. They come back once
        the program under the lens is in front again."""
        full = (self.fullscreen and not self.minimized and not self.exclusive
                and not self.dialog_in_front())
        want = {a: text for a, text in HOTKEYS.items() if full or a not in FULL_HOTKEYS}
        for a in self.nav_wanted():
            want[a] = NAV_KEYS[a]
        return want

    def sync_hotkeys(self, forget=()):
        """Register what hotkeys_wanted says, after anything that changes it.
        forget names the actions whose combination Settings has just changed,
        whose records the listener drops, see Hotkeys.

        A key that worked the menu, the panel or the note is let go only once it
        is up again. Let go while it is down, the key's repeats would reach the
        program in front, Escape in a game included, so it is held a little
        longer and looked at again every 50 ms."""
        if self.closing:
            return
        want = self.hotkeys_wanted()
        down = [a for a in self.nav_held if a not in want and u.GetAsyncKeyState(NAV_VK[a]) & 0x8000]
        for a in down:
            want[a] = NAV_KEYS[a]
        if down and not self.nav_wait:
            self.nav_wait = True
            self.root.after(50, self._nav_wait_end)
        self.nav_held = {a for a in want if a in NAV_KEYS}
        if want != self.hk_sent or forget:
            self.hk_sent = dict(want)
            if forget:
                self.hotkeys.set(want, forget=forget)
            else:
                self.hotkeys.set(want)

    def _nav_wait_end(self):
        self.nav_wait = False
        self.sync_hotkeys()

    def key_for(self, action):
        """The combination that brings this action up, as text, or None where
        none is set, the one set cannot be used, another program holds it, or
        the lens holds it for another action, see Hotkeys.dup. That last is
        also read from the combinations themselves, see _hotkey_holder, so it
        is known before the listener has had the action in a mapping, as a
        lens that has not been fullscreen yet has not had the lens menu's."""
        text = HOTKEYS.get(action, "")
        if (not text or _hotkey_problem(text) or action in self.hotkeys.failed
                or action in getattr(self.hotkeys, "dup", {}) or _hotkey_holder(action)):
            return None
        return text

    def keys_list(self):
        """How a fullscreen lens, which has no bar to click, is reached, as
        one sentence for each way, in this order: the key that brings up its
        menu, where Leave fullscreen is, or a click on the taskbar button
        where no key does, then the keys that bring up the NR settings, turn
        Neural Rendering off and on and show or hide the on-screen readout,
        and last the keys that work the menu and the panel. A key that is not
        set, or that the lens does not hold, is left out, see key_for. The
        note on going fullscreen lists these one to a line."""
        menu, panel = self.key_for("lens_menu"), self.key_for("nr_panel")
        nr, readout = self.key_for("nr_toggle"), self.key_for("readout_toggle")
        if menu:
            lines = ["%s opens the lens menu, where Leave fullscreen %s."
                     % (menu, "is" if panel else "and the NR settings are")]
        else:
            lines = ["A click on the lens's taskbar button opens the lens menu, where Leave fullscreen and the "
                     "NR settings are."]
        if panel:
            lines.append("%s opens the NR settings%s." % (panel, "" if menu else " too"))
        if nr:
            lines.append("%s turns Neural Rendering off and on." % nr)
        if readout:
            lines.append("%s shows or hides the on-screen readout." % readout)
        lines.append("The arrow keys, Enter and Escape work the menu and the NR settings panel while one is open.")
        return lines

    def keys_words(self):
        """How a fullscreen lens, which has no bar to click, is reached, in
        four parts. keys: the first of keys_list, the way to the lens menu.
        more: the rest of keys_list as one paragraph. held: which of the
        fullscreen keys another program holds, or None. twice: which of them
        the lens holds for another of its actions, naming it, or None.

        The note on going fullscreen lists keys_list and says held and twice.
        Settings, Fullscreen has keys on its page and more in the explanation
        that comes up for it, so keys stays one sentence."""
        keys, *more = self.keys_list()
        more = " ".join(more)
        taken = [HOTKEYS[a] for a in FULL_HOTKEYS if a in self.hotkeys.failed and HOTKEYS.get(a)]
        held = None
        if taken:
            named = ", ".join(taken[:-1]) + " and " + taken[-1] if len(taken) > 1 else taken[0]
            held = "%s %s in use by another program." % (named, "is" if len(taken) == 1 else "are")
        dup = getattr(self.hotkeys, "dup", {})
        twice = " ".join("%s is held for %s." % (HOTKEYS[a], HOTKEY_LABELS.get(dup[a], dup[a]))
                         for a in FULL_HOTKEYS if a in dup and HOTKEYS.get(a)) or None
        return keys, more, held, twice

    def nr_keys(self):
        """The keys that turn Neural Rendering off and on right now, as a list
        such as ["F6", "F9"], which _either makes "F6 or F9". F6 does under
        the ReShade engine, whose add-on reads it itself, and never under the
        fast engine, which has the NR key alone, see _nr_toggled. The NR key
        is held only while the lens is fullscreen and in view."""
        keys = ["F6"] if self.engine != "fast" else []
        if self.fullscreen and not self.minimized and self.key_for("nr_toggle"):
            keys.append(self.key_for("nr_toggle"))
        return keys

    def note_first(self):
        """The note's first line: the lens is out of sight while the picture
        goes on, or, while Neural Rendering is off, that it is off and what
        brings it back, with the keys as they are set."""
        if self.nr_on:
            return NOTE_WORDS
        return NOTE_OFF_WORDS % _either(self.nr_keys() + ["Turn NR back on in the lens menu"])

    def own_pids(self):
        """The ids of the lens's own processes: this one and its presenters."""
        return {os.getpid()} | {s["proc"].pid for s in self.stages if s.get("proc") is not None}

    def own_foreground(self, fg=None):
        """Whether the window in front, or fg where it is given, is one of the
        lens's own: one of this process, or its presenter's. Only then may the
        lens attach to an input queue, and only to the one of the very window
        it judged, see hand_focus_back."""
        if fg is None:
            fg = u.GetForegroundWindow()
        if not fg:
            return False
        return fg in {s["hwnd"] for s in self.stages} or _window_pid(fg) in self.own_pids()

    def show_note(self):
        """The note a lens shows as it goes fullscreen, where it has no bar:
        the lens itself is out of sight while the picture goes on, the keys of
        a fullscreen lens one to a line, see keys_list, and the taskbar
        button's list. A small window of the lens's own over the middle of
        its monitor, out of the picture and never taking the keyboard, so a
        game under the lens keeps it. OK closes it, and so do Enter and
        Escape, which the lens holds while it is up, see nav_wanted. Don't
        show this again switches it off the moment it is ticked, see
        set_note, and Settings, Fullscreen switches it on again. It shows all
        the same when another program holds one of the fullscreen keys, since
        a key then does nothing, and a note that is switched off then has no
        Don't show this again. A key the lens holds for another of its own
        actions is named on a note that shows, and does not bring it up. Over
        a program in exclusive fullscreen, where it cannot be seen, it does
        not show, see check_exclusive."""
        if self.closing or not self.fullscreen or self.minimized or self.exclusive:
            return
        _keys, _more, held, twice = self.keys_words()
        if not (self.fs_note or held):
            return
        self.close_note()
        t = self.note_win = self._own_window()
        t.configure(bg=ACCENT)
        box = tk.Frame(t, bg=BG)
        box.pack(padx=1, pady=1)
        tk.Label(box, text="Fullscreen", bg=BG, fg=FG, font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=18, pady=(14, 6))
        font = ("Segoe UI", 11)

        def line(text, colour=FG):
            lbl = tk.Label(box, text=text, bg=BG, fg=colour, font=font, justify="left", wraplength="330p")
            lbl.pack(anchor="w", padx=18, pady=(0, 6))
            return lbl

        t.first, t.nr_on = line(self.note_first()), self.nr_on     # see note_nr
        # the keys one to a line, each after a bullet in a column of its own, so
        # a line that wraps goes on under its words and not under the bullet
        listed = tk.Frame(box, bg=BG)
        listed.pack(anchor="w", padx=18, pady=(0, 6))
        for i, text in enumerate(self.keys_list()):
            tk.Label(listed, text="•", bg=BG, fg=FG, font=font).grid(row=i, column=0, sticky="nw", padx=(0, 8))
            tk.Label(listed, text=text, bg=BG, fg=FG, font=font, justify="left", wraplength="316p").grid(
                row=i, column=1, sticky="w", pady=(0, 2))
        line(NOTE_TASKBAR)
        for text in (held, twice):
            if text:
                line(text, WARN)
        row = tk.Frame(box, bg=BG)
        row.pack(fill="x", padx=18, pady=(8, 14))
        # only while the note is switched on, since one that shows because
        # another program holds a key would come back all the same
        if self.fs_note:
            quiet = tk.BooleanVar(master=t, value=False)
            tk.Checkbutton(row, text="Don't show this again", variable=quiet,
                           command=lambda: self.set_note(not quiet.get(), "Don't show this again"), bg=BG, fg=FG,
                           selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).pack(side="left")
        tk.Button(row, text="OK", command=lambda: self.close_note("OK"), relief="flat", bg=ACCENT,
                  fg=FIELD, activebackground=HOVER, font=("Segoe UI", 10), padx=18).pack(side="right")
        self._place_note(t)
        print("the fullscreen note is up%s%s" % (", with a key held by another program" if held else "",
                                                ", with a key held for another of the lens's actions" if twice
                                                else ""), flush=True)
        self.sync_hotkeys()             # Enter and Escape close it

    def _place_note(self, t):
        """Size the note to what it holds, over the middle of the lens's
        monitor, and show it the first time, see _show_own."""
        try:
            t.update_idletasks()
            wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
            x, y = self.inner()
            mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
            t.geometry("%dx%d+%d+%d" % (wd, ht, mx + max(0, (mw - wd) // 2), my + max(0, (mh - ht) // 2)))
            if t.state() == "withdrawn":
                self._show_own(t, 0.98)
            else:
                t.update_idletasks()
                self._own_styles(t)
        except Exception:
            pass

    def note_nr(self):
        """A key or the menu can switch Neural Rendering while the note is up,
        and a change of engine changes the keys that bring it back, so its
        first line follows what note_first says now. It changes in place, since
        showing the note again would drop it once Don't show this again is
        ticked."""
        t = self.note_win
        if t is None:
            return
        text = self.note_first()
        try:
            if t.first.cget("text") == text:
                return
            t.first.config(text=text)
        except Exception:
            return
        t.nr_on = self.nr_on
        self._place_note(t)
        print("the fullscreen note now says Neural Rendering is %s" % ("on" if self.nr_on else "off"), flush=True)

    def close_note(self, how=None):
        """Take the note on going fullscreen away. how is the way the person at
        the lens closed it, OK, Enter or Escape, for the log. The lens closing
        it itself gives none."""
        t, self.note_win = self.note_win, None
        if t is not None:
            if how:
                self.act("note closed (%s)" % how)
            try:
                t.destroy()
            except Exception:
                pass
            self.sync_hotkeys()         # Enter and Escape go back once they are up

    def set_note(self, on, how=None):
        """Switch the note on going fullscreen on or off, and the ini with it,
        where on is the default and is left unwritten. The note's Don't show
        this again calls this the moment it is ticked or unticked, so the tick
        counts however the note then closes."""
        if on == self.fs_note:
            return
        if how:
            self.act("note switched %s (%s)" % ("on" if on else "off", how))
        self.fs_note = on
        try:
            _save_ini("fullscreen_note", None if on else "0")
        except OSError:
            pass
        print("the fullscreen note is switched %s" % ("on" if on else "off"), flush=True)

    def tweak_by_key(self, how=None):
        """Tweak mode on or off from the NR settings hotkey, under the ReShade
        engine, once the keys of the hotkey are up again.

        ReShade opens and closes its overlay on a Home the lens posts to the
        presenter. With the hotkey's own keys still down, a combination with
        Home in it such as Ctrl+Home, which Settings can set, ReShade would read
        that Home together with them, or the key still held as a second press.
        So the lens waits for them to be let go, two seconds at most.
        watch_home stands still meanwhile, since it would take the hotkey's Home
        for the user's own, which ends tweak mode."""
        if self.key_wait:
            return
        want = not self.tweak
        parsed = _parse_hotkey(HOTKEYS.get("nr_panel", ""))
        keys = []
        if parsed:
            keys = [parsed[1]] + [vk for flag, vk in ((MOD_CONTROL, 0x11), (MOD_ALT, 0x12), (MOD_SHIFT, 0x10),
                                                      (MOD_WIN, 0x5B), (MOD_WIN, 0x5C)) if parsed[0] & flag]
        self.key_wait = True

        def look(tries):
            if tries > 0 and not self.closing and any(u.GetAsyncKeyState(vk) & 0x8000 for vk in keys):
                self.root.after(50, look, tries - 1)
                return
            self.key_wait = False
            if (not self.closing and not self.rebuilding and not self.minimized and self.fullscreen
                    and self.engine != "fast" and self.stages and self.tweak != want):
                self.toggle_tweak(how)

        look(40)

    # ---- profiles
    # A profile is everything that makes the picture, under a name: the windowed
    # place and size, fullscreen, the pass count, the Cost Scaler rule, the
    # motion detail, ready, the frame rate limit, what the title bar shows, and
    # the add-on's whole section of ReShade.ini,
    # which is every setting the Home menu holds. Applying one writes all of
    # that and restarts the picture, since the add-on reads its settings only
    # when its process starts. The selector on the bar switches; Settings
    # renames and deletes.
    def capture_profile(self):
        if self.attach is not None:
            cw, ch, x, y = self.attach["saved"]
        elif self.fullscreen:
            cw, ch, x, y = 1400, 1000, 100, 100
            try:
                v = [int(n) for n in open(STATE).read().split()]
                cw, ch, x, y = v[:4]
            except Exception:
                pass
        else:
            x, y = self.inner()
            cw, ch = self.cw, self.ch
        addon = {k: v for k, v in _read_addon_section().items() if k not in ADDON_KEEP}
        return {"width": cw, "height": ch, "x": x, "y": y, "fullscreen": bool(self.fullscreen),
                "passes": self.passes, "cost_scaler": COST_SCALER, "ready": bool(self.ready),
                "max_fps": int(self.max_fps), "motion_detail": self.motion_detail,
                "readout": self.readout, "latency": bool(self.latency_on),
                "title_size": bool(self.show_size), "title_style": bool(self.show_style),
                "title_intensity": bool(self.show_intensity), "addon": addon}

    def show_bar_mirrors(self):
        """Put the Home menu's style and intensity on the bar, or take them off,
        as Settings says, and read them once."""
        for widget, on in ((self.style_btn, self.show_style), (self.intensity_lbl, self.show_intensity)):
            if on:
                widget.pack(side="left")
            else:
                widget.pack_forget()
        self.mirror_addon()

    def mirror_addon(self):
        """The bar's copy of the Home menu's style and intensity, from the add-on's
        section. Called once a second while either is shown."""
        if not (self.show_style or self.show_intensity):
            return
        try:
            a = _read_addon_section()
        except Exception:
            return
        self.addon_seen = a
        self.style_btn.config(text="▾ " + STYLE_NAMES.get(str(a.get("NRStyle", "0")).strip(), "Default"))
        try:
            self.intensity_lbl.config(text="intensity %.2f" % float(a.get("NRIntensity", "1")))
        except ValueError:
            self.intensity_lbl.config(text="intensity ?")

    def list_menu(self, items, name, anchor, how):
        """Open one of the title bar's lists, name being the style list or the
        profile list, under its button, or with that list, the other or the
        lens menu open, close it instead. The log has a line either way, which
        names the list. how is the way it was asked for, for the log."""
        was = self.popup.name if self.popup.win is not None else None
        self.anchor_widget = anchor
        try:
            self.popup.toggle(items, name)
        finally:
            self.anchor_widget = None
        if was is not None:
            self.act("%s closed (%s)" % (was, how))
        elif self.popup.win is not None:
            self.act("%s opened (%s)" % (name, how))

    def style_menu(self, how="title bar"):
        cur = str(self.addon_seen.get("NRStyle", "0")).strip()
        items = [("%s%s" % (name, "   ✓" if code == cur else ""), lambda c=code: self.set_style(c), True)
                 for code, name in STYLE_NAMES.items()]
        self.list_menu(items, "style list", self.style_btn, how)

    def set_style(self, code):
        """Write the style into the add-on's section and restart the picture, which
        is when the add-on reads it."""
        if self.closing or self.rebuilding or self.rs is not None:
            return
        vals = _read_addon_section()
        if str(vals.get("NRStyle", "0")).strip() == str(code):
            return
        vals["NRStyle"] = str(code)
        _replace_addon_section(vals)
        self.mirror_addon()
        self.update_profile_label()
        self.restart_presenter("NR style %s, restarting ..." % STYLE_NAMES.get(str(code), code))

    def profile_menu(self, how="title bar"):
        names = sorted(self.profiles["profiles"], key=str.lower)
        items = []
        for n in names:
            items.append(("%s%s" % (n, "   ✓" if n == self.profile else ""),
                          lambda n=n: self.apply_profile(n), n != self.profile or True))
        if names:
            items.append(None)
        items.append(("Save the current settings as a new profile...", self.profile_save_as, True))
        if self.profile in self.profiles["profiles"]:
            items.append(("Update '%s' with the current settings" % self.profile,
                          lambda: self.profile_store(self.profile), True))
        items.append(("Manage profiles in Settings...", self.settings_dialog, True))
        self.list_menu(items, "profile list", self.prof_btn, how)

    def profile_store(self, name, how=None):
        """Save what the lens is now under this name, and make it the one in
        use. how is the way the person at the lens asked, for the log."""
        name = (name or "").strip()
        if not name:
            return
        if how:
            self.act('profile "%s" saved (%s)' % (name, how))
        self.profiles["profiles"][name] = self.capture_profile()
        self.profiles["current"] = self.profile = name
        _save_profiles(self.profiles)
        print("profile %r saved" % name, flush=True)
        self.update_profile_label()

    def profile_save_as(self):
        """Ask for a name, then store the current settings under it."""
        d = tk.Toplevel(self.root)
        d.title("New profile")
        d.attributes("-topmost", True)
        d.configure(bg=BG)
        tk.Label(d, text="A name for these settings, such as Video, Text or Photo", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 4))
        var = tk.StringVar(master=d, value="")
        n = 1
        while "Profile %d" % n in self.profiles["profiles"]:
            n += 1
        var.set("Profile %d" % n)
        ent = tk.Entry(d, textvariable=var, width=32, bg=FIELD, fg=FG, insertbackground=FG, relief="flat")
        ent.grid(row=1, column=0, columnspan=2, sticky="we", padx=12)
        ent.selection_range(0, "end")

        def save(*event):
            name = var.get().strip()
            d.destroy()
            if name:
                self.profile_store(name, "Enter" if event else "Save")

        tk.Button(d, text="Save", command=save, relief="flat", bg=ACCENT, fg=FIELD).grid(
            row=2, column=0, sticky="e", padx=(12, 4), pady=12)
        tk.Button(d, text="Cancel", command=d.destroy, relief="flat", bg=HOVER, fg=FG).grid(
            row=2, column=1, sticky="w", padx=(4, 12), pady=12)
        ent.bind("<Return>", save)
        d.update_idletasks()
        x, y = self.inner()
        d.geometry("+%d+%d" % (x + 40, y + 40))
        ent.focus_force()

    def profile_delete(self, name, how=None):
        """Delete this profile. how is the way the person at the lens asked,
        for the log."""
        if name in self.profiles["profiles"]:
            if how:
                self.act('profile "%s" deleted (%s)' % (name, how))
            del self.profiles["profiles"][name]
            if self.profile == name:
                self.profile = self.profiles["current"] = None
            _save_profiles(self.profiles)
            self.update_profile_label()

    def profile_rename(self, old, new, how=None):
        """Give this profile a new name. how is the way the person at the lens
        asked, for the log."""
        new = (new or "").strip()
        if old not in self.profiles["profiles"]:
            return
        if not new or new == old:
            if how:
                self.act('profile "%s" keeps its name (%s)' % (old, how))
            return
        if how:
            self.act('profile "%s" renamed to "%s" (%s)' % (old, new, how))
        self.profiles["profiles"][new] = self.profiles["profiles"].pop(old)
        if self.profile == old:
            self.profile = self.profiles["current"] = new
        _save_profiles(self.profiles)
        self.update_profile_label()

    def apply_profile(self, name, how=None):
        """Make the lens what this profile says: the settings, the add-on's
        section, and the picture restarted at the profile's place, size and
        pass count. Attached, the target keeps the place and size. how is the
        way the person at the lens asked, for the log."""
        p = self.profiles["profiles"].get(name)
        if p is None or self.closing or self.rebuilding or self.rs is not None:
            return
        if how:
            self.act('profile "%s" applied (%s)' % (name, how))
        self.summarise(now=True)        # what the fast engine did under the settings before, see summarise
        if self.minimized:
            self.restore()
        self.popup.close()
        self.profiles["current"] = self.profile = name
        _save_profiles(self.profiles)
        print("profile %r applied" % name, flush=True)
        # the settings the bar and Settings hold, each written to the ini as
        # Settings would write it
        self.readout = p.get("readout", self.readout)
        _save_ini("readout", None if self.readout == "size" else self.readout)
        self.latency_on = bool(p.get("latency", self.latency_on))
        self.latency_ms = None
        _save_ini("latency", None if self.latency_on else "0")
        self.show_size = bool(p.get("title_size", self.show_size))
        _save_ini("title_size", None if self.show_size else "0")
        self.show_style = bool(p.get("title_style", self.show_style))
        _save_ini("title_style", "1" if self.show_style else None)
        self.show_intensity = bool(p.get("title_intensity", self.show_intensity))
        _save_ini("title_intensity", "1" if self.show_intensity else None)
        self.show_bar_mirrors()
        self.ready = bool(p.get("ready", self.ready))
        _save_ini("ready", "1" if self.ready else None)
        # a profile from before the limit existed keeps whatever is set now
        if "max_fps" in p:
            self.max_fps = int(p.get("max_fps") or 0)
            _save_ini("max_fps", str(self.max_fps) if self.max_fps else None)
        if p.get("motion_detail") in ("full", "half", "quarter"):
            self.motion_detail = p["motion_detail"]
            _save_ini("motion_detail", None if self.motion_detail == "full" else self.motion_detail)
        mode = p.get("cost_scaler", COST_SCALER)
        if COST_SCALER != "manual" and mode in ("off", "fullscreen", "always") and mode != COST_SCALER:
            _set_cost_scaler(mode)
        # the Home menu, whole, for the presenter about to start
        if isinstance(p.get("addon"), dict):
            _replace_addon_section(p["addon"])
        self.passes = self.pending = max(1, min(_pass_limit(), int(p.get("passes", self.passes))))
        cw, ch = int(p.get("width", self.cw)), int(p.get("height", self.ch))
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        full = bool(p.get("fullscreen"))
        if self.attach is not None:
            self.resize_to(*self.attach["rect"])
        elif full:
            # a fullscreen lens keeps its own pass count, read from this file
            try:
                with open(FULL_STATE, "w") as f:
                    f.write("%d\n" % self.passes)
            except OSError:
                pass
            self.set_fullscreen(True, how="profile")
        elif self.fullscreen:
            # the way back reads the windowed geometry and count from this file
            try:
                with open(STATE, "w") as f:
                    f.write("%d %d %d %d %d\n" % (cw, ch, x, y, self.passes))
            except OSError:
                pass
            self.set_fullscreen(False, how="profile")
        else:
            x, y, cw, ch = fit_rect(x, y, cw, ch)
            self.resize_to(x, y, cw, ch)
        self.save_state()
        self.update_info()

    def toggle_split(self, how=None):
        """The live A/B split on or off. how is the way the person at the lens
        asked, for the log."""
        if self.closing:
            return
        if how:
            self.act("A/B split %s (%s)" % ("on" if self.split is None else "off", how))
        if self.split is None:
            self.split = 0.5
            d = tk.Toplevel(self.root)
            d.overrideredirect(True)
            d.attributes("-topmost", True)
            d.configure(bg=BG, cursor="sb_h_double_arrow")
            # a wider grab area than the line itself, so it is easy to catch
            tk.Frame(d, bg=ACCENT).place(x=DIVIDER // 2 - 2, y=0, width=4, relheight=1.0)
            d.bind("<ButtonPress-1>", self._split_down)
            x, y = self.inner()
            d.geometry("%dx%d+%d+%d" % (DIVIDER, self.ch, x + self.cw // 2 - DIVIDER // 2, y))
            self.divider = d
            # idle tasks only: a full update() here runs the lens's own timers
            # in the middle of building the window
            d.update_idletasks()
            h = u.GetParent(d.winfo_id()) or d.winfo_id()
            u.SetWindowLongPtrW(h, GWL_EXSTYLE,
                                u.GetWindowLongPtrW(h, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
            u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)
        else:
            self.split = None
            try:
                self.divider.destroy()
            except Exception:
                pass
            self.divider = None
        self.apply_split()
        self.place_divider()

    def apply_split(self):
        """Clip the presenter to the left of the divider, or unclip it."""
        for s in list(self.stages):
            try:
                if self.split is None:
                    u.SetWindowRgn(s["hwnd"], None, True)
                else:
                    px = max(0, min(self.cw, int(self.cw * self.split)))
                    # the system owns the region once it is set
                    u.SetWindowRgn(s["hwnd"], ctypes.windll.gdi32.CreateRectRgn(0, 0, px, self.ch),
                                   True)
            except Exception:
                pass

    def place_divider(self):
        if self.divider is None or self.split is None:
            return
        x, y = self.inner()
        px = int(self.cw * self.split)
        # not tk's geometry(): while the mouse button is held on this window
        # Tk ignores it, and the line the user is dragging never moves
        try:
            h = u.GetParent(self.divider.winfo_id()) or self.divider.winfo_id()
            u.SetWindowPos(h, 0, x + px - DIVIDER // 2, y, DIVIDER, self.ch,
                           SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            self.divider.geometry("%dx%d+%d+%d" % (DIVIDER, self.ch, x + px - DIVIDER // 2, y))
        self.raise_chrome()

    def _split_down(self, e):
        """Follow the mouse until the button is released.

        Not tk's motion events: the divider is a thin window under a click
        through neighbour, and a drag that starts on it has to keep working
        after the pointer has left it. A thread polls the button and the cursor
        instead and hands each position to the mainloop.
        """
        self.drag = None            # never a lens drag while on the divider
        if getattr(self, "_split_dragging", False):
            return
        self._split_dragging = True

        def follow():
            try:
                while not self.closing and u.GetAsyncKeyState(0x01) & 0x8000:
                    p = w.POINT()
                    u.GetCursorPos(ctypes.byref(p))
                    self.root.after(0, self.split_to, p.x)
                    time.sleep(0.01)
            finally:
                self._split_dragging = False

        threading.Thread(target=follow, daemon=True).start()

    def split_to(self, x_root):
        if self.split is None:
            return
        x, _ = self.inner()
        split = max(0.0, min(1.0, (x_root - x) / float(self.cw)))
        if split != self.split:
            self.split = split
            self.apply_split()
            self.place_divider()

    # ---- passes
    def set_passes(self, n, save=True, how=None):
        """Restart the presenter at n passes.

        The add-on reads its pass count when its process starts, so the count
        is written to ReShade.ini once the old presenter is gone and before
        the new one spawns. The Cost Scaler's scale follows the count. how is
        the way the person at the lens asked, for the log.
        """
        n = max(1, min(_pass_limit(), n))
        if how:
            self.act(("passes %d (%s)" if n != self.passes else "passes stay at %d (%s)") % (n, how))
        self.pending = n
        if self.closing or n == self.passes:
            self.update_info()
            return
        self.summarise(now=True)        # under the count it had, see summarise
        self.passes = n
        self.restart_presenter("restarting at %d pass%s ..." % (n, "" if n == 1 else "es"), save)

    def follow_monitor(self):
        """Restart the presenter when the lens has been dragged onto another monitor.

        The presenter captures the monitor the lens was on when it started, so
        over another monitor it crops the wrong picture. It does while the drag
        lasts; once the lens is let go there, it starts again on that monitor.
        """
        if self.closing or self.fullscreen or not self.stages:
            return
        x, y = self.inner()
        _, mx, my = monitor_of(x + self.cw // 2, y + self.ch // 2)
        if (mx, my) != (self.mon_x, self.mon_y):
            print("the lens moved to the monitor at (%d,%d)" % (mx, my), flush=True)
            self.restart_presenter("moving to this monitor ...")

    def restart_presenter(self, note, save=True, stand_in=False, nr=None):
        """Replace the presenter with a new one at the lens's place, pass count and
        monitor, since all three are fixed when a presenter starts. stand_in
        keeps the stack presenter where the lens wants the fast engine, see
        pick_engine. nr, when given, goes into ReShade.ini as NeuralUplift once
        the old presenter is gone, so the new one starts with Neural Rendering
        on or off as the lens asks, see nr_by_restart. Should ReShade.ini not
        take it, the lens goes by what the file says, which the new add-on
        starts with, and says that the switch did not take. A switch that
        waits for the overlay's last write goes with this restart."""
        if self.nr_wait is not None:
            self.nr_wait = None
            if nr is None:
                nr = self.nr_on
                print("Neural Rendering %s, through ReShade.ini and a restart" % ("on" if nr else "off"), flush=True)
        # the summary of what the engine that goes did since the last one, and
        # the next one covers the engine that comes alone, see summarise
        self.summarise(now=True)
        if self.recover_after is not None:
            try:
                self.root.after_cancel(self.recover_after)
            except Exception:
                pass
            self.recover_after = None
        self.recover_held = False
        self.healthy_since = self.last_arrival = time.perf_counter()
        self.say(note, WARN, 30.0)      # until the new picture is up, see below
        self.root.update_idletasks()
        # Tweak mode applied to the presenter about to be replaced, and its
        # successor is built click-through, so the flag has to come back down
        # or the lens believes it is interactive while behaving otherwise. The
        # ReShade overlay itself goes with the process that was hosting it, and
        # the keyboard goes back as it would on Done.
        if self.tweak:
            prev = self.tweak_prev
            self.root.after(0, lambda: self.hand_focus_back(prev, None))
        self.tweak = False
        # and the add-on that wrote the overlay's values goes too, so there is
        # nothing more of it to follow, see follow_overlay and nr_by_restart
        self.tweak_until = 0.0
        self.rebuilding = True
        unswitched = False              # Neural Rendering was to be switched, and ReShade.ini did not take it
        try:
            for s in reversed(self.stages):
                self._kill_stage(s)
            self.stages = []
            self.pick_engine(stand_in)  # before the proxy's ini, which the fast engine leaves alone
            self.apply_proxy()
            if nr is not None and not _set_addon_values({"NeuralUplift": "1" if nr else "0"}):
                unswitched = True
                print("ReShade.ini could not be written, so Neural Rendering starts as the file says", flush=True)
            if ADDON_PASSES:
                _write_addon_settings(self.passes)
            self.sync_motion_detail()
            self.latency_ms = None
            self.frames, self.t_first = 0, None
            x, y = self.inner()
            try:
                self._build_presenter(x, y)
            except SystemExit:
                self.info.config(text="the presenter failed to start", fg=WARN)
            if self.stages:
                self.apply_split()
        except Exception:
            # Windows refusing to start the presenter at all, say. The error goes
            # into the log and the lens carries on below as it does after any
            # start that failed. It must not stay rebuilding: such a lens takes
            # no hotkey, no word and no click on its taskbar button, and a
            # fullscreen lens has no bar to close it by
            import traceback
            traceback.print_exc()
        self.rebuilding = False
        if not self.stages:
            # nothing left to show. visible() is stages[-1], so carrying on would
            # raise on the next menu action rather than here, where it is clear.
            messagebox.showerror("Neural Lens",
                                 "The presenter could not be started, so Neural Lens has to quit.\n"
                                 "The most recent logs are in this folder.\n%s" % LOGDIR)
            print("quit (the presenter could not be started)", flush=True)
            self.quit()
            return
        # the note has had its time, and the NR settings panel is the fast
        # engine's: it goes with that engine, and under a new one it shows what
        # the file holds now
        self.notes.pop("note", None)
        if unswitched:
            # the new add-on started as the file says, and so the lens goes by it
            self.nr_on = _read_nr_enabled()
            word = "on" if self.nr_on else "off"
            print("Neural Rendering %s, as ReShade.ini has it" % word, flush=True)
            self.hold_note("Neural Rendering stays %s, since ReShade.ini could not be written." % word, 8.0,
                           windowed=True)
        self.show_notice()
        if self.engine != "fast":
            self.close_panel()
        else:
            self.load_panel()
        self.raise_chrome()
        self.aim()
        self.update_info()
        # the next summary covers the engine that runs now from its start
        self.summary_at = time.perf_counter()
        if save:
            self.save_state()

    def capture_lost(self, reason, proc=None):
        """Start the presenter again when its capture has ended.

        Windows ends a monitor capture when the displays change: measured, with a
        second monitor switched on while the lens ran, the presenter went on
        presenting its last frame, and switching that monitor off again did not
        bring its capture back. A new presenter captures afresh, on the monitor
        under the lens as the displays are now. A screen that is off or locked
        stops frames as well, so the wait before each new start doubles, up to a
        minute, until a presenter has run for half a minute.

        proc is the presenter that said it. One that has been replaced since is
        not listened to: its line can arrive late, after its successor is up,
        because the reader's call into Tk waits while the lens starts a presenter.
        """
        if self.closing or self.minimized or self.recover_after is not None:
            return
        if proc is not None and not any(s["proc"].pid == proc.pid for s in self.stages):
            return
        if time.perf_counter() - self.healthy_since > 30.0:
            self.recover_wait = 1.0
        delay, self.recover_wait = self.recover_wait, min(60.0, self.recover_wait * 2)
        print("capture lost (%s); starting the presenter again in %.0f s" % (reason, delay), flush=True)
        self.recover_after = self.root.after(int(delay * 1000), self._recover)

    def _recover(self):
        """The start a lost capture asked for, unless frames have come back.

        Under a locked screen, or while a prompt of Windows is up, nothing is
        started: no presenter gets a picture then, and a fast engine started
        blind shows no window at all. The lens looks again every second, and once
        the desktop is back gives the presenter it has a moment to report frames.

        Frames have come back when a report of them was read after the loss was
        said. The stats line a presenter prints in the same second, just before
        it says the loss, counts frames from before it and must not. For the
        stack presenter the report also has to be fresh, since it says a loss
        once and no more. The fast engine watches its capture again as soon as
        frames return, and says a new loss anew.

        While the stack presenter stands in for a fast engine that got no
        picture, see spawn_presenter, frames it has just had mean the screen
        gives pictures again, so the fast engine is started, and the stand-in
        was the proof it needs to be judged by. Without frames the stand-in is
        started again as any presenter is, and the fast engine is left alone.
        """
        self.recover_after = None
        if self.closing or self.rebuilding or self.minimized:
            self.recover_held = False
            return
        if not desktop_is_the_users():
            if not self.recover_held:
                self.recover_held = True
                print("the screen is locked or a prompt of Windows is up, so no presenter is started "
                      "until the desktop is back", flush=True)
            self.recover_after = self.root.after(1000, self._recover)
            return
        if self.recover_held:
            self.recover_held = False
            print("the desktop is back", flush=True)
            self.recover_after = self.root.after(1500, self._recover)
            return
        now = time.perf_counter()
        standing = self.standing_in()
        if standing:
            fed = self.fed_at > self.stand_in and now - self.fed_at < 1.5
        else:
            fed = self.last_arrival > self.lost_at and (self.engine == "fast"
                                                        or now - self.last_arrival < 1.5)
            if fed:
                return                      # frames came back by themselves
        self.layout = monitor_layout()
        self.layout_seen = (self.layout, time.perf_counter())
        if self.refit():
            return
        if standing and fed:
            print("the screen gives pictures again, so the fast engine is started again", flush=True)
            self.held = None                # the sentence about the stand-in has had its day
            self.notes.pop("held", None)
            self.fast_retry = True
            self.restart_presenter("back to the fast engine ...")
        else:
            self.restart_presenter("capture ended, starting again ...", stand_in=standing)

    def watch_layout(self):
        """Start the presenter again once the monitor layout has changed and settled.

        A display being added, removed or rearranged renumbers the monitors and
        ends the presenter's capture, so there is no point waiting for the loss to
        be reported. The layout is read on the 200 ms timer and acted on once it
        has held still for a second, since one change arrives as several.
        Fullscreen covers its monitor again as it is now. A minimised lens
        waits: restore compares the layout and starts again if it must.
        """
        now = monitor_layout()
        if now != self.layout_seen[0]:
            self.layout_seen = (now, time.perf_counter())
            return
        if (now == self.layout or self.closing or self.rebuilding or self.minimized
                or time.perf_counter() - self.layout_seen[1] < 1.0):
            return
        print("the monitors changed: %s" % (now,), flush=True)
        self.layout = now
        if self.fullscreen:
            self.set_fullscreen(True, "the monitors changed, starting again ...")
            return
        if self.refit():
            return
        self.restart_presenter("the monitors changed, starting again ...")

    def refit(self):
        """Keep the windowed lens on one monitor as the displays are now.

        A lens that only needs moving is moved. One that has to shrink gets a
        new picture at the smaller size, the same way a resize does, and this
        returns True. Fullscreen already covers exactly its monitor.
        """
        if self.fullscreen or self.closing or self.attach is not None:
            return False
        x, y = self.inner()
        nx, ny, ncw, nch = fit_rect(x, y, self.cw, self.ch)
        if (ncw, nch) != (self.cw, self.ch):
            print("the lens no longer fits its monitor; resizing to %d x %d" % (ncw, nch), flush=True)
            self.resize_to(nx, ny, ncw, nch)
            return True
        if (nx, ny) != (x, y):
            self.t.geometry("+%d+%d" % (nx - EDGE, ny - BAR))
            self.t.update()                 # so inner() reads the new place
            self.place()
            self.aim()
            self.save_state()
        return False

    def sync_motion_detail(self):
        """Write the motion detail into the preset for a presenter about to start.

        A value the preset holds that differs from the one the lens last wrote
        was chosen in the ReShade overlay, which writes the preset back, so it is
        kept, in the lens and its ini, the way a choice in the add-on's overlay is
        kept. At the first start the lens's own setting wins."""
        seen = _read_motion_detail()
        if self.md_written is not None and seen is not None and seen != self.md_written:
            print("motion detail %s, as chosen in the ReShade overlay" % seen, flush=True)
            self.motion_detail = seen
            _save_ini("motion_detail", None if seen == "full" else seen)
        _write_motion_detail(self.motion_detail)
        self.md_written = self.motion_detail

    def apply_proxy(self):
        """Set the Cost Scaler for this lens: on for fullscreen at the scale the
        monitor and the pass count call for, off when windowed, or as the ini
        says. The proxy reads its ini when it starts and again within a second
        of a change, so this is right both before the presenter spawns and live.

        The fast engine scales the picture itself and keeps a proxy ini of its
        own beside its exe, so while it is the engine the stack's ini is left as
        it is. This runs before every start, so the rule is back in force with
        the next stack presenter."""
        if not _proxy_installed() or COST_SCALER == "manual" or self.engine == "fast":
            return
        want = COST_SCALER == "always" or (COST_SCALER == "fullscreen" and self.fullscreen)
        scale = _proxy_scale(self.cw, self.ch, self.passes) if want else None
        if _write_proxy(scale is not None, scale) and scale != self.proxy_scale:
            self.proxy_scale = scale
            print("cost scaler %s" % ("on at %.2f" % scale if scale else "off"), flush=True)

    def add_pass(self, save=True, how=None):
        self.set_passes(self.passes + 1, save, how)

    def drop_pass(self, save=True, how=None):
        self.set_passes(self.passes - 1, save, how)

    # ---- geometry
    def inner(self):
        if self.fullscreen:
            # fullscreen cannot be dragged, and it has no chrome to count from
            return self.fs_origin
        if self.attach is not None:
            return self.attach["rect"][:2]
        if self.folded:
            return self.t.winfo_x() + LINE, self.t.winfo_y() + LINE
        return self.t.winfo_x() + EDGE, self.t.winfo_y() + BAR

    def layout_chrome(self, x, y, cw=None, ch=None, settle=True):
        """Lay the chrome out around a picture of this size at this place.

        Windowed, the bar sits above the picture inside the frame, which draws
        the border and carries the grips. Fullscreen there is no chrome: the
        bar, the frame and the tab are taken out of view, and come back as they
        were, folded or not, when the lens is a window again.
        The size is the lens's own unless one is given, which is how a drag
        previews its outcome; settle waits for the window to be where it was
        put, so inner() reads the new place, which a preview has no need of.
        """
        cw = self.cw if cw is None else cw
        ch = self.ch if ch is None else ch
        t = self.t
        if self.fullscreen:
            self.show_chrome(False)
            return
        if self.attach is not None or self.folded:
            # attached or folded, the chrome is the line around the picture and
            # the tab on its top edge; no bar and no grips. Attached, the target
            # decides the size; folded, the tab drags the lens and opens the menu
            t.geometry("%dx%d+%d+%d" % (cw + 2 * LINE, ch + 2 * LINE, x - LINE, y - LINE))
            self.bar.place_forget()
            self.hole.place(x=LINE, y=LINE, width=cw, height=ch)
            for g in self.grips.values():
                g.place_forget()
            self.place_tab(x, y, cw)
        else:
            t.geometry("%dx%d+%d+%d" % (cw + 2 * EDGE, ch + BAR + EDGE, x - EDGE, y - BAR))
            self.bar.place(x=EDGE, y=0, width=cw, height=BAR)
            self.hole.place(x=EDGE, y=BAR, width=cw, height=ch)
            grab = EDGE - LINE
            self.grips["w"].place(x=LINE, y=0, width=grab, height=BAR + ch + grab)
            self.grips["e"].place(x=EDGE + cw, y=0, width=grab, height=BAR + ch + grab)
            self.grips["s"].place(x=LINE, y=BAR + ch, width=cw + 2 * grab, height=grab)
        if self.show_chrome(True):      # back in view after a fullscreen lens
            self.place_tab(x, y, cw)    # the tab where it belongs now, not where it was hidden
        if settle:
            t.update()

    def aim(self):
        """Tell the presenter where the lens is on its monitor."""
        x, y = self.inner()
        self.tell_presenter("crop %d %d" % (x - self.mon_x, y - self.mon_y))

    def place(self):
        x, y = self.inner()
        flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        for s in self.stages:
            u.SetWindowPos(s["hwnd"], 0, x, y, 0, 0, flags)
        self.place_divider()

    def update_info(self):
        n = self.passes
        p = max(1, min(_pass_limit(), self.pending))
        self.pending = p
        chosen = p != n
        self.sync_panel()               # the NR settings panel shows the same state
        self.note_nr()                  # and so does the note on going fullscreen
        if not self.nr_on:
            # every pass is a neural pass, so with Neural Rendering off each one
            # is a copy of the last; the controls wait until it is back
            self.pass_lbl.config(text="NR off", fg=DIM)
            for b in (self.set_btn, self.plus, self.minus):
                b.config(fg=DIM)
            return
        self.pass_lbl.config(text="%d pass%s" % (p, "" if p == 1 else "es"),
                             fg=WARN if chosen else ACCENT)
        self.set_btn.config(fg=ACCENT if chosen else DIM)
        self.plus.config(fg=DIM if p >= _pass_limit() else FG)
        self.minus.config(fg=DIM if p <= 1 else FG)
        self.update_profile_label()

    def update_profile_label(self):
        """The profile's name on the bar, amber with a star once the lens no
        longer matches it in what the bar and Settings hold."""
        name = self.profile
        if not name or name not in self.profiles["profiles"]:
            self.prof_btn.config(text="▾ Profile", fg=DIM)
            return
        p = self.profiles["profiles"][name]
        same = (p.get("passes") == self.passes and p.get("cost_scaler") == COST_SCALER
                and bool(p.get("ready")) == self.ready and p.get("readout") == self.readout
                and int(p.get("max_fps", self.max_fps) or 0) == int(self.max_fps)
                and p.get("motion_detail", self.motion_detail) == self.motion_detail
                and bool(p.get("latency")) == self.latency_on and bool(p.get("fullscreen")) == self.fullscreen
                and bool(p.get("title_size", True)) == bool(self.show_size)
                and bool(p.get("title_style", False)) == bool(self.show_style)
                and bool(p.get("title_intensity", False)) == bool(self.show_intensity))
        self.prof_btn.config(text="▾ %s%s" % (name, "" if same else "*"), fg=ACCENT if same else WARN)

    def bump_passes(self, step):
        """Choose a pass count on the bar without restarting anything yet."""
        if not self.nr_on:
            return
        self.pending = max(1, min(_pass_limit(), self.pending + step))
        self.update_info()

    def apply_passes(self, how="title bar"):
        if self.nr_on and self.pending != self.passes:
            self.set_passes(self.pending, how=how)

    def hold_note(self, text, seconds=20.0, windowed=False):
        """Say a sentence and keep it up long enough to be read: on the notice
        of a fullscreen lens, and on the bar, where stats would replace it
        within a second, so it shows this again each time until the seconds are
        up, and then the readout comes back. It is for a fullscreen lens, and is
        dropped when the lens leaves fullscreen, unless windowed keeps it on
        the bar of a windowed lens as well."""
        self.held = (text, time.perf_counter() + seconds, windowed)
        self.say(text, WARN, seconds, slot="held")

    # ---- the notice
    # A fullscreen lens has no bar to say anything on. What the bar would have
    # said, a restart's note, a screenshot's result, a sentence that has to be
    # read, goes onto a notice at the top of the lens's monitor instead: a small
    # window of the lens's own that is out of the picture, takes no click and no
    # focus, and goes away by itself. It has five slots: exclusive while a
    # program has the screen in exclusive fullscreen, see check_exclusive, held
    # for a sentence from hold_note, behind for the warning that the lens runs
    # behind the program in front, see check_behind, and note for whatever is
    # going on right now, shown one under the other in that order, and attached
    # for the sentence do_command gives a lens attached to a window, which has
    # no bar either.
    def say(self, text, colour=None, seconds=4.0, slot="note", bar=True):
        """Tell the person at the lens something: on the bar, unless bar is
        False, and for a fullscreen lens on the notice as well, for this many
        seconds."""
        colour = colour or WARN
        if bar:
            self.info.config(text=text, fg=colour)
        if self.fullscreen and not self.closing:
            self.notes[slot] = (text, colour, time.perf_counter() + seconds)
            self.show_notice()

    def show_notice(self):
        """Draw the notice from what is still to be said, or take it away when
        nothing is, or when the lens is not fullscreen and in view. Called
        whenever a slot changes and once a second from stats, which is how a
        slot's time runs out. An attached lens has no bar either, and shows the
        one sentence do_command gives it in a slot of its own."""
        now = time.perf_counter()
        for slot in [s for s, v in self.notes.items() if v[2] <= now]:
            del self.notes[slot]
        lines = []
        if self.fullscreen and not self.minimized and not self.closing:
            for slot in ("exclusive", "held", "behind", "note"):
                v = self.notes.get(slot)
                if v is not None and v[0] not in [l[0] for l in lines]:
                    lines.append(v[:2])
        elif self.attach is not None and not self.minimized and not self.closing and "attached" in self.notes:
            lines.append(self.notes["attached"][:2])
        if lines == self.notice_lines and (self.notice is not None) == bool(lines):
            return
        self.notice_lines = lines
        if not lines:
            t, self.notice = self.notice, None
            if t is not None:
                try:
                    t.destroy()
                except Exception:
                    pass
            return
        try:
            x, y = self.inner()
            mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
            t, new = self.notice, self.notice is None
            if new:
                t = self.notice = self._own_window()
                t.configure(bg=ACCENT)
                tk.Frame(t, bg=BG).pack(padx=1, pady=1)
            box = t.winfo_children()[0]
            for c in box.winfo_children():
                c.destroy()
            for i, (text, colour) in enumerate(lines):
                tk.Label(box, text=text, bg=BG, fg=colour, font=("Segoe UI", 11), justify="left",
                         wraplength=max(300, min(1200, mw - 120)), padx=16,
                         pady=6).pack(anchor="w", pady=(2 if i else 0, 0))
            t.update_idletasks()
            wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
            t.geometry("%dx%d+%d+%d" % (wd, ht, mx + max(0, (mw - wd) // 2), my + 24))
            if new:
                self._show_own(t, 0.96, through=True)
            else:
                t.update_idletasks()
                self._own_styles(t, through=True)
        except Exception:
            pass

    def _own_styles(self, win, through=False, top=True):
        """Give a window of the lens's own what they all have: it never takes the
        keyboard, lies on top, and is out of the picture. With through it lets
        every click pass to what is under it as well. Without top it keeps its
        place among the windows on top, which the readout's updates need, see
        show_readout."""
        h = u.GetParent(win.winfo_id()) or win.winfo_id()
        ex = u.GetWindowLongPtrW(h, GWL_EXSTYLE) | WS_EX_NOACTIVATE
        if through:
            ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        u.SetWindowLongPtrW(h, GWL_EXSTYLE, ex)
        u.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)
        if top:
            u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _own_window(self):
        """A window of the lens's own for the menu, the NR settings panel, the
        note, the notice or the readout, made so it can never take the
        foreground from the program in front, a game included: withdrawn from
        the start, with no frame, on top, and unseen. Fill it, give it a place,
        and show it with _show_own."""
        t = tk.Toplevel(self.root)
        t.withdraw()                        # before Tk first maps it, see _show_own
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.0)         # unseen until it is out of the picture
        return t

    def _show_own(self, t, alpha=1.0, through=False):
        """Show a window from _own_window without it ever being active.

        Tk makes the window that carries the styles at its first idle moment,
        hidden while the window is withdrawn, so the styles go onto it before
        it is first seen: it never takes the keyboard, lies on top, and is out
        of the picture. Tk then shows it as it shows any window it brings back,
        without activating it (ShowWindow with SW_SHOWNOACTIVATE), and for a
        window with no frame it does nothing about the keyboard. That is how
        Tk 8.6's code for Windows reads, where a window first mapped in view
        can instead be made active as it appears, and its styles came only
        after. The alpha comes last, once it is out of the picture for
        certain, and 30 ms on, see _own_alpha. Tk lays out and draws what a
        window holds only from its event loop, which this runs inside of, so
        a window given its alpha here would show empty for a moment."""
        t.update_idletasks()
        self._own_styles(t, through)
        t.deiconify()
        t.update_idletasks()
        self._own_styles(t, through)        # again, should showing it have cost it any of them
        self.root.after(30, lambda: self._own_alpha(t, alpha))

    def _own_alpha(self, t, alpha):
        """The alpha of a window that _show_own showed, once the event loop
        has mapped and drawn it, unless it is gone by then."""
        try:
            if t.winfo_exists():
                t.attributes("-alpha", alpha)
                t.update_idletasks()
        except Exception:
            pass

    def stats(self):
        if self.closing:
            return
        # The new pictures the presenter actually showed over the last few
        # seconds, which is the number a person means by fps. Its counter
        # restarts with the presenter, so a step backwards starts the average over.
        now, n = time.perf_counter(), self.out_frames
        if self._shown is not None and n >= self._shown[1] and now > self._shown[0]:
            self._fps_hist.append((n - self._shown[1]) / (now - self._shown[0]))
        elif self._shown is not None and n < self._shown[1]:
            self._fps_hist.clear()
        self._shown = (now, n)
        shown = sum(self._fps_hist) / len(self._fps_hist) if self._fps_hist else None
        # The stack presenter standing in for the fast engine has frames, so the
        # screen gives pictures again and the fast engine can have its turn now,
        # which _recover gives it. Not under tweak mode, which the restart would end
        if (self.standing_in() and self.fed_at > self.stand_in and now - self.fed_at < 1.5
                and not (self.rebuilding or self.minimized or self.tweak)):
            if self.recover_after is not None:
                try:
                    self.root.after_cancel(self.recover_after)
                except Exception:
                    pass
            self.recover_held = False
            self.recover_after = self.root.after(0, self._recover)
        if self.held is not None and (now >= self.held[1] or not (self.fullscreen or self.held[2])):
            self.held = None
        readout = None
        # nothing under the lens has changed for a few seconds: the presenter
        # shows nothing new, the neural pass rests, and the delay of the last
        # new picture is history
        idle = shown is not None and shown < 0.5
        self.fps_now, self.idle_now = shown, idle       # for the readout, see show_readout
        if self.t_first and self.frames > 0:
            parts = ["%d x %d" % (self.cw, self.ch)] if self.show_size else []
            if self.engine == "fast":
                # the one sign on the bar of which engine draws the picture; the
                # stack presenter is the usual one and goes unnamed
                parts.append("fast engine")
            if self.readout in ("detail", "both"):
                parts.append("%.0f in  %.0f out" % (self.pres_in, self.pres_out))
            if idle and self.readout != "detail":
                parts.append("idle")
            elif not idle and self.readout in ("fps", "both") and shown is not None:
                parts.append("%.0f fps" % shown)
            if self.latency_on and self.latency_ms is not None and not idle:
                # the tilde marks the ReShade engine's estimated last part, which the
                # fast engine measures, so its figure goes without one
                parts.append("latency %s%.0f ms" % ("" if self.engine == "fast" else "~", self.latency_ms))
            readout = "   ".join(parts)
        self.readout_now = readout
        # not during a drag on the frame, which shows the size it is making
        if self.held is not None and not self.tweak and self.rs is None:
            self.info.config(text=self.held[0], fg=WARN)       # see hold_note
        elif readout is not None and not self.tweak and self.rs is None:
            self.info.config(text=readout, fg=DIM)
        # a fullscreen lens has no bar, so its menu carries the readout while it
        # is open, see menu, and its notice is looked after here
        if self.popup.live is not None and readout:
            try:
                self.popup.live.config(text=readout)
            except Exception:
                pass
        self.check_exclusive()
        self.show_notice()
        self.show_readout()
        self.sync_panel()               # the engine's own quality step arrives with its ready line
        self.mirror_addon()
        self.summarise()
        self.root.after(1000, self.stats)

    def readout_text(self):
        """What the on-screen readout of a fullscreen lens says, see
        show_readout, or "" where it shows nothing: the figures Settings,
        Fullscreen switches on, see FS_READOUT, in their own order. The frame
        rate and the latency are the ones the menu's readout line has, the
        quality step is the fast engine's alone, the passes read NR off while
        Neural Rendering is off, and the style is the add-on's. Nothing while
        the lens is windowed or minimised."""
        parts = []
        if self.fullscreen and not self.minimized and not self.closing and self.stages:
            idle = self.idle_now
            if "fps" in FS_READOUT and (idle or self.fps_now is not None):
                parts.append("idle" if idle else "%.0f fps" % self.fps_now)
            if "latency" in FS_READOUT and self.latency_ms is not None and not idle:
                parts.append("latency %s%.0f ms" % ("" if self.engine == "fast" else "~", self.latency_ms))
            if "step" in FS_READOUT and self.engine == "fast":
                parts.append("step " + FAST_QUALITY_NAMES[self.quality_now()])
            if "passes" in FS_READOUT:
                parts.append("%d pass%s" % (self.passes, "" if self.passes == 1 else "es") if self.nr_on
                             else "NR off")
            if "style" in FS_READOUT:
                code = str(_read_addon_section().get("NRStyle", "0")).strip()
                parts.append("style " + STYLE_NAMES.get(code, "Default"))
        return "   ".join(parts)

    def show_readout(self):
        """The on-screen readout of a fullscreen lens: readout_text on one line
        at the corner of the lens's monitor that Settings names, FS_READOUT_AT.
        A window of the lens's own that lets every click through, never takes
        the keyboard and is out of the picture. It is there only while the
        lens is fullscreen and in view and something is switched on. Called
        once a second from stats, and when Settings changes it. It lies under
        the menu, the NR settings panel and the note. A new one puts them back
        over it, and a new text leaves its place among them as it is."""
        text = self.readout_text()
        if not text:
            t, self.readout_win, self.readout_drawn = self.readout_win, None, None
            if t is not None:
                try:
                    t.destroy()
                except Exception:
                    pass
            return
        try:
            x, y = self.inner()
            mon = monitor_rect(x + self.cw // 2, y + self.ch // 2)
            if (text, FS_READOUT_AT, mon) == self.readout_drawn and self.readout_win is not None:
                return
            self.readout_drawn = (text, FS_READOUT_AT, mon)
            t, new = self.readout_win, self.readout_win is None
            if new:
                t = self.readout_win = self._own_window()
                t.configure(bg=ACCENT)
                tk.Label(t, bg=BG, fg=FG, font=("Segoe UI", 11), padx=10, pady=3).pack(padx=1, pady=1)
            t.winfo_children()[0].config(text=text)
            t.update_idletasks()
            wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
            mx, my, mw, mh = mon
            # a little in from the corner, and at the bottom above the two rows
            # the picture leaves free, see FULL_SHORT
            rx = mx + 12 if FS_READOUT_AT.endswith("left") else mx + mw - wd - 12
            ry = my + 12 if FS_READOUT_AT.startswith("top") else my + mh - FULL_SHORT - ht - 12
            t.geometry("%dx%d+%d+%d" % (wd, ht, rx, ry))
            if new:
                self._show_own(t, 0.9, through=True)
                self.raise_over_readout()
            else:
                t.update_idletasks()
                self._own_styles(t, through=True, top=False)
        except Exception:
            pass

    def toggle_readout(self, how=None):
        """Hide the on-screen readout, or show it, from its key while the lens
        is fullscreen. Hidden, it keeps what it showed, and shown again it
        shows that, or the frame rate and the latency where nothing is kept,
        see _set_fs_readout. So the ini and Settings, Fullscreen hold what is
        on the screen, and the readout comes or goes at once. how is the way
        it was asked for, for the log."""
        items = () if FS_READOUT else FS_READOUT_LAST
        if how:
            self.act("readout %s (%s)" % ("shown" if items else "hidden", how))
        try:
            _set_fs_readout(items, FS_READOUT_AT)
        except OSError:
            print("neural-lens.ini could not be written, so the next start shows the readout as it was", flush=True)
        print("the on-screen readout shows %s" % ", ".join(FS_READOUT) if FS_READOUT
              else "the on-screen readout is hidden, and its key brings back %s" % ", ".join(FS_READOUT_LAST),
              flush=True)
        self.show_readout()

    def check_exclusive(self):
        """While the lens is fullscreen and in view: whether a program has the
        lens's monitor in exclusive fullscreen, which no window of another
        program is drawn over, so the lens shows nothing there. The shell only
        says that a program has a monitor so, not which, so it counts while
        the window in front is on the lens's monitor and is not one of the
        lens's own, see _exclusive_here. The notice says so for as long as it
        lasts, and that borderless windowed works, and the log says it once
        each way. Nothing of the lens can be seen then, so the menu, the NR
        settings panel and the note close as it begins, the note does not
        come up, and the lens holds none of the keys of a fullscreen lens
        until it ends, see hotkeys_wanted and nav_wanted. Called once a second
        from stats, and as the lens starts or goes fullscreen. The caller
        draws the notice."""
        looking = self.fullscreen and not self.minimized and not self.closing
        ex = bool(looking and _exclusive_fullscreen() and self._exclusive_here())
        if ex:
            self.notes["exclusive"] = (EXCLUSIVE_WORDS, WARN, time.perf_counter() + 2.5)
        else:
            self.notes.pop("exclusive", None)
        if ex == self.exclusive:
            return
        if looking:
            print("a program is in exclusive fullscreen, so the lens cannot draw over it" if ex
                  else "no program is in exclusive fullscreen any more", flush=True)
        self.exclusive = ex
        if ex:
            shut = []
            if self.popup.win is not None:
                shut.append("the lens menu" if self.popup.name == "menu" else "the " + self.popup.name)
                self.popup.close()
            if self.panel is not None:
                shut.append("the NR settings panel")
                self.close_panel()
            if self.note_win is not None:
                shut.append("the note")
                self.close_note()
            if shut:
                print("%s closed, since nothing of the lens can be seen over that program"
                      % (", ".join(shut[:-1]) + " and " + shut[-1] if len(shut) > 1 else shut[0]), flush=True)
        self.sync_hotkeys()             # the keys of a fullscreen lens go, or come back

    def _exclusive_here(self):
        """Whether the window in front, which a program in exclusive fullscreen
        has, lies on the lens's monitor and is not one of the lens's own. Only
        GetForegroundWindow and MonitorFromWindow are asked, and no process is
        opened."""
        fg = u.GetForegroundWindow()
        if not fg or self.own_foreground(fg):
            return False
        x, y = self.inner()
        here = _u32.MonitorFromPoint(w.POINT(x + self.cw // 2, y + self.ch // 2), 2)    # MONITOR_DEFAULTTONEAREST
        return bool(here) and _u32.MonitorFromWindow(fg, 0) == here                     # MONITOR_DEFAULTTONULL

    def summarise(self, now=False):
        """While a fullscreen lens runs on the fast engine and is in view, one
        line in the log every ten seconds from the engine's own stats lines,
        see _read_presenter: new and arrived pictures a second, the repeated,
        dropped and skipped ones, the median of the engine's delay as it
        reports it, unclamped, what the picture is made with, and the frame
        rate limit. Only the lines of the engine that runs count, by its
        process's id, and anything else empties the record.

        now writes what has come since the last line at once and starts the
        next ten seconds. A restart, a new quality step, Neural Rendering
        switched, a new pass count, a new frame rate limit, Ready mode
        switched, fullscreen and back, a profile and minimising ask for it
        before they change anything, so each line covers one engine in one
        state. The line names that state, though not Ready mode. A single
        second is too little to sum up and is left out, which also keeps out
        a stats line that came between two of those asks, such as a new pass
        count's and its restart's, after the count had changed.

        Each ten seconds' median then goes to check_behind, None where there
        was none, with the time those seconds began, and a line written at
        once does not, since it covers a state that is about to change. When
        the lens is anything but fullscreen and in view on the fast engine,
        that count starts again."""
        at = time.perf_counter()
        proc = self.stages[0].get("proc") if self.stages else None
        if not (self.fullscreen and self.engine == "fast" and proc is not None and not self.minimized
                and not self.closing):
            self.fast_seconds.clear()
            self.summary_at = at
            self.behind_run = 0
            return
        if not now and at - self.summary_at < 10.0:
            return
        since, self.summary_at = self.summary_at, at
        # a summary written early neither counts nor starts the count again, but a
        # window that came to the front in its seconds must not leave the count
        # standing for a window the next summary sees from its own start
        if now and self.fg_since > since:
            self.behind_run = 0
        got = []
        while self.fast_seconds:
            pid, *second = self.fast_seconds.popleft()
            if pid == proc.pid:
                got.append(second)
        if not got or now and len(got) < 2:
            if not now:
                self.check_behind(None, since)
            return
        n = len(got)
        delays = sorted(g[5] for g in got if g[5] is not None and g[5] == g[5])
        mid = None
        if delays:
            half = len(delays) // 2
            mid = delays[half] if len(delays) % 2 else (delays[half - 1] + delays[half]) / 2.0
        median = "unknown" if mid is None else "%.1f ms" % mid
        step = self.quality_now()
        print("fast engine, last %d s: %.1f new and %.1f arrived pictures a second, %d repeated, %d dropped, "
              "%d skipped, median delay %s, quality step %d %s, %d pass%s, NR %s, %s"
              % (n, sum(g[0] for g in got) / float(n), sum(g[1] for g in got) / float(n),
                 sum(g[2] for g in got), sum(g[3] for g in got), sum(g[4] for g in got), median, step,
                 FAST_QUALITY_NAMES[step], self.passes, "" if self.passes == 1 else "es",
                 "on" if self.nr_on else "off",
                 "frame rate limit %d fps" % self.max_fps if self.max_fps else "no frame rate limit"), flush=True)
        if not now:
            self.check_behind(mid, since)

    def check_behind(self, median, since):
        """Whether a fullscreen lens on the fast engine has fallen behind the
        program in front, from the median delay of the seconds summarise has
        just summed up, None where it had none, and since, when those seconds
        began. It counts as behind from three refreshes of the lens's monitor
        less a tenth of one, and from 25 ms less 0.8 ms where the rate cannot
        be read, while no program has the lens's monitor in exclusive
        fullscreen, where the lens draws nothing, see check_exclusive, and one
        window that is neither one of the lens's own nor the desktop or the
        taskbar has been in front for all those seconds, as log_foreground
        saw it. Anything else and the count starts again. Two such summaries
        in a row and the notice says so for twelve seconds, see BEHIND_WORDS,
        unless Settings, Fullscreen has it off, and the log says so either
        way. Then neither comes again for ten minutes, unless Settings
        switches the warning on.

        Why a program in front that keeps the card fully busy holds the lens
        back, and what helps, is in the README, under A game in front that
        keeps the card busy."""
        fg = u.GetForegroundWindow()
        if median is None or self.exclusive or not fg or self.own_foreground(fg):
            self.behind_run = 0
            return
        # the warning puts the delay down to the program in front, so the
        # desktop and the taskbar count as the lens's own, and its window has to
        # be the one log_foreground saw at its last look, with no other window
        # in front at any of its looks since these seconds began
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(fg, cls, 256)
        if (fg != self.fg_seen or self.fg_since > since
                or cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")):
            self.behind_run = 0
            return
        hz = monitor_hz(self.stages[0]["hwnd"])
        # three refreshes in tenths of a ms, as the engine gives its delay and
        # the log names it. A median up to a tenth of a refresh below it counts
        # too, since Windows gives a rate such as 119.88 Hz as 119, which puts
        # the line at 25.2 ms where three refreshes read 25.0
        line = round(3000.0 / hz, 1) if hz else 25.0
        if median < line - (100.0 / hz if hz else 0.8):
            self.behind_run = 0
            return
        self.behind_run += 1
        at = time.perf_counter()
        if self.behind_run < 2 or at < self.behind_next:
            return
        self.behind_next = at + 600.0
        print("the lens is running behind the program in front, median delay %.1f ms, %d summaries in a row at "
              "%.1f ms or more, and the warning is %s"
              % (median, self.behind_run, line, "shown" if FS_BEHIND_WARN else "off in Settings"), flush=True)
        if FS_BEHIND_WARN:
            self.say(BEHIND_WORDS % median, seconds=12.0, slot="behind", bar=False)

    def log_foreground(self, own):
        """While the lens is fullscreen and in view, one line in the log each
        time another window comes to the front: its class, and whether it is
        one of the lens's own, by the list of them, own, that watch_filter
        made. Only GetForegroundWindow and GetClassNameW are asked: no process
        is opened and no title is read, since a title can hold private text.

        It also notes when it saw another window, or none, take the place of
        the one it saw before, fg_since, for check_behind. The first window
        it sees once the lens is fullscreen and in view is no such change,
        since the summaries start their seconds afresh then, see summarise."""
        if not self.fullscreen or self.minimized or self.closing:
            self.fg_seen = None
            return
        fg = u.GetForegroundWindow()
        if fg == self.fg_seen:
            return
        if self.fg_seen is not None:
            self.fg_since = time.perf_counter()
        self.fg_seen = fg
        if not fg:
            print("foreground: no window", flush=True)
            return
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(fg, cls, 256)
        mine = fg in own or fg in {s["hwnd"] for s in self.stages}
        print("foreground: %s, %s" % (cls.value or "a window with no class name",
                                      "one of the lens's own" if mine else "another program's"), flush=True)

    def save_state(self):
        x, y = self.inner()
        if self.attach is not None:
            # the attached place and size belong to the target; the windowed
            # geometry is what comes back on detach and on the next launch
            cw, ch, x, y = self.attach["saved"]
        else:
            cw, ch = self.cw, self.ch
        try:
            if self.fullscreen:
                # the windowed geometry stays untouched for the way back
                with open(FULL_STATE, "w") as f:
                    f.write("%d\n" % self.passes)
                return
            with open(STATE, "w") as f:
                f.write("%d %d %d %d %d\n" % (cw, ch, x, y, self.passes))
        except OSError:
            pass

    # ---- drag (title bar only; a move never resizes)
    def down(self, e):
        if self.fullscreen:
            return
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
            if self.refit():
                return
            self.save_state()
            self.follow_monitor()

    # ---- menu / tweak mode
    # The ReShade overlay lives INSIDE the presenter's swapchain, so it cannot
    # be moved to a separate window. Tweak mode makes the viewport interactive
    # (drops WS_EX_TRANSPARENT / WS_EX_NOACTIVATE), focuses it and presses Home
    # so the overlay opens in place. It ends with Done, which presses Home again,
    # or with a Home the user presses, which has closed the overlay already;
    # either way the viewport goes back to click-through and the keyboard to the
    # window that had it.
    def menu(self, e, how="title bar"):
        """The lens menu, or with a menu open, that menu closed. how is the way
        it was asked for, for the log: the title bar, the tab, a key, the
        taskbar button or its list. The log names the list that closes, which
        can be the style list or the profile list, see PopupMenu."""
        if self.popup.win is not None:
            was = self.popup.name
            self.popup.close()
            self.act("%s closed (%s)" % (was, how))
            return
        off = self.nr_on
        # the fast engine has no ReShade in it, so what needs ReShade is shown as
        # not available, with the reason and where the choice of engine is. Its
        # NR settings are the lens's own panel, and the entry says which of the
        # two it opens
        fast = self.engine == "fast"
        full = self.fullscreen
        no_fast = "(not with the fast engine, see Settings, Fullscreen)"
        if self.tweak:
            nr_entry = ("Done tweaking  (back to click-through)", lambda: self.toggle_tweak("menu"))
        elif fast:
            key = self.key_for("nr_panel")
            nr_entry = ("%s  (the lens's own panel%s)" % ("Close the NR settings" if self.panel is not None
                                                        else "NR settings", ", " + key if key else ""),
                        lambda: self.toggle_panel("menu"))
        else:
            nr_entry = ("Tweak NR settings  (ReShade overlay, Home)", lambda: self.toggle_tweak("menu"))
        nr_keys = _either(self.nr_keys())       # the keys as they are set, F6 only under the ReShade engine
        # a bug report is much easier to act on when the reporter can read the
        # version off the app rather than having to work out which build they have
        items = [("Neural Lens %s  (beta)" % __version__, None, False)]
        if full:
            # a fullscreen lens has no bar: the readout the bar would show is the
            # menu's second line, kept current by stats while the menu is open,
            # and what the bar's own buttons did comes first
            items += [(self.readout_now or "%d x %d" % (self.cw, self.ch), None, False),
                      None,
                      ("Leave fullscreen", lambda: self.toggle_fullscreen("menu"), True),
                      ("Minimise to the taskbar", lambda: self.minimize("menu"), True)]
        items += [
            None,
            (nr_entry[0], nr_entry[1], True),
            (("Turn NR back on" if not self.nr_on else "Turn NR off") + ("   (%s)" % nr_keys if nr_keys else ""),
             lambda: self.toggle_nr("menu"), True),
            None,
            ("Add a pass now", lambda: self.add_pass(how="menu"), off and self.passes < _pass_limit()),
            ("Remove a pass now", lambda: self.drop_pass(how="menu"), off and self.passes > 1),
            None,
            ("Save before and after      (both images, plus a join)", lambda: self.take_screenshot("menu"), True),
            (("Save the result only       " + no_fast if fast
              else "Save the result only       (F5, ReShade's own)"), lambda: self.send_key(0x74), not fast),
            ("Open screenshot folder", self.open_shots, True),
            None,
            (("End the A/B split" if self.split is not None
              else "Live A/B split      (neural left, raw right)"), lambda: self.toggle_split("menu"), True),
        ] + ([
            None,
            ("Detach from the window", lambda: self.detach("menu"), True),
        ] if self.attach is not None else [] if full else [      # a fullscreen lens attaches to nothing
            None,
            ("Attach to a window...       (then click the window)", lambda: self.pick_target(False), True),
            ("Attach to a region in a window...   (click it, then drag the region)",
             lambda: self.pick_target(True), True),
        ]) + [
            None,
            # no bar to hide in a fullscreen lens, and no profile selector in
            # view, so its menu leads to the profiles instead
            (("Profiles...", lambda: self.profile_menu("menu"), True) if full
             else (("Show the title bar" if self.folded else "Hide the title bar   (only the tab stays)"),
                   lambda: self.toggle_fold("menu"), self.attach is None)),
            ("Settings...", self.settings_dialog, True),
            None,
            # Quit and not Close, which could be read as closing only this menu
            # or a dialog
            ("Quit Neural Lens", lambda: self.quit(how="menu"), True),
        ]
        self.popup.open(items, "menu")
        if self.popup.win is not None:
            self.act("menu opened (%s)" % how)
        if full and self.popup.win is not None and len(self.popup.labels) > 1:
            self.popup.live = self.popup.labels[1]

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
        """Give the keyboard to the presenter, for tweak mode. hwnd is only
        ever the presenter's window, which is the lens's own, and the thread
        the lens attaches to is checked on the very call that names it to be
        a thread of the lens's own processes, so the input it joins is its
        own presenter's and never another program's, see point 12 at the top."""
        me = k32.GetCurrentThreadId()
        pid = w.DWORD()
        tid = _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not tid or pid.value not in self.own_pids():
            return
        u.AttachThreadInput(me, tid, True)
        u.SetForegroundWindow(hwnd)
        u.SetFocus(hwnd)
        u.AttachThreadInput(me, tid, False)

    def post_key(self, hwnd, vk):
        """Deliver one key press straight to the presenter's message queue.

        ReShade reads its hotkeys from the window's own messages, so a posted
        WM_KEYDOWN and WM_KEYUP reach it whether or not the window has focus.
        But it only notices a press when it polls, once per presented frame,
        and a key that goes down and up inside one frame is never seen. So the
        key is held for a third of a second, longer than the slowest frame,
        before it is released.

        A posted message is no input of the system. It changes no key's state,
        and no low-level hook or raw input reader sees it. Only a hook that
        runs in the presenter's own message loop could. Each message goes only
        to a window of the lens's own processes, read on the very handle it is
        posted to, so never to another program, see point 12 at the top.
        """
        if _window_pid(hwnd) not in self.own_pids():
            return
        scan = u.MapVirtualKeyW(vk, 0)
        ext = 0x1000000 if vk in (0x24, 0x21, 0x22, 0x23, 0x2D, 0x2E) else 0
        lp = (scan << 16) | 1 | ext
        u.PostMessageW(hwnd, 0x100, vk, lp)
        self.root.after(KEY_HOLD, lambda: _window_pid(hwnd) in self.own_pids()
                        and u.PostMessageW(hwnd, 0x101, vk, lp | 0xC0000000))

    def toggle_tweak(self, how=None):
        """The NR settings, or with them open, closed: tweak mode under the
        ReShade engine and the lens's own panel under the fast engine. how is
        the way it was asked for, for the log."""
        if self.tweak:
            self.end_tweak(how=how)
        elif self.engine == "fast":
            # no ReShade in the fast engine, so there is no overlay to open: its
            # NR settings are the lens's own panel, which the menu's entry opens,
            # and so does this, for any other way here
            self.toggle_panel(how)
        else:
            self.start_tweak(how)

    def start_tweak(self, how=None):
        if self.nr_wait is not None:
            # the overlay would open on the presenter that the waiting restart
            # ends, see nr_by_restart
            print("tweak mode waits for the restart of the NR switch", flush=True)
            return
        h = self.visible()
        if how:
            self.act("tweak mode on (%s)" % how)
        self.tweak = True
        self.tweak_prev = u.GetForegroundWindow()
        # interactive first, so the overlay that opens can be used with the
        # mouse; the key itself does not need the focus. The overlay is drawn
        # and read on every present, so the presenter presents at full rate
        # for as long as it is open
        self.set_interactive(h, True)
        self.tell_presenter("live 1")
        self.say("Tweak mode is on. Press Home when done.", WARN, 8.0)
        self.post_key(h, 0x24)
        self.root.after(150, lambda: self.focus(h))
        self.tweak_until = float("inf")
        self.root.after(700, self.follow_overlay)
        u.GetAsyncKeyState(0x24)            # forget a press from before, see watch_home
        self.root.after(KEY_HOLD, lambda: self.watch_home(h))

    def end_tweak(self, press_home=True, how=None):
        """Leave tweak mode: from Done, which closes the overlay with Home, or
        with press_home False once the user's own Home has closed it. how is
        the way, for the log."""
        h = self.visible()
        if how:
            self.act("tweak mode off (%s)" % how)
        self.tweak = False
        prev = self.tweak_prev
        if press_home:
            # the key first, and the window made click-through only after it
            # has been released: taking the styles back drops the focus, and
            # ReShade forgets every key it is holding when that happens. The
            # keyboard goes back before the styles, while the presenter is
            # still in front, which hand_focus_back needs
            self.post_key(h, 0x24)
        self.root.after(KEY_HOLD + 200 if press_home else 200,
                        lambda: (self.hand_focus_back(prev, h), self.set_interactive(h, False),
                                 self.tell_presenter("live 0")))
        self.info.config(text="%d x %d" % (self.cw, self.ch), fg=DIM)
        self.notes.pop("note", None)        # a fullscreen lens's notice of tweak mode goes with it
        self.show_notice()
        # the add-on's write of a change made just before Done can still be
        # on its way, so the file is followed a few seconds longer
        self.tweak_until = time.perf_counter() + 4.0

    def watch_home(self, h, pressing=False):
        """End tweak mode when the user's Home closes the overlay.

        A Home press reaches the presenter, and so ReShade, only while the
        presenter is the foreground window, and ReShade closes the overlay on
        it. The key is read from the physical keyboard, the way F6 is, so the
        presses the lens posts itself are not counted, and tweak mode ends once
        the key is back up: dropping the focus while it is down makes ReShade
        forget it. The low bit catches a press that came and went between two
        looks.
        """
        if self.closing or not self.tweak or not self.stages or h != self.visible():
            return
        state = u.GetAsyncKeyState(0x24)
        last = self.hotkeys.last
        if self.key_wait or (last[0] == "nr_panel" and time.perf_counter() - last[1] < 0.7):
            # the NR settings hotkey is being pressed, and its Home is not the
            # user's own Home for the overlay, see tweak_by_key
            self.root.after(30, lambda: self.watch_home(h))
            return
        down = bool(state & 0x8000)
        if not pressing and (down or state & 1) and u.GetForegroundWindow() == h:
            pressing = True
        if pressing and not down:
            self.end_tweak(press_home=False, how="Home")
            return
        self.root.after(30, lambda: self.watch_home(h, pressing))

    def hand_focus_back(self, prev, h):
        """Give the keyboard back to the window that had it before the presenter
        took it, so the next key goes where the user expects rather than to
        ReShade. A window of the lens's own, or one that has gone, is left be.

        Windows lets a program hand the foreground on while the window in front
        is its own or shares its input. So this is done only while a window of
        the lens's own is in front, the presenter that had the keyboard for
        tweak mode, and the lens attaches to that window's input, which is its
        own presenter's. It never attaches to another program's input, the one
        that gets the keyboard back included, see point 12 at the top. With
        another window in front, the person has moved on, and nothing is done.
        Whose the window is, is judged on the very handle the lens attaches
        to, read once, and the thread is checked to be of a process of the
        lens's own on the same call that names it."""
        if not prev or prev == h or not u.IsWindow(prev):
            return
        if _window_pid(prev) == os.getpid():
            return
        fg = u.GetForegroundWindow()
        if not fg or not self.own_foreground(fg):
            return
        try:
            me = k32.GetCurrentThreadId()
            pid = w.DWORD()
            tid = _u32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if pid.value not in self.own_pids():
                return
            joined = bool(tid) and tid != me and bool(u.AttachThreadInput(me, tid, True))
            u.SetForegroundWindow(prev)
            if joined:
                u.AttachThreadInput(me, tid, False)
        except Exception:
            pass

    def follow_overlay(self):
        """Keep the title bar in step with a pass count chosen in the overlay.

        The overlay's own control changes the add-on's count live, inside its
        process, and the add-on writes it to ReShade.ini within about a second.
        While the overlay is open, and for a few seconds after it closes, the
        file is read back and a changed count becomes the bar's own, with
        nothing restarted: the add-on is already running it. The fast engine
        has no overlay and takes its count when it starts, so under it there is
        nothing to follow, and the next tweak mode starts this again.
        """
        if (self.closing or self.engine == "fast"
                or not (self.tweak or time.perf_counter() < self.tweak_until)):
            return
        if ADDON_PASSES and not self.rebuilding:
            n = _read_nr_passes()
            if n is not None and 1 <= n <= ADDON_MAX_PASSES and n != self.passes:
                print("passes set to %d in the overlay" % n, flush=True)
                self.passes = self.pending = n
                self.update_info()
                self.apply_proxy()
                self.save_state()
        self.root.after(700, self.follow_overlay)

    def send_key(self, vk):
        """Post a key to the presenter, for ReShade's own hotkeys. The fast
        engine has no ReShade in it and does nothing with a key, so none is
        sent there, and the menu shows what would send one as not available."""
        if self.closing or self.engine == "fast":
            return
        for s in list(self.stages):
            self.post_key(s["hwnd"], vk)

    # ---- Neural Rendering on or off
    # The add-on reads its F6 from the physical keyboard, through
    # GetAsyncKeyState, not from window messages. Measured with a still image
    # under the lens and the in-to-out difference as the witness: F6 posted to
    # the window did nothing in three runs, with or without focus, while one
    # real keystroke with no focus at all took it from 1.20 to 2.22. So F6
    # anywhere on the system toggles Neural Rendering, and the lens watches
    # the same key the same way to keep its own idea in step.
    #
    # The fast engine has no add-on in it and reads no key, so under it F6
    # does nothing. There Neural Rendering goes off and on by the lens's own
    # NR key, which Settings can change, by the menu and by the NR settings
    # panel, and the lens tells the engine "nr 0" or "nr 1" itself, see
    # toggle_nr. F6 is watched all the same for the ReShade engine, which can
    # take the fast engine's place at any time, see _nr_toggled.
    def watch_f6(self):
        def loop():
            down = False
            while not self.closing:
                now = bool(u.GetAsyncKeyState(0x75) & 0x8000)
                # a paused presenter presents no frame for the add-on to read
                # the key on, so a press while minimised changes nothing there
                if now and not down and not self.minimized:
                    self.root.after(0, self._nr_toggled)
                down = now
                time.sleep(0.05)      # a human press lasts longer than this

        threading.Thread(target=loop, daemon=True).start()

    def _nr_toggled(self, how="F6"):
        """Neural Rendering switched: by F6 under the ReShade engine, whose
        add-on reads that key, which watch_f6 saw, or under the fast engine by
        the lens itself. An F6 under the fast engine changes nothing, since
        nothing there reads it, and the log says so once for each engine. how
        is the way, for the log."""
        if self.closing:
            return
        if self.engine == "fast":
            if how == "F6":
                if not self.f6_said:
                    self.f6_said = True
                    key = self.key_for("nr_toggle")
                    print("F6 does nothing under the fast engine, where %s turns Neural Rendering off and on"
                          % (key or "the lens menu"), flush=True)
                return
            # no add-on is there to keep the state, so the lens does what it
            # would have done: the engine is told, and the state goes into
            # ReShade.ini where the add-on keeps it, for the presenter that
            # starts next
            self.summarise(now=True)    # under the state it had, see summarise
            self.nr_on = not self.nr_on
            self.act("NR %s (%s)" % ("on" if self.nr_on else "off", how))
            self.tell_presenter("nr %d" % (1 if self.nr_on else 0))
            _write_addon_settings(self.passes, nr=self.nr_on)
            print("Neural Rendering %s" % ("on" if self.nr_on else "off"), flush=True)
            self.update_info()
            return
        # the add-on reads the key on a present, and an idle presenter presents
        # four times a second, so it presents at full rate for a moment; and the
        # add-on's own answer, written to ReShade.ini within about a second and a
        # half, is read back to keep the two in step should it have missed the key
        self.tell_presenter("wake")
        self.nr_on = not self.nr_on
        self.act("NR %s (%s)" % ("on" if self.nr_on else "off", how))
        print("Neural Rendering %s" % ("on" if self.nr_on else "off"), flush=True)
        self.update_info()
        self.root.after(2500, self._check_nr)

    def _check_nr(self):
        if self.closing or self.rebuilding:
            return
        on = _read_nr_enabled()
        if on != self.nr_on:
            self.nr_on = on
            print("Neural Rendering %s, as the add-on has it" % ("on" if on else "off"), flush=True)
            self.update_info()

    def toggle_nr(self, how="menu"):
        """Neural Rendering off or on from the menu, the NR settings panel or
        the NR key, how being which, for the log.

        Under the fast engine nothing reads a key, so the state is flipped and
        the engine told directly. Under the ReShade engine the add-on keeps the
        state, and it reads F6 from the keyboard. A key the lens made would
        reach every program on the system that reads the keyboard, a game and
        its anti-cheat included, whichever window is in front, and nothing of
        the lens may go into another program, see point 12 at the top. So
        there the state goes into ReShade.ini, where the add-on reads it as it
        starts, and the picture restarts, see nr_by_restart. A real F6 still
        reaches the add-on, and watch_f6 follows it."""
        if self.closing:
            return
        if self.engine == "fast":
            self._nr_toggled(how)
        else:
            self.nr_by_restart(how)

    def nr_by_restart(self, how):
        """Neural Rendering off or on under the ReShade engine, see toggle_nr.
        The new state goes into ReShade.ini as NeuralUplift once the presenter
        is gone, and the add-on of the one that starts next begins in it, see
        _read_nr_enabled. It costs a restart of the picture, and no key is
        pressed.

        A value moved in ReShade's overlay reaches ReShade.ini about a second
        later, written by the presenter that the restart ends (1.3 s,
        measured), and a restart before then would lose it. So with tweak
        mode on, it ends first, as Done ends it, and with tweak mode on or
        ended less than four seconds ago, see end_tweak, the restart waits
        until ReShade.ini has not changed for a second and 1.5 s have passed,
        four seconds at most. A minimised lens's presenter writes nothing, so
        the wait starts again once the lens is back. A restart that comes in
        the meantime takes the switch with it, see restart_presenter."""
        if self.closing or self.rebuilding or not self.stages:
            return
        if self.nr_wait is not None:
            self.act("NR %s already waits for its restart (%s)" % ("on" if self.nr_on else "off", how))
            return
        start = time.perf_counter()
        wait = self.tweak or start < self.tweak_until
        if self.tweak:
            self.end_tweak(how=how)         # as Done ends it, which closes the overlay
        self.nr_on = not self.nr_on
        word = "on" if self.nr_on else "off"
        self.act("NR %s (%s)" % (word, how))
        if not wait:
            self._nr_restart()
            return
        print("the restart for Neural Rendering %s waits for the overlay's last write to ReShade.ini" % word,
              flush=True)
        self.say("Neural Rendering %s, restarting ..." % word, WARN, 30.0)
        path = os.path.join(STACK_DIR or "", "ReShade.ini")

        def stamp():
            try:
                st = os.stat(path)
                return st.st_mtime_ns, st.st_size
            except OSError:
                return None

        token = self.nr_wait = object()
        seen = {"start": start, "still": start, "stamp": stamp()}

        def look():
            if self.nr_wait is not token:
                return                      # a restart took the switch with it, see restart_presenter
            if self.closing or not self.stages:
                self.nr_wait = None
                return
            now = time.perf_counter()
            st = stamp()
            if st != seen["stamp"]:
                seen["stamp"], seen["still"] = st, now
            if self.minimized:
                seen["away"] = True
                self.root.after(500, look)
                return
            if seen.pop("away", False):
                seen["start"] = seen["still"] = now     # back, so the wait starts again
            if self.rebuilding or not (now - seen["start"] >= 4.0
                                       or now - seen["start"] >= 1.5 and now - seen["still"] >= 1.0):
                self.root.after(100, look)
                return
            self.nr_wait = None
            print("the restart waited %.1f s for the overlay's last write, and ReShade.ini %s"
                  % (now - start, "has not changed for %.1f s" % (now - seen["still"])
                     if now - seen["still"] >= 1.0 else "was still changing"), flush=True)
            self._nr_restart()

        self.root.after(100, look)

    def _nr_restart(self):
        """The restart of nr_by_restart, for the state the lens has now."""
        word = "on" if self.nr_on else "off"
        print("Neural Rendering %s, through ReShade.ini and a restart" % word, flush=True)
        self.restart_presenter("Neural Rendering %s, restarting ..." % word, nr=self.nr_on)

    # ---- NR settings, the lens's own panel
    # Under the ReShade engine these values are set in ReShade's overlay. The
    # fast engine has no ReShade in it, so under it the lens shows them on a
    # panel of its own: the network on or off, the style, the four strengths,
    # the auto mask, the pass count and the quality step. A change goes into the
    # add-on's section of ReShade.ini at once, where both engines read it, and
    # the engine is told reload, so the picture follows a slider while it moves.
    # The panel is a window like the menu: on top, out of the picture, and never
    # taking the keyboard from the program under the lens. The arrow keys, Enter
    # and Escape work it all the same, see panel_key.
    def toggle_panel(self, how=None):
        if self.panel is not None:
            self.close_panel(how)
        else:
            self.open_panel(how)

    def quality_control(self, parent, command=None, font=("Segoe UI", 10)):
        """The fast engine's quality step as a slider with five positions, and
        a label that names the step it is on, for Settings and for the NR
        settings panel. command, when given, is called with a step the slider
        is moved to. Returns the slider and the label, for the caller to place."""
        name = tk.Label(parent, text=FAST_QUALITY_NAMES[self.quality_now()], bg=BG, fg=FG, font=font,
                        width=12, anchor="w")

        def moved(value):
            step = max(0, min(len(FAST_QUALITY_NAMES) - 1, int(float(value))))
            name.config(text=FAST_QUALITY_NAMES[step])
            if command is not None:
                command(step)

        scale = tk.Scale(parent, from_=0, to=len(FAST_QUALITY_NAMES) - 1, resolution=1, orient="horizontal",
                         showvalue=False, length=240, width=14, sliderlength=26, bg=DIM, troughcolor=FIELD,
                         activebackground=ACCENT, highlightthickness=0, bd=0, sliderrelief="flat", command=moved)
        scale.set(self.quality_now())
        return scale, name

    def default_quality(self):
        """The quality step this lens's fullscreen picture has where the ini
        names none: the one a fast engine took by itself for this picture, when
        one has said so, and else the same rule worked out here."""
        if self.fullscreen and self.engine_default is not None and self.engine_default[:2] == (self.cw, self.ch):
            return self.engine_default[2]
        if self.fullscreen:
            return _default_quality(self.cw, self.ch)
        x, y = self.inner()
        return _default_quality(*fullscreen_rect(x, y, self.cw, self.ch)[2:])

    def quality_now(self):
        """The quality step in force, which the controls show: the one the ini
        names, else the one the fast engine that runs is at, else the default."""
        if self.quality_set is not None:
            return self.quality_set
        if self.engine == "fast" and self.engine_quality is not None:
            return self.engine_quality
        return self.default_quality()

    def set_quality(self, step, how=None):
        """The fast engine's quality step, chosen in Settings, on the NR
        settings panel or by its keys. It is kept in the ini, apart from the
        step that is the default for this lens's fullscreen picture, which is
        left unwritten so the lens goes by the default again. A fast engine
        that is running is told, and changes its work size in place. how is
        the way it was chosen, for the log."""
        step = max(0, min(len(FAST_QUALITY_NAMES) - 1, int(step)))
        if step == self.quality_now():
            return
        if how:
            self.act("quality step %d %s (%s)" % (step, FAST_QUALITY_NAMES[step], how))
        self.summarise(now=True)        # under the step it had, see summarise
        self.quality_set = None if step == self.default_quality() else step
        _set_fast_quality(self.quality_set)
        print("quality step %d, %s%s" % (step, FAST_QUALITY_NAMES[step],
                                        "" if self.quality_set is not None else ", the default for this picture"),
              flush=True)
        if self.engine == "fast":
            self.tell_presenter("quality %d" % step)
            self.engine_quality = step
        self.sync_panel()

    def open_panel(self, how=None):
        """Open the NR settings panel on what ReShade.ini holds. Only under the
        fast engine: the ReShade engine has ReShade's own overlay for this, see
        toggle_tweak. how is the way it was asked for, for the log."""
        if (self.panel is not None or self.closing or self.rebuilding or self.minimized
                or self.engine != "fast"):
            return
        self.popup.close()
        t = self._own_window()
        self.panel = t
        t.configure(bg=ACCENT)
        box = tk.Frame(t, bg=BG)
        box.pack(padx=1, pady=1)
        ui = self.panel_ui = {}
        rows = self.panel_rows = []         # (kind, name, the widget lit for it), in order, see panel_key
        self.panel_row = None
        font, small = ("Segoe UI", 10), ("Segoe UI", 9)
        tick = dict(bg=BG, fg=FG, selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                    disabledforeground=DIM, font=font)

        # the head, which the panel is dragged by, with the cross that closes it
        head = tk.Frame(box, bg=CAP)
        head.grid(row=0, column=0, columnspan=3, sticky="we")
        name = tk.Label(head, text="  NR settings", bg=CAP, fg=FG, font=("Segoe UI", 10, "bold"), pady=5)
        name.pack(side="left")
        key = self.key_for("nr_panel")
        hint = tk.Label(head, text="%s or Escape closes it" % key if key else "Escape closes it", bg=CAP, fg=DIM,
                        font=small)
        hint.pack(side="left", padx=(12, 0))
        cross = tk.Label(head, text=self.glyphs["close"], bg=CAP, fg=FG, font=self.capfont, padx=11)
        cross.pack(side="right", fill="y")
        cross.bind("<Button-1>", lambda e: self.close_panel("cross"))
        cross.bind("<Enter>", lambda e: cross.config(bg=CLOSE))
        cross.bind("<Leave>", lambda e: cross.config(bg=CAP))
        for wdg in (head, name, hint):
            wdg.bind("<ButtonPress-1>", self._panel_down)
            wdg.bind("<B1-Motion>", self._panel_move)
            wdg.bind("<ButtonRelease-1>", self._panel_up)

        def label(row, text):
            lbl = tk.Label(box, text=text, bg=BG, fg=FG, font=font)
            lbl.grid(row=row, column=0, sticky="w", padx=(12, 10), pady=(4, 0))
            return lbl

        ui["nr"] = tk.BooleanVar(master=t, value=bool(self.nr_on))
        nr_keys = _either(self.nr_keys())
        nr_box = tk.Checkbutton(box, text="Neural Rendering on" + ("   (%s)" % nr_keys if nr_keys else ""),
                                variable=ui["nr"], command=self._panel_nr, **tick)
        nr_box.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))
        rows.append(("switch", "nr", nr_box))
        rows.append(("choice", "style", label(2, "Style")))
        styles = tk.Frame(box, bg=BG)
        styles.grid(row=2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        ui["style"] = tk.StringVar(master=t, value="0")
        for code, text in STYLE_NAMES.items():
            tk.Radiobutton(styles, text=text, variable=ui["style"], value=code,
                           command=lambda: self.panel_set("NRStyle", ui["style"].get()),
                           **tick).pack(side="left", padx=(0, 8))
        row = 3
        for nr_key, text, lo, hi, _default in NR_SLIDERS:
            rows.append(("slider", nr_key, label(row, text)))
            scale = tk.Scale(box, from_=lo, to=hi, resolution=0.01, orient="horizontal", showvalue=False,
                             length=240, width=14, sliderlength=22, bg=DIM, troughcolor=FIELD,
                             activebackground=ACCENT, highlightthickness=0, bd=0, sliderrelief="flat",
                             command=lambda v, k=nr_key: self._panel_slider(k, v))
            scale.grid(row=row, column=1, sticky="w", pady=(6, 0))
            shown = tk.Label(box, text="", bg=BG, fg=FG, font=("Consolas", 10), width=5, anchor="e")
            shown.grid(row=row, column=2, sticky="e", padx=(8, 12), pady=(4, 0))
            ui[nr_key] = (scale, shown)
            row += 1
        ui["skin_auto"] = tk.BooleanVar(master=t, value=False)
        skin_box = tk.Checkbutton(box, text="Leave skin structure to the model", variable=ui["skin_auto"],
                                  command=self._panel_skin, **tick)
        skin_box.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))
        rows.append(("switch", "skin_auto", skin_box))
        ui["mask"] = tk.BooleanVar(master=t, value=False)
        mask_box = tk.Checkbutton(box, text="Auto mask", variable=ui["mask"],
                                  command=lambda: self.panel_set("NRAutoMask", "1" if ui["mask"].get() else "0"),
                                  **tick)
        mask_box.grid(row=row + 1, column=0, columnspan=3, sticky="w", padx=8)
        rows.append(("switch", "mask", mask_box))
        rows.append(("passes", "passes", label(row + 2, "Passes")))
        passes = tk.Frame(box, bg=BG)
        passes.grid(row=row + 2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        ui["minus"] = tk.Label(passes, text=" − ", bg=BG, fg=FG, font=("Segoe UI", 12, "bold"))
        ui["passes"] = tk.Label(passes, text="1", bg=BG, fg=FG, font=("Consolas", 10), width=2)
        ui["plus"] = tk.Label(passes, text=" + ", bg=BG, fg=FG, font=("Segoe UI", 12, "bold"))
        for wdg, step in ((ui["minus"], -1), (ui["passes"], 0), (ui["plus"], 1)):
            wdg.pack(side="left")
            if step:
                wdg.bind("<Button-1>", lambda e, s=step: self._panel_pass(s))
                wdg.bind("<Enter>", lambda e, b=wdg: b.config(bg=HOVER))
                wdg.bind("<Leave>", lambda e, b=wdg: b.config(bg=BG))
        tk.Label(passes, text="a change restarts the picture", bg=BG, fg=DIM, font=small).pack(side="left", padx=(10, 0))
        rows.append(("quality", "quality", label(row + 3, "Quality step")))
        ui["quality"], ui["quality_name"] = self.quality_control(box, self._panel_quality)
        ui["quality"].grid(row=row + 3, column=1, sticky="w", pady=(6, 0))
        ui["quality_name"].grid(row=row + 3, column=2, sticky="w", padx=(8, 12), pady=(4, 0))
        texts = (FAST_QUALITY_WORDS,
                 "A change shows in the picture at once. It is kept, and the ReShade engine uses it too.",
                 "The arrow keys pick a setting and change it, and Enter switches a switch.")
        for i, text in enumerate(texts):
            tk.Label(box, text=text, bg=BG, fg=DIM, font=small, justify="left", wraplength=430).grid(
                row=row + 4 + i, column=0, columnspan=3, sticky="w", padx=12,
                pady=(8 if i == 0 else 2, 10 if i == len(texts) - 1 else 0))
        self.load_panel()

        t.update_idletasks()
        wd, ht = t.winfo_reqwidth(), t.winfo_reqheight()
        x, y = self.inner()
        mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
        px, py = self.panel_at or (mx + 24, my + 24)
        # a readout at the top of the monitor that the panel would lie over,
        # as one at the top left does where the panel first opens, has the
        # panel open below it, so neither hides the other
        r = self.readout_win
        if r is not None and FS_READOUT_AT.startswith("top"):
            try:
                rx, ry, rw, rh = r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height()
                if px < rx + rw and rx < px + wd and py < ry + rh and ry < py + ht:
                    py = ry + rh + 12
            except Exception:
                pass
        t.geometry("%dx%d+%d+%d" % (wd, ht, max(mx, min(px, mx + mw - wd)), max(my, min(py, my + mh - ht))))
        self._show_own(t, 0.99)
        if how:
            self.act("NR settings opened (%s)" % how)
        print("NR settings panel opened", flush=True)
        self.sync_hotkeys()             # the arrow keys, Enter and Escape work it now

    def load_panel(self):
        """Set the panel's controls from what ReShade.ini holds now, which is
        not a change to write back: when it opens, and when a new engine has
        started, which read the same file."""
        if self.panel is None:
            return
        self._panel_flush_now()         # a change still on its way is in the file first
        ui, vals = self.panel_ui, _read_addon_section()
        self.panel_live = False
        try:
            style = str(vals.get("NRStyle", "0")).strip()
            ui["style"].set(style if style in STYLE_NAMES else "0")
            self.panel_vals, self.panel_pos = {"NRStyle": ui["style"].get()}, {}
            for key, _text, lo, hi, default in NR_SLIDERS:
                v = _nr_number(vals, key, default)
                scale, shown = ui[key]
                auto = key == "NRSkinStructure" and v < 0
                if key == "NRSkinStructure":
                    ui["skin_auto"].set(auto)
                at = max(lo, min(hi, 0.0 if auto else v))
                scale.config(state="normal")
                scale.set(at)
                scale.config(state="disabled" if auto else "normal")
                shown.config(text="auto" if auto else "%.2f" % v, fg=DIM if auto else FG)
                self.panel_pos[key] = at
                self.panel_vals[key] = _nr_text(-1 if auto else v)
            mask = _nr_number(vals, "NRAutoMask", 0) != 0
            ui["mask"].set(mask)
            self.panel_vals["NRAutoMask"] = "1" if mask else "0"
            self.panel.update_idletasks()
        except Exception:
            pass
        self.panel_live = True
        self.sync_panel()

    def sync_panel(self):
        """The panel's copy of what the lens itself holds: the network on or
        off, the pass count and the quality step. Called whenever one of them
        may have changed, by the panel or by anything else."""
        if self.panel is None or not self.panel_ui:
            return
        ui = self.panel_ui
        try:
            ui["nr"].set(bool(self.nr_on))
            ui["passes"].config(text="%d" % self.passes, fg=FG if self.nr_on else DIM)
            ui["minus"].config(fg=FG if self.nr_on and self.passes > 1 else DIM)
            ui["plus"].config(fg=FG if self.nr_on and self.passes < _pass_limit() else DIM)
            step = self.quality_now()
            if int(float(ui["quality"].get())) != step:
                ui["quality"].set(step)
            ui["quality_name"].config(text=FAST_QUALITY_NAMES[step])
        except Exception:
            pass

    def close_panel(self, how=None):
        """Close the NR settings panel. how is the way the person at the lens
        closed it, for the log. The lens closing it itself gives none."""
        t, self.panel = self.panel, None
        if t is None:
            return
        self._panel_flush_now()         # what a slider's last move left unwritten goes out first
        self._panel_said_now()          # and the log has every change made on it
        try:
            self.panel_at = (t.winfo_x(), t.winfo_y())
        except Exception:
            pass
        self.panel_ui, self.panel_drag = {}, None
        self.panel_rows, self.panel_row = [], None
        try:
            t.destroy()
        except Exception:
            pass
        if how:
            self.act("NR settings closed (%s)" % how)
        print("NR settings panel closed", flush=True)
        self.sync_hotkeys()             # the keys that worked it go back once they are up

    def panel_set(self, key, text, how="mouse"):
        """A value changed on the panel: into ReShade.ini at once, and the engine
        told to read it, see _panel_flush. how is mouse or keyboard, for the
        log, which gets one line once the value has held still, see
        _panel_said."""
        if self.panel_vals.get(key) == text:
            return
        self.panel_vals[key] = text
        self.panel_pending[key] = text
        self._panel_said(key, text, how)
        if self.panel_timer is None:
            self._panel_flush()

    def _panel_said(self, key, text, how):
        """Log a change on the panel once it has held still for 0.6 s, so a
        slider dragged across its range is one line with where it ended, and
        not one for every step on the way."""
        old = self.panel_said.pop(key, None)
        if old is not None:
            try:
                self.root.after_cancel(old[2])
            except Exception:
                pass
        self.panel_said[key] = (text, how, self.root.after(600, lambda: self._panel_say(key)))

    def _panel_say(self, key):
        said = self.panel_said.pop(key, None)
        if said is not None:
            self.act("NR settings %s %s (%s)" % (key, said[0], said[1]))

    def _panel_said_now(self):
        """Every change still waiting for its line, at once, as the panel closes."""
        for key in list(self.panel_said):
            try:
                self.root.after_cancel(self.panel_said[key][2])
            except Exception:
                pass
            self._panel_say(key)

    def panel_key(self, name):
        """An arrow key, Enter or Escape while the panel is open over a
        fullscreen lens, see nav_key. Up and Down move from setting to setting,
        which the panel shows in the accent colour, Left and Right change the
        style, a slider by 0.05, the pass count or the quality step, Enter
        switches a switch, and Escape closes the panel."""
        rows = self.panel_rows
        if self.panel is None or not rows:
            return
        if name == "escape":
            self.close_panel("Escape")
            return
        if name in ("up", "down"):
            d = -1 if name == "up" else 1
            if self.panel_row is None:
                self.panel_light(len(rows) - 1 if d < 0 else 0)
            else:
                self.panel_light((self.panel_row + d) % len(rows))
            return
        if self.panel_row is None or not self.panel_live:
            return
        kind, what, _lit = rows[self.panel_row]
        ui = self.panel_ui
        if name == "enter":
            if what == "nr":
                self.toggle_nr("panel")
            elif what == "skin_auto":
                ui["skin_auto"].set(not ui["skin_auto"].get())
                self._panel_skin("keyboard")
            elif what == "mask":
                ui["mask"].set(not ui["mask"].get())
                self.panel_set("NRAutoMask", "1" if ui["mask"].get() else "0", "keyboard")
            return
        d = -1 if name == "left" else 1
        if kind == "choice":
            codes = list(STYLE_NAMES)
            now = ui["style"].get()
            i = max(0, min(len(codes) - 1, (codes.index(now) if now in codes else 0) + d))
            if codes[i] != now:
                ui["style"].set(codes[i])
                self.panel_set("NRStyle", codes[i], "keyboard")
        elif kind == "slider":
            scale, shown = ui[what]
            if str(scale.cget("state")) == "disabled":
                return                  # skin structure left to the model
            lo, hi = float(scale.cget("from")), float(scale.cget("to"))
            v = round(max(lo, min(hi, float(scale.get()) + 0.05 * d)), 2)
            self.panel_pos[what] = v    # so the slider's own call that follows is no second change
            scale.set(v)
            shown.config(text="%.2f" % v, fg=FG)
            self.panel_set(what, _nr_text(v), "keyboard")
        elif kind == "passes":
            # a pass restarts the picture, and the arrow key's repeats that came
            # in meanwhile are not more passes asked for
            if time.perf_counter() - self.panel_pass_at > 0.5:
                self._panel_pass(d)
                self.panel_pass_at = time.perf_counter()
        elif kind == "quality":
            step = max(0, min(len(FAST_QUALITY_NAMES) - 1, self.quality_now() + d))
            if step != self.quality_now():
                self.set_quality(step, "panel")

    def panel_light(self, n):
        """Show which setting the arrow keys are on: its name in the accent
        colour, the rest as they were."""
        self.panel_row = n
        for i, (_kind, _what, lit) in enumerate(self.panel_rows):
            try:
                lit.config(fg=ACCENT if i == n else FG)
            except Exception:
                pass

    def _panel_flush(self):
        """Write what the panel changed and have the engine read it: now, or
        when the last write went out under a tenth of a second ago, once that
        time is up. So a slider that is dragged sends about ten a second, and
        its last value always lands. A write that fails is tried again."""
        self.panel_timer = None
        if not self.panel_pending or self.closing:
            return
        wait = self.panel_sent + 0.1 - time.perf_counter()
        if wait > 0:
            self.panel_timer = self.root.after(int(wait * 1000) + 1, self._panel_flush)
            return
        vals, self.panel_pending = self.panel_pending, {}
        self.panel_sent = time.perf_counter()
        if _set_addon_values(vals):
            self.panel_tries = 0
            if self.engine == "fast":
                self.tell_presenter("reload")
            return
        self.panel_tries += 1
        if self.panel_tries <= 20:
            for k, v in vals.items():
                self.panel_pending.setdefault(k, v)
            self.panel_timer = self.root.after(100, self._panel_flush)
        else:
            print("ReShade.ini could not be written, so the NR settings kept their old %s"
                  % ", ".join(sorted(vals)), flush=True)

    def _panel_flush_now(self):
        """The same without the wait, before the panel closes or reads the file."""
        if self.panel_timer is not None:
            try:
                self.root.after_cancel(self.panel_timer)
            except Exception:
                pass
        self.panel_sent = 0.0
        self._panel_flush()

    def _panel_slider(self, key, value):
        """A slider's own call, which Tk also makes when the panel itself has
        put the slider somewhere: only a place it was not put at is a change."""
        try:
            v = float(value)
        except ValueError:
            return
        if not self.panel_live or self.panel is None or abs(v - self.panel_pos.get(key, v)) < 0.004:
            return
        self.panel_pos[key] = v
        self.panel_ui[key][1].config(text="%.2f" % v, fg=FG)
        self.panel_set(key, _nr_text(v))

    def _panel_skin(self, how="mouse"):
        """Skin structure left to the model, which is -1, or set by its slider."""
        ui = self.panel_ui
        auto = bool(ui["skin_auto"].get())
        scale, shown = ui["NRSkinStructure"]
        scale.config(state="disabled" if auto else "normal")
        v = float(scale.get())
        shown.config(text="auto" if auto else "%.2f" % v, fg=DIM if auto else FG)
        self.panel_set("NRSkinStructure", "-1" if auto else _nr_text(v), how)

    def _panel_nr(self):
        if bool(self.panel_ui["nr"].get()) != bool(self.nr_on):
            self.toggle_nr("panel")

    def _panel_pass(self, step):
        """One pass more or fewer, which restarts the picture as it does from
        the bar. Every pass is a neural pass, so the count waits while Neural
        Rendering is off."""
        if self.nr_on and not self.rebuilding and not self.closing:
            self.set_passes(self.passes + step, how="panel")

    def _panel_quality(self, step):
        if self.panel_live and step != self.quality_now():
            self.set_quality(step, "panel")

    def _panel_down(self, e):
        self.panel_drag = (e.x_root - self.panel.winfo_x(), e.y_root - self.panel.winfo_y())

    def _panel_move(self, e):
        if self.panel_drag is None or self.panel is None:
            return
        x, y = self.inner()
        mx, my, mw, mh = monitor_rect(x + self.cw // 2, y + self.ch // 2)
        px = max(mx, min(e.x_root - self.panel_drag[0], mx + mw - self.panel.winfo_width()))
        py = max(my, min(e.y_root - self.panel_drag[1], my + mh - self.panel.winfo_height()))
        self.panel.geometry("+%d+%d" % (px, py))

    def _panel_up(self, e):
        self.panel_drag = None

    # ---- resize
    # The picture cannot change size in place: the presenter's swapchain is
    # made at its size, and the add-on crashes when a swapchain is recreated
    # under it. So a new size replaces the presenter, the way a new pass count
    # does, and the chrome is laid out again around the new one. The size
    # comes from the frame around the lens, dragged the way any window is.
    def resize_to(self, x, y, cw, ch):
        """Give the lens this size at this place: the chrome is laid out again
        and the presenter replaced, since its size is fixed when it starts."""
        if self.closing:
            return
        cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
        self.cw, self.ch = cw, ch
        self.layout_chrome(x, y)
        self.restart_presenter("resizing to %d x %d ..." % (cw, ch))

    # The frame: a drag on a side moves that side, a drag on a bottom corner
    # moves both of its sides. The chrome follows the mouse as a preview, the
    # picture stays as it is, and letting go replaces the picture at the new
    # size, kept within the monitor like any other.
    def _grip_zone(self, side, e):
        if side == "s":
            wd = e.widget.winfo_width()
            return "sw" if e.x < CORNER else "se" if e.x > wd - CORNER else "s"
        ht = e.widget.winfo_height()
        if e.y < ht - CORNER:
            return side
        return "sw" if side == "w" else "se"

    def _grip_hover(self, side, e):
        if self.rs is None:
            e.widget.config(cursor={"w": "size_we", "e": "size_we", "s": "size_ns",
                                    "sw": "size_ne_sw", "se": "size_nw_se"}[self._grip_zone(side, e)])

    def _grip_down(self, side, e):
        if self.fullscreen or self.closing or self.rebuilding or self.rs is not None:
            return
        self.popup.close()
        x, y = self.inner()
        self.rs = {"zone": self._grip_zone(side, e), "x0": e.x_root, "y0": e.y_root,
                   "start": (x, y, self.cw, self.ch), "rect": (x, y, self.cw, self.ch)}

    def _grip_rect(self, e):
        zone = self.rs["zone"]
        x, y, cw, ch = self.rs["start"]
        dx, dy = e.x_root - self.rs["x0"], e.y_root - self.rs["y0"]
        if "e" in zone:
            cw = max(MIN_W, cw + dx)
        if "w" in zone:
            nw = max(MIN_W, cw - dx)
            x, cw = x + cw - nw, nw
        if "s" in zone:
            ch = max(MIN_H, ch + dy)
        return x, y, cw - cw % 2, ch - ch % 2

    def _grip_move(self, e):
        if self.rs is None:
            return
        rect = self._grip_rect(e)
        if rect != self.rs["rect"]:
            self.rs["rect"] = rect
            self.layout_chrome(*rect, settle=False)
            self.info.config(text="%d x %d" % rect[2:], fg=WARN)

    def _grip_up(self, e):
        if self.rs is None:
            return
        x, y, cw, ch = self._grip_rect(e)          # while the drag's record is still there
        sx, sy, scw, sch = self.rs["start"]
        self.rs = None
        if (cw, ch) != (scw, sch):
            self.resize_to(*fit_rect(x, y, cw, ch))
            return
        self.layout_chrome(sx, sy)
        self.info.config(text="%d x %d" % (scw, sch), fg=DIM)

    # ---- fullscreen and back
    def toggle_fullscreen(self, how=None):
        """The maximise button: fullscreen, or back to the window the lens was.
        how is the way it was asked for, for the log."""
        if not self.closing and not self.rebuilding:
            self.set_fullscreen(not self.fullscreen, how=how)

    def set_fullscreen(self, on, note=None, how=None):
        """Fill the monitor the lens is on, or come back to the window it was.

        Either way the picture is replaced, since the presenter's size is fixed
        when it starts. Fullscreen the chrome goes out of view, the keys of a
        fullscreen lens are taken, and the notice names them. Back in a window
        the chrome is laid out around the picture as it was, folded or not, and
        the keys are given back. The windowed geometry is saved on the way in
        and read back on the way out, and the fullscreen lens keeps its own pass
        count, as it does across a launch. The ini follows, so the next launch
        opens the same way. Already fullscreen, going fullscreen again covers
        the monitor as it is now, which is what a change of the monitors asks
        for, with a note of its own for the restart. how is the way the person
        at the lens asked, for the log. The lens itself gives none.
        """
        if self.closing or self.rebuilding:
            return
        if self.minimized:
            self.restore()
        self.popup.close()
        if self.rs is not None:
            return
        passes = self.passes
        if on:
            if not self.fullscreen:
                self.save_state()           # the windowed geometry, for the way back
                if os.path.exists(FULL_STATE):
                    try:
                        passes = int(open(FULL_STATE).read().split()[0])
                    except Exception:
                        pass
            x, y = self.inner()
            x, y, cw, ch = fullscreen_rect(x, y, self.cw, self.ch)
            note = note or "going fullscreen ..."
        else:
            if not self.fullscreen:
                return
            cw, ch, x, y = 1400, 1000, None, None
            try:
                v = [int(n) for n in open(STATE).read().split()]
                cw, ch, x, y = v[:4]
                if len(v) > 4:
                    passes = v[4]
            except Exception:
                cw, ch, x, y = 1400, 1000, None, None
            if x is None:
                mx, my, mw, mh = work_area(0, 0)
                x, y, cw, ch = fit_rect(mx + EDGE, my + BAR, cw, ch, (mx, my, mw, mh))
                x = mx + (mw - cw) // 2
                y = my + BAR + (mh - BAR - EDGE - ch) // 2
            x, y, cw, ch = fit_rect(x, y, cw, ch)
            note = "back to a window ..."
        cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
        if how:
            self.act("fullscreen %s (%s)" % ("on" if on else "off", how))
        self.summarise(now=True)        # what the fast engine did before, see summarise
        was = self.fullscreen
        self.fullscreen = on
        self.fs_origin = (x, y)
        self.cw, self.ch = cw, ch
        self.passes = self.pending = max(1, min(_pass_limit(), passes))
        try:
            _save_ini("fullscreen", "1" if on else None)
        except OSError:
            # an ini that cannot be written right now. The lens changes all the
            # same: stopping here would leave it half way, and for a lens on its
            # way out of fullscreen that is a picture over the whole monitor
            # with no bar, no menu and no key that answers
            print("neural-lens.ini could not be written, so the next start opens the lens as it was",
                  flush=True)
        self.max_btn.config(text=self.glyphs["restore" if on else "max"])
        if not on:
            # the notice, the note, the NR settings panel and the readout are a
            # fullscreen lens's alone
            self.notes.clear()
            self.show_notice()
            self.close_note()
            self.close_panel()
            self.show_readout()
        else:
            self.check_exclusive()      # the notice says it at once, over the restart's note
        self.sync_hotkeys()             # its keys are held only while it is fullscreen
        self.layout_chrome(x, y)
        print("%s %dx%d at (%d,%d)" % ("fullscreen" if on else "windowed", cw, ch, x, y), flush=True)
        self.restart_presenter(note)
        if on and not was:
            self.show_note()
        elif on and self.note_win is not None:
            # a note that is up as the monitors change goes over the middle of
            # the monitor as it is now
            self.close_note()
            self.show_note()

    # ---- screenshots
    # ReShade's own key can only give the processed image. The presenter holds
    # the exact frame it captured and reads back the picture it presented last,
    # so it saves a genuinely aligned before and after from the same moment,
    # plus a composite, which is the shot worth posting.
    def take_screenshot(self, how=None):
        """Save the before, the after and the two joined. how is the way the
        person at the lens asked, for the log."""
        if self.closing or self.shot_busy:
            return
        if how:
            self.act("screenshot (%s)" % how)
        self.shot_busy = True
        self.say("saving screenshot ...", WARN, 8.0)
        threading.Thread(target=self._shot_worker, daemon=True).start()

    def _shot_worker(self):
        text, colour = "screenshot captured nothing", WARN
        try:
            time.sleep(0.1)                     # let the menu finish closing
            os.makedirs(SHOT_DIR, exist_ok=True)
            base = os.path.join(SHOT_DIR, "lens-%s-%dpass" % (time.strftime("%Y%m%d-%H%M%S"),
                                                               self.passes))
            self.shot_event.clear()
            self.shot_reply = None
            self.tell_presenter("clip %d" % (1 if self.clip_shots else 0))
            self.tell_presenter("shot " + base)
            if self.shot_event.wait(5.0) and self.shot_reply and self.shot_reply.startswith("done"):
                text, colour = "saved " + self.shot_reply[5:], ACCENT
            elif self.shot_reply:
                text = "screenshot " + self.shot_reply      # "failed REASON", as the presenter says it
        except Exception as exc:
            text = "screenshot failed, %s" % exc
        finally:
            self.shot_busy = False
        try:
            self.root.after(0, lambda: self._shot_done(text, colour))
        except Exception:
            pass

    def _shot_done(self, text, colour):
        if self.closing:
            return
        print(text, flush=True)
        self.say(text, colour, 4.0)
        self.root.after(4000, lambda: self.info.config(fg=DIM))

    def open_shots(self):
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            os.startfile(SHOT_DIR)
        except Exception:
            messagebox.showinfo("Screenshots", "Screenshots are saved in this folder.\n%s" % SHOT_DIR)

    # ---- settings
    def settings_dialog(self):
        """Every setting the lens has, each as one short label, on pages rather
        than one column: the picture, power, fullscreen, the title bar,
        profiles, hotkeys, screenshots, the look, and the program itself.

        What a setting does is not on the page. It shows in a small window by
        the pointer once the pointer has rested on the setting, see Hints, and
        the one line at the dialog's foot says so. Only what has to be seen
        without that stays beside a setting, in a few words: that a change
        restarts the picture or the lens, or why a setting does nothing.

        Nothing here requires editing the ini; the dialog writes it. A value
        put back to its default is removed from the ini, so it follows the
        default on the next machine rather than pinning this one's value. The
        folders take effect at the next launch, so changing them restarts the
        lens.
        """
        t = tk.Toplevel(self.root)
        t.title("Neural Lens settings")
        t.attributes("-topmost", True)
        t.configure(bg=BG)
        t.resizable(False, False)
        # the settings themselves in a size that reads at a glance, the headings
        # the same size in bold, buttons and fields a little smaller, and the few
        # words that stay beside a setting smaller again
        font, head, ctl, small = ("Segoe UI", 12), ("Segoe UI", 12, "bold"), ("Segoe UI", 11), ("Segoe UI", 10)
        # the explanations, which a test reaches as the dialog's hints
        hints = t.hints = Hints(self, t)

        # ttk draws the tabs, in the lens's colours; the pages are plain frames,
        # so every control is the widget it was when the dialog was one column
        style = ttk.Style(t)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Lens.TNotebook", background=BG, borderwidth=0, tabmargins=(8, 8, 8, 0))
        # eight pixels beside each name: with fourteen, nine tabs are wider than
        # anything on the pages and the dialog grows by a tab's width
        style.configure("Lens.TNotebook.Tab", background=TAB_BG, foreground=DIM, borderwidth=0,
                        padding=(8, 6), font=ctl)
        style.map("Lens.TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)],
                  expand=[("selected", (0, 0, 0, 0))])
        nb = ttk.Notebook(t, style="Lens.TNotebook")
        nb.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 0))

        def page(name):
            p = tk.Frame(nb, bg=BG)
            p.row, p.name = 0, name
            p.columnconfigure(0, weight=1)
            nb.add(p, text=name)
            return p

        def tip(p, label, why, *widgets):
            """Give the widgets that make up one setting its explanation. The
            label is what the setting is listed under for a review of the
            texts, and a text several labels share is listed once for each."""
            if why:
                if label:
                    hints.listed.append((p.name, label, why))
                for wdg in widgets:
                    hints.add(wdg, why)

        def words(row, text, colour=None):
            """A few words beside a setting, for what has to be seen without its
            explanation. Returns the label, for words that come and go."""
            lbl = tk.Label(row, text=text, bg=BG, fg=colour or DIM, font=small)
            lbl.pack(side="left", padx=(12, 0), pady=(3, 0))
            return lbl

        def heading(p, text, why=None, beside=None):
            row = tk.Frame(p, bg=BG)
            row.grid(row=p.row, column=0, columnspan=3, sticky="w", padx=12, pady=(16, 4))
            p.row += 1
            tk.Label(row, text=text, bg=BG, fg=FG, font=head).pack(side="left")
            if beside:
                words(row, beside)
            tip(p, text, why, row)

        def line(p, text, why=None, colour=None):
            """A sentence on a row of its own, for what a page has to say
            whether or not the pointer rests anywhere."""
            lbl = tk.Label(p, text=text, bg=BG, fg=colour or DIM, justify="left", wraplength="430p", font=small)
            lbl.grid(row=p.row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 6))
            p.row += 1
            tip(p, text, why, lbl)
            return lbl

        def option(kind, p, text, why, beside, **kw):
            row = tk.Frame(p, bg=BG)
            row.grid(row=p.row, column=0, columnspan=3, sticky="w", padx=8, pady=(1, 0))
            p.row += 1
            b = kind(row, text=text, bg=BG, fg=FG, selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                     disabledforeground=DIM, font=font, **kw)
            b.pack(side="left")
            # the words beside it, empty for most: a switch that another one holds
            # on says so there while it is greyed
            b.beside = words(row, beside or "")
            tip(p, text, why, row)
            return b

        def switch(p, text, var, why=None, beside=None):
            return option(tk.Checkbutton, p, text, why, beside, variable=var)

        def radio(p, text, var, value, why=None, beside=None):
            return option(tk.Radiobutton, p, text, why, beside, variable=var, value=value)

        def press(holder, text, command, look=ctl, bg=HOVER, fg=FG):
            """A button in the dialog's look. Without a border of its own it is
            no taller than the field beside it, and while it is pressed it has
            the window buttons' shade."""
            return tk.Button(holder, text=text, command=command, relief="flat", bd=0, highlightthickness=0,
                             padx=10, bg=bg, fg=fg, activebackground=CAP, activeforeground=FG, font=look)

        def folder(p, label, var, prompt, why=None):
            """A folder as a field with a Browse button, under its label where
            it has one of its own and not a heading."""
            made = []
            if label:
                made.append(tk.Label(p, text=label, bg=BG, fg=FG, font=font))
                made[0].grid(row=p.row, column=0, columnspan=3, sticky="w", padx=12, pady=(6, 0))
                p.row += 1
            made.append(tk.Entry(p, textvariable=var, width=48, bg=FIELD, fg=FG, insertbackground=FG,
                                 relief="flat", font=ctl))
            made[-1].grid(row=p.row, column=0, columnspan=2, padx=(12, 6), pady=4, sticky="we")

            def browse():
                d = filedialog.askdirectory(initialdir=var.get() or DATA_DIR, title=prompt)
                if d:
                    var.set(os.path.normpath(d))

            made.append(press(p, "Browse", browse))
            made[-1].grid(row=p.row, column=2, padx=(0, 12), pady=4)
            p.row += 1
            tip(p, label, why, *made)

        def button(p, text, command, why=None):
            b = press(p, text, command)
            b.grid(row=p.row, column=0, sticky="w", padx=12, pady=(6, 2))
            p.row += 1
            tip(p, text, why, b)

        # the fast engine can run only where its exe is, and the Cost Scaler's
        # files, since it calls the model through that proxy. Where it can, the
        # settings it takes no notice of say so, and the Fullscreen page has the choice
        eng_ok = FAST_EXE is not None and _proxy_installed()

        # ================================================================ picture
        # Every explanation in this dialog says what its setting does and no
        # more: no card, no watts, no milliseconds and no frame rates. What was
        # measured is in README.md and docs/NOTES.md.
        pic = page("Picture")

        cs_what = ("The Cost Scaler runs the neural model on a smaller copy of the picture and blends the model's "
                   "change back onto the full-size picture, so the card has less work to do.")
        heading(pic, "The Cost Scaler",
                cs_what + " The lens uses it only where the picture and its passes give the model enough work to "
                          "gain from it.")
        if COST_SCALER == "manual":
            line(pic, "neural-lens.ini has cost_scaler = manual, so these two do nothing.",
                 "With cost_scaler = manual the lens leaves the Cost Scaler's own ini alone. Take that line "
                 "out of neural-lens.ini and these two switches work again.")
        cs_full = tk.BooleanVar(value=COST_SCALER in ("fullscreen", "always"))
        cs_always = tk.BooleanVar(value=COST_SCALER == "always")
        cs_full_btn = switch(
            pic, "Use the Cost Scaler for a fullscreen lens", cs_full,
            "With this on, a fullscreen lens on the ReShade engine runs the model through the Cost Scaler wherever "
            "the picture and its passes give the model enough work to gain from it."
            + (" The fast engine does its own scaling and takes no notice of this switch." if eng_ok else "")
            + " Applies straight away.")
        cs_always_btn = switch(
            pic, "Use the Cost Scaler for a windowed lens too", cs_always,
            "A windowed lens gets the Cost Scaler as well, wherever the picture and its passes give the model "
            "enough work to gain from it. This switch turns the one above on too. Applies straight away.")
        if COST_SCALER == "manual":
            cs_full_btn.config(state="disabled")
            cs_always_btn.config(state="disabled")

        def follow_always(*_):
            if cs_always.get():
                cs_full.set(True)
                cs_full_btn.config(state="disabled")
            elif COST_SCALER != "manual":
                cs_full_btn.config(state="normal")
            cs_full_btn.beside.config(text="on while the switch below is on" if cs_always.get() else "")

        cs_always.trace_add("write", follow_always)
        follow_always()

        # only where the stack runs ReshadeMotionEstimation, the estimator it sets
        md_var, md_opened = None, None
        if _drme_in_use():
            # what each detail costs is in docs/NOTES.md, Motion detail
            md_why = ("How finely the lens works out motion between frames, which keeps moving content clean "
                      "under the neural pass. Half and Quarter work on a smaller picture, which costs the card "
                      "less, and fast-moving text then shows a faint double."
                      + (" The fast engine does not use it, so its picture does not restart." if eng_ok else ""))
            heading(pic, "Motion detail", md_why, beside="a change restarts the picture")
            md_opened = self.motion_detail
            md_var = tk.StringVar(value=self.motion_detail)
            radio(pic, "Full, the sharpest on fast motion", md_var, "full", md_why)
            radio(pic, "Half", md_var, "half", md_why)
            radio(pic, "Quarter, the least power", md_var, "quarter", md_why)

        # ================================================================ power
        pwr = page("Power")

        # what a rest costs the first change after it, and what Ready mode costs,
        # is in docs/NOTES.md, The first frame after a rest, and The still screen
        # and the settle
        ready_why = ("When nothing under the lens changes, the lens rests and the card runs cooler, and on some "
                     "cards the first change after a rest is a little slower to show. Ready mode keeps the "
                     "picture ready all the time, so that change is not held back, for a little more power. "
                     "Applies straight away.")
        heading(pwr, "Ready mode", ready_why)
        ready = tk.BooleanVar(value=self.ready)
        switch(pwr, "Keep the picture ready while nothing changes", ready, ready_why)

        # what a limit saves, and the latency it adds on the ReShade engine, is
        # in docs/NOTES.md, The frame rate limit
        fps_why = ("At most this many new pictures a second, so the card does less work and draws less power. "
                   "On the ReShade engine, which every windowed lens uses, a limit also makes the lens run "
                   "further behind what is under it. Applies straight away.")
        heading(pwr, "Frame rate limit", fps_why)
        fps_opened = self.max_fps
        fps_var = tk.IntVar(value=self.max_fps)
        radio(pwr, "No limit", fps_var, 0, fps_why)
        radio(pwr, "60 frames a second", fps_var, 60, fps_why)
        radio(pwr, "30 frames a second", fps_var, 30, fps_why)
        if self.max_fps not in (0, 30, 60):
            radio(pwr, "%d frames a second" % self.max_fps, fps_var, self.max_fps, fps_why,
                  beside="as neural-lens.ini sets it")

        # only where the fast engine can run, since the step is that engine's alone
        q_scale, q_opened = None, self.quality_now()
        if eng_ok:
            q_why = FAST_QUALITY_WORDS + " Applies straight away."
            heading(pwr, "Quality step of the fast engine", q_why)
            q_row = tk.Frame(pwr, bg=BG)
            q_row.grid(row=pwr.row, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 6))
            pwr.row += 1
            q_scale, q_name = self.quality_control(q_row, font=font)
            q_scale.pack(side="left")
            q_name.pack(side="left", padx=(12, 0))
            tip(pwr, None, q_why, q_row)

        # ================================================================ fullscreen
        # A page of its own, and not a third section of the Power page: the
        # dialog is as high as its tallest page.
        ful = page("Fullscreen")

        # how to get out of a lens that has no bar is on the page itself, and
        # the NR key and the keys of the menu and the panel in its explanation
        keys, more, _held, _twice = self.keys_words()
        # two short explanations rather than one long one: what a fullscreen
        # lens is, on the heading, and how it is reached, on the line of keys
        keys_why = (more + " The keys can be changed on the Hotkeys page, and a right click on the lens's "
                    "taskbar button lists the lens menu, the NR settings and fullscreen.")
        full_why = ("The picture alone over the whole monitor, with no title bar. Two rows at the bottom stay "
                    "free, so notifications and a taskbar that hides itself still come up, and what the title "
                    "bar would say shows at the top of the screen for a few seconds.")
        heading(ful, "A fullscreen lens", full_why)
        line(ful, "It has no title bar. " + keys, keys_why, FG)
        note_opened = self.fs_note
        note_on = tk.BooleanVar(value=note_opened)
        switch(ful, "Show a note on going fullscreen", note_on,
               "A short note each time the lens goes fullscreen, saying that the lens itself is invisible while "
               "it goes on applying DLSS 5, with the keys and the taskbar button's list. Its Don't show this "
               "again switches this off. While another program holds one of the lens's keys the note comes up "
               "all the same, since that key then does nothing. Applies the next time the lens goes fullscreen.")
        # the warning of check_behind, which only the fast engine can give, since
        # only it measures the delay up to the screen
        behind_on = tk.BooleanVar(value=FS_BEHIND_WARN)
        switch(ful, "Warn when the lens falls behind", behind_on,
               "When the lens's picture keeps running well behind the program in front, a warning at the top of "
               "the screen says so, with what usually helps, and goes away by itself. It comes only while the "
               "fast engine draws the picture. Applies straight away.")

        heading(ful, "Fullscreen engine",
                "Which renderer draws a fullscreen lens. A windowed lens always runs on the ReShade engine.",
                beside="a change restarts a fullscreen picture")
        # one line on why the two buttons are greyed, or on why the choice is not
        # what is running, before the buttons it is about. Where the engine
        # belongs depends on how the lens runs, see _find_fast_exe
        if getattr(sys, "frozen", False):
            belongs = "It belongs in the fast folder beside the lens's own program, where the installer puts it."
        else:
            belongs = ("From source it is built by fast_engine\\build.cmd, into fast_engine\\bin beside "
                       "neural_lens.py.")
        if FAST_EXE is None and not _proxy_installed():
            line(ful, "The fast engine and the Cost Scaler it needs were not found, so fullscreen runs on the "
                      "ReShade engine.",
                 "lens-fast.exe is the fast engine itself. " + belongs + " It calls the model through the Cost "
                 "Scaler, whose files the stack setup puts into the stack folder.", WARN)
        elif FAST_EXE is None:
            line(ful, "The fast engine, lens-fast.exe, was not found, so fullscreen runs on the ReShade engine.",
                 belongs, WARN)
        elif not eng_ok:
            line(ful, "The Cost Scaler is not in the stack folder, so fullscreen runs on the ReShade engine.",
                 "The fast engine calls the model through the Cost Scaler. The stack setup puts its files into "
                 "the stack folder.", WARN)
        elif self.fast_failed:
            line(ful, "The fast engine %s. Fullscreen runs on the ReShade engine until the lens is started "
                      "again." % self.fast_failed, colour=WARN)
        # greyed, the buttons show the engine that runs, whatever the ini asks for.
        # How the two compare in frame rate and power is in README.md
        eng_var = tk.StringVar(value=FULLSCREEN_ENGINE if eng_ok else "stack")
        for b in (radio(ful, "The fast engine", eng_var, "fast",
                        "The lens's own renderer, made for fullscreen. It has no ReShade in it, so ReShade's "
                        "effects are not there, and its NR settings are a panel of the lens's own."),
                  radio(ful, "The ReShade engine", eng_var, "stack",
                        "The renderer every windowed lens uses. It has ReShade in it, so the Home menu, "
                        "ReShade's effects and its screenshot key work fullscreen as they do in a window.")):
            if not eng_ok:
                b.config(state="disabled")

        # the on-screen readout, see show_readout: the five on one row and the
        # four corners on the next, which keeps the page no taller than it must be.
        # Its key, as it is set, see toggle_readout
        ro_key = self.key_for("readout_toggle")
        ro_why = ("A line of figures in a corner of the screen while the lens is fullscreen. Nothing shows until "
                  "at least one of these is on. %s It stays out of the picture and lets every click through. "
                  "Applies straight away." % ("%s shows or hides it." % ro_key if ro_key
                                              else "A key set on the Hotkeys page can show or hide it."))
        heading(ful, "On-screen readout in fullscreen", ro_why)
        ro_opened = FS_READOUT          # what it showed as the dialog opened, see save
        ro_vars = {}
        ro_row = tk.Frame(ful, bg=BG)
        ro_row.grid(row=ful.row, column=0, columnspan=3, sticky="w", padx=8, pady=(1, 0))
        ful.row += 1
        for item, text, why in (
                ("fps", "Frame rate", "How many new pictures a second the lens shows, or idle while nothing "
                                      "under it changes."),
                ("latency", "Latency", "How far the lens's picture runs behind what is under it."),
                ("step", "Quality step", "The fast engine's quality step. It shows only while the fast engine "
                                         "draws the picture."),
                ("passes", "Passes", "How many neural passes run, or NR off while Neural Rendering is off."),
                ("style", "Style", "The NR style in use, Default, Natural or Cinematic.")):
            ro_vars[item] = tk.BooleanVar(master=t, value=item in FS_READOUT)
            b = tk.Checkbutton(ro_row, text=text, variable=ro_vars[item], bg=BG, fg=FG, selectcolor=FIELD,
                               activebackground=BG, activeforeground=FG, disabledforeground=DIM, font=font)
            b.pack(side="left", padx=(0, 10))
            tip(ful, text, why, b)
        at_row = tk.Frame(ful, bg=BG)
        at_row.grid(row=ful.row, column=0, columnspan=3, sticky="w", padx=12, pady=(2, 0))
        ful.row += 1
        at_var = tk.StringVar(master=t, value=FS_READOUT_AT)
        at_made = [tk.Label(at_row, text="Corner", bg=BG, fg=FG, font=font)]
        at_made[0].pack(side="left", padx=(0, 10))
        for corner in FS_READOUT_CORNERS:
            at_made.append(tk.Radiobutton(at_row, text=corner.capitalize(), variable=at_var, value=corner, bg=BG,
                                          fg=FG, selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                                          font=font))
            at_made[-1].pack(side="left", padx=(0, 8))
        tip(ful, "Corner", "Which corner of the lens's monitor the readout sits in.", *at_made)

        # ================================================================ title bar
        bar = page("Title bar")

        heading(bar, "What to show on the title bar",
                "What the title bar of a windowed lens shows beside its buttons. All of these apply straight "
                "away. A fullscreen lens has no title bar. Its menu shows the size, the frame rate and the "
                "latency instead, and the Fullscreen page can put figures on the screen.")
        size_on = tk.BooleanVar(value=self.show_size)
        switch(bar, "Lens size", size_on, "The picture's width and height in pixels.")
        fps_on = tk.BooleanVar(value=self.readout in ("fps", "both"))
        switch(bar, "Frame rate", fps_on,
               "How many new pictures a second the lens shows, which follows the content under it up to the "
               "frame rate limit, averaged over the last few seconds. When nothing moves it reads idle, on the "
               "title bar or in a fullscreen lens's menu, and the picture stays the neural rendering of the last "
               "frame.")
        latency = tk.BooleanVar(value=self.latency_on)
        switch(bar, "Latency", latency, "How far the lens's picture runs behind what is under it.")
        style_on = tk.BooleanVar(value=self.show_style)
        switch(bar, "NR style", style_on,
               "The Home menu's style, Default, Natural or Cinematic, as a picker on the title bar. Picking "
               "one there restarts the picture, because the add-on reads its settings only when it starts. A "
               "change made in the Home menu shows on the bar too.")
        inten_on = tk.BooleanVar(value=self.show_intensity)
        switch(bar, "Overall intensity", inten_on,
               "The Home menu's intensity, shown only. A change made in the Home menu shows on the bar too. It "
               "is changed in the Home menu, where the picture follows it live.")

        # ================================================================ profiles
        prof = page("Profiles")

        prof_why = ("A profile is everything that makes the picture, saved under a name, from the window's place "
                    "and size to every setting in the Home menu. The selector on the title bar saves and "
                    "switches them, and the picture restarts when one is applied.")
        heading(prof, "Profiles", prof_why)
        names = sorted(self.profiles["profiles"], key=str.lower)
        plist = tk.Listbox(prof, height=max(4, min(8, len(names))), bg=FIELD, fg=FG, relief="flat",
                           selectbackground=HOVER, selectforeground=FG, exportselection=False,
                           font=font, highlightthickness=0)
        for n in names:
            plist.insert("end", n)
        plist.grid(row=prof.row, column=0, columnspan=2, sticky="nwe", padx=12, pady=(2, 2))
        tip(prof, "The list", "The saved profiles. Choosing one shows what it holds and puts its name in the "
                              "field.", plist)
        # beside the list: the name, and what is done with it
        side = tk.Frame(prof, bg=BG)
        side.grid(row=prof.row, column=2, sticky="nw", padx=(6, 12), pady=(2, 2))
        pname = tk.StringVar(master=t, value="")
        named = tk.Frame(side, bg=BG)
        named.pack(anchor="w")
        tk.Label(named, text="Name", bg=BG, fg=FG, font=font).pack(side="left")
        tk.Entry(named, textvariable=pname, width=22, bg=FIELD, fg=FG, insertbackground=FG, relief="flat",
                 font=ctl).pack(side="left", padx=(10, 0))
        tip(prof, "Name", "The name a profile is renamed to or saved under.", named)
        prof.row += 1

        def chosen():
            sel = plist.curselection()
            return plist.get(sel[0]) if sel else None

        # what the chosen profile holds, the lens's own settings on the left and
        # the Home menu's on the right, grouped the way the menu groups them
        facts = tk.Frame(prof, bg=BG)
        facts.grid(row=prof.row, column=0, columnspan=3, sticky="we", padx=12, pady=(10, 4))
        prof.row += 1

        def fact_rows(p):
            a = p.get("addon", {}) or {}

            def val(key, names=None):
                v = a.get(key)
                if v is None:
                    return "default"
                if names is not None:
                    return names.get(str(v).strip(), str(v))
                return str(v)

            onoff = {"0": "off", "1": "on"}
            bar_parts = [x for x in (("size" if p.get("title_size", True) else ""),
                                     {"fps": "frame rate", "detail": "in and out",
                                      "both": "frame rate, in and out"}.get(p.get("readout"), ""),
                                     ("latency" if p.get("latency") else ""),
                                     ("NR style" if p.get("title_style") else ""),
                                     ("intensity" if p.get("title_intensity") else "")) if x]
            lens_rows = [("Passes", str(p.get("passes", ""))),
                         ("Size", "%s x %s" % (p.get("width", "?"), p.get("height", "?"))),
                         ("Place", "%s, %s" % (p.get("x", "?"), p.get("y", "?"))),
                         ("Fullscreen", "yes" if p.get("fullscreen") else "no"),
                         ("Ready mode", "on" if p.get("ready") else "off"),
                         ("Frame rate limit", ("%d fps" % p["max_fps"]) if p.get("max_fps") else
                          ("none" if "max_fps" in p else "not saved in this profile")),
                         ("Motion detail", p["motion_detail"].capitalize() if p.get("motion_detail")
                          else "not saved in this profile"),
                         ("Cost Scaler", str(p.get("cost_scaler", ""))),
                         ("Title bar", ", ".join(bar_parts) or "nothing")]
            nr_rows = [("Neural Rendering", val("NeuralUplift", onoff)),
                       ("NR style", val("NRStyle", {"0": "Default", "1": "Natural", "2": "Cinematic"})),
                       ("Overall intensity", val("NRIntensity")),
                       ("NR passes", val("NRPasses")),
                       ("Chained temporal history", val("NRChainedHistory", onoff)),
                       ("Codec", val("NRCodecMode", {"0": "Classic", "1": "Anchored"})),
                       ("Global tone", val("NRGlobalTone")),
                       ("Local tone", val("NRLocalTone")),
                       ("Auto mask", val("NRAutoMask", onoff)),
                       ("Upscaling", val("NREnableUpscaling", onoff))]
            return lens_rows, nr_rows

        def show_facts(name):
            for c in facts.winfo_children():
                c.destroy()
            p = self.profiles["profiles"].get(name) if name else None
            if p is None:
                return
            for col, (title, rows) in enumerate((("The lens", fact_rows(p)[0]),
                                                 ("Neural Rendering, the Home menu", fact_rows(p)[1]))):
                tk.Label(facts, text=title, bg=BG, fg=FG, font=small + ("bold",)).grid(
                    row=0, column=col * 2, columnspan=2, sticky="w", padx=(0, 24), pady=(0, 2))
                for i, (k, v) in enumerate(rows):
                    tk.Label(facts, text=k, bg=BG, fg=DIM, font=small, bd=0, pady=0).grid(
                        row=i + 1, column=col * 2, sticky="w", padx=(0, 10))
                    tk.Label(facts, text=v, bg=BG, fg=FG, font=small, bd=0, pady=0, justify="left",
                             wraplength="130p").grid(row=i + 1, column=col * 2 + 1, sticky="w", padx=(0, 24))

        def on_pick(*_):
            n = chosen()
            if n:
                pname.set(n)
                show_facts(n)

        plist.bind("<<ListboxSelect>>", on_pick)

        def refresh():
            plist.delete(0, "end")
            for n in sorted(self.profiles["profiles"], key=str.lower):
                plist.insert("end", n)
            show_facts(None)

        def rename():
            n = chosen()
            if n:
                self.profile_rename(n, pname.get(), "Settings")
                refresh()

        def delete():
            n = chosen()
            if n:
                self.profile_delete(n, "Settings")
                refresh()
                pname.set("")

        def save_current():
            n = pname.get().strip()
            if n:
                self.profile_store(n, "Settings")
                refresh()

        def act(holder, text, command, why, **how):
            b = press(holder, text, command)
            b.pack(**how)
            tip(prof, text, why, b)

        btns = tk.Frame(side, bg=BG)
        btns.pack(anchor="w", pady=(8, 0))
        act(btns, "Rename", rename, "Gives the profile chosen in the list the name in the field.",
            side="left", padx=(0, 6))
        act(btns, "Delete", delete, "Deletes the profile chosen in the list, at once and for good.", side="left")
        act(side, "Save the current settings", save_current,
            "Saves what the lens is now as a profile under the name in the field, and makes it the one in use. "
            "A profile that has that name already is replaced.", anchor="w", pady=(6, 0))
        # the profile in use starts chosen, with its facts shown
        if self.profile in self.profiles["profiles"]:
            plist.selection_set(names.index(self.profile))
            pname.set(self.profile)
            show_facts(self.profile)

        # ================================================================ hotkeys
        hk = page("Hotkeys")

        heading(hk, "Global hotkeys",
                "A key combination that works from anywhere, whichever window has the keyboard. Each one is "
                "taken from every other program while the lens runs, so none is set until you set it, apart "
                "from the last four, which are held only while the lens is fullscreen and in view. Home, F5 "
                "and F6 on their own are kept for ReShade and the add-on.",
                beside="click a field, then press the combination")
        # what each key does, which is its row's explanation
        hk_does = {
            "screenshot": "Saves the picture under the lens, the lens's picture and the two joined side by "
                          "side, as Save before and after in the menu does.",
            "add_pass": "Adds a neural pass, up to four. The picture restarts.",
            "drop_pass": "Takes a neural pass away. The picture restarts.",
            "quality_up": "Moves the fast engine's quality step one step up, toward Quality.",
            "quality_down": "Moves the fast engine's quality step one step down, toward Lowest power.",
            "split": "Puts a divider across the lens that can be dragged, with Neural Rendering on its left "
                     "and the untouched picture on its right.",
            "minimize": "Puts the lens away on the taskbar, where it pauses and costs the card nothing, and "
                        "brings it back.",
            "fullscreen": "Fills the monitor the lens is on, and goes back to the window it was. The picture "
                          "restarts each way. A lens attached to a window stays as it is.",
            "hide_bar": "Folds the title bar and the frame away, leaving a small tab on the picture's top "
                        "edge, and brings them back.",
            "profile": "Applies the next profile in order of name. The picture restarts.",
            "ready": "Switches Ready mode, which the Power page explains.",
            "detach": "Lets go of the window the lens is attached to and puts the lens back where it was.",
            "lens_menu": "Opens and closes the lens menu at the pointer. While it is open, the arrow keys move "
                         "through it, Enter chooses and Escape closes it. Taken only while the lens is "
                         "fullscreen and in view.",
            "nr_panel": "Opens and closes the NR settings, which are the lens's own panel with the fast "
                        "engine and ReShade's overlay with the ReShade engine. On the panel the arrow keys pick "
                        "a setting and change it, Enter switches a switch and Escape closes it. Taken only while "
                        "the lens is fullscreen and in view.",
            "nr_toggle": "Turns Neural Rendering off and on. Taken only while the lens is fullscreen and in view.",
            "readout_toggle": "Shows or hides the on-screen readout, the line of figures the Fullscreen page sets "
                              "up. Shown again, it has the figures it had before, or the frame rate and the latency "
                              "if it had none. Taken only while the lens is fullscreen and in view.",
        }
        hk_vars, hk_note = {}, {}
        failed = dict(self.hotkeys.failed)

        def capture(action, var, ent):
            def on_key(e):
                sym = e.keysym
                if sym == "F1" and not e.state & 0x20005:
                    return None             # F1 alone is the dialog's help, see Hints.key. With Ctrl,
                                            # Alt or Shift it can still be set
                hints.hide()                # any other key the field takes, as a key does elsewhere
                if sym in ("Tab", "ISO_Left_Tab") and not e.state & 0x20004:
                    return None             # Tab and Shift+Tab move on to the next setting, as anywhere
                if sym in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                           "Win_L", "Win_R", "Meta_L", "Meta_R"):
                    return "break"
                mods = 0
                if e.state & 0x4:
                    mods |= MOD_CONTROL
                if e.state & 0x20000:
                    mods |= MOD_ALT
                if e.state & 0x1:
                    mods |= MOD_SHIFT
                low = sym.lower()
                names = {"prior": "pageup", "next": "pagedown", "return": "enter", "print": "printscreen",
                         "scroll_lock": "scrolllock", "apostrophe": "quote", "grave": "backquote",
                         "kp_multiply": "multiply", "kp_add": "add", "kp_subtract": "subtract",
                         "kp_divide": "divide", "kp_decimal": "decimal"}
                low = names.get(low, low)
                if low.startswith("kp_") and low[3:].isdigit():
                    low = "numpad" + low[3:]
                if len(low) == 1 and (low.isalpha() or low.isdigit()):
                    vk = ord(low.upper())
                elif low in VK_BY_NAME:
                    vk = VK_BY_NAME[low]
                else:
                    return "break"
                text = _hotkey_text(mods, vk)
                problem = _hotkey_problem(text)
                # a combination another row has would be held for one of the
                # two alone, so it is refused here, naming that row
                other = None if problem else next(
                    (b for b, v in hk_vars.items() if b != action and v.get().strip()
                     and not _hotkey_problem(v.get().strip()) and _parse_hotkey(v.get().strip()) == (mods, vk)),
                    None)
                if problem:
                    hk_note[action].config(text=problem, fg=WARN)
                elif other is not None:
                    hk_note[action].config(text="already set for %s" % HOTKEY_LABELS[other], fg=WARN)
                else:
                    var.set(text)
                    hk_note[action].config(text="", fg=DIM)
                return "break"
            ent.bind("<KeyPress>", on_key)

        for action, label in HOTKEY_ACTIONS:
            var = tk.StringVar(master=t, value=HOTKEYS.get(action, ""))
            hk_vars[action] = var
            name = tk.Label(hk, text=label, bg=BG, fg=FG, font=font)
            name.grid(row=hk.row, column=0, sticky="w", padx=12, pady=(3, 0))
            ent = tk.Entry(hk, textvariable=var, width=18, bg=FIELD, fg=FG, insertbackground=BG,
                           relief="flat", justify="center", font=ctl)
            ent.grid(row=hk.row, column=1, sticky="w", padx=(6, 6), pady=(3, 0))
            capture(action, var, ent)
            fr = tk.Frame(hk, bg=BG)
            fr.grid(row=hk.row, column=2, sticky="w", padx=(0, 12), pady=(3, 0))
            press(fr, "Clear", lambda v=var, a=action: (v.set(""), hk_note[a].config(text="")),
                  small).pack(side="left")
            # a key another program holds, or one the lens holds for a row above
            # this one, which an ini of 0.5.1 can have given two actions, or on
            # a row left empty its default, which another row has, see
            # _hotkeys_from_ini
            holder = _hotkey_holder(action)
            left = None if HOTKEYS.get(action) else HOTKEY_LEFT_OUT.get(action)
            hk_note[action] = tk.Label(fr, text=("in use by another program" if action in failed
                                                 else "held for %s" % HOTKEY_LABELS[holder] if holder
                                                 else "%s held for %s" % (HOTKEY_DEFAULTS[action], HOTKEY_LABELS[left])
                                                 if left else ""),
                                       bg=BG, fg=WARN, font=small)
            hk_note[action].pack(side="left", padx=(8, 0))
            hk.row += 1
            tip(hk, label, hk_does.get(action), name, ent, fr)

        # ================================================================ screenshots
        sh = page("Screenshots")

        shots_why = ("Each screenshot saves the picture under the lens, the lens's picture, and the two joined "
                     "side by side, into this folder.")
        heading(sh, "Where to save screenshots", shots_why)
        shots = tk.StringVar(value=SHOT_DIR)
        folder(sh, None, shots, "Where should screenshots go?", shots_why)

        clip_why = ("The side by side image goes onto the clipboard as well as into the folder, ready to paste "
                    "into a message or a document. Applies to the next screenshot.")
        heading(sh, "The clipboard", clip_why)
        clip = tk.BooleanVar(value=self.clip_shots)
        switch(sh, "Copy the side by side image to the clipboard", clip, clip_why)

        # ================================================================ look
        look = page("Look")

        theme_why = ("The colours of the title bar, the menus and this dialog, never of the picture. A "
                     "themes.json in the data folder can add themes of your own, with the keys the built-in "
                     "ones use. Choosing one restarts the lens.")
        heading(look, "Theme", theme_why, beside="choosing one restarts the lens")
        theme_var = tk.StringVar(value=THEME_NAME)
        for name in sorted(ALL_THEMES, key=lambda n: (n != "Slate", n.lower())):
            t_ = ALL_THEMES[name]
            row_ = tk.Frame(look, bg=BG)
            row_.grid(row=look.row, column=0, columnspan=3, sticky="w", padx=8, pady=(1, 0))
            tk.Radiobutton(row_, text=name, variable=theme_var, value=name, bg=BG, fg=FG,
                           selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                           font=font, width=12, anchor="w").pack(side="left")
            for key in ("bg", "field", "hover", "cap", "fg", "dim", "accent", "warn", "close"):
                tk.Frame(row_, bg=t_[key], width=26, height=18, highlightthickness=1,
                         highlightbackground=t_["dim"]).pack(side="left", padx=1)
            look.row += 1
            tip(look, name, theme_why, row_)

        # ================================================================ program
        prog = page("Program")

        heading(prog, "Updates", "Whether the lens looks for a newer release than this, %s. With both "
                                 "switches off the lens never contacts anything." % __version__)
        upd = tk.BooleanVar(value=self.check_updates_on)
        auto = tk.BooleanVar(value=self.auto_update_on)
        upd_btn = switch(prog, "Check for a new version when the lens starts", upd,
                         "The lens asks GitHub for the newest release when it starts, at most once a day, and "
                         "says nothing unless there is one newer than this, %s. Then it asks, and opens the "
                         "release page only if you say so. Off, the lens never contacts anything."
                         % __version__)
        switch(prog, "Offer to download and install it, after asking", auto,
               "When there is a newer release the lens offers to download its installer and run it over this "
               "install, only if you say yes, and comes back on the new version. With this on, the switch "
               "above is on as well.")
        button(prog, "Check now", lambda: self.check_updates(quiet=False, how="Settings"),
               "Asks GitHub for the newest release once, straight away, and says what it found.")

        def follow_auto(*_):
            if auto.get():
                upd.set(True)
                upd_btn.config(state="disabled")
            else:
                upd_btn.config(state="normal")
            upd_btn.beside.config(text="on while the switch below is on" if auto.get() else "")

        auto.trace_add("write", follow_auto)
        follow_auto()

        heading(prog, "Folders", "Where the lens finds the stack and where it keeps its own files. Both take "
                                 "effect at the next launch, so changing either restarts the lens.",
                beside="a change restarts the lens")
        stack = tk.StringVar(value=STACK_DIR or "")
        folder(prog, "The Neural Rendering stack", stack, "Where is the Neural Rendering stack?",
               "The folder that holds the Neural Rendering stack and lens-presenter.exe. Takes effect at the "
               "next launch, so a change restarts the lens.")
        data = tk.StringVar(value=DATA_DIR)
        folder(prog, "The lens's state and logs", data, "Where should the lens keep its state and logs?",
               "Where the lens keeps its window state and archived logs. Takes effect at the next launch, so "
               "a change restarts the lens.")

        # every page ends a little above its bottom edge, the tallest one too
        for p in (pic, pwr, ful, bar, prof, hk, sh, look, prog):
            tk.Frame(p, bg=BG, height=12).grid(row=p.row, column=0)

        # ================================================================ footer
        def save():
            global SHOT_DIR
            restart = False
            # each setting that changes, by its name in the ini and its new
            # value, for the one line the log gets for the save
            changed = []

            def said(key, value):
                changed.append("%s %s" % (key, value))

            d = shots.get().strip()
            if d and d != SHOT_DIR:
                SHOT_DIR = d
                _save_ini("screenshot_dir", d)
                said("screenshot_dir", d)
            m = stack.get().strip()
            if m and m != (STACK_DIR or ""):
                _save_ini("stack_dir", m)
                said("stack_dir", m)
                restart = True
                # a --stack-dir on this run's command line, such as the stack setup's
                # restart gives, would outrank the ini and bring the old folder back
                k = 1
                while k < len(sys.argv):
                    if sys.argv[k] in ("--stack-dir", "--mpv-dir"):
                        del sys.argv[k:k + 2]
                    else:
                        k += 1
            dd = data.get().strip()
            if dd and dd != DATA_DIR:
                _save_ini("data_dir", dd)
                said("data_dir", dd)
                restart = True
            if theme_var.get() != THEME_NAME:
                _save_ini("theme", None if theme_var.get() == "Slate" else theme_var.get())
                said("theme", theme_var.get())
                restart = True
            # the in-and-out readout is the ini's alone, readout = detail, so a save
            # here keeps it if it was set
            detail = self.readout in ("detail", "both")
            r = ("both" if detail and fps_on.get() else "detail" if detail
                 else "fps" if fps_on.get() else "size")
            if r != self.readout:
                self.readout = r
                _save_ini("readout", None if r == "size" else r)
                said("readout", r)
            mirrors_changed = False
            if bool(style_on.get()) != self.show_style:
                self.show_style = bool(style_on.get())
                _save_ini("title_style", "1" if self.show_style else None)
                said("title_style", int(self.show_style))
                mirrors_changed = True
            if bool(inten_on.get()) != self.show_intensity:
                self.show_intensity = bool(inten_on.get())
                _save_ini("title_intensity", "1" if self.show_intensity else None)
                said("title_intensity", int(self.show_intensity))
                mirrors_changed = True
            if mirrors_changed:
                self.show_bar_mirrors()
            if bool(latency.get()) != self.latency_on:
                self.latency_on = bool(latency.get())
                self.latency_ms = None
                _save_ini("latency", None if self.latency_on else "0")
                said("latency", int(self.latency_on))
            if bool(size_on.get()) != self.show_size:
                self.show_size = bool(size_on.get())
                _save_ini("title_size", None if self.show_size else "0")
                said("title_size", int(self.show_size))
            if bool(ready.get()) != self.ready:
                self.summarise(now=True)    # under the mode it had, see summarise
                self.ready = bool(ready.get())
                _save_ini("ready", "1" if self.ready else None)
                said("ready", int(self.ready))
                self.tell_presenter("ready %d" % (1 if self.ready else 0))
            # a limit or a detail changed by a profile or the overlay while the dialog
            # was open stays, unless it was changed here too
            if int(fps_var.get()) != fps_opened and int(fps_var.get()) != self.max_fps:
                self.summarise(now=True)    # under the limit it had, which the line names
                self.max_fps = int(fps_var.get())
                _save_ini("max_fps", str(self.max_fps) if self.max_fps else None)
                said("max_fps", self.max_fps)
                self.tell_presenter("cap %d" % self.max_fps)
            # the same rule for the quality step, which the NR settings panel changes too
            if q_scale is not None and int(float(q_scale.get())) not in (q_opened, self.quality_now()):
                self.set_quality(int(float(q_scale.get())), "Settings")
                said("fast_quality", int(float(q_scale.get())))
            detail_changed = (md_var is not None and md_var.get() != md_opened
                              and md_var.get() != self.motion_detail)
            if detail_changed:
                self.motion_detail = md_var.get()
                _save_ini("motion_detail", None if self.motion_detail == "full" else self.motion_detail)
                said("motion_detail", self.motion_detail)
            # the engine a fullscreen lens asks for. The picture restarts below only
            # when the lens is fullscreen and the new choice gives it another engine
            # than the one running, which a fast engine that has failed does not
            engine_changed = False
            if eng_ok and eng_var.get() != FULLSCREEN_ENGINE:
                _set_fullscreen_engine(eng_var.get())
                said("fullscreen_engine", eng_var.get())
                engine_changed = self.fullscreen and self.engine_wanted() != self.engine
            mode = "always" if cs_always.get() else "fullscreen" if cs_full.get() else "off"
            if COST_SCALER != "manual" and mode != COST_SCALER:
                _set_cost_scaler(mode)
                said("cost_scaler", mode)
                # the proxy reads its ini within a second of a change, so this is live
                self.apply_proxy()
            for a, v in hk_vars.items():
                if v.get().strip() != HOTKEYS.get(a, ""):
                    said("hotkey_" + a, v.get().strip() or "none")
            self.set_hotkeys({a: v.get() for a, v in hk_vars.items()})
            if bool(clip.get()) != self.clip_shots:
                self.clip_shots = bool(clip.get())
                _save_ini("clipboard_shots", "1" if self.clip_shots else None)
                said("clipboard_shots", int(self.clip_shots))
            # the same rule for the note, which its own Don't show this again switches too
            if bool(note_on.get()) != note_opened and bool(note_on.get()) != self.fs_note:
                self.fs_note = bool(note_on.get())
                _save_ini("fullscreen_note", None if self.fs_note else "0")
                said("fullscreen_note", int(self.fs_note))
            if bool(behind_on.get()) != FS_BEHIND_WARN:
                _set_fs_behind_warn(behind_on.get())
                said("fs_behind_warn", int(FS_BEHIND_WARN))
                if FS_BEHIND_WARN:
                    self.behind_next = 0.0      # not held back by a line written while it was off
                else:
                    self.notes.pop("behind", None)      # a warning that is up goes at once
                    self.show_notice()
            # the readout shows its new figures or corner at once, or goes. Its
            # key can show or hide it while the dialog is open, and that stays
            # unless the figures were changed here too
            items = tuple(i for i in FS_READOUT_ITEMS if ro_vars[i].get())
            if items == ro_opened:
                items = FS_READOUT
            if items != FS_READOUT or at_var.get() != FS_READOUT_AT:
                if items != FS_READOUT:
                    said("fs_readout", ",".join(items) or "none")
                if at_var.get() != FS_READOUT_AT:
                    said("fs_readout_at", at_var.get())
                _set_fs_readout(items, at_var.get())
                self.readout_drawn = None
                self.show_readout()
            if bool(upd.get()) != self.check_updates_on:
                self.check_updates_on = bool(upd.get())
                _save_ini("check_updates", "1" if self.check_updates_on else None)
                said("check_updates", int(self.check_updates_on))
            if bool(auto.get()) != self.auto_update_on:
                self.auto_update_on = bool(auto.get())
                _save_ini("auto_update", "1" if self.auto_update_on else None)
                said("auto_update", int(self.auto_update_on))
            self.act("Settings saved: %s (Save)" % ", ".join(changed) if changed
                     else "Settings saved with nothing changed (Save)")
            self.update_info()              # the profile's name on the bar follows the settings
            t.destroy()
            # the fast engine has no estimator, so under it a new detail waits for
            # the next stack presenter, which reads it as it starts
            if (engine_changed or detail_changed and self.engine != "fast") and not restart:
                # the estimator reads its detail when the presenter starts, and the engine is
                # chosen then. A minimised lens comes back first, as it does for a profile, so
                # the new picture has its chrome
                if self.minimized:
                    self.restore()
                if engine_changed:
                    self.restart_presenter("changing to the %s engine ..."
                                           % ("fast" if self.engine_wanted() == "fast" else "ReShade"))
                else:
                    self.restart_presenter("restarting with %s motion detail ..." % self.motion_detail)
            if restart:
                # the folders take effect at the next launch, so the lens restarts.
                # The windowed geometry is what a fullscreen launch derives its
                # monitor from, and what the way back restores, so keep it current.
                if not self.fullscreen:
                    self.save_state()
                self.quit(restart=True, how="Settings")

        # the one line that says how an explanation comes up, on every page. The
        # version sits beside Save on every page too: a bug report is far more
        # likely to be written with this dialog open than with the console
        foot = tk.Frame(t, bg=BG)
        foot.grid(row=1, column=0, sticky="we", padx=8, pady=(8, 10))
        foot.columnconfigure(0, weight=1)
        tk.Label(foot, text="Rest the pointer on a setting or press F1 for help.", bg=BG, fg=FG,
                 font=small).grid(row=0, column=0, sticky="w", padx=12)
        tk.Label(foot, text="Neural Lens %s (beta)" % __version__, bg=BG, fg=DIM,
                 font=small).grid(row=0, column=1, sticky="e", padx=(12, 14))
        press(foot, "Save", save, bg=ACCENT, fg=FIELD).grid(row=0, column=2, sticky="e", padx=(0, 6))
        press(foot, "Cancel", t.destroy).grid(row=0, column=3, sticky="w", padx=(0, 12))
        self._place_over_lens(t)

    def _place_over_lens(self, win):
        """Put a dialog over the middle of the lens, kept inside that monitor's
        work area, rather than wherever Tk would put it."""
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        try:
            x, y = self.inner()
            cx, cy = x + self.cw // 2, y + self.ch // 2
        except Exception:
            cx, cy = win.winfo_screenwidth() // 2, win.winfo_screenheight() // 2
        left, top = cx - w // 2, cy - h // 2
        try:
            l, t, ww, hh = tuple(work_area(cx, cy))[:4]
            left = max(l, min(left, l + ww - w))
            top = max(t, min(top, t + hh - h))
        except Exception:
            pass
        win.geometry("+%d+%d" % (left, top))

    def _ask(self, title, text, choices):
        """A question with these buttons, the first one the accent. Returns the
        one chosen, or None when the window is closed instead."""
        d = tk.Toplevel(self.root)
        d.title(title)
        d.attributes("-topmost", True)
        d.configure(bg=BG)
        d.resizable(False, False)
        tk.Label(d, text=text, bg=BG, fg=FG, justify="left", wraplength=460, font=("Segoe UI", 10)).grid(
            row=0, column=0, columnspan=len(choices), sticky="w", padx=14, pady=(14, 12))
        picked = []
        for i, c in enumerate(choices):
            tk.Button(d, text=c, command=lambda c=c: (picked.append(c), d.destroy()), relief="flat",
                      bg=ACCENT if i == 0 else HOVER, fg=FIELD if i == 0 else FG).grid(
                row=1, column=i, sticky="w", padx=(14 if i == 0 else 6, 14 if i == len(choices) - 1 else 0),
                pady=(0, 14))
        self._place_over_lens(d)
        d.grab_set()
        self.root.wait_window(d)
        return picked[0] if picked else None

    def quit(self, restart=False, how=None):
        """Close the lens, or with restart, close it for main to start it
        again. how is the way the person at the lens asked, for the log. Where
        the lens closes by itself, the caller says why."""
        if self.closing:
            return
        if how:
            self.act("quit (%s)" % how)
        try:
            self.close_panel()          # what its sliders left unwritten goes into ReShade.ini first
        except Exception:
            pass
        self.restart = restart
        self.closing = True
        self.popup.close()
        try:
            self.hotkeys.stop()
            if self.commands is not None:
                self.commands.stop()
        except Exception:
            pass
        for s in reversed(self.stages):
            self._kill_stage(s)
        # the taskbar button's list goes with the last lens, or a button that
        # is pinned to the taskbar would go on showing it. An entry that a lens
        # ended by force leaves behind starts the lens, see --do
        try:
            if not _other_lens():
                _taskbar_list(False)
        except Exception:
            pass
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self.root.quit()


def _pause():
    """Hold the console open so a message on the way out can be read.

    stdin is not always a console. With input redirected, input() raises
    EOFError, and without a console it raises RuntimeError; either would bury
    the message this exists to let you read under a traceback about the
    attempt to wait for you. With no console at all there is nothing to hold
    open.
    """
    if HEADLESS:
        return
    try:
        input("\nPress Enter to close.")
    except (EOFError, OSError, RuntimeError):
        print("")            # the prompt carries no newline of its own


def _fatal(text):
    """Say why the lens cannot start, somewhere it will actually be seen.

    With a console, print and wait for Enter. Without one, the print goes to
    lens.log and a dialog carries the message: a line in a log file is not
    something a person who just double clicked a launcher is going to find.
    """
    print(text, flush=True)
    if not HEADLESS:
        _pause()
        return
    try:
        made = None
        if tk._default_root is None:
            made = tk.Tk()          # or messagebox makes a visible one itself
            made.withdraw()
        messagebox.showerror("Neural Lens", text)
        if made is not None:
            made.destroy()
    except Exception:
        pass


def _offer_setup(reason):
    """Offer to fetch and assemble the neural stack, and relaunch if it worked.

    Returns True when the lens has been relaunched and this process should
    simply return. The stack setup lives in neural_stack.py; the relaunch is
    told the folder it installed into, so no ini change is needed and nothing
    that pointed elsewhere gets in the way.
    """
    try:
        import neural_stack
    except ImportError:
        return False
    root = tk.Tk()
    _set_icon(root)
    root.withdraw()
    root.attributes("-topmost", True)
    want = messagebox.askyesno(
        "Neural Lens",
        reason + "\n\nSet up the Neural Rendering stack now? About %d MB is downloaded from "
        "the projects that publish each part, into the lens's own folder, and registered for "
        "your user only, with no administrator prompt. It takes a few minutes."
        % neural_stack.DOWNLOAD_MB)
    where = False
    if want:
        where = neural_stack.wizard(root)
    try:
        root.destroy()
    except Exception:
        pass
    if not where:
        return False
    # name the new stack first, ahead of whatever led here: a --stack-dir or an
    # ini stack_dir that pointed at an incomplete folder would otherwise be
    # found again by the relaunch, which would offer the setup all over again.
    # From source the command starts with the interpreter and the script, and
    # the interpreter refuses a --stack-dir of its own, so the pair goes after both
    cmd = _relaunch_cmd()
    n = 1 if getattr(sys, "frozen", False) else 2
    subprocess.Popen(cmd[:n] + ["--stack-dir", where] + cmd[n:], cwd=_script_dir())
    return True


def _main():
    # Three entry points the installer uses. This one runs DURING setup, so it
    # must never open a window of its own: the whole point is that the user
    # meets one installer and not a second surprise afterwards. Everything goes
    # to its own log, which the installer reads line by line to show progress
    # on its own page, and the last line is a sentinel carrying the exit code.
    # The fourth flag the lens accepts, --stack-dir, is read by _find_stack_dir
    # at import time; the lens passes it to itself when it relaunches after a
    # setup.
    if "--install-stack" in sys.argv:
        import neural_stack
        argv = [a for a in sys.argv[1:] if a != "--install-stack"]

        class _Tee:
            """Write to every stream that exists, ignoring the ones that do not.

            The installer reads this process's stdout to show progress on its
            own page, and the log file has to survive for a post mortem.
            Replacing stdout with the file would leave the installer reading
            nothing for the whole download while the log filled up where
            nobody could see it.
            """

            def __init__(self, *streams):
                self.streams = [s for s in streams if s is not None]

            def write(self, text):
                for s in self.streams:
                    try:
                        s.write(text)
                        s.flush()
                    except Exception:
                        pass
                return len(text)

            def flush(self):
                for s in self.streams:
                    try:
                        s.flush()
                    except Exception:
                        pass

        handle = None
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            handle = open(os.path.join(LOGDIR, "stack-setup.log"), "w",
                          encoding="utf-8", errors="replace", buffering=1)
        except OSError:
            pass
        # __stdout__ is None in a windowed build launched with no pipe; when the
        # installer runs us it supplies one, and that is what it reads back
        sys.stdout = sys.stderr = _Tee(handle, getattr(sys, "__stdout__", None))
        try:
            rc = neural_stack.main(argv)
        except Exception as exc:                  # never die silently mid-setup
            print("FAILED: %r" % (exc,), flush=True)
            rc = 3
        print("__STACK_SETUP_EXIT__ %d" % rc, flush=True)
        try:
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(rc)
    # the Start Menu's stack setup, which is the repair path and may show its
    # own window, and the uninstaller's removal of what the setup wrote, and of
    # the taskbar button's list, which a lens that was ended by force leaves
    if "--setup-stack" in sys.argv:
        import neural_stack
        neural_stack.wizard()
        return
    if "--uninstall-stack" in sys.argv:
        import neural_stack
        _taskbar_list(False)
        try:
            neural_stack.uninstall()
        except neural_stack.StackError as exc:
            print(exc, flush=True)
        return
    # From source the taskbar button and its list belong together through an id
    # of the lens's own, which the process has to carry before its first window
    # is made. Installed there is none to set, see APP_ID.
    if APP_ID:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_ID))
        except Exception:
            pass
    if not STACK_DIR:
        if _offer_setup("The lens could not find its Neural Rendering stack."):
            return
        _fatal("\n".join([
            "Could not find the Neural Rendering stack.",
            "",
            "The lens looks for lens-presenter.exe in its own folder when installed,",
            "in the 'stack' folder beside the script when run from source, and in a",
            "folder pointed at in any of these ways:",
            "",
            '  --stack-dir "D:\\path\\to\\stack" on the command line',
            "  set NEURAL_LENS_STACK=D:\\path\\to\\stack",
            "  copy neural-lens.ini.example to neural-lens.ini and set stack_dir",
            "",
            "The Start Menu's stack setup entry, or python neural_stack.py from",
            "source, fetches and assembles the stack.",
        ]))
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as exc:
        # data_dir is taken from the ini or the environment verbatim and is the
        # one setting nothing validates, so a path on a drive that does not
        # exist would otherwise arrive here as a raw traceback
        _fatal("\n".join([
            "Could not use the folder the lens keeps its state in:",
            "",
            "  %s" % DATA_DIR,
            "",
            "  %s" % exc,
            "",
            "Set data_dir in neural-lens.ini to a folder that exists, or delete",
            "that line to use the data folder beside the program.",
        ]))
        return
    cw, ch, x, y, passes = 1400, 1000, None, None, 1
    if os.path.exists(STATE):
        try:
            v = [int(n) for n in open(STATE).read().split()]
            cw, ch, x, y = v[:4]
            if len(v) > 4:
                passes = v[4]
        except Exception:
            cw, ch, x, y = 1400, 1000, None, None
    if x is None:
        # nothing saved: the preferred size, centred on the main monitor, whose
        # top left corner is always the desktop's origin
        mx, my, mw, mh = work_area(0, 0)
        x, y, cw, ch = fit_rect(mx + EDGE, my + BAR, cw, ch, (mx, my, mw, mh))
        x = mx + (mw - cw) // 2
        y = my + BAR + (mh - BAR - EDGE - ch) // 2
    # kept on one monitor: a saved place can be on a monitor that has since gone,
    # or larger than a lowered resolution leaves room for
    x, y, cw, ch = fit_rect(x, y, cw, ch)
    if FULLSCREEN:
        # the whole of the monitor the windowed lens sits on, from its top edge,
        # see fullscreen_rect. A fullscreen lens has no title bar, so nothing lies
        # over the ReShade overlay, which opens at the picture's top left with
        # its tabs along its top edge. The picture stops two rows short of the
        # monitor's bottom edge, so it never covers the monitor exactly, see
        # FULL_SHORT. The pass count comes from the fullscreen lens's own file.
        x, y, cw, ch = fullscreen_rect(x, y, cw, ch)
        if os.path.exists(FULL_STATE):
            try:
                passes = int(open(FULL_STATE).read().split()[0])
            except Exception:
                pass
    cw -= cw % 2
    ch -= ch % 2
    passes = max(1, min(_pass_limit(), passes))
    archive_logs()
    root = tk.Tk()
    _set_icon(root)
    root.withdraw()
    missing = _missing_stack()
    if missing:
        # This has to run before the presenter exists. Its window is topmost
        # and a stock messagebox is not, so once the lens is up this dialog
        # would be drawn underneath it: see Lens.confirm.
        note = "\n".join(
            ["Neural Rendering will probably not run.",
             "",
             "These are not in the stack folder:",
             "  %s" % STACK_DIR,
             ""]
            + ["  %s   (%s)" % (n, d) for n, d in missing]
            + ["",
               "The lens will still open, but it will most likely show the screen",
               "back to you unchanged. The stack setup fetches every one of them."])
        print("\n" + note + "\n", flush=True)
        if _offer_setup(note):
            return
    # the lens's ReShade has to switch on in its own presenter alone, see
    # _layer_ungated. Where this copy's own description would switch it on in
    # every program, the lens says so and offers the stack setup, which writes
    # the limit, unless the setup was just offered for a stack that is
    # incomplete. The setup writes nothing but this copy's own, so for one that
    # another copy of the lens registered the lens asks whether to remove that
    # registration, once, see _layer_stray
    ungated = _layer_ungated()
    if ungated:
        print("the lens's Vulkan layer is not limited to the lens: %s has no enable_environment for "
              "ENABLE_VK_LAYER_reshade_neural_lens" % ", ".join(ungated), flush=True)
        own = _layer_own()
        if any(_layer_key(p) == own for p in ungated) and not missing and _offer_setup(LAYER_WORDS):
            return
        for p in ungated:
            # kept by the ini, or a moment ago, see _layer_stray
            if _layer_key(p) != own and _layer_key(p) not in {_layer_key(k) for k in LAYER_STRAY_KEPT}:
                _layer_stray(p, root)
    try:
        lens = Lens(root, x, y, cw, ch, passes, FULLSCREEN)
    except SystemExit as exc:
        # a presenter that never opened its window. Without a console the
        # message would go to the log and the lens would simply fail to appear.
        _fatal(str(exc))
        return
    # a lens that an entry of the taskbar list started fullscreen writes the flag
    # as set_fullscreen does, so a restart, an update or the next launch opens
    # it fullscreen again
    if _DO_START == "fullscreen" and lens.fullscreen:
        try:
            _save_ini("fullscreen", "1")
        except OSError:
            pass
    lens.show_in_taskbar()
    print("Neural Lens %s (beta)" % __version__, flush=True)
    print("lens ready %dx%d at (%d,%d), %d pass%s%s, stack %s"
          % (cw, ch, x, y, lens.passes, "" if lens.passes == 1 else "es",
             ", fullscreen on the fast engine" if lens.engine == "fast"
             else ", fullscreen" if FULLSCREEN else "", STACK_DIR),
          flush=True)
    if not ADDON_PASSES:
        print("the add-on in the stack cannot run several passes itself, so the lens runs one",
              flush=True)
    # the list on the taskbar button's right click. The lens runs without it
    # where Windows does not take it
    try:
        wrong = _taskbar_list()
    except Exception as exc:
        wrong = str(exc) or type(exc).__name__
    print("the taskbar button's list is set, %d entries" % len(DO_ENTRIES) if wrong is None
          else "the taskbar button's list could not be set (%s), so the lens runs without it" % wrong,
          flush=True)

    def watch():
        # the stage list is empty for a moment during a restart, and reading
        # stages[0] then would kill this thread, after which a presenter that
        # died would go unnoticed for the rest of the session
        while not lens.closing:
            time.sleep(0.4)
            stages = lens.stages
            if lens.rebuilding or not stages:
                continue
            proc = stages[0]["proc"]
            fast = lens.engine == "fast"
            gone = lens.engine_gone(proc) if fast else proc.poll() is not None
            # a restart that began since the list was read has killed this one
            # itself, and may have changed the engine: that is not a death
            if not gone or lens.rebuilding or lens.stages is not stages:
                continue
            if not fast:
                break
            # the fast engine going is not the end of the lens: the stack
            # presenter takes over, see Lens.engine_lost. A minimised lens is
            # left alone, and restore sees to it when it comes back
            if not lens.minimized:
                try:
                    root.after(0, lens.engine_lost, proc)
                except Exception:
                    pass
        else:
            # the lens is closing by itself, and its main loop may be over by
            # now, which leaves Tk nothing to call quit with
            return
        # the stack presenter died: that ends the lens
        print("quit (the presenter ended, exit code %s)" % proc.poll(), flush=True)
        try:
            root.after(0, lens.quit)
        except RuntimeError:
            pass                            # the main loop ended meanwhile

    threading.Thread(target=watch, daemon=True).start()
    root.mainloop()

    if lens.restart:
        # The folder settings take effect at the next launch, so hand the process
        # over to a fresh copy of itself once the presenter is really gone.
        #
        # Not os.execv. On Windows that goes through the CRT, which does not quote
        # arguments containing spaces, so a script path such as
        # "C:\\Some Folder\\neural-lens\\neural_lens.py" reaches the replacement
        # process split at the space. It does not raise either: it starts something
        # broken while this process is already gone, so the lens never comes back
        # and nothing is reported. subprocess quotes correctly through list2cmdline.
        try:
            root.destroy()
        except Exception:
            pass
        time.sleep(1.0)
        cmd = _relaunch_cmd()
        note = os.path.join(LOGDIR, "restart.log")
        print("restarting", flush=True)
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            # The console this was started from may go away with this process, so
            # give the replacement its own destination for anything it prints.
            out = open(note, "w", encoding="utf-8", errors="replace")
            env = None
            if isinstance(sys.stdout, _StampedLines):
                # a lens that logs to lens.log hands it on. NEURAL_LENS_LOG_APPEND
                # names the file, and the replacement goes on in it where it is
                # the replacement's own lens.log too, which a new data folder
                # changes. What this one has left to say goes to restart.log,
                # so that the two never write the same file. restart.log then
                # holds only what the replacement prints before it takes up its
                # lens.log, and stays in this data folder
                log = sys.stdout
                handed = os.path.abspath(getattr(log.f, "name", "") or os.path.join(LOGDIR, "lens.log"))
                sys.stdout = sys.stderr = _StampedLines(out)
                try:
                    log.f.close()
                except OSError:
                    pass
                env = dict(os.environ, NEURAL_LENS_LOG_APPEND=handed)
            child = subprocess.Popen(cmd, cwd=_script_dir(), env=env,
                                     stdout=out, stderr=subprocess.STDOUT)
        except Exception as exc:
            print("could not restart: %s" % exc, flush=True)
            print("start it again yourself, the settings are already saved", flush=True)
            return
        # A restart that fails should say so rather than vanishing without a word.
        time.sleep(3.0)
        if child.poll() is not None:
            print("the restart exited straight away (code %s)" % child.poll(), flush=True)
            print("what it printed is in %s" % note, flush=True)
            print("start it again yourself, the settings are already saved", flush=True)


def main():
    """The program, see _main. It holds the mutex that marks a lens alive from
    its start until it returns, a restart included, see _hold_alive. Whether
    another lens holds it too makes no difference here, so several lenses can
    still run. It is let go here and not left to the end of the process,
    since a test runs main in a process that goes on and then starts a lens
    with --do."""
    global _ALIVE
    _hold_alive()
    try:
        _main()
    finally:
        if _ALIVE is not None:
            _k32.CloseHandle(_ALIVE)
            _ALIVE = None


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # without a console a traceback goes to lens.log and the lens simply
        # never appears, which is the silence the log and the dialogs exist to end
        import traceback
        _fatal("The lens stopped with an error.\n\n" + traceback.format_exc())
        sys.exit(1)
