# -*- coding: utf-8 -*-
"""
memory/axis_observations.jsonl — the history that did not exist.

WHY (6 Sep 2026)
----------------
proposal_intake admitted `WATER_REVIEW +1.2 by 2026-09-10` because the number
parsed. Nothing could say whether +1.2 is a routine week or a physical
impossibility, because THERE WAS NO HISTORY OF THE INDICATOR: the file this
module writes did not exist, and 0 of 177 archived snapshots carried an
`axis_observations` block.

`memory/goal_score_history.json` looks like a substitute and is not. It stores a
normalised 0-100 SCORE, a different quantity: on 6 Sep INEQUALITY_POVERTY_REVIEW
read 10.4 as an indicator and 82.67 as a score. Grading a delta against the score
series would compare a prediction to a number the prediction was never about, so
it is not used here and must not be.

So the history starts tonight. One line per gradeable indicator per cycle,
append-only:

    {"utc", "indicator", "value", "unit", "source_step", "cycle_id"}

UNITS ARE NOT INVENTED. The unit comes from config/target_config.json; an
indicator with no declared unit is written as "UNDECLARED" and named in the
report, because a delta whose units nobody wrote down cannot be checked against
a range.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
PATH = BASE / "memory" / "axis_observations.jsonl"
TARGET_CONFIG = BASE / "config" / "target_config.json"
UNDECLARED = "UNDECLARED"


def _units(path: pathlib.Path | None = None) -> dict:
    """indicator -> declared unit, from target_config.json.

    The file nests axes under subgoals, so the whole tree is walked and any dict
    carrying a "unit" is taken at the key it sits under. Never guesses: an axis
    the file does not mention simply is not in the map.
    """
    p = path or TARGET_CONFIG
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}
    out: dict = {}

    def walk(node, key=None):
        if isinstance(node, dict):
            if "unit" in node and key:
                out[key] = str(node["unit"])
            for k, v in node.items():
                walk(v, k)
    walk(blob)
    return out


def unit_for(indicator: str, units: dict | None = None) -> str:
    u = (units if units is not None else _units()).get(indicator)
    return u if u else UNDECLARED


def observations(indicators: dict | None = None, source_step: str = "axis_history",
                 cycle_id: str | None = None, units: dict | None = None) -> list:
    """One record per gradeable indicator. Non-numeric values are DROPPED, not
    coerced: a history with a string in it cannot produce a range."""
    if indicators is None:
        from core.gate_contract import gradeable_indicators
        indicators = gradeable_indicators()
    umap = _units() if units is None else units
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for name in sorted(indicators):
        value = indicators[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        rows.append({
            "utc": now,
            "indicator": name,
            "value": float(value),
            "unit": unit_for(name, umap),
            "source_step": source_step,
            "cycle_id": cycle_id,
        })
    return rows


def record(indicators: dict | None = None, source_step: str = "axis_history",
           cycle_id: str | None = None, path: pathlib.Path | None = None) -> dict:
    """Append tonight's observations. Returns a summary for the cycle log.

    Append-only and never rewrites: a history that can be rewritten is not
    evidence about the past.
    """
    p = path or PATH
    rows = observations(indicators, source_step, cycle_id)
    if rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    undeclared = sorted({r["indicator"] for r in rows if r["unit"] == UNDECLARED})
    return {"written": len(rows), "undeclared_units": undeclared, "path": str(p)}


def load(indicator: str, path: pathlib.Path | None = None) -> list:
    """[(utc, value)] for one indicator, oldest first. Malformed lines are
    skipped and counted by the caller's own reading, never silently repaired."""
    p = path or PATH
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:                                        # noqa: BLE001
            continue
        if d.get("indicator") == indicator and isinstance(d.get("value"), (int, float)):
            out.append((str(d.get("utc") or ""), float(d["value"])))
    return out


def daily_range(indicator: str, days: int = 30, path: pathlib.Path | None = None) -> dict:
    """{"n", "min", "max", "range", "days"} over the last `days` CALENDAR DAYS.

    n counts DISTINCT DAYS, not rows. A cycle that runs twice in a night must not
    count as two days of evidence — that is the same row-vs-question error the
    rank metric's cluster bootstrap exists to prevent.
    """
    from datetime import date, timedelta
    rows = load(indicator, path)
    if not rows:
        return {"n": 0, "min": None, "max": None, "range": None, "days": days}
    cut = (date.today() - timedelta(days=days)).isoformat()
    by_day: dict = {}
    for utc, v in rows:
        day = utc[:10]
        if day >= cut:
            by_day.setdefault(day, []).append(v)
    if not by_day:
        return {"n": 0, "min": None, "max": None, "range": None, "days": days}
    vals = [v for vs in by_day.values() for v in vs]
    lo, hi = min(vals), max(vals)
    return {"n": len(by_day), "min": lo, "max": hi, "range": hi - lo, "days": days}
