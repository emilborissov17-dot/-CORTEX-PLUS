#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cortex_proposal_executor.py
Валидира → alignment чек → изпълнява → записва резултат
ФИКС: fail-closed fallback, urllib разрешен, mission_filter интегриран
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List

BASE_DIR = pathlib.Path(__file__).resolve().parent
PROPOSALS_FILE = BASE_DIR / "memory" / "improvement_proposals.json"
EXECUTION_LOG = BASE_DIR / "memory" / "proposal_execution_log.json"
PATCHES_DIR = BASE_DIR / "agents" / "core"

# urllib е легитимен за predictor — само os.system и eval са опасни
BANNED_IMPORTS = [
    "os.system", "shutil.rmtree",
    "__import__", "eval(", "exec(",
    "socket.connect", "socket.bind",
]

# ФИКС: fail-closed — ако guard липсва, блокира всичко
try:
    from alignment.civilization_guard import evaluate_proposal_alignment
    _GUARD_LOADED = True
except Exception as e:
    _GUARD_LOADED = False
    def evaluate_proposal_alignment(proposal: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "allowed": False,
            "risk_score": 1.0,
            "notes": f"alignment_guard_missing_FAIL_CLOSED: {e}",
        }

# Mission filter (опционален, не блокира ако липсва)
try:
    from alignment.mission_filter import filter_proposal as _mission_filter
    def check_mission(proposal):
        return _mission_filter(proposal)
except Exception:
    def check_mission(proposal):
        return {"allowed": True, "mission_score": None, "notes": "mission_filter_not_loaded"}


def _validate_python_code(code: str) -> tuple[bool, str]:
    if not code or len(code.strip()) < 10:
        return False, "Кодът е твърде кратък"
    for banned in BANNED_IMPORTS:
        if banned in code:
            return False, f"Забранена операция: {banned}"
    return True, "OK"


def _validate_proposal(proposal: Dict) -> tuple[bool, str]:
    if not proposal.get("component"):
        return False, "Липсва component"
    if not proposal.get("problem"):
        return False, "Липсва problem описание"
    if not proposal.get("python_code") and not proposal.get("target_file"):
        return False, "Няма нито python_code нито target_file"
    return True, "OK"


def _inject_base_dir(code: str) -> str:
    base_str = str(BASE_DIR).replace("\\", "/")
    for n in range(5):
        code = code.replace(
            f"pathlib.Path(__file__).resolve().parents[{n}]",
            f'pathlib.Path(r"{base_str}")'
        )
    if "BASE = " not in code and "BASE_DIR = " not in code:
        code = f'import pathlib\nBASE = pathlib.Path(r"{base_str}")\n' + code
    return code


def execute_python_code(proposal: Dict) -> Dict[str, Any]:
    code = proposal.get("python_code", "")
    valid, reason = _validate_python_code(code)
    if not valid:
        return {"status": "skipped", "reason": reason}

    code = _inject_base_dir(code)

    target = proposal.get("target_file")
    if target:
        patch_path = BASE_DIR / target
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            patch_path.write_text(code, encoding="utf-8")
        except Exception as e:
            return {"status": "error", "reason": f"write_failed: {e}"}

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=60, cwd=str(BASE_DIR),
        )
        pathlib.Path(tmp_path).unlink(missing_ok=True)

        status = "ok" if result.returncode == 0 else "error"
        return {
            "status": status,
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[:4000],
            "stderr": (result.stderr or "")[:4000],
        }
    except Exception as e:
        return {"status": "error", "reason": f"subprocess_failed: {e}"}


def execute_description_only(proposal: Dict) -> Dict[str, Any]:
    pending_file = BASE_DIR / "memory" / "pending_tasks.json"
    try:
        try:
            data = json.loads(pending_file.read_text(encoding="utf-8"))
            tasks = data.get("tasks", [])
        except Exception:
            tasks = []
        tasks.append({
            "component": proposal.get("component"),
            "problem": proposal.get("problem"),
            "solution": proposal.get("solution"),
            "priority": proposal.get("priority", "MEDIUM"),
            "added_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        })
        pending_file.write_text(
            json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return {"status": "queued", "reason": "Добавено в pending_tasks.json"}
    except Exception as e:
        return {"status": "error", "reason": f"pending_write_failed: {e}"}


def load_proposals() -> List[Dict]:
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding="utf-8"))
        return data.get("proposals", [])
    except Exception:
        return []


def save_execution_log(log_entries: List[Dict]) -> None:
    try:
        try:
            existing = json.loads(EXECUTION_LOG.read_text(encoding="utf-8"))
            all_logs = existing if isinstance(existing, list) else []
        except Exception:
            all_logs = []
        all_logs.extend(log_entries)
        all_logs = all_logs[-200:]
        EXECUTION_LOG.write_text(
            json.dumps(all_logs, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[EXECUTOR] Грешка при запис на лог: {e}")


def run() -> None:
    print("\n[EXECUTOR] ══════════════════════════════════")
    print(f"[EXECUTOR] guard_loaded={_GUARD_LOADED}")
    print("[EXECUTOR] ══════════════════════════════════\n")

    proposals = load_proposals()
    if not proposals:
        print("[EXECUTOR] Няма proposals.")
        return

    log_entries: List[Dict[str, Any]] = []

    for i, proposal in enumerate(proposals):
        if not proposal.get("approved"):
            print(f"[EXECUTOR] [{i+1}] ⏳ Чака одобрение: {proposal.get('component','?')}")
            continue

        component = proposal.get("component", "unknown")
        problem = proposal.get("problem", "")[:60]
        print(f"[EXECUTOR] [{i+1}] {component}: {problem}")

        # Стъпка 1: структурна валидация
        valid, reason = _validate_proposal(proposal)
        if not valid:
            print(f"  ⚠️  Невалиден: {reason}")
            log_entries.append({"index": i, "component": component,
                "status": "invalid", "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat()})
            continue

        # Стъпка 2: civilization alignment (FAIL-CLOSED)
        align = evaluate_proposal_alignment(proposal)
        if not align.get("allowed", False):
            print(f"  ❌ alignment_blocked: risk={align.get('risk_score',1):.2f} | {align.get('notes','')[:80]}")
            log_entries.append({"index": i, "component": component,
                "problem": problem, "result": {"status": "blocked_alignment"},
                "alignment": align, "timestamp": datetime.now(timezone.utc).isoformat()})
            continue

        # Стъпка 3: mission filter
        mission = check_mission(proposal)
        if not mission.get("allowed", True):
            print(f"  ❌ mission_blocked: {mission.get('notes','')[:80]}")
            log_entries.append({"index": i, "component": component,
                "problem": problem, "result": {"status": "blocked_mission"},
                "mission": mission, "timestamp": datetime.now(timezone.utc).isoformat()})
            continue

        # Стъпка 4: изпълнение
        try:
            if proposal.get("python_code"):
                result = execute_python_code(proposal)
            else:
                result = execute_description_only(proposal)
        except Exception:
            traceback.print_exc()
            result = {"status": "error", "reason": "uncaught_exception"}

        status = result.get("status", "unknown")
        icon = "✅" if status == "ok" else "🟡" if status in ("skipped", "queued") else "❌"
        reason_text = result.get("reason") or result.get("stderr", "")[:160] or "(няма детайли)"
        print(f"  {icon} {status}: {reason_text[:160]}")

        log_entries.append({
            "index": i, "component": component, "problem": problem,
            "result": result, "alignment": align, "mission": mission,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    save_execution_log(log_entries)

    ok      = sum(1 for e in log_entries if e.get("result", {}).get("status") == "ok")
    queued  = sum(1 for e in log_entries if e.get("result", {}).get("status") == "queued")
    blocked = sum(1 for e in log_entries if "blocked" in e.get("result", {}).get("status", ""))
    errors  = sum(1 for e in log_entries if e.get("result", {}).get("status") == "error")

    print(f"\n[EXECUTOR] ✅ OK:{ok} | 🟡 Queued:{queued} | ❌ Blocked:{blocked} | Error:{errors}")
    print("[EXECUTOR] ══════════════════════════════════\n")


if __name__ == "__main__":
    run()
