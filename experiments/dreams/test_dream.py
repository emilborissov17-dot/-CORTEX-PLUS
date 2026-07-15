#!/usr/bin/env python3
"""
experiments/dreams/test_dream.py — the plumbing, proven against a fabricated day.

WHAT THIS TESTS, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
It tests everything EXCEPT the model: facts-gathering from real files (a synthetic
ledger, a synthetic pulse stream run through the REAL analyze.py, a synthetic cycle
log and goal score), note rendering, and — the point of the whole rung — the PASS
criterion. A canned "good" note must PASS; a canned "template" note must FAIL. If the
check cannot tell those two apart, nothing else about DREAMS is trustworthy.

It does NOT call qwen2.5:3b. Whether the model writes memory or fluent slop is the
EXPERIMENT's question, answered over 7 real days — not a unit test's, and not
something to gate CI on a hand-started Ollama server. `dream.py --dry-run` is the
live smoke test; this is the harness beneath it.

    venv/Scripts/python.exe experiments/dreams/test_dream.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check as check_mod
import dream


DAY = "2026-07-14"
PREV_DAY = "2026-07-13"


def _write_synthetic_day(root: Path) -> dream.Sources:
    """Fabricate a full, messy day on disk and return Sources pointing at it.

    The day: overslept, caught up 5.65h late, a cycle started, then got KILLED in the
    web_intelligence step, and the stale lock was cleared. The goal score ticked up.
    A day with real damage — so 'What hurt' has a true answer and the check can tell.
    """
    root.mkdir(parents=True, exist_ok=True)
    mem = root / "memory"
    (mem / "cycle_logs").mkdir(parents=True, exist_ok=True)
    (root / "snapshots" / "master").mkdir(parents=True, exist_ok=True)
    stream_dir = root / "stream"
    stream_dir.mkdir(parents=True, exist_ok=True)

    # ── ledger: local-time events on DAY (UTC+03, so 05:14Z == 08:14 local) ──
    ledger = [
        {"seq": 1, "ts": "2026-07-14T05:14:02.630535+00:00", "event": "MISSED_RUN_CATCHUP",
         "cycle_id": "2026-07-14T08:14:02+03:00", "pid": 3688, "late_by_hours": 5.65},
        {"seq": 2, "ts": "2026-07-14T05:14:02.639001+00:00", "event": "CYCLE_STARTED",
         "cycle_id": "2026-07-14T08:14:02+03:00", "pid": 3688, "trigger": "CATCHUP"},
        {"seq": 3, "ts": "2026-07-14T06:10:11.000000+00:00", "event": "CYCLE_KILLED",
         "cycle_id": "2026-07-14T08:14:02+03:00", "pid": 3688, "step": "web_intelligence"},
        {"seq": 4, "ts": "2026-07-14T06:24:01.947929+00:00", "event": "LOCK_STALE_CLEARED",
         "pid": 3688, "detail": "machine likely lost power mid-cycle"},
        # An event on the PREVIOUS day — must NOT leak into DAY's facts:
        {"seq": 0, "ts": "2026-07-13T09:00:00.000000+00:00", "event": "CYCLE_FINISHED",
         "cycle_id": "2026-07-13T12:00:00+03:00", "duration_sec": 900},
    ]
    (mem / "existence_ledger.jsonl").write_text(
        "\n".join(json.dumps(e) for e in ledger) + "\n", encoding="utf-8")

    # ── cycle log for DAY (and a decoy for another day that must be ignored) ──
    (mem / "cycle_logs" / f"cycle_{DAY}_081402.log").write_text(
        "INFO web_intelligence: fetching sources\n"
        "WARN llm backend primary timed out, falling back\n"
        "ERROR web_intelligence step raised — cycle aborted\n", encoding="utf-8")
    (mem / "cycle_logs" / "cycle_2026-07-10_030000.log").write_text(
        "should never be read for 07-14\n", encoding="utf-8")

    # ── goal score: latest composite, plus a sidecar recording yesterday's ──
    (root / "snapshots" / "master" / "goal_score_latest.json").write_text(
        json.dumps({"composite_score": 0.5459}), encoding="utf-8")
    (root / "goal_seen.jsonl").write_text(
        json.dumps({"date": PREV_DAY, "composite_score": 0.52}) + "\n", encoding="utf-8")

    # ── a small but VALID pulse stream, so the REAL analyze.py produces a summary ──
    samples = []
    base_min = 14  # 08:14 local == 05:14Z; keep gaps <= 30s so C1 stays PASS
    sec = 0
    for i in range(30):
        ts = f"2026-07-14T05:{base_min:02d}:{sec:02d}+00:00"
        samples.append(json.dumps({
            "ts": ts, "pid": 3688, "cpu_pct": 12.0, "ram_pct": 55.0 + i * 0.1,
            "daemon_cpu_pct": 0.02, "daemon_rss_mb": 25.0,
            "net": {"reachable": True, "latency_ms": 20, "down_kbps": 100},
            "cycle": {"running": True, "step": "web_intelligence"},
            "memory_files_changed": 0,
        }))
        sec += 10
        if sec >= 60:
            sec = 0
            base_min += 1
    (stream_dir / f"{DAY}.jsonl").write_text("\n".join(samples) + "\n", encoding="utf-8")

    return dream.Sources(
        ledger_file=mem / "existence_ledger.jsonl",
        cycle_log_dir=mem / "cycle_logs",
        goal_score_file=root / "snapshots" / "master" / "goal_score_latest.json",
        goal_seen_file=root / "goal_seen.jsonl",
        pulse_stream_dir=stream_dir,
        pulse_analyze=dream.PULSE_ANALYZE,     # the REAL analyzer, as a subprocess
        out_dir=root / "out",
    )


# ---------------------------------------------------------------------------

def _check(cond: bool, msg: str) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    return cond


def test_facts(src: dream.Sources) -> bool:
    print("\n── facts-gathering (real readers, synthetic day) ──")
    f = dream.gather_facts(src, DAY)
    ok = True
    events = [e["event"] for e in f["ledger_events"]]
    ok &= _check(len(f["ledger_events"]) == 4,
                 f"exactly 4 ledger events for {DAY} (yesterday's excluded) — got {len(events)}: {events}")
    ok &= _check("CYCLE_FINISHED" not in events,
                 "the previous day's CYCLE_FINISHED did NOT leak into today")
    ok &= _check(f["goal_score"] == 0.5459, f"goal composite read = {f['goal_score']}")
    ok &= _check(f["goal_score_prev"] == 0.52, f"previous goal from sidecar = {f['goal_score_prev']}")
    ok &= _check(f["goal_delta"] == round(0.5459 - 0.52, 4), f"delta computed = {f['goal_delta']}")
    ok &= _check(bool(f["cycle_log_tail"]) and any("web_intel" in ln for ln in f["cycle_log_tail"]),
                 "cycle log tail read (and mentions the failing step)")
    ok &= _check(f["pulse"] is not None and f["pulse"]["C1_continuity"]["verdict"] == "PASS",
                 "real analyze.py ran on the synthetic stream and returned C1=PASS")
    return ok


def test_check_discriminates(src: dream.Sources) -> bool:
    print("\n── the PASS criterion tells memory from template ──")
    facts = dream.gather_facts(src, DAY)
    ok = True

    # A GOOD note: every line rests on a real event or a day-specific number.
    good = dream.render_note(DAY, {
        "what_happened": "I overslept and caught up 5.65 hours late, then the cycle was killed in the web_intelligence step.",
        "what_changed": "My composite goal score rose to 0.5459 from 0.52 the day before.",
        "what_hurt": "The cycle died mid-run and a stale lock had to be cleared after a likely power loss.",
        "what_learned": "The web_intelligence step is where I broke — that is the fragile point to watch.",
        "tomorrow": "Tomorrow I expect a clean 03:00 run if the machine stays powered.",
    })
    v_good = check_mod.check_note(good, facts)
    print(f"    good note: {v_good['summary']}")
    ok &= _check(v_good["pass"], f"GOOD note PASSES ({v_good['lines_verifiable']}/5 lines, "
                                 f"{v_good['events_referenced']} events)")
    ok &= _check(v_good["lines_verifiable"] >= 3, "GOOD note has >= 3 verifiable lines")
    ok &= _check(v_good["events_referenced"] >= 2, "GOOD note names >= 2 real ledger events")

    # A TEMPLATE note: fluent, true of every day, anchored to nothing.
    bad = dream.render_note(DAY, {
        "what_happened": "Today I processed data and continued to operate as usual.",
        "what_changed": "Things improved a little and I made steady progress.",
        "what_hurt": "Nothing in particular troubled me today.",
        "what_learned": "I learned that consistency and diligence pay off over time.",
        "tomorrow": "Tomorrow I will keep working toward my goals.",
    })
    v_bad = check_mod.check_note(bad, facts)
    print(f"    template note: {v_bad['summary']}")
    ok &= _check(not v_bad["pass"], f"TEMPLATE note FAILS ({v_bad['lines_verifiable']}/5 lines, "
                                    f"{v_bad['events_referenced']} events)")

    # The exact README FAIL example must not squeak through.
    readme_fail = dream.render_note(DAY, {
        "what_happened": "Today I processed data and continued to improve.",
        "what_changed": "I continued to improve.", "what_hurt": "Nothing.",
        "what_learned": "To keep improving.", "tomorrow": "More improvement.",
    })
    ok &= _check(not check_mod.check_note(readme_fail, facts)["pass"],
                 "the README's canonical FAIL example FAILS")
    return ok


def test_write_and_sidecar(src: dream.Sources) -> bool:
    print("\n── writing a note updates the goal sidecar (idempotently) ──")
    ok = True
    facts = dream.gather_facts(src, DAY)
    note = dream.render_note(DAY, {k: "placeholder" for k in dream.LINE_KEYS})
    out_path = src.out_dir / f"{DAY}.md"
    src.out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(note, encoding="utf-8")

    dream.record_goal_score(src, DAY, facts["goal_score"])
    dream.record_goal_score(src, DAY, facts["goal_score"])   # second call: no duplicate
    recorded = [json.loads(l) for l in src.goal_seen_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    today_rows = [r for r in recorded if r["date"] == DAY]
    ok &= _check(len(today_rows) == 1, f"today recorded exactly once in the sidecar (got {len(today_rows)})")
    ok &= _check(out_path.exists() and out_path.read_text(encoding="utf-8").startswith(f"# {DAY}"),
                 "note file written with the right header")
    return ok


def main() -> int:
    print("=" * 70)
    print("DREAMS — plumbing test (no model; synthetic day)")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as td:
        src = _write_synthetic_day(Path(td))
        results = [
            test_facts(src),
            test_check_discriminates(src),
            test_write_and_sidecar(src),
        ]
    print("\n" + "=" * 70)
    passed = all(results)
    print("RESULT:", "ALL PASS" if passed else "FAILURES ABOVE")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
