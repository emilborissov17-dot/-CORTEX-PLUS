"""
test/test_no_ollama_writes_from_tests.py — the conftest net that keeps tests off the
live Ollama's residency (25 Sep 2026: two evictions of the warm core mid-cycle).

Rule: these tests must fail if conftest._no_ollama_writes is removed. Every model
name below is one Ollama does not have (NOT_A_MODEL), so a run WITHOUT the net asks
the live server for nothing it can load or unload - the mutation is safe to run.
Run on 25 Sep 2026 with the fixture body replaced by `return`: all three failed
(HTTP 404 from the live server for NOT_A_MODEL; the release recorded HTTPError, not
OllamaWriteRefused), and cortex-l1b-3b stayed resident.
"""
from __future__ import annotations

import urllib.request as ur

import pytest

NOT_A_MODEL = "no-such-model-for-tests:0"

from core import aggressive_cleanup as ac
from core import model_window as mw


def test_a_post_to_ollama_raises_in_tests():
    req = ur.Request("http://127.0.0.1:11434/api/generate", data=('{"model":"%s","keep_alive":0}' % NOT_A_MODEL).encode(),
                     headers={"Content-Type": "application/json"})
    with pytest.raises(RuntimeError, match="live Ollama refused"):
        ur.urlopen(req, timeout=1)


def test_a_requests_post_to_ollama_raises_in_tests():
    import requests
    with pytest.raises(RuntimeError, match="live Ollama refused"):
        requests.post("http://127.0.0.1:11434/api/generate",
                      json={"model": NOT_A_MODEL, "keep_alive": 0}, timeout=1)


def test_release_ollama_cannot_unload_from_a_test(monkeypatch):
    monkeypatch.setattr(mw, "is_open", lambda: False)

    class _PS:
        def read(self):
            return ('{"models": [{"name": "%s"}]}' % NOT_A_MODEL).encode()

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
    assert rec.get("errors") == [f"{NOT_A_MODEL}: OllamaWriteRefused"]
