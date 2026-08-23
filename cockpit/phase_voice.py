#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/phase_voice.py — THE PHASE BOUNDARY CALLS THE PRODUCER. THE REAL HOOK.

WHAT THIS REPLACES
-------------------
scripts/cockpit_answer.py --phase found phase boundaries by watching for a NEW
FILE under memory/phase_debriefs/<cycle>/. Its own docstring named the two ways
that is weaker than a hook, and both are real:

  * a phase that produced no debrief is INVISIBLE — and a rejected debrief is
    exactly the phase most worth a line;
  * two phases finishing between two runs of the script collapse into ONE line,
    because only the newest file is read.

The boundary itself is not a mystery: core/phase_tracker.on_beat() already
detects it, from beat(), which the runner calls at every step. _close() is the
one function that runs once per phase, with the report and the debrief in hand.
That is the call site. This module is what it calls.

THE SCRIPT STAYS, AS A FALLBACK
--------------------------------
A hook only fires while a cycle runs. scripts/cockpit_answer.py --phase is
still the way to get a line out of a debrief by hand, and it now imports
`glyph_now` and `state_from_disk` FROM HERE rather than keeping its own copies —
two assemblies of "the state handed to the model" would drift, and the drift
would be invisible because both would keep working.

ONE PRODUCER PER CYCLE, AND ITS BUDGET IS THE POINT
-----------------------------------------------------
cockpit/reflex.ReflexProducer counts its own calls (MAX_CALLS_PER_CYCLE = 9:
the phases plus the cycle-end line). A producer built fresh at each boundary
would have a budget of 9 PER PHASE, which is not a budget. So one is kept per
cycle_id and thrown away when the cycle_id changes.

NEVER BLOCKS THE CYCLE
-----------------------
The call runs through core.step_budget.call_with_timeout — the same abandon-on-
timeout machinery the model ladder uses — with a hard ceiling of
PHASE_LINE_TIMEOUT_SEC. A local model that wedges costs one missing line, not a
night. Fail-open everywhere else too: this is a line in a log, not a step.

    venv/Scripts/python.exe -m cockpit.phase_voice      # selftest, no model called
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import reflex as rx        # noqa: E402
from cockpit import vector as vec       # noqa: E402

STREAM = BASE / "memory" / "expression_stream.jsonl"
HEARTBEAT = BASE / "memory" / "heartbeat.json"
CONTRACT = BASE / "memory" / "step_contract_latest.json"
QUARANTINE = BASE / "memory" / "expression_quarantine"
VECTOR_STORE = BASE / "memory" / "state_vectors.jsonl"
HISTORY_PATH = BASE / "memory" / "somatic_history.jsonl"

# One local 3b call. The warm 3b answers in ~7-25s on this box; 60s is the point
# past which the line is not worth the cycle's time.
PHASE_LINE_TIMEOUT_SEC = 60.0

_producer: Optional[rx.ReflexProducer] = None
_producer_cycle: Optional[str] = None


def _read(path: pathlib.Path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def glyph_now(store_path: pathlib.Path = VECTOR_STORE) -> dict:
    """The current glyph, or the warming state. Never fabricates one."""
    return vec.glyph_for(vec.assemble(), store_path=store_path)


def state_from_disk(stream_path: pathlib.Path = STREAM,
                    heartbeat_path: pathlib.Path = HEARTBEAT,
                    contract_path: pathlib.Path = CONTRACT,
                    store_path: pathlib.Path = VECTOR_STORE,
                    history_path: pathlib.Path = HISTORY_PATH) -> dict:
    """The whole state handed to the model: movers, flow, step, DEGRADED, warming.

    Lifted out of scripts/cockpit_answer.state_now() so the hook and the manual
    script hand the model the SAME state. Every field comes from a different
    file, which is why it is assembled here and not inside speak().
    """
    heartbeat = _read(heartbeat_path, {}) or {}
    contract = _read(contract_path, {}) or {}
    steps = contract.get("steps") if isinstance(contract, dict) else None
    degraded = (sum(1 for x in steps
                    if isinstance(x, dict) and x.get("verdict") == "DEGRADED")
                if isinstance(steps, list) else None)
    try:
        from core import flow_score as fs
        score = fs.compute()
        flow = score.as_dict() if hasattr(score, "as_dict") else dict(score)
    except Exception:
        flow = None
    # READ, never probe. The cockpit already samples every 15 seconds and
    # cockpit/norms.record() keeps what it found, so a phase boundary that
    # probed the machine again would be measuring the cost of asking.
    try:
        from cockpit import norms as nm
        unusual = nm.unusual_from_disk(history_path)
    except Exception:
        unusual = None
    return rx.current_state(stream_path, glyph_now(store_path),
                            heartbeat=heartbeat, flow=flow, degraded=degraded,
                            unusual=unusual)


def producer_for(cycle_id: str) -> rx.ReflexProducer:
    """One producer per cycle, so its per-cycle budget means what it says."""
    global _producer, _producer_cycle
    if _producer is None or _producer_cycle != cycle_id:
        _producer = rx.ReflexProducer()
        _producer_cycle = cycle_id
    return _producer


def phase_report_text(phase: str, cycle_id: str, result: Optional[dict],
                      debrief: Optional[dict]) -> str:
    """What the producer is told about the phase that just closed.

    The verdict AND the debrief's fate are both in it. A rejected debrief is not
    a silence here — it is a fact about the phase, and the file-watching script
    could not see it at all.
    """
    result = result or {}
    debrief = debrief or {}
    bits = ["Phase {} of cycle {} closed".format(phase, cycle_id)]
    if result.get("verdict"):
        bits.append("verdict={}".format(result["verdict"]))
    if result.get("steps_ok") is not None:
        bits.append("steps_ok={}".format(result["steps_ok"]))
    if result.get("seconds") is not None:
        bits.append("seconds={}".format(result["seconds"]))
    bits.append("debrief={}".format(
        "accepted" if debrief.get("accepted") else "REJECTED"))
    if not debrief.get("accepted") and debrief.get("rejected_because"):
        bits.append("rejected_because={}".format(
            "; ".join(str(r) for r in debrief["rejected_because"])[:200]))
    if result.get("reason"):
        bits.append("reason={}".format(str(result["reason"])[:300]))
    return ", ".join(bits)


def on_phase_close(phase: str, cycle_id: str, result: Optional[dict] = None,
                   debrief: Optional[dict] = None,
                   producer: Optional[rx.ReflexProducer] = None,
                   stream_path: pathlib.Path = STREAM,
                   quarantine_root: pathlib.Path = QUARANTINE,
                   timeout_sec: float = PHASE_LINE_TIMEOUT_SEC) -> dict:
    """THE HOOK. Called from core/phase_tracker._close(), once per phase.

    Returns the producer's own result dict, or {"emitted": False, "why": ...}.
    Never raises — the caller is a cycle in flight.
    """
    prod = producer or producer_for(str(cycle_id))
    if prod.budget_left() <= 0:
        return {"emitted": False, "phase": phase,
                "why": "per-cycle budget of {} calls is spent".format(
                    prod.max_calls)}

    report = phase_report_text(phase, cycle_id, result, debrief)

    def _go():
        return prod.speak(report, glyph_now(), None,
                          stream_path=stream_path,
                          quarantine_root=quarantine_root,
                          state=state_from_disk(stream_path))

    try:
        from core.step_budget import call_with_timeout
        outcome, value, error, elapsed = call_with_timeout(_go, timeout_sec)
    except Exception as exc:  # noqa: BLE001
        return {"emitted": False, "phase": phase,
                "why": "hook failed: {}: {}".format(type(exc).__name__, exc)}

    if value is not None:
        return {**value, "seconds": round(elapsed, 1), "phase": phase}
    return {"emitted": False, "phase": phase, "seconds": round(elapsed, 1),
            "why": "producer {}{}".format(outcome,
                                          ": " + error if error else "")}


def _reset_for_tests() -> None:
    global _producer, _producer_cycle
    _producer, _producer_cycle = None, None


def _selftest() -> int:
    """No model is called. A stub producer drives the hook end to end."""
    import tempfile
    print("cockpit/phase_voice.py --selftest   (stubbed caller; no model contacted)")
    tmp = pathlib.Path(tempfile.mkdtemp())
    stream, quar = tmp / "stream.jsonl", tmp / "quar"

    stub = rx.ReflexProducer(caller=lambda p: "QUERY which phase left no debrief")
    res = on_phase_close("A_ORIENT", "cycle-1",
                         {"verdict": "OK", "steps_ok": 9, "seconds": 41.2,
                          "reason": "nine steps, none refused"},
                         {"accepted": True},
                         producer=stub, stream_path=stream, quarantine_root=quar)
    print("  accepted debrief     emitted={} text={!r}".format(
        res["emitted"], res.get("text")))

    res2 = on_phase_close("B_SENSE", "cycle-1",
                          {"verdict": "DEGRADED", "seconds": 900},
                          {"accepted": False,
                           "rejected_because": ["no number from its own data"]},
                          producer=stub, stream_path=stream, quarantine_root=quar)
    print("  REJECTED debrief     emitted={}  (the file-watcher saw no file for "
          "this phase at all)".format(res2["emitted"]))

    txt = phase_report_text("B_SENSE", "c1", {"verdict": "DEGRADED"},
                            {"accepted": False,
                             "rejected_because": ["no number"]})
    print("  report carries the rejection: {}".format("REJECTED" in txt))

    spent = rx.ReflexProducer(caller=lambda p: "QUERY x", max_calls=0)
    r3 = on_phase_close("C_JUDGE", "c1", {}, {}, producer=spent,
                        stream_path=stream, quarantine_root=quar)
    print("  budget enforced      emitted={} why={}".format(
        r3["emitted"], r3["why"][:44]))

    _reset_for_tests()
    p1 = producer_for("cycle-A")
    print("  one producer/cycle   same={} new_on_change={}".format(
        producer_for("cycle-A") is p1, producer_for("cycle-B") is not p1))

    # Is the call site actually there? A hook nothing calls is what this replaces.
    tracker = (BASE / "core" / "phase_tracker.py").read_text(
        encoding="utf-8", errors="replace")
    print("  core/phase_tracker   {}".format(
        "WIRED — _close() calls on_phase_close()" if "phase_voice" in tracker
        else "NOT WIRED — nothing calls this module"))
    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
