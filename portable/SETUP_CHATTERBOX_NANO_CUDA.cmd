@echo off
cd /d "%~dp0"
echo Official Chatterbox Nano with PyTorch CUDA 12.4 (experimental).
echo Close the game and GPU-intensive apps. Existing CPU Nano is preserved.
echo Reuses the installed official model. CUDA packages are a large separate download.
echo Keep at least 10 GB free on the game drive.
choice /C YN /M "Install and test CUDA Nano"
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_nano.ps1" -Cuda
if errorlevel 1 echo CUDA setup failed. CPU Nano and Piper remain available. See models\chatterbox-nano\setup-cuda.log.
pause
