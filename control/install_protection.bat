@echo off
REM ===========================================================================================
REM CORTEX++ - STEP 4: LOCK THE CONTROL (Kimi R72 Q1). Right click -> "Run as administrator".
REM Shown to Kimi before it is run. What it does, in order:
REM  1. C:\ProgramData\CORTEX_control : administrators and SYSTEM write, your user only reads.
REM     The nightly reviewer is copied there, so the copy that runs cannot be edited by Claude Code.
REM  2. Makes read-only for your user (Claude Code runs as you): the folder control\ (gate, list, seal),
REM     the folder .git\hooks\ (the commit/push gate) and the file .claude\settings.json (the tool gate).
REM  3. Records the hashes and the permissions of those files there (reviewer_seal.json).
REM  4. Registers the task CORTEX_ControlReviewer: runs as SYSTEM every day at 07:30 and wakes the PC.
REM  5. Runs the reviewer once now: the first daily "alive" message comes to Telegram.
REM NOT HERE: the firewall (C-CONTROL-3, after Kimi answers how Telegram/GitHub/pip pass it).
REM Undo: an administrator runs  icacls <path> /reset /T  on the three paths and deletes the task.
REM ===========================================================================================
chcp 65001 >nul
net session >nul 2>&1 || (echo This file must be run as administrator. & pause & exit /b 1)
set "REPO=C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
set "CH=C:\ProgramData\CORTEX_control"
set "U=EMILIO-LAPTOP\emilb"
if not exist "%REPO%\control\gate.py" (echo control\gate.py not found - C-CONTROL-1 is not installed. & pause & exit /b 1)

echo [1/5] %CH%
if not exist "%CH%" mkdir "%CH%" || goto :fail
icacls "%CH%" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "%U%:(OI)(CI)RX" >nul || goto :fail
copy /Y "%REPO%\control\nightly_reviewer.ps1" "%CH%\nightly_reviewer.ps1" >nul || goto :fail

echo [2/5] read-only for %U%: control\  .git\hooks\  .claude\settings.json
icacls "%REPO%\control" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "%U%:(OI)(CI)RX" /T >nul || goto :fail
icacls "%REPO%\.git\hooks" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "%U%:(OI)(CI)RX" /T >nul || goto :fail
icacls "%REPO%\.claude\settings.json" /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" "%U%:R" >nul || goto :fail

echo [3/5] seal
powershell -NoProfile -ExecutionPolicy Bypass -File "%CH%\nightly_reviewer.ps1" -Seal || goto :fail

echo [4/5] task CORTEX_ControlReviewer (SYSTEM, daily 07:30, wakes the PC)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\CORTEX_control\nightly_reviewer.ps1'; $t=New-ScheduledTaskTrigger -Daily -At 07:30; $s=New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15); Register-ScheduledTask -TaskName 'CORTEX_ControlReviewer' -Action $a -Trigger $t -Settings $s -User 'SYSTEM' -RunLevel Highest -Force | Out-Null" || goto :fail

echo [5/5] first review - watch Telegram for the first daily "alive" message
powershell -NoProfile -ExecutionPolicy Bypass -File "%CH%\nightly_reviewer.ps1"
echo.
echo DONE. Results: %CH%\review_*.json
pause
exit /b 0

:fail
echo.
echo FAILED at the step above. Nothing after it was done. Send a photo of this window to Claude.
pause
exit /b 1
