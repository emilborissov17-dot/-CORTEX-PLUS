#!/usr/bin/env python3
"""
memory/prediction_tracker.py
CORTEX++ се учи от резултатите си.
Самопредложено от системата на 2026-03-14.

QUARANTINED — NON-AUTHORITATIVE (2026-07-21).
---------------------------------------------
This path is legacy. Its records are NOT sealed (no hash chain) and their
was_correct is scored against web-intelligence `urgency` — an unstable LLM
signal, not an authoritative outcome. They are therefore NOT valid K1/K1a
learning evidence and must never be treated as such. Every record written here
is stamped `authoritative: False, superseded_by: "prophecy:axis_next"`.

The authoritative, tamper-evident axis-prediction path is the sealed prophecy
apparatus: experiments/prophecy/prophecy.py --predict-axes (target_kind
'axis_next'), chained in experiments/prophecy/prophecy_ledger.py.
"""
import json, pathlib
from datetime import datetime, timezone, timedelta

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
PRED_FILE = BASE_DIR / "memory" / "predictions.json"

# Every legacy record carries this so no consumer can mistake it for sealed
# K1 evidence. The authoritative path is prophecy target_kind 'axis_next'.
QUARANTINE = {"authoritative": False, "superseded_by": "prophecy:axis_next"}

def _now(): return datetime.now(timezone.utc).isoformat()
def _load():
    try: return json.loads(PRED_FILE.read_text(encoding="utf-8"))
    except Exception: return []

def make_prediction(axis, prediction, urgency):
    preds = _load()
    preds.append({
        "axis": axis, "prediction": prediction,
        "predicted_urgency": urgency, "made_at": _now(),
        "verify_after": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()[:10],
        "verified": False, "was_correct": None, "lesson": "",
        **QUARANTINE,
    })
    PRED_FILE.write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")

def mark_legacy_nonauthoritative():
    """Idempotently stamp existing predictions.json records as non-authoritative.
    Data-only migration (writes memory/predictions.json); safe to run repeatedly.
    Returns the number of records newly tagged."""
    preds = _load()
    tagged = 0
    for p in preds:
        if not isinstance(p, dict):
            continue
        if p.get("authoritative") is not False:
            p.update(QUARANTINE)
            tagged += 1
    if tagged:
        PRED_FILE.write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")
    return tagged

def verify_and_learn(current_axes):
    preds = _load()
    today = _now()[:10]
    lessons = []
    correct = 0
    for p in preds:
        if p["verified"] or p["verify_after"] > today: continue
        axis = p["axis"]
        if axis not in current_axes: continue
        actual = current_axes[axis].get("urgency", "LOW")
        was_correct = actual == p["predicted_urgency"]
        p["verified"] = True
        p["was_correct"] = was_correct
        p["lesson"] = f"Предсказах {p['predicted_urgency']}, реалността: {actual}. {'ПРАВИЛНО' if was_correct else 'ГРЕШНО'}"
        lessons.append(p["lesson"])
        if was_correct: correct += 1
    PRED_FILE.write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")
    total = len(lessons)
    if total > 0:
        print(f"[FEEDBACK] Верифицирани: {total} | Правилни: {correct}/{total} ({100*correct//total}%)")
        from memory.semantic_memory import remember
        remember(f"Feedback: {correct}/{total} предсказания верни. Уроци: {lessons[:3]}", axis="SELF_IMPROVEMENT")
    return lessons

if __name__ == "__main__":
    print(f"Predictions: {len(_load())}")
