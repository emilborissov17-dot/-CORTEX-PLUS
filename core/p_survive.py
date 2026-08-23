#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/p_survive.py — ONE SCALAR. A METRIC, NEVER CONTEXT.

23 Aug 2026.

p_survive_next_cycle is a single number in [0, 1]: given what the defended
variables are doing right now and how fast they are moving, what is the chance
the next cycle reaches its end without a defended variable crossing its gate?

It is computed from the defended variables and their times-to-threshold, and
recorded once per cycle, at boot, beside the gate's own decision.

═══════════════════════════════════════════════════════════════════════════
THE HARD CONSTRAINT: THIS VALUE NEVER ENTERS A MODEL PROMPT.
═══════════════════════════════════════════════════════════════════════════

Not in the ТЯЛО line, not in the ДУХ block, not in the five-row mirror, not in
an evidence blob, not in a debrief, not as a rounded number, not as a word.

It is a metric, not self-knowledge. Feeding a 3B model text about its own
mortality produces risk-averse hallucination masked as self-preservation: the
system starts refusing risky but necessary steps, and the refusal reads like
judgement rather than like the artefact of a prompt it is. The failure mode is
not that the model panics — it is that the panic is indistinguishable, in the
log, from a reasoned decision.

The number exists so a HUMAN can look at a trend line. That is the whole
audience. core/survival_gate.py already carries every mechanical consequence:
the gate does not consult this scalar and would behave identically if this
module were deleted. Nothing may read it back into a prompt builder, and
test/test_p_survive.py asserts that by assembling every prompt component in the
repo and searching for the string.

WHAT THE NUMBER MEANS, AND WHAT IT DOES NOT
-------------------------------------------
Per defended variable:

    at or below its gate threshold  ->  0.0   (a cycle would not start at all)
    falling toward it               ->  time-to-gate / horizon, clamped to 1
    rising, or flat                 ->  1.0   (it is not going there)
    rate not yet measurable         ->  unknown; excluded, and said so

The whole is the product of the known ones, because the variables gate
independently: either one alone stops the night.

`horizon` is how long the next cycle is expected to take, taken from the median
of recent finished cycles in the existence ledger, or DEFAULT_HORIZON_SECONDS
when there are not enough of them. A TTT of two hours is comfortable against a
one-hour cycle and fatal against a six-hour one, so the horizon has to be a
measurement and not a constant.

CONFIDENCE IS ABOUT THE SAMPLE, NOT THE FUTURE. At boot there is one sample per
variable, so the rate is not yet measurable and the honest answer is
`confidence: none` with the variables excluded. A p of 1.0 at confidence none
means "nothing measured says otherwise", not "safe".

    venv/Scripts/python.exe core/p_survive.py            # read-only
    venv/Scripts/python.exe core/p_survive.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

NAME = "p_survive_next_cycle"
HISTORY = BASE / "memory" / "p_survive_history.jsonl"

# Used only when the ledger cannot supply enough finished cycles to take a
# median from. Four hours is the order of magnitude of a full night here.
DEFAULT_HORIZON_SECONDS = 4 * 3600.0
MIN_CYCLES_FOR_HORIZON = 3

CONF_NONE, CONF_LOW, CONF_HIGH = "none", "low", "high"
_CONF_RANK = {CONF_NONE: 0, CONF_LOW: 1, CONF_HIGH: 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# The horizon — how long the next cycle is expected to last
# ---------------------------------------------------------------------------

def horizon_seconds(ledger_rows=None) -> tuple:
    """(seconds, source). The median duration of recent finished cycles."""
    try:
        if ledger_rows is None:
            from memory import existence_ledger as ledger
            ledger_rows = ledger.read_all()
    except Exception as exc:
        return DEFAULT_HORIZON_SECONDS, "default ({}: {})".format(
            type(exc).__name__, exc)

    durations = []
    for row in reversed(list(ledger_rows or [])):
        if str(row.get("event", "")).upper() != "CYCLE_FINISHED":
            continue
        for key in ("duration_seconds", "duration_sec", "elapsed_seconds"):
            v = row.get(key)
            if isinstance(v, (int, float)) and v > 0:
                durations.append(float(v))
                break
        if len(durations) >= 10:
            break

    if len(durations) < MIN_CYCLES_FOR_HORIZON:
        return DEFAULT_HORIZON_SECONDS, (
            "default — only {} finished cycle(s) in the ledger carry a "
            "duration".format(len(durations)))
    return statistics.median(durations), "median of {} finished cycles".format(
        len(durations))


# ---------------------------------------------------------------------------
# The scalar
# ---------------------------------------------------------------------------

def _ttt_to_gate(info: dict, gate_threshold: float):
    """Seconds until this variable reaches its GATE, not its next threshold.

    interoception() reports the distance to whichever threshold is nearest
    below the current value; for p_survive only the gate matters, because only
    the gate stops a cycle.
    """
    rate = info.get("rate_per_second")
    if rate is None:
        return None                       # not yet measurable
    if rate >= 0:
        return float("inf")               # rising or flat: not going there
    distance = float(info.get("value")) - float(gate_threshold)
    if distance <= 0:
        return 0.0
    return distance / abs(rate)


def per_variable(evaluation: dict, cfg: dict, horizon: float) -> dict:
    out = {}
    for name, info in (evaluation.get("variables") or {}).items():
        spec = (cfg.get("variables") or {}).get(name) or {}
        gate = (spec.get("levels") or {}).get("gate")
        if info.get("level") == "unknown" or gate is None:
            out[name] = {"p": None, "why": "sensor unreadable",
                         "confidence": CONF_NONE}
            continue
        if info.get("level") == "gate":
            out[name] = {"p": 0.0, "why": "already at or past its gate "
                                          "threshold",
                         "confidence": info.get("ttt_confidence", CONF_NONE),
                         "ttt_to_gate_seconds": 0.0}
            continue

        ttt = _ttt_to_gate(info, gate)
        conf = info.get("ttt_confidence", CONF_NONE)
        if ttt is None:
            out[name] = {"p": None, "confidence": CONF_NONE,
                         "why": "rate not yet measurable ({} sample(s))".format(
                             info.get("samples"))}
            continue
        if ttt == float("inf"):
            out[name] = {"p": 1.0, "confidence": conf,
                         "ttt_to_gate_seconds": "inf",
                         "why": "{} — not moving toward the gate".format(
                             info.get("direction"))}
            continue
        p = max(0.0, min(1.0, ttt / horizon)) if horizon > 0 else 0.0
        out[name] = {
            "p": round(p, 4),
            "confidence": conf,
            "ttt_to_gate_seconds": round(ttt, 1),
            "why": "falling; reaches its gate in {:.0f} min against a "
                   "{:.0f} min cycle".format(ttt / 60.0, horizon / 60.0),
        }
    return out


def compute(evaluation=None, cfg=None, horizon=None, ledger_rows=None) -> dict:
    """The scalar plus everything needed to explain it. Never raises."""
    try:
        from core import homeostasis as h
        cfg = cfg or h.load_config()
        if evaluation is None:
            evaluation = h.evaluate(state=h.load_state())
    except Exception as exc:
        return {"metric": NAME, "value": None, "confidence": CONF_NONE,
                "error": "{}: {}".format(type(exc).__name__, exc),
                "variables": {}, "ts": _now().isoformat()}

    if horizon is None:
        horizon, horizon_source = horizon_seconds(ledger_rows)
    else:
        horizon_source = "supplied"

    parts = per_variable(evaluation, cfg, horizon)
    known = [v["p"] for v in parts.values() if v.get("p") is not None]

    if not known:
        value, conf = None, CONF_NONE
    else:
        value = 1.0
        for p in known:
            value *= p
        value = round(value, 4)
        # The weakest link decides how much the number is worth.
        conf = min((v.get("confidence", CONF_NONE) for v in parts.values()
                    if v.get("p") is not None),
                   key=lambda c: _CONF_RANK.get(c, 0))

    return {
        "metric": NAME,
        "value": value,
        "confidence": conf,
        "horizon_seconds": round(horizon, 1),
        "horizon_source": horizon_source,
        "excluded": [n for n, v in parts.items() if v.get("p") is None],
        "variables": parts,
        "config_sha256": evaluation.get("config_sha256"),
        "ts": evaluation.get("ts") or _now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Recorded per cycle — durably, and nowhere a prompt builder looks
# ---------------------------------------------------------------------------

def record(cycle_id=None, evaluation=None, cfg=None, path=None) -> dict:
    """Append one line per cycle. Fail-open: a metric never stops a cycle."""
    rec = compute(evaluation=evaluation, cfg=cfg)
    rec["cycle_id"] = cycle_id
    try:
        from core.durable import append_json
        append_json(pathlib.Path(path or HISTORY), rec)
    except Exception as exc:
        rec["write_error"] = "{}: {}".format(type(exc).__name__, exc)
    return rec


def history(n: int = 20, path=None) -> list:
    try:
        lines = pathlib.Path(path or HISTORY).read_text(
            encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------

def _report() -> int:
    rec = compute()
    print("core/p_survive.py — READ ONLY.\n")
    print("  THIS VALUE NEVER ENTERS A MODEL PROMPT. It exists so a human can")
    print("  look at a trend line; the survival gate does not consult it.\n")
    if rec.get("error"):
        print("  could not compute: {}".format(rec["error"]))
        return 0
    print("  {} = {}   (confidence {})".format(
        NAME, rec["value"], rec["confidence"]))
    print("  horizon      {:.0f} min — {}".format(
        rec["horizon_seconds"] / 60.0, rec["horizon_source"]))
    if rec["excluded"]:
        print("  excluded     {}".format(", ".join(rec["excluded"])))
    print("")
    for name, v in sorted(rec["variables"].items()):
        print("  {:<16} p = {}".format(name, v.get("p")))
        print("  {:<16} {}".format("", v.get("why", "")))
    rows = history(5)
    if rows:
        print("\n  last {} recorded:".format(len(rows)))
        for r in rows:
            print("    {}  {}  (confidence {})".format(
                r.get("ts"), r.get("value"), r.get("confidence")))
    return 0


def _selftest() -> int:
    rows = []
    try:
        rec = compute()
        rows.append(("computes against this repo",
                     "INERT" if rec.get("error") else "LIVE",
                     rec.get("error") or "value={} confidence={}".format(
                         rec["value"], rec["confidence"])))
    except Exception as exc:
        rows.append(("computes against this repo", "INERT", str(exc)))

    try:
        from core.durable import append_json  # noqa: F401
        rows.append(("core.durable (the write is fsynced)", "LIVE", "imported"))
    except Exception as exc:
        rows.append(("core.durable (the write is fsynced)", "INERT", str(exc)))

    try:
        src = (BASE / "core" / "survival_gate.py").read_text(encoding="utf-8")
        wired = "p_survive" in src
        rows.append(("recorded per cycle by survival_gate.guard()",
                     "LIVE" if wired else "INERT",
                     "called at boot" if wired else "NOTHING CALLS record()"))
    except Exception as exc:
        rows.append(("recorded per cycle by survival_gate.guard()", "INERT",
                     str(exc)))

    # The constraint is an integration too, and it is the important one.
    leaks = prompt_leaks()
    rows.append(("the value is in NO prompt builder",
                 "LIVE" if not leaks else "INERT",
                 "clean" if not leaks else "LEAKED INTO: {}".format(leaks)))

    print("core/p_survive.py --selftest\n")
    bad = sum(1 for _, s, _ in rows if s != "LIVE")
    for what, status, detail in rows:
        print("  {:<8} {:<44} {}".format(status, what, detail))
    print("\n  {} integration(s) INERT".format(bad) if bad
          else "\n  every integration is LIVE")
    return 1 if bad else 0


# The scan is here, not only in the test, so that --selftest can answer the
# question on the machine it is actually running on.
PROMPT_MODULES = (
    "core/brain.py",
    "core/interoception.py",
    "core/phase_debrief.py",
    "core/death_bell.py",
    "core/hypothesis_search.py",
    "cockpit/expression.py",
    "cockpit/reflex.py",
    "cockpit/vector.py",
    "experiments/pulse/self_sense.py",
    "experiments/dreams/dream.py",
    "experiments/meadow/meadow.py",
)


def prompt_leaks() -> list:
    """Any prompt-building module that so much as mentions the metric."""
    hits = []
    for rel in PROMPT_MODULES:
        p = BASE / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "p_survive" in text:
            hits.append(rel)
    return hits


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--json" in sys.argv:
        print(json.dumps(compute(), ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0)
    raise SystemExit(_report())
