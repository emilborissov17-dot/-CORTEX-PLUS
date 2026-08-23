#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cockpit_answer.py — RUN THE REFLEX PRODUCER BY HAND. THE FALLBACK.

cockpit/reflex.py was committed in 41267ee with a passing selftest and no
caller. This was the first caller, and for one day it was the only one.

THE PHASE HOOK NOW LIVES WHERE IT BELONGS (23 Aug 2026)
---------------------------------------------------------
core/phase_tracker._close() calls cockpit/phase_voice.on_phase_close() at every
phase boundary, from beat(), from the runner. That is the real hook, and it sees
what this script could not:

    a phase that produced NO debrief — invisible to a file watcher, and the
    phase most worth a line, because a rejected debrief is a fact about it;
    two phases closing between two runs of this script — one line here, two
    there.

WHAT THIS IS STILL FOR
-----------------------
A hook only fires while a cycle runs. By hand, after the fact:

    --drain    answer every unanswered human_input_queue row routed to the 3b
    --phase    emit one expression line for the newest phase debrief on disk
    --dry-run  show what would be called, and call nothing

--phase still detects boundaries from disk, with the same two blind spots named
above. That is what makes it a fallback and not the mechanism.

The state handed to the model is assembled in cockpit/phase_voice.py and
imported here. Two copies of "what the model is told about now" would drift, and
both would keep working while they drifted.

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
from cockpit import phase_voice as pv     # noqa: E402
from cockpit import reflex as rx          # noqa: E402

STREAM = BASE / "memory" / "expression_stream.jsonl"
HEARTBEAT = BASE / "memory" / "heartbeat.json"
CONTRACT = BASE / "memory" / "step_contract_latest.json"
QUEUE_DB = BASE / "memory" / "human_input_queue.db"
QUARANTINE = BASE / "memory" / "expression_quarantine"
VECTOR_STORE = BASE / "memory" / "state_vectors.jsonl"
DEBRIEFS = BASE / "memory" / "phase_debriefs"
PHASE_SEEN = BASE / "memory" / "cockpit_phase_seen.json"


def glyph_now() -> dict:
    """The current glyph, or the warming state. One implementation, in the hook."""
    return pv.glyph_now(VECTOR_STORE)


def _read(path: pathlib.Path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def state_now() -> dict:
    """The whole state handed to the model — the SAME assembly the hook uses.

    This used to be a second copy of cockpit/phase_voice.state_from_disk(). Two
    assemblies of "what the model is told about now" drift, and nothing fails
    while they do: both keep producing a state, and the hand-run line stops
    describing the same machine as the hooked one.
    """
    return pv.state_from_disk(STREAM, HEARTBEAT, CONTRACT, VECTOR_STORE)


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
    # ONE KEY BUILDER, IN THE HOOK. `cycle` here is already the mangled folder
    # name, so seen_key's normalisation is a no-op on it — which is exactly the
    # property that makes the hook's raw cycle_id land on the same string.
    key = pv.seen_key(cycle, phase)
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
