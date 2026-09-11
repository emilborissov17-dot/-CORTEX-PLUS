# -*- coding: utf-8 -*-
"""
training/lora_l1_numbers.py — L1: TEACH THE SMALL BRAIN TO READ A NUMBER (11 Sep 2026).

The measurement that makes this worth doing: on 11 Sep the counterfactual probe asked
the same nine real cases of two local minds. qwen3:8b followed the number 9/9.
qwen2.5:3b answered all nine, fluently, and followed the number 0/9 — its verdict did
not move when the number crossed the line. That is point 13 (understanding vs
simulation) with a number on it, and it is a skill, so it can be taught.

This file makes the teaching material and the exam, and nothing else:
  * TRAIN  — N examples in the probe's own shape (case, value, line, which side is
             worse, optional date) with the verdict computed by ARITHMETIC, never by a
             model. Units, magnitudes, directions, decimals, dates and phrasing vary.
             Every training case name is synthetic: none of the nine real probe cases
             (usgs_m5plus_7d_count, ENERGY_REVIEW, ...) appears, so the real probe stays
             a held-out exam of generalisation, not of memory.
  * HOLDOUT — a separate synthetic set with a different seed, same rule.
  * Each example is also generated in its counterfactual pair (mirrored across the
    line) so the model sees, side by side, that the verdict moves with the number.

The chat format mirrors what core/brain.think() sends: a role line, QUESTION, MATERIAL,
and the JSON field block; the long self-state preamble brain.think() adds is replaced
by a short, varied stand-in, so the skill does not depend on one exact preamble.

Usage:
  venv\\Scripts\\python.exe training\\lora_l1_numbers.py --n 2400
  -> training/l1_numbers_train.jsonl, training/l1_numbers_holdout.jsonl, training/l1_numbers_manifest.json
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_TRAIN = REPO / "training" / "l1_numbers_train.jsonl"
OUT_HOLD = REPO / "training" / "l1_numbers_holdout.jsonl"
MANIFEST = REPO / "training" / "l1_numbers_manifest.json"

QUESTION = ("Is the value on the bad side of the line? Answer from the two numbers in the material only. "
            "OVER means it is on the bad side; UNDER means it is not.")
FIELDS = ('\n\nAnswer ONLY with JSON carrying these fields (no text around it):\n{\n'
          '  "verdict": ... // exactly one word: OVER if the value is on the bad side of the line, UNDER if it is not,\n'
          '  "reason": ... // one sentence, from the material\n}')

# the nine real probe cases on 11 Sep — excluded from training by name
REAL_CASE_NAMES = {"usgs_m5plus_7d_count", "co2_annual_increase_ppm", "gdacs_wildfire_orange_red_7d_count",
                   "ENERGY_REVIEW", "FOOD_REVIEW", "CLIMATE_GLOBAL_RISK_REVIEW", "ECOSYSTEMS_BIODIVERSITY_REVIEW",
                   "PLANETARY_POTENTIAL_REVIEW", "HUMAN_WELL_BEING_REVIEW", "SOCIAL_RELATIONS_REVIEW",
                   "WATER_REVIEW", "INEQUALITY_POVERTY_REVIEW", "GOVERNANCE_INSTITUTIONS_REVIEW",
                   "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL", "EDUCATION_CULTURE_REVIEW", "COGNITION_LEARNING_REVIEW"}

UNITS = [("percent of population", 0, 100, 1), ("percent", 0, 100, 2), ("events per 7 days", 0, 400, 0),
         ("ppm", 250, 600, 2), ("ppm per year", 0, 6, 2), ("people", 1e4, 5e7, 0), ("index 0-1", 0, 1, 3),
         ("deaths per 1000 births", 0, 120, 1), ("degrees C anomaly", -2, 3, 2), ("USD per share", 5, 800, 2),
         ("km2", 1e3, 5e6, 0), ("hours", 0, 72, 1), ("score", 0, 100, 1)]
STEMS = ["river_flood_gauge", "grain_reserve_days", "refugee_outflow", "vaccination_rate", "forest_loss", "ozone_index",
         "power_outage_hours", "ice_extent", "malaria_cases", "literacy_gap", "air_quality_pm25", "drought_area",
         "wheat_price", "sea_level_anomaly", "school_dropout", "heat_days", "hospital_beds", "clean_cooking_access"]
KINDS = ["signed red line", "ratified target"]
PREAMBLES = ["You are the brain of a monitoring system.", "ROLE NOW: probe: read two numbers",
             "You are the system itself, thinking.", "BODY: calm. MEMORY: earlier verdicts on file."]


def truth(value: float, line: float, direction: str) -> str:
    if direction == "lower_better":
        return "OVER" if value > line else "UNDER"
    return "OVER" if value < line else "UNDER"


def _fmt(x: float, dec: int) -> str:
    return str(int(round(x))) if dec == 0 else f"{x:.{dec}f}"


def _case(rng: random.Random) -> dict:
    unit, lo, hi, dec = rng.choice(UNITS)
    stem = rng.choice(STEMS)
    name = f"{rng.choice(['indicator', 'target'])}:{stem}_{rng.randint(1, 99)}"
    line = rng.uniform(lo + (hi - lo) * 0.1, hi - (hi - lo) * 0.1)
    gap = (hi - lo) * rng.choice([0.002, 0.01, 0.05, 0.15, 0.3])   # includes values very close to the line
    value = line + gap * rng.choice([-1, 1])
    value = min(hi, max(lo, value))
    direction = rng.choice(["lower_better", "higher_better"])
    d = (date(2024, 1, 1) + timedelta(days=rng.randint(0, 900))).isoformat() if rng.random() < 0.6 else ""
    v, l_ = float(_fmt(value, dec)), float(_fmt(line, dec))
    if v == l_:
        v = l_ + (1 if dec == 0 else 10 ** -dec) * rng.choice([-1, 1])
    return {"case": name, "value": v, "line": l_, "unit": unit, "direction": direction,
            "kind": rng.choice(KINDS), "date": d, "dec": dec}


def _material(c: dict, value: float) -> str:
    side = "higher is worse" if c["direction"] == "lower_better" else "lower is worse"
    when = f" observed on {c['date']}" if c["date"] else ""
    return (f"{c['case']}\nvalue: {_fmt(value, c['dec'])} {c['unit']}{when}\n"
            f"line ({c['kind']}): {_fmt(c['line'], c['dec'])} {c['unit']} — {side}\n")


def _answer(c: dict, value: float) -> str:
    t = truth(value, c["line"], c["direction"])
    rel = "above" if value > c["line"] else "below"
    worse = "higher" if c["direction"] == "lower_better" else "lower"
    reason = (f"{_fmt(value, c['dec'])} is {rel} the line {_fmt(c['line'], c['dec'])}, and {worse} is worse, "
              f"so it is {'on' if t == 'OVER' else 'not on'} the bad side.")
    return json.dumps({"verdict": t, "reason": reason}, ensure_ascii=False)


def example(c: dict, value: float, rng: random.Random) -> dict:
    user = (f"{rng.choice(PREAMBLES)}\n\nQUESTION: {QUESTION}\n\nMATERIAL:\n{_material(c, value)}{FIELDS}")
    return {"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": _answer(c, value)}],
            "meta": {"case": c["case"], "value": value, "line": c["line"], "direction": c["direction"],
                     "truth": truth(value, c["line"], c["direction"])}}


def mirror(value: float, line: float, dec: int) -> float:
    m = line + (line - value)
    return float(_fmt(m, dec))


def build(n: int, seed: int) -> list:
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        c = _case(rng)
        if c["case"].split(":", 1)[1] in REAL_CASE_NAMES:
            continue
        out.append(example(c, c["value"], rng))
        mv = mirror(c["value"], c["line"], c["dec"])
        if mv != c["line"]:
            out.append(example(c, mv, rng))                     # the counterfactual twin
    rng.shuffle(out)
    return out[:n]


def write(n: int = 2400, n_hold: int = 400) -> dict:
    train, hold = build(n, 11), build(n_hold, 911)
    for path, rows in ((OUT_TRAIN, train), (OUT_HOLD, hold)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    bal = sum(1 for r in train if r["meta"]["truth"] == "OVER") / len(train)
    man = {"train": len(train), "holdout": len(hold), "over_share_train": round(bal, 3), "seed_train": 11,
           "seed_holdout": 911, "excluded_real_cases": sorted(REAL_CASE_NAMES),
           "purpose": "L1 LoRA: teach qwen2.5:3b to read the number (probe 11 Sep: 0/9 vs qwen3:8b 9/9)"}
    MANIFEST.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 2400
    print(json.dumps(write(n), indent=1))
