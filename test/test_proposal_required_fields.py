# -*- coding: utf-8 -*-
"""
test/test_proposal_required_fields.py — a malformed model proposal is REFUSED,
named and counted; the step neither crashes nor silently skips (C4 C, 26 Sep 2026).

The cycle of 26 Sep 2026 11:50 failed self_observer with KeyError: 'problem' in
save_proposals: one model proposal lacked the field, and the whole step raised.

THE RULE, for a batch holding a malformed proposal: save_proposals must return
normally; the malformed proposal must be refused with the missing field NAMED in
the output and in the archive, and counted in the returned summary; the
well-formed proposals in the same batch must still be saved.
The forbidden fallbacks: raising (the old behaviour), and dropping the malformed
item without a count or a word.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import alignment.civilization_guard as guard
import agents.core.self_observer as so
from memory import proposal_archive as pa


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "BASE_DIR", tmp_path)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pa, "ARCHIVE_DIR", tmp_path / "proposal_archive")
    monkeypatch.setattr(pa, "LIVE_PROPOSALS", tmp_path / "memory" / "improvement_proposals.json")
    monkeypatch.setenv("CORTEX_CYCLE_ID", "test-cycle-1")
    monkeypatch.setattr(guard, "evaluate_proposal_alignment",
                        lambda _o: {"allowed": True, "risk_score": 0.0, "notes": "ok"})
    return tmp_path


def _good(problem="Замърсяване на водата в региона"):
    return {"component": "WATER", "problem": problem, "root_cause": "x",
            "solution": "build treatment capacity", "measurable_goal": "safe_water_pct > 80"}


def _live(tmp_path) -> list:
    return json.loads((tmp_path / "memory" / "improvement_proposals.json")
                      .read_text(encoding="utf-8"))["proposals"]


def test_a_proposal_without_problem_is_refused_named_and_counted(sandbox, capsys):
    bad = _good()
    del bad["problem"]                      # the exact shape of 26 Sep 11:50
    out = so.save_proposals([bad, _good("a different real problem")])
    assert out["refused"] == 1
    assert out["refused_fields"] == {"problem": 1}
    assert out["added"] == 1, "the well-formed proposal in the same batch was lost"
    printed = capsys.readouterr().out
    assert "REFUSED" in printed and "problem" in printed
    assert [p["problem"] for p in _live(sandbox)] == ["a different real problem"]


def test_every_missing_field_is_named(sandbox):
    out = so.save_proposals([{"problem": "only a problem", "component": "  "}])
    assert out["refused"] == 1 and out["added"] == 0
    assert set(out["refused_fields"]) == {"component", "solution", "measurable_goal"}


def test_a_non_object_item_is_refused_not_raised(sandbox):
    out = so.save_proposals(["the model returned a bare string", None])
    assert out["refused"] == 2 and out["added"] == 0


def test_the_refusal_is_archived_with_the_field_named(sandbox):
    bad = _good()
    del bad["solution"]
    so.save_proposals([bad])
    body = "\n".join(f.read_text(encoding="utf-8")
                     for f in sorted((sandbox / "proposal_archive").glob("20*.md")))
    assert "BLOCKED" in body and "missing required field(s) solution" in body


def test_a_stored_row_without_problem_does_not_crash_dedup(sandbox):
    (sandbox / "memory" / "improvement_proposals.json").write_text(
        json.dumps({"proposals": [{"component": "legacy", "timestamp": "2099-01-01T00:00:00+00:00"}]}),
        encoding="utf-8")
    out = so.save_proposals([_good()])
    assert out["added"] == 1
