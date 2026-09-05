@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File tools\commit_plan_contract_5sep.ps1
echo.
echo (log: claude\reports\PLAN_CONTRACT_5SEP_launcher.log)
pause
