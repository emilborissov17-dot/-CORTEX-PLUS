from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent

ORCHESTRATOR = ROOT / "hyperclaw_orchestrator.py"
EXECUTOR = ROOT / "hyperclaw_executor.py"

HOURS_BETWEEN_CYCLES = 4  # можем да коригираме после


def run_once(script: Path) -> int:
    cmd = ["python3", str(script)]
    print(f"[HYPERCYCLE] RUN: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def main() -> None:
    print("[HYPERCYCLE] starting loop...")
    while True:
        now = datetime.now()
        print(f"[HYPERCYCLE] cycle start at {now.isoformat(timespec='seconds')}")

        # 1) План от Qwen (multi-axis)
        rc1 = run_once(ORCHESTRATOR)
        print(f"[HYPERCYCLE] orchestrator rc={rc1}")

        # 2) Изпълнение на плана чрез агенти
        rc2 = run_once(EXECUTOR)
        print(f"[HYPERCYCLE] executor rc={rc2}")

        next_time = datetime.now() + timedelta(hours=HOURS_BETWEEN_CYCLES)
        print(f"[HYPERCYCLE] sleeping until ~{next_time.isoformat(timespec='minutes')}")
        time.sleep(HOURS_BETWEEN_CYCLES * 3600)


if __name__ == "__main__":
    main()
