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

WHAT HAS SINCE BEEN BUILT, AND WHAT HAS NOT
-------------------------------------------
Trigger computation now lives OUTSIDE the component that benefits from it:
experiments/watchdog/trigger_watchdog.py reads the pulse's raw signal, applies thresholds
it never computes, and proposes. That closes the "the escalating process decides whether
to escalate" hole.

It does NOT close co-residence. The watchdog, approve_reader and the pulse all run as the
same OS user, on the same file system, from editable code, and this key is readable by any
of them. That remains open and is recorded as:

    BACKLOG #58 — escalation capability boundary
    Dedicated service account for trigger_watchdog + approve_reader; NTFS ACL on this key
    restricted to that account; consider DPAPI/TPM for the key material. Until then the
    separation is organisational, not enforced.
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


REQUIRED_EVIDENCE = ("pre_composite", "post_composite", "delta")
REQUIRED_ANOMALY_EVIDENCE = ("anomaly_leaf_hash", "source_url", "rule_violated")


def evidence_digest(evidence: dict) -> str:
    """SHA-256 over the canonical evidence block.

    This exists so the verifier can RECOMPUTE the digest from the raw fields rather than
    trust a digest handed to it. The digest is itself inside the signed payload, so the
    chain is: raw fields -> recomputed digest -> must equal the signed digest -> signature
    must verify. Changing any displayed number breaks it at the first step."""
    return hashlib.sha256(json.dumps(evidence or {}, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def evidence_complete(evidence: dict, keys=()) -> tuple:
    """(ok, missing). Raw fields are mandatory: a human asked to approve an escalation must
    see the numbers the decision was made on, not a sentence the system composed about
    them. Anomaly-triggered escalations additionally need the leaf hash, the source and
    the violated rule — the three things that make the claim checkable."""
    ev = evidence or {}
    need = list(REQUIRED_EVIDENCE)
    if any("anomaly" in str(k) for k in (keys or [])):
        need += list(REQUIRED_ANOMALY_EVIDENCE)
    missing = [k for k in need if ev.get(k) is None]
    return (not missing), missing


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
