"""
test/test_llm_dead_legs.py — a leg with no ok answer in 24 h leaves the ladder by evidence.

Task #19 (d), 24 Sep 2026. A leg with 0 ok rows in the last 24 h of provenance is
skipped; once per night its first call goes through as a probe; the rest of the
night it is skipped, and exactly one provenance row per leg per night says so.

Failure shapes: a dead leg tried on every call; a leg skipped with no row, or with
a row per call; a successful probe skipped on the next call; the probe never
repeated on a later night; a live leg skipped.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import llm_door  # noqa: E402
from core import groq_backend as gb  # noqa: E402

NIGHT1 = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)


def _prov_rows():
    if not llm_door.PROVENANCE.exists():
        return []
    return [json.loads(x) for x in llm_door.PROVENANCE.read_text(encoding="utf-8").splitlines() if x.strip()]


def _ok_row(backend, when):
    llm_door.PROVENANCE.write_text(json.dumps({"ts": when.isoformat(), "backend": backend,
                                               "outcome": "ok", "latency_s": 1.0}) + "\n", encoding="utf-8")


def test_a_leg_with_an_ok_answer_in_24h_is_used():
    _ok_row("Groq", NIGHT1 - timedelta(hours=3))
    assert llm_door.leg_gate("Groq", now=NIGHT1) == "use"


def test_a_dead_leg_is_probed_once_a_night_then_skipped_with_one_row():
    _ok_row("NVIDIA", NIGHT1 - timedelta(hours=30))           # outside the 24 h window
    assert llm_door.leg_gate("NVIDIA", now=NIGHT1) == "probe"
    assert llm_door.leg_gate("NVIDIA", now=NIGHT1 + timedelta(minutes=5)) == "skip"
    assert llm_door.leg_gate("NVIDIA", now=NIGHT1 + timedelta(minutes=9)) == "skip"
    skips = [r for r in _prov_rows() if r.get("error") == llm_door.SKIPPED]
    assert len(skips) == 1 and skips[0]["backend"] == "NVIDIA" and skips[0]["outcome"] == "refused"
    assert llm_door.leg_gate("NVIDIA", now=NIGHT1 + timedelta(days=1)) == "probe", \
        "a dead leg was not re-probed on the next night"


def _ladder(monkeypatch, openrouter):
    calls = []

    def groq(prompt, max_tokens):
        calls.append("groq")
        raise RuntimeError("down")

    def orouter(prompt, max_tokens):
        calls.append("openrouter")
        return openrouter()

    monkeypatch.setattr(gb, "_call_groq", groq)
    monkeypatch.setattr(gb, "_call_openrouter", orouter)
    monkeypatch.setattr(gb, "_call_local_as", lambda m, p, t: ("local answer", {}))
    monkeypatch.setattr(gb, "ordered_backend_keys", lambda: ["groq", "openrouter"])
    monkeypatch.setattr(gb, "_cooldowns", {})
    monkeypatch.setattr(gb, "_cooldown_hits", {})
    monkeypatch.setattr(gb, "_set_cooldown", lambda *a, **k: None)
    _ok_row("Groq", datetime.now(timezone.utc) - timedelta(hours=1))   # Groq alive, OpenRouter dead
    return calls


def test_a_successful_probe_is_not_skipped_on_the_next_call(monkeypatch):
    calls = _ladder(monkeypatch, lambda: ("x", {"finish_reason": "stop"}))
    gb.call_groq_meta("p", 50)
    gb.call_groq_meta("p", 50)
    assert calls.count("openrouter") == 2, calls


def test_a_failed_probe_leaves_the_leg_skipped_for_the_night(monkeypatch):
    def dead():          # transient: a 402 would make backend_policy disable the leg first
        raise ConnectionError("connection reset")
    calls = _ladder(monkeypatch, dead)
    gb.call_groq_meta("p", 50)
    gb.call_groq_meta("p", 50)
    assert calls.count("openrouter") == 1, calls
    assert any(r.get("error") == llm_door.SKIPPED and r["backend"] == "OpenRouter" for r in _prov_rows())
