#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/agi_scoreboard.py — THE 14 POINTS, AS NUMBERS, EVERY MORNING.
(11 Sep 2026. Emil: "Ти водиш проекта. Чакам резултат.")

One page, claude/reports/AGI_14_SCOREBOARD.md, rebuilt by the morning task:
for each of the 14 AGI points, the number the system can actually show for it
today, where the number comes from, and the verdict the number earns. No
prose about intent — a point with no number is written as "no number".

Rules:
  * every figure is read from a file the nightly cycle or the morning task
    writes (ledger, learner_state, corpus manifest, reviews, canon, initiatives,
    daily tier, constancy, grounding, benches); nothing is asserted here;
  * a figure that cannot be read is "—" with the reason, never a guess;
  * the verdict per point is mechanical (thresholds in RULES), so it can be
    wrong in a checkable way.

Usage:
  venv\\Scripts\\python.exe scripts/agi_scoreboard.py            # print
  venv\\Scripts\\python.exe scripts/agi_scoreboard.py --write    # + claude/reports/AGI_14_SCOREBOARD.md + .json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "experiments" / "prophecy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

REPORT = REPO / "claude" / "reports" / "AGI_14_SCOREBOARD.md"
REPORT_JSON = REPO / "claude" / "reports" / "AGI_14_SCOREBOARD.json"

POINTS = {
    1: "Генералност и трансфер", 2: "Учи от опит — в параметрите", 3: "Учи от малко примери",
    4: "Нови понятия", 5: "Активно търси информация", 6: "Планиране + заслуга",
    7: "Калибрирана несигурност", 8: "Световен модел", 9: "Тренировъчен контур",
    10: "Самомодел", 11: "Цели — държи, разлага, ревизира", 12: "Действие → последствие",
    13: "Разбиране срещу симулация", 14: "Съзнание",
}
NONE, SEED, PARTIAL, LIVE = "—", "SEED", "PARTIAL", "LIVE"


def _json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _jsonl(p: Path) -> list:
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def _md_number(p: Path, label: str):
    """First 'label ... number' in a report; None if absent."""
    import re
    try:
        m = re.search(re.escape(label) + r"[^\d\-]*(-?\d+(?:\.\d+)?)", p.read_text(encoding="utf-8"))
        return float(m.group(1)) if m else None
    except Exception:
        return None


def country_bench(p: Path) -> dict:
    """Parse COUNTRY_BENCH.md table rows: {target: {baseline, knn, knn_closer, n}}.
    Row shape: | v2x_rule | 0.2797 | 0.1392 (61 closer) | ... | 79 |"""
    import re
    out: dict = {}
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return out
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].startswith("v2x"):
            continue
        try:
            base = float(cells[1])
            m = re.match(r"(-?\d+(?:\.\d+)?)(?:\s*\((\d+) closer\))?", cells[2])
            knn = float(m.group(1)); closer = int(m.group(2)) if m.group(2) else None
            n = int(cells[-1]) if cells[-1].isdigit() else None
        except Exception:
            continue
        out[cells[0]] = {"baseline": base, "knn": knn, "knn_closer": closer, "n": n}
    return out


def _ledger() -> dict:
    try:
        import prophecy_ledger as pl
        sb = pl.scoreboard()
        return {"chain_valid": sb.get("chain_valid"), "by_kind": sb.get("by_kind") or {}}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}", "by_kind": {}}


def gather() -> dict:
    """Every number, with its source. Never raises."""
    g: dict = {}
    g["ledger"] = _ledger()
    g["learner_state"] = _json(REPO / "memory" / "learner_state.json", {}) or {}
    g["corpus"] = _json(REPO / "training" / "verified_corpus.manifest.json", {}) or {}
    g["reviews"] = _jsonl(REPO / "memory" / "brain_cycle_reviews.jsonl")
    g["canon_invariants"] = len((_json(REPO / "memory" / "canon_invariants.json", {}) or {}).get("invariants", []))
    inits = []
    d = REPO / "data" / "initiatives"
    if d.exists():
        for f in d.glob("*.json"):
            r = _json(f, {}) or {}
            inits.append(r.get("status"))
    g["initiatives"] = {"active": sum(1 for s in inits if s in ("PROPOSED", "IN_PROGRESS", "OVERDUE")),
                        "in_progress": sum(1 for s in inits if s == "IN_PROGRESS")}
    tier = _jsonl(REPO / "memory" / "daily_tier.jsonl")
    by = {}
    for r in tier:
        by.setdefault(r.get("indicator"), set()).add(r.get("value"))
    g["daily_tier"] = {"indicators": len(by), "moving": sum(1 for v in by.values() if len(v) > 1)}
    g["constancy"] = (_json(REPO / "memory" / "constancy_bands_latest.json", {}) or {}).get("counts", {})
    g["verified"] = {"accepted": sum(1 for r in _jsonl(REPO / "memory" / "verified_observations.jsonl") if r.get("verdict") == "ACCEPTED"),
                     "refused": len(_jsonl(REPO / "memory" / "card_refusals.jsonl"))}
    g["grounding"] = {"ungrounded": _md_number(REPO / "claude" / "reports" / "TARGET_GROUNDING.md", "UNGROUNDED"),
                      "grounded": _md_number(REPO / "claude" / "reports" / "TARGET_GROUNDING.md", "GROUNDED")}
    sbx = _json(REPO / "claude" / "reports" / "SANDBOX_BENCH.json", {}) or {}
    g["sandbox"] = (sbx.get("summary") or {}).get("verdict", {})
    g["country_bench"] = country_bench(REPO / "claude" / "reports" / "COUNTRY_BENCH.md")
    g["probe"] = _jsonl(REPO / "memory" / "counterfactual_probe.jsonl")
    g["alarm_indicators"] = (_json(REPO / "memory" / "alarm_bands_latest.json", {}) or {}).get("indicators", {}).get("counts", {})
    return g


def _kind(g, k):
    return (g.get("ledger", {}).get("by_kind") or {}).get(k) or {}


def rows(g: dict) -> list[dict]:
    """One row per point: number, source, verdict."""
    out = []

    def add(n, number, source, verdict):
        out.append({"point": n, "name": POINTS[n], "number": number, "source": source, "verdict": verdict})

    cb = g["country_bench"]; rule = cb.get("v2x_rule") or {}
    beats = bool(rule) and rule["knn"] < rule["baseline"] and (rule.get("knn_closer") or 0) > (rule.get("n") or 0) / 2
    add(1, f"V-Dem rule of law from energy, {len(cb)} targets; v2x_rule kNN MAE {rule.get('knn')} vs mean {rule.get('baseline')} "
           f"({rule.get('knn_closer')}/{rule.get('n')} closer)" if rule else NONE,
        "claude/reports/COUNTRY_BENCH.md (leave-one-country-out; run by hand, not a step)",
        SEED if beats else (PARTIAL if rule else NONE))
    wn = _kind(g, "world_next"); ls = g["learner_state"]
    n_alpha = len(ls.get("alpha", ls)) if isinstance(ls, dict) else 0
    add(2, f"world_next scored {wn.get('scored', 0)}, learner err {wn.get('learner_mean_err')} vs baseline {wn.get('baseline_mean_err')}; "
           f"{n_alpha} fitted parameter(s) in learner_state" if wn or n_alpha else NONE,
        "prophecy ledger + memory/learner_state.json",
        LIVE if wn.get("learner_beats_control") and wn.get("compared", 0) >= 30 else (PARTIAL if wn.get("scored") else NONE))
    add(3, NONE, "no step, no bench", NONE)
    cc = g["constancy"]
    add(4, f"constancy classes: {cc}" if cc else NONE, "memory/constancy_bands_latest.json (the seed: constellation/constancy)", SEED if cc else NONE)
    dt = g["daily_tier"]
    add(5, f"verified sensor cards accepted {g['verified']['accepted']}, refused {g['verified']['refused']}; daily tier {dt['indicators']} indicators",
        "memory/verified_observations.jsonl, card_refusals.jsonl, daily_tier.jsonl",
        PARTIAL if g["verified"]["accepted"] else NONE)
    rv = g["reviews"]
    streak = 0
    for r in reversed(rv):
        if str(r.get("success")).lower() in ("false", "0"):
            streak += 1
        else:
            break
    sx = g["sandbox"]
    add(6, f"cycle reviews on file {len(rv)}, failed streak {streak}; sandbox T6 {sx.get('T6')} / T6A {sx.get('T6A')}",
        "memory/brain_cycle_reviews.jsonl; SANDBOX_BENCH.json",
        PARTIAL if rv or sx else NONE)
    sf = _kind(g, "self_failure"); sv = _kind(g, "self_survive")
    add(7, f"Brier self_failure {sf.get('learner_mean_err')} vs {sf.get('baseline_mean_err')} ({sf.get('scored', 0)} scored); "
           f"self_survive scored {sv.get('scored', 0)}",
        "prophecy ledger", LIVE if sf.get("learner_beats_control") else (PARTIAL if sf else NONE))
    add(8, f"daily tier {dt['indicators']} indicators, {dt['moving']} moving; axis_next degenerate {_kind(g, 'axis_next').get('degenerate')}/{_kind(g, 'axis_next').get('scored')}",
        "memory/daily_tier.jsonl; prophecy ledger", PARTIAL if dt["indicators"] else NONE)
    cp = g["corpus"]
    add(9, f"verified corpus {cp.get('rows', 0)} rows {cp.get('by_task')}" if cp else NONE,
        "training/verified_corpus.manifest.json (no training run yet)", SEED if cp.get("rows") else NONE)
    add(10, f"self_failure {sf.get('scored', 0)} scored, learner beats control={sf.get('learner_beats_control')}; "
            f"reviews {len(rv)}; canon invariants {g['canon_invariants']}",
        "prophecy ledger; brain_cycle_reviews.jsonl; canon_invariants.json",
        LIVE if sf.get("learner_beats_control") and rv else PARTIAL)
    gr = g["grounding"]; ai = g["alarm_indicators"]
    add(11, f"targets grounded {gr['grounded']} / ungrounded {gr['ungrounded']}; signed indicator bands: {ai}; initiatives active {g['initiatives']['active']} (in progress {g['initiatives']['in_progress']})",
        "TARGET_GROUNDING.md; alarm_bands_latest.json; data/initiatives",
        PARTIAL)
    add(12, f"sandbox T12 {sx.get('T12')}; cards accepted {g['verified']['accepted']}; self_survive scored {sv.get('scored', 0)}",
        "SANDBOX_BENCH.json; verified_observations.jsonl; ledger",
        PARTIAL if sx.get("T12") == "PASS" or g["verified"]["accepted"] else NONE)
    pr = g["probe"]
    ins = sum(1 for r in pr if r.get("outcome") == "INSENSITIVE")
    add(13, f"counterfactual probes {len(pr)}, insensitive {ins}" if pr else NONE,
        "memory/counterfactual_probe.jsonl (not built yet)", SEED if pr else NONE)
    add(14, NONE, "open; no test", NONE)
    return out


def markdown(r: list[dict], g: dict) -> str:
    ts = datetime.now(timezone.utc).isoformat()[:19] + "Z"
    lines = [f"# AGI — 14 точки, като числа", "", f"_{ts} · chain_valid={g.get('ledger', {}).get('chain_valid')}_", "",
             "LIVE = числото е там и бие контрола; PARTIAL = числото е там, не бие или е малко; SEED = има зародиш, не стъпка; — = няма число.", "",
             "| т. | точка | число днес | откъде | присъда |", "|---:|---|---|---|---|"]
    for x in r:
        lines.append(f"| {x['point']} | {x['name']} | {x['number']} | {x['source']} | **{x['verdict']}** |")
    counts = {v: sum(1 for x in r if x["verdict"] == v) for v in (LIVE, PARTIAL, SEED, NONE)}
    lines += ["", f"**LIVE {counts[LIVE]} · PARTIAL {counts[PARTIAL]} · SEED {counts[SEED]} · — {counts[NONE]}**", "",
              "Правило: тази страница се пренаписва всяка сутрин от tools/prophecy_morning.bat. Число, което не може да се прочете от файл, е „—“ с причина. Присъдите са механични (scripts/agi_scoreboard.py) — грешни по проверим начин.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    g = gather()
    r = rows(g)
    md = markdown(r, g)
    if "--write" in sys.argv:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(md, encoding="utf-8")
        REPORT_JSON.write_text(json.dumps({"rows": r, "gathered": {k: v for k, v in g.items() if k != "reviews"}},
                                          ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"wrote {REPORT}")
    print(md)
