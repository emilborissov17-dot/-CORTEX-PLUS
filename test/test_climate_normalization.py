"""Permanent test suite for CLIMATE_GLOBAL_RISK normalization (climate LOW bug).

THE BUG
-------
`normalize_climate()` computed its risk_score from three metric keys —
`temperature_trend`, `extreme_days_share`, `precipitation_change` — that the
provider (climate_global_risk_review_provider.py) NEVER emits under those names.
Each `_safe_get(..., 0.0)` therefore returned 0.0, so:

    risk_score = abs(0.0) + 0.0*2 + abs(0.0)*0.5 = 0.0  →  level = "LOW"

...every single cycle, regardless of reality. Meanwhile the real, alarming
readings (CO₂ 428 ppm and rising, +1.19 °C on record) sat unused in the SAME
payload. The planetary synthesis (Cerebras) then faithfully echoed LOW — a dead
computation publishing a green light. A second bug double-prefixed provider
keys: `forecast_forecast_max_temp_7d`, `wb_wb_country_code_mentions`.

THE FIX
-------
`normalize_climate()` now scores from the keys the provider actually emits, led
by CO₂ concentration (the globally-valid signal). Missing data maps to None →
UNKNOWN, never a silent LOW. The provider emits single-prefix keys.

Sanity anchor: with CO₂ ≥ 425 ppm and rising, this axis MUST NOT resolve LOW.
"""
import pytest

from data_providers.planet.planet_normalization import normalize_climate


# The real metrics block from
# snapshots/planet/climate_global_risk/climate_global_risk_snapshot_latest.json
# (2026-07-20), with the double-prefix bug fixed to the corrected key name.
REAL_SNAPSHOT_METRICS = {
    "co2_ppm_current": 428.48,
    "co2_ppm_year_ago": 427.91,
    "co2_annual_increase": 0.57,
    "co2_date": "2026-07-12",
    "co2_annual_mean": 427.35,
    "archive_precipitation_variability": 2.1825398892247443,
    "forecast_max_temp_7d": 31.4,
    "forecast_heavy_rain_days_7d": 0.0,
    "wb_country_code_mentions": 0.0,
}


def _norm(metrics):
    return normalize_climate({"metrics": metrics, "data_mode": "REAL_FROM_APPROVED_SOURCE"})


def test_real_co2_428_is_not_low():
    """The regression: CO₂ 428 rising used to score LOW. It must not anymore."""
    out = _norm(REAL_SNAPSHOT_METRICS)
    assert out["level"] != "LOW", f"CO₂ 428 rising resolved to {out['level']} — the bug is back"
    # 428 (>=425 → +2.0) + rising 0.57 (+0.5) + precip σ/μ 2.18 (+0.5) = 3.0 → HIGH
    assert out["level"] == "HIGH", f"expected HIGH, got {out['level']} (score={out['risk_score']})"
    assert out["risk_score"] >= 2.5


def test_co2_dominates_even_with_benign_local_weather():
    """A mild 7-day local forecast must not drag global risk down to LOW."""
    out = _norm({"co2_ppm_current": 428.48, "co2_annual_increase": 0.57,
                 "forecast_max_temp_7d": 18.0})  # cool local week
    assert out["level"] != "LOW"


def test_missing_data_is_unknown_not_low():
    """The core harm was defaulting absent data to LOW. Absent → UNKNOWN now."""
    out = _norm({"forecast_heavy_rain_days_7d": 0.0})  # no CO₂, no temp, no var
    assert out["level"] == "UNKNOWN"
    assert out["source_type"] == "NO_REAL_DATA"


def test_genuinely_safe_co2_is_low():
    """Pre-industrial-ish CO₂ below the 350 boundary, not rising → LOW is correct."""
    out = _norm({"co2_ppm_current": 300.0, "co2_annual_increase": -0.1})
    assert out["level"] == "LOW"


def test_co2_450_is_high():
    out = _norm({"co2_ppm_current": 451.0, "co2_annual_increase": 2.4})
    assert out["level"] == "HIGH"


def test_risk_score_is_persisted_into_metrics():
    """climate_risk_score was a description with no value — now it carries one."""
    out = _norm(REAL_SNAPSHOT_METRICS)
    assert "climate_risk_score" in out["metrics"]
    assert out["metrics"]["climate_risk_score"] == out["risk_score"]


def test_provider_emits_single_prefix_keys():
    """Guard the double-prefix regression at the source: internal fetch methods
    return bare keys so fetch() can apply exactly one prefix."""
    import inspect
    from data_providers.planet import climate_global_risk_review_provider as prov
    src = inspect.getsource(prov)
    # No internal method may self-prefix (that + fetch()'s uniform prefix = the
    # double bug). fetch() uses the f-string form `metrics[f"forecast_{k}"]`,
    # which does NOT match the non-f assignment pattern below.
    assert 'metrics["forecast_' not in src, "internal method self-prefixes 'forecast_'"
    assert 'metrics["wb_' not in src, "internal method self-prefixes 'wb_'"
    # the corrected bare keys the internal methods now return
    assert '"max_temp_7d"' in src
    assert '"country_code_mentions"' in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
