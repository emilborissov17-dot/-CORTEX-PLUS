#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_phase_report.py — THE REPORT MUST BE ABLE TO CONTRADICT THE STEPS.

THE DEFECT THIS GUARDS
-----------------------
"No step raised" is the weakest evidence a cycle produces. The 17:05 cycle
logged 29 truncated LLM answers and every step reported success; the feedback
loop returned {} for a month while every axis "succeeded". A step that swallows
its exception, writes nothing and returns is indistinguishable from a step that
worked — unless something checks the artifact instead of the exception.

So the rule under test is asymmetric on purpose:

    A phase that promised a file and did not leave it is PARTIAL,
    EVEN IF NO STEP RAISED.

THE NEGATIVE CONTROL
---------------------
test_a_silent_phase_that_produced_nothing_is_not_done is the one that matters.
It runs a phase whose every step succeeds and which writes nothing, and demands
the verdict is NOT DONE. Make verdict() consider only self.steps_failed — the
obvious "simplification" — and it goes red. Proven both ways before commit.

Everything here runs against tmp_path. Nothing reads or writes the real
memory/ tree, which a live cycle may be using while these tests run.

    venv\\Scripts\\python.exe -m pytest test/test_phase_report.py -v
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from core.phase_report import (DONE, FAILED, PARTIAL, PhaseReport,
                               safe_cycle_dir)

REPO = pathlib.Path(__file__).resolve().parents[1]
CYCLE = "2026-08-20T17:59:34.463459+03:00"

# F_SELF is the smallest phase, which makes it the cleanest one to test the
# contradiction rule against — but WHAT it promises is read from the config, not
# retyped here. It promised one artifact until 2026-08-28, when G_LEARN's
# misattributed files were moved to the phases that actually write them and
# memory/development_journal.json joined it. A hardcoded copy of a declared list
# goes stale silently and then fails for a reason that has nothing to do with
# what the test is about.
def _phase_produces(phase: str) -> list:
    import json
    cfg = json.loads((REPO / "config" / "cycle_phases.json").read_text(
        encoding="utf-8"))
    return list(cfg["phases"][phase]["produces"])


F_SELF_ALL = _phase_produces("F_SELF")
# The one the assertions name when they need a single path.
F_SELF_PRODUCES = F_SELF_ALL[0]


def _write_all(base: pathlib.Path, rels, text: str = "{}"):
    """Every artifact the phase promises. Writing only the first leaves the rest
    absent, which is PARTIAL for a correct reason and a confusing test."""
    return [_write(base, r, text) for r in rels]


def _write(base: pathlib.Path, rel: str, text: str = "{}") -> pathlib.Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _report_on_disk(rep: PhaseReport) -> dict:
    return json.loads(rep.path().read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) THE NEGATIVE CONTROL
# ---------------------------------------------------------------------------

def test_a_silent_phase_that_produced_nothing_is_not_done(tmp_path):
    """Every step 'succeeded'. Nothing was written. This must not read as success.

    Delete the produces_check from verdict() and this test goes red.
    """
    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("self_modifier")
        rep.step_ok("execute_patches")

    report = _report_on_disk(rep)

    assert report["steps_failed"] == [], "fixture broken: no step should have failed"
    assert report["verdict"] != DONE, (
        "\n  A PHASE THAT WROTE NOTHING REPORTED SUCCESS.\n"
        "  Every step returned without raising and the verdict was DONE anyway,\n"
        "  which means the report is only echoing the steps instead of checking\n"
        "  what they left behind. That is the exact failure this module exists to\n"
        "  catch: a step that swallows its exception looks identical to one that\n"
        "  worked. verdict() must consult produces_check(), not just steps_failed.\n"
    )
    assert report["verdict"] == PARTIAL
    assert F_SELF_PRODUCES in report["reason"]


def test_the_same_phase_is_done_once_it_writes_the_file(tmp_path):
    """POSITIVE CONTROL. Without this, a verdict() hardcoded to PARTIAL passes."""
    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("self_modifier")
        _write_all(tmp_path, F_SELF_ALL)
        rep.step_ok("execute_patches")

    report = _report_on_disk(rep)
    assert report["verdict"] == DONE, report["reason"]
    assert report["produces_check"][0]["written_during_phase"] is True


# ---------------------------------------------------------------------------
# (b) Existing is not the same as belonging
# ---------------------------------------------------------------------------

def test_a_file_left_over_from_an_earlier_cycle_does_not_count(tmp_path):
    """output/cortex_scores_latest.json exists right now and is from a cycle that
    died hours ago. Presence alone must never satisfy a promise."""
    stale = _write_all(tmp_path, F_SELF_ALL)[0]
    old = (datetime.now(timezone.utc) - timedelta(hours=6)).timestamp()
    import os
    os.utime(stale, (old, old))

    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("self_modifier")
        rep.step_ok("execute_patches")

    report = _report_on_disk(rep)
    row = report["produces_check"][0]
    assert row["present"] is True
    assert row["written_during_phase"] is False
    assert report["verdict"] == PARTIAL
    assert "stale copy" in report["reason"]


def test_a_file_written_the_instant_the_phase_began_still_counts(tmp_path):
    """Regression: st_mtime and datetime.now() are different clock reads, so a
    file written immediately can stamp a fraction of a second BEFORE the phase
    started. Measured skew was up to -0.53ms; the selftest caught it as a phase
    that had just written its artifact being called stale."""
    for _ in range(20):
        with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
            _write_all(tmp_path, F_SELF_ALL)
        assert _report_on_disk(rep)["verdict"] == DONE, (
            "a file written in the same instant the phase began was judged stale"
        )


# ---------------------------------------------------------------------------
# (c) FAILED means broke; PARTIAL means came back empty-handed
# ---------------------------------------------------------------------------

def test_a_step_that_raised_and_produced_nothing_is_failed(tmp_path):
    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_failed("self_modifier", RuntimeError("patch guardian refused"))
        rep.step_ok("execute_patches")

    report = _report_on_disk(rep)
    assert report["verdict"] == FAILED
    assert "self_modifier" in report["reason"]
    assert report["steps_failed"][0]["error"].startswith("RuntimeError:")


def test_a_step_that_raised_but_left_the_artifact_is_partial_not_failed(tmp_path):
    """Half a loaf. The distinction matters: FAILED means read the traceback,
    PARTIAL means look at what is missing."""
    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_failed("self_modifier", ValueError("one proposal was malformed"))
        _write_all(tmp_path, F_SELF_ALL)
        rep.step_ok("execute_patches")

    assert _report_on_disk(rep)["verdict"] == PARTIAL


def test_an_exception_escaping_the_phase_is_recorded_and_not_swallowed(tmp_path):
    with pytest.raises(RuntimeError):
        with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
            rep.step_ok("self_modifier")
            raise RuntimeError("the phase itself blew up")

    report = _report_on_disk(rep)
    assert report["verdict"] == FAILED
    assert any("phase aborted" in f["step"] for f in report["steps_failed"])


# ---------------------------------------------------------------------------
# (d) The report's shape
# ---------------------------------------------------------------------------

def test_the_report_carries_every_field_the_operator_needs(tmp_path):
    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("self_modifier")
        _write_all(tmp_path, F_SELF_ALL)
        rep.step_ok("execute_patches")

    report = _report_on_disk(rep)
    for field in ("phase", "cycle_id", "started", "ended", "seconds", "steps_run",
                  "steps_failed", "produces_check", "llm_calls", "verdict", "reason"):
        assert field in report, f"the report has no {field}"

    assert report["cycle_id"] == CYCLE
    assert report["steps_run"] == ["self_modifier", "execute_patches"]
    assert report["seconds"] >= 0


def test_the_report_lands_under_its_own_cycle_id(tmp_path):
    """Two cycles must not overwrite each other's reports."""
    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("self_modifier")

    expected = (tmp_path / "memory" / "phase_reports" /
                safe_cycle_dir(CYCLE) / "F_SELF.json")
    assert rep.path() == expected
    assert expected.exists()
    assert ":" not in safe_cycle_dir(CYCLE), "a cycle_id with colons is not a Windows path"


def test_llm_calls_are_counted_by_backend_within_the_phase_window(tmp_path):
    """Attribution comes from llm_provenance.jsonl by timestamp, so it cannot
    drift from reality the way a hand-kept counter would."""
    prov = tmp_path / "prov.jsonl"

    with PhaseReport("F_SELF", CYCLE, base_dir=tmp_path, provenance=prov) as rep:
        # Stamped INSIDE the phase, exactly as the backend would log them. An
        # entry written before the phase began is outside the window by
        # definition and must not be attributed to it.
        during = datetime.now(timezone.utc)
        prov.write_text("".join(json.dumps(r) + "\n" for r in [
            {"ts": (during - timedelta(hours=2)).isoformat(), "backend": "Groq"},
            {"ts": during.isoformat(), "backend": "Groq"},
            {"ts": during.isoformat(), "backend": "Gemini"},
            {"ts": during.isoformat(), "backend": "Groq"},
        ]), encoding="utf-8")
        rep.step_ok("self_modifier")
        _write_all(tmp_path, F_SELF_ALL)

    calls = _report_on_disk(rep)["llm_calls"]
    assert calls == {"Groq": 2, "Gemini": 1}, (
        f"expected the three in-window calls only, got {calls} — the two-hour-old "
        f"entry must not be attributed to this phase"
    )


@pytest.mark.parametrize("phase", ["A_ORIENT", "B_SENSE", "C_SNAPSHOT", "D_SCORE",
                                   "E_PROPOSE", "F_SELF", "G_LEARN"])
def test_every_real_phase_can_be_reported_on(tmp_path, phase):
    """Every phase in config/cycle_phases.json must be constructible — a typo in
    the config would otherwise only surface at 03:00 in the middle of a cycle."""
    with PhaseReport(phase, CYCLE, base_dir=tmp_path) as rep:
        rep.step_ok("whatever")

    report = _report_on_disk(rep)
    assert report["phase"] == phase
    assert report["verdict"] in (DONE, PARTIAL, FAILED)
    assert len(report["produces_check"]) >= 1
