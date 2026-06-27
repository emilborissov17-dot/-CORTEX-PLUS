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
    gc.collect()  # release memory after every agent step

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
    gc.collect()

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


def _check_dependencies() -> bool:
    """Step 0 — проверява API ключове и Groq свързаност преди цикъла."""
    out_path = BASE / "snapshots" / "master" / "dependency_check_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Зарежда .env в os.environ (само ако ключът не е вече зареден)
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip()

    checks      = {}
    critical_ok = True

    # 1. Проверка на ключове
    key_levels = {
        "GROQ_API_KEY":    "critical",
        "GEMINI_API_KEY":  "important",
        "YOUTUBE_API_KEY": "optional",
        "NASA_API_KEY":    "optional",
    }
    for key, level in key_levels.items():
        present = bool(os.environ.get(key))
        checks[key] = {"present": present, "level": level}
        if not present and level == "critical":
            critical_ok = False
        print(f"[DEP_CHECK] {'OK' if present else 'MISSING':7s} {key} ({level})")

    # 2. Тестов call към Groq chat — директна HTTP заявка с requests.
    #    429 (rate limit) = ключът е валиден, API достъпно → третираме като OK.
    #    Не викаме call_groq() за да не задействаме 60s cooldown в главния цикъл.
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        try:
            import requests as _req
            from core.groq_backend import GROQ_API_URL, GROQ_MODEL
            r = _req.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 3},
                timeout=15,
            )
            # 200 = success, 429 = rate limited but key is valid and endpoint reachable
            if r.status_code in (200, 429):
                checks["groq_chat"] = {"ok": True, "http": r.status_code}
                print(f"[DEP_CHECK] OK      groq_chat (HTTP {r.status_code})")
            else:
                checks["groq_chat"] = {"ok": False, "error": f"HTTP {r.status_code}"}
                print(f"[DEP_CHECK] FAIL    groq_chat: HTTP {r.status_code}")
                critical_ok = False
        except Exception as e:
            checks["groq_chat"] = {"ok": False, "error": str(e)[:150]}
            print(f"[DEP_CHECK] FAIL    groq_chat: {e}")
            critical_ok = False
    else:
        checks["groq_chat"] = {"ok": False, "error": "no key"}

    # 3. Groq Whisper — same key as groq_chat; ако chat мина, Whisper ще мине също
    if checks.get("groq_chat", {}).get("ok"):
        checks["groq_whisper"] = {"ok": True, "note": "key verified via groq_chat"}
        print("[DEP_CHECK] OK      groq_whisper (key verified via groq_chat)")
    else:
        checks["groq_whisper"] = {"ok": False, "note": "skipped — groq_chat failed"}
        print("[DEP_CHECK] SKIP    groq_whisper (groq_chat failed)")

    report = {
        "timestamp":       _utc_now(),
        "all_critical_ok": critical_ok,
        "checks":          checks,
        "note":            "" if critical_ok else (
            "ЦИКЪЛЪТ Е СПРЯН. Провери горните грешки и рестартирай fast_cycle_runner.py."
        ),
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return critical_ok


def _openclaw_to_proposals():
    snap_path     = BASE / "snapshots" / "openclaw" / "openclaw_snapshot_latest.json"
    proposals_path = BASE / "memory" / "improvement_proposals.json"
    if not snap_path.exists():
        print("[FAST_CYCLE] openclaw_to_proposals -> no snapshot yet")
        return
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
        new_proposals = []
        for act in data.get("immediate_actions", []):
            new_proposals.append({
                "component":       "unknown",
                "problem":         act.get("why", "OpenClaw action"),
                "solution":        act.get("action", ""),
                "measurable_goal": act.get("action", "")[:80],
                "root_cause":      f"OpenClaw scan → {act.get('file', 'unknown')}",
                "priority":        "HIGH",
                "real_world_signal": True,
                "generated_by":    "OPENCLAW",
                "timestamp":       _utc_now(),
            })
        for gap in data.get("critical_gaps", []):
            if gap.get("impact") == "HIGH":
                new_proposals.append({
                    "component":       "unknown",
                    "problem":         gap.get("gap", ""),
                    "solution":        gap.get("fix", ""),
                    "measurable_goal": gap.get("gap", "")[:80],
                    "root_cause":      "Critical gap — OpenClaw full-scan",
                    "priority":        "HIGH",
                    "real_world_signal": True,
                    "generated_by":    "OPENCLAW",
                    "timestamp":       _utc_now(),
                })
        if not new_proposals:
            print("[FAST_CYCLE] openclaw_to_proposals -> 0 HIGH proposals")
            return
        try:
            existing = json.loads(proposals_path.read_text(encoding="utf-8"))
            existing_list = existing.get("proposals", existing) if isinstance(existing, dict) else existing
        except Exception:
            existing_list = []
        merged = new_proposals + [p for p in existing_list if p.get("generated_by") != "OPENCLAW"]
        proposals_path.write_text(
            json.dumps({"proposals": merged}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[FAST_CYCLE] openclaw_to_proposals -> {len(new_proposals)} proposals injected")
    except Exception as e:
        print(f"[FAST_CYCLE] openclaw_to_proposals -> FAILED: {e}")


def _hyperclaw_to_proposals():
    """Convert the latest HyperClaw markdown plan to improvement proposals."""
    plans_dir = BASE / "plans"
    proposals_path = BASE / "memory" / "improvement_proposals.json"
    if not plans_dir.exists():
        return
    plan_files = sorted(plans_dir.glob("plan-*.md"), key=lambda p: p.name, reverse=True)
    if not plan_files:
        print("[FAST_CYCLE] hyperclaw_to_proposals -> no plan file found")
        return
    plan_text = plan_files[0].read_text(encoding="utf-8", errors="ignore")
    new_proposals = []
    current_axis = None
    import re as _re
    _bold_re      = _re.compile(r'\*{1,2}([^*]+)\*{1,2}')
    _obj_re       = _re.compile(r'^\*{0,2}OBJECTIVE\*{0,2}\s*:', _re.IGNORECASE)
    _step_num_re  = _re.compile(r'^\d+\.\s+(.+)')
    _step_dash_re = _re.compile(r'^-\s+STEP\s+\d+\s*[:.~]?\s*(.+)', _re.IGNORECASE)

    def _clean(text: str) -> str:
        return _bold_re.sub(r'\1', text).strip()

    for line in plan_text.splitlines():
        line = line.strip()
        for marker in ("HUMAN_AXIS_FOCUS", "PLANET_AXIS_FOCUS", "CIVILIZATION_AXIS_FOCUS", "COSMOS_AXIS_FOCUS"):
            if marker in line:
                current_axis = marker.replace("_AXIS_FOCUS", "")
        if current_axis and _obj_re.match(line):
            objective = _clean(_obj_re.sub("", line, count=1))
            if objective and "<" not in objective and len(objective) > 10:
                new_proposals.append({
                    "component":         current_axis,
                    "problem":           f"{current_axis} axis needs progress",
                    "solution":          objective,
                    "measurable_goal":   objective[:80],
                    "root_cause":        f"HyperClaw plan — {plan_files[0].name}",
                    "priority":          "MEDIUM",
                    "real_world_signal": True,
                    "generated_by":      "HYPERCLAW",
                    "timestamp":         _utc_now(),
                })
        if current_axis:
            m = _step_num_re.match(line) or _step_dash_re.match(line)
            if m:
                step = _clean(m.group(1))
                if step and "<" not in step and len(step) > 10:
                    new_proposals.append({
                        "component":         current_axis,
                        "problem":           f"Action required for {current_axis}",
                        "solution":          step,
                        "measurable_goal":   step[:80],
                        "root_cause":        f"HyperClaw step — {plan_files[0].name}",
                        "priority":          "MEDIUM",
                        "real_world_signal": True,
                        "generated_by":      "HYPERCLAW",
                        "timestamp":         _utc_now(),
                    })
    if not new_proposals:
        if len(plan_text) > 500:
            print("[FAST_CYCLE] hyperclaw_to_proposals -> 0 steps from non-empty plan (parser drift?)")
        else:
            print("[FAST_CYCLE] hyperclaw_to_proposals -> 0 concrete steps extracted")
        return
    try:
        existing = json.loads(proposals_path.read_text(encoding="utf-8"))
        existing_list = existing.get("proposals", existing) if isinstance(existing, dict) else existing
    except Exception:
        existing_list = []
    merged = new_proposals + [p for p in existing_list if p.get("generated_by") != "HYPERCLAW"]
    proposals_path.write_text(
        json.dumps({"proposals": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[FAST_CYCLE] hyperclaw_to_proposals -> {len(new_proposals)} proposals injected")


def _scan_needs_reanalysis() -> list[dict]:
    """
    Сканира всички snapshot JSON файлове за needs_reanalysis: true.
    Връща списък от {"axis", "file", "error"} — за логване и приоритизиране.
    Резултатът се записва в snapshots/master/needs_reanalysis_latest.json
    за да може initiative_tracker / openclaw да го намерят.
    """
    snap_dir = BASE / "snapshots"
    flagged = []
    for path in snap_dir.rglob("*.json"):
        if "master" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("needs_reanalysis"):
                axis = data.get("axis") or data.get("axis_name") or path.stem
                flagged.append({
                    "axis":  axis,
                    "file":  str(path.relative_to(BASE)),
                    "error": data.get("error", ""),
                })
        except Exception:
            continue

    out = BASE / "snapshots" / "master" / "needs_reanalysis_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"timestamp": _utc_now(), "count": len(flagged), "axes": flagged},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return flagged


def _load_directives() -> dict:
    """Read adaptive_directives.json written by body_scanner. Safe fallback to defaults."""
    p = BASE / "memory" / "adaptive_directives.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"cycle_mode": "FULL", "max_parallel_workers": 3, "llm_sleep_secs": 10}


def _send_windows_toast(title: str, body: str) -> None:
    """Send a Windows balloon notification via PowerShell NotifyIcon."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Warning; "
        "$n.BalloonTipIcon = 'Warning'; "
        "$n.BalloonTipTitle = $env:NOTIFY_TITLE; "
        "$n.BalloonTipText  = $env:NOTIFY_BODY; "
        "$n.Visible = $true; "
        "$n.ShowBalloonTip(30000); "
        "Start-Sleep -Milliseconds 500; "
        "$n.Dispose()"
    )
    env = {**os.environ, "NOTIFY_TITLE": title[:63], "NOTIFY_BODY": body[:255]}
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=15, env=env,
        )
    except Exception as e:
        print(f"[NOTIFY] toast failed: {e}")


def _get_pending_patches() -> list[str]:
    """Scan agents/core/*_patch.py for sensitive patches; return list of flagged filenames."""
    import re as _re
    _RULES = [
        (_re.compile(r"execute_patches"),                              "пипа execute_patches.py"),
        (_re.compile(r"self_modifier"),                                "пипа self_modifier.py"),
        (_re.compile(r"""["']git[\s"']"""),                            "git операция"),
        (_re.compile(r'subprocess[^\n]*"git'),                         "git subprocess"),
        (_re.compile(r"(?i)(password|secret)\s*=\s*[\"'][^\"']{4,}"), "credentials"),
        (_re.compile(r"open\s*\([^)]*\.env"),                          "пише в .env"),
    ]
    _DEL = _re.compile(r"(os\.remove|\.unlink\b|shutil\.rmtree|shutil\.rmdir)")

    pending = []
    for patch in sorted((BASE / "agents" / "core").glob("*_patch.py")):
        try:
            content = patch.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pending.append(patch.name)
            continue
        for line in content.splitlines():
            if line.strip().startswith("#"):
                continue
            hit = next((msg for rx, msg in _RULES if rx.search(line)), "")
            if not hit and _DEL.search(line) and "patch" not in line.lower():
                hit = "изтрива файл"
            if hit:
                pending.append(patch.name)
                break
    return pending


def _notify_patches_and_initiatives() -> None:
    """Run initiative tracker then send a single Windows notification combining
    pending code patches and PROPOSED/IN_PROGRESS initiatives."""
    # 1. Pending code patches
    pending_patches = _get_pending_patches()
    if pending_patches:
        print(f"[NOTIFY] {len(pending_patches)} patch(es) чакат одобрение: "
              f"{', '.join(pending_patches[:4])}" +
              (f" +{len(pending_patches)-4}" if len(pending_patches) > 4 else ""))
    else:
        print("[NOTIFY] няма patches чакащи одобрение")

    # 2. Run initiative tracker → creates data/initiatives/*.json
    active_initiatives: list[dict] = []
    try:
        from initiative_tracker import run as _it_run
        active_initiatives = _it_run()
    except Exception as e:
        print(f"[NOTIFY] initiative_tracker FAILED: {e}")

    if active_initiatives:
        prop  = sum(1 for i in active_initiatives if i.get("status") == "PROPOSED")
        prog  = sum(1 for i in active_initiatives if i.get("status") == "IN_PROGRESS")
        print(f"[NOTIFY] initiatives — PROPOSED={prop} IN_PROGRESS={prog}")
        for init in active_initiatives[:3]:
            print(f"[NOTIFY]   [{init['status']:11s}] {init['milestone'][:60]}  → {init['target_date']}")

    # 3. Build combined notification
    if not pending_patches and not active_initiatives:
        return

    body_parts: list[str] = []

    if pending_patches:
        patch_list = ", ".join(pending_patches[:5])
        if len(pending_patches) > 5:
            patch_list += f" +{len(pending_patches)-5}"
        body_parts.append(f"Patches({len(pending_patches)}): {patch_list}")

    if active_initiatives:
        prop  = sum(1 for i in active_initiatives if i.get("status") == "PROPOSED")
        prog  = sum(1 for i in active_initiatives if i.get("status") == "IN_PROGRESS")
        counts = []
        if prop: counts.append(f"{prop} PROPOSED")
        if prog: counts.append(f"{prog} IN_PROGRESS")
        # append first initiative milestone for context
        first = active_initiatives[0]
        body_parts.append(
            f"Initiatives({', '.join(counts)}): {first['milestone'][:50]}"
        )

    if pending_patches and active_initiatives:
        title = f"CORTEX++ — {len(pending_patches)} patch(es) + {len(active_initiatives)} initiatives"
    elif pending_patches:
        title = f"CORTEX++ — {len(pending_patches)} patch(es) чакат одобрение"
    else:
        title = f"CORTEX++ — {len(active_initiatives)} active initiatives"

    body = " | ".join(body_parts)
    print(f"[NOTIFY] {title}")
    _send_windows_toast(title, body)


def main():
    print("=" * 50)
    print(f"[FAST_CYCLE] started at {_utc_now()}")
    print("=" * 50)

    # ── Проверка за patches + initiatives преди всичко друго ──
    _notify_patches_and_initiatives()

    # ── 0. Body scan → adaptive directives (runs FIRST, before everything) ──
    print("[FAST_CYCLE] Step 0: body scan + dependency check...")
    try:
        from agents.body.body_scanner import run as _body_run
        _body_run()
    except Exception as e:
        print(f"[FAST_CYCLE] body_scan -> FAILED: {e}")

    directives = _load_directives()
    cycle_mode = directives.get("cycle_mode", "FULL")
    llm_sleep  = directives.get("llm_sleep_secs", 2)
    workers    = directives.get("max_parallel_workers", 3)
    print(f"[FAST_CYCLE] adaptive mode={cycle_mode} | workers={workers} | llm_sleep={llm_sleep}s")

    # ── Homeostatic assessment — самопознание преди старт ──
    try:
        from core.homeostasis import assess as _homeo_assess, as_prompt_block as _homeo_block
        homeo = _homeo_assess(verbose=True)
        if not homeo.get("can_start"):
            print(f"[FAST_CYCLE] СПРЯН — {homeo.get('abort_reason')}")
            print(f"[FAST_CYCLE] Нужди: {homeo.get('resource_needs')}")
            return
        # Override cycle_mode if homeostasis is more conservative
        h_mode = homeo.get("cycle_mode", "FULL")
        if h_mode == "MINIMAL" and cycle_mode != "MINIMAL":
            cycle_mode = "MINIMAL"
            workers    = 1
            llm_sleep  = 15
            print(f"[FAST_CYCLE] homeostasis overrides to MINIMAL mode")
        # Apply skip directives
        _skip_steps = set(homeo.get("skip_steps", []))
    except Exception as e:
        print(f"[FAST_CYCLE] homeostasis -> FAILED: {e}")
        _skip_steps = set()

    # Apply LLM sleep directive to groq_backend globally
    try:
        import core.groq_backend as _gb
        _gb._SLEEP_SECS = llm_sleep
    except Exception:
        pass

    # ── 0.5. Dependency check ──
    if not _check_dependencies():
        print("\n[FAST_CYCLE] СПРЯН — dependency check failed.")
        print("[FAST_CYCLE] Отчет: snapshots/master/dependency_check_latest.json")
        return

    # Skip web intel if offline
    if directives.get("skip_web_intel"):
        print("[FAST_CYCLE] OFFLINE — skipping web intelligence")
    else:
        pass  # falls through to Step 1 below

    # ── 0.7. needs_reanalysis scan — find axes that failed all LLM backends ──
    try:
        flagged = _scan_needs_reanalysis()
        if flagged:
            axes_str = ", ".join(f["axis"] for f in flagged)
            print(f"[FAST_CYCLE] needs_reanalysis: {len(flagged)} axes flagged — {axes_str}")
        else:
            print("[FAST_CYCLE] needs_reanalysis: no flagged axes")
    except Exception as e:
        print(f"[FAST_CYCLE] needs_reanalysis scan -> FAILED: {e}")

    # ── 1. Web Intelligence ──
    if not directives.get("skip_web_intel"):
        run_web_intelligence()
    else:
        print("[FAST_CYCLE] Step 1: web_intelligence SKIPPED (offline)")

    # ── 2. LLM self-review оси ──
    refresh_llm_axes()
    update_master()

    # ── 2.5. Global indicators — реални данни от 7 источника ──
    try:
        from core.global_indicators import fetch_all as _gi_fetch
        gi_data = _gi_fetch()
        gi_path = BASE / "snapshots" / "master" / "global_indicators_latest.json"
        gi_path.parent.mkdir(parents=True, exist_ok=True)
        gi_path.write_text(json.dumps(gi_data, ensure_ascii=False, indent=2), encoding="utf-8")
        co2  = gi_data.get("co2", {}).get("co2_ppm", "?")
        temp = gi_data.get("temperature", {}).get("temp_anomaly_c", "?")
        conf = gi_data.get("conflicts", {}).get("active_armed_conflicts", "?")
        print(f"[FAST_CYCLE] global_indicators -> CO2={co2}ppm | +{temp}°C | conflicts={conf}")
    except Exception as e:
        import traceback as _tb
        print(f"[FAST_CYCLE] global_indicators -> FAILED: {e}")
        _tb.print_exc()

    # ── 3. Trend tracker ──
    run_trend_tracker()

    # ── 3.5. OpenClaw — MUST run early before token budget is depleted by snapshots ──
    # Groq free tier: 100K tokens/day. Steps 4-11 consume ~90K tokens.
    # OpenClaw needs ~7K tokens — running it here ensures budget is available.
    _run("openclaw_agent", lambda: __import__(
        "agents.openclaw.openclaw_agent", fromlist=["run"]).run(), free_after=True)
    _openclaw_to_proposals()

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

    # ── 12.3. System hypergraph — rebuild so openclaw/self_observer can query it ──
    try:
        from system_hypergraph import build_hypergraph
        hg = build_hypergraph()
        print(f"[FAST_CYCLE] system_hypergraph -> {hg['triples_count']} triples | {len(hg['isolated_nodes'])} isolated")
    except Exception as e:
        print(f"[FAST_CYCLE] system_hypergraph -> FAILED: {e}")

    # ── 12.4. Scoring engine — освежи cortex_scores_latest.json ──
    try:
        from cortex_scoring_engine import score_all_snapshots as _score_all, AXIS_SCORERS as _AXIS_SCORERS
        import datetime as _dt
        _scores = _score_all()
        _out = BASE / "output" / "cortex_scores_latest.json"
        _out.parent.mkdir(parents=True, exist_ok=True)
        _out.write_text(
            json.dumps(
                {
                    "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    "scorer_version": "1.1",
                    "total_axes": len(_scores),
                    "scores": {
                        ax: {
                            "score": r.score,
                            "level": r.level,
                            "signals": r.signals,
                            "metrics_used": r.metrics_used,
                        }
                        for ax, r in _scores.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _real = sum(1 for ax in _scores if ax in _AXIS_SCORERS)
        print(f"[FAST_CYCLE] scoring_engine -> {len(_scores)} axes | {_real} real scorers | output/cortex_scores_latest.json")
    except Exception as e:
        print(f"[FAST_CYCLE] scoring_engine -> FAILED: {e}")

    # ── 12.5. Auto levels — СЛЕД snapshot агентите, не преди! ──
    # Тук auto_level чете реални данни от обновения master snapshot.
    # execute_patches ще вика auto_level отново за before/after measurement.
    levels = {}  # initialized here so MerkleMemory commit can read it at step 24
    try:
        from memory.auto_level import run as compute_levels
        levels, corrections, alerts = compute_levels()
        print(f"[FAST_CYCLE] auto_levels -> {len(levels)} оси | {len(corrections)} корекции | {len(alerts)} alerts")
    except Exception as e:
        print(f"[FAST_CYCLE] auto_levels -> FAILED: {e}")

    # ── 12.6. Goal score calculator ──
    composite = 0.0  # initialized here so MerkleMemory commit can read it at step 24
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

    # ── 12.7. Cognitive Orchestrator — Attentional Meta Protocol ──
    # Runs BEFORE HyperClaw so it can use its priority_axes assessment.
    # (OpenClaw was moved to step 3.5 to run before token budget is depleted.)
    try:
        from core.cortex_orchestrator import run as _orchestrate
        _orchestrate()
        print("[FAST_CYCLE] cortex_orchestrator -> OK")
    except Exception as e:
        print(f"[FAST_CYCLE] cortex_orchestrator -> FAILED: {e}")

    # ── 13. Body scan ──
    _run("body_scanner", lambda: __import__(
        "agents.body.body_scanner", fromlist=["run"]).run())

    # ── 14. Growth planner ──
    _run("growth_planner", lambda: __import__(
        "agents.body.growth_planner", fromlist=["run"]).run())

    # ── 15.6. HyperClaw — multi-axis 24-72h plan ──
    _run("hyperclaw_orchestrator", lambda: __import__(
        "agents.hyperclaw.hyperclaw_orchestrator", fromlist=["main"]).main(), free_after=True)

    # ── 15.7. HyperClaw plan → improvement proposals ──
    _hyperclaw_to_proposals()

    # ── 15.8. GitHub publish — cycle synthesis + verified hypotheses ──
    try:
        from github_publisher import publish_synthesis as _gh_publish
        _gh_publish()
        print("[FAST_CYCLE] github_publisher -> OK")
    except Exception as e:
        print(f"[FAST_CYCLE] github_publisher -> FAILED: {e}")

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

    # ── 21. Session update ──
    try:
        from core.session_updater import update as _update
        _update()
        print("[FAST_CYCLE] session_updater -> OK")
    except Exception as e:
        print(f"[SESSION] Грешка: {e}")

    # ── 22. Daily analysis ──
    _run("daily_analysis", lambda: __import__(
        "agents.core.daily_analysis_agent", fromlist=["main"]).main())

    # ── 22.5. Data Scout — автономно търсене на нови реални данни ──
    # Пуска се ПОСЛЕДНО — не се бие с основния цикъл за LLM rate limit.
    # Кешира предложенията; пита LLM само когато ги няма или са >7 дни.
    try:
        from core.data_scout import run as _scout_run
        scout_summary = _scout_run(max_axes=2)
        print(
            f"[FAST_CYCLE] data_scout -> "
            f"scanned={scout_summary.get('scanned',0)} | "
            f"validated={scout_summary.get('validated',0)} new sources"
        )
    except Exception as e:
        print(f"[FAST_CYCLE] data_scout -> FAILED: {e}")

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

    # ── 24. MerkleMemory commit ──
    try:
        import asyncio
        import re as _re
        from merkle_memory import MerkleMemory

        # signals — parse from auto_levels details: "metric=value → LEVEL"
        _signals = []
        for _axis, _info in levels.items():
            if not isinstance(_info, dict):
                continue
            for _detail in _info.get("details", []):
                _m = _re.match(r"([\w]+)=([-\d.]+)", _detail)
                if _m:
                    _signals.append({
                        "metric":   _m.group(1),
                        "value":    float(_m.group(2)),
                        "domain":   _axis,
                        "source":   _info.get("source", "auto_level"),
                        "category": "CIVILIZATION",
                    })

        # decisions — improvement_proposals.json (written by openclaw/hyperclaw, steps 15.5/15.7)
        _decisions = []
        try:
            _raw = json.loads((BASE / "memory" / "improvement_proposals.json").read_text(encoding="utf-8"))
            _decisions = (_raw.get("proposals", _raw) if isinstance(_raw, dict) else _raw)[:30]
        except Exception:
            pass

        # results — today's patch executions from development_journal.json (written by execute_patches, step 19)
        _patch_results = []
        try:
            _journal = json.loads((BASE / "memory" / "development_journal.json").read_text(encoding="utf-8"))
            _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _patch_results = _journal.get(_today, {}).get("patch_executions", [])
        except Exception:
            pass

        asyncio.run(MerkleMemory().commit(
            cycle_id  = _utc_now(),
            signals   = _signals,
            decisions = _decisions,
            results   = _patch_results,
            goal_score = float(composite),
        ))
        print(f"[FAST_CYCLE] MerkleMemory -> committed | signals={len(_signals)} decisions={len(_decisions)} results={len(_patch_results)} goal={composite:.4f}")
    except Exception as e:
        print(f"[FAST_CYCLE] MerkleMemory -> FAILED: {e}")

    # ── 25. Training data accumulation ──
    # Runs AFTER MerkleMemory commit (step 24) so the archive entry exists.
    try:
        from merkle_to_training import append_latest_cycle as _append_training
        if _append_training():
            print("[FAST_CYCLE] merkle_to_training -> appended latest cycle")
        else:
            print("[FAST_CYCLE] merkle_to_training -> already processed or no archive")
    except Exception as e:
        print(f"[FAST_CYCLE] merkle_to_training -> FAILED: {e}")

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