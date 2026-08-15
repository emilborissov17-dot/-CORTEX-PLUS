#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/kimi_duel/duel.py
=============================
PRE-REGISTERED DUEL: Kimi K3 (challenger) vs current primary backbone (Groq
llama-3.3-70b-versatile).  This is an EVALUATION HARNESS ONLY — it does NOT
integrate Kimi into core/groq_backend.py or the live fallback chain.

--------------------------------------------------------------------------
WHAT IS COMPARED
--------------------------------------------------------------------------
6 REAL prompts, harvested from the actual live prompt builders (never invented):

  AXIS-SCORING (JSON schema)  -- verbatim from fast_cycle_runner.refresh_llm_axes
    T1  GOAL_PROGRESS_REVIEW        (fast_cycle_runner.py:170-177)
    T2  LONG_TERM_FUTURE_REVIEW     (fast_cycle_runner.py:183-188)

  WEB-INTEL URGENCY SUMMARIES -- captured from web_intelligence_agent._analyze_for_axis
    T3  GOAL_PROGRESS_REVIEW    (real RSS items fetched via the pipeline's _fetch_rss)
    T4  LONG_TERM_FUTURE_REVIEW (real RSS items fetched via the pipeline's _fetch_rss)

  GLOBAL SYNTHESIS            -- captured from the two real global synthesizers
    T5  cortex_strategist_agent.synthesize(scan_project())      (JSON, full-project)
    T6  daily_analysis_agent._generate_overall_assessment(...)  (FREE TEXT / Bulgarian)

The web-intel and synthesis prompts are captured by monkeypatching each builder's
LLM entry point with a stub that records the EXACT prompt string the builder built
(real builder + real live data) and aborts before any real network/LLM call or
snapshot write.  Zero reconstruction, zero invention.

Primary side  : groq_backend._call_groq (the real first link of the live chain,
                Groq llama-3.3-70b-versatile), isolated — NOT the full fallback
                chain, so the comparison is model-vs-model.
Challenger side: moonshotai/kimi-k3 via OpenRouter (exact slug verified against
                https://openrouter.ai/api/v1/models on 2026-07-23; ctx 1,048,576;
                $3.00 / 1M input tok, $15.00 / 1M output tok).

==========================================================================
PRE-DECLARED CRITERIA  (frozen in code BEFORE the single run — see CRITERIA)
==========================================================================
Per task, per model, we record: json_valid, schema-field completeness (0..1),
citation_present, latency_s, cost_usd.

DECISIVE metric (per the pre-registration): JSON validity + schema completeness.
  * Per-task "better": compare the tuple (json_rank, completeness), where
        json_rank = 1 if json_valid else 0            (for JSON-expected tasks)
        json_rank = 1 if output non-empty else 0      (for the free-text task T6)
    The model with the strictly greater tuple wins that task; equal tuples => TIE.
  * WINNER RULE: the challenger (Kimi K3) replaces the current backbone ONLY IF it
    wins >= 4 of the 6 tasks on (json_valid + completeness).
  * TIE-BREAK: anything short of Kimi winning >= 4/6  ==>  KEEP CURRENT.

Latency, cost, and citation presence are RECORDED and REPORTED but are NOT
decisive under the pre-registered rule above.
--------------------------------------------------------------------------
Run once:  PYTHONIOENCODING=utf-8 venv/Scripts/python.exe experiments/kimi_duel/duel.py
Outputs:   experiments/kimi_duel/results.json  (raw outputs + scores)  + scorecard to stdout
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

RESULTS_PATH = Path(__file__).resolve().parent / "results.json"

KIMI_SLUG          = "moonshotai/kimi-k3"
KIMI_PRICE_IN      = 3.0 / 1_000_000     # USD per input token
KIMI_PRICE_OUT     = 15.0 / 1_000_000    # USD per output token
PRIMARY_MODEL_NAME = "Groq llama-3.3-70b-versatile"

# ── PRE-DECLARED, FROZEN BEFORE RUN ──────────────────────────────────────────
CRITERIA = {
    "decisive_metrics": ["json_valid", "schema_field_completeness"],
    "reported_only":    ["citation_present", "latency_s", "cost_usd"],
    "per_task_better":  "greater tuple (json_rank, completeness); equal => TIE",
    "winner_rule":      "challenger replaces current ONLY IF it wins >= 4/6 tasks",
    "tie_break":        "anything < 4/6 for challenger => KEEP CURRENT",
    "frozen_at":        "declared in source before the single run; not tuned post-hoc",
}
CHALLENGER_WIN_THRESHOLD = 4   # out of 6


# ── capture machinery (BaseException escapes the builders' `except Exception`) ─
class _Captured(BaseException):
    def __init__(self, prompt: str):
        self.prompt = prompt
        super().__init__("prompt captured")


def _capture_call_groq(prompt, *a, **k):
    raise _Captured(prompt)


def _capture_groq_dict(prompt, *a, **k):
    raise _Captured(prompt)


# ── tolerant JSON extraction (mirrors what the live parsers tolerate) ─────────
def _clean(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if "```json" in t:
        t = t.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in t:
        parts = t.split("```")
        if len(parts) >= 3:
            t = parts[1].strip()
    return t.strip()


def _try_json(text: str):
    for cand in (text, _clean(text)):
        cand = (cand or "").strip()
        if not cand:
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    # last resort: largest {...} block
    for m in sorted(re.findall(r"\{.*\}", text or "", re.DOTALL), key=len, reverse=True):
        try:
            obj = json.loads(m)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


# ── PROMPT HARVEST ───────────────────────────────────────────────────────────
def harvest_axis_prompts() -> list:
    """T1/T2 — copied VERBATIM from fast_cycle_runner.refresh_llm_axes (the
    prompt strings are function-local literals; reproduced here byte-for-byte
    with source citation, not paraphrased)."""
    goal = (
        "You are CORTEX++ AGI working toward: sustainable civilization, "
        "dignity for all, AGI in transparent service of humanity. "
        "Generate JSON for GOAL_PROGRESS_REVIEW. Include: "
        "current_level (LOW/MEDIUM/HIGH), overall_progress_pct (0-100), "
        "progress_by_domain dict (HUMAN/PLANET/CIVILIZATION/COSMOS each 0-100), "
        "main_bottlenecks list, next_actions list. Return ONLY valid JSON."
    )
    ltf = (
        "Generate fresh JSON for LONG_TERM_FUTURE_REVIEW "
        "(existential risks: nuclear, AGI misalignment, biorisks, climate collapse). "
        "Include: current_level, xrisk_score (0-100, lower=safer), "
        "main_risks list, trends list. Return ONLY valid JSON."
    )
    return [
        {"id": "T1", "kind": "axis_scoring", "label": "AXIS GOAL_PROGRESS_REVIEW",
         "source": "fast_cycle_runner.py:170-177", "prompt": goal, "max_tokens": 1024,
         "json_expected": True,
         "expected_fields": ["current_level", "overall_progress_pct",
                             "progress_by_domain", "main_bottlenecks", "next_actions"]},
        {"id": "T2", "kind": "axis_scoring", "label": "AXIS LONG_TERM_FUTURE_REVIEW",
         "source": "fast_cycle_runner.py:183-188", "prompt": ltf, "max_tokens": 1024,
         "json_expected": True,
         "expected_fields": ["current_level", "xrisk_score", "main_risks", "trends"]},
    ]


def _fetch_real_items(wia, axis: str, urls: list, keywords: list) -> list:
    items = []
    for u in urls:
        try:
            items.extend(wia._fetch_rss(u, max_items=4))
        except Exception as e:
            print(f"    [harvest] RSS {u[:50]} failed: {e}")
        time.sleep(0.2)
    if len(items) < 3 and getattr(wia, "HAS_DDG", False):
        for kw in keywords[:2]:
            try:
                items.extend(wia._ddg_search(kw, max_results=3))
            except Exception:
                pass
    return items


def harvest_webintel_prompts() -> list:
    """T3/T4 — capture the EXACT prompt web_intelligence_agent._analyze_for_axis
    builds, over REAL items fetched live through the pipeline's own _fetch_rss."""
    import web_intelligence_agent as wia
    orig = wia.call_groq
    wia.call_groq = _capture_call_groq
    out = []
    specs = [
        ("T3", "WEB-INTEL GOAL_PROGRESS_REVIEW", "GOAL_PROGRESS_REVIEW", "cosmos",
         ["https://www.un.org/sustainabledevelopment/feed/", "https://sdg.iisd.org/feed/"],
         ["sustainable development goals", "SDG", "UN goals 2030"]),
        ("T4", "WEB-INTEL LONG_TERM_FUTURE_REVIEW", "LONG_TERM_FUTURE_REVIEW", "cosmos",
         ["https://www.lesswrong.com/feed.xml", "https://forum.effectivealtruism.org/feed.xml"],
         ["existential risk", "civilization collapse", "future of humanity"]),
    ]
    try:
        for tid, label, axis, domain, urls, kws in specs:
            items = _fetch_real_items(wia, axis, urls, kws)
            print(f"    [harvest] {axis}: {len(items)} real items fetched")
            captured = None
            try:
                wia._analyze_for_axis(axis, items, domain)
            except _Captured as c:
                captured = c.prompt
            if captured is None:
                print(f"    [harvest] WARNING: {axis} produced no prompt "
                      f"(no live items) — task skipped")
                continue
            out.append({
                "id": tid, "kind": "web_intel_urgency", "label": label,
                "source": "web_intelligence_agent._analyze_for_axis",
                "n_real_items": len(items),
                "prompt": captured, "max_tokens": 800, "json_expected": True,
                "expected_fields": ["problem", "root_cause", "severity",
                                    "leverage_points", "proposed_actions", "evidence",
                                    "generalization", "summary", "risk_level"],
            })
    finally:
        wia.call_groq = orig
    return out


def harvest_strategist_prompt() -> list:
    """T5 — capture the EXACT global strategic-synthesis prompt built by
    cortex_strategist_agent.synthesize over the real scan_project() context."""
    import agents.cortex_strategist.cortex_strategist_agent as strat
    orig = strat._groq
    strat._groq = _capture_groq_dict
    captured = None
    try:
        ctx = strat.scan_project()
        try:
            strat.synthesize(ctx)
        except _Captured as c:
            captured = c.prompt
    finally:
        strat._groq = orig
    if captured is None:
        print("    [harvest] WARNING: strategist produced no prompt — task skipped")
        return []
    return [{
        "id": "T5", "kind": "global_synthesis", "label": "SYNTHESIS cortex_strategist",
        "source": "cortex_strategist_agent.synthesize",
        "prompt": captured, "max_tokens": 1500, "json_expected": True,
        "expected_fields": ["system_health", "mission_alignment_pct", "critical_gaps",
                            "immediate_actions", "missing_agents_to_build",
                            "fast_cycle_improvements", "next_milestone",
                            "strategist_self_assessment"],
    }]


def harvest_daily_prompt() -> list:
    """T6 — capture the EXACT global overall-assessment prompt built by
    daily_analysis_agent._generate_overall_assessment, over a REAL analyses dict
    derived from the live master snapshot's per-axis levels (free-text output)."""
    import agents.core.daily_analysis_agent as daily
    # real analyses from the live master snapshot
    analyses = {}
    snap = BASE / "snapshots" / "master" / "master_snapshot_latest.json"
    try:
        m = json.loads(snap.read_text(encoding="utf-8"))
        for axis, s in m.get("snapshots", {}).items():
            if not isinstance(s, dict):
                continue
            lvl = s.get("current_level") or s.get("level") or "UNKNOWN"
            analyses[axis] = {"current_level": lvl}
    except Exception as e:
        print(f"    [harvest] daily: could not read master snapshot: {e}")
    orig = daily._llm
    daily._llm = _capture_call_groq
    captured = None
    try:
        try:
            daily._generate_overall_assessment(analyses)
        except _Captured as c:
            captured = c.prompt
    finally:
        daily._llm = orig
    if captured is None:
        print("    [harvest] WARNING: daily synthesis produced no prompt — task skipped")
        return []
    return [{
        "id": "T6", "kind": "global_synthesis", "label": "SYNTHESIS daily_overall_assessment",
        "source": "daily_analysis_agent._generate_overall_assessment",
        "n_axes": len(analyses),
        "prompt": captured, "max_tokens": 1024, "json_expected": False,
        "expected_fields": None,
    }]


def harvest_all() -> list:
    tasks = []
    tasks += harvest_axis_prompts()
    for fn in (harvest_webintel_prompts, harvest_strategist_prompt, harvest_daily_prompt):
        try:
            tasks += fn()
        except Exception as e:
            print(f"    [harvest] {fn.__name__} FAILED: {e}")
    return tasks


# ── MODEL RUNNERS ────────────────────────────────────────────────────────────
def run_primary(prompt: str, max_tokens: int) -> dict:
    """Current primary backbone, isolated: groq_backend._call_groq (Groq)."""
    import core.groq_backend as gb
    gb._SLEEP_SECS = 0.0  # harness: skip the adaptive inter-call sleep
    last = None
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            content, meta = gb._call_groq(prompt, max_tokens)
            dt = round(time.monotonic() - t0, 3)
            return {"ok": True, "text": content, "latency_s": dt,
                    "cost_usd": 0.0,  # Groq free tier
                    "backend": "Groq(primary)", "finish_reason": meta.get("finish_reason")}
        except Exception as e:
            last = str(e)[:200]
            time.sleep(3)
    return {"ok": False, "text": "", "latency_s": None, "cost_usd": 0.0,
            "backend": "Groq(primary)", "error": last}


# Kimi K3 is a REASONING model: it spends output tokens on a hidden reasoning
# phase BEFORE emitting the answer. Run-1 (2026-07-23) used the pipeline's real
# per-call budgets (800-1500) and every response came back with finish_reason=
# "length" and EMPTY content — the reasoning phase ate the whole budget. To give
# the challenger a fair shot, the harness now (a) floors the output budget high
# enough for reasoning+answer, and (b) falls back to the `reasoning` field when
# `content` is empty (mirroring groq_backend._call_cerebras). A response that is
# STILL empty-with-finish_reason=length is flagged budget_starved (invalid), not
# scored as a quality loss.
KIMI_REASONING_FLOOR = 8000  # output-token floor for the reasoning model


def run_kimi(prompt: str, max_tokens: int) -> dict:
    """Challenger: moonshotai/kimi-k3 via OpenRouter (same system msg, isolated)."""
    import requests
    import core.groq_backend as gb
    key = gb._load_key("OPENROUTER_API_KEY")
    if not key:
        return {"ok": False, "text": "", "latency_s": None, "cost_usd": None,
                "backend": KIMI_SLUG, "error": "OPENROUTER_API_KEY missing"}
    budget = max(max_tokens, KIMI_REASONING_FLOOR)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cortex-agi",
    }
    payload = {
        "model": KIMI_SLUG,
        "messages": [
            {"role": "system", "content": gb._system_msg()},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": budget,
    }
    last = None
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            r = requests.post(gb.OPENROUTER_API_URL, headers=headers, json=payload,
                              timeout=(10, 240))
            dt = round(time.monotonic() - t0, 3)
            if r.status_code == 402:
                return {"ok": False, "text": "", "latency_s": dt, "cost_usd": None,
                        "backend": KIMI_SLUG, "error": "HTTP 402 — OpenRouter credits exhausted"}
            r.raise_for_status()
            j = r.json()
            choice = j["choices"][0]
            msg = choice["message"]
            finish = choice.get("finish_reason")
            content = (msg.get("content") or "")
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            used_reasoning_fallback = False
            if not content:
                reasoning = (msg.get("reasoning") or "").strip()
                if reasoning:
                    content = reasoning
                    used_reasoning_fallback = True
            budget_starved = (not content) and finish == "length"
            usage = j.get("usage", {}) or {}
            pt = usage.get("prompt_tokens", 0) or 0
            ct = usage.get("completion_tokens", 0) or 0
            cost = round(pt * KIMI_PRICE_IN + ct * KIMI_PRICE_OUT, 6)
            return {"ok": True, "text": content, "latency_s": dt, "cost_usd": cost,
                    "backend": KIMI_SLUG, "finish_reason": finish,
                    "budget_used": budget, "used_reasoning_fallback": used_reasoning_fallback,
                    "budget_starved": budget_starved,
                    "prompt_tokens": pt, "completion_tokens": ct}
        except Exception as e:
            last = str(e)[:200]
            time.sleep(3)
    return {"ok": False, "text": "", "latency_s": None, "cost_usd": None,
            "backend": KIMI_SLUG, "error": last}


# ── SCORING (uses the PRE-DECLARED criteria only) ────────────────────────────
def score_output(task: dict, run: dict) -> dict:
    text = run.get("text", "") or ""
    non_empty = bool(text.strip())
    json_expected = task["json_expected"]
    obj = _try_json(text) if json_expected else None
    json_valid = bool(obj is not None) if json_expected else None

    if json_expected:
        fields = task["expected_fields"] or []
        if obj:
            present = sum(1 for f in fields
                          if f in obj and obj[f] not in (None, "", [], {}))
            completeness = round(present / len(fields), 3) if fields else 0.0
        else:
            completeness = 0.0
        json_rank = 1 if json_valid else 0
    else:
        # free-text task (T6): pre-declared prose completeness ladder
        s = text.strip()
        if len(s) >= 200 and s.count(".") >= 4:
            completeness = 1.0
        elif len(s) >= 80:
            completeness = 0.5
        else:
            completeness = 0.0
        json_rank = 1 if non_empty else 0

    # citation presence (reported only): URL, non-empty evidence, or a .py filename
    cite = bool(re.search(r"https?://", text))
    if obj and isinstance(obj.get("evidence"), list) and obj["evidence"]:
        cite = True
    if re.search(r"\b[\w/]+\.py\b", text):
        cite = True

    return {
        "json_valid": json_valid,
        "completeness": completeness,
        "json_rank": json_rank,
        "citation_present": cite,
        "latency_s": run.get("latency_s"),
        "cost_usd": run.get("cost_usd"),
        "ok": run.get("ok", False),
        "error": run.get("error"),
    }


def task_winner(primary: dict, kimi: dict) -> str:
    a = (primary["json_rank"], primary["completeness"])
    b = (kimi["json_rank"], kimi["completeness"])
    if b > a:
        return "KIMI"
    if a > b:
        return "PRIMARY"
    return "TIE"


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 74)
    print("  PRE-REGISTERED DUEL — Kimi K3 vs current primary backbone")
    print(f"  challenger : {KIMI_SLUG} (OpenRouter)")
    print(f"  primary    : {PRIMARY_MODEL_NAME} (isolated first link of live chain)")
    print(f"  winner rule: challenger replaces current IFF wins >= "
          f"{CHALLENGER_WIN_THRESHOLD}/6 on (json_valid + completeness)")
    print("=" * 74)

    print("\n[1/3] Harvesting 6 REAL prompts from live builders...")
    tasks = harvest_all()
    print(f"      harvested {len(tasks)} tasks: {[t['id'] for t in tasks]}")

    print("\n[2/3] Running each prompt against BOTH models (single run)...")
    records = []
    for t in tasks:
        print(f"  -- {t['id']} {t['label']} (max_tokens={t['max_tokens']})")
        pr = run_primary(t["prompt"], t["max_tokens"])
        print(f"       primary: ok={pr['ok']} latency={pr.get('latency_s')}s")
        kr = run_kimi(t["prompt"], t["max_tokens"])
        print(f"       kimi   : ok={kr['ok']} latency={kr.get('latency_s')}s "
              f"cost=${kr.get('cost_usd')}")
        ps = score_output(t, pr)
        ks = score_output(t, kr)
        winner = task_winner(ps, ks)
        records.append({
            "id": t["id"], "label": t["label"], "kind": t["kind"],
            "source": t["source"], "json_expected": t["json_expected"],
            "expected_fields": t["expected_fields"],
            "prompt": t["prompt"],
            "primary": {"raw_output": pr.get("text", ""), **ps},
            "kimi":    {"raw_output": kr.get("text", ""), **ks},
            "task_winner": winner,
        })

    # ── tally per pre-declared rule ──
    n = len(records)
    kimi_wins    = sum(1 for r in records if r["task_winner"] == "KIMI")
    primary_wins = sum(1 for r in records if r["task_winner"] == "PRIMARY")
    ties         = sum(1 for r in records if r["task_winner"] == "TIE")
    decision = ("ADOPT_KIMI_K3" if kimi_wins >= CHALLENGER_WIN_THRESHOLD
                else "KEEP_CURRENT")

    json_tasks = [r for r in records if r["json_expected"]]
    def _rate(side):
        if not json_tasks:
            return None
        return round(sum(1 for r in json_tasks if r[side]["json_valid"]) / len(json_tasks), 3)

    def _avg(side, key):
        vals = [r[side][key] for r in records if isinstance(r[side].get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "n_tasks": n,
        "kimi_task_wins": kimi_wins,
        "primary_task_wins": primary_wins,
        "ties": ties,
        "challenger_win_threshold": CHALLENGER_WIN_THRESHOLD,
        "decision": decision,
        "valid_json_rate": {"primary": _rate("primary"), "kimi": _rate("kimi"),
                            "denominator_json_tasks": len(json_tasks)},
        "avg_completeness": {"primary": _avg("primary", "completeness"),
                             "kimi": _avg("kimi", "completeness")},
        "avg_latency_s": {"primary": _avg("primary", "latency_s"),
                          "kimi": _avg("kimi", "latency_s")},
        "total_cost_usd": {"primary": 0.0,
                           "kimi": round(sum(r["kimi"]["cost_usd"] for r in records
                                             if isinstance(r["kimi"].get("cost_usd"), (int, float))), 6)},
    }

    out = {
        "meta": {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "challenger": KIMI_SLUG,
            "challenger_pricing_usd_per_token": {"input": KIMI_PRICE_IN, "output": KIMI_PRICE_OUT},
            "challenger_context_length": 1_048_576,
            "primary": PRIMARY_MODEL_NAME,
            "integration_status": "EVALUATION ONLY — not wired into call_groq",
        },
        "pre_declared_criteria": CRITERIA,
        "summary": summary,
        "tasks": records,
    }
    RESULTS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── scorecard ──
    print("\n[3/3] SCORECARD")
    print("=" * 74)
    hdr = f"{'TASK':<34}{'json P/K':<11}{'compl P/K':<13}{'winner':<9}"
    print(hdr)
    print("-" * 74)
    for r in records:
        p, k = r["primary"], r["kimi"]
        jv = lambda x: ("-" if x["json_valid"] is None else ("Y" if x["json_valid"] else "n"))
        js = f"{jv(p)}/{jv(k)}"
        cs = f"{p['completeness']:.2f}/{k['completeness']:.2f}"
        print(f"{(r['id']+' '+r['label']):<34}{js:<11}{cs:<13}{r['task_winner']:<9}")
    print("-" * 74)
    print(f"valid-JSON rate (JSON tasks)  primary={summary['valid_json_rate']['primary']}  "
          f"kimi={summary['valid_json_rate']['kimi']}")
    print(f"avg completeness              primary={summary['avg_completeness']['primary']}  "
          f"kimi={summary['avg_completeness']['kimi']}")
    print(f"avg latency (s)               primary={summary['avg_latency_s']['primary']}  "
          f"kimi={summary['avg_latency_s']['kimi']}")
    print(f"total cost (USD)              primary={summary['total_cost_usd']['primary']}  "
          f"kimi={summary['total_cost_usd']['kimi']}")
    print("-" * 74)
    print(f"TASK WINS   kimi={kimi_wins}  primary={primary_wins}  ties={ties}   "
          f"(threshold for adopt: kimi >= {CHALLENGER_WIN_THRESHOLD}/{n})")
    print(f"DECISION    >>> {decision} <<<")
    print("=" * 74)
    print(f"raw outputs saved -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
