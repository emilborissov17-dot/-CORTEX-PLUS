@echo off
REM ====================================================================
REM  CORTEX_Collector — one-time setup (#44).
REM  Registers a scheduled task that runs the independent sensing layer
REM  every 4 hours, HIDDEN: Ollama watchdog -> headless browse -> read
REM  -> guarded goal-impact vector -> REAL Merkle drop.
REM
REM  The axis is NOT fixed here. --from-needs makes the system pick it
REM  from its own composer_needs.json, so what it senses follows what it
REM  currently lacks.
REM
REM  Double-click ONCE. If it says access denied, right-click ->
REM  Run as administrator.
REM
REM  To watch it:   type memory\collector_runs.log
REM  To audit it:   type memory\collector_runs.jsonl
REM  To stop it:    schtasks /Delete /TN "CORTEX_Collector" /F
REM  To fire it now: schtasks /Run /TN "CORTEX_Collector"
REM ====================================================================

schtasks /Create /TN "CORTEX_Collector" /SC HOURLY /MO 4 /F /TR "wscript.exe C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\experiments\collector\run_collector.vbs"

if %errorlevel%==0 (
  echo.
  echo   OK - CORTEX_Collector is live: every 4 hours, headless, real drops.
  echo   First run happens at the next 4-hour boundary; fire one now with:
  echo     schtasks /Run /TN "CORTEX_Collector"
) else (
  echo.
  echo   Could not register. Right-click this file and choose "Run as administrator".
)
echo.
pause
