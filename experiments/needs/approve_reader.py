#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/needs/approve_reader.py — turn a Telegram "OK <id>" into the action.

The organism pushes what it needs and, for approvable items, a short id (see
needs_report.py, which writes memory/pending_approvals.json). You reply
"OK <id>" in the bot chat. This reader — run once per cycle, no daemon — reads
your new replies and applies exactly the approved action:

  promote_source  -> composer.promote(axis, url, slot, kind, org)   [a sensing hand]
  accept_goal     -> append the proposal to memory/improvement_proposals.json
                     (the stream the cycle already reads)            [a goal it pursues]

HARD BOUNDARY, by design:
  • only messages from the configured chat_id are honored (nobody else can approve)
  • only the two action types above — NEVER a world-changing action. OpenClaw
    level_3 / anything that acts on the world stays under key regardless of replies.
  • every approval is appended to memory/approvals_ledger.jsonl (who/when/what/result)
  • promotions only edit the spec (reversible via git diff); goals only enter a
    human-readable proposal file. Nothing here touches the outside world.

FAIL-OPEN: any error is caught and logged; the cycle is never broken by this step.

  python experiments/needs/approve_reader.py          # one poll-and-apply pass
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "experiments" / "composers"))

NOTIFY_CFG = REPO / "memory" / "notify_channel.json"
PENDING    = REPO / "memory" / "pending_approvals.json"
OFFSET     = REPO / "memory" / "telegram_offset.json"
LEDGER     = REPO / "memory" / "approvals_ledger.jsonl"
PROPOSALS  = REPO / "memory" / "improvement_proposals.json"
DISCOVERED = REPO / "memory" / "discovered_data_sources.json"

# "OK d8df", "ok  d8df", "approve d8df", "OK: d8df" -> the id
_OK_RE = re.compile(r"^\s*(?:ok|approve|yes|да)\b[:\s]+([0-9a-fA-F]{3,8})\s*$", re.IGNORECASE)


def _load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ledger(entry: dict):
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now(), **entry}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _tg(token, method, **params):
    import requests  # requests-first: urllib 403s behind the proxy on this box
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                      json=params, timeout=20)
    return r.json()


def _reply(token, chat_id, text):
    try:
        _tg(token, "sendMessage", chat_id=chat_id, text=text)
    except Exception:
        pass


_NEEDS_EXTRACT = ("http_json_path", "http_json_count", "http_json_series")


def _apply_promote(spec: dict):
    """Promote a self-discovered sensing source. Guarded against double-promote."""
    import composer  # experiments/composers/composer.py
    axis, url, slot = spec["axis"], spec["url"], spec["slot"]
    # FAIL-CLOSED: these kinds cannot be fetched without knowing WHERE the value lives.
    # Promoting one anyway creates a source that raises on every fetch and is dead in
    # three cycles — a silent hole in the portfolio that looks like an approved source.
    kind = spec.get("kind") or "http_json_path"
    _parse = spec.get("parse") or {}
    if kind in _NEEDS_EXTRACT and not _parse.get("extract"):
        return {"ok": False, "error": f"no parsing rule: kind '{kind}' needs an 'extract' path. "
                                      f"Candidate was registered without one — not promoted."}
    # a 'file' source is read from `path`, never from `url`; promoting one without a path
    # yields KeyError('path') on every fetch
    if kind == "file" and not _parse.get("path"):
        return {"ok": False, "error": "no parsing rule: kind 'file' needs a repo-relative "
                                      "'path' — not promoted."}
    # dedupe: if this url is already in the slot, don't append a twin
    specs = _load(getattr(composer, "SPEC_FILE"), {})
    portfolio = (specs.get(axis) or {}).get("portfolio", {})
    existing = portfolio.get(slot, {}).get("sources", [])
    if any(s.get("url") == url for s in existing):
        return {"ok": True, "note": "already promoted (no-op)"}
    # the parsing rule travels WITH the approval — promoting a bare url would create a
    # source that raises on its first fetch and dies against DEATH_AT
    res = composer.promote(axis, url, slot, spec.get("kind") or "http_json_path",
                           spec.get("org") or "?", **(spec.get("parse") or {}))
    return {"ok": "error" not in res, **res}


def _mark_candidate(axis, url, why):
    """A REFUSED candidate must stop coming back. The promote guard is deterministic —
    a record with no parsing rule fails identically every time — so without this the same
    broken candidate is re-offered in every brief, and now in a one-tap message too.
    FAIL-OPEN: bookkeeping must never break the approval loop."""
    try:
        doc = _load(DISCOVERED, {})
        hit = False
        for s in ((doc.get(axis) or {}).get("sources") or []):
            if s.get("url") == url:
                s["status"] = "rejected"
                s["rejected_why"] = str(why)[:200]
                s["rejected_at"] = _now()
                hit = True
        if hit:
            DISCOVERED.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return hit
    except Exception:
        return False


EXTRAORDINARY = REPO / "memory" / "extraordinary_request.json"
CYCLE_PROPOSALS = REPO / "memory" / "pulse_cycle_requests.json"


def _apply_cycle_request(spec: dict, chat_id):
    """Emil's OK is what turns a pulse PROPOSAL into a request the supervisor will honour.

    This function is the only authorised writer of extraordinary_request.json — the
    supervisor refuses any file not authored here and not carrying a human approver. The
    pulse can notice and propose; the alarm clock stays in human hands. Even after this,
    the supervisor still applies the lock, the restart budget and a 4h rate limit."""
    reason = str(spec.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "error": "cycle request has no named reason — not written"}
    evidence = spec.get("evidence") or {}
    try:
        sys.path.insert(0, str(REPO))
        from core.request_signing import evidence_complete, evidence_digest
        ok, missing = evidence_complete(evidence, spec.get("keys", []))
    except Exception as e:
        return {"ok": False, "error": f"evidence check unavailable ({type(e).__name__}) "
                                      f"— not written"}
    if not ok:
        return {"ok": False, "error": f"refusing to sign an escalation with incomplete "
                                      f"evidence (missing {', '.join(missing)})"}
    payload = {
        "ts": _now(),
        "authored_by": "approve_reader",
        "approved_by": str(chat_id),
        "proposed_at": spec.get("proposed_at"),
        "keys": spec.get("keys", []),
        "reason": reason,
        # the RAW fields Emil was shown, plus a digest over them. The supervisor
        # recomputes the digest from the raw fields rather than trusting this one, so
        # what was displayed and what is honoured cannot diverge.
        "evidence": evidence,
        "evidence_sha256": evidence_digest(evidence),
    }
    # SIGN it. approve_reader holds the key; the pulse does not. The supervisor verifies
    # and refuses anything unsigned or wrongly signed — an authored_by string is a claim,
    # a signature is evidence.
    try:
        sys.path.insert(0, str(REPO))
        from core.request_signing import signed
        payload = signed(payload)
    except Exception as e:
        return {"ok": False, "error": f"cannot sign the request ({type(e).__name__}) — "
                                      f"not written; the supervisor would refuse it anyway"}
    EXTRAORDINARY.parent.mkdir(parents=True, exist_ok=True)
    EXTRAORDINARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    try:                       # the proposal is spent; it must not re-surface
        doc = _load(CYCLE_PROPOSALS, {})
        doc.pop("pending", None)
        CYCLE_PROPOSALS.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "note": "supervisor will pick it up within a minute (subject to "
                                "lock, restart budget and the 4h rate limit)"}


def _apply_goal(spec: dict, chat_id):
    """Accept a goal-proposal: append it to improvement_proposals.json, the file
    the cycle already consumes. Human-accepted, timestamped, auditable."""
    axis = spec["axis"]
    prop = spec.get("proposal") or {}
    goal = prop.get("measurable_goal", "")
    doc = _load(PROPOSALS, {"proposals": []})
    if not isinstance(doc, dict) or "proposals" not in doc:
        doc = {"proposals": []}
    # dedupe, mirroring promotions: an approve_id is STABLE across cycles, so the same
    # goal reappears in every brief and a second "OK <id>" would append a twin. Three
    # identical SOCIAL_RELATIONS entries accumulated this way before this guard existed.
    if any(p.get("component") == axis and p.get("measurable_goal") == goal
           for p in doc["proposals"]):
        return {"ok": True, "duplicate": True, "note": "already accepted (no-op)"}
    doc["proposals"].append({
        "component": axis,
        "problem": spec.get("need", f"{axis} furthest from goal"),
        "solution": goal,
        "measurable_goal": goal,
        "root_cause": "human-accepted via Telegram approval",
        "priority": "HIGH",
        "real_world_signal": True,
        "generated_by": "human_telegram_approval",
        "accepted_by": str(chat_id),
        "authored_by": prop.get("authored_by"),
        "moral_check": prop.get("moral_check"),
        "timestamp": _now(),
    })
    PROPOSALS.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "note": "accepted into improvement_proposals.json"}


def run():
    cfg = _load(NOTIFY_CFG, {})
    if cfg.get("channel") != "telegram":
        print("[approve] no telegram config — nothing to read")
        return 0
    token, chat_id = cfg.get("token"), str(cfg.get("chat_id") or "")
    if not token or not chat_id:
        print("[approve] telegram config incomplete")
        return 0

    offset = _load(OFFSET, {}).get("offset", 0)
    try:
        data = _tg(token, "getUpdates", offset=offset + 1, timeout=0)
    except Exception as e:
        print(f"[approve] getUpdates failed: {type(e).__name__}: {e}")
        return 0  # fail-open
    if not data.get("ok"):
        print(f"[approve] telegram error: {data.get('description')}")
        return 0

    updates = data.get("result", [])
    max_id = offset
    applied = 0
    for u in updates:
        max_id = max(max_id, u.get("update_id", offset))
        msg = u.get("message") or u.get("edited_message") or {}
        chat = str((msg.get("chat") or {}).get("id") or "")
        text = (msg.get("text") or "").strip()
        if chat != chat_id:
            continue  # LOCKED: only the owner can approve
        m = _OK_RE.match(text)
        if not m:
            continue
        aid = m.group(1).lower()
        pend = _load(PENDING, {}).get("approvals", {})
        spec = pend.get(aid)
        if not spec:
            _reply(token, chat_id, f"❓ unknown id '{aid}' — it may have expired. "
                                   f"Check the latest CORTEX needs message.")
            _ledger({"event": "unknown_id", "id": aid, "by": chat})
            continue
        try:
            if spec["type"] == "promote_source":
                res = _apply_promote(spec)
                label = spec.get("label", spec["axis"])
                ok = res.get("ok")
                if not ok:
                    res["marked_rejected"] = _mark_candidate(spec["axis"], spec["url"],
                                                             res.get("error"))
                _reply(token, chat_id,
                       (f"✅ promoted {label} ({spec['slot']}). {res.get('note','spec edited — review git diff')}"
                        if ok else f"⚠️ promote failed for {label}: {res.get('error')}"
                                   + (" — marked rejected, it won't be offered again."
                                      if res.get("marked_rejected") else "")))
            elif spec["type"] == "request_cycle":
                res = _apply_cycle_request(spec, chat_id)
                ok = res.get("ok")
                _reply(token, chat_id,
                       (f"✅ extraordinary cycle requested. {res.get('note')}" if ok
                        else f"⚠️ cycle request not written: {res.get('error')}"))
            elif spec["type"] == "accept_goal":
                res = _apply_goal(spec, chat_id)
                _reply(token, chat_id,
                       f"✅ goal for {spec['axis']}: {res['note']}"
                       if res.get("duplicate") else
                       f"✅ accepted goal for {spec['axis']} into the improvement stream.")
                ok = True
            else:
                _reply(token, chat_id, f"⚠️ id '{aid}' has an unsupported action type; ignored.")
                res, ok = {"ok": False, "error": "unsupported_type"}, False
            _ledger({"event": "approval", "id": aid, "type": spec["type"],
                     "axis": spec.get("axis"), "by": chat, "ok": bool(ok), "result": res})
            if ok:
                applied += 1
        except Exception as e:
            _reply(token, chat_id, f"⚠️ error applying '{aid}': {type(e).__name__}: {e}")
            _ledger({"event": "error", "id": aid, "by": chat,
                     "error": f"{type(e).__name__}: {e}"})

    if updates:
        try:
            OFFSET.parent.mkdir(parents=True, exist_ok=True)
            OFFSET.write_text(json.dumps({"offset": max_id, "ts": _now()}), encoding="utf-8")
        except Exception:
            pass
    print(f"[approve] read {len(updates)} update(s), applied {applied} approval(s)")
    return applied


if __name__ == "__main__":
    run()
