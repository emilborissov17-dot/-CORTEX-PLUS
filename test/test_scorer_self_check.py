"""Tests for the scoring-layer facade self-check (core/scorer_self_check.py).

The check exists to make the CLIMATE-LOW / EDUCATION-0.50 bug class LOUD: a
scorer that reads metric keys the provider never emits silently defaults to a
constant. Verdicts are keyed on whether read keys EXIST in the payload, so a
transient all-None data outage reads as STALE, never as a bug.
"""
import pytest

from core import scorer_self_check as sc


# ── pure verdict logic (classify) ────────────────────────────────────────────

def test_dead_when_no_read_key_exists():
    r = sc.classify({"adult_literacy_rate", "pisa_score_average"},
                    {"literacy_rate_adult_pct": 87.7})  # provider uses different names
    assert r["verdict"] == sc.DEAD
    assert r["n_exist"] == 0


def test_dead_on_empty_snapshot():
    r = sc.classify({"rule_of_law", "democracy_index"}, {})
    assert r["verdict"] == sc.DEAD


def test_stale_when_keys_exist_but_all_none():
    """Wiring is fine; the data source returned nothing this cycle. NOT a bug."""
    r = sc.classify({"gdp_growth", "unemployment"},
                    {"gdp_growth": None, "unemployment": None})
    assert r["verdict"] == sc.STALE


def test_live_when_all_keys_present():
    r = sc.classify({"gdp_growth", "unemployment"},
                    {"gdp_growth": 2.1, "unemployment": 5.0})
    assert r["verdict"] == sc.LIVE


def test_degraded_when_some_keys_never_appear():
    r = sc.classify({"urban_population_pct", "access_to_electricity_pct"},
                    {"urban_population_pct": 65.0})  # 2nd name never appears
    assert r["verdict"] == sc.DEGRADED
    assert r["keys_never_appear"] == ["access_to_electricity_pct"]


def test_unwraps_nested_metrics():
    r = sc.classify({"literacy_rate_adult_pct"},
                    {"axis": "EDU", "metrics": {"literacy_rate_adult_pct": 90.0}})
    assert r["verdict"] == sc.LIVE


def test_transient_outage_never_reads_as_dead():
    """Design-fix regression: a correctly-wired scorer whose data is all None
    this cycle must be STALE, not DEAD (no false alarm on data outages)."""
    r = sc.classify({"k1", "k2", "k3"}, {"k1": None, "k2": None, "k3": None})
    assert r["verdict"] != sc.DEAD


def test_no_keys_when_scorer_reads_nothing_literal():
    r = sc.classify(set(), {"anything": 1})
    assert r["verdict"] == sc.NO_KEYS


# ── keys_read against a real (source-backed) function ─────────────────────────

def _sample_scorer(metrics):
    a = metrics.get("literacy_rate_adult_pct")
    b = metrics.get('secondary_enrollment_pct', 0)  # single quotes + default
    return a, b


def test_keys_read_extracts_literal_gets():
    assert sc.keys_read(_sample_scorer) == {"literacy_rate_adult_pct",
                                            "secondary_enrollment_pct"}


# ── audit() aggregation ──────────────────────────────────────────────────────

def test_audit_summary_and_lists():
    def dead_scorer(metrics):
        return metrics.get("absent_a")

    def live_scorer(metrics):
        return metrics.get("present_a")

    rep = sc.audit({"DEADAXIS": dead_scorer, "LIVEAXIS": live_scorer},
                   {"DEADAXIS": {"other": 1}, "LIVEAXIS": {"present_a": 3}})
    assert rep["dead"] == ["DEADAXIS"]
    assert rep["summary"][sc.DEAD] == 1
    assert rep["summary"][sc.LIVE] == 1


def test_no_snapshot_for_scorer_without_data():
    def orphan(metrics):
        return metrics.get("k")

    rep = sc.audit({"ORPHAN": orphan}, {})
    assert rep["axes"][0]["verdict"] == sc.NO_SNAPSHOT


def test_main_exit_code_reflects_dead(monkeypatch):
    """main() returns non-zero iff a dead scorer exists (usable as a gate)."""
    base = {"axes": [], "summary": {}, "degraded": [], "stale": [], "no_snapshot": []}
    monkeypatch.setattr(sc, "run_from_snapshots", lambda: {**base, "dead": ["X"]})
    assert sc.main() == 1
    monkeypatch.setattr(sc, "run_from_snapshots", lambda: {**base, "dead": []})
    assert sc.main() == 0


# ── live wiring smoke test ────────────────────────────────────────────────────

def test_run_from_snapshots_smoke():
    """Runs against the real snapshots without error, returns the structure."""
    rep = sc.run_from_snapshots()
    assert set(rep) >= {"axes", "summary", "dead", "degraded"}
    assert isinstance(rep["dead"], list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
