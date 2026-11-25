@echo off
cd /d "%~dp0"
echo Experimental native Chatterbox Nano Q8 Vulkan GPU engine.
echo Close The Last Connection and other GPU-intensive apps first.
echo Reuses the verified existing Nano Q8 model; new Vulkan runtime is about 88 MB.
echo If the model is not installed, setup also downloads it (about 616 MB).
echo Your CPU Nano and Piper installations are preserved.
choice /C YN /M "Install and test native Vulkan Nano"
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_native_nano.ps1" -Backend vulkan
if errorlevel 1 echo Vulkan setup failed. Existing voice engines remain available. See setup-server-vulkan-error.log and devices-vulkan-error.log.
pause
