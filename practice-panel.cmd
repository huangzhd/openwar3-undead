@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo 未找到项目 Python 环境，请先完成项目安装。
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -B "%~dp0practice_panel.py"
exit /b 0
