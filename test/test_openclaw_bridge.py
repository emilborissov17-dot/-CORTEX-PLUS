"""Tests for agents/openclaw_bridge.py (OpenClaw Phase 0).

Every test passes explicit tmp_path-derived policy_path/audit_path/
pending_path arguments — none of them touch the real repo's
config/openclaw_action_policy.json or memory/openclaw_*.json.
"""
import json

import pytest

from agents.openclaw_bridge import classify, submit_action

REAL_POLICY = {
    "version": 2,
    "default_unclassified": "level_3",
    "level_1": {"action_types": ["web_fetch_get"]},
    "level_2": {"action_types": ["write_data_file"]},
    "level_3": {"action_types": ["send_email"]},
    "always_blocked": {"action_types": ["execute_arbitrary_shell"]},
}


def _write_policy(tmp_path, policy: dict, name="policy.json"):
    path = tmp_path / name
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def test_always_blocked_wins_over_everything(tmp_path):
    # deliberately duplicate the same action_type in level_1 AND always_blocked
    # to prove always_blocked is checked first and cannot be overridden.
    conflicting_policy = {
        "default_unclassified": "level_3",
        "level_1": {"action_types": ["dangerous_action"]},
        "level_2": {"action_types": []},
        "level_3": {"action_types": []},
        "always_blocked": {"action_types": ["dangerous_action"]},
    }
    policy_path = _write_policy(tmp_path, conflicting_policy)
    assert classify("dangerous_action", policy_path=policy_path) == "blocked"


def test_unclassified_action_type_falls_to_level_3(tmp_path):
    policy_path = _write_policy(tmp_path, REAL_POLICY)
    assert classify("citation_link_liveness_check", policy_path=policy_path) == "level_3"
    assert classify("axis_data_source_fetch", policy_path=policy_path) == "level_3"
    assert classify("rss_headline_scan", policy_path=policy_path) == "level_3"


def test_missing_policy_file_classifies_everything_level_3(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    assert classify("web_fetch_get", policy_path=missing_path) == "level_3"
    assert classify("execute_arbitrary_shell", policy_path=missing_path) == "level_3"
    assert classify("send_email", policy_path=missing_path) == "level_3"


def test_corrupt_policy_file_classifies_everything_level_3(tmp_path):
    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not valid json", encoding="utf-8")
    assert classify("web_fetch_get", policy_path=corrupt_path) == "level_3"
    assert classify("execute_arbitrary_shell", policy_path=corrupt_path) == "level_3"


def test_dry_run_never_executes(tmp_path, monkeypatch):
    import agents.openclaw_bridge as bridge

    calls = []
    monkeypatch.setattr(bridge, "_execute", lambda task, verdict: calls.append((task, verdict)))

    policy_path = _write_policy(tmp_path, REAL_POLICY)
    result = submit_action(
        {"action_type": "web_fetch_get"},
        dry_run=True,
        policy_path=policy_path,
        audit_path=tmp_path / "audit.json",
        pending_path=tmp_path / "pending.json",
    )

    assert result["executed"] is False
    assert result["status"] == "dry_run"
    assert calls == []


def test_dry_run_false_on_level_1_reaches_execute_stub(tmp_path, monkeypatch):
    import agents.openclaw_bridge as bridge

    calls = []
    monkeypatch.setattr(bridge, "_execute", lambda task, verdict: calls.append((task, verdict)) or "ok")

    policy_path = _write_policy(tmp_path, REAL_POLICY)
    result = submit_action(
        {"action_type": "web_fetch_get"},
        dry_run=False,
        policy_path=policy_path,
        audit_path=tmp_path / "audit.json",
        pending_path=tmp_path / "pending.json",
    )

    assert result["executed"] is True
    assert calls == [({"action_type": "web_fetch_get"}, "level_1")]


def test_level_3_never_reaches_execute_even_with_dry_run_false(tmp_path, monkeypatch):
    import agents.openclaw_bridge as bridge

    calls = []
    monkeypatch.setattr(bridge, "_execute", lambda task, verdict: calls.append((task, verdict)))

    policy_path = _write_policy(tmp_path, REAL_POLICY)
    audit_path = tmp_path / "audit.json"
    pending_path = tmp_path / "pending.json"

    result = submit_action(
        {"action_type": "send_email", "to": "someone@example.com"},
        dry_run=False,
        policy_path=policy_path,
        audit_path=audit_path,
        pending_path=pending_path,
    )

    assert result["executed"] is False
    assert result["status"] == "awaiting_approval"
    assert calls == []

    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert len(pending) == 1
    assert pending[0]["task"]["action_type"] == "send_email"


def test_blocked_never_reaches_execute_even_with_dry_run_false(tmp_path, monkeypatch):
    import agents.openclaw_bridge as bridge

    calls = []
    monkeypatch.setattr(bridge, "_execute", lambda task, verdict: calls.append((task, verdict)))

    policy_path = _write_policy(tmp_path, REAL_POLICY)
    result = submit_action(
        {"action_type": "execute_arbitrary_shell", "cmd": "rm -rf /"},
        dry_run=False,
        policy_path=policy_path,
        audit_path=tmp_path / "audit.json",
        pending_path=tmp_path / "pending.json",
    )

    assert result["executed"] is False
    assert result["status"] == "blocked"
    assert calls == []


def test_audit_record_exists_before_any_status_change(tmp_path, monkeypatch):
    """Proves log-then-act ordering: by the time _execute (or the blocked/
    level_3 branch) runs, the audit record already exists on disk with its
    initial "pending" status — logging happens strictly before acting."""
    import agents.openclaw_bridge as bridge

    audit_path = tmp_path / "audit.json"
    policy_path = _write_policy(tmp_path, REAL_POLICY)
    seen_status_at_execute_time = []

    def fake_execute(task, verdict):
        log = json.loads(audit_path.read_text(encoding="utf-8"))
        seen_status_at_execute_time.append(log[-1]["status"])
        return "ok"

    monkeypatch.setattr(bridge, "_execute", fake_execute)

    submit_action(
        {"action_type": "web_fetch_get"},
        dry_run=False,
        policy_path=policy_path,
        audit_path=audit_path,
        pending_path=tmp_path / "pending.json",
    )

    # the audit record was already written (status="pending") before
    # _execute ran, proving the log write happened before the act.
    assert seen_status_at_execute_time == ["pending"]

    # and after submit_action returns, the same record has been updated
    # to a terminal status — the log is never left stale.
    final_log = json.loads(audit_path.read_text(encoding="utf-8"))
    assert final_log[-1]["status"] == "completed"


def test_execute_stub_raises_not_implemented_when_actually_reached(tmp_path):
    """Phase 0 ships zero real execution capability: _execute() itself
    must raise, and submit_action must propagate that (not swallow it)."""
    policy_path = _write_policy(tmp_path, REAL_POLICY)
    audit_path = tmp_path / "audit.json"

    with pytest.raises(NotImplementedError):
        submit_action(
            {"action_type": "web_fetch_get"},
            dry_run=False,
            policy_path=policy_path,
            audit_path=audit_path,
            pending_path=tmp_path / "pending.json",
        )

    # the audit record still reflects the failure, not "pending" forever
    log = json.loads(audit_path.read_text(encoding="utf-8"))
    assert log[-1]["status"] == "error"
