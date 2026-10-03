# -*- coding: utf-8 -*-
"""test/test_ladder_local_only.py — the ladder has one rung: the local model (C-CLOUD-1 Step 2).

Emil, R45 (2 Oct 2026): "Нали нямаше да имаме външни LLM-и… и щяхме да работим само с
OpenClaw?" — "Защо го имаме изобщо… защо някой друг да мисли вместо мозъкът на системата?"

THE RULES: a call through core.local_llm reaches only the local model, even with every
outside key in the environment; when the local model does not answer the caller gets the
named failure (AllBackendsFailedError), never invented text; core.llm_door.post refuses an
address outside the machine before any socket is opened. The transport is injected.
"""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import local_llm as gb  # noqa: E402
from core import llm_door  # noqa: E402

OUTSIDE_KEYS = ("GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY")


class Reply:
    def __init__(self, status=200, content="Paris."):
        self.status_code, self._content = status, content

    def json(self):
        return {"message": {"content": self._content}}


@pytest.fixture
def transport(monkeypatch):
    for k in OUTSIDE_KEYS:
        monkeypatch.setenv(k, "test-key-not-real")
    seen = {"hosts": [], "reply": Reply()}

    def post(caller, backend, model, url, **kw):
        seen["hosts"].append(urllib.parse.urlparse(url).hostname)
        r = seen["reply"]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(llm_door, "post", post)
    from core import model_window as mw
    monkeypatch.setattr(mw, "guard_local", lambda model, purpose: model, raising=False)
    monkeypatch.setattr(mw, "is_open", lambda: False, raising=False)
    return seen


def test_a_call_with_every_outside_key_present_reaches_only_localhost(transport):
    out = gb.call_local_llm("What is the capital of France? One word.", max_tokens=16)
    assert str(out) == "Paris."
    assert transport["hosts"] and set(transport["hosts"]) <= {"localhost", "127.0.0.1"}, transport["hosts"]


def test_the_meta_names_the_local_model(transport):
    content, meta = gb.call_local_llm_meta("ping", max_tokens=16)
    assert str(meta["backend"]).startswith("local:")


def test_a_silent_local_model_is_the_named_failure_never_text(transport):
    transport["reply"] = Reply(status=500)
    with pytest.raises(gb.AllBackendsFailedError):
        gb.call_local_llm("ping", max_tokens=16)


def test_an_empty_local_answer_is_the_named_failure(transport):
    transport["reply"] = Reply(content="")
    with pytest.raises(gb.AllBackendsFailedError):
        gb.call_local_llm("ping", max_tokens=16)


def test_no_outside_backend_is_left_in_the_ladder():
    names = [n for n in vars(gb) if any(b in n.lower() for b in ("openrouter", "gemini", "nvidia", "cerebras"))]
    names += [n for n in vars(gb) if n in ("GROQ_API_URL", "GROQ_MODEL", "ordered_backend_keys",
                                            "DEFAULT_ORDER", "_load_key", "_is_cooling", "_set_cooldown")]
    assert names == []


def test_the_door_refuses_an_address_outside_the_machine(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("a socket was attempted"))
    with pytest.raises(llm_door.OutsideModelRefused, match="R45.*api.groq.com"):
        llm_door.post("t", "Groq", "m", "https://api.groq.com/openai/v1/chat/completions", json={})


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_restored_outside_rung_is_seen_by_the_host_check(transport, monkeypatch):
    real = gb.call_local_llm_meta

    def with_outside_rung(prompt, max_tokens=1024, purpose=None):
        llm_door.post("restored", "Groq", "m", "https://api.groq.com/openai/v1/chat/completions", json={})
        return real(prompt, max_tokens)
    monkeypatch.setattr(gb, "call_local_llm_meta", with_outside_rung)
    gb.call_local_llm("ping", max_tokens=16)
    assert "api.groq.com" in transport["hosts"], "the assertion above would see an outside host"


def test_mutation_without_the_host_rule_the_door_would_send(monkeypatch):
    import requests
    sent = []
    monkeypatch.setattr(llm_door, "_outside_host", lambda url: None)
    monkeypatch.setattr(requests, "post", lambda url, **k: sent.append(url) or Reply())
    try:
        llm_door.post("t", "Groq", "m", "https://api.groq.com/openai/v1/chat/completions", json={})
    except Exception:                                                # noqa: BLE001  whatever happens after
        pass
    assert sent, "with the host rule removed the request goes out: the refusal is the guard"
