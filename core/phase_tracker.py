#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/phase_tracker.py — CLOSE A PHASE THE MOMENT THE CYCLE LEAVES IT.

WHY THIS EXISTS
----------------
config/cycle_phases.json groups the 55 steps into 7 phases, and
core/phase_report.py can judge one — but nothing was calling it. The map, the
report, the debrief and the per-phase Telegram message were four finished parts
with no seam between them.

beat() is the one path every step passes through, so the seam goes there: when
a beat lands in a different phase from the last one, the previous phase is
CLOSED — its report written, its debrief asked of the local brain, and one
message sent. Nothing else has to know phases exist.

NOT THE SAME AS RUNNING PHASES. --only and --from still do not skip steps; that
needs main() decomposed and is deliberately untouched. This observes the phases
the cycle already walks through.

FAIL-OPEN THROUGHOUT. A phase that cannot be reported must not stop the cycle
that is trying to finish.

    venv\\Scripts\\python.exe core/phase_tracker.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
PHASES_FILE = BASE / "config" / "cycle_phases.json"

_open_phase = None      # str
_open_report = None     # PhaseReport
_cycle_id = None


def phase_of(step: str, index: str | None = None) -> str | None:
    """Which phase does this beat belong to? Identity is (name, index)."""
    try:
        phases = json.loads(PHASES_FILE.read_text(encoding="utf-8"))["phases"]
    except Exception:
        return None
    for phase, body in phases.items():
        for s in body["steps"]:
            if s["name"] == step and (index is None or str(s["index"]) == str(index)):
                return phase
    for phase, body in phases.items():          # fall back to name alone
        if any(s["name"] == step for s in body["steps"]):
            return phase
    return None


def _evidence(phase: str) -> dict:
    """What the debrief is allowed to cite: this phase's own numbers."""
    ev = {"phase": phase}
    try:
        from core.phase_report import load_phases
        spec = load_phases()[phase]
        ev["promised_artifacts"] = len(spec["produces"])
        ev["steps"] = len(spec["steps"])
    except Exception:
        pass
    try:
        goal = json.loads((BASE / "snapshots" / "master" /
                           "goal_score_latest.json").read_text(encoding="utf-8"))
        ev["composite_score"] = goal.get("composite_score")
        ev["measured_metrics"] = sum(
            1 for d in (goal.get("metric_details") or {}).values()
            if d.get("measured"))
    except Exception:
        pass
    return ev


def _close(phase: str, report) -> None:
    """Write the report, ask for a debrief, send one message. All fail-open."""
    try:
        result = report.finish()
    except Exception as exc:  # noqa: BLE001
        print(f"[PHASE] {phase}: report failed ({type(exc).__name__}: {exc})")
        return

    debrief = None
    try:
        from core.phase_debrief import debrief_phase
        debrief = debrief_phase(phase, str(_cycle_id), _evidence(phase))
    except Exception as exc:  # noqa: BLE001
        print(f"[PHASE] {phase}: debrief failed ({type(exc).__name__}: {exc})")

    try:
        import supervisor
        if debrief and debrief.get("accepted"):
            text = debrief["telegram"]
        else:
            why = "; ".join((debrief or {}).get("rejected_because", [])) or "no debrief"
            text = (f"CORTEX++ · фаза {phase} · {result['verdict']}\n"
                    f"{result['reason'][:300]}\n"
                    f"(дебрифът е отхвърлен: {why[:160]})")
        supervisor.send_phase_debrief(phase, str(_cycle_id), text,
                                      trigger="MANUAL")
    except Exception as exc:  # noqa: BLE001
        print(f"[PHASE] {phase}: telegram failed ({type(exc).__name__}: {exc})")


def on_beat(step: str, index: str | None = None,
            cycle_id: str | None = None) -> None:
    """Called from beat(). Closes the previous phase when the cycle leaves it."""
    global _open_phase, _open_report, _cycle_id

    phase = phase_of(step, index)
    if phase is None:
        return
    if cycle_id:
        _cycle_id = cycle_id
    if _cycle_id is None:
        try:
            _cycle_id = json.loads((BASE / "memory" / "cycle.lock")
                                   .read_text(encoding="utf-8"))["cycle_id"]
        except Exception:
            _cycle_id = "unknown-cycle"

    if phase == _open_phase:
        if _open_report is not None:
            _open_report.step_ok(step)
        return

    if _open_phase is not None and _open_report is not None:
        _close(_open_phase, _open_report)

    try:
        from core.phase_report import PhaseReport
        _open_report = PhaseReport(phase, str(_cycle_id))
        _open_report.__enter__()
        _open_report.step_ok(step)
        _open_phase = phase
        print(f"[PHASE] >>> {phase}")
    except Exception as exc:  # noqa: BLE001
        print(f"[PHASE] could not open {phase}: {type(exc).__name__}: {exc}")
        _open_phase, _open_report = None, None


def close_last() -> None:
    """At the end of the cycle, close whatever is still open."""
    global _open_phase, _open_report
    if _open_phase is not None and _open_report is not None:
        _close(_open_phase, _open_report)
    _open_phase, _open_report = None, None


def _reset_for_tests() -> None:
    global _open_phase, _open_report, _cycle_id
    _open_phase, _open_report, _cycle_id = None, None, None


def _selftest() -> int:
    print("core/phase_tracker.py --selftest")
    checks = [
        ("boot is in A_ORIENT", phase_of("boot", "-1") == "A_ORIENT"),
        ("body_scan(0) is A_ORIENT", phase_of("body_scan", "0") == "A_ORIENT"),
        ("body_scan(13) is E_PROPOSE", phase_of("body_scan", "13") == "E_PROPOSE"),
        ("axis_feed(12.68) is D_SCORE", phase_of("axis_feed", "12.68") == "D_SCORE"),
        ("an unknown step has no phase", phase_of("not_a_step") is None),
    ]
    ok = True
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    ev = _evidence("D_SCORE")
    print(f"  D_SCORE evidence: {json.dumps(ev, ensure_ascii=False)[:160]}")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
