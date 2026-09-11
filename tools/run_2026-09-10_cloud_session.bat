@echo off
REM 10 Sep 2026 - written from Ivan's cloud session. Everything the cloud could
REM not run on the machine, in the order it should run. Read the output, do not
REM trust this file's opinion of it.
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8

echo === 1. the new tests (10, with negative controls) ===
venv\Scripts\python.exe -m pytest test\test_self_forecast.py -q -p no:cacheprovider

echo === 2. selftest on the real ledger: says LIVE or INERT ===
venv\Scripts\python.exe experiments\prophecy\self_forecast.py --selftest

echo === 3. the CORTEX scoreboard, written to claude\reports\PROPHECY_SCOREBOARD.md ===
venv\Scripts\python.exe experiments\prophecy\scoreboard.py --write

echo === 4. Kimi on the three questions (free kimi-k2.6 via OpenRouter) ===
venv\Scripts\python.exe -m experiments.kimi_duel.consult experiments\kimi_duel\briefs\2026-09-10_next_learning_hypothesis.brief.md

echo === done. Kimi's answer is in experiments\kimi_duel\consults\ ===
