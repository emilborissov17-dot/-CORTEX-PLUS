#!/usr/bin/env python3
"""
memory/cycle_reaper.py — the cycle's last word: its exit code.

THE GAP THIS CLOSES (17 Aug 2026)
---------------------------------
A manually started cycle died at 14:16:33 UTC. The log ended mid-step with no
traceback, the heartbeat froze on `notify_patches_and_initiatives`, and twelve
minutes later the lock was cleared as a "death". FOUR explanations survived the
autopsy and nothing on disk could separate them:

    exit code 1           an outside TerminateProcess — taskkill /F, Task Manager,
                          or the console window closing (this is what it was)
    exit code 0xC0000005  an access violation in a C extension
    exit code 130 / 143   a SystemExit from a signal handler
    exit code 0           a clean finish that failed to seal its own record

One integer separates all four, and that integer existed: Popen returns a handle
from which it can be read. But `supervisor.spawn_cycle()` never waits on the
child, so the handle went out of scope when the five-millisecond tick exited —
and the number was gone before anyone could want it.

WHY A SEPARATE PROCESS AND NOT A THREAD
---------------------------------------
The supervisor is a short-lived tick by design: it spawns a 90-minute cycle and
exits in milliseconds. A tick that waited on the cycle WOULD BE the cycle. A
thread inside it dies with it. So the reaper is spawned detached alongside the
cycle, opens a handle to it immediately, and outlives the tick that created them
both. Cost, stated plainly: one idle python process (~12 MB) for the life of the
cycle. That is the price of the integer, and it is worth it.

WHY IT WAITS ON Popen's PID AND NOT THE CYCLE'S OWN
---------------------------------------------------
`venv\\Scripts\\python.exe` on this machine is a LAUNCHER. Popen.pid names a stub
that re-launches the real interpreter under a different pid — measured 17 Aug
2026: Popen.pid=48484, the child's own os.getpid()=52088. That mismatch is why
the lock and the heartbeat disagree about the pid, and it would be a trap here
too, except for one measured fact: THE STUB FORWARDS ITS CHILD'S EXIT CODE
(child called sys.exit(7); waiting on the stub returned 7). So the stub's handle
carries the number we want. The reaper needs no heartbeat lookup to find the
"real" pid and no guessing about which of two pids is authoritative.

WHAT THIS STILL CANNOT TELL US — read before trusting a record
--------------------------------------------------------------
  * WHO ended the process. Windows reports the exit code, never the killer. A 1
    from taskkill, a 1 from a closed console and a 1 from a python that called
    sys.exit(1) are the same integer. `ended_by` below is inferred from the
    heartbeat, not observed, and it can only ever name a killer that WRITES
    something (our own watchdog, our own signal handler). An outside kill stays
    anonymous and lands as "death".
  * A machine that reboots or loses power takes the reaper with the cycle. No
    record is written at all — the same blindness as today, for the same reason.
  * If the cycle dies in the ~200 ms before the reaper opens its handle, the
    code is unrecoverable and is recorded as null with `exit_code_source` saying
    why. A missing number is reported as missing, never guessed.
  * The exit code says nothing about WHERE the cycle was. That is the
    heartbeat's job, and the two are meant to be read together.
"""
from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# ── THE WRITE SURFACE, AS MODULE CONSTANTS ────────────────────────────────────
# Not `BASE / "memory" / ...` inside a function body. That is the exact shape
# that let a test write a fabricated failure into the real night log on 16 Aug
# 2026: a path built inside a function cannot be redirected by a fixture and
# cannot be seen by the write-surface guard. Both of these are also overridable
# from argv, because the reaper runs as a DETACHED process where monkeypatching
# cannot reach it — the supervisor passes its own (redirectable) constants down.
EXIT_RECORD = BASE / "memory" / "cycle_exit.json"
NIGHT_LOG = BASE / "memory" / "night_events.jsonl"

# How long to wait, AFTER the process is gone, for its killer to sign the
# heartbeat. supervisor.tick() kills and then retires the heartbeat a few
# milliseconds later, so the reaper's wait returns BEFORE the signature exists.
# Without this settle window every watchdog kill would be recorded as a death —
# which is precisely the distinction this module was asked to make.
SETTLE_SEC = 8.0
SETTLE_POLL_SEC = 0.25

SUBJECT = "CYCLE_EXIT"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Waiting on a process we did not spawn
# ---------------------------------------------------------------------------

def _wait_windows(pid: int) -> tuple[int | None, str]:
    """Block until `pid` exits; return (exit_code, source).

    OpenProcess returns a HANDLE — a pointer. ctypes defaults a foreign
    function's restype to c_int, which TRUNCATES it on 64-bit Windows and yields
    a handle that fails every subsequent call for no visible reason. The
    argtypes/restype declarations below are load-bearing, not decoration.

    The handle is opened ONCE and held across the wait. That is what makes the
    exit code readable afterwards: Windows keeps the process object alive while
    any handle to it is open, so a recycled pid cannot make us read a stranger's
    exit code.
    """
    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    INFINITE = 0xFFFFFFFF
    WAIT_OBJECT_0 = 0x00000000

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k32.WaitForSingleObject.restype = ctypes.c_ulong
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_ulong)]
    k32.GetExitCodeProcess.restype = ctypes.c_int
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.restype = ctypes.c_int

    handle = k32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                             0, int(pid))
    if not handle:
        # Almost always ERROR_INVALID_PARAMETER (87): the process was already
        # gone when we got here. Honest null, not a guess.
        return None, f"openprocess_failed:winerr={ctypes.get_last_error()}"
    try:
        rc = k32.WaitForSingleObject(handle, INFINITE)
        if rc != WAIT_OBJECT_0:
            return None, f"wait_failed:rc={rc}"
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None, f"getexitcode_failed:winerr={ctypes.get_last_error()}"
        return int(code.value), "GetExitCodeProcess"
    finally:
        k32.CloseHandle(handle)


def _wait_posix(pid: int) -> tuple[int | None, str]:
    """POSIX fallback. Honest about what it cannot do.

    On POSIX only a parent can reap a child, and the reaper is deliberately NOT
    the cycle's parent. So this works when the caller happens to own the pid
    (the tests do) and otherwise waits for the process to disappear and reports
    the code as unavailable rather than inventing one. This system runs on
    Windows; this branch exists so the module imports and tests anywhere.
    """
    try:
        _, status = os.waitpid(int(pid), 0)
        return os.waitstatus_to_exitcode(status), "waitpid"
    except ChildProcessError:
        pass
    except OSError as e:
        return None, f"waitpid_failed:{type(e).__name__}"
    while True:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return None, "posix_not_our_child"
        time.sleep(0.05)


def wait_for_exit(pid: int) -> tuple[int | None, str]:
    """Block until `pid` exits. Returns (exit_code, source-of-that-number)."""
    if os.name == "nt":
        return _wait_windows(pid)
    return _wait_posix(pid)


# ---------------------------------------------------------------------------
# A kill and a death are not the same event
# ---------------------------------------------------------------------------

def _read_heartbeat() -> dict | None:
    """The heartbeat as the reaper sees it, through the heartbeat module.

    Imported rather than re-read from a duplicated path constant, so a test that
    redirects memory.heartbeat.HEARTBEAT_PATH redirects this too, and so there is
    exactly one definition of where the heartbeat lives.
    """
    try:
        from memory import heartbeat as hb
        return hb.read()
    except Exception:
        return None


def _belongs_to(hb: dict | None, cycle_id: str | None) -> bool:
    if not hb or not cycle_id:
        return False
    return cycle_id in (hb.get("ended_cycle_id"), hb.get("cycle_id"))


def classify(exit_code: int | None, cycle_id: str | None,
             hb: dict | None) -> str:
    """Name the ending: watchdog_kill | signal | clean | death | unknown.

    THE POINT OF THIS FUNCTION (the second thing that was asked for): until now a
    watchdog kill and a spontaneous death both arrived at the morning report as
    "the cycle died". They are opposite facts. One means the system correctly
    stopped something wedged; the other means something is wrong that nobody
    chose. A ledger that spells them the same way cannot be used to tell whether
    the watchdog is working.

    `ended_by` is INFERRED, not observed — see the module docstring. Only a killer
    that signs the heartbeat can be named. Everything else is "death", which is
    the honest word for "it stopped and nobody admitted to it".
    """
    retired_by = str((hb or {}).get("retired_by") or "")
    if _belongs_to(hb, cycle_id):
        if (hb or {}).get("killed_by_watchdog") or \
                retired_by.startswith("supervisor:watchdog_kill"):
            return "watchdog_kill"
        if retired_by.startswith("cycle:signal"):
            return "signal"
    if exit_code is None:
        return "unknown"
    if exit_code == 0:
        return "clean"
    return "death"


def _settle_for_signature(cycle_id: str | None,
                          settle_sec: float) -> dict | None:
    """Give the killer a moment to sign, then read the heartbeat.

    Only used for a NON-ZERO exit. A clean exit needs no disambiguation, and the
    runner deletes its heartbeat on a clean finish anyway, so polling for one
    would be twenty seconds spent proving a file is still absent.
    """
    deadline = time.monotonic() + max(0.0, settle_sec)
    hb = _read_heartbeat()
    while time.monotonic() < deadline:
        if _belongs_to(hb, cycle_id) and hb.get("retired_utc"):
            return hb
        time.sleep(SETTLE_POLL_SEC)
        hb = _read_heartbeat()
    return hb


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

def _append_night(night_log: Path, fields: dict) -> bool:
    """One line in the night log. Never raises — see reap()'s docstring."""
    try:
        night_log.parent.mkdir(parents=True, exist_ok=True)
        with open(night_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _utc_now(), **fields},
                                ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _write_provisional(exit_record: Path, pid: int, cycle_id) -> bool:
    """Open the record in state WATCHING, before the wait begins.

    If the reaper dies during the wait, THIS is what is left on disk, and it
    says plainly that the watcher did not outlive the watched.
    """
    try:
        _write_atomic(exit_record, {
            "ts": _utc_now(),
            "cycle_id": cycle_id,
            "pid": int(pid),
            "reaper_pid": os.getpid(),
            "state": "WATCHING",
            "note": ("The reaper is waiting on this pid. If this record is still "
                     "in state WATCHING after the cycle is gone, the reaper died "
                     "before it could write the exit code — the cycle's last "
                     "integer is lost for that run, and that is itself the "
                     "finding, not an absence of one."),
        })
        return True
    except Exception:
        return False


def _note_orphaned_predecessor(exit_record: Path, night_log: Path, cycle_id) -> None:
    """A WATCHING record for some OTHER cycle means the previous reaper vanished.

    This is how the 17:59 death would have been visible: the 17:05 record was
    RECORDED, the 17:59 one never appeared at all, and nothing said a watcher
    had gone missing.
    """
    try:
        prev = json.loads(exit_record.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(prev, dict) or prev.get("state") != "WATCHING":
        return
    if str(prev.get("cycle_id")) == str(cycle_id):
        return
    _append_night(night_log, {
        "subject": f"{SUBJECT} PREVIOUS REAPER VANISHED",
        "detail": (f"the exit record was still in state WATCHING for cycle "
                   f"{prev.get('cycle_id')} (cycle pid={prev.get('pid')}, reaper "
                   f"pid={prev.get('reaper_pid')}) when the reaper for "
                   f"{cycle_id} started. That reaper died while waiting, so that "
                   f"cycle's exit code was never recorded."),
        "cycle_id": prev.get("cycle_id"),
        "pid": prev.get("pid"),
        "reaper_pid": prev.get("reaper_pid"),
    })


def _write_atomic(path: Path, payload: dict) -> None:
    """temp + os.replace, the same way the heartbeat is written.

    The supervisor reads this file from another process; a half-written record
    that failed to parse would be indistinguishable from no record at all.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _detail(record: dict) -> str:
    code = record.get("exit_code")
    shown = "unavailable" if code is None else \
        f"{code} ({record.get('exit_code_hex')})"
    return (f"cycle {record.get('cycle_id')} (pid {record.get('pid')}) ended "
            f"with exit code {shown} — ended_by={record.get('ended_by')}, "
            f"last step {record.get('last_step')!r} after "
            f"{record.get('waited_sec')}s")


def reap(pid: int, cycle_id: str | None = None,
         exit_record: Path | None = None, night_log: Path | None = None,
         settle_sec: float = SETTLE_SEC) -> dict:
    """Wait for `pid`, then record how it ended. Returns the record.

    Never raises: a reaper that dies while recording a death is worse than no
    reaper, because it looks like the record was written. Each sink is written
    independently, so a failure to append the night log still leaves the exit
    record on disk, and the record says which sinks landed.
    """
    exit_record = Path(exit_record) if exit_record else EXIT_RECORD
    night_log = Path(night_log) if night_log else NIGHT_LOG

    # ── THE RECORD MUST EXIST BEFORE IT CAN BE LOST (20 Aug 2026) ───────────
    # The 17:59 cycle left NO cycle_exit.json at all, while the 17:05 one did.
    # Everything below used to happen after wait_for_exit() returned, so a
    # reaper that died while waiting wrote nothing — and its silence was
    # indistinguishable from a reaper that was never started. Two processes
    # died together and the surviving evidence said only that one of them had
    # been alive at some point.
    #
    # So the record is now opened at the START, in state WATCHING, and closed
    # at the end in state RECORDED. A WATCHING record left on disk is itself
    # the finding: the reaper did not outlive the cycle it was watching.
    _note_orphaned_predecessor(exit_record, night_log, cycle_id)
    _write_provisional(exit_record, pid, cycle_id)
    _finalised = {"done": False}

    def _on_exit() -> None:
        # A reaper killed outright cannot run this. One that exits for any
        # reason python can see — an exception, a SystemExit, an interpreter
        # shutdown — leaves a line saying it went without recording.
        if _finalised["done"]:
            return
        _append_night(night_log, {
            "subject": f"{SUBJECT} REAPER EXITED WITHOUT RECORDING",
            "detail": (f"reaper pid={os.getpid()} stopped while waiting on cycle "
                       f"pid={pid} (cycle_id={cycle_id}). The cycle's exit code "
                       f"is lost for this run. A WATCHING record is on disk at "
                       f"{exit_record}."),
            "cycle_id": cycle_id, "pid": int(pid), "reaper_pid": os.getpid(),
        })

    atexit.register(_on_exit)

    t0 = time.monotonic()
    exit_code, source = wait_for_exit(int(pid))
    waited = round(time.monotonic() - t0, 1)

    hb = _settle_for_signature(cycle_id, settle_sec) if exit_code != 0 \
        else _read_heartbeat()
    ended_by = classify(exit_code, cycle_id, hb)

    record = {
        "ts": _utc_now(),
        "cycle_id": cycle_id,
        "pid": int(pid),
        "exit_code": exit_code,
        # 0xC0000005 is unreadable as 3221225477, and the hex is the whole
        # reason anyone looks at this field.
        "exit_code_hex": None if exit_code is None else f"0x{exit_code:08X}",
        "exit_code_source": source,
        "ended_by": ended_by,
        "last_step": (hb or {}).get("step"),
        "last_step_index": (hb or {}).get("step_index"),
        "retired_by": (hb or {}).get("retired_by"),
        "kill_landed": (hb or {}).get("kill_landed"),
        "waited_sec": waited,
        "reaper_pid": os.getpid(),
        # RECORDED means the reaper outlived the cycle and this is the whole
        # story. WATCHING on disk means it did not.
        "state": "RECORDED",
    }

    try:
        _write_atomic(exit_record, record)
        _finalised["done"] = True
        record["exit_record_written"] = True
    except Exception as e:
        record["exit_record_written"] = f"{type(e).__name__}: {e}"

    # The night log keeps ts/subject/detail because core/cycle_report.py reads
    # exactly those three for the "what happened while you slept" section. The
    # structured fields ride alongside for anything that wants the number.
    try:
        night_log.parent.mkdir(parents=True, exist_ok=True)
        with open(night_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": record["ts"],
                                 "subject": f"{SUBJECT} {ended_by}",
                                 "detail": _detail(record),
                                 **{k: record[k] for k in
                                    ("cycle_id", "pid", "exit_code",
                                     "exit_code_hex", "ended_by", "last_step")}},
                                ensure_ascii=False) + "\n")
        record["night_log_written"] = True
    except Exception as e:
        record["night_log_written"] = f"{type(e).__name__}: {e}"

    return record


def selftest() -> dict:
    """Report which integrations are LIVE and which are INERT in THIS repo.

    A module that degrades silently lets a claim stay true in the docstring and
    false on disk. The probe below really spawns a process, really waits on it by
    handle and really reads its exit code — into a TEMP directory, never into
    live memory/, because a diagnostic that writes a fabricated CYCLE_EXIT into
    the night log would be reported to the human as something that happened.
    """
    import shutil
    import subprocess

    rep: dict = {"ts": _utc_now(), "platform": os.name}

    # 1. Can we wait on a process we did not spawn, and read its code?
    try:
        tmpdir = Path(tempfile.mkdtemp(prefix="reaper_selftest_"))
        try:
            probe = subprocess.Popen(
                [sys.executable, "-c", "import sys,time; time.sleep(0.2); sys.exit(7)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            rec = reap(probe.pid, cycle_id="selftest",
                       exit_record=tmpdir / "cycle_exit.json",
                       night_log=tmpdir / "night_events.jsonl",
                       settle_sec=0.0)
            probe.wait(timeout=30)
            rep["wait_and_exit_code"] = {
                "LIVE": rec.get("exit_code") == 7,
                "got": rec.get("exit_code"), "expected": 7,
                "source": rec.get("exit_code_source"),
                "note": ("the launcher stub forwards its child's exit code"
                         if rec.get("exit_code") == 7 else
                         "could not read an exit code — every death will be "
                         "recorded with exit_code=null"),
            }
            rep["both_sinks"] = {
                "LIVE": bool(rec.get("exit_record_written") is True
                             and rec.get("night_log_written") is True),
                "exit_record": rec.get("exit_record_written"),
                "night_log": rec.get("night_log_written"),
            }
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as e:
        rep["wait_and_exit_code"] = {"LIVE": False,
                                     "error": f"{type(e).__name__}: {e}"}

    # 2. Is the heartbeat readable? Without it every ending is "death".
    try:
        from memory import heartbeat as _hb
        rep["heartbeat"] = {"LIVE": True, "path": str(_hb.HEARTBEAT_PATH),
                            "present": _hb.HEARTBEAT_PATH.exists()}
    except Exception as e:
        rep["heartbeat"] = {"LIVE": False, "error": f"{type(e).__name__}: {e}",
                            "note": "a kill can no longer be told from a death"}

    # 3. Does anything actually CALL us? A reaper nobody spawns is dead weight.
    try:
        src = (BASE / "supervisor.py").read_text(encoding="utf-8", errors="replace")
        wired = "memory.cycle_reaper" in src
        rep["supervisor_wiring"] = {
            "LIVE": wired,
            "note": ("supervisor.spawn_cycle spawns this module" if wired else
                     "NOTHING SPAWNS THIS MODULE — no cycle's exit code is "
                     "being recorded, whatever this file says it does"),
            "detached": "DETACHED_PROCESS" in src,
        }
    except Exception as e:
        rep["supervisor_wiring"] = {"LIVE": False,
                                    "error": f"{type(e).__name__}: {e}"}

    rep["writes_to"] = {"exit_record": str(EXIT_RECORD),
                        "night_log": str(NIGHT_LOG)}
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Wait for a cycle process and record how it ended.")
    ap.add_argument("--pid", type=int, required=True,
                    help="the pid returned by Popen (the launcher stub is fine — "
                         "it forwards the real interpreter's exit code)")
    ap.add_argument("--cycle-id", default=None)
    ap.add_argument("--exit-record", default=None,
                    help="where to write the latest exit record "
                         "(default memory/cycle_exit.json)")
    ap.add_argument("--night-log", default=None,
                    help="where to append the night event "
                         "(default memory/night_events.jsonl)")
    ap.add_argument("--settle-sec", type=float, default=SETTLE_SEC)
    a = ap.parse_args(argv)

    rec = reap(a.pid, a.cycle_id, a.exit_record, a.night_log, a.settle_sec)
    print(json.dumps(rec, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # --selftest is handled before argparse, which requires --pid.
    if "--selftest" in sys.argv:
        r = selftest()
        print(f"cycle_reaper selftest — {r['ts']} (os={r['platform']})")
        for key in ("wait_and_exit_code", "both_sinks", "heartbeat",
                    "supervisor_wiring"):
            d = r.get(key, {})
            print(f"  {'LIVE ' if d.get('LIVE') else 'INERT'}  {key}: "
                  f"{ {k: v for k, v in d.items() if k != 'LIVE'} }")
        print(f"  writes to: {r['writes_to']['exit_record']}")
        print(f"             {r['writes_to']['night_log']}")
        sys.exit(0 if all(r.get(k, {}).get("LIVE")
                          for k in ("wait_and_exit_code", "both_sinks",
                                    "supervisor_wiring")) else 1)
    sys.exit(main())
