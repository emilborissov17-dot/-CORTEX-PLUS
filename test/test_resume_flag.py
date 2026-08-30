#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_resume_flag.py — --resume IS OFF, AND EVERY WAY OF SAYING NO MEANS
"RUN THE WHOLE CYCLE".

core/cycle_checkpoint.decide_resume is already tested as a pure function. What is
tested here is the RUNNER's use of it, which is where a resume can do damage:

  * off by default. A manual `fast_cycle_runner.py` skips nothing, whatever is on
    disk. Only a supervisor RESTART passes the flag.
  * a resume needs to be TOLD which cycle it continues. A KILL_RESTART mints a
    brand-new cycle_id, so without CORTEX_RESUME_CYCLE_ID the checkpoint would
    never match and every resume would silently be a full run wearing a flag.
  * the artifact gate is a VETO, not advice.
  * a step is skipped only if it is on record as COMPLETED — not merely because
    it falls inside the prefix. Prefix arithmetic is unsafe here: 33 of 54 steps
    checkpoint nothing, and `body_scan` appears twice in the step list.
  * every refusal path skips nothing at all. There is no half-resume.

    venv\\Scripts\\python.exe -m pytest test/test_resume_flag.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import fast_cycle_runner as r  # noqa: E402
from core.cycle_map import STEPS  # noqa: E402

STEP_NAMES = [s[0] for s in STEPS]


@pytest.fixture
def resumable(monkeypatch):
    """A dead cycle that completed its first few steps, with every gate green."""
    import core.cycle_checkpoint as cc
    import memory.existence_ledger as el

    done = [n for n in STEP_NAMES[:6]]
    monkeypatch.setenv("CORTEX_RESUME_CYCLE_ID", "dead-cycle-1")
    monkeypatch.setattr(cc, "latest", lambda base=None: {
        "cycle_id": "dead-cycle-1", "last_completed_step": done[-1]})
    monkeypatch.setattr(cc, "completed_steps", lambda cid, base=None: list(done))
    monkeypatch.setattr(el, "has_finished", lambda cid: False)
    monkeypatch.setattr(r, "_artifact_veto", lambda step: None)
    return done


# ---------------------------------------------------------------------------
# Off by default
# ---------------------------------------------------------------------------

def test_without_the_flag_nothing_is_skipped(resumable):
    d = r._decide_resume([])
    assert d["active"] is False
    assert d["skip"] == frozenset()
    assert "OFF by default" in d["reason"]


def test_a_manual_run_gets_no_resume_even_with_a_perfect_checkpoint(resumable):
    """The checkpoint, the ledger and the artifacts are all green here."""
    assert r._decide_resume(["fast_cycle_runner.py"])["active"] is False


@pytest.mark.xfail(strict=True, reason=(
    "ITEM 51 (30 Aug 2026): --resume is DISABLED, so _decide_resume() "
    "short-circuits before the logic this test describes. The test is KEPT, "
    "not deleted: it is the specification ITEM 50 has to restore when it "
    "unifies the step bodies on _run(). strict=True on purpose — the day "
    "resume is re-enabled this XPASSes and fails the suite, forcing whoever "
    "re-enables it to remove this marker deliberately rather than find a "
    "quietly-green test that has not run its assertion in months."))
def test_with_the_flag_and_a_named_cycle_it_resumes(resumable):
    d = r._decide_resume(["--resume"])
    assert d["active"] is True, d["reason"]
    assert d["skip"], "resume active but nothing to skip"


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "ITEM 51 (30 Aug 2026): --resume is DISABLED, so _decide_resume() "
    "short-circuits before the logic this test describes. The test is KEPT, "
    "not deleted: it is the specification ITEM 50 has to restore when it "
    "unifies the step bodies on _run(). strict=True on purpose — the day "
    "resume is re-enabled this XPASSes and fails the suite, forcing whoever "
    "re-enables it to remove this marker deliberately rather than find a "
    "quietly-green test that has not run its assertion in months."))
def test_the_flag_without_a_named_cycle_refuses(resumable, monkeypatch):
    monkeypatch.delenv("CORTEX_RESUME_CYCLE_ID", raising=False)
    d = r._decide_resume(["--resume"])
    assert d["active"] is False
    assert "CORTEX_RESUME_CYCLE_ID" in d["reason"]


def test_a_checkpoint_from_another_cycle_refuses(resumable, monkeypatch):
    import core.cycle_checkpoint as cc
    monkeypatch.setattr(cc, "latest", lambda base=None: {
        "cycle_id": "some-other-cycle", "last_completed_step": STEP_NAMES[3]})
    d = r._decide_resume(["--resume"])
    assert d["active"] is False
    assert d["skip"] == frozenset()


@pytest.mark.xfail(strict=True, reason=(
    "ITEM 51 (30 Aug 2026): --resume is DISABLED, so _decide_resume() "
    "short-circuits before the logic this test describes. The test is KEPT, "
    "not deleted: it is the specification ITEM 50 has to restore when it "
    "unifies the step bodies on _run(). strict=True on purpose — the day "
    "resume is re-enabled this XPASSes and fails the suite, forcing whoever "
    "re-enables it to remove this marker deliberately rather than find a "
    "quietly-green test that has not run its assertion in months."))
def test_a_cycle_that_already_sealed_is_not_resumed(resumable, monkeypatch):
    import memory.existence_ledger as el
    monkeypatch.setattr(el, "has_finished", lambda cid: True)
    d = r._decide_resume(["--resume"])
    assert d["active"] is False
    assert "nothing to resume" in d["reason"] or "CYCLE_FINISHED" in d["reason"]


def test_the_artifact_gate_is_a_veto(resumable, monkeypatch):
    monkeypatch.setattr(r, "_artifact_veto",
                        lambda step: "output/cortex_scores_latest.json is from "
                                     "an earlier cycle")
    d = r._decide_resume(["--resume"])
    assert d["active"] is False, (
        "the artifact gate refused and the resume happened anyway. Scoring would "
        "have run on last night's snapshots and stamped today's date on them")
    assert d["skip"] == frozenset()


def test_no_checkpoint_at_all_refuses(resumable, monkeypatch):
    import core.cycle_checkpoint as cc
    monkeypatch.setattr(cc, "latest", lambda base=None: None)
    assert r._decide_resume(["--resume"])["active"] is False


def test_an_exploding_gate_runs_the_full_cycle(resumable, monkeypatch):
    import core.cycle_checkpoint as cc

    def _boom(*a, **k):
        raise RuntimeError("ledger unreadable")

    monkeypatch.setattr(cc, "decide_resume", _boom)
    d = r._decide_resume(["--resume"])
    assert d["active"] is False and d["skip"] == frozenset(), (
        "a resume that cannot be reasoned about must not happen")


# ---------------------------------------------------------------------------
# Evidence, not arithmetic
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "ITEM 51 (30 Aug 2026): --resume is DISABLED, so _decide_resume() "
    "short-circuits before the logic this test describes. The test is KEPT, "
    "not deleted: it is the specification ITEM 50 has to restore when it "
    "unifies the step bodies on _run(). strict=True on purpose — the day "
    "resume is re-enabled this XPASSes and fails the suite, forcing whoever "
    "re-enables it to remove this marker deliberately rather than find a "
    "quietly-green test that has not run its assertion in months."))
def test_a_step_in_the_prefix_but_not_recorded_is_still_run(resumable, monkeypatch):
    """The prefix says six steps; the record says four. Four is the answer."""
    import core.cycle_checkpoint as cc
    recorded = resumable[:4]
    monkeypatch.setattr(cc, "completed_steps", lambda cid, base=None: list(recorded))
    d = r._decide_resume(["--resume"])
    assert d["active"] is True
    assert set(d["skip"]) == set(recorded), (
        "a step inside the prefix that never recorded a completion was skipped. "
        "Only 21 of 54 steps checkpoint at all, so the prefix is not evidence")


def test_nothing_recorded_means_nothing_skipped(resumable, monkeypatch):
    import core.cycle_checkpoint as cc
    monkeypatch.setattr(cc, "completed_steps", lambda cid, base=None: [])
    d = r._decide_resume(["--resume"])
    assert d["skip"] == frozenset()


# ---------------------------------------------------------------------------
# seal-only
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "ITEM 51 (30 Aug 2026): --resume is DISABLED, so _decide_resume() "
    "short-circuits before the logic this test describes. The test is KEPT, "
    "not deleted: it is the specification ITEM 50 has to restore when it "
    "unifies the step bodies on _run(). strict=True on purpose — the day "
    "resume is re-enabled this XPASSes and fails the suite, forcing whoever "
    "re-enables it to remove this marker deliberately rather than find a "
    "quietly-green test that has not run its assertion in months."))
def test_all_steps_done_but_never_sealed_is_flagged_seal_only(resumable, monkeypatch):
    import core.cycle_checkpoint as cc
    monkeypatch.setattr(cc, "latest", lambda base=None: {
        "cycle_id": "dead-cycle-1", "last_completed_step": STEP_NAMES[-1]})
    monkeypatch.setattr(cc, "completed_steps", lambda cid, base=None: list(STEP_NAMES))
    d = r._decide_resume(["--resume"])
    assert d["active"] is True
    assert d["seal_only"] is True, (
        "every step completed and the cycle never sealed; start_index == len(steps) "
        "means there is nothing left to run but the seal")


# ---------------------------------------------------------------------------
# _run() honours the gate
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_run(monkeypatch):
    """_run() with its side channels stubbed.

    StepContract takes two snapshots of 4853 files and writes
    memory/step_contract_*.json — live state, which test/conftest.py rightly
    fails on. Neither the snapshot nor the checkpoint is what these tests are
    about; the skip decision is.
    """
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
    monkeypatch.setattr(r, "_checkpoint_step", lambda label: None)
    monkeypatch.setattr(r, "_free_ollama", lambda: None)
    import core.model_window as mw
    monkeypatch.setattr(mw, "on_step", lambda *a, **k: {"changed": False})
    import core.brain as brain
    monkeypatch.setattr(brain, "skipped_by_brain", lambda step: False)


def test_run_skips_a_step_the_gate_names(monkeypatch, isolated_run):
    called = []
    monkeypatch.setattr(r, "_RESUME", {"active": True, "skip": frozenset({"data_scout"}),
                                       "reason": "unit", "seal_only": False})
    r._run("data_scout", lambda: called.append("ran"))
    assert called == [], "the step ran despite being on the skip list"


def test_run_runs_a_step_the_gate_does_not_name(monkeypatch, isolated_run):
    called = []
    monkeypatch.setattr(r, "_RESUME", {"active": True, "skip": frozenset({"other_step"}),
                                       "reason": "unit", "seal_only": False})
    r._run("data_scout", lambda: called.append("ran"))
    assert called == ["ran"]


def test_an_inactive_gate_skips_nothing(monkeypatch, isolated_run):
    called = []
    monkeypatch.setattr(r, "_RESUME", {"active": False, "skip": frozenset({"data_scout"}),
                                       "reason": "unit", "seal_only": False})
    r._run("data_scout", lambda: called.append("ran"))
    assert called == ["ran"], (
        "an inactive gate with a stale skip set skipped a step; `active` is the "
        "only thing that may authorise skipping")


# ---------------------------------------------------------------------------
# The supervisor side
# ---------------------------------------------------------------------------

def test_only_the_restart_path_passes_resume():
    src = (REPO / "supervisor.py").read_text(encoding="utf-8", errors="replace")
    assert "spawn_cycle(cycle_id, resume_from=action.cycle_id)" in src, (
        "the KILL_RESTART path no longer passes the dead cycle's id; a restart "
        "cannot resume without being told what it continues")
    assert src.count("resume_from=") == 1, (
        "more than one spawn path passes resume_from. The daily START and the "
        "human's --run-now begin a new day and must never skip work")


def test_spawn_without_resume_from_adds_no_flag():
    import inspect
    import supervisor
    src = inspect.getsource(supervisor.spawn_cycle)
    assert 'argv.append("--resume")' in src
    assert "if resume_from:" in src, (
        "--resume is appended unconditionally; every spawn would resume")
