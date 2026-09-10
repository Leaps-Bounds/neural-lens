@echo off
setlocal enabledelayedexpansion
rem ---------------------------------------------------------------
rem  Screen -> DLSS 5 Neural Rendering, live.
rem
rem  Desktop Duplication (GPU-native, zero-copy into NVENC) -> pipe
rem  -> mpv, whose NR stack (ReShade Vulkan layer + dlss5-feed +
rem  renodx-dlss5) applies Neural Rendering.
rem
rem  Captures the LEFT of the panel, shows the result on the RIGHT,
rem  so it never captures itself and you get a live side-by-side.
rem
rem  RESIZING: press Ctrl+Alt+R. A translucent outline appears over
rem  the NR window -- drag its edges, let go, confirm, and it
rem  relaunches at that size. It cannot resize live: a resize
rem  recreates the swapchain, forcing the NR add-on to release the
rem  DLSS feature -> 0xC0000005. Same defect as the exit crash.
rem
rem  Usage:  Launch-ScreenNR-Demo.cmd         2x magnify demo
rem          Launch-ScreenNR-Demo.cmd half    1:1 half-screen
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
set "STATE=C:\Games\_screennr-demo-state.txt"

rem --- capture region (from top-left of the panel) ---
set "SRC=1536x1280"
set "OX=0"
set "OY=0"
if /i "%~1"=="half" set "SRC=3072x2560"

rem --- output window geometry: remembered from the last resize, else default
set "OW=3072"
set "OH=2560"
set "OPX=3072"
set "OPY=0"
if exist "%STATE%" for /f "tokens=1-4" %%a in ('type "%STATE%"') do (
  set "OW=%%a"
  set "OH=%%b"
  set "OPX=%%c"
  set "OPY=%%d"
)

:relaunch
if exist "%STATE%.restart" del "%STATE%.restart" >nul 2>&1

set "ENC=-c:v h264_nvenc -preset p1 -tune ull -bf 0 -g 60 -forced-idr 1 -rc constqp -qp 12"
set "MPVARGS=--geometry=!OW!x!OH!+!OPX!+!OPY! --hidpi-window-scale=no --no-border --no-osc --force-window=immediate --keep-open=yes --cache=no --demuxer-lavf-o=fflags=+nobuffer+flush_packets --demuxer-max-bytes=2MiB --title=ScreenNR"

echo.
echo   source : %SRC% at (%OX%,%OY%)   [top-left of the panel]
echo   output : !OW!x!OH! at (!OPX!,!OPY!)
echo   Ctrl+Alt+R to resize   -   q in the NR window to stop
echo.

start "" /b python "C:\Games\_screennr-resize.py" ScreenNR "%STATE%"

cd /d "C:\Games\_mpv"
"%FF%" -hide_banner -loglevel warning -init_hw_device d3d11va -filter_complex "ddagrab=output_idx=0:framerate=60:video_size=%SRC%:offset_x=%OX%:offset_y=%OY%" %ENC% -f mpegts - | "%MPV%" - !MPVARGS!

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
