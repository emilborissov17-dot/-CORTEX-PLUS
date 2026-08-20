#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/metta_parallel.py — A SECOND COLUMN THAT CAN DISAGREE WITH THE FIRST.

WHAT THIS IS
-------------
Five rules, R1..R5, applied to the axis feeds. Not a second brain and not a
better brain: a column of derivations that follow from the numbers alone, run
beside the model's column so the two can be compared. Where they disagree, the
disagreement is the output — that is the whole value.

The rules are emitted as a REAL MeTTa program and evaluated by hyperon when the
sidecar venv is present. When it is not, an equivalent Python reference
implementation runs and says so. The engine that produced each verdict is
recorded in the output, because "the symbolic layer agrees" means one thing
from an SMT-adjacent engine and another from thirty lines of Python that
re-state the same conditionals.

    hyperon        venv312_metta present, MeTTa ran the program
    python-reference  no sidecar; the same rules, evaluated in this process

THE RULES
----------
  R1 UNGROUNDED       weight > 0 and the axis has no measurement
  R2 INCOMPLETE       a value exists but no score was computed from it
  R3 LEVEL_CONTRADICTS_SCORE
                      the level word and the numeric score point opposite ways
  R4 OFF_TARGET       the measured value is on the wrong side of its own target
  R5 CRITICAL_LOSS    heavy axis, more than half its scale lost

R3 IS THE ONE THAT MATTERS TONIGHT. Live data, 20 August 2026:

    auto_levels.json          CLIMATE_GLOBAL_RISK_REVIEW -> level LOW
    goal_score_latest.json    CLIMATE_GLOBAL_RISK_REVIEW -> score 0.8185

A level of LOW next to a score of 81.85/100 is not a nuance, it is two parts of
the same system saying opposite things about the same axis on the same night.
Nothing in the cycle noticed, because nothing was comparing them.

    venv\\Scripts\\python.exe core/metta_parallel.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
FEEDS = BASE / "openclaw_queue" / "axis_feeds_latest.json"
GOAL_SCORE = BASE / "snapshots" / "master" / "goal_score_latest.json"
AUTO_LEVELS = BASE / "memory" / "auto_levels.json"
OUT = BASE / "memory" / "metta_assessment_latest.json"

SIDECAR_PY = BASE / "venv312_metta" / "Scripts" / "python.exe"
SIDECAR_PY_POSIX = BASE / "venv312_metta" / "bin" / "python"

ENGINE_HYPERON = "hyperon"
ENGINE_PYTHON = "python-reference"

# A level word and a score disagree when they are more than this far apart on
# the same 0..1 scale. LOW is read as 0.17, MEDIUM 0.5, HIGH 0.83.
LEVEL_VALUE = {"LOW": 0.17, "MEDIUM": 0.5, "HIGH": 0.83}
LEVEL_GAP = 0.4

HEAVY_WEIGHT = 8.0
HALF_LOST = 0.5

RULES = ("R1_UNGROUNDED", "R2_INCOMPLETE", "R3_LEVEL_CONTRADICTS_SCORE",
         "R4_OFF_TARGET", "R5_CRITICAL_LOSS")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sidecar_python() -> pathlib.Path | None:
    for p in (SIDECAR_PY, SIDECAR_PY_POSIX):
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

def gather_facts(feeds_path=None, goal_path=None, levels_path=None) -> list[dict]:
    """One fact row per axis: what every column of the system says about it."""
    try:
        feeds = json.loads((feeds_path or FEEDS).read_text(encoding="utf-8"))["feeds"]
    except Exception:
        feeds = []
    try:
        goal = json.loads((goal_path or GOAL_SCORE).read_text(encoding="utf-8"))
    except Exception:
        goal = {}
    try:
        levels = json.loads((levels_path or AUTO_LEVELS).read_text(encoding="utf-8"))
    except Exception:
        levels = {}

    details = {}
    for detail in (goal.get("metric_details") or {}).values():
        if detail.get("axis"):
            details[detail["axis"]] = detail

    facts = []
    for feed in feeds:
        axis = feed.get("axis")
        if not axis:
            continue
        d = details.get(axis) or {}
        lvl = levels.get(axis) or {}
        facts.append({
            "axis": axis,
            "measured": feed.get("status") == "PRESENT",
            "value": feed.get("value"),
            "weight": feed.get("weight"),
            "score": d.get("score"),
            "target": d.get("target"),
            "direction": d.get("direction"),
            "unit": d.get("unit") or feed.get("unit"),
            "level": (lvl.get("level") or "").upper() or None,
        })
    return facts


# ---------------------------------------------------------------------------
# The MeTTa program — emitted for real, not described
# ---------------------------------------------------------------------------

def _atom(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(round(float(value), 6))
    return f'"{value}"'


def metta_program(facts: list[dict]) -> str:
    """A real MeTTa program. The engine does the joins and the comparisons.

    TYPED ATOMS, NOT ONE GENERIC FACT. The first version emitted a single
    (axis-fact ...) with `none` in any missing slot, and every rule had to guard
    against arithmetic on a symbol. hyperon ran it, matched nothing, and
    returned an empty result that looked exactly like "no rule fired" — which is
    the failure mode this whole module exists to expose, reproduced inside the
    module itself. Now an atom is emitted ONLY when its fields are real numbers,
    so a rule can compare without guarding, and an empty result means empty.

    abs is not a builtin in hyperon 0.2.10 (measured: it comes back
    unevaluated), so R3 compares both directions instead.
    """
    lines = [
        "; CORTEX++ symbolic column — generated by core/metta_parallel.py",
        "; Atoms are emitted only when their numeric fields exist.",
        "",
    ]
    for f in facts:
        a = _atom(f["axis"])
        w, s, v, t = (_num(f["weight"]), _num(f["score"]),
                      _num(f["value"]), _num(f["target"]))
        if not f["measured"] and w is not None:
            lines.append(f"(unmeasured {a} {_atom(w)})")
        if f["measured"] and v is not None and s is None:
            lines.append(f"(measured-no-score {a})")
        if f["level"] in LEVEL_VALUE:
            lines.append(f"(levelled {a} {_atom(LEVEL_VALUE[f['level']])})")
        if s is not None:
            lines.append(f"(scored {a} {_atom(s)})")
        if f["measured"] and v is not None and t is not None:
            if f["direction"] == "lower_better":
                lines.append(f"(lower-better {a} {_atom(v)} {_atom(t)})")
            elif f["direction"] == "higher_better":
                lines.append(f"(higher-better {a} {_atom(v)} {_atom(t)})")
        if w is not None and s is not None:
            lines.append(f"(weighted-score {a} {_atom(w)} {_atom(s)})")

    lines += [
        "",
        "; R1 — weight but no measurement",
        "!(match &self (unmeasured $a $w)",
        "    (if (> $w 0) (R1_UNGROUNDED $a) (empty)))",
        "",
        "; R2 — a value exists but nothing scored it",
        "!(match &self (measured-no-score $a) (R2_INCOMPLETE $a))",
        "",
        "; R3 — the level word and the score point opposite ways",
        "!(match &self (levelled $a $lv)",
        "    (match &self (scored $a $s)",
        f"       (if (or (> (- $lv $s) {LEVEL_GAP}) (> (- $s $lv) {LEVEL_GAP}))",
        "           (R3_LEVEL_CONTRADICTS_SCORE $a)",
        "           (empty))))",
        "",
        "; R4 — the measured value is on the wrong side of its own target",
        "!(match &self (lower-better $a $v $t)",
        "    (if (> $v $t) (R4_OFF_TARGET $a) (empty)))",
        "!(match &self (higher-better $a $v $t)",
        "    (if (< $v $t) (R4_OFF_TARGET $a) (empty)))",
        "",
        "; R5 — heavy axis, more than half its scale lost",
        "!(match &self (weighted-score $a $w $s)",
        f"    (if (and (>= $w {HEAVY_WEIGHT}) (>= (- 1 $s) {HALF_LOST}))",
        "        (R5_CRITICAL_LOSS $a)",
        "        (empty)))",
        "",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The Python reference — the same rules, so the two engines can be compared
# ---------------------------------------------------------------------------

def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def evaluate_python(facts: list[dict]) -> dict[str, list[str]]:
    fired: dict[str, list[str]] = {r: [] for r in RULES}
    for f in facts:
        axis = f["axis"]
        w, s, v, t = (_num(f["weight"]), _num(f["score"]),
                      _num(f["value"]), _num(f["target"]))

        if not f["measured"] and w is not None and w > 0:
            fired["R1_UNGROUNDED"].append(axis)
        if f["measured"] and v is not None and s is None:
            fired["R2_INCOMPLETE"].append(axis)
        if f["level"] in LEVEL_VALUE and s is not None:
            if abs(LEVEL_VALUE[f["level"]] - s) > LEVEL_GAP:
                fired["R3_LEVEL_CONTRADICTS_SCORE"].append(axis)
        if f["measured"] and v is not None and t is not None:
            if (f["direction"] == "lower_better" and v > t) or \
               (f["direction"] == "higher_better" and v < t):
                fired["R4_OFF_TARGET"].append(axis)
        if w is not None and s is not None and w >= HEAVY_WEIGHT and (1 - s) >= HALF_LOST:
            fired["R5_CRITICAL_LOSS"].append(axis)
    return {k: sorted(v) for k, v in fired.items()}


def evaluate_hyperon(program: str, timeout: int = 60) -> tuple[dict | None, str]:
    """Run the emitted program through the sidecar. Returns (fired, error)."""
    py = sidecar_python()
    if py is None:
        return None, f"sidecar venv not found at {SIDECAR_PY}"
    worker = (
        "import json,sys\n"
        "from hyperon import MeTTa\n"
        "prog = sys.stdin.read()\n"
        "m = MeTTa()\n"
        "try:\n"
        "    res = m.run(prog)\n"
        "except Exception as e:\n"
        "    print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}))\n"
        "    sys.exit(0)\n"
        "print(json.dumps({'ok': True, 'raw': [[str(a) for a in r] for r in res]}))\n"
    )
    try:
        proc = subprocess.run([str(py), "-c", worker], input=program,
                              capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8")
    except subprocess.TimeoutExpired:
        return None, f"sidecar timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return None, f"sidecar launch failed: {type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        return None, f"sidecar exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None, f"unreadable sidecar output: {proc.stdout.strip()[:200]}"
    if not payload.get("ok"):
        return None, payload.get("error", "sidecar reported failure")

    fired: dict[str, list[str]] = {r: [] for r in RULES}
    for group in payload.get("raw", []):
        for atom in group:
            for rule in RULES:
                if atom.startswith(f"({rule} "):
                    axis = atom[len(rule) + 2:].strip(") ").strip('"')
                    if axis and axis not in fired[rule]:
                        fired[rule].append(axis)
    return {k: sorted(v) for k, v in fired.items()}, ""


# ---------------------------------------------------------------------------
# The column, and the disagreements
# ---------------------------------------------------------------------------

def disagreements(facts: list[dict], fired: dict[str, list[str]]) -> list[dict]:
    """One entry per firing of a rule that says two columns contradict."""
    by_axis = {f["axis"]: f for f in facts}
    out = []
    for axis in fired.get("R3_LEVEL_CONTRADICTS_SCORE", []):
        f = by_axis.get(axis, {})
        score = _num(f.get("score"))
        out.append({
            "rule": "R3_LEVEL_CONTRADICTS_SCORE",
            "axis": axis,
            "level": f.get("level"),
            "score": score,
            "score_pct": round(score * 100, 2) if score is not None else None,
            "level_reads_as": LEVEL_VALUE.get(f.get("level")),
            "gap": (round(abs(LEVEL_VALUE[f["level"]] - score), 4)
                    if f.get("level") in LEVEL_VALUE and score is not None else None),
            "says": (f"auto_levels says {f.get('level')}, goal_score says "
                     f"{round(score * 100, 2) if score is not None else '?'}/100 — "
                     f"the same axis, the same night, opposite readings"),
        })
    for axis in fired.get("R4_OFF_TARGET", []):
        f = by_axis.get(axis, {})
        out.append({
            "rule": "R4_OFF_TARGET", "axis": axis,
            "value": f.get("value"), "target": f.get("target"),
            "direction": f.get("direction"), "unit": f.get("unit"),
            "says": (f"{f.get('value')} {f.get('unit') or ''} against a target of "
                     f"{f.get('target')} ({f.get('direction')})"),
        })
    return out


def assess(feeds_path=None, goal_path=None, levels_path=None,
           prefer_hyperon: bool = True) -> dict:
    facts = gather_facts(feeds_path, goal_path, levels_path)
    program = metta_program(facts)

    engine, engine_error, fired = ENGINE_PYTHON, "", None
    if prefer_hyperon:
        t0 = time.time()
        fired, engine_error = evaluate_hyperon(program)
        if fired is not None:
            engine = ENGINE_HYPERON
        latency = round(time.time() - t0, 3)
    else:
        engine_error, latency = "hyperon not attempted", 0.0

    reference = evaluate_python(facts)

    # ── AN EMPTY SECOND OPINION MUST NOT ERASE A FIRING FIRST ONE ──────────
    # The first version of this module trusted hyperon whenever it returned
    # without error. It returned an EMPTY result — the program was malformed —
    # and the module reported 0 firings on data where the reference found 31.
    # That is the exact defect this file exists to catch, reproduced inside the
    # file. So: the Python reference is the SPECIFICATION, hyperon is a second
    # opinion, and where they differ the difference is recorded and the
    # specification is used.
    hyperon_fired = fired
    engines_agree = None
    if hyperon_fired is not None:
        engines_agree = (hyperon_fired == reference)
        if not engines_agree:
            engine_error = (
                f"hyperon disagreed with the reference and was NOT used: "
                f"hyperon {sum(len(v) for v in hyperon_fired.values())} firings vs "
                f"reference {sum(len(v) for v in reference.values())}")
            engine = ENGINE_PYTHON
    fired = reference if engines_agree is not True else hyperon_fired

    return {
        "ts": _now(),
        "engine": engine,
        "engine_error": engine_error or None,
        "engine_latency_s": latency,
        "engines_agree": engines_agree,
        "hyperon_fired_counts": ({k: len(v) for k, v in hyperon_fired.items()}
                                 if hyperon_fired is not None else None),
        "_engine_matters": (
            "'the symbolic layer agrees' means one thing from a MeTTa engine and "
            "another from a Python re-statement of the same conditionals. The "
            "engine that produced this verdict is recorded so the claim can be "
            "read at its real strength."),
        "axes": len(facts),
        "rules": list(RULES),
        "fired": fired,
        "fired_counts": {k: len(v) for k, v in fired.items()},
        "python_reference": reference,
        "disagreements": disagreements(facts, fired),
        "program": program,
    }


def write(result: dict, out: pathlib.Path | None = None) -> str:
    path = out or OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return str(path)


def for_phase_report() -> list[dict]:
    """The disagreement list, for the D_SCORE phase report."""
    try:
        return json.loads(OUT.read_text(encoding="utf-8")).get("disagreements", [])
    except Exception:
        return []


def run() -> dict:
    result = assess()
    path = write(result)
    print(f"[METTA] engine={result['engine']} axes={result['axes']} "
          f"agree={result['engines_agree']}")
    for rule, axes in result["fired"].items():
        if axes:
            print(f"[METTA]   {rule}: {len(axes)} -> {', '.join(axes[:4])}"
                  f"{' ...' if len(axes) > 4 else ''}")
    for d in result["disagreements"]:
        print(f"[METTA] DISAGREEMENT {d['axis']}: {d['says']}")
    print(f"[METTA] -> {path}")
    return result


def _selftest() -> int:
    print("core/metta_parallel.py --selftest")
    print(f"  sidecar: {sidecar_python() or 'ABSENT — python-reference only'}")
    result = assess()
    ok = True

    checks = [
        ("facts gathered", result["axes"] > 0),
        ("engine recorded", result["engine"] in (ENGINE_HYPERON, ENGINE_PYTHON)),
        ("a real MeTTa program was emitted",
         "!(match &self" in result["program"]
         and "(scored " in result["program"]
         and "R3_LEVEL_CONTRADICTS_SCORE" in result["program"]),
        ("all five rules present", set(result["fired"]) == set(RULES)),
    ]
    climate = [d for d in result["disagreements"]
               if d["axis"] == "CLIMATE_GLOBAL_RISK_REVIEW"]
    checks.append(("R3 fires on CLIMATE_GLOBAL_RISK (live)", bool(climate)))

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed

    print(f"  engine={result['engine']} error={result['engine_error']}")
    for rule, axes in result["fired_counts"].items():
        print(f"    {rule:<28} {axes}")
    for d in result["disagreements"][:4]:
        print(f"    DISAGREE {d['axis']}: {d['says'][:90]}")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else (run() and 0))
