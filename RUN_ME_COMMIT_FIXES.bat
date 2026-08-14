@echo off
REM One double-click: commit the 13-14 Aug fix batch (EXPLICIT file list — never the
REM memory/snapshots churn) and install the search package. Written by Claude 14 Aug 2026.
cd /d "%~dp0"

echo === installing ddgs (search) ===
venv\Scripts\python.exe -m pip install ddgs

echo === committing the fix batch (explicit files only) ===
git add agents/core/feedback_loop.py agents/core/self_modifier.py core/source_registration.py experiments/needs/approve_reader.py experiments/needs/needs_report.py web_intelligence_agent.py execute_patches.py fast_cycle_runner.py config/composer_specs.json patch_guardian.py conftest.py youtube_intel.py web_intelligence_agent.py RUN_ME_COMMIT_FIXES.bat
git commit -m "feedback honesty: risk axes invert, measurements outrank LLM buckets; patches must print MEASURED or be named UNMEASURED; error envelopes are refusals; search falls back to GDELT with pacing and self-installs ddgs; the human can say NO; junk governance proxies removed from the spec"
git push
echo === done — review with: git log -1 --stat ===
pause
