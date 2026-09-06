# -*- coding: utf-8 -*-
"""
Every outcome of a gate writes an event — success included. Step 5, 6 Sep 2026.

MEASURED that morning: github_publish pushed three commits at 01:36:26-30Z and
`memory/night_events.jsonl` held neither a publish event nor a refusal. Reading
the log honestly gave "neither published nor refused", a conclusion produced
entirely by the log recording only refusals. The two steps that WERE refused
wrote events; the one that worked wrote nothing.

Silence on success is the same defect as silence on refusal, one outcome later.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RUNNER = REPO / "fast_cycle_runner.py"
PUBLISHER = REPO / "github_publisher.py"


def _events(tmp_path, monkeypatch, fn, *a, **kw):
    """Run a runner function with night_events.jsonl redirected into tmp_path."""
    import memory.heartbeat as hb
    monkeypatch.setattr(hb, "BASE", tmp_path)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    fn(*a, **kw)
    p = tmp_path / "memory" / "night_events.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


@pytest.fixture(scope="module")
def runner():
    sys.path.insert(0, str(REPO))
    return importlib.import_module("fast_cycle_runner")


# ── the event writer itself ──────────────────────────────────────────────────

def test_a_pass_writes_an_event_naming_the_gate(runner, tmp_path, monkeypatch):
    rows = _events(tmp_path, monkeypatch, runner._gate_event,
                   "github_publish", "ПРОПУСНАТА", "notary", "level_2, all inputs fresh")
    assert len(rows) == 1
    r = rows[0]
    assert r["step"] == "github_publish"
    assert r["outcome"] == "ПРОПУСНАТА"
    assert r["gate"] == "notary"
    assert "level_2" in r["detail"]


def test_a_refusal_still_writes_its_event(runner, tmp_path, monkeypatch):
    rows = _events(tmp_path, monkeypatch, runner._refusal_event,
                   "self_modifier", "notary", "blind step 'hyperclaw_plan'")
    assert len(rows) == 1
    assert rows[0]["gate"] == "notary"
    assert "blind step" in rows[0]["detail"]


def test_extra_fields_reach_the_record(runner, tmp_path, monkeypatch):
    rows = _events(tmp_path, monkeypatch, runner._gate_event,
                   "github_publish", "ПУБЛИКУВАНА", "publisher", "3 file(s)",
                   {"commit_shas": ["abc123"], "files": ["reports/x.md"],
                    "file_count": 3})
    r = rows[0]
    assert r["commit_shas"] == ["abc123"]
    assert r["files"] == ["reports/x.md"]
    assert r["file_count"] == 3


def test_the_writer_prints_when_it_cannot_write(runner, monkeypatch, capsys):
    """A recorder that fails silently is the same defect one level up."""
    import memory.heartbeat as hb
    monkeypatch.setattr(hb, "BASE", Path("/nonexistent-root-for-this-test"))
    runner._gate_event("s", "ПРОПУСНАТА", "g", "w")
    assert "night_events write FAILED" in capsys.readouterr().out


# ── the publisher records what it wrote ─────────────────────────────────────

def test_push_file_records_path_and_commit_sha(monkeypatch):
    import github_publisher as gp

    class R:
        status_code = 201

        def raise_for_status(self):
            pass

        def json(self):
            return {"commit": {"sha": "deadbeef"}, "content": {"sha": "c0ffee"}}

    monkeypatch.setattr(gp, "_get_sha", lambda path: None)
    monkeypatch.setattr(gp.requests, "put", lambda *a, **k: R())
    monkeypatch.setattr(gp, "_headers", lambda: {})
    gp.PUBLISHED.clear()
    gp._push_file("reports/2026-09-06/index.md", "x", "msg")
    assert gp.PUBLISHED == [{"path": "reports/2026-09-06/index.md",
                             "commit_sha": "deadbeef", "status": 201}]


def test_publish_synthesis_returns_what_it_wrote(monkeypatch):
    import github_publisher as gp
    monkeypatch.setattr(gp, "publish_cycle",
                        lambda: gp.PUBLISHED.append(
                            {"path": "a.md", "commit_sha": "s1", "status": 201}))
    monkeypatch.setattr(gp, "publish_verified_hypotheses",
                        lambda: gp.PUBLISHED.append(
                            {"path": "b.md", "commit_sha": "s2", "status": 200}))
    out = gp.publish_synthesis()
    assert [w["path"] for w in out] == ["a.md", "b.md"]
    assert [w["commit_sha"] for w in out] == ["s1", "s2"]


def test_publish_synthesis_starts_from_empty(monkeypatch):
    """Two cycles in one process must not report the first cycle's commits."""
    import github_publisher as gp
    gp.PUBLISHED.append({"path": "stale.md", "commit_sha": "old", "status": 200})
    monkeypatch.setattr(gp, "publish_cycle", lambda: None)
    monkeypatch.setattr(gp, "publish_verified_hypotheses", lambda: None)
    assert gp.publish_synthesis() == []


# ── structural: the success path is wired, not just available ───────────────

def test_the_publish_step_writes_a_success_event():
    src = RUNNER.read_text(encoding="utf-8")
    body = src.split("def _github_publisher", 1)[1].split("_run(", 1)[0]
    assert "_gate_event(" in body, "the publish step still records nothing on success"
    assert "commit_shas" in body, "the event does not carry the commit shas"


def test_the_gate_records_its_passes_not_only_its_refusals():
    src = RUNNER.read_text(encoding="utf-8")
    body = src.split("def _witness_or_refuse", 1)[1].split("\ndef ", 1)[0]
    assert body.count("_gate_event(") >= 2, (
        "the gate still returns True without writing an event")
