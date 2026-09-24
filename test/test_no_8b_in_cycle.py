"""
test/test_no_8b_in_cycle.py — inside a cycle, no local call ever loads qwen3:8b.

24 Sep 2026: the 15:14 cycle spent 1594 s in 13 qwen3:8b brain calls and switched
local models four times on a 4 GB card. Inside a cycle there is now one local
model (core.model_window.cycle_local_model, cortex-l1b-3b) for every brain role
and for the ladder's local leg; a request for 8b is refused by name.

Failure shapes: brain.think, brain.attend or a ladder leg handing "qwen3:8b" to
Ollama while the cycle flag is set; the refusal happening silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

from core import brain, groq_backend, model_window  # noqa: E402

BIG = "qwen3:8b"


class _Reply:
    status_code = 200

    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._c}, "done_reason": "stop"}


def _capture(monkeypatch, tmp_path, content='{"stance": "go", "expect": "x", "serves_goal": "y"}'):
    sent = []

    def post(url, json=None, **kw):
        sent.append((json or {}).get("model"))
        return _Reply(content)

    monkeypatch.setattr(requests, "post", post)
    for name in ("JOURNAL", "PLAN", "REVIEWS", "STEP_LOG", "STANCE"):
        monkeypatch.setattr(brain, name, tmp_path / f"{name}.jsonl")
    monkeypatch.setattr(brain, "models", lambda: [BIG, "qwen2.5:3b", model_window.CYCLE_LOCAL_DEFAULT])
    monkeypatch.setattr(brain, "_pick_model", lambda: (BIG, "http://localhost:11434"))
    monkeypatch.setattr(brain, "_fast_model", lambda: BIG)
    monkeypatch.setattr(model_window, "_persist", lambda: None)
    # the warm core holds the cycle model (task #8); asserted in test_warm_core
    monkeypatch.setattr(__import__("core.llm_door", fromlist=["x"]), "_resident",
                        lambda base: {model_window.cycle_local_model()})
    return sent


def test_inside_a_cycle_the_model_sent_to_ollama_is_never_8b(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_IN_CYCLE", "2026-09-24T15:14:01+03:00")
    sent = _capture(monkeypatch, tmp_path)
    local = model_window.cycle_local_model()

    brain.think("judge of phase X", "is it fine?", remember_it=False)
    brain.attend("some_step")
    groq_backend._call_local_as(BIG, "hello", 64)
    groq_backend._call_local("hello", 64)
    assert model_window.local_model(want_big=True, purpose="t") == local

    assert sent, "nothing reached the (mocked) Ollama endpoint"
    assert BIG not in sent, sent
    assert set(sent) == {local}, sent
    assert model_window.REFUSED_8B in capsys.readouterr().out


def test_outside_a_cycle_8b_is_still_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv("CORTEX_IN_CYCLE", raising=False)
    monkeypatch.delenv("CORTEX_CYCLE_ID", raising=False)
    sent = _capture(monkeypatch, tmp_path)
    brain.think("reader outside the cycle", "is it fine?", remember_it=False)
    assert sent and sent[0] == BIG, sent
