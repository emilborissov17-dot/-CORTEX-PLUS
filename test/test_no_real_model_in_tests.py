# -*- coding: utf-8 -*-
"""test/test_no_real_model_in_tests.py — no test reaches a real model (C-CLOUD-2 Step 5).

Decided after the CLOUD report (3 Oct 2026): test_registration_wall reached the real local model
from a test_script_suite subprocess. The rules are held by the tests below: a request to the
model's port inside a test is refused and fails the test at teardown; core/llm_door refuses any
model request on the genuine transport while CORTEX_NO_REAL_MODEL=1 (set by conftest and passed to
subprocesses by test_script_suite); a test that needs the real model carries @pytest.mark.real_model.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))

import requests.sessions as _sessions  # noqa: E402
# captured at import, before any fixture patches it: the genuine transport
REAL_SESSION_REQUEST = _sessions.Session.request


def test_the_suite_runs_with_the_model_switch_off():
    assert os.environ.get("CORTEX_NO_REAL_MODEL") == "1"


def test_the_door_refuses_a_model_request_while_the_switch_is_off(monkeypatch):
    """With the genuine transport in place (no stub), the door refuses before any socket."""
    import requests
    import requests.api
    import requests.sessions
    from core import llm_door
    monkeypatch.setattr(requests, "post", requests.api.post)
    monkeypatch.setattr(requests.sessions.Session, "request", REAL_SESSION_REQUEST)
    with pytest.raises(llm_door.RealModelRefused, match="CORTEX_NO_REAL_MODEL"):
        llm_door.post("t", "local:m", "m", "http://localhost:11434/api/chat", json={})


def test_a_direct_request_to_the_port_is_refused_and_recorded(request):
    import requests
    import conftest
    with pytest.raises(conftest.OllamaWriteRefused):
        requests.post("http://127.0.0.1:11434/api/generate", json={}, timeout=1)
    hits = conftest.model_net_hits(request.node)
    assert hits and "11434" in hits[-1]
    hits.clear()                              # this test made it on purpose; teardown must not fail it


def test_the_script_suite_passes_the_switch_to_its_subprocesses():
    import ast
    tree = ast.parse((REPO / "test" / "test_script_suite.py").read_text(encoding="utf-8"))
    assert "CORTEX_NO_REAL_MODEL" in ast.unparse(tree)


@pytest.mark.real_model
def test_a_real_model_test_is_skipped_unless_asked():
    pytest.fail("a real_model test ran without CORTEX_REAL_MODEL=1")


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_without_the_switch_the_door_would_send(monkeypatch):
    import requests
    from core import llm_door
    monkeypatch.delenv("CORTEX_NO_REAL_MODEL", raising=False)
    sent = []

    class Reply:
        status_code = 200

        def json(self):
            return {"message": {"content": "x"}}
    monkeypatch.setattr(requests, "post", lambda url, **k: sent.append(url) or Reply())
    monkeypatch.setattr(llm_door, "_require_warm", lambda *a, **k: None, raising=False)
    try:
        llm_door.post("t", "local:m", "m", "http://localhost:11434/api/chat", json={})
    except Exception:                                                # noqa: BLE001
        pass
    assert sent, "with the switch off the request goes out: the refusal is the guard"


def test_mutation_a_swallowed_refusal_still_fails_the_test(request):
    import requests
    import conftest
    try:
        requests.post("http://localhost:11434/api/chat", json={}, timeout=1)
    except Exception:                                                # noqa: BLE001  what a module does
        pass
    hits = conftest.model_net_hits(request.node)
    assert hits, "the swallowed request was not recorded: teardown could not fail the test"
    hits.clear()
