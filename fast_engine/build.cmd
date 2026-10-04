@echo off
rem build.cmd: builds the fast engine with MSVC and the Windows SDK, as they come with Visual
rem Studio 2022 or later, the full edition or its Build Tools. It has been built with MSVC
rem 14.44 from Build Tools 2022 and Windows SDK 10.0.26100.
rem
rem Run it as:   cmd /c "C:\...\fast_engine\build.cmd TARGET"
rem
rem   all           bin\lens-fast.exe: main.cpp and every module in src except the two
rem                 *_main.cpp files. The default target. A windowed program with a wmain
rem                 entry, so no console window opens when the lens starts it, while stdin,
rem                 stdout and stderr still work through the pipes the lens hands it.
rem   selftest      bin\lens-fast-selftest.exe, a console program:
rem                 selftest_main, selftest, pipeline, nr, gpu, common
rem   capturetest   bin\lens-fast-capturetest.exe, a console program:
rem                 capturetest_main, capturetest, capture, common
rem   check FILE    compiles that one source in a folder of its own, keeps nothing and links
rem                 nothing. FILE is a name in src, as in: check window.cpp
rem
rem Each target has its own object folder, build\TARGET, so two targets can be built at the
rem same moment by different people. Two builds of the same target take turns: the second
rem waits for the first, and takes a lock over when it is older than 90 seconds, which is
rem what a build that was killed leaves behind.
rem
rem Before anything is compiled, every src\shaders\*.hlsl goes through fxc into
rem build\shaders\NAME.h, a byte array named g_NAME. The entry point is main and the profile
rem comes from the end of the name: _cs is cs_5_0, _vs is vs_5_0, _ps is ps_5_0. Each header
rem is made in a folder of this build's own and only then moved into place, and not at all
rem when it would not change, so a build running at the same moment never reads half a file
rem and an unchanged shader never touches a header someone is reading. Sources include them
rem by bare name, as in: #include "downscale_cs.h". The arrays are BYTE, so windows.h comes
rem first.
rem
rem Flags: /std:c++20 /O2 /MT /EHsc /W3. The C runtime is linked statically because the
rem installed lens ships no MSVC runtime DLLs. A module that needs a system library the list
rem below does not have names it in its own source with #pragma comment(lib, "name.lib").
rem
rem The compiler comes from the vcvars64.bat of a Visual Studio with the workload "Desktop
rem development with C++". The first of these that exists is used:
rem   1. the vcvars64.bat that LENS_FAST_VCVARS names, for an install in a place of its own
rem   2. the newest instance with the x64 compiler that vswhere.exe reports. vswhere comes
rem      with the Visual Studio Installer, always in the same folder.
rem   3. the default folders of Visual Studio 2022 and of 2026, whose folder is named 18,
rem      every edition and the Build Tools
rem The Windows SDK has to be 10.0.26100 or later, because the capture sets the session's
rem MinUpdateInterval, which older SDKs do not have.
rem
rem Exit code: 0 built, 1 a step failed (the first error stops the build), 2 a bad command line.

setlocal EnableExtensions
set "ROOT=%~dp0"
set "TARGET=%~1"
set "ARG=%~2"
set "ARG_FULL=%~f2"
if "%TARGET%"=="" set "TARGET=all"

set "KNOWN="
for %%T in (all selftest capturetest check) do if /i "%TARGET%"=="%%T" set "KNOWN=%%T"
if not defined KNOWN goto :bad_target
set "TARGET=%KNOWN%"

cd /d "%ROOT%"
if errorlevel 1 goto :no_root

call :find_vcvars
if not defined VCVARS goto :no_vcvars
rem vcvars prints a banner, and a complaint about vswhere.exe that means nothing here
call "%VCVARS%" >nul 2>&1
where cl.exe >nul 2>&1
if errorlevel 1 goto :no_cl
where fxc.exe >nul 2>&1
if errorlevel 1 goto :no_fxc
call :check_sdk
if errorlevel 1 goto :old_sdk

setlocal EnableDelayedExpansion

set "CFLAGS=/nologo /std:c++20 /O2 /MT /EHsc /W3 /utf-8 /MP /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS /Isrc /Ibuild\shaders"
rem kernel32 and user32 come before windowsapp so the classic imports stay with the classic
rem DLLs: windowsapp.lib, which C++/WinRT needs, would otherwise answer for them first
set "LIBS=kernel32.lib user32.lib gdi32.lib advapi32.lib ole32.lib d3d12.lib dxgi.lib d3d11.lib dcomp.lib windowscodecs.lib windowsapp.lib"
set "LFLAGS=/nologo /INCREMENTAL:NO /MANIFEST:EMBED /ENTRY:wmainCRTStartup"

rem The work is a subroutine so that every way out of it passes the two lines after the
rem call, which give back this build's own folder and its lock.
set "WORK="
set "HELD="
call :build
set "RC=%ERRORLEVEL%"
if defined WORK rmdir /s /q "%WORK%" 2>nul
if defined HELD rmdir "%LOCK%" 2>nul
exit /b %RC%

:build
mkdir build 2>nul
mkdir build\shaders 2>nul
if not exist build\shaders\ goto :no_build_dir

rem A folder of this build's own for what is not finished yet. mkdir either makes it or
rem fails, so two builds never share one. The name cannot simply be a random number: cmd
rem seeds RANDOM from the clock, and two builds started in the same second draw the same
rem numbers. The one that loses the mkdir draws again.
set /a TRIES=0
:work_dir
set "WORK=build\tmp.%RANDOM%%RANDOM%"
mkdir "%WORK%" 2>nul
if not errorlevel 1 goto :work_ready
set /a TRIES+=1
if %TRIES% lss 100 goto :work_dir
set "WORK="
goto :no_build_dir
:work_ready

rem ---- shaders
set /a SHADERS=0
for %%F in (src\shaders\*.hlsl) do (
  call :shader "%%F"
  if errorlevel 1 exit /b 1
  set /a SHADERS+=1
)

rem ---- check: one source, no link
if "%TARGET%"=="check" goto :check

rem ---- the three programs
if "%TARGET%"=="selftest" (
  set "EXE=bin\lens-fast-selftest.exe"
  set "SUBSYSTEM=CONSOLE"
  set "SRCS=src\selftest_main.cpp src\selftest.cpp src\pipeline.cpp src\nr.cpp src\gpu.cpp src\common.cpp"
)
if "%TARGET%"=="capturetest" (
  set "EXE=bin\lens-fast-capturetest.exe"
  set "SUBSYSTEM=CONSOLE"
  set "SRCS=src\capturetest_main.cpp src\capturetest.cpp src\capture.cpp src\common.cpp"
)
if "%TARGET%"=="all" (
  set "EXE=bin\lens-fast.exe"
  set "SUBSYSTEM=WINDOWS"
  set "SRCS="
  for %%F in (src\*.cpp) do (
    set "N=%%~nF"
    if /i not "!N:~-5!"=="_main" set "SRCS=!SRCS! %%F"
  )
)
if not defined SRCS goto :no_sources
set "OBJ=build\%TARGET%"
mkdir "%OBJ%" 2>nul
mkdir bin 2>nul
if not exist "%OBJ%\" goto :no_build_dir
if not exist bin\ goto :no_build_dir

set "LOCK=build\%TARGET%.lock"
set /a WAITED=0
:lock_wait
mkdir "%LOCK%" 2>nul
if not errorlevel 1 goto :lock_held
if %WAITED% equ 0 echo build.cmd: another %TARGET% build is running, waiting for it
if %WAITED% geq 90 (
  echo build.cmd: the lock %LOCK% is older than 90 seconds, taking it over
  goto :lock_held
)
ping -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto :lock_wait
:lock_held
set "HELD=1"

cl %CFLAGS% /Fo%OBJ%\ /Fe%EXE% %SRCS% /link %LFLAGS% /SUBSYSTEM:%SUBSYSTEM% %LIBS%
if errorlevel 1 (
  echo build.cmd: the %TARGET% build failed
  exit /b 1
)
echo build.cmd: built %EXE% ^(%SHADERS% shaders^)
exit /b 0

:check
if "%ARG%"=="" goto :no_check_file
set "FILE="
if exist "src\%ARG%" set "FILE=src\%ARG%"
if not defined FILE if exist "%ARG%" set "FILE=%ARG%"
if not defined FILE if exist "%ARG_FULL%" set "FILE=%ARG_FULL%"
if not defined FILE goto :no_such_file
rem The object goes into this run's own folder, which the way out removes: two checks of one
rem file at the same moment would otherwise write the same object, and the second would be
rem told the file does not compile.
cl %CFLAGS% /c /Fo%WORK%\ "%FILE%"
if errorlevel 1 (
  echo build.cmd: %FILE% does not compile
  exit /b 1
)
echo build.cmd: %FILE% compiles
exit /b 0

rem ---- one shader: src\shaders\NAME.hlsl into build\shaders\NAME.h
:shader
set "SRC=%~1"
set "NAME=%~n1"
set "PROFILE="
if /i "%NAME:~-3%"=="_cs" set "PROFILE=cs_5_0"
if /i "%NAME:~-3%"=="_vs" set "PROFILE=vs_5_0"
if /i "%NAME:~-3%"=="_ps" set "PROFILE=ps_5_0"
if not defined PROFILE (
  echo build.cmd: %SRC%: a shader's name must end in _cs, _vs or _ps
  exit /b 1
)
set "OUT=build\shaders\%NAME%.h"
set "NEW=%WORK%\%NAME%.h"
set "LOG=%WORK%\%NAME%.log"
fxc.exe /nologo /T %PROFILE% /E main /O3 /Vn g_%NAME% /Fh "%NEW%" "%SRC%" >"%LOG%" 2>&1
if errorlevel 1 (
  type "%LOG%"
  echo build.cmd: fxc failed on %SRC%
  exit /b 1
)
findstr /i /c:"warning" "%LOG%"
set /a PLACE_TRIES=0
:shader_place
if exist "%OUT%" (
  fc /b "%NEW%" "%OUT%" >nul 2>&1
  if not errorlevel 1 exit /b 0
)
move /y "%NEW%" "%OUT%" >nul 2>&1
if not errorlevel 1 exit /b 0
rem The header is open in a compiler of another build. Wait and look again: by then that
rem build may have put the same header there itself.
set /a PLACE_TRIES+=1
if %PLACE_TRIES% geq 15 (
  echo build.cmd: could not replace %OUT%, another program holds it open
  exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto :shader_place

rem ---- the compiler: VCVARS is the vcvars64.bat to use, or undefined when none was found
:find_vcvars
set "VCVARS="
if not defined LENS_FAST_VCVARS goto :find_vswhere
if exist "%LENS_FAST_VCVARS%" set "VCVARS=%LENS_FAST_VCVARS%"
if defined VCVARS exit /b 0
echo build.cmd: LENS_FAST_VCVARS names "%LENS_FAST_VCVARS%", which does not exist, so it is not used
:find_vswhere
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto :find_folders
for /f "usebackq delims=" %%P in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
  if exist "%%P\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%P\VC\Auxiliary\Build\vcvars64.bat"
)
if defined VCVARS exit /b 0
:find_folders
for %%R in ("%ProgramFiles%" "%ProgramFiles(x86)%") do for %%V in (18 2022) do for %%E in (Enterprise Professional Community BuildTools) do (
  if not defined VCVARS if exist "%%~R\Microsoft Visual Studio\%%V\%%E\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%~R\Microsoft Visual Studio\%%V\%%E\VC\Auxiliary\Build\vcvars64.bat"
)
exit /b 0

rem ---- the Windows SDK that vcvars chose, the newest installed: 1 when it is older than 26100.
rem vcvars sets WindowsSDKVersion as in 10.0.26100.0\ and the third number is the build.
:check_sdk
set "SDKBUILD="
for /f "tokens=3 delims=." %%B in ("%WindowsSDKVersion%") do set "SDKBUILD=%%B"
if not defined SDKBUILD exit /b 0
if %SDKBUILD% lss 26100 exit /b 1
exit /b 0

:bad_target
echo build.cmd: unknown target "%TARGET%". The targets are: all, selftest, capturetest, check FILE.cpp
exit /b 2

:no_check_file
echo build.cmd: check needs a source file, as in: build.cmd check window.cpp
exit /b 2

:no_such_file
echo build.cmd: no such source: "%ARG%" ^(looked in src, in fast_engine and at the path as given^)
exit /b 2

:no_root
echo build.cmd: cannot enter "%ROOT%"
exit /b 1

:no_vcvars
echo build.cmd: no C++ compiler was found. The engine is built with MSVC and the Windows SDK,
echo which come with Visual Studio 2022 or later, or with its Build Tools, when the workload
echo "Desktop development with C++" is installed. Install one of them and run build.cmd again,
echo or set LENS_FAST_VCVARS to the full path of a vcvars64.bat. A lens run from source works
echo without the engine and draws fullscreen with the ReShade engine.
exit /b 1

:old_sdk
echo build.cmd: the engine needs Windows SDK 10.0.26100 or later, and the newest one installed
echo is %WindowsSDKVersion:~0,-1%. The Visual Studio Installer adds a newer one under Individual components.
exit /b 1

:no_cl
echo build.cmd: cl.exe is not on the path after "%VCVARS%"
exit /b 1

:no_fxc
echo build.cmd: fxc.exe is not on the path after "%VCVARS%", so the Windows SDK is missing.
echo The Visual Studio Installer adds it under Individual components.
exit /b 1

:no_build_dir
echo build.cmd: could not create the build folders under "%ROOT%"
exit /b 1

:no_sources
echo build.cmd: no sources found for %TARGET%
exit /b 1
