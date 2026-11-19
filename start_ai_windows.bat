@echo off
cd /d "%~dp0"
echo The Last Connection - local AI bridge
python -m ai_bridge.server
pause
