#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_prev_step_is_not_the_current_step.py — A STEP IS NOT ITS OWN PREDECESSOR.

THE DEFECT (measured 17 August 2026, on the live logs)
-------------------------------------------------------
`memory/heartbeat.py::beat()` writes `[STEP] <name>` into the cycle log, then calls
`core/brain.py::attend()`. `attend()` called `_prev_step_output()`, which took the
LAST `[STEP]` line in that log — which is the line beat() had just written. So the
"previous step" was always the current one:

    brain_step_log.jsonl, 2026-08-17:  prev_step == step in 53 of 53 rows
    attestation chain, github_publish: prev_step='github_publish'

Downstream, `core/notary.py::_promise_state()` asked whether the previous step kept
its promise, and was handed the step itself. A step comparing against itself is not
evidence, and the notary is the layer that decides whether irreversible actions may
run.

WHY THE FIX IS NOT "PRINT THE MARKER LATER"
--------------------------------------------
Checked rather than assumed. The supervisor does NOT read this line — its staleness
check reads `heartbeat.get("step")` and `heartbeat.get("updated_utc")` from
memory/heartbeat.json (supervisor.py:642-643), so the marker is not the watchdog's
signal and delaying it would not make a slow step look stale.

The real reason is different, and it is in beat()'s own comment: the marker exists so
the autopsy can find WHERE a wedged step began. Printed after a brain call whose
timeout is 60s, a cycle that dies during that call never writes the marker at all —
losing the boundary exactly when the autopsy needs it. `core/cycle_report.py:49` also
slices each step's output as the lines BETWEEN two markers, so a late marker would
file the brain's own words under the previous step.

So the marker stays where it is, and the PREDECESSOR IS CAPTURED BEFORE IT IS
OVERWRITTEN: beat() reads the last marker, keeps it, then prints. Reading is the
operation that cannot tell the two apart; not reading twice is the fix.

    venv\\Scripts\\python.exe -m pytest test/test_prev_step_is_not_the_current_step.py -v
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def cycle_log(tmp_path, monkeypatch):
    """A throwaway cycle log that heartbeat and brain both look at."""
    import core.brain as brain
    import memory.heartbeat as hb

    logs = tmp_path / "memory" / "cycle_logs"
    logs.mkdir(parents=True)
    monkeypatch.setattr(hb, "CYCLE_LOG_DIR", logs)
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "memory" / "heartbeat.json")
    monkeypatch.setattr(brain, "BASE", tmp_path)
    monkeypatch.setattr(hb, "_PREV_STEP", None, raising=False)
    return logs / "cycle_test.log"


def _append(log: Path, *lines: str) -> None:
    with log.open("a", encoding="utf-8") as fh:
        for l in lines:
            fh.write(l + "\n")


# ---------------------------------------------------------------------------
# Positive control
# ---------------------------------------------------------------------------

def test_the_old_behaviour_would_be_caught(cycle_log):
    """POSITIVE CONTROL: reproduce the OLD reader and prove this file catches it.

    The old implementation was "take the last [STEP] line". If that came back — by a
    revert, or by someone 'simplifying' _prev_step_output back to a re-read — the
    assertions below must fail. Re-implemented here rather than described, so the
    control tests the actual defect and not a paraphrase of it.
    """
    _append(cycle_log, "[STEP] alpha", "  alpha output", "[STEP] beta")

    def old_reader() -> str:
        lines = cycle_log.read_text(encoding="utf-8").splitlines()
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].lstrip().startswith("[STEP] "):
                return lines[i].split("[STEP] ", 1)[1].strip()
        return ""

    # The current step is 'beta'. The old reader returns 'beta' — itself.
    assert old_reader() == "beta", (
        "the positive control no longer reproduces the old behaviour; it can no "
        "longer prove this test would catch a regression")


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_prev_step_is_never_the_step_currently_running(cycle_log):
    """THE STAKE: `_promise_state()` asks whether the PREVIOUS step kept its promise.
    Handed the current step, it compares a step against itself and calls the answer
    evidence. The notary gates irreversible actions on that answer."""
    import core.brain as brain
    import memory.heartbeat as hb

    _append(cycle_log, "[STEP] alpha", "  alpha output")

    hb.beat("beta")                       # captures 'alpha', then announces 'beta'
    _append(cycle_log, "[STEP] beta")     # what beat's print does, via the real log

    prev_name, _body = brain._prev_step_output()
    assert prev_name != "beta", (
        "the previous step is the step currently running — a step is its own "
        "predecessor, which is the defect this file exists to prevent")
    assert prev_name == "alpha", f"expected 'alpha', got {prev_name!r}"


def test_three_consecutive_beats_each_see_the_one_before(cycle_log):
    """The name must track the sequence, not merely differ from the current step."""
    import core.brain as brain
    import memory.heartbeat as hb

    seen = []
    for step in ("alpha", "beta", "gamma"):
        hb.beat(step)
        _append(cycle_log, f"[STEP] {step}", f"  {step} output")
        seen.append((step, brain._prev_step_output()[0]))

    assert seen == [("alpha", ""), ("beta", "alpha"), ("gamma", "beta")], seen
    for step, prev in seen:
        assert prev != step, f"{step} is its own predecessor"


def test_the_first_beat_of_a_cycle_reports_no_predecessor(cycle_log):
    """An empty log means there genuinely is no previous step — and that must read as
    absence, not as a name. The notary scores an unstated predecessor as UNKNOWN, so
    inventing one here would manufacture trust two layers down."""
    import core.brain as brain
    import memory.heartbeat as hb

    hb.beat("alpha")
    _append(cycle_log, "[STEP] alpha")

    assert hb.previous_step() is None
    assert brain._prev_step_output()[0] == ""


def test_the_body_belongs_to_the_previous_step_not_the_current_one(cycle_log):
    """The output the brain judges must be the PREVIOUS step's lines.

    `core/cycle_report.py` slices output between two markers; this reader must agree
    with it, or the brain judges one step's words while naming another.
    """
    import core.brain as brain
    import memory.heartbeat as hb

    _append(cycle_log, "[STEP] alpha", "  alpha said this")
    hb.beat("beta")
    _append(cycle_log, "[STEP] beta", "  beta said this")

    name, body = brain._prev_step_output()
    assert name == "alpha"
    assert "alpha said this" in body
    assert "beta said this" not in body, (
        "the body carries the CURRENT step's output — the reader is not stopping at "
        "the next [STEP] marker")


def test_the_marker_is_still_written_before_the_brain_is_called():
    """Source-structure: the fix must NOT have been 'print the marker later'.

    The marker is what the autopsy uses to find where a wedged step began. Printed
    after a brain call with a 60s timeout, a cycle dying inside that call writes no
    marker at all.
    """
    src = (REPO / "memory" / "heartbeat.py").read_text(encoding="utf-8-sig")
    i_capture = src.index("_PREV_STEP = _last_step_in_log()")
    i_print = src.index('print(f"[STEP] {step}"')
    i_attend = src.index("_attend(step)")

    assert i_capture < i_print, (
        "the predecessor must be captured BEFORE the new marker is written — after "
        "it, nothing can tell the new line from the old one")
    assert i_print < i_attend, (
        "the [STEP] marker is now printed AFTER the brain call. That was explicitly "
        "not the fix: a cycle that dies inside a 60s brain call would leave no "
        "marker, and the autopsy loses the step boundary.")
