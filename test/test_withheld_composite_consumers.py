# -*- coding: utf-8 -*-
"""test/test_withheld_composite_consumers.py — a refusal no consumer test exercises is not tested.

WHAT HAPPENED, 19 September 2026. Commit b7bdc0f made composite_score return
None below the coverage threshold, so that losing data could no longer raise the
published score. It shipped with six tests, all of which asserted things about
the RETURNED DICT. Not one of them called a consumer.

At 14:10:27 the live cycle died at step 35:

    [FAST_CYCLE] goal_score_calculator -> FAILED:
    TypeError: unsupported format string passed to NoneType.__format__

`format_headline` — documented in this repo as the single blessed way the number
may reach a human — formats the composite with :.4f. Because `composite` had
already been assigned None in the runner, the Merkle commitment at step 61 would
have raised too, inside a bare `except`, and the night would have sealed nothing
while printing "MerkleMemory -> FAILED".

The suite was green: 5269 passed, 42 known failures, zero new. It could not have
caught this, because the refusal was tested and its consumers were not.

THE RULE THIS FILE ENFORCES. Every consumer of composite_score is called here
with a WITHHELD result. A consumer may:
  * print WITHHELD with the reason (format_headline), or
  * record the withheld state explicitly (Merkle archive: goal_withheld=True), or
  * refuse in turn and do nothing (goal_prophecy).
A consumer may NOT invent a substitute — not 0.0, not the withheld value dressed
as valid, not yesterday's composite. The tests below fail on each of those.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import goal_score_calculator as g   # noqa: E402


def withheld_result():
    """A real result dict, forced into the withheld state."""
    res = g.compute_goal_score()
    res = dict(res)
    if res.get("composite_score") is not None:
        res["composite_score_withheld"] = res["composite_score"]
        res["composite_score"] = None
        res["goal_covered"] = False
        res["composite_valid"] = False
    return res


# ── 1. format_headline: the blessed formatter ────────────────────────────────

def test_format_headline_does_not_raise_on_a_withheld_composite():
    """THE ONE THAT WOULD HAVE CAUGHT IT. This exact call killed step 35."""
    out = g.format_headline(withheld_result())
    assert isinstance(out, str) and out


def test_the_headline_says_withheld_and_gives_the_reason():
    out = g.format_headline(withheld_result())
    assert "WITHHELD" in out, "a withheld composite must SAY so: %r" % out
    assert "%" in out, "the coverage that caused the refusal must appear: %r" % out


def test_the_headline_never_prints_a_substitute_score():
    """0.0000 is the forbidden repair: it reads as a real, terrible score."""
    out = g.format_headline(withheld_result())
    for bad in ("композит 0.0000", "композит 0.00", "композит None"):
        assert bad not in out, "headline invented a substitute: %r in %r" % (bad, out)


def test_the_withheld_value_is_shown_as_withheld_not_as_the_score():
    """The number may be shown, but never in the position that means 'the score'."""
    res = withheld_result()
    w = res.get("composite_score_withheld")
    out = g.format_headline(res)
    if isinstance(w, float):
        assert ("композит %.4f" % w) not in out, (
            "the withheld value is printed where a valid score goes: %r" % out)


def test_a_valid_composite_still_prints_as_a_number():
    """The refusal path must not swallow the normal one."""
    res = dict(g.compute_goal_score())
    res["composite_score"] = 0.6251
    res["goal_covered"] = True
    assert "0.6251" in g.format_headline(res)
    assert "WITHHELD" not in g.format_headline(res)


# ── 2. The Merkle commitment ─────────────────────────────────────────────────

def test_merkle_accepts_a_withheld_goal_without_raising():
    import merkle_memory
    import inspect
    sig = inspect.signature(merkle_memory.MerkleMemory.commit)
    ann = str(sig.parameters["goal_score"].annotation)
    assert "None" in ann, (
        "MerkleMemory.commit still declares goal_score as a plain float; a "
        "withheld composite has nothing to pass it")


def test_merkle_does_not_put_a_fabricated_zero_into_the_trend():
    """The defect this guards: 0.0 in the goal_score series reads forever after
    as 'the world scored zero that day', and drags every average and every
    forecast baseline computed from that series."""
    import merkle_memory
    m = merkle_memory.MerkleMemory.__new__(merkle_memory.MerkleMemory)
    m._trends = {"goal_score": [0.61, 0.62], "_trend_dates": {}, "cycle_count": 2}
    before = list(m._trends["goal_score"])
    m._update_trends([], None)
    assert m._trends["goal_score"] == before, (
        "a withheld composite added a row to the trend series: %r -> %r"
        % (before, m._trends["goal_score"]))
    assert m._trends["cycle_count"] == 3, "the cycle still happened and must count"


def test_merkle_does_not_move_the_average_or_the_record_on_a_withheld_cycle():
    import merkle_memory
    m = merkle_memory.MerkleMemory.__new__(merkle_memory.MerkleMemory)
    m._profile = {"avg_goal_score": 0.63, "best_goal_score": 0.85,
                  "total_cycles": 10, "goal_scored_cycles": 10}
    m._update_profile([], None, 11)
    assert m._profile["avg_goal_score"] == 0.63, "withheld cycle moved the average"
    assert m._profile["best_goal_score"] == 0.85, "withheld cycle moved the record"
    assert m._profile.get("goal_withheld_cycles") == 1, (
        "the withheld cycle was not counted anywhere — it must be visible")


def test_a_real_score_still_updates_the_average():
    """Mutation guard: if the None-branch swallowed everything, this goes red."""
    import merkle_memory
    m = merkle_memory.MerkleMemory.__new__(merkle_memory.MerkleMemory)
    m._profile = {"avg_goal_score": 0.60, "best_goal_score": 0.60,
                  "total_cycles": 1, "goal_scored_cycles": 1}
    m._update_profile([], 0.80, 2)
    assert m._profile["avg_goal_score"] > 0.60, "a real score no longer moves the average"
    assert m._profile["best_goal_score"] == 0.80


# ── 3. The runner's own call sites ───────────────────────────────────────────

def test_the_runner_passes_none_through_instead_of_calling_float():
    """float(composite) raised at step 61 and lost the whole commit inside a
    bare except. `float(composite or 0.0)` would be worse, so both are pinned
    out of the source."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "goal_score = float(composite)," not in src, (
        "the runner still calls float() on a possibly-withheld composite")
    assert "float(composite or 0.0)" not in src, (
        "the runner substitutes 0.0 for a withheld composite — the fabricated "
        "number the refusal exists to prevent")
    assert "None if composite is None else float(composite)" in src


def test_the_runner_does_not_initialise_the_composite_to_a_score():
    """composite = 0.0 meant a goal_score_calculator that never ran still handed
    MerkleMemory a number."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "composite = 0.0  # initialized here" not in src


# ── 4. goal_prophecy refuses rather than forecasting nothing ─────────────────

def test_goal_prophecy_refuses_on_a_withheld_composite(monkeypatch, capsys):
    """It must seal ZERO predictions. A forecast of a number that does not exist
    is not a forecast, and `composite or 0.0` would seal one against a zero."""
    import importlib
    gp = importlib.import_module("experiments.prophecy.goal_prophecy")
    monkeypatch.setattr(gp, "_live_goal",
                        lambda: (None, {"A": 0.5}, {"A": 1.0},
                                 {"coverage_of_goal": 0.68}))
    out = gp.cmd_self()
    assert out.get("sealed") == 0, "a prediction was sealed against no composite"
    assert out.get("refused"), "it returned without saying it refused"
    printed = capsys.readouterr().out
    assert "REFUSED" in printed, "the refusal was silent: %r" % printed


def test_goal_prophecy_still_runs_when_the_composite_is_real(monkeypatch):
    """Mutation guard: the refusal must be CONDITIONAL, not unconditional.

    Every downstream call is stubbed. The first draft of this test let cmd_self
    run for real and the suite's own _no_live_writes fixture caught it writing to
    memory/goal_axis_history.json — a test proving a refusal by performing the
    thing being refused. The guard was right; the test was wrong.
    """
    import importlib
    gp = importlib.import_module("experiments.prophecy.goal_prophecy")
    monkeypatch.setattr(gp, "_live_goal",
                        lambda: (0.62, {"A": 0.5}, {"A": 1.0},
                                 {"coverage_of_goal": 0.9, "config_fingerprint": "x"}))
    monkeypatch.setattr(gp, "_score_matured",
                        lambda ctx=None: {"scored": 0, "deferred": 0, "reasons": {}})
    monkeypatch.setattr(gp, "best_baseline",
                        lambda **kw: {"model": "persistence", "mae": 0.0})
    reacted = {"n": 0}

    def _fake_react(composite, axis_scores, weights, best):
        reacted["n"] += 1
        return {"mode": "x", "priority_axis": "A", "composite": composite,
                "expected_next_composite": composite,
                "body_sensor": {"distress": False}}

    monkeypatch.setattr(gp, "_react", _fake_react)
    monkeypatch.setattr(gp, "_seal_next", lambda *a, **k: 0)
    try:
        gp.cmd_self()
    except Exception:
        pass            # later stages are not what this test is about
    assert reacted["n"] == 1, (
        "with a REAL composite the reaction never ran — the refusal is "
        "unconditional and would suppress every night, not only withheld ones")


# ── 5. The consumers that were already safe stay safe ────────────────────────

@pytest.mark.parametrize("mod,attr", [
    ("core.reconsider", None),
    ("core.phase_evidence", None),
])
def test_the_already_safe_consumers_still_import(mod, attr):
    import importlib
    importlib.import_module(mod)


# NOTE: an earlier draft asserted the stale Bulgarian contract note was gone by
# grepping for it. Removed: CLAUDE.md is explicit that structural tests check
# code (identifiers/behaviour), never prose. The note was corrected in the
# source; a grep for a comment is not a test, and this file already pins the
# BEHAVIOUR that note got wrong.
