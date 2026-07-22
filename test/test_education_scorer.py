"""Permanent test suite for EDUCATION_CULTURE scoring (dead-scorer facade).

THE BUG
-------
`score_education` read `adult_literacy_rate` / `literacy_rate_adult_total`,
`school_enrollment_secondary/tertiary`, `education_expenditure_pct_gdp` /
`govt_expenditure_education_pct`, `pisa_score_average` — NONE of which the
provider (education_culture_provider.py, World Bank SE.*/IT.* indicators)
emits. The provider emits `literacy_rate_adult_pct`, `secondary_enrollment_pct`,
`govt_education_spend_pct_gdp`, `internet_users_pct`. Every `metrics.get()`
returned None → the score sat at the base 0.5 forever (axis_history: 50.0,
50.0, 50.0, …) while real literacy/enrollment data rode along unused. Same class
as the CLIMATE LOW facade.

THE FIX
-------
Read the keys the provider actually emits (canonical names first, old names as
fallback). Add the real `internet_users_pct` signal. When NO real reading
survives, mark SELF_REPORTED and say so, instead of publishing 0.5 as measured.
"""
import pytest

from cortex_scoring_engine import score_education


# Real unwrapped metrics from
# snapshots/civilization/education_culture/education_culture_snapshot_latest.json
REAL = {
    "literacy_rate_adult_pct": 87.74,
    "primary_enrollment_pct": None,
    "secondary_enrollment_pct": 66.27,
    "tertiary_enrollment_pct": None,
    "govt_education_spend_pct_gdp": None,
    "internet_users_pct": 73.6,
}


def test_real_data_is_read_not_defaulted():
    """The regression: real literacy 87.7 must actually move the score off 0.5."""
    r = score_education(REAL)
    assert r.metrics_used["literacy"] == pytest.approx(87.74)
    assert r.metrics_used["enrollment"] == pytest.approx(66.27)
    assert r.metrics_used["internet"] == pytest.approx(73.6)
    # literacy 87.74 (80-95 band) -> 0.55; internet 73.6 (40-80) -> no nudge
    assert r.score != 0.5, "score still pinned at the default — scorer is not reading real data"
    assert r.verification == "VERIFIED"


def test_high_literacy_scores_higher_than_low():
    hi = score_education({"literacy_rate_adult_pct": 99.0})
    lo = score_education({"literacy_rate_adult_pct": 60.0})
    assert hi.score > lo.score


def test_old_key_names_still_work_as_fallback():
    """Backward compatibility: any snapshot using the legacy names still scores."""
    r = score_education({"adult_literacy_rate": 99.0,
                         "school_enrollment_secondary": 90.0})
    assert r.metrics_used["literacy"] == pytest.approx(99.0)
    assert r.metrics_used["enrollment"] == pytest.approx(90.0)
    assert r.verification == "VERIFIED"


def test_no_real_data_is_self_reported_not_silent():
    """The core harm: absent data used to publish a silent 0.5. Now flagged."""
    r = score_education({"unrelated_key": 1.0})
    assert r.verification == "SELF_REPORTED"
    assert any("ЛИПСВАЩ" in s for s in r.signals)


def test_canonical_keys_are_the_ones_the_provider_emits():
    """Guard the contract: the names the scorer reads first must match the
    provider's INDicator map, so a rename on either side fails this test."""
    import data_providers.civilization.education_culture_provider as prov
    import inspect
    src = inspect.getsource(prov)
    for key in ("literacy_rate_adult_pct", "secondary_enrollment_pct",
                "govt_education_spend_pct_gdp", "internet_users_pct"):
        assert f'"{key}"' in src, f"provider no longer emits {key}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
