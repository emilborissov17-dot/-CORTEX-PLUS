"""F1 guard: the legacy self-grading loop is retired.

Two findings converged here (2026-07-21): the old feedback path graded an
LLM-urgency prediction against the SAME LLM-urgency signal that produced it — a
self-confirming loop via memory.prediction_tracker (make_prediction /
verify_and_learn). That legacy grader is now quarantined non-authoritative and
replaced by the sealed prophecy 'axis_next' path.

This suite is the permanent guard that the retired grader can never re-enter a
cycle path:
  1. feedback_loop.make_predictions is a no-op — it writes nothing, grades
     nothing, returns None.
  2. Running the feedback_loop cycle never invokes the legacy grader.
  3. Running the orchestrator cycle write-block never invokes the legacy grader,
     and DOES drive the sealed prophecy path in its place.

The legacy grader is wired as a tripwire: if a cycle path ever calls it again,
these tests fail loud.
"""
import sys
import types

import pytest

import agents.core.feedback_loop as fl
import core.cortex_orchestrator as co
import memory.prediction_tracker as pt


@pytest.fixture
def grader_tripwire(monkeypatch):
    """Any call to the legacy grader detonates. Returns the (empty) hit list."""
    hits = []

    def _boom(name):
        def _f(*a, **k):
            hits.append(name)
            raise AssertionError(f"legacy grader {name} was invoked in a cycle path")
        return _f

    monkeypatch.setattr(pt, "make_prediction", _boom("make_prediction"))
    monkeypatch.setattr(pt, "verify_and_learn", _boom("verify_and_learn"))
    return hits


# ── 1. make_predictions is a no-op: writes nothing, grades nothing ───────────

def test_make_predictions_writes_nothing(monkeypatch, grader_tripwire):
    writes = []
    monkeypatch.setattr(fl, "_save_json", lambda *a, **k: writes.append(a))

    result = fl.make_predictions({"WATER_REVIEW": 50.0}, {"WATER_REVIEW": 1.0})

    assert result is None            # no prediction produced
    assert writes == []              # nothing persisted
    assert grader_tripwire == []     # legacy grader never touched


# ── 2. the feedback_loop cycle never invokes the legacy grader ───────────────

def test_feedback_cycle_never_grades(monkeypatch, grader_tripwire):
    # light-weight cycle inputs; block all disk writes and the heavy memory dep
    monkeypatch.setattr(fl, "read_current_scores", lambda: {"WATER_REVIEW": 50.0})
    monkeypatch.setattr(fl, "read_baseline", lambda: {"WATER_REVIEW": 49.0})
    monkeypatch.setattr(fl, "read_last_actions", lambda: [])
    monkeypatch.setattr(fl, "_save_json", lambda *a, **k: None)
    stub = types.ModuleType("memory.semantic_memory")
    stub.remember = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "memory.semantic_memory", stub)

    fl.run()                         # real cycle, including make_predictions()

    assert grader_tripwire == []     # never graded


# ── 3. the orchestrator cycle drives the sealed path, not the legacy grader ──

def test_orchestrator_cycle_uses_sealed_path_not_grader(monkeypatch, grader_tripwire):
    # stub the upstream (LLM/IO) stages so run() reaches the write-block cheaply
    monkeypatch.setattr(co, "load_latest_intelligence", lambda: {})
    monkeypatch.setattr(co, "assess_attention", lambda state: {})
    monkeypatch.setattr(co, "generate_strategic_plan", lambda att, state: {"plan_24h": []})
    monkeypatch.setattr(co, "save_orchestration_result", lambda *a, **k: {"ok": True})

    # spy on the sealed prophecy path the block invokes instead of the grader
    import experiments.prophecy.prophecy as prophecy
    sealed = []
    monkeypatch.setattr(prophecy, "cmd_score_axes", lambda *a, **k: sealed.append("score"))
    monkeypatch.setattr(prophecy, "cmd_predict_axes", lambda *a, **k: sealed.append("predict"))

    co.run()

    assert grader_tripwire == []                     # legacy grader never invoked
    assert sealed == ["score", "predict"]            # sealed path ran in its place


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
