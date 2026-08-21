#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_step_contract.py — A SWALLOWED ERROR MUST NOT LOOK LIKE SUCCESS.

THE DEFECT
-----------
_run() in fast_cycle_runner.py catches every exception and prints one line, and
ten more places in that file do `except Exception: pass`. So a step that
swallows its error and writes nothing is indistinguishable — in every artifact
the cycle leaves behind — from a step that did its job.

The measurement is the FOOTPRINT: which files the step touched, against which
files it usually touches.

    OK          wrote what it normally writes
    NO_EFFECT   returned without raising and touched none of them
    SLOW        past learned p95 x3, warned WHILE STILL RUNNING
    MISSING     no footprint and no baseline expecting one
    RAISED      threw, and the exception is kept
    UNKNOWN     fewer than WARMUP_CYCLES runs recorded

THE REQUIRED PROOF
-------------------
test_a_step_that_swallows_its_error_still_yields_no_effect reproduces the exact
shape: try / raise / except: pass, no writes. It must be NO_EFFECT.

    venv\\Scripts\\python.exe -m pytest test/test_step_contract.py -v
"""
from __future__ import annotations

import json
import pathlib
import time

import pytest

from core import step_contract as sc

REPO = pathlib.Path(__file__).resolve().parents[1]
CALLMAP_FIXTURE = REPO / "test" / "fixtures" / "step_callmap_2026-08-21.json"


@pytest.fixture
def sandbox(tmp_path):
    """A fake repo with one watched tree. Nothing here touches the real one."""
    (tmp_path / "memory").mkdir()
    return tmp_path


def contract(label, sandbox, **kw):
    kw.setdefault("announce", lambda *_: None)
    return sc.StepContract(label, base=sandbox,
                           baseline_path=sandbox / "baseline.json",
                           report_path=sandbox / "report.json",
                           watched=("memory",), **kw)


def warm_up(label, sandbox, writes=True, runs=None):
    """Give a step a baseline so it can be judged."""
    for i in range(runs or sc.WARMUP_CYCLES):
        with contract(label, sandbox) as c:
            if writes:
                (sandbox / "memory" / f"{label}.json").write_text(str(i),
                                                                  encoding="utf-8")
    return c


# ---------------------------------------------------------------------------
# (a) THE REQUIRED PROOF
# ---------------------------------------------------------------------------

def test_a_step_that_swallows_its_error_still_yields_no_effect(sandbox):
    """The exact shape from fast_cycle_runner.py: try / raise / except: pass."""
    warm_up("swallower", sandbox)

    with contract("swallower", sandbox) as c:
        try:
            raise RuntimeError("the thing that actually went wrong")
        except Exception:
            pass          # <- the defect, verbatim

    assert c.result["verdict"] == sc.NO_EFFECT, (
        f"\n  A STEP THAT ATE ITS ERROR AND WROTE NOTHING REPORTED "
        f"{c.result['verdict']}.\n"
        f"  Nothing raised, so every exception-based check says it worked. The\n"
        f"  footprint is the only thing that can tell them apart.\n"
    )
    assert "touched none" in c.result["why"]
    assert c.result["error"] is None, (
        "the step never raised out; the verdict must come from the footprint"
    )


def test_the_same_step_writing_normally_is_ok(sandbox):
    """POSITIVE CONTROL — a contract that always says NO_EFFECT is useless."""
    warm_up("writer", sandbox)
    with contract("writer", sandbox) as c:
        (sandbox / "memory" / "writer.json").write_text("fresh", encoding="utf-8")
    assert c.result["verdict"] == sc.OK


def test_a_step_that_writes_something_else_is_still_no_effect(sandbox):
    """Touching SOME file is not the same as doing your job."""
    warm_up("picky", sandbox)
    with contract("picky", sandbox) as c:
        (sandbox / "memory" / "unrelated.json").write_text("x", encoding="utf-8")
    assert c.result["verdict"] == sc.NO_EFFECT


# ---------------------------------------------------------------------------
# (b) Warmup
# ---------------------------------------------------------------------------

def test_the_verdict_is_unknown_until_there_is_a_baseline(sandbox):
    """Guessing before then would mark every step NO_EFFECT on the first night
    and teach everyone to ignore the whole thing."""
    for i in range(sc.WARMUP_CYCLES):
        with contract("fresh", sandbox) as c:
            pass
        assert c.result["verdict"] == sc.UNKNOWN, f"run {i + 1}"
        assert "warming up" in c.result["why"]


def test_after_warmup_it_starts_judging(sandbox):
    warm_up("judged", sandbox)
    with contract("judged", sandbox) as c:
        pass
    assert c.result["verdict"] != sc.UNKNOWN


def test_the_footprint_is_recorded_during_warmup(sandbox):
    warm_up("recorded", sandbox)
    baseline = json.loads((sandbox / "baseline.json").read_text(encoding="utf-8"))
    runs = baseline["recorded"]["runs"]
    assert len(runs) == sc.WARMUP_CYCLES
    assert all("memory/recorded.json" in r["touched"] for r in runs)


# ---------------------------------------------------------------------------
# (c) The other verdicts
# ---------------------------------------------------------------------------

def test_an_exception_that_escapes_is_recorded_as_raised(sandbox):
    warm_up("thrower", sandbox)
    with pytest.raises(ValueError):
        with contract("thrower", sandbox) as c:
            raise ValueError("out it goes")

    assert c.result["verdict"] == sc.RAISED
    assert "ValueError" in c.result["error"]


def test_a_step_with_no_baseline_and_no_footprint_is_missing(sandbox):
    for _ in range(sc.WARMUP_CYCLES):
        with contract("ghost", sandbox) as c:
            pass
    with contract("ghost", sandbox) as c:
        pass
    assert c.result["verdict"] == sc.MISSING


def test_slow_is_warned_while_the_step_is_still_running(sandbox):
    """A duration printed afterwards is an obituary. daily_analysis was killed
    at 1243s against a 900s ceiling with nothing said in between."""
    said = []
    for _ in range(sc.WARMUP_CYCLES):
        with contract("slowpoke", sandbox) as c:
            (sandbox / "memory" / "slowpoke.json").write_text("x", encoding="utf-8")

    # force a tiny learned p95 so the timer fires inside the test
    baseline = json.loads((sandbox / "baseline.json").read_text(encoding="utf-8"))
    for run in baseline["slowpoke"]["runs"]:
        run["seconds"] = 0.01
    (sandbox / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")

    with contract("slowpoke", sandbox, announce=said.append):
        time.sleep(0.3)

    warnings = [s for s in said if "SLOW" in s and "still running" in s]
    assert warnings, f"no warning was emitted while it ran: {said}"


# ---------------------------------------------------------------------------
# (d) usual_files is a majority, not a union
# ---------------------------------------------------------------------------

def test_a_one_off_file_does_not_become_a_requirement():
    """A step that once wrote something extra would otherwise be judged
    NO_EFFECT forever after for not writing it again."""
    record = {"runs": [
        {"touched": ["a", "b"]}, {"touched": ["a", "b"]},
        {"touched": ["a", "b", "once"]}, {"touched": ["a", "b"]},
    ]}
    assert sc.usual_files(record) == {"a", "b"}


def test_p95_needs_at_least_two_samples():
    assert sc.p95([1.0]) is None
    assert sc.p95([1.0, 2.0, 3.0, 100.0]) == 100.0


# ---------------------------------------------------------------------------
# (e) Substeps are attached on a non-OK verdict
# ---------------------------------------------------------------------------

def test_a_non_ok_verdict_carries_the_steps_substeps(sandbox):
    """So the reader does not start from a step name and 900 lines of runner."""
    callmap = sandbox / "callmap.json"
    callmap.write_text(json.dumps({"steps": [
        {"name": "wired", "substeps": [
            {"module": "agents.core.daily_analysis_agent", "symbol": "run",
             "file": "agents/core/daily_analysis_agent.py"}],
         "delegates_to": []}]}), encoding="utf-8")

    warm_up("wired", sandbox)
    with contract("wired", sandbox, callmap_path=callmap) as c:
        pass

    assert c.result["verdict"] != sc.OK
    assert c.result["substeps"][0]["module"] == "agents.core.daily_analysis_agent"


def test_an_ok_verdict_does_not_carry_them(sandbox):
    warm_up("quiet", sandbox)
    with contract("quiet", sandbox) as c:
        (sandbox / "memory" / "quiet.json").write_text("y", encoding="utf-8")
    assert c.result["verdict"] == sc.OK
    assert "substeps" not in c.result


def test_it_reads_a_real_callmap_for_a_real_step():
    """The map must actually answer for a step that exists.

    Reads the capture of 21 Aug 2026 (test/fixtures/step_callmap_2026-08-21.json,
    VERBATIM from memory/step_callmap.json, producer scripts/step_callmap.py). The
    live map is regenerable runtime state and is no longer tracked; what is guarded
    here is that a real map parses and answers for a real step, which does not
    depend on today's AST.
    """
    subs = sc.substeps_for("daily_analysis", callmap_path=CALLMAP_FIXTURE)
    assert subs, "the captured callmap has nothing for daily_analysis"
    assert any("daily_analysis_agent" in str(s.get("module")) for s in subs)


# ---------------------------------------------------------------------------
# (f) Wiring
# ---------------------------------------------------------------------------

def test_the_runner_wraps_every__run_in_a_contract():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "from core.step_contract import StepContract" in src
    assert "note_swallowed" in src, (
        "the runner's own except-block does not tell the contract it ate an error"
    )


def test_a_broken_contract_does_not_kill_the_step(sandbox, monkeypatch):
    """FAIL-OPEN. The contract is a measurement, not a gate."""
    monkeypatch.setattr(sc, "snapshot",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        with contract("boom", sandbox):
            pass
