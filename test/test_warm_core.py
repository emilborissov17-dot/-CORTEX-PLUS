"""
test/test_warm_core.py — inside a cycle no model is ever loaded.

Task #8 part 1, 24 Sep 2026. On the 19:45 cycle model_window.pin_small() loaded
qwen2.5:3b at boot and the brain then loaded cortex-l1b-3b over it - a reload the
card pays for. The warm core (tools/ollama_serve.ps1 -WarmCore, task CORTEX_WarmCore)
now holds the cycle's one model resident; the cycle only checks /api/ps.

Failure shapes, before the happy path: a local call in a cycle that goes out while
its model is not resident (that request IS a load); the refusal leaving no row, or a
row that says ok; model_window loading a model inside a cycle; the warm core's own
model unloaded by the cycle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import llm_door, model_window  # noqa: E402

CORE = model_window.cycle_local_model()
_REAL_RESIDENT = llm_door._resident      # conftest stubs it; these tests test it


class _Reply:
    status_code = 200

    @staticmethod
    def json():
        return {"message": {"content": "ok"}, "done_reason": "stop"}


def _fake_ollama(monkeypatch, resident):
    posts, gets = [], []
    import requests

    class _PS:
        @staticmethod
        def json():
            return {"models": [{"name": n} for n in resident]}

    monkeypatch.setattr(requests, "get", lambda url, **k: gets.append(url) or _PS())
    monkeypatch.setattr(requests, "post", lambda url, **k: posts.append((url, k.get("json"))) or _Reply())
    monkeypatch.setattr(llm_door, "_ps_cache", {})
    monkeypatch.setattr(llm_door, "_resident", _REAL_RESIDENT)
    return posts, gets


def _rows():
    return [json.loads(x) for x in llm_door.PROVENANCE.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_in_a_cycle_an_absent_model_is_refused_and_nothing_is_loaded(monkeypatch):
    monkeypatch.setenv("CORTEX_IN_CYCLE", "c")
    posts, gets = _fake_ollama(monkeypatch, resident=["qwen2.5:3b"])
    with pytest.raises(llm_door.WarmCoreAbsent):
        llm_door.post("brain:x", f"local:{CORE}", CORE, "http://localhost:11434/api/chat",
                      json={"model": CORE})
    assert posts == [], "a request went out for a model that is not resident - that is a load"
    assert gets and gets[0].endswith("/api/ps")
    row = _rows()[-1]
    assert row["outcome"] == "refused" and row["error"].startswith(model_window.WARM_CORE_ABSENT)


def test_in_a_cycle_a_resident_model_is_used(monkeypatch):
    monkeypatch.setenv("CORTEX_IN_CYCLE", "c")
    posts, _ = _fake_ollama(monkeypatch, resident=[CORE])
    llm_door.post("brain:x", f"local:{CORE}", CORE, "http://localhost:11434/api/chat", json={"model": CORE})
    assert len(posts) == 1 and _rows()[-1]["outcome"] == "ok"


def test_the_urllib_door_is_guarded_too(monkeypatch):
    monkeypatch.setenv("CORTEX_IN_CYCLE", "c")
    _fake_ollama(monkeypatch, resident=[])
    called = []
    with pytest.raises(llm_door.WarmCoreAbsent):
        llm_door.call("data_scout:x", f"local:{CORE}", CORE, lambda: called.append(1) or {})
    assert called == []


def test_outside_a_cycle_nothing_is_checked(monkeypatch):
    monkeypatch.delenv("CORTEX_IN_CYCLE", raising=False)
    monkeypatch.delenv("CORTEX_CYCLE_ID", raising=False)
    posts, gets = _fake_ollama(monkeypatch, resident=[])
    llm_door.post("pulse:x", "local:qwen3:8b", "qwen3:8b", "http://localhost:11434/api/chat", json={})
    assert len(posts) == 1 and gets == []


def test_model_window_loads_nothing_inside_a_cycle(monkeypatch):
    monkeypatch.setenv("CORTEX_IN_CYCLE", "c")
    opened = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: opened.append(a) or None)
    assert model_window.pin_small() is False
    assert model_window._set_keep_alive(CORE, 0) is False, "the cycle unloaded the warm core"
    assert opened == [], "model_window made a load/unload request for the warm core inside a cycle"
