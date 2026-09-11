# -*- coding: utf-8 -*-
"""test/test_consult_roster.py — the second opinion is a real Kimi when one is free (10 Sep 2026)."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load(monkeypatch, keys):
    gb = types.ModuleType("core.groq_backend")
    gb._load_key = lambda name: keys.get(name)
    monkeypatch.setitem(sys.modules, "core.groq_backend", gb)
    # `import core.groq_backend as gb` resolves through the `core` package attribute once the
    # real module has been imported by another test; patch that too, or the fake is bypassed.
    import core
    monkeypatch.setattr(core, "groq_backend", gb, raising=False)
    spec = importlib.util.spec_from_file_location("consult_under_test", REPO / "experiments" / "kimi_duel" / "consult.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, status, body, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


def _post_factory(calls, groq_status=200, groq_model="moonshotai/kimi-k2-instruct-0905"):
    def post(url, headers=None, json=None, timeout=None):
        calls.append((url, json["model"]))
        if "groq.com" in url:
            if groq_status != 200:
                return _Resp(groq_status, {}, "rate limited")
            return _Resp(200, {"model": groq_model, "choices": [{"message": {"content": "несъгласие"}}], "usage": {}})
        if "kimi" in json["model"]:
            return _Resp(404, {}, "This model is unavailable for free")     # measured on the machine, 10 Sep
        return _Resp(200, {"model": json["model"], "choices": [{"message": {"content": "резерва"}}], "usage": {}})
    return post


def test_groq_kimi_is_asked_first_and_is_labelled_kimi(monkeypatch):
    C = _load(monkeypatch, {"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": "o"})
    calls = []
    import requests
    monkeypatch.setattr(requests, "post", _post_factory(calls))
    r = C.ask_kimi("brief")
    assert r["ok"] and r["is_kimi"] and r["backend"].startswith("groq:moonshotai/kimi-k2")
    assert calls == [(C.GROQ_URL, C.GROQ_KIMI)]           # nothing else was asked
    assert r["cost_usd"] == 0.0


def test_a_busy_groq_falls_back_to_the_free_roster_and_says_it_is_not_kimi(monkeypatch):
    C = _load(monkeypatch, {"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": "o"})
    calls = []
    import requests
    monkeypatch.setattr(requests, "post", _post_factory(calls, groq_status=429))
    r = C.ask_kimi("brief")
    assert r["ok"] and r["is_kimi"] is False
    assert calls[0][0] == C.GROQ_URL and "openrouter" in calls[1][0]
    assert any("429" in t for t in r["tried"])


def test_no_groq_key_is_named_not_silent(monkeypatch):
    C = _load(monkeypatch, {"OPENROUTER_API_KEY": "o"})
    calls = []
    import requests
    monkeypatch.setattr(requests, "post", _post_factory(calls))
    r = C.ask_kimi("brief")
    assert "groq: GROQ_API_KEY missing" in r["tried"]


def test_a_groq_reply_served_by_a_non_kimi_model_is_not_called_kimi(monkeypatch):
    C = _load(monkeypatch, {"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": "o"})
    import requests
    monkeypatch.setattr(requests, "post", _post_factory([], groq_model="llama-3.3-70b"))
    r = C.ask_kimi("brief")
    assert r["ok"] and r["is_kimi"] is False


def test_nvidia_kimi_is_asked_first_when_its_key_exists(monkeypatch):
    C = _load(monkeypatch, {"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": "o", "NVIDIA_API_KEY": "n"})
    gb = sys.modules["core.groq_backend"]
    gb.NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
    gb._nvidia_model = lambda key: "moonshotai/kimi-k2.6"
    calls = []

    def post(url, **kw):
        calls.append(url)
        return _Resp(200, {"model": "moonshotai/kimi-k2.6", "choices": [{"message": {"content": "несъгласие"}}], "usage": {}})
    monkeypatch.setattr("requests.post", post)
    r = C.ask_kimi("brief")
    assert r["ok"] and r["is_kimi"] and r["backend"] == "nvidia:moonshotai/kimi-k2.6"
    assert calls == ["https://integrate.api.nvidia.com/v1/chat/completions"]
