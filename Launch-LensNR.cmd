@echo off
setlocal
rem ---------------------------------------------------------------
rem  DLSS 5 Neural Lens
rem
rem  Runs from wherever this folder lives. Point it at your mpv
rem  install (the one carrying the DLSS 5 Neural Rendering stack)
rem  with any of:
rem
rem    Launch-LensNR.cmd --mpv-dir "D:\path\to\mpv"
rem    set NEURAL_LENS_MPV_DIR=D:\path\to\mpv
rem    copy neural-lens.ini.example to neural-lens.ini, set mpv_dir
rem    or put an "mpv" folder beside this script
rem
rem  Requires python 3 with numpy and windows-capture:
rem    pip install numpy windows-capture
rem ---------------------------------------------------------------

where python >nul 2>&1
if errorlevel 1 (
  echo   python was not found on PATH. Install Python 3 and try again.
  pause
  exit /b 1
)

echo.
echo   DLSS 5 Neural Lens
echo   drag the title bar to move it. The X closes it.
echo.

python "%~dp0neural_lens.py" %*

endlocal
