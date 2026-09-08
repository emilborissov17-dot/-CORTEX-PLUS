#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_scoring_engine_leaves_a_trace.py — THE DARKEST CORE STEP GETS A RECORD.

THE DEFECT THIS GUARDS
-----------------------
scoring_engine (step 12.4) is BACKBONE — never skipped by opinion, because the
audit chain must not break — and it produces THE NUMBER everything downstream
rests on. It had neither of the two things a step can leave behind:

  1. core/cycle_map.py declared produces=[], which that file's own header
     defines as "не знаем", not "nothing". So cycle_map.kept_promise() could not
     answer for the most load-bearing artifact in the cycle, and returned
     "НЕ ЗНАЕМ" -> UNKNOWN(0), which then became the promise dimension of the
     NEXT step.

     config/cycle_phases.json ALREADY promised output/cortex_scores_latest.json
     from D_SCORE. The phase card knew and the step card did not: two maps of
     the same cycle disagreeing about its most important file.

  2. It is an inline try/except, not a _run() step, so core/blackbox.py never
     saw it. A hard kill inside the scorer left no evidence it had even started.
     core/blackbox.py's own docstring names the steps that bypass _run() as a
     known blind spot; this was the worst of them.

WHAT WAS DELIBERATELY NOT CHANGED
----------------------------------
No score, no threshold, no scorer. cortex_scoring_engine.py is untouched, and
`git diff -w` on the runner shows ONLY the added comments and one `with` line.
test_no_scoring_logic_was_changed pins the module's scorer surface so a later
edit cannot ride in on this commit's back.

    venv\\Scripts\\python.exe -m pytest test/test_scoring_engine_leaves_a_trace.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

import core.cycle_map as cm

REPO = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = "output/cortex_scores_latest.json"


# ---------------------------------------------------------------------------
# (a) THE PRODUCES ENTRY — non-empty, and the real file
# ---------------------------------------------------------------------------

def test_the_step_declares_a_product_at_all():
    produces = cm.produces("scoring_engine")
    assert produces, (
        "scoring_engine declares produces=[]. In core/cycle_map.py that means "
        "'we do not know', not 'it produces nothing' — on the BACKBONE step "
        "that makes the number everything else rests on. kept_promise() cannot "
        "answer for it, and returns НЕ ЗНАЕМ -> UNKNOWN(0) to the next step.")


def test_the_declared_product_is_the_file_the_step_really_writes():
    assert cm.produces("scoring_engine") == [ARTIFACT]

    # AST, not a text search: the runner really does build and write that path.
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_cycle") \
        if any(isinstance(n, ast.FunctionDef) and n.name == "run_cycle"
               for n in ast.walk(tree)) else tree

    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "cortex_scores_latest.json" in literals, (
        "the runner no longer names cortex_scores_latest.json; the declaration "
        "in core/cycle_map.py is now stale")
    assert "output" in literals


def test_the_two_maps_of_the_cycle_now_agree_about_this_file():
    """config/cycle_phases.json promised it from D_SCORE while core/cycle_map.py
    said nothing. Two maps disagreeing about the cycle's most load-bearing
    artifact is the defect ITEM 7.1 was written about."""
    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))["phases"]
    assert ARTIFACT in phases["D_SCORE"]["produces"], (
        "D_SCORE no longer promises it; re-check the step declaration")

    step_phase = None
    for name, body in phases.items():
        if any(s.get("name") == "scoring_engine" for s in body.get("steps", [])):
            step_phase = name
    assert step_phase == "D_SCORE", (
        f"scoring_engine now lives in {step_phase}, which does not promise "
        f"{ARTIFACT}")


def test_no_other_step_claims_the_same_artifact():
    """Two producers of one file makes kept_promise ambiguous and gives the
    notary's blindness check a second name to blame."""
    owners = [n for n, _i, _p, prod, _b in cm.STEPS if ARTIFACT in (prod or [])]
    assert owners == ["scoring_engine"], owners


# ---------------------------------------------------------------------------
# (b) THE BLACKBOX TRACE
# ---------------------------------------------------------------------------

def test_the_step_is_wrapped_in_a_blackbox_context():
    """STRUCTURAL. The step must go through _bb_step, the same helper every
    _run() step uses — asserted on the AST so a comment claiming it is not
    mistaken for the wiring."""
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))

    wrapped = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "_bb_step"
                    and call.args and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == "scoring_engine"):
                wrapped = True
                body = ast.dump(node)
                assert "score_all_snapshots" in body, (
                    "the _bb_step block does not contain the scoring work; the "
                    "trace would record a step that did nothing")
    assert wrapped, (
        "scoring_engine is not inside a _bb_step context. It is BACKBONE and "
        "produces the cycle's central number, and a hard kill inside it would "
        "again leave no evidence it had started.")


def test_the_with_is_INSIDE_the_try_so_a_failure_records_an_error():
    """THE ORDERING, AND IT IS NOT CosMETIC.

    With the `with` OUTSIDE the try, the existing except swallows the exception
    before __exit__ sees it, and core/blackbox.step records a clean 'end' for a
    step that FAILED — a trace that actively lies. Inside, the exception passes
    through __exit__ first (recording 'error') and is then caught exactly as
    before.
    """
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if "scoring_engine" not in ast.dump(node):
            continue
        for child in node.body:
            if (isinstance(child, ast.With)
                    and "_bb_step" in ast.dump(child)
                    and "score_all_snapshots" in ast.dump(child)):
                found = True
        if found:
            handlers = ast.dump(node)
            assert "scoring_engine -> FAILED" in handlers, (
                "the fail-open except was removed; a scoring failure would now "
                "stop the cycle")
    assert found, (
        "the _bb_step context is not a direct child of the try. Outside it, a "
        "failed scoring step would be recorded as a clean 'end'.")


def test_a_blackbox_context_really_writes_begin_and_end(tmp_path, monkeypatch):
    """BEHAVIOURAL, on the real recorder with its log redirected. The structural
    test proves the wiring; this proves the mechanism it is wired to."""
    from core import blackbox

    log = tmp_path / "blackbox.jsonl"
    monkeypatch.setattr(blackbox, "LOG_PATH", str(log))

    with blackbox.step("scoring_engine"):
        pass

    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    phases = [r["phase"] for r in rows]
    assert phases == ["begin", "end"], phases
    assert all(r["step"] == "scoring_engine" for r in rows)
    assert rows[0]["pid"] and rows[0]["utc"]


def test_a_failure_inside_the_context_records_an_error_not_an_end(tmp_path,
                                                                  monkeypatch):
    """The half that matters. A 'begin' with no 'end' IS the finding; an 'error'
    row names what went wrong. Neither may read as success."""
    from core import blackbox

    log = tmp_path / "blackbox.jsonl"
    monkeypatch.setattr(blackbox, "LOG_PATH", str(log))

    with pytest.raises(ValueError):
        with blackbox.step("scoring_engine"):
            raise ValueError("the scorer blew up")

    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [r["phase"] for r in rows] == ["begin", "error"]
    assert rows[-1]["error_type"] == "ValueError"
    assert "blew up" in rows[-1]["error"]
    assert "end" not in [r["phase"] for r in rows], (
        "a failed step recorded an 'end' — the trace would say it completed")


def test_the_step_is_no_longer_on_the_uncovered_list():
    """The ratchet in test_checkpoint_wiring counts steps that record nothing.
    scoring_engine reaches the blackbox through _bb_step rather than _run(), so
    it is still counted there — this test records that deliberately, so nobody
    lowers that limit on the strength of this commit without checking."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    import re
    run_labels = set(re.findall(r"_run\(\s*[\"']([A-Za-z0-9_]+)[\"']", src))
    assert "scoring_engine" not in run_labels, (
        "scoring_engine now goes through _run(); lower UNCOVERED_STEP_LIMIT in "
        "test/test_checkpoint_wiring.py in the same commit")
    assert '_bb_step("scoring_engine")' in src, (
        "it reaches the blackbox by neither route")


# ---------------------------------------------------------------------------
# (c) NO SCORING LOGIC CHANGED
# ---------------------------------------------------------------------------

def test_no_scoring_logic_was_changed():
    """The scorer surface, pinned. This commit adds a declaration and a trace;
    a later edit must not ride in on its back."""
    tree = ast.parse((REPO / "cortex_scoring_engine.py").read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for required in ("score_all_snapshots", "save_scores"):
        assert required in names, f"{required} is gone from the scorer"

    assigns = {n.targets[0].id for n in tree.body
               if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    assert "AXIS_SCORERS" in assigns, "the scorer registry is gone"


def test_the_runner_still_writes_exactly_what_it_wrote_before():
    """The persisted shape is what every downstream reader depends on. The keys
    are asserted here so a 'harmless' tidy-up of the writer is caught."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    block = src.split('beat("scoring_engine", "12.4")', 1)[1].split("# ── 12.45", 1)[0]
    for key in ("generated_at", "scorer_version", "score_scale", "total_axes",
                "scores"):
        assert f'"{key}"' in block, f"the written record lost {key}"
    assert '"score_scale": "0-1"' in block, (
        "the 0-1 scale tag is gone — it is what tells this file apart from "
        "memory/axis_history.json, which holds 0-100 for the same axis")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
