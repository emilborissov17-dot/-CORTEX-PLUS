#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_backbone_steps_leave_a_trace.py — THE DARK BACKBONE STEPS GET A RECORD.

THE CLASS OF DEFECT
--------------------
A BACKBONE step is one the brain may never skip, because the audit chain must
not break. Several of them recorded NOTHING: they are inline blocks rather than
_run() steps, so core/blackbox.py never saw them, and a hard kill inside one left
no evidence it had started. core/blackbox.py's own docstring names the steps that
bypass _run() as a known blind spot.

Several also declared a produces that was empty — which core/cycle_map.py's own
header defines as "не знаем", not "nothing" — or a DIRECTORY that other steps
also write into, so kept_promise() could pass on somebody else's file.

scoring_engine (12.4) was the first of these, fixed in 6b4faad. DARK_STEPS below
grows by one entry per commit as each is fixed; the parametrized tests apply to
every entry, so a later regression on an earlier step fails here too.

THE ORDERING RULE, WHICH IS THE POINT
--------------------------------------
Where a step has a fail-open `except`, the `with _bb_step(...)` must be INSIDE
the try. Outside it, the except swallows the exception before __exit__ sees it
and core/blackbox.step records a clean 'end' for a step that FAILED — a trace
that actively lies, which is worse than no trace at all. Where a step has NO
except, there is nothing to swallow and the bare `with` is correct.

    venv\\Scripts\\python.exe -m pytest test/test_backbone_steps_leave_a_trace.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

import core.cycle_map as cm

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNNER = REPO / "fast_cycle_runner.py"


# step -> what must be true of it.
#   produces  : the exact declaration expected in core/cycle_map.py
#   marker    : an identifier that must appear inside the _bb_step block, so a
#               trace around an empty block cannot pass
#   guarded   : True  -> it has a fail-open except; the `with` MUST be inside the
#                        try, or a failure records a clean 'end'
#               False -> unguarded by design; adding a handler would be a logic
#                        change, and the bare `with` is correct
DARK_STEPS = {
    "update_master": {
        "produces": ["snapshots/master/master_snapshot_latest.json"],
        "marker": "update_master",
        "guarded": False,
    },
    "merklememory_commit": {
        "produces": ["cortex_memory/archive/merkle_root.txt"],
        "marker": "MerkleMemory",
        "guarded": True,
    },
    # produces was ALREADY correct for this one — the only dark step of the four
    # whose declaration needed nothing. Its commit is trace-only.
    "brain_debrief": {
        "produces": ["memory/brain_journal.jsonl"],
        "marker": "debrief",
        "guarded": True,
    },
    # produces was ALREADY correct here too, and the DIRECTORY is the right unit:
    # CYCLE_REPORT_<date>.md is a dated name. dated_output=True is what lets it
    # past test_a_declared_file_is_not_a_directory_another_step_also_writes, and
    # it is only honest because nothing else writes into output/reports —
    # unlike snapshots/master, which three steps share.
    "cycle_report": {
        "produces": ["output/reports"],
        "marker": "cycle_report",
        "guarded": True,
        "dated_output": True,
    },
}

PARAMS = sorted(DARK_STEPS)


def _tree() -> ast.Module:
    return ast.parse(RUNNER.read_text(encoding="utf-8"))


def _bb_blocks(step: str, tree: ast.Module | None = None) -> list:
    """Every `with _bb_step("<step>"):` node in the runner.

    `tree` is threaded through because the ordering test compares nodes by
    IDENTITY. Parsing twice produces two disjoint object graphs and `is` never
    matches, so the containment check silently found nothing and passed on a
    mutation that should have failed it — caught by that mutation, 8 Sep 2026.
    """
    out = []
    for node in ast.walk(tree if tree is not None else _tree()):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "_bb_step"
                    and call.args and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == step):
                out.append(node)
    return out


# ---------------------------------------------------------------------------
# (a) THE PRODUCES DECLARATION
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", PARAMS)
def test_the_step_declares_a_product_at_all(step):
    assert cm.produces(step), (
        f"{step} declares produces=[]. In core/cycle_map.py that means 'we do "
        f"not know', not 'it produces nothing' — on a BACKBONE step.")


@pytest.mark.parametrize("step", PARAMS)
def test_the_declaration_is_the_one_this_commit_established(step):
    assert cm.produces(step) == DARK_STEPS[step]["produces"], (
        f"{step} now declares {cm.produces(step)}; this table expects "
        f"{DARK_STEPS[step]['produces']}")


@pytest.mark.parametrize("step", PARAMS)
def test_the_step_is_backbone_so_the_declaration_matters(step):
    assert cm.is_backbone(step), (
        f"{step} is no longer backbone; re-check whether it belongs in this file")


@pytest.mark.parametrize("step", PARAMS)
def test_no_two_steps_claim_the_same_artifact(step):
    """Two producers of one file makes kept_promise ambiguous, and gives the
    notary's blindness check a second name to blame."""
    for artifact in DARK_STEPS[step]["produces"]:
        owners = [n for n, _i, _p, prod, _b in cm.STEPS if artifact in (prod or [])]
        assert owners == [step], f"{artifact} is claimed by {owners}"


@pytest.mark.parametrize("step", PARAMS)
def test_a_declared_file_is_not_a_directory_another_step_also_writes(step):
    """THE update_master LESSON. Declaring the TREE snapshots/master let
    kept_promise() pass on goal_score_latest.json — written by a different step
    in the same cycle. A promise another step can keep for you is not a promise.
    """
    for artifact in DARK_STEPS[step]["produces"]:
        path = REPO / artifact
        if not path.exists():
            continue
        if path.is_dir():
            # A directory is only acceptable when the step writes DATED files,
            # whose names move — config/cycle_phases.json._not_exhaustive.
            assert DARK_STEPS[step].get("dated_output"), (
                f"{step} declares the directory {artifact}; kept_promise takes "
                f"the newest file in a tree, so another step writing there "
                f"keeps this step's promise for it")


# ---------------------------------------------------------------------------
# (b) THE BLACKBOX TRACE — wiring
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", PARAMS)
def test_the_step_is_wrapped_in_a_blackbox_context(step):
    blocks = _bb_blocks(step)
    assert blocks, (
        f"{step} is not inside a _bb_step context. It is BACKBONE, and a hard "
        f"kill inside it would leave no evidence it had started.")
    marker = DARK_STEPS[step]["marker"]
    assert any(marker in ast.dump(b) for b in blocks), (
        f"the _bb_step block for {step} does not contain {marker!r}; the trace "
        f"would record a step that did nothing")


@pytest.mark.parametrize("step", PARAMS)
def test_the_trace_cannot_record_a_clean_end_for_a_failed_step(step):
    """THE ORDERING, AND IT IS NOT COSMETIC.

    For a GUARDED step the `with` must be a descendant of the try whose handler
    swallows — otherwise the except eats the exception before __exit__ sees it
    and blackbox records 'end' for a failure.

    For an UNGUARDED step the opposite must hold: no swallowing handler may sit
    between the `with` and the caller, or the same lie appears by another route.
    """
    # ONE tree for both halves. See _bb_blocks: identity comparison across two
    # parses is always False, and the check quietly tested nothing.
    tree = _tree()
    blocks = _bb_blocks(step, tree)
    assert blocks

    # every Try in the runner, with the set of With-nodes inside its body
    swallowing_tries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.handlers:
            swallowing_tries.append(node)

    for block in blocks:
        enclosing = [t for t in swallowing_tries
                     if any(block is w for w in ast.walk(t))]
        in_try_body = [t for t in enclosing
                       if any(block is w for b in t.body for w in ast.walk(b))]

        if DARK_STEPS[step]["guarded"]:
            assert in_try_body, (
                f"{step} has a fail-open except but its _bb_step context is not "
                f"inside the try body. The except would swallow the exception "
                f"before __exit__ saw it, and the blackbox would record a clean "
                f"'end' for a step that FAILED.")
        else:
            assert not enclosing, (
                f"{step} is unguarded by design, but its _bb_step context is now "
                f"inside a try with a handler. Either that handler swallows "
                f"failures — in which case the trace can record a clean 'end' "
                f"for a failure — or the step's fail-open behaviour changed, "
                f"which is a logic change this commit does not make.")


@pytest.mark.parametrize("step", PARAMS)
def test_the_step_still_is_not_a_run_step(step):
    """PINNED SO NOBODY LOWERS THE RATCHET ON THIS WORK.

    These steps reach the blackbox through _bb_step, NOT through _run(). So they
    are STILL counted by test_checkpoint_wiring's UNCOVERED_STEP_LIMIT, which
    counts steps absent from the _run() labels. Lowering that limit on the
    strength of this commit would be wrong: the crash trace is there, the _run()
    wrapper (survival gate, resume gate, model window, phase failure reporting)
    is not.
    """
    src = RUNNER.read_text(encoding="utf-8")
    run_labels = set(re.findall(r"_run\(\s*[\"']([A-Za-z0-9_]+)[\"']", src))
    assert step not in run_labels, (
        f"{step} now goes through _run(); lower UNCOVERED_STEP_LIMIT in "
        f"test/test_checkpoint_wiring.py in the same commit")


def test_the_uncovered_ratchet_was_not_lowered_by_this_work():
    src = (REPO / "test" / "test_checkpoint_wiring.py").read_text(encoding="utf-8")
    m = re.search(r"UNCOVERED_STEP_LIMIT\s*=\s*(\d+)", src)
    assert m, "the ratchet is gone"
    assert int(m.group(1)) == 30, (
        f"UNCOVERED_STEP_LIMIT is {m.group(1)}. These commits add a blackbox "
        f"trace, not _run() coverage, so the count of steps outside _run() has "
        f"not moved. If it was lowered for another reason, say which step.")


# ---------------------------------------------------------------------------
# (c) THE BLACKBOX TRACE — the real recorder, redirected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", PARAMS)
def test_a_successful_run_records_begin_then_end(step, tmp_path, monkeypatch):
    from core import blackbox

    log = tmp_path / "blackbox.jsonl"
    monkeypatch.setattr(blackbox, "LOG_PATH", str(log))

    with blackbox.step(step):
        pass

    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert [r["phase"] for r in rows] == ["begin", "end"]
    assert all(r["step"] == step for r in rows)
    assert rows[0]["pid"] and rows[0]["utc"]


@pytest.mark.parametrize("step", PARAMS)
def test_a_failure_records_begin_then_error_and_never_end(step, tmp_path,
                                                          monkeypatch):
    """A 'begin' with no 'end' IS the finding; an 'error' row names what went
    wrong. Neither may read as success."""
    from core import blackbox

    log = tmp_path / "blackbox.jsonl"
    monkeypatch.setattr(blackbox, "LOG_PATH", str(log))

    with pytest.raises(RuntimeError):
        with blackbox.step(step):
            raise RuntimeError(f"{step} blew up")

    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    phases = [r["phase"] for r in rows]
    assert phases == ["begin", "error"], phases
    assert "end" not in phases, (
        "a failed step recorded an 'end' — the trace would say it completed")
    assert rows[-1]["error_type"] == "RuntimeError"
    assert "blew up" in rows[-1]["error"]


def test_the_tests_never_write_to_the_live_blackbox():
    """LOG_PATH is a module constant and every test above redirects it. If one
    forgot, the live memory/blackbox.jsonl would gain fabricated rows — the
    record a human reads after a crash."""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    uses = src.count("blackbox.step(")
    redirects = src.count('monkeypatch.setattr(blackbox, "LOG_PATH"')
    assert redirects >= uses - 1, (
        f"{uses} uses of blackbox.step but only {redirects} LOG_PATH "
        f"redirections; one test may be writing to the live recorder")


# ---------------------------------------------------------------------------
# (d) NO STEP'S LOGIC CHANGED
# ---------------------------------------------------------------------------

def test_update_master_still_writes_exactly_one_file():
    """The function itself is untouched: one mkdir, one write_text, to the path
    this commit declared."""
    tree = _tree()
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "update_master")
    ops = [n.attr for n in ast.walk(fn)
           if isinstance(n, ast.Attribute)
           and n.attr in ("write_text", "write_bytes", "mkdir", "open")]
    assert sorted(ops) == ["mkdir", "write_text"], ops

    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "master_snapshot_latest.json" in literals
    assert "master" in literals and "snapshots" in literals


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
