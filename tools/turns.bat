@echo off
rem tools/turns.bat - start the turns loop (C-TURN-1 Part 5, Emil R31): the brain's
rem turn and the agents' turn alternate by baton (scripts/turns_loop.py, core/turn.py).
rem
rem Detached through tools/launch_detached.ps1, because a long job started by a
rem harness or a tick is killed with it. scripts/turns_loop.py keeps one loop at a
rem time (memory/turns_loop.pid), so starting it twice is harmless.
rem
rem   stop:   venv\Scripts\python.exe scripts\turns_loop.py --stop
rem   state:  venv\Scripts\python.exe -m core.turn
rem
rem Started at logon by the scheduled task CORTEX_Turns.
cd /d "%~dp0.."
rem 5 Oct 2026: a test switch set in this window reaches every turn. Refuse, and say so here.
if defined CORTEX_NO_REAL_MODEL (echo REFUSED: CORTEX_NO_REAL_MODEL is set in this window - every turn would inherit it. Open a new window. & exit /b 4)
if defined CONTROL_NO_TELEGRAM (echo REFUSED: CONTROL_NO_TELEGRAM is set in this window - every turn would inherit it. Open a new window. & exit /b 4)
powershell -NoProfile -ExecutionPolicy Bypass -File tools\launch_detached.ps1 -Exe venv\Scripts\python.exe -Arguments "scripts\turns_loop.py" -Log logs\turns\turns_loop.log
