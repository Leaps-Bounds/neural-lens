@echo off
setlocal enabledelayedexpansion
rem ---------------------------------------------------------------
rem  Phone screen -> DLSS 5 Neural Rendering.
rem
rem  Keeps scrcpy for CONTROL (taps, keyboard, clipboard, audio, no
rem  180s limit) and captures its client area for NR. You drive the
rem  scrcpy window; the neural-rendered copy renders beside it.
rem
rem  Start scrcpy FIRST, then run this.
rem
rem  RESIZING: press Ctrl+Alt+R. A translucent outline appears over
rem  the NR window -- drag its edges to any size, let go, and confirm.
rem  It relaunches at the new size. The window cannot resize live: a
rem  resize recreates the swapchain, which forces the NR add-on to
rem  release the DLSS feature -> 0xC0000005. Same defect as the exit
rem  crash. Restarting is the only safe path.
rem
rem  NOTE 1: the ffmpeg | mpv pipeline MUST stay on ONE physical line.
rem          With ^ continuation cmd eats the | and hands mpv's args
rem          to ffmpeg.
rem  NOTE 2: h264, NOT hevc -- hevc_nvenc -tune ull emits a stream mpv
rem          cannot sync to.
rem  NOTE 3: ddagrab REQUIRES -init_hw_device d3d11va.
rem  NOTE 4: NEVER add --untimed. It makes mpv present as fast as it
rem          can instead of on frame arrival, so the same frame is
rem          re-presented dozens of times; ReShade fires on every
rem          present and NR re-processes its OWN output each time ->
rem          the runaway loop that collapses the image to a blob.
rem ---------------------------------------------------------------

set "DISABLE_DLSS5_VK_BRIDGE=1"
set "FF=C:\Users\jx\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"
set "MPV=C:\Games\_mpv\mpv.exe"
set "STATE=C:\Games\_screennr-state.txt"
set "WIN=SDL_app"
if not "%~1"=="" set "WIN=%~1"

rem --- output window geometry: remembered from the last resize, else default
set "OW=3000"
set "OH=2500"
set "OPX=3112"
set "OPY=0"
if exist "%STATE%" for /f "tokens=1-4" %%a in ('type "%STATE%"') do (
  set "OW=%%a"
  set "OH=%%b"
  set "OPX=%%c"
  set "OPY=%%d"
)

:relaunch
if exist "%STATE%.restart" del "%STATE%.restart" >nul 2>&1

rem --- locate scrcpy's client area fresh each time (physical px, even dims) ---
set "SW="
for /f "tokens=1-4" %%a in ('python "C:\Games\_screennr-findwin.py" "%WIN%"') do (
  set "OX=%%a"
  set "OY=%%b"
  set "SW=%%c"
  set "SH=%%d"
)
if not defined SW echo. & echo   ERROR: no window matching "%WIN%" -- start scrcpy first. & echo. & pause & exit /b 1

set "ENC=-c:v h264_nvenc -preset p1 -tune ull -bf 0 -g 60 -forced-idr 1 -rc constqp -qp 12"
set "MPVARGS=--geometry=!OW!x!OH!+!OPX!+!OPY! --hidpi-window-scale=no --no-border --no-osc --force-window=immediate --keep-open=yes --cache=no --demuxer-lavf-o=fflags=+nobuffer+flush_packets --demuxer-max-bytes=2MiB --title=PhoneNR"

echo.
echo   source : !SW!x!SH! at (!OX!,!OY!)   [scrcpy]
echo   output : !OW!x!OH! at (!OPX!,!OPY!)
echo   Ctrl+Alt+R to resize. Press q in the NR window to stop.
echo.

rem --- helper: locks the window against live resize, serves Ctrl+Alt+R ---
start "" /b python "C:\Games\_screennr-resize.py" PhoneNR "%STATE%"

cd /d "C:\Games\_mpv"
"%FF%" -hide_banner -loglevel warning -init_hw_device d3d11va -filter_complex "ddagrab=output_idx=0:framerate=60:video_size=!SW!x!SH!:offset_x=!OX!:offset_y=!OY!" %ENC% -f mpegts - | "%MPV%" - !MPVARGS!

if exist "%STATE%.restart" (
  for /f "tokens=1-4" %%a in ('type "%STATE%"') do (
    set "OW=%%a"
    set "OH=%%b"
    set "OPX=%%c"
    set "OPY=%%d"
  )
  echo.
  echo   restarting at !OW!x!OH! ...
  timeout /t 1 >nul
  goto relaunch
)

echo.
echo   stopped.
pause
endlocal
