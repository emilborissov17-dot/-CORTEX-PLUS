#!/usr/bin/env python3
"""
run_daily.py
Пуска пълния daily цикъл на CORTEX++_QWEN:
1. hypercortex_runner.py  — събира всички snapshots
2. daily_analysis_agent.py — анализира и обновява next_actions.txt
"""
import subprocess, sys, pathlib
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = pathlib.Path(__file__).resolve().parent

def main():
    print(f"[DAILY] CORTEX++_QWEN daily cycle — {datetime.now(timezone.utc).isoformat()}")
    r1 = subprocess.run([sys.executable, str(BASE / "hypercortex_runner.py")], cwd=str(BASE))
    r2 = subprocess.run([sys.executable, "-m", "agents.core.daily_analysis_agent"], cwd=str(BASE))
    print(f"\n[DAILY] done — hypercortex: {'OK' if r1.returncode==0 else 'FAILED'}, analysis: {'OK' if r2.returncode==0 else 'FAILED'}")

if __name__ == "__main__":
    main()
