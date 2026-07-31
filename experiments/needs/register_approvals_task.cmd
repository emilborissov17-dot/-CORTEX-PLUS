@echo off
REM ====================================================================
REM  CORTEX_Approvals — one-time setup.
REM  Registers a scheduled task that checks your Telegram "OK <id>"
REM  replies every 1 minute and applies them, HIDDEN (no popup window).
REM  After this you never touch PowerShell for approvals again:
REM  press OK in Telegram -> it acts within ~1 minute.
REM  Double-click this file ONCE. If it says access denied, right-click
REM  -> Run as administrator.
REM ====================================================================

schtasks /Create /TN "CORTEX_Approvals" /SC MINUTE /MO 1 /F /TR "wscript.exe C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\experiments\needs\run_approvals.vbs"

if %errorlevel%==0 (
  echo.
  echo   OK - CORTEX_Approvals is live. Press OK in Telegram; it applies within ~1 min.
  echo   To stop it later:  schtasks /Delete /TN "CORTEX_Approvals" /F
) else (
  echo.
  echo   Could not register. Right-click this file and choose "Run as administrator", then try again.
)
echo.
pause
