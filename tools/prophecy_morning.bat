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

REM --- THE WEEKLY BATCH, LAUNCHED FIRST AND DETACHED (19 Sep 2026) -------------
REM --- Sunday only. weekday() is 6 for Sunday and comes from python, not %DATE%,
REM --- which is locale-formatted and would have to be parsed to be trusted.
REM ---
REM --- WHY FIRST, having first written it last. The obvious placement is the end:
REM --- wellbeing_batch.py replaces output\wellbeing_all_countries.json and
REM --- daily_board row 8 reads that file, so launching late keeps the writer away
REM --- from its readers. Then the reachability was measured, and the end of this
REM --- chain is not a place that reliably happens: this script runs ~2h45m, and
REM --- claude\reports\ holds TRACE pages - rendered at the very last step - for
REM --- 13, 17 and 18 September but not for the 14th, 15th or 16th. Today's run
REM --- was terminated at 12:30:35 (LastTaskResult 0xC000013A) thirty minutes in,
REM --- during cross_series_bench, having never reached the wellbeing steps at all.
REM ---
REM --- A WEEKLY job hung on the end of a chain that ends about half the time is
REM --- not weekly. It is "most Sundays", and a missed Sunday means the governance
REM --- axes are fed fourteen-day-old inputs, not seven.
REM ---
REM --- So the reader-collision was removed instead of dodged: _save now writes a
REM --- .tmp and os.replace()s it, which is atomic, so a reader sees the whole old
REM --- file or the whole new one and never a truncated prefix. With that gone,
REM --- FIRST is strictly better than LAST - it is the one point in this script
REM --- that is reached every single time it starts.
REM ---
REM --- DETACHED via tools\launch_detached.ps1, so this script does not wait for
REM --- the half hour and the batch is not killed when the chain is. Its exit code
REM --- is therefore NOT this script's exit code: it reports itself into the log
REM --- named below, and a failure shows up as a wellbeing file a week older. The
REM --- LAUNCH failing - as opposed to the batch failing - is recorded loudly here.
REM --- AN UNKNOWN WEEKDAY IS NOT "NOT SUNDAY". If %PY% is missing or the -c call
REM --- fails, the for /f body never runs and DOW stays empty; `if "!DOW!"=="6"`
REM --- is then false and the else branch prints "skipped by design". That is a
REM --- missing value taking the do-nothing path behind a reassuring message, on
REM --- the one morning of the week that matters. Observed while testing this
REM --- block from the wrong directory: "weekday=" and a cheerful skip.
REM --- So DOW is cleared first and its emptiness is a FAILURE, announced.
set DOW=
for /f "usebackq delims=" %%w in (`%PY% -c "import datetime;print(datetime.date.today().weekday())"`) do set DOW=%%w
if "!DOW!"=="" (
  echo [PROPHECY_MORNING] wellbeing_weekly: COULD NOT DETERMINE THE WEEKDAY
  echo [PROPHECY_MORNING]   %PY% -c failed; refusing to guess whether today is Sunday
  set FAILED=!FAILED! wellbeing_weekly_weekday
  call :night_event "wellbeing_weekly weekday UNKNOWN" "%PY% could not report today's weekday, so prophecy_morning could not tell whether to fire the weekly 217-country batch. It did NOT fire. If today is Sunday, output/wellbeing_all_countries.json is now a week older than it should be."
) else if "!DOW!"=="6" (
  echo.
  echo [PROPHECY_MORNING] --- wellbeing_weekly ^(Sunday^): launching detached ---
  powershell -NoProfile -ExecutionPolicy Bypass -File "tools\launch_detached.ps1" -Exe "%ComSpec%" -Arguments "/c tools\wellbeing_weekly.bat" -Log "claude\reports\WELLBEING_WEEKLY.log"
  if errorlevel 1 (
    echo [PROPHECY_MORNING] wellbeing_weekly LAUNCH FAILED
    set FAILED=!FAILED! wellbeing_weekly_launch
    call :night_event "wellbeing_weekly LAUNCH FAILED" "tools/launch_detached.ps1 could not start tools/wellbeing_weekly.bat; the 217-country batch did not run this Sunday, so output/wellbeing_all_countries.json stays a week older"
  ) else (
    echo [PROPHECY_MORNING] wellbeing_weekly launched; see claude\reports\WELLBEING_WEEKLY.log
  )
) else (
  echo.
  echo [PROPHECY_MORNING] wellbeing_weekly: not Sunday ^(weekday=!DOW!^), skipped by design
)

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

rem card_intake MOVED OUT, 20 Sep 2026, and it is a REMOVAL not a relocation of
rem a duplicate: there may be exactly one owner of the judge. judge_inbox builds
rem its `seen` set once, at the top, from the card_keys already accepted or
rem refused, so two judges running together both read it before either writes and
rem both append the same card_key to memory/verified_observations.jsonl - the very
rem duplicate the key exists to prevent, in a file four modules count rows from.
rem CORTEX_OpenClaw fires at 11:50, ten minutes before this task, and the judge
rem fetches every unjudged card with a 30-second timeout each, so ten minutes is
rem not a distance. The judge now runs as step 2 of tools/openclaw_chain.bat,
rem immediately after the fetch, four times a day instead of once.
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
REM --- THE DAILY BOARD (18 Sep 2026). Emil, 17 Sep: "an experiment that does not
REM --- show a number every day is built wrong. Long horizons are for the verdict,
REM --- not for visibility." One row per running experiment, rewritten every
REM --- morning into claude\reports\DAILY_BOARD.md plus a dated copy under
REM --- claude\reports\daily_board\ that tomorrow reads for its "yesterday" column.
REM --- AFTER agi_scoreboard, and after both --score steps, on purpose: the board
REM --- reads what those wrote, and a board built first would show last night's
REM --- self-predictions as still open.
REM --- IT NEVER EXITS 2. A row whose source is unusable prints MISSING and the
REM --- path; that is the row's correct output for the morning, not a refusal of
REM --- the step, so REFUSAL_OK stays `no` and any non-zero here is a real failure.
REM --- INSTITUTION #0 (WITNESS STAGE), 18 Sep 2026. Counts UCDP one-sided
REM --- violence against civilians per commitment in config\commitments.json,
REM --- appends to experiments\institution\ledger.jsonl, scores what matured.
REM --- BEFORE daily_board, because board row 7 reads the ledger this writes.
REM --- NEVER in the 03:04 cycle: this fetches ~280 MB of UCDP files on refresh
REM --- and the cycle's memory budget is the thing that kills it.
REM --- Exit 2 is not used here; a source it cannot read is a MISSING row, not a
REM --- refusal of the step, so REFUSAL_OK stays `no`.
REM --- THE PER-COUNTRY LAYER (19 Sep 2026). Until today output\wellbeing_all_
REM --- countries.json was computed 2026-07-02 and nothing recomputed it, while
REM --- GOVERNANCE_INSTITUTIONS and GOVERNANCE_RIGHTS were scored FROM it into
REM --- every night's composite as if it were current. 79 days.
REM ---
REM --- THE CHAIN IS THREE SCRIPTS, NOT TWO. wellbeing_country.py is a SINGLE-
REM --- COUNTRY CLI; the batch driver is wellbeing_batch.py, which is what
REM --- wellbeing_globe.py names in its own error path ("run wellbeing_batch.py
REM --- first"). An earlier recommendation of mine named the wrong entry point.
REM ---
REM --- AND THE GLOBE MUST RUN TWICE. A plain wellbeing_globe.py run WIPES
REM --- governance_computed_at, governance_rights_score and governance_
REM --- institutions_score to null - measured today - and goal_score_calculator
REM --- then drops both governance axes to 0.5 with a warning nobody reads.
REM --- --governance-only restores them. Running the first without the second is
REM --- strictly worse than not running either.
REM ---
REM --- SPLIT WEEKLY / DAILY (19 Sep 2026, Emil's ruling). All three ran here in
REM --- line, every morning, for exactly one day. The batch is ~30 minutes of CPU:
REM --- 217 countries of World Bank fetches, measured 1817 s at 6 workers,
REM --- re-fetching annual indicators that change a few times a YEAR. Half an hour
REM --- of the 09:00 chain, every day, for data that moves annually.
REM ---
REM --- So the batch and the globe pair moved to tools\wellbeing_weekly.bat, fired
REM --- ONCE A WEEK on Sunday, DETACHED, from the TOP of this script - see the
REM --- launch block near the start, and the reasoning in that file's header.
REM ---
REM --- WHAT STAYS DAILY is this one pass. It reads output\wb_cache\, does no
REM --- network, and takes seconds. It is what keeps governance_rights_score and
REM --- governance_institutions_score present in output\wellbeing_globe.json, and
REM --- since b7bdc0f their absence makes the composite REFUSE rather than
REM --- substitute 0.5. REFUSAL_OK stays `no`: it has no refusal path.
REM ---
REM --- AND IT RESTAMPS governance_computed_at = now from an unchanged cache on six
REM --- mornings in seven. goal_score_calculator's 90-day freshness gate therefore
REM --- no longer reads that field - it reads governance_source_newest_at, the age
REM --- of the INPUTS. Gating on the restamped field would have left a guard that
REM --- cannot fire.
call :step "wellbeing_governance"  "%PY% wellbeing_globe.py --governance-only"              no
call :step "institution0"          "%PY% tools\institution0_morning.py --write"              no
REM --- The reply to last morning's message. Its own offset file, its own parser;
REM --- it never touches approve_reader's, whose refusal boundary is a feature.
call :step "institution0_witness"  "%PY% experiments\institution\witness_reader.py"          no
call :step "daily_board"           "%PY% tools\daily_board.py --write"                       no

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
