#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backend_league.py — WHICH CLOUD MIND GOES FIRST, BY MEASUREMENT (11 Sep 2026).

Emil: "order the most effective first". Effective is measured here, from what the
chain itself wrote down, not from a leaderboard on the internet:

  memory/llm_provenance.jsonl                  every cloud call: backend, model, outcome,
                                               http_status, finish_reason, latency_s
  memory/counterfactual_probe_by_model.json    does this mind read the number? (point 13)

Per backend over the last WINDOW_DAYS:
  success   = ok / (ok + error)                 a mind that does not answer is not effective
  complete  = 1 - share of ok answers cut at the token limit (finish_reason=length)
  speed     = 1 / (1 + median latency_s / 20)  20 s is one third of a typical step slice
  reads     = probe tracks_rate for that model, if measured; else neutral 0.5

  score = success * complete * (0.7 + 0.3 * speed) * (0.5 + 0.5 * reads)

A backend with fewer than MIN_CALLS calls in the window is UNMEASURED: it is placed
SECOND (right after the leader) so it earns data without taking the first slot on
faith. Output: memory/backend_order_measured.json (read by core/groq_backend.py,
ignored when older than 8 days) + claude/reports/BACKEND_LEAGUE.md.

Usage:
  venv\\Scripts\\python.exe scripts\\backend_league.py            # print
  venv\\Scripts\\python.exe scripts\\backend_league.py --write    # + order file + report
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROVENANCE = REPO / "memory" / "llm_provenance.jsonl"
PROBE = REPO / "memory" / "counterfactual_probe_by_model.json"
ORDER = REPO / "memory" / "backend_order_measured.json"
REPORT = REPO / "claude" / "reports" / "BACKEND_LEAGUE.md"

KEYS = {"Groq": "groq", "NVIDIA-Kimi": "nvidia", "OpenRouter": "openrouter", "Gemini": "gemini"}
DEFAULT_ORDER = ["groq", "nvidia", "openrouter", "gemini"]
WINDOW_DAYS = 7
MIN_CALLS = 30


def _rows(path: Path) -> list[dict]:
    out = []
    for p in (path.with_suffix(".jsonl.1"), path):          # the 5 MB rotation keeps one old file
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            continue
    return out


def _reads(probe_path: Path) -> dict[str, float]:
    """model id -> tracks_rate, from the probe's per-mind comparison."""
    try:
        bm = json.loads(probe_path.read_text(encoding="utf-8")).get("by_model") or {}
    except Exception:
        return {}
    out = {}
    for name, m in bm.items():
        tr = m.get("tracks_rate")
        if tr is None:
            continue
        for seen in m.get("models_seen") or [name]:
            out[str(seen).split("groq:", 1)[-1]] = float(tr)
        out[name.split("groq:", 1)[-1]] = float(tr)
    return out


def league(rows: list[dict], reads: dict[str, float], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    stats: dict[str, dict] = {}
    for r in rows:
        key = KEYS.get(r.get("backend"))
        if not key:
            continue
        try:
            ts = datetime.fromisoformat(str(r.get("ts")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < since:
            continue
        s = stats.setdefault(key, {"ok": 0, "error": 0, "rate_limited": 0, "truncated": 0, "lat": [], "models": set()})
        if r.get("model"):
            s["models"].add(str(r["model"]))
        if r.get("outcome") == "error":
            s["error"] += 1
            if r.get("http_status") == 429 or "rate limit" in str(r.get("error", "")).lower():
                s["rate_limited"] += 1
        else:
            s["ok"] += 1
            if r.get("finish_reason") == "length":
                s["truncated"] += 1
            if isinstance(r.get("latency_s"), (int, float)):
                s["lat"].append(float(r["latency_s"]))
    table = {}
    for key in DEFAULT_ORDER:
        s = stats.get(key)
        if not s:
            table[key] = {"calls": 0, "measured": False}
            continue
        calls = s["ok"] + s["error"]
        success = s["ok"] / calls if calls else 0.0
        complete = 1 - (s["truncated"] / s["ok"]) if s["ok"] else 0.0
        med = statistics.median(s["lat"]) if s["lat"] else None
        speed = 1 / (1 + med / 20) if med is not None else 0.5
        rd = [reads[m] for m in s["models"] if m in reads]
        read = max(rd) if rd else None
        score = success * complete * (0.7 + 0.3 * speed) * (0.5 + 0.5 * (read if read is not None else 0.5))
        table[key] = {"calls": calls, "measured": calls >= MIN_CALLS, "success": round(success, 3),
                      "complete": round(complete, 3), "rate_limited": s["rate_limited"],
                      "median_latency_s": round(med, 2) if med is not None else None,
                      "reads_number": read, "models": sorted(s["models"]), "score": round(score, 4)}
    measured = sorted([k for k, v in table.items() if v.get("measured")], key=lambda k: -table[k]["score"])
    unmeasured = [k for k in DEFAULT_ORDER if k not in measured]
    order = (measured[:1] + unmeasured + measured[1:]) if measured else list(DEFAULT_ORDER)
    return {"ts": now.isoformat()[:19] + "Z", "window_days": WINDOW_DAYS, "min_calls": MIN_CALLS,
            "order": order, "table": table,
            "rule": "measured backends by score; unmeasured ones placed right after the leader to earn data"}


def markdown(lg: dict) -> str:
    L = ["# BACKEND LEAGUE — which cloud mind goes first, by measurement", "",
         f"_{lg['ts']} · last {lg['window_days']} days · a backend needs {lg['min_calls']} calls to be ranked_", "",
         "| backend | calls | success | complete | 429s | median s | reads the number | score | ranked |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for k, v in lg["table"].items():
        if not v.get("calls"):
            L.append(f"| {k} | 0 | — | — | — | — | — | — | not in use |")
            continue
        L.append(f"| {k} | {v['calls']} | {v['success']} | {v['complete']} | {v['rate_limited']} | "
                 f"{v['median_latency_s']} | {v['reads_number']} | {v['score']} | {'yes' if v['measured'] else 'UNMEASURED'} |")
    L += ["", f"**Order tonight:** {' → '.join(lg['order'])} → local (degraded, last resort)", "",
          f"Rule: {lg['rule']}. core/groq_backend.py reads memory/backend_order_measured.json and ignores it "
          "after 8 days, so a league that stops running cannot freeze an old order in place.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    lg = league(_rows(PROVENANCE), _reads(PROBE))
    md = markdown(lg)
    if "--write" in sys.argv:
        ORDER.parent.mkdir(parents=True, exist_ok=True)
        ORDER.write_text(json.dumps({"ts": lg["ts"], "order": lg["order"], "source": "scripts/backend_league.py"},
                                    indent=1), encoding="utf-8")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(md, encoding="utf-8")
        print(f"wrote {ORDER} and {REPORT}")
    print(md)
