"""An empty fetch must never erase an axis.

WHAT HAPPENED (measured 2026-08-04). The axis snapshot agents did:

    raw = provider.fetch()
    _write(folder, axis, {"source_type": "REAL_DATA", "metrics": raw, "raw": raw})

An empty fetch raises nothing, so `{}` went down the SUCCESS path and was written as
REAL_DATA. GOVERNANCE_INSTITUTIONS_REVIEW went from 18 metrics to zero in one cycle;
core.scorer_self_check moved it from "degraded" to DEAD — "reads 10 keys, none exist in
the payload" — while the file on disk still said REAL_DATA. The provider returned all 18
when run by hand minutes later. Nothing about the world had changed.

core/global_indicators.py fixed the same class of bug one layer up a day earlier, after a
slow minute at the World Bank turned eleven metrics into None. That rule is reused here
rather than reimplemented, so "carried" cannot come to mean two different things.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agents.snapshot_carry import carry_forward_metrics  # noqa: E402

PREV = {
    "source_type": "REAL_DATA",
    "metrics": {"rule_of_law_weighted_mean": -0.358,
                "control_of_corruption_weighted_mean": -0.257,
                "government_effectiveness_weighted_mean": 0.076},
    "snapshot_timestamp": "2026-08-01T00:00:00+00:00",
}


def _snapshot(tmp_path, payload):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_an_empty_fetch_carries_every_previous_metric(tmp_path):
    p = _snapshot(tmp_path, PREV)
    merged, carried = carry_forward_metrics(p, {})
    assert merged == PREV["metrics"], "an empty fetch must not erase the axis"
    assert set(carried) == set(PREV["metrics"])


def test_carried_values_keep_their_ORIGINAL_observation_date(tmp_path):
    """Carried is not laundered into fresh — a value copied forward for a month may not
    pass as today's reading."""
    p = _snapshot(tmp_path, PREV)
    _merged, carried = carry_forward_metrics(p, {})
    for key, rec in carried.items():
        assert rec["since"] == PREV["snapshot_timestamp"], key
        assert rec["age_hours"] is None or rec["age_hours"] > 0


def test_a_partial_fetch_keeps_what_it_got_and_carries_only_the_rest(tmp_path):
    p = _snapshot(tmp_path, PREV)
    fresh = {"rule_of_law_weighted_mean": -0.400}
    merged, carried = carry_forward_metrics(p, fresh)
    assert merged["rule_of_law_weighted_mean"] == -0.400, "fresh value must win"
    assert "rule_of_law_weighted_mean" not in carried
    assert merged["control_of_corruption_weighted_mean"] == -0.257
    assert "control_of_corruption_weighted_mean" in carried


def test_the_raw_only_shape_is_also_covered(tmp_path):
    """human/ and cosmos/ store the same values under "raw" and write no "metrics"."""
    p = _snapshot(tmp_path, {"source_type": "REAL_DATA",
                             "raw": {"life_expectancy": 73.48},
                             "snapshot_timestamp": "2026-08-01T00:00:00+00:00"})
    merged, carried = carry_forward_metrics(p, {})
    assert merged == {"life_expectancy": 73.48}
    assert "life_expectancy" in carried


def test_no_previous_snapshot_means_nothing_is_invented(tmp_path):
    merged, carried = carry_forward_metrics(tmp_path / "missing.json", {})
    assert merged == {} and carried == {}
    merged, carried = carry_forward_metrics(tmp_path / "missing.json", {"a": 1})
    assert merged == {"a": 1} and carried == {}


def test_a_previous_snapshot_with_no_values_carries_nothing(tmp_path):
    p = _snapshot(tmp_path, {"source_type": "REAL_DATA", "metrics": {}})
    merged, carried = carry_forward_metrics(p, {})
    assert merged == {} and carried == {}


def test_the_carried_marker_does_not_leak_into_the_metrics(tmp_path):
    p = _snapshot(tmp_path, PREV)
    merged, _carried = carry_forward_metrics(p, {})
    assert "_carried" not in merged, "bookkeeping must sit beside the metrics, not inside"


def test_every_axis_agent_guards_the_empty_fetch():
    """The guard is the whole fix; a new agent without it silently reopens the hole."""
    agents = ["agents/civilization/civilization_snapshots_agent_qwen.py",
              "agents/human/human_snapshots_agent_qwen.py",
              "agents/cosmos/cosmos_snapshots_agent_qwen.py"]
    for rel in agents:
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "if not raw:" in src, f"{rel} writes an empty fetch as REAL_DATA"
        assert "carry_forward" in src, f"{rel} has no carry-forward path"
