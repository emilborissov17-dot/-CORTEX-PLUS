"""
test/test_warm_core_restore.py — the core is back before a cycle, and after any other model.

25 Sep 2026. The 03:04 cycle found cortex-l1b-3b absent: on the evening of 24 Sep
source_registration called qwen3:8b five times and a qwen2.5:3b load followed, each
evicting the core on a 4 GB card, and CORTEX_WarmCore only ran at logon. The cycle
refused 178 local calls ("warm core absent").

Failure shapes: a spawn that goes ahead without checking the core; a pre-flight
that loads when the core is already resident (a needless load) or does not load
when it is absent; a call to another model outside a cycle that leaves that model
on the card; source_registration asking for the strongest qwen3 again.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import llm_door, model_window  # noqa: E402
import supervisor as sup  # noqa: E402

CORE = model_window.cycle_local_model()
_REAL_ENSURE = model_window.ensure_core          # conftest stubs these two;
_REAL_RESTORE = model_window.restore_core        # these tests test them


def _fake(monkeypatch, resident):
    loads = []
    state = set(resident)

    def keep(model, keep_alive, url=None, timeout=300.0):
        loads.append((model, keep_alive))
        if keep_alive == 0:
            state.discard(model)
        else:
            state.clear()
            state.add(model)
        return True

    monkeypatch.setattr(model_window, "_set_keep_alive", keep)
    monkeypatch.setattr(model_window, "resident_models", lambda url=None: set(state))
    monkeypatch.setattr(model_window, "ensure_core", _REAL_ENSURE)
    monkeypatch.setattr(model_window, "restore_core", _REAL_RESTORE)
    monkeypatch.delenv("CORTEX_IN_CYCLE", raising=False)
    monkeypatch.delenv("CORTEX_CYCLE_ID", raising=False)
    return loads, state


def test_preflight_loads_the_core_when_it_is_absent(monkeypatch):
    loads, state = _fake(monkeypatch, resident=["qwen2.5:3b"])
    said = sup._warm_core_preflight()
    assert loads == [(CORE, -1)], loads
    assert said.startswith("warm core reloaded in ") and CORE in state


def test_preflight_does_nothing_when_the_core_is_resident(monkeypatch):
    loads, _ = _fake(monkeypatch, resident=[CORE])
    said = sup._warm_core_preflight()
    assert loads == [], "a load was made for a core that was already resident"
    assert said == f"warm core resident ({CORE}), 0 reloads"


def test_a_call_to_8b_outside_a_cycle_ends_with_the_core_restored(monkeypatch):
    loads, state = _fake(monkeypatch, resident=[CORE])

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"message": {"content": "ok"}, "done_reason": "stop"}

    import requests

    def post(url, **k):
        state.clear()
        state.add("qwen3:8b")          # the 8b request evicts the core, as on the card
        return _R()

    monkeypatch.setattr(requests, "post", post)
    llm_door.post("pulse:x", "local:qwen3:8b", "qwen3:8b", "http://localhost:11434/api/chat", json={})
    assert ("qwen3:8b", 0) in loads, "the other model was not unloaded"
    assert loads[-1] == (CORE, -1) and state == {CORE}, loads


def test_a_call_to_the_core_restores_nothing(monkeypatch):
    loads, _ = _fake(monkeypatch, resident=[CORE])
    assert model_window.restore_core(CORE) is None and loads == []


def test_source_registration_asks_the_core():
    import inspect
    from core import source_registration as sr
    src = inspect.getsource(sr._semantic_rule)
    assert "cycle_local_model()" in src and "_pick_local_model()" not in src
