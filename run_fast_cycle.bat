@echo off
cd /d C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 >nul
echo [%date% %time%] Fast cycle start >> logs\fast_cycle_log.txt
venv\Scripts\python.exe fast_cycle_runner.py >> logs\fast_cycle_log.txt 2>&1
echo [%date% %time%] Fast cycle done >> logs\fast_cycle_log.txt
