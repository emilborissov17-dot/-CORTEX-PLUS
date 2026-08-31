#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_llm_models_exist.py — A DECOMMISSION MUST BE REPORTED BY NAME.

WHAT WENT WRONG (measured 20 August 2026)
------------------------------------------
Two of the four configured cloud models had been switched off upstream:

    llama-3.3-70b-versatile   decommissioned 2026-08-16 (free/dev tier)
    gemini-2.0-flash          decommissioned 2026-06-01

Nothing said so. Both ids sat in core/groq_backend.py as string literals, and
the calls 404'd inside the retry path — three nights running, eating the
45-minute step ceiling. The cycle did not report "this model is gone"; it
reported that it had run out of time.

A decommission is a scheduled, announced, entirely ordinary event. The cost of
finding it should be ten seconds, not three nights. This test turns it into a
named failure: the id, the provider, and what to run next.

HOW IT FAILS SAFE
------------------
No key in the environment -> skip, not fail, so CI without secrets stays green.
Network or auth trouble -> skip, because that is not a decommission and must not
cry wolf. The ONLY thing that turns this red is a provider answering normally
with a listing that does not contain the id we have pinned.

MARKED `network` (21 Aug 2026). It is the only module in test/ that makes a
live outbound request, so it is the only one CI excludes with -m "not network".
The skip-without-keys behaviour above is kept anyway: CI is not the only place
without a network, and a marker is a routing hint, not a safety mechanism.

NEGATIVE CONTROL (proven both ways before commit)
--------------------------------------------------
Point GROQ_MODEL at a fabricated id -- "llama-does-not-exist-70b" -- and
test_the_configured_model_is_live[groq] goes RED naming that id. Restore the
real id and it goes GREEN. Run recorded in the commit message.

WHAT THIS DOES NOT DO
----------------------
It asserts the id is SERVED, not that it is any good, and not that it answers
within the caller's token budget. Both new models are reasoning models that
spend tokens thinking before they emit content; a call site with a small
max_tokens can still get an empty answer from a perfectly live model. That is a
different defect and is not what this file measures.

    venv\\Scripts\\python.exe -m pytest test/test_llm_models_exist.py -v
"""
from __future__ import annotations

import pathlib
import re

import pytest

requests = pytest.importorskip("requests", reason="requests is needed to reach a provider")

# Every test in this module reaches a real provider. Registered in pytest.ini;
# CI excludes it with -m "not network".
pytestmark = pytest.mark.network

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "core" / "groq_backend.py"
ENV = REPO / ".env"

TIMEOUT = 30
PROBE = "venv\\Scripts\\python.exe scripts/_probe_models.py"


# ---------------------------------------------------------------------------
# Reading the configuration — as text, never by importing
# ---------------------------------------------------------------------------
# core/groq_backend.py performs network calls and reads keys at import time in
# some paths. This test only needs the literals, so it reads them as source.
# That also means the test sees what is ON DISK, which is what ships.

def _literal(name: str) -> str:
    src = BACKEND.read_text(encoding="utf-8")
    m = re.search(rf'^{name}\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else ""


def configured_model(provider: str) -> str:
    if provider == "gemini":
        url = _literal("GEMINI_API_URL")
        return url.rsplit("/", 1)[-1].split(":")[0] if url else ""
    return _literal({"groq": "GROQ_MODEL",
                     "openrouter": "OPENROUTER_MODEL"}[provider])


def env_value(name: str) -> str | None:
    """Read one value from .env. Never returned to the caller for printing."""
    if not ENV.exists():
        return None
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'") or None
    return None


# ---------------------------------------------------------------------------
# Listings. {model_id: can_it_answer_a_generation_call}
# ---------------------------------------------------------------------------

def _openai_compatible(url: str, key: str | None) -> dict[str, bool]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return {m["id"]: True for m in r.json().get("data", [])}


def _gemini(key: str) -> dict[str, bool]:
    """Gemini's listing includes embedding, TTS and video models that cannot
    serve the :generateContent call the config makes, so the method matters."""
    out: dict[str, bool] = {}
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    params = {"key": key, "pageSize": 200}
    while True:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        for m in payload.get("models", []):
            ident = m.get("name", "").removeprefix("models/")
            out[ident] = "generateContent" in m.get("supportedGenerationMethods", [])
        token = payload.get("nextPageToken")
        if not token:
            break
        params = {"key": key, "pageSize": 200, "pageToken": token}
    return out


PROVIDERS = {
    "groq": ("GROQ_API_KEY", True,
             lambda k: _openai_compatible("https://api.groq.com/openai/v1/models", k)),
    "openrouter": ("OPENROUTER_API_KEY", False,
                   lambda k: _openai_compatible("https://openrouter.ai/api/v1/models", k)),
    "gemini": ("GEMINI_API_KEY", True, _gemini),
}


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_the_configured_model_is_live(provider: str):
    """The pinned id must appear in what the provider says it serves today."""
    env_name, key_required, lister = PROVIDERS[provider]
    want = configured_model(provider)

    assert want, (
        f"no model id could be read for {provider} out of core/groq_backend.py. "
        f"The literal was renamed or reformatted; this test reads it by regex."
    )

    key = env_value(env_name)
    if key_required and not key:
        pytest.skip(f"{env_name} not in .env — cannot ask {provider} what it serves")

    try:
        listing = lister(key)
    except Exception as exc:  # noqa: BLE001
        # Not a decommission. Never fail on this, or the test cries wolf and
        # gets muted, which is how the original defect survived a month.
        pytest.skip(f"{provider} listing unreachable ({type(exc).__name__}) — not a decommission")

    assert listing, f"{provider} returned an empty listing — treating as unreachable"

    assert want in listing, (
        f"\n"
        f"  MODEL GONE: {provider} no longer serves {want!r}.\n"
        f"  It is pinned in core/groq_backend.py and every call to it will fail.\n"
        f"  This is a decommission, not an outage — fix the literal, do not retry.\n"
        f"  {len(listing)} ids are being served right now; run:  {PROBE}\n"
    )

    assert listing[want], (
        f"\n"
        f"  {provider} still lists {want!r}, but it cannot serve a generation\n"
        f"  call — it is an embedding/TTS/video model. The configured URL calls\n"
        f"  :generateContent on it, which will fail. Run:  {PROBE}\n"
    )


def test_every_configured_provider_has_a_model_literal():
    """Cheap, offline, always runs: a provider whose literal went missing would
    otherwise skip its way to green everywhere."""
    missing = [p for p in PROVIDERS if not configured_model(p)]
    assert not missing, (
        f"no model id readable for {missing} in core/groq_backend.py — "
        f"the literals were renamed, and the live checks above would skip silently"
    )
