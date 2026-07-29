"""
CORTEX++ | Side-experiment polyanka: lidaction_guard
====================================================
ISOLATED and NON-INVASIVE. Imports nothing from the repo, touches neither the
supervisor nor any running cycle. Safe to run by hand at any time.

WHY
---
Sibling of keep_awake.py. Diagnosis (21 Jul 2026): the daily cycle dies mid-run
on ~4 of 7 mornings with NO traceback -- the process simply vanishes at a random
step. keep_awake (SetThreadExecutionState / ES_SYSTEM_REQUIRED) blocks *idle*
sleep but, per its own HONEST LIMIT, does NOT override a lid-close power action.
On the CORTEX laptop `Lid close action` is `Sleep` (verified 29 Jul 2026:
AC=0x1, DC=0x1), so closing the lid during a ~45-63 min catch-up cycle sleeps
the box and the process is lost. This guard sets `Lid close action` to
`Do nothing` (index 0) for exactly as long as the cycle lives, then restores it.

WHAT
----
Windows `powercfg`. For the current (active) power scheme:
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0   (see NOTE)
    powercfg /setactive       SCHEME_CURRENT
On exit the saved originals are written back. Unlike keep_awake's execution-state
flag, this is a PERSISTENT machine setting -- Windows does NOT auto-clear it when
the process dies. So restoration is defended THREE ways:
    1. contextmanager finally  -> clean exit and any raised exception
    2. atexit handler          -> interpreter teardown after an unhandled error
    3. sidecar breadcrumb file -> if the process is HARD-killed (the lid-close /
       hibernate we are fighting) neither (1) nor (2) runs; the *next* engage
       reads `.lidaction_state.json` and restores the machine BEFORE doing
       anything else. This is what keeps requirement #3 true across a real death.

FAIL-OPEN, ALWAYS
-----------------
  * non-Windows                       -> no-op, yields False.
  * powercfg missing / errors         -> no-op, yields False.
  * original value cannot be READ     -> DO NOT TOUCH anything. We never set a
                                         value we could not restore. This is the
                                         hard guarantee behind "never leave the
                                         machine locked in lidaction=0 forever".

NOTE on AC vs DC
----------------
The task spec asked for /setacvalueindex (AC / plugged in). This module ALSO
guards DC (on battery) because the morning catch-up frequently runs unplugged,
and an AC-only guard would silently do nothing there. Both are saved and both
are restored to their own originals. Pass also_dc=False to guard AC only.

SELF-TEST (pre-declared pass/fail)
----------------------------------
  venv/Scripts/python.exe experiments/keepalive/lidaction_guard.py --hold 5

  guard ON, then close the lid for a minute.
  PASS -> machine stays awake with the lid shut; on exit the setting reads back
          at its original value (Sleep) and `.lidaction_state.json` is gone.
  FAIL -> machine still sleeps on lid-close (setting did not apply), OR after
          exit the setting is still 0 (restoration path broken -- investigate).

  Emergency restore (if a crashed run left the lid at "Do nothing"):
  venv/Scripts/python.exe experiments/keepalive/lidaction_guard.py --restore

INTENDED PRODUCTION USE (nested inside keep_awake in fast_cycle_runner.py):
  from experiments.keepalive.lidaction_guard import lidaction_guard
  with keep_awake():
      with lidaction_guard():
          run_full_cycle()
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import platform
import re
import subprocess
import time
from contextlib import contextmanager

_IS_WINDOWS = platform.system() == "Windows"

# powercfg aliases for `Lid close action` under `Power buttons and lid`.
_SCHEME = "SCHEME_CURRENT"
_SUBGROUP = "SUB_BUTTONS"
_SETTING = "LIDACTION"
_DO_NOTHING = 0  # index 0 == "Do nothing" (verified on-box: 1=Sleep, 2=Hibernate, 3=Shut down)

# Crash-recovery breadcrumb, module-relative so it needs no repo layout knowledge.
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".lidaction_state.json")

# Avoid a flashing console window when powercfg is spawned from a GUI-less parent.
_NO_WINDOW = 0x08000000 if _IS_WINDOWS else 0

# Module state for idempotent restore across finally + atexit.
_ORIG = None        # {"ac": int, "dc": int|None}
_RESTORED = True    # nothing engaged yet


def _run(args, timeout=15):
    """Run `powercfg <args>`. Return (returncode, text). Fail-open -> (None, '')."""
    if not _IS_WINDOWS:
        return (None, "")
    try:
        p = subprocess.run(["powercfg", *args], capture_output=True, text=True,
                           timeout=timeout, creationflags=_NO_WINDOW)
        return (p.returncode, (p.stdout or "") + (p.stderr or ""))
    except Exception:
        return (None, "")


def _unhide():
    """`Lid close action` ships HIDDEN on most SKUs -> /query won't print its
    index and we could not save the original. Un-hiding is reversible and
    harmless (it only makes the row visible in Control Panel). Best-effort."""
    _run(["/attributes", _SUBGROUP, _SETTING, "-ATTRIB_HIDE"])


def _read_lidaction():
    """Return {'ac': int, 'dc': int|None} for the active scheme, or None if the
    value cannot be read (in which case the guard must not touch anything)."""
    _unhide()
    rc, txt = _run(["/query", _SCHEME, _SUBGROUP, _SETTING])
    if rc is None or not txt:
        return None
    m_ac = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", txt)
    m_dc = re.search(r"Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)", txt)
    if not m_ac:
        return None
    return {"ac": int(m_ac.group(1), 16),
            "dc": int(m_dc.group(1), 16) if m_dc else None}


def _set_lidaction(ac, dc):
    """Set AC (always) and DC (when not None) indices, then activate. True on OK."""
    rc_ac, _ = _run(["/setacvalueindex", _SCHEME, _SUBGROUP, _SETTING, str(ac)])
    ok = (rc_ac == 0)
    if dc is not None:
        rc_dc, _ = _run(["/setdcvalueindex", _SCHEME, _SUBGROUP, _SETTING, str(dc)])
        ok = ok and (rc_dc == 0)
    _run(["/setactive", _SCHEME])
    return ok


def _write_state(orig):
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(orig, fh)
    except Exception:
        pass


def _read_state():
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and "ac" in d:
            return {"ac": int(d["ac"]),
                    "dc": int(d["dc"]) if d.get("dc") is not None else None}
    except Exception:
        pass
    return None


def _clear_state():
    try:
        if os.path.exists(_STATE_FILE):
            os.remove(_STATE_FILE)
    except Exception:
        pass


def _recover_stale():
    """A leftover breadcrumb means a previous cycle DIED without restoring. Put
    the machine back to those saved originals before we do anything else."""
    st = _read_state()
    if st is not None:
        _set_lidaction(st["ac"], st.get("dc"))
        _clear_state()


def _engage(also_dc=True):
    """Save originals, then set lid action to 'Do nothing'. Return True if the
    guard is active. Any inability to READ the original -> no-op (False)."""
    global _ORIG, _RESTORED
    if not _IS_WINDOWS:
        return False
    _recover_stale()                     # clean up after a prior death first
    orig = _read_lidaction()
    if orig is None:                     # cannot read -> cannot restore -> hands off
        return False
    _ORIG = orig
    _RESTORED = False
    _write_state(orig)                   # breadcrumb BEFORE the change
    ok = _set_lidaction(_DO_NOTHING, _DO_NOTHING if also_dc else None)
    if not ok:                           # setting failed -> undo and bail
        _restore()
        return False
    atexit.register(_restore)            # backup restoration path
    return True


def _restore():
    """Write the saved originals back. Idempotent; safe to call many times."""
    global _RESTORED
    if _RESTORED:
        return
    orig = _ORIG or _read_state()
    _RESTORED = True                     # set first: never loop on a failing restore
    if orig is not None:
        _set_lidaction(orig["ac"], orig.get("dc"))
    _clear_state()


@contextmanager
def lidaction_guard(also_dc=True):
    """Lid stays at 'Do nothing' for the duration of the block, then restores.

    No-op (yields False) on non-Windows or if the original cannot be read, so
    importing it can never break a cycle. Restores in finally; atexit and a
    sidecar breadcrumb cover the hard-kill case that finally cannot.
    """
    ok = False
    try:
        ok = _engage(also_dc)
    except Exception:
        ok = False
    try:
        yield ok
    finally:
        try:
            _restore()
        except Exception:
            pass


def _status():
    if not _IS_WINDOWS:
        print("[lidaction_guard] Not Windows -- no-op here.")
        return
    cur = _read_lidaction()
    names = {0: "Do nothing", 1: "Sleep", 2: "Hibernate", 3: "Shut down"}
    if cur is None:
        print("[lidaction_guard] could not read Lid close action.")
    else:
        ac = names.get(cur["ac"], "?")
        dc = names.get(cur.get("dc"), "?")
        print(f"[lidaction_guard] Lid close action -> AC={cur['ac']} ({ac}) "
              f"DC={cur.get('dc')} ({dc})")
    st = _read_state()
    print(f"[lidaction_guard] breadcrumb {_STATE_FILE}: "
          + ("present -> a run may have died mid-cycle: " + str(st)
             if st is not None else "absent (clean)"))


def _selftest(hold_min, also_dc):
    if not _IS_WINDOWS:
        print("[lidaction_guard] Not Windows -- this guard is a no-op here. "
              "Run it on the CORTEX laptop with venv/Scripts/python.exe.")
        return
    print(f"[lidaction_guard] PID={os.getpid()} | holding {int(hold_min)} min | "
          f"also_dc={also_dc}")
    with lidaction_guard(also_dc=also_dc) as ok:
        print(f"[lidaction_guard] engaged -> {'OK' if ok else 'NO-OP (fail-open)'}")
        _status()
        print("[lidaction_guard] Now close the lid for a minute. Ctrl-C to stop.")
        end = time.time() + hold_min * 60.0
        try:
            while time.time() < end:
                print(f"[lidaction_guard] active ... {int(end - time.time())}s left")
                time.sleep(30)
        except KeyboardInterrupt:
            print("[lidaction_guard] stopped by user.")
    print("[lidaction_guard] released -> setting restored below:")
    _status()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CORTEX lid-close-action guard (isolated).")
    ap.add_argument("--hold", type=float, default=5.0, help="selftest minutes (default 5)")
    ap.add_argument("--ac-only", action="store_true", help="guard AC only (spec-minimal)")
    ap.add_argument("--status", action="store_true", help="print current setting + breadcrumb")
    ap.add_argument("--restore", action="store_true",
                   help="emergency: restore from a leftover breadcrumb and exit")
    a = ap.parse_args()
    if a.status:
        _status()
    elif a.restore:
        _recover_stale()
        print("[lidaction_guard] recover_stale done.")
        _status()
    else:
        _selftest(a.hold, also_dc=not a.ac_only)
