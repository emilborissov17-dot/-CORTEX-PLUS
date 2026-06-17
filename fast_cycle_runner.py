#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fast_cycle_runner.py
Бърз цикъл — пуска се всеки час.
"""
from __future__ import annotations
import subprocess, sys, pathlib, json, time, gc
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = pathlib.Path(__file__).resolve().parent
import os
os.environ["CORTEX_BASE"] = str(BASE)

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _free_ollama():
    gc.collect()

def _llm(prompt):
    try:
        from core.groq_backend import call_groq
        text = call_groq(prompt, max_tokens=1024)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if "</think>" in text:
            text = text.split("</think>")[-1].strip()
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

def _write_snapshot(axis, folder, domain, data):
    out_dir = BASE / "snapshots" / domain / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{folder}_snapshot_latest.json"
    data["snapshot_timestamp"] = _utc_now()
    data["axis"]               = axis
    data["source_type"]        = "LLM_FAST_CYCLE"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

def _run(label, fn, free_after=False):
    try:
        fn()
        print(f"[FAST_CYCLE] {label} -> OK")
    except Exception as e:
        print(f"[FAST_CYCLE] {label} -> FAILED: {e}")
    if free_after:
        _free_ollama()

def run_web_intelligence():
    try:
        sys.path.insert(0, str(BASE))
        from web_intelligence_agent import run as _wi_run
        _wi_run()
        print("[FAST_CYCLE] web_intelligence_agent -> OK")
    except ImportError:
        print("[FAST_CYCLE] web_intelligence_agent -> SKIP")
    except Exception as e:
        print(f"[FAST_CYCLE] web_intelligence_agent -> FAILED: {e}")

def refresh_llm_axes():
    axes = [
        {
            "axis": "GENERAL_SELF_REVIEW",
            "folder": "general_self_review",
            "domain": "cosmos",
            "use_reasoner": True,
        },
        {
            "axis": "GOAL_PROGRESS_REVIEW",
            "folder": "goal_progress",
            "domain": "cosmos",
            "prompt": (
                "You are CORTEX++ AGI working toward: sustainable civilization, "
                "dignity for all, AGI in transparent service of humanity. "
                "Generate JSON for GOAL_PROGRESS_REVIEW. Include: "
                "current_level (LOW/MEDIUM/HIGH), overall_progress_pct (0-100), "
                "progress_by_domain dict (HUMAN/PLANET/CIVILIZATION/COSMOS each 0-100), "
                "main_bottlenecks list, next_actions list. Return ONLY valid JSON."
            ),
        },
        {
            "axis": "LONG_TERM_FUTURE_REVIEW",
            "folder": "long_term_future",
            "domain": "cosmos",
            "prompt": (
                "Generate fresh JSON for LONG_TERM_FUTURE_REVIEW "
                "(existential risks: nuclear, AGI misalignment, biorisks, climate collapse). "
                "Include: current_level, xrisk_score (0-100, lower=safer), "
                "main_risks list, trends list. Return ONLY valid JSON."
            ),
        },
    ]
    for cfg in axes:
        print(f"[FAST_CYCLE] refreshing {cfg['axis']}...")
        if cfg.get("use_reasoner"):
            from core.cortex_reasoner import self_review
            snap = self_review()
        else:
            snap = _llm(cfg["prompt"])
        path = _write_snapshot(cfg["axis"], cfg["folder"], cfg["domain"], snap)
        print(f"[FAST_CYCLE] wrote {cfg['axis']} -> {path}")
    _free_ollama()

def run_trend_tracker():
    print("[FAST_CYCLE] running trend_tracker...")
    r = subprocess.run(
        [sys.executable, "-m", "memory.trend_tracker"],
        cwd=str(BASE), capture_output=False, timeout=120
    )
    print(f"[FAST_CYCLE] trend_tracker -> {'OK' if r.returncode == 0 else 'FAILED'}")

def update_master():
    snap_dir  = BASE / "snapshots"
    snapshots = {}
    for json_file in sorted(snap_dir.rglob("*_snapshot_latest.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            axis = data.get("axis", json_file.stem)
            if axis != "master_snapshot_latest":
                snapshots[axis] = data
        except Exception:
            pass
    out = BASE / "snapshots" / "master" / "master_snapshot_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "report_type": "MASTER_CIVILIZATION_SNAPSHOT",
        "timestamp":   _utc_now(),
        "cycle_type":  "FAST_CYCLE",
        "axes_count":  len(snapshots),
        "axes":        list(snapshots.keys()),
        "snapshots":   snapshots,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[FAST_CYCLE] master updated — {len(snapshots)} axes")


def main():
    print("=" * 50)
    print(f"[FAST_CYCLE] started at {_utc_now()}")
    print("=" * 50)

    # ── 1. Web Intelligence ──
    run_web_intelligence()

    # ── 2. LLM self-review оси ──
    refresh_llm_axes()
    update_master()

    # ── 3. Trend tracker ──
    run_trend_tracker()

    # ── 4. Internet intelligence ──
    _run("internet_agent", lambda: __import__(
        "agents.internet.internet_agent", fromlist=["run"]).run(), free_after=True)

    # ── 5. Civilization snapshots ──
    _run("civilization_snapshots_agent", lambda: __import__(
        "agents.civilization.civilization_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 6. Planet snapshots ──
    _run("planet_snapshots_agent", lambda: __import__(
        "agents.planet.planet_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 7. Human snapshots ──
    _run("human_snapshots_agent", lambda: __import__(
        "agents.human.human_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 8. Cosmos snapshots ──
    _run("cosmos_snapshots_agent", lambda: __import__(
        "agents.cosmos.cosmos_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 9. Planetary potential ──
    _run("planetary_potential_agent", lambda: __import__(
        "agents.planet.planetary_potential_review_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 10. Energy review ──
    _run("energy_review_agent", lambda: __import__(
        "agents.energy.energy_review_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 11. Self awareness ──
    def _self_awareness():
        from agents.self.self_awareness_agent import SelfAwarenessAgent
        SelfAwarenessAgent().run()
    _run("self_awareness_agent", _self_awareness, free_after=True)

    # ── 12. Update master след всички snapshots ──
    update_master()

    # ── 12.5. Auto levels — СЛЕД snapshot агентите, не преди! ──
    # Тук auto_level чете реални данни от обновения master snapshot.
    # execute_patches ще вика auto_level отново за before/after measurement.
    try:
        from memory.auto_level import run as compute_levels
        levels, corrections, alerts = compute_levels()
        print(f"[FAST_CYCLE] auto_levels -> {len(levels)} оси | {len(corrections)} корекции | {len(alerts)} alerts")
    except Exception as e:
        print(f"[FAST_CYCLE] auto_levels -> FAILED: {e}")

    # ── 12.6. Goal score calculator ──
    try:
        from goal_score_calculator import compute_goal_score
        gs_result = compute_goal_score()
        composite  = gs_result["composite_score"]
        print(f"[FAST_CYCLE] goal_score_calculator -> composite={composite:.4f}")
        # Persist result as snapshot so master + MerkleMemory can read it
        gs_snap = BASE / "snapshots" / "master" / "goal_score_latest.json"
        gs_snap.parent.mkdir(parents=True, exist_ok=True)
        gs_snap.write_text(
            json.dumps({**gs_result, "axis": "GOAL_SCORE", "source_type": "CALCULATED"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[FAST_CYCLE] goal_score_calculator -> FAILED: {e}")

    # ── 13. Body scan ──
    _run("body_scanner", lambda: __import__(
        "agents.body.body_scanner", fromlist=["run"]).run())

    # ── 14. Growth planner ──
    _run("growth_planner", lambda: __import__(
        "agents.body.growth_planner", fromlist=["run"]).run())

    # ── 15. OpenClaw ──
    _run("openclaw_agent", lambda: __import__(
        "agents.openclaw.openclaw_agent", fromlist=["run"]).run(), free_after=True)

    # ── 16. Action recommendations ──
    try:
        from core.cortex_reasoner import reason
        from memory.semantic_memory import remember
        rec = reason(
            "Какви са най-важните действия сега базирани на "
            "последните данни, тенденции и web intelligence?"
        )
        remember(rec[:500], axis="ACTION_RECOMMENDATIONS", source="fast_cycle")
        print("[FAST_CYCLE] Препоръка записана в паметта.")
        try:
            from memory.context_injector import record_causal
            record_causal(
                action="fast_cycle_groq_reasoning",
                effect=rec[:200],
                why="Groq reasoning върху последни данни, тенденции и snapshots",
                axis="ACTION_RECOMMENDATIONS",
            )
        except Exception as e:
            print(f"[FAST_CYCLE] record_causal грешка: {e}")
    except Exception as e:
        print(f"[FAST_CYCLE] Препоръка грешка: {e}")

    # ── 17. Self observer ──
    _run("self_observer", lambda: __import__(
        "agents.core.self_observer", fromlist=["run"]).run(), free_after=True)

    # ── 18. Self modifier ──
    _run("self_modifier", lambda: __import__(
        "agents.core.self_modifier", fromlist=["run"]).run(), free_after=True)

    # ── 19. Execute patches — вика auto_level вътрешно за реален before/after ──
    _run("execute_patches", lambda: __import__(
        "execute_patches", fromlist=["run"]).run())

    # ── 20. Feedback loop ──
    _run("feedback_loop", lambda: __import__(
        "agents.core.feedback_loop", fromlist=["run"]).run())

    # ── 21. Orchestrator + session ──
    try:
        from core.cortex_orchestrator import run as _orchestrate
        from core.session_updater import update as _update
        _orchestrate()
        _update()
        print("[FAST_CYCLE] orchestrator + session -> OK")
    except Exception as e:
        print(f"[SESSION] Грешка: {e}")

    # ── 22. Daily analysis ──
    _run("daily_analysis", lambda: __import__(
        "agents.core.daily_analysis_agent", fromlist=["main"]).main())

    # ── 23. Continuous learning ──
    try:
        from memory.continuous_learner import learn_from_cycle
        result = learn_from_cycle({"source": "fast_cycle_runner", "timestamp": _utc_now()})
        if isinstance(result, dict):
            print(f"[FAST_CYCLE] Continuous learning: {result.get('axes_updated', '?')} оси, {result.get('total_in_kb', '?')} KB")
        else:
            print("[FAST_CYCLE] Continuous learning -> OK")
    except Exception as e:
        print(f"[FAST_CYCLE] Continuous learning грешка: {e}")

    print("=" * 50)
    print(f"[FAST_CYCLE] done at {_utc_now()}")
    print("=" * 50)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pulse":
        try:
            from memory.autonomic_pulse import start as _ps, read as _pr, stop as _pstop
        except ImportError:
            print("autonomic_pulse not available")
            sys.exit(1)
        _ps()
        print("\nPulse monitor active. Press Ctrl+C to stop.\n")
        try:
            while True:
                stats = _pr()
                print(f"CPU: {stats['cpu_pct']}% | RAM: {stats['ram_pct']}% | Free: {stats['ram_free_gb']}GB")
                time.sleep(2)
        except KeyboardInterrupt:
            print("\nStopping pulse monitor...")
            _pstop()
    else:
        main()