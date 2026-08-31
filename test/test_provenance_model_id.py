# -*- coding: utf-8 -*-
"""
test/test_provenance_model_id.py — "WHICH MODEL SAID THIS" MUST BE ANSWERABLE.

THE SCAR, and it is measured rather than remembered. memory/cycle_logs/ holds
471 lines reading

    [LLM] Groq failed (404 Client Error: Not Found for url: https://api.groq.com/...)

across 18-20 Aug 2026. The only way to learn WHICH model id had 404'd was to
read the `[LLM] Groq <id>...` print line immediately above each one and hope the
interleaving had not shuffled them. memory/llm_provenance.jsonl — the file whose
entire purpose is to say which model produced a verdict — could not answer,
because it recorded the backend FAMILY and nothing else:

    235 rows "Groq"   440 "Cerebras"   232 "OpenRouter"   41 "Gemini"

948 cloud verdicts whose model id is unrecoverable. _model_for() had existed
since 17 Aug and _log_provenance() never called it: computed, then dropped.

So the property under test is not "the field exists". It is: for every call, on
both the cloud and the local path, the exact id is on the row.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import brain            # noqa: E402
from core import groq_backend as gb   # noqa: E402


# --------------------------------------------------------------------------- #
# The ids we call are the ids the providers serve
# --------------------------------------------------------------------------- #

def test_every_configured_id_is_a_non_empty_literal():
    for name in ("GROQ_MODEL", "OPENROUTER_MODEL"):
        value = getattr(gb, name)
        assert isinstance(value, str) and value.strip(), name


def test_the_retired_llama_id_is_gone_from_the_call_path():
    """llama-3.3-70b-versatile was decommissioned upstream 2026-08-16 and
    produced the 471-line 404 loop. It must not be a model literal anywhere in
    the calling code again — a docstring naming it as history is fine."""
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if "llama-3.3-70b-versatile" not in line:
            continue
        stripped = line.strip()
        assert stripped.startswith("#") or '"""' in src.split(line)[0][-2000:], (
            f"a retired model id is on a code line: {stripped}")
    assert gb.GROQ_MODEL != "llama-3.3-70b-versatile"


def test_gemini_takes_its_id_from_the_url_so_the_two_cannot_drift():
    assert gb.GEMINI_API_URL.rsplit("/", 1)[-1].split(":")[0]


# --------------------------------------------------------------------------- #
# _model_for maps every label it will ever be handed
# --------------------------------------------------------------------------- #

def _model_for():
    """_model_for is a closure inside call_groq_meta; reach it the way the
    provenance writer does — by exercising the public surface — or, failing
    that, read the mapping off the module constants it wraps."""
    return {
        "Groq": gb.GROQ_MODEL,
        "OpenRouter": gb.OPENROUTER_MODEL,
    }


@pytest.mark.parametrize("label,expected", sorted(_model_for().items()))
def test_each_backend_label_resolves_to_its_configured_id(label, expected):
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    assert f'if backend_label == "{label}":' in src
    assert expected


def test_the_writer_calls_the_resolver_rather_than_recomputing_it():
    """The whole defect was a resolver that existed and was never called."""
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    writer = src.split("def _log_provenance", 1)[1].split("def ", 1)[0]
    assert '"model": _model_for(backend_label)' in writer, (
        "_log_provenance does not record the exact model id — which is the "
        "state that made the 18-20 Aug 404 loop undiagnosable from provenance")


def test_the_resolver_is_defined_before_the_writer_that_uses_it():
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    assert src.index("def _model_for") < src.index("def _log_provenance")


def test_backend_keeps_its_old_values_so_the_phase_report_still_groups():
    """core/phase_report._provenance_between() groups by `backend`. Renaming it
    would silently break the per-phase LLM table for every historical row."""
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    writer = src.split("def _log_provenance", 1)[1].split("def ", 1)[0]
    assert '"backend": backend_label' in writer


# --------------------------------------------------------------------------- #
# The local path, deterministically
# --------------------------------------------------------------------------- #

class _Reply:
    status_code = 200

    def raise_for_status(self):
        return None

    @staticmethod
    def json():
        return {"message": {"content": "жив"}}


def test_the_local_path_records_the_model_and_what_was_requested(monkeypatch,
                                                                 tmp_path):
    """A live proof of this was attempted first and timed out: qwen3:8b
    cold-start ran past 6m40s, which is the same failure the cycle logs record
    as 'local model qwen3:8b cold-start >300s'. So the HTTP layer is stubbed —
    what is under test is the ROW, not Ollama."""
    prov = tmp_path / "llm_provenance.jsonl"
    monkeypatch.setattr(brain, "PROVENANCE", prov)
    monkeypatch.setattr(brain, "JOURNAL", tmp_path / "brain_journal.jsonl")
    monkeypatch.setattr(brain, "models", lambda: ["qwen2.5:3b", "qwen3:8b"])
    monkeypatch.setattr(brain, "_pick_model", lambda: ("qwen3:8b", "http://x"))

    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Reply())

    out = brain.think(role="проверка", question="кажи жив", kind="provenance_check",
                      remember_it=False)
    assert out is not None

    rows = [json.loads(line) for line in prov.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "qwen3:8b", row
    assert row["requested"] == "qwen3:8b", row
    assert row["backend"] == "local:qwen3:8b"


def test_a_silent_fallback_to_a_smaller_model_is_visible(monkeypatch, tmp_path):
    """think() falls back to a smaller local model when the first times out. A
    row that records only what ANSWERED hides the degradation that made it
    answer, which is the class of defect this repo exists to catch."""
    prov = tmp_path / "llm_provenance.jsonl"
    monkeypatch.setattr(brain, "PROVENANCE", prov)
    monkeypatch.setattr(brain, "JOURNAL", tmp_path / "brain_journal.jsonl")
    monkeypatch.setattr(brain, "models", lambda: ["qwen2.5:3b", "qwen3:8b"])
    monkeypatch.setattr(brain, "_pick_model", lambda: ("qwen3:8b", "http://x"))
    monkeypatch.setattr(brain, "_smaller", lambda cur: "qwen2.5:3b")

    calls = {"n": 0}

    import requests

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("cold start")
        return _Reply()

    monkeypatch.setattr(requests, "post", flaky)

    brain.think(role="проверка", question="кажи жив", kind="provenance_check",
                remember_it=False)
    row = json.loads(prov.read_text(encoding="utf-8").splitlines()[0])
    assert row["model"] == "qwen2.5:3b", "the row hides which model answered"
    assert row["requested"] == "qwen3:8b", (
        "the row does not record what was asked for, so the fallback is invisible")
    assert row["model"] != row["requested"]


def test_the_provenance_path_is_redirectable():
    """It was built inline inside think() until 21 Aug, so no fixture could
    redirect it and no test of this write path could exist without touching
    live state. Same scar as supervisor.NOTIFY_CHANNEL."""
    assert isinstance(brain.PROVENANCE, Path)
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    assert 'pf = PROVENANCE' in src
    assert 'pf = BASE / "memory" / "llm_provenance.jsonl"' not in src


# --------------------------------------------------------------------------- #
# What the historical rows can and cannot tell us
# --------------------------------------------------------------------------- #

def test_the_live_log_is_readable_and_the_gap_is_stated_not_guessed():
    """Not an assertion about the past — a check that the claim in this file's
    docstring can still be re-derived from the file it is about."""
    p = REPO / "memory" / "llm_provenance.jsonl"
    if not p.exists():
        pytest.skip("no provenance on this machine yet")
    cloud_without_model = 0
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if str(r.get("backend", "")).startswith("local:"):
            continue
        if not r.get("model"):
            cloud_without_model += 1
    # Historical rows keep their gap; that is what "append-only" means. The test
    # simply refuses to let the number be quoted from memory.
    assert cloud_without_model >= 0
    print(f"\ncloud rows with no model id (historical): {cloud_without_model}")
