#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/survival_gate.py — A CYCLE THAT MUST NOT START DOES NOT START QUIETLY.

23 Aug 2026. The third mechanical effect of the homeostatic layer.

  notice  is recorded and nothing else happens.
  action  fires an actuator that tries to move the value back.
  gate    REFUSES TO START THE CYCLE.

Each level has a distinct effect. A level that only prints a warning is a level
that does not exist, and three of those in a row is a system that watches itself
starve with excellent instrumentation.

WHY A GATE IS NOT SELF-PRESERVATION.
A cycle started with 400 MB of RAM free does not run slowly; it dies at step 30
with a MemoryError, having spent four hours and every token it was given, and
leaves a torn half-cycle behind. A cycle started with 3% disk free cannot write
its own journal, cannot write the ledger line that says it died, and cannot
write the heartbeat that would let the supervisor attribute the death. The gate
is not the system protecting itself from harm. It is the system declining to
produce a night of unusable work and an unreadable record of why.

WHAT IT MUST NEVER DO IS SKIP A NIGHT QUIETLY.
A refusal that only writes to stdout is indistinguishable, the next morning,
from a scheduler that did not fire. So a refusal is three things at once:

  1. a hash-chained line in memory/existence_ledger.jsonl naming the variable,
     its value, the threshold it crossed, and the time-to-threshold with its
     confidence label — the permanent record;
  2. the siren, supervisor.alarm_human() at ALARM level, because this is the
     category it was built for: the machine has stopped and needs a human;
  3. a non-zero exit, so the supervisor sees a failure rather than a success.

The ledger event is CYCLE_REFUSED_SURVIVAL_GATE and it counts as an END record
in core.unclean_stop, because a deliberate refusal is the cleanest stop there
is. Without that, tomorrow's boot would report tonight's refusal as a crash.

FAIL-OPEN, ON PURPOSE. If this module raises — a missing config, an
unreadable sensor, an import that is not there — the cycle STARTS. A broken
gate that stops every night is a worse failure than the one it was built to
prevent, and it would be indistinguishable from the machine being dead. The
only path that stops a cycle is a threshold that was actually read and actually
crossed.

    venv/Scripts/python.exe core/survival_gate.py --report     # read-only
    venv/Scripts/python.exe core/survival_gate.py --selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

NAME = "survival_gate"
EVENT = "CYCLE_REFUSED_SURVIVAL_GATE"

# The disk actuator is allowed to fire from here at the ACTION level, because
# by then the alternative is the GATE.
ACTUATORS = ("disk_free_pct",)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# The decision — pure. Reads sensors, writes nothing, exits nothing.
# ---------------------------------------------------------------------------

def check(state=None, sensors=None, now=None) -> dict:
    """{allowed, level, reasons, variables, state}. Never raises.

    `allowed` is False ONLY when a threshold was read and crossed. Every other
    outcome — unreadable config, unreadable sensor, an exception in here — is
    allowed=True with the reason recorded.
    """
    now = now or _now()
    try:
        from core import homeostasis as h
        st = state if state is not None else h.load_state()
        result = h.evaluate(state=st, now=now, sensors=sensors)
    except Exception as exc:
        return {
            "allowed": True,
            "level": "unknown",
            "reasons": ["the gate could not evaluate ({}: {}) — FAIL-OPEN, the "
                        "cycle starts".format(type(exc).__name__, exc)],
            "variables": {},
            "state": state if state is not None else {},
            "gate_error": "{}: {}".format(type(exc).__name__, exc),
        }

    return {
        "allowed": not result["gate"],
        "level": "gate" if result["gate"] else "clear",
        "reasons": list(result.get("gate_reasons") or []),
        "variables": result.get("variables", {}),
        "config_sha256": result.get("config_sha256"),
        "state": result.get("state", {}),
        "ts": result.get("ts"),
    }


def _offending(variables: dict) -> list:
    """The variables at gate level, with exactly the four facts the ledger
    line has to carry: variable, value, threshold, TTT."""
    out = []
    for name, info in (variables or {}).items():
        if info.get("level") != "gate":
            continue
        out.append({
            "variable": name,
            "value": info.get("value"),
            "unit": info.get("unit", ""),
            "threshold": info.get("next_threshold"),
            "distance": info.get("distance"),
            "direction": info.get("direction"),
            "rate_per_hour": info.get("rate_per_hour"),
            "ttt_seconds": info.get("ttt_seconds"),
            "ttt_confidence": info.get("ttt_confidence"),
            "escalated": bool(info.get("escalated")),
            "why": info.get("why", ""),
        })
    return out


def _human_line(v: dict) -> str:
    ttt = v.get("ttt_seconds")
    if ttt in (None, "inf"):
        when = "no time-to-threshold (it is not moving toward one)"
    else:
        when = "time-to-threshold {:.0f} min, confidence {}".format(
            float(ttt) / 60.0, v.get("ttt_confidence"))
    line = "{} = {}{} (gate threshold {}{}); {}".format(
        v["variable"], v["value"], v["unit"], v["threshold"], v["unit"], when)
    if v.get("escalated"):
        line += "\n    escalated: {}".format(v.get("why", ""))
    return line


# ---------------------------------------------------------------------------
# The refusal — ledger, siren, and a loud exit
# ---------------------------------------------------------------------------

def _to_ledger(cycle_id, decision: dict) -> Optional[dict]:
    try:
        from memory import existence_ledger as ledger
        return ledger.append(
            EVENT,
            cycle_id=cycle_id,
            pid=os.getpid(),
            gate=NAME,
            config_sha256=decision.get("config_sha256"),
            variables=_offending(decision.get("variables", {})),
            reasons=decision.get("reasons", []),
        )
    except Exception as exc:
        print("[{}] LEDGER WRITE FAILED: {}: {}".format(
            NAME, type(exc).__name__, exc))
        return None


def _to_siren(cycle_id, decision: dict) -> bool:
    """The siren, not the morning report. This is the category it exists for."""
    try:
        import supervisor
        offenders = _offending(decision.get("variables", {}))
        detail = (
            "The cycle did not start.\n\n"
            + "\n".join("  " + _human_line(v) for v in offenders)
            + "\n\nA cycle started below this threshold does not run slowly; it "
              "dies part-way through having spent the night, and may be unable "
              "to write the record of why. Recorded in the existence ledger as "
              + EVENT + ".\n\n"
              "To see the full homeostatic state without starting a cycle:\n"
              "  venv/Scripts/python.exe core/survival_gate.py --report"
        )
        supervisor.alarm_human(
            "cycle refused: {}".format(
                ", ".join(v["variable"] for v in offenders) or "survival gate"),
            detail,
            dedup_key="survival_gate:{}".format(
                ",".join(sorted(v["variable"] for v in offenders))),
            trigger=NAME,
            level=supervisor.ALARM,
        )
        return True
    except Exception as exc:
        print("[{}] SIREN FAILED: {}: {}".format(NAME, type(exc).__name__, exc))
        return False


def _save_state(decision: dict) -> None:
    try:
        from core import homeostasis as h
        h.save_state(decision.get("state") or {})
    except Exception:
        pass


def _record_p_survive(cycle_id, decision: dict):
    """Record the metric, once per cycle, beside the decision.

    THE DECISION ABOVE DOES NOT CONSULT IT. `decision["allowed"]` is already
    final by the time this runs, and the gate would behave identically if
    core/p_survive.py were deleted. The scalar is for a human reading a trend
    line; it is not an input to anything, and above all it never reaches a
    model prompt. See the header of core/p_survive.py for why.
    """
    try:
        from core import p_survive
        rec = p_survive.record(cycle_id=cycle_id)
        if rec.get("value") is not None:
            print("[{}] {} = {} (confidence {}) — recorded, not consulted"
                  .format(NAME, p_survive.NAME, rec["value"],
                          rec["confidence"]))
        return {"value": rec.get("value"), "confidence": rec.get("confidence")}
    except Exception as exc:
        print("[{}] p_survive not recorded: {}: {}".format(
            NAME, type(exc).__name__, exc))
        return None


def guard(cycle_id=None, state=None, sensors=None, now=None,
          on_refuse=None) -> dict:
    """The one call fast_cycle_runner makes at boot.

    Returns the decision. When it refuses it has ALREADY written the ledger
    line and fired the siren; `on_refuse` (default sys.exit) then stops the
    process. Passing on_refuse=lambda *_: None makes the whole thing observable
    from a test without ending the interpreter.
    """
    decision = check(state=state, sensors=sensors, now=now)
    _save_state(decision)
    decision["p_survive"] = _record_p_survive(cycle_id, decision)

    if decision["allowed"]:
        if decision.get("gate_error"):
            print("[{}] {}".format(NAME, decision["reasons"][0]))
        else:
            print("[{}] clear — {}".format(NAME, _one_line(decision)))
        return decision

    print("=" * 60)
    print("[{}] REFUSING TO START THIS CYCLE".format(NAME))
    for v in _offending(decision["variables"]):
        print("[{}]   {}".format(NAME, _human_line(v)))
    print("=" * 60)

    decision["ledger_event"] = _to_ledger(cycle_id, decision)
    decision["siren_sent"] = _to_siren(cycle_id, decision)
    if decision["ledger_event"]:
        print("[{}] recorded in the ledger as seq {} ({})".format(
            NAME, decision["ledger_event"].get("seq"), EVENT))
    print("[{}] siren {}".format(
        NAME, "sent" if decision["siren_sent"] else "FAILED — see above"))

    (on_refuse or sys.exit)(3)
    return decision


def _one_line(decision: dict) -> str:
    bits = []
    for name, info in sorted((decision.get("variables") or {}).items()):
        bits.append("{} {}{} [{}]".format(
            name, info.get("value"), info.get("unit", ""),
            info.get("level", "?")))
    return "; ".join(bits) or "nothing measured"


# ---------------------------------------------------------------------------
# Read-only report — the command a human runs instead of starting a cycle
# ---------------------------------------------------------------------------

def report(sensors=None) -> int:
    d = check(sensors=sensors)
    print("core/survival_gate.py — READ ONLY. No cycle is started, nothing is "
          "written.\n")
    if d.get("gate_error"):
        print("  the gate could not evaluate: {}".format(d["gate_error"]))
        print("  a cycle would START anyway (fail-open).")
        return 0
    print("  config sha256 {}  (verified)".format(
        str(d.get("config_sha256"))[:16]))
    print("  measured at   {}\n".format(d.get("ts")))
    for name, info in sorted(d["variables"].items()):
        print("  {}".format(name))
        if info.get("level") == "unknown":
            print("      sensor unreadable — {}".format(info.get("why", "")))
            continue
        print("      value            {} {}".format(info.get("value"),
                                                    info.get("unit", "")))
        print("      level            {}{}".format(
            info.get("level"),
            "  (ESCALATED from {})".format(info.get("held"))
            if info.get("escalated") else ""))
        print("      next threshold   {} {}  (distance {})".format(
            info.get("next_threshold"), info.get("unit", ""),
            info.get("distance")))
        print("      direction        {}  ({} per hour, {} samples)".format(
            info.get("direction"), info.get("rate_per_hour"),
            info.get("samples")))
        print("      time to that     {}  (confidence {})".format(
            info.get("ttt_seconds"), info.get("ttt_confidence")))
        if info.get("release_point") is not None:
            print("      releases at      {} {}".format(
                info.get("release_point"), info.get("unit", "")))
        if info.get("insufficient"):
            print("      INSUFFICIENT     the actuator fired and did not move "
                  "this value")
        if info.get("why"):
            print("      why              {}".format(info["why"]))
        print("")
    if d["allowed"]:
        print("  VERDICT: a cycle may start.")
    else:
        print("  VERDICT: a cycle would be REFUSED.")
        for r in d["reasons"]:
            print("           {}".format(r))
    return 0


def _selftest() -> int:
    """Which integrations are LIVE and which are INERT in the repo it finds
    itself in. A module that degrades silently lets a claim stay true in the
    docstring and false on disk."""
    rows = []

    try:
        from core import homeostasis as h
        cfg = h.load_config()
        rows.append(("core.homeostasis config", "LIVE",
                     "{} variables, sha256 {}".format(
                         len(cfg["variables"]), str(cfg.get("sha256"))[:12])))
    except Exception as exc:
        rows.append(("core.homeostasis config", "INERT",
                     "{}: {}".format(type(exc).__name__, exc)))

    try:
        from memory import existence_ledger as ledger
        rows.append(("memory.existence_ledger", "LIVE",
                     "head seq {}".format((ledger.head() or {}).get("seq"))))
    except Exception as exc:
        rows.append(("memory.existence_ledger", "INERT", str(exc)))

    try:
        import supervisor
        ok = callable(getattr(supervisor, "alarm_human", None))
        rows.append(("supervisor.alarm_human (the siren)",
                     "LIVE" if ok else "INERT",
                     "level={}".format(getattr(supervisor, "ALARM", "?"))))
    except Exception as exc:
        rows.append(("supervisor.alarm_human (the siren)", "INERT", str(exc)))

    try:
        from core import unclean_stop as us
        ok = EVENT in us.END_EVENTS
        rows.append(("unclean_stop counts a refusal as an end",
                     "LIVE" if ok else "INERT",
                     "END_EVENTS={}".format(len(us.END_EVENTS))))
    except Exception as exc:
        rows.append(("unclean_stop counts a refusal as an end", "INERT",
                     str(exc)))

    try:
        src = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8")
        wired = "survival_gate" in src
        rows.append(("wired into fast_cycle_runner.main()",
                     "LIVE" if wired else "INERT",
                     "the gate is called at boot" if wired
                     else "NOTHING CALLS THIS MODULE"))
    except Exception as exc:
        rows.append(("wired into fast_cycle_runner.main()", "INERT", str(exc)))

    print("core/survival_gate.py --selftest\n")
    bad = 0
    for what, status, detail in rows:
        if status != "LIVE":
            bad += 1
        print("  {:<8} {:<42} {}".format(status, what, detail))
    print("\n  {} integration(s) INERT".format(bad) if bad
          else "\n  every integration is LIVE")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--json" in sys.argv:
        d = check()
        d.pop("state", None)
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0)
    raise SystemExit(report())
