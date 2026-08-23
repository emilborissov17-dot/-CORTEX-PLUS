#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_merit.py — THE EXAM IS NOT WRITTEN BY THE STUDENT.

AMENDMENT_001's first condition, made checkable. The three the command names:

  * a claim closed by its own generation is SELF_EXAMINED and never ELIGIBLE;
  * a claim closed by an external observation and correct is ELIGIBLE;
  * the ledger is byte-identical after a read.

Plus the one that decides whether any of this can ever train anything: only a
MODEL claim can earn a weight. A statistical learner beating a naive baseline
is a fact about arithmetic and no gradient descends from it.

Assertions about code parse it. Never grep.

    venv/Scripts/python.exe -m pytest test/test_merit.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import merit as mt   # noqa: E402


@pytest.fixture
def led(tmp_path):
    return tmp_path / "merit_ledger.jsonl"


def _states(path):
    return {p["claim_id"]: p["state"] for p in mt.pair(mt.read(path))}


# ═══ THE THREE ══════════════════════════════════════════════════════════════

def test_a_claim_closed_by_its_own_generation_is_self_examined(led):
    a = mt.open_claim("ram will fall", how_checked="read ram_percent after",
                      model="qwen2.5:3b", step="s1", generation_id="gen-1",
                      path=led)
    mt.close_claim(a["claim_id"], actual=1, correct=True,
                   generation_id="gen-1", path=led)
    st = _states(led)
    assert st[a["claim_id"]] == mt.SELF_EXAMINED


def test_and_a_self_examined_claim_is_never_eligible_however_right(led):
    a = mt.open_claim("x", how_checked="y", model="m", generation_id="g",
                      path=led)
    mt.close_claim(a["claim_id"], actual=1, correct=True, generation_id="g",
                   path=led)
    p = mt.pair(mt.read(led))[0]
    assert p["state"] == mt.SELF_EXAMINED
    assert p["state"] != mt.ELIGIBLE
    assert "own paper" in p["why"] or "one generation" in p["why"]


def test_a_model_claim_closed_externally_and_correct_is_eligible(led):
    b = mt.open_claim("disk will hold", how_checked="shutil.disk_usage",
                      model="qwen2.5:3b", step="s2", generation_id="gen-2",
                      path=led)
    mt.close_claim(b["claim_id"], actual=65.5, correct=True,
                   observer=mt.OBSERVER_CODE, generation_id=None, path=led)
    assert _states(led)[b["claim_id"]] == mt.ELIGIBLE


def test_the_ledger_is_byte_identical_after_a_read(led):
    a = mt.open_claim("x", how_checked="y", model="m", path=led)
    mt.close_claim(a["claim_id"], actual=1, correct=True, path=led)
    before = led.read_bytes()
    mt.read(led)
    mt.pair(mt.read(led))
    mt.summary(path=led)
    mt.would_be_eligible(30)
    assert led.read_bytes() == before


# ── only a model claim can earn a weight ────────────────────────────────────

def test_a_code_claim_is_never_eligible(led):
    e = mt.open_claim("axis will rise", how_checked="the scorer",
                      claimant=mt.CLAIMANT_CODE, path=led)
    mt.close_claim(e["claim_id"], actual=1, correct=True, path=led)
    p = mt.pair(mt.read(led))[0]
    assert p["state"] == mt.CLOSED
    assert "not a model" in p["why"]


def test_an_observation_a_model_produced_is_self_examined(led):
    f = mt.open_claim("w", how_checked="z", model="m", generation_id="g1",
                      path=led)
    mt.close_claim(f["claim_id"], actual=1, correct=True,
                   observer=mt.OBSERVER_MODEL, generation_id="g2", path=led)
    assert _states(led)[f["claim_id"]] == mt.SELF_EXAMINED


# ── nothing is deleted ──────────────────────────────────────────────────────

def test_a_wrong_prediction_is_kept(led):
    c = mt.open_claim("cpu will spike", how_checked="cpu_percent", model="m",
                      path=led)
    mt.close_claim(c["claim_id"], actual=6.0, correct=False, path=led)
    p = mt.pair(mt.read(led))[0]
    assert p["state"] == mt.CLOSED
    assert "more valuable half" in p["why"]
    assert len(mt.read(led)) == 2


def test_an_unclosed_claim_stays_open(led):
    d = mt.open_claim("tomorrow will finish", how_checked="the ledger",
                      model="m", path=led)
    assert _states(led)[d["claim_id"]] == mt.OPEN


def test_a_claim_with_no_stated_test_is_refused(led):
    """A claim whose test is decided after the outcome cannot fail, and a claim
    that cannot fail cannot earn anything."""
    with pytest.raises(ValueError) as e:
        mt.open_claim("something", how_checked="", path=led)
    assert "cannot be wrong" in str(e.value)
    with pytest.raises(ValueError):
        mt.open_claim("something", how_checked="   ", path=led)


def test_the_pairing_is_reconstructable_from_the_ledger_alone(led):
    """One of the ELIGIBLE conditions, so it is how pairing is actually done."""
    a = mt.open_claim("x", how_checked="y", model="m", path=led)
    mt.close_claim(a["claim_id"], actual=1, correct=True, path=led)
    rows = [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines()]
    pairs = mt.pair(rows)                     # no index, no outside state
    assert len(pairs) == 1 and pairs[0]["closed"] is not None


def test_a_close_with_no_matching_open_is_ignored(led):
    mt.close_claim("no-such-claim", actual=1, correct=True, path=led)
    assert mt.pair(mt.read(led)) == []


# ── it wraps what exists rather than replacing it ───────────────────────────

def test_prophecy_imports_as_code_claims_and_never_earns_a_weight():
    """541 sealed and 471 scored, hash-chained, every ref_hash resolving — and
    the learner is trend/persistence/damped. Excellent evidence, wrong
    claimant."""
    rows = mt.from_prophecy(days=30)
    if not rows:
        pytest.skip("no prophecy ledger on this machine")
    opens = [r for r in rows if r["entry"] == mt.OPEN]
    assert opens, rows[:2]
    assert all(r["claimant"] == mt.CLAIMANT_CODE for r in opens)
    s = mt.summary(rows)
    assert s["eligible"] == 0, "a statistical learner earned a weight"


def test_divergence_imports_as_model_claims():
    """prev_promise is what the brain said a step would do; `observed` is a
    file-touch audit measured from disk. The exam is not the student."""
    rows = mt.from_divergence(days=30)
    if not rows:
        pytest.skip("no divergence log on this machine")
    opens = [r for r in rows if r["entry"] == mt.OPEN]
    closes = [r for r in rows if r["entry"] == mt.CLOSED]
    assert all(r["claimant"] == mt.CLAIMANT_MODEL for r in opens)
    assert all(r["observer"] == mt.OBSERVER_CODE for r in closes)
    assert all(r["generation_id"] is None for r in closes), (
        "the audit is not a generation")


def test_the_adapters_do_not_write_to_the_source_records():
    """Wrap, do not replace — and above all do not touch. Parsed: neither
    adapter may call anything that writes."""
    tree = ast.parse((REPO / "core" / "merit.py").read_text(encoding="utf-8"))
    for name in ("from_prophecy", "from_divergence"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        called |= {n.func.attr for n in ast.walk(fn)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)}
        for w in ("_append", "open_claim", "close_claim", "write_text",
                  "append_json", "append_durable"):
            assert w not in called, "{} calls {}".format(name, w)


def test_the_headline_number_is_reproducible():
    w = mt.would_be_eligible(30)
    assert w["days"] == 30
    assert w["prophecy"]["eligible"] == 0
    assert w["eligible_total"] == w["combined"]["eligible"]
    assert w["eligible_total"] == w["divergence"]["eligible"]


# ── durability ──────────────────────────────────────────────────────────────

def test_the_write_is_durable():
    tree = ast.parse((REPO / "core" / "merit.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_append")
    names = {a.name for n in ast.walk(fn)
             if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "append_json" in names


def test_it_appends_and_never_rewrites(led):
    for i in range(5):
        mt.open_claim("c{}".format(i), how_checked="x", model="m", path=led)
    assert len(mt.read(led)) == 5
    mt.open_claim("c5", how_checked="x", model="m", path=led)
    assert len(mt.read(led)) == 6


def test_no_function_here_removes_a_line():
    tree = ast.parse((REPO / "core" / "merit.py").read_text(encoding="utf-8"))
    banned = {"unlink", "remove", "truncate", "rmtree"}
    hit = {n.func.attr for n in ast.walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr in banned}
    assert not hit, hit


def test_the_selftest_passes():
    assert mt._selftest() == 0
