#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/level_reconciler.py — WHEN THE WORD AND THE NUMBER DISAGREE, THE NUMBER WINS.

WHAT IT FIXES
--------------
auto_levels writes a level word per axis from its own thresholds.
goal_score_calculator writes a 0..1 score per axis from the metric, its target
and its direction. Nothing compared them, so they drifted, and on 21 August:

    SOCIAL_RELATIONS_REVIEW    level MEDIUM    score 0.034   (3.4/100)
    HUMAN_WELL_BEING_REVIEW    level MEDIUM    score 0.9025
    CLIMATE_GLOBAL_RISK_REVIEW level LOW       score 0.8185

An axis at 3.4 out of 100 was being reported as MEDIUM. Everything downstream
that reads a level word — self_modifier deciding which axis deserves a patch,
the orchestrator, the reports — was reading a word that its own number
contradicts.

THE NUMBER WINS, AND ONLY WHERE THE MEANING IS PINNED
-------------------------------------------------------
The score is derived from a measured value against a declared target and
direction. The level word is a threshold someone chose. Where they disagree the
score is the better evidence — but ONLY on an axis whose score_meaning is
pinned to "goodness" (see scripts/migrate_pin_score_meaning.py).

The two _RISK_ axes are deliberately unpinned. On those, LOW might mean "low
risk" — the opposite polarity — so a disagreement there is not evidence of an
error, it is evidence that nobody has said what the word means. Those are
FLAGGED and never corrected. Correcting them would be guessing, and guessing on
two axes is exactly how the drift started.

    CORRECTED   pinned axis, word and number disagree -> the word is replaced
    AGREES      they already agree
    FLAGGED     unpinned axis, they disagree -> reported, untouched
    NO_SCORE    nothing to compare against

Every correction is appended to memory/level_corrections.jsonl with the old
word, the new word, the score that decided it and the rationale.

    venv\\Scripts\\python.exe core/level_reconciler.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "target_config.json"
LEVELS = BASE / "memory" / "auto_levels.json"
GOAL_SCORE = BASE / "snapshots" / "master" / "goal_score_latest.json"
CORRECTIONS = BASE / "memory" / "level_corrections.jsonl"

GOODNESS = "goodness"

CORRECTED, AGREES, FLAGGED, NO_SCORE = "CORRECTED", "AGREES", "FLAGGED", "NO_SCORE"

# The bands a goodness score falls into. Chosen to match how auto_levels already
# speaks, so a correction reads as the same vocabulary rather than a new one.
BANDS = ((0.66, "HIGH"), (0.33, "MEDIUM"), (0.0, "LOW"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def level_for(score: float) -> str:
    for floor, word in BANDS:
        if score >= floor:
            return word
    return "LOW"


# ── THE POLARITY RULING, 21 August 2026 (Emil) ────────────────────────────
# ONE rule for all 25 axes: the LEVEL WORD describes CLOSENESS TO GOAL.
# LOW = far from goal = bad, everywhere, without exception. Risk inverts ONCE,
# at measurement — the score is already risk-inverted — and never again in the
# label.
#
# So CLIMATE_GLOBAL_RISK at 81.85/100 is HIGH: close to goal. Which is correct
# and reads backwards to a person, because the axis is NAMED for risk. The
# machine keeps one rule; the human gets a translation.
#
# Renaming the axes so they stop inviting the wrong reading is Emil's and
# belongs to the August axis migration, not here.
RISK_TRANSLATION = {"HIGH": "нисък риск", "MEDIUM": "среден риск",
                    "LOW": "висок риск"}


def is_risk_axis(axis: str) -> bool:
    return "RISK" in axis.upper()


def human_level(axis: str, word: str | None) -> str:
    """The level word as a PERSON should read it.

    Everywhere user-facing. On an ordinary axis this is the word itself; on a
    _RISK_ axis it carries the translation, because "ниво HIGH" on an axis
    called GLOBAL_RISK reads as danger when it means the opposite.
    """
    if not word:
        return "—"
    word = word.upper()
    if is_risk_axis(axis) and word in RISK_TRANSLATION:
        return f"ниво {word} ({RISK_TRANSLATION[word]})"
    return f"ниво {word}"


def pinned_axes(config_path=None) -> dict[str, str]:
    """{axis: score_meaning} for axes whose meaning someone has written down."""
    try:
        cfg = json.loads((config_path or CONFIG).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for branch, axes in cfg.items():
        if branch.startswith("_") or not isinstance(axes, dict):
            continue
        for axis, spec in axes.items():
            if isinstance(spec, dict) and spec.get("score_meaning"):
                out[axis] = spec["score_meaning"]
    return out


def scores(goal_path=None) -> dict[str, float]:
    try:
        goal = json.loads((goal_path or GOAL_SCORE).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for detail in (goal.get("metric_details") or {}).values():
        axis, score = detail.get("axis"), detail.get("score")
        if axis and isinstance(score, (int, float)) and not isinstance(score, bool):
            out[axis] = float(score)
    return out


def reconcile(levels_path=None, goal_path=None, config_path=None) -> dict:
    """Compare every level word with its own axis's score. Never raises."""
    try:
        levels = json.loads((levels_path or LEVELS).read_text(encoding="utf-8"))
    except Exception:
        levels = {}
    by_score = scores(goal_path)
    pinned = pinned_axes(config_path)

    rows = []
    for axis, node in levels.items():
        if axis.startswith("_") or not isinstance(node, dict):
            continue
        word = str(node.get("level") or "").upper() or None
        score = by_score.get(axis)

        if score is None or not word:
            rows.append({"axis": axis, "verdict": NO_SCORE, "level": word,
                         "score": score,
                         "why": "no score to compare the word against"})
            continue

        implied = level_for(score)
        if implied == word:
            rows.append({"axis": axis, "verdict": AGREES, "level": word,
                         "score": score, "implied": implied})
            continue

        if axis not in pinned:
            rows.append({
                "axis": axis, "verdict": FLAGGED, "level": word, "score": score,
                "implied": implied,
                "why": (f"{axis} has no score_meaning pinned, so {word} may mean "
                        f"low RISK rather than low goodness. A disagreement here "
                        f"is not evidence of an error — it is evidence that "
                        f"nobody has said what the word means. Emil decides."),
            })
            continue

        rows.append({
            "axis": axis, "verdict": CORRECTED, "level": word, "score": score,
            "implied": implied, "corrected_to": implied,
            "human": human_level(axis, implied),
            "why": (f"score {round(score * 100, 2)}/100 puts this axis in "
                    f"{implied}; auto_levels said {word}. The score is derived "
                    f"from a measured value against a declared target and "
                    f"direction; the word is a threshold someone chose. "
                    f"score_meaning={pinned[axis]}."),
        })

    return {
        "ts": _now(),
        "axes": len(rows),
        "counts": {v: sum(1 for r in rows if r["verdict"] == v)
                   for v in (CORRECTED, AGREES, FLAGGED, NO_SCORE)},
        "rows": rows,
        "corrections": [r for r in rows if r["verdict"] == CORRECTED],
        "flagged": [r for r in rows if r["verdict"] == FLAGGED],
    }


def apply(result: dict, levels_path=None, corrections_path=None) -> int:
    """Write the corrected words back, and record why. Returns how many moved."""
    path = levels_path or LEVELS
    try:
        levels = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    moved = 0
    for row in result["corrections"]:
        node = levels.get(row["axis"])
        if isinstance(node, dict):
            node["level"] = row["corrected_to"]
            node["corrected_by"] = "level_reconciler"
            node["corrected_from"] = row["level"]
            node["corrected_at"] = result["ts"]
            moved += 1

    if moved:
        try:
            path.write_text(json.dumps(levels, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        except Exception:
            return 0

    cpath = corrections_path or CORRECTIONS
    try:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        with open(cpath, "a", encoding="utf-8") as fh:
            for row in result["corrections"] + result["flagged"]:
                fh.write(json.dumps({"ts": result["ts"], **row},
                                    ensure_ascii=False) + "\n")
    except Exception:
        pass
    return moved


def for_phase_report() -> list[dict]:
    """The FLAGGED rows — the unpinned axes nobody has ruled on."""
    try:
        return reconcile()["flagged"]
    except Exception:
        return []


def run() -> dict:
    result = reconcile()
    moved = apply(result)
    c = result["counts"]
    print(f"[LEVELS] {result['axes']} axes | corrected {c[CORRECTED]} "
          f"({moved} written) | agrees {c[AGREES]} | flagged {c[FLAGGED]} | "
          f"no score {c[NO_SCORE]}")
    for row in result["corrections"]:
        print(f"[LEVELS] CORRECTED {row['axis']}: {row['level']} -> "
              f"{row['corrected_to']} (score {round(row['score'] * 100, 2)}/100)"
              + (f"  [{row['human']}]" if is_risk_axis(row["axis"]) else ""))
    for row in result["flagged"]:
        print(f"[LEVELS] FLAGGED {row['axis']}: {row['level']} vs "
              f"{round(row['score'] * 100, 2)}/100 — unpinned, left alone")
    return result


def _selftest() -> int:
    print("core/level_reconciler.py --selftest")
    result = reconcile()
    pinned = pinned_axes()
    ok = True

    social = [r for r in result["rows"] if r["axis"] == "SOCIAL_RELATIONS_REVIEW"]
    climate = [r for r in result["rows"] if r["axis"] == "CLIMATE_GLOBAL_RISK_REVIEW"]

    checks = [
        (f"23 axes pinned, 2 left for Emil ({len(pinned)})", len(pinned) == 23),
        ("SOCIAL_RELATIONS is corrected",
         bool(social) and social[0]["verdict"] == CORRECTED
         and social[0]["corrected_to"] == "LOW"),
        ("CLIMATE_GLOBAL_RISK is flagged, not corrected",
         bool(climate) and climate[0]["verdict"] == FLAGGED),
        ("no unpinned axis was corrected",
         all(r["axis"] in pinned for r in result["corrections"])),
    ]
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed

    print(f"  counts: {result['counts']}")
    for r in result["corrections"][:4]:
        print(f"    CORRECTED {r['axis']}: {r['level']} -> {r['corrected_to']} "
              f"({round(r['score'] * 100, 2)}/100)")
    for r in result["flagged"]:
        print(f"    FLAGGED   {r['axis']}: {r['level']} vs "
              f"{round(r['score'] * 100, 2)}/100")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else (run() and 0))
