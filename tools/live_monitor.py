#!/usr/bin/env python3
"""tools/live_monitor.py — the tests that watch the world, run apart from the gate.

ITEM 45, 30 August 2026.

WHAT THIS IS. The exact complement of tools/suite_gate.py. The gate runs
`-m "not live_state"`; this runs `-m live_state`. Between them they run every
test in the repository, and no test is deleted, skipped or weakened by the split.

WHY THE SPLIT EXISTS. Kimi: "A gating test must be deterministic; any test whose
outcome varies with live state is an operational monitor, not a correctness
gate." And: "A baseline amended after every cycle is a tolerance log, not a
baseline. The property it must have is stability against external state changes
- it must reflect code defects, not world mutations."

Twice in eighteen hours a commit was blocked by a test that went red because the
WORLD moved: on 29 Aug three metta_parallel tests lost the live CLIMATE
contradiction they assert, and on 30 Aug test_flow_score found
memory/step_contract_latest.json holding zero steps because the 03:00 cycle had
refused at the homeostasis gate. Neither was a code defect. Both would have been
"fixed" by widening the baseline, which is how a baseline becomes a tolerance
log.

RED HERE IS INFORMATION, NOT FAILURE — AND SILENCE IS THE REAL FAILURE.
Kimi's objection to this whole design was that a second-class suite gets ignored:
a green folder nobody opens is worse than a red line in the suite everyone reads.
That objection is answered by SURFACING, not by the split. This module writes
memory/live_monitor_latest.json so the result is visible to whatever reads it —
and the record carries `NEVER_RUN` as a distinct state from `OK`, because
"nothing is wrong" and "nobody looked" are different facts. That is the same
distinction core/answered_by.py draws between degraded=False and degraded=None,
and for the same reason.

THE COMPASS NEEDLE IS NOT BUILT HERE, DELIBERATELY. Surfacing this in
tools/compass.py would change what "N of 4 needles" means, and K1-K4's meaning is
not something to settle as a side effect of a test-runner commit. That decision
is with Kimi. Until it lands, this file writes the record and nothing reads it —
which is stated plainly rather than left for someone to discover.

    venv/Scripts/python.exe tools/live_monitor.py           # run and record
    venv/Scripts/python.exe tools/live_monitor.py --no-record
    venv/Scripts/python.exe tools/live_monitor.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "memory" / "live_monitor_latest.json"
LOG = BASE / "memory" / "live_monitor_runs.jsonl"
MARKER = "live_state"

NEVER_RUN = "NEVER_RUN"
OK = "OK"
RED = "LIVE_CHECKS_RED"
NO_TESTS = "NO_TESTS_MARKED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(write: bool = True, extra=None) -> dict:
    """Run the marked tests. Never raises on their failure — red is the output."""
    cmd = [sys.executable, "-m", "pytest", "-q", "-rf", "-m", MARKER,
           *(extra or [])]
    proc = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = proc.stdout or ""
    failed = sorted(l.split(" ")[1] for l in out.splitlines()
                    if l.startswith("FAILED ") and len(l.split(" ")) > 1)
    summary = ""
    for line in reversed(out.splitlines()):
        if " passed" in line or " failed" in line or "no tests ran" in line:
            summary = line.strip()
            break

    total = 0
    for line in out.splitlines():
        if "deselected" in line and "collected" in line:
            try:
                total = int(line.split("/")[0].strip().split()[-1])
            except Exception:
                pass

    if "no tests ran" in out or (total == 0 and not failed and "passed" not in out):
        status, why = NO_TESTS, (
            f"no test carries @pytest.mark.{MARKER}. Either the markers were "
            f"removed or the marker was renamed; the monitor is watching "
            f"nothing, which is not the same as everything being well.")
    elif failed:
        status = RED
        why = (f"{len(failed)} live check(s) disagree with the world right now. "
               f"This is NOT a code defect and must not gate a commit — see "
               f"tools/live_monitor.py. It IS a statement about the system's "
               f"current state and should be read as one.")
    else:
        status, why = OK, "every live check agrees with the world right now"

    rec = {"ts": _now(), "status": status, "why": why, "summary": summary,
           "failed": failed, "returncode": proc.returncode,
           "marker": MARKER, "command": cmd}
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rec["_stdout"] = out
    return rec


def latest() -> dict:
    """What the last run said — or NEVER_RUN. For whatever surfaces this.

    NEVER_RUN IS THE POINT OF THIS FUNCTION. A caller that treated a missing
    file as "fine" would report a monitor that has never executed as green, and
    a monitor that reads green without running is worse than no monitor.
    """
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"ts": None, "status": NEVER_RUN,
                # str(), not relative_to(): the selftest points OUT at a temp
                # directory outside the repo, and a diagnostic that raises while
                # explaining a missing file is a diagnostic nobody gets to read.
                "why": (f"{OUT} does not exist: the live monitor has never run, "
                        f"or its record was removed. This is not a pass."),
                "failed": [], "summary": None}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    if "--latest" in argv:
        print(json.dumps(latest(), indent=2, ensure_ascii=False))
        return 0
    write = "--no-record" not in argv
    extra = [a for a in argv if a not in ("--no-record",)]
    rec = run(write=write, extra=extra)
    print(rec.get("_stdout", ""))
    print(f"LIVE MONITOR {rec['status']}")
    print(f"  {rec['why']}")
    for f in rec["failed"]:
        print(f"  RED  {f}")
    if rec["summary"]:
        print(f"  summary: {rec['summary']}")
    print("  NOTE: this suite is ALLOWED to be red. It does not gate a commit.")
    if not write:
        print("  (--no-record: nothing written)")
    # EXIT 0 EVEN WHEN RED, on purpose: a non-zero exit invites someone to wire
    # this into CI as a gate, which is the thing ITEM 45 exists to undo.
    return 0


def selftest() -> int:
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    import tempfile
    global OUT
    real = OUT
    with tempfile.TemporaryDirectory() as td:
        OUT = pathlib.Path(td) / "nope.json"
        want(latest()["status"] == NEVER_RUN,
             "a missing record reads as NEVER_RUN, never as OK")
        want("not a pass" in latest()["why"],
             "and says so in words, so a reader cannot mistake it")
    OUT = real

    marked = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", MARKER, "--collect-only", "-q"],
        cwd=str(BASE), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    n = sum(1 for l in (marked.stdout or "").splitlines() if "::" in l)
    want(n > 0, f"the marker selects something ({n} test(s) carry it)", str(n))

    gate = (BASE / "tools" / "suite_gate.py").read_text(encoding="utf-8")
    want('"not live_state"' in gate,
         "and tools/suite_gate.py EXCLUDES exactly this marker — otherwise the "
         "two suites overlap and the split means nothing")

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         got {detail}")
    print("\n  integrations, in THIS repo:")
    print(f"    marked tests                 {n}")
    print(f"    memory/live_monitor_latest   "
          f"{'LIVE' if OUT.exists() else 'INERT — never run'}")
    print(f"    surfaced anywhere?           NO — the compass needle is ITEM 45 "
          f"step 2, held pending Kimi's ruling on what N of 4 means")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
