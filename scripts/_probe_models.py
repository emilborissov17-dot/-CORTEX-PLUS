#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/_probe_models.py — ask each provider what it actually serves today.

WHY THIS IS IN THE TREE
------------------------
On 2026-08-20 two of the four configured cloud models were dead upstream:

    llama-3.3-70b-versatile   decommissioned 2026-08-16 (free/dev tier)
    gemini-2.0-flash          decommissioned 2026-06-01

Neither failed in a way that said so. They 404'd inside the retry path, three
nights running, eating the 45-minute step ceiling. A decommission is a normal,
scheduled, announced event; it should be found by name in ten seconds, not
inferred from a cycle that ran out of clock.

Run this whenever a provider call starts failing, or before pinning a new id:

    PYTHONIOENCODING=utf-8 venv/Scripts/python.exe scripts/_probe_models.py

READ-ONLY. GET requests to public /models listings. Prints model ids only.
It never prints, logs or echoes a key.
"""
from __future__ import annotations

import pathlib
import re
import sys

import requests

BASE = pathlib.Path(__file__).resolve().parents[1]
ENV = BASE / ".env"
BACKEND = BASE / "core" / "groq_backend.py"

TIMEOUT = 30


def env_value(name: str) -> str | None:
    """Read one value out of .env without importing anything or printing it."""
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


def configured() -> dict[str, str]:
    """The ids as literally written in core/groq_backend.py right now.

    Read as text rather than imported, so the probe reports what is on disk and
    cannot be fooled by an env override at import time.
    """
    src = BACKEND.read_text(encoding="utf-8")

    def literal(name: str) -> str:
        m = re.search(rf'^{name}\s*=\s*"([^"]+)"', src, re.M)
        return m.group(1) if m else ""

    gemini_url = literal("GEMINI_API_URL")
    gemini = gemini_url.rsplit("/", 1)[-1].split(":")[0] if gemini_url else ""

    return {
        "groq": literal("GROQ_MODEL"),
        "cerebras": literal("CEREBRAS_MODEL"),
        "openrouter": literal("OPENROUTER_MODEL"),
        "gemini": gemini,
    }


# --------------------------------------------------------------------------
# Listings. Each returns {id: supports_chat}. Gemini is the odd one: its
# listing includes embedding, TTS and video models that cannot answer the
# :generateContent call the config makes.
# --------------------------------------------------------------------------

def list_openai_compatible(url: str, key: str | None) -> dict[str, bool]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return {m["id"]: True for m in r.json().get("data", [])}


def list_groq(key: str) -> dict[str, bool]:
    return list_openai_compatible("https://api.groq.com/openai/v1/models", key)


def list_cerebras(key: str) -> dict[str, bool]:
    return list_openai_compatible("https://api.cerebras.ai/v1/models", key)


def list_openrouter(key: str | None) -> dict[str, bool]:
    return list_openai_compatible("https://openrouter.ai/api/v1/models", key)


def list_gemini(key: str) -> dict[str, bool]:
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
    "groq": ("GROQ_API_KEY", list_groq, True),
    "cerebras": ("CEREBRAS_API_KEY", list_cerebras, True),
    "openrouter": ("OPENROUTER_API_KEY", list_openrouter, False),
    "gemini": ("GEMINI_API_KEY", list_gemini, True),
}


def main() -> int:
    cfg = configured()
    verdicts: list[tuple[str, str, str]] = []

    for provider, (env_name, lister, key_required) in PROVIDERS.items():
        want = cfg.get(provider, "")
        print()
        print("=" * 66)
        print(f"{provider.upper()} — configured: {want or '(not found)'}")
        print("=" * 66)

        key = env_value(env_name)
        if key_required and not key:
            print(f"{env_name} absent from .env — skipped")
            verdicts.append((provider, want, "SKIPPED (no key)"))
            continue

        try:
            listing = lister(key)
        except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
            print(f"probe failed: {type(exc).__name__}: {exc}")
            verdicts.append((provider, want, f"PROBE FAILED ({type(exc).__name__})"))
            continue

        for ident in sorted(listing):
            print(ident if listing[ident] else f"{ident}   (no generateContent)")

        print()
        if want in listing and listing[want]:
            print(f"configured id present and usable -> True")
            verdicts.append((provider, want, "LIVE"))
        elif want in listing:
            print(f"configured id present but cannot generateContent -> True/False")
            verdicts.append((provider, want, "PRESENT BUT NOT USABLE"))
        else:
            print(f"configured id present -> False   <-- DEAD LITERAL")
            verdicts.append((provider, want, "DEAD"))

    print()
    print("=" * 66)
    print("SUMMARY")
    print("=" * 66)
    for provider, want, verdict in verdicts:
        print(f"  {provider:12} {want:48} {verdict}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
