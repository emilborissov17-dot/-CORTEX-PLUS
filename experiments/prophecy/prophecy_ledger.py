#!/usr/bin/env python3
"""
experiments/prophecy/prophecy_ledger.py — tamper-evident self-prediction ledger.

WHY THIS EXISTS (K1a of the AGI roadmap)
----------------------------------------
The bet is: persistence + self-observation + self-correction -> intelligence.
The ONLY honest way to test it is to make the system PREDICT the consequences of
its own actions and state, SEAL the prediction before the outcome is known, and
then check — against a matched baseline that does NOT self-observe — whether the
self-observing "learner" gets less wrong over time. The proof is not "the error
curve falls" (a trend-line does that); the proof is "the learner beats the
control on predictions that were sealed before reality answered".

WHY A HASH CHAIN (same pattern as memory/existence_ledger.py)
-------------------------------------------------------------
    hash = sha256(prev_hash + canonical_json(record_without_hash))
Any edit to any past record breaks every hash after it. This is what makes the
learning claim un-gameable: you cannot quietly rewrite a prediction after you
have seen the outcome. At cycle commit the head hash should be anchored into the
Merkle tree (results[]), exactly as the existence ledger is — so the whole
prediction history is sealed into a root that a later edit cannot match.

WHAT IS PREDICTED — the system's OWN actions/state, never smooth externalities
------------------------------------------------------------------------------
target_kind ∈ {
  "patch_effect"  — applying patch P will move axis A's score by Δ by date D
  "self_failure"  — the next cycle will die at step S (or: will finish)
  "axis_next"     — axis X will be LEVEL L next cycle
}
Getting these right requires a model of the SYSTEM, not of the weather. Each
record carries BOTH a learner prediction and a control (baseline) prediction, so
scoring is a head-to-head, not an absolute.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE = Path(__file__).resolve().parent
LEDGER_PATH = BASE / "prophecy_ledger.jsonl"   # gitignored — data, not code
GENESIS_HASH = "0" * 64

PREDICTION = "PREDICTION_SEALED"
OUTCOME = "OUTCOME_SCORED"
# A prediction the system WANTED to make and honestly could not yet — too few
# observations to state a band that could fail. Recorded in the chain rather than
# skipped silently, because "we have no prediction and here is exactly why" is
# evidence and an empty ledger is not. Never counted as a sealed prediction.
PENDING = "PREDICTION_PENDING"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(prev_hash: str, record: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(record)).encode("utf-8")).hexdigest()


def read_all(skip_torn: bool = True) -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    out = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if skip_torn:
                continue
            raise
    return out


def head_hash() -> str:
    events = read_all()
    return events[-1]["hash"] if events else GENESIS_HASH


def _append(event_type: str, **fields: Any) -> dict:
    prev = head_hash()
    seq = (read_all()[-1]["seq"] if LEDGER_PATH.exists() and read_all() else 0) + 1
    rec = {"seq": seq, "ts": _utc_now(), "event": event_type, **fields, "prev_hash": prev}
    rec["hash"] = _hash(prev, rec)
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rec


# ── Public API ──────────────────────────────────────────────────────────────

def seal_prediction(target_kind: str, target_id: str, horizon_utc: str,
                    learner_value: Any, baseline_value: Any,
                    basis: Optional[str] = None, **extra: Any) -> dict:
    """Seal ONE prediction before its outcome is known.

    learner_value : what the self-observing system predicts.
    baseline_value: the control — a naive/non-self-observing predictor over the
                    same information (e.g. 'no change', last-level-persists).
    Returns the sealed record (its 'hash' is the reference used to score it).
    """
    return _append(
        PREDICTION,
        target_kind=target_kind,
        target_id=target_id,
        horizon_utc=horizon_utc,
        learner=learner_value,
        baseline=baseline_value,
        basis=basis,
        **extra,
    )


def note_pending(target_id: str, reason: str, **extra: Any) -> dict:
    """Record that a prediction cannot yet be honestly stated, and why.

    The alternative is to invent a prediction wide enough that it cannot fail, which
    would score as a 'hit' forever and make the K1a curve a lie. A named absence is
    worth more than a vacuous presence."""
    return _append(PENDING, target_id=target_id, reason=reason, **extra)


def _abs_err(pred: Any, actual: Any) -> Optional[float]:
    """Numeric absolute error, or None for non-numeric (categorical scored 0/1 by caller)."""
    try:
        return abs(float(pred) - float(actual))
    except (TypeError, ValueError):
        return None


def score_prediction(ref_hash: str, actual: Any, **extra: Any) -> dict:
    """Score a previously sealed prediction against the observed outcome.

    Records BOTH errors (learner vs baseline) so a later analysis is a head-to-head.
    For categorical targets (levels, died-at-step) pass numeric 1/0 correctness in
    'learner'/'baseline' at seal time, or use learner_correct/baseline_correct here.
    """
    sealed = next((r for r in read_all()
                   if r.get("hash") == ref_hash and r.get("event") == PREDICTION), None)
    if sealed is None:
        raise ValueError(f"no sealed PREDICTION with hash {ref_hash[:12]}...")

    l_err = extra.pop("learner_err", None)
    b_err = extra.pop("baseline_err", None)
    if l_err is None:
        l_err = _abs_err(sealed.get("learner"), actual)
    if b_err is None:
        b_err = _abs_err(sealed.get("baseline"), actual)

    return _append(
        OUTCOME,
        ref_hash=ref_hash,
        target_kind=sealed.get("target_kind"),
        target_id=sealed.get("target_id"),
        actual=actual,
        learner_err=l_err,
        baseline_err=b_err,
        learner_wins=(l_err is not None and b_err is not None and l_err < b_err),
        **extra,
    )


def is_sealed(record: dict) -> bool:
    """A record is sealed iff it is a link in the tamper-evident chain — it
    carries a non-empty hash AND prev_hash. A bare dict (e.g. a legacy
    predictions.json entry) is NOT sealed and must never pass as K1 evidence.
    """
    return bool(record.get("hash")) and bool(record.get("prev_hash"))


def verify() -> dict:
    """Re-derive the whole chain. {'valid': bool, 'broken_at': seq|None, 'head_hash': ...}."""
    events = read_all()
    if not events:
        return {"valid": True, "events": 0, "broken_at": None, "head_hash": GENESIS_HASH}
    prev = GENESIS_HASH
    for e in events:
        if e.get("prev_hash") != prev or e.get("hash") != _hash(prev, e):
            return {"valid": False, "broken_at": e.get("seq"), "head_hash": None}
        prev = e["hash"]
    return {"valid": True, "events": len(events), "broken_at": None, "head_hash": prev}


def scoreboard() -> dict:
    """THE K1a verdict: does the self-observing learner beat the control on
    sealed self-predictions? Reported as a head-to-head, not an absolute curve."""
    outcomes = [e for e in read_all() if e.get("event") == OUTCOME]
    scored = [o for o in outcomes if o.get("learner_wins") is not None
              and o.get("learner_err") is not None and o.get("baseline_err") is not None]
    n = len(scored)
    wins = sum(1 for o in scored if o["learner_wins"])
    l_mae = round(sum(o["learner_err"] for o in scored) / n, 4) if n else None
    b_mae = round(sum(o["baseline_err"] for o in scored) / n, 4) if n else None
    return {
        "chain_valid": verify()["valid"],
        "sealed_predictions": sum(1 for e in read_all() if e.get("event") == PREDICTION),
        "scored_outcomes": n,
        "learner_win_rate": round(wins / n, 3) if n else None,
        "learner_mae": l_mae,
        "baseline_mae": b_mae,
        # K1a passes only if the learner beats the control — an absolute error
        # curve proves nothing on its own.
        "learner_beats_control": (l_mae is not None and b_mae is not None and l_mae < b_mae
                                  and (wins / n) > 0.5) if n else None,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(scoreboard() if "--score" not in sys.argv else verify(),
                     ensure_ascii=False, indent=2))
