@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -B persistent_auto_load.py --disable
pause
