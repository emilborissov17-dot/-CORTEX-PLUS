# -*- coding: utf-8 -*-
"""test/test_backend_league.py — the cloud order is measured (11 Sep 2026, Emil).

Pinned:
  * a backend that fails, truncates or is slow scores lower; a mind that reads the number scores higher
  * an unmeasured backend is placed right after the leader, never first on faith
  * groq_backend.ordered_backend_keys(): fresh league file wins, stale/malformed/unknown keys fall back
  * the NVIDIA-Kimi leg is absent from the chain without NVIDIA_API_KEY, and the model id is resolved
    from /v1/models (newest Kimi), never hard-coded
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))
import backend_league as BL  # noqa: E402
import core.groq_backend as gb  # noqa: E402

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


def _row(backend, outcome="ok", lat=5.0, finish="stop", status=None, model=None, days_ago=1):
    return {"ts": (NOW - timedelta(days=days_ago)).isoformat(), "backend": backend, "outcome": outcome,
            "latency_s": lat, "finish_reason": finish, "http_status": status, "model": model or backend}


def test_scores_reward_answers_and_reading():
    rows = ([_row("Groq", model="openai/gpt-oss-120b")] * 40 + [_row("Groq", "error", status=429)] * 10
            + [_row("OpenRouter", lat=40.0, finish="length")] * 20 + [_row("OpenRouter")] * 20
            + [_row("Gemini")] * 5 + [_row("Groq", days_ago=30)] * 100)          # outside the window
    lg = BL.league(rows, {"openai/gpt-oss-120b": 1.0}, now=NOW)
    t = lg["table"]
    assert t["groq"]["calls"] == 50 and t["groq"]["success"] == 0.8 and t["groq"]["rate_limited"] == 10
    assert t["groq"]["reads_number"] == 1.0
    assert t["openrouter"]["complete"] == 0.5 and t["groq"]["score"] > t["openrouter"]["score"]
    assert t["gemini"]["measured"] is False and t["nvidia"]["calls"] == 0
    assert lg["order"] == ["groq", "nvidia", "gemini", "openrouter"]       # unmeasured right after the leader


def test_no_data_keeps_the_default_order():
    assert BL.league([], {}, now=NOW)["order"] == BL.DEFAULT_ORDER


def test_groq_backend_reads_a_fresh_order_and_refuses_a_stale_or_bad_one(tmp_path):
    p = tmp_path / "order.json"
    p.write_text(json.dumps({"ts": NOW.isoformat(), "order": ["openrouter", "groq", "evil"]}), encoding="utf-8")
    assert gb.ordered_backend_keys(p, now=NOW) == ["openrouter", "groq", "nvidia", "gemini"]
    assert gb.ordered_backend_keys(p, now=NOW + timedelta(days=9)) == list(gb.DEFAULT_ORDER)
    p.write_text("not json", encoding="utf-8")
    assert gb.ordered_backend_keys(p, now=NOW) == list(gb.DEFAULT_ORDER)
    assert gb.ordered_backend_keys(tmp_path / "absent.json", now=NOW) == list(gb.DEFAULT_ORDER)


def test_nvidia_model_is_resolved_from_the_listing(monkeypatch):
    class R:
        def __init__(self, data): self._d = data
        def raise_for_status(self): pass
        def json(self): return self._d
    monkeypatch.setattr(gb, "_NVIDIA_MODEL", None)
    monkeypatch.setattr(gb.requests, "get", lambda *a, **k: R({"data": [{"id": "meta/llama-4"}, {"id": "moonshotai/kimi-k2-instruct"},
                                                                         {"id": "moonshotai/kimi-k2.5"}]}))
    assert gb._nvidia_model("k") == "moonshotai/kimi-k2.5"
    monkeypatch.setattr(gb, "_NVIDIA_MODEL", None)
    monkeypatch.setattr(gb.requests, "get", lambda *a, **k: R({"data": [{"id": "meta/llama-4"}]}))
    import pytest
    with pytest.raises(ValueError, match="no Kimi"):
        gb._nvidia_model("k")


def test_without_the_key_the_nvidia_leg_is_not_in_the_chain_and_refuses(monkeypatch):
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    assert '(k != "nvidia" or _has_nvidia)' in src                       # the guard where the chain is built
    monkeypatch.setattr(gb, "_load_key", lambda name: "")
    import pytest
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        gb._call_nvidia_kimi("hi", 10)
