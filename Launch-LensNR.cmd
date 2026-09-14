@echo off
setlocal
rem ---------------------------------------------------------------
rem  DLSS 5 Neural Lens, run from source
rem
rem  Runs from wherever this folder lives. The Neural Rendering stack
rem  comes from neural_stack.py, which assembles it in a "stack" folder
rem  beside this script, where the lens finds it:
rem    python neural_stack.py
rem
rem  A stack somewhere else can be named with any of:
rem    Launch-LensNR.cmd --stack-dir "D:\path\to\stack"
rem    set NEURAL_LENS_STACK=D:\path\to\stack
rem    copy neural-lens.ini.example to neural-lens.ini, set stack_dir
rem
rem  Requires Python 3 with tkinter, and these packages:
rem    pip install numpy windows-capture glfw vulkan
rem
rem  The lens runs without a console. Everything it prints goes to
rem  data\logs\lens.log beside this script, and anything that stops it
rem  from starting is shown as a dialog. To run it with a console:
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
