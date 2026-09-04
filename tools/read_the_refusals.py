#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/read_the_refusals.py — the reader, not another writer.

WHY THIS EXISTS (5 September 2026)
----------------------------------
Publishing to cortex-civilization-watch stopped after 2026-08-17T01:07:16Z and did not
resume until 31 August: thirteen nights with nothing published. The diagnosis assumed a
gate had refused SILENTLY.

It had not. memory/night_events.jsonl contained 26 github_publish refusal events
covering exactly that gap, each naming the gate and the reason. The mechanism worked
perfectly. Nobody opened the file.

So the fix is not more events. It is something that READS them and says, in one line,
"this gate has been refusing for N nights running". A streak is the unit that matters:
one refusal is a Tuesday, thirteen in a row is an outage.

  venv\\Scripts\\python.exe tools/read_the_refusals.py
  venv\\Scripts\\python.exe tools/read_the_refusals.py --json
  venv\\Scripts\\python.exe tools/read_the_refusals.py --min-streak 3 --since 2026-08-01
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
EVENTS = REPO / "memory" / "night_events.jsonl"

# A streak longer than this many consecutive nights is a finding, not a blip.
DEFAULT_MIN_STREAK = 2

# A refusal is recognised by its subject; the marker is the Bulgarian the cycle writes.
REFUSED = "ОТКАЗАНА"


def load(path: Path | None = None) -> list[dict]:
    """Every event, oldest first. A malformed line is COUNTED, never skipped quietly —
    silently dropping rows is the defect this tool exists to catch."""
    p = path or EVENTS
    rows, bad = [], 0
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            bad += 1
            continue
        if isinstance(d, dict):
            d["_malformed_seen"] = bad
            rows.append(d)
    if bad:
        print(f"[refusals] WARNING: {bad} malformed line(s) in {p.name} were not parsed",
              file=sys.stderr)
    return rows


def _step_of(subject: str) -> str:
    """'github_publish ОТКАЗАНА от нотариуса' -> 'github_publish'."""
    return (subject or "").split(REFUSED)[0].strip() or "?"


def _gate_of(ev: dict) -> str:
    """The gate that refused.

    `gate` is a first-class field only since 5 Sep 2026. Older rows carry it in the
    subject, so it is recovered rather than reported as unknown — a reader that cannot
    read its own history is not a reader.
    """
    g = ev.get("gate")
    if isinstance(g, str) and g.strip():
        return g
    subj = str(ev.get("subject") or "")
    if "нотариус" in subj:
        return "notary"
    if REFUSED in subj:
        return "metta_witness_or_older"
    return "unknown"


def refusals(rows: list[dict], since: str | None = None) -> list[dict]:
    out = []
    for ev in rows:
        if REFUSED not in str(ev.get("subject") or ""):
            continue
        ts = str(ev.get("ts") or "")
        day = ts[:10]
        if since and day < since:
            continue
        out.append({"day": day, "ts": ts, "step": _step_of(str(ev.get("subject"))),
                    "gate": _gate_of(ev), "detail": str(ev.get("detail") or "")})
    return out


def streaks(items: list[dict], min_streak: int = DEFAULT_MIN_STREAK) -> list[dict]:
    """Runs of CONSECUTIVE CALENDAR DAYS on which a (step, gate) refused.

    Consecutive days, not consecutive events: a night that refuses four times is one
    night, and a gap of one clear night ends the streak. That is what makes the number
    mean 'how long has this been broken'.
    """
    by_key: dict[tuple, set] = defaultdict(set)
    detail: dict[tuple, str] = {}
    for it in items:
        key = (it["step"], it["gate"])
        try:
            d = date.fromisoformat(it["day"])
        except ValueError:
            continue
        by_key[key].add(d)
        detail.setdefault(key + (it["day"],), it["detail"])

    found = []
    for (step, gate), days in by_key.items():
        run: list[date] = []
        for d in sorted(days) + [None]:
            if run and d is not None and d == run[-1] + timedelta(days=1):
                run.append(d)
                continue
            if len(run) > min_streak:
                found.append({
                    "step": step, "gate": gate,
                    "start": run[0].isoformat(), "end": run[-1].isoformat(),
                    "nights": len(run),
                    "reason": detail.get((step, gate, run[0].isoformat()), ""),
                })
            run = [d] if d is not None else []
    return sorted(found, key=lambda f: (-f["nights"], f["start"]))


def report(path: Path | None = None, since: str | None = None,
           min_streak: int = DEFAULT_MIN_STREAK) -> dict:
    rows = load(path)
    items = refusals(rows, since)
    by_gate: dict[str, int] = defaultdict(int)
    by_step: dict[str, int] = defaultdict(int)
    by_reason: dict[str, int] = defaultdict(int)
    for it in items:
        by_gate[it["gate"]] += 1
        by_step[it["step"]] += 1
        by_reason[it["detail"][:90]] += 1
    found = streaks(items, min_streak)
    return {
        "events_total": len(rows),
        "refusals_total": len(items),
        "date_range": [items[0]["day"], items[-1]["day"]] if items else None,
        "by_gate": dict(sorted(by_gate.items(), key=lambda kv: -kv[1])),
        "by_step": dict(sorted(by_step.items(), key=lambda kv: -kv[1])),
        "by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
        "min_streak_nights": min_streak,
        "streaks": found,
    }


def render(rec: dict) -> str:
    L = []
    L.append(f"events scanned   : {rec['events_total']}")
    L.append(f"refusals found   : {rec['refusals_total']}")
    if rec["date_range"]:
        L.append(f"covering         : {rec['date_range'][0]} .. {rec['date_range'][1]}")
    L.append("")
    if rec["by_gate"]:
        L.append("BY GATE")
        for g, n in rec["by_gate"].items():
            L.append(f"  {g:34s} {n:5d}")
        L.append("")
    if rec["by_step"]:
        L.append("BY STEP")
        for s, n in rec["by_step"].items():
            L.append(f"  {s:34s} {n:5d}")
        L.append("")
    if not rec["streaks"]:
        L.append(f"NO STREAK LONGER THAN {rec['min_streak_nights']} NIGHTS. "
                 f"Nothing has been refusing continuously.")
        return "\n".join(L)
    L.append(f"FINDINGS — refusal streaks longer than {rec['min_streak_nights']} nights")
    L.append("")
    for f in rec["streaks"]:
        L.append(f"  {f['step']} / {f['gate']}")
        L.append(f"      {f['nights']} consecutive nights, {f['start']} .. {f['end']}")
        L.append(f"      reason: {f['reason'][:150]}")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read the refusals nobody read.")
    ap.add_argument("--events", default=None, help="path to night_events.jsonl")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    ap.add_argument("--min-streak", type=int, default=DEFAULT_MIN_STREAK)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rec = report(Path(a.events) if a.events else None, a.since, a.min_streak)
    print(json.dumps(rec, ensure_ascii=False, indent=2) if a.json else render(rec))
    # A streak is a finding, and a finding should be visible to a script too.
    return 2 if rec["streaks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
