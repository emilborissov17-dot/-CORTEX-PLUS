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
         actual=10.0, lo=9.0, hi=11.0, when="2026-09-03T01:00:00+00:00",
         skill=0.5, baseline=None, **kw):
    """A resolved record as the evaluator writes it since H1 (4 Sep 2026).

    skill is the authoritative field: 1 - model_error / persistence_error. The
    module no longer decides anything from surprise, so a row must carry a skill
    or be refused by name.
    """
    model_error = abs(predicted - actual)
    baseline_error = (abs(baseline - actual) if baseline is not None
                      else (model_error / (1.0 - skill) if skill not in (None, 1.0)
                            else None))
    return {"id": hid, "axis": axis, "method": method,
            "predicted_value": predicted, "actual_value": actual,
            "lo": lo, "hi": hi, "evaluated_at": when,
            "skill": skill, "model_error": model_error,
            "baseline_error": baseline_error, **kw}


def _paths(tmp_path):
    """State, ledger AND archive all inside tmp_path.

    The archive matters: is_unscoreable() reads the sealed cycles to decide whether
    an axis can carry signal at all, and ENERGY_REVIEW is genuinely UNSCOREABLE in
    the live repo (one distinct value across 30 cycles). A test that did not pass
    its own archive would silently be asserting against this machine's data.
    """
    arch = tmp_path / "archive"
    arch.mkdir(exist_ok=True)
    return {"state_path": tmp_path / "belief_state.json",
            "ledger_path": tmp_path / "revision_ledger.jsonl",
            "archive": arch}


# ── the two directions ────────────────────────────────────────────────────────

def test_a_miss_shifts_weight_away_from_the_method_that_missed(tmp_path):
    """The whole point of the module."""
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0, lo=9.0, hi=11.0,
                                  skill=-1.0)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["revisions"] == 1 and rec["misses"] == 1
    rev = rec["revision_records"][0]
    assert rev["verdict"] == "lost_to_persistence"
    assert rev["weight_after"] < rev["weight_before"], "a miss cost nothing"
    assert rev["shift"] < 0
    w = rec["state"]["axes"]["ENERGY_REVIEW"]["method_weights"]
    assert w["trend"] < w["persistence"], "the method that missed still leads"


def test_a_hit_shifts_weight_toward_the_method_that_hit(tmp_path):
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=10.05, lo=9.0, hi=11.0)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["hits"] == 1
    rev = rec["revision_records"][0]
    assert rev["verdict"] == "beat_persistence"
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

def test_the_same_error_costs_more_when_persistence_was_harder_to_beat(tmp_path):
    """AMENDED 4 Sep 2026 (H1). The old property was about interval width: the same
    raw error had to cost more at +/-1 than at +/-50. That guarded against buying
    immunity with a vague interval, and it is now recorded but not decisive.

    The property that replaces it is the one that matters: the same raw error is a
    different event depending on how well DOING NOTHING would have done. Missing by
    5 when persistence would have missed by 5 is no skill at all; missing by 5 when
    persistence would have missed by 50 is a win. Only the ratio distinguishes them,
    and it is the ratio that moves the weight."""
    hard = tmp_path / "hard"; hard.mkdir()
    easy = tmp_path / "easy"; easy.mkdir()
    # same error of 5.0 in both; persistence would have missed by 5 vs by 50
    hard_rec = BR.run(write=False, resolved_path=_resolved(
        hard, [_row(predicted=10.0, actual=15.0, skill=0.0, baseline=10.0)]),
        state_path=hard / "s.json", ledger_path=hard / "l.jsonl", archive=hard)
    easy_rec = BR.run(write=False, resolved_path=_resolved(
        easy, [_row(predicted=10.0, actual=15.0, skill=0.9, baseline=-35.0)]),
        state_path=easy / "s.json", ledger_path=easy / "l.jsonl", archive=easy)

    h, ez = hard_rec["revision_records"][0], easy_rec["revision_records"][0]
    assert h["error"] == ez["error"] == 5.0, "the raw error must be identical"
    assert h["skill"] < ez["skill"]
    assert h["shift"] < ez["shift"],         "beating a hard baseline earned no more than tying an easy one"


def test_one_strange_night_cannot_flip_an_axis(tmp_path):
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=1e6, lo=9.9, hi=10.1)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))
    assert abs(rec["revision_records"][0]["shift"]) <= BR.MAX_SHIFT


def test_weights_stay_a_distribution_and_no_method_dies(tmp_path):
    rows = [_row(hid=f"h{i}", predicted=10.0, actual=99.0, lo=9.9, hi=10.1,
                 skill=-1.0,
                 when=f"2026-09-{3 + i:02d}T01:00:00+00:00") for i in range(6)]
    rec = BR.run(write=True, resolved_path=_resolved(tmp_path, rows),
                 **_paths(tmp_path))
    w = rec["state"]["axes"]["ENERGY_REVIEW"]["method_weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert all(v >= BR.MIN_WEIGHT for v in w.values()), \
        "a method was driven to zero and can never recover"


def test_without_an_interval_the_weight_still_moves_and_surprise_is_recorded_null(tmp_path):
    """AMENDED 4 Sep 2026 (H1). Under C11 the update rode on surprise, so a missing
    interval meant nothing could be learned. It no longer does: SKILL decides, and
    skill needs a baseline, not a width. A row without an interval is therefore
    still learnable - and surprise is written as null rather than invented, so a
    later reader can tell "no width was claimed" from "the width was wide"."""
    r = _resolved(tmp_path, [_row(lo=None, hi=None, skill=-1.0)])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["revisions"] == 1
    assert rec["skipped"]["no_interval"] == 0
    assert rec["revision_records"][0]["surprise"] is None


def test_a_resolution_without_a_skill_is_refused_by_name(tmp_path):
    """H1: skill is the only thing that may move a weight. A record the grader could
    not score is refused with its reason, not folded in as a small update."""
    r = _resolved(tmp_path, [_row(skill=None,
                                  unresolvable_reason="persistence was exact")])
    rec = BR.run(write=True, resolved_path=r, **_paths(tmp_path))

    assert rec["revisions"] == 0
    assert rec["skipped"]["no_skill"] == 1
    assert rec["refusals"][0]["why"] == "persistence was exact"


def test_an_unscoreable_axis_is_refused_by_name(tmp_path):
    """H3: a series with no spread cannot separate a forecast from a restatement.
    Nine of twelve live axes were in exactly that state on 4 Sep 2026."""
    arch = tmp_path / "archive"
    arch.mkdir(exist_ok=True)
    for i in range(4):
        d = arch / f"cycle_{i:06d}"
        d.mkdir()
        (d / "signals.json").write_text(json.dumps({"signals": [
            {"metric": "renewable_energy_pct", "domain": "ENERGY_REVIEW",
             "value": 19.7}]}), encoding="utf-8")

    rec = BR.run(write=True, resolved_path=_resolved(tmp_path, [_row(skill=-1.0)]),
                 state_path=tmp_path / "s.json",
                 ledger_path=tmp_path / "l.jsonl", archive=arch)

    assert rec["revisions"] == 0
    assert rec["skipped"]["unscoreable_axis"] == 1
    assert "UNSCOREABLE" in rec["refusals"][0]["why"]


def test_the_two_june_hypotheses_are_skipped_rather_than_mislearned(tmp_path):
    """The live resolved.json rows predate intervals and methods entirely. They must
    not be folded in at some invented width. RESTORED 4 Sep 2026 after an edit
    dropped it."""
    rec = BR.run(write=False, state_path=tmp_path / "s.json",
                 ledger_path=tmp_path / "l.jsonl")
    assert rec["revisions"] == 0
    assert rec["resolved_seen"] >= 2



# ── the record ────────────────────────────────────────────────────────────────

def test_every_revision_is_appended_with_before_after_and_why(tmp_path):
    """A state file alone cannot answer 'when did this axis stop trusting trend'."""
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0, skill=-1.0)])
    p = _paths(tmp_path)
    BR.run(write=True, resolved_path=r, **p)

    lines = [json.loads(x) for x in
             p["ledger_path"].read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    e = lines[0]
    for k in ("hypothesis_id", "axis", "method", "error", "skill", "surprise",
              "model_error", "baseline_error", "weight_before", "weight_after", "why"):
        assert k in e, f"the ledger cannot explain itself without {k}"
    assert "skill" in e["why"] and "moved" in e["why"]
    assert "persistence" in e["why"],         "the why does not name the baseline the skill was measured against"


def test_a_resolution_is_not_learned_from_twice(tmp_path):
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0, skill=-1.0)])
    p = _paths(tmp_path)
    first = BR.run(write=True, resolved_path=r, **p)
    second = BR.run(write=True, resolved_path=r, **p)

    assert first["revisions"] == 1 and second["revisions"] == 0
    lines = [x for x in p["ledger_path"].read_text(encoding="utf-8").splitlines()
             if x.strip()]
    assert len(lines) == 1


def test_source_trust_is_a_delta_for_source_lifecycle_not_applied_here(tmp_path):
    """Two writers to one judgement is how a system ends up disagreeing with itself."""
    r = _resolved(tmp_path, [_row(predicted=10.0, actual=30.0, skill=-1.0,
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
