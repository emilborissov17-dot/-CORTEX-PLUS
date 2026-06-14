#!/usr/bin/env python3
import os
import sys
import time
from datetime import datetime, timezone
import subprocess
from pathlib import Path

BASEDIR = Path(os.path.dirname(os.path.abspath(__file__)))
LOGFILE = BASEDIR / "history" / "resource_review_daemon.log"

# интервал между циклите (в секунди) – сега 15 минути
CYCLE_SECONDS = 900


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str):
    ts = utc_iso()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOGFILE.parent.mkdir(exist_ok=True)
        with LOGFILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def start_runner_for_domain(domain: str) -> subprocess.Popen:
    cmd = [sys.executable, str(BASEDIR / "resource_review_runner.py"), f"--domain={domain}"]
    log(f"RESOURCE_REVIEW_DAEMON: starting runner for domain={domain} (parallel)")
    proc = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def main():
    log("RESOURCE_REVIEW_DAEMON: started (parallel mode)")

    # ENERGY и WATER в паралел; после лесно добавяме още домейни.
    domains = ["energy", "water"]

    while True:
        start_ts = utc_iso()
        log(f"RESOURCE_REVIEW_DAEMON: cycle start at {start_ts}")
        log("=== RESOURCE_REVIEW: BEGIN CYCLE ===")

        procs = {}
        for d in domains:
            log(f"{d.upper()}_REVIEW: START RESOURCE_REVIEW {d}")
            procs[d] = start_runner_for_domain(d)

        # изчакваме всички да свършат
        for d, p in procs.items():
            stdout, stderr = p.communicate()
            if p.returncode != 0:
                log(f"RESOURCE_REVIEW_DAEMON: runner for {d} exited with {p.returncode}")
                if stderr:
                    log(f"STDERR {d}: {stderr.strip()}")
            else:
                out_len = len(stdout or "")
                log(f"RESOURCE_REVIEW_DAEMON: runner for {d} finished OK (stdout length={out_len})")
            log(f"{d.upper()}_REVIEW: END RESOURCE_REVIEW {d}")

        log("=== RESOURCE_REVIEW: END CYCLE ===")
        log(f"RESOURCE_REVIEW_DAEMON: sleeping {CYCLE_SECONDS} seconds")
        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
