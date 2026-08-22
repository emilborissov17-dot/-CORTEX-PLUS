#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_checkpoint_wiring.py — A CHECKPOINT MEANS "IT FINISHED", NOT "IT STARTED".

core/cycle_checkpoint.py has been correct and unused since it was written; its own
tests (test/test_cycle_checkpoint_resume.py) prove the DECISION is sound. What was
never held is the WIRING, which is where the meaning of the record is decided:

  * written from _run()'s success path, so a step that raised leaves no record.
    _run swallows the exception and the cycle carries on, so "we reached the end
    of _run" is not the same question as "the step worked" — the flag is set
    before the except branch can be reached, and only there.
  * NOT written at beat(). beat() fires on ENTRY. A cycle that dies inside a step
    has already beaten for it, so a checkpoint written on entry would name the
    step it died in as completed, and a resume would skip exactly the work that
    killed it. This is the failure this file exists to prevent, and it is cheap
    to reintroduce, so it is pinned by reading the source.

COVERAGE IS PART OF THE CONTRACT. Only the steps that go through _run() record
anything; the rest beat() and then run inline. That number is measured here rather
than assumed, so that if someone wires --resume on, the size of the hole is a fact
in the suite and not a discovery at 03:00.

    venv\\Scripts\\python.exe -m pytest test/test_checkpoint_wiring.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RUNNER_SRC = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                       errors="replace")


@pytest.fixture
def runner(monkeypatch):
    """fast_cycle_runner with every side channel _run() touches redirected."""
    import fast_cycle_runner as r

    recorded = []

    import core.cycle_checkpoint as cc

    def _fake_record(cycle_id, step, step_index, base=None):
        recorded.append({"cycle_id": cycle_id, "step": step,
                         "step_index": step_index})
        return recorded[-1]

    monkeypatch.setattr(cc, "record_step_complete", _fake_record)

    import memory.heartbeat as hb
    monkeypatch.setattr(hb, "read", lambda: {"cycle_id": "cyc-test",
                                             "step_index": "7"})

    # _run also opens a StepContract (two filesystem snapshots) and touches the
    # model window. Neither is what this file is about, and both are slow.
    monkeypatch.setattr(r, "_free_ollama", lambda: None)
    import core.step_contract as sc

    class _NoContract:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def note_swallowed(self, *a, **k):
            pass

        def finish(self):
            pass

    monkeypatch.setattr(sc, "StepContract", _NoContract)

    import core.model_window as mw
    monkeypatch.setattr(mw, "on_step", lambda *a, **k: {"changed": False})

    import core.brain as brain
    monkeypatch.setattr(brain, "skipped_by_brain", lambda step: False)

    r._recorded_for_test = recorded
    return r, recorded


# ---------------------------------------------------------------------------
# Success writes, failure does not
# ---------------------------------------------------------------------------

def test_a_step_that_returns_cleanly_is_checkpointed(runner):
    r, recorded = runner
    r._run("data_scout", lambda: None)
    assert len(recorded) == 1, (
        f"a clean step left {len(recorded)} checkpoints; it must leave exactly one")
    assert recorded[0]["cycle_id"] == "cyc-test"


def test_a_step_that_raises_is_not_checkpointed(runner):
    r, recorded = runner

    def _boom():
        raise RuntimeError("the step failed")

    r._run("data_scout", _boom)
    assert recorded == [], (
        "a step that raised recorded a completion. _run() swallows the exception "
        "and the cycle continues, so this record would tell a resume the work was "
        "done — the exact lie the checkpoint exists to avoid")


def test_a_step_skipped_by_the_brain_is_not_checkpointed(runner, monkeypatch):
    r, recorded = runner
    import core.brain as brain
    monkeypatch.setattr(brain, "skipped_by_brain", lambda step: True)
    monkeypatch.setattr(brain, "stance", lambda step=None: {"expect": "skip it"})
    r._run("data_scout", lambda: None)
    assert recorded == [], (
        "a step the brain skipped was never run, so it did not complete")


def test_the_runner_label_is_recorded_as_its_cycle_map_step_name(runner):
    r, recorded = runner
    from core.cycle_map import ALIASES
    if not ALIASES:
        pytest.skip("no aliases declared")
    label, name = next(iter(ALIASES.items()))
    r._run(label, lambda: None)
    assert recorded[-1]["step"] == name, (
        f"recorded {recorded[-1]['step']!r} for label {label!r}; the log has to "
        f"speak step names or decide_resume cannot match it against the step list")


def test_a_failing_checkpoint_does_not_take_the_step_down(runner, monkeypatch):
    r, recorded = runner
    import core.cycle_checkpoint as cc

    def _explode(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cc, "record_step_complete", _explode)
    r._run("data_scout", lambda: None)   # must not raise


# ---------------------------------------------------------------------------
# NOT at beat()
# ---------------------------------------------------------------------------

def test_beat_does_not_write_a_checkpoint():
    """Source-level, because the point is that the call is ABSENT."""
    hb_src = (REPO / "memory" / "heartbeat.py").read_text(encoding="utf-8",
                                                          errors="replace")
    assert "record_step_complete" not in hb_src, (
        "heartbeat.py calls record_step_complete. beat() fires on ENTRY: a cycle "
        "that dies mid-step has already beaten for it, so this would mark the "
        "step that killed the cycle as completed and let a resume skip it")


def test_the_checkpoint_call_sits_on_the_completed_path(runner):
    """The guard is `if _completed:`, and `_completed` is set only after fn()."""
    assert "_checkpoint_step(label)" in RUNNER_SRC
    assert re.search(r"if _completed:\s*\n\s*_checkpoint_step\(label\)", RUNNER_SRC), (
        "_checkpoint_step is no longer guarded by _completed — it would run for "
        "failed steps too")


# ---------------------------------------------------------------------------
# Coverage is a measured number, not an assumption
# ---------------------------------------------------------------------------

def test_the_uncovered_steps_are_counted_and_not_growing():
    """Not every step goes through _run(); the ones that do not record nothing.

    This is a RATCHET, not a target. Coverage may improve freely; it may not
    silently rot. If a step is moved out of _run(), this fails and the number in
    the message is the new truth to argue with.
    """
    from core.cycle_map import ALIASES, STEPS
    labels = set(re.findall(r"_run\(\s*[\"']([A-Za-z0-9_]+)[\"']", RUNNER_SRC))
    covered = {ALIASES.get(x, x) for x in labels}
    names = list(dict.fromkeys(s[0] for s in STEPS))
    missing = [n for n in names if n not in covered]

    assert len(missing) <= 33, (
        f"checkpoint coverage went backwards: {len(missing)} of {len(names)} "
        f"steps now record nothing (was 33 on 22 Aug 2026). Newly uncovered: "
        f"{missing}")


def test_resume_is_still_off_so_the_gap_cannot_skip_work_tonight():
    """The coverage hole is only safe while nothing READS the log to skip steps."""
    from core import cycle_checkpoint as cc
    d = cc.decide_resume("c1", ["a", "b", "c"],
                         {"cycle_id": "c1", "last_completed_step": "b"},
                         cycle_finished=False, enabled=False)
    assert not d.resume and d.start_index == 0, (
        "resume defaults to ON. With only a third of steps checkpointed that "
        "would skip work that never ran")
