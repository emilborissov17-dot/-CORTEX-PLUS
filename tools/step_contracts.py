#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""tools/step_contracts.py — a step's contract, harvested from a trace it left.

B4 STEP 1. 44 of the 75 steps in the map have a measured contract; 31 have none,
because they are inline blocks that never call _run(). core/flight_recorder now
gives every step a boundary from beat(), so a trace can finally say, for each of
them: how long it took, which files it read, where it went on the network, and
what it wrote. That set is the contract.

WHY NOT memory/step_contract_latest.json, WHICH IS WHERE THE BRIEF SAID TO WRITE.
Measured, not assumed: core/step_contract.py:_append_report appends to that file
during a cycle, and archive_and_reset() empties it into memory/steps/ at the
start of the next one. A contract written there is filed away by morning. It is
also read by cycle_integrity, flow_score, phase_evidence and self_mirror, and
cycle_integrity.is_full() treats any verdict that is not OK as a failed step — so
a new row type dropped in there changes an integrity score that means something
else. The durable home is a file of its own, and --also-latest still appends to
the window for anyone watching it live.

WHAT A REFUSAL LOOKS LIKE. A step whose span carries no reads, no writes, no
network and no subprocess is NOT given a contract. It goes to
memory/dead_steps.json and is reported. A contract invented for a step that does
nothing is worse than no contract: it would be a hash that always matches, and a
step that is skipped for ever on the strength of it.

THE HONEST GAP, stated rather than filled. `params` — dates, windows, the things
that make yesterday's answer wrong today — cannot be observed from outside. A
trace sees the file that was opened, not the date that was passed. Every contract
carries params: [] with the reason attached, and STEP 3 (the hash) must take them
from the step's own code. Filling them with a guess here would be the exact
failure this file exists to avoid.

    venv\Scripts\python.exe tools\step_contracts.py                 # newest trace, dry
    venv\Scripts\python.exe tools\step_contracts.py --trace X --write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

TRACE_DIR = BASE / "memory" / "cycle_trace"
MEASURED = BASE / "memory" / "step_contracts_measured.json"
DEAD = BASE / "memory" / "dead_steps.json"
LATEST = BASE / "memory" / "step_contract_latest.json"

WRITE_EVENTS = ("open-w", "open-a", "open-x", "rename", "remove", "mkdir")


def _show(p) -> str:
    """A path for a human. relative_to() RAISES on anything outside the repo, and
    the tests point these at a tmp dir — a printer that can abort the write it is
    announcing is not a printer."""
    p = Path(p)
    try:
        return str(p.relative_to(BASE))
    except ValueError:
        return str(p)


def _canon(name: str) -> str:
    try:
        from core.cycle_map import _canon as c
        return c(name)
    except Exception:
        return name


def newest_trace() -> Path | None:
    if not TRACE_DIR.is_dir():
        return None
    files = sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def read_trace(path: Path) -> tuple[dict, list]:
    head, rows = {}, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("k") == "head":
            head = r
        else:
            rows.append(r)
    return head, rows


def harvest(path: Path) -> dict:
    """One trace in, one contract per step out. Judges nothing but 'dead'."""
    head, rows = read_trace(path)
    channels = head.get("channels") or []
    reads_on = "read" in channels

    spans = [r for r in rows if r.get("k") == "span"
             and str(r.get("name", "")).startswith(("step:", "stepb:"))]
    events = [r for r in rows if r.get("k") == "ev"]
    by_span: dict[str, list] = {}
    for e in events:
        by_span.setdefault(e.get("sp"), []).append(e)

    out: dict[str, dict] = {}
    for s in spans:
        label = s["name"].split(":", 1)[1]
        canon = _canon(label)
        src = "_run" if s["name"].startswith("step:") else "beat"
        ev = by_span.get(s["sp"], [])

        files_read, files_written, network, spawns = set(), set(), set(), set()
        for e in ev:
            a = e.get("attr") or {}
            if e.get("name") == "read" and a.get("path"):
                files_read.add(a["path"])
            elif e.get("name") == "touch" and a.get("path"):
                if str(a.get("ev", "")) in WRITE_EVENTS:
                    files_written.add(a["path"])
            elif e.get("name") == "connect":
                host = a.get("host")
                if host:
                    network.add(f"{host}:{a.get('port')}" if a.get("port") else str(host))
            elif e.get("name") == "spawn":
                argv = a.get("argv") or []
                if argv:
                    spawns.add(str(argv[0])[:120])

        c = out.get(canon)
        if c is None:
            c = out[canon] = {
                "step": canon, "index": (s.get("attr") or {}).get("index"),
                "measured_seconds": None, "span_status": s.get("st"),
                "source": src,
                "inputs": {"files": [], "network": [], "params": [],
                           "params_why": ("not observable from a trace: a date or "
                                          "window is passed in the step's own code, "
                                          "not opened as a file")},
                "outputs": [], "spawns": [], "events_attributed": 0,
                "reads_recorded": reads_on,
            }
        elif c["source"] != src:
            c["source"] = "both"

        # PREFER THE _run SPAN FOR THE DURATION. The beat span wraps it, so it
        # also carries whatever ran between the beat and the step body.
        secs = round((s.get("ms") or 0) / 1000.0, 3)
        if c["measured_seconds"] is None or src == "_run":
            c["measured_seconds"] = secs
            c["span_status"] = s.get("st")

        c["inputs"]["files"] = sorted(set(c["inputs"]["files"]) | files_read)
        c["inputs"]["network"] = sorted(set(c["inputs"]["network"]) | network)
        c["outputs"] = sorted(set(c["outputs"]) | files_written)
        c["spawns"] = sorted(set(c["spawns"]) | spawns)
        c["events_attributed"] += len(ev)

    for c in out.values():
        touched_nothing = not (c["inputs"]["files"] or c["inputs"]["network"]
                               or c["outputs"] or c["spawns"])
        if not reads_on and touched_nothing:
            # REFUSE TO JUDGE. A step that only READS and prints — a self-check,
            # an audit, a reconciler — writes nothing and calls nobody. On a
            # trace with the read channel off it is indistinguishable from a step
            # that does nothing at all, and calling it dead would put a working
            # audit on a list headed "to be REMOVED". Unknown is the honest
            # answer and it is cheap to fix: run again with CORTEX_TRACE_READS=1.
            c["dead"] = None
            c["dead_why"] = ("cannot be judged: the read channel was off, so a "
                             "step that only reads looks the same as a step that "
                             "does nothing")
        else:
            c["dead"] = bool(touched_nothing)
            c["dead_why"] = ("touched no file, opened no connection and spawned "
                             "nothing while its span was open"
                             if c["dead"] else None)
    return {"trace": _show(path),
            "cycle_id": head.get("cycle_id"), "trace_t0": head.get("t0"),
            "channels": channels, "reads_recorded": reads_on,
            "steps": out}


def merge(previous: dict, fresh: dict) -> dict:
    """Newest measurement wins per step; a step absent tonight keeps yesterday's."""
    steps = dict((previous or {}).get("steps") or {})
    steps.update(fresh["steps"])
    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_trace": fresh["trace"], "last_cycle_id": fresh["cycle_id"],
            "reads_recorded": fresh["reads_recorded"], "steps": steps}


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", default=None)
    ap.add_argument("--write", action="store_true",
                    help="persist; without it nothing is written (house rule)")
    ap.add_argument("--also-latest", action="store_true",
                    help="also append into memory/step_contract_latest.json")
    a = ap.parse_args(argv)

    path = Path(a.trace) if a.trace else newest_trace()
    if path is None or not path.is_file():
        print("no trace to read")
        return 2

    fresh = harvest(path)
    live = [c for c in fresh["steps"].values() if c["dead"] is False]
    dead = [c for c in fresh["steps"].values() if c["dead"] is True]
    unjudged = [c for c in fresh["steps"].values() if c["dead"] is None]

    print(f"trace              : {fresh['trace']}")
    print(f"channels           : {', '.join(fresh['channels']) or '(none)'}")
    if not fresh["reads_recorded"]:
        print("  NOTE: the read channel was OFF for this trace, so inputs.files is "
              "empty for every step — that is 'not recorded', not 'reads nothing'.")
    print(f"steps with a span  : {len(fresh['steps'])}")
    print(f"  contracted       : {len(live)}")
    print(f"  DEAD (no contract): {len(dead)}")
    if unjudged:
        print(f"  cannot be judged   : {len(unjudged)} "
              f"(the read channel was off; rerun with CORTEX_TRACE_READS=1)")
    print()
    print(f"{'step':<32}{'sec':>9}{'in':>5}{'net':>5}{'out':>5}  source")
    for c in sorted(fresh["steps"].values(),
                    key=lambda c: -(c["measured_seconds"] or 0)):
        print(f"{c['step'][:31]:<32}{(c['measured_seconds'] or 0):>9.2f}"
              f"{len(c['inputs']['files']):>5}{len(c['inputs']['network']):>5}"
              f"{len(c['outputs']):>5}  {c['source']}"
              f"{'   DEAD' if c['dead'] else ('   ?' if c['dead'] is None else '')}")

    if not a.write:
        print()
        print("DRY RUN — nothing written. Add --write.")
        return 0

    # ONLY A STEP JUDGED ALIVE EARNS A CONTRACT. A dead one would carry empty
    # inputs, its hash would match every night, and it would be skipped for ever
    # instead of being removed. An unjudged one is worse: it is not known to be
    # dead, and a contract with unknown inputs is the same always-matching hash
    # wearing a respectable face.
    keep = {"steps": {k: v for k, v in fresh["steps"].items() if v["dead"] is False},
            "trace": fresh["trace"], "cycle_id": fresh["cycle_id"],
            "reads_recorded": fresh["reads_recorded"]}
    merged = merge(_load(MEASURED), keep)
    MEASURED.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    dead_blob = _load(DEAD)
    known = dict(dead_blob.get("steps") or {})
    for c in dead:
        known[c["step"]] = {"why": c["dead_why"], "seen": fresh["cycle_id"],
                            "measured_seconds": c["measured_seconds"]}
    DEAD.write_text(json.dumps(
        {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "why": ("a step that touches nothing gets no contract: its hash would "
                 "always match and it would be skipped for ever. These are to be "
                 "REMOVED, not skipped."),
         "steps": known}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {_show(MEASURED)} ({len(merged['steps'])} steps) "
          f"and {_show(DEAD)} ({len(known)} dead)")

    if a.also_latest:
        blob = _load(LATEST) or {"steps": []}
        rows = [r for r in blob.get("steps", [])
                if r.get("step") not in {c["step"] for c in live}]
        for c in live:
            rows.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "step": c["step"], "seconds": c["measured_seconds"],
                # OK, deliberately: cycle_integrity.is_full() reads any other
                # verdict as a failed step, and these rows are measurements, not
                # verdicts about the night.
                "verdict": "OK" if c["span_status"] == "OK" else "DEGRADED",
                "why": f"harvested from {fresh['trace']}",
                "touched": c["outputs"], "touched_count": len(c["outputs"]),
                "error": None, "degraded": None, "degraded_calls": 0,
                "runs_recorded": 1, "inputs": c["inputs"], "source": "trace",
            })
        blob["steps"] = rows[-200:]
        LATEST.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(f"appended {len(live)} rows to {_show(LATEST)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
