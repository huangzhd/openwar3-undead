@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -B install_auto_takeover.py
pause
