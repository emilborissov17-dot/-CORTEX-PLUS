#!/usr/bin/env python3
"""
agents/openclaw_bridge.py
OpenClaw Phase 0 — policy gate + audit-first bridge skeleton.

Single entry point (`submit_action`) between CORTEX++ domain agents and the
external OpenClaw gateway. Per docs/OPENCLAW_INTEGRATION_DESIGN.md:

  (a) Hard JSON policy match — classify() is a pure allowlist membership
      lookup against config/openclaw_action_policy.json. No LLM, no
      substring/fuzzy matching. always_blocked is checked first, before
      level_1/2/3. Fail-closed: a missing/corrupt policy file classifies
      EVERY action as level_3 (never auto-blocked, never auto-allowed).

  (b) Log-then-act — submit_action() writes the audit record to
      memory/openclaw_audit_log.json BEFORE any branch (blocked / level_3
      queue / dry_run / execute) runs. That file is later folded into the
      `decisions` list a cycle hands to MerkleMemory().commit() — same
      pattern as safety/quarantine.py's development_journal.json logging.
      MerkleMemory.commit() itself is a once-per-cycle batch archive, not
      something called per individual action.

  (c) dry_run=True default — _execute() is only reachable when dry_run is
      explicitly False AND the verdict is level_1 or level_2. level_3 and
      blocked actions never reach _execute regardless of dry_run.

Phase 0 has NO real execution capability: _execute() is a stub that raises
NotImplementedError. Wiring an actual OpenClaw gateway call is a later phase.
"""
import json
import pathlib
import uuid
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = BASE_DIR / "config" / "openclaw_action_policy.json"
AUDIT_LOG_PATH = BASE_DIR / "memory" / "openclaw_audit_log.json"
PENDING_L3_PATH = BASE_DIR / "memory" / "openclaw_pending_l3.json"


def load_policy(policy_path: pathlib.Path = POLICY_PATH) -> dict | None:
    """Fail-closed JSON policy load.

    Returns None if the file is missing or not valid JSON — callers must
    treat None as "classify everything as level_3", never as "allow".
    """
    try:
        return json.loads(pathlib.Path(policy_path).read_text(encoding="utf-8"))
    except Exception:
        return None


def classify(action_type: str, policy_path: pathlib.Path = POLICY_PATH) -> str:
    """Pure allowlist membership lookup. Returns one of:
    "blocked", "level_1", "level_2", "level_3".

    Order matters: always_blocked is checked first, unconditionally, before
    any level_1/2/3 membership — an action_type present in always_blocked
    can never be reclassified as autonomous by also appearing elsewhere.
    """
    policy = load_policy(policy_path)
    if policy is None:
        return "level_3"

    if action_type in policy.get("always_blocked", {}).get("action_types", []):
        return "blocked"
    if action_type in policy.get("level_1", {}).get("action_types", []):
        return "level_1"
    if action_type in policy.get("level_2", {}).get("action_types", []):
        return "level_2"
    if action_type in policy.get("level_3", {}).get("action_types", []):
        return "level_3"
    return policy.get("default_unclassified", "level_3")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_audit_id() -> str:
    return f"oc_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _append_json_list(path: pathlib.Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    data.append(record)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_audit_status(audit_path: pathlib.Path, audit_id: str, **fields) -> None:
    try:
        log = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return
    for rec in log:
        if rec.get("audit_id") == audit_id:
            rec.update(fields)
            break
    audit_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _execute(task: dict, verdict: str):
    """Phase 0 stub — no execution capability exists yet.

    Reaching this function is only possible for level_1/level_2 verdicts
    with dry_run=False; level_3 and blocked verdicts return before ever
    calling it. Raises unconditionally until a later phase wires a real
    OpenClaw gateway call.
    """
    raise NotImplementedError(
        "OpenClaw Phase 0 has no execution capability — "
        f"_execute() must not be called (action_type={task.get('action_type')!r}, verdict={verdict!r})"
    )


def submit_action(
    task: dict,
    dry_run: bool = True,
    policy_path: pathlib.Path = POLICY_PATH,
    audit_path: pathlib.Path = AUDIT_LOG_PATH,
    pending_path: pathlib.Path = PENDING_L3_PATH,
) -> dict:
    """Single entry point for any OpenClaw action request.

    task must contain "action_type". Log-then-act: the audit record is
    written to disk before any of the branches below (blocked / level_3
    queue / dry_run / execute) runs — never after.
    """
    action_type = task.get("action_type")
    verdict = classify(action_type, policy_path=policy_path)

    audit_id = _new_audit_id()
    record = {
        "audit_id": audit_id,
        "timestamp_utc": _now_iso(),
        "action_type": action_type,
        "autonomy_level": verdict,
        "dry_run": dry_run,
        "status": "pending",
        "task": task,
    }
    _append_json_list(audit_path, record)

    if verdict == "blocked":
        _update_audit_status(audit_path, audit_id, status="blocked")
        return {"executed": False, "status": "blocked", "audit_id": audit_id}

    if verdict == "level_3":
        _append_json_list(pending_path, {
            "audit_id": audit_id,
            "task": task,
            "submitted_at": record["timestamp_utc"],
            "status": "awaiting_approval",
        })
        _update_audit_status(audit_path, audit_id, status="awaiting_approval")
        return {"executed": False, "status": "awaiting_approval", "audit_id": audit_id}

    # verdict is level_1 or level_2 from here on
    if dry_run:
        _update_audit_status(audit_path, audit_id, status="validated_not_executed")
        return {"executed": False, "status": "dry_run", "would_run_as": verdict, "audit_id": audit_id}

    try:
        result = _execute(task, verdict)
    except Exception as e:
        _update_audit_status(audit_path, audit_id, status="error", error=str(e))
        raise

    _update_audit_status(audit_path, audit_id, status="completed")
    return {"executed": True, "status": "completed", "result": result, "audit_id": audit_id}
