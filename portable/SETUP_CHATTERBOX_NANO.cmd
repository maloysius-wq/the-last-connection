@echo off
cd /d "%~dp0"
echo Chatterbox Nano is optional. Setup downloads several GB to this game drive.
echo No cloud speech service or subscription is used.
choice /C YN /M "Install the local Nano voice engine"
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_nano.ps1"
if errorlevel 1 echo Setup failed. Piper remains available. Check the error above.
pause
