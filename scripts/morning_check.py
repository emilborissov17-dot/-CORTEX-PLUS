#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/morning_check.py — the predictions made on 17 Aug 2026, checked by machine.

WHY THIS FILE EXISTS
--------------------
On 17 August 2026, before the night's run, four outcomes were predicted in a
conversation. A prediction a human has to remember to check is not a prediction — it
is a hope with a timestamp. The expectations are therefore embedded HERE, with the
date they were made, and the machine reads the evidence and says PASS or FAIL.

The four, AS DECLARED ON 2026-08-17, before the 17->18 Aug cycle ran:

  1. The cycle STARTS and FINISHES. The fail-closed notary refuses steps; a refusal
     skips a step, it does not abort the run. Verified against the 17 Aug run, where
     execute_patches was refused at 01:13 and the cycle finished at 01:37.

  2. EXACTLY THREE refusals — self_modifier, github_publish, execute_patches.
     Before 74eea3e only execute_patches was refused, and only because of a phantom
     filename. The flip (empty inputs -> UNKNOWN) should now catch the other two.
     Fewer than three means the flip did not bite. More than three means something
     else is being refused, and it must be named rather than averaged away.

  3. ZERO rows in brain_step_log.jsonl where prev_step == step. On 17 Aug this was
     53 of 53. Commit 15c5d8f captures the predecessor before the marker is
     overwritten. Any surviving row means the fix did not hold in the live runner.

  4. NO step died from a SystemExit or KeyboardInterrupt. 68 bare `except:` handlers
     were narrowed to `except Exception:` in 464f172, so a kill that used to be
     swallowed now propagates. That is intended — but if it kills a step, the step
     must be named, not discovered weeks later.

RULES THIS SCRIPT KEEPS
-----------------------
- An unperformed check is NOT a pass. A missing file prints MISSING with its path and
  counts as a failure of the run, never as a silent success.
- The raw evidence line is printed under every verdict. A verdict with no evidence is
  an assertion, and this whole file exists because assertions were being trusted.
- Read-only. No network, no writes, nothing mutated.

    venv\\Scripts\\python.exe scripts/morning_check.py            # last night
    venv\\Scripts\\python.exe scripts/morning_check.py 2026-08-17 # a named night
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DECLARED_ON = "2026-08-17"

# The first night these expectations can be true of. The commits they rest on —
# 74eea3e (fail-closed notary), 15c5d8f (predecessor capture), 464f172 (bare except)
# — all landed on 17 Aug, AFTER that night's 00:04 cycle had already run. Run against
# 2026-08-17 this script therefore reports criteria 2 and 3 as FAIL, correctly: it is
# measuring the state the fixes were written to change. That is a self-test, not a
# regression, and it is called out at the top of the output so nobody reads it as one.
FIRST_APPLICABLE_NIGHT = date(2026, 8, 18)

EXPECTED_REFUSALS = {"self_modifier", "github_publish", "execute_patches"}

NIGHT_EVENTS = REPO / "memory" / "night_events.jsonl"
EXISTENCE_LEDGER = REPO / "memory" / "existence_ledger.jsonl"
BRAIN_LOG = REPO / "memory" / "brain_step_log.jsonl"
CYCLE_LOGS = REPO / "memory" / "cycle_logs"

PASS, FAIL, MISSING = "PASS", "FAIL", "MISSING"


def _read_jsonl(path: Path):
    """(rows, error). error is not None if the file could not be read at all."""
    if not path.exists():
        return None, f"{MISSING}: {path.relative_to(REPO).as_posix()} does not exist"
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        return None, f"{MISSING}: {path.relative_to(REPO).as_posix()} unreadable ({e})"
    return rows, None


def _on_night(ts: str, night: date) -> bool:
    """A 'night' is that date plus the small hours of the next: the cycle starts at
    03:00 local, which is 00:00 UTC on the following day."""
    if not ts:
        return False
    day = str(ts)[:10]
    return day in (night.isoformat(), (night + timedelta(days=1)).isoformat())


# ---------------------------------------------------------------------------
# The four criteria
# ---------------------------------------------------------------------------

def check_1_cycle_started_and_finished(night: date) -> tuple:
    rows, err = _read_jsonl(EXISTENCE_LEDGER)
    if err:
        return MISSING, [err]
    ev = [r for r in rows if _on_night(r.get("ts", ""), night)
          and r.get("event") in ("CYCLE_STARTED", "CYCLE_FINISHED")]
    ev.sort(key=lambda r: r.get("ts", ""))
    evidence = [f"  {r['ts']}  {r['event']}"
                + (f"  duration_sec={r['duration_sec']}" if r.get("duration_sec") else "")
                for r in ev] or ["  (no CYCLE_STARTED / CYCLE_FINISHED for this night)"]
    started = any(r["event"] == "CYCLE_STARTED" for r in ev)
    finished = any(r["event"] == "CYCLE_FINISHED" for r in ev)
    if started and finished:
        return PASS, evidence
    why = ("never started" if not started else "STARTED but never FINISHED — a "
           "refusal must skip a step, not abort the cycle")
    return FAIL, evidence + [f"  -> {why}"]


def check_2_exactly_three_refusals(night: date) -> tuple:
    rows, err = _read_jsonl(NIGHT_EVENTS)
    if err:
        return MISSING, [err]
    ref = [r for r in rows if _on_night(r.get("ts", ""), night)
           and "нотариуса" in json.dumps(r, ensure_ascii=False)]
    named = set()
    evidence = []
    for r in ref:
        subj = str(r.get("subject", ""))
        step = subj.split(" ")[0] if subj else "?"
        named.add(step)
        evidence.append(f"  {r['ts']}  {subj}")
    if not evidence:
        evidence = ["  (no 'ОТКАЗАНА от нотариуса' events for this night)"]

    missing = EXPECTED_REFUSALS - named
    extra = named - EXPECTED_REFUSALS
    if named == EXPECTED_REFUSALS and len(ref) == 3:
        return PASS, evidence
    notes = []
    if missing:
        notes.append(f"  -> NOT refused, but expected to be: {sorted(missing)} "
                     f"— the fail-closed flip did not bite for these")
    if extra:
        notes.append(f"  -> refused but NOT expected: {sorted(extra)} — name it, "
                     f"do not average it away")
    if not missing and not extra and len(ref) != 3:
        notes.append(f"  -> right steps, but {len(ref)} refusal events, not 3")
    return FAIL, evidence + notes


def check_3_no_step_is_its_own_predecessor(night: date) -> tuple:
    rows, err = _read_jsonl(BRAIN_LOG)
    if err:
        return MISSING, [err]
    tonight = [r for r in rows if _on_night(r.get("ts", ""), night)]
    if not tonight:
        return FAIL, [f"  (no brain rows for this night in "
                      f"{BRAIN_LOG.relative_to(REPO).as_posix()}) "
                      f"-> nothing to check; an unperformed check is not a pass"]
    bad = [r for r in tonight if r.get("prev_step") is not None
           and r.get("prev_step") == r.get("step")]
    evidence = [f"  rows tonight: {len(tonight)} · prev_step == step: {len(bad)}"]
    evidence += [f"    {r['ts']}  step={r.get('step')!r} prev_step={r.get('prev_step')!r}"
                 for r in bad[:5]]
    if len(bad) > 5:
        evidence.append(f"    ... and {len(bad) - 5} more")
    if not bad:
        return PASS, evidence
    return FAIL, evidence + ["  -> 15c5d8f did not hold in the live runner"]


def check_4_no_swallowed_kill_became_a_death(night: date) -> tuple:
    evidence, found = [], []

    rows, err = _read_jsonl(NIGHT_EVENTS)
    if err:
        return MISSING, [err]
    for r in rows:
        blob = json.dumps(r, ensure_ascii=False)
        if _on_night(r.get("ts", ""), night) and \
                ("SystemExit" in blob or "KeyboardInterrupt" in blob):
            found.append(f"  {r['ts']}  {str(r.get('subject'))[:70]}")

    logs = sorted(CYCLE_LOGS.glob("cycle_*.log")) if CYCLE_LOGS.exists() else []
    tonight_logs = [p for p in logs
                    if _on_night(p.name.replace("cycle_", "")[:10], night)]
    if not tonight_logs:
        evidence.append(f"  {MISSING}: no cycle log for this night under "
                        f"{CYCLE_LOGS.relative_to(REPO).as_posix()}")
        return MISSING, evidence

    step = "?"
    for p in tonight_logs:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("[STEP] "):
                step = s.split("[STEP] ", 1)[1].strip()
            elif "SystemExit" in s or "KeyboardInterrupt" in s:
                found.append(f"  {p.name}  during step {step!r}: {s[:90]}")

    evidence.append(f"  scanned: {', '.join(p.name for p in tonight_logs)}")
    if not found:
        evidence.append("  no SystemExit / KeyboardInterrupt in the night's evidence")
        return PASS, evidence
    return FAIL, evidence + found[:8] + [
        "  -> a kill that used to be swallowed now propagates (464f172). That is "
        "intended, but the step above must be named and looked at."]


CHECKS = [
    ("1. cycle started AND finished", check_1_cycle_started_and_finished),
    ("2. exactly three notary refusals", check_2_exactly_three_refusals),
    ("3. no step is its own predecessor", check_3_no_step_is_its_own_predecessor),
    ("4. no swallowed kill became a death", check_4_no_swallowed_kill_became_a_death),
]


def main(argv) -> int:
    if len(argv) > 1:
        night = date.fromisoformat(argv[1])
    else:
        night = (datetime.now() - timedelta(days=1)).date()

    print(f"morning check — night of {night.isoformat()} "
          f"(expectations declared {DECLARED_ON}, before the run)")
    if night < FIRST_APPLICABLE_NIGHT:
        print(f"NOTE: this night predates {FIRST_APPLICABLE_NIGHT.isoformat()}, the "
              f"first night the fixes were in place.\n"
              f"      Criteria 2 and 3 are EXPECTED to fail here — that is the "
              f"self-test, not a regression.")
    print("=" * 78)

    verdicts = []
    for title, fn in CHECKS:
        verdict, evidence = fn(night)
        verdicts.append(verdict)
        print(f"\n[{verdict}] {title}")
        for line in evidence:
            print(line)

    print("\n" + "=" * 78)
    if all(v == PASS for v in verdicts):
        print("VERDICT: ALL FOUR AS PREDICTED")
        return 0
    n_fail = sum(1 for v in verdicts if v == FAIL)
    n_missing = sum(1 for v in verdicts if v == MISSING)
    parts = []
    if n_fail:
        parts.append(f"{n_fail} FAILED")
    if n_missing:
        parts.append(f"{n_missing} COULD NOT BE CHECKED (not a pass)")
    print(f"VERDICT: {' · '.join(parts)} — read the evidence above, do not re-run "
          f"and hope")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
