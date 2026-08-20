#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_phase_resume.py — --from MUST REFUSE ON EVIDENCE THAT IS NOT THERE.

THE DEFECT THIS GUARDS
-----------------------
`--from D_SCORE` asserts that A_ORIENT through C_SNAPSHOT already ran THIS
cycle. If they did not, scoring runs anyway, reads whatever snapshots are on
disk — last night's — and writes a composite with today's timestamp on it.
The number would be wrong in the one way that is hardest to notice: current
looking and stale underneath.

Every required file EXISTS on this machine right now. Checked against the live
repo while writing this:

    snapshots/civilization/economy_work/...  mtime 01:10  (13 hours old)
    snapshots/planet/energy/...              mtime 01:12
    snapshots/human/cognition_learning/...   mtime 01:15
    snapshots/cosmos/goal_progress/...       mtime 14:38

An existence check would have waved all four through. So the gate checks
BELONGING too: written at or after this cycle began, or carrying the cycle_id
inside the file.

THE NEGATIVE CONTROL
---------------------
test_from_refuses_when_a_require_is_missing_and_names_it is the required case.
Weaken _belongs_to_cycle to `return path.exists()` and it goes red, because the
stale artifacts would then satisfy the gate. Proven both ways before commit.

    venv\\Scripts\\python.exe -m pytest test/test_phase_resume.py -v
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from core.phase_report import load_phases
from core.phase_resume import (FROM, ONLY, ResumeRefused, check_requires,
                               phase_names, selected_phases, verify_or_refuse)

REPO = pathlib.Path(__file__).resolve().parents[1]
CYCLE = "2026-08-20T17:59:34.463459+03:00"

D_SCORE_REQUIRES = load_phases()["D_SCORE"]["requires"]


def _satisfy(base: pathlib.Path, rels, cycle_id: str | None = None) -> None:
    for rel in rels:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"cycle_id": cycle_id} if cycle_id else {}),
                     encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) THE REQUIRED NEGATIVE CONTROL
# ---------------------------------------------------------------------------

def test_from_refuses_when_a_require_is_missing_and_names_it(tmp_path):
    """--from D_SCORE with one require absent must refuse, and say which."""
    started = datetime.now(timezone.utc)
    present = D_SCORE_REQUIRES[:-1]
    missing = D_SCORE_REQUIRES[-1]
    _satisfy(tmp_path, present)

    with pytest.raises(ResumeRefused) as caught:
        verify_or_refuse(FROM, "D_SCORE", CYCLE, started, base_dir=tmp_path)

    message = str(caught.value)
    assert missing in message, (
        f"\n  The refusal did not name the missing artifact.\n"
        f"  Missing: {missing}\n  Said: {message}\n"
        f"  An operator who is told 'requires not met' and not WHICH one has to\n"
        f"  go and diff the tree by hand. Naming it is the whole point.\n"
    )
    assert "REFUSING --from D_SCORE" in message
    for satisfied in present:
        assert satisfied not in message, "only the missing artifact should be listed"


def test_from_refuses_when_the_requires_are_stale(tmp_path):
    """THE HALF THAT MATTERS. Every file present, all from an earlier cycle.

    Weaken the check to mere existence and this goes red.
    """
    started = datetime.now(timezone.utc)
    _satisfy(tmp_path, D_SCORE_REQUIRES)
    old = (started - timedelta(hours=13)).timestamp()
    for rel in D_SCORE_REQUIRES:
        os.utime(tmp_path / rel, (old, old))

    with pytest.raises(ResumeRefused) as caught:
        verify_or_refuse(FROM, "D_SCORE", CYCLE, started, base_dir=tmp_path)

    message = str(caught.value)
    assert "belongs to an earlier cycle" in message
    assert f"4 of {len(D_SCORE_REQUIRES)}" in message
    for rel in D_SCORE_REQUIRES:
        assert rel in message, f"{rel} is stale but was not named"


def test_from_allows_when_every_require_belongs_to_this_cycle(tmp_path):
    """POSITIVE CONTROL. A gate that refuses everything is not a gate."""
    started = datetime.now(timezone.utc)
    _satisfy(tmp_path, D_SCORE_REQUIRES)

    phases = verify_or_refuse(FROM, "D_SCORE", CYCLE, started, base_dir=tmp_path)
    assert phases == ["D_SCORE", "E_PROPOSE", "F_SELF", "G_LEARN"]


def test_a_file_carrying_the_cycle_id_counts_even_if_its_mtime_is_old(tmp_path):
    """The strongest evidence is the file saying so itself. A snapshot written
    early in a long cycle can be hours old and still belong to it."""
    started = datetime.now(timezone.utc)
    _satisfy(tmp_path, D_SCORE_REQUIRES, cycle_id=CYCLE)
    old = (started - timedelta(hours=13)).timestamp()
    for rel in D_SCORE_REQUIRES:
        os.utime(tmp_path / rel, (old, old))

    assert verify_or_refuse(FROM, "D_SCORE", CYCLE, started, base_dir=tmp_path)


def test_a_file_carrying_a_DIFFERENT_cycle_id_does_not_count(tmp_path):
    started = datetime.now(timezone.utc)
    _satisfy(tmp_path, D_SCORE_REQUIRES, cycle_id="2026-08-19T03:04:01+03:00")
    old = (started - timedelta(hours=13)).timestamp()
    for rel in D_SCORE_REQUIRES:
        os.utime(tmp_path / rel, (old, old))

    with pytest.raises(ResumeRefused):
        verify_or_refuse(FROM, "D_SCORE", CYCLE, started, base_dir=tmp_path)


# ---------------------------------------------------------------------------
# (b) Selection
# ---------------------------------------------------------------------------

def test_only_runs_exactly_one_phase():
    assert selected_phases(ONLY, "D_SCORE") == ["D_SCORE"]


def test_from_runs_the_phase_and_everything_after_it():
    names = phase_names()
    assert selected_phases(FROM, names[0]) == names
    assert selected_phases(FROM, names[-1]) == [names[-1]]


def test_an_unknown_phase_is_refused_with_the_real_names():
    with pytest.raises(ResumeRefused) as caught:
        selected_phases(FROM, "D_SCORING")
    assert "D_SCORE" in str(caught.value)


def test_only_does_not_demand_the_requires(tmp_path):
    """--only is the operator deliberately running one phase. --from is the one
    that silently claims the earlier phases happened."""
    assert verify_or_refuse(ONLY, "D_SCORE", CYCLE,
                            datetime.now(timezone.utc), base_dir=tmp_path) == ["D_SCORE"]


@pytest.mark.parametrize("phase", ["B_SENSE", "C_SNAPSHOT", "D_SCORE",
                                   "E_PROPOSE", "F_SELF", "G_LEARN"])
def test_every_resumable_phase_reports_its_requires(tmp_path, phase):
    rows = check_requires(phase, CYCLE, datetime.now(timezone.utc), base_dir=tmp_path)
    assert rows, f"{phase} declares no requires, so --from {phase} checks nothing"
    assert all(r["ok"] is False for r in rows), "tmp_path is empty; nothing can be ok"


# ---------------------------------------------------------------------------
# (c) The gate is read-only — it must not touch the running cycle's lock
# ---------------------------------------------------------------------------

def test_the_cli_refuses_without_claiming_the_cycle_lock():
    """REGRESSION, 20 Aug 2026. The first version called _classify_cycle_id() to
    learn the cycle_id — and that function CLAIMS memory/cycle.lock as a side
    effect. Running `--from D_SCORE` therefore overwrote the lock of a cycle
    that was still on disk. A gate that seizes the lock in order to announce it
    will not run is worse than no gate.
    """
    lock = REPO / "memory" / "cycle.lock"
    before = lock.read_bytes() if lock.exists() else None

    result = subprocess.run(
        [sys.executable, str(REPO / "fast_cycle_runner.py"), "--from", "D_SCORE"],
        cwd=str(REPO), capture_output=True, text=True, timeout=180,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    after = lock.read_bytes() if lock.exists() else None
    assert after == before, (
        "running the resume gate modified memory/cycle.lock. It must be read-only: "
        "a live cycle owns that file."
    )
    assert "поех ключалката" not in result.stdout, (
        "the gate ran the boot block, which claims the lock"
    )
    assert result.returncode == 2, f"expected refusal exit 2, got {result.returncode}"
    assert "REFUSING --from" in result.stdout
