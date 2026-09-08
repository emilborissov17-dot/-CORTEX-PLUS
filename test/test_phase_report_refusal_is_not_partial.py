#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_phase_report_refusal_is_not_partial.py

THE DEFECT THIS GUARDS
-----------------------
2026-09-08T01:35:34Z, memory/night_events.jsonl:

    {"subject": "self_modifier OTKAZANA",   "gate": "notary", ...}
    {"subject": "execute_patches OTKAZANA", "gate": "notary",
     "detail": "explicit ceiling for 'execute_patches': this step is capped at
                level_1 ... regardless of its own vector"}

Both of F_SELF's steps were stopped by the notary, so the phase was never
allowed to write anything - and the report graded it PARTIAL, "promised but last
written BEFORE this phase began", for artifacts it had been forbidden to touch.

    PARTIAL means a step RAN and silently failed to produce.
    REFUSED means the step was never allowed to run at all.

A gate that reports as a defect every time it works is a gate nobody reads, and
the pressure it creates points exactly the wrong way: toward writing a
placeholder artifact so the square goes green. That repair is forbidden. The
report is what had to learn the difference.

THE MUTATION TEST
------------------
test_deleting_the_exemption_makes_the_phase_partial_again pins the branch
itself: it calls verdict() on rows with `refused_by_gate` stripped - which is
exactly what the code would see if the exemption in produces_check/verdict were
removed - and asserts THAT reads PARTIAL. Together with the positive test above
it, the pair goes red from either direction: delete the exemption and the first
fails, hardcode DONE and the second fails.

Everything runs against tmp_path.

    venv\\Scripts\\python.exe -m pytest test/test_phase_report_refusal_is_not_partial.py -v
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from core.cycle_map import produces as declared_produces
from core.phase_report import DONE, PARTIAL, REFUSED, PhaseReport

REPO = pathlib.Path(__file__).resolve().parents[1]

# The step the notary refused on 2026-09-08, and the artifact the cycle table
# says it produces. Read from cycle_map, never retyped: a hardcoded copy of a
# declared list goes stale in silence and then fails for the wrong reason.
REFUSED_STEP = "self_modifier"
REFUSED_ARTIFACT = declared_produces(REFUSED_STEP)[0]
NOTARY_REASON = ("level_1 - explicit ceiling for 'self_modifier': capped by "
                 "core/notary.MAX_LEVEL regardless of its own vector")


def _phase_file(tmp_path: pathlib.Path, produces: list) -> pathlib.Path:
    """A one-phase config naming exactly the artifacts under test."""
    spec = {"phases": {"F_SELF": {"purpose": "t", "index_range": ["18", "19"],
                                  "steps": [], "requires": [],
                                  "produces": list(produces)}}}
    path = tmp_path / "phases.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _stale(tmp_path: pathlib.Path, rel: str, hours: float = 11.0) -> pathlib.Path:
    """The artifact as it really is: present, and last touched days ago.
    memory/runtime_experiences.json has carried mtime 2026-08-28T15:09:22Z since
    the gate started refusing the only step that writes it."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    old = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    os.utime(path, (old, old))
    return path


def _read(tmp_path: pathlib.Path) -> dict:
    return json.loads((tmp_path / "memory" / "phase_reports" / "cid" /
                       "F_SELF.json").read_text(encoding="utf-8"))


def _run(tmp_path: pathlib.Path, refuse: bool) -> dict:
    pf = _phase_file(tmp_path, [REFUSED_ARTIFACT])
    _stale(tmp_path, REFUSED_ARTIFACT)
    with PhaseReport("F_SELF", "cid", base_dir=tmp_path, phases_file=pf) as rep:
        rep.step_ok(REFUSED_STEP)
        if refuse:
            rep.step_refused(REFUSED_STEP, "notary", NOTARY_REASON)
    return _read(tmp_path)


# ---------------------------------------------------------------------------
# (a) the fix
# ---------------------------------------------------------------------------

def test_a_notary_refused_step_is_not_partial_for_what_it_could_not_write(tmp_path):
    """The 2026-09-08 night, replayed. Refusing correctly is a SUCCESS state."""
    report = _run(tmp_path, refuse=True)
    row = report["produces_check"][0]

    assert row["present"] is True, "fixture broken: the stale artifact is there"
    assert row["written_during_phase"] is False, "fixture broken: it is stale"

    assert report["verdict"] != PARTIAL, (
        "\n  A REFUSED STEP WAS GRADED PARTIAL.\n"
        "  The notary forbade " + REFUSED_STEP + " to act, so " +
        REFUSED_ARTIFACT + " was\n"
        "  never owed - and the phase was still marked as having silently failed\n"
        "  to produce it. PARTIAL means a step RAN and wrote nothing; this step\n"
        "  was never allowed to run. produces_check/verdict must exempt the\n"
        "  artifacts of a step recorded in steps_refused.\n"
        "  reason was: " + report["reason"] + "\n")
    assert report["verdict"] == DONE, report["reason"]


def test_the_row_and_the_reason_both_name_the_refusal(tmp_path):
    """A verdict of DONE over a night that wrote nothing is only honest if it
    says WHY nothing was written. Silent exemption would be its own lie."""
    report = _run(tmp_path, refuse=True)
    row = report["produces_check"][0]

    assert row["state"] == REFUSED, row
    assert row["refused_by_gate"]["step"] == REFUSED_STEP
    assert row["refused_by_gate"]["gate"] == "notary"
    assert REFUSED_STEP in report["reason"], report["reason"]
    assert "notary" in report["reason"], report["reason"]
    assert "refused" in report["reason"].lower(), report["reason"]
    assert "BEFORE this phase began" not in report["reason"], (
        "the refusal is still being reported as staleness: " + report["reason"])
    assert report["steps_refused"][0]["step"] == REFUSED_STEP
    assert report["steps_failed"] == [], "a refusal was recorded as a failure"


# ---------------------------------------------------------------------------
# (b) THE MUTATION TESTS - each goes red if the exemption is removed
# ---------------------------------------------------------------------------

def test_deleting_the_exemption_makes_the_phase_partial_again(tmp_path):
    """Pin the BRANCH, not just the outcome.

    Strip `refused_by_gate` from the rows and verdict() sees precisely what it
    would see with the exemption removed. If that still reads DONE, the fix is
    not the exemption - it is something unconditional, and the test above is
    passing for a reason that has nothing to do with refusals.
    """
    pf = _phase_file(tmp_path, [REFUSED_ARTIFACT])
    _stale(tmp_path, REFUSED_ARTIFACT)
    with PhaseReport("F_SELF", "cid", base_dir=tmp_path, phases_file=pf) as rep:
        rep.step_refused(REFUSED_STEP, "notary", NOTARY_REASON)

    unexempted = [dict(row, refused_by_gate=None) for row in rep.produces_check()]
    verdict, reason = rep.verdict(unexempted)
    assert verdict == PARTIAL, (
        "verdict() called DONE on a stale artifact with no refusal attached - "
        "the exemption is not what made the phase pass")
    assert "BEFORE this phase began" in reason, reason


def test_without_a_recorded_refusal_the_same_phase_is_still_partial(tmp_path):
    """THE NEGATIVE CONTROL, end to end. Same phase, same stale artifact, the
    only difference being that no gate refused: the old rule must still bite."""
    report = _run(tmp_path, refuse=False)
    assert report["verdict"] == PARTIAL, (
        "a step that simply wrote nothing is being excused; the exemption is "
        "leaking to steps no gate ever refused: " + report["reason"])
    assert report["produces_check"][0]["state"] == "STALE"
    assert report["produces_check"][0]["refused_by_gate"] is None
    assert report["steps_refused"] == []


def test_a_refusal_does_not_excuse_another_steps_artifact(tmp_path):
    """THE NARROWNESS. self_modifier's refusal covers what cycle_map says
    self_modifier produces - and nothing else in the phase. Widen the exemption
    to "everything this phase promised" and this goes red."""
    other = "memory/development_journal.json"
    assert other not in declared_produces(REFUSED_STEP), (
        "fixture broken: pick an artifact this step does not produce")

    pf = _phase_file(tmp_path, [REFUSED_ARTIFACT, other])
    _stale(tmp_path, REFUSED_ARTIFACT)
    _stale(tmp_path, other)
    with PhaseReport("F_SELF", "cid", base_dir=tmp_path, phases_file=pf) as rep:
        rep.step_refused(REFUSED_STEP, "notary", NOTARY_REASON)
    report = _read(tmp_path)

    by_path = {r["path"]: r for r in report["produces_check"]}
    assert by_path[REFUSED_ARTIFACT]["state"] == REFUSED
    assert by_path[other]["state"] == "STALE", (
        "the refusal of one step excused another step's artifact")
    assert report["verdict"] == PARTIAL, report["reason"]
    # Both facts survive into the sentence: one forbidden, one simply missing.
    assert other in report["reason"] and REFUSED_ARTIFACT in report["reason"]


def test_a_refused_step_that_wrote_anyway_is_not_marked_refused(tmp_path):
    """If the artifact arrived, the refusal is not what explains it. This is the
    guard against the forbidden repair: a placeholder written under a refusal
    shows up as WRITTEN and is judged on its merits, never laundered into a
    REFUSED row that no longer looks at the file at all."""
    pf = _phase_file(tmp_path, [REFUSED_ARTIFACT])
    with PhaseReport("F_SELF", "cid", base_dir=tmp_path, phases_file=pf) as rep:
        rep.step_refused(REFUSED_STEP, "notary", NOTARY_REASON)
        path = tmp_path / REFUSED_ARTIFACT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    report = _read(tmp_path)
    assert report["produces_check"][0]["state"] == "WRITTEN"
    assert report["produces_check"][0]["refused_by_gate"] is None


# ---------------------------------------------------------------------------
# (c) structural: the gate is wired to the report, not merely able to be
# ---------------------------------------------------------------------------

def test_every_refusal_return_in_the_runners_gate_goes_through_the_recorder():
    """Reads the CODE, not prose. `_witness_or_refuse` has three refusal exits;
    each must hand the refusal to the phase report. A fourth added later that
    just `return False`s would leave a phase graded PARTIAL for a step that was
    never permitted to act - the exact defect this file exists to close."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    gate = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_witness_or_refuse")

    bare = [n for n in ast.walk(gate)
            if isinstance(n, ast.Return)
            and isinstance(n.value, ast.Constant) and n.value.value is False]
    assert not bare, (
        str(len(bare)) + " refusal(s) in _witness_or_refuse still `return False` "
        "directly instead of `return _refused(step, gate, why)`; those refusals "
        "never reach the phase report and will be graded PARTIAL")

    recorded = [n for n in ast.walk(gate)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_refused"]
    assert len(recorded) >= 3, (
        "only " + str(len(recorded)) + " refusal exit(s) go through _refused(); "
        "the gate has three (human_channel, notary, metta_witness)")

    recorder = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_refused")
    attrs = {n.func.attr for n in ast.walk(recorder)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    names = {n.func.id for n in ast.walk(recorder)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_refusal_event" in names, "_refused stopped writing night_events.jsonl"
    assert "note_refusal" in attrs, "_refused stopped telling the phase report"


def test_the_tracker_hands_refusals_to_the_open_report():
    """core.phase_tracker.note_refusal must call PhaseReport.step_refused, and
    must fail open the way note_failure does - it runs inside the gate."""
    src = (REPO / "core" / "phase_tracker.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "note_refusal")
    attrs = {n.func.attr for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "step_refused" in attrs, "note_refusal records nothing"
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), (
        "note_refusal is not fail-open; raising here turns a clean refusal "
        "into a crashed cycle")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
