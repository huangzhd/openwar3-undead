@echo off
setlocal
cd /d "%~dp0"
:menu
echo.
echo OpenWar3AI attach controls (existing bridge required)
echo 1. Scan game processes
echo 2. Show connection command (starts paused)
echo 3. Resume bot
echo 4. Pause bot
echo 5. Release bot (keep game open)
echo 6. Status
echo 0. Exit this menu
choice /c 1234560 /n /m "Select: "
if errorlevel 7 exit /b
if errorlevel 6 goto status
if errorlevel 5 goto release
if errorlevel 4 goto pausebot
if errorlevel 3 goto resume
if errorlevel 2 goto attach
.venv\Scripts\python.exe -B bot.py attach-check
goto menu
:attach
echo Use a separate terminal to run: .venv\Scripts\python.exe -u -B bot.py attach --pid GAME_PID --enemy-race 3
echo This menu remains available for pause / resume / release.
goto menu
:resume
.venv\Scripts\python.exe -B bot.py attach-resume
goto menu
:pausebot
.venv\Scripts\python.exe -B bot.py attach-pause
goto menu
:release
.venv\Scripts\python.exe -B bot.py attach-release
goto menu
:status
.venv\Scripts\python.exe -B bot.py attach-status
goto menu
