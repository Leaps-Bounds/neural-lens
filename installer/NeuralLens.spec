# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the DLSS 5 Neural Lens: two programs in one folder.
#
# NeuralLens.exe is the lens and lens-presenter.exe the presenter it starts,
# sharing one _internal folder. The installed program's folder is also the
# stack folder, because ReShade reads its configuration from the folder of the
# program it attaches to; see neural_stack.py.
#
# From the repository root:
#   python -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work installer\NeuralLens.spec
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "neural-lens.ico")
EXCLUDES = ["charset_normalizer"]      # an optional import of numpy's f2py that nothing uses

# the lens: Tk, the stack setup, and nothing of the capture or Vulkan side
lens = Analysis(
    [os.path.join(ROOT, "neural_lens.py")],
    pathex=[ROOT],
    datas=[(ICON, "assets")],
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
