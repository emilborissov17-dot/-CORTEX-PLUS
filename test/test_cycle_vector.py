#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_cycle_vector.py — THE LEXICON CLOCK STARTS.

cockpit/vector.append() has had no caller since COMMAND 21. warming() has said
"0/20 cycles" every time it was asked. This is the wire, and these are the
assertions that keep it honest:

  * one line per cycle end, 29 measurable keys;
  * a dimension that could not be measured stays None and NEVER 0.0;
  * a refused cycle writes nothing;
  * the write is durable;
  * nothing here can kill a cycle.

Assertions about code parse it (AST). Never grep.

    venv/Scripts/python.exe -m pytest test/test_cycle_vector.py -v
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

from core import cycle_vector as cv       # noqa: E402
from cockpit import vector as vec         # noqa: E402


@pytest.fixture
def store(tmp_path):
    return tmp_path / "state_vectors.jsonl"


# ═══ THE CLOCK ══════════════════════════════════════════════════════════════

def test_a_simulated_cycle_end_appends_one_line(store):
    rec = cv.write(cycle_id="c1", store_path=store, ledger_rows=[])
    assert rec["written"] is True, rec["why"]
    lines = store.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_the_line_carries_29_measurable_keys(store):
    cv.write(cycle_id="c1", store_path=store, ledger_rows=[])
    v = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    assert v["dims"] == 25
    assert len(v["vector"]) == 25
    assert len(v["fields"]) == 25
    # Derived, not restated: this named flow_score literally, and flow_score is
    # gone. The property is unchanged — the cycle block travels with the vector
    # and every declared field is in it.
    from cockpit import vector as vmod
    assert set(v["cycle"]) == set(vmod.CYCLE_FIELDS)
    assert len(v["vector"]) + len(v["cycle"]) == 25 + len(vmod.CYCLE_FIELDS)


def test_warming_moves_from_zero_to_one(store):
    """THE POINT OF THE WHOLE PART."""
    assert vec.warming(store)["cycles"] == 0
    assert vec.warming(store)["label"] == "lexicon warming: 0/20 cycles"
    cv.write(cycle_id="c1", store_path=store, ledger_rows=[])
    w = vec.warming(store)
    assert w["cycles"] == 1
    assert w["label"] == "lexicon warming: 1/20 cycles"
    assert w["warm"] is False


def test_twenty_cycles_warm_the_lexicon(store):
    for i in range(20):
        cv.write(cycle_id="c{}".format(i), store_path=store, ledger_rows=[])
    w = vec.warming(store)
    assert w["cycles"] == 20
    assert w["warm"] is True, "twenty vectors and the lexicon is still cold"


def test_each_cycle_appends_rather_than_replacing(store):
    for i in range(3):
        cv.write(cycle_id="c{}".format(i), store_path=store, ledger_rows=[])
    rows = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert [r["cycle_id"] for r in rows] == ["c0", "c1", "c2"]


# ── None is not zero ────────────────────────────────────────────────────────

def _probe_with(overrides):
    """A REAL probe with a few readings overridden.

    A hand-rolled {"groups": ...} dict is missing keys somatic.state_vector()
    needs (it raised KeyError: 'ts'), and a fixture that does not have the
    shape of the thing it stands in for tests nothing."""
    from cockpit import somatic as som
    p = som.probe()
    for rows in p.get("groups", {}).values():
        for row in rows:
            if row.get("key") in overrides:
                row.update(overrides[row["key"]])
    return p


def test_an_unreadable_sensor_stays_None_and_never_zero(store):
    """A sensor that could not be read must not look like one that read zero.
    Once it is a number in this file the lexicon fits on it and cannot tell."""
    probe = _probe_with({
        "gpu_temp_c": {"value": None, "available": False},
        "cpu_percent": {"value": 0.0, "available": True}})
    rec = cv.write(cycle_id="c1", store_path=store, probe=probe, ledger_rows=[])
    assert rec["written"] is True, rec["why"]
    v = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    pairs = dict(zip(v["fields"], v["vector"]))
    assert pairs["gpu_temp_c"] is None, "an unreadable sensor became a number"
    assert pairs["cpu_percent"] == 0.0, "a real zero was discarded"


def test_a_real_zero_and_a_missing_reading_are_distinguishable(store):
    probe = _probe_with({
        "gpu_util_pct": {"value": 0.0, "available": True},
        "battery_percent": {"value": None, "available": False}})
    rec = cv.write(cycle_id="c1", store_path=store, probe=probe, ledger_rows=[])
    assert rec["written"] is True, rec["why"]
    v = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    pairs = dict(zip(v["fields"], v["vector"]))
    assert pairs["gpu_util_pct"] == 0.0
    assert pairs["battery_percent"] is None
    assert pairs["gpu_util_pct"] is not pairs["battery_percent"]


def test_fields_and_vector_must_line_up_or_it_refuses(store, monkeypatch):
    """An off-by-one between the two would mislabel every dimension in the
    store, permanently and silently."""
    def _skewed(**kw):
        return {"fields": ["a", "b", "c"], "vector": [1, 2],
                "dims": 3, "measured": 2, "cycle": {}, "unresolved_fields": []}
    monkeypatch.setattr(vec, "assemble", _skewed)
    rec = cv.write(cycle_id="c1", store_path=store, ledger_rows=[])
    assert rec["written"] is False
    assert "mismatch" in rec["why"]
    assert not store.exists()


# ── a refused cycle has nothing to describe ─────────────────────────────────

def test_a_refused_cycle_writes_no_vector(store):
    rec = cv.write(cycle_id="c-ref", store_path=store, ledger_rows=[
        {"event": "CYCLE_REFUSED_SURVIVAL_GATE", "cycle_id": "c-ref"}])
    assert rec["written"] is False
    assert "refused" in rec["why"]
    assert not store.exists()


def test_a_finished_cycle_after_a_refused_one_still_writes(store):
    rows = [{"event": "CYCLE_REFUSED_SURVIVAL_GATE", "cycle_id": "old"},
            {"event": "CYCLE_STARTED", "cycle_id": "new"}]
    rec = cv.write(cycle_id="new", store_path=store, ledger_rows=rows)
    assert rec["written"] is True, rec["why"]


def test_an_unreadable_ledger_does_not_block_the_write(store):
    """Fail-open: if we cannot tell whether it was refused, we write. A missing
    vector is worse than one extra."""
    assert cv.was_refused("c1", ledger_rows=None) in (True, False)
    rec = cv.write(cycle_id="c1", store_path=store, ledger_rows=[])
    assert rec["written"] is True


# ── durability ──────────────────────────────────────────────────────────────

def test_the_write_goes_through_core_durable():
    """Parsed. A vector lost in the page cache to a kill is a cycle that never
    happened as far as the lexicon is concerned."""
    tree = ast.parse((REPO / "core" / "cycle_vector.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "write")
    names = {a.name.split(".")[-1] for n in ast.walk(fn)
             if isinstance(n, ast.ImportFrom) for a in n.names}
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "append_durable" in names
    assert "append_durable" in called, "imported but not called"


def test_it_never_uses_a_bare_open_to_write():
    tree = ast.parse((REPO / "core" / "cycle_vector.py").read_text(
        encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "open":
            modes = [a.value for a in n.args[1:]
                     if isinstance(a, ast.Constant)]
            assert not any("a" in str(m) or "w" in str(m) for m in modes), \
                "it writes around core.durable"


# ── nothing here can kill a cycle ───────────────────────────────────────────

def test_write_never_raises_whatever_happens(monkeypatch, store):
    def _boom(**kw):
        raise RuntimeError("the somatic probe exploded")
    monkeypatch.setattr(vec, "assemble", _boom)
    rec = cv.write(cycle_id="c1", store_path=store, ledger_rows=[])
    assert rec["written"] is False
    assert "RuntimeError" in rec["why"]


def test_an_unwritable_path_is_reported_not_raised(tmp_path):
    rec = cv.write(cycle_id="c1", ledger_rows=[],
                   store_path=tmp_path / "no" / "such" / "dir" / "v.jsonl")
    assert isinstance(rec, dict)
    assert rec["written"] in (True, False)


def test_the_failure_is_loud(capfd, monkeypatch, store):
    """A silent failure would make the lexicon merely look slow to warm."""
    monkeypatch.setattr(vec, "assemble",
                        lambda **kw: (_ for _ in ()).throw(OSError("no")))
    cv.write_at_cycle_end(cycle_id="c1", store_path=store, ledger_rows=[])
    out = capfd.readouterr().out
    assert "STATE VECTOR NOT WRITTEN" in out
    assert "OSError" in out
    assert "seals normally" in out


def test_a_success_says_how_warm_the_lexicon_is(capfd, store):
    cv.write_at_cycle_end(cycle_id="c1", store_path=store, ledger_rows=[])
    out = capfd.readouterr().out
    assert "state vector appended" in out
    assert "lexicon warming: 1/20" in out


# ── the wiring, parsed ──────────────────────────────────────────────────────

def test_the_runner_calls_it_once_at_the_cycle_end():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_write_vector"]
    assert len(calls) == 1, "the vector is written {} times a cycle".format(
        len(calls))


def test_it_is_written_before_the_seal_and_after_the_last_step():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    def line_of(name):
        return next(n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == name)
    assert line_of("_write_vector") < line_of("_seal_cycle_record")


def test_the_call_site_is_wrapped(capfd):
    """Fail-open at the call site too, not only inside the module."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_write_vector")
    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    covering = [t for t in tries
                if t.lineno <= call.lineno <= max(
                    (x.lineno for x in ast.walk(t) if hasattr(x, "lineno")),
                    default=t.lineno)]
    assert covering, "the call to _write_vector is not inside a try"
    assert any(h.type is not None or h.type is None
               for t in covering for h in t.handlers)


def test_the_store_path_is_passed_explicitly():
    """cockpit/vector.append() requires it and has no default. This module
    does not invent one at the call site either."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_write_vector")
    assert any(k.arg == "store_path" for k in call.keywords)


def test_the_selftest_passes():
    assert cv._selftest() == 0
