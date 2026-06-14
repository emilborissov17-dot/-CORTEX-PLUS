#!/usr/bin/env python3
import subprocess
import pathlib
import datetime

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]

DAILY_REVIEW_CMDS = [
    ["python3", "energy_review_runner.py"],
    # Тук по-късно ще добавим и други REVIEW-и
]

def run_parallel(commands):
    procs = []
    for cmd in commands:
        procs.append(
            subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
            )
        )
    for p in procs:
        p.wait()

def main():
    ts = datetime.datetime.now().isoformat()
    print(f"[DAILY_REVIEW_RUNNER] start at {ts}")
    run_parallel(DAILY_REVIEW_CMDS)
    print("[DAILY_REVIEW_RUNNER] done")

if __name__ == "__main__":
    main()
