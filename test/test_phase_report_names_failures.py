# -*- coding: utf-8 -*-
"""ITEM 21(c) — a step that RAISED must be visible in the cycle report.

MEASURED FIRST, 2026-08-29: 133 phase reports on disk and NOT ONE names a failed
step. The 2026-08-29 cycle's G_LEARN report lists feedback_loop in steps_run,
with steps_failed: [], while the log says

    [FAST_CYCLE] feedback_loop -> FAILED: TypeError: cannot use 'dict' as a dict key

THE REASON IS STRUCTURAL, not an oversight in one place. core/phase_tracker.py
calls step_ok() from on_step(), which runs at beat() time — BEFORE the step
does its work. So steps_run has always meant "steps STARTED", and nothing ever
told the report how any of them ended. PhaseReport.step_failed() existed the
whole time and its only live caller was "<phase aborted>" in __exit__.

WHY IT MATTERED HERE AND WOULD HAVE MATTERED MORE. G_LEARN did reach PARTIAL —
but only because produces_check independently noticed the artifact was stale. A
step that crashed AFTER writing its artifact would have left the phase reading
DONE with a crash in the log and nothing in the record.
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.phase_report import PhaseReport  # noqa: E402
from core import phase_tracker as pt  # noqa: E402

CYCLE = "2026-08-29T03:04:01"


def test_a_failed_step_is_named_in_the_record(tmp_path):
    with PhaseReport("G_LEARN", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("measurement_honesty")
        rep.step_failed("feedback_loop", TypeError("cannot use 'dict' as a dict key"))
    blob = json.loads(next(tmp_path.rglob("G_LEARN.json")).read_text(encoding="utf-8"))
    names = [f["step"] for f in blob["steps_failed"]]
    assert "feedback_loop" in names
    err = [f["error"] for f in blob["steps_failed"] if f["step"] == "feedback_loop"][0]
    assert "TypeError" in err and "dict" in err, (
        "the record must carry the exception, not merely the fact of one")


def test_a_step_recorded_ok_and_then_failed_is_listed_once(tmp_path):
    """on_step() calls step_ok at BEAT time, before the step runs, so the
    failure always arrives second. It must correct the record, not duplicate
    the step."""
    with PhaseReport("G_LEARN", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("feedback_loop")
        rep.step_failed("feedback_loop", RuntimeError("boom"))
    blob = json.loads(next(tmp_path.rglob("G_LEARN.json")).read_text(encoding="utf-8"))
    assert blob["steps_run"].count("feedback_loop") == 1
    assert [f["step"] for f in blob["steps_failed"]] == ["feedback_loop"]


def test_the_verdict_cannot_be_done_while_a_step_raised(tmp_path):
    """The property that matters. Every promised artifact is fresh, so the
    artifact check is satisfied — and the phase must still not read DONE."""
    produced = tmp_path / "artifact.json"
    produced.write_text("{}", encoding="utf-8")
    with PhaseReport("G_LEARN", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("session_update")
        rep.step_failed("feedback_loop", RuntimeError("crashed after writing"))
    blob = json.loads(next(tmp_path.rglob("G_LEARN.json")).read_text(encoding="utf-8"))
    assert blob["verdict"] != "DONE", (
        "a phase whose step raised must never report DONE, however fresh its "
        "artifacts are — that is the case the artifact check cannot catch")
    assert "feedback_loop" in blob["reason"]


def test_the_tracker_forwards_a_failure_to_the_open_report(tmp_path, monkeypatch):
    """The seam that was missing: something has to TELL the report."""
    monkeypatch.setattr(pt, "_open_phase", None, raising=False)
    monkeypatch.setattr(pt, "_open_report", None, raising=False)
    monkeypatch.setattr(pt, "_cycle_id", CYCLE, raising=False)

    rep = PhaseReport("G_LEARN", CYCLE, base_dir=tmp_path)
    rep.__enter__()
    rep.step_ok("feedback_loop")
    monkeypatch.setattr(pt, "_open_report", rep, raising=False)
    monkeypatch.setattr(pt, "_open_phase", "G_LEARN", raising=False)

    pt.note_failure("feedback_loop", TypeError("unhashable type: 'dict'"))
    assert [f["step"] for f in rep.steps_failed] == ["feedback_loop"]
    rep.__exit__(None, None, None)


def test_note_failure_is_silent_when_no_phase_is_open(monkeypatch):
    """FAIL-OPEN. A reporting seam must never be the thing that kills a step."""
    monkeypatch.setattr(pt, "_open_report", None, raising=False)
    pt.note_failure("feedback_loop", RuntimeError("boom"))  # must not raise


def test_the_runner_tells_the_tracker_when_a_step_raises():
    """By AST: _run's except branch must reach note_failure. Without this the
    whole mechanism above is dead code, which is how it got here."""
    import ast
    src = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_run"):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "note_failure"):
                found = True
    assert found, "_run() does not tell the phase report that a step raised"
