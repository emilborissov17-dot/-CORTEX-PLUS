#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/glass.py — A WINDOW, NOT A SENSE.

23 Aug 2026.

Three panels, each rendering something that ALREADY FLOWS:

  1. RAW STDOUT           the live cycle log, unfiltered and unformatted
  2. BLOCKED CONNECTIONS  the tail of pfirewall.log, with the pid column
  3. TRAFFIC COUNTERS     from the reading the cockpit already took

THE HARD CONSTRAINT: THIS TAB ADDS ZERO NEW SENSOR PROBES.
------------------------------------------------------------
Not "few". Zero. It subscribes to the bus or reads a cache that another
component filled; it never calls somatic.probe(), read_ram_free_mb() or
read_disk_free_pct(). This is the bug from two days ago by name: /api/somatic
probed every 15 seconds and threw the readings away, so the panel that was
supposed to display the body was instead a second, disagreeing body.

A viewer is a visitor with the chart, not a nurse with a thermometer.

The constraint is measured, not asserted. core/event_bus.py counts every
guarded probe, and test/test_glass.py takes that count with the tab shut and
again after rendering it repeatedly. The numbers have to be identical.

IT SAYS WHAT IT IS, ON SCREEN
-------------------------------
    Render of existing numbers. Mediation 1.0. Not expression.

Mediation 1.0 means nothing has been compressed, ranked, judged or phrased.
The pulse stream is mediated — it decides what earns a line. The expression
window is mediated further — a model chooses words. This is the raw article,
and labelling it stops it from being mistaken for the other two.

WHY "BLOCKED CONNECTIONS" AND NEVER "ATTACKS"
-----------------------------------------------
Every row in that log today is a DROP, and the newest is
`192.168.2.1 -> 239.255.255.250:1900` — SSDP multicast from the router
announcing itself. Most of the rest is internet background noise, and some of
it is Emil's own software being denied a port it asked for. Calling that an
attack would be a lie that makes the panel feel important. The log carries a
`path` and a `pid` column, so where a row CAN be attributed to a process, it is.

    venv/Scripts/python.exe -m cockpit.glass --selftest
"""
from __future__ import annotations

import pathlib
import sys
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LABEL = "Render of existing numbers. Mediation 1.0. Not expression."
MEDIATION = 1.0

CYCLE_LOG_DIR = BASE / "memory" / "cycle_logs"
STDOUT_TAIL_LINES = 200
FIREWALL_TAIL_ROWS = 40


# ---------------------------------------------------------------------------
# 1. Raw stdout
# ---------------------------------------------------------------------------

def newest_cycle_log(log_dir: Optional[pathlib.Path] = None):
    d = pathlib.Path(log_dir or CYCLE_LOG_DIR)
    try:
        logs = sorted((f for f in d.glob("cycle_*.log") if f.is_file()),
                      key=lambda f: f.stat().st_mtime)
    except OSError:
        return None
    return logs[-1] if logs else None


def stdout_tail(n: int = STDOUT_TAIL_LINES,
                log_dir: Optional[pathlib.Path] = None) -> dict:
    """The live cycle log, unfiltered.

    NO LAUNCH CHANGE WAS NEEDED and Part 0 established why: both paths already
    write this file line by line. supervisor.spawn_cycle() opens it with mode
    "w" before the spawn and runs the child with PYTHONUNBUFFERED=1; a
    hand-started cycle tees through core/cycle_log.py, which flushes after
    every write. So a tail is enough, and reading a file is not a probe.
    """
    out = {"panel": "raw stdout", "path": None, "lines": [], "bytes": 0,
           "why": "", "mediation": MEDIATION}
    p = newest_cycle_log(log_dir)
    if p is None:
        out["why"] = "no cycle log in {} yet".format(log_dir or CYCLE_LOG_DIR)
        return out
    out["path"] = str(p)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out["why"] = "{}: {}".format(type(exc).__name__, exc)
        return out
    out["bytes"] = len(raw)
    lines = raw.splitlines()
    out["lines"] = lines[-n:]
    out["truncated"] = len(lines) > n
    out["total_lines"] = len(lines)
    return out


# ---------------------------------------------------------------------------
# 2. Blocked connections
# ---------------------------------------------------------------------------

def blocked_connections(n: int = FIREWALL_TAIL_ROWS,
                        path: Optional[pathlib.Path] = None,
                        since: int = 0) -> dict:
    """The firewall log tail. Reading a file the OS already writes.

    `since` is a row offset, so the panel can ask for only what ARRIVED and
    draw a spark per new row rather than redrawing the whole tail. Part 0.5
    proved this does not lock the file: with our reader handle held open, a
    concurrent append succeeded and the held reader saw the new bytes.
    """
    from core import receptors as rc
    raw = rc.read_firewall_drops(path=path, since_offset=since)
    out = {"panel": "blocked connections", "available": raw["available"],
           "total": raw["count"], "rows": [], "why": raw["why"],
           "mediation": MEDIATION,
           "note": ("Most of this is internet background noise and some of it "
                    "is your own software being denied a port. It is not an "
                    "attack log.")}
    out["offset"] = raw.get("offset", 0)
    out["new"] = len(raw["rows"] or [])
    rows = raw["rows"][-n:] if raw["rows"] else []
    for r in rows:
        out["rows"].append({
            "date": r.get("date", ""), "time": r.get("time", ""),
            "action": r.get("action", ""), "protocol": r.get("protocol", ""),
            "src": r.get("src-ip", ""), "dst": r.get("dst-ip", ""),
            "src_port": r.get("src-port", ""), "dst_port": r.get("dst-port", ""),
            "direction": r.get("path", ""),
            "pid": r.get("pid", ""),
            "process": _process_for(r.get("pid")),
        })
    # THE COUNTERS GO UNDER THE SPARKS, not above them. The arrivals are the
    # panel; a total is context for them, and context that sits on top becomes
    # the headline.
    from collections import Counter
    out["counters"] = {
        "by_action": dict(Counter(r["action"] for r in out["rows"] if r["action"])),
        "by_protocol": dict(Counter(r["protocol"] for r in out["rows"] if r["protocol"])),
        "by_process": dict(Counter(r["process"] for r in out["rows"] if r["process"]).most_common(6)),
        "by_port": dict(Counter(r["dst_port"] for r in out["rows"] if r["dst_port"]).most_common(6)),
    }
    return out


_PID_CACHE: dict = {}


def _process_for(pid) -> str:
    """A pid is only a number until it has a name. psutil.Process(pid).name()
    is a lookup of a process the OS already has, not a probe of the machine's
    state — but it is cached anyway, because the log repeats pids and this
    panel redraws."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ""
    if pid in _PID_CACHE:
        return _PID_CACHE[pid]
    name = ""
    try:
        import psutil
        name = psutil.Process(pid).name()
    except Exception:
        name = "(gone)"
    _PID_CACHE[pid] = name
    return name


# ---------------------------------------------------------------------------
# 3. Traffic counters — FROM THE STREAM, NEVER A FRESH PROBE
# ---------------------------------------------------------------------------

def traffic(last_reading: Optional[dict] = None,
            history_path: Optional[pathlib.Path] = None) -> dict:
    """Network counters from the reading the cockpit ALREADY took.

    Two sources, in order, and neither is a probe:
      1. `last_reading` — the dict /api/somatic filled on its own last call;
      2. memory/somatic_history.jsonl — what cockpit/norms.record() persisted.

    If neither has anything, this panel says so. It does NOT reach for
    psutil.net_io_counters(): a number nobody else has seen is a second body.
    """
    keys = ("net_sent_mb", "net_recv_mb", "connections", "wifi_signal_pct",
            "gateway_ping_ms")
    out = {"panel": "traffic counters", "source": None, "values": {},
           "series": {}, "why": "", "mediation": MEDIATION}

    if last_reading:
        vals = {k: last_reading.get(k) for k in keys if k in last_reading}
        if any(v is not None for v in vals.values()):
            out["source"] = "the cockpit's own last reading"
            out["values"] = vals

    try:
        from cockpit import norms as nm
        hist = nm.history(history_path or nm.HISTORY)
    except Exception as exc:
        hist = {}
        out["why"] = "{}: {}".format(type(exc).__name__, exc)

    for k in keys:
        series = [v for v in (hist.get(k) or []) if isinstance(v, (int, float))]
        if series:
            out["series"][k] = series[-60:]
            if out["values"].get(k) is None:
                out["values"][k] = series[-1]
                out["source"] = out["source"] or "memory/somatic_history.jsonl"

    if not out["values"]:
        out["why"] = out["why"] or (
            "nothing has read the network yet this session — this panel waits "
            "for a reading rather than taking one")
    return out


# ---------------------------------------------------------------------------

def render(last_reading: Optional[dict] = None) -> dict:
    """Everything the tab needs, in one call. Reads files and caches only."""
    return {"label": LABEL, "mediation": MEDIATION,
            "stdout": stdout_tail(),
            "blocked": blocked_connections(),
            "traffic": traffic(last_reading)}


def _selftest() -> int:
    from core import event_bus as eb
    print("cockpit/glass.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    before = eb.probe_count()
    for _ in range(5):
        d = render()
    after = eb.probe_count()

    check("five renders add ZERO sensor probes ({} -> {})".format(before, after),
          after == before)
    check("it says what it is", d["label"] == LABEL and d["mediation"] == 1.0)
    check("panel 1 names a real cycle log",
          d["stdout"]["path"] is not None or d["stdout"]["why"])
    check("panel 2 read the firewall log", d["blocked"]["available"] is True)
    check("panel 2 carries the pid column",
          not d["blocked"]["rows"] or "pid" in d["blocked"]["rows"][0])
    check("panel 2 does not call them attacks",
          "attack" not in str(d["blocked"]).lower().replace(
              "not an attack log", ""))
    check("panel 3 came from a cache, not a probe",
          d["traffic"]["source"] is not None or d["traffic"]["why"])

    print("\n  stdout   {} line(s) from {}".format(
        len(d["stdout"]["lines"]),
        pathlib.Path(d["stdout"]["path"]).name if d["stdout"]["path"] else "-"))
    print("  blocked  {} of {} row(s)".format(
        len(d["blocked"]["rows"]), d["blocked"]["total"]))
    print("  traffic  {} -> {}".format(
        d["traffic"]["source"], list(d["traffic"]["values"])))
    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
