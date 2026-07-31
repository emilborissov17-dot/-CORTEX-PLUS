#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/watchdog/trigger_watchdog.py — the process that decides is not the process
that benefits.

THE CHAIN, AFTER THE SPLIT
--------------------------
  pulse_continuum  emits memory/pulse_signal.json     (raw numbers, no judgement)
  trigger_watchdog reads it, applies thresholds from config/watchdog.json, VERIFIES any
                   cited penumbra leaf hash against the chain, and — only then — writes a
                   PROPOSAL to the needs report                       (the cry)
  Emil            replies "OK <id>"                                   (the decision)
  approve_reader  signs the request (raw evidence + digest)           (the authority)
  supervisor      recomputes the digest, verifies the signature, consumes, acts
This module touches none of the last three. It can cry; it cannot act.

HONEST FRAMING — READ THIS BEFORE TRUSTING IT
---------------------------------------------
This is DEFENSE-IN-DEPTH WITH A KNOWN CO-RESIDENCE VULNERABILITY, not a capability
boundary. The watchdog runs as the same OS user, on the same file system, under the same
kernel, from code the system can edit. Anything able to modify this file can modify what
it decides. What the split buys is that escalation logic no longer sits inside the
component whose necessity score rises when it escalates — a real reduction in the most
likely failure mode, and not a wall.

The minimal REAL boundary is a dedicated service account plus an NTFS ACL on the signing
key, or a hardware-backed key (DPAPI/TPM). That is recorded as a named backlog item:

    BACKLOG #58 — escalation capability boundary
    Run trigger_watchdog + approve_reader under a dedicated service account; ACL the
    signing key to that account only; consider DPAPI/TPM for the key material. Until then
    the separation here is organisational, not enforced.

THREE CAPABILITY WALLS, asserted in code below and each covered by a fixture. They are
speed bumps with names, not boundaries:
  (a) CANNOT execute a cycle  — imports neither fast_cycle_runner nor the supervisor
  (b) CANNOT sign             — never imports core.request_signing, never reads the key
  (c) CANNOT write the file supervisor.read_extraordinary() consumes

  venv/Scripts/python.exe experiments/watchdog/trigger_watchdog.py        # one pass
  venv/Scripts/python.exe experiments/watchdog/trigger_watchdog.py --dry  # decide, no write
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "experiments" / "sensorium"))

CONFIG      = REPO / "config" / "watchdog.json"
SIGNAL      = REPO / "memory" / "pulse_signal.json"
PROPOSALS   = REPO / "memory" / "pulse_cycle_requests.json"

# WALL (c), named: the watchdog knows this path only so it can assert it never writes it.
# Only approve_reader, on Emil's OK, may create the file the supervisor consumes.
FORBIDDEN_OUTPUT = REPO / "memory" / "extraordinary_request.json"

REQUIRED_EVIDENCE = ("pre_composite", "post_composite", "delta")
ANOMALY_EVIDENCE = ("anomaly_leaf_hash", "source_url", "rule_violated")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def thresholds() -> dict:
    """READ, never computed.

    There is deliberately no code in this module that looks at history, fits a baseline,
    or adapts a trigger point. A watchdog that could learn its own threshold would be
    tuning the very thing it exists to check, and the split would be theatre. Every value
    below comes verbatim from config/watchdog.json, with a literal fallback."""
    c = _load(CONFIG, {})
    return {
        "composite_move_min": float(c.get("composite_move_min", 0.02)),
        "propose_on_verified_anomaly": bool(c.get("propose_on_verified_anomaly", True)),
        "min_gap_minutes": float(c.get("min_gap_minutes", 60)),
        "signal_max_age_minutes": float(c.get("signal_max_age_minutes", 30)),
    }


def read_signal(now: datetime = None) -> dict:
    """The pulse's raw signal, if it is fresh. A stale signal is not evidence of anything
    current, and proposing a cycle off it would be proposing off the past."""
    sig = _load(SIGNAL, None)
    if not isinstance(sig, dict):
        return {}
    t = thresholds()
    now = now or datetime.now(timezone.utc)
    try:
        age_min = (now - datetime.fromisoformat(sig["ts"])).total_seconds() / 60
    except Exception:
        return {}
    if age_min > t["signal_max_age_minutes"] or age_min < -1:
        return {}
    return sig


def verify_anomaly(sig: dict) -> tuple:
    """(ok, why). RECOMPUTE the cited leaf hash from the penumbra chain.

    A hash that arrives from another process is a claim about evidence, not evidence. The
    watchdog re-derives it from the chain and its file; if it does not match, no proposal
    is forwarded and the reason is named. This is the one place the watchdog is allowed to
    trust something the pulse said — so it doesn't."""
    h = sig.get("anomaly_leaf_hash")
    if not h:
        return False, "no anomaly cited"
    try:
        import sensorium
        if sensorium.leaf_hash_matches(h, sig.get("anomaly_drop_id")):
            return True, "leaf hash verified against the penumbra chain"
        return False, (f"leaf hash {str(h)[:12]}… does NOT match the penumbra chain — "
                       f"refusing to forward a proposal on an unverifiable citation")
    except Exception as e:
        return False, f"cannot verify leaf hash ({type(e).__name__}) — refusing"


def decide(sig: dict, now: datetime = None) -> dict:
    """Should this signal become a proposal? Deterministic, thresholds read from file."""
    t = thresholds()
    now = now or datetime.now(timezone.utc)
    if not sig:
        return {"propose": False, "why": "no fresh signal"}

    last = (_load(PROPOSALS, {}) or {}).get("pending", {}).get("ts")
    if last:
        try:
            gap = (now - datetime.fromisoformat(last)).total_seconds() / 60
            if gap < t["min_gap_minutes"]:
                return {"propose": False,
                        "why": f"a proposal is already pending ({gap:.0f}m old, minimum "
                               f"gap {t['min_gap_minutes']:.0f}m)"}
        except Exception:
            pass

    keys, reasons = [], []
    delta = sig.get("delta")
    if isinstance(delta, (int, float)) and abs(delta) > t["composite_move_min"]:
        keys.append("composite_moved")
        reasons.append(f"composite_moved: {sig.get('pre_composite')} -> "
                       f"{sig.get('post_composite')} (delta {delta}, threshold "
                       f"{t['composite_move_min']})")

    if sig.get("anomaly_leaf_hash") and t["propose_on_verified_anomaly"]:
        ok, why = verify_anomaly(sig)
        if ok:
            keys.append("penumbra_model_anomaly_new")
            reasons.append(f"penumbra_model_anomaly_new: {why}")
        else:
            return {"propose": False, "why": f"anomaly refused — {why}"}

    if not keys:
        return {"propose": False, "why": "nothing over threshold"}
    return {"propose": True, "keys": keys, "reason": "; ".join(reasons)}


def evidence_from(sig: dict, keys) -> tuple:
    """The Commit-A evidence shape, built from the RAW signal fields."""
    ev = {k: sig.get(k) for k in REQUIRED_EVIDENCE}
    ev.update({k: sig.get(k) for k in ANOMALY_EVIDENCE})
    if sig.get("anomaly_drop_id"):
        ev["anomaly_drop_id"] = sig["anomaly_drop_id"]
    need = list(REQUIRED_EVIDENCE)
    if any("anomaly" in str(k) for k in keys):
        need += list(ANOMALY_EVIDENCE)
    missing = [k for k in need if ev.get(k) is None]
    return ev, missing


def propose(sig: dict, verdict: dict, dry: bool = False) -> str:
    """Write the PROPOSAL the needs report reads. This is the watchdog's only output."""
    ev, missing = evidence_from(sig, verdict["keys"])
    if missing:
        return "not_proposed:incomplete_evidence:" + ",".join(missing)
    if dry:
        return "dry:would_propose:" + ",".join(verdict["keys"])
    try:
        doc = _load(PROPOSALS, {})
        doc["pending"] = {"ts": _now(), "proposed_by": "trigger_watchdog",
                          "reason": verdict["reason"], "evidence": ev,
                          "keys": verdict["keys"]}
        doc["history"] = ([h for h in (doc.get("history") or [])][-50:]
                          + [{"ts": _now(), "keys": verdict["keys"]}])
        PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
        PROPOSALS.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return "proposed:" + ",".join(verdict["keys"])
    except Exception as e:
        return f"propose_failed:{type(e).__name__}"


def run(dry: bool = False, now: datetime = None) -> dict:
    sig = read_signal(now)
    verdict = decide(sig, now)
    out = {"ts": _now(), "signal_ts": sig.get("ts"), "verdict": verdict}
    before = FORBIDDEN_OUTPUT.exists()
    out["result"] = propose(sig, verdict, dry) if verdict.get("propose") else "silent"
    # WALL (c), checked every pass rather than only asserted in a test: if this module
    # ever became the reason that file appeared, the run says so loudly instead of
    # quietly having crossed the line.
    if FORBIDDEN_OUTPUT.exists() and not before:
        out["WALL_BREACH"] = (f"{FORBIDDEN_OUTPUT.name} appeared during a watchdog pass — "
                              f"only approve_reader may create it")
    return out


if __name__ == "__main__":
    print(json.dumps(run(dry="--dry" in sys.argv), ensure_ascii=False, indent=2))
