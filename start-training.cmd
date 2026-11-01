@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0python\pythonw.exe" (
    echo Please extract the complete dayuan-training package first.
    echo Keep this script inside the dayuan-training folder.
    pause
    exit /b 1
)
start "" "%~dp0python\pythonw.exe" -E -s -X utf8 -B "%~dp0training_launcher.py"
exit /b 0
