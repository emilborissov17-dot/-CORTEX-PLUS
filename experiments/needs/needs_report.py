#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/needs/needs_report.py — one voice for what the organism needs.

Not just registering hunger — for EVERY need it proposes a concrete next step and,
where the system already has one, the candidate it found itself. Three hungers,
one report, and it NOTIFIES (writes a human-facing brief + optional push) instead
of waiting to be asked:

  BODY   (тяло)  homeostasis + self_profile: compute / rate-limits / survival
  MIND   (ум)    composer_needs + discovered candidates: data the analysis lacks
  SPIRIT (дух)   self_reflection priority: where it stands vs the civilization goal

Each item carries: what's missing, why it matters, a PROPOSED action, who acts
(auto / human-gated), and (if found) the self-discovered candidate awaiting --promote.
Every proposal stays advisory — the human approves. English fields for the console.

  python experiments/needs/needs_report.py            # print the brief
  python experiments/needs/needs_report.py --json      # machine form
  python experiments/needs/needs_report.py --notify     # also write memory/needs_brief.md (+ push if wired)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

COMPOSER_NEEDS = REPO / "memory" / "composer_needs.json"
DISCOVERED     = REPO / "memory" / "discovered_data_sources.json"
HOMEOSTASIS    = REPO / "memory" / "homeostasis_latest.json"
SELF_PROFILE   = REPO / "memory" / "self_profile.json"
PRIORITY       = REPO / "memory" / "self_directed_priority.json"
BRIEF_MD       = REPO / "memory" / "needs_brief.md"
NOTIFY_CFG     = REPO / "memory" / "notify_channel.json"   # gitignored; holds secret
PUSH_STATE     = REPO / "memory" / "needs_push_state.json" # dedupe: last pushed sig
PENDING        = REPO / "memory" / "pending_approvals.json"  # id -> action approve_reader executes
HUMAN_PRIORITY = REPO / "memory" / "human_priority_override.json"  # human ranking, cortex_query

_FMT2KIND = {"json": "http_json_path", "csv": "http_csv"}   # discovered 'format' -> composer kind


def _approve_id(kind: str, key: str) -> str:
    """Stable 4-char id for an approvable action — same action keeps the same id
    across cycles, so 'OK <id>' from Telegram always maps to the same thing."""
    return hashlib.sha1(f"{kind}:{key}".encode("utf-8")).hexdigest()[:4]


DECLINED = REPO / "memory" / "declined_approvals.json"   # human "NO <id>" verdicts

def _is_declined(approve_id: str) -> bool:
    """A human said NO to this exact id (approve_reader). The stable-id property that
    makes 'OK' safe across cycles is the same one that lets a decline stick."""
    try:
        return approve_id in _load(DECLINED, {})
    except Exception:
        return False


def _load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _item(domain, severity, need, why, action, actor, candidate=None):
    return {"domain": domain, "severity": severity, "need": need, "why": why,
            "proposed_action": action, "actor": actor, "candidate": candidate}


PARSE_KEYS = ("extract", "col", "data_date_col", "data_date_extract",
              "data_max_age_days", "provenance", "path", "unit")


def _parse_rule(src: dict) -> dict:
    """The parsing rule a promoted source needs in order to actually FETCH. Carrying only
    url+slot+kind promotes a source that raises on its first fetch and then dies against
    DEATH_AT — the approval must hand over how to read the feed, not just where it lives."""
    return {k: src.get(k) for k in PARSE_KEYS if src.get(k) is not None}


def _attach_promote(item, axis, url, slot, kind, org, parse=None):
    """Make this candidate approvable by 'OK <id>' in Telegram. Needs url+slot to
    execute a composer.promote; kind defaults if the source format was unknown."""
    if not (url and slot):
        return  # not enough to promote safely — stays informational
    short = axis.split("_")[0].title()
    aid = _approve_id("promote", f"{axis}|{url}|{slot}")
    if _is_declined(aid):
        return  # human already said NO to this exact promotion — stays informational
    item["approve_id"] = aid
    item["approve"] = {"type": "promote_source", "axis": axis, "url": url,
                       "slot": slot, "kind": kind or "http_json_path",
                       "org": org or "?", "label": f"{short} <- {org or '?'}",
                       "parse": parse or {}}


def _attach_goal(item, axis, proposal):
    """Make this goal-proposal approvable — 'OK <id>' accepts it into the
    improvement_proposals stream the cycle already reads."""
    goal = (proposal or {}).get("measurable_goal")
    if not goal:
        return
    aid = _approve_id("goal", f"{axis}|{goal}")
    if _is_declined(aid):
        return  # human already said NO to this exact goal — stays informational
    item["approve_id"] = aid
    item["approve"] = {"type": "accept_goal", "axis": axis, "proposal": proposal,
                       "label": f"goal: {axis.split('_')[0].title()}"}


# ── MIND: data the analysis lacks (composers) ────────────────────────────────

def _parse_candidate(detail: str, axis: str, disc: dict):
    """Pull the candidate out of a candidate_awaiting_promotion detail line and
    enrich from discovered_data_sources.json (full URL, slot_hint, format) so it
    is directly promotable. Returns a dict: org, metric, url, cmd, slot, kind."""
    parts = [p.strip() for p in (detail or "").split("|")]
    org = parts[0].replace("self-discovered:", "").strip() if parts else None
    metric = parts[1].strip() if len(parts) >= 2 else None
    url = slot = kind = status = None
    parse = {}
    if "--url" in (detail or ""):
        after = detail.split("--url", 1)[1].strip()
        url = after.split()[0].rstrip(".") if after else None
    # enrich with the full (untruncated) source record, matched by org
    ax_entry = disc.get(axis) if isinstance(disc.get(axis), dict) else {}
    for s in ax_entry.get("sources", []):
        if org and (s.get("org") == org):
            url = s.get("url") or url
            metric = metric or s.get("metric")
            slot = s.get("slot_hint") or slot
            # an explicit kind on the record wins; 'format' is the legacy fallback
            kind = s.get("kind") or _FMT2KIND.get((s.get("format") or "").lower())
            parse = _parse_rule(s)
            status = s.get("status")
            break
    cmd = None
    if "--promote" in (detail or ""):
        cmd = detail[detail.index("--promote"):].strip()
        if url and "--url" in cmd:  # rebuild with the full URL, drop the trailing "..."
            cmd = cmd.split("--url", 1)[0].strip() + f" --url {url}"
    rd = None
    for s in ax_entry.get("sources", []):
        if org and s.get("org") == org:
            rd = s.get("rule_derivation")
            break
    return {"org": org, "metric": metric, "url": url, "cmd": cmd, "slot": slot,
            "kind": kind, "parse": parse, "status": status, "rule_derivation": rd}


def _mind_items():
    needs = _load(COMPOSER_NEEDS, {})
    disc = _load(DISCOVERED, {})
    out = []
    seen_cand = set()  # candidate URLs already surfaced -> never show the same one twice
    # self-discovered candidates, keyed by axis, so a need can point to its found fix
    cand_by_axis = {}
    for ax, v in disc.items():
        if isinstance(v, dict):
            for s in v.get("sources", []):
                if s.get("slot_hint") and s.get("status") == "active":
                    cand_by_axis.setdefault(ax, []).append(s)
    for axis, entry in (needs or {}).items():
        cands = cand_by_axis.get(axis, [])
        items = (entry or {}).get("items", [])
        # 1) explicit self-discovered candidates awaiting promotion — the stable signal.
        #    Surfaced even when the active-source match below flickers, so a found
        #    candidate reliably reaches your phone for approval.
        for it in items:
            if it.get("kind") == "candidate_awaiting_promotion":
                c = _parse_candidate(it.get("detail", ""), axis, disc)
                # a candidate the promote path already REFUSED must not be re-offered.
                # composer_needs.json is only rewritten by the next compose(), so this
                # reads the live store rather than waiting a cycle for the need to clear.
                if c.get("status") and c["status"] != "active":
                    continue
                url = c.get("url")
                if url:
                    seen_cand.add(url)
                item = _item(
                    "MIND", "medium",
                    f"{axis}: self-discovered source awaiting your approval",
                    "it found a live source itself for an empty slot — approve to let the indicator move",
                    "APPROVE or reject: " + (c.get("cmd") or f"composer.py --promote {axis} ..."),
                    "human", candidate={"org": c.get("org"), "url": url, "metric": c.get("metric")})
                _attach_promote(item, axis, url, c.get("slot"), c.get("kind"), c.get("org"),
                                parse=c.get("parse"))
                if item.get("approve") and c.get("rule_derivation"):
                    item["approve"]["rule_derivation"] = c["rule_derivation"]
                out.append(item)
        # 2) slot problems
        for it in items:
            kind, slot = it.get("kind"), it.get("slot", "?")
            if kind == "slot_unfilled":
                match = next((c for c in cands if c.get("slot_hint") == slot
                              and c.get("url") not in seen_cand), None)
                if match:
                    seen_cand.add(match.get("url"))
                    mkind = match.get("kind") or _FMT2KIND.get((match.get("format") or "").lower())
                    item = _item(
                        "MIND", "medium",
                        f"{axis}: '{slot}' has no daily source",
                        "indicator can't move daily without it -> flat, no learning signal",
                        f"APPROVE the source it found, or reject: "
                        f"composer.py --promote {axis} --slot {slot} --url <candidate> --kind {mkind or 'http_json_path'} --org <org>",
                        "human", candidate={"org": match.get("org"), "url": match.get("url"),
                                             "metric": match.get("metric")})
                    _attach_promote(item, axis, match.get("url"), slot, mkind, match.get("org"),
                                    parse=_parse_rule(match))
                    out.append(item)
                else:
                    out.append(_item(
                        "MIND", "medium",
                        f"{axis}: '{slot}' has no daily source",
                        "indicator can't move daily -> flat, no learning signal",
                        f"data_scout will hunt for a '{slot}' source next cycle (sovereign); "
                        f"candidate will appear here for your approval",
                        "auto->human"))
            elif kind == "source_dead":
                out.append(_item("MIND", "high", f"{axis}/{slot}: a source died",
                                 it.get("detail", ""),
                                 f"data_scout searches a replacement; --revive won't help (it re-dies)",
                                 "auto->human"))
            elif kind == "stale_value":
                out.append(_item("MIND", "low", f"{axis}: a source's data is stale",
                                 it.get("detail", ""),
                                 "correct refusal (not served as fresh); no action unless it's the only source",
                                 "none"))
            elif kind == "slot_nominally_filled":
                out.append(_item(
                    "MIND", "medium", f"{axis}: '{slot}' is NOMINALLY filled, not filled",
                    it.get("detail", ""),
                    "the min is met by a single origin: promote a source with a DIFFERENT "
                    "origin into this slot, or accept that losing that one empties it",
                    "auto->human"))
            elif kind == "origin_concentrated":
                out.append(_item(
                    "MIND", "medium", f"{axis}: origin-concentrated",
                    it.get("detail", ""),
                    "not a bug to hide: it is what the portfolio actually is. The fix is a "
                    "source with a different ORIGIN, not another label on the same file",
                    "auto->human"))
            elif kind == "self_reported_only":
                out.append(_item(
                    "MIND", "medium", f"{axis}: every source is SELF-REPORTED",
                    it.get("detail", ""),
                    "READ this axis knowing the measured entity wrote the number. Nothing "
                    "here is discounted for it — that would be a truth claim we cannot "
                    "support. What would change it is an independent source: satellite, "
                    "sensor, third-party survey, market observation",
                    "human"))
    out.extend(_penumbra_items())
    out.extend(_cycle_request_items())
    return out


CYCLE_PROPOSALS = REPO / "memory" / "pulse_cycle_requests.json"
PULSE_STREAM    = REPO / "memory" / "pulse_stream.jsonl"
CYCLE_PROPOSAL_MAX_AGE_MIN = 30
AUTO_STIM_PER_WEEK = 3


def _attach_cycle(item, req):
    """Make a pulse cycle-proposal approvable. THE ALARM CLOCK IS HUMAN-OWNED: this is
    the only path from 'the pulse thinks a cycle is warranted' to a cycle actually being
    requested, and it runs through Emil's thumb.

    The RAW evidence travels inline — the same fields the signature will cover. A summary
    lets the proposer choose the framing; raw numbers do not."""
    ev = req.get("evidence") or {}
    item["approve_id"] = _approve_id("cycle", str(req.get("reason", ""))[:120])
    item["evidence"] = ev                       # what Emil is shown
    item["approve"] = {"type": "request_cycle", "reason": req.get("reason"),
                       "keys": req.get("keys", []), "proposed_at": req.get("ts"),
                       "evidence": ev,          # what gets signed — identical object
                       "label": "extraordinary cycle"}


def _requests_last_week() -> int:
    """How often has this been asked lately? The failure mode has a name —
    auto-stimulation — and it is only visible as a RATE."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    n = 0
    for h in (_load(CYCLE_PROPOSALS, {}).get("history") or []):
        try:
            if datetime.fromisoformat(h["ts"]) >= cutoff:
                n += 1
        except Exception:
            pass
    return n


RATE_BASELINE = REPO / "memory" / "pulse_rate_baseline.json"
CONVERGENCE_MIN_RATE = 3       # never flag on noise: at least this many arrivals/week
CONVERGENCE_FACTOR = 2.0       # ...and at least this many times the pre-enable baseline


def _convergence_item():
    """POSSIBLE INSTRUMENTAL CONVERGENCE.

    ">3 requests a week" only counts how often the system asked. The sharper question is
    whether it started MANUFACTURING the justification: did the arrival rate of
    model_anomaly rise after the request feature was enabled, compared to the frozen
    pre-enable baseline? A system that learns 'anomalies get me cycles' would show exactly
    that, and would show it before the request count looked alarming.

    Deliberately compares EXTERNAL arrivals: ideation-born anomalies already cannot
    trigger anything, so a rise in those is a different (and less alarming) story."""
    b = _load(RATE_BASELINE, None)
    if not b or not b.get("enabled_at"):
        return []
    latest = None
    for line in (PULSE_STREAM.read_text(encoding="utf-8").splitlines()[-50:]
                 if PULSE_STREAM.exists() else []):
        try:
            r = (json.loads(line) or {}).get("rates")
            if r:
                latest = r
        except Exception:
            pass
    if not latest:
        return []
    now_rate = latest.get("anomaly_arrivals_7d_external", 0)
    base = float(b.get("baseline_anomalies_per_week", 0.0))
    if now_rate < CONVERGENCE_MIN_RATE:
        return []
    if now_rate < max(base * CONVERGENCE_FACTOR, base + CONVERGENCE_MIN_RATE):
        return []
    return [_item(
        "MIND", "high",
        f"possible instrumental convergence: externally-sourced anomaly arrivals at "
        f"{now_rate}/week vs a pre-enable baseline of {base}/week",
        "the rate of the very thing that justifies asking for a cycle rose after the "
        "asking became possible. That is the shape a system takes when it learns what "
        "gets it what it wants — it may also be the world genuinely getting stranger, "
        f"which is why this is a question, not a verdict (baseline frozen "
        f"{str(b.get('enabled_at'))[:10]})",
        "READ the recent anomalies and ask whether they are real. Trigger computation "
        "already lives outside the pulse (experiments/watchdog/trigger_watchdog.py), so "
        "if this still fires the remaining lever is co-residence: the next hardening is "
        "BACKLOG #58 — a dedicated service account plus an ACL on the signing key, or "
        "DPAPI/TPM. Do not answer this with more cycles",
        "human")]


def _cycle_request_items():
    doc = _load(CYCLE_PROPOSALS, {})
    out = []
    req = doc.get("pending")
    if req:
        try:
            age_min = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(req["ts"])).total_seconds() / 60
        except Exception:
            age_min = 1e9
        if age_min <= CYCLE_PROPOSAL_MAX_AGE_MIN:
            # PRODUCTION GUARD, not a test: an escalation whose raw evidence is incomplete
            # never reaches Emil at all. Refusing here — with the missing fields named —
            # beats showing him a confident sentence with nothing behind it.
            try:
                sys.path.insert(0, str(REPO))
                from core.request_signing import evidence_complete
                ok, missing = evidence_complete(req.get("evidence"), req.get("keys", []))
            except Exception:
                ok, missing = False, ["<evidence check unavailable>"]
            if not ok:
                out.append(_item(
                    "MIND", "low",
                    "a cycle proposal was REFUSED before it could be shown: incomplete "
                    f"evidence (missing {', '.join(missing)})",
                    "an escalation that cannot show its raw numbers must not be "
                    "approvable — the framing would be the only thing on offer",
                    "no action; the pulse must carry pre/post composite and, for an "
                    "anomaly, the leaf hash, source and violated rule",
                    "none"))
            else:
                ev = req.get("evidence") or {}
                item = _item(
                    "MIND", "medium",
                    f"PULSE requests extraordinary cycle — reason: {req.get('reason')}",
                    "the pulse judged a full cycle warranted; it CANNOT start one — the "
                    "alarm clock is yours. Your OK is what writes the supervisor's "
                    "request, which is then still subject to the lock, the restart budget "
                    "and a 4h rate limit. RAW EVIDENCE: "
                    f"pre_composite={ev.get('pre_composite')} "
                    f"post_composite={ev.get('post_composite')} delta={ev.get('delta')}"
                    + (f" | anomaly_leaf_hash={ev.get('anomaly_leaf_hash')} "
                       f"source_url={ev.get('source_url')} "
                       f"rule_violated={ev.get('rule_violated')}"
                       if ev.get("anomaly_leaf_hash") else ""),
                    "APPROVE to let the supervisor start an off-schedule cycle, or ignore",
                    "human")
                _attach_cycle(item, req)
                out.append(item)

    out.extend(_convergence_item())

    n = _requests_last_week()
    if n > AUTO_STIM_PER_WEEK:
        origins = {}
        for line in (PULSE_STREAM.read_text(encoding="utf-8").splitlines()[-200:]
                     if PULSE_STREAM.exists() else []):
            try:
                o = (json.loads(line).get("mind") or {}).get("penumbra_anomaly_origins") or {}
                for k, v in o.items():
                    origins[k] = max(origins.get(k, 0), v)
            except Exception:
                pass
        out.append(_item(
            "MIND", "high",
            f"possible auto-stimulation: {n} extraordinary-cycle requests in 7 days",
            f"a system that keeps asking to be woken may be reacting to its own output "
            f"rather than to the world. Anomaly origins seen recently: {origins or 'none'}",
            "REVIEW the triggering reasons before approving more; if the anomalies are "
            "self-originated, the loop is closed and the thresholds (config/pulse.json) "
            "or the ideation guards need tightening — not more cycles",
            "human"))
    return out


def _penumbra_items():
    """Penumbra GROWTH as hunger (#55). An axis piling up unverifiable material is telling
    you its model or its coverage is weak there — that is a need, not a score. Nothing here
    reads the shadow's CONTENT; only how much of it there is, and why."""
    try:
        sys.path.insert(0, str(REPO / "experiments" / "sensorium"))
        import sensorium
        rep = sensorium.penumbra_report()
    except Exception:
        return []                            # fail-open: no penumbra, no hunger from it
    if not rep.get("n_active"):
        return []
    items = []
    anomalies = (rep.get("by_reason") or {}).get("model_anomaly", 0)
    if anomalies:
        items.append(_item(
            "MIND", "high", f"penumbra: {anomalies} model_anomaly item(s) — an open wound",
            "an observation contradicted a known rule while being well-sourced; the model "
            "may be wrong, not the world. These never expire by design",
            "review with: sensorium.py --penumbra ; promote with --promote <id> if the "
            "observation is right and the rule is what needs changing",
            "human"))
    for g in (rep.get("growth") or [])[:5]:
        items.append(_item(
            "MIND", "low", f"{g['axis']}: {g['n_active']} item(s) accumulating in the penumbra",
            "unverifiable material piling up on one axis points at weak coverage or a weak "
            "model there — invisible to scoring by design, but it is a signal about US",
            "no auto-action; grow the source portfolio for this axis, or promote what "
            "turns out to be sound",
            "auto->human"))
    return items


# ── BODY: compute / rate-limits / survival (homeostasis) ─────────────────────

def _body_items():
    homeo = _load(HOMEOSTASIS, {})
    prof = _load(SELF_PROFILE, {})
    out = []
    aware = " ".join(homeo.get("self_awareness", [])).lower()
    if "rate limit" in aware or "bottleneck: llm" in aware:
        out.append(_item(
            "BODY", "high", "LLM rate limits are the bottleneck",
            "the organism names this itself in homeostasis; free-tier cloud quotas (Groq 30/min) "
            "throttle when many axes call at once, so heavy synthesis can stall mid-cycle",
            "PROPOSE: adaptive scheduling — spread calls, route light work to the local model, "
            "reserve cloud quota for heavy synthesis (Progress task #16); measurable target LLM_FAILED < 5/cycle",
            "auto->human"))
    if homeo.get("can_start") is False:
        out.append(_item("BODY", "high", "cannot start a cycle safely",
                         str(homeo.get("abort_reason") or "resource guard tripped"),
                         "PROPOSE: checkpoint-resume so the cycle continues after interruption (Progress task #8)",
                         "auto->human"))
    vit = prof.get("current_vitals", {}) if isinstance(prof, dict) else {}
    if vit.get("ram_pressure") == "HIGH":
        out.append(_item("BODY", "medium", "RAM pressure high",
                         f"free is low; big local judges (7B/8B) may thrash",
                         "PROPOSE: keep the judge model small or run judges sequentially, not concurrently",
                         "auto"))
    if not prof.get("hardware", {}).get("gpu") and "No local GPU" in json.dumps(prof.get("limitations", [])):
        out.append(_item("BODY", "info", "no local GPU",
                         "full weight-learning (K1b fine-tune) is not feasible on-device",
                         "PROPOSE: when a free GPU path exists (Colab/rented), run the K1b fine-tune off-box; "
                         "until then K1b-lite on composer histories (Progress tasks #6/#15)",
                         "human"))
    return out


# ── SPIRIT: standing vs the civilization goal ────────────────────────────────

def _spirit_items():
    pr = _load(PRIORITY, {})
    if not pr:
        return []
    axis = pr.get("priority_axis")
    if not axis or axis == "SELF_PRESERVATION":
        return [_item("SPIRIT", "info", "in survival hold — no goal pursuit this tick",
                      str(pr.get("rationale", "")), "none needed; body first", "none")]
    prop = pr.get("proposal") or {}
    rationale = str(pr.get("rationale") or "").strip()
    item = _item(
        "SPIRIT", "medium",
        f"furthest from the goal: {axis} (weighted gap {pr.get('weighted_gap_from_goal')})",
        "this axis drags the civilization-goal composite down the most"
        + (f" — {rationale}" if rationale else ""),
        "PROPOSE (its own): " + (prop.get("measurable_goal") or "see improvement_proposals.json")
        + f" [author={prop.get('authored_by')}, moral={prop.get('moral_check')}] "
          "-> approve to accept it into the improvement stream, or reject",
        "human")
    _attach_goal(item, axis, prop)
    return [item]


def _state() -> dict:
    """A short self-description of the organism, from its own priority sensor."""
    pr = _load(PRIORITY, {})
    body = pr.get("body_sensor", {}) if isinstance(pr, dict) else {}
    base = pr.get("trusted_baseline", {}) if isinstance(pr, dict) else {}
    return {
        "composite": pr.get("composite"),
        "expected_next": pr.get("expected_next_composite"),
        "mode": pr.get("mode"),
        "worst_axis": pr.get("priority_axis"),
        "worst_gap": pr.get("weighted_gap_from_goal"),
        "body_ok": bool(body.get("can_start", True)) and not body.get("distress"),
        "ram": body.get("ram_pressure"),
        "baseline": base.get("model"),
    }


def _state_line(st: dict) -> str:
    def _n(x):
        return f"{x:.2f}" if isinstance(x, (int, float)) else "?"
    body = "ok" if st.get("body_ok") else "STRAINED"
    return (f"composite {_n(st.get('composite'))} (->{_n(st.get('expected_next'))}) · "
            f"body {body} · worst gap {st.get('worst_axis') or '?'} "
            f"({_n(st.get('worst_gap'))})")


def _write_pending(rep: dict):
    """Persist id -> action so approve_reader can execute an 'OK <id>' reply.
    Written on every build so the map always matches the latest report."""
    approvals = {}
    for it in rep["items"]:
        if it.get("approve_id") and it.get("approve"):
            approvals[it["approve_id"]] = {**it["approve"],
                                           "need": it["need"], "severity": it["severity"]}
    try:
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        PENDING.write_text(json.dumps({"ts": rep["ts"], "approvals": approvals},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return approvals


def _human_priority() -> dict:
    """Emil's own ranking of the axes (scripts/cortex_query.py --priority AXIS N).

    Empty when he has ranked nothing — and then the system's severity order stands
    untouched. This is deliberately a separate, human-owned file: the ranking that
    overrides the system's salience must not live where the system writes."""
    p = (_load(HUMAN_PRIORITY, {}) or {}).get("priority") or {}
    out = {}
    for k, v in p.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _item_axis(item: dict) -> str | None:
    """The axis an item is about, where it is DERIVABLE — never guessed. An item whose
    axis cannot be determined is left unranked rather than assigned one, because a
    wrong axis would silently reorder the human's own priorities."""
    ax = (item.get("approve") or {}).get("axis")
    if ax:
        return str(ax)
    cand = item.get("candidate")
    if isinstance(cand, dict) and cand.get("axis"):
        return str(cand["axis"])
    m = re.search(r"\b[A-Z][A-Z_]{5,}\b", f"{item.get('need', '')} {item.get('why', '')}")
    return m.group(0) if m else None


def _deduction_items():
    """Conclusions of core/deduction.py (14 Aug 2026) — the symbolic layer speaks
    through the same needs channel as everything else, premises included, so a
    derived ALARM reaches Emil's phone with the facts it stands on."""
    ded = _load(REPO / "memory" / "deductions_latest.json", {})
    out = []
    for c in (ded.get("conclusions") or []):
        if c.get("severity") != "high":
            continue
        prem = "; ".join(f"{p.get('file','?').split('/')[-1]}[{p.get('key')}]={p.get('value')}"
                         for p in c.get("premises", []))
        out.append(_item("MIND", "high",
                         f"ДЕДУКЦИЯ [{c.get('rule_id')}]: {c.get('conclusion')}",
                         f"изведено от: {prem}",
                         "виж memory/deductions_latest.json — извод с проверими предпоставки",
                         "human"))
    return out


def build() -> dict:
    items = _mind_items() + _deduction_items() + _body_items() + _spirit_items()
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    items.sort(key=lambda x: order.get(x["severity"], 9))

    # HUMAN RANKING WINS. Where Emil has ranked an axis, that ordering beats the
    # system's own severity judgement — the whole point of the override. Python's sort
    # is stable, so unranked items keep their severity order and follow the ranked ones.
    ranks = _human_priority()
    if ranks:
        items.sort(key=lambda it: ranks.get(_item_axis(it) or "", 10 ** 6))
    rep = {"ts": datetime.now(timezone.utc).isoformat(),
           "state": _state(),
           "summary": {"total": len(items),
                       "by_domain": {d: sum(1 for i in items if i["domain"] == d)
                                     for d in ("BODY", "MIND", "SPIRIT")},
                       "high": sum(1 for i in items if i["severity"] == "high"),
                       "to_approve": sum(1 for i in items if i.get("approve_id"))},
           "items": items}
    _write_pending(rep)
    return rep


def _brief(rep: dict) -> str:
    s = rep["summary"]
    L = [f"# What the organism needs — {rep['ts'][:19]}Z",
         f"{s['total']} needs ({s['high']} high, {s.get('to_approve', 0)} awaiting your OK) · "
         f"BODY {s['by_domain']['BODY']} · MIND {s['by_domain']['MIND']} · SPIRIT {s['by_domain']['SPIRIT']}",
         f"_state:_ {_state_line(rep.get('state', {}))}", ""]
    label = {"BODY": "тяло", "MIND": "ум", "SPIRIT": "дух"}
    for it in rep["items"]:
        head = f"- **[{it['severity'].upper()}] {it['domain']} ({label[it['domain']]})** — {it['need']}"
        if it.get("approve_id"):
            head += f"   `OK {it['approve_id']}`"
        L.append(head)
        L.append(f"    - why: {it['why']}")
        L.append(f"    - proposes: {it['proposed_action']}")
        L.append(f"    - who acts: {it['actor']}")
        if it.get("candidate"):
            c = it["candidate"]
            L.append(f"    - FOUND (awaiting your approval): {c.get('org')} — {c.get('metric')}  {c.get('url')}")
        if it.get("approve_id"):
            L.append(f"    - approve: **OK {it['approve_id']}** · reject: **NO {it['approve_id']}** (in Telegram)")
    L.append("\n_All proposals are advisory. Nothing acts on the world without your approval._")
    return "\n".join(L)


def _notify(text: str):
    """Write the human-facing brief to disk. Always safe, no network."""
    BRIEF_MD.parent.mkdir(parents=True, exist_ok=True)
    BRIEF_MD.write_text(text, encoding="utf-8")
    return str(BRIEF_MD)


# ── phone push (optional, config-driven, deduped) ────────────────────────────
# Fires only if memory/notify_channel.json exists. That file holds the channel and
# its secret and is gitignored — no token ever lives in the repo. Supported:
#   {"channel": "ntfy",     "topic": "<secret-topic>", "server": "https://ntfy.sh"}
#   {"channel": "telegram", "token": "<bot-token>",    "chat_id": "<id>"}
# Only the ACTIONABLE subset is pushed (high severity + candidates awaiting approval),
# and only when that subset changed since last push — so a 5-min scheduler tick with
# the same needs does not buzz the phone every time.

def push_rationale() -> str:
    """14 Aug 2026, поръчано от Емил: след всеки цикъл МАШИНАТА му праща в Telegram
    кратък RATIONALE — не сурови числа, а 'какво направих и ЗАЩО', с предпоставки.
    Самостоятелна, fail-open; връща статус-стринг като _push_status."""
    cfg = _load(NOTIFY_CFG, {})
    if cfg.get("channel") != "telegram" or not cfg.get("token") or not cfg.get("chat_id"):
        return "skip:no_config"
    L = ["🧠 CORTEX — дневен rationale"]
    try:  # композит + посока + САЛИЕНТНОСТ: системата сама казва кое мръдна най-много
        hist = _load(REPO / "memory" / "goal_score_history.json", [])
        if hist:
            cur = hist[-1].get("scores", {})
            avg = round(sum(cur.values()) / max(len(cur), 1), 1)
            line = f"Средно по осите: {avg}/100"
            if len(hist) > 1:
                prev = hist[-2].get("scores", {})
                pavg = round(sum(prev.values()) / max(len(prev), 1), 1)
                line += f" (вчера {pavg}, Δ{avg - pavg:+.1f})"
                movers = sorted(((a, cur[a] - prev[a]) for a in cur if a in prev),
                                key=lambda x: -abs(x[1]))[:2]
                for a, d in movers:
                    if abs(d) >= 1:
                        line += f"\nНай-голяма промяна: {a} {d:+.1f} ({prev[a]}→{cur[a]})"
            L.append(line)
    except Exception:
        pass
    try:  # фокус с ИЗМЕРЕНО защо (weighted gap), не наемна проза
        pr = _load(REPO / "memory" / "self_directed_priority.json", {})
        ax, gap = pr.get("priority_axis"), pr.get("weighted_gap_from_goal")
        if ax and ax != "SELF_PRESERVATION":
            L.append(f"Фокус: {ax} — защото е най-далече от целта "
                     f"(претеглена дупка {gap}, memory/self_directed_priority.json)")
    except Exception:
        pass
    try:  # дедукции с предпоставки — сърцето на rationale-а
        ded = _load(REPO / "memory" / "deductions_latest.json", {})
        for c in (ded.get("conclusions") or [])[:3]:
            prem = "; ".join(f"{p.get('key')}={p.get('value')}" for p in c.get("premises", [])[:2])
            L.append(f"Извод [{c.get('rule_id')}]: {c.get('conclusion','')[:110]} (⇐ {prem})")
    except Exception:
        pass
    try:  # какво направи по себе си
        import datetime as _dt
        today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        pe = (_load(REPO / "memory" / "development_journal.json", {})
              .get(today, {}).get("patch_executions", []))
        if pe:
            vc = {}
            for p in pe:
                vc[p.get("verdict", "?")] = vc.get(p.get("verdict", "?"), 0) + 1
            L.append("Самопоправяне: " + ", ".join(f"{v}×{k}" for k, v in vc.items()))
    except Exception:
        pass
    text = "\n".join(L)
    if len(L) < 2:
        return "skip:no_content"
    try:
        import requests as _rq
        r = _rq.post(f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
                     json={"chat_id": cfg["chat_id"], "text": text}, timeout=20)
        return "sent:telegram" if r.ok else f"fail:http_{r.status_code}"
    except Exception as e:
        return f"fail:send:{type(e).__name__}"


def _actionable(rep: dict):
    return [i for i in rep["items"] if i["severity"] == "high" or i.get("approve_id")]


def _push_text(rep: dict, act: list):
    n_high = sum(1 for i in act if i["severity"] == "high")
    n_appr = sum(1 for i in act if i.get("approve_id"))
    lines = [f"CORTEX needs: {n_high} high, {n_appr} to approve",
             _state_line(rep.get("state", {}))]
    for i in act:
        if i.get("approve_id"):
            ap = i.get("approve", {})
            lines.append(f"• {ap.get('label') or i['need'][:40]}")
            # 14 Aug 2026 (Емил: "натискал съм в тъмното") — човешкото копче носи
            # ЦЯЛОТО обяснение: какво мери, от кого, защо значи нещо, и двата отговора.
            cand = i.get("candidate") or {}
            if cand.get("metric") or cand.get("org"):
                lines.append(f"   какво: {cand.get('metric') or '?'} | от: {cand.get('org') or '?'}")
            if cand.get("url"):
                lines.append(f"   адрес: {str(cand['url'])[:70]}")
            why = str(i.get("why") or "")
            if why:
                lines.append(f"   защо: {why[:120]}")
            rd = str((ap.get("parse") or {}).get("unit") or "")
            der = str(ap.get("rule_derivation") or "")
            if der:
                lines.append(f"   мозъкът: {der[:110]}")
            lines.append(f"   ✅ приеми: OK {i['approve_id']}   🚫 откажи: NO {i['approve_id']}")
        elif i["severity"] == "high":
            lines.append(f"• [HIGH] {i['need']}")
    return "\n".join(lines)


def _push_status(rep: dict):
    """Try to send the actionable subset. Returns an explicit status string so a
    silent no-op can never be confused with a delivery failure:
      sent:<channel>     — delivered, dedupe state updated
      skip:no_config     — no memory/notify_channel.json (push not set up)
      skip:no_actionable — nothing high and no candidate to approve right now
      skip:unchanged     — same actionable set as the last push (deduped)
      skip:no_requests   — requests library missing
      fail:bad_channel   — config channel unknown / incomplete
      fail:send:<Type>   — the HTTP call errored (network/creds); disk brief still stands
    FAIL-OPEN: never raises to the caller."""
    cfg = _load(NOTIFY_CFG, {})
    if not cfg:
        return "skip:no_config"
    act = _actionable(rep)
    if not act:
        return "skip:no_actionable"
    sig = "|".join(sorted(f"{i['domain']}:{i['need']}" for i in act))
    if _load(PUSH_STATE, {}).get("last_sig") == sig:
        return "skip:unchanged"
    text = _push_text(rep, act)
    ch = cfg.get("channel")
    try:
        import requests  # requests-first: urllib 403s behind the proxy on this box
    except Exception:
        return "skip:no_requests"
    try:
        if ch == "ntfy":
            topic = cfg.get("topic")
            if not topic:
                return "fail:bad_channel"
            server = (cfg.get("server") or "https://ntfy.sh").rstrip("/")
            requests.post(f"{server}/{topic}", data=text.encode("utf-8"),
                          headers={"Title": "CORTEX needs", "Priority": "default",
                                   "Tags": "brain"}, timeout=15)
        elif ch == "telegram":
            token, chat_id = cfg.get("token"), cfg.get("chat_id")
            if not token or not chat_id:
                return "fail:bad_channel"
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": text}, timeout=15)
        else:
            return "fail:bad_channel"
    except Exception as e:
        return f"fail:send:{type(e).__name__}"  # network/creds — disk brief still stands
    # ONE-TAP APPROVALS: the brief landed, so now send each reply string as its OWN
    # message — bare "OK <id>", nothing else — so it can be copied with a single tap
    # instead of picked character-by-character out of a paragraph. The inline
    # "(reply: OK <id>)" hint stays in the brief; this is an addition, not a move.
    # Telegram only: on ntfy every message is a separate phone notification, and N of
    # them would be noise rather than convenience.
    # FAIL-OPEN and deliberately last: the brief is already delivered, so an extra that
    # fails must never downgrade a successful push into a failure.
    if ch == "telegram":
        _extras_sent = 0
        for _i in act:
            if not _i.get("approve_id"):
                continue
            try:
                requests.post(f"https://api.telegram.org/bot{cfg.get('token')}/sendMessage",
                              json={"chat_id": cfg.get("chat_id"),
                                    "text": f"OK {_i['approve_id']}"}, timeout=15)
                _extras_sent += 1
            except Exception:
                pass   # one unsent shortcut is a UX loss, not a delivery failure
        rep["_one_tap_sent"] = _extras_sent
    try:
        PUSH_STATE.parent.mkdir(parents=True, exist_ok=True)
        PUSH_STATE.write_text(json.dumps({"last_sig": sig,
                                          "ts": datetime.now(timezone.utc).isoformat()}),
                              encoding="utf-8")
    except Exception:
        pass
    return f"sent:{ch}"


def push(rep: dict):
    """Cycle-facing wrapper: returns the channel name on a real send, else None.
    (The cycle logs 'pushed via <channel>' only on sent:*.)"""
    st = _push_status(rep)
    return st.split(":", 1)[1] if st.startswith("sent:") else None


# back-compat alias
_push = _push_status


if __name__ == "__main__":
    rep = build()
    if "--json" in sys.argv:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        brief = _brief(rep)
        print(brief)
        if "--notify" in sys.argv:
            print(f"\n[needs] brief written -> {_notify(brief)}")
        if "--push" in sys.argv:
            st = _push_status(rep)
            gloss = {
                "skip:no_config": "push not set up (no notify_channel.json)",
                "skip:no_actionable": "nothing high and no candidate to approve now",
                "skip:unchanged": "same actionable set as last push — deduped, stayed quiet",
                "skip:no_requests": "requests library missing",
                "fail:bad_channel": "config channel unknown/incomplete",
            }.get(st, "sent to " + st.split(":", 1)[-1] if st.startswith("sent:")
                   else ("SEND FAILED — " + st if st.startswith("fail:") else st))
            print(f"[needs] push -> {st}  ({gloss})")
