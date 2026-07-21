"""K1a keystone: axis predictions must be SEALED (tamper-evident), and the
legacy unsealed path must never pass as authoritative.

Two findings converged here (2026-07-21): (1) all 25 memory/predictions.json
records were unsealed — the tamper-evidence that is K1a's whole moat did not
exist for axis predictions; (2) their was_correct was scored against web-intel
urgency, not an authoritative outcome. The fix seals axis predictions under the
existing prophecy apparatus (target_kind 'axis_next') and quarantines the legacy
records as non-authoritative. This suite is the permanent guard.

All ledger writes go to a tmp file — the real prophecy_ledger.jsonl is untouched.
"""
import json
import pytest

import experiments.prophecy.prophecy as prophecy
pl = prophecy.pl  # the prophecy_ledger module prophecy actually writes through
import memory.prediction_tracker as pt


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "LEDGER_PATH", tmp_path / "prophecy_ledger.jsonl")
    return tmp_path


# ── sealing: the forward path is tamper-evident ──────────────────────────────

def test_seal_axis_prediction_is_chained(tmp_ledger):
    r1 = prophecy.seal_axis_prediction("WATER_REVIEW", 48.0, 50.0, 50.0, basis="t")
    r2 = prophecy.seal_axis_prediction("FOOD_REVIEW", 44.0, 45.0, 45.0, basis="t")
    assert r1["target_kind"] == "axis_next"
    assert pl.is_sealed(r1) and pl.is_sealed(r2)
    assert r2["prev_hash"] == r1["hash"]           # chained
    assert pl.verify()["valid"] is True


def test_tamper_breaks_the_chain(tmp_ledger):
    prophecy.seal_axis_prediction("WATER_REVIEW", 48.0, 50.0, 50.0, basis="t")
    prophecy.seal_axis_prediction("WATER_REVIEW", 40.0, 50.0, 50.0, basis="t")
    # rewrite a sealed learner value after the fact
    p = pl.LEDGER_PATH
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0]); rec["learner"] = 0.0
    lines[0] = json.dumps(rec, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert pl.verify()["valid"] is False           # edit is caught


# ── the invariant: unsealed ⟹ non-authoritative ──────────────────────────────

def test_legacy_record_is_not_sealed():
    """A bare predictions.json record must fail the seal check."""
    legacy = {"axis": "WATER_REVIEW", "predicted_urgency": "LOW", "verified": True}
    assert pl.is_sealed(legacy) is False


def test_legacy_make_prediction_is_flagged_nonauthoritative(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PRED_FILE", tmp_path / "predictions.json")
    pt.make_prediction("WATER_REVIEW", "ситуацията ще продължи", "LOW")
    rec = json.loads(pt.PRED_FILE.read_text(encoding="utf-8"))[-1]
    assert rec["authoritative"] is False
    assert rec["superseded_by"] == "prophecy:axis_next"
    assert pl.is_sealed(rec) is False              # legacy can never masquerade as sealed


def test_mark_legacy_nonauthoritative_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "PRED_FILE", tmp_path / "predictions.json")
    pt.PRED_FILE.write_text(json.dumps([
        {"axis": "A", "verified": True},
        {"axis": "B", "authoritative": False},
    ], ensure_ascii=False), encoding="utf-8")
    assert pt.mark_legacy_nonauthoritative() == 1   # only the untagged one
    assert pt.mark_legacy_nonauthoritative() == 0   # idempotent
    recs = json.loads(pt.PRED_FILE.read_text(encoding="utf-8"))
    assert all(r["authoritative"] is False for r in recs)


# ── sanity: one axis end-to-end (seal → mature → score) ──────────────────────

def test_single_axis_seal_then_score(tmp_ledger, monkeypatch):
    monkeypatch.setattr(prophecy, "_live_axes", lambda: {"WATER_REVIEW"})
    series = [50.0, 45.0, 48.0]
    monkeypatch.setattr(prophecy, "_axis_history_scores", lambda ax: list(series))

    sealed = prophecy.cmd_predict_axes(one_axis="WATER_REVIEW")
    assert len(sealed) == 1 and pl.is_sealed(sealed[0])
    # learner = last-step trend: 48 + (48-45) = 51 ; baseline = persistence 48
    assert sealed[0]["learner"] == 51.0 and sealed[0]["baseline"] == 48.0

    prophecy.cmd_score_axes()                       # not matured yet (len unchanged)
    assert pl.scoreboard()["scored_outcomes"] == 0

    series.append(46.0)                             # a new cycle score lands
    prophecy.cmd_score_axes()
    sb = pl.scoreboard()
    assert sb["scored_outcomes"] == 1
    assert sb["chain_valid"] is True
    # baseline 48 (|48-46|=2) beats learner 51 (|51-46|=5) here — recorded head-to-head
    assert sb["learner_mae"] == 5.0 and sb["baseline_mae"] == 2.0


def test_only_live_axes_are_sealed(tmp_ledger, monkeypatch):
    """We never seal a prediction we cannot honestly score: DEAD/DEGRADED axes
    (no authoritative outcome) are skipped."""
    monkeypatch.setattr(prophecy, "_live_axes", lambda: {"WATER_REVIEW"})
    monkeypatch.setattr(prophecy, "_axis_history_scores", lambda ax: [50.0, 48.0])
    prophecy.cmd_predict_axes(one_axis="EDUCATION_CULTURE_REVIEW")  # DEAD scorer
    assert pl.scoreboard()["sealed_predictions"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
