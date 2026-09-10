@echo off
setlocal
rem ---------------------------------------------------------------
rem  DLSS 5 Neural Lens (v3): a floating see-through NR window.
rem
rem  Drag it by the title bar. Whatever is behind it gets neural-
rem  rendered inside it. The viewport is click-through: the mouse
rem  reaches the desktop underneath, like Windows Magnifier. Close
rem  with the X (the viewport can never take keyboard focus).
rem
rem  Pipeline (each stage was measured before it was built):
rem    Magnification API host window under the lens, with our own
rem    windows on its EXCLUDE list  ->  Windows.Graphics.Capture of
rem    that host by HWND (works while occluded; Desktop Duplication
rem    does not)  ->  raw BGRA into mpv's stdin (no ffmpeg at all)
rem    ->  ReShade + dlss5-feed + renodx-dlss5 = NR, drawn on top.
rem
rem  Moving never restarts anything. RESIZING is not possible while
rem  running (swapchain recreate -> NR add-on releases the DLSS
rem  feature -> 0xC0000005). To change size: close, edit the first
rem  line of the state file (W H X Y), relaunch.
rem
rem  Requires: python 3.12 with numpy + windows-capture
rem            (pip install windows-capture)
rem ---------------------------------------------------------------

set "STATE=C:\Games\_screennr-lens-state.txt"

echo.
echo   DLSS 5 Neural Lens
echo   drag the title bar to move it. The X closes it.
echo.

python "C:\Games\_screennr-lens3.py" "%STATE%"

echo.
echo   stopped.
endlocal
