# -*- coding: utf-8 -*-
"""
core/belief_revision.py — C7, the spine (3 Sep 2026).

Step 20.06 pre-registers a prediction with an interval; 20.05 grades what came due.
Until this landed, nothing happened next: the system could be wrong every night for a
year and predict the same way on the last night as on the first. Being wrong has to
cost something, or measurement is theatre.

The properties defended here:
  a miss shifts weight AWAY from the method that missed;
  a hit shifts it TOWARD;
  zero resolutions changes nothing and says "0 revisions";
  the update is proportional to SURPRISE (|error| / interval width), not raw error,
    so a method cannot buy immunity by predicting a huge interval;
  every revision is appended to the ledger with before/after/why;
  and the weights are actually READ by the generator that runs the next night.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import core.belief_revision as BR      # noqa: E402
import core.hypothesis_intake as HI    # noqa: E402


def _resolved(tmp_path: Path, rows: list) -> Path:
    p = tmp_path / "resolved.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def _row(hid="h1", axis="ENERGY_REVIEW", method="trend", predicted=10.0,
         actual=10.0, lo=9.0, hi=11.0, when="2026-09-03T01:00:00+00:00", **kw):
    return {"id": hid, "axis": axis, "method": method,
            "predicted_value": predicted, "actual_value": actual,
            "lo": lo, "hi": hi, "evaluated_at": when, **kw}


def _paths(tmp_path):
    return {"state_path": tmp_path / "belief_state.json",
            "ledger_path": tmp_path / "revision_ledger.jsonl"}


# ── the two directions ────────────────────────────────────────────────────────

def test_a_miss_shifts_weight_away_from_the_method_that_missed(tmp_path):
    """The whole point of the module."""
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0, lo=9.0, hi=11.0)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["revisions"] == 1 and rec["misses"] == 1
    rev = rec["revision_records"][0]
    assert rev["verdict"] == "miss"
    assert rev["weight_after"] < rev["weight_before"], "a miss cost nothing"
    assert rev["shift"] < 0
    w = rec["state"]["axes"]["ENERGY_REVIEW"]["method_weights"]
    assert w["trend"] < w["persistence"], "the method that missed still leads"


def test_a_hit_shifts_weight_toward_the_method_that_hit(tmp_path):
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=10.05, lo=9.0, hi=11.0)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["hits"] == 1
    rev = rec["revision_records"][0]
    assert rev["verdict"] == "hit"
    assert rev["weight_after"] > rev["weight_before"]
    w = rec["state"]["axes"]["ENERGY_REVIEW"]["method_weights"]
    assert w["trend"] > w["persistence"]


def test_zero_resolutions_changes_nothing_and_reports_zero(tmp_path):
    r = _resolved(tmp_path, [])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["revisions"] == 0
    assert rec["state"].get("axes") == {}
    assert "0 revisions" in BR.summary_line(rec)
    assert not (tmp_path / "revision_ledger.jsonl").exists(), \
        "an empty night wrote a ledger line"


# ── C11: surprise, not error ──────────────────────────────────────────────────

def test_the_same_error_costs_more_when_the_interval_was_confident(tmp_path):
    """A method must not buy immunity by predicting a huge interval. The SAME raw
    error of 5 is a different event at +/-1 than at +/-50, and only the ratio
    distinguishes them."""
    tight = BR.run(write=False, resolved_path=_resolved(
        tmp_path / "a", []) if False else _resolved(
        tmp_path, [_row(predicted=10.0, actual=15.0, lo=9.0, hi=11.0)]),
        **_paths(tmp_path))
    loose_dir = tmp_path / "loose"
    loose_dir.mkdir()
    loose = BR.run(write=False, resolved_path=_resolved(
        loose_dir, [_row(predicted=10.0, actual=15.0, lo=-40.0, hi=60.0)]),
        state_path=loose_dir / "s.json", ledger_path=loose_dir / "l.jsonl")

    t, ll = tight["revision_records"][0], loose["revision_records"][0]
    assert t["error"] == ll["error"] == 5.0, "the raw error must be identical"
    assert t["surprise"] > ll["surprise"]
    assert t["shift"] < ll["shift"], "the confident miss cost no more than the vague one"


def test_a_hypothesis_without_an_interval_is_skipped_not_guessed_at(tmp_path):
    """C11 has no meaning without a width. Inventing one would make the update a
    number nobody chose."""
    r = _resolved(tmp_path, [_row(lo=None, hi=None)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["revisions"] == 0
    assert rec["skipped"]["no_interval"] == 1


def test_the_two_june_hypotheses_are_skipped_rather_than_mislearned(tmp_path):
    """The live resolved.json rows predate intervals and methods entirely. They must
    not be folded in at some invented width."""
    rec = BR.run(write=False, state_path=tmp_path / "s.json",
                 ledger_path=tmp_path / "l.jsonl")
    assert rec["revisions"] == 0
    assert rec["resolved_seen"] >= 2


# ── bounds ────────────────────────────────────────────────────────────────────

def test_one_strange_night_cannot_flip_an_axis(tmp_path):
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=1e6, lo=9.9, hi=10.1)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))
    assert abs(rec["revision_records"][0]["shift"]) <= BR.MAX_SHIFT


def test_weights_stay_a_distribution_and_no_method_dies(tmp_path):
    rows = [_row(hid=f"h{i}", predicted=10.0, actual=99.0, lo=9.9, hi=10.1,
                 when=f"2026-09-{3 + i:02d}T01:00:00+00:00") for i in range(6)]
    rec = BR.run(write=True, resolved_path=_resolved(tmp_path, rows),
                 **_paths(tmp_path))
    w = rec["state"]["axes"]["ENERGY_REVIEW"]["method_weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert all(v >= BR.MIN_WEIGHT for v in w.values()), \
        "a method was driven to zero and can never recover"


# ── the record ────────────────────────────────────────────────────────────────

def test_every_revision_is_appended_with_before_after_and_why(tmp_path):
    """A state file alone cannot answer 'when did this axis stop trusting trend'."""
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0)])
    p = _paths(tmp_path)
    BR.run(write=True, resolved_path=r, **p)

    lines = [json.loads(x) for x in
             p["ledger_path"].read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    e = lines[0]
    for k in ("hypothesis_id", "axis", "method", "error", "surprise",
              "weight_before", "weight_after", "why"):
        assert k in e, f"the ledger cannot explain itself without {k}"
    assert "surprise" in e["why"] and "moved" in e["why"]


def test_a_resolution_is_not_learned_from_twice(tmp_path):
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0)])
    p = _paths(tmp_path)
    first = BR.run(write=True, resolved_path=r, **p)
    second = BR.run(write=True, resolved_path=r, **p)

    assert first["revisions"] == 1 and second["revisions"] == 0
    lines = [x for x in p["ledger_path"].read_text(encoding="utf-8").splitlines()
             if x.strip()]
    assert len(lines) == 1


def test_source_trust_is_a_delta_for_source_lifecycle_not_applied_here(tmp_path):
    """Two writers to one judgement is how a system ends up disagreeing with itself."""
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0,
                                  measured_by={"source_id": "WORLD_BANK"})])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))
    d = rec["state"]["source_trust_delta"]["WORLD_BANK"]
    assert d["n"] == 1 and d["delta"] < 0
    src = (REPO / "core" / "belief_revision.py").read_text(encoding="utf-8")
    assert "source_lifecycle" not in src.split('"""')[2], \
        "belief_revision writes source trust itself instead of handing over a delta"


# ── the reader (WIRE_FIRST) ───────────────────────────────────────────────────

def test_the_generator_actually_uses_these_weights(tmp_path, monkeypatch):
    """Without this, C7 is another producer nobody reads. A revision must change
    what gets predicted the next night."""
    state = {"axes": {"ENERGY_REVIEW": {"method_weights": {
        "persistence": 0.05, "trend": 0.80, "mean_reversion": 0.10,
        "anchored": 0.05}}}}
    monkeypatch.setattr(HI, "_load_beliefs", lambda: state)
    assert HI._best_method("ENERGY_REVIEW", state) == "trend"
    # and an axis the state says nothing about falls back, it does not crash
    assert HI._best_method("UNSEEN_AXIS", state) == "persistence"


def test_revision_runs_before_generation_so_the_loop_closes_in_one_cycle():
    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))
    names = [s["name"] for s in phases["phases"]["G_LEARN"]["steps"]]
    assert names.index("resolve_hypotheses") < names.index("belief_revision")
    assert names.index("belief_revision") < names.index("hypothesis_intake")

    import core.cycle_map as cm
    assert cm.produces("belief_revision") == ["memory/belief_state.json"]
    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert 'beat("belief_revision", "20.07")' in runner
