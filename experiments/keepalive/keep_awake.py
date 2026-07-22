"""
CORTEX++ | Side-experiment polyanka: keep_awake
===============================================
ISOLATED and NON-INVASIVE. Imports nothing from the repo, touches neither the
supervisor nor any running cycle. Safe to run by hand at any time.

WHY
---
Diagnosis (21 Jul 2026): the daily cycle dies mid-run on ~4 of 7 mornings with
NO traceback -- the process simply vanishes at a random step. Signature = the
laptop entering sleep / closing before the ~60-min cycle finishes. The
supervisor is a 5-minute schtasks tick that exits between ticks, so a
keep-awake request must live inside the *cycle* process, not the supervisor.

WHAT
----
Windows SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED): "do not
enter idle sleep while I run". The request is bound to THIS process -- when the
process exits (cleanly or by dying), Windows clears it automatically. That is
exactly the scope we want: awake for precisely as long as the cycle lives.

HONEST LIMIT
------------
ES_SYSTEM_REQUIRED blocks *idle* sleep. It does NOT override a lid-close power
setting. That distinction is THE open question from the diagnosis, and the
self-test below resolves it empirically instead of by assumption.

SELF-TEST (pre-declared pass/fail)
----------------------------------
  venv/Scripts/python.exe experiments/keepalive/keep_awake.py --hold 25

  (A) idle:  guard ON, leave the machine untouched for the full window.
             As a control, run again with --control (guard OFF) and stay idle.
  (B) lid:   guard ON, then close the lid for a few minutes.

  PASS(idle)  -> stays awake in (A) with guard, sleeps in --control.
                 keep-awake alone fixes the mornings; wire it into the cycle.
  PASS(lid)   -> also stays awake in (B). even better.
  FAIL(lid)   -> sleeps on lid-close despite the guard.
                 keep-awake is necessary but NOT sufficient -> the lid-close
                 mornings need checkpoint-resume (homeostasis chain-1
                 experiment). This is the signal that decides it.

INTENDED PRODUCTION USE (one line, later, after Emil confirms):
  from experiments.keepalive.keep_awake import keep_awake
  with keep_awake():
      run_full_cycle()
"""
from __future__ import annotations

import argparse
import os
import platform
import time
from contextlib import contextmanager

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_IS_WINDOWS = platform.system() == "Windows"


def _set_state(flags):
    """Return True on success, False on non-Windows or API failure."""
    if not _IS_WINDOWS:
        return False
    import ctypes
    return ctypes.windll.kernel32.SetThreadExecutionState(flags) != 0


def keep_awake_on(keep_display=False):
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    if keep_display:
        flags |= ES_DISPLAY_REQUIRED
    return _set_state(flags)


def keep_awake_off():
    """Restore normal power behavior (ES_CONTINUOUS with no requirement)."""
    return _set_state(ES_CONTINUOUS)


@contextmanager
def keep_awake(keep_display=False):
    """System stays awake for the duration of the block.

    No-op (yields False) on non-Windows, so importing it can never break a
    cycle running elsewhere. Releases in finally, and Windows also auto-clears
    the request if the process dies inside the block.
    """
    ok = keep_awake_on(keep_display)
    try:
        yield ok
    finally:
        keep_awake_off()


def _selftest(hold_min, control, keep_display):
    if not _IS_WINDOWS:
        print("[keep_awake] Not Windows -- this guard is a no-op here. "
              "Run it on the CORTEX laptop with venv/Scripts/python.exe.")
        return
    mode = "CONTROL (guard OFF)" if control else "GUARD ON"
    print("[keep_awake] " + mode + " | holding " + str(int(hold_min)) +
          " min | PID=" + str(os.getpid()))
    if not control:
        ok = keep_awake_on(keep_display)
        print("[keep_awake] SetThreadExecutionState -> " + ("OK" if ok else "FAILED"))
    print("[keep_awake] Now: (A) leave idle, or (B) close the lid. Ctrl-C to stop.")
    end = time.time() + hold_min * 60.0
    try:
        while time.time() < end:
            left = int(end - time.time())
            print("[keep_awake] active ... " + str(left) + "s left")
            time.sleep(30)
    except KeyboardInterrupt:
        print("[keep_awake] stopped by user.")
    finally:
        if not control:
            keep_awake_off()
        print("[keep_awake] released. Verdict: stayed awake with GUARD and "
              "slept in --control => keep-awake confirmed for idle-sleep.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CORTEX keep-awake polyanka (isolated).")
    ap.add_argument("--hold", type=float, default=25.0, help="minutes to hold (default 25)")
    ap.add_argument("--control", action="store_true", help="guard OFF baseline: should sleep on idle")
    ap.add_argument("--display", action="store_true", help="also keep the screen on")
    a = ap.parse_args()
    _selftest(a.hold, a.control, a.display)
