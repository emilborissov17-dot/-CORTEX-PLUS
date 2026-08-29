#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/phase_report.py — A PHASE MUST BE ABLE TO CONTRADICT ITS OWN STEPS.

WHAT THIS IS FOR
-----------------
config/cycle_phases.json says what each phase PROMISES to leave behind. This
module writes down what it actually left:

    memory/phase_reports/<cycle_id>/<PHASE>.json

The verdict is not a summary of whether the steps raised. Steps not raising is
the weakest possible evidence — the 17:05 cycle logged 29 truncated LLM answers
and every step "succeeded". A step that swallows its exception, writes nothing
and returns is indistinguishable from a step that worked, unless something
checks the artifact.

So the rule is deliberately asymmetric:

    A phase that promised a file and did not leave it is PARTIAL,
    EVEN IF NO STEP RAISED.

That is the whole point. The report is allowed to disagree with the steps, and
when it does, the report is the one telling the truth.

WHAT "WRITTEN DURING THIS PHASE" MEANS
---------------------------------------
Existing is not the same as belonging. output/cortex_scores_latest.json exists
right now and is from a cycle that died four hours ago. A promised file counts
only if its mtime is at or after the moment the phase started. A stale file is
reported present=true, written_during_phase=false, and the phase is PARTIAL.

LLM ATTRIBUTION
----------------
llm_calls is derived from memory/llm_provenance.jsonl by timestamp window, not
by instrumenting call sites. The ledger is already written on every call; asking
it "who answered between these two instants" needs no new bookkeeping and cannot
drift from reality the way a hand-maintained counter would.

    venv\\Scripts\\python.exe core/phase_report.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
PHASES_FILE = REPO / "config" / "cycle_phases.json"
PROVENANCE = REPO / "memory" / "llm_provenance.jsonl"

DONE, PARTIAL, FAILED = "DONE", "PARTIAL", "FAILED"

# A file written in the first instants of a phase can carry an mtime a fraction
# of a second BEFORE the phase's own start time: st_mtime and datetime.now() do
# not come from the same clock read, and the filesystem stamp is rounded.
# Measured on this machine, 20 Aug 2026, over five immediate writes:
#
#     mtime - started:  -0.000356  +0.000177  -0.000186  -0.000533  +0.000120
#
# The selftest caught this as a phase that had just written its artifact being
# reported as stale. Two seconds is enormous next to a half-millisecond skew and
# still tiny next to the gap between cycles (hours), so it cannot let a genuinely
# old file pass as fresh.
MTIME_TOLERANCE_SEC = 2.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def safe_cycle_dir(cycle_id: str) -> str:
    """A cycle_id is an ISO timestamp with colons and a '+' — not a directory
    name on Windows. Flatten it reversibly enough to stay recognisable."""
    return re.sub(r"[^0-9A-Za-z._-]", "_", cycle_id)


def load_phases(path: pathlib.Path | None = None) -> dict:
    return json.loads((path or PHASES_FILE).read_text(encoding="utf-8"))["phases"]


def _provenance_between(start: datetime, end: datetime,
                        provenance: pathlib.Path | None = None) -> dict[str, int]:
    """{backend: calls} for entries whose ts falls inside the window."""
    path = provenance or PROVENANCE
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            stamp = datetime.fromisoformat(record["ts"])
        except Exception:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if start <= stamp <= end:
            backend = str(record.get("backend") or "unknown")
            counts[backend] = counts.get(backend, 0) + 1
    return counts


def _symbolic_disagreements() -> list[dict]:
    """The metta column's objections, for the D_SCORE report. Fail-open."""
    try:
        from core.metta_parallel import for_phase_report
        return for_phase_report()
    except Exception:
        return []


class PhaseReport:
    """Records one phase and writes its report.

    Usage inside the runner:

        with PhaseReport("B_SENSE", cycle_id) as report:
            for step in ...:
                try:
                    run(step); report.step_ok(step)
                except Exception as exc:
                    report.step_failed(step, exc)
    """

    def __init__(self, phase: str, cycle_id: str,
                 base_dir: pathlib.Path | None = None,
                 phases_file: pathlib.Path | None = None,
                 provenance: pathlib.Path | None = None):
        self.phase = phase
        self.cycle_id = cycle_id
        self.base = pathlib.Path(base_dir) if base_dir else REPO
        self.provenance = provenance
        self.spec = load_phases(phases_file)[phase]
        self.started: datetime | None = None
        self.ended: datetime | None = None
        self.steps_run: list[str] = []
        self.steps_failed: list[dict] = []

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "PhaseReport":
        self.started = _now()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.step_failed("<phase aborted>", exc)
        self.finish()
        return False  # never swallow

    def step_ok(self, name: str) -> None:
        self.steps_run.append(name)

    def step_failed(self, name: str, exc: BaseException | str) -> None:
        # NOT append-always (ITEM 21c, 29 Aug 2026). core/phase_tracker.py calls
        # step_ok() from on_step(), which fires at beat() time — BEFORE the step
        # runs — so a failure ALWAYS arrives second, for a step already in
        # steps_run. Appending again would list it twice and make steps_run
        # disagree with itself. The failure corrects the record; it does not add
        # to it.
        if name not in self.steps_run:
            self.steps_run.append(name)
        self.steps_failed.append({
            "step": name,
            "error": f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException)
                     else str(exc),
        })

    # -- the part that can disagree with the steps -------------------------

    def produces_check(self) -> list[dict]:
        """Present? And written during THIS phase, not left over from before?"""
        assert self.started is not None, "produces_check before the phase started"
        rows = []
        for rel in self.spec["produces"]:
            path = self.base / rel
            present = path.exists()
            written = False
            mtime = None
            if present:
                stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                mtime = _iso(stamp)
                written = (self.started - stamp).total_seconds() <= MTIME_TOLERANCE_SEC
            rows.append({
                "path": rel,
                "present": present,
                "written_during_phase": written,
                "mtime": mtime,
            })
        return rows

    def verdict(self, checks: list[dict]) -> tuple[str, str]:
        promised = len(checks)
        fresh = [c for c in checks if c["written_during_phase"]]
        stale = [c for c in checks if c["present"] and not c["written_during_phase"]]
        absent = [c for c in checks if not c["present"]]

        # FAILED is reserved for a phase that BROKE: something raised and nothing
        # was produced. A phase where nothing raised is never FAILED, however
        # empty-handed it came back — that is PARTIAL, and the distinction
        # matters because the two need different responses. FAILED means read the
        # traceback; PARTIAL means a step returned quietly without doing its job,
        # which is the harder and more common defect.
        if self.steps_failed and not fresh:
            return FAILED, (
                f"{len(self.steps_failed)} step(s) failed and the phase produced none "
                f"of its {promised} promised artifact(s): "
                + ", ".join(f["step"] for f in self.steps_failed)
            )

        if not self.steps_failed and not stale and not absent:
            return DONE, f"all {promised} promised artifact(s) written by this phase"

        reasons = []
        if self.steps_failed:
            reasons.append(
                f"{len(self.steps_failed)} step(s) failed: "
                + ", ".join(f["step"] for f in self.steps_failed))
        if absent:
            reasons.append(
                "promised but never written: " + ", ".join(c["path"] for c in absent))
        if stale:
            reasons.append(
                "promised but only a stale copy from an earlier cycle: "
                + ", ".join(c["path"] for c in stale))
        return PARTIAL, "; ".join(reasons)

    def build(self) -> dict:
        assert self.started is not None
        self.ended = self.ended or _now()
        checks = self.produces_check()
        verdict, reason = self.verdict(checks)
        return {
            "phase": self.phase,
            "cycle_id": self.cycle_id,
            "started": _iso(self.started),
            "ended": _iso(self.ended),
            "seconds": round((self.ended - self.started).total_seconds(), 1),
            "steps_run": self.steps_run,
            "steps_failed": self.steps_failed,
            "produces_check": checks,
            "llm_calls": _provenance_between(self.started, self.ended, self.provenance),
            "verdict": verdict,
            "reason": reason,
            # D_SCORE is where the composite is born, so it is where the
            # symbolic column's objections belong. R3 caught auto_levels saying
            # LOW while goal_score said 81.85/100 for the same axis on the same
            # night; nothing in the cycle had been comparing them.
            **({"symbolic_disagreements": _symbolic_disagreements()}
               if self.phase == "D_SCORE" else {}),
        }

    def path(self) -> pathlib.Path:
        return (self.base / "memory" / "phase_reports" /
                safe_cycle_dir(self.cycle_id) / f"{self.phase}.json")

    def finish(self) -> dict:
        report = self.build()
        out = self.path()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"[PHASE] {self.phase}: {report['verdict']} — {report['reason']}")
        print(f"[PHASE] -> {out}")
        return report


# ---------------------------------------------------------------------------
# selftest — reports which integrations are LIVE and which are INERT here
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile

    print("core/phase_report.py --selftest")
    print(f"  config/cycle_phases.json : "
          f"{'LIVE' if PHASES_FILE.exists() else 'INERT (missing)'}")
    print(f"  memory/llm_provenance.jsonl : "
          f"{'LIVE' if PROVENANCE.exists() else 'INERT — llm_calls will be empty'}")

    phases = load_phases()
    print(f"  phases declared: {', '.join(phases)}")

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)

        # a phase that raises nothing and produces nothing must NOT be DONE
        with PhaseReport("F_SELF", "selftest-cycle", base_dir=base) as rep:
            rep.step_ok("self_modifier")
            rep.step_ok("execute_patches")
        quiet = json.loads(rep.path().read_text(encoding="utf-8"))
        print(f"  silent-but-empty phase -> {quiet['verdict']} "
              f"({'correct' if quiet['verdict'] != DONE else 'WRONG — reports success'})")

        # the same phase, having actually written its artifact
        target = base / "memory" / "improvement_proposals.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with PhaseReport("F_SELF", "selftest-cycle-2", base_dir=base) as rep2:
            rep2.step_ok("self_modifier")
            target.write_text("{}", encoding="utf-8")
            rep2.step_ok("execute_patches")
        good = json.loads(rep2.path().read_text(encoding="utf-8"))
        print(f"  phase that wrote it    -> {good['verdict']} "
              f"({'correct' if good['verdict'] == DONE else 'WRONG'})")

    ok = quiet["verdict"] == PARTIAL and good["verdict"] == DONE
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else _selftest())
