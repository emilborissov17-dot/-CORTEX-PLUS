#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import pathlib
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.groq_backend import call_groq

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

ACTIONS_PLAN_PATH = REPORTS_DIR / "actions_plan_latest.json"
ACTIONS_LOG_PATH = REPORTS_DIR / "actions_run_log.json"

# Whitelists / safety
ALLOWED_SCRIPTS = {
    "fast_cycle_runner.py",
    "run_daily.py",
    "cortex_scan.py",
    "hypercortex_runner.py",
}

ALLOWED_CONFIGS = {
    "config/config_fresco_agent.json",
    "config/config_planet.json",
    "config/config_civilization.json",
}

ALLOWED_REFACTOR_TARGETS = {
    "hypercortex_runner.py",
    "agents/planet/planet_snapshot_agent_qwen.py",
    "agents/civilization/civilization_snapshot_agent_qwen.py",
}

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _strip_markdown_code(text: str) -> str:
    """
    Премахва markdown code fences (```python ... ``` или ``` ... ```)
    от LLM output, за да остане само валиден Python код.
    """
    # Премахни ```python ... ``` или ``` ... ```
    pattern = r"^```(?:python)?\s*\n?(.*?)\n?```\s*$"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Ако няма fences, върни оригинала
    return text.strip()


# ---------- LLM helper (Groq → Gemini → Ollama fallback chain) ----------

def call_llm_refactor(prompt: str, max_tokens: int = 4096) -> str:
    return call_groq(prompt, max_tokens=max_tokens)


# ---------- Actions: run_script / modify_config / llm_refactor ----------

def _run_script(action: Dict[str, Any]) -> Dict[str, Any]:
    cmd = action.get("command")
    cwd = action.get("cwd", ".")
    if not isinstance(cmd, list) or not cmd:
        return {"status": "error", "reason": "invalid_command"}

    script = cmd[-1]
    script_name = pathlib.Path(script).name
    if script_name not in ALLOWED_SCRIPTS:
        return {"status": "skipped", "reason": f"script_not_whitelisted: {script_name}"}

    try:
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR if cwd == "." else BASE_DIR / cwd),
            capture_output=True,
            text=True,
            timeout=600,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def _apply_changes(obj: Any, changes: Dict[str, Any]) -> Any:
    if isinstance(obj, dict):
        for k, v in changes.items():
            obj[k] = v
    return obj


def _modify_config(action: Dict[str, Any]) -> Dict[str, Any]:
    rel_path = action.get("config_path")
    if not isinstance(rel_path, str):
        return {"status": "error", "reason": "invalid_config_path"}

    if rel_path not in ALLOWED_CONFIGS:
        return {"status": "skipped", "reason": f"config_not_whitelisted: {rel_path}"}

    cfg_path = BASE_DIR / rel_path
    backup_enabled = bool(action.get("backup", True))
    changes = action.get("changes", {})

    if not isinstance(changes, dict):
        return {"status": "error", "reason": "invalid_changes"}

    if not cfg_path.exists():
        return {"status": "error", "reason": f"config_not_found: {rel_path}"}

    try:
        original_text = cfg_path.read_text(encoding="utf-8")
        data = json.loads(original_text)
    except Exception as e:
        return {"status": "error", "reason": f"json_load_failed: {e}"}

    if backup_enabled:
        backup_path = cfg_path.with_suffix(
            cfg_path.suffix + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        try:
            shutil.copy2(str(cfg_path), str(backup_path))
        except Exception as e:
            return {"status": "error", "reason": f"backup_failed: {e}"}

    try:
        new_data = _apply_changes(data, changes)
        cfg_path.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "reason": f"write_failed: {e}"}


def _llm_refactor(action: Dict[str, Any]) -> Dict[str, Any]:
    rel_path = action.get("target_path")
    if not isinstance(rel_path, str):
        return {"status": "error", "reason": "invalid_target_path"}

    if rel_path not in ALLOWED_REFACTOR_TARGETS:
        return {"status": "skipped", "reason": f"target_not_whitelisted: {rel_path}"}

    instructions = action.get("instructions") or "Improve structure and readability without changing behavior."
    max_tokens = int(action.get("max_tokens", 4096))
    backup_enabled = bool(action.get("backup", True))

    file_path = BASE_DIR / rel_path
    if not file_path.exists():
        return {"status": "error", "reason": f"target_not_found: {rel_path}"}

    try:
        original_code = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"status": "error", "reason": f"read_failed: {e}"}

    backup_path = None
    if backup_enabled:
        backup_path = file_path.with_suffix(
            file_path.suffix + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        try:
            shutil.copy2(str(file_path), str(backup_path))
        except Exception as e:
            return {"status": "error", "reason": f"backup_failed: {e}"}

    prompt = (
        "You are a precise Python code refactoring engine.\n"
        "Refactor the following code.\n"
        "Requirements:\n"
        "- Preserve behavior exactly.\n"
        "- Improve structure, readability, and modularity.\n"
        "- Do NOT add comments about what you did.\n"
        "- Return ONLY valid Python code, no markdown, no explanations.\n\n"
        "Additional instructions:\n"
        f"{instructions}\n\n"
        "CODE START\n"
        f"{original_code}\n"
        "CODE END\n"
    )

    try:
        raw_output = call_llm_refactor(prompt=prompt, max_tokens=max_tokens)
    except Exception as e:
        return {"status": "error", "reason": f"llm_call_failed: {e}"}

    # Премахни markdown code fences ако LLM ги е добавил
    new_code = _strip_markdown_code(raw_output)

    if not new_code or len(new_code.strip()) < len(original_code) * 0.3:
        return {"status": "error", "reason": "suspicious_output_too_short"}

    try:
        file_path.write_text(new_code, encoding="utf-8")
    except Exception as e:
        return {"status": "error", "reason": f"write_failed: {e}"}

    return {
        "status": "ok",
        "backup_path": str(backup_path) if backup_path else None,
        "bytes_before": len(original_code.encode("utf-8")),
        "bytes_after": len(new_code.encode("utf-8")),
    }


# ---------- Main run loop ----------

def run_actions() -> None:
    print("[ACTIONS] HyperCortex actions agent starting...")
    plan = _load_json(ACTIONS_PLAN_PATH)
    if not plan:
        print(f"[ACTIONS] No plan found at {ACTIONS_PLAN_PATH}")
        return

    actions = plan.get("actions") or []
    if not isinstance(actions, list) or not actions:
        print("[ACTIONS] No actions in plan.")
        return

    log_entry = {
        "run_at": _utc_now(),
        "plan_file": str(ACTIONS_PLAN_PATH),
        "actions": [],
    }

    for action in actions:
        try:
            if not isinstance(action, dict):
                continue
            if not action.get("enabled", True):
                log_entry["actions"].append({
                    "id": action.get("id"),
                    "type": action.get("type"),
                    "status": "skipped",
                    "reason": "disabled",
                })
                continue

            a_type = action.get("type")
            if a_type == "run_script":
                res = _run_script(action)
            elif a_type == "modify_config":
                res = _modify_config(action)
            elif a_type == "llm_refactor":
                res = _llm_refactor(action)
            else:
                res = {"status": "skipped", "reason": f"unknown_type: {a_type}"}

            log_entry["actions"].append({
                "id": action.get("id"),
                "type": a_type,
                "result": res,
            })
            print(f"[ACTIONS] {action.get('id')} -> {res.get('status')}")
        except Exception as e:
            log_entry["actions"].append({
                "id": action.get("id"),
                "type": action.get("type"),
                "status": "error",
                "reason": str(e),
            })
            print(f"[ACTIONS] {action.get('id')} -> error: {e}")

    existing_log = _load_json(ACTIONS_LOG_PATH)
    if not isinstance(existing_log, list):
        existing_log = []
    existing_log.append(log_entry)
    _save_json(ACTIONS_LOG_PATH, existing_log)
    print("[ACTIONS] Done.")


if __name__ == "__main__":
    run_actions()