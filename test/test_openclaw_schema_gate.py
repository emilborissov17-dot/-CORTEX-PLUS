#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_openclaw_schema_gate.py — THE LABEL WAS CHECKED. THE PAYLOAD WAS NOT.

classify() only ever read action_type — a string. Everything else in the task
dict travelled untouched, so this was a level_1 autonomous action:

    {"action_type": "web_fetch_get",
     "parameters": {"url": "__import__('os').system('calc')"}}

Phase 0 has no execution capability, so nothing would have run. That made the
hole invisible rather than absent: the day _execute() stops raising is the day
the payload matters, and by then the gate's shape is settled.

WHAT THESE TESTS PIN
---------------------
  * the ORDER: always_blocked, then schema, then policy match. Each step tested
    against the one before it, not just in isolation.
  * that a refused payload NEVER REACHES classify(). Asserted by counting calls
    to classify, not by inspecting the verdict — a verdict can be corrected
    after the fact, a call cannot be un-made.
  * that the patterns are ALLOWLISTS. The __import__ case is one payload; the
    tests also throw shell metacharacters, traversal, and a javascript: url at
    the same fields, because a rule that only stops the example is a blocklist
    wearing a schema's clothes.

    venv/Scripts/python.exe -m pytest test/test_openclaw_schema_gate.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import agents.openclaw_bridge as bridge  # noqa: E402

REAL_POLICY = REPO / "config" / "openclaw_action_policy.json"
REAL_SCHEMAS = REPO / "config" / "openclaw_action_schemas.json"


@pytest.fixture
def policy(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(REAL_POLICY.read_text(encoding="utf-8"), encoding="utf-8")
    return p


@pytest.fixture
def schemas(tmp_path):
    p = tmp_path / "schemas.json"
    p.write_text(REAL_SCHEMAS.read_text(encoding="utf-8"), encoding="utf-8")
    return p


def _submit(tmp_path, policy, schemas, task, dry_run=True):
    return bridge.submit_action(
        task, dry_run=dry_run, policy_path=policy, schema_path=schemas,
        audit_path=tmp_path / "audit.json",
        pending_path=tmp_path / "pending.json")


# ---------------------------------------------------------------------------
# THE ATTACK CASE
# ---------------------------------------------------------------------------

def test_an_import_payload_is_refused_by_schema(schemas):
    ok, reason = bridge.validate_parameters(
        "read_local_file", {"path": "__import__('os').system('calc')"},
        schema_path=schemas)
    assert ok is False
    assert "path" in reason


def test_the_import_payload_never_reaches_classification(tmp_path, policy, schemas,
                                                         monkeypatch):
    """THE LOAD-BEARING ONE. A verdict can be corrected; a call cannot be un-made."""
    seen = []
    real = bridge.classify
    monkeypatch.setattr(bridge, "classify",
                        lambda *a, **k: seen.append(a) or real(*a, **k))

    result = _submit(tmp_path, policy, schemas, {
        "action_type": "read_local_file",
        "parameters": {"path": "__import__('os').system('calc')"}})

    assert result["status"] == bridge.REFUSED_SCHEMA
    assert seen == [], (
        "classify() was called on a payload the schema had already refused — "
        "a malformed action must never be handed an autonomy level")


def test_a_refused_action_never_executes_even_with_dry_run_false(tmp_path, policy,
                                                                 schemas, monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, "_execute",
                        lambda task, verdict: calls.append((task, verdict)))
    result = _submit(tmp_path, policy, schemas, {
        "action_type": "web_fetch_get",
        "parameters": {"url": "__import__('os').system('calc')"}}, dry_run=False)
    assert result["executed"] is False
    assert result["status"] == bridge.REFUSED_SCHEMA
    assert calls == []


def test_the_audit_log_records_why_it_was_refused(tmp_path, policy, schemas):
    _submit(tmp_path, policy, schemas, {
        "action_type": "read_local_file",
        "parameters": {"path": "../../etc/passwd"}})
    log = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert log[-1]["autonomy_level"] == bridge.REFUSED_SCHEMA
    assert log[-1]["status"] == bridge.REFUSED_SCHEMA
    assert log[-1].get("schema_error"), "refused with no reason recorded"


# ---------------------------------------------------------------------------
# THE ORDER
# ---------------------------------------------------------------------------

def test_always_blocked_beats_a_malformed_payload(tmp_path, policy, schemas):
    """'This action may never run' must not be softened to 'your payload was
    invalid' — the second invites a corrected retry."""
    result = _submit(tmp_path, policy, schemas, {
        "action_type": "execute_arbitrary_shell",
        "parameters": {"anything": "at all", "nested": {"x": 1}}})
    assert result["status"] == "blocked"


def test_always_blocked_is_checked_before_the_schema_is_even_loaded(tmp_path, policy,
                                                                   monkeypatch):
    loaded = []
    monkeypatch.setattr(bridge, "load_schemas",
                        lambda *a, **k: loaded.append(1) or {})
    result = _submit(tmp_path, policy, REAL_SCHEMAS,
                     {"action_type": "disable_audit_log", "parameters": {"x": 1}})
    assert result["status"] == "blocked"
    assert loaded == [], "the schema file was read for an always_blocked action"


def test_a_valid_payload_still_reaches_the_policy_verdict(tmp_path, policy, schemas):
    result = _submit(tmp_path, policy, schemas, {
        "action_type": "web_fetch_get",
        "parameters": {"url": "https://example.com/feed.xml"}})
    assert result["status"] == "dry_run"
    assert result["would_run_as"] == "level_1"


def test_an_unclassified_but_valid_action_still_falls_to_level_3(tmp_path, policy,
                                                                 schemas):
    result = _submit(tmp_path, policy, schemas,
                     {"action_type": "some_new_action"})
    assert result["status"] == "awaiting_approval"


# ---------------------------------------------------------------------------
# UNKNOWN FIELDS, TYPES, PATTERNS
# ---------------------------------------------------------------------------

def test_an_unknown_field_is_refused_not_ignored(schemas):
    ok, reason = bridge.validate_parameters(
        "web_fetch_get",
        {"url": "https://example.com/a", "follow_redirects_to": "file:///etc"},
        schema_path=schemas)
    assert ok is False
    assert "follow_redirects_to" in reason or "Additional" in reason


def test_a_wrong_type_is_refused(schemas):
    ok, reason = bridge.validate_parameters(
        "web_search", {"query": "ok", "max_results": "all of them"},
        schema_path=schemas)
    assert ok is False


def test_parameters_must_be_an_object(schemas):
    ok, reason = bridge.validate_parameters(
        "web_fetch_get", ["url", "https://example.com"], schema_path=schemas)
    assert ok is False
    assert "object" in reason


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "https://example.com/a; rm -rf /",
    "https://example.com/a`whoami`",
    "https://example.com/a\nHost: evil",
    "ftp://example.com/a",
])
def test_the_url_pattern_is_an_allowlist_not_an_example_blocklist(schemas, bad):
    ok, _ = bridge.validate_parameters("web_fetch_get", {"url": bad},
                                       schema_path=schemas)
    assert ok is False, "{!r} passed the url pattern".format(bad)


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "config/../../../etc/passwd",
    "/etc/passwd",
    "C:\\Windows\\system32",
    "data/x.json; cat /etc/passwd",
    "__import__('os').system('calc')",
    "$(whoami)",
])
def test_the_path_pattern_refuses_traversal_and_shell(schemas, bad):
    ok, _ = bridge.validate_parameters("read_local_file", {"path": bad},
                                       schema_path=schemas)
    assert ok is False, "{!r} passed the path pattern".format(bad)


def test_an_ordinary_relative_path_still_works(schemas):
    ok, reason = bridge.validate_parameters(
        "read_local_file", {"path": "config/target_config.json"},
        schema_path=schemas)
    assert ok is True, reason


def test_backup_enabled_false_is_refused_on_a_write(schemas):
    """The policy already says backup_enabled must be true for level_2. Now the
    schema refuses the task before a level is ever assigned."""
    ok, _ = bridge.validate_parameters(
        "write_knowledge_file",
        {"target_path": "knowledge/x.md", "backup_enabled": False},
        schema_path=schemas)
    assert ok is False


def test_a_write_without_a_backup_field_is_refused(schemas):
    ok, _ = bridge.validate_parameters(
        "write_knowledge_file", {"target_path": "knowledge/x.md"},
        schema_path=schemas)
    assert ok is False


# ---------------------------------------------------------------------------
# FAIL-CLOSED
# ---------------------------------------------------------------------------

def test_an_action_with_no_schema_may_carry_no_parameters(schemas):
    ok, _ = bridge.validate_parameters("transcribe_media_local", {"file": "a.mp3"},
                                       schema_path=schemas)
    assert ok is False, (
        "an action type with no schema accepted parameters — a new action must "
        "have a schema written for it, in a commit, before it can carry data")
    ok2, _ = bridge.validate_parameters("transcribe_media_local", {},
                                        schema_path=schemas)
    assert ok2 is True


def test_a_missing_schema_file_refuses_anything_with_parameters(tmp_path):
    gone = tmp_path / "nope.json"
    ok, reason = bridge.validate_parameters("web_fetch_get",
                                            {"url": "https://example.com/a"},
                                            schema_path=gone)
    assert ok is False and "missing" in reason
    ok2, _ = bridge.validate_parameters("web_fetch_get", {}, schema_path=gone)
    assert ok2 is True, (
        "a deleted config file must not be a way to take the bridge down; the "
        "policy gate is itself fail-closed for parameterless actions")


def test_a_corrupt_schema_file_refuses_anything_with_parameters(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    ok, _ = bridge.validate_parameters("web_fetch_get",
                                       {"url": "https://example.com/a"},
                                       schema_path=bad)
    assert ok is False


def test_a_schema_that_is_itself_invalid_refuses_rather_than_passes(tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps({
        "_default": {"type": "object"},
        "schemas": {"web_fetch_get": {"type": "object",
                                      "properties": {"url": {"type": 12345}}}},
    }), encoding="utf-8")
    ok, reason = bridge.validate_parameters(
        "web_fetch_get", {"url": "https://example.com/a"}, schema_path=bad)
    assert ok is False
    assert "invalid" in reason


# ---------------------------------------------------------------------------
# The shipped file is the one that is tested
# ---------------------------------------------------------------------------

def test_every_schema_in_the_shipped_file_is_a_valid_schema():
    import jsonschema
    blob = json.loads(REAL_SCHEMAS.read_text(encoding="utf-8"))
    checked = 0
    for name, schema in list(blob["schemas"].items()) + [("_default", blob["_default"])]:
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema.get("additionalProperties") is False, (
            "{} allows unknown fields".format(name))
        checked += 1
    assert checked >= 10


def test_every_schema_covers_an_action_type_the_policy_knows():
    """A schema for an action nobody can request is dead weight; an action type
    with no schema is the fail-closed default and is fine."""
    policy = json.loads(REAL_POLICY.read_text(encoding="utf-8"))
    known = set()
    for level in ("level_1", "level_2", "level_3", "always_blocked"):
        known |= set(policy.get(level, {}).get("action_types", []))
    schemas = set(json.loads(REAL_SCHEMAS.read_text(encoding="utf-8"))["schemas"])
    assert schemas <= known, "schemas for unknown action types: {}".format(
        sorted(schemas - known))
