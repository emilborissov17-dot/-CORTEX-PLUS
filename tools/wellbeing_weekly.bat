@echo off
REM ===========================================================================
REM tools\wellbeing_weekly.bat - the 217-country batch and the globe pair.
REM
REM WHY THIS IS ITS OWN FILE, AND WEEKLY (19 September 2026, Emil's ruling).
REM
REM Yesterday all three of these ran inside prophecy_morning.bat, every morning,
REM in line. The batch is 217 sequential World Bank country fetches: 1817 s
REM measured at 6 workers. That is half an hour of the 09:00 chain spent
REM re-fetching annual indicators that change a few times a YEAR, and half an
REM hour during which anything else wanting the machine has to wait.
REM
REM So: the batch runs ONCE A WEEK, on Sunday, detached, launched from the TOP
REM of prophecy_morning.bat.
REM
REM THE TOP, not the end, and the first draft had it the other way. The batch
REM replaces output\wellbeing_all_countries.json while daily_board row 8 reads
REM that file, so launching late keeps the writer clear of its readers. Then the
REM reachability was measured: the morning chain runs ~2h45m and reaches its last
REM step about half the time - claude\reports\ has TRACE pages for 13, 17 and 18
REM September and none for the 14th, 15th or 16th, and the run on 19 September was
REM terminated thirty minutes in, during cross_series_bench, having never reached
REM the wellbeing steps. A WEEKLY job hanging off the end of that is not weekly;
REM it is "most Sundays", and a missed Sunday feeds the governance axes fourteen-
REM day-old inputs instead of seven.
REM
REM The collision was removed rather than dodged: wellbeing_batch._save now writes
REM a .tmp and os.replace()s it, which is atomic, so a concurrent reader gets the
REM whole old file or the whole new one and never a truncated prefix.
REM
REM DETACHED, so a 30-minute step cannot hold the 09:00 chain open, cannot share
REM its hour with a gate, and is not killed when the chain is killed.
REM
REM THE THREE STEPS ARE ONE UNIT AND MUST NOT BE SPLIT:
REM
REM   1. wellbeing_batch.py    - 217 countries -> output\wellbeing_all_countries
REM                              .json, and the ONLY writer of output\wb_cache\,
REM                              which is what the daily governance pass reads.
REM   2. wellbeing_globe.py    - Merkle continent/globe tree. This run NULLS
REM                              governance_computed_at, governance_rights_score
REM                              and governance_institutions_score. Measured
REM                              19 Sep 2026.
REM   3. wellbeing_globe.py --governance-only  - puts them back.
REM
REM Step 2 without step 3 leaves the globe with no governance scores at all.
REM Until today goal_score_calculator answered that with 0.5 for both axes; as of
REM commit b7bdc0f it answers with None and the composite REFUSES. Which means a
REM half-finished weekly run no longer quietly degrades the published number - it
REM stops it. That is the intended behaviour and the reason this file runs the
REM three in order and reports a failure if any of them fails.
REM
REM Exit 0 if every step exited 0; 1 otherwise. None of the three has a refusal
REM path, so there is no acceptable non-zero here.
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe
set FAILED=

echo [WELLBEING_WEEKLY] start %DATE% %TIME%  cwd=%CD%

call :step "wellbeing_batch"       "%PY% wellbeing_batch.py --workers 6"
call :step "wellbeing_globe"       "%PY% wellbeing_globe.py"
call :step "wellbeing_governance"  "%PY% wellbeing_globe.py --governance-only"

echo.
if defined FAILED (
  echo [WELLBEING_WEEKLY] FAILED:!FAILED!
  endlocal & exit /b 1
)
echo [WELLBEING_WEEKLY] every step OK
endlocal & exit /b 0

REM --- :step NAME COMMAND ----------------------------------------------------
:step
echo.
echo [WELLBEING_WEEKLY] --- %~1 ---
%~2
set RC=!ERRORLEVEL!
if "!RC!"=="0" (
  echo [WELLBEING_WEEKLY] %~1 OK
  goto :eof
)
echo [WELLBEING_WEEKLY] %~1 FAILED rc=!RC!
set FAILED=!FAILED! %~1
goto :eof
