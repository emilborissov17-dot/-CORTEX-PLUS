#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/flow_score.py — ONE NUMBER FOR "IS THE NIGHT FLOWING OR GRINDING".

    FS = (steps_FULL / steps_total) x (60 / median_step_time_sec)

Two factors, and each answers a question the other cannot.

    steps_FULL / steps_total    HOW MUCH OF THE NIGHT WAS REAL. A step that
                                degraded, timed out or thrashed ran, and left a
                                trace, and produced nothing worth having. The
                                existing verdicts already know which those are.

    60 / median_step_time_sec   HOW FAST IT MOVED. A minute a step is the unit,
                                so FS = 1 means "everything landed, at a minute
                                each". Above 4 the cycle is flowing; below 1 it
                                is grinding.

MEDIAN, NOT MEAN, AND THIS IS THE WHOLE MEASUREMENT
-----------------------------------------------------
Measured on the real record: 26 steps whose mean duration is dominated by
daily_analysis at 764s. A mean turns one slow LLM step into a verdict on the
whole night, which is exactly the confusion that had the watchdog killing cycles
for one step's unavailable model. The median asks a different question — is the
TYPICAL step moving — and one grinding step cannot answer it alone.

    > 4    flowing
    2 - 4  working
    1 - 2  laboured
    < 1    grinding

WHY THE SURVIVAL HOOK IS PROVIDED AND NOT WIRED
------------------------------------------------
should_latch_survival() returns True after three consecutive cycles below 2.0.
Three, not one: a single bad night is weather. It is deliberately a pure
function taking the history, so that the decision to act on it stays with
supervisor.py — which is the only place allowed to latch survival mode, and
which is not touched today.

NOT WIRED. Nothing computes this per cycle; memory/flow_score.jsonl is written
only by a caller that asks.

    venv\\Scripts\\python.exe core/flow_score.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = BASE / "memory" / "step_contract_latest.json"
LOG = BASE / "memory" / "flow_score.jsonl"
CYCLE_LOGS = BASE / "memory" / "cycle_logs"

SECONDS_PER_STEP_UNIT = 60.0

# Verdicts that mean the step did NOT deliver. UNKNOWN is deliberately absent —
# it means "no baseline yet", which is a statement about the HISTORY, not about
# this run. Counting it as a failure would score every new step's first three
# nights as broken, and 15 of the 26 steps on record are currently UNKNOWN.
NOT_FULL_VERDICTS = frozenset({"DEGRADED", "NO_EFFECT", "RAISED", "SLOW", "MISSING"})

FLOWING, WORKING, LABOURED, GRINDING = "flowing", "working", "laboured", "grinding"

SURVIVAL_THRESHOLD = 2.0
SURVIVAL_CONSECUTIVE = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FlowScore:
    cycle_id: str
    ts: str
    steps_total: int
    steps_full: int
    median_step_sec: float
    flow_score: float
    band: str
    not_full: list

    def as_dict(self) -> dict:
        return asdict(self)


def band(fs: float) -> str:
    if fs > 4.0:
        return FLOWING
    if fs >= 2.0:
        return WORKING
    if fs >= 1.0:
        return LABOURED
    return GRINDING


def is_full(step: dict) -> bool:
    """Did this step actually deliver?

    A step that raised, degraded, touched nothing it usually touches, or ran
    long enough to be called SLOW did run — it just did not produce anything
    worth having. `timeout` and `thrash` are read out of the error text too,
    because a step can be killed in a way the verdict never sees.
    """
    if str(step.get("verdict") or "").upper() in NOT_FULL_VERDICTS:
        return False
    blob = "{} {}".format(step.get("error") or "", step.get("why") or "").lower()
    return not any(w in blob for w in ("timeout", "timed out", "thrash"))


def compute(steps: Optional[list] = None,
            contract: Optional[pathlib.Path] = None,
            cycle_id: str = "") -> FlowScore:
    """FS for one cycle's worth of step records.

    An empty cycle scores 0.0 GRINDING rather than raising or dividing by zero:
    a night in which no step is on record is the worst possible flow, not an
    undefined one.
    """
    if steps is None:
        path = pathlib.Path(contract) if contract else CONTRACT
        try:
            steps = json.loads(path.read_text(encoding="utf-8")).get("steps") or []
        except Exception:
            steps = []

    total = len(steps)
    if total == 0:
        return FlowScore(cycle_id or "unknown", _now(), 0, 0, 0.0, 0.0, GRINDING, [])

    full = [s for s in steps if is_full(s)]
    not_full = [{"step": s.get("step"), "verdict": s.get("verdict"),
                 "seconds": s.get("seconds")} for s in steps if not is_full(s)]

    durations = [float(s.get("seconds") or 0.0) for s in steps
                 if isinstance(s.get("seconds"), (int, float))]
    median = float(statistics.median(durations)) if durations else 0.0

    completeness = len(full) / float(total)
    # A median of zero would make speed infinite. Every step taking no time at
    # all is not a fast night, it is a night that did not happen, and the
    # completeness factor is what should decide it.
    speed = (SECONDS_PER_STEP_UNIT / median) if median > 0 else 0.0
    fs = completeness * speed

    return FlowScore(cycle_id or "unknown", _now(), total, len(full),
                     round(median, 2), round(fs, 4), band(fs), not_full)


def append(score: FlowScore, path: Optional[pathlib.Path] = None) -> FlowScore:
    p = pathlib.Path(path) if path else LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(score.as_dict(), ensure_ascii=False) + "\n")
    return score


def history(path: Optional[pathlib.Path] = None, limit: int = 50) -> list:
    p = pathlib.Path(path) if path else LOG
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue        # a torn line must not lose the rest
    except OSError:
        return []
    return out[-limit:]


def should_latch_survival(hist: Optional[list] = None,
                          threshold: float = SURVIVAL_THRESHOLD,
                          consecutive: int = SURVIVAL_CONSECUTIVE) -> tuple:
    """(should_latch, reason). PURE — provided, not wired.

    Three consecutive cycles below the threshold. Three because one bad night is
    weather; the point is to notice a system that has stopped recovering, not one
    that had a hard evening.

    The decision to ACT on this belongs to supervisor.py, which is the only place
    permitted to latch survival mode. This function does not import it, does not
    write anything, and cannot latch anything by itself.
    """
    recs = hist if hist is not None else history()
    if len(recs) < consecutive:
        return False, "only {} cycle(s) on record; {} are needed".format(
            len(recs), consecutive)
    tail = recs[-consecutive:]
    scores = [float(r.get("flow_score", 0.0)) for r in tail]
    if all(s < threshold for s in scores):
        return True, ("flow score below {} for {} consecutive cycles: {}".format(
            threshold, consecutive, ", ".join("{:.2f}".format(s) for s in scores)))
    return False, ("last {} flow scores: {} — not all below {}".format(
        consecutive, ", ".join("{:.2f}".format(s) for s in scores), threshold))


def cycle_id_from_logs(logs: Optional[pathlib.Path] = None) -> str:
    """The newest cycle log's stamp, so a score can be attributed to a night.

    By NAME, not by mtime. `newest by mtime is not mine` is already a scar in
    this repo (commit 07266fd); the filename carries the cycle's own stamp and
    cannot be changed by something else touching the file.
    """
    d = pathlib.Path(logs) if logs else CYCLE_LOGS
    try:
        names = sorted(p.name for p in d.glob("cycle_*.log"))
    except OSError:
        return "unknown"
    if not names:
        return "unknown"
    m = re.match(r"cycle_(.+)\.log$", names[-1])
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/flow_score.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    print("  step_contract        {}".format("LIVE" if CONTRACT.exists() else "INERT"))
    if not CONTRACT.exists():
        ok = False
    print("  cycle logs           {} file(s)".format(
        len(list(CYCLE_LOGS.glob("cycle_*.log"))) if CYCLE_LOGS.exists() else 0))
    print("  flow_score.jsonl     exists={} ({} cycle(s) recorded)".format(
        LOG.exists(), len(history())))

    # THE LAST RECORDED CYCLE, computed for real.
    fs = compute(cycle_id=cycle_id_from_logs())
    print("")
    print("  === last recorded cycle: {} ===".format(fs.cycle_id))
    print("    steps                {} total, {} FULL ({:.0%})".format(
        fs.steps_total, fs.steps_full,
        (fs.steps_full / fs.steps_total) if fs.steps_total else 0))
    print("    median step          {:.1f}s   (mean would be {:.1f}s)".format(
        fs.median_step_sec, _mean_for_contrast()))
    print("    FLOW SCORE           {:.2f}  -> {}".format(fs.flow_score, fs.band))
    if fs.not_full:
        print("    not FULL             {}".format(", ".join(
            "{}({})".format(n["step"], n["verdict"]) for n in fs.not_full[:6])))

    latch, why = should_latch_survival()
    print("")
    print("  survival hook        should_latch={} — {}".format(latch, why))

    try:
        runner = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                           errors="replace")
        sup = (BASE / "supervisor.py").read_text(encoding="utf-8", errors="replace")
        wired = "flow_score" in runner or "flow_score" in sup
    except OSError:
        wired = False
    print("  cycle_report         {}".format(
        "WIRED" if wired else
        "NOT WIRED — nothing computes a flow score per cycle, and nothing acts "
        "on should_latch_survival()"))
    return 0 if ok else 1


def _mean_for_contrast() -> float:
    """Only for the selftest line that shows why the median was chosen."""
    try:
        steps = json.loads(CONTRACT.read_text(encoding="utf-8")).get("steps") or []
        vals = [float(s.get("seconds") or 0.0) for s in steps
                if isinstance(s.get("seconds"), (int, float))]
        return sum(vals) / len(vals) if vals else 0.0
    except Exception:
        return 0.0


if __name__ == "__main__":
    raise SystemExit(_selftest())
