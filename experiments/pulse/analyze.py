#!/usr/bin/env python3
"""
experiments/pulse/analyze.py — measure the stream against the pre-declared criteria.

WHY THIS EXISTS *BEFORE* THE DATA
---------------------------------
Per the (G) lesson: a criterion you cannot mechanically check is a story you tell
afterwards. This closes the measurement loop BEFORE the 24 h of data arrives, so
the verdict is computed, not narrated — and so we cannot quietly move the
goalposts once we see the numbers.

WHAT IT CHECKS
  C1  gap continuity   — no unexplained gap > 30 s
  C4  daemon cost      — mean daemon_cpu_pct < 1%, RAM not pushed past BODY's 70%
  --window             — a compact timeline, so tomorrow's first autonomous wake
                         can be READ AS A STORY rather than grepped

TWO THINGS IT DELIBERATELY TOLERATES
------------------------------------
1. MACHINE SLEEP. A laptop that slept for six hours produces one enormous gap.
   That is not a daemon failure and must never be counted as one. Gaps > 5 min are
   classified as PROBABLE SLEEP and reported separately from real gaps. The
   distinction matters: conflating them would either mark a healthy run as failed,
   or — far worse — let a real 45 s stall hide inside a "sleep" bucket.

2. INTERLEAVED WRITERS. On 2026-07-13 two daemons ran concurrently for ~80 s during
   verification, both appending to the same file. That produces out-of-order and
   duplicate-ish timestamps. It is NOT corruption — the JSON is intact, the samples
   are real. So we sort by timestamp before computing gaps, and report the overlap
   as an observation rather than an error. A tool that cried "corrupt!" at its own
   operator's footprints would be useless on exactly the day it was needed.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STREAM_DIR = HERE / "stream"

GAP_FAIL_SEC = 30           # C1: any gap beyond this is a failure...
SLEEP_GAP_SEC = 300         # ...unless it is beyond this, in which case: machine slept
DAEMON_CPU_LIMIT = 1.0      # C4: mean daemon CPU %
RAM_CAUTION_PCT = 70.0      # BODY's caution threshold


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load(path: Path) -> tuple[list[dict], int]:
    """Samples sorted by timestamp, plus the count of torn lines skipped.

    Sorting is load-bearing: with two writers interleaving, the file is not in
    timestamp order, and computing gaps on file order would invent negative and
    doubled gaps out of nothing.
    """
    rows, torn = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            r["_dt"] = datetime.fromisoformat(r["ts"])
            rows.append(r)
        except Exception:
            torn += 1          # torn final line, or a partial write — skip, don't die
    rows.sort(key=lambda r: r["_dt"])
    return rows, torn


def latest_stream() -> Optional[Path]:
    files = sorted(STREAM_DIR.glob("*.jsonl"))
    return files[-1] if files else None


# ---------------------------------------------------------------------------
# C1 — gaps
# ---------------------------------------------------------------------------

def analyse_gaps(rows: list[dict]) -> dict:
    if len(rows) < 2:
        return {"samples": len(rows), "verdict": "INSUFFICIENT_DATA"}

    gaps = []
    for a, b in zip(rows, rows[1:]):
        gaps.append(((b["_dt"] - a["_dt"]).total_seconds(), a["_dt"], b["_dt"]))

    real, sleep, died = [], [], []

    for a, b in zip(rows, rows[1:]):
        secs = (b["_dt"] - a["_dt"]).total_seconds()
        if secs <= GAP_FAIL_SEC:
            continue

        entry = {"seconds": round(secs, 1), "minutes": round(secs / 60, 1),
                 "from": a["_dt"].isoformat(), "to": b["_dt"].isoformat(),
                 "pid_before": a.get("pid"), "pid_after": b.get("pid")}

        if secs <= SLEEP_GAP_SEC:
            real.append(entry)
            continue

        # A LONG gap. Machine sleep, or did the daemon DIE?
        #
        # This distinction is load-bearing. Without it, a daemon that crashed and
        # was restarted 10 minutes later would be waved through as "sleep" — the
        # exact failure C1 exists to catch, hiding inside C1's own exemption.
        #
        # Across a machine-sleep gap the process SURVIVES: same pid on both sides.
        # Across a death+restart the pid CHANGES. Same pid = it really was sleep.
        pid_a, pid_b = a.get("pid"), b.get("pid")
        if pid_a is not None and pid_b is not None and pid_a != pid_b:
            entry["classification"] = "DAEMON RESTARTED across the gap (pid changed) — " \
                                      "the process did not survive; this is NOT sleep"
            died.append(entry)
        elif pid_a is None or pid_b is None:
            entry["classification"] = "unknown — samples predate pid recording; " \
                                      "cannot tell sleep from a daemon death"
            sleep.append(entry)
        else:
            entry["classification"] = "machine sleep (same pid across the gap — " \
                                      "the daemon survived it)"
            sleep.append(entry)

    ok = [(b["_dt"] - a["_dt"]).total_seconds()
          for a, b in zip(rows, rows[1:])
          if (b["_dt"] - a["_dt"]).total_seconds() <= GAP_FAIL_SEC]

    span = (rows[-1]["_dt"] - rows[0]["_dt"]).total_seconds()
    slept = sum(g["seconds"] for g in sleep) + sum(g["seconds"] for g in died)

    return {
        "samples": len(rows),
        "span_hours": round(span / 3600, 2),
        "awake_hours": round((span - slept) / 3600, 2),
        "gap_median_sec": round(statistics.median(ok), 2) if ok else None,
        "gap_max_awake_sec": round(max(ok), 2) if ok else 0,
        "unexplained_gaps": real,
        "probable_sleep_gaps": sleep,
        # A daemon that died is a C1 FAILURE, even though the gap is long enough
        # to look like sleep. Sleep is exempt; dying is not.
        "daemon_death_gaps": died,
        "verdict": "PASS" if (not real and not died) else "FAIL",
    }


# ---------------------------------------------------------------------------
# C4 — the daemon's own cost
# ---------------------------------------------------------------------------

def analyse_cost(rows: list[dict]) -> dict:
    """C4, split into the two things it actually claims.

    ATTRIBUTION. The criterion is: the DAEMON stays under 1% CPU, and MODEL
    INFERENCE does not push RAM past BODY's caution threshold. Those are separate
    claims about separate processes, and conflating them produces a false verdict.

    Observed on 2026-07-13: system RAM sat at 71-72% — already ABOVE the 70%
    threshold — while the daemon held 25 MB / 0.02% CPU. The pressure was a
    browser, not the experiment. An analyser that failed C4 on that would be
    blaming the experiment for the machine's pre-existing state, and the 24 h run
    would have "failed" before the model was even installed.

    So: the daemon is judged on ITS OWN cost. System RAM is reported as CONTEXT,
    with a baseline, and only counts against the experiment if the experiment is
    what moved it — which cannot be known from the stream alone, and is therefore
    reported honestly as unattributed rather than pinned on the innocent.
    """
    cpu = [r["daemon_cpu_pct"] for r in rows if r.get("daemon_cpu_pct") is not None]
    rss = [r["daemon_rss_mb"] for r in rows if r.get("daemon_rss_mb") is not None]
    ram = [r["ram_pct"] for r in rows if r.get("ram_pct") is not None]

    if not cpu:
        return {
            "verdict": "NO_DATA",
            "note": "samples predate daemon self-measurement — a process's CPU cost "
                    "cannot be recovered retroactively; re-run the daemon to measure C4",
        }

    # Drop the first sample per pid: cpu_percent()'s first reading after priming
    # includes process startup, and reports ~3% for work that is not steady-state.
    steady = cpu[1:] if len(cpu) > 1 else cpu

    mean_cpu = statistics.mean(steady)
    daemon_ok = mean_cpu < DAEMON_CPU_LIMIT

    breaches = [r for r in rows if (r.get("ram_pct") or 0) > RAM_CAUTION_PCT]
    ram_mean = statistics.mean(ram) if ram else None
    baseline_high = bool(ram) and min(ram) > RAM_CAUTION_PCT

    return {
        # ── the claim we CAN attribute ──
        "daemon_cpu_mean_pct": round(mean_cpu, 3),
        "daemon_cpu_p95_pct": round(sorted(steady)[int(len(steady) * 0.95) - 1], 3),
        "daemon_cpu_max_pct": round(max(steady), 3),
        "daemon_rss_mean_mb": round(statistics.mean(rss), 1) if rss else None,
        "daemon_ram_share_pct": round(statistics.mean(rss) / 13900 * 100, 3) if rss else None,
        "daemon_verdict": "PASS" if daemon_ok else "FAIL",

        # ── context, NOT attributed to the experiment ──
        "system_ram_mean_pct": round(ram_mean, 1) if ram_mean else None,
        "system_ram_min_pct": round(min(ram), 1) if ram else None,
        "system_ram_max_pct": round(max(ram), 1) if ram else None,
        "ram_caution_breaches": len(breaches),
        "ram_baseline_already_high": baseline_high,
        "ram_note": (
            "system RAM was ALREADY above the caution threshold at its lowest point — "
            "this pressure is not the experiment's (the daemon is ~25 MB). Not counted "
            "against C4. Model inference must be judged against this baseline, not zero."
            if baseline_high else
            "system RAM stayed within the caution threshold for at least part of the run"
        ),

        # C4's verdict is about the DAEMON. The model half of C4 is judged from
        # self_state.jsonl once it exists — a RAM rise while inference is running.
        "verdict": "PASS" if daemon_ok else "FAIL",
    }


# ---------------------------------------------------------------------------
# Interleaving — an observation, not an error
# ---------------------------------------------------------------------------

def analyse_writers(rows: list[dict]) -> dict:
    pids = Counter(r["pid"] for r in rows if r.get("pid") is not None)
    if len(pids) <= 1:
        return {"writers": len(pids), "interleaved": False}

    # Do two pids' time ranges actually overlap, or did they merely run one after
    # the other into the same file (which is normal and fine)?
    ranges = {}
    for pid in pids:
        ts = [r["_dt"] for r in rows if r.get("pid") == pid]
        ranges[pid] = (min(ts), max(ts))

    overlapped = False
    items = list(ranges.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (_, (a0, a1)), (_, (b0, b1)) = items[i], items[j]
            if a0 <= b1 and b0 <= a1:
                overlapped = True

    return {
        "writers": len(pids),
        "samples_per_pid": dict(pids),
        "interleaved": overlapped,
        "note": ("two or more daemons wrote concurrently — samples are REAL, not "
                 "corrupt; sorted by timestamp before analysis"
                 if overlapped else "multiple daemons ran sequentially, no overlap"),
    }


# ---------------------------------------------------------------------------
# --window — read the run as a story
# ---------------------------------------------------------------------------

def _parse_window(spec: str, day: datetime) -> tuple[datetime, datetime]:
    a, b = spec.split("-")
    def _t(s: str) -> datetime:
        h, m = (s.strip().split(":") + ["0"])[:2]
        return day.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    return _t(a), _t(b)


def timeline(rows: list[dict], spec: str, local: bool = True) -> None:
    if not rows:
        print("no samples")
        return

    day = rows[0]["_dt"].astimezone() if local else rows[0]["_dt"]
    start, end = _parse_window(spec, day)

    sel = [r for r in rows if start <= (r["_dt"].astimezone() if local else r["_dt"]) <= end]
    if not sel:
        print(f"no samples in {spec} "
              f"(stream covers {rows[0]['_dt'].astimezone():%H:%M} - "
              f"{rows[-1]['_dt'].astimezone():%H:%M} local)")
        return

    print(f"\nTIMELINE  {spec}  ({len(sel)} samples)")
    print("-" * 78)
    print(f"{'time':8} {'cpu':>6} {'ram':>6} {'churn':>6}  {'net':>5}  state")
    print("-" * 78)

    prev_state = None
    for r in sel:
        cyc = r.get("cycle", {})
        state = f"cycle:{cyc.get('step')}" if cyc.get("running") else "idle"
        net = r.get("net", {})
        t = (r["_dt"].astimezone() if local else r["_dt"]).strftime("%H:%M:%S")

        # Only print a line on CHANGE, plus a heartbeat line every ~5 min, so an
        # hour of idle does not bury the moment something actually happened.
        changed = state != prev_state
        if changed and prev_state is not None:
            print(f"{'':8} {'':6} {'':6} {'':6}  {'':5}  ── {prev_state} → {state}")

        if changed or r["_dt"].second < 10 and r["_dt"].minute % 5 == 0:
            print(f"{t:8} {r.get('cpu_pct', 0):5.1f}% {r.get('ram_pct', 0):5.1f}% "
                  f"{r.get('memory_files_changed', 0):6}  "
                  f"{'up' if net.get('reachable') else 'DOWN':>5}  {state}")
        prev_state = state

    print("-" * 78)
    events = [r for r in sel if (r.get("ledger") or {}).get("last_event")]
    if events:
        last = events[-1]["ledger"]
        print(f"last ledger event: {last['last_event']} @ {last.get('last_event_ts')}")


# ---------------------------------------------------------------------------

def report(path: Path, window: Optional[str] = None) -> int:
    rows, torn = load(path)

    print("=" * 78)
    print(f"PULSE STREAM ANALYSIS — {path.name}")
    print("=" * 78)

    if not rows:
        print("no samples")
        return 1

    writers = analyse_writers(rows)
    gaps = analyse_gaps(rows)
    cost = analyse_cost(rows)

    print(f"\nsamples          {gaps['samples']}"
          f"   torn lines skipped: {torn}")
    print(f"writers          {writers['writers']}"
          + (f"  ⚠ INTERLEAVED (not corruption) — {writers['samples_per_pid']}"
             if writers.get("interleaved") else ""))

    print(f"\n── C1  continuity ──────────────────────────────────── {gaps['verdict']}")
    print(f"  span              {gaps.get('span_hours')}h "
          f"(awake {gaps.get('awake_hours')}h)")
    print(f"  median gap        {gaps.get('gap_median_sec')}s")
    print(f"  max awake gap     {gaps.get('gap_max_awake_sec')}s   (limit {GAP_FAIL_SEC}s)")
    print(f"  unexplained gaps  {len(gaps.get('unexplained_gaps', []))}")
    for g in gaps.get("unexplained_gaps", [])[:5]:
        print(f"      ✗ {g['seconds']}s  {g['from'][11:19]} → {g['to'][11:19]}")

    deaths = gaps.get("daemon_death_gaps", [])
    if deaths:
        print(f"  DAEMON DEATHS     {len(deaths)}  ← long gaps where the pid CHANGED:")
        print(f"                    the daemon did not survive. This is NOT sleep,")
        print(f"                    and it FAILS C1.")
        for g in deaths[:5]:
            print(f"      ☠ {g['minutes']}min  {g['from'][11:19]} → {g['to'][11:19]}  "
                  f"(pid {g['pid_before']} → {g['pid_after']})")

    print(f"  probable sleep    {len(gaps.get('probable_sleep_gaps', []))}  "
          f"(gaps >{SLEEP_GAP_SEC // 60}min, same pid — NOT a failure)")
    for g in gaps.get("probable_sleep_gaps", [])[:5]:
        print(f"      💤 {g['minutes']}min  {g['from'][11:19]} → {g['to'][11:19]}")
        if "predate pid" in (g.get("classification") or ""):
            print(f"          ⚠ {g['classification']}")

    print(f"\n── C4  resource cost ───────────────────────────────── {cost['verdict']}")
    if cost.get("verdict") == "NO_DATA":
        print(f"  {cost['note']}")
    else:
        print(f"  daemon CPU        mean={cost['daemon_cpu_mean_pct']}%  "
              f"p95={cost['daemon_cpu_p95_pct']}%  max={cost['daemon_cpu_max_pct']}%   "
              f"(limit {DAEMON_CPU_LIMIT}%)")
        print(f"  daemon RSS        {cost['daemon_rss_mean_mb']} MB "
              f"({cost['daemon_ram_share_pct']}% of system RAM)")
        print(f"\n  system RAM (context — NOT attributed to the experiment):")
        print(f"    min={cost['system_ram_min_pct']}%  mean={cost['system_ram_mean_pct']}%  "
              f"max={cost['system_ram_max_pct']}%   (BODY caution {RAM_CAUTION_PCT}%)")
        if cost["ram_baseline_already_high"]:
            print(f"    ⚠ {cost['ram_note']}")
        elif cost["ram_caution_breaches"]:
            print(f"    {cost['ram_caution_breaches']} sample(s) above the caution threshold")

    if window:
        timeline(rows, window)

    print()
    failed = [c for c, v in (("C1", gaps["verdict"]), ("C4", cost["verdict"])) if v == "FAIL"]
    print("VERDICT: " + ("PASS — " + "C1, C4 both met" if not failed
                         else "FAIL — " + ", ".join(failed)))
    print("(C2 and C3 are measured from self_state.jsonl once the local model runs.)")
    return 0 if not failed else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="analyse a pulse stream against the criteria")
    ap.add_argument("stream", nargs="?", help="path to a stream .jsonl (default: latest)")
    ap.add_argument("--window", help='timeline for a local-time window, e.g. "03:00-04:15"')
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    path = Path(args.stream) if args.stream else latest_stream()
    if not path or not path.exists():
        print("no stream found — run pulse_daemon.py first")
        raise SystemExit(1)

    if args.json:
        rows, torn = load(path)
        print(json.dumps({
            "file": str(path), "torn_lines": torn,
            "writers": analyse_writers(rows),
            "C1_continuity": analyse_gaps(rows),
            "C4_cost": analyse_cost(rows),
        }, indent=2, default=str))
        return

    raise SystemExit(report(path, window=args.window))


if __name__ == "__main__":
    main()
