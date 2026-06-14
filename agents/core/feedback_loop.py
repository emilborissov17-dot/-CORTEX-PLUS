#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agents/core/feedback_loop.py — CORTEX++ затворен feedback loop."""
from __future__ import annotations
import json, pathlib, os
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(os.environ.get("CORTEX_BASE", pathlib.Path(__file__).resolve().parents[2])).resolve()
FEEDBACK_LOG   = BASE_DIR / "memory" / "feedback_log.json"
SCORES_FILE    = BASE_DIR / "memory" / "goal_score_history.json"
PROPOSALS_FILE = BASE_DIR / "memory" / "improvement_proposals.json"
JOURNAL_FILE   = BASE_DIR / "memory" / "development_journal.json"
MASTER_SNAP    = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"
LEVEL_MAP   = {"LOW": 30, "MEDIUM": 60, "HIGH": 85, "CRITICAL": 10}
URGENCY_MAP = {"LOW": 80, "MEDIUM": 50, "HIGH": 20, "CRITICAL": 5}

def _now(): return datetime.now(timezone.utc).isoformat()
def _load_json(path, default):
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else default
    except Exception: return default
def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _axis_score(snap):
    candidates = [snap]
    if "metrics" in snap and isinstance(snap["metrics"], dict):
        candidates.append(snap["metrics"])
    if "error" in snap: return None
    for s in candidates:
        if "score" in s and isinstance(s["score"], (int, float)): return float(s["score"])
        if "overall_progress_pct" in s: return float(s["overall_progress_pct"])
        if "capacity_pct" in s: return float(s["capacity_pct"])
        for field in ["current_level", "level"]:
            val = s.get(field, "")
            if val in LEVEL_MAP: return float(LEVEL_MAP[val])
        urgency = s.get("urgency", "")
        if urgency in URGENCY_MAP: return float(URGENCY_MAP[urgency])
        if "xrisk_score" in s: return max(0.0, 100.0 - float(s["xrisk_score"]))
    return None

def read_current_scores():
    master = _load_json(MASTER_SNAP, {})
    scores = {}
    for axis, snap in master.get("snapshots", {}).items():
        if isinstance(snap, dict):
            s = _axis_score(snap)
            if s is not None: scores[axis] = round(s, 2)
    return scores

def read_baseline():
    history = _load_json(SCORES_FILE, [])
    return history[-1].get("scores", {}) if history else {}

def compute_delta(current, baseline):
    delta = {}
    for axis in set(current) | set(baseline):
        if axis in current and axis in baseline:
            delta[axis] = round(current[axis] - baseline[axis], 2)
    return delta

def read_last_actions():
    journal = _load_json(JOURNAL_FILE, {})
    actions = []
    for day_data in journal.values():
        if isinstance(day_data, dict):
            actions.extend(day_data.get("auto_modifications", []))
    return [a for a in actions if a.get("action") != "FAILED"][-10:]

def attribute_effects(delta, actions):
    attributed = []
    total_pos = sum(v for v in delta.values() if v > 0)
    total_neg = sum(v for v in delta.values() if v < 0)
    n = max(len(actions), 1)
    for action in actions:
        net = round((total_pos + total_neg) / n, 2)
        attributed.append({
            "action": action.get("action", "?")[:80],
            "problem": action.get("problem_solved", "")[:80],
            "timestamp": action.get("timestamp", _now()),
            "net_effect": net,
            "axes_improved": [k for k, v in delta.items() if v > 0.5],
            "axes_degraded": [k for k, v in delta.items() if v < -0.5],
            "verdict": "BENEFICIAL" if net > 0.5 else "HARMFUL" if net < -0.5 else "NEUTRAL",
        })
    return attributed

def update_proposal_priorities(attributed):
    raw = _load_json(PROPOSALS_FILE, {})
    proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
    if not isinstance(proposals, list): return
    harmful    = {e["problem"][:50] for e in attributed if e["verdict"] == "HARMFUL"}
    beneficial = {e["problem"][:50] for e in attributed if e["verdict"] == "BENEFICIAL"}
    changed = 0
    for p in proposals:
        prob = p.get("problem", "")[:50]
        if prob in harmful and p.get("priority") != "LOW":
            p["priority"] = "LOW"; p["feedback_note"] = "Понижен — влошаване"; changed += 1
        elif prob in beneficial and p.get("priority") == "LOW":
            p["priority"] = "MEDIUM"; p["feedback_note"] = "Повишен — подобрение"; changed += 1
    if changed:
        if isinstance(raw, dict): raw["proposals"] = proposals
        _save_json(PROPOSALS_FILE, raw if isinstance(raw, dict) else proposals)
        print(f"[FEEDBACK] Обновени {changed} proposals.")

def save_feedback(current, delta, attributed):
    log = _load_json(FEEDBACK_LOG, [])
    log.append({
        "timestamp": _now(),
        "avg_score": round(sum(current.values()) / max(len(current), 1), 2),
        "axes_count": len(current),
        "axes_improved": len([v for v in delta.values() if v > 0]),
        "axes_degraded": len([v for v in delta.values() if v < 0]),
        "top_improvements": sorted([(k,v) for k,v in delta.items() if v>0], key=lambda x:x[1], reverse=True)[:5],
        "top_degradations": sorted([(k,v) for k,v in delta.items() if v<0], key=lambda x:x[1])[:5],
        "beneficial_actions": len([a for a in attributed if a["verdict"]=="BENEFICIAL"]),
        "harmful_actions": len([a for a in attributed if a["verdict"]=="HARMFUL"]),
    })
    _save_json(FEEDBACK_LOG, log[-200:])

def save_score_snapshot(current):
    history = _load_json(SCORES_FILE, [])
    history.append({"timestamp": _now(), "scores": current})
    _save_json(SCORES_FILE, history[-500:])

def make_predictions(current, delta):
    try:
        from memory.prediction_tracker import make_prediction
        for axis, d in delta.items():
            if d > 2.0:
                score = current.get(axis, 50)
                urgency = "LOW" if score > 70 else "MEDIUM" if score > 40 else "HIGH"
                make_prediction(axis, f"Очакваме продължаване (delta={d})", urgency)
    except Exception as e:
        print(f"[FEEDBACK] Предсказания грешка: {e}")

def run():
    print("[FEEDBACK_LOOP] ══════════════════════════════")
    print("[FEEDBACK_LOOP] Затворен feedback цикъл")
    current = read_current_scores()
    if not current:
        print("[FEEDBACK_LOOP] Няма scores в master snapshot.")
        return
    baseline  = read_baseline()
    delta     = compute_delta(current, baseline)
    actions   = read_last_actions()
    avg_score = round(sum(current.values()) / max(len(current), 1), 2)
    improved  = len([v for v in delta.values() if v > 0])
    degraded  = len([v for v in delta.values() if v < 0])
    print(f"[FEEDBACK_LOOP] Axes: {len(current)} | Avg score: {avg_score}/100")
    print(f"[FEEDBACK_LOOP] Δ improved: {improved} | degraded: {degraded}")
    top_up = sorted([(k,v) for k,v in delta.items() if v>0], key=lambda x:x[1], reverse=True)[:3]
    top_dn = sorted([(k,v) for k,v in delta.items() if v<0], key=lambda x:x[1])[:3]
    if top_up: print(f"[FEEDBACK_LOOP] Gains:  {top_up}")
    if top_dn: print(f"[FEEDBACK_LOOP] Losses: {top_dn}")
    attributed = attribute_effects(delta, actions)
    beneficial = [a for a in attributed if a["verdict"]=="BENEFICIAL"]
    harmful    = [a for a in attributed if a["verdict"]=="HARMFUL"]
    if beneficial: print(f"[FEEDBACK_LOOP] ✅ Beneficial: {len(beneficial)}")
    if harmful:    print(f"[FEEDBACK_LOOP] ❌ Harmful:    {len(harmful)}")
    update_proposal_priorities(attributed)
    save_feedback(current, delta, attributed)
    save_score_snapshot(current)
    make_predictions(current, delta)
    try:
        from memory.semantic_memory import remember
        remember(f"Feedback: avg={avg_score}, +{improved}/-{degraded} axes, {len(beneficial)} beneficial", axis="FEEDBACK_LOOP", source="feedback_loop")
    except Exception: pass
    print(f"[FEEDBACK_LOOP] ✅ done at {_now()}")

if __name__ == "__main__":
    run()
