@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_floor_5sep.ps1
echo.
echo (log: claude\reports\FLOOR_5SEP_launcher.log)
pause
