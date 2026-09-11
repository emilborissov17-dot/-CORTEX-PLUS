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
call :step "daily_tier"             "%PY% core\daily_tier.py"                              no
call :step "world_forecast --score"   "%PY% experiments\prophecy\world_forecast.py --score"     yes
call :step "world_forecast --predict" "%PY% experiments\prophecy\world_forecast.py --predict"   yes
call :step "scoreboard --write"      "%PY% experiments\prophecy\scoreboard.py --write"          no
call :step "card_intake"            "%PY% core\card_intake.py"                                no
call :step "verified_corpus"        "%PY% training\verified_corpus.py"                       no

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
