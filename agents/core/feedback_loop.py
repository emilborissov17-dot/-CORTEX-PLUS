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
# For *_RISK_* axes the LLM's current_level describes the RISK, not the health:
# HIGH risk is a BAD state. Mapping it through LEVEL_MAP (HIGH->85) recorded a
# month of "CLIMATE_GLOBAL_RISK_REVIEW = 85" while the data said +1.19°C.
# (NOTED item "LOW/HIGH naming on _RISK_ axes", 13 Jul 2026 — fixed 13 Aug 2026.)
RISK_LEVEL_MAP = {"LOW": 85, "MEDIUM": 50, "HIGH": 20, "CRITICAL": 5}

def _is_risk_axis(axis_name: str) -> bool:
    return "RISK" in str(axis_name).upper()

def _now(): return datetime.now(timezone.utc).isoformat()
def _load_json(path, default):
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else default
    except Exception: return default
def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _axis_score(snap, axis_name=""):
    candidates = [snap]
    if "metrics" in snap and isinstance(snap["metrics"], dict):
        candidates.append(snap["metrics"])
    if "error" in snap: return None
    level_map = RISK_LEVEL_MAP if _is_risk_axis(axis_name) else LEVEL_MAP
    for s in candidates:
        if "score" in s and isinstance(s["score"], (int, float)): return float(s["score"])
        if "overall_progress_pct" in s: return float(s["overall_progress_pct"])
        if "capacity_pct" in s: return float(s["capacity_pct"])
        for field in ["current_level", "level"]:
            val = s.get(field, "")
            if val in level_map: return float(level_map[val])
        urgency = s.get("urgency", "")
        if urgency in URGENCY_MAP: return float(URGENCY_MAP[urgency])
        if "xrisk_score" in s: return max(0.0, 100.0 - float(s["xrisk_score"]))
    return None

def _measured_axis_scores():
    """Evidence-grounded per-axis scores (0-100) from goal_score_calculator —
    ONLY for axes whose primary metric had a real observed value this cycle.
    Verification over assertion: where a measurement exists, it outranks the
    LLM's LOW/MEDIUM/HIGH bucket, which for a month collapsed every axis to
    a constant 60. Fail-open: any error returns {} and the LLM buckets stand."""
    try:
        import goal_score_calculator as gsc
        res = gsc.compute_goal_score()
        measured = {}
        for detail in res.get("metric_details", {}).values():
            if detail.get("current") is not None and detail.get("axis"):
                measured[detail["axis"]] = round(float(detail["score"]) * 100.0, 2)
        return measured
    except Exception as e:
        print(f"[FEEDBACK] measured scores unavailable ({type(e).__name__}: {e}) — using LLM levels only")
        return {}

def read_current_scores():
    master = _load_json(MASTER_SNAP, {})
    measured = _measured_axis_scores()
    scores = {}
    sources = {}
    for axis, snap in master.get("snapshots", {}).items():
        if not isinstance(snap, dict):
            continue
        if axis in measured:
            scores[axis] = measured[axis]
            sources[axis] = "measured"
        else:
            s = _axis_score(snap, axis)
            if s is not None:
                scores[axis] = round(s, 2)
                sources[axis] = "llm_level(risk-inverted)" if _is_risk_axis(axis) else "llm_level"
    if sources:
        n_meas = sum(1 for v in sources.values() if v == "measured")
        print(f"[FEEDBACK] axis scores: {n_meas} measured / {len(sources) - n_meas} LLM-level")
    read_current_scores.last_sources = sources  # exposed for the history snapshot
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
    for action in actions:
        if "delta" in action and action["delta"] is not None:
            net = round(float(action["delta"]), 2)
        elif action.get("score_before") is not None and action.get("score_after") is not None:
            net = round(float(action["score_after"]) - float(action["score_before"]), 2)
        else:
            net = None  # no score data recorded for this action → unattributable

        verdict = ("BENEFICIAL" if net is not None and net > 0.5
                   else "HARMFUL"  if net is not None and net < -0.5
                   else "NEUTRAL")

        attributed.append({
            "action":        action.get("action", "?")[:80],
            "problem":       action.get("problem_solved", "")[:80],
            "timestamp":     action.get("timestamp", _now()),
            "net_effect":    net,
            "axes_improved": [k for k, v in delta.items() if v > 0.5],
            "axes_degraded": [k for k, v in delta.items() if v < -0.5],
            "verdict":       verdict,
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
    entry = {"timestamp": _now(), "scores": current}
    sources = getattr(read_current_scores, "last_sources", None)
    if sources:
        entry["score_sources"] = sources  # audit: which number is a measurement, which is an LLM opinion
    history.append(entry)
    _save_json(SCORES_FILE, history[-500:])

def make_predictions(current, delta):
    # RETIRED (F1, 2026-07-21): legacy unsealed self-graded predictor removed.
    # Authoritative axis self-prediction runs via the sealed prophecy 'axis_next'
    # path from the orchestrator. No-op: writes nothing, grades nothing.
    print("[FEEDBACK] legacy predictor retired — sealed axis_next path is authoritative")
    return None

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
