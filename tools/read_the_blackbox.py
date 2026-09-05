#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/read_the_blackbox.py — the night, in one committed page.

WHY THIS EXISTS (5 September 2026)
----------------------------------
core/blackbox.py was wired into the cycle on 4 Sep so a run that dies can say
where. It writes memory/blackbox.jsonl — which is **gitignored**. So the
recorder's output could not leave this machine, and a reader whose output nobody
can reach is the same as no reader. That is the same defect as
night_events.jsonl: thirteen nights of loud refusals into a file nobody opened.

The raw log stays ignored — it is per-machine, high-volume and rewritten every
night. What gets committed is the READING of it: claude/reports/NIGHT_<date>.md,
one page per night, small enough to read over coffee and durable enough to diff
against last week.

It folds in the two other readers, because these three are read together every
morning and a page that omitted them would send the reader back to the machine:

  * the blackbox      — step sequence, elapsed, the slowest three, how it exited
  * the phase reports — DONE / PARTIAL / FAILED, and what a PARTIAL promised
  * the refusals      — streaks longer than N nights, via read_the_refusals

  venv\\Scripts\\python.exe tools/read_the_blackbox.py
  venv\\Scripts\\python.exe tools/read_the_blackbox.py --date 2026-09-05 --stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BLACKBOX = REPO / "memory" / "blackbox.jsonl"
PHASE_DIR = REPO / "memory" / "phase_reports"


def load(path: Path) -> list:
    """Every row, oldest first. A malformed line is COUNTED, never dropped
    quietly — the defect these readers exist to catch."""
    rows, bad = [], 0
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            bad += 1
            continue
        if isinstance(d, dict):
            rows.append(d)
    if bad:
        print(f"[blackbox] WARNING: {bad} malformed line(s) not parsed",
              file=sys.stderr)
    return rows


def pick_run(rows: list, date: str | None) -> tuple:
    """The last cycle START on `date` (local), and every row of that pid after it.

    Keyed on pid AND start index, because a pid can be reused and because more
    than one cycle can run in a day — the 4 Sep log holds a `--from D_SCORE`
    attempt eight minutes before the real run.
    """
    starts = [(i, r) for i, r in enumerate(rows)
              if r.get("step") == "cycle" and r.get("phase") == "start"]
    if not starts:
        return None, []
    if date:
        def local_day(r):
            t = datetime.fromisoformat(str(r["utc"]).replace("Z", "+00:00"))
            return (t + _local_offset(t)).strftime("%Y-%m-%d")
        starts = [(i, r) for i, r in starts if local_day(r) == date] or starts
    idx, start = starts[-1]
    pid = start.get("pid")
    run = [r for r in rows[idx:] if r.get("pid") == pid]
    return start, run


def _local_offset(when: datetime) -> timedelta:
    """The machine's UTC offset. The cycle fires at 03:04 LOCAL, so a night is a
    local day; grouping by UTC would split it at 21:00."""
    return (datetime.fromtimestamp(when.timestamp())
            - datetime.fromtimestamp(when.timestamp(), tz=timezone.utc)
            .replace(tzinfo=None))


def analyse(run: list) -> dict:
    begins, steps = {}, []
    for r in run:
        if r.get("step") == "cycle":
            continue
        if r.get("phase") == "begin":
            begins[r["step"]] = r
        elif r.get("phase") == "end" and r["step"] in begins:
            b = begins.pop(r["step"])
            steps.append({"step": r["step"],
                          "at_s": b.get("elapsed_s", 0.0),
                          "secs": round(r.get("elapsed_s", 0) - b.get("elapsed_s", 0), 1),
                          "gpu_mib": r.get("gpu_mib"),
                          "rss_mb": r.get("rss_mb"),
                          "avail_mb": r.get("avail_mb")})
    exits = [r for r in run if r.get("step") == "cycle" and r.get("phase") == "exit"]
    return {"steps": steps,
            # THE HEADLINE. A begin with no end is where the cycle stopped, and
            # naming it is the entire reason the recorder was wired.
            "unclosed": [{"step": s, "at_s": b.get("elapsed_s"),
                          "rss_mb": b.get("rss_mb"), "avail_mb": b.get("avail_mb"),
                          "gpu_mib": b.get("gpu_mib")}
                         for s, b in begins.items()],
            "exit": exits[-1] if exits else None,
            "slowest": sorted(steps, key=lambda s: -s["secs"])[:3]}


def phases(cycle_id: str | None) -> list:
    if not cycle_id:
        return []
    safe = cycle_id.replace(":", "_").replace("+", "_")
    d = PHASE_DIR / safe
    if not d.is_dir():
        cands = sorted(PHASE_DIR.glob(safe[:19] + "*"))
        d = cands[-1] if cands else d
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:                                   # noqa: BLE001
            out.append({"phase": f.stem, "verdict": "UNREADABLE", "reason": str(e)})
    return out


def refusal_section(min_streak: int, since: str | None) -> dict:
    try:
        sys.path.insert(0, str(REPO))
        from tools.read_the_refusals import report
        return report(min_streak=min_streak, since=since)
    except Exception as e:                                       # noqa: BLE001
        # Named, not swallowed: a missing sub-reader must be visible in the page.
        return {"error": f"{type(e).__name__}: {e}"}


def render(date: str, start: dict | None, a: dict, phs: list, ref: dict) -> str:
    L = [f"# NIGHT {date}", ""]
    if start is None:
        L += ["**No cycle start recorded in memory/blackbox.jsonl for this date.**",
              "That is itself the finding: either the cycle did not run, or it died "
              "before the entry hook, or the recorder is not wired."]
        return "\n".join(L)

    ex = a["exit"]
    total = (ex or {}).get("elapsed_s")
    L += [f"- started `{start['utc']}` · pid `{start['pid']}`",
          f"- argv `{start.get('argv', '?')}`",
          (f"- exited `{ex['utc']}` after **{total / 60:.1f} min** — reason "
           f"`{ex.get('reason')}`" if ex else
           "- **NO EXIT LINE.** The process did not reach its atexit hook."),
          ""]

    # ── did it finish? ──────────────────────────────────────────────────────
    if a["unclosed"]:
        L += ["## IT STOPPED HERE", ""]
        for u in a["unclosed"]:
            L += [f"**`{u['step']}` began at {u['at_s'] / 60:.1f} min and never ended.**",
                  f"- RSS {u['rss_mb']} MB · system available {u['avail_mb']} MB "
                  f"· GPU {u['gpu_mib']} MiB at the moment it began", ""]
    else:
        L += ["## IT FINISHED", "",
              "Every `begin` has a matching `end`. The cycle did not have to say "
              "where it stopped, because it did not stop.", ""]

    L += [f"## STEPS — {len(a['steps'])} recorded", "",
          "| at (min) | step | secs | GPU MiB | RSS MB | avail MB |",
          "|---:|---|---:|---:|---:|---:|"]
    for s in a["steps"]:
        L.append(f"| {s['at_s'] / 60:.1f} | {s['step']} | {s['secs']:.1f} "
                 f"| {s['gpu_mib']} | {s['rss_mb']} | {s['avail_mb']} |")
    L += ["", "**Slowest three:** "
          + ", ".join(f"`{s['step']}` {s['secs'] / 60:.1f} min" for s in a["slowest"]),
          "", "> The blackbox records only steps wrapped in `_run()`. Steps whose "
          "bodies are inline in `main()` never emit a begin/end, so this table is a "
          "subset of the cycle, not the whole of it.", ""]

    # ── phases ──────────────────────────────────────────────────────────────
    if phs:
        L += ["## PHASES", "",
              "| phase | verdict | secs | steps run | failed |",
              "|---|---|---:|---:|---:|"]
        for p in phs:
            L.append(f"| {p.get('phase')} | **{p.get('verdict')}** "
                     f"| {p.get('seconds', 0):.1f} | {len(p.get('steps_run') or [])} "
                     f"| {len(p.get('steps_failed') or [])} |")
        bad = [p for p in phs if p.get("verdict") not in ("DONE", None)]
        if bad:
            L += ["", "### What the non-DONE phases promised and did not deliver", ""]
            for p in bad:
                L.append(f"**{p.get('phase')} — {p.get('verdict')}**")
                L.append(f"> {p.get('reason')}")
                for c in p.get("produces_check") or []:
                    if not c.get("written_during_phase"):
                        L.append(f"- `{c['path']}` present={c['present']} "
                                 f"mtime `{c.get('mtime')}`")
                L.append("")
        L.append("")

    # ── refusals ────────────────────────────────────────────────────────────
    L += ["## REFUSALS", ""]
    if ref.get("error"):
        L += [f"**The refusal reader could not run: {ref['error']}**", ""]
    else:
        L += [f"{ref['refusals_total']} refusal(s) in {ref['events_total']} events"
              + (f", covering {ref['date_range'][0]} .. {ref['date_range'][1]}"
                 if ref.get("date_range") else ""), ""]
        if ref.get("streaks"):
            L += [f"### Streaks longer than {ref['min_streak_nights']} nights", ""]
            for f in ref["streaks"]:
                L += [f"- **`{f['step']}` / {f['gate']} — {f['nights']} consecutive "
                      f"nights**, {f['start']} .. {f['end']}",
                      f"  > {f['reason'][:220]}"]
        else:
            L.append("No streak longer than "
                     f"{ref.get('min_streak_nights')} nights.")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Read the blackbox; write the night.")
    ap.add_argument("--blackbox", default=None)
    ap.add_argument("--date", default=None, help="local YYYY-MM-DD; default: latest run")
    ap.add_argument("--out", default=None, help="default claude/reports/NIGHT_<date>.md")
    ap.add_argument("--min-streak", type=int, default=2)
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    a = ap.parse_args()

    rows = load(Path(a.blackbox) if a.blackbox else BLACKBOX)
    start, run = pick_run(rows, a.date)
    analysis = analyse(run)
    cid = None
    if start:
        t = datetime.fromisoformat(str(start["utc"]).replace("Z", "+00:00"))
        date = (t + _local_offset(t)).strftime("%Y-%m-%d")
        cands = sorted(p.name for p in PHASE_DIR.glob(date + "T*")) if PHASE_DIR.is_dir() else []
        cid = cands[-1] if cands else None
    else:
        date = a.date or datetime.now().strftime("%Y-%m-%d")

    page = render(date, start, analysis, phases(cid),
                  refusal_section(a.min_streak, None))
    if a.stdout:
        print(page)
        return 0
    out = Path(a.out) if a.out else REPO / "claude" / "reports" / f"NIGHT_{date}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)} ({len(page)} bytes)")
    # A cycle that did not finish is a finding a script should be able to act on.
    return 2 if analysis["unclosed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
