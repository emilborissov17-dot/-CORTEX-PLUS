@echo off
REM ===========================================================================
REM tools\prophecy_morning.bat — the whole 09:00 UTC prophecy morning, in order.
REM
REM Written 2026-09-10 (HANDOVER STEP 2 / ITEM 76). Before this, the
REM CORTEX_Prophecy task held its commands inline:
REM
REM   cmd /c cd /d <repo> && python prophecy.py --score && python prophecy.py --predict
REM
REM Two reasons that could not simply be extended with three more `&&`:
REM
REM 1. LENGTH. schtasks caps the /TR field (261 chars). The inline form was
REM    already ~190; five commands do not fit. A task field is also unreadable
REM    and untestable — a .bat in the repo is both.
REM
REM 2. `&&` CANNOT SAY "REFUSED IS FINE". self_forecast.py exits 2 when it
REM    REFUSES — a cycle is running, or there is less history than MIN_HISTORY.
REM    That is a correct, designed outcome, not a failure. Under `&&` it would
REM    cancel every later command, so a legitimate refusal at 09:00 would have
REM    silently skipped scoreboard --write and nobody would see a gap.
REM
REM SO: every step runs, unconditionally, and its exit code is judged per step.
REM Nothing is skipped because something earlier refused.
REM
REM WHAT COUNTS AS A FAILURE, PER STEP — exit 2 does NOT mean the same thing
REM everywhere, and collapsing them would be the silent-degradation defect this
REM repo exists to catch:
REM   prophecy.py --predict exit 2 = Refused -> EXPECTED. One forecast per night:
REM                     if the anchor has not moved (no cycle since the last
REM                     --predict) there is nothing to seal. Announced, not a
REM                     failure. --score does not refuse, so it stays `no`.
REM   self_forecast.py  exit 2 = Refused  -> EXPECTED. Announced, not a failure.
REM   world_forecast.py exit 2 = Refused  -> EXPECTED (no indicator moves). Same.
REM   scoreboard.py     exit 2 = ChainBroken -> the prophecy ledger's hash chain
REM                     does not verify. That is an integrity alarm and it
REM                     COUNTS AS A FAILURE here, loudly.
REM   anything else non-zero = FAILURE.
REM
REM A no-output morning is a legitimate success: if a cycle is running, every
REM self_forecast step refuses, nothing is sealed, and this script exits 0 having
REM sealed nothing. The forbidden fallback is sealing a forecast anyway so the
REM morning "has output".
REM
REM Exit code: 0 if every step was OK or acceptably REFUSED; 1 if any step
REM failed, so Task Scheduler's "Last Result" stops being 0 and the failure is
REM visible in schtasks /Query without reading a log.
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe
set FAILED=

echo [PROPHECY_MORNING] start %DATE% %TIME%  cwd=%CD%

REM --- SCORE BEFORE PREDICT, both pairs: a morning closes last night before it
REM --- opens the next one. Predicting first would leave last night's sealed
REM --- forecast unscored for a day and let two open forecasts exist at once.
call :step "prophecy --score"        "%PY% experiments\prophecy\prophecy.py --score"            no
call :step "prophecy --predict"      "%PY% experiments\prophecy\prophecy.py --predict"          yes
call :step "self_forecast --score"   "%PY% experiments\prophecy\self_forecast.py --score"       yes
call :step "self_forecast --predict" "%PY% experiments\prophecy\self_forecast.py --predict"     yes
REM --- daily_tier BEFORE the world loop: keep tonight's global_indicators fetch as
REM --- dated observations (AGI-5). The world loop reads this tier; before it, the
REM --- daily leaves were fetched every night and overwritten every night.
REM --- The years behind every axis (Emil, 11 Sep 2026): World Bank + NOAA annual series,
REM --- oldest to last, into memory\axis_history_annual.json (own file; never the learner).
call :step "axis_backfill"          "%PY% core\axis_backfill.py"                           yes
call :step "daily_tier"             "%PY% core\daily_tier.py"                              no
call :step "world_forecast --score"   "%PY% experiments\prophecy\world_forecast.py --score"     yes
call :step "world_forecast --predict" "%PY% experiments\prophecy\world_forecast.py --predict"   yes
call :step "scoreboard --write"      "%PY% experiments\prophecy\scoreboard.py --write"          no
rem The reader goes FIRST: six machines wrote their failure honestly on 13 Sep

rem 2026 and nobody read one of them. A log nobody reads is a log that is not kept.

rem THE PANTRY FILLER. The night stopped fetching on 13 Sep 2026 and the cycle

rem was the only thing writing news/<day>/, so without this the system goes blind

rem to news from the next morning. Same work, at an hour the machine can hold it.

rem It asks the same survival gate the cycle asks and refuses when that refuses.

call :step "fill_pantry"           "%PY% tools\fill_pantry.py"                              no

call :step "morning_read"          "%PY% tools\morning_read.py"                              no

call :step "card_intake"            "%PY% core\card_intake.py"                                no
call :step "verified_corpus"        "%PY% training\verified_corpus.py"                       no
REM --- E1 (11 Sep 2026): does knowing the other daily series help? transfer A->B and
REM --- the learning curve k=10/20/40/80, walk-forward, against persistence (points 1, 3).
call :step "cross_series_bench"     "%PY% experiments\prophecy\cross_series_bench.py --write" yes
REM --- E3 (11 Sep 2026): the BRAIN (qwen3:8b) proposes inputs for the direction learner;
REM --- the EXAM keeps an input only if it improves direction on unseen days (>= 2 SE).
call :step "feature_proposals"      "%PY% core\feature_proposals.py"                         yes
REM --- Point 13 probe: the same two numbers, mirrored across the line, and a date
REM --- change; the verdict must follow the number and only the number (#61).
call :step "counterfactual_probe"   "%PY% core\counterfactual_probe.py"                       yes
REM --- Which cloud mind goes first, by measurement (11 Sep 2026): provenance + probe ->
REM --- memory\backend_order_measured.json, read by core\groq_backend.py tonight.
call :step "backend_league"         "%PY% scripts\backend_league.py --write"                  no
REM --- LAST: the 14 AGI points as numbers, read from everything above (11 Sep 2026,
REM --- Claude accountable). A number that cannot be read is "-" with a reason.
call :step "agi_scoreboard"         "%PY% scripts\agi_scoreboard.py --write"                  no

REM --- THE PER-STEP TRACE PAGE, and why it is rendered HERE and not in the
REM --- cycle: the trace is only closed at process exit (recorder_stop), so a
REM --- report built INSIDE the cycle would miss its own tail -- the last step's
REM --- span and every event after it. The next morning is the earliest moment a
REM --- COMPLETE trace exists. Recorded every night since 13 Sep 2026 and
REM --- rendered exactly once, because tools\trace_report.py had no caller.
REM --- TODAY comes from python, not %DATE%: %DATE% is locale-formatted and would
REM --- disagree with the filename trace_report.py picks for itself. One variable
REM --- feeds both the --date flag and the copy, so the two cannot diverge.
for /f "usebackq delims=" %%d in (`%PY% -c "import datetime;print(datetime.date.today().isoformat())"`) do set TODAY=%%d
echo.
echo [PROPHECY_MORNING] --- trace_report ---
%PY% tools\trace_report.py --date !TODAY!
set RC=!ERRORLEVEL!
if "!RC!"=="0" goto :trace_ok
echo [PROPHECY_MORNING] trace_report FAILED rc=!RC!
set FAILED=!FAILED! trace_report
call :night_event "trace_report FAILED" "tools/trace_report.py exited !RC!; no TRACE page written for !TODAY!"
goto :trace_done
:trace_ok
copy /y "claude\reports\TRACE_!TODAY!.html" "claude\reports\TRACE_LATEST.html" >nul
if errorlevel 1 echo [PROPHECY_MORNING] trace_report: copy to TRACE_LATEST.html FAILED & set FAILED=!FAILED! trace_latest_copy
echo [PROPHECY_MORNING] trace_report OK
:trace_done

echo.
if defined FAILED (
  echo [PROPHECY_MORNING] FAILED:!FAILED!
  endlocal & exit /b 1
)
echo [PROPHECY_MORNING] every step OK or acceptably REFUSED
endlocal & exit /b 0

REM --- :step NAME COMMAND REFUSAL_OK ----------------------------------------
:step
echo.
echo [PROPHECY_MORNING] --- %~1 ---
%~2
set RC=!ERRORLEVEL!
if "!RC!"=="0" (
  echo [PROPHECY_MORNING] %~1 OK
  goto :eof
)
if "!RC!"=="2" if /i "%~3"=="yes" (
  echo [PROPHECY_MORNING] %~1 REFUSED ^(exit 2^) — expected while a cycle runs or
  echo [PROPHECY_MORNING]   history is short. Nothing sealed. NOT a failure.
  goto :eof
)
echo [PROPHECY_MORNING] %~1 FAILED rc=!RC!
set FAILED=!FAILED! %~1
goto :eof

REM --- :night_event SUBJECT DETAIL -------------------------------------------
REM This bat had NO helper that writes memory\night_events.jsonl. :step only
REM echoes and appends to !FAILED!, which Task Scheduler's Last Result shows but
REM the morning report (core\cycle_report.py) never reads -- it reads
REM night_events.jsonl. So a 09:00 failure was invisible to the one document a
REM human actually opens. This is the smallest helper that puts a morning
REM failure where the night's failures already live, in the same three-key shape
REM supervisor.note_night_event writes:
REM   {"ts": <ISO-8601 UTC>, "subject": ..., "detail": ...}
REM supervisor.py is NOT imported (importing it would run a supervisor module's
REM top-level code); only its record shape is reused.
REM It PRINTS when the write itself fails -- a recorder that fails silently is
REM the same defect one level up.
:night_event
%PY% -c "import json,sys,datetime,pathlib;p=pathlib.Path('memory/night_events.jsonl');p.parent.mkdir(parents=True,exist_ok=True);open(p,'a',encoding='utf-8').write(json.dumps({'ts':datetime.datetime.now(datetime.timezone.utc).isoformat(),'subject':sys.argv[1],'detail':sys.argv[2]},ensure_ascii=False)+chr(10))" %1 %2
if errorlevel 1 echo [PROPHECY_MORNING] night_event write FAILED for %~1
goto :eof
