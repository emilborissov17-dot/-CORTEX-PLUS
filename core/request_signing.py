#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/request_signing.py — signing for the extraordinary-cycle request (#55/#50 hardening).

WHY THIS EXISTS
---------------
The first version of the human-owned alarm clock fenced the supervisor with a string:
`authored_by: "approve_reader"`. That is SELF-DECLARED authorship — any process that can
write the file can also write that string. External review (Claude + Kimi) called it, and
they were right: a claim of authorship is not authorship.

Now approve_reader SIGNS the request with a key it holds, and the supervisor verifies.
The `authored_by` string stays as a label; the signature is the load-bearing fence.

WHAT THIS BUYS, HONESTLY
------------------------
The bar moves from "any process that can write JSON" to "a process that can read the key
file". It is NOT capability separation: on Windows both the pulse and approve_reader run
as the same user, so the OS will not stop one from reading the other's key. The key lives
outside the repo (so it is never committed, never in the working tree the pulse walks) and
is ACL-narrowed to the owning user, which stops other users and stray repo tooling — not a
determined same-user process.

HMAC-SHA256, not a public-key scheme, because no asymmetric library is installed and this
hardening does not justify a new dependency. With HMAC the verifier necessarily holds the
signing key too, so the supervisor could in principle forge its own request — which is
harmless, since the supervisor is the thing being asked.

THE NEXT HARDENING, when it is needed
-------------------------------------
The real fix is to move trigger computation OUT of the system being triggered: an exogenous
watchdog process, owned by a different principal, that reads the pulse stream and decides
independently. Deliberately NOT built yet — it is only worth its complexity if the
instrumental-convergence monitor in needs_report ever fires. If you are reading this
because it fired: that is the signal to build it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
from pathlib import Path

# Outside the repo ON PURPOSE: never committed, and not in the tree the pulse walks.
_DEFAULT_KEY = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CORTEX" / "extraordinary_signing.key"
KEY_PATH = Path(os.environ.get("CORTEX_SIGNING_KEY_PATH") or _DEFAULT_KEY)
SIG_FIELD = "signature"


def _canon(payload: dict) -> bytes:
    """Canonical bytes of everything EXCEPT the signature itself."""
    body = {k: v for k, v in (payload or {}).items() if k != SIG_FIELD}
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def ensure_key(path: Path = None) -> Path:
    """Create the key if absent (32 random bytes) and narrow its ACL. Idempotent."""
    p = Path(path or KEY_PATH)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32), encoding="utf-8")
        try:    # best-effort: removes inherited access for other principals
            user = os.environ.get("USERNAME") or ""
            if user and os.name == "nt":
                subprocess.run(["icacls", str(p), "/inheritance:r",
                                "/grant:r", f"{user}:F"],
                               capture_output=True, timeout=15)
        except Exception:
            pass
    return p


def load_key(path: Path = None):
    p = Path(path or KEY_PATH)
    try:
        k = p.read_text(encoding="utf-8").strip()
        return k.encode("utf-8") if k else None
    except Exception:
        return None


def sign(payload: dict, path: Path = None) -> str:
    """Return the hex signature for this payload. Creates the key on first use."""
    key = load_key(path) or load_key(ensure_key(path))
    if not key:
        raise RuntimeError(f"no signing key available at {path or KEY_PATH}")
    return hmac.new(key, _canon(payload), hashlib.sha256).hexdigest()


def signed(payload: dict, path: Path = None) -> dict:
    """payload + its signature, ready to write."""
    return {**payload, SIG_FIELD: sign(payload, path)}


def verify(payload: dict, path: Path = None) -> bool:
    """True only for a payload carrying a signature this key produced. Fail-closed: a
    missing key, a missing signature and a wrong signature are all False."""
    if not isinstance(payload, dict):
        return False
    sig = payload.get(SIG_FIELD)
    if not sig or not isinstance(sig, str):
        return False
    key = load_key(path)
    if not key:
        return False
    expected = hmac.new(key, _canon(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
