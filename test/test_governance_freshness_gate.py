# -*- coding: utf-8 -*-
"""test/test_governance_freshness_gate.py - the gate must watch the DATA, not the sum.

THE HOLE THE WEEKLY SCHEDULE OPENED (19 September 2026).

Until today wellbeing_batch.py and wellbeing_globe.py --governance-only both ran
inside the 09:00 chain, so "when the cache was refreshed" and "when governance
was recomputed" were the same morning, and gating on either was the same gate.

From today the batch runs WEEKLY (Sunday, detached, tools/wellbeing_weekly.bat)
and the governance pass runs DAILY. The daily pass reads output/wb_cache/, does
no network, and writes governance_computed_at = now. So on six mornings in seven
it restamps the timestamp without a single input having changed.

Gate the 90-day freshness check on that field and age_days is ~0 EVERY DAY,
forever, no matter how old the WGI/V-Dem data underneath actually is. The check
would still be there, still be 90 days, still print its warning text in the
source - and be incapable of ever firing. A guard that cannot fail is not a
guard; it is a comment.

These tests pin the gate to governance_source_newest_at, and the last one is a
mutation test: point the gate back at governance_computed_at and it goes red.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import goal_score_calculator as g   # noqa: E402


def _globe(source_age_days=None, computed_age_days=0.0, drop_source=False):
    """A wellbeing_globe.json payload with the two timestamps set independently."""
    now = datetime.now(timezone.utc)
    d = {
        "governance_rights_score": 0.43,
        "governance_institutions_score": 0.45,
        "governance_computed_at": (now - timedelta(days=computed_age_days)).isoformat(),
    }
    if not drop_source and source_age_days is not None:
        d["governance_source_newest_at"] = (now - timedelta(days=source_age_days)).isoformat()
    return d


@pytest.fixture
def patched(monkeypatch):
    """Feed load_governance_globals a payload without touching the real file."""
    def install(payload):
        monkeypatch.setattr(g, "_load", lambda path, default=None: payload)
    return install


def test_fresh_inputs_load(patched):
    patched(_globe(source_age_days=3, computed_age_days=0))
    out = g.load_governance_globals()
    assert out.get("governance_rights_score_global") == 0.43


def test_stale_inputs_refuse_even_when_recomputed_this_morning(patched):
    """THE ONE THAT MATTERS.

    Inputs 200 days old, arithmetic run 4 hours ago - exactly the state the
    daily-pass-over-a-weekly-cache produces once the weekly batch stops running.
    The gate must refuse on the 200, not be reassured by the 4 hours.
    """
    patched(_globe(source_age_days=200, computed_age_days=0.17))
    out = g.load_governance_globals()
    assert out == {}, (
        "governance loaded with 200-day-old inputs because the arithmetic was "
        "rerun this morning — the freshness gate is watching the wrong clock")


def test_the_daily_restamp_cannot_rescue_stale_data_at_the_boundary(patched):
    """One day past the threshold refuses; one day inside loads. Pins that the
    threshold is applied to the source date and is not off by a schedule."""
    assert g.GOVERNANCE_FRESHNESS_DAYS == 90, (
        "threshold changed to %r — this test's boundaries are stale"
        % g.GOVERNANCE_FRESHNESS_DAYS)
    patched(_globe(source_age_days=91, computed_age_days=0))
    assert g.load_governance_globals() == {}, "91-day-old inputs were accepted"
    patched(_globe(source_age_days=89, computed_age_days=0))
    assert g.load_governance_globals() != {}, "89-day-old inputs were refused"


def test_an_old_globe_file_without_the_source_field_still_gets_a_gate(patched):
    """Backward compatibility must not become an escape hatch: when
    governance_source_newest_at is absent the gate falls back to
    governance_computed_at, and STILL refuses when that is old."""
    patched(_globe(drop_source=True, computed_age_days=200))
    assert g.load_governance_globals() == {}, (
        "a globe file predating governance_source_newest_at got no gate at all")
    patched(_globe(drop_source=True, computed_age_days=1))
    assert g.load_governance_globals() != {}, "the fallback refused fresh data"


def test_the_observation_date_reports_the_inputs_not_the_arithmetic(patched):
    """The date attached to both axes is what a reader will quote as 'as of'.
    It must be the day the DATA is from."""
    patched(_globe(source_age_days=30, computed_age_days=0))
    g.load_governance_globals()
    expected = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    for k in ("governance_rights_score_global", "governance_institutions_score_global"):
        assert g._OBS_DATES.get(k) == expected, (
            "%s is dated %r, but its inputs are from %s — the observation date "
            "is reporting when the sum was taken"
            % (k, g._OBS_DATES.get(k), expected))


def test_mutation_pointing_the_gate_back_at_the_restamped_field_is_detectable():
    """MUTATION TEST. Simulate the regression — read governance_computed_at
    first — and assert that doing so accepts data this suite must reject. If
    this test ever passes while test_stale_inputs... also passes, the two have
    stopped disagreeing and the gate has been neutered.
    """
    payload = _globe(source_age_days=200, computed_age_days=0.17)

    # What the REGRESSED code would compute.
    regressed_ts = payload.get("governance_computed_at")
    regressed_age = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(regressed_ts)).total_seconds() / 86400
    assert regressed_age <= g.GOVERNANCE_FRESHNESS_DAYS, (
        "the fixture no longer reproduces the regression")

    # What the CURRENT code computes.
    correct_ts = payload.get("governance_source_newest_at")
    correct_age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(correct_ts)).total_seconds() / 86400
    assert correct_age > g.GOVERNANCE_FRESHNESS_DAYS

    # And that the source really does prefer the source field.
    src = (REPO / "goal_score_calculator.py").read_text(encoding="utf-8")
    assert 'data.get("governance_source_newest_at") or data.get("governance_computed_at")' in src, (
        "load_governance_globals no longer prefers governance_source_newest_at; "
        "the 90-day gate is back to watching a field that is restamped daily")
