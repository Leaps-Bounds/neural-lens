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
rem
rem  The lens runs without a console. Everything it prints goes to
rem  %LOCALAPPDATA%\NeuralLens\logs\lens.log, and anything that stops it
rem  from starting is shown as a dialog. To run it with a console instead,
rem  for example to watch the rate decisions live:
rem    python neural_lens.py
rem ---------------------------------------------------------------

where pythonw >nul 2>&1
if errorlevel 1 (
  echo   pythonw was not found on PATH. Install Python 3 and try again.
  pause
  exit /b 1
)

start "" pythonw "%~dp0neural_lens.py" %*

endlocal
