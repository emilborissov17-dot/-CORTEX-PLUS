# -*- coding: utf-8 -*-
"""
test/test_prophecy_one_per_night.py — one night, one self_failure forecast.

WHY THIS EXISTS, and it is not hypothetical. On 10 Sep 2026 two scheduler runs of
CORTEX_Prophecy 64 seconds apart sealed TWO identical self_failure forecasts
(5b23984 and 95d22eb) for the same anchor, 2026-09-10T01:49:35. The anchor is the
last terminal cycle event, so every --predict between two cycles is a forecast of
the SAME night. cmd_score() dedupes on ref_hash, not on target, so both copies
would have scored against that one night and one observation would have counted
twice in the Brier mean — the board moving with no new evidence.

TWO BIASES, DOUBLE DEFENSE (claude/NORM_TWO_BIASES_DOUBLE_DEFENSE_7SEP.md):

  BIAS 1, helpfulness: seal SOMETHING every morning so the run "has output".
  WHAT A REFUSAL LOOKS LIKE: Refused is RAISED, exit 2, nothing appended, ledger
  byte-identical. A morning that seals nothing because the anchor has not moved is
  a SUCCESS. The forbidden fallbacks are a second seal, a seal with a "duplicate"
  note, and widening the target_id so the duplicate looks like a new target.

  BIAS 2, least resistance: delete the offending line from the ledger. The ledger
  is an append-only hash chain; deleting 95d22eb breaks every hash after it. The
  duplicate must stay visible AND never score.

Failure paths first, happy path last. Each guard has a mutation test that fails
if the guard is removed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROPHECY = REPO / "experiments" / "prophecy"
sys.path.insert(0, str(PROPHECY))
sys.path.insert(0, str(REPO))

import prophecy_ledger as pl  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROPHECY / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pr = _load("prophecy")


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A private ledger AND a private existence ledger — never the real ones."""
    path = tmp_path / "prophecy_ledger.jsonl"
    monkeypatch.setattr(pl, "LEDGER_PATH", path)
    return path


def _existence(tmp_path, monkeypatch, nights, last="CYCLE_FINISHED"):
    """nights finished cycles, the last one of the given terminal kind.

    The dates are in 2027 ON PURPOSE. prophecy.cmd_score() matures a prediction
    when an outcome's ts is later than the SEAL'S OWN wall-clock ts, so a fixture
    dated in the past matures nothing and every scoring assertion below would pass
    vacuously on 0 observations. (self_forecast.py matures off the ANCHOR instead,
    deliberately, so a back-dated ledger scores identically; the two modules differ
    here and that difference is not this test's subject.)"""
    import json
    p = tmp_path / "existence_ledger.jsonl"
    lines = []
    for i in range(1, nights + 1):
        ev = last if i == nights else "CYCLE_FINISHED"
        lines.append(json.dumps({"event": ev, "ts": f"2027-09-{i:02d}T02:00:00+00:00",
                                 "cycle_id": f"c{i}"}))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(pr, "LEDGER_JSONL", p)
    return p


# ── failure paths first ──────────────────────────────────────────────────────

def test_predict_refuses_a_second_forecast_for_the_same_anchor(ledger, tmp_path, monkeypatch):
    _existence(tmp_path, monkeypatch, 6)
    pr.cmd_predict()
    before = ledger.read_bytes()
    with pytest.raises(pr.Refused):
        pr.cmd_predict()
    assert ledger.read_bytes() == before, \
        "the refused second seal still wrote — a refusal must leave the ledger untouched"


def test_a_new_anchor_is_a_new_night_and_is_allowed(ledger, tmp_path, monkeypatch):
    """NEGATIVE CONTROL. The guard must block a duplicate, not block forecasting.
    Without this, `raise Refused` unconditionally would pass the test above."""
    _existence(tmp_path, monkeypatch, 6)
    pr.cmd_predict()
    _existence(tmp_path, monkeypatch, 7)          # a cycle ended; the anchor moved
    rec = pr.cmd_predict()
    assert rec, "a genuinely new night was refused"
    seals = [r for r in pl.read_all()
             if r.get("event") == pl.PREDICTION and r.get("target_kind") == "self_failure"]
    assert len({r["target_id"] for r in seals}) == 2


def test_mutation_the_one_per_night_guard_is_load_bearing(ledger, tmp_path, monkeypatch):
    """Blind the guard's only input and the duplicate goes through — so removing
    the guard turns this red instead of silently double-counting."""
    _existence(tmp_path, monkeypatch, 6)
    pr.cmd_predict()
    real = pl.read_all
    monkeypatch.setattr(pl, "read_all", lambda: [])
    pr.cmd_predict()
    monkeypatch.setattr(pl, "read_all", real)
    seals = [r for r in pl.read_all()
             if r.get("event") == pl.PREDICTION and r.get("target_kind") == "self_failure"]
    assert len(seals) == 2 and len({r["target_id"] for r in seals}) == 1, \
        "with the guard blinded the duplicate seals — proving the guard refused it"


# ── containment: the duplicate already in the chain ──────────────────────────

def _plant_duplicate(tmp_path, monkeypatch):
    """Two seals on one anchor, the way 10 Sep actually produced them."""
    _existence(tmp_path, monkeypatch, 6)
    pr.cmd_predict()
    real = pl.read_all
    monkeypatch.setattr(pl, "read_all", lambda: [])
    pr.cmd_predict()
    monkeypatch.setattr(pl, "read_all", real)


def test_a_duplicate_in_the_chain_is_never_scored_twice(ledger, tmp_path, monkeypatch):
    _plant_duplicate(tmp_path, monkeypatch)
    _existence(tmp_path, monkeypatch, 7)          # the predicted night ends
    pr.cmd_score()
    recs = pl.read_all()
    outs = [r for r in recs if r.get("event") == pl.OUTCOME]
    assert len(outs) == 1, f"one night produced {len(outs)} observations"
    # and the duplicate is still IN the ledger, named — not deleted
    seals = [r for r in recs
             if r.get("event") == pl.PREDICTION and r.get("target_kind") == "self_failure"]
    assert len(seals) == 2, "the duplicate was removed from an append-only chain"
    pend = [r for r in recs if r.get("event") == pl.PENDING]
    assert len(pend) == 1 and pend[0].get("superseded_hash"), \
        "the superseded duplicate was swallowed silently instead of named"


def test_the_superseded_note_is_written_once_not_every_morning(ledger, tmp_path, monkeypatch):
    """A superseded duplicate is never scored, so it stays open forever. Noting it
    on every --score would append one PENDING per morning without end."""
    _plant_duplicate(tmp_path, monkeypatch)
    _existence(tmp_path, monkeypatch, 7)
    for _ in range(4):                             # four mornings
        pr.cmd_score()
    pend = [r for r in pl.read_all() if r.get("event") == pl.PENDING]
    assert len(pend) == 1, f"{len(pend)} PENDING records for one duplicate — unbounded growth"


def test_mutation_the_score_dedup_is_load_bearing(ledger, tmp_path, monkeypatch):
    """Remove the per-target dedup and the duplicate scores too, giving two
    observations for one night. This is the damage the containment prevents."""
    _plant_duplicate(tmp_path, monkeypatch)
    _existence(tmp_path, monkeypatch, 7)
    # The path is passed EXPLICITLY. _cycle_outcomes' default binds the real
    # existence ledger at definition time, and with that default this test read
    # live state and matured nothing (0 observations) instead of failing honestly.
    outcomes = pr._cycle_outcomes(pr.LEDGER_JSONL)
    records = pl.read_all()
    scored = {r.get("ref_hash") for r in records if r.get("event") == pl.OUTCOME}
    opened = [r for r in records if r.get("event") == pl.PREDICTION
              and r.get("target_kind") == "self_failure" and r.get("hash") not in scored]
    for p in opened:                               # the un-deduped loop, verbatim
        later = [o for o in outcomes if o["ts"] and o["ts"] > p["ts"]]
        if later:
            pl.score_prediction(p["hash"], later[0]["outcome"])
    outs = [r for r in pl.read_all() if r.get("event") == pl.OUTCOME]
    assert len(outs) == 2, \
        "without the dedup both copies score — which is why cmd_score dedupes by target"


# ── the happy path, last ─────────────────────────────────────────────────────

def test_one_forecast_per_night_scores_once_per_night(ledger, tmp_path, monkeypatch):
    for nights in (6, 7, 8):
        _existence(tmp_path, monkeypatch, nights)
        pr.cmd_score()
        pr.cmd_predict()
    recs = pl.read_all()
    seals = [r for r in recs
             if r.get("event") == pl.PREDICTION and r.get("target_kind") == "self_failure"]
    outs = [r for r in recs if r.get("event") == pl.OUTCOME]
    assert len(seals) == len({r["target_id"] for r in seals}) == 3
    assert len(outs) == 2, "three forecasts, two matured nights, two observations"
    assert not [r for r in recs if r.get("event") == pl.PENDING]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
