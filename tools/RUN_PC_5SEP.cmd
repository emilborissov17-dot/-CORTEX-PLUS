@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_pc_5sep.ps1
echo.
echo (log: claude\reports\PC_5SEP_launcher.log)
pause
