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

REFUSED IS NOT PARTIAL (8 Sep 2026)
------------------------------------
The asymmetric rule above has exactly one exception. On 2026-09-08 at 01:35 the
notary refused self_modifier and capped execute_patches, so F_SELF ran no step
that was allowed to touch the disk - and the report graded it PARTIAL for
artifacts the gate had forbidden it to write. That is a false accusation:

    PARTIAL means a step RAN and silently failed to produce.
    REFUSED means the step was never allowed to run at all.

Conflating them turns a working containment gate into a nightly red square, and
a red square that is always red stops being read. So a promised artifact whose
DECLARED PRODUCER (core/cycle_map.produces) was refused or capped by a gate in
this phase is exempt from the mtime rule and reported refused_by_gate={...}.

The forbidden repair is the obvious one: a refused step must NOT write a
placeholder artifact to satisfy the check. Refusing correctly is a SUCCESS
state, and the report is what has to learn that - not the gate.

The exemption is narrow on purpose. It needs a refusal recorded for THIS phase
(PhaseReport.step_refused, wired from the runner's gate), and it covers only the
paths cycle_map says that particular step produces. A step that ran and wrote
nothing is still PARTIAL; an unrelated stale artifact is still PARTIAL.

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
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
PHASES_FILE = REPO / "config" / "cycle_phases.json"
PROVENANCE = REPO / "memory" / "llm_provenance.jsonl"

DONE, PARTIAL, FAILED = "DONE", "PARTIAL", "FAILED"

# Not a verdict - a per-artifact state, so a reader of produces_check can
# tell "the gate said no" apart from "nobody wrote it".
REFUSED = "REFUSED"

# How much of a gate's reason the verdict sentence carries. The notary's
# refusals are paragraphs; the reason line has to stay readable.
GATE_REASON_CHARS = 160

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


def _age_phrase(age_seconds) -> str:
    """'3.4 min' / '2.1 h' / '8.0 days', from the SAME number the report carries.

    It takes `age_seconds` rather than recomputing from the timestamp, so the
    prose and the field cannot drift apart — one computation, one truth.

    It no longer has a branch for a negative age. Earlier it rendered one as
    "5326.0s AFTER", which handled the defect instead of removing it; now
    produces_check emits null for anything not older than the phase, so a negative
    value cannot reach here. If one ever does, that is a bug upstream and this
    says so out loud rather than formatting it into something readable.

    Never raises: a reason string must not be able to break the report carrying it.
    """
    try:
        secs = float(age_seconds)
    except (TypeError, ValueError):
        return "age unknown"
    if secs < 0:
        return f"NEGATIVE AGE {secs:.1f}s — bug in produces_check"
    if secs < 3600:
        return f"{secs / 60:.1f} min"
    if secs < 86400:
        return f"{secs / 3600:.1f} h"
    return f"{secs / 86400:.1f} days"


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
        # Steps a gate REFUSED or CAPPED in this phase. Not failures: a refusal
        # is the containment working, and it must not read as a silent miss.
        self.steps_refused: list[dict] = []

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

    def step_refused(self, name: str, gate: str, reason: str) -> None:
        """A gate said no to this step. NOT a failure and NOT a success of the
        step - a success of the CONTAINMENT, which is a different thing and has
        to be recorded as one.

        Called from core.phase_tracker.note_refusal(), which the runner's
        _witness_or_refuse() calls at each of its three refusal returns. The
        step is left in steps_run (beat() already put it there: it was reached,
        it just was not permitted to act) and is deliberately NOT added to
        steps_failed, because nothing raised.

        Recording the same step twice is possible - the human-channel gate and
        the notary can both refuse in one pass - and harmless: the exemption is
        a set of paths, so the first refusal already covers them. The second is
        kept anyway, because a step refused by two gates is worth reading.
        """
        self.steps_refused.append({
            "step": name,
            "gate": str(gate),
            "reason": str(reason),
        })
        if name not in self.steps_run:
            self.steps_run.append(name)

    def refused_artifacts(self) -> dict:
        """{promised path -> the refusal that explains it}.

        THE NARROWNESS IS THE POINT. A refusal exempts only what cycle_map says
        THAT step produces, intersected with what THIS phase promised. It cannot
        launder a stale artifact belonging to some other step of the same phase:
        on 2026-09-08 F_SELF refused both its steps, so both its promises were
        covered - but E_PROPOSE refused nothing and stays graded in full.

        Fail-open on the import, and that is a real choice: if cycle_map cannot
        be read, NOTHING is exempt and the phase grades PARTIAL as it did
        before. A broken lookup must not be able to hand out exemptions.
        """
        if not self.steps_refused:
            return {}
        try:
            from core.cycle_map import produces as _declared
        except Exception as exc:  # noqa: BLE001
            print(f"[PHASE] {self.phase}: cycle_map unreadable, no refusal "
                  f"exemptions granted ({type(exc).__name__}: {exc})")
            return {}
        promised = set(self.spec["produces"])
        out: dict = {}
        for refusal in self.steps_refused:
            for rel in (_declared(refusal["step"]) or []):
                if rel in promised:
                    out.setdefault(rel, refusal)
        return out

    # -- the part that can disagree with the steps -------------------------

    def produces_check(self) -> list[dict]:
        """Present? And written during THIS PHASE — not during an earlier phase of
        this same cycle, and not on an earlier night. The two failures look alike
        in the artifact and are very different to diagnose, so the reason string
        names the phase and both timestamps rather than guessing which it was."""
        assert self.started is not None, "produces_check before the phase started"
        refused = self.refused_artifacts()
        rows = []
        for rel in self.spec["produces"]:
            path = self.base / rel
            present = path.exists()
            written = False
            mtime = None
            age_seconds = None
            if present:
                stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                mtime = _iso(stamp)
                gap = (self.started - stamp).total_seconds()
                written = gap <= MTIME_TOLERANCE_SEC
                # AGE IS NULL WHEN THE FILE IS NOT OLD (5 Sep 2026).
                # `gap` is negative for a file written AFTER the phase began —
                # which is the normal, healthy case — and a field called
                # `age_seconds` carrying -5326 is the same defect as a refusal
                # called a verdict: a name asserting something the number does not
                # mean. There is no "age" to report for an artifact this phase
                # produced, so the honest value is null, not a negative duration.
                # Every consumer must branch on `written_during_phase` first.
                if not written:
                    age_seconds = round(gap, 1)
            # THE EXEMPTION (8 Sep 2026). Non-null only when a gate refused the
            # step cycle_map names as this path's producer. A written artifact
            # is never marked refused: if the file arrived anyway, the refusal
            # is not what explains it and the row must not claim otherwise.
            refused_by = None if written else refused.get(rel)
            rows.append({
                "path": rel,
                "present": present,
                "written_during_phase": written,
                "mtime": mtime,
                # null unless the file predates this phase by more than the
                # tolerance; never negative, never zero-ish, never a guess.
                "age_seconds": age_seconds,
                "refused_by_gate": refused_by,
                "state": ("WRITTEN" if written else
                          REFUSED if refused_by else
                          "STALE" if present else "ABSENT"),
            })
        return rows

    def verdict(self, checks: list[dict]) -> tuple[str, str]:
        promised = len(checks)
        fresh = [c for c in checks if c["written_during_phase"]]
        # REFUSED COMES OUT FIRST (8 Sep 2026), before stale and absent are cut,
        # so an artifact the gate forbade cannot land in either bucket. Both
        # filters below therefore mean what their names say: `stale` is a file a
        # step was ALLOWED to write and left old, `absent` one it was ALLOWED to
        # write and never made.
        refused = [c for c in checks if c.get("refused_by_gate")]
        stale = [c for c in checks if c["present"] and not c["written_during_phase"]
                 and not c.get("refused_by_gate")]
        absent = [c for c in checks if not c["present"]
                  and not c.get("refused_by_gate")]

        def _refusal_clause() -> str:
            return "refused by the gate, not owed: " + "; ".join(
                f"{c['path']} ({c['refused_by_gate']['step']} refused by "
                f"{c['refused_by_gate']['gate']}: "
                f"{c['refused_by_gate']['reason'][:GATE_REASON_CHARS]})"
                for c in refused)

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
            # DONE WITH A REFUSAL IS STILL DONE. The phase owed nothing it did
            # not deliver: what it did not deliver, it was forbidden to. The
            # sentence has to say so out loud, because a bare "all N written"
            # over a night that wrote nothing would be the same lie in reverse.
            if refused:
                return DONE, (
                    f"{len(fresh)} of {promised} promised artifact(s) written by "
                    f"this phase; {len(refused)} " + _refusal_clause())
            return DONE, f"all {promised} promised artifact(s) written by this phase"

        reasons = []
        if refused:
            # Named even when something else went wrong, so a reader never has
            # to guess whether a missing artifact was forbidden or forgotten.
            reasons.append(f"{len(refused)} " + _refusal_clause())
        if self.steps_failed:
            reasons.append(
                f"{len(self.steps_failed)} step(s) failed: "
                + ", ".join(f["step"] for f in self.steps_failed))
        if absent:
            reasons.append(
                "promised but never written: " + ", ".join(c["path"] for c in absent))
        if stale:
            # SAY WHAT THE CHECK ACTUALLY TESTED (5 Sep 2026). This read "a stale
            # copy from an earlier CYCLE", and on 2026-09-05 F_SELF reported that
            # for memory/improvement_proposals.json whose mtime — 01:32:49Z — fell
            # squarely INSIDE that cycle's own window of 00:04:03Z..02:08:17Z. The
            # file was written by hyperclaw_plan in E_PROPOSE, one phase earlier.
            #
            # The check is right: `written_during_phase` compares against
            # self.started, the PHASE start, which is the correct contract. Only
            # the sentence was wrong, and it sent a reader hunting for a stale
            # artifact that does not exist. So the message now names the phase and
            # prints both timestamps, and a reader can see for themselves how far
            # before the phase the file was last written.
            reasons.append(
                "promised but last written BEFORE this phase began — "
                + "; ".join(
                    f"{c['path']} (mtime {c['mtime']}, {self.phase} began "
                    f"{_iso(self.started)}"
                    + (f", {_age_phrase(c['age_seconds'])} earlier)"
                       if c.get("age_seconds") is not None else ")")
                    for c in stale))
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
            # SEPARATE FROM steps_failed ON PURPOSE. Merging them would make a
            # night of correct containment indistinguishable from a night of
            # crashes in every downstream reader of these files.
            "steps_refused": self.steps_refused,
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

    # Run as a script, this file's directory is sys.path[0] and the repo root is
    # nowhere on it, so `core.cycle_map` would import-fail and the selftest would
    # report the refusal exemption INERT in a repo where it is live. Fixing the
    # path is the honest move; reporting a false INERT is the same class of lie
    # as reporting a false LIVE.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/phase_report.py --selftest")
    print(f"  config/cycle_phases.json : "
          f"{'LIVE' if PHASES_FILE.exists() else 'INERT (missing)'}")
    print(f"  memory/llm_provenance.jsonl : "
          f"{'LIVE' if PROVENANCE.exists() else 'INERT — llm_calls will be empty'}")

    # The refusal exemption needs BOTH halves in this repo: the table that says
    # which step produces what, and the runner gate that reports a refusal. If
    # either is missing the exemption is inert and phases go back to reporting
    # PARTIAL for artifacts a gate forbade — say so, rather than let a docstring
    # keep claiming a feature the repo cannot perform.
    try:
        from core.cycle_map import produces as _p
        print(f"  core/cycle_map.produces : LIVE "
              f"(self_modifier -> {_p('self_modifier')})")
    except Exception as exc:  # noqa: BLE001
        print(f"  core/cycle_map.produces : INERT ({type(exc).__name__}: {exc}) "
              f"— NO refusal exemptions can be granted")
    try:
        runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
        wired = runner.count("return _refused(")
        print(f"  gate -> phase report : "
              f"{'LIVE' if wired >= 3 else f'INERT — only {wired}/3 refusal exits wired'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  gate -> phase report : UNVERIFIED ({type(exc).__name__}: {exc})")

    phases = load_phases()
    print(f"  phases declared: {', '.join(phases)}")

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)

        # WHAT F_SELF PROMISES IS READ, NOT RETYPED (8 Sep 2026). This selftest
        # wrote one hardcoded artifact and had been printing "phase that wrote
        # it -> PARTIAL (WRONG)" since 2026-08-28, when G_LEARN's misattributed
        # files were moved and memory/development_journal.json joined F_SELF. The
        # positive control was failing for a reason that had nothing to do with
        # what it tests — which is exactly how a selftest stops being run.
        promised = phases["F_SELF"]["produces"]

        def _write_all():
            for rel in promised:
                path = base / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

        # a phase that raises nothing and produces nothing must NOT be DONE
        with PhaseReport("F_SELF", "selftest-cycle", base_dir=base) as rep:
            rep.step_ok("self_modifier")
            rep.step_ok("execute_patches")
        quiet = json.loads(rep.path().read_text(encoding="utf-8"))
        print(f"  silent-but-empty phase -> {quiet['verdict']} "
              f"({'correct' if quiet['verdict'] != DONE else 'WRONG — reports success'})")

        # the same phase, having actually written its artifacts
        with PhaseReport("F_SELF", "selftest-cycle-2", base_dir=base) as rep2:
            rep2.step_ok("self_modifier")
            _write_all()
            rep2.step_ok("execute_patches")
        good = json.loads(rep2.path().read_text(encoding="utf-8"))
        print(f"  phase that wrote it    -> {good['verdict']} "
              f"({'correct' if good['verdict'] == DONE else 'WRONG'})")

        # a phase whose step the gate REFUSED must NOT be graded PARTIAL for
        # the artifact it was never allowed to write (8 Sep 2026)
        import os
        old_t = (_now() - timedelta(hours=6)).timestamp()
        for rel in promised:
            os.utime(base / rel, (old_t, old_t))
        with PhaseReport("F_SELF", "selftest-cycle-3", base_dir=base) as rep3:
            rep3.step_refused("self_modifier", "notary", "capped at level_1")
            rep3.step_refused("execute_patches", "notary", "capped at level_1")
        gated = json.loads(rep3.path().read_text(encoding="utf-8"))
        print(f"  gate-refused phase     -> {gated['verdict']} "
              f"({'correct' if gated['verdict'] != PARTIAL else 'WRONG — blames the gate'})")

    ok = (quiet["verdict"] == PARTIAL and good["verdict"] == DONE
          and gated["verdict"] != PARTIAL)
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else _selftest())
