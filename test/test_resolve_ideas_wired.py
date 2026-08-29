# -*- coding: utf-8 -*-
"""ITEM 11 — the idea scorer is actually called by the cycle.

tools/resolve_ideas.py was on disk, verified, and CALLED BY NOTHING: 437
hypotheses written by the pulse over weeks, zero ever graded. A generator with
no scorer is a system that can only agree with itself. 226 horizons fall on
2026-09-02, which is why this is wired now.

These tests hold the wiring, not the arithmetic — the tool's own --selftest
(9/9) covers the verdict logic and the queue records its --as-of run. What is
tested here is the part that was missing: that something calls it, that all
three step maps know about it, and that it can never write over the claims it
is judging.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tools import resolve_ideas as ri  # noqa: E402


def _digest(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


_LIVE_BEFORE = {p.as_posix(): _digest(p) for p in (ri.IDEAS, ri.OUT, ri.HISTORY)}


# ── the wiring, in all three places ────────────────────────────────────────

def _beats():
    tree = ast.parse((BASE / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    out = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "beat" and len(n.args) > 1
                and all(isinstance(a, ast.Constant) for a in n.args[:2])):
            out[n.args[0].value] = n.args[1].value
    return out


def test_the_cycle_calls_it_at_all():
    """The whole of ITEM 11. Before this, nothing did."""
    assert "resolve_ideas" in _beats()


def test_it_runs_after_the_series_it_reads():
    """It grades ideas against memory/axis_history.json, which trend_tracker
    writes at index 3. Running before that would judge today's claims against
    yesterday's series."""
    b = _beats()
    assert float(b["resolve_ideas"]) > float(b["trend_tracker"])


def test_all_three_step_maps_know_about_it():
    """ITEM 7.1 declared its step in one map and not the other, and the first
    cycle that ran it recorded an unmapped checkpoint. Three maps, one step."""
    assert "resolve_ideas" in _beats()

    phases = json.loads((BASE / "config" / "cycle_phases.json").read_text(encoding="utf-8"))["phases"]
    g = phases["G_LEARN"]
    assert any(s["name"] == "resolve_ideas" for s in g["steps"])
    assert "memory/idea_resolutions.jsonl" in g["produces"]

    from core import cycle_map
    assert any(s[0] == "resolve_ideas" for s in cycle_map.STEPS)


def test_the_step_resolves_through_the_map_and_is_not_unmapped():
    from core import cycle_map
    resolved = cycle_map.resolve("resolve_ideas")
    assert resolved and resolved[0] == "resolve_ideas"


# ── the separation that matters ────────────────────────────────────────────

def test_the_verdict_file_is_not_the_claim_file():
    """A verdict must never be written back over the claim it judges."""
    assert ri.OUT != ri.IDEAS
    assert ri.OUT.name == "idea_resolutions.jsonl"
    assert ri.IDEAS.name == "idea_stream.jsonl"


def test_the_tool_never_opens_the_idea_stream_for_writing():
    """By AST, not by trust: no write path in the module targets IDEAS."""
    src = (BASE / "tools" / "resolve_ideas.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            # IDEAS.write_text(...) / IDEAS.open("w")
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    and f.value.id == "IDEAS"):
                assert f.attr not in ("write_text", "write_bytes", "unlink"), (
                    f"the tool calls IDEAS.{f.attr} — it must only ever read the claims")
            # open(IDEAS, "w")
            if isinstance(f, ast.Name) and f.id == "open" and n.args:
                a0 = n.args[0]
                if isinstance(a0, ast.Name) and a0.id == "IDEAS":
                    mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                    assert "w" not in str(mode) and "a" not in str(mode), (
                        "the tool opens the idea stream for writing")


def test_a_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "OUT", tmp_path / "idea_resolutions.jsonl")
    import datetime as dt
    res = ri.run(dt.date(2026, 9, 30), False)
    assert res["summary"]["wrote"] is False
    assert not (tmp_path / "idea_resolutions.jsonl").exists()


def test_write_appends_and_never_truncates(tmp_path, monkeypatch):
    out = tmp_path / "idea_resolutions.jsonl"
    out.write_text('{"idea_ts": "PRE-EXISTING"}\n', encoding="utf-8")
    monkeypatch.setattr(ri, "OUT", out)
    import datetime as dt
    ri.run(dt.date(2026, 9, 30), True)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"idea_ts": "PRE-EXISTING"}', (
        "the first line was overwritten — this file is append-only")
    assert len(lines) > 1


def test_an_idea_already_resolved_is_not_resolved_twice(tmp_path, monkeypatch):
    """Idempotence, because the cycle runs it every day against the same file."""
    out = tmp_path / "idea_resolutions.jsonl"
    monkeypatch.setattr(ri, "OUT", out)
    import datetime as dt
    first = ri.run(dt.date(2026, 9, 30), True)["summary"]
    second = ri.run(dt.date(2026, 9, 30), True)["summary"]
    assert first["due_now"] > 0, "the fixture needs something due to be meaningful"
    assert second["due_now"] == 0, (
        "a second run re-graded ideas the first had already written down")
    assert second["already_resolved"] == first["due_now"]


# ── live state ─────────────────────────────────────────────────────────────

def test_the_live_idea_files_are_untouched():
    for path, before in _LIVE_BEFORE.items():
        after = _digest(pathlib.Path(path))
        assert after == before, f"{path} moved during the test run"
