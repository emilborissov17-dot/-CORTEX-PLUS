#!/usr/bin/env python3
"""
memory/prediction_tracker.py
CORTEX++ се учи от резултатите си.
Самопредложено от системата на 2026-03-14.
"""
import json, pathlib
from datetime import datetime, timezone, timedelta

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
PRED_FILE = BASE_DIR / "memory" / "predictions.json"

def _now(): return datetime.now(timezone.utc).isoformat()
def _load():
    try: return json.loads(PRED_FILE.read_text(encoding="utf-8"))
    except: return []

def make_prediction(axis, prediction, urgency):
    preds = _load()
    preds.append({
        "axis": axis, "prediction": prediction,
        "predicted_urgency": urgency, "made_at": _now(),
        "verify_after": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()[:10],
        "verified": False, "was_correct": None, "lesson": ""
    })
    PRED_FILE.write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")

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
