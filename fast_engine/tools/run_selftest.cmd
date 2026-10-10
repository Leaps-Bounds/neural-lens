@echo off
rem run_selftest.cmd: the fast engine's self test and its scoring in one go.
rem
rem Run it as:   cmd /c "C:\...\fast_engine\tools\run_selftest.cmd [OUTDIR] [ENGINE ARGUMENTS]"
rem
rem bin\lens-fast.exe --selftest renders docs\images\blender-before.png against the stack copy
rem in fast_engine\test-stack, and tools\score_selftest.py --check scores the pictures: change
rem 3.21, edge 270, and on an RTX 5090 the network at most 3.6 ms. Where the reference
rem pictures of the first test program are at hand it also compares with them byte for byte,
rem and says so when they are not, and the same with the baseline run kept under _harnesses.
rem --shared runs the shared mode's reference (two passes through one feature) against its
rem own baseline, and --both runs the two in turn. Build the exe first with build.cmd all.
rem The work is in run_selftest.py next to this file, which waits for a quiet card before it
rem runs, and for the measuring lock where the project's other measuring tools are, see there.
rem
rem Exit code: 0 within the targets, 1 a score is off or a file differs from the baseline's,
rem 2 the engine failed, 3 the lock never went or could not be made, 4 the card stayed busy,
rem 5 no Python or no engine.

setlocal
where python >nul 2>&1
if errorlevel 1 (
  echo run_selftest.cmd: python is not on the path
  exit /b 5
)
if not exist "%~dp0..\bin\lens-fast.exe" (
  echo run_selftest.cmd: no bin\lens-fast.exe, run build.cmd all first
  exit /b 5
)
python "%~dp0run_selftest.py" %*
exit /b %ERRORLEVEL%
