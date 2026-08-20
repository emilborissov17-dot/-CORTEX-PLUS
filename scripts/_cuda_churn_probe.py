#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/_cuda_churn_probe.py — DOES REPEATED LOAD/UNLOAD LEAK DRIVER MEMORY?

THE STANDING CANDIDATE FOR THE SILENT DEATHS
---------------------------------------------
Four cycles have died leaving a log that stops mid-step with no traceback, no
Windows event and no exit record. Both named suspects (the ChromaDB vector
query, the full brain.attend path) were cleared in a fresh process: 200 and 50
iterations, exit 0, flat timings.

What could not be reproduced there is the machine mid-cycle. Measured tonight
on this GPU (4096 MB total):

    qwen2.5:3b   used 2566 MB   free 1385 MB   100% GPU
    qwen3:8b     used 3812 MB   free  139 MB   38%/62% CPU/GPU

qwen3:8b does not fit. It is already spilling to CPU, and it leaves 139 MB of
headroom. The cycle switches between these two models many times per run —
beat() calls the brain on every one of 53 steps, and the chain falls to the
local model whenever the cloud is down (14 times tonight).

So the question this probe asks is narrow and answerable: does churning a model
in and out at that headroom leak driver memory, so that the Nth load fails or
takes the process down?

TWO CURVES
-----------
  A. load -> 1 token -> unload -> wait -> sample     (the churn)
  B. load once, keep_alive, 1 token per iteration    (the control)

If A drifts upward and B does not, the churn leaks. If neither drifts, this
suspect is cleared too and the silent deaths are something else.

READ-ONLY WITH RESPECT TO THE REPO. Writes its trace to the path given by
--out, which defaults to the system temp directory, NOT into memory/.

    venv/Scripts/python.exe scripts/_cuda_churn_probe.py --iterations 50
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

OLLAMA = os.environ.get(
    "CORTEX_OLLAMA_BIN",
    str(pathlib.Path(os.environ.get("LOCALAPPDATA", "")) /
        "Programs" / "Ollama" / "ollama.exe"))
OLLAMA_URL = os.environ.get("CORTEX_OLLAMA_URL", "http://localhost:11434")


def vram() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20)
        total, used, free = [int(x.strip()) for x in
                             out.stdout.strip().splitlines()[0].split(",")]
        return {"total_mb": total, "used_mb": used, "free_mb": free}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def generate(model: str, keep_alive) -> tuple[bool, str]:
    """One token from `model`. keep_alive=0 unloads immediately after."""
    try:
        import requests
        r = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": model, "prompt": "1", "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_predict": 1},
        }, timeout=300)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def unload(model: str) -> None:
    try:
        subprocess.run([OLLAMA, "stop", model], capture_output=True, timeout=60)
    except Exception:
        pass


def run_curve(name: str, model: str, iterations: int, wait: float,
              churn: bool, out) -> list[dict]:
    """churn=True: load/unload every iteration. False: keep it resident."""
    rows = []
    print(f"\n=== {name} — {'load/unload each time' if churn else 'keep_alive, no unload'} ===",
          flush=True)
    if churn:
        unload(model)
        time.sleep(wait)
    baseline = vram()
    print(f"  baseline  used {baseline.get('used_mb')} free {baseline.get('free_mb')}",
          flush=True)

    for i in range(1, iterations + 1):
        t0 = time.perf_counter()
        ok, err = generate(model, keep_alive=0 if churn else "10m")
        if churn:
            unload(model)
        time.sleep(wait)
        v = vram()
        secs = time.perf_counter() - t0
        row = {"ts": datetime.now(timezone.utc).isoformat(), "curve": name,
               "i": i, "ok": ok, "error": err, "secs": round(secs, 1), **v}
        rows.append(row)
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()
        print(f"  {i:>3}/{iterations}  {'ok ' if ok else 'ERR'}  {secs:6.1f}s  "
              f"used {v.get('used_mb')}  free {v.get('free_mb')}  {err[:60]}",
              flush=True)
        if not ok and "connection" in err.lower():
            print("  [PROBE] ollama unreachable — stopping this curve", flush=True)
            break
    return rows


def summarise(name: str, rows: list[dict]) -> dict:
    frees = [r["free_mb"] for r in rows if isinstance(r.get("free_mb"), int)]
    if not frees:
        return {"curve": name, "error": "no readings"}
    first_five = sum(frees[:5]) / len(frees[:5])
    last_five = sum(frees[-5:]) / len(frees[-5:])
    return {
        "curve": name,
        "iterations": len(rows),
        "failures": sum(1 for r in rows if not r["ok"]),
        "free_first": frees[0],
        "free_last": frees[-1],
        "free_min": min(frees),
        "mean_free_first5": round(first_five),
        "mean_free_last5": round(last_five),
        "drift_mb": round(last_five - first_five),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--wait", type=float, default=10.0)
    ap.add_argument("--out", default=str(pathlib.Path(tempfile.gettempdir()) /
                                         "cortex_cuda_churn.jsonl"))
    a = ap.parse_args()

    print(f"[PROBE] model={a.model} iterations={a.iterations} wait={a.wait}s")
    print(f"[PROBE] ollama={OLLAMA}")
    print(f"[PROBE] trace -> {a.out}   (NOT in the repo)")

    with open(a.out, "a", encoding="utf-8") as out:
        churn = run_curve("A_churn", a.model, a.iterations, a.wait, True, out)
        control = run_curve("B_resident", a.model, a.iterations, a.wait, False, out)
    unload(a.model)

    print("\n=== SUMMARY ===")
    verdicts = []
    for name, rows in (("A_churn", churn), ("B_resident", control)):
        s = summarise(name, rows)
        verdicts.append(s)
        print(f"  {json.dumps(s, ensure_ascii=False)}")

    a_drift = verdicts[0].get("drift_mb")
    b_drift = verdicts[1].get("drift_mb")
    if isinstance(a_drift, int) and isinstance(b_drift, int):
        print(f"\n  churn drift {a_drift:+d} MB vs resident drift {b_drift:+d} MB")
        print("  -> LEAK SUSPECTED" if a_drift < -50 and a_drift < b_drift - 50
              else "  -> no leak visible at this headroom")
    return 0


if __name__ == "__main__":
    sys.exit(main())
