#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cockpit_answer.py — RUN THE REFLEX PRODUCER. THE CALLER IT NEVER HAD.

cockpit/reflex.py was committed in 41267ee with a passing selftest and no
caller. This is the caller.

WHY A SCRIPT AND NOT A HOOK IN THE RUNNER
-------------------------------------------
The right home for the phase-boundary call is fast_cycle_runner.py, at the same
place the phase debrief is written. That file is the live cycle's own path and
is out of bounds while a cycle is running, so this exists to be run BY HAND, and
the phase hook is named in the report as still-unwired rather than pretended.

What this script can do without touching the runner:

    --drain    answer every unanswered human_input_queue row routed to the 3b
    --phase    emit one expression line for the newest phase debrief on disk
    --dry-run  show what would be called, and call nothing

PHASE BOUNDARIES ARE DETECTED FROM DISK, NOT FROM A HOOK. A new file under
memory/phase_debriefs/<cycle>/ means a phase finished. That is a real signal and
a weaker one than the runner calling us: a phase that produced no debrief is
invisible here, and two phases finishing between runs of this script produce one
line, not two. Said here rather than discovered later.

    venv/Scripts/python.exe scripts/cockpit_answer.py --drain
    venv/Scripts/python.exe scripts/cockpit_answer.py --phase
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import expression as ex      # noqa: E402
from cockpit import reflex as rx          # noqa: E402
from cockpit import vector as vec         # noqa: E402

STREAM = BASE / "memory" / "expression_stream.jsonl"
HEARTBEAT = BASE / "memory" / "heartbeat.json"
CONTRACT = BASE / "memory" / "step_contract_latest.json"
QUEUE_DB = BASE / "memory" / "human_input_queue.db"
QUARANTINE = BASE / "memory" / "expression_quarantine"
VECTOR_STORE = BASE / "memory" / "state_vectors.jsonl"
DEBRIEFS = BASE / "memory" / "phase_debriefs"
PHASE_SEEN = BASE / "memory" / "cockpit_phase_seen.json"


def glyph_now() -> dict:
    """The current glyph, or the warming state. Never fabricates one."""
    return vec.glyph_for(vec.assemble(), store_path=VECTOR_STORE)


def _read(path: pathlib.Path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def state_now() -> dict:
    """The whole state handed to the model: movers, flow, step, DEGRADED, warming.

    Assembled here rather than inside speak() because every field comes from a
    different file on disk, and speak() takes its inputs as arguments so a test
    can hand it a state without a filesystem.
    """
    heartbeat = _read(HEARTBEAT, {}) or {}
    contract = _read(CONTRACT, {}) or {}
    steps = contract.get("steps") if isinstance(contract, dict) else None
    degraded = (sum(1 for x in steps
                    if isinstance(x, dict) and x.get("verdict") == "DEGRADED")
                if isinstance(steps, list) else None)
    flow = None
    try:
        from core import flow_score as fs
        score = fs.compute()
        flow = score.as_dict() if hasattr(score, "as_dict") else dict(score)
    except Exception:
        flow = None
    return rx.current_state(STREAM, glyph_now(), heartbeat=heartbeat,
                            flow=flow, degraded=degraded)


def drain(producer: rx.ReflexProducer, db_path: pathlib.Path,
          stream_path: pathlib.Path, quarantine_root: pathlib.Path,
          dry_run: bool = False) -> list:
    """Answer unanswered 3b-routed questions. All paths REQUIRED."""
    rows = [r for r in ex.queue_read(db_path=db_path)
            if not r.get("answered") and r.get("route") == ex.ROUTE_3B]
    if dry_run:
        return [{"would_answer": r["id"], "text": r["text"]} for r in rows]

    g = glyph_now()
    st = state_now()
    out = []
    for row in rows:
        if producer.budget_left() <= 0:
            out.append({"id": row["id"], "skipped": "per-cycle budget spent"})
            break
        res = producer.speak(
            "A human asked, in the cockpit: {}".format(row["text"])[:600],
            g, None, stream_path=stream_path, quarantine_root=quarantine_root,
            state=st)
        if res["emitted"]:
            ex.queue_mark_answered(row["id"], db_path=db_path)
        out.append({"id": row["id"], "question": row["text"], **res})
    return out


def newest_phase(debriefs_dir: pathlib.Path):
    """(cycle, phase, path) for the most recent debrief file, or None."""
    if not debriefs_dir.is_dir():
        return None
    files = [p for d in debriefs_dir.iterdir() if d.is_dir()
             for p in d.glob("*.json")]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return newest.parent.name, newest.stem, newest


def phase_line(producer: rx.ReflexProducer, seen_path: pathlib.Path,
               stream_path: pathlib.Path, quarantine_root: pathlib.Path,
               debriefs_dir: pathlib.Path, dry_run: bool = False) -> dict:
    """One expression line for the newest phase debrief, once. Paths REQUIRED."""
    found = newest_phase(debriefs_dir)
    if not found:
        return {"emitted": False, "why": "no phase debrief on disk"}
    cycle, phase, path = found
    key = "{}::{}".format(cycle, phase)
    try:
        seen = json.loads(pathlib.Path(seen_path).read_text(encoding="utf-8"))
    except Exception:
        seen = {"seen": []}
    if key in (seen.get("seen") or []):
        return {"emitted": False, "why": "already spoken for {}".format(key)}
    if dry_run:
        return {"would_speak": key}

    blob = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    report = "Phase {} of cycle {}: accepted={} attempts={} seconds={}".format(
        blob.get("phase"), cycle, blob.get("accepted"), blob.get("attempts"),
        blob.get("seconds"))
    res = producer.speak(report, glyph_now(), None, stream_path=stream_path,
                         quarantine_root=quarantine_root, state=state_now())
    seen.setdefault("seen", []).append(key)
    pathlib.Path(seen_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(seen_path).write_text(json.dumps(seen, ensure_ascii=False,
                                                  indent=2), encoding="utf-8")
    return {"phase": key, **res}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the reflex producer by hand.")
    ap.add_argument("--drain", action="store_true",
                    help="answer unanswered questions in human_input_queue.db")
    ap.add_argument("--phase", action="store_true",
                    help="emit one line for the newest phase debrief")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be called; call nothing")
    args = ap.parse_args(argv)
    if not (args.drain or args.phase):
        ap.print_help()
        return 0

    producer = rx.ReflexProducer()
    print("lexicon: {}".format(glyph_now()["label"]))

    if args.drain:
        for r in drain(producer, QUEUE_DB, STREAM, QUARANTINE,
                       dry_run=args.dry_run):
            print(json.dumps(r, ensure_ascii=False)[:400])
    if args.phase:
        print(json.dumps(
            phase_line(producer, PHASE_SEEN, STREAM, QUARANTINE, DEBRIEFS,
                       dry_run=args.dry_run), ensure_ascii=False)[:400])
    print("model calls made: {}".format(producer.calls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
