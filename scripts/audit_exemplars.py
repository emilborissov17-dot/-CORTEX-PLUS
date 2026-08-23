#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit_exemplars.py — WHAT WAS THE MODEL BEING FED, ALL ALONG?

THE QUESTION THE LIVE GATE CANNOT ANSWER
------------------------------------------
core/language_gate.py stops a contaminated exemplar being used TOMORROW. It says
nothing about what was already used, and the whole failure is that the system
was eating its own bad output for six days while every check it had was green.

So this walks the entire journal and asks, per kind: of the entries that WOULD
have been injected as few-shot exemplars, what fraction would today's gate
reject? Above 10 percent it prints FED_ON_DEAD_FOOD with the rate, because that
is the retrospective test — the one that catches drift which already passed
whatever gate existed at the time.

WOULD HAVE BEEN INJECTED, not "exists". _memory() reads the last 400 lines of
the journal and takes the n most recent of the requested kind. A kind that wrote
24 rows per cycle crowded that window and a kind that wrote one row a day was
often not in it at all, so "how much of this kind is dirty" and "how much of
what the model SAW was dirty" are different numbers. This computes the second
one, by replaying the window as it stood at each call.

IT WRITES ONE FILE AND MODIFIES NOTHING
-----------------------------------------
memory/exemplar_audit_latest.json, and its own report to stdout. No journal line
is read for anything but counting, and none is rewritten, reordered or removed.
The journal is append-only history; history that lied is still evidence, and it
is the only evidence this audit has.

    venv/Scripts/python.exe scripts/audit_exemplars.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import language_gate as lg   # noqa: E402

JOURNAL = BASE / "memory" / "brain_journal.jsonl"
OUT = BASE / "memory" / "exemplar_audit_latest.json"

# core/brain.py::_memory reads this many lines and shows this many entries.
WINDOW_LINES = 400
DEFAULT_N = 5

# Above this, the exemplar stream for that kind was mostly poison.
DEAD_FOOD_RATE = 0.10


def _rel(path) -> str:
    """Repo-relative where possible, absolute otherwise. Never raises.

    relative_to() throws for anything outside the repo, which is every path a
    test hands in — and an audit that crashes on an unfamiliar journal is an
    audit that cannot be run against a copy.
    """
    try:
        return str(pathlib.Path(path).relative_to(BASE))
    except ValueError:
        return str(path)


def _rows() -> list:
    try:
        lines = JOURNAL.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print("cannot read {}: {}".format(JOURNAL, exc))
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def replay(rows: list, n: int = DEFAULT_N, window: int = WINDOW_LINES) -> dict:
    """For every row, reconstruct the exemplar block _memory() would have built
    for that row's kind at that moment, and judge each exemplar in it.

    The row itself is EXCLUDED from its own block — _memory() runs before the
    answer it is prompting exists.
    """
    stats: dict = {}
    for i, row in enumerate(rows):
        kind = row.get("kind")
        if not kind:
            continue
        rec = stats.setdefault(kind, {
            "calls_replayed": 0, "exemplars_shown": 0, "exemplars_rejected": 0,
            "calls_with_a_rejected_exemplar": 0, "calls_with_no_exemplar": 0,
            "entries_total": 0, "entries_rejected": 0,
        })
        rec["entries_total"] += 1
        ok_self, _ = lg.entry_is_clean(row)
        if not ok_self:
            rec["entries_rejected"] += 1

        # The window as it stood immediately BEFORE this row was written.
        past = rows[max(0, i - window):i]
        shown, dirty = 0, 0
        for prior in reversed(past):
            if prior.get("kind") != kind:
                continue
            shown += 1
            ok, _reason = lg.entry_is_clean(prior)
            if not ok:
                dirty += 1
            if shown >= n:
                break

        rec["calls_replayed"] += 1
        rec["exemplars_shown"] += shown
        rec["exemplars_rejected"] += dirty
        if dirty:
            rec["calls_with_a_rejected_exemplar"] += 1
        if not shown:
            rec["calls_with_no_exemplar"] += 1

    for rec in stats.values():
        shown = rec["exemplars_shown"]
        rec["rejected_rate"] = (round(rec["exemplars_rejected"] / shown, 4)
                                if shown else 0.0)
        total = rec["entries_total"]
        rec["entry_rejected_rate"] = (round(rec["entries_rejected"] / total, 4)
                                      if total else 0.0)
        rec["fed_on_dead_food"] = rec["rejected_rate"] > DEAD_FOOD_RATE
    return stats


def first_contaminated(rows: list) -> dict:
    """Per kind, the timestamp of the first entry today's gate would reject.

    The date the ratchet started, per stream, recovered rather than remembered.
    """
    out = {}
    for row in rows:
        kind = row.get("kind")
        if not kind or kind in out:
            continue
        ok, reason = lg.entry_is_clean(row)
        if not ok:
            out[kind] = {"ts": row.get("ts"), "reason": reason}
    return out


def main() -> int:
    rows = _rows()
    print("scripts/audit_exemplars.py")
    print("  journal   {}".format(JOURNAL))
    print("  {} entr{} read; window={} lines, n={} exemplars per call".format(
        len(rows), "y" if len(rows) == 1 else "ies", WINDOW_LINES, DEFAULT_N))
    if not rows:
        return 1

    print("  gate layers:")
    for layer in lg.active_layers():
        print("    {:<22} {}".format(layer["layer"],
                                     "ON" if layer["active"] else "OFF"))
    print()

    stats = replay(rows)
    firsts = first_contaminated(rows)

    header = ("  {:<18} {:>6} {:>8} {:>9} {:>9}  {}".format(
        "kind", "calls", "shown", "rejected", "rate", "first contaminated"))
    print(header)
    print("  " + "-" * (len(header) - 2))
    dead = []
    for kind, rec in sorted(stats.items(), key=lambda kv: -kv[1]["rejected_rate"]):
        first = firsts.get(kind, {}).get("ts") or "-"
        print("  {:<18} {:>6} {:>8} {:>9} {:>8.0%}  {}".format(
            kind, rec["calls_replayed"], rec["exemplars_shown"],
            rec["exemplars_rejected"], rec["rejected_rate"], str(first)[:19]))
        if rec["fed_on_dead_food"]:
            dead.append((kind, rec["rejected_rate"]))

    print()
    if dead:
        for kind, rate in dead:
            print("FED_ON_DEAD_FOOD kind={} rate={:.2f}".format(kind, rate))
    else:
        print("  no kind is over the {:.0%} line".format(DEAD_FOOD_RATE))

    shown = sum(r["exemplars_shown"] for r in stats.values())
    bad = sum(r["exemplars_rejected"] for r in stats.values())
    print()
    print("  OVERALL: {} of {} exemplar injections would be rejected today "
          "({:.0%})".format(bad, shown, (bad / shown) if shown else 0.0))
    print("  This is what the model was actually shown, replayed call by call.")

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "journal": _rel(JOURNAL),
        "entries_read": len(rows),
        "window_lines": WINDOW_LINES,
        "exemplars_per_call": DEFAULT_N,
        "dead_food_rate_threshold": DEAD_FOOD_RATE,
        "gate_layers": lg.active_layers(),
        "by_kind": stats,
        "first_contaminated": firsts,
        "overall": {"exemplars_shown": shown, "exemplars_rejected": bad,
                    "rejected_rate": round((bad / shown) if shown else 0.0, 4)},
        "fed_on_dead_food": [k for k, _ in dead],
        "note": ("READ-ONLY AUDIT. No journal line was modified, reordered or "
                 "removed. The rates are what TODAY's gate says about what was "
                 "shown to the model at the time."),
    }
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print("  wrote {}".format(_rel(OUT)))
    except OSError as exc:
        print("  could not write {}: {}".format(OUT, exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
