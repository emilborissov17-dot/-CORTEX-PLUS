"""A step counts as full only if it actually did its work.

flow_score multiplied a completeness ratio by a speed:

    fs = (steps_full / steps_total) * (60.0 / median_step_seconds)

Two independent facts collapsed into one number, neither recoverable from the
result. The speed term is unbounded — the smallest non-zero median the contract
can record is 0.005s, putting the ceiling at 12000 — and band() called anything
above 4.0 "flowing". A cycle whose steps all returned in milliseconds, one that
did NOTHING, scored maximally flowing.

The headline test here is exactly that cycle: fast, degraded, useless. It must
score LOW and raise SUSPECT_PACE, where the old metric gave it the best score it
could produce.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import cycle_integrity as ci  # noqa: E402


def _baseline(tmp_path, medians: dict, n: int = 8):
    """A history file with `n` observations per label at the given median."""
    blob = {label: {"runs": [{"ts": "2026-08-01T00:00:00+00:00", "seconds": sec}
                             for _ in range(n)]}
            for label, sec in medians.items()}
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(blob), encoding="utf-8")
    return p


# ── the headline ────────────────────────────────────────────────────────────

def test_a_cycle_of_degraded_but_fast_steps_scores_low_and_raises_suspect_pace(tmp_path):
    """THE CYCLE THE OLD METRIC CALLED PERFECT."""
    steps = [{"step": "alpha", "seconds": 0.02, "verdict": "DEGRADED",
              "degraded": "answered by local_3b after the cloud tier was abandoned"},
             {"step": "beta", "seconds": 0.03, "verdict": "DEGRADED",
              "degraded": "answered by local_3b after the cloud tier was abandoned"},
             {"step": "gamma", "seconds": 0.02, "verdict": "OK",
              "why": "answered by local_3b after the cloud tier was abandoned"}]
    base = _baseline(tmp_path, {"alpha": 40.0, "beta": 30.0, "gamma": 20.0})

    m = ci.scalars(steps=steps, baseline_path=base)

    assert m["integrity_ratio"] == 0.0, (
        f"a cycle in which nothing did its work scored "
        f"{m['integrity_ratio']} integrity")
    assert m["degraded_ratio"] > 0.6
    assert m["cloud_success_ratio"] == 0.0, (
        "every step fell back to a local model and cloud_success_ratio does "
        "not say so")
    assert m["suspect_pace"]["alarm"] is True
    flagged = {s["step"] for s in m["suspect_pace"]["steps"]}
    assert flagged == {"alpha", "beta", "gamma"}, (
        f"SUSPECT_PACE named {flagged}; every step ran at under 1% of its own "
        f"median")
    assert "fail-open" in m["suspect_pace"]["steps"][0]["why"]


def test_a_normal_cycle_raises_neither(tmp_path):
    steps = [{"step": "alpha", "seconds": 41.0, "verdict": "OK"},
             {"step": "beta", "seconds": 29.0, "verdict": "OK"},
             {"step": "gamma", "seconds": 22.0, "verdict": "OK"}]
    base = _baseline(tmp_path, {"alpha": 40.0, "beta": 30.0, "gamma": 20.0})

    m = ci.scalars(steps=steps, baseline_path=base)
    assert m["integrity_ratio"] == 1.0
    assert m["degraded_ratio"] == 0.0
    assert m["failed_ratio"] == 0.0
    assert m["cloud_success_ratio"] == 1.0
    assert m["suspect_pace"]["alarm"] is False


# ── the redefinition of FULL ────────────────────────────────────────────────

@pytest.mark.parametrize("step,expected,fragment", [
    ({"step": "s", "verdict": "OK"}, True, ""),
    ({"step": "s", "verdict": "DEGRADED"}, False, "DEGRADED"),
    ({"step": "s", "verdict": "RAISED"}, False, "RAISED"),
    ({"step": "s", "verdict": "MISSING"}, False, "MISSING"),
    ({"step": "s", "verdict": "NO_EFFECT"}, False, "NO_EFFECT"),
    ({"step": "s", "verdict": "SLOW"}, False, "SLOW"),
    ({"step": "s", "verdict": "UNKNOWN"}, False, "warmup"),
    ({"step": "s", "verdict": "OK", "degraded": "x"}, False, "degraded"),
    ({"step": "s", "verdict": "OK", "error": "timed out after 20s"}, False, "timed out"),
])
def test_full_is_all_four_conditions(step, expected, fragment):
    full, why = ci.is_full(step)
    assert full is expected, f"{step} -> full={full} ({why})"
    if not expected:
        assert fragment.lower() in why.lower(), f"why={why!r}"


def test_unknown_no_longer_counts_as_full():
    """It used to. A new step inflated the score for three nights, precisely
    when a human was most likely to be watching it."""
    m = ci.scalars(steps=[{"step": "brand_new", "seconds": 1.0,
                           "verdict": "UNKNOWN"}])
    assert m["integrity_ratio"] == 0.0
    assert m["failed_ratio"] == 0.0, (
        "warmup was counted as a FAILURE — it is an absence of judgement, not "
        "a bad one")
    assert "warmup" in m["not_full"][0]["why"]


def test_a_planned_local_fallback_is_not_a_fallback():
    """data_scout owns a labelled sovereign local fallback (Emil-approved)."""
    assert "data_scout" in ci.LOCAL_PLANNED
    full, _ = ci.is_full({"step": "data_scout", "verdict": "OK",
                          "why": "answered by local_3b"})
    assert full is True
    full, why = ci.is_full({"step": "web_intelligence", "verdict": "OK",
                            "why": "answered by local_3b"})
    assert full is False and "locally" in why


# ── SUSPECT_PACE stays silent rather than guessing ──────────────────────────

def test_suspect_pace_is_silent_without_enough_history(tmp_path):
    base = _baseline(tmp_path, {"alpha": 40.0}, n=4)      # under the minimum
    out = ci.suspect_pace([{"step": "alpha", "seconds": 0.01}], baseline_path=base)
    assert out["alarm"] is False
    assert "alpha" in out["unjudged"], (
        "a label with too little history must be named as unjudged, not "
        "silently passed")


def test_suspect_pace_says_why_it_is_silent_with_no_history_at_all(tmp_path):
    empty = tmp_path / "none.json"
    empty.write_text("{}", encoding="utf-8")
    out = ci.suspect_pace([{"step": "a", "seconds": 0.01}], baseline_path=empty)
    assert out["alarm"] is False
    assert out["why_silent"] and "prior observations" in out["why_silent"]


def test_the_floor_is_ten_percent_and_bounds_are_tested(tmp_path):
    base = _baseline(tmp_path, {"alpha": 100.0})
    just_under = ci.suspect_pace([{"step": "alpha", "seconds": 9.9}],
                                 baseline_path=base)
    just_over = ci.suspect_pace([{"step": "alpha", "seconds": 10.1}],
                                baseline_path=base)
    assert just_under["alarm"] is True, "9.9s against a 100s median is not flagged"
    assert just_over["alarm"] is False, "10.1s against a 100s median IS flagged"


# ── no composite may come back ──────────────────────────────────────────────

def test_the_five_are_independent_and_no_product_is_returned():
    m = ci.scalars(steps=[{"step": "a", "seconds": 1.0, "verdict": "OK"}])
    for banned in ("flow_score", "fs", "score", "composite", "band"):
        assert banned not in m, (
            f"measure() returned {banned!r} — the whole point is that these "
            f"five are never combined")
    for k in ("integrity_ratio", "degraded_ratio", "failed_ratio",
              "median_step_seconds", "cloud_success_ratio"):
        assert k in m


def test_band_is_gone_loudly_not_silently():
    with pytest.raises(NotImplementedError) as e:
        ci.band(9.0)
    assert "composite" in str(e.value)


def test_an_empty_cycle_says_why_rather_than_scoring_zero():
    m = ci.scalars(steps=[])
    assert m["integrity_ratio"] is None, (
        "an empty cycle scored 0.0 integrity — that is a measurement of "
        "nothing presented as a bad result")
    assert m["empty_because"]


def test_every_step_that_is_not_full_says_why():
    """'42% integrity' with no account of the other 58% can only be believed
    or ignored."""
    m = ci.scalars(steps=[{"step": "a", "verdict": "OK", "seconds": 1.0},
                          {"step": "b", "verdict": "RAISED", "seconds": 1.0},
                          {"step": "c", "verdict": "UNKNOWN", "seconds": 1.0}])
    assert m["integrity_ratio"] == pytest.approx(1 / 3, abs=1e-4)
    assert len(m["not_full"]) == 2
    for row in m["not_full"]:
        assert row["why"], f"{row['step']} is not full and does not say why"


def test_it_reads_the_live_contract_without_raising():
    """Against the real file, because the shape is the repo's, not the test's."""
    m = ci.scalars()
    assert m["steps_total"] >= 0
    if m["steps_total"]:
        assert 0.0 <= m["integrity_ratio"] <= 1.0
        assert 0.0 <= m["cloud_success_ratio"] <= 1.0
