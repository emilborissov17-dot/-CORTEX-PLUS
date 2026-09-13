#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""tools/bench_suite.py — how much memory does the test suite actually want?

WHY THIS EXISTS. The rule was "run the full suite when the machine drops under 80%
used". Nobody measured where that number came from — it was a guess, and a guess
dressed as a threshold is the thing this repo keeps finding in its own logs. If
the suite wants 600 MB then 80% was needlessly timid and the suite has been
skipped on nights it could have run; if it wants 3 GB then 80% was not enough and
the suite has been started on nights it could not finish.

THREE CHANNELS, and this file records which of them a given run may be read from.
A contaminated channel is marked contaminated and kept. Deleting it would leave
the next reader with no way to know the measurement was ever attempted.

  * LOWEST FREE RAM during the run — CONTAMINATABLE. What the filler is measured
    by, and it answers "could this machine have run it". It moves with everything
    else on the machine: on 13 Sep 2026 an ARC evaluation loaded qwen2.5:3b and a
    browser held 1.9 GB while the suite ran, and the channel read 900 MB free for
    a suite holding 86 MB. Reported with `min_free_mb_contaminated` and the
    witnesses that made it so.
  * PEAK RSS OF THE PYTEST TREE — ALWAYS VALID. Parent plus every child. 86 MB is
    86 MB no matter what else the machine loaded, which is why the pass/fail
    threshold is taken from here and from nowhere else. It misses page cache and
    whatever the OS charges elsewhere, so it is a floor, not a ceiling.
  * OLLAMA DELTA — NOT YET MEASURED. What the suite costs in model memory, taken
    as a before/after around a run with nothing else on the machine. It cannot be
    separated from a concurrent evaluation, so it stays absent rather than wrong.

WITNESSES ARE SAMPLED, NOT ASSUMED. The harness records what else was resident
while it ran, so contamination is detected from the machine rather than declared
afterwards by whoever remembers.

    venv\Scripts\python.exe tools\bench_suite.py [pytest args...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SAMPLE_SEC = 0.5


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv):
    import psutil

    args = argv or ["test/", "-q", "--no-header", "-p", "no:cacheprovider"]
    log = BASE / "claude" / "reports" / f"SUITE_{datetime.now().strftime('%Y-%m-%d_%H%M')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    base_free = psutil.virtual_memory().available / 1048576.0
    base_pct = psutil.virtual_memory().percent
    print(f"[{_stamp()}] baseline: {base_free:.1f} MB free, {base_pct}% used")
    print(f"[{_stamp()}] log: {log}")
    print(f"[{_stamp()}] pytest {' '.join(args)}")

    fh = log.open("w", encoding="utf-8", errors="replace")
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, "-m", "pytest", *args], cwd=str(BASE),
                            stdout=fh, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    stats = {"min_free_mb": base_free, "max_used_pct": base_pct,
             "peak_tree_rss_mb": 0.0, "peak_children": 0, "samples": 0,
             "min_free_at_s": 0.0, "peak_rss_at_s": 0.0,
             "peak_foreign_rss_mb": 0.0, "witnesses": {}}
    WITNESS_FLOOR_MB = 40.0     # below this a process cannot explain a channel
    stop = threading.Event()

    def _sample():
        me = psutil.Process(proc.pid)
        while not stop.is_set():
            try:
                v = psutil.virtual_memory()
                free = v.available / 1048576.0
                el = time.time() - t0
                if free < stats["min_free_mb"]:
                    stats["min_free_mb"], stats["min_free_at_s"] = free, el
                stats["max_used_pct"] = max(stats["max_used_pct"], v.percent)
                kids = []
                try:
                    kids = me.children(recursive=True)
                    rss = me.memory_info().rss
                    for k in kids:
                        try:
                            rss += k.memory_info().rss
                        except Exception:
                            pass
                    rss /= 1048576.0
                    if rss > stats["peak_tree_rss_mb"]:
                        stats["peak_tree_rss_mb"], stats["peak_rss_at_s"] = rss, el
                    stats["peak_children"] = max(stats["peak_children"], len(kids))
                except psutil.NoSuchProcess:
                    pass
                stats["samples"] += 1
                # Every fourth sample: who else is holding memory. Cheap enough at
                # 2s, and it is the difference between "the channel is dirty" and
                # "the channel is dirty BECAUSE ollama held 2.2 GB from 16:36".
                if stats["samples"] % 4 == 0:
                    mine = {proc.pid} | {k.pid for k in kids}
                    foreign = 0.0
                    for q in psutil.process_iter(["pid", "name"]):
                        if q.info["pid"] in mine or q.info["pid"] == os.getpid():
                            continue
                        try:
                            r = q.memory_info().rss / 1048576.0
                        except Exception:
                            continue
                        if r < WITNESS_FLOOR_MB:
                            continue
                        foreign += r
                        nm = q.info["name"] or "?"
                        w = stats["witnesses"].setdefault(nm, {"n": 0, "peak_rss_mb": 0.0})
                        w["peak_rss_mb"] = max(w["peak_rss_mb"], round(r, 1))
                        w["n"] += 1
                    stats["peak_foreign_rss_mb"] = max(stats["peak_foreign_rss_mb"], foreign)
            except Exception:
                pass
            stop.wait(SAMPLE_SEC)

    th = threading.Thread(target=_sample, name="bench-suite-sampler", daemon=True)
    th.start()
    rc = proc.wait()
    stop.set()
    th.join(timeout=5)
    fh.close()
    dur = time.time() - t0

    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = [l for l in tail if " passed" in l or " failed" in l or " error" in l]
    rec = {"utc": _stamp(), "rc": rc, "duration_sec": round(dur, 1),
           "baseline_free_mb": round(base_free, 1), "baseline_used_pct": base_pct,
           "min_free_mb": round(stats["min_free_mb"], 1),
           "min_free_at_sec": round(stats["min_free_at_s"], 1),
           "max_used_pct": stats["max_used_pct"],
           "peak_tree_rss_mb": round(stats["peak_tree_rss_mb"], 1),
           "peak_rss_at_sec": round(stats["peak_rss_at_s"], 1),
           "peak_child_processes": stats["peak_children"],
           "drop_from_baseline_mb": round(base_free - stats["min_free_mb"], 1),
           "samples": stats["samples"], "log": str(log.relative_to(BASE)),
           "summary_line": summary[-1] if summary else "(no summary line)"}

    # WHICH CHANNEL MAY BE READ. Foreign load bigger than the suite's own peak
    # means the free-RAM channel is measuring the machine, not the suite.
    foreign = round(stats["peak_foreign_rss_mb"], 1)
    dirty = foreign > stats["peak_tree_rss_mb"]
    rec["peak_foreign_rss_mb"] = foreign
    rec["witnesses"] = dict(sorted(stats["witnesses"].items(),
                                   key=lambda kv: -kv[1]["peak_rss_mb"])[:12])
    rec["min_free_mb_contaminated"] = bool(dirty)
    rec["contamination_note"] = (
        f"{foreign} MB of other processes were resident while a suite holding "
        f"{rec['peak_tree_rss_mb']} MB ran; min_free_mb measures the machine, not "
        f"the suite. Kept, marked, not deleted." if dirty else
        "no process outside the pytest tree outweighed it; min_free_mb is readable")
    rec["ollama_delta_mb"] = None
    rec["ollama_delta_note"] = (
        "not measured: requires a run with nothing else on the machine")
    rec["threshold_channel"] = "peak_tree_rss_mb"
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    # A smoke test of this harness must not overwrite the night's real number.
    out = Path(os.environ.get("CORTEX_BENCH_OUT") or
               (BASE / "claude" / "reports" / "SUITE_MEMORY_LATEST.json"))
    out.write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
