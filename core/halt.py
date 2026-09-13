#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/halt.py — the third state: stopped on purpose, part way through.

WHY THIS EXISTS. Until today a cycle had two endings: it finished, or it was
killed. There was nothing in between, so one bad minute at step 48 threw away two
hours of work and left a record that said only "died". On 13 Sep 2026 that
happened three times, and the last of them spent the restart budget in fifteen
minutes.

A cycle that notices it is out of memory can do better than be killed. It can
stop, say where it stopped and why, and leave 47 steps of results behind instead
of nothing.

THE LINE IS NOT A NEW ONE. It comes from core/homeostasis, by way of
core/survival_gate.check(), which delegates to homeostasis.evaluate(). No second
threshold lives here and this module does not know what the number is. See
gate_refuses() for why the read-only path is used rather than assess(), and for
the one honest caveat: assess() is the stricter of homeostasis' two thresholds,
so this stops a cycle later than the boot gate would, never earlier.

WHY VoluntaryHalt DERIVES FROM BaseException. Every step in this repo runs inside
`_run`, which catches `Exception` so that one broken step cannot cost the night.
That is right, and it is exactly what would swallow a halt: the cycle would decide
to stop, the step would eat the decision, and the next step would carry on into
memory that is not there. BaseException is the one thing `except Exception` cannot
hold. That is not a trick; it is the same reason KeyboardInterrupt and SystemExit
are built that way.

THE FORBIDDEN FALLBACK is a halt that becomes a death. If the record says
CYCLE_DIED the supervisor charges a restart, the day is re-attempted immediately,
and the whole point — a night that ends early with work saved — is lost. A halt
writes CYCLE_HALTED_SELF and exits with HALT_EXIT_CODE, which is neither zero nor
the code of a crash.

    venv\\Scripts\\python.exe core\\halt.py --selftest
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# Distinct from 0 (finished), 2 (boot abort), 3 (another cycle running),
# 130 (Ctrl+C) and 128+signal (killed). A reader of exit codes must be able to
# tell "I stopped myself" from "something stopped me".
HALT_EXIT_CODE = 7
LEDGER_EVENT = "CYCLE_HALTED_SELF"


class VoluntaryHalt(BaseException):
    """Raised inside beat() when the gate says the machine cannot go on.

    Carries what the record needs, so the handler at the top does not have to
    re-measure a moment that has already passed.
    """

    def __init__(self, step, index=None, reason="", free_mb=None, used_pct=None):
        self.step = step
        self.index = index
        self.reason = reason or "the survival gate refused mid-cycle"
        self.free_mb = free_mb
        self.used_pct = used_pct
        super().__init__(f"halted at step {step!r}: {self.reason}")


def _seen():
    """What the moment looked like. For the RECORD; it decides nothing."""
    try:
        import psutil
        v = psutil.virtual_memory()
        return round(v.available / 1048576.0, 1), v.percent
    except Exception:
        return None, None


_LAST_ASK = 0.0
ASK_GAP_SEC = 15.0


def gate_refuses(min_gap_sec: float = None):
    """(refuses, reason) from homeostasis — by its READ-ONLY path.

    WHICH ENTRY POINT, AND WHY NOT THE OBVIOUS ONE. core/homeostasis.assess() is
    what the supervisor and the boot call, and it cannot be called here: it runs
    build_self_profile(), which spawns nvidia-smi and WRITES
    memory/self_profile.json. beat() runs 75 times a night, so that would be 75
    subprocesses and 150 writes to live state per cycle. The test suite caught it
    within a minute — twelve tests failed on the live-state guard, correctly.

    So this asks core/survival_gate.check(), which delegates straight to
    homeostasis.evaluate(): the same module, the same thresholds, no writes, no
    subprocess, and never raises. It is also the oracle aggressive_cleanup already
    uses, so a halt refuses on the same line that triggers the cleaning.

    Worth stating plainly rather than hiding: survival_gate's own header records
    that homeostasis.assess has a STRICTER threshold than evaluate. The two are
    not identical, and this is the looser of them. It will stop a cycle later than
    assess would — never earlier — which is the safe direction for a guard that
    can end a night.

    Throttled: at most one ask every ASK_GAP_SEC. Cheap is not free, and a step
    that beats twice in a second does not need two answers.

    FAIL-OPEN. An unreadable gate answers "carry on": a sensor that cannot be read
    must not be able to end a healthy cycle.
    """
    import time as _t
    global _LAST_ASK
    gap = ASK_GAP_SEC if min_gap_sec is None else float(min_gap_sec)
    now = _t.time()
    if now - _LAST_ASK < gap:
        return False, None
    _LAST_ASK = now
    try:
        from core.survival_gate import check as _check
        verdict = _check() or {}
    except Exception:
        return False, None
    if verdict.get("allowed", True):
        return False, None
    reasons = verdict.get("reasons") or []
    return True, ("; ".join(str(r) for r in reasons)[:300]
                  or "the survival gate refused")


def check(step, index=None) -> None:
    """Called from beat(). Raises VoluntaryHalt, or returns and the cycle walks on."""
    refuses, reason = gate_refuses()
    if not refuses:
        return
    free_mb, used_pct = _seen()
    raise VoluntaryHalt(step, index, reason, free_mb, used_pct)


def record(exc: "VoluntaryHalt", cycle_id=None, steps_done=None) -> dict:
    """Write the halt where both a human and the supervisor will find it.

    Three places, and each is read by someone different: the ledger is the
    hash-chained account the supervisor reads, the trace is what a human opens
    the next morning, and stdout is what is tailed while it happens.
    """
    rec = {"event": LEDGER_EVENT, "cycle_id": cycle_id, "step": exc.step,
           "step_index": exc.index, "reason": exc.reason,
           "free_mb": exc.free_mb, "used_pct": exc.used_pct,
           "steps_completed": steps_done}

    line = (f"[FAST_CYCLE] СПРЯХ САМ на стъпка {exc.step}"
            f"{' (' + str(exc.index) + ')' if exc.index is not None else ''}: "
            f"свободни {exc.free_mb} MB ({exc.used_pct}% заети) — {exc.reason}. "
            f"Това НЕ е смърт: каквото е записано на диска остава, и следващият "
            f"пуск продължава оттук.")
    print(line, flush=True)

    try:
        from memory import existence_ledger as ledger
        ledger.append(LEDGER_EVENT, cycle_id=cycle_id or "unknown",
                      step=exc.step, step_index=exc.index, reason=exc.reason,
                      free_mb=exc.free_mb, used_pct=exc.used_pct,
                      steps_completed=steps_done)
        rec["ledger"] = True
    except Exception as e:                                   # noqa: BLE001
        rec["ledger"] = f"{type(e).__name__}: {e}"

    try:
        from core import flight_recorder as fr
        if fr.is_on():
            fr.event("halt", {"step": exc.step, "index": exc.index,
                              "reason": exc.reason[:200], "free_mb": exc.free_mb,
                              "used_pct": exc.used_pct})
            fr.stop("HALTED_SELF")
        rec["trace"] = True
    except Exception as e:                                   # noqa: BLE001
        rec["trace"] = f"{type(e).__name__}: {e}"

    return rec


def _selftest() -> int:
    print("core/halt.py --selftest")
    ok = True

    print(f"  exit code            : {HALT_EXIT_CODE} "
          f"(0 finished, 2 boot abort, 3 busy, 130 Ctrl+C, 128+n killed)")
    ok &= HALT_EXIT_CODE not in (0, 1, 2, 3, 130)

    caught = False
    try:
        raise VoluntaryHalt("demo", "12.5", "RAM 99%", 88.0, 99.0)
    except Exception:                                        # noqa: BLE001
        print("  FAIL: 'except Exception' swallowed the halt")
        ok = False
    except VoluntaryHalt as e:
        caught = True
        print(f"  survives except Exception: yes -> {e.step} / {e.free_mb} MB")
    ok &= caught

    refuses, reason = gate_refuses()
    print(f"  the live gate right now : "
          f"{'REFUSES — ' + str(reason)[:60] if refuses else 'allows'}")

    free, pct = _seen()
    print(f"  reading for the record  : {free} MB free, {pct}% used")
    print("  VERDICT               :", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
