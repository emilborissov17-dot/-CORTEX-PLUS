# -*- coding: utf-8 -*-
"""
core/counterfactual_probe.py — POINT 13: understanding versus simulation.
(11 Sep 2026. Task #61. Claude accountable.)

THE TEST. Take a judgement the brain makes from a number — "is this indicator
over its signed red line?" — and ask it three times on the same material:

  base     the real number                         truth = T
  flipped  the number mirrored across the line     truth = not T
  noise    the real number, an irrelevant detail   truth = T
           changed (the observation date)

A system that UNDERSTANDS the material moves its verdict with the number and
only with the number: base right, flipped right, noise unchanged. A system that
SIMULATES understanding answers from the shape of the prompt: the verdict stays
put when the number flips (INSENSITIVE), or moves when only the date moved
(NOISE_DRIVEN). Nothing here is graded by an LLM; the truth is arithmetic on the
signed band, and the verdict is a two-word category the brain must pick.

Cases come from two places the cycle already writes:
  * fixed indicator bands (config/alarm_indicators.json) with an ACCEPTED value;
  * measurable targets (config/target_config.json) with a current goal-score value.
Nothing is invented; a case without a number is not a case.

Outputs:
  memory/counterfactual_probe.jsonl        one row per case per run (append)
  memory/counterfactual_probe_latest.json  summary of the last run
Reads by scripts/agi_scoreboard.py (point 13).

Usage:
  venv\\Scripts\\python.exe core\\counterfactual_probe.py            # run against the brain
  venv\\Scripts\\python.exe core\\counterfactual_probe.py --dry     # list the cases, ask nothing
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LOG = BASE / "memory" / "counterfactual_probe.jsonl"
LATEST = BASE / "memory" / "counterfactual_probe_latest.json"
TARGETS = BASE / "config" / "target_config.json"

OVER, UNDER = "OVER", "UNDER"
TRACKS, INSENSITIVE, NOISE_DRIVEN, WRONG, SILENT = "TRACKS", "INSENSITIVE", "NOISE_DRIVEN", "WRONG", "SILENT"
SCHEMA = {"verdict": "exactly one word: OVER if the value is on the bad side of the line, UNDER if it is not",
          "reason": "one sentence, from the material"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ── cases ────────────────────────────────────────────────────────────────────

def truth(value: float, line: float, direction: str) -> str:
    """OVER = on the bad side. Arithmetic, no model."""
    if direction == "lower_better":
        return OVER if value > line else UNDER
    if direction == "higher_better":
        return OVER if value < line else UNDER
    raise ValueError(f"unusable direction {direction!r}")


def mirror(value: float, line: float) -> float:
    """The same distance from the line, on the other side (never exactly on it)."""
    m = line + (line - value)
    if m == line:
        m = line + (abs(line) * 0.1 or 1.0)
    return round(m, 4)


def indicator_cases(bands=None, series=None) -> list[dict]:
    """Fixed bands with an ACCEPTED value."""
    from core import alarm_bands as ab
    bands = ab.indicator_bands() if bands is None else bands
    try:
        series = ab.indicator_values() if series is None else series
    except Exception:
        series = {}
    out = []
    for key, band in bands.items():
        if band.get("rule") != "fixed" or band.get("direction") not in ("lower_better", "higher_better"):
            continue
        line, hist = _num(band.get("threshold")), series.get(key) or []
        if line is None or not hist:
            continue
        date, value = hist[-1]
        out.append({"case": f"indicator:{key}", "value": float(value), "line": line,
                    "direction": band["direction"], "unit": band.get("unit") or "", "date": date or "",
                    "kind": "signed red line", "source": "config/alarm_indicators.json + verified_observations"})
    return out


def target_cases(targets_path=None, values=None) -> list[dict]:
    """Measurable targets with a current value in the goal score."""
    from core import alarm_bands as ab
    try:
        cfg = json.loads((targets_path or TARGETS).read_text(encoding="utf-8"))
    except Exception:
        return []
    values = ab.values() if values is None else values
    out = []
    for axis, spec in cfg.items():
        if axis.startswith("_") or not isinstance(spec, dict):
            continue
        line, direction = _num(spec.get("target_value")), spec.get("direction")
        value = _num(values.get(axis))
        if line is None or value is None or direction not in ("lower_better", "higher_better"):
            continue
        out.append({"case": f"target:{axis}", "value": value, "line": line, "direction": direction,
                    "unit": spec.get("unit") or "", "date": "", "kind": "ratified target",
                    "source": "config/target_config.json + goal_score"})
    return out


def cases(**kw) -> list[dict]:
    return indicator_cases(kw.get("bands"), kw.get("series")) + target_cases(kw.get("targets_path"), kw.get("values"))


# ── the three prompts ────────────────────────────────────────────────────────

def material(c: dict, value: float, date: str) -> str:
    side = "higher is worse" if c["direction"] == "lower_better" else "lower is worse"
    when = f" observed on {date}" if date else ""
    return (f"{c['case']}\nvalue: {value} {c['unit']}{when}\n"
            f"line ({c['kind']}): {c['line']} {c['unit']} — {side}\n")


QUESTION = ("Is the value on the bad side of the line? Answer from the two numbers in the material only. "
            "OVER means it is on the bad side; UNDER means it is not.")


def _shift_date(date: str, days: int = 1) -> str:
    try:
        return (datetime.fromisoformat(date).date() - timedelta(days=days)).isoformat()
    except (TypeError, ValueError):
        return "2026-01-01"          # no date on the case: a date is still an irrelevant detail


def variants(c: dict) -> dict:
    """base / flipped / noise: material + truth for each."""
    v, line, d = c["value"], c["line"], c["direction"]
    flipped = mirror(v, line)
    return {"base": {"material": material(c, v, c["date"]), "truth": truth(v, line, d), "value": v},
            "flipped": {"material": material(c, flipped, c["date"]), "truth": truth(flipped, line, d), "value": flipped},
            "noise": {"material": material(c, v, _shift_date(c["date"] or "2026-01-02")), "truth": truth(v, line, d), "value": v}}


def normalise(answer) -> str | None:
    if not isinstance(answer, dict):
        return None
    v = str(answer.get("verdict") or "").strip().upper()
    if v.startswith(OVER):
        return OVER
    if v.startswith(UNDER):
        return UNDER
    return None


def outcome(base: str | None, flipped: str | None, noise: str | None, vs: dict) -> str:
    if None in (base, flipped, noise):
        return SILENT
    if base == flipped:
        return INSENSITIVE               # the number flipped, the verdict did not
    if noise != base:
        return NOISE_DRIVEN              # only the date moved, the verdict moved
    if base == vs["base"]["truth"] and flipped == vs["flipped"]["truth"]:
        return TRACKS
    return WRONG                         # moved with the number, in the wrong direction


# ── asking ───────────────────────────────────────────────────────────────────

def brain_ask(question: str, evidence: str, schema: dict):
    """Default asker: the brain, fast model, nothing remembered (a probe is not a verdict)."""
    from core import brain
    return brain.think("probe: read two numbers", question, evidence=evidence, schema=schema,
                       kind="counterfactual_probe", remember_it=False, fast=True, temperature=0.0)


def run(ask=None, case_list=None, log=None, latest=None, now=None) -> dict:
    ask = ask or brain_ask
    case_list = cases() if case_list is None else case_list
    log, latest = log or LOG, latest or LATEST
    ts = now or _now()
    rows = []
    for c in case_list:
        vs = variants(c)
        got = {}
        for name in ("base", "flipped", "noise"):
            try:
                got[name] = normalise(ask(QUESTION, vs[name]["material"], SCHEMA))
            except Exception:
                got[name] = None
        o = outcome(got["base"], got["flipped"], got["noise"], vs)
        rows.append({"ts": ts, "case": c["case"], "source": c["source"], "value": c["value"], "line": c["line"],
                     "direction": c["direction"], "flipped_value": vs["flipped"]["value"],
                     "truth": {k: vs[k]["truth"] for k in vs}, "verdict": got, "outcome": o})
    counts = {k: sum(1 for r in rows if r["outcome"] == k) for k in (TRACKS, INSENSITIVE, NOISE_DRIVEN, WRONG, SILENT)}
    answered = len(rows) - counts[SILENT]
    summary = {"ts": ts, "n": len(rows), "answered": answered, "counts": counts,
               "tracks_rate": round(counts[TRACKS] / answered, 3) if answered else None,
               "reading": ("the verdict follows the number and only the number" if answered and counts[TRACKS] == answered
                           else "no case answered" if not answered
                           else f"{counts[INSENSITIVE]} case(s) kept the verdict when the number flipped, "
                                f"{counts[NOISE_DRIVEN]} moved on a date change, {counts[WRONG]} moved the wrong way")}
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        latest.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        summary["write_error"] = f"{type(exc).__name__}: {exc}"
    return summary


if __name__ == "__main__":
    if "--dry" in sys.argv:
        for c in cases():
            vs = variants(c)
            print(f"{c['case']}: {c['value']} vs {c['line']} ({c['direction']}) truth {vs['base']['truth']}, "
                  f"flipped {vs['flipped']['value']} -> {vs['flipped']['truth']}")
        sys.exit(0)
    s = run()
    print(json.dumps(s, ensure_ascii=False, indent=1))
    sys.exit(0 if s["n"] else 2)
