#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/deduction.py — DEDUCTION LAYER v1 (14 Aug 2026, built live at Emil's order)

The system's first symbolic reasoning organ. Pure Python, no hyperon dependency
(a MeTTa mirror can be added later through hyperon_bridge — same facts, same rules).

PRINCIPLE (Emil, 13-14 Aug): a claim is only knowledge as the pair
"conclusion + premises a human can check". Every conclusion this engine emits
carries rule_id + the exact facts (file, key, value) it was derived from.
Rules are NOT sacred: memory/deduction_rule_stats.json counts every firing so a
rule that time refutes can be demoted by a human — earned trust, like everything
else in this repo.

Facts come only from files the cycle already writes:
  memory/auto_levels.json          — LLM level per axis (LOW/MEDIUM/HIGH)
  memory/trends_latest.json        — direction per axis (IMPROVING/STABLE/DETERIORATING)
  memory/goal_score_history.json   — last entry: numeric scores + score_sources
  config/target_config.json        — the canonical axis list

Consumers (wire-first, no orphan output):
  notes/next_actions.txt           — via daily_analysis_agent (human)
  needs_report                     — high-severity conclusions become needs (Telegram)
  memory/deductions_latest.json    — machine-readable, for orchestrator/cross-check
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT_FILE   = BASE / "memory" / "deductions_latest.json"
STATS_FILE = BASE / "memory" / "deduction_rule_stats.json"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gather_facts() -> dict:
    levels = _load(BASE / "memory" / "auto_levels.json", {})
    trends = _load(BASE / "memory" / "trends_latest.json", {})
    hist   = _load(BASE / "memory" / "goal_score_history.json", [])
    last   = hist[-1] if isinstance(hist, list) and hist else {}
    tc     = _load(BASE / "config" / "target_config.json", {})
    axes   = {ax for dom, a in tc.items() if not str(dom).startswith("_") for ax in a}
    # composer readings (the SENSES: anchor vs daily, browser_scout feeds among them) —
    # added same day at Emil's push: senses stay dumb, but their numbers MUST reach
    # the reasoning floor, not only indirectly through scores.
    comp = _load(BASE / "memory" / "composed_indicators.json", {})
    composed = {}
    for ax, doc in (comp.items() if isinstance(comp, dict) else []):
        c = (doc or {}).get("composed", {}) if isinstance(doc, dict) else {}
        composed[ax] = {
            "anchor": (c.get("anchor") or {}).get("value"),
            "anchor_org": (c.get("anchor") or {}).get("org"),
            "daily": (c.get("daily") or {}).get("value") if isinstance(c.get("daily"), dict) else c.get("daily"),
            "divergence": c.get("divergence"),
        }
    return {
        "levels":  {a: (d.get("level") if isinstance(d, dict) else d) for a, d in levels.items()},
        "trends":  {a: (d.get("direction") if isinstance(d, dict) else None) for a, d in trends.items()},
        "scores":  last.get("scores", {}),
        "sources": last.get("score_sources", {}),
        "config_axes": axes,
        "composed": composed,
    }


def _c(rule_id, axis, conclusion, severity, premises):
    return {"rule_id": rule_id, "axis": axis, "conclusion": conclusion,
            "severity": severity, "premises": premises}


def run_rules(f: dict) -> list:
    out = []
    all_axes = f["config_axes"] | set(f["levels"]) | set(f["scores"])

    # R7 — SENSOR REUSE: two different axes "measured" by the IDENTICAL anchor
    # reading (same value+org). Discovered live on 14 Aug: MATERIALS_WASTE's anchor
    # was NOAA CO2 ppm — the same instrument as CLIMATE. An axis wearing another
    # axis's sensor is not measured; it is dressed up. One conclusion per group.
    by_anchor = {}
    for ax2, c2 in f.get("composed", {}).items():
        if isinstance(c2.get("anchor"), (int, float)):
            by_anchor.setdefault((c2["anchor"], c2.get("anchor_org")), []).append(ax2)
    for (val, org), axs in by_anchor.items():
        if len(axs) > 1:
            out.append(_c("R7_SENSOR_REUSE", "+".join(sorted(axs)),
                          f"Оси {', '.join(sorted(axs))} споделят ЕДИН И СЪЩ anchor ({org}={val}) — поне една носи чужд сензор и реално не е измерена",
                          "high",
                          [{"file": "memory/composed_indicators.json",
                            "key": f"{a}.anchor", "value": val, "org": org} for a in sorted(axs)]))
    for ax in sorted(all_axes):
        lv  = f["levels"].get(ax)
        tr  = f["trends"].get(ax)
        sc  = f["scores"].get(ax)
        src = f["sources"].get(ax, "")
        p_lv = {"file": "memory/auto_levels.json", "key": ax, "value": lv}
        p_tr = {"file": "memory/trends_latest.json", "key": ax, "value": tr}
        p_sc = {"file": "memory/goal_score_history.json", "key": ax, "value": sc,
                "source": src}

        # R1 — critical AND worsening: the loudest possible alarm this data can justify.
        if lv == "LOW" and tr == "DETERIORATING":
            out.append(_c("R1_ALARM", ax,
                          f"{ax} е критична И се влошава — най-приоритетна ос по данни",
                          "high", [p_lv, p_tr]))

        # R2 — a measured score near the floor while the trend claims STABLE:
        # either the trend window is blind or the measurement broke. Someone must look.
        if isinstance(sc, (int, float)) and sc < 30 and tr == "STABLE" and src == "measured":
            out.append(_c("R2_CONTRADICTION", ax,
                          f"{ax}: измерени {sc} (<30), а трендът твърди STABLE — трендът или измерването е сляпо",
                          "high", [p_sc, p_tr]))

        # R3 — level says LOW while a MEASURED score is high: measurements outrank
        # opinions (13 Aug decision), so the LEVEL is what needs revision.
        if lv == "LOW" and isinstance(sc, (int, float)) and sc > 70:
            if src == "measured":
                out.append(_c("R3_REVISE_LEVEL", ax,
                              f"{ax}: ниво LOW при ИЗМЕРЕНИ {sc} — нивото е остаряло/грешно, измерването печели",
                              "high", [p_lv, p_sc]))
            else:
                out.append(_c("R3b_INVESTIGATE", ax,
                              f"{ax}: ниво LOW срещу LLM-оценка {sc} — мнение срещу мнение, никоя страна няма доказателство",
                              "medium", [p_lv, p_sc]))

        # R4 — critical but improving: recovery underway; keep attention, don't panic.
        if lv == "LOW" and tr == "IMPROVING":
            out.append(_c("R4_WATCH_RECOVERY", ax,
                          f"{ax} е критична, но се подобрява — възстановяване в ход, дръж под око",
                          "medium", [p_lv, p_tr]))

        # R6 — the SENSES disagree with themselves: the yearly anchor and the daily
        # feed for the same axis have diverged past 25% — one of the two instruments
        # (or the world) has moved sharply; a human must know WHICH numbers clash.
        cmp_ = f.get("composed", {}).get(ax, {})
        div = cmp_.get("divergence")  # АБСОЛЮТНА разлика (проверено 14 Aug: -4.02 = ppm, не процент!)
        anch = cmp_.get("anchor")
        rel = (div / anch) if (isinstance(div, (int, float)) and isinstance(anch, (int, float)) and anch) else None
        if rel is not None and abs(rel) > 0.10:
            out.append(_c("R6_SENSE_DIVERGENCE", ax,
                          f"{ax}: годишната котва и дневният сензор се разминават с {rel:+.1%} относително — инструмент или свят се е преместил рязко",
                          "high",
                          [{"file": "memory/composed_indicators.json", "key": f"{ax}.anchor",
                            "value": cmp_.get("anchor"), "org": cmp_.get("anchor_org")},
                           {"file": "memory/composed_indicators.json", "key": f"{ax}.daily",
                            "value": cmp_.get("daily")},
                           {"file": "memory/composed_indicators.json", "key": f"{ax}.divergence",
                            "value": div}]))

        # R5 — an axis the canon says exists but NOTHING measures or grades: a blind spot.
        if ax in f["config_axes"] and lv is None and sc is None:
            out.append(_c("R5_BLIND_SPOT", ax,
                          f"{ax} е в канона, но нито ниво, нито измерване съществуват — сляпо петно",
                          "medium",
                          [{"file": "config/target_config.json", "key": ax, "value": "declared"},
                           p_lv, p_sc]))
    return out


def _update_stats(conclusions: list) -> dict:
    stats = _load(STATS_FILE, {})
    for c in conclusions:
        r = stats.setdefault(c["rule_id"], {"fired_total": 0, "last_fired": None,
                                            "human_confirmed": 0, "human_refuted": 0})
        r["fired_total"] += 1
        r["last_fired"] = _now()
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        pass
    return stats


def run() -> dict:
    facts = gather_facts()
    conclusions = run_rules(facts)
    doc = {
        "ts": _now(),
        "engine": "deduction-v1 (pure python; MeTTa mirror pending)",
        "n_conclusions": len(conclusions),
        "conclusions": conclusions,
        "fact_files": ["memory/auto_levels.json", "memory/trends_latest.json",
                       "memory/goal_score_history.json", "config/target_config.json"],
    }
    try:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception as e:
        print(f"[DEDUCTION] write failed: {type(e).__name__}: {e}")
    _update_stats(conclusions)
    print(f"[DEDUCTION] {len(conclusions)} conclusion(s) from "
          f"{len(facts['config_axes'])} canonical axes")
    for c in conclusions:
        print(f"[DEDUCTION] [{c['rule_id']}] {c['conclusion'][:110]}")
    return doc


if __name__ == "__main__":
    run()
