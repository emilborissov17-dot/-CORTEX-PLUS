@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File tools\commit_intake_5sep.ps1
echo.
echo (log: claude\reports\INTAKE_5SEP_launcher.log)
pause
