"""Permanent test suite for trend_tracker axis scoring (item 6).

THE BUG
-------
trend_tracker reported GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL = 0.0 while the real
scorer (cortex_scoring_engine / wellbeing_globe --governance-only) said 0.44.

It was not a 0-100 vs 0-1 mismatch. trend_tracker never read the scoring engine
at all: it re-derived its own score by averaging raw metric values clamped with
max(0, min(100, val)). The governance metrics are World Bank WGI indicators,
which are z-scores on a -2.5..+2.5 scale where the world average is ~0. All
three were slightly negative, so all three clamped to 0 — and the mean of
zeros is 0.0.

The same assumption ("every metric is a 0-100 percentage") corrupted other axes
too: 9,000 satellites and 114 treaty signatories both clamped to a perfect 100.

THE FIX
-------
The score now comes from cortex_scoring_engine (the authoritative per-axis
scorer, 0-1, rescaled to 0-100). The crude metric mean survives only as a
labelled fallback, so a rough number can never pass as an authoritative one.
"""
import json

import pytest

import memory.trend_tracker as tt


@pytest.fixture
def engine_scores_file(tmp_path, monkeypatch):
    def _write(scores):
        p = tmp_path / "cortex_scores_latest.json"
        p.write_text(json.dumps({
            "generated_at": "2026-07-11T07:57:54+00:00",
            "scorer_version": "1.1",
            "scores": {k: {"score": v, "level": "MEDIUM"} for k, v in scores.items()},
        }), encoding="utf-8")
        monkeypatch.setattr(tt, "SCORES_PATH", p)
        return p
    return _write


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------


def test_governance_rights_is_not_zero(engine_scores_file):
    """THE bug: 0.0 while the real scorer said 0.44."""
    engine_scores_file({"GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": 0.44})

    metrics = {"rule_of_law": -0.046, "voice_accountability": -0.1,
               "political_stability": -0.026}
    score, source = tt._compute_axis_score(metrics, "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL")

    assert score == 44.0, "must match the scoring engine (0.44 -> 44.0)"
    assert source == "cortex_scoring_engine"
    assert score != 0.0, "the clamped-negative-WGI bug is back"


def test_engine_score_is_rescaled_from_0_1_to_0_100(engine_scores_file):
    engine_scores_file({"SOME_AXIS": 0.43})
    score, _ = tt._compute_axis_score({"x": 1.0}, "SOME_AXIS")
    assert score == 43.0


def test_engine_score_wins_over_the_metric_mean(engine_scores_file):
    """Even when the metric mean would produce a plausible-looking number."""
    engine_scores_file({"AXIS": 0.5})
    # metric mean would say 90.0 here
    score, source = tt._compute_axis_score({"some_pct": 90.0}, "AXIS")
    assert score == 50.0
    assert source == "cortex_scoring_engine"


def test_score_zero_from_engine_is_respected(engine_scores_file):
    """A genuine 0.0 from the real scorer must not be mistaken for 'missing'
    and silently replaced by the fallback."""
    engine_scores_file({"AXIS": 0.0})
    score, source = tt._compute_axis_score({"some_pct": 90.0}, "AXIS")
    assert score == 0.0
    assert source == "cortex_scoring_engine", "a real 0.0 is a value, not an absence"


# ---------------------------------------------------------------------------
# The labelled fallback
# ---------------------------------------------------------------------------


def test_axis_missing_from_engine_falls_back_and_says_so(engine_scores_file):
    engine_scores_file({"OTHER_AXIS": 0.5})
    score, source = tt._compute_axis_score({"pct_metric": 60.0}, "UNSCORED_AXIS")
    assert score == 60.0
    assert source == "fallback_metric_mean", "a crude score must be labelled crude"


def test_missing_scores_file_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "SCORES_PATH", tmp_path / "nope.json")
    score, source = tt._compute_axis_score({"pct_metric": 60.0}, "AXIS")
    assert score == 60.0
    assert source == "fallback_metric_mean"


def test_corrupt_scores_file_falls_back(tmp_path, monkeypatch):
    p = tmp_path / "cortex_scores_latest.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(tt, "SCORES_PATH", p)
    score, source = tt._compute_axis_score({"pct_metric": 60.0}, "AXIS")
    assert source == "fallback_metric_mean"


def test_fallback_normalises_wgi_instead_of_clamping_to_zero(tmp_path, monkeypatch):
    """Even the fallback must not collapse a below-average WGI score to 0.

    rule_of_law = 0.0 is the world average -> the middle of the scale (50),
    not 'the worst possible governance on Earth'.
    """
    monkeypatch.setattr(tt, "SCORES_PATH", tmp_path / "nope.json")

    score, source = tt._compute_axis_score({"rule_of_law": 0.0}, "AXIS")

    assert source == "fallback_metric_mean"
    assert score == 50.0, "WGI 0.0 (world average) must map to the middle, not 0"


def test_fallback_maps_wgi_extremes_correctly(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "SCORES_PATH", tmp_path / "nope.json")

    worst, _ = tt._compute_axis_score({"rule_of_law": -2.5}, "A")
    best, _ = tt._compute_axis_score({"rule_of_law": 2.5}, "A")

    assert worst == 0.0
    assert best == 100.0


def test_fallback_still_inverts_bad_is_high_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "SCORES_PATH", tmp_path / "nope.json")
    score, _ = tt._compute_axis_score({"infant_mortality": 27.7}, "AXIS")
    assert score == pytest.approx(72.3), "inverted metrics must stay inverted"


def test_no_metrics_and_no_engine_score_yields_none(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "SCORES_PATH", tmp_path / "nope.json")
    score, _ = tt._compute_axis_score({}, "AXIS")
    assert score is None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_load_engine_scores_rescales_every_axis(engine_scores_file):
    engine_scores_file({"A": 0.44, "B": 1.0, "C": 0.0})
    got = tt._load_engine_scores()
    assert got == {"A": 44.0, "B": 100.0, "C": 0.0}


def test_load_engine_scores_skips_non_numeric(engine_scores_file, tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"scores": {
        "GOOD": {"score": 0.5},
        "BAD":  {"score": None},
        "UGLY": {},
    }}), encoding="utf-8")
    monkeypatch.setattr(tt, "SCORES_PATH", p)

    got = tt._load_engine_scores()

    assert got == {"GOOD": 50.0}, "a null score is not a zero score"


# ---------------------------------------------------------------------------
# The real files agree
# ---------------------------------------------------------------------------


def test_real_engine_scores_load_and_governance_is_nonzero():
    """Guards the actual repo state, not a fixture: whatever the scoring engine
    currently says about governance, it must not be the old fake 0.0."""
    scores = tt._load_engine_scores()
    if not scores:
        pytest.skip("no cortex_scores_latest.json in this checkout")

    gov = scores.get("GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL")
    if gov is None:
        pytest.skip("governance axis not scored in this run")

    assert gov > 0.0, "governance collapsed to 0.0 again"
    assert 0.0 <= gov <= 100.0, "score must be on the 0-100 scale"
