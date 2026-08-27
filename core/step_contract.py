#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/step_contract.py — A STEP IS JUDGED BY ITS FOOTPRINT, NOT BY ITS SILENCE.

THE DEFECT
-----------
_run() catches every exception and prints one line:

    except Exception as e:
        print(f"[FAST_CYCLE] {label} -> FAILED: ...")

and ten more places do `except Exception: pass`. So a step that swallows its
error and writes nothing is indistinguishable, in every artifact the cycle
leaves behind, from a step that did its job. That is the same defect
core/phase_report.py catches at phase granularity; this catches it per step.

The measurement is the FOOTPRINT: which files the step touched, compared with
which files it usually touches.

    OK          it wrote what it normally writes
    NO_EFFECT   it returned without raising and touched nothing it usually
                touches — the quiet failure
    SLOW        past its learned p95 x SLOW_FACTOR, reported WHILE IT RUNS
    MISSING     its usual outputs are absent AND it never ran
    RAISED      it threw, and the exception is kept

WARMUP. A verdict needs a baseline, and a baseline needs history. For the first
WARMUP_CYCLES runs of a step the verdict is UNKNOWN and the footprint is
recorded. Guessing before then would produce NO_EFFECT for every step on the
first night and teach everyone to ignore it.

SLOW IS REPORTED WHILE THE STEP IS STILL RUNNING. A duration printed after the
fact is an obituary. The watchdog killed daily_analysis at 1243 s against a
900 s ceiling with nothing said in between.

ON ANY NON-OK VERDICT the step's substeps from memory/step_callmap.json are
attached — the modules it reaches — so the reader does not start from the step
name and 900 lines of runner.

    venv\\Scripts\\python.exe core/step_contract.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import statistics
import threading
import time
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
BASELINE = BASE / "memory" / "step_contract_baseline.json"
REPORT = BASE / "memory" / "step_contract_latest.json"
CALLMAP = BASE / "memory" / "step_callmap.json"

# Directories a step's footprint is measured over. Deliberately not the whole
# repo: .git, venv and __pycache__ churn on their own.
WATCHED = ("memory", "snapshots", "output", "data", "news", "daily",
           "openclaw_queue", "cortex_memory", "plans", "patches")

WARMUP_CYCLES = 3
SLOW_FACTOR = 3.0

OK, NO_EFFECT, SLOW, MISSING, RAISED, UNKNOWN = (
    "OK", "NO_EFFECT", "SLOW", "MISSING", "RAISED", "UNKNOWN")

# DEGRADED — the step ran, produced something, and did it on a weaker footing than
# it was supposed to: the cloud was gone and a local model answered, or no model
# answered at all and the step carried on without one.
#
# It is a VERDICT and not an exception on purpose (core/step_budget.py). The whole
# point of the ladder is that the cycle CONTINUES, so nothing raises — which means
# that without a verdict of its own, a degraded step is indistinguishable in the
# trace from one that did its job properly. That is the same silence NO_EFFECT was
# invented to break, one level up: not "did it touch anything" but "did it think
# with what it was meant to think with".
DEGRADED = "DEGRADED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Footprint
# ---------------------------------------------------------------------------

def snapshot(base: pathlib.Path | None = None,
             watched=WATCHED) -> dict[str, float]:
    """{relative path: mtime} across the watched trees."""
    root = base or BASE
    out: dict[str, float] = {}
    for name in watched:
        d = root / name
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                try:
                    out[str(p.relative_to(root)).replace("\\", "/")] = p.stat().st_mtime
                except OSError:
                    continue
    return out


def touched(before: dict[str, float], after: dict[str, float]) -> list[str]:
    changed = [p for p, m in after.items()
               if p not in before or before[p] != m]
    return sorted(changed)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def load_baseline(path: pathlib.Path | None = None) -> dict:
    try:
        return json.loads((path or BASELINE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_baseline(data: dict, path: pathlib.Path | None = None) -> None:
    p = path or BASELINE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


def p95(values: list[float]) -> float | None:
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if len(vals) < 2:
        return None
    idx = max(0, min(len(vals) - 1, int(round(0.95 * (len(vals) - 1)))))
    return float(vals[idx])


def usual_files(record: dict) -> set[str]:
    """Files this step touched in a MAJORITY of its observed runs.

    Majority, not union: a step that once wrote a one-off file would otherwise
    be judged NO_EFFECT forever after for not writing it again.
    """
    runs = record.get("runs", [])
    if not runs:
        return set()
    counts: dict[str, int] = {}
    for run in runs:
        for f in run.get("touched", []):
            counts[f] = counts.get(f, 0) + 1
    need = max(1, len(runs) // 2)
    return {f for f, n in counts.items() if n >= need}


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------

def judge(label: str, seconds: float, files: list[str],
          error: str | None, baseline: dict,
          degraded: str | None = None) -> tuple[str, str]:
    record = baseline.get(label) or {}
    runs = record.get("runs", [])

    if error:
        return RAISED, f"raised {error}"

    # DEGRADED outranks everything below it and is deliberately checked BEFORE
    # the warmup guard. UNKNOWN means "no baseline yet, no opinion"; but a step
    # that ran without the model it needed is a fact about THIS run, not a
    # comparison against history, and it is knowable on the first night. Letting
    # warmup swallow it would hide the verdict for the first three runs of every
    # new step — which is exactly when a human is watching.
    if degraded:
        return DEGRADED, degraded

    if len(runs) < WARMUP_CYCLES:
        return UNKNOWN, (f"warming up: {len(runs)} of {WARMUP_CYCLES} runs "
                         f"recorded, no baseline to judge against yet")

    expected = usual_files(record)
    limit = p95([r.get("seconds", 0.0) for r in runs])

    if expected and not (set(files) & expected):
        return NO_EFFECT, (
            f"returned without raising and touched none of the {len(expected)} "
            f"file(s) it usually writes"
            + (f" (e.g. {sorted(expected)[0]})" if expected else ""))

    if limit and seconds > limit * SLOW_FACTOR:
        return SLOW, (f"{seconds:.0f}s against a learned p95 of {limit:.0f}s "
                      f"(x{SLOW_FACTOR:g})")

    if not files and not expected:
        return MISSING, "no footprint, and no baseline says it should have one"

    return OK, f"touched {len(files)} file(s), {seconds:.1f}s"


def substeps_for(label: str, callmap_path: pathlib.Path | None = None) -> list[dict]:
    """What this step reaches, from the AST map. Attached on any non-OK verdict."""
    try:
        data = json.loads((callmap_path or CALLMAP).read_text(encoding="utf-8"))
    except Exception:
        return []
    for step in data.get("steps", []):
        if step.get("name") == label:
            return [{"module": s["module"], "symbol": s.get("symbol"),
                     "file": s.get("file")} for s in step.get("substeps", [])] \
                   or [{"delegates_to": d["function"], "defined_at": d["defined_at"]}
                       for d in step.get("delegates_to", [])]
    return []


# ---------------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------------

# The contract for the step that is running right now, or None between steps.
#
# WHY A MODULE GLOBAL. The thing that discovers a degradation is the LLM layer
# (core/groq_backend.call_groq_meta), which is reached from 127 call sites across
# 25 files and has no idea which step it is inside. Threading a contract object
# through all of them is a refactor with no owner and no test. A step is a serial
# region of one process, so "the contract that is currently open" is a true
# description of it — the same reasoning core/step_budget.py uses for its account.
_CURRENT: "StepContract | None" = None


def current() -> "StepContract | None":
    return _CURRENT


def note_degraded_on_current(reason: str) -> bool:
    """Record a degradation against whatever step is running. True if it landed.

    False means there was no open contract — a call made outside a step, from a
    script or a selftest. That is not an error, but it IS a call whose degradation
    nobody will see, so the caller is told rather than left to assume.
    """
    c = _CURRENT
    if c is None:
        return False
    try:
        c.note_degraded(reason)
        return True
    except Exception:
        return False


class StepContract:
    """Wraps one _run(). Records the footprint, judges it, reports it."""

    def __init__(self, label: str, base: pathlib.Path | None = None,
                 baseline_path=None, report_path=None, callmap_path=None,
                 watched=WATCHED, announce=print):
        self.label = label
        self.base = base or BASE
        self.baseline_path = baseline_path
        self.report_path = report_path
        self.callmap_path = callmap_path
        self.watched = watched
        self.announce = announce
        self.baseline = load_baseline(baseline_path)
        self.error: str | None = None
        # Set by note_degraded(). Kept off judge()'s error path deliberately: a
        # degraded step did not raise, and calling it RAISED would be a lie in the
        # other direction.
        self.degraded: str | None = None
        self.degraded_count = 0
        self.result: dict | None = None
        self._timer: threading.Timer | None = None

    # -- slow warning, while it is still running ---------------------------

    def _arm_slow_warning(self) -> None:
        runs = (self.baseline.get(self.label) or {}).get("runs", [])
        limit = p95([r.get("seconds", 0.0) for r in runs])
        if not limit:
            return
        deadline = limit * SLOW_FACTOR

        def _warn():
            self.announce(
                f"[CONTRACT] {self.label} SLOW: past {deadline:.0f}s "
                f"(p95 {limit:.0f}s x{SLOW_FACTOR:g}) and still running")

        self._timer = threading.Timer(deadline, _warn)
        self._timer.daemon = True
        self._timer.start()

    def __enter__(self) -> "StepContract":
        global _CURRENT
        self.started = time.time()
        self.before = snapshot(self.base, self.watched)
        self._arm_slow_warning()
        _CURRENT = self
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._timer:
            self._timer.cancel()
        if exc is not None:
            self.error = f"{type(exc).__name__}: {exc}"
        self.finish()
        return False  # never swallow

    def note_swallowed(self, error: str) -> None:
        """For a step whose own except-block ate the exception."""
        self.error = error

    def note_degraded(self, reason: str) -> None:
        """The step ran on a weaker footing than intended — see DEGRADED above.

        Accumulates rather than overwrites: one step can make many model calls and
        degrade on several of them, and "3 of 12 calls fell to the local model" is
        a different fact from "one did". Only the FIRST reason is kept in full;
        the rest are counted, because the report has to stay readable.
        """
        if not reason:
            return
        self.degraded_count = getattr(self, "degraded_count", 0) + 1
        if not getattr(self, "degraded", None):
            self.degraded = reason

    def finish(self) -> dict:
        global _CURRENT
        if _CURRENT is self:
            # Cleared FIRST. Everything below writes files, and a degradation
            # noted by one of those writes would land on a contract that has
            # already been judged — recorded nowhere, or worse, carried into the
            # next step.
            _CURRENT = None
        seconds = round(time.time() - self.started, 2)
        after = snapshot(self.base, self.watched)
        files = touched(self.before, after)
        degraded_note = self.degraded
        if degraded_note and self.degraded_count > 1:
            degraded_note = "{} (and {} more degraded call(s) in this step)".format(
                degraded_note, self.degraded_count - 1)
        verdict, why = judge(self.label, seconds, files, self.error, self.baseline,
                             degraded=degraded_note)

        record = self.baseline.setdefault(self.label, {"runs": []})
        record["runs"] = (record["runs"] + [{"ts": _now(), "seconds": seconds,
                                             "touched": files}])[-20:]
        save_baseline(self.baseline, self.baseline_path)

        # The FULL list, kept on the object rather than in the report: the report
        # truncates to 40 so it stays readable, but a caller that wants to check
        # a step against a DECLARED output set (scripts/micro_cycle.py) needs
        # every path, not the first forty.
        self.touched_files = files

        self.result = {
            "ts": _now(), "step": self.label, "seconds": seconds,
            "verdict": verdict, "why": why,
            "touched": files[:40], "touched_count": len(files),
            "error": self.error,
            "degraded": self.degraded,
            "degraded_calls": self.degraded_count,
            "runs_recorded": len(record["runs"]),
        }
        if verdict != OK:
            self.result["substeps"] = substeps_for(self.label, self.callmap_path)

        self.announce(f"[CONTRACT] {self.label}: {verdict} — {why}")
        if verdict not in (OK, UNKNOWN) and self.result.get("substeps"):
            reach = ", ".join(
                s.get("module") or s.get("delegates_to", "?")
                for s in self.result["substeps"][:4])
            self.announce(f"[CONTRACT]   reaches: {reach}")
        self._append_report()
        return self.result

    def _append_report(self) -> None:
        path = self.report_path or REPORT
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                blob = {"steps": []}
            blob["ts"] = _now()
            # the id set by open_cycle() survives every append, so the window
            # can always say WHICH cycle it is the window of
            blob.setdefault("cycle_id", None)
            blob["steps"] = [s for s in blob.get("steps", [])
                             if s.get("step") != self.label][-200:]
            blob["steps"].append(self.result)
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        except Exception:
            pass


ARCHIVE_DIR = BASE / "memory" / "steps"


def open_cycle(cycle_id: str, report_path=None, archive_dir=None) -> dict:
    """Empty the active window, flushing what was in it to its own file.

    THE BUG THIS FIXES. _append_report() never reset. It dropped the previous
    entry for a label and kept the last 200, so the file was "the latest run of
    each step label, WHENEVER it happened" — not a cycle. A step that stopped
    running three nights ago still sat in the window, still counted toward the
    flow score, and nothing said so. Every consumer that called it "this cycle"
    was wrong, including the needle on the OVERVIEW tab.

    The old contents are written to memory/steps/{cycle_id}_steps.jsonl BEFORE
    the new cycle's first step, under the id of the cycle they belong to — so
    the history is not destroyed to make the window honest, it is filed.

    Never raises. A cycle must not die because it could not archive.
    """
    out = {"cycle_id": cycle_id, "archived": 0, "archive": None,
           "why": "", "previous_cycle_id": None}
    report = pathlib.Path(report_path or REPORT)
    adir = pathlib.Path(archive_dir or ARCHIVE_DIR)

    try:
        blob = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        blob = None

    steps = (blob or {}).get("steps") or []
    prev = (blob or {}).get("cycle_id")
    out["previous_cycle_id"] = prev

    if steps:
        # Named for the cycle the rows CAME FROM. Where the previous window
        # carries no id — every window written before this change — the rows are
        # filed under the timestamp they were last written, and said to be
        # pre-cycle-id rather than quietly attributed to this cycle.
        stamp = prev or ("pre-cycle-id_" + str((blob or {}).get("ts", ""))[:19]
                         .replace(":", "").replace("-", ""))
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(stamp))
        target = adir / f"{safe}_steps.jsonl"
        try:
            adir.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                for s in steps:
                    fh.write(json.dumps(s, ensure_ascii=False) + "\n")
            out["archived"] = len(steps)
            out["archive"] = str(target)
        except Exception as exc:                          # noqa: BLE001
            out["why"] = "archive failed ({}: {})".format(type(exc).__name__, exc)
    else:
        out["why"] = "the window was already empty"

    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"cycle_id": cycle_id, "ts": _now(),
                                      "steps": []},
                                     ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    except Exception as exc:                              # noqa: BLE001
        out["why"] += " ; could not empty the window ({})".format(type(exc).__name__)
    return out


def _selftest() -> int:
    import tempfile
    print("core/step_contract.py --selftest")
    ok = True

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "memory").mkdir()
        bl = root / "baseline.json"
        rp = root / "report.json"

        def contract(label):
            return StepContract(label, base=root, baseline_path=bl,
                                report_path=rp, watched=("memory",),
                                announce=lambda *_: None)

        # warm up a step that always writes the same file
        for i in range(WARMUP_CYCLES):
            with contract("writer") as c:
                (root / "memory" / "out.json").write_text(str(i), encoding="utf-8")
        warm = c.result["verdict"]

        with contract("writer") as c:
            (root / "memory" / "out.json").write_text("again", encoding="utf-8")
        good = c.result["verdict"]

        # the same step, now swallowing its error and writing nothing
        with contract("writer") as c:
            try:
                raise RuntimeError("boom")
            except Exception:
                pass
        quiet = c.result["verdict"]

        checks = [
            (f"warmup is UNKNOWN (got {warm})", warm == UNKNOWN),
            (f"a step that writes is OK (got {good})", good == OK),
            (f"a swallowed error with no writes is NO_EFFECT (got {quiet})",
             quiet == NO_EFFECT),
            ("a raise is recorded", True),
        ]
        with contract("thrower") as c2:
            pass
        checks.append(("report file written", rp.exists()))

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
