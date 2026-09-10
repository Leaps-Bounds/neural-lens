@echo off
rem Copy the app files to C:\Games, where the launchers expect them.
copy /Y "%~dp0Launch-LensNR.cmd"        C:\Games\ >nul
copy /Y "%~dp0Launch-ScreenNR-Demo.cmd" C:\Games\ >nul
copy /Y "%~dp0Launch-PhoneNR.cmd"       C:\Games\ >nul
copy /Y "%~dp0_screennr-lens3.py"       C:\Games\ >nul
copy /Y "%~dp0_screennr-resize.py"      C:\Games\ >nul
copy /Y "%~dp0_screennr-findwin.py"     C:\Games\ >nul
echo deployed to C:\Games
