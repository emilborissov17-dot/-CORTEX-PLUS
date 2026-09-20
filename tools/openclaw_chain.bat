@echo off
setlocal
rem tools/openclaw_chain.bat - fetch, then judge, in that order, as one event.
rem
rem WHY THIS EXISTS (20 September 2026)
rem --------------------------------------------------------------------------
rem CORTEX_OpenClaw fetches at 05:50 / 11:50 / 17:50 / 23:50 and core/card_intake
rem ran ONCE, from tools/prophecy_morning.bat at 12:00. Three of the four daily
rem batches therefore sat in openclaw_queue/cards unjudged for up to twenty
rem hours: today's 14:50 cards were still waiting while
rem memory/verified_observations.jsonl stood at 9 rows.
rem
rem ONE OWNER FOR THE JUDGE, AND THE REASON IS A RACE, NOT TIDINESS.
rem core.card_intake.judge_inbox computes `seen` ONCE, at the top, from the
rem card_keys already in accepted + refused. Two judges running together both
rem read that set before either writes, both find a card absent, both fetch it,
rem both judge it and both append - two rows with the SAME card_key in
rem memory/verified_observations.jsonl, which is precisely the duplicate the
rem card_key exists to prevent, in a file four modules count rows from. The ten
rem minutes between 11:50 and 12:00 are no guarantee either: the judge fetches
rem every unjudged card over HTTP with a 30-second timeout each, so a backlog of
rem slow sources runs past ten minutes without trying.
rem
rem So the chain owns the judge and the line in prophecy_morning.bat is gone.
rem
rem SAFE TO RUN FOUR TIMES A DAY: judge_inbox skips any card_key already in
rem accepted or refused (card_intake.py, `if k in seen: skipped += 1`), so an
rem unchanged inbox costs one read. Measured on the first live run: skipped 9.
rem
rem ONE run_id FOR BOTH HALVES. core.task_runs.run_id() returns CORTEX_RUN_ID
rem when it is set, so the fetch and the judge are one event in
rem memory/task_runs.jsonl - and because unfinished() keys on (task, run_id),
rem a chain whose fetch finished and whose judge died still shows one start
rem without a finish instead of hiding behind the shared id.

cd /d "%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "PY=venv\Scripts\python.exe"

rem A chain id from the clock, so two steps seconds apart read as one event and
rem a human scanning the log can see WHEN, which a hash cannot tell them.
rem
rem NOT FROM %DATE%, and the first live run is why. Slicing %DATE% by character
rem position assumes one locale's format; on this machine it produced
rem "chain-202600Su-193031" - the weekday where the month should be. Get-Date
rem with an explicit format string does not care what the short date looks like.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "CORTEX_RUN_ID=chain-%%i"
if not defined CORTEX_RUN_ID set "CORTEX_RUN_ID=chain-unknown-%RANDOM%"

echo [CHAIN] %CORTEX_RUN_ID% step 1/2 openclaw_axis_worker
%PY% scripts\openclaw_axis_worker.py
set "WORKER_RC=%ERRORLEVEL%"

rem THE JUDGE RUNS EVEN IF THE FETCH RETURNED NON-ZERO, and that is deliberate:
rem the worker exits 1 when it produced no TRUSTED row, which is an ordinary
rem night, not a failure - and cards from an earlier batch may still be waiting.
rem Skipping the judge on a quiet fetch would strand them exactly as the 12:00
rem schedule did.
echo [CHAIN] %CORTEX_RUN_ID% step 2/2 card_intake (worker rc=%WORKER_RC%)
%PY% core\card_intake.py
set "JUDGE_RC=%ERRORLEVEL%"

echo [CHAIN] %CORTEX_RUN_ID% done: worker rc=%WORKER_RC% judge rc=%JUDGE_RC%
endlocal & exit /b %JUDGE_RC%
