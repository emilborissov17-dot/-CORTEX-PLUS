# -*- coding: utf-8 -*-
"""
core/hypothesis_resolution.py — the cycle's caller for evaluator.py (3 Sep 2026).

The claim under test is the one that matters for the calibration bench: a hypothesis
whose prediction_date has passed MOVES from pending.json to resolved.json and arrives
there carrying an accuracy score. Everything else here defends the two properties that
make the step safe to run unattended — it never generates, and it never reports "0 due"
when something was due.

No network. The store is a tmp_path and evaluator's module-level path constants are
monkeypatched, so the live cortex_memory/hypotheses/ is never touched.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import evaluator as EV                      # noqa: E402
import core.hypothesis_resolution as HR     # noqa: E402


def _hyp(hid, axis, predicted, when, **extra):
    return {"id": hid, "axis": axis, "predicted_value": predicted,
            "prediction_date": when.isoformat(), "status": "pending", **extra}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A complete, isolated hypothesis store wired into evaluator's constants."""
    pending = tmp_path / "pending.json"
    resolved = tmp_path / "resolved.json"
    trends = tmp_path / "trends.json"
    pending.write_text("[]", encoding="utf-8")
    resolved.write_text("[]", encoding="utf-8")
    trends.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(EV, "PENDING_PATH", str(pending))
    monkeypatch.setattr(EV, "RESOLVED_PATH", str(resolved))
    monkeypatch.setattr(EV, "TRENDS_PATH", str(trends))
    monkeypatch.setattr(HR, "LATEST", tmp_path / "hypothesis_resolution_latest.json")
    return {"pending": pending, "resolved": resolved, "trends": trends,
            "latest": tmp_path / "hypothesis_resolution_latest.json"}


# ── THE POINT OF THE STEP ─────────────────────────────────────────────────────

def test_a_due_hypothesis_moves_to_resolved_with_a_skill_score(store):
    """pending -> resolved, with a number attached. AMENDED 4 Sep 2026 (H1): the
    number is SKILL against persistence, not accuracy against the level."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("h1", "co2_ppm", 430.0, yesterday, value_at_registration=420.0)]),
        encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [420.0, 425.0, 430.0]}),
                               encoding="utf-8")

    rec = HR.run(write=True)

    assert rec["due"] == 1
    assert rec["resolved_now"] == 1
    assert rec["verdict"] == "RESOLVED"

    assert json.loads(store["pending"].read_text(encoding="utf-8")) == []
    landed = json.loads(store["resolved"].read_text(encoding="utf-8"))
    assert len(landed) == 1
    assert landed[0]["id"] == "h1"
    assert landed[0]["status"] == "resolved"
    assert landed[0]["actual_value"] == 430.0
    # exact hit, and persistence would have been 10 out -> perfect skill
    assert landed[0]["skill"] == pytest.approx(1.0)
    assert landed[0]["beat_persistence"] is True
    assert landed[0]["model_error"] == pytest.approx(0.0)
    assert landed[0]["baseline_error"] == pytest.approx(10.0)
    assert "evaluated_at" in landed[0]


def test_skill_is_measured_against_persistence_not_against_the_level(store):
    """THE H1 DEFECT, as a test. A wrong prediction must score below a right one —
    and 'wrong' has to mean 'worse than doing nothing', not 'small next to a big
    number'."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("close", "co2_ppm", 99.0, yesterday, value_at_registration=90.0),
         _hyp("wild", "kp_index", 10.0, yesterday, value_at_registration=2.0)]),
        encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [100.0], "kp_index": [1.0]}),
                               encoding="utf-8")

    HR.run(write=True)
    by_id = {r["id"]: r for r in
             json.loads(store["resolved"].read_text(encoding="utf-8"))}

    # close: out by 1 where persistence was out by 10  -> skill 0.9, a win
    assert by_id["close"]["skill"] == pytest.approx(0.9)
    assert by_id["close"]["beat_persistence"] is True
    # wild: out by 9 where persistence was out by 1    -> skill -8, a loss
    assert by_id["wild"]["skill"] == pytest.approx(-8.0)
    assert by_id["wild"]["beat_persistence"] is False
    assert by_id["close"]["skill"] > by_id["wild"]["skill"]


def test_the_live_co2_miss_does_not_come_out_as_a_success(store):
    """THE CASE THAT EXPOSED IT. On 4 Sep the 20 July co2_ppm prediction was graded
    98.7% ТОЧНА on a miss of 5.5 ppm — more than two years of CO2 growth — because
    the error was measured against the level (~427) instead of the variation.

    Persistence would have missed by exactly the same 5.5, because the prediction
    WAS the last observed value. Skill is therefore 0.0: the model did not beat
    doing nothing, and must not read as a success."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("co2", "co2_ppm", 432.44, yesterday,
              value_at_registration=432.44)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [426.94]}), encoding="utf-8")

    HR.run(write=True)
    r = json.loads(store["resolved"].read_text(encoding="utf-8"))[0]

    assert r["skill"] == pytest.approx(0.0)
    assert r["beat_persistence"] is False
    assert r["model_error"] == pytest.approx(5.5)
    assert r["baseline_error"] == pytest.approx(5.5)
    # the old number is still recorded, and is no longer what decides
    assert r["accuracy"] > 0.98, "the level-relative number should still be ~98.7%"


def test_a_frozen_series_is_unresolvable_not_a_hundred_percent(store):
    """The 13 predictions due 11 Sep are persistence on series that have not moved
    in 30 cycles: predicted == baseline == actual. Under the old metric every one
    of them scores 100%. There is no skill in restating a constant, and a
    baseline_error of 0 is a division by zero, not a triumph."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("frozen", "co2_ppm", 426.94, yesterday,
              value_at_registration=426.94)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [426.94]}), encoding="utf-8")

    rec = HR.run(write=True)
    r = json.loads(store["resolved"].read_text(encoding="utf-8"))[0]

    assert rec["resolved_now"] == 0 and rec["unresolvable_now"] == 1
    assert r["status"] == "unresolvable"
    assert r["skill"] is None
    assert r["baseline_error"] == 0.0
    assert "did not move" in r["unresolvable_reason"]


def test_a_hypothesis_with_no_baseline_is_unresolvable(store):
    """No persistence anchor recorded at creation means there is nothing to be
    better than. That is a registration failure, not a bad forecast."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("nobase", "co2_ppm", 430.0, yesterday)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [420.0]}), encoding="utf-8")

    HR.run(write=True)
    r = json.loads(store["resolved"].read_text(encoding="utf-8"))[0]

    assert r["status"] == "unresolvable"
    assert r["skill"] is None
    assert "value_at_registration missing" in r["unresolvable_reason"]


# ── "0 due" IS A RESULT, NOT SILENCE ──────────────────────────────────────────

def test_zero_due_reports_zero_due_and_still_writes_the_artifact(store):
    """A step that succeeds silently when it did nothing cannot be told from a step
    that is not wired. The artifact must appear on a quiet night too."""
    rec = HR.run(write=True)

    assert rec["due"] == 0
    assert rec["verdict"] == "NOTHING_DUE"
    assert store["latest"].is_file(), "no artifact on a quiet night — the phase " \
                                      "report cannot catch this step going inert"
    assert "0 due" in HR.summary_line(rec)


def test_a_future_hypothesis_is_not_due_and_is_left_alone(store):
    tomorrow = date.today() + timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("later", "co2_ppm", 430.0, tomorrow)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [430.0]}), encoding="utf-8")

    rec = HR.run(write=True)

    assert rec["due"] == 0 and rec["resolved_now"] == 0
    assert len(json.loads(store["pending"].read_text(encoding="utf-8"))) == 1


def test_due_but_unresolvable_is_not_reported_as_nothing_due(store):
    """THE LIVE CASE, 3 Sep 2026: kp_index and co2_ppm are empty lists in the real
    trends.json, so both hypotheses have been due since July with nothing to grade
    them against. Calling that "0 due" would hide a failure that is upstream of the
    evaluator entirely."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("stuck", "kp_index", 2.67, yesterday)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"kp_index": []}), encoding="utf-8")

    rec = HR.run(write=True)

    assert rec["due"] == 1
    assert rec["resolved_now"] == 0
    assert rec["skipped_no_data"] == 1
    assert rec["unresolvable_now"] == 1
    assert rec["verdict"] == "DUE_BUT_UNRESOLVABLE"
    assert rec["stuck"][0]["axis"] == "kp_index"
    line = HR.summary_line(rec)
    assert "NONE resolvable" in line and "kp_index" in line
    assert "0 due" not in line
    # AMENDED 4 Sep 2026 (Q0). It no longer stays pending. Staying pending is what
    # let this exact hypothesis rot for seven weeks while the step reported clean.
    # It leaves pending carrying a named reason instead — not discarded, graded as
    # ungradeable.
    assert json.loads(store["pending"].read_text(encoding="utf-8")) == []
    moved = json.loads(store["resolved"].read_text(encoding="utf-8"))
    assert len(moved) == 1
    assert moved[0]["status"] == "unresolvable"
    assert moved[0]["actual_value"] is None
    assert moved[0]["accuracy"] is None
    assert moved[0]["days_overdue"] == 1
    assert "kp_index" in moved[0]["unresolvable_reason"]


def test_the_named_reason_says_which_lookups_came_up_empty(store):
    """A reason is only a reason if it is actionable. "no current value" was true
    for seven weeks and told nobody which of the three lookups to go and fix."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("stuck", "kp_index", 2.67, yesterday)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"kp_index": []}), encoding="utf-8")

    HR.run(write=True)

    why = json.loads(store["resolved"].read_text(encoding="utf-8"))[0][
        "unresolvable_reason"]
    # all three lookups named, each with its own outcome
    assert "trends.json['kp_index'] is an EMPTY series" in why
    assert "axis_observations has no axis 'kp_index'" in why
    assert "metric_details has no metric 'kp_index'" in why


def test_a_past_due_hypothesis_never_survives_the_step_in_pending(store):
    """THE CONTRACT, stated as one property: after this step runs, nothing in
    pending.json may carry a prediction_date in the past. Both exits are legal —
    graded, or marked unresolvable — but staying is not."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps([
        _hyp("gradeable", "co2_ppm", 430.0, yesterday,
             value_at_registration=420.0),                 # has a series
        _hyp("ungradeable", "kp_index", 2.67, yesterday),    # has nothing
    ]), encoding="utf-8")
    store["trends"].write_text(json.dumps(
        {"co2_ppm": [426.94], "kp_index": []}), encoding="utf-8")

    rec = HR.run(write=True)

    left = json.loads(store["pending"].read_text(encoding="utf-8"))
    assert [h for h in left
            if date.fromisoformat(h["prediction_date"]) < date.today()] == []
    assert rec["resolved_now"] == 1 and rec["unresolvable_now"] == 1
    by_id = {r["id"]: r for r in
             json.loads(store["resolved"].read_text(encoding="utf-8"))}
    assert by_id["gradeable"]["status"] == "resolved"
    assert isinstance(by_id["gradeable"]["accuracy"], float)
    assert by_id["ungradeable"]["status"] == "unresolvable"


def test_an_unresolvable_record_moves_no_belief_weight(store, tmp_path):
    """C7 must not learn from a prediction nobody could grade. A vacuous record
    reaching belief_revision has to produce zero weight movement and a named
    refusal, not a micro-update from a missing number."""
    import core.belief_revision as BR

    resolved = tmp_path / "resolved_for_br.json"
    resolved.write_text(json.dumps([{
        "id": "u1", "axis": "kp_index", "method": "persistence",
        "predicted_value": 2.67, "actual_value": None, "accuracy": None,
        "lo": 2.0, "hi": 3.0, "status": "unresolvable",
        "unresolvable_reason": "no ground truth",
        "evaluated_at": "2026-09-04T00:00:00+00:00",
    }]), encoding="utf-8")

    rec = BR.run(write=False, state_path=tmp_path / "state.json",
                 resolved_path=resolved)

    assert rec["revisions"] == 0
    assert rec["skipped"]["unresolvable"] == 1
    assert rec["state"]["axes"] == {}


# ── RESOLUTION ONLY, NEVER GENERATION ─────────────────────────────────────────

def test_the_step_never_generates_hypotheses(store):
    """The guard is structural, not a promise in a docstring: pending must not grow."""
    yesterday = date.today() - timedelta(days=1)
    store["pending"].write_text(json.dumps(
        [_hyp("h1", "co2_ppm", 430.0, yesterday)]), encoding="utf-8")
    store["trends"].write_text(json.dumps({"co2_ppm": [430.0]}), encoding="utf-8")

    rec = HR.run(write=True)

    assert rec["resolution_only_ok"] is True
    assert rec["pending_after"] <= rec["pending_before"]


def test_a_grown_pending_store_is_reported_as_illegal_growth(store, monkeypatch):
    """If anything ever makes this step generate, it must say so rather than pass."""
    store["pending"].write_text("[]", encoding="utf-8")

    def _sneaky_generator():
        Path(EV.PENDING_PATH).write_text(json.dumps(
            [_hyp("invented", "co2_ppm", 1.0, date.today())]), encoding="utf-8")
        return []
    monkeypatch.setattr(EV, "check_due_hypotheses", _sneaky_generator)

    rec = HR.run(write=True)

    assert rec["resolution_only_ok"] is False
    assert rec["verdict"] == "ILLEGAL_GROWTH"
    assert "ILLEGAL_GROWTH" in HR.summary_line(rec)


def test_the_generator_module_is_not_imported_by_the_step(store):
    """hypothesis_generator must not be reachable from this step at all."""
    src = (REPO / "core" / "hypothesis_resolution.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "import hypothesis_generator" not in code
    assert "from hypothesis_generator" not in code


# ── FAIL-OPEN ─────────────────────────────────────────────────────────────────

def test_an_evaluator_that_raises_does_not_take_the_cycle_with_it(store, monkeypatch):
    def _boom():
        raise RuntimeError("trends.json is a directory")
    monkeypatch.setattr(EV, "check_due_hypotheses", _boom)

    rec = HR.run(write=True)          # must not raise

    assert rec["verdict"] == "ERROR"
    assert "RuntimeError" in rec["error"]
    assert "FAILED" in HR.summary_line(rec)


# ── THE THREE MAPS (the lesson of ITEM 7.1, paid for twice) ───────────────────

def test_the_step_is_declared_in_all_three_maps_and_the_inputs_contract():
    """A step declared in fast_cycle_runner but not in the maps is recorded as an
    unmapped_checkpoint and cannot light a square in the cockpit."""
    import core.cycle_map as cm

    assert cm.produces("resolve_hypotheses") == \
        ["memory/hypothesis_resolution_latest.json"]

    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))
    g = phases["phases"]["G_LEARN"]
    names = [s["name"] for s in g["steps"]]
    assert "resolve_hypotheses" in names
    assert "memory/hypothesis_resolution_latest.json" in g["produces"]

    inputs = json.loads((REPO / "config" / "step_inputs.json")
                        .read_text(encoding="utf-8"))
    assert "resolve_hypotheses" in inputs["steps"]

    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert 'beat("resolve_hypotheses", "20.05")' in runner


def test_it_runs_before_measurement_honesty():
    """Ordering is the requirement: K1 must read today's resolutions, not tomorrow's."""
    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))
    names = [s["name"] for s in phases["phases"]["G_LEARN"]["steps"]]
    assert names.index("resolve_hypotheses") < names.index("measurement_honesty")

    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert runner.index('beat("resolve_hypotheses"') < \
        runner.index('beat("measurement_honesty"')
