#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_score_prophecies.py — fixtures for the calendar-horizon scoring loop.

Every ledger write goes to a tmp file. The real prophecy_ledger.jsonl is never touched.

The test that matters most is test_original_prediction_is_never_mutated: the whole claim
of a sealed ledger is that a prediction cannot be quietly improved after reality answers.
If scoring edited the record in place, every "we got it right" in this repo would be
unfalsifiable. So it is asserted on the bytes and on the hash, not assumed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "experiments" / "prophecy"))

import score_prophecies as sp  # noqa: E402
import prophecy_ledger as pl  # noqa: E402

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Ledger and composer state both redirected into tmp_path."""
    monkeypatch.setattr(pl, "LEDGER_PATH", tmp_path / "prophecy_ledger.jsonl")
    state = tmp_path / "composer_state"
    state.mkdir()
    monkeypatch.setattr(sp, "COMPOSER_STATE", state)
    return state


def _write_series(state: Path, axis: str, sid: str, values, start=T0, step_days=1):
    """A composer_state file with one source and a dated history."""
    hist = [[(start + timedelta(days=i * step_days)).isoformat(), v]
            for i, v in enumerate(values)]
    f = state / f"{axis}.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"sources": {}}
    doc["sources"][sid] = {"status": "active", "consecutive_fails": 0,
                           "last_value": values[-1] if values else None, "history": hist}
    f.write_text(json.dumps(doc), encoding="utf-8")


def _seal(band, horizon, axis="A_REVIEW", sid="s1", baseline=100.0):
    return pl.seal_prediction(
        sp.KIND, f"{axis}::{sid}", horizon.isoformat(),
        learner_value=sum(band) / 2, baseline_value=baseline,
        basis="test", band=band, axis=axis, source_id=sid, n_points=14)


# ── the band ─────────────────────────────────────────────────────────────────

def test_band_refuses_a_short_series():
    series = [(T0 + timedelta(days=i), 100.0 + i) for i in range(5)]
    band, _, _, why = sp.band_for(series)
    assert band is None
    assert "need 14" in why


def test_band_refuses_a_constant_series():
    """A band around a constant cannot fail — refusing it by name is the point."""
    series = [(T0 + timedelta(days=i), 428.72) for i in range(20)]
    band, _, _, why = sp.band_for(series)
    assert band is None
    assert "cannot fail" in why


def test_band_from_real_variance():
    vals = [100.0 + (i % 3) for i in range(20)]
    series = [(T0 + timedelta(days=i), v) for i, v in enumerate(vals)]
    band, centre, sigma, why = sp.band_for(series)
    assert why is None
    assert sigma > 0
    assert band[0] < centre < band[1]


# ── scoring: hit / miss / unresolvable ───────────────────────────────────────

def test_hit_is_scored(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0], start=T0)
    _seal([99.0, 103.0], T0)
    res = sp.score_matured(now=T0 + timedelta(days=1))
    assert res["hit"] == 1 and res["miss"] == 0
    out = [r for r in pl.read_all() if r["event"] == pl.OUTCOME]
    assert out[-1]["verdict"] == "hit"
    assert out[-1]["learner_err"] == 0.0


def test_miss_is_scored_with_distance_to_the_band(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [120.0], start=T0)
    _seal([99.0, 103.0], T0)
    res = sp.score_matured(now=T0 + timedelta(days=1))
    assert res["miss"] == 1
    out = [r for r in pl.read_all() if r["event"] == pl.OUTCOME][-1]
    assert out["verdict"] == "miss"
    assert out["learner_err"] == 17.0, "distance to the nearest edge, not a flat 1"


def test_unscored_before_the_horizon_is_left_alone(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0], start=T0)
    _seal([99.0, 103.0], T0 + timedelta(days=14))
    res = sp.score_matured(now=T0)
    assert res["waiting"] == 1
    assert not [r for r in pl.read_all() if r["event"] == pl.OUTCOME]


def test_unresolvable_when_the_source_vanished(isolated):
    _seal([99.0, 103.0], T0, axis="GONE_REVIEW", sid="dead")
    res = sp.score_matured(now=T0 + timedelta(days=1))
    assert res["unresolvable"] == 1
    out = [r for r in pl.read_all() if r["event"] == pl.OUTCOME][-1]
    assert out["verdict"] == "unresolvable"
    assert "no longer present" in out["reason"], "the reason must be NAMED, not blank"
    assert out["learner_err"] is None


def test_within_grace_it_waits_then_closes_as_unresolvable(isolated):
    """A source that stopped updating must not leave a prediction open forever — an
    open prediction is one that never got to be wrong."""
    _write_series(isolated, "A_REVIEW", "s1", [100.0], start=T0 - timedelta(days=5))
    _seal([99.0, 103.0], T0)

    res = sp.score_matured(now=T0 + timedelta(days=3))
    assert res["waiting"] == 1 and res["unresolvable"] == 0

    res = sp.score_matured(now=T0 + timedelta(days=sp.GRACE_DAYS + 1))
    assert res["unresolvable"] == 1
    assert "stopped updating" in [r for r in pl.read_all()
                                  if r["event"] == pl.OUTCOME][-1]["reason"]


def test_scoring_is_idempotent(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0], start=T0)
    _seal([99.0, 103.0], T0)
    sp.score_matured(now=T0 + timedelta(days=1))
    again = sp.score_matured(now=T0 + timedelta(days=1))
    assert again["hit"] == 0, "an already-scored prediction must not be scored twice"
    assert len([r for r in pl.read_all() if r["event"] == pl.OUTCOME]) == 1


def test_first_observation_at_or_after_horizon_is_used(isolated):
    """Not the latest value — the one that answers the question as it was asked."""
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 500.0], start=T0)
    _seal([99.0, 103.0], T0)
    sp.score_matured(now=T0 + timedelta(days=5))
    assert [r for r in pl.read_all() if r["event"] == pl.OUTCOME][-1]["actual"] == 100.0


# ── the guarantee ────────────────────────────────────────────────────────────

def test_original_prediction_is_never_mutated(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [120.0], start=T0)
    sealed = _seal([99.0, 103.0], T0)

    raw_before = (pl.LEDGER_PATH).read_text(encoding="utf-8")
    sp.score_matured(now=T0 + timedelta(days=1))
    raw_after = (pl.LEDGER_PATH).read_text(encoding="utf-8")

    assert raw_after.startswith(raw_before), "scoring must APPEND, never rewrite"

    still = [r for r in pl.read_all() if r.get("hash") == sealed["hash"]]
    assert len(still) == 1
    assert still[0] == sealed, "the sealed record must be byte-identical after scoring"
    assert still[0]["band"] == [99.0, 103.0]
    assert pl.verify()["valid"], "the hash chain must still verify after scoring"


def test_outcome_references_the_prediction_by_hash(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0], start=T0)
    sealed = _seal([99.0, 103.0], T0)
    sp.score_matured(now=T0 + timedelta(days=1))
    assert [r for r in pl.read_all()
            if r["event"] == pl.OUTCOME][-1]["ref_hash"] == sealed["hash"]


# ── proposing ────────────────────────────────────────────────────────────────

def test_propose_seals_when_a_series_qualifies(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0 + (i % 3) for i in range(20)])
    res = sp.propose(now=T0)
    assert res["action"] == "sealed"
    assert res["band"][0] < res["centre"] < res["band"][1]
    rec = [r for r in pl.read_all() if r["event"] == pl.PREDICTION][-1]
    assert rec["target_kind"] == sp.KIND
    assert rec["horizon_utc"][:4] == "2026", "a calendar horizon, not a symbolic one"
    assert datetime.fromisoformat(rec["horizon_utc"]) == T0 + timedelta(days=sp.HORIZON_DAYS)


def test_propose_records_pending_instead_of_fabricating(isolated):
    """The honest branch: too little data, so a named shortfall — not a vacuous band."""
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0, 102.0])
    res = sp.propose(now=T0)
    assert res["action"] == "pending"
    assert res["need_more"] == sp.MIN_POINTS - 3
    rec = [r for r in pl.read_all() if r["event"] == pl.PENDING][-1]
    assert rec["have_points"] == 3
    assert "auto-checked next cycle" in rec["reason"]
    assert not [r for r in pl.read_all() if r["event"] == pl.PREDICTION], \
        "no prediction may be sealed on data that cannot support one"


def test_pending_names_the_series_that_can_actually_qualify(isolated):
    """A long constant series is not 'nearly there' — it can never produce a band. The
    shortfall must be reported against the series that varies, however short it is."""
    _write_series(isolated, "FLAT_REVIEW", "flat", [428.72] * 10)
    _write_series(isolated, "MOVING_REVIEW", "moves", [100.0, 101.0, 102.5])
    res = sp.propose(now=T0)
    assert res["action"] == "pending"
    assert res["target_id"] == "MOVING_REVIEW::moves", \
        "the constant series must not be reported as the one closest to qualifying"


def test_pending_is_not_reappended_every_cycle(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0, 102.0])
    sp.propose(now=T0)
    res = sp.propose(now=T0 + timedelta(days=1))
    assert res["action"] == "pending_unchanged"
    assert len([r for r in pl.read_all() if r["event"] == pl.PENDING]) == 1


def test_pending_reappends_when_the_series_grows(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0, 102.0])
    sp.propose(now=T0)
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0, 102.0, 103.0])
    res = sp.propose(now=T0 + timedelta(days=1))
    assert res["action"] == "pending"
    assert len([r for r in pl.read_all() if r["event"] == pl.PENDING]) == 2


def test_propose_does_not_stack_open_predictions(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0 + (i % 3) for i in range(20)])
    sp.propose(now=T0)
    res = sp.propose(now=T0 + timedelta(days=1))
    assert res["action"] == "skipped"
    assert len([r for r in pl.read_all() if r["event"] == pl.PREDICTION]) == 1


def test_pending_never_counts_as_a_sealed_prediction(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0])
    sp.propose(now=T0)
    assert pl.scoreboard()["sealed_predictions"] == 0


def test_dry_writes_nothing(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0 + (i % 3) for i in range(20)])
    sp.run(dry=True)
    assert not pl.LEDGER_PATH.exists() or pl.read_all() == []


# ── cycle wiring ─────────────────────────────────────────────────────────────

def test_cycle_wiring_is_fail_open():
    """One line in the cycle log, and an exception here must never break the cycle."""
    src = (REPO / "core" / "cortex_orchestrator.py").read_text(encoding="utf-8")
    assert "score_prophecies" in src
    i = src.index("score_prophecies")
    window = src[max(0, i - 700): i + 700]
    assert "try:" in window and "except Exception" in window, "wiring must be fail-open"


def test_summary_line_is_one_line(isolated):
    _write_series(isolated, "A_REVIEW", "s1", [100.0, 101.0])
    line = sp.summary_line(sp.run(dry=True))
    assert "\n" not in line and len(line) < 200
