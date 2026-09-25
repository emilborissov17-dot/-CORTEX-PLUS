"""
test/test_no_ollama_writes_from_tests.py — the conftest net that keeps tests off the
live Ollama's residency (25 Sep 2026: two evictions of the warm core mid-cycle).

Mutation check: delete conftest._no_ollama_writes and both tests fail - the first
because urlopen no longer raises, the second because release_ollama then really
unloads (on a machine with a resident model) or the assertion on the recorded
refusal fails.
"""
from __future__ import annotations

import urllib.request as ur

import pytest

from core import aggressive_cleanup as ac
from core import model_window as mw


def test_a_post_to_ollama_raises_in_tests():
    req = ur.Request("http://127.0.0.1:11434/api/generate", data=b'{"model":"x","keep_alive":0}',
                     headers={"Content-Type": "application/json"})
    with pytest.raises(RuntimeError, match="live Ollama refused"):
        ur.urlopen(req, timeout=1)


def test_a_requests_post_to_ollama_raises_in_tests():
    import requests
    with pytest.raises(RuntimeError, match="live Ollama refused"):
        requests.post("http://127.0.0.1:11434/api/generate",
                      json={"model": "qwen2.5:3b", "keep_alive": 4200}, timeout=1)


def test_release_ollama_cannot_unload_from_a_test(monkeypatch):
    monkeypatch.setattr(mw, "is_open", lambda: False)

    class _PS:
        def read(self):
            return b'{"models": [{"name": "cortex-l1b-3b:latest"}]}'

    real = ur.urlopen

    def ps_only(url, data=None, *a, **k):
        target = url.full_url if isinstance(url, ur.Request) else str(url)
        if target.endswith("/api/ps") and data is None:
            return _PS()
        return real(url, data, *a, **k)      # the conftest net underneath

    monkeypatch.setattr(ur, "urlopen", ps_only)
    monkeypatch.setattr("time.sleep", lambda s: None)
    rec = ac.release_ollama(apply=True)
    assert rec["released"] == []
    assert rec.get("errors") == ["cortex-l1b-3b:latest: OllamaWriteRefused"]
