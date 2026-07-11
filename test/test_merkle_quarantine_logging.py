"""Quarantine events must land in development_journal.json[today]["quarantine_events"]
and be visible to fast_cycle_runner's step-24 combined-read logic
(patch_executions + quarantine_events), the same journal that
MerkleMemory().commit() archives at the end of a cycle.

Runs entirely against a sandbox tmp_path via self_modifier.BASE_DIR
monkeypatching — never touches the real memory/development_journal.json.
"""
import json
from datetime import datetime, timezone

import agents.core.self_modifier as self_modifier


def _write_bad_patch(sandbox, monkeypatch):
    monkeypatch.setattr(self_modifier, "BASE_DIR", sandbox)
    target = "agents/core/merkletest_patch.py"
    bad_code = "#!/usr/bin/env python3\nimport subprocess\nsubprocess.check_output(['echo'])\n"
    return self_modifier._write_python(target, bad_code, {"component": "merkletest"})


def _today_quarantine_events(sandbox):
    journal_path = sandbox / "memory" / "development_journal.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return journal.get(today, {})


def test_quarantine_event_logged_to_journal(sandbox, monkeypatch):
    result = _write_bad_patch(sandbox, monkeypatch)
    events = _today_quarantine_events(sandbox).get("quarantine_events", [])
    matching = [e for e in events if e.get("source_proposal_component") == "merkletest"]

    assert not result["success"]
    assert len(matching) == 1
    assert matching[0]["type"] == "quarantine"
    assert matching[0]["verdict_gate"] == "ast_gate"
    assert "subprocess" in matching[0]["deny_reason"]


def test_fast_cycle_runner_read_logic_picks_up_quarantine_event(sandbox, monkeypatch):
    _write_bad_patch(sandbox, monkeypatch)
    today_entry = _today_quarantine_events(sandbox)

    # Mirrors fast_cycle_runner's step-24 read logic: patch_executions and
    # quarantine_events are combined before being handed to MerkleMemory().commit().
    patch_results = today_entry.get("patch_executions", [])
    quarantine_events = today_entry.get("quarantine_events", [])
    combined = patch_results + quarantine_events

    assert any(e.get("source_proposal_component") == "merkletest" for e in combined)
