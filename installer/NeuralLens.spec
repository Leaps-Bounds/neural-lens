# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the DLSS 5 Neural Lens: two programs in one folder, and
# the fast engine beside them.
#
# NeuralLens.exe is the lens and lens-presenter.exe the presenter it starts,
# sharing one _internal folder. The installed program's folder is also the
# stack folder, because ReShade reads its configuration from the folder of the
# program it attaches to; see neural_stack.py.
#
# The fast engine, lens-fast.exe, is the lens's own C++ program for a
# fullscreen lens. This spec builds it first with fast_engine\build.cmd, which
# needs MSVC and the Windows SDK from Visual Studio 2022 or later or its Build
# Tools, and stops when that build fails, so no release goes out without it.
# It goes into a fast folder beside NeuralLens.exe, which is where the
# installed lens looks for it (_find_fast_exe in neural_lens.py).
#
# From the repository root:
#   python -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work installer\NeuralLens.spec
import os
import shutil
import subprocess

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "neural-lens.ico")
EXCLUDES = ["charset_normalizer"]      # an optional import of numpy's f2py that nothing uses
FAST_DIR = os.path.join(ROOT, "fast_engine")
FAST_EXE = os.path.join(FAST_DIR, "bin", "lens-fast.exe")

# the fast engine, built before anything else so a failed build costs no time.
# build.cmd is run from its own folder, so the path needs no quoting for cmd, and
# as .\build.cmd, since cmd does not look in the current folder for a program
# where NoDefaultCurrentDirectoryInExePath is set.
built = subprocess.run(["cmd.exe", "/d", "/c", ".\\build.cmd", "all"], cwd=FAST_DIR)
if built.returncode != 0 or not os.path.isfile(FAST_EXE):
    raise SystemExit("fast_engine\\build.cmd did not build lens-fast.exe (exit code %d). Its output is "
                     "above. The release needs the fast engine." % built.returncode)

# the lens: Tk, the stack setup, and nothing of the capture or Vulkan side. The
# fonts of its looks go into the bundle's assets beside the icon, in
# _internal\assets\fonts with FONTS.txt, see lens_look\fonts.py
lens = Analysis(
    [os.path.join(ROOT, "neural_lens.py")],
    pathex=[ROOT],
    datas=[(ICON, "assets"), (os.path.join(ROOT, "assets", "fonts"), "assets/fonts")],
    hiddenimports=["neural_stack"],
    excludes=EXCLUDES,
)

# the presenter: capture, numpy, glfw and the Vulkan binding. glfw finds its DLL
# beside its own package, which collect_all keeps; the Vulkan binding is cffi
# in ABI mode and loads the system's vulkan-1.dll. copy_metadata carries
# OpenCV's and cffi's licence texts, which their hooks leave out.
datas = copy_metadata("opencv-python") + copy_metadata("cffi")
binaries = []
hidden = ["_cffi_backend"]
for package in ("windows_capture", "glfw", "vulkan"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hidden += h
presenter = Analysis(
    [os.path.join(ROOT, "lens_presenter.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=EXCLUDES + ["tkinter"],
)

lens_exe = EXE(
    PYZ(lens.pure),
    lens.scripts,
    [],
    exclude_binaries=True,
    name="NeuralLens",
    console=False,
    upx=False,
    icon=[ICON],
)
presenter_exe = EXE(
    PYZ(presenter.pure),
    presenter.scripts,
    [],
    exclude_binaries=True,
    name="lens-presenter",
    console=False,
    upx=False,
    icon=[ICON],
)
COLLECT(
    lens_exe, lens.binaries, lens.datas,
    presenter_exe, presenter.binaries, presenter.datas,
    upx=False,
    name="NeuralLens",
)

# The fast engine beside the lens. COLLECT has written the folder by now, and a
# file it collected would land in _internal, where the lens does not look, so
# the engine is copied in after it. It runs once with --help from there, which
# opens no window, to show that the copy that ships starts.
fast_out = os.path.join(DISTPATH, "NeuralLens", "fast")
os.makedirs(fast_out, exist_ok=True)
shipped = shutil.copy2(FAST_EXE, os.path.join(fast_out, "lens-fast.exe"))
helped = subprocess.run([shipped, "--help"], capture_output=True, text=True, timeout=60)
if helped.returncode != 0 or "lens-fast" not in helped.stdout:
    raise SystemExit("%s --help gave exit code %d and printed:\n%s%s"
                     % (shipped, helped.returncode, helped.stdout, helped.stderr))
print("fast engine: %s" % helped.stdout.splitlines()[0])
