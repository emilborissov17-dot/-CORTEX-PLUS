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
# "NO d8df", "reject d8df", "не d8df", "откажи d8df" -> the id. Before 13 Aug 2026 the
# only human verb was OK — a junk proposal could not be dismissed and re-surfaced in
# every brief forever. A decline is a HUMAN VERDICT on the proposal (recorded in
# memory/declined_approvals.json + the ledger); it is NOT a blacklist of the provider —
# nothing was fetched, nothing failed. The candidate is simply no longer offered.
_NO_RE = re.compile(r"^\s*(?:no|reject|не|откажи)\b[:\s]+([0-9a-fA-F]{3,8})\s*$", re.IGNORECASE)
DECLINED = REPO / "memory" / "declined_approvals.json"


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
    """Promote a self-discovered sensing source. Guarded against double-promote.

    Every refusal carries a failure_class. 'schema' means OUR record is incomplete — the
    source was never contacted and must not be charged for it. 'fetch' means a real
    request was made and the source failed it. Only the second may lead to a blacklist.
    """
    import composer  # experiments/composers/composer.py
    axis, url, slot = spec["axis"], spec["url"], spec["slot"]
    # FAIL-CLOSED: these kinds cannot be fetched without knowing WHERE the value lives.
    # Promoting one anyway creates a source that raises on every fetch and is dead in
    # three cycles — a silent hole in the portfolio that looks like an approved source.
    #
    # As of the registration wall (core/source_registration.py) a candidate in this state
    # should no longer EXIST: the rule is derived at discovery or the candidate is dropped.
    # This stays as a second line, and it is now explicitly a SCHEMA refusal — an
    # incomplete record of ours, never evidence against the provider.
    kind = spec.get("kind") or "http_json_path"
    _parse = spec.get("parse") or {}
    if kind in _NEEDS_EXTRACT and not _parse.get("extract"):
        return {"ok": False, "failure_class": composer.FAILURE_SCHEMA,
                "reason_code": "incomplete_registration",
                "error": f"no parsing rule: kind '{kind}' needs an 'extract' path. "
                         f"Candidate was registered without one — not promoted. "
                         f"The source was NOT contacted and is NOT blacklisted."}
    # a 'file' source is read from `path`, never from `url`; promoting one without a path
    # yields KeyError('path') on every fetch
    if kind == "file" and not _parse.get("path"):
        return {"ok": False, "failure_class": composer.FAILURE_SCHEMA,
                "reason_code": "incomplete_registration",
                "error": "no parsing rule: kind 'file' needs a repo-relative 'path' — "
                         "not promoted. The source was NOT contacted and is NOT blacklisted."}
    # dedupe: if this url is already in the slot, don't append a twin
    specs = _load(getattr(composer, "SPEC_FILE"), {})
    portfolio = (specs.get(axis) or {}).get("portfolio", {})
    existing = portfolio.get(slot, {}).get("sources", [])
    if any(s.get("url") == url for s in existing):
        return {"ok": True, "note": "already promoted (no-op)"}
    # the parsing rule travels WITH the approval — promoting a bare url would create a
    # source that raises on its first fetch and dies against DEATH_AT.
    # composer.promote() runs the SMOKE FETCH through the real loader before it writes
    # anything: a raise or an empty read aborts the promotion and the spec is untouched.
    res = composer.promote(axis, url, slot, spec.get("kind") or "http_json_path",
                           spec.get("org") or "?", **(spec.get("parse") or {}))
    return {"ok": "error" not in res, **res}


def _mark_candidate(axis, url, why, reason_code="unspecified"):
    """BLACKLIST — and only ever after a REAL FETCH FAILURE.

    A source that answered with nothing usable, never answered at all, or answered with
    data already too old has earned this. A record of ours that was missing a field has
    not: that is _discard_candidate below. The `rejected_class` says which failure it was,
    so a future reader is never left guessing whether this source was tested or merely
    mis-registered — the question that cost OWID and the World Bank their place.

    FAIL-OPEN: bookkeeping must never break the approval loop."""
    try:
        doc = _load(DISCOVERED, {})
        hit = False
        for s in ((doc.get(axis) or {}).get("sources") or []):
            if s.get("url") == url:
                s["status"] = "rejected"
                s["rejected_why"] = str(why)[:200]
                s["rejected_at"] = _now()
                s["rejected_class"] = str(reason_code)
                s["rejected_after"] = "a real fetch through composer.fetch()"
                hit = True
        if hit:
            DISCOVERED.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return hit
    except Exception:
        return False


def _discard_candidate(axis, url, why):
    """INCOMPLETE, not bad. The candidate stops being offered — a deterministic refusal
    would repeat forever otherwise — but it is marked 'incomplete', never 'rejected', so
    it stays visible (cortex_query --rejected), can be completed by a later derivation,
    and can be re-proposed by hand with scripts/cortex_ingest.py. Nothing about the
    provider has been established, because nothing was ever asked of it.

    FAIL-OPEN, same as the blacklist path."""
    try:
        doc = _load(DISCOVERED, {})
        hit = False
        for s in ((doc.get(axis) or {}).get("sources") or []):
            if s.get("url") == url:
                s["status"] = "incomplete"
                s["incomplete_why"] = str(why)[:200]
                s["incomplete_at"] = _now()
                hit = True
        if hit:
            DISCOVERED.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        try:
            sys.path.insert(0, str(REPO))
            from core.source_registration import discard as _sr_discard
            _sr_discard(axis, url, why, stage="approval")
        except Exception:
            pass
        return hit
    except Exception:
        return False


def _record_decline(aid: str, spec: dict, chat_id: str):
    """Persist a human 'NO': the id stops being offered by needs_report. For a
    promote_source the discovered-store record also gets status='declined' (any
    non-'active' status stops the candidate items). FAIL-OPEN like everything here."""
    try:
        doc = _load(DECLINED, {})
        doc[aid] = {"ts": _now(), "type": spec.get("type"), "axis": spec.get("axis"),
                    "label": spec.get("label") or spec.get("need", "")[:60],
                    "declined_by": str(chat_id)}
        DECLINED.parent.mkdir(parents=True, exist_ok=True)
        DECLINED.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    if spec.get("type") == "promote_source":
        try:
            doc = _load(DISCOVERED, {})
            hit = False
            for s in ((doc.get(spec["axis"]) or {}).get("sources") or []):
                if s.get("url") == spec.get("url"):
                    s["status"] = "declined"
                    s["declined_why"] = "declined by human via Telegram (NO <id>)"
                    s["declined_at"] = _now()
                    hit = True
            if hit:
                DISCOVERED.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        except Exception:
            pass


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


# ── СЪСТОЯНИЕТО НА ЧОВЕШКИЯ КАНАЛ (консенсус с Kimi, стъпка 4, 15 авг 2026) ──
# Той: „Мълчанието не значи разрешено — но трябва да различаваш „НЯМА НОВИ
# СЪОБЩЕНИЯ" (норма) от „КАНАЛЪТ Е МЪРТЪВ" (отказ). Разграничението е в HTTP
# статуса/таймаута, не в празния отговор. При мъртъв канал: необратимите стъпки
# спират като при липса на свидетел — freeze, не спиране на цикъла."
# Дотогава двете бяха неразличими: всяка грешка се преглъщаше с return 0, тоест
# ЗАБРАНА, изпратена снощи, можеше да се загуби мълчаливо и цикълът продължаваше
# неограничен. Сега състоянието се записва и необратимите стъпки го четат.
#
# ТРЕТО СЪСТОЯНИЕ, което добавям и обявявам: not_configured. Канал, който никога
# не е бил настроен, не е ОТКАЗАЛ — човекът просто не го ползва. Да замразим
# необратимото заради него би значело системата да си върже ръцете завинаги заради
# функция, която никой не е поискал. Замразява само `dead`.
CHANNEL_STATE = REPO / "memory" / "human_channel_state.json"


UNKNOWN_CHANNEL = "unknown"


def _mark_channel(state: str, why: str, human_msgs: int = 0) -> None:
    """Запиши какво знаем за канала — И кога човек за последно е ПИСАЛ.

    `human_msgs` е добавено на 17 авг 2026. Дотук записът казваше само че
    Telegram е върнал 200 — тоест че ТРАНСПОРТЪТ работи. Това не е човек. Без
    следа кога човек наистина е проговорил, нотариусът нямаше как да различи
    „каналът е жив и човекът отговаря" от „каналът е жив и от седмици никой не е
    писал", и даваше FULL и на двете. `last_human_msg_utc` се пренася напред,
    защото фактът „човек писа онзи ден" не изчезва, когато днешната проверка
    върне празен inbox.
    """
    try:
        prev = {}
        try:
            prev = json.loads(CHANNEL_STATE.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
        now = datetime.now(timezone.utc).isoformat()
        last_human = prev.get("last_human_msg_utc")
        if human_msgs:
            last_human = now
        CHANNEL_STATE.parent.mkdir(parents=True, exist_ok=True)
        CHANNEL_STATE.write_text(json.dumps(
            {"ts": now, "state": state, "why": why,
             "human_msgs": int(human_msgs),
             "last_human_msg_utc": last_human},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def channel_state() -> dict:
    """Какво ЗНАЕМ за канала. `unknown` когато не сме гледали или не сме могли.

    Отделено от channel_alive() на 17 авг 2026, защото „не проверено" и
    „проверено и мъртво" се връщаха като едно и също нещо — по-точно, „не
    проверено" се връщаше като ПО-ДОБРОТО от двете. Виж channel_alive().
    """
    try:
        d = json.loads(CHANNEL_STATE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"state": UNKNOWN_CHANNEL, "why": "няма запис — каналът НЕ Е проверяван"}
    except Exception as e:
        return {"state": UNKNOWN_CHANNEL,
                "why": f"записът за канала е нечетим: {type(e).__name__}"}
    if not isinstance(d, dict) or not d.get("state"):
        return {"state": UNKNOWN_CHANNEL, "why": "записът няма поле state"}
    return d


def channel_alive() -> tuple:
    """(може ли да се действа необратимо, защо). Мъртъв ИЛИ непроверен = не.

    ПРОМЯНА, 17 авг 2026 — и тя е поправка на дупка, не затягане:
    досега липсващ или нечетим запис връщаше True („не се третира като отказ").
    Тоест НИКОГА НЕ ПРОВЕРЕН канал даваше повече права от канал, който сме
    проверили и е бил мъртъв. Невежеството не бива да струва по-малко от лошата
    новина; иначе най-безопасният начин да минеш през портата е да не гледаш.

    `not_configured` остава НЕ-отказ нарочно (решението на Емил/Kimi, 15 авг:
    ненастроен канал не е отказ) — това е проверен, определен отговор, не липса
    на проверка. Необратимите стъпки пак спират, но ги спира нотариусът, който
    му дава MINIMAL — виж core/notary.py:_human_state.
    """
    st = channel_state()
    state = str(st.get("state", UNKNOWN_CHANNEL))
    why = f"{state}: {st.get('why', '')}"
    if state in ("dead", UNKNOWN_CHANNEL):
        return False, why
    return True, why


def run():
    cfg = _load(NOTIFY_CFG, {})
    if cfg.get("channel") != "telegram":
        print("[approve] no telegram config — nothing to read")
        _mark_channel("not_configured", "channel != telegram")
        return 0
    token, chat_id = cfg.get("token"), str(cfg.get("chat_id") or "")
    if not token or not chat_id:
        print("[approve] telegram config incomplete")
        _mark_channel("not_configured", "token/chat_id missing")
        return 0

    offset = _load(OFFSET, {}).get("offset", 0)
    try:
        data = _tg(token, "getUpdates", offset=offset + 1, timeout=0)
    except Exception as e:
        # HTTP/таймаут отказ = МЪРТЪВ канал, не „няма съобщения". Цикълът върви,
        # но необратимите стъпки замръзват (виж channel_alive).
        print(f"[approve] getUpdates FAILED -> channel treated as DEAD: "
              f"{type(e).__name__}: {e}")
        _mark_channel("dead", f"{type(e).__name__}: {e}")
        return 0
    if not data.get("ok"):
        print(f"[approve] telegram error -> channel DEAD: {data.get('description')}")
        _mark_channel("dead", f"telegram ok=false: {data.get('description')}")
        return 0

    # 200 OK с празно тяло Е валидно състояние — човекът просто не е писал.
    updates = data.get("result", [])
    _mark_channel("alive", f"200 OK, {len(updates)} нови съобщения",
                  human_msgs=len(updates))
    max_id = offset
    applied = 0
    for u in updates:
        max_id = max(max_id, u.get("update_id", offset))
        msg = u.get("message") or u.get("edited_message") or {}
        chat = str((msg.get("chat") or {}).get("id") or "")
        text = (msg.get("text") or "").strip()
        if chat != chat_id:
            continue  # LOCKED: only the owner can approve
        m_no = _NO_RE.match(text)
        if m_no:
            aid = m_no.group(1).lower()
            pend = _load(PENDING, {}).get("approvals", {})
            spec = pend.get(aid)
            if not spec:
                _reply(token, chat_id, f"❓ unknown id '{aid}' — nothing to decline.")
                _ledger({"event": "unknown_id", "id": aid, "by": chat})
                continue
            _record_decline(aid, spec, chat)
            _ledger({"event": "decline", "id": aid, "type": spec.get("type"),
                     "axis": spec.get("axis"), "by": chat, "ok": True})
            _reply(token, chat_id,
                   f"🚫 declined '{spec.get('label') or aid}' — it will not be offered again. "
                   f"(The provider is NOT blacklisted; nothing was fetched.)")
            applied += 1
            continue
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
                    # THE FORK THIS WHOLE FIX EXISTS FOR. A blacklist is a verdict on a
                    # provider and may only follow evidence — a request that was actually
                    # made and actually failed. A schema refusal is a verdict on our own
                    # record and gets a discard instead.
                    import composer as _c
                    if res.get("failure_class") == _c.FAILURE_FETCH:
                        res["marked_rejected"] = _mark_candidate(
                            spec["axis"], spec["url"], res.get("error"),
                            res.get("reason_code", "unspecified"))
                    else:
                        res["discarded"] = _discard_candidate(
                            spec["axis"], spec["url"], res.get("error"))
                tail = ""
                if res.get("marked_rejected"):
                    tail = (f" — marked rejected after a real fetch failure "
                            f"({res.get('reason_code')}); it won't be offered again.")
                elif res.get("discarded"):
                    tail = (" — our record was incomplete, so it is DISCARDED, not "
                            "blacklisted. The source was never contacted.")
                if res.get("exception"):
                    tail += f"\nraw: {str(res['exception'])[:300]}"
                _reply(token, chat_id,
                       (f"✅ promoted {label} ({spec['slot']}). {res.get('note','spec edited — review git diff')}"
                        if ok else f"⚠️ promote failed for {label}: {res.get('error')}" + tail))
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
