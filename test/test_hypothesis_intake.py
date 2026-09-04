# -*- coding: utf-8 -*-
"""
core/hypothesis_intake.py — predictions that can fail, every night (I, 3 Sep 2026).

C5 + C11. Until this landed the system had produced two hypotheses, both in June, and
graded neither. Only MEASURED axes are eligible (the K1 gate, read from the same
place); every hypothesis carries lo/hi, because a point can always be called close
and an interval either contains the outcome or it does not; and generation and
resolution are separate steps that stay out of each other's files.

Everything here is tmp_path and monkeypatch.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import core.consolidation as CO        # noqa: E402
import core.hypothesis_intake as HI    # noqa: E402


def _cycle(root: Path, n: int, when: date, signals: list):
    d = root / f"cycle_{n:06d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "signals.json").write_text(json.dumps({
        "cycle_id": f"c{n}",
        "timestamp": datetime(when.year, when.month, when.day,
                              tzinfo=timezone.utc).isoformat(),
        "count": len(signals), "signals": signals}), encoding="utf-8")
    return d


def _drifting(root: Path, days: int, start: float, step: float, noise=(0.0,)):
    """A metric that creeps by `step` a day. Whether that is invisible night to
    night depends on `noise`: the drift must be small against the night-to-night
    step, or the daily cycle would already have caught it."""
    today = date(2026, 9, 3)
    for i in range(days):
        when = today - timedelta(days=days - 1 - i)
        val = start + step * i + noise[i % len(noise)]
        _cycle(root, i + 1, when, [{"metric": "m", "value": round(val, 6),
                                    "domain": "ENERGY_REVIEW", "source": "metrics"}])
    return today


# ── I: intake ─────────────────────────────────────────────────────────────────

def _stub_measured(monkeypatch, axes: dict, resolves=True):
    """Measured axes, a history, AND the ground-truth resolver.

    The resolver matters since H2 (4 Sep 2026): intake now asks the grader's own
    lookup whether a key resolves before writing a hypothesis, so an unstubbed test
    would be asking the live snapshot on this machine.
    """
    monkeypatch.setattr(HI, "measured_axes", lambda: axes)
    monkeypatch.setattr(HI, "axis_history", lambda *a, **k: [10.0, 10.5, 11.0, 11.5])
    monkeypatch.setattr(
        HI, "_resolves",
        (lambda axis, metric: (axes.get(axis, 12.0), None)) if resolves
        else (lambda axis, metric: (None, f"no such key {axis}/{metric}")))


def test_every_hypothesis_carries_an_interval_not_just_a_point(tmp_path, monkeypatch):
    """C11. A point prediction can always be called close; an interval either
    contains the outcome or it does not."""
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0})
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "none.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["registered"] == 1
    h = json.loads(pending.read_text(encoding="utf-8"))[0]
    assert h["lo"] < h["predicted_value"] < h["hi"]
    assert h["interval_width"] > 0
    assert h["prediction_date"] == "2026-09-10"
    assert rec["every_hypothesis_has_an_interval"] is True


def test_only_measured_axes_may_be_predicted(monkeypatch, tmp_path):
    """An ASSERTED axis is an opinion; a prediction about it grades an opinion
    against itself. Same gate K1 uses, read from the same place."""
    _stub_measured(monkeypatch, {})
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["measured_axes"] == 0 and rec["registered"] == 0
    assert "nothing may be predicted" in HI.summary_line(rec)


def test_nothing_is_pre_registered_twice(tmp_path, monkeypatch):
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0})
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")
    kw = dict(pending=pending, queue=tmp_path / "n.json",
              latest=tmp_path / "l.json", today=date(2026, 9, 3))

    HI.run(write=True, **kw)
    second = HI.run(write=True, **kw)

    assert second["registered"] == 0
    assert second["skipped"]["already_registered"] == 1
    assert len(json.loads(pending.read_text(encoding="utf-8"))) == 1


def test_consolidation_claims_are_taken_up_verbatim(tmp_path, monkeypatch):
    """WIRE_FIRST: the queue consolidation writes must actually be read, and the
    claim that gets graded must be the claim that was made."""
    _stub_measured(monkeypatch, {})
    q = tmp_path / "q.json"
    q.write_text(json.dumps({"made_on": "2026-09-03", "hypotheses": [{
        "axis": "ENERGY_REVIEW", "metric": "m", "direction": "up",
        "horizon_days": 30, "predicted": 5.5, "lo": 5.0, "hi": 6.0,
        "made_on": "2026-09-03", "due_on": "2026-10-03", "r2": 0.7}]}),
        encoding="utf-8")
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=q,
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["from_consolidation"] == 1
    h = [x for x in json.loads(pending.read_text(encoding="utf-8"))
         if x["method"] == "anchored"][0]
    assert h["predicted_value"] == 5.5 and h["lo"] == 5.0 and h["hi"] == 6.0
    assert h["prediction_date"] == "2026-10-03"


def test_a_hypothesis_on_a_key_that_does_not_resolve_is_refused_at_write_time(
        tmp_path, monkeypatch):
    """H2. The seven-week freeze was a metric-name mismatch: registered as
    "co2_ppm", graded as "co2_ppm_mauna_loa". Third instance of this defect class.
    A prediction must never be born ungradeable and discover it 49 days later."""
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0}, resolves=False)
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["registered"] == 0
    assert rec["skipped"]["key_unresolvable"] == 1
    assert json.loads(pending.read_text(encoding="utf-8")) == []
    assert rec["refused_count"] == 1
    assert "does not resolve" in rec["refused"][0]["refused"]
    assert "key_unresolvable" in HI.summary_line(rec)


def test_a_prediction_equal_to_its_anchor_is_refused_as_a_restatement(
        tmp_path, monkeypatch):
    """H2. A prediction identical to persistence cannot be wrong, so it cannot
    teach. Measured 4 Sep 2026: 13 of 14 live pendings had |predicted - anchor|
    EXACTLY 0, on axes that had not moved in 30 cycles.

    The history here is FLAT, so every method restates and there is no honest
    prediction to fall back to."""
    monkeypatch.setattr(HI, "measured_axes", lambda: {"ENERGY_REVIEW": 12.0})
    monkeypatch.setattr(HI, "axis_history", lambda *a, **k: [12.0] * 6)
    monkeypatch.setattr(HI, "_resolves", lambda axis, metric: (12.0, None))
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["registered"] == 0
    assert rec["skipped"]["restatement"] == 1
    assert json.loads(pending.read_text(encoding="utf-8")) == []
    assert "not a prediction" in rec["refused"][0]["refused"]
    assert "restatement" in HI.summary_line(rec)


def test_a_genuinely_different_prediction_still_passes(tmp_path, monkeypatch):
    """The guard must refuse restatements, not predictions. A moving series still
    produces a falsifiable claim."""
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0})
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["registered"] == 1
    assert rec["skipped"]["restatement"] == 0
    h = json.loads(pending.read_text(encoding="utf-8"))[0]
    assert h["predicted_value"] != h["value_at_registration"]


def test_every_interval_declares_its_nominal_level(tmp_path, monkeypatch):
    """H3. Without this field neither an interval score nor coverage is computable
    later — the same defect class as axis_observations having no observation date.
    And it is written as DECLARED, not calibrated, so nobody reads it as measured."""
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0})
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
           latest=tmp_path / "l.json", today=date(2026, 9, 3))

    h = json.loads(pending.read_text(encoding="utf-8"))[0]
    assert h["interval_nominal"] == HI.INTERVAL_NOMINAL == 0.80
    assert "not calibrated" in h["interval_basis"]
    assert "UNKNOWN" in h["interval_basis"]


def test_an_interval_without_a_declared_level_never_reaches_disk(
        tmp_path, monkeypatch):
    """The guard is structural, not a promise at each construction site."""
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0})
    monkeypatch.setattr(HI, "INTERVAL_NOMINAL", None)
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["registered"] == 0
    assert rec["skipped"]["interval_without_level"] == 1
    assert json.loads(pending.read_text(encoding="utf-8")) == []



def test_the_generator_never_writes_the_resolvers_file():
    """The guard that keeps 20.05 and 20.06 honest: a step that both invents and
    grades could settle a claim it had just made."""
    import ast

    def written_paths(rel):
        """Names the module calls .write_text() on — the actual writes, not the
        docstring. Both files DISCUSS the other's file at length; a substring
        check would flag the explanation instead of a violation."""
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        out = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write_text"):
                tgt = node.func.value
                while isinstance(tgt, ast.Call) and tgt.args:
                    tgt = tgt.args[0]
                if isinstance(tgt, ast.Name):
                    out.add(tgt.id)
        return out

    gen = written_paths("core/hypothesis_intake.py")
    res = written_paths("core/hypothesis_resolution.py")
    assert "RESOLVED" not in " ".join(gen).upper(), gen
    assert not ({"PENDING", "pending_p", "RESOLVED"} & res), res


def test_generation_and_resolution_are_separate_steps():
    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))
    names = [s["name"] for s in phases["phases"]["G_LEARN"]["steps"]]
    assert "resolve_hypotheses" in names and "hypothesis_intake" in names
    # generation AFTER resolution: tonight's claims must not be settled tonight
    assert names.index("hypothesis_intake") > names.index("resolve_hypotheses")
    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert 'beat("hypothesis_intake", "20.06")' in runner


def test_the_intake_uses_belief_state_method_weights(tmp_path, monkeypatch):
    """THE READER for J. If belief_state says a method has been missing on an axis,
    tonight's prediction must stop coming from it — otherwise belief revision is
    another unread producer."""
    _stub_measured(monkeypatch, {"ENERGY_REVIEW": 12.0})
    monkeypatch.setattr(HI, "_load_beliefs", lambda: {
        "axes": {"ENERGY_REVIEW": {"method_weights": {
            "persistence": 0.1, "trend": 0.9, "mean_reversion": 0.1}}}})
    pending = tmp_path / "pending.json"
    pending.write_text("[]", encoding="utf-8")

    rec = HI.run(write=True, pending=pending, queue=tmp_path / "n.json",
                 latest=tmp_path / "l.json", today=date(2026, 9, 3))

    assert rec["methods_used"] == ["trend"], rec["methods_used"]


def test_the_evaluator_can_now_read_a_review_axis():
    """The gap that would have made every one of these unresolvable: trends.json has
    never carried an axis under its REVIEW name, so a hypothesis about ENERGY_REVIEW
    could be registered, come due, and be skipped forever."""
    import evaluator as EV
    v = EV._get_current_value("ENERGY_REVIEW")
    assert isinstance(v, float), "the scorer snapshot fallback is not reachable"
