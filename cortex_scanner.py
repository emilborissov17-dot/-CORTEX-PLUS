#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, pathlib
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent
OUT = BASE / "memory" / "cortex_full_state.json"

def axis_scores(history: dict) -> dict:
    """Axis -> its latest score, 0..100. An axis with no score gets NOTHING.

    WHAT WAS REMOVED HERE AND WHY (ITEM 34-A, 29 Aug 2026). When the latest
    point had score None, this used to average every numeric value in that
    point's `metrics` falling between 0 and 100 and publish the mean AS THE AXIS
    SCORE — to state["trends"]["scores"] and on to
    memory/cortex_full_state.json, which cortex_dashboard.html renders.

        else:
            metrics = last.get("metrics", {})
            vals = [...every metric value in 0..100...]
            if vals:
                scores[axis] = round(sum(vals)/len(vals), 1)

    Metrics are not commensurable with a score, nor with each other. A
    percentage, a count and a ratio that all happen to land in 0..100 would be
    averaged into a number that means nothing and looks exactly like a
    measurement. Kimi: "active fabrication, worse than omission."

    MEASURED BEFORE REMOVAL, twice and independently reproduced: 0 axes affected
    on 2026-08-29, and 0 of 1848 points in the whole retained history would ever
    have triggered it. Not a survivorship artefact — such a point has TRUTHY
    metrics, so ITEM 12(c)'s old filter would have kept it. THAT ZERO IS A DATED
    MEASUREMENT AND IT EXPIRES: nothing prevents _extract_metrics returning data
    while _compute_axis_score returns None, so the branch was disarmed while it
    was still unreachable rather than after automation made it reachable.
    test/test_scanner_never_invents_a_score.py is what turns the dated zero into
    a property, by feeding the exact shape that has never occurred.

    AN AXIS WITH NO SCORE IS NOT LOST. It is routed to trends.insufficient,
    which comes from trends_latest.json's own categorisation above and is
    rendered by cortex_dashboard.html at :87 as a count and at :89 by name,
    labelled INSUFFICIENT. That is correct categorisation, not omission — a
    point all three of us had described wrongly until the scanner was actually
    run.
    """
    scores: dict = {}
    for axis, entries in (history or {}).items():
        if not (isinstance(entries, list) and entries):
            continue
        last = entries[-1]
        if not isinstance(last, dict):
            continue
        raw = last.get("score")
        if raw is None:
            continue          # no score is no score. Nothing is derived from metrics.
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 100:
            scores[axis] = round(value, 1)
    return scores


def scan():
    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "snapshots": {}, "memory": {}, "agents": {},
        "trends": {}, "session": {}, "reasoning": {},
        "predictor": {}, "system": {}
    }

    # Snapshots
    snap_dir = BASE / "snapshots"
    snap_count = 0
    for f in sorted(snap_dir.rglob("*_snapshot_latest.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            axis = data.get("axis", f.stem)
            if axis != "master_snapshot_latest":
                state["snapshots"][axis] = {
                    "timestamp": data.get("snapshot_timestamp"),
                    "current_level": data.get("current_level"),
                    "summary": str(data.get("summary", data.get("real_state", "")))[:200]
                }
                snap_count += 1
        except Exception: pass
    state["system"]["snap_count"] = snap_count

    # Trends
    trends_file = BASE / "memory" / "trends_latest.json"
    if trends_file.exists():
        try:
            t = json.loads(trends_file.read_text(encoding="utf-8"))
            state["trends"] = {
                "date": t.get("date"),
                "stable": t.get("stable", []),
                "improving": t.get("improving", []),
                "deteriorating": t.get("deteriorating", []),
                "insufficient": t.get("insufficient_data", []),
                "axes_tracked": t.get("axes_tracked", 0)
            }
        except Exception: pass

    # Axis scores — само нормализирани 0-100
    history_file = BASE / "memory" / "axis_history.json"
    if history_file.exists():
        try:
            h = json.loads(history_file.read_text(encoding="utf-8"))
            state["trends"]["scores"] = axis_scores(h)
        except Exception: pass

    # Session — последният наличен файл
    sessions = sorted((BASE / "memory").glob("session_*.json"), reverse=True)
    session_file = sessions[0] if sessions else None
    if session_file.exists():
        try:
            s = json.loads(session_file.read_text(encoding="utf-8"))
            cs = s.get("current_state", {})
            state["session"] = {
                "date": s.get("date"),
                "chromadb_memories": cs.get("chromadb_memories"),
                "groq": cs.get("groq"),
                "achievements": s.get("achievements", [])[:5]
            }
        except Exception: pass

    # Reasoning
    reasoning_file = BASE / "memory" / "reasoning_memory.json"
    if reasoning_file.exists():
        try:
            r = json.loads(reasoning_file.read_text(encoding="utf-8"))
            sessions = r.get("sessions", [])
            state["reasoning"] = {
                "total_sessions": len(sessions),
                "last": sessions[-1] if sessions else None
            }
        except Exception: pass

    # Journal
    journal_file = BASE / "memory" / "development_journal.json"
    if journal_file.exists():
        try:
            j = json.loads(journal_file.read_text(encoding="utf-8"))
            ok, fail = 0, 0
            recent = []
            for day in sorted(j.keys())[-3:]:
                for m in j[day].get("auto_modifications", []):
                    if m.get("action") != "FAILED":
                        ok += 1
                        recent.append({"status": "OK", "action": m.get("action", "")[:80]})
                    else:
                        fail += 1
                        recent.append({"status": "FAIL", "problem": m.get("problem", "")[:80]})
            state["memory"]["modifier_ok"] = ok
            state["memory"]["modifier_fail"] = fail
            state["memory"]["modifier_recent"] = recent[-12:]
        except Exception: pass

    # Body scan
    body_file = BASE / "memory" / "body_scan_latest.json"
    if body_file.exists():
        try:
            b = json.loads(body_file.read_text(encoding="utf-8"))
            hw = b.get("hardware", {})
            gpu = hw.get("gpu", {})
            feeling = b.get("self_feeling", "")
            state["system"]["health"] = feeling[:60] if feeling else None
            state["system"]["cpu"] = hw.get("cpu_percent")
            state["system"]["ram_free"] = hw.get("ram_free_gb")
            state["system"]["ram_used"] = hw.get("ram_percent")
            state["system"]["gpu_name"] = gpu.get("name")
            state["system"]["gpu_vram_free"] = gpu.get("vram_free_mb")
        except Exception: pass

    # CortexStrategist
    cortex_strategist_file = BASE / "snapshots" / "cortex_strategist" / "cortex_strategist_snapshot_latest.json"
    if cortex_strategist_file.exists():
        try:
            o = json.loads(cortex_strategist_file.read_text(encoding="utf-8"))
            state["agents"]["cortex_strategist"] = {
                "health": o.get("health"),
                "mission_pct": o.get("mission_alignment_pct"),
            }
        except Exception: pass

    # Predictor
    predictor_file = BASE / "memory" / "predictor_memory.json"
    if predictor_file.exists():
        try:
            p = json.loads(predictor_file.read_text(encoding="utf-8"))
            preds = p.get("predictions", [])
            resolved = [x for x in preds if x.get("actual") is not None]
            errs = [x["error"] for x in resolved if x.get("error") is not None]
            state["predictor"] = {
                "total": len(preds),
                "resolved": len(resolved),
                "avg_error": round(sum(errs)/len(errs), 2) if errs else None,
                "last_5": preds[-5:]
            }
        except Exception: pass

    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SCANNER] Сканирано: {snap_count} snapshots")
    print(f"[SCANNER] Trends: {len(state['trends'].get('stable',[]))} stable / {len(state['trends'].get('insufficient',[]))} insufficient")
    print(f"[SCANNER] ChromaDB: {state['session'].get('chromadb_memories','—')}")
    print(f"[SCANNER] CPU: {state['system'].get('cpu','—')}% | RAM free: {state['system'].get('ram_free','—')}GB")
    print(f"[SCANNER] Записано → {OUT}")
    return state

if __name__ == "__main__":
    scan()