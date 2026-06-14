#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, pathlib
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent
OUT = BASE / "memory" / "cortex_full_state.json"

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
        except: pass
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
        except: pass

    # Axis scores — само нормализирани 0-100
    history_file = BASE / "memory" / "axis_history.json"
    if history_file.exists():
        try:
            h = json.loads(history_file.read_text(encoding="utf-8"))
            scores = {}
            for axis, entries in h.items():
                if isinstance(entries, list) and entries:
                    last = entries[-1]
                    if last.get("score") is not None:
                        s = float(last["score"])
                        if 0 <= s <= 100:
                            scores[axis] = round(s, 1)
                    else:
                        metrics = last.get("metrics", {})
                        vals = []
                        for v in metrics.values():
                            try:
                                fv = float(v)
                                if 0 <= fv <= 100:
                                    vals.append(fv)
                            except: pass
                        if vals:
                            scores[axis] = round(sum(vals)/len(vals), 1)
            state["trends"]["scores"] = scores
        except: pass

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
        except: pass

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
        except: pass

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
        except: pass

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
        except: pass

    # OpenClaw
    openclaw_file = BASE / "snapshots" / "openclaw" / "openclaw_snapshot_latest.json"
    if openclaw_file.exists():
        try:
            o = json.loads(openclaw_file.read_text(encoding="utf-8"))
            state["agents"]["openclaw"] = {
                "health": o.get("health"),
                "mission_pct": o.get("mission_alignment_pct"),
            }
        except: pass

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
        except: pass

    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SCANNER] Сканирано: {snap_count} snapshots")
    print(f"[SCANNER] Trends: {len(state['trends'].get('stable',[]))} stable / {len(state['trends'].get('insufficient',[]))} insufficient")
    print(f"[SCANNER] ChromaDB: {state['session'].get('chromadb_memories','—')}")
    print(f"[SCANNER] CPU: {state['system'].get('cpu','—')}% | RAM free: {state['system'].get('ram_free','—')}GB")
    print(f"[SCANNER] Записано → {OUT}")
    return state

if __name__ == "__main__":
    scan()