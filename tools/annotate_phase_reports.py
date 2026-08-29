#!/usr/bin/env python3
"""
tools/annotate_phase_reports.py — ITEM 29.

THE HISTORY CANNOT BE TRUSTED AND MUST NOT BE REWRITTEN.

ITEM 21 fixed the mechanism: fast_cycle_runner._run() now calls
core.phase_tracker.note_failure() when a step raises, and PhaseReport records it.
Before that fix, phase_tracker recorded step_ok() from on_step(), which fires at
beat() time — BEFORE the step does its work — and nothing ever called
step_failed() except "<phase aborted>" in __exit__.

So every phase report written before the fix carries steps_failed: [] because the
mechanism COULD NOT SAY OTHERWISE. That is not the same sentence as "nothing
failed", and 133 files on disk currently invite a reader to confuse the two.

WHY THIS APPENDS RATHER THAN EDITS. Rewriting 133 records to say something their
writer never knew would be inventing evidence — the precise failure the whole
queue exists to catch, committed while cleaning up after itself. The records stay
byte-identical; ONE annotation is appended beside them, and it is the annotation
that carries the warning.

The record is written to memory/phase_reports/_ANNOTATIONS.jsonl, in the same
directory as the reports, with a leading underscore so it sorts first for anyone
listing that folder. It is also summarised in docs/QUEUE.md under ITEM 29,
because memory/phase_reports/ is untracked and a fresh clone has neither the
reports nor this file.

DRY-RUN BY DEFAULT, per CLAUDE.md, and IDEMPOTENT: re-running never appends a
second copy of the same annotation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
REPORTS_DIR = BASE / "memory" / "phase_reports"
OUT = REPORTS_DIR / "_ANNOTATIONS.jsonl"
CYCLE_LOGS = BASE / "memory" / "cycle_logs"

ANNOTATION_ID = "ITEM29/phase_reports_could_not_report_failure"
FIX_COMMIT = "d6bf2f5"
FIX_ITEM = "ITEM 21(c)"

_FAILED = re.compile(r"\[FAST_CYCLE\] (\S+) -> FAILED:")


def survey(reports_dir: pathlib.Path | None = None) -> dict:
    """What the reports on disk actually say. Read-only."""
    d = reports_dir or REPORTS_DIR
    files = sorted(glob.glob(str(d / "*" / "*.json")))
    n = with_key = empty = named = 0
    verdicts: dict = {}
    phases: dict = {}
    mtimes: list = []
    for f in files:
        p = pathlib.Path(f)
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        n += 1
        mtimes.append(p.stat().st_mtime)
        verdicts[j.get("verdict")] = verdicts.get(j.get("verdict"), 0) + 1
        phases[j.get("phase")] = phases.get(j.get("phase"), 0) + 1
        if "steps_failed" in j:
            with_key += 1
            if j["steps_failed"] == []:
                empty += 1
            else:
                named += 1
    return {
        "reports": n,
        "with_steps_failed_key": with_key,
        "with_an_empty_steps_failed": empty,
        "naming_any_failed_step": named,
        "verdicts": verdicts,
        "phases": phases,
        "earliest": (dt.datetime.fromtimestamp(min(mtimes)).isoformat()
                     if mtimes else None),
        "latest": (dt.datetime.fromtimestamp(max(mtimes)).isoformat()
                   if mtimes else None),
    }


def failures_in_logs(since: str = "2026-08-21", logs_dir=None) -> dict:
    """What the LOGS recorded in the same window — the evidence that survives.

    This is the number that makes the annotation actionable: it shows a reader
    that re-derivation is possible, and how far the reports were from the truth.
    """
    d = logs_dir or CYCLE_LOGS
    cut = dt.date.fromisoformat(since)
    total = 0
    by_step: dict = {}
    logs = 0
    for f in sorted(glob.glob(str(d / "*.log"))):
        p = pathlib.Path(f)
        if dt.date.fromtimestamp(p.stat().st_mtime) < cut:
            continue
        logs += 1
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for step in _FAILED.findall(txt):
            total += 1
            by_step[step] = by_step.get(step, 0) + 1
    return {"logs_scanned": logs, "step_failures_found": total,
            "by_step": by_step, "marker": "[FAST_CYCLE] <step> -> FAILED:",
            "since": since}


def build(reports_dir=None, logs_dir=None) -> dict:
    s = survey(reports_dir)
    lg = failures_in_logs(logs_dir=logs_dir)
    return {
        "annotation_id": ANNOTATION_ID,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kind": "RETROACTIVE_ANNOTATION",
        "applies_to": ("every phase report in this directory written before "
                       f"{FIX_ITEM} landed in commit {FIX_COMMIT}"),
        "the_defect": (
            "core/phase_tracker.py recorded step_ok() from on_step(), which "
            "fires at beat() time — BEFORE the step runs — so steps_run meant "
            "'steps STARTED'. PhaseReport.step_failed() existed but had no live "
            "caller except '<phase aborted>' in __exit__, and "
            "fast_cycle_runner._run() caught step exceptions, printed them, told "
            "the contract, and never told the report."),
        "what_steps_failed_means_in_those_reports": (
            "'the report could not say otherwise'. It does NOT mean 'nothing "
            "failed'. The two sentences are different and every report before "
            "the fix supports only the first."),
        "reports_at_time_of_annotation": s,
        "evidence_that_survives": lg,
        "the_gap": (
            f"the logs record {lg['step_failures_found']} step failure(s) in the "
            f"same window in which {s['reports']} reports record 0"),
        "verdicts_now_unverifiable": (
            f"{s['verdicts'].get('DONE', 0)} reports read DONE. DONE was "
            f"reachable while a step had raised, because nothing could populate "
            f"steps_failed. Those verdicts are not evidence that their phase was "
            f"clean."),
        "instruction": (
            "Any past analysis resting on these reports is VOID and must be "
            "re-derived from memory/cycle_logs/*.log, not from the reports. "
            "Grep '[FAST_CYCLE] <step> -> FAILED:' and '[CONTRACT] <step>: "
            "RAISED'; both markers agreed at 3 on 2026-08-29."),
        "reports_were_not_rewritten": True,
        "why_not_rewritten": (
            "Editing 133 records to state something their writer never knew "
            "would be inventing evidence while cleaning up after a defect about "
            "invented evidence. They stay byte-identical; this record carries "
            "the warning."),
        "fixed_by": {"item": FIX_ITEM, "commit": FIX_COMMIT},
    }


def already_annotated(out: pathlib.Path | None = None) -> bool:
    p = out or OUT
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("annotation_id") == ANNOTATION_ID:
                return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
    return False


def digests(reports_dir=None) -> dict:
    d = reports_dir or REPORTS_DIR
    return {f: hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
            for f in sorted(glob.glob(str(d / "*" / "*.json")))}


def append(record: dict, write: bool = False, out=None) -> dict:
    p = out or OUT
    if already_annotated(p):
        return {"appended": False, "why": "this annotation is already on file",
                "path": str(p)}
    if write:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"appended": bool(write), "path": str(p),
            "why": None if write else "dry run — pass --write"}


def _selftest() -> int:
    import tempfile
    print("tools/annotate_phase_reports.py --selftest")
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'} {label}")
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        rd = root / "phase_reports"
        (rd / "cycleA").mkdir(parents=True)
        (rd / "cycleA" / "G_LEARN.json").write_text(json.dumps(
            {"phase": "G_LEARN", "verdict": "PARTIAL", "steps_failed": [],
             "steps_run": ["feedback_loop"]}), encoding="utf-8")
        (rd / "cycleA" / "B_SENSE.json").write_text(json.dumps(
            {"phase": "B_SENSE", "verdict": "DONE", "steps_failed": []}),
            encoding="utf-8")
        ld = root / "cycle_logs"
        ld.mkdir()
        (ld / "cycle_x.log").write_text(
            "[FAST_CYCLE] feedback_loop -> FAILED: TypeError: boom\n",
            encoding="utf-8")

        s = survey(rd)
        check("the survey counts the reports", s["reports"] == 2)
        check("and notices none names a failed step", s["naming_any_failed_step"] == 0)
        check("and counts the DONE verdicts that are now unverifiable",
              s["verdicts"].get("DONE") == 1)

        lg = failures_in_logs(since="2000-01-01", logs_dir=ld)
        check("the logs still hold what the reports lost",
              lg["step_failures_found"] == 1 and lg["by_step"] == {"feedback_loop": 1})

        rec = build(rd, ld)
        check("the record names the defect, not just the symptom",
              "beat() time" in rec["the_defect"])
        check("and says what steps_failed means in those files",
              "could not say otherwise" in rec["what_steps_failed_means_in_those_reports"])
        check("and voids past analysis",
              "VOID" in rec["instruction"])

        out = root / "_ANNOTATIONS.jsonl"
        before = digests(rd)
        check("a dry run writes nothing",
              append(rec, write=False, out=out)["appended"] is False and not out.exists())
        check("--write appends one line",
              append(rec, write=True, out=out)["appended"] is True
              and len(out.read_text(encoding="utf-8").splitlines()) == 1)
        check("a second run does not append a duplicate",
              append(build(rd, ld), write=True, out=out)["appended"] is False
              and len(out.read_text(encoding="utf-8").splitlines()) == 1)
        check("THE REPORTS ARE BYTE-IDENTICAL AFTERWARDS", digests(rd) == before)

    print(f"\n{'every check passed' if ok else 'SOMETHING FAILED'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="append the annotation to memory/phase_reports/_ANNOTATIONS.jsonl")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()

    before = digests()
    rec = build()
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    res = append(rec, write=a.write)
    print(f"\n-> {res['path']}  appended={res['appended']}"
          + (f"  ({res['why']})" if res["why"] else ""))
    after = digests()
    print(f"the {len(before)} phase reports are byte-identical: {before == after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
