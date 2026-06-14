@echo off
cd /d C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 >nul
venv\Scripts\python.exe -m memory.body_scan >> logs\daily_log.txt
venv\Scripts\python.exe -m memory.existence_model >> logs\daily_log.txt
venv\Scripts\python.exe hypercortex_runner.py >> logs\daily_log.txt
venv\Scripts\python.exe -m memory.trend_tracker >> logs\daily_log.txt
venv\Scripts\python.exe -m memory.auto_threshold >> logs\daily_log.txt
venv\Scripts\python.exe -m memory.auto_level >> logs\daily_log.txt
venv\Scripts\python.exe -m memory.semantic_memory >> logs\daily_log.txt
venv\Scripts\python.exe -m agents.core.system2_agent >> logs\daily_log.txt
venv\Scripts\python.exe -m agents.core.self_modifier >> logs\daily_log.txt
venv\Scripts\python.exe -m agents.core.action_layer >> logs\daily_log.txt
venv\Scripts\python.exe -m agents.core.daily_analysis_agent >> logs\daily_log.txt
venv\Scripts\python.exe -c "from agents.internet.internet_agent import run; run()" >> logs\daily_log.txt
git add memory/ snapshots/master/ reports/ && git commit -m "AUTO: daily snapshot %date%"
