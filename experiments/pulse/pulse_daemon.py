#!/usr/bin/env python3
"""
experiments/pulse/pulse_daemon.py — the sensory stream.

WHAT THIS IS
------------
The live system senses itself in SNAPSHOTS: once per cycle, it looks at itself
and writes down what it saw. This experiment tests something different — a
CONTINUOUS proprioceptive stream. Every 10 seconds, cheap local samples, appended
to a JSONL file. No LLM, no API, no network beyond one ping.

Proprioception, not introspection: this file only *senses*. Making meaning of the
stream is self_sense.py's job, and it is deliberately a separate process.

ISOLATION — READ THIS BEFORE EDITING
------------------------------------
This experiment is OUTSIDE the live cycle path, and must stay that way:

  * It WRITES only under experiments/pulse/. Nothing else. Ever.
  * It IMPORTS no live-path module. It reads their OUTPUT FILES (heartbeat.json,
    existence_ledger.jsonl) as plain JSON — deliberately NOT via
    `from memory.heartbeat import read`. An import would couple the experiment to
    live code and let a change here break the cycle. A file read cannot.
  * It has no scheduler integration. Start it by hand:
        venv/Scripts/python.exe experiments/pulse/pulse_daemon.py
  * If it earns promotion, it goes through the normal path — gates, guardian,
    review. Not by quietly growing into the cycle.

The one thing it takes from the live system is a LESSON, not a dependency: the
torn-line tolerance and fsync-on-append come from memory/existence_ledger.py,
because a sensory record lost in the page cache when the machine dies is not a
record.

Stop with Ctrl+C. It flushes and exits cleanly.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psutil

# ── Paths ───────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STREAM_DIR = HERE / "stream"

# Live-system files we OBSERVE (read-only, never written, never imported).
HEARTBEAT_FILE = REPO / "memory" / "heartbeat.json"
LEDGER_FILE    = REPO / "memory" / "existence_ledger.jsonl"
MEMORY_DIR     = REPO / "memory"

SAMPLE_INTERVAL_SEC = 10
PING_HOST = ("1.1.1.1", 53)     # Cloudflare DNS: TCP connect, no ICMP privileges needed
PING_TIMEOUT_SEC = 2.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Senses
# ---------------------------------------------------------------------------

def _sense_net(prev: Optional[dict]) -> dict:
    """Throughput since the last sample + reachability.

    Rates, not counters: "3.2 MB/s down" is a sensation; "184,203,918 bytes since
    boot" is a number nobody can feel.
    """
    io = psutil.net_io_counters()
    out: dict[str, Any] = {"bytes_sent_total": io.bytes_sent, "bytes_recv_total": io.bytes_recv}

    if prev:
        dt = max(0.001, time.time() - prev["_t"])
        out["up_kbps"]   = round((io.bytes_sent - prev["bytes_sent_total"]) / dt / 1024, 1)
        out["down_kbps"] = round((io.bytes_recv - prev["bytes_recv_total"]) / dt / 1024, 1)

    start = time.perf_counter()
    try:
        with socket.create_connection(PING_HOST, timeout=PING_TIMEOUT_SEC):
            out["reachable"] = True
            out["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
    except Exception:
        out["reachable"] = False
        out["latency_ms"] = None

    out["_t"] = time.time()
    return out


def _sense_cycle() -> dict:
    """Is a cycle running, and where is it?

    Reads memory/heartbeat.json as a plain file. A missing or torn heartbeat means
    "no cycle" — the same reading the supervisor takes, arrived at independently.
    """
    if not HEARTBEAT_FILE.exists():
        return {"running": False}
    try:
        hb = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False, "heartbeat_unreadable": True}

    age = None
    try:
        updated = datetime.fromisoformat(hb["updated_utc"])
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = round((datetime.now(timezone.utc) - updated).total_seconds(), 1)
    except Exception:
        pass

    return {
        "running": True,
        "step": hb.get("step"),
        "step_index": hb.get("step_index"),
        "heartbeat_age_sec": age,
        "pid": hb.get("pid"),
    }


def _sense_ledger() -> dict:
    """The tail of the existence ledger — the system's last remembered event.

    Reads only the final line. Torn-line tolerant, exactly as the ledger itself is:
    a half-written last line is skipped, not treated as corruption.
    """
    if not LEDGER_FILE.exists():
        return {"last_event": None}
    try:
        lines = [l for l in LEDGER_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        for line in reversed(lines):          # skip a torn final line
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            return {"last_event": ev.get("event"), "last_event_ts": ev.get("ts"),
                    "last_event_seq": ev.get("seq")}
        return {"last_event": None}
    except Exception:
        return {"last_event": None}


def _sense_memory_churn(prev_mtimes: dict) -> tuple[int, dict]:
    """How many files under memory/ changed since the last sample.

    This is the system's own thinking, felt from outside: when a cycle is writing
    proposals, snapshots and journals, churn spikes. When it is idle, churn is 0.
    """
    mtimes: dict[str, float] = {}
    try:
        for p in MEMORY_DIR.rglob("*"):
            if p.is_file():
                try:
                    mtimes[str(p)] = p.stat().st_mtime
                except OSError:
                    continue
    except Exception:
        return 0, prev_mtimes

    if not prev_mtimes:
        return 0, mtimes      # first sample has nothing to compare against

    changed = sum(1 for k, v in mtimes.items() if prev_mtimes.get(k) != v)
    return changed, mtimes


# The daemon measures its OWN cost, in-band, on every sample.
#
# This is not a nicety. Criterion C4 says the daemon must average <1% CPU — and a
# process's CPU cost CANNOT be recovered retroactively from a stream that did not
# record it. Either it is measured while running, or the criterion is unfalsifiable
# and we would be left asserting it from vibes. So the sense senses itself.
#
# psutil.Process.cpu_percent() is relative to ONE core, so 100% = one core fully
# used. We normalise by core count to get true machine-wide percent — otherwise a
# daemon using half a core on a 16-thread box would report 50% and look like a
# catastrophe when it is really 3%.
_PROC = psutil.Process()
_CPU_COUNT = psutil.cpu_count() or 1


def sample(prev_net: Optional[dict], prev_mtimes: dict) -> tuple[dict, dict, dict]:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(REPO.anchor or "C:\\"))
    net = _sense_net(prev_net)
    churn, mtimes = _sense_memory_churn(prev_mtimes)

    try:
        daemon_cpu = round(_PROC.cpu_percent(interval=None) / _CPU_COUNT, 3)
        daemon_rss = round(_PROC.memory_info().rss / 1e6, 1)
    except Exception:
        daemon_cpu, daemon_rss = None, None

    s = {
        "ts": _utc_now(),
        "pid": os.getpid(),          # so analyze.py can spot two daemons interleaving
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_pct": vm.percent,
        "ram_available_gb": round(vm.available / 1e9, 2),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "net": {k: v for k, v in net.items() if not k.startswith("_")},
        "cycle": _sense_cycle(),
        "ledger": _sense_ledger(),
        "memory_files_changed": churn,
        # ── the daemon's own cost (criterion C4) ──
        "daemon_cpu_pct": daemon_cpu,
        "daemon_rss_mb": daemon_rss,
    }
    return s, net, mtimes


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------

def stream_path(now: Optional[datetime] = None) -> Path:
    now = now or datetime.now(timezone.utc)
    return STREAM_DIR / f"{now.date().isoformat()}.jsonl"


def append(s: dict) -> None:
    """Append one sample. fsync'd — a sample lost to the page cache on a crash is
    exactly the sample that would have explained the crash."""
    STREAM_DIR.mkdir(parents=True, exist_ok=True)
    path = stream_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(s, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def run(interval: int = SAMPLE_INTERVAL_SEC, max_samples: Optional[int] = None) -> int:
    print(f"[PULSE] sensory stream starting — every {interval}s")
    print(f"[PULSE] writing to {STREAM_DIR}{os.sep}<date>.jsonl")
    print("[PULSE] Ctrl+C to stop\n")

    psutil.cpu_percent(interval=None)   # prime: the first call always returns 0.0
    _PROC.cpu_percent(interval=None)    # prime the daemon's own counter too

    prev_net: Optional[dict] = None
    prev_mtimes: dict = {}
    n = 0

    try:
        while max_samples is None or n < max_samples:
            t0 = time.time()
            try:
                s, prev_net, prev_mtimes = sample(prev_net, prev_mtimes)
                append(s)
                n += 1

                cyc = s["cycle"]
                where = f"cycle:{cyc['step']}" if cyc.get("running") else "idle"
                print(f"[PULSE] {n:5}  cpu={s['cpu_pct']:5.1f}%  ram={s['ram_pct']:5.1f}%  "
                      f"net={'up' if s['net']['reachable'] else 'DOWN'}  "
                      f"churn={s['memory_files_changed']:3}  "
                      f"self={s['daemon_cpu_pct']:.2f}%/{s['daemon_rss_mb']:.0f}MB  {where}")
            except Exception as e:
                # A sensory failure must not kill the sense. Losing one sample is
                # survivable; losing the stream is not.
                print(f"[PULSE] sample failed: {type(e).__name__}: {e}")

            # Drift-free: sleep the REMAINDER of the interval, not the interval.
            # Otherwise sampling cost accumulates and the 10s cadence slowly rots
            # into 11s, 12s — and the >30s gap criterion would fail for no reason.
            time.sleep(max(0.0, interval - (time.time() - t0)))
    except KeyboardInterrupt:
        print(f"\n[PULSE] stopped after {n} samples -> {stream_path()}")

    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="CORTEX++ pulse — continuous sensory stream")
    ap.add_argument("--interval", type=int, default=SAMPLE_INTERVAL_SEC)
    ap.add_argument("--samples", type=int, default=None, help="stop after N samples (default: forever)")
    ap.add_argument("--once", action="store_true", help="take one sample, print it, exit")
    args = ap.parse_args()

    if args.once:
        psutil.cpu_percent(interval=None)
        time.sleep(0.2)
        s, _, _ = sample(None, {})
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return

    run(interval=args.interval, max_samples=args.samples)


if __name__ == "__main__":
    main()
