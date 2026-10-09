# -*- coding: utf-8 -*-
"""test/test_proposed_once.py — a proposal is written once, and the repair of the file the old
code wrote (C-PROPOSED-1, 9 Oct 2026).

THE CASE. core.symbols.propose appended every proposal blindly, so the same 13 proposals piled up
to 397 lines by 9 Oct; proposed/3 crossed the arity-3 budget (390) and core.space.derive refused
the brain's turn (ENGINE_BUDGET, exit 2). The file is a SET of proposals.

A REFUSAL here: tools.dedup_proposed refuses loudly — a missing file, a file with no proposal, a
read-back that differs (and then puts the original back) — and never writes a line it did not read.
Failure paths first, then the happy path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import symbols                                               # noqa: E402
from tools import dedup_proposed as dd                                 # noqa: E402

SENT = "Reuters reported six people were hurt in Kyiv."


def _paths(tmp_path):
    v = tmp_path / "vocab.json"
    v.write_text(json.dumps({"suggested_heads": ["says", "supports"]}), encoding="utf-8")
    return {"proposed": tmp_path / "proposed.metta", "refused": tmp_path / "refused.jsonl",
            "new_relations": tmp_path / "new.jsonl", "log": tmp_path / "log.jsonl", "vocabulary": v,
            "ledger": tmp_path / "ledger.jsonl"}


def _propose(paths, head="supports", args=("six people",), sid="s-1"):
    def think(prompt, evidence, schema):
        d = {"head": head, "args": list(args)}
        return {"data": d, "raw": json.dumps(d), "sec": 0.1}
    return symbols.propose([{"id": sid, "text": SENT}], think=think, engine=lambda prog: ["ok"], paths=paths)


def _props(paths):
    p = Path(paths["proposed"])
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("(proposed ")] if p.exists() else []


# --------------------------------------------------------------------------- #
# propose(): once per distinct proposal
# --------------------------------------------------------------------------- #

def test_the_same_proposal_twice_is_written_once_and_counted_as_already(tmp_path):
    paths = _paths(tmp_path)
    first = _propose(paths)
    assert len(first["accepted"]) == 1 and first["already"] == [] and len(_props(paths)) == 1
    second = _propose(paths)
    assert second["accepted"] == [] and len(second["already"]) == 1 and len(_props(paths)) == 1
    assert second["calls"][0]["outcome"] == "ALREADY PROPOSED"
    rows = [json.loads(l) for l in Path(paths["log"]).read_text(encoding="utf-8").splitlines()]
    assert [r["already"] for r in rows if r.get("event") == "PROPOSED"] == [0, 1]


def test_a_different_expression_for_the_same_statement_is_new_and_is_written(tmp_path):
    paths = _paths(tmp_path)
    _propose(paths)
    r = _propose(paths, head="says", args=("Reuters", "six people"))
    assert len(r["accepted"]) == 1 and r["already"] == [] and len(_props(paths)) == 2


def test_the_same_expression_for_another_statement_is_written(tmp_path):
    paths = _paths(tmp_path)
    _propose(paths)
    r = _propose(paths, sid="s-2")
    assert len(r["accepted"]) == 1 and len(_props(paths)) == 2


def test_two_identical_proposals_inside_one_turn_are_written_once(tmp_path):
    paths = _paths(tmp_path)

    def think(prompt, evidence, schema):
        d = {"head": "supports", "args": ["six people"]}
        return {"data": d, "raw": json.dumps(d), "sec": 0.1}
    r = symbols.propose([{"id": "s-1", "text": SENT}, {"id": "s-1", "text": SENT}],
                        think=think, engine=lambda prog: ["ok"], paths=paths)
    assert len(r["accepted"]) == 1 and len(r["already"]) == 1 and len(_props(paths)) == 1


def test_an_unreadable_proposed_file_suppresses_nothing(tmp_path):
    paths = _paths(tmp_path)
    Path(paths["proposed"]).write_bytes(b"\xff\xfe not utf-8 at all")
    assert symbols.existing_proposals(paths["proposed"]) == set()
    assert symbols.existing_proposals(tmp_path / "no_such_file.metta") == set()


# --------------------------------------------------------------------------- #
# the repair: refusals first
# --------------------------------------------------------------------------- #

def test_the_repair_refuses_a_missing_file_and_a_file_with_no_proposal(tmp_path):
    with pytest.raises(dd.RefusedRepair, match="does not exist"):
        dd.repair(tmp_path / "none.metta")
    p = tmp_path / "empty.metta"
    p.write_text("; proposed-by m for statement x at t\n", encoding="utf-8")
    with pytest.raises(dd.RefusedRepair, match="nothing to repair"):
        dd.repair(p)
    assert p.read_text(encoding="utf-8") == "; proposed-by m for statement x at t\n"


def test_the_repair_keeps_each_proposal_once_in_order_with_its_first_comment(tmp_path):
    p = tmp_path / "proposed.metta"
    p.write_text("; proposed-by m for statement a at t1\n(proposed \"a\" \"m\" (says \"x\" \"y\"))\n"
                 "; proposed-by m for statement b at t2\n(proposed \"b\" \"m\" (supports \"z\"))\n"
                 "; proposed-by m for statement a at t3\n(proposed \"a\" \"m\" (says \"x\" \"y\"))\n"
                 "; proposed-by m for statement a at t4\n(proposed \"a\" \"m\" (says \"x\" \"y\"))\n",
                 encoding="utf-8")
    r = dd.repair(p, now=lambda: "STAMP")
    assert r["lines_before"] == 4 and r["distinct"] == 2 and r["dropped"] == 2 and r["written"] is True
    assert p.read_text(encoding="utf-8") == (
        "; proposed-by m for statement a at t1\n(proposed \"a\" \"m\" (says \"x\" \"y\"))\n"
        "; proposed-by m for statement b at t2\n(proposed \"b\" \"m\" (supports \"z\"))\n")
    bak = tmp_path / "proposed.metta.STAMP.bak"
    assert bak.exists() and bak.read_text(encoding="utf-8").count("(proposed ") == 4
    # idempotent: a second run writes nothing and says so
    again = dd.repair(p)
    assert again["dropped"] == 0 and again["written"] is False and again["backup"] is None


def test_the_repair_writes_nothing_on_a_dry_run(tmp_path):
    p = tmp_path / "proposed.metta"
    before = ("(proposed \"a\" \"m\" (says \"x\"))\n" * 3)
    p.write_text(before, encoding="utf-8")
    r = dd.repair(p, dry_run=True)
    assert r["dropped"] == 2 and r["written"] is False and p.read_text(encoding="utf-8") == before
    assert not list(p.parent.glob("*.bak"))


def test_a_read_back_that_differs_restores_the_original_and_refuses(tmp_path, monkeypatch):
    p = tmp_path / "proposed.metta"
    before = "(proposed \"a\" \"m\" (says \"x\"))\n(proposed \"a\" \"m\" (says \"x\"))\n"
    p.write_text(before, encoding="utf-8")
    monkeypatch.setattr(dd, "render", lambda keep: "(proposed \"INVENTED\" \"m\" (says \"x\"))\n")
    with pytest.raises(dd.RefusedRepair, match="read-back differs"):
        dd.repair(p, now=lambda: "S")
    assert p.read_text(encoding="utf-8") == before


def test_the_cli_reports_and_never_raises(tmp_path, capsys):
    assert dd.main(["--path", str(tmp_path / "none.metta")]) == 2
    assert "REFUSED" in capsys.readouterr().out
    p = tmp_path / "proposed.metta"
    p.write_text("(proposed \"a\" \"m\" (says \"x\"))\n" * 2, encoding="utf-8")
    assert dd.main(["--path", str(p), "--dry-run"]) == 0
    assert "before 2, distinct 1, dropped 1" in capsys.readouterr().out


def test_the_repair_defaults_to_the_live_path_but_this_test_touches_only_tmp():
    assert dd.PROPOSED == REPO / "memory" / "space" / "proposed.metta"
