#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_audit_exemplars.py — THE RETROSPECTIVE AUDIT, AND ITS ONE HARD RULE.

The rule: it must never modify or delete a journal line. The journal is the only
evidence of the six days of drift, and an audit that tidied it would be
destroying the thing it exists to measure.

    venv/Scripts/python.exe -m pytest test/test_audit_exemplars.py -v
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCRIPT = REPO / "scripts" / "audit_exemplars.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_exemplars", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RU = "Это указывает на возможную замръзнала сензор или застой в измерении."
EN = "The indicator has not moved, which suggests a frozen sensor."


def _rows(kind, pattern):
    """pattern is a string of C (clean) and D (dirty), oldest first."""
    return [{"ts": "2026-08-{:02d}T10:00:00+00:00".format(10 + i),
             "kind": kind, "summary": (EN if ch == "C" else RU)}
            for i, ch in enumerate(pattern)]


def test_an_all_clean_kind_is_not_dead_food():
    mod = _load()
    stats = mod.replay(_rows("k", "CCCCCCCC"))
    assert stats["k"]["exemplars_rejected"] == 0
    assert stats["k"]["rejected_rate"] == 0.0
    assert stats["k"]["fed_on_dead_food"] is False


def test_an_all_dirty_kind_is():
    mod = _load()
    stats = mod.replay(_rows("k", "DDDDDDDD"))
    assert stats["k"]["fed_on_dead_food"] is True
    assert stats["k"]["rejected_rate"] > mod.DEAD_FOOD_RATE


def test_the_first_call_saw_no_exemplar_at_all():
    """_memory() runs before the answer it prompts exists, so row 0 has none."""
    mod = _load()
    stats = mod.replay(_rows("k", "CC"))
    assert stats["k"]["calls_with_no_exemplar"] == 1


def test_a_row_is_never_its_own_exemplar():
    mod = _load()
    stats = mod.replay(_rows("k", "D"))
    assert stats["k"]["exemplars_shown"] == 0
    assert stats["k"]["entries_rejected"] == 1


def test_the_ratchet_shows_up_as_a_rate_near_one():
    """31 clean then 17 dirty in a row — the shape of 17 Aug."""
    mod = _load()
    rec = mod.replay(_rows("k", "C" * 31 + "D" * 17))["k"]
    # Measured, not guessed: 48 calls, 225 exemplars shown, 70 of them dirty.
    # 16 and not 17 calls saw a dirty one, because the FIRST dirty answer was
    # produced from five clean exemplars — which is the point. The drift starts
    # spontaneously and only then becomes self-feeding.
    assert rec["calls_replayed"] == 48
    assert rec["exemplars_shown"] == 225
    assert rec["exemplars_rejected"] == 70
    assert rec["calls_with_a_rejected_exemplar"] == 16
    assert rec["entries_rejected"] == 17
    assert rec["fed_on_dead_food"] is True


def test_first_contaminated_finds_the_date_the_drift_started():
    mod = _load()
    firsts = mod.first_contaminated(_rows("k", "CCDDD"))
    assert firsts["k"]["ts"] == "2026-08-12T10:00:00+00:00"
    assert firsts["k"]["reason"].startswith("CYRILLIC_")


def test_a_kind_that_never_drifted_has_no_first_contaminated():
    mod = _load()
    assert "k" not in mod.first_contaminated(_rows("k", "CCCC"))


def test_the_window_is_the_one_memory_actually_reads():
    """400 lines and 5 exemplars, or the audit is measuring a different system."""
    mod = _load()
    from core import brain
    assert mod.WINDOW_LINES == 400
    assert mod.DEFAULT_N == 5
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    assert "splitlines()[-400:]" in src
    assert brain._memory.__defaults__[-1] == mod.DEFAULT_N


# ── the hard rule ───────────────────────────────────────────────────────────

def test_the_script_contains_no_write_to_the_journal():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in (
                "write_text", "write_bytes", "unlink", "rename", "replace"):
            # the one permitted writer is the report, and it writes to OUT
            parent_src = ast.unparse(node) if hasattr(ast, "unparse") else ""
            assert "OUT" in parent_src, (
                "audit_exemplars.py calls .{}() on something that is not its "
                "own report: {}".format(node.attr, parent_src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "open":
            mode = node.args[1] if len(node.args) > 1 else None
            value = getattr(mode, "value", "r")
            assert str(value).startswith("r"), \
                "audit_exemplars.py opens a file for writing"


def test_running_it_leaves_the_journal_byte_identical(tmp_path, monkeypatch):
    mod = _load()
    journal = tmp_path / "brain_journal.jsonl"
    journal.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False)
                  for r in _rows("k", "CDCDCDCD")) + "\n", encoding="utf-8")
    before = journal.read_bytes()
    digest = hashlib.sha256(before).hexdigest()

    monkeypatch.setattr(mod, "JOURNAL", journal)
    monkeypatch.setattr(mod, "OUT", tmp_path / "audit.json")
    assert mod.main() == 0

    assert journal.read_bytes() == before
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == digest
    assert (tmp_path / "audit.json").exists()


def test_the_report_says_it_is_read_only(tmp_path, monkeypatch):
    mod = _load()
    journal = tmp_path / "j.jsonl"
    journal.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False)
                  for r in _rows("k", "CDCD")) + "\n", encoding="utf-8")
    monkeypatch.setattr(mod, "JOURNAL", journal)
    monkeypatch.setattr(mod, "OUT", tmp_path / "audit.json")
    mod.main()
    blob = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert "READ-ONLY AUDIT" in blob["note"]
    assert blob["entries_read"] == 4
    assert "by_kind" in blob and "overall" in blob


def test_it_takes_no_arguments():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    src = SCRIPT.read_text(encoding="utf-8")
    assert "argparse" not in src, "the brief says it takes no arguments"
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            assert not node.args.args, "main() grew a parameter"
