@echo off
REM One double-click: commit the 13-14 Aug fix batch (EXPLICIT file list — never the
REM memory/snapshots churn), install the search package, and (optionally) move secrets
REM out of the repo tree. Written by Claude, updated 14 Aug 2026 (v2).
cd /d "%~dp0"

echo === installing ddgs (search) ===
venv\Scripts\python.exe -m pip install ddgs

echo === moving .env out of the repo tree (safer; code already looks there first) ===
if not exist "%USERPROFILE%\.cortex" mkdir "%USERPROFILE%\.cortex"
if exist ".env" copy /Y ".env" "%USERPROFILE%\.cortex\.env"

echo === installing the CI workflow (bridge cannot write .github - your hands do) ===
if not exist ".github\workflows" mkdir ".github\workflows"
copy /Y "docs\ci.yml.proposed" ".github\workflows\ci.yml"

echo === committing the fix batch (explicit files only) ===
git add agents/core/feedback_loop.py agents/core/self_modifier.py core/source_registration.py core/groq_backend.py experiments/needs/approve_reader.py experiments/needs/needs_report.py web_intelligence_agent.py execute_patches.py fast_cycle_runner.py config/composer_specs.json memory/existence_model.py memory/body_scan.py patch_guardian.py conftest.py youtube_intel.py RUNBOOK.md docs/ci.yml.proposed .github/workflows/ci.yml RUN_ME_COMMIT_FIXES.bat
git commit -m "honesty batch: risk axes invert and measurements outrank LLM buckets; patches must print MEASURED; error envelopes are refusals; search self-heals via ddgs/GDELT; the human can say NO; body_scan and existence stop lying about the local brain and the axis count; every LLM verdict gets provenance; RUNBOOK and CI so the system survives its operators"
git push
echo === done — review with: git log -1 --stat ===
pause
