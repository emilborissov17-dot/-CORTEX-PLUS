"""
test/test_llm_timeouts.py — per-leg timeouts come from measurement, and truncated is an error.

Task #19 (c), 24 Sep 2026. The 15:14 cycle: every cloud leg allowed a 60-120 s read
while Groq's measured p95 was 17.6 s, and 7 of 91 cloud "ok" answers were cut at
max_tokens and used as whole.

Failure shapes: a leg keeping its literal timeout; the door letting a caller's
timeout through for a governed leg; a truncated answer recorded or returned as ok;
the p95 computed over errors or truncations; a local model given the warm timeout
on its cold first call.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import llm_door  # noqa: E402
from core import groq_backend as gb  # noqa: E402

NOW = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)


def _rows(tmp_path, rows):
    p = tmp_path / "prov.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_recompute_is_max_floor_or_p95_times_1_5_over_ok_untruncated_rows(tmp_path):
    ts = (NOW - timedelta(hours=5)).isoformat()
    old = (NOW - timedelta(days=9)).isoformat()
    rows = [{"ts": ts, "backend": "Groq", "outcome": "ok", "latency_s": float(i)} for i in range(1, 21)]
    rows += [{"ts": ts, "backend": "Groq", "outcome": "error", "latency_s": 500.0},
             {"ts": ts, "backend": "Groq", "outcome": "ok", "finish_reason": "length", "latency_s": 400.0},
             {"ts": old, "backend": "Groq", "outcome": "ok", "latency_s": 300.0},
             {"ts": ts, "backend": "local:m", "outcome": "ok", "latency_s": 2.0}]
    out = tmp_path / "t.json"
    t = llm_door.recompute(_rows(tmp_path, rows), out, NOW)
    assert t["legs"]["Groq"]["p95_ok_s"] == 19.0 and t["legs"]["Groq"]["timeout_s"] == 28.5
    assert t["legs"]["local:m"]["timeout_s"] == 8.0, "the floor did not apply"
    assert json.loads(out.read_text(encoding="utf-8"))["legs"]["Groq"]["n"] == 20


def test_the_seed_applies_until_something_is_measured(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_door, "TIMEOUTS", tmp_path / "absent.json")
    assert llm_door.timeout_for("Groq") == 25.0
    assert llm_door.timeout_for("OpenRouter") == 45.0
    assert llm_door.timeout_for("local:x") == 60.0
    assert llm_door.timeout_for("Groq-Whisper") is None


def test_the_door_enforces_the_measured_timeout_over_the_callers(tmp_path, monkeypatch):
    t = tmp_path / "t.json"
    t.write_text(json.dumps({"legs": {"Groq": {"timeout_s": 25.0}, "local": {"timeout_s": 20.0}}}), encoding="utf-8")
    monkeypatch.setattr(llm_door, "TIMEOUTS", t)
    monkeypatch.setattr(llm_door, "_warm", set())
    got = []

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}

    import requests
    monkeypatch.setattr(requests, "post", lambda url, **k: got.append(k.get("timeout")) or _R())
    llm_door.post("t", "Groq", "m", "https://x", timeout=(10, 60))
    llm_door.post("t", "local:m", "m", "http://x", timeout=300)
    llm_door.post("t", "local:m", "m", "http://x", timeout=300)
    llm_door.post("t", "Groq-Whisper", "w", "https://x", timeout=(10, 600))
    assert got == [(10.0, 25.0), (10.0, 300.0), (10.0, 20.0), (10, 600)], got


def test_a_truncated_answer_is_an_error_row():
    assert llm_door._judge(200, {"finish_reason": "length", "reply_chars": 40})[0] == "error"
    assert llm_door._judge(200, {"finish_reason": "MAX_TOKENS", "reply_chars": 40})[0] == "error"
    assert llm_door._judge(200, {"finish_reason": "stop", "reply_chars": 40}) == ("ok", None)


def _ladder(monkeypatch, groq_replies, openrouter_reply=("fallback", {"finish_reason": "stop"})):
    calls = []

    def groq(prompt, max_tokens):
        calls.append(("groq", max_tokens))
        return groq_replies.pop(0)

    def openrouter(prompt, max_tokens):
        calls.append(("openrouter", max_tokens))
        return openrouter_reply

    monkeypatch.setattr(gb, "_call_groq", groq)
    monkeypatch.setattr(gb, "_call_openrouter", openrouter)
    monkeypatch.setattr(gb, "ordered_backend_keys", lambda: ["groq", "openrouter"])
    monkeypatch.setattr(gb, "_cooldowns", {})
    monkeypatch.setattr(gb, "_cooldown_hits", {})
    return calls


def test_truncated_once_is_retried_on_the_same_leg_with_twice_the_room(monkeypatch):
    calls = _ladder(monkeypatch, [("cut", {"finish_reason": "length"}), ("whole", {"finish_reason": "stop"})])
    out = gb.call_groq_meta("p", 100)
    text = out[0] if isinstance(out, tuple) else out
    assert text == "whole"
    assert calls == [("groq", 100), ("groq", 200)], calls


def test_truncated_twice_moves_to_the_next_leg_and_is_never_returned(monkeypatch):
    calls = _ladder(monkeypatch, [("cut", {"finish_reason": "length"}), ("cut again", {"finish_reason": "length"})])
    out = gb.call_groq_meta("p", 100)
    text = out[0] if isinstance(out, tuple) else out
    assert text == "fallback"
    assert calls == [("groq", 100), ("groq", 200), ("openrouter", 100)], calls


def test_no_ladder_leg_passes_its_own_timeout_to_the_door():
    tree = ast.parse((REPO / "core" / "groq_backend.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "post" and getattr(node.func.value, "id", "") == "llm_door":
            assert not any(k.arg == "timeout" for k in node.keywords), \
                f"groq_backend.py:{node.lineno} passes a literal timeout to the door"
