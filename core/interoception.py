#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/interoception.py — FIVE LINES THE BRAIN CARRIES INTO EVERY THOUGHT.

WHY
----
core/brain.py already gives every call a ТЯЛО line (cpu, ram, ollama) and a ДУХ
block (the law, the canon). Both describe the machine and the mission. Neither
says how the system has been DOING — whether its own doubts have been coming out
false, how many proposals are waiting on a human, whether the last cycle
finished or was killed and on which step, how much headroom is left, how many
restarts remain today.

Those five facts change what a sensible answer looks like. A brain asked "should
I flag this as a risk?" answers differently when its own false-alarm rate is 0.62
than when it is 0.05, and it cannot know which unless it is told, every time. A
mirror that is read once a week is a report; a mirror that is in the room is a
sense.

THE FORMAT IS POSITIONAL ROWS, AND THAT IS DELIBERATE
------------------------------------------------------
Five lines, fixed order, `LABEL: value` — never a sparkline, never a bar of
block characters, never an emoji gauge. Three reasons, in order of how much they
cost:

  1. A model reads "0.62" and a bar of eight blocks differently, and only one of
     them is the number. The other is a picture of the number that has to be
     decoded back, badly.
  2. This repo has already been bitten by unreadable model output — see the CJK
     rejection rule in core/phase_debrief.py, added after all four fields of a
     verdict came back in Chinese.
  3. Fixed positions mean a missing value is VISIBLE as a row that says
     "неизвестно", instead of a line that quietly is not there.

Every row says "неизвестно" plus the reason when its source cannot be read. Five
rows go in, always, or the block is not five rows and the position argument is
worthless.

COST
-----
Measured on this machine, 21 Aug 2026 — see `--selftest`, which prints the real
number every time it runs rather than quoting this paragraph. Built per call:
the point is freshness, and a cached self-state is the report again.

    venv\\Scripts\\python.exe core/interoception.py --selftest
    venv\\Scripts\\python.exe core/interoception.py --show
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

MIRROR = BASE / "memory" / "self_mirror_latest.json"
LEDGER = BASE / "memory" / "existence_ledger.jsonl"
SCHED_STATE = BASE / "memory" / "scheduler_state.json"
SCHED_CFG = BASE / "config" / "scheduler.json"

UNKNOWN = "unknown"

# The five, in this order, always.
ROWS = ("FALSE_ALARMS", "OPEN_PROPOSALS", "LAST_CYCLE",
        "FREE_MEMORY", "RESTARTS_TODAY")

# If building the block costs more than this, say so out loud rather than
# letting it be discovered as "the cycle got slower".
LATENCY_BUDGET_SEC = 2.0

TERMINAL = ("CYCLE_FINISHED", "CYCLE_KILLED", "CYCLE_DIED",
            "CYCLE_FAILED_BUDGET_EXHAUSTED")


def _json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The five readings
# ---------------------------------------------------------------------------

def _false_alarms(mirror) -> str:
    if not isinstance(mirror, dict):
        return f"{UNKNOWN} (memory/self_mirror_latest.json cannot be read)"
    cal = mirror.get("calibration")
    if not isinstance(cal, dict):
        return f"{UNKNOWN} (огледалото няма раздел calibration)"
    fa = cal.get("false_alarms")
    judged = sum(int(cal.get(k) or 0) for k in
                 ("false_alarms", "justified_doubts", "missed_failures"))
    if fa is None or judged == 0:
        return f"{UNKNOWN} (0 paired verdicts in the window — nothing to compute from)"
    return f"{round(int(fa) / judged, 3)} ({fa} of {judged} paired)"


def _open_proposals(mirror) -> str:
    if not isinstance(mirror, dict):
        return f"{UNKNOWN} (memory/self_mirror_latest.json не се чете)"
    p = mirror.get("proposals")
    if not isinstance(p, dict) or p.get("open") is None:
        return f"{UNKNOWN} (the mirror does not count proposals)"
    out = f"{p['open']}"
    if p.get("overdue") is not None:
        out += f" ({p['overdue']} overdue)"
    if p.get("oldest_days") is not None:
        out += f", oldest {p['oldest_days']} days"
    return out


def _last_cycle(ledger_path: pathlib.Path | None = None) -> str:
    """FINISHED, or KILLED and on WHICH STEP. The step is the whole point: a
    brain that knows the last cycle died in daily_analysis can weigh a plan that
    schedules more of it."""
    p = ledger_path or LEDGER
    try:
        lines = [ln for ln in p.read_text(encoding="utf-8",
                                          errors="ignore").splitlines() if ln.strip()]
    except Exception:
        return f"{UNKNOWN} (the existence ledger cannot be read)"
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except Exception:
            continue
        ev = e.get("event")
        if ev not in TERMINAL:
            continue
        if ev == "CYCLE_FINISHED":
            return "FINISHED"
        step = (e.get("reason") or {}).get("wedged_step") or e.get("last_step") \
            or e.get("wedged_step") or "an unknown step"
        return f"{ev.replace('CYCLE_', '')} at step {step}"
    return f"{UNKNOWN} (no terminal event in the ledger)"


def _headroom(body_row) -> str:
    if not isinstance(body_row, dict):
        return f"{UNKNOWN} (the sensorium has no row at all — the supervisor has not ticked)"
    parts = []
    if body_row.get("ram_available_mb") is not None:
        parts.append(f"RAM {body_row['ram_available_mb']} MB "
                     f"({body_row.get('ram_pct', '?')}% used)")
    if body_row.get("gpu_vram_total_mb"):
        free = body_row["gpu_vram_total_mb"] - body_row.get("gpu_vram_used_mb", 0)
        parts.append(f"VRAM {free} MB of {body_row['gpu_vram_total_mb']}")
    elif (body_row.get("unavailable") or {}).get("gpu"):
        parts.append("VRAM unknown (no nvidia-smi)")
    return ", ".join(parts) or f"{UNKNOWN} (the row has neither memory nor VRAM)"


_UNSET = object()   # "not passed" is a different thing from "passed, unreadable"


def _restart_budget(state=_UNSET, cfg=_UNSET) -> str:
    # Defaulting these to None conflated two cases: a caller that did not
    # supply the state, and a caller saying the state IS unreadable. The second
    # is exactly what a test needs to express, and with None it silently became
    # the first — so the test read the machine's real scheduler_state.json and
    # got the live 2/2 instead of the fallback it was asserting.
    st = _json(SCHED_STATE) if state is _UNSET else state
    cf = _json(SCHED_CFG) if cfg is _UNSET else cfg
    if not isinstance(cf, dict):
        return f"{UNKNOWN} (config/scheduler.json cannot be read)"
    budget = int(cf.get("max_restarts_per_day", 2))
    if not isinstance(st, dict):
        return f"0/{budget} (memory/scheduler_state.json cannot be read — 0 assumed)"
    today = datetime.now().astimezone().date().isoformat()
    used = int((st.get("restarts") or {}).get(today, 0))
    return f"{used}/{budget}, {max(budget - used, 0)} left"


# ---------------------------------------------------------------------------
# The block
# ---------------------------------------------------------------------------

def self_state(mirror=None, body_row=None) -> dict:
    """The five values, keyed by their fixed row labels. Never raises."""
    if mirror is None:
        mirror = _json(MIRROR)
    if body_row is None:
        try:
            from core.body_sensorium import latest
            body_row = latest()
        except Exception:
            body_row = None

    out = {}
    for label, fn in (
        ("FALSE_ALARMS", lambda: _false_alarms(mirror)),
        ("OPEN_PROPOSALS", lambda: _open_proposals(mirror)),
        ("LAST_CYCLE", _last_cycle),
        ("FREE_MEMORY", lambda: _headroom(body_row)),
        ("RESTARTS_TODAY", _restart_budget),
    ):
        try:
            out[label] = str(fn())
        except Exception as exc:                      # noqa: BLE001
            # A row that raises still gets a row. Five rows, or the positions
            # mean nothing.
            out[label] = f"{UNKNOWN} ({type(exc).__name__})"
    return out


def block(state: dict | None = None) -> str:
    """The five lines, in order, as they go into the prompt."""
    s = state if state is not None else self_state()
    return "\n".join(f"{label}: {s.get(label, UNKNOWN)}" for label in ROWS)


def timed_block() -> tuple:
    """(text, seconds). The cost is returned rather than assumed."""
    t0 = time.perf_counter()
    text = block()
    return text, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# THE DELIBERATE DAILY READ
# ---------------------------------------------------------------------------
#
# The five-line block above is ambient: it is present in every call whether or
# not anybody attends to it. That is what a sense is, and it is not the same as
# reading. Once per cycle, in G_LEARN, the brain is handed the WHOLE mirror —
# calibration, stances, debriefs, predictions, proposals, sources, levels — and
# asked what it sees. The numbers it quotes are recorded, and the G_LEARN
# debrief must then cite at least two of them.
#
# Why a quota at all: without one, "I read the mirror" is unfalsifiable. Two
# numbers is the smallest count that cannot be satisfied by restating a single
# headline, and citing them means the debrief is anchored in the mirror rather
# than in the phase's file sizes.

READ_OUT = BASE / "memory" / "mirror_read_latest.json"

MIRROR_QUOTA = 2

READ_PROMPT = """This is your WHOLE mirror for this cycle — how you have been
doing, not how you are built. Read it and say what you see.

THE MIRROR:
{mirror}

Answer with JSON and nothing else:
  saw      — what matters most in these numbers, with the EXACT numbers in the
             sentence
  worries  — what worries you in them, and why
  numbers  — the numbers you cited, as a list, written as they stand in the
             mirror

Do not invent a number that is not there."""


def mirror_numbers(mirror=None) -> set:
    """Every number that appears anywhere in the mirror, as written."""
    import re
    m = mirror if mirror is not None else _json(MIRROR)
    if not isinstance(m, dict):
        return set()
    blob = json.dumps(m, ensure_ascii=False, default=str)
    return {x.group(0).replace(",", ".")
            for x in re.finditer(r"-?\d+(?:[.,]\d+)?", blob)}


def read_the_mirror(thinker=None, mirror=None, out_path=None) -> dict:
    """G_LEARN's substep. Never raises; a failed read must not fail the phase.

    Writes memory/mirror_read_latest.json: what the brain said, which mirror
    numbers it actually quoted (verified against the mirror, not taken on
    trust), and how long it took.
    """
    started = time.perf_counter()
    m = mirror if mirror is not None else _json(MIRROR)
    rec: dict = {"ts": datetime.now(timezone.utc).isoformat(),
                 "quota": MIRROR_QUOTA}
    if not isinstance(m, dict):
        rec["error"] = "memory/self_mirror_latest.json could not be read"
        rec["cited"] = []
        _write_read(rec, out_path)
        return rec

    available = mirror_numbers(m)
    rec["mirror_numbers_available"] = len(available)
    rec["mirror_bytes"] = len(json.dumps(m, ensure_ascii=False))

    said = None
    try:
        if thinker is None:
            from core.brain import think as thinker      # noqa: N806
        said = thinker(
            role="читател на собственото си огледало",
            question=READ_PROMPT.format(
                mirror=json.dumps(m, ensure_ascii=False, indent=1)[:6000]),
            schema={"saw": "", "worries": "", "numbers": ""},
            kind="mirror_read",
        )
    except Exception as exc:                          # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"

    rec["said"] = said if isinstance(said, dict) else None

    # VERIFIED, NOT TAKEN ON TRUST. The model is asked which numbers it cited;
    # what counts is which of them are actually in the mirror AND actually in
    # the sentence. A list of numbers with no sentence behind them is not a
    # reading, and a number that is not in the mirror is an invention.
    cited = []
    if isinstance(said, dict):
        import re
        prose = " ".join(str(said.get(k) or "") for k in ("saw", "worries"))
        in_prose = {x.group(0).replace(",", ".")
                    for x in re.finditer(r"-?\d+(?:[.,]\d+)?", prose)}
        cited = sorted(in_prose & available)
    rec["cited"] = cited
    rec["cited_count"] = len(cited)
    rec["met_quota"] = len(cited) >= MIRROR_QUOTA
    rec["seconds"] = round(time.perf_counter() - started, 1)
    _write_read(rec, out_path)
    return rec


def _write_read(rec: dict, out_path=None) -> None:
    p = out_path or READ_OUT
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    except Exception:
        pass


def must_cite(base=None) -> set:
    """The numbers a G_LEARN debrief is required to draw two of.

    Read from the mirror itself, not from what the model claimed — so the
    requirement stands even if read_the_mirror never ran, and the debrief cannot
    satisfy it by agreeing with a bad reading.
    """
    p = (base / "memory" / "self_mirror_latest.json") if base else MIRROR
    return mirror_numbers(_json(p))


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/interoception.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {name}")

    for name, p in (("memory/self_mirror_latest.json", MIRROR),
                    ("memory/existence_ledger.jsonl", LEDGER),
                    ("memory/scheduler_state.json", SCHED_STATE),
                    ("config/scheduler.json", SCHED_CFG)):
        print(f"  {'LIVE  ' if p.exists() else 'INERT '}  {name}")

    text, secs = timed_block()
    lines = text.splitlines()
    check("the block is exactly five rows", len(lines) == 5)
    check("...in the fixed order",
          [ln.split(":")[0] for ln in lines] == list(ROWS))
    check("...and every row has a value",
          all(len(ln.split(": ", 1)) == 2 and ln.split(": ", 1)[1].strip()
              for ln in lines))

    # No pictures of numbers.
    bad = [c for c in text if c in "▁▂▃▄▅▆▇█░▒▓●○◆■□▲▼★☆"]
    check("no sparklines, bars or gauge glyphs", not bad)
    check("no emoji", all(ord(c) < 0x1F000 for c in text))

    empty = self_state(mirror=None, body_row=None)
    check("an absent source yields five rows anyway", len(empty) == 5)
    check("...each saying UNKNOWN with a reason, not an empty string",
          all(v.strip() and (UNKNOWN not in v or "(" in v) for v in empty.values()))

    print(f"\n  MEASURED COST: {secs * 1000:.1f} ms per call "
          f"(budget {LATENCY_BUDGET_SEC * 1000:.0f} ms)")
    over = secs > LATENCY_BUDGET_SEC
    check(f"the block is built inside the {LATENCY_BUDGET_SEC}s budget", not over)
    if over:
        print(f"  OVER BUDGET by {secs - LATENCY_BUDGET_SEC:.2f}s — say so, do not "
              f"let it be discovered as 'the cycle got slower'")

    print("\n" + text)
    print(f"\n  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--show" in sys.argv:
        t, s = timed_block()
        print(t)
        print(f"\n({s * 1000:.1f} ms)")
        sys.exit(0)
    sys.exit(_selftest())
