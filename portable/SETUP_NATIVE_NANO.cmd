@echo off
cd /d "%~dp0"
echo Native Chatterbox Nano Q8 CPU engine (about 650 MB download).
echo Close the game first. This will not replace your existing voice engines.
choice /C YN /M "Install and test native Nano"
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_native_nano.ps1"
if errorlevel 1 echo Native setup failed. Existing Nano and Piper remain available.
pause
