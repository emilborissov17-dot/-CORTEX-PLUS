"""
test/test_forward_row.py — Institution 0, forward row F-001 (task #9, 25 Sep 2026).

A refusal looks like: schema() naming the missing field, verify() ok=False for an
edited row, append_resolution() refusing anything but an append. The forbidden
fallbacks: a FINAL source that is a version number (GED 26.1 covers 1989-2025 and
can never hold 2026-10), a window that is not one calendar month, and a resolution
that rewrites an earlier one.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date
from pathlib import Path

import pytest

from experiments.institution import forward_rows as fr

REPO = Path(__file__).resolve().parents[1]
ROW = REPO / "experiments" / "institution" / "forward" / "F-001.json"


def _row():
    return json.loads(ROW.read_text(encoding="utf-8"))


# ── test_forward_row_schema ──────────────────────────────────────────────────

def test_forward_row_schema():
    row = _row()
    assert fr.schema_problems(row) == [], fr.schema_problems(row)
    for k in ("id", "commitment", "registered", "registered_by", "liveness", "condition",
              "resolution", "baseline", "sentences", "citation", "lane", "retrospective"):
        assert k in row, k
    c = row["condition"]
    assert c["type_of_violence"] == 1 and c["metric"] == "sum(best)"
    assert c["kept_if"] == "< 25" and c["not_kept_if"] == ">= 25"
    lo, hi = date.fromisoformat(c["date_start_from"]), date.fromisoformat(c["date_start_to"])
    assert lo.day == 1 and (lo.year, lo.month) == (hi.year, hi.month)
    assert hi.day == calendar.monthrange(hi.year, hi.month)[1], "the window is one full calendar month"


def test_both_resolve_by_rules_and_the_final_source_is_a_coverage_rule():
    r = _row()["resolution"]
    for stage in ("provisional", "final"):
        assert "release date + 14 days" in r[stage]["resolve_by"], stage
        assert r[stage]["source_late_if_no_release_by"], stage
    final = r["final"]["source"]
    assert "coverage includes 2026-10" in final
    assert not re.fullmatch(r"\s*(UCDP\s+)?GED\s+\d+(\.\d+)*\s*", final), "a version number alone"
    assert r["status"] == "OPEN" and r["append_only"] is True


def test_schema_refuses_a_version_only_final_and_a_partial_month():
    row = _row()
    row["resolution"]["final"]["source"] = "GED 26.1"
    assert any("final.source" in p for p in fr.schema_problems(row))
    row = _row()
    row["condition"]["date_start_to"] = "2026-10-30"
    assert any("calendar month" in p for p in fr.schema_problems(row))
    row = _row()
    del row["baseline"]
    assert any("baseline" in p for p in fr.schema_problems(row))


# ── test_forward_row_immutable ───────────────────────────────────────────────

def test_forward_row_immutable(tmp_path):
    p = tmp_path / "F-001.json"
    p.write_bytes(ROW.read_bytes())
    seal = fr.seal(p, prev_root="0" * 64, writer={"pid": 1, "process": "t", "commit": "x"})
    assert fr.verify(p, seal)["ok"] is True
    b = bytearray(p.read_bytes())
    b[b.index(b"25")] = ord("3")                      # one byte: the threshold
    p.write_bytes(bytes(b))
    v = fr.verify(p, seal)
    assert v["ok"] is False and v["why"]


# ── test_resolution_appends_never_overwrites ─────────────────────────────────

def test_resolution_appends_never_overwrites(tmp_path):
    log = tmp_path / "F-001.resolutions.jsonl"
    fr.append_resolution(log, "F-001", "PROVISIONAL", "NOT_KEPT", "ucdp:26.0.10", 31.0)
    first = log.read_bytes()
    assert fr.status("F-001", log) == "OPEN", "only FINAL closes the row"
    fr.append_resolution(log, "F-001", "FINAL", "KEPT", "ucdp:27.1", 12.0)
    assert log.read_bytes().startswith(first), "the first resolution was rewritten"
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert [r["stage"] for r in rows] == ["PROVISIONAL", "FINAL"]
    assert fr.status("F-001", log) == "RESOLVED"


def test_a_resolution_with_an_unknown_stage_or_outcome_is_refused(tmp_path):
    log = tmp_path / "r.jsonl"
    with pytest.raises(ValueError):
        fr.append_resolution(log, "F-001", "PROVISIONAL", "MAYBE", "x", 1.0)
    with pytest.raises(ValueError):
        fr.append_resolution(log, "F-001", "LATER", "KEPT", "x", 1.0)
    assert not log.exists()
