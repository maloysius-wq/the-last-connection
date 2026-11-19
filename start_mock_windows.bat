@echo off
cd /d "%~dp0"
echo The Last Connection - scripted demo mode (NO LLM)
python -m ai_bridge.server --mock
pause
