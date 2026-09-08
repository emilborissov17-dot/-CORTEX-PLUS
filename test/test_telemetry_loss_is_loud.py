#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_telemetry_loss_is_loud.py — A DEGRADED COMPONENT MUST NOT LOOK HEALTHY.

THE DEFECT THIS GUARDS
-----------------------
agents/core/self_modifier.py opened with:

    try:
        from memory.runtime_telemetry import record_experience as _rec
    except Exception:
        _rec = lambda *a, **k: None

If that import failed — a missing psutil, a syntax error, a circular import —
every _rec() call afterwards succeeded, returned None and wrote nothing.
self_modifier would go on reporting SUCCESS and FAILED for patch after patch
while memory/runtime_experiences.json stayed frozen, and NOTHING anywhere would
say why.

The staleness would then be blamed on the notary refusals — a story that is
already true, verified 2026-09-08 (35 refusals out of 35 since 2026-08-17) — so
the second cause would hide perfectly behind the first. Two causes, one visible.

A degraded component is allowed. A degraded component indistinguishable from a
healthy one is not.

THE FORBIDDEN FALLBACK, BOTH ENDS OF IT
----------------------------------------
Returning a silent None is forbidden. Raising is equally forbidden: losing
telemetry must not cost the patch run, only stop being invisible. Both ends are
pinned below — test_the_replacement_is_not_silent and
test_losing_telemetry_does_not_cost_the_run.

    venv\\Scripts\\python.exe -m pytest test/test_telemetry_loss_is_loud.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# (a) THE MUTATION TEST — restore the lambda and this goes red
# ---------------------------------------------------------------------------

def test_the_replacement_is_not_silent(capsys, monkeypatch, tmp_path):
    """Simulate the import having failed, then call the recorder the module
    installs. It must PRINT and it must leave a durable trace.

    Restore `_rec = lambda *a, **k: None` and this fails on the first assert:
    a lambda prints nothing and records nothing.
    """
    import agents.core.self_modifier as sm
    from core import blackbox

    written = []
    monkeypatch.setattr(blackbox, "record",
                        lambda step, phase="mark", **extra:
                            written.append((step, phase, extra)))

    rec = sm._telemetry_unavailable("ModuleNotFoundError: No module named 'psutil'")
    out = rec("SUCCESS", {"message": "patch written", "problem": "axis drift"})

    printed = capsys.readouterr().out
    assert "TELEMETRY LOST" in printed, (
        "\n  TELEMETRY WAS LOST IN SILENCE.\n"
        "  The recorder installed when memory.runtime_telemetry cannot be\n"
        "  imported returned without printing anything, which is exactly the\n"
        "  no-op lambda this test exists to keep out. self_modifier would report\n"
        "  SUCCESS while runtime_experiences.json never moved, and the staleness\n"
        "  would be blamed on the notary refusals instead.\n"
        f"  stdout was: {printed!r}\n")
    assert "psutil" in printed, "the import error is not named"
    assert "SUCCESS" in printed, "the lost event is not named"
    assert "runtime_experiences.json" in printed, (
        "the artifact that will not move is not named, so a reader cannot "
        "connect the message to the stale file")

    assert written, (
        "nothing durable was written; a printed line dies with the terminal, "
        "and this is read after the fact")
    step, phase, extra = written[-1]
    assert step == "self_modifier"
    assert phase == "telemetry_unavailable"
    assert "psutil" in extra["import_error"]
    assert extra["lost_event"] == "SUCCESS"
    assert out is None, "the return contract changed; callers ignore the value"


def test_the_import_failure_itself_is_recorded_not_only_the_calls(monkeypatch):
    """STRUCTURAL. Two things must be traced, not one: the moment the import
    failed, and each experience subsequently lost. With only the second, a night
    where self_modifier is refused before run() — which is every night since
    2026-08-17 — would record nothing at all, and the broken import would stay
    invisible for as long as the gate stayed shut."""
    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    tries = [n for n in tree.body if isinstance(n, ast.Try)
             and any(isinstance(b, ast.ImportFrom)
                     and b.module == "memory.runtime_telemetry" for b in n.body)]
    assert tries, "the telemetry import is no longer a module-level try"
    handler_src = ast.dump(tries[0].handlers[0])
    assert "blackbox" in handler_src, (
        "the import failure itself is not written to the blackbox; only the "
        "later calls would be traced, and on a refused night there are none")
    assert "telemetry_import_failed" in handler_src


def test_the_no_op_lambda_is_gone_for_good():
    """The exact shape of the original defect, pinned. `lambda *a, **k: None`
    bound to the telemetry recorder is the thing that must never come back."""
    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == "_rec" for t in node.targets):
            continue
        assert not isinstance(node.value, ast.Lambda), (
            "_rec is bound to a lambda again. If that lambda returns None the "
            "component is degraded and indistinguishable from a healthy one.")


# ---------------------------------------------------------------------------
# (b) non-fatal — the other forbidden end
# ---------------------------------------------------------------------------

def test_losing_telemetry_does_not_cost_the_run(monkeypatch):
    """Raising here would turn a missing dependency into a dead self_modifier.
    Loud, never fatal."""
    import agents.core.self_modifier as sm
    from core import blackbox

    def _boom(*a, **k):
        raise OSError("blackbox disk full")

    monkeypatch.setattr(blackbox, "record", _boom)
    rec = sm._telemetry_unavailable("ImportError: circular")
    assert rec("ERROR", {"message": "x"}) is None      # must not raise


def test_even_the_last_resort_speaks(capsys, monkeypatch):
    """A recorder whose own failure is silent is the same defect one level
    down."""
    import agents.core.self_modifier as sm
    from core import blackbox

    monkeypatch.setattr(blackbox, "record",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    sm._telemetry_unavailable("ImportError: circular")("ERROR", {})
    printed = capsys.readouterr().out
    assert "blackbox could not record" in printed, printed


# ---------------------------------------------------------------------------
# (c) the healthy path is still the healthy path
# ---------------------------------------------------------------------------

def test_when_the_import_works_the_real_writer_is_used():
    """POSITIVE CONTROL. Without this, a module that always installed the
    fallback would pass everything above."""
    import agents.core.self_modifier as sm

    assert sm.TELEMETRY_IMPORT_ERROR is None, (
        f"memory.runtime_telemetry does not import in this repo: "
        f"{sm.TELEMETRY_IMPORT_ERROR}")
    assert sm._rec.__module__ == "memory.runtime_telemetry", (
        "the fallback is installed even though the import succeeded")


def test_the_error_is_readable_from_outside_the_module():
    """A module-level flag, so a caller or a report can ask 'is telemetry live
    here?' instead of inferring it from a file that has not moved."""
    import agents.core.self_modifier as sm
    assert hasattr(sm, "TELEMETRY_IMPORT_ERROR")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
