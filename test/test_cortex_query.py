#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_cortex_query.py — fixtures for the human's unmediated query interface.

The load-bearing test here is test_imports_nothing_from_the_project: cortex_query's whole
claim is that it reads the same bytes the system reads through a path the system does not
own. The moment it imports a project module, that claim is gone — the import could pull in
a salience filter, a confidence discount, or a summarizer, and the human would be reading
the system's account of the file instead of the file. So it is asserted structurally, over
the AST, not by convention.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "scripts" / "cortex_query.py"

sys.path.insert(0, str(REPO / "scripts"))
import cortex_query as cq  # noqa: E402


# ── the structural guarantee ─────────────────────────────────────────────────

STDLIB_OK = {"argparse", "json", "sys", "datetime", "pathlib", "__future__"}


def test_imports_nothing_from_the_project():
    """No cycle, supervisor, composer, pulse or signing code — stdlib only."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # any relative import is a project import
                pytest.fail(f"relative import at line {node.lineno}")
            imported.add((node.module or "").split(".")[0])

    forbidden = imported - STDLIB_OK
    assert not forbidden, (
        f"cortex_query must import stdlib only; found {sorted(forbidden)}. "
        "A project import would put the system back between the human and the bytes."
    )


def test_no_llm_call():
    src = MODULE.read_text(encoding="utf-8").lower()
    for needle in ("groq", "ollama", "openai", "_local(", "llm(", "anthropic"):
        assert needle not in src, f"cortex_query must make no LLM call; found {needle!r}"


# ── --axis --force ───────────────────────────────────────────────────────────

def test_axis_force_appends_human_sense_request(tmp_path, monkeypatch, capsys):
    needs = tmp_path / "composer_needs.json"
    needs.write_text(json.dumps({
        "WATER_REVIEW": {"ts": "2026-08-01T00:00:00+00:00",
                         "items": [{"slot": "event_daily", "kind": "slot_unfilled", "detail": "x"}]}
    }), encoding="utf-8")
    monkeypatch.setattr(cq, "COMPOSER_NEEDS", needs)

    assert cq.cmd_axis_force("WATER_REVIEW") == 0

    doc = json.loads(needs.read_text(encoding="utf-8"))
    items = doc["WATER_REVIEW"]["items"]
    assert len(items) == 2, "the system's own need must survive alongside the human's"
    human = [i for i in items if i["kind"] == "human_sense_request"]
    assert len(human) == 1
    assert human[0]["requested_by"] == "human"
    assert "WATER_REVIEW" in human[0]["detail"]


def test_axis_force_creates_axis_entry_when_absent(tmp_path, monkeypatch):
    needs = tmp_path / "composer_needs.json"
    needs.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cq, "COMPOSER_NEEDS", needs)

    cq.cmd_axis_force("ENERGY_REVIEW")
    doc = json.loads(needs.read_text(encoding="utf-8"))
    assert doc["ENERGY_REVIEW"]["items"][0]["kind"] == "human_sense_request"


def test_axis_without_force_refuses(capsys):
    assert cq.main(["--axis", "WATER_REVIEW"]) == 2
    assert "--force" in capsys.readouterr().out


# ── --priority ───────────────────────────────────────────────────────────────

def test_priority_writes_override(tmp_path, monkeypatch):
    pf = tmp_path / "human_priority_override.json"
    monkeypatch.setattr(cq, "PRIORITY_FILE", pf)

    assert cq.cmd_priority("WATER_REVIEW", "1") == 0
    assert cq.cmd_priority("ENERGY_REVIEW", "3") == 0

    doc = json.loads(pf.read_text(encoding="utf-8"))
    assert doc["priority"] == {"WATER_REVIEW": 1, "ENERGY_REVIEW": 3}
    assert doc["set_by"] == "human"


def test_priority_rejects_non_integer(tmp_path, monkeypatch):
    monkeypatch.setattr(cq, "PRIORITY_FILE", tmp_path / "p.json")
    assert cq.cmd_priority("WATER_REVIEW", "soon") == 2


# ── --raw ────────────────────────────────────────────────────────────────────

def test_raw_prints_value_and_names_the_data_date_gap(tmp_path, monkeypatch, capsys):
    state = tmp_path / "composer_state"
    state.mkdir()
    (state / "CLIMATE_GLOBAL_RISK_REVIEW.json").write_text(json.dumps({
        "sources": {"noaa_gml_daily": {
            "status": "active", "consecutive_fails": 0, "last_value": 424.91,
            "last_ok_ts": "2026-08-01T05:34:23+00:00",
            "history": [["2026-07-30T07:50:44+00:00", 427.84],
                        ["2026-08-01T05:34:23+00:00", 424.91]]}}}), encoding="utf-8")
    monkeypatch.setattr(cq, "COMPOSER_STATE", state)
    monkeypatch.setattr(cq, "COMPOSED_OUT", tmp_path / "nope.json")

    assert cq.cmd_raw("noaa_gml_daily") == 0
    out = capsys.readouterr().out
    assert "424.91" in out
    assert "CLIMATE_GLOBAL_RISK_REVIEW" in out
    # the honest gap, stated rather than papered over with last_ok_ts
    assert "NOT PERSISTED" in out
    assert "2 point(s), 2 distinct value(s)" in out


def test_raw_unknown_source_returns_1(tmp_path, monkeypatch):
    state = tmp_path / "composer_state"
    state.mkdir()
    monkeypatch.setattr(cq, "COMPOSER_STATE", state)
    assert cq.cmd_raw("no_such_source") == 1


# ── --penumbra ───────────────────────────────────────────────────────────────

def test_penumbra_prints_leaf_and_payload_verbatim(tmp_path, monkeypatch, capsys):
    payload = tmp_path / "drop.json"
    payload.write_text('{"raw": "a cookie banner, unsummarized"}', encoding="utf-8")
    leaves = tmp_path / "_penumbra_leaves.jsonl"
    leaves.write_text(json.dumps({
        "id": "WATER_REVIEW/2026-08-01_deadbeef", "leaf": "deadbeef" * 8,
        "path": "drop.json", "axis": "WATER_REVIEW",
        "quarantine": {"reason": "source_singleton"}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cq, "PENUMBRA_LEAVES", leaves)
    monkeypatch.setattr(cq, "REPO", tmp_path)

    assert cq.cmd_penumbra("deadbeef") == 0
    out = capsys.readouterr().out
    assert "source_singleton" in out
    assert "a cookie banner, unsummarized" in out, "payload must be printed verbatim"


def test_penumbra_empty_is_not_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cq, "PENUMBRA_LEAVES", tmp_path / "absent.jsonl")
    assert cq.cmd_penumbra("anything") == 0
    assert "empty" in capsys.readouterr().out


def test_penumbra_miss_lists_what_exists(tmp_path, monkeypatch, capsys):
    leaves = tmp_path / "_penumbra_leaves.jsonl"
    leaves.write_text(json.dumps({"id": "A/b", "leaf": "ff" * 32, "path": "p.json",
                                  "quarantine": {"reason": "low_confidence"}}) + "\n",
                      encoding="utf-8")
    monkeypatch.setattr(cq, "PENUMBRA_LEAVES", leaves)
    assert cq.cmd_penumbra("nothing_like_this") == 1
    assert "A/b" in capsys.readouterr().out


# ── --ledger ─────────────────────────────────────────────────────────────────

def test_ledger_counts_and_marks_calendar_vs_symbolic(tmp_path, monkeypatch, capsys):
    led = tmp_path / "prophecy_ledger.jsonl"
    led.write_text("\n".join([
        json.dumps({"seq": 1, "event": "PREDICTION_SEALED", "target_kind": "axis_next",
                    "target_id": "A::next", "horizon_utc": "next_cycle_axis_score",
                    "learner": 50.0, "baseline": 50.0, "hash": "a" * 64}),
        json.dumps({"seq": 2, "event": "PREDICTION_SEALED", "target_kind": "composer_series",
                    "target_id": "B::band", "horizon_utc": "2026-08-15T00:00:00+00:00",
                    "learner": 1.0, "baseline": 1.0, "hash": "b" * 64}),
        json.dumps({"seq": 3, "event": "OUTCOME_SCORED", "ref_hash": "a" * 64, "actual": 50.0}),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(cq, "LEDGER", led)

    assert cq.cmd_ledger() == 0
    out = capsys.readouterr().out
    assert "predictions sealed 2" in out
    assert "outcomes scored    1" in out
    assert "unscored           1" in out
    assert "[calendar]" in out and "[symbolic]" in out


def test_ledger_absent_returns_1(tmp_path, monkeypatch):
    monkeypatch.setattr(cq, "LEDGER", tmp_path / "nope.jsonl")
    assert cq.cmd_ledger() == 1


# ── the consumer side: the queued demand must actually be drained ────────────

def test_composer_preserves_human_request_across_rewrite():
    """The composer replaces its OWN findings for an axis on every compose. If it also
    dropped the human's queued demand — as it did before this loop was closed — the
    request would die at beat 2.6, hours before data_scout reads the file at 22.5."""
    src = (REPO / "experiments" / "composers" / "composer.py").read_text(encoding="utf-8")
    assert "kept_human" in src
    assert 'i.get("kind") == "human_sense_request"' in src


def test_data_scout_drains_human_sense_request():
    src = (REPO / "core" / "data_scout.py").read_text(encoding="utf-8")
    assert '"human_sense_request"' in src, "data_scout must accept the human's demand kind"


def test_needs_report_orders_by_human_priority(monkeypatch, tmp_path):
    sys.path.insert(0, str(REPO / "experiments" / "needs"))
    import needs_report as nr

    pf = tmp_path / "human_priority_override.json"
    pf.write_text(json.dumps({"priority": {"ENERGY_REVIEW": 1}}), encoding="utf-8")
    monkeypatch.setattr(nr, "HUMAN_PRIORITY", pf)

    assert nr._human_priority() == {"ENERGY_REVIEW": 1}
    # axis derivable from an approve block, from a candidate, and from the text
    assert nr._item_axis({"approve": {"axis": "WATER_REVIEW"}}) == "WATER_REVIEW"
    assert nr._item_axis({"candidate": {"axis": "FOOD_REVIEW"}}) == "FOOD_REVIEW"
    assert nr._item_axis({"need": "ENERGY_REVIEW is starving", "why": ""}) == "ENERGY_REVIEW"
    # undeterminable stays unranked rather than being guessed at
    assert nr._item_axis({"need": "something vague", "why": "no axis here"}) is None


def test_needs_report_unranked_keeps_severity_order(monkeypatch, tmp_path):
    sys.path.insert(0, str(REPO / "experiments" / "needs"))
    import needs_report as nr
    monkeypatch.setattr(nr, "HUMAN_PRIORITY", tmp_path / "absent.json")
    assert nr._human_priority() == {}, "no override file means the system's order stands"
