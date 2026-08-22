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

  (d) Per-action PARAMETER SCHEMAS, checked before classification. classify()
      only ever looked at action_type — a string. Everything else in the task
      dict travelled untouched, so "web_fetch_get" carrying
      {"url": "__import__('os').system('calc')"} was classified level_1 on the
      strength of its label while the payload rode along unread. Phase 0 could
      not execute it, which made the hole invisible rather than absent.

      config/openclaw_action_schemas.json holds one JSON Schema (Draft 2020-12)
      per action_type, validated by validate_parameters(). Every string pattern
      is an ALLOWLIST of the characters that field legitimately needs, never a
      blocklist of attack strings: a blocklist of "__import__" loses to the next
      payload, whereas a path pattern permitting only [A-Za-z0-9_./-] refuses
      that payload for its quotes and parentheses and refuses the next one too.
      additionalProperties is false everywhere, so an unknown field is refused
      rather than ignored.

      THE ORDER IS PART OF THE CONTRACT:

          1. always_blocked   — first, unconditionally. A blocked action stays
                                blocked even if its parameters are malformed;
                                "your payload was invalid" is a softer answer
                                than "this action may never run", and the harder
                                answer must win.
          2. schema           — refused actions never reach classification, so a
                                malformed payload can never be handed a level.
          3. policy match     — the pure allowlist lookup, fail-closed level_3.

      An action_type with no schema entry falls to "_default", which permits NO
      parameters at all. Fail-closed by construction: a new action type must
      have a schema written for it, in a commit, before it can carry data.
"""
import json
import pathlib
import uuid
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = BASE_DIR / "config" / "openclaw_action_policy.json"
SCHEMA_PATH = BASE_DIR / "config" / "openclaw_action_schemas.json"
AUDIT_LOG_PATH = BASE_DIR / "memory" / "openclaw_audit_log.json"
PENDING_L3_PATH = BASE_DIR / "memory" / "openclaw_pending_l3.json"

REFUSED_SCHEMA = "refused_schema"


def load_policy(policy_path: pathlib.Path = POLICY_PATH) -> dict | None:
    """Fail-closed JSON policy load.

    Returns None if the file is missing or not valid JSON — callers must
    treat None as "classify everything as level_3", never as "allow".
    """
    try:
        return json.loads(pathlib.Path(policy_path).read_text(encoding="utf-8"))
    except Exception:
        return None


def is_always_blocked(action_type: str, policy_path: pathlib.Path = POLICY_PATH) -> bool:
    """The first question asked about any action, before anything else runs.

    Split out of classify() so submit_action() can ask it BEFORE schema
    validation. A blocked action must stay blocked even when its parameters are
    also malformed: "your payload was invalid" invites a corrected retry, and
    "this action may never run" does not.

    Fail-closed: an unreadable policy is not a licence. It returns False here
    because classify() will then send everything to level_3 anyway — no path
    reaches execution on a missing policy.
    """
    policy = load_policy(policy_path)
    if policy is None:
        return False
    return action_type in policy.get("always_blocked", {}).get("action_types", [])


def load_schemas(schema_path: pathlib.Path = SCHEMA_PATH) -> dict | None:
    """Fail-closed schema load. None means "refuse anything with parameters"."""
    try:
        blob = json.loads(pathlib.Path(schema_path).read_text(encoding="utf-8"))
        return blob if isinstance(blob, dict) else None
    except Exception:
        return None


def validate_parameters(action_type: str, parameters: dict,
                        schema_path: pathlib.Path = SCHEMA_PATH) -> tuple[bool, str | None]:
    """(ok, reason). Runs BEFORE classification — see the module docstring.

    A missing or corrupt schema file refuses every action that carries
    parameters and lets parameterless ones through to classification, which is
    itself fail-closed. That is deliberately not "refuse everything": a deleted
    config file would then be a way to take the bridge down, and the policy gate
    already answers level_3 to anything it cannot vouch for.
    """
    params = parameters if isinstance(parameters, dict) else None
    if params is None:
        return False, "parameters must be a JSON object, got {}".format(
            type(parameters).__name__)

    blob = load_schemas(schema_path)
    if blob is None:
        if params:
            return False, ("schema file is missing or unreadable and this action "
                           "carries parameters — refused rather than guessed")
        return True, None

    schemas = blob.get("schemas") or {}
    schema = schemas.get(action_type, blob.get("_default"))
    if schema is None:
        return False, "no schema and no _default for {!r}".format(action_type)

    try:
        import jsonschema                                    # noqa: PLC0415
    except ImportError:
        # The validator itself is missing. Refuse anything carrying data rather
        # than wave it through unvalidated; an unchecked payload is the exact
        # thing this function exists to stop.
        if params:
            return False, "jsonschema is not installed — parameters cannot be validated"
        return True, None

    try:
        jsonschema.validate(instance=params, schema=schema)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        return False, "{}: {}".format(where, e.message)
    except jsonschema.SchemaError as e:
        return False, "the schema for {!r} is itself invalid: {}".format(
            action_type, e.message)
    return True, None


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
    schema_path: pathlib.Path = SCHEMA_PATH,
) -> dict:
    """Single entry point for any OpenClaw action request.

    task must contain "action_type"; its parameters live under "parameters".
    Log-then-act: the audit record is written to disk before any of the branches
    below (blocked / schema-refused / level_3 queue / dry_run / execute) runs —
    never after.

    The three checks happen in the order the docstring fixes — always_blocked,
    then schema, then policy — and only then is anything written or branched on.
    Deciding before logging is not a violation of log-then-act: what that rule
    protects is that no ACTION is taken without a record, and the record below is
    written before the first branch.
    """
    action_type = task.get("action_type")

    # 1. always_blocked, unconditionally first.
    blocked = is_always_blocked(action_type, policy_path=policy_path)

    # 2. schema — but only if the action was not already blocked. A blocked
    #    action must not be re-labelled "your payload was invalid".
    schema_ok, schema_reason = (True, None) if blocked else validate_parameters(
        action_type, task.get("parameters") or {}, schema_path=schema_path)

    # 3. the policy lookup, fail-closed level_3. Never reached by a refused
    #    payload: a malformed action is not handed an autonomy level at all.
    if blocked:
        verdict = "blocked"
    elif not schema_ok:
        verdict = REFUSED_SCHEMA
    else:
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
    if verdict == REFUSED_SCHEMA:
        record["schema_error"] = schema_reason
    _append_json_list(audit_path, record)

    if verdict == "blocked":
        _update_audit_status(audit_path, audit_id, status="blocked")
        return {"executed": False, "status": "blocked", "audit_id": audit_id}

    if verdict == REFUSED_SCHEMA:
        _update_audit_status(audit_path, audit_id, status=REFUSED_SCHEMA,
                             schema_error=schema_reason)
        return {"executed": False, "status": REFUSED_SCHEMA,
                "reason": schema_reason, "audit_id": audit_id}

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
