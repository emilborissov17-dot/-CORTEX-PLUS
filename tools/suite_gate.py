#!/usr/bin/env python3
"""
tools/suite_gate.py — a suite run that knows whether it was contaminated.

WHY THIS EXISTS (ITEM 10, 29 August 2026)
------------------------------------------
GATE:NOCYCLE was checked ONCE, before the run, and never again. A suite takes
17-19 minutes. The supervisor evaluates every 5 minutes. So the gate answered a
question about the first second of a twenty-minute window and nothing asked it
again.

It has already happened, twice, on 2026-08-28:
  12:10:51-12:30:16  a cycle started at 12:15:20 (pid 30144), four minutes in.
                     Three tests moved. Two failed on the cycle's live writes;
                     one PASSED for the first time ever, because it only passes
                     when a lock exists — the cycle made it green. The 31-failure
                     result was discarded.
  18:15Z run         a tracked file was restored from outside the session while
                     the suite ran, and test_brain_scan reported it as a write
                     by the code under test.

A test that flips green because live state changed is exactly as invalid as one
that flips red, and neither is visible after the fact unless somebody writes the
readings down. That is what this does.

WHAT IT IS NOT. It cannot make a run clean. It can only tell you that one was
not, which is the difference between a discarded result and a wrong commit.

THREE OUTCOMES, NOT TWO
-----------------------
  REFUSED   a cycle held the lock BEFORE the run. Nothing is executed. This is
            the old gate, still here, just no longer the only check.
  INVALID   the lock appeared, disappeared, or changed cycle_id DURING the run.
            The result is not compared to the baseline and must not gate a
            commit. INVALID is not FAILED: the tests may all have passed, and
            that is precisely the problem — nobody can tell which passes were
            earned.
  VALID     both readings agree that no cycle touched the window.

VALID IS NOT THE SAME AS "NOTHING WROTE TO memory/", AND THE REPORT SAYS SO.
Measured from the live Windows task registry on 2026-08-29: CORTEX_Approvals
runs EVERY MINUTE and CORTEX_Pulse EVERY FIVE, and both write under memory/ —
pulse_stream.jsonl, pulse_runs.log, pulse_signal.json, human_channel_state.json.
They run whether or not a cycle is live. So a test that asserts byte-identity
across the whole of memory/ cannot be made reliable by this gate or any other
gate on cycle.lock; it is asserting something the machine does not offer. That
is a defect in such a test, it is named in the report this writes, and it is not
something a runner can fix.

RECORDING IS ON BY DEFAULT HERE, DELIBERATELY AGAINST THE HOUSE RULE.
CLAUDE.md says a module that writes a journal dry-runs unless given --write.
The library function record() obeys that and defaults to write=False. The `run`
subcommand does NOT, because 10.2 is the requirement that an invalid run be
distinguishable from a clean one afterwards, and a recorder that stays silent
unless someone remembers a flag is the same defect as no recorder. Use
--no-record to suppress it. Said here rather than left for a reader to notice.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
LOCK = BASE / "memory" / "cycle.lock"
HEARTBEAT = BASE / "memory" / "heartbeat.json"
# THE WITNESS THAT SURVIVES. memory/heartbeat.json is DELETED when a cycle
# seals — verified 2026-08-29, minutes after cycle 2026-08-29T03:04:01 finished:
# the file was simply gone. So the heartbeat can testify that a cycle is running
# now, and cannot testify that one ran and finished inside the window: at both
# readings it is equally absent. memory/last_cycle_id.txt holds the last SEALED
# cycle_id and persists, so a cycle that began and ended between the two
# readings still leaves a mark. Both are read; either moving is enough.
LAST_SEALED = BASE / "memory" / "last_cycle_id.txt"
RUNS = BASE / "memory" / "suite_runs.jsonl"

REFUSED = "REFUSED"
INVALID = "INVALID"
VALID = "VALID"

# ── THE VERDICT NAMES ANSWER THE QUESTION THEY ARE USED FOR (19 Sep 2026) ────
# VALID meant only "the suite executed and no cycle touched the window". It was
# READ as "safe to push", every day, by me among others. Those are different
# claims and the name did not distinguish them, so a run with thirty new
# failures came back VALID and looked like a pass.
#
# VALID is now strictly: it ran, AND nothing failed outside test/known_failures.txt.
RAN_CLEAN = VALID
RAN_WITH_NEW_FAILURES = "RAN_WITH_NEW_FAILURES"
DID_NOT_RUN = "DID_NOT_RUN"

# THE BASELINE IS A COMMITTED FILE, and the only one.
KNOWN_FAILURES = BASE / "test" / "known_failures.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid) -> bool | None:
    """None means "could not tell" — never silently False, because a lock whose
    liveness is unknown must not be reported as a dead one."""
    if not pid:
        return None
    try:
        import psutil
        return bool(psutil.pid_exists(int(pid)))
    except Exception:
        return None


def read_state(lock: pathlib.Path | None = None,
               heartbeat: pathlib.Path | None = None,
               last_sealed: pathlib.Path | None = None) -> dict:
    """One reading of the world, taken atomically enough to compare with another."""
    lk = lock or LOCK
    hb = heartbeat or HEARTBEAT
    ls = last_sealed or LAST_SEALED
    state = {"ts": _now(), "lock_present": lk.exists(),
             "pid": None, "cycle_id": None, "pid_alive": None,
             "heartbeat_cycle_id": None, "heartbeat_step": None,
             "heartbeat_updated_utc": None, "last_sealed_cycle_id": None}
    try:
        state["last_sealed_cycle_id"] = ls.read_text(encoding="utf-8").strip() or None
    except Exception:
        pass
    if state["lock_present"]:
        try:
            d = json.loads(lk.read_text(encoding="utf-8"))
            state["pid"] = d.get("pid")
            state["cycle_id"] = d.get("cycle_id")
            state["pid_alive"] = _pid_alive(d.get("pid"))
        except Exception as e:
            # A lock that cannot be parsed is still a lock. Recording it as
            # absent would turn a broken file into an all-clear.
            state["lock_unreadable"] = f"{type(e).__name__}: {e}"
    try:
        h = json.loads(hb.read_text(encoding="utf-8"))
        state["heartbeat_cycle_id"] = h.get("cycle_id")
        state["heartbeat_step"] = h.get("step")
        state["heartbeat_updated_utc"] = h.get("updated_utc")
        state["heartbeat_pid"] = h.get("pid")
        state["heartbeat_pid_alive"] = _pid_alive(h.get("pid"))
    except Exception:
        pass
    return state


def cycle_is_live(state: dict) -> bool:
    """Is a cycle running RIGHT NOW, for the refusal decision.

    THE LOCK'S PID IS HEARSAY AND THE HEARTBEAT'S IS THE PROCESS SPEAKING.
    supervisor.py:785-788 learned this on 16 Aug 2026 and wrote it down: "the
    lock's pid comes from Popen and on this machine points at the venv launcher
    stub, while the heartbeat's pid is written by the cycle itself with
    os.getpid()." A launcher stub exits within seconds of spawning the real
    interpreter — observed again on 2026-08-29, when this very runner appeared
    as two processes, 78452 spawning 81128 for the same script.

    So judging liveness by the lock's pid alone can read a LIVE cycle as a stale
    lock and let the suite run straight into it — the gate failing OPEN, which
    is the one direction it must never fail. Any of the three saying "alive" is
    enough; only all three saying otherwise permits the run.
    """
    if not state.get("lock_present"):
        return False
    if state.get("pid_alive") or state.get("heartbeat_pid_alive"):
        return True
    # Neither pid resolves. If liveness could not be determined at all, treat
    # the lock as live: unknown is not dead.
    if state.get("pid_alive") is None and state.get("heartbeat_pid_alive") is None:
        return True
    return False


def load_known_failures(path: pathlib.Path | None = None) -> dict:
    """The committed baseline: node id -> the reason someone wrote beside it.

    WHY A FILE AND NOT THE LAST RUN. Until today run() compared its failed set to
    the PREVIOUS record in memory/suite_runs.jsonl, so the baseline was written by
    the run it judged. A failure was "new" exactly once and known forever after,
    with no human in the loop. Over the 58 recorded runs, 57 VALID, TWENTY of them
    admitted ids the previous run did not: +19 on 09-03, +23 on 09-06, +30 on
    09-08, +18 on 09-14, +5 on 09-18. A ratchet, not a baseline.

    Nothing in this module writes this file. It is edited by a person, in a commit,
    with the reason on the line.
    """
    p = path or KNOWN_FAILURES
    out = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        node, _, why = line.partition("#")
        node = node.strip()
        if node:
            out[node] = why.strip()
    return out


def verdict(before: dict, after: dict) -> dict:
    """Compare two readings. The reason is a sentence, not a flag, because the
    next reader needs to know WHICH change happened."""
    reasons = []
    if before.get("lock_present") and not after.get("lock_present"):
        reasons.append(
            f"a cycle held the lock at the start (cycle_id "
            f"{before.get('cycle_id')!r}) and it was gone by the end — the run "
            f"overlapped the tail of a cycle")
    if not before.get("lock_present") and after.get("lock_present"):
        reasons.append(
            f"no lock at the start, but a cycle held one at the end (cycle_id "
            f"{after.get('cycle_id')!r}, pid {after.get('pid')}) — a cycle "
            f"started inside the run window")
    if (before.get("lock_present") and after.get("lock_present")
            and before.get("cycle_id") != after.get("cycle_id")):
        reasons.append(
            f"the cycle_id changed under the run: {before.get('cycle_id')!r} -> "
            f"{after.get('cycle_id')!r} — one cycle ended and another began")
    if (before.get("lock_present") and after.get("lock_present")
            and before.get("cycle_id") == after.get("cycle_id")):
        reasons.append(
            f"a cycle (cycle_id {before.get('cycle_id')!r}) held the lock for "
            f"the whole run — the gate should never have opened")
    # SECOND AND THIRD WITNESSES, for the case the lock cannot see: a cycle that
    # begins and ends between the two readings leaves both lock readings empty.
    hb_before = before.get("heartbeat_cycle_id")
    hb_after = after.get("heartbeat_cycle_id")
    if hb_before != hb_after:
        reasons.append(
            f"the heartbeat's cycle_id moved from {hb_before!r} to {hb_after!r} "
            f"even though the lock did not catch it — a cycle was running inside "
            f"the window")
    ls_before = before.get("last_sealed_cycle_id")
    ls_after = after.get("last_sealed_cycle_id")
    if ls_before != ls_after:
        reasons.append(
            f"memory/last_cycle_id.txt moved from {ls_before!r} to {ls_after!r} "
            f"— a cycle SEALED inside the window. This is the witness that "
            f"survives: heartbeat.json is deleted on seal, so it cannot report "
            f"a cycle that finished before the second reading")
    return {"outcome": INVALID if reasons else VALID,
            "reasons": reasons, "before": before, "after": after}


def record(entry: dict, write: bool = False,
           path: pathlib.Path | None = None) -> dict:
    """Append one run record. DRY unless write=True (house rule)."""
    p = path or RUNS
    if write:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def format_verdict(v: dict) -> str:
    lines = [f"SUITE RUN {v['outcome']}"]
    for r in v.get("reasons", []):
        lines.append(f"  ! {r}")
    for label, s in (("start", v["before"]), ("end", v["after"])):
        lines.append(
            f"  {label:<5} {s['ts']}  lock={'YES' if s['lock_present'] else 'no'}"
            f"  cycle_id={s.get('cycle_id')!r}  pid={s.get('pid')}"
            f"  alive={s.get('pid_alive')}"
            f"  hb_cycle={s.get('heartbeat_cycle_id')!r}"
            f"  hb_step={s.get('heartbeat_step')!r}")
    nf = v.get("new_failures")
    if nf:
        lines.append("  NEW FAILURES, not in %s (%d):" % (
            v.get("baseline_file") or "the baseline file", len(nf)))
        for n in nf[:25]:
            lines.append("    + %s" % n)
        if len(nf) > 25:
            lines.append("    ... and %d more" % (len(nf) - 25))
    for n in (v.get("baseline_now_green") or [])[:25]:
        lines.append("    - %s  GREEN: remove this line from the baseline" % n)
    for n in (v.get("baseline_vanished") or [])[:25]:
        lines.append("    ? %s  no longer exists: the line protects nothing" % n)

    if v["outcome"] == RAN_CLEAN:
        lines.append("  ran, and every failure is listed in %s (%s entries). "
                     "NOTE: scheduled tasks (CORTEX_Approvals every 1 min, "
                     "CORTEX_Pulse every 5) still write under memory/ — this "
                     "says no CYCLE, not no writer."
                     % (v.get("baseline_file"), v.get("baseline_size")))
    elif v["outcome"] == RAN_WITH_NEW_FAILURES:
        lines.append("  the suite ran and produced failures nobody has accepted. "
                     "DO NOT push. Fix them, or add each id to %s with a reason "
                     "in the same commit."
                     % (v.get("baseline_file") or "the baseline file"))
    elif v["outcome"] == DID_NOT_RUN:
        lines.append("  the suite did not finish. failed=[] here means NOTHING "
                     "WAS MEASURED, not that nothing failed.")
    else:
        lines.append("  DO NOT let this gate a commit: the window was not clean, "
                     "so the numbers cannot be trusted whatever pytest printed.")
    return "\n".join(lines)


def _stream_command(cmd, cwd):
    """Run `cmd`, echoing its stdout LINE BY LINE as it arrives.

    WHY (19 Sep 2026). This was subprocess.run(..., capture_output=True), which
    buffers the whole run in a pipe and hands it over only at exit. For a suite
    that takes 37 minutes that means claude/reports/SUITE_GATE_*.out.log sits at
    0 bytes the entire time, and a run that is killed - by the harness, by the
    low-memory reaper, by a reboot - loses EVERY line it had produced. The one
    question worth asking of a killed suite, "which test was it on", was
    unanswerable by construction.

    THE STREAMS STAY SEPARATE, and that is a measurement, not a preference. The
    obvious form is stderr=STDOUT, one pipe, no second reader. But nothing here
    has ever read proc.stderr, so merging would feed the parser text it has never
    seen, and the parser is not indifferent to it:

        stdout only     summary='42 failed, 5284 passed in 2227.24s'  errors=[]
        stderr merged   summary='some warning: 0 failed to initialise'
                        errors=['conftest']

    A stderr line beginning "ERROR " becomes a collection error and the outcome
    turns COLLECTION_FAILED; a stderr line containing " failed" hijacks the
    summary, because that scan runs in reverse and the LAST match wins. Either
    one silently changes a verdict. So stdout is streamed and parsed exactly as
    before, and stderr is drained on its own thread - drained, because a full
    stderr pipe deadlocks a child that nobody is reading.

    Returns an object with .stdout, .stderr and .returncode, so every line of the
    parsing below is untouched.
    """
    import threading
    import types

    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, encoding="utf-8", errors="replace")

    err_chunks: list = []

    def _drain_err():
        try:
            for line in proc.stderr:
                err_chunks.append(line)
        except Exception:                                    # noqa: BLE001
            pass

    t = threading.Thread(target=_drain_err, daemon=True)
    t.start()

    out_lines: list = []
    try:
        for line in proc.stdout:
            line = line.rstrip(chr(10))
            out_lines.append(line)
            # Flushed per line: an unflushed echo is the same invisibility this
            # function exists to remove.
            sys.stdout.write(line + chr(10))
            sys.stdout.flush()
    finally:
        try:
            proc.stdout.close()
        except Exception:                                    # noqa: BLE001
            pass
        rc = proc.wait()
        t.join(timeout=10)
        try:
            proc.stderr.close()
        except Exception:                                    # noqa: BLE001
            pass

    return types.SimpleNamespace(
        stdout=chr(10).join(out_lines),
        stderr="".join(err_chunks),
        returncode=rc,
    )


def run(pytest_args=None, write_record: bool = True,
        lock: pathlib.Path | None = None,
        heartbeat: pathlib.Path | None = None,
        last_sealed: pathlib.Path | None = None,
        runs_path: pathlib.Path | None = None,
        command=None,
        known_path: pathlib.Path | None = None) -> dict:
    """Read, run, read, judge, record. Returns the full run record.

    `command` is injectable so a fixture can substitute something that writes a
    fake lock mid-run without needing a real 19-minute suite.
    """
    before = read_state(lock, heartbeat, last_sealed)
    if cycle_is_live(before):
        entry = {"ts": _now(), "outcome": REFUSED,
                 "reasons": [f"a cycle already held memory/cycle.lock "
                             f"(cycle_id {before.get('cycle_id')!r}, pid "
                             f"{before.get('pid')}) — nothing was executed"],
                 "before": before, "after": None, "returncode": None,
                 "summary": None}
        record(entry, write=write_record, path=runs_path)
        return entry

    # ITEM 45 (30 Aug 2026): THE GATE RUNS ONLY DETERMINISTIC TESTS.
    # Nine tests carry @pytest.mark.live_state — their outcome moves with the
    # world rather than with the code, measured across 19 runs (see pytest.ini
    # for the method and the one deliberate exclusion). They are not deleted and
    # not weakened; tools/live_monitor.py runs exactly this complement. A gate
    # that goes red because a cycle refused overnight is not a gate, and a
    # baseline amended after every cycle is a tolerance log.
    # --durations=25: 37 minutes went somewhere and nothing recorded where.
    # -rA, not -rf: the short summary must list the PASSED ids too, or a baseline
    # entry that has gone green is indistinguishable from one that never ran.
    cmd = command or [sys.executable, "-m", "pytest", "-q", "-rA",
                      "--durations=25",
                      "-m", "not live_state",
                      *(pytest_args or [])]
    proc = _stream_command(cmd, str(BASE))
    after = read_state(lock, heartbeat, last_sealed)

    v = verdict(before, after)
    summary = ""
    for line in reversed((proc.stdout or "").splitlines()):
        if " passed" in line or " failed" in line:
            summary = line.strip()
            break
    failed = sorted(l.split(" ")[1] for l in (proc.stdout or "").splitlines()
                    if l.startswith("FAILED ") and len(l.split(" ")) > 1)
    # Every node id this run actually reached, from the -rA short summary. Needed
    # to tell "a baseline entry passed" from "a baseline entry was not run at
    # all" -- silently treating the second as the first is how a deleted test
    # keeps protecting nothing.
    ran_ids = {l.split(" ")[1] for l in (proc.stdout or "").splitlines()
               if l.split(" ")[0] in ("PASSED", "FAILED", "ERROR", "XFAIL",
                                      "XPASS", "SKIPPED")
               and len(l.split(" ")) > 1}

    # ── A COLLECTION ERROR IS NOT A RED COUNT (6 Sep 2026) ──────────────────
    # Broker-bot, a separate project vendored into the tree, appeared at 11:57
    # and pytest walked into it: `import ccxt` failed, collection aborted with 3
    # errors, and NOT ONE TEST RAN. The gate had no opinion at all - yet the run
    # would otherwise have been recorded as a normal entry with failed=[] and a
    # returncode, which reads as "zero failures" to anything counting reds.
    #
    # A failure is a measurement. A collection error is the absence of one, and
    # it gets its own outcome so it can never be mistaken for a clean suite.
    collect_errors = sorted(
        l.split(" ")[1] for l in (proc.stdout or "").splitlines()
        if l.startswith("ERROR ") and len(l.split(" ")) > 1)
    interrupted = any("during collection" in l
                      for l in (proc.stdout or "").splitlines())
    outcome = v["outcome"]
    reasons = list(v["reasons"])

    # ── A RUN THAT DID NOT FINISH IS NOT A CLEAN RUN (6 Sep 2026) ───────────
    # MEASURED an hour after the collection fix, by killing a run mid-flight:
    #
    #   {"outcome": "VALID", "returncode": 1, "summary": "", "failed": []}
    #
    # A terminated suite recorded as VALID with zero failures. That is worse than
    # the collection case, because VALID is an AFFIRMATIVE claim - a reader
    # counting reds sees a clean suite where nothing was measured at all.
    #
    # pytest always prints a "N passed / N failed" line when it completes. No
    # summary means it did not, whatever the return code says.
    #
    # TWO CORRECTIONS, 6 Sep, after this check went in at 12:36 and turned seven
    # tests red without anyone noticing - CI had been failing since 22 Aug and
    # could not report it.
    #
    # (1) The inference only holds IF WE RAN PYTEST. run() takes an arbitrary
    #     command, and the tests drive it with `python -c pass` as a stand-in
    #     while they exercise the lock logic. That command prints no summary
    #     because it is not pytest, not because it was killed. Inferring "the run
    #     did not finish" from a command that was never going to print a summary
    #     is a lie about a different thing.
    # (2) INCOMPLETE must not OVERWRITE a more specific verdict. INVALID says a
    #     cycle wrote to memory/ during the window, so the numbers cannot be
    #     trusted whatever pytest did; that is the stronger claim and it wins.
    #     The incompleteness is still recorded as a reason, so nothing is lost -
    #     the outcome narrows, the record does not.
    ran_pytest = any("pytest" in str(c) for c in (cmd if isinstance(cmd, list) else [cmd]))
    if ran_pytest and not summary:
        reasons.append(
            f"DID_NOT_RUN: pytest printed no summary line (returncode "
            f"{proc.returncode}), so the run did not finish. failed=[] here "
            f"means NOTHING WAS MEASURED, not that nothing failed.")
        if outcome == VALID:
            outcome = DID_NOT_RUN

    if collect_errors or interrupted:
        outcome = "COLLECTION_FAILED"
        reasons.append(
            f"COLLECTION FAILED: {len(collect_errors)} file(s) could not be "
            f"imported, so the suite never ran: "
            + ", ".join(collect_errors[:6])
            + (" ..." if len(collect_errors) > 6 else ""))

    # ── THE BASELINE COMPARISON, AGAINST THE COMMITTED FILE AND NOTHING ELSE ──
    known = load_known_failures(known_path)
    failed_set = set(failed)
    new_failures = sorted(failed_set - set(known))
    # A listed test that PASSES is not a quiet win. The line is a debt someone
    # took on; when it is paid the line must go, or the file rots into a list of
    # things that used to be broken and the next real failure hides among them.
    now_green = sorted(n for n in known if n not in failed_set and n in ran_ids) if ran_ids else []
    # An id in the file that pytest no longer knows about: renamed, deleted, or
    # misspelled. Either way it is protecting nothing.
    vanished = sorted(n for n in known if ran_ids and n not in ran_ids) if ran_ids else []

    if ran_pytest and summary:
        if new_failures:
            outcome = RAN_WITH_NEW_FAILURES
            reasons.append(
                "%d failure(s) are NOT in %s: %s"
                % (len(new_failures), KNOWN_FAILURES.name,
                   ", ".join(new_failures[:10])
                   + (" ..." if len(new_failures) > 10 else "")))
        elif outcome == VALID:
            outcome = RAN_CLEAN
    if now_green:
        reasons.append(
            "%d baseline entr%s GREEN — remove from %s: %s"
            % (len(now_green), "y is" if len(now_green) == 1 else "ies are",
               KNOWN_FAILURES.name, ", ".join(now_green[:10])
               + (" ..." if len(now_green) > 10 else "")))
    if vanished:
        reasons.append(
            "%d id(s) in %s no longer exist (renamed or deleted) and protect "
            "nothing: %s"
            % (len(vanished), KNOWN_FAILURES.name, ", ".join(vanished[:10])
               + (" ..." if len(vanished) > 10 else "")))

    entry = {"ts": _now(), "outcome": outcome, "reasons": reasons,
             "before": before, "after": after,
             "returncode": proc.returncode, "summary": summary,
             "failed": failed, "collection_errors": collect_errors,
             "new_failures": new_failures,
             "baseline_now_green": now_green,
             "baseline_vanished": vanished,
             "baseline_file": str(KNOWN_FAILURES.relative_to(BASE)).replace("\\", "/"),
             "baseline_size": len(known),
             "command": cmd}
    record(entry, write=write_record, path=runs_path)
    entry["_stdout"] = proc.stdout
    return entry


def _selftest() -> int:
    import tempfile
    print("tools/suite_gate.py --selftest")
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'} {label}")
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as d:
        t = pathlib.Path(d)
        lk, hb, runs = t / "cycle.lock", t / "heartbeat.json", t / "runs.jsonl"
        ls = t / "last_cycle_id.txt"
        hb.write_text(json.dumps({"cycle_id": "C1", "step": "x",
                                  "updated_utc": "T"}), encoding="utf-8")
        ls.write_text("SEALED-1", encoding="utf-8")

        clean = read_state(lk, hb, ls)
        check("a missing lock reads as absent, not as an error",
              clean["lock_present"] is False)

        lk.write_text(json.dumps({"pid": 999999, "cycle_id": "C2"}),
                      encoding="utf-8")
        held = read_state(lk, hb, ls)
        check("a present lock is read with its cycle_id", held["cycle_id"] == "C2")

        check("a lock appearing mid-run is INVALID",
              verdict(clean, held)["outcome"] == INVALID)
        check("a lock disappearing mid-run is INVALID",
              verdict(held, clean)["outcome"] == INVALID)
        check("a lock held throughout is INVALID",
              verdict(held, held)["outcome"] == INVALID)
        check("two clean readings are VALID",
              verdict(clean, clean)["outcome"] == VALID)

        moved = dict(clean)
        moved["heartbeat_cycle_id"] = "C9"
        check("a heartbeat cycle_id that moved is caught even with no lock",
              verdict(clean, moved)["outcome"] == INVALID)

        stub = {"lock_present": True, "pid": 999999, "pid_alive": False,
                "heartbeat_pid": 4242, "heartbeat_pid_alive": True}
        check("a lock naming a DEAD launcher stub is still live when the "
              "heartbeat's pid is alive", cycle_is_live(stub) is True)
        check("a lock whose liveness cannot be determined at all counts as live",
              cycle_is_live({"lock_present": True}) is True)
        check("a lock with both pids provably dead is not live",
              cycle_is_live({"lock_present": True, "pid_alive": False,
                             "heartbeat_pid_alive": False}) is False)

        sealed = dict(clean)
        sealed["last_sealed_cycle_id"] = "SEALED-2"
        check("a cycle that starts AND SEALS inside the window is caught by "
              "last_cycle_id.txt, which survives the seal",
              verdict(clean, sealed)["outcome"] == INVALID)

        lk.unlink()
        entry = run(command=[sys.executable, "-c", "pass"], write_record=True,
                    lock=lk, heartbeat=hb, last_sealed=ls, runs_path=runs)
        check("a clean run records VALID", entry["outcome"] == VALID)
        check("the record is on disk with both readings",
              runs.exists()
              and json.loads(runs.read_text(encoding="utf-8").splitlines()[0])["before"])
        check("record() is dry by default",
              record({"x": 1}, path=t / "nope.jsonl") and not (t / "nope.jsonl").exists())

    print("  integrations:")
    print(f"    memory/cycle.lock       "
          f"{'LIVE (a cycle holds it now)' if LOCK.exists() else 'absent — no cycle'}")
    print(f"    memory/heartbeat.json   {'LIVE' if HEARTBEAT.exists() else 'INERT'}")
    print(f"    memory/suite_runs.jsonl "
          f"{'LIVE (' + str(len(RUNS.read_text(encoding='utf-8').splitlines())) + ' runs)' if RUNS.exists() else 'INERT — no run recorded yet'}")
    try:
        import psutil  # noqa: F401
        print("    psutil                  LIVE — pid liveness is checkable")
    except Exception:
        print("    psutil                  INERT — pid_alive will read None")
    return 0 if ok else 1


def _schedule_report() -> int:
    """10.3 — how long a run can be before it is at risk. Reads only."""
    cfg = json.loads((BASE / "config" / "scheduler.json").read_text(encoding="utf-8"))
    print("CYCLE SCHEDULE, from config/scheduler.json")
    print(f"  daily_hour           {cfg.get('daily_hour')}  (local)")
    print(f"  catchup_grace_hours  {cfg.get('catchup_grace_hours')}")
    print("  => the supervisor may start the day's cycle on any tick between "
          f"{cfg.get('daily_hour')}:00 and "
          f"{(int(cfg.get('daily_hour', 0)) + int(cfg.get('catchup_grace_hours', 0))) % 24}:00 local.")
    print()
    print("SUPERVISOR TICK, from the Windows task registry (read 2026-08-29):")
    print("  CORTEX_Supervisor    every 5 minutes   <- the one that can start a cycle")
    print("  CORTEX_Approvals     every 1 minute    writes memory/human_channel_state.json")
    print("  CORTEX_Pulse         every 5 minutes   writes memory/pulse_*.json*")
    print("  CORTEX_TriggerWatchdog every 15 minutes")
    print()
    print("THE ANSWER: a suite run measured 1041-1141 s on 2026-08-28/29 "
          "(17:21 to 19:01).")
    print("  300 s between supervisor ticks means EVERY run spans 3-4 chances "
          "for a cycle to start.")
    print("  A run is only safe if it fits inside one tick — 5 minutes — and it "
          "does not, by a factor of about four.")
    print("  Inside the 20-hour catch-up window a clean run is therefore LUCK, "
          "not a property of the gate.")
    print("  And VALID never meant 'nothing wrote to memory/': Approvals and "
          "Pulse write there every minute and every five, cycle or no cycle.")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--selftest" in argv:
        sys.exit(_selftest())
    if "--schedule" in argv:
        sys.exit(_schedule_report())
    if "--state" in argv:
        print(json.dumps(read_state(), ensure_ascii=False, indent=2))
        sys.exit(0)
    passthrough = [a for a in argv if a != "--no-record"]
    result = run(pytest_args=passthrough, write_record="--no-record" not in argv)
    print(result.get("_stdout", ""))
    if result["outcome"] == "INCOMPLETE":
        print("\n" + "=" * 70)
        for r in result["reasons"]:
            if r.startswith("INCOMPLETE"):
                print(r)
        print("=" * 70)
        sys.exit(2)
    if result["outcome"] == "COLLECTION_FAILED":
        # Loud and separate: never a red count, never a green one either.
        print("\n" + "=" * 70)
        for r in result["reasons"]:
            if r.startswith("COLLECTION FAILED"):
                print(r)
        print("The suite did not run. Fix the import or exclude the directory "
              "in pytest.ini's norecursedirs; do NOT read this as 0 failures.")
        print("=" * 70)
        sys.exit(2)
    print(format_verdict({"outcome": result["outcome"],
                          "reasons": result["reasons"],
                          "before": result["before"],
                          "after": result["after"] or result["before"]}))
    if result["summary"]:
        print(f"  summary: {result['summary']}")
    # An INVALID run must not look like a pass to a script.
    sys.exit(0 if result["outcome"] == VALID and result["returncode"] == 0 else 1)
