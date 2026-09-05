@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_a_5sep.ps1
echo.
echo (log: claude\reports\RUN_A_5SEP_launcher.log)
pause
