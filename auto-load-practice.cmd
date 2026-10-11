@echo off
setlocal
cd /d "%~dp0"
echo Experimental KK practice runtime loader.
echo Watches the NEXT new KK game. After connection the bot starts PAUSED.
echo Windows will request administrator permission for the background helper.
echo Stop with: bot.py auto-load-stop
.venv\Scripts\python.exe -u -B auto_load_entry.py
pause
