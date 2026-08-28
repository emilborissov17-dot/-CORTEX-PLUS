"""The two axes that declared a metric and never got a number.

WHAT WAS WRONG
--------------
PLANETARY_POTENTIAL_REVIEW declares primary_metric protected_terrestrial_area_pct
and EDUCATION_CULTURE_REVIEW declares primary_completion_rate. goal_score_
calculator._resolve_metric has mapped both to obs keys since it was written:

    "protected_terrestrial_area_pct": "wb_ER.LND.PTLD.ZS"
    "primary_completion_rate":        "wb_SE.PRM.CMPT.ZS"

Nothing ever put those keys INTO last_obs. Not data/last_observations.json
(8 keys, frozen 2026-06-17, and its only writer is imported by nothing), not
memory/probed_signals.json (does not exist), and not load_global_indicators()'s
hard-coded put() list. So both axes reported metric_unresolved every cycle and
14 of 173 goal weight — K1's denominator — resolved to nothing. (That
denominator is 167 across 24 axes since commit 8052397, 2026-08-21. The 14
did not move: neither of these axes was the one retired.)

Worth stating because it was nearly fixed the expensive way: the obvious
suspect was config/axis_source_map.json's wrong-row entry, and correcting that
would have moved K1 by exactly zero. goal_score_calculator does not read
memory/composed_indicators.json at all — the composer pipeline and the scoring
pipeline are not connected. The fix is four lines in the OTHER pipeline.

WHAT THIS SUITE HOLDS
---------------------
That the two indicators are fetched, that they reach last_obs under the keys
_resolve_metric already expects, and that the mapping is not quietly renamed.
It does NOT assert the world values themselves — those move — only that the
plumbing carries whatever the World Bank says.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import goal_score_calculator as g          # noqa: E402
from core import global_indicators as gi   # noqa: E402

PAIRS = (
    ("protected_terrestrial_area_pct", "wb_ER.LND.PTLD.ZS", "ER.LND.PTLD.ZS",
     "PLANETARY_POTENTIAL_REVIEW"),
    ("primary_completion_rate", "wb_SE.PRM.CMPT.ZS", "SE.PRM.CMPT.ZS",
     "EDUCATION_CULTURE_REVIEW"),
)


@pytest.mark.parametrize("metric,obs_key,indicator,axis", PAIRS)
def test_the_metric_still_maps_to_the_obs_key(metric, obs_key, indicator, axis):
    """If someone renames one side, this says so before a cycle does."""
    src = (REPO / "goal_score_calculator.py").read_text(encoding="utf-8")
    assert f'"{metric}":' in src and f'"{obs_key}"' in src, (
        f"{metric} -> {obs_key} is the mapping the fix depends on")


@pytest.mark.parametrize("metric,obs_key,indicator,axis", PAIRS)
def test_the_indicator_is_actually_fetched(metric, obs_key, indicator, axis):
    src = (REPO / "core" / "global_indicators.py").read_text(encoding="utf-8")
    assert f'_wb_world("{indicator}")' in src, (
        f"{indicator} must be fetched, or {metric} has nothing to resolve from")
    assert f'"{metric}"' in src


@pytest.mark.parametrize("metric,obs_key,indicator,axis", PAIRS)
def test_the_value_reaches_last_obs(metric, obs_key, indicator, axis):
    """The join that was missing: fetched is not the same as available."""
    src = (REPO / "goal_score_calculator.py").read_text(encoding="utf-8")
    assert f'put("{obs_key}"' in src, (
        f"{obs_key} is fetched but never put into last_obs — which is exactly "
        f"the state this fix ended")


def test_both_axes_resolve_when_the_keys_are_present():
    """The whole point, asserted on the computation rather than on a file.

    Uses an injected last_obs so the test never writes live state and never
    depends on when the last cycle ran.
    """
    obs = {"wb_ER.LND.PTLD.ZS": 16.5, "wb_SE.PRM.CMPT.ZS": 88.0}
    for metric, obs_key, _ind, _axis in PAIRS:
        assert g._resolve_metric(metric, {}, obs) is not None, (
            f"{metric} did not resolve from {obs_key}")


def test_neither_axis_resolves_without_them():
    """The negative control: absent keys must still mean unresolved, not zero."""
    for metric, _k, _i, _a in PAIRS:
        assert g._resolve_metric(metric, {}, {}) is None, (
            "a missing observation must be None, never a default")


def test_the_year_is_recorded_beside_the_value():
    """A world value with no year cannot be judged for staleness."""
    src = (REPO / "core" / "global_indicators.py").read_text(encoding="utf-8")
    for _m, _k, indicator, _a in PAIRS:
        assert f'_WB_YEARS.get("{indicator}")' in src, (
            f"{indicator} must record its observed year")
