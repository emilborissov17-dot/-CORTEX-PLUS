#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/watch_cycle.py — watch a cycle happen, from the trace, live.

Tails the newest file in memory/cycle_trace/ and prints, every two seconds, the
one line a human standing at the machine actually wants:

    [00:23:45] step=daily_analysis  in_step=412s  at=core/daily.py:188:fetch  RSS=108MB  free=1281MB

and once a minute the running arithmetic:

    -- 00:24:00 | 31 steps closed, 1 open | 214s unattributed | 47 files written

READ-ONLY. It opens the trace for reading and nothing else. A watcher that could
disturb the thing it watches would be the second recorder in this repo to record
its own writes.

    venv\\Scripts\\python.exe tools\\watch_cycle.py
    venv\\Scripts\\python.exe tools\\watch_cycle.py --file memory\\cycle_trace\\X.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE_DIR = REPO / "memory" / "cycle_trace"


def newest() -> Path | None:
    if not TRACE_DIR.is_dir():
        return None
    files = sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def hhmmss(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


class View:
    """Everything the printer needs, folded from the rows as they arrive."""

    def __init__(self):
        self.open = {}          # sp -> (name, t)
        self.closed = 0
        self.unattributed = 0.0
        self.files = set()
        self.spawns = 0
        self.hosts = set()
        self.last_t = 0.0
        self.last_pulse = None
        self.cycle_id = None
        self.step_name = None
        self.step_t = None

    def feed(self, r: dict) -> None:
        k = r.get("k")
        t = r.get("t_end") or r.get("t") or 0.0
        if isinstance(t, (int, float)):
            self.last_t = max(self.last_t, t)
        if k == "head":
            self.cycle_id = r.get("cycle_id")
        elif k == "open":
            self.open[r["sp"]] = (r.get("name", ""), r.get("t", 0.0))
            if str(r.get("name", "")).startswith("step:"):
                self.step_name = r["name"][5:]
                self.step_t = r.get("t", 0.0)
        elif k == "span":
            self.open.pop(r.get("sp"), None)
            if str(r.get("name", "")).startswith("step:"):
                self.closed += 1
                if self.step_name == r["name"][5:]:
                    self.step_name, self.step_t = None, None
        elif k == "ev":
            a = r.get("attr") or {}
            if r.get("name") == "pulse":
                self.last_pulse = a
                if r.get("sp") is None:
                    span = (a.get("t_end", r.get("t", 0.0)) - r.get("t", 0.0))
                    self.unattributed += max(1.0, span)
            elif r.get("name") == "touch":
                if a.get("path"):
                    self.files.add(a["path"])
            elif r.get("name") == "spawn":
                self.spawns += a.get("n", 1)
            elif r.get("name") == "connect":
                if a.get("host"):
                    self.hosts.add(a["host"])

    def line(self) -> str:
        p = self.last_pulse or {}
        step = self.step_name or "-"
        in_step = f"{self.last_t - self.step_t:.0f}s" if self.step_t is not None else "-"
        rss = p.get("rss_mb")
        free = p.get("avail_mb")
        return (f"[{hhmmss(self.last_t)}] step={step:<28} in_step={in_step:>7} "
                f"at={str(p.get('where') or '-'):<44} "
                f"RSS={('%dMB' % rss) if rss else '-':>8} "
                f"free={('%dMB' % free) if free else '-':>9}")

    def minute(self) -> str:
        return (f"-- {hhmmss(self.last_t)} | {self.closed} steps closed, "
                f"{len(self.open)} open | {self.unattributed:.0f}s unattributed | "
                f"{len(self.files)} files written | {self.spawns} children | "
                f"{len(self.hosts)} hosts")


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args(argv)

    path = Path(a.file) if a.file else newest()
    while path is None:
        print("waiting for a trace in memory/cycle_trace/ ...", flush=True)
        time.sleep(a.interval)
        path = newest()
    print(f"watching {path}", flush=True)

    view = View()
    pos = 0
    last_minute = 0.0
    while True:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                chunk = fh.readlines()
                pos = fh.tell()
        except OSError:
            chunk = []
        # A partial last line is normal while the writer is mid-write; it is
        # skipped and re-read next tick rather than guessed at.
        for line in chunk:
            line = line.strip()
            if not line:
                continue
            try:
                view.feed(json.loads(line))
            except Exception:
                pos -= len(line.encode("utf-8")) + 1
                break
        print(view.line(), flush=True)
        if view.last_t - last_minute >= 60:
            last_minute = view.last_t
            print(view.minute(), flush=True)
        time.sleep(a.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nstopped watching (the cycle is unaffected)")
