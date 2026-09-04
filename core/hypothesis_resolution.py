#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/hypothesis_resolution.py — THE CYCLE'S CALLER FOR evaluator.py (3 Sep 2026).

WHY THIS EXISTS. evaluator.check_due_hypotheses() has existed for months and has
exactly one caller in the whole repo: `hypothesis_generator.py --check`, a manual CLI
flag. Nothing on the nightly cycle invokes it — fast_cycle_runner.py does not mention
hypothesis_generator at all. The store proves it:

    cortex_memory/hypotheses/pending.json   last written 2026-06-20
    cortex_memory/hypotheses/resolved.json  last written 2026-06-17

Seventy-five days. The machinery for scoring a prediction against the outcome was
built, tested, documented — and never once fired. A system that generates hypotheses
and never grades them can only ever agree with itself, and every accuracy claim it
makes rests on nothing.

WHAT IT DOES. Wraps the evaluator so the cycle can call it and so the phase report can
catch it going inert:

  - RESOLUTION ONLY. It never generates a hypothesis. That is not a promise in a
    docstring, it is checked: pending.json must not GROW across the call, and a step
    that grew it reports ILLEGAL_GROWTH and says so out loud. The generator lives in
    hypothesis_generator.py and is deliberately not imported here.

  - "0 due" IS A RESULT, NOT SILENCE. A night where nothing has reached its
    prediction_date reports `due=0` and writes the artifact anyway. A step that
    succeeds silently when it did nothing is indistinguishable from a step that is
    not wired.

  - DUE BUT UNRESOLVABLE IS ITS OWN VERDICT, AND IT LEAVES PENDING (amended 4 Sep
    2026, Q0). A hypothesis whose prediction_date has passed but whose axis has no
    reading anywhere is NOT graded and NOT counted as "nothing due". Until today the
    evaluator returned it to pending, which is why kp_index (due 17 July) and
    co2_ppm (due 20 July) sat there for seven weeks while this step reported cleanly
    every night: "still pending" and "forgotten" were the same state on disk. Now the
    evaluator marks it `status: "unresolvable"` with the lookup trail that came up
    empty and moves it to resolved.json; this module counts it as `unresolvable_now`
    (and keeps `skipped_no_data` as its alias). A past-due hypothesis that is still
    in pending after this step is a contract violation and is reported as one.

The artifact (memory/hypothesis_resolution_latest.json) is written on EVERY run, which
is what lets G_LEARN's produces list catch this step going inert. resolved.json is
deliberately NOT the produces artifact: the evaluator only writes it when something
actually resolves, so a correct quiet night would read as a broken phase.

  venv\\Scripts\\python.exe -m core.hypothesis_resolution --selftest
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LATEST = REPO / "memory" / "hypothesis_resolution_latest.json"


def _abs(p: str) -> Path:
    """evaluator.py holds its paths as repo-relative strings and depends on the CWD.
    Read them through this so the step works from anywhere and a test that
    monkeypatches evaluator's constants is still followed."""
    q = Path(p)
    return q if q.is_absolute() else (REPO / q)


def _rel(p: Path) -> str:
    """Repo-relative POSIX for the record. A store OUTSIDE the repo is legitimate —
    a test points evaluator at a tmp dir — so this reports the absolute path rather
    than raising, which is what relative_to() does off-tree."""
    try:
        return str(p.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _load_list(p: Path) -> list:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _due(records: list, today: date) -> list:
    out = []
    for h in records:
        try:
            if date.fromisoformat(str(h.get("prediction_date"))) <= today:
                out.append(h)
        except Exception:
            continue          # an unparseable date is not due; it is malformed
    return out


def run(write: bool = True, today: date | None = None) -> dict:
    """Resolve every due hypothesis. Returns the record that is written to disk."""
    import evaluator as _ev          # imported here so a test can patch its constants

    today = today or date.today()
    pending_p, resolved_p = _abs(_ev.PENDING_PATH), _abs(_ev.RESOLVED_PATH)

    before_pending = _load_list(pending_p)
    before_resolved = _load_list(resolved_p)
    due_before = _due(before_pending, today)

    error = None
    try:
        # The evaluator resolves against the CWD, so give it the repo.
        cwd = os.getcwd()
        try:
            os.chdir(REPO)
            newly = _ev.check_due_hypotheses() or []
        finally:
            os.chdir(cwd)
    except Exception as e:
        newly, error = [], f"{type(e).__name__}: {e}"

    after_pending = _load_list(pending_p)
    after_resolved = _load_list(resolved_p)

    # THE GUARD. This step resolves; it must never generate. A grown pending store
    # means something called a generator behind our back.
    grew = len(after_pending) > len(before_pending)

    # GRADED AND UNGRADEABLE ARE TWO OUTCOMES, NOT ONE (4 Sep 2026, Q0). The
    # evaluator now returns both: a hypothesis it scored, and a past-due one it
    # could not score and therefore moved out of pending marked "unresolvable"
    # with the lookup trail that came up empty. Counting them together would let a
    # night of pure failure report the same number as a night of pure success.
    graded = [r for r in newly if r.get("status") != "unresolvable"]
    ungradeable = [r for r in newly if r.get("status") == "unresolvable"]

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "due": len(due_before),
        "resolved_now": len(graded),
        "unresolvable_now": len(ungradeable),
        "skipped_no_data": len(ungradeable),
        "pending_before": len(before_pending),
        "pending_after": len(after_pending),
        "resolved_total": len(after_resolved),
        "resolved_added": len(after_resolved) - len(before_resolved),
        "accuracies": [round(float(r.get("accuracy")), 4) for r in graded
                       if isinstance(r.get("accuracy"), (int, float))],
        # SKILL IS THE BENCH NUMBER (H1). accuracies stays for continuity and is
        # explicitly not what a night is judged on: it is the error against the
        # level, which read a 5.5 ppm miss as 98.7%.
        "skills": [round(float(r.get("skill")), 4) for r in graded
                   if isinstance(r.get("skill"), (int, float))],
        "beat_persistence": sum(1 for r in graded
                                if r.get("beat_persistence") is True),
        "resolution_only_ok": not grew,
        "verdict": ("ERROR" if error else
                    "ILLEGAL_GROWTH" if grew else
                    "RESOLVED" if graded else
                    "DUE_BUT_UNRESOLVABLE" if (ungradeable or due_before) else
                    "NOTHING_DUE"),
        "error": error,
        "store": {"pending": _rel(pending_p), "resolved": _rel(resolved_p)},
    }
    # Which axes were due but had nothing to grade them against — the actionable half.
    if rec["skipped_no_data"]:
        # Each stuck entry now carries WHY it could not be graded, straight from the
        # evaluator's lookup trail. "no current value" was true and useless; naming
        # the three lookups that missed is what makes it fixable.
        rec["stuck"] = [{"id": h.get("id"), "axis": h.get("axis"),
                         "prediction_date": h.get("prediction_date"),
                         "days_overdue": h.get("days_overdue"),
                         "reason": h.get("unresolvable_reason")}
                        for h in ungradeable]

    if write:
        LATEST.parent.mkdir(parents=True, exist_ok=True)
        LATEST.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return rec


def summary_line(rec: dict) -> str:
    """The one line the cycle log carries. 0 due says 0 due."""
    if rec.get("error"):
        return f"[FAST_CYCLE] resolve_hypotheses -> FAILED: {rec['error']}"
    if not rec.get("resolution_only_ok"):
        return ("[FAST_CYCLE] resolve_hypotheses -> ILLEGAL_GROWTH: pending grew "
                f"{rec['pending_before']} -> {rec['pending_after']}; this step "
                f"resolves and must never generate")
    if rec["resolved_now"]:
        sk = rec.get("skills") or []
        mean = f"{sum(sk) / len(sk):+.3f}" if sk else "n/a"
        won = rec.get("beat_persistence", 0)
        return (f"[FAST_CYCLE] resolve_hypotheses -> {rec['resolved_now']} of "
                f"{rec['due']} due graded; {won} beat persistence "
                f"(mean skill {mean}); {rec['pending_after']} still pending")
    if rec.get("unresolvable_now"):
        axes = ", ".join(sorted({s.get("axis", "?") for s in rec.get("stuck", [])}))
        return (f"[FAST_CYCLE] resolve_hypotheses -> {rec['due']} due but NONE "
                f"resolvable: no ground truth for {axes or '?'}; "
                f"{rec['unresolvable_now']} marked UNRESOLVABLE and moved out of "
                f"pending")
    if rec["due"]:
        return (f"[FAST_CYCLE] resolve_hypotheses -> {rec['due']} due, none graded "
                f"and none marked unresolvable — the contract broke")
    return (f"[FAST_CYCLE] resolve_hypotheses -> 0 due "
            f"({rec['pending_after']} pending, {rec['resolved_total']} resolved "
            f"all-time)")


def _selftest() -> int:
    import evaluator as _ev
    print("core/hypothesis_resolution --selftest")
    print(f"  evaluator module        : {_ev.__file__}")
    for label, p in (("pending", _abs(_ev.PENDING_PATH)),
                     ("resolved", _abs(_ev.RESOLVED_PATH)),
                     ("trends", _abs(_ev.TRENDS_PATH))):
        print(f"  {label:24s}: {'LIVE ' if p.is_file() else 'INERT '}{p}")
    # integrations checked for existence in THIS repo, not assumed
    for rel, needle in (("fast_cycle_runner.py", "resolve_hypotheses"),
                        ("core/cycle_map.py", "resolve_hypotheses"),
                        ("config/cycle_phases.json", "resolve_hypotheses"),
                        ("config/step_inputs.json", "resolve_hypotheses")):
        p = REPO / rel
        wired = p.is_file() and needle in p.read_text(encoding="utf-8", errors="ignore")
        print(f"  consumer {rel:26s}: {'LIVE' if wired else 'INERT'}")
    rec = run(write=False)
    print("  dry run -> " + summary_line(rec).replace("[FAST_CYCLE] ", ""))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(json.dumps(run(write="--write" in sys.argv), ensure_ascii=False, indent=2))
