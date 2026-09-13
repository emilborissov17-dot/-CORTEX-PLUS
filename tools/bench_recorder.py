#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/bench_recorder.py — what the flight recorder costs, on this machine.

The same real work twice: once bare, once with channels A (pulse) and B (audit).
Channel C stays off, as it is by default.

The payload is core.consolidation.run(write=False) repeated. It was chosen because
it is real code from this repo that does the two things a cycle mostly does — pure
Python arithmetic and a great many file READS — and reads are the audit hook's hot
path: the hook is entered on every open() and must decide in a few instructions
that a read is not interesting. If the cost is anywhere, it is there.

Medians of three, because one slow run on a laptop is not a measurement.

    venv\\Scripts\\python.exe tools\\bench_recorder.py --n 600 --reps 3
"""
from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / "venv" / "Scripts" / "python.exe"

PAYLOAD = '''
import sys, os
sys.path.insert(0, REPO)
if os.environ.get("BENCH_RECORDER") == "1":
    from core import flight_recorder as fr
    fr.TRACE_DIR = os.environ["BENCH_TRACE_DIR"]
    fr.start("bench")
from core import consolidation as c
for _ in range(N):
    c.run(write=False)
if os.environ.get("BENCH_RECORDER") == "1":
    fr.stop()
'''


def _payload(path: Path, n: int) -> Path:
    path.write_text(f'REPO = r"{REPO}"\nN = {n}\n' + PAYLOAD, encoding="utf-8")
    return path


def once(payload: Path, on: bool, trace_dir: str) -> float:
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               BENCH_RECORDER="1" if on else "0",
               BENCH_TRACE_DIR=trace_dir)
    env.pop("CORTEX_TRACE_CALLS", None)          # channel C stays off
    t0 = time.perf_counter()
    p = subprocess.run([str(PY), str(payload)], cwd=str(REPO), env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    dt = time.perf_counter() - t0
    if p.returncode != 0:
        sys.exit(f"payload failed (recorder={'on' if on else 'off'}): "
                 f"{p.stderr.decode('utf-8', 'replace')[-800:]}")
    return dt


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args(argv)

    tmp = Path(tempfile.mkdtemp())
    payload = _payload(tmp / "payload.py", a.n)
    trace_dir = str(tmp / "traces")
    os.makedirs(trace_dir, exist_ok=True)

    once(payload, False, trace_dir)              # warm the caches, discarded
    off, on = [], []
    for i in range(a.reps):
        off.append(round(once(payload, False, trace_dir), 3))
        on.append(round(once(payload, True, trace_dir), 3))
        print(f"rep{i + 1}  off {off[-1]:7.3f}s   on {on[-1]:7.3f}s", flush=True)

    mo, mn = statistics.median(off), statistics.median(on)
    pct = (mn / mo - 1.0) * 100.0
    print()
    print(f"payload            : core.consolidation.run(write=False) x {a.n}")
    print(f"without the record : {off}  median {mo:.3f}s")
    print(f"with A+B           : {on}  median {mn:.3f}s")
    print(f"cost               : {mn - mo:+.3f}s  =  {pct:+.2f}%")
    traces = list(Path(trace_dir).glob("*.jsonl"))
    if traces:
        rows = sum(1 for _ in traces[-1].open(encoding="utf-8"))
        print(f"rows recorded      : {rows} in {traces[-1].name}")
    if pct > 5.0:
        print()
        print(f"OVER 5%. The pulse is the adjustable part: PULSE_SEC is "
              f"{ '1.0' } today, and 2.0 or 5.0 halves or fifths that share of the "
              f"cost while still catching any step longer than a few seconds. The "
              f"audit hook is not adjustable in the same way — it is per-open, not "
              f"per-second — so if the excess is there, the answer is a narrower "
              f"filter, not a slower pulse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
