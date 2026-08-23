#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_reaction.py — VERBATIM, AND OFF UNTIL ASKED.

The three the command names:
  * a fixture stream produces a stored record containing BOTH lines and answer;
  * a non-English answer is DISPLAYED and is NOT added to the exemplar pool;
  * with the flag off, no model call is made from any path.

Assertions about code parse it. Never grep.

    venv/Scripts/python.exe -m pytest test/test_reaction.py -v
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

from core import reaction as rx        # noqa: E402

LINES = [
    {"text": "12345.678  receptor.ram_percent    R  residual  82.5% "
             "base 79.31  signal +3.19 > 2.9652"},
    {"text": "12350.114  receptor.gpu_temp_c     R  anchor    57.0C "
             "base 51.20  drift +6.0 > 12.93"},
]


def _fake(monkeypatch, response, calls=None):
    import io
    import urllib.request

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _open(req, timeout=None):
        if calls is not None:
            calls.append(json.loads(req.data.decode("utf-8")))
        return _R(json.dumps({"response": response,
                              "eval_count": 12}).encode("utf-8"))
    monkeypatch.setattr(urllib.request, "urlopen", _open)


# ═══ OFF UNTIL ASKED ════════════════════════════════════════════════════════

def test_the_flag_is_off_in_the_committed_config():
    assert rx.enabled() is False
    d = json.loads((REPO / "config" / "reactions.json").read_text(
        encoding="utf-8"))
    assert d["reaction"]["enabled"] is False


def test_with_the_flag_off_no_model_call_is_made(monkeypatch):
    calls = []
    _fake(monkeypatch, "should never be reached", calls)
    r = rx.at_phase_boundary(LINES)
    assert r["asked"] is False
    assert r["skipped"] is True
    assert calls == [], "a model was called with the flag off"


def test_and_it_says_why_rather_than_pretending_nothing_happened():
    r = rx.at_phase_boundary(LINES)
    assert "reaction.enabled" in r["why"]
    assert r["n_lines"] == 2


def test_the_flag_file_is_protected():
    from safety.protected_paths import is_protected
    assert is_protected("config/reactions.json") is True


def test_the_cockpit_endpoint_never_asks():
    """The panel is a reader. The call belongs at a phase boundary."""
    tree = ast.parse((REPO / "cockpit" / "server.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "api_reaction")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for forbidden in ("ask", "react", "at_phase_boundary"):
        assert forbidden not in called, forbidden
    assert "history" in called


def test_no_module_calls_ask_or_react_unconditionally():
    import subprocess
    r = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                       capture_output=True, text=True)
    offenders = []
    for rel in r.stdout.splitlines():
        if rel in ("core/reaction.py",) or rel.startswith("test/"):
            continue
        try:
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8",
                                                    errors="replace"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr in ("ask", "react"):
                v = n.func.value
                if isinstance(v, ast.Name) and v.id in ("rx", "reaction"):
                    offenders.append((rel, n.lineno))
    assert not offenders, offenders


# ═══ BOTH LINES AND ANSWER, IN ONE RECORD ═══════════════════════════════════

def test_a_fixture_stream_stores_lines_and_answer_together(tmp_path, monkeypatch):
    out = tmp_path / "r.jsonl"
    _fake(monkeypatch, "Memory is climbing and the GPU has warmed.")
    rec = rx.react(LINES, path=out)
    assert rec["stored"] is True

    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["answer"] == "Memory is climbing and the GPU has warmed."
    assert len(row["lines"]) == 2
    assert "receptor.ram_percent" in row["lines"][0]
    assert row["n_lines"] == 2


def test_the_record_is_readable_as_one_thing(tmp_path, monkeypatch):
    """A record that kept only the answer would be an opinion with no evidence
    attached."""
    out = tmp_path / "r.jsonl"
    _fake(monkeypatch, "steady")
    rx.react(LINES, path=out)
    row = rx.history(1, path=out)[0]
    assert row["lines"] and row["answer"]


def test_the_raw_lines_are_sent_not_a_summary(tmp_path, monkeypatch):
    calls = []
    _fake(monkeypatch, "ok", calls)
    rx.react(LINES, path=tmp_path / "r.jsonl")
    prompt = calls[0]["prompt"]
    assert "receptor.ram_percent" in prompt
    assert "base 79.31" in prompt
    assert "signal +3.19" in prompt


def test_truncation_says_it_truncated():
    many = [{"text": "line {}".format(i)} for i in range(100)]
    f = rx.format_lines(many, limit=10)
    assert "not shown" in f
    assert "line 99" in f and "line 0" not in f


def test_no_lines_means_no_call(monkeypatch):
    calls = []
    _fake(monkeypatch, "x", calls)
    r = rx.ask([])
    assert r["asked"] is False and calls == []


# ═══ THE GATE DECIDES THE POOL, NEVER THE DISPLAY ═══════════════════════════

def test_a_non_english_answer_is_displayed(tmp_path, monkeypatch):
    """An answer that came back in Russian is a fact about the system. A panel
    that quietly drops it shows a system behaving better than it is."""
    out = tmp_path / "r.jsonl"
    _fake(monkeypatch, "Памет расте и дискът е под нивото си.")
    rec = rx.react(LINES, path=out)
    assert rec["displayed"] is True
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["answer"].startswith("Памет")
    assert row["displayed"] is True


def test_and_is_not_added_to_the_exemplar_pool(tmp_path, monkeypatch):
    _fake(monkeypatch, "Памет расте и дискът е под нивото си.")
    rec = rx.react(LINES, path=tmp_path / "r.jsonl")
    assert rec["exemplar"] is False
    assert rec["language"]["exemplar_ok"] is False
    assert "CYRILLIC" in rec["language"]["reason"]


def test_an_english_answer_is_both_displayed_and_poolable(tmp_path, monkeypatch):
    _fake(monkeypatch, "Memory is climbing and the disk crossed its notice level.")
    rec = rx.react(LINES, path=tmp_path / "r.jsonl")
    assert rec["displayed"] is True and rec["exemplar"] is True


def test_displayed_is_true_no_matter_what_the_gate_said(tmp_path, monkeypatch):
    for answer in ("Памет расте.", "内存正在增长。", "Memory climbs.", ""):
        _fake(monkeypatch, answer)
        rec = rx.react(LINES, path=tmp_path / "r.jsonl")
        assert rec["displayed"] is True, answer


def test_the_display_path_never_consults_the_gate():
    """Parsed: `displayed` must not depend on the language verdict."""
    tree = ast.parse((REPO / "core" / "reaction.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "react")
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets
                       if isinstance(t, ast.Subscript)
                       and isinstance(t.slice, ast.Constant)
                       and t.slice.value == "displayed"]
            if targets:
                assert isinstance(node.value, ast.Constant), (
                    "displayed is computed from something")
                assert node.value.value is True


# ═══ VERBATIM ═══════════════════════════════════════════════════════════════

def test_a_weak_answer_is_not_replaced_by_a_template(tmp_path, monkeypatch):
    """The most interesting thing this panel can produce is the discovery that
    the model has nothing useful to say about its own body."""
    _fake(monkeypatch, "ok")
    rec = rx.react(LINES, path=tmp_path / "r.jsonl")
    assert rec["answer"] == "ok"
    assert "template" not in rec["answer"].lower()


def test_an_empty_answer_is_stored_as_empty(tmp_path, monkeypatch):
    _fake(monkeypatch, "   ")
    rec = rx.react(LINES, path=tmp_path / "r.jsonl")
    assert rec["answer"] == ""
    assert "returned nothing" in rec["why"]


def test_the_answer_is_only_stripped_and_never_edited(tmp_path, monkeypatch):
    body = "Line one.\n\n  Line two with  odd   spacing."
    _fake(monkeypatch, "\n" + body + "\n")
    rec = rx.react(LINES, path=tmp_path / "r.jsonl")
    assert rec["answer"] == body


def test_the_page_renders_the_answer_without_clamping():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function drawReaction()", 1)[1][:2200]
    assert "r.answer" in block
    assert "substring" not in block and "slice(0," not in block
    assert "pre-wrap" in html


def test_the_panel_shows_the_gate_verdict_beside_the_answer():
    html = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    block = html.split("async function drawReaction()", 1)[1][:2200]
    assert "exemplar_ok" in block
    assert "exemplar: no" in block


# ── labels and failure ──────────────────────────────────────────────────────

def test_it_is_labelled_source_model_directed_self_mediation_model():
    assert (rx.SOURCE, rx.DIRECTED, rx.MEDIATION) == ("model", "self", "model")


def test_an_unreachable_model_never_raises(monkeypatch, tmp_path):
    import urllib.request

    def _boom(req, timeout=None):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    rec = rx.react(LINES, path=tmp_path / "r.jsonl")
    assert rec["asked"] is False
    assert "OSError" in rec["why"]


def test_the_record_is_durable():
    tree = ast.parse((REPO / "core" / "reaction.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "react")
    names = {a.name for n in ast.walk(fn)
             if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "append_json" in names


def test_the_selftest_passes():
    assert rx._selftest() == 0
