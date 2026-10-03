# -*- coding: utf-8 -*-
"""test/test_self_profile_truth.py — the system describes itself as it is (C-CLOUD-2 Step 4).

core/homeostasis.build_self_profile() said the system had "LLM synthesis via Groq + Gemini",
"audio transcription via Groq Whisper API", "web intelligence" and "data_scout" — all gone
— and read profile["apis"]["groq"], a key C-CLOUD-1 deleted, so the body gate assess()
raised KeyError (defect class A). THE RULE: every capability names the module that backs it,
and that module exists; the limitations and apis name nothing that is gone. The profile is
written to tmp_path; nothing here touches memory/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import homeostasis as H  # noqa: E402

GONE = ("groq", "gemini", "openrouter", "cerebras", "whisper api", "web intelligence", "web_intelligence",
        "data_scout", "cloud api")


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "SELF_PROFILE_PATH", tmp_path / "self_profile.json")
    return H.build_self_profile()


def test_the_profile_builds_without_raising(profile):
    assert isinstance(profile["capabilities"], list) and isinstance(profile["limitations"], list)


def test_every_capability_names_a_module_that_exists():
    assert H.CAPABILITIES and H.missing_capability_modules(H.CAPABILITIES) == []


def test_no_line_of_the_profile_names_something_gone(profile):
    lines = profile["capabilities"] + profile["limitations"] + list(profile["apis"])
    bad = [l for l in lines if any(g in str(l).lower() for g in GONE)]
    assert bad == [], bad


def test_the_capability_lines_carry_their_module(profile):
    for text, module in H.CAPABILITIES:
        assert any(module in line for line in profile["capabilities"]), (text, module)


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_capability_naming_a_missing_file_is_found():
    caps = list(H.CAPABILITIES) + [("audio transcription", "core/whisper_bridge.py")]
    assert H.missing_capability_modules(caps) == ["core/whisper_bridge.py"]


def test_mutation_an_old_line_would_be_seen():
    assert any(g in "llm synthesis via groq (llama-3.3-70b) + gemini fallback" for g in GONE)
