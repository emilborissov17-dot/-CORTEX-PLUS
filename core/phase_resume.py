#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/phase_resume.py — REFUSE TO RESUME ON EVIDENCE THAT IS NOT THERE.

WHAT THIS IS
-------------
The gate behind `fast_cycle_runner.py --only <PHASE>` and `--from <PHASE>`.

Resuming mid-cycle is only meaningful if the earlier phases really did leave
their work behind. --from D_SCORE means "the snapshots are already on disk".
If they are not, scoring will run anyway, read whatever it finds, and produce a
composite out of last night's numbers — with today's timestamp on it. That is
worse than not resuming at all, because the output looks current.

So the gate checks two things for every file a phase requires:

    EXISTS      — the artifact is on disk at all
    BELONGS     — it was written by THIS cycle, not left over from another

and REFUSES if anything is missing, naming the file. It does not guess, does
not substitute a default, and does not run a partial phase.

BELONGING IS THE HALF THAT MATTERS
-----------------------------------
Every one of these files exists right now. output/cortex_scores_latest.json is
from a cycle that died hours ago; snapshots/master/master_snapshot_latest.json
is older still. An existence check alone would wave all of that through. A file
belongs to this cycle if it was written at or after the cycle began, or if it
carries the cycle_id inside it.

    venv\\Scripts\\python.exe core/phase_resume.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

# Run as `python core/phase_resume.py` and the repo root is NOT on sys.path, so
# `from core.phase_report import ...` fails with ModuleNotFoundError. The
# docstring above tells an operator to run exactly that, so the docstring has to
# be true. (Caught by running the documented command instead of assuming it.)
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.phase_report import MTIME_TOLERANCE_SEC, REPO, load_phases  # noqa: E402

ONLY, FROM = "only", "from"


class ResumeRefused(RuntimeError):
    """Raised instead of starting a phase whose evidence is not on disk."""


def phase_names(phases_file: pathlib.Path | None = None) -> list[str]:
    return list(load_phases(phases_file))


def resolve_phase(name: str, phases_file: pathlib.Path | None = None) -> str:
    names = phase_names(phases_file)
    if name not in names:
        raise ResumeRefused(
            f"unknown phase {name!r}. The cycle has: {', '.join(names)}")
    return name


def selected_phases(mode: str, phase: str,
                    phases_file: pathlib.Path | None = None) -> list[str]:
    """--only runs one phase. --from runs it and everything after it."""
    names = phase_names(phases_file)
    resolve_phase(phase, phases_file)
    if mode == ONLY:
        return [phase]
    return names[names.index(phase):]


def _belongs_to_cycle(path: pathlib.Path, cycle_id: str,
                      cycle_started: datetime | None) -> tuple[bool, str]:
    """Was this file written by THIS cycle? Returns (verdict, evidence)."""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    # The strongest evidence: the file says so itself.
    try:
        if path.suffix == ".json":
            blob = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(blob, dict):
                for key in ("cycle_id", "cycleId", "cycle"):
                    if str(blob.get(key) or "") == cycle_id:
                        return True, f"carries cycle_id {cycle_id}"
    except Exception:
        pass  # unreadable or not an object — fall through to the clock

    if cycle_started is None:
        return True, f"mtime {stamp.isoformat()} (no cycle start to compare against)"

    fresh = (cycle_started - stamp).total_seconds() <= MTIME_TOLERANCE_SEC
    return fresh, f"mtime {stamp.isoformat()}"


def check_requires(phase: str, cycle_id: str,
                   cycle_started: datetime | None = None,
                   base_dir: pathlib.Path | None = None,
                   phases_file: pathlib.Path | None = None) -> list[dict]:
    """One row per required file. Nothing is raised here — the caller decides."""
    base = pathlib.Path(base_dir) if base_dir else REPO
    rows = []
    for rel in load_phases(phases_file)[phase]["requires"]:
        path = base / rel
        if not path.exists():
            rows.append({"path": rel, "ok": False, "present": False,
                         "reason": "does not exist"})
            continue
        belongs, evidence = _belongs_to_cycle(path, cycle_id, cycle_started)
        rows.append({
            "path": rel,
            "ok": belongs,
            "present": True,
            "reason": "ok" if belongs
                      else f"exists but belongs to an earlier cycle ({evidence})",
        })
    return rows


def verify_or_refuse(mode: str, phase: str, cycle_id: str,
                     cycle_started: datetime | None = None,
                     base_dir: pathlib.Path | None = None,
                     phases_file: pathlib.Path | None = None) -> list[str]:
    """Returns the phases to run, or raises ResumeRefused naming what is missing.

    --only checks nothing: running one phase on purpose is the operator's call,
    and they can see what it needs. --from is the dangerous one, because it
    claims everything before it already happened.
    """
    phases = selected_phases(mode, phase, phases_file)
    if mode == ONLY:
        return phases

    rows = check_requires(phase, cycle_id, cycle_started, base_dir, phases_file)
    bad = [r for r in rows if not r["ok"]]
    if bad:
        lines = "\n".join(f"    {r['path']}  —  {r['reason']}" for r in bad)
        raise ResumeRefused(
            f"REFUSING --from {phase}.\n"
            f"  {len(bad)} of {len(rows)} required artifact(s) are not available "
            f"for cycle {cycle_id}:\n{lines}\n"
            f"  --from {phase} asserts that everything before it already ran. It "
            f"did not.\n"
            f"  Running anyway would read whatever is on disk — in most cases last "
            f"night's numbers — and stamp today's date on the result.\n"
            f"  Run the earlier phases, or start a full cycle."
        )
    return phases


def _selftest() -> int:
    import tempfile

    print("core/phase_resume.py --selftest")
    print(f"  config/cycle_phases.json : LIVE ({len(phase_names())} phases)")

    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        started = datetime.now(timezone.utc)

        try:
            verify_or_refuse(FROM, "D_SCORE", "cid", started, base_dir=base)
            print("  empty repo, --from D_SCORE -> ALLOWED (WRONG)")
            ok = False
        except ResumeRefused as exc:
            named = "economy_work_snapshot_latest.json" in str(exc)
            print(f"  empty repo, --from D_SCORE -> REFUSED "
                  f"({'names the file' if named else 'DOES NOT NAME THE FILE'})")
            ok = ok and named

        for rel in load_phases()["D_SCORE"]["requires"]:
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}", encoding="utf-8")
        try:
            phases = verify_or_refuse(FROM, "D_SCORE", "cid", started, base_dir=base)
            print(f"  requires satisfied        -> ALLOWED, runs {len(phases)} phases")
        except ResumeRefused as exc:
            print(f"  requires satisfied        -> REFUSED (WRONG): {exc}")
            ok = False

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
