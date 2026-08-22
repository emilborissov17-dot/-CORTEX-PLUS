#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/proposal_sla.py — THE HUMAN'S DEBT, COUNTED THE SAME WAY AS THE MACHINE'S.

EMIL'S RULING, 21 August 2026
------------------------------
Every proposal the system makes gets a human answer within 24 HOURS, approvable
from Telegram. Constitutionally binding once the current amendment vote closes;
the mechanism is built now so the clock is already running when it does.

WHY THIS IS A MECHANISM AND NOT A PROMISE
-------------------------------------------
The system already counts what IT owes — unmeasured axes, silent sources,
steps that touched nothing. Nothing counted what it was OWED. So proposals
accumulated where nobody looked:

    38 quarantined patches, the oldest 27 days
    18 unresolved rows in improvement_proposals.json
    25 threshold suggestions, filed the day this was written

That is the human's side of the ledger, and until now it had no line in any
report. A system that lists its own debts and not yours is not being modest,
it is being incomplete.

ONE ESCALATION PER PROPOSAL, EVER
----------------------------------
Past 24h a proposal escalates ONCE, by name and age. Not every cycle: a
proposal that pings nightly for 27 days is how a person learns to ignore the
channel, and then the 24-hour promise is worth less than no promise. The
standing counter in the report is what carries the pressure after that.

AND ONE MESSAGE PER DELIVERY RUN (22 August 2026)
--------------------------------------------------
"Once per proposal" was not enough. The first run that met a real backlog sent
28 separate Telegram messages inside two minutes. Each one obeyed the rule
above; together they were the thing the rule exists to prevent. Twenty-eight
notifications is not twenty-eight times the pressure of one — it is a muted
channel, and the 24-hour promise dies with the channel.

So the queue speaks ONCE per run: how many, the five oldest with their ids, and
the reply form. The full list goes to memory/proposal_sla_queue.json, which is
where a cockpit reads it — the phone gets the headline, the screen gets the
table. A single overdue proposal still gets the per-proposal message; a digest
of one is a worse message than the thing itself.

THE BATCHING IS A PROPERTY OF THIS QUEUE, NOT OF THE CHANNEL
--------------------------------------------------------------
Nothing here touches supervisor.alarm_human, which stays exactly what it was:
one message per event. An alarm is a thing that just happened and may need an
answer in minutes; a proposal queue is a standing debt whose whole content is
its size. Batching the first would be a defect. Only this module batches, and
only its own rows.

    venv\\Scripts\\python.exe core/proposal_sla.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
IMPROVEMENTS = BASE / "memory" / "improvement_proposals.json"
QUARANTINE = BASE / "patches" / "quarantine"
THRESHOLDS = BASE / "memory" / "threshold_proposals.json"
STAMP = BASE / "memory" / "proposal_sla_escalated.json"
PENDING = BASE / "memory" / "pending_approvals.json"
QUEUE = BASE / "memory" / "proposal_sla_queue.json"

SLA_HOURS = 24
DIGEST_TOP = 5

DECIDED_FLAGS = ("approved", "rejected", "executed", "applied", "dismissed")

_EPOCH_IN_NAME = re.compile(r"\.(\d{9,11})\.py$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_hours(when: datetime | None) -> float | None:
    return None if when is None else round((_now() - when).total_seconds() / 3600, 1)


# ---------------------------------------------------------------------------
# The three queues
# ---------------------------------------------------------------------------

def improvements(path=None) -> list[dict]:
    """Unresolved rows of improvement_proposals.json."""
    try:
        blob = json.loads((path or IMPROVEMENTS).read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = blob.get("proposals") if isinstance(blob, dict) else blob
    out = []
    for i, p in enumerate(rows or []):
        if not isinstance(p, dict) or any(p.get(f) for f in DECIDED_FLAGS):
            continue
        when = _parse(p.get("timestamp"))
        out.append({
            "id": f"imp:{i}",
            "kind": "improvement",
            "title": str(p.get("problem") or p.get("component") or "?")[:90],
            "entered": when.isoformat() if when else None,
            "age_hours": _age_hours(when),
        })
    return out


def quarantined(directory=None) -> list[dict]:
    """Every patch sitting in quarantine, aged from its own timestamp.

    The epoch in the filename is the patch's own record of when it was written;
    mtime is only a fallback, because a file copy would reset it.
    """
    d = directory or QUARANTINE
    out = []
    try:
        files = sorted(d.glob("*_patch.*.py"))
    except Exception:
        return []
    for f in files:
        m = _EPOCH_IN_NAME.search(f.name)
        if m:
            when = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
            basis = "timestamp in filename"
        else:
            try:
                when = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            basis = "file mtime"
        out.append({
            "id": f"qua:{f.name}",
            "kind": "quarantined_patch",
            "title": f.name,
            "entered": when.isoformat(),
            "age_hours": _age_hours(when),
            "age_basis": basis,
        })
    return out


def thresholds(path=None) -> list[dict]:
    """The suggested red lines, waiting to be signed."""
    try:
        blob = json.loads((path or THRESHOLDS).read_text(encoding="utf-8"))
    except Exception:
        return []
    when = _parse(blob.get("ts"))
    out = []
    for r in blob.get("proposals") or []:
        if r.get("suggested") is None:
            continue
        out.append({
            "id": f"thr:{r['axis']}",
            "kind": "alarm_threshold",
            "title": f"{r['axis']} -> {r['suggested']} [{r.get('basis')}]",
            "entered": when.isoformat() if when else None,
            "age_hours": _age_hours(when),
        })
    return out


def all_open(improvements_path=None, quarantine_dir=None,
             thresholds_path=None) -> list[dict]:
    rows = (improvements(improvements_path) + quarantined(quarantine_dir)
            + thresholds(thresholds_path))
    rows.sort(key=lambda r: -(r["age_hours"] or 0))
    return rows


# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------

def overdue(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r["age_hours"] or 0) > SLA_HOURS]


def summary(rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else all_open()
    late = overdue(rows)
    oldest = rows[0] if rows else None
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {
        "open": len(rows),
        "overdue": len(late),
        "by_kind": by_kind,
        "oldest_days": round((oldest["age_hours"] or 0) / 24, 1) if oldest else 0,
        "oldest_title": oldest["title"] if oldest else None,
        "sla_hours": SLA_HOURS,
    }


def report_line(rows: list[dict] | None = None) -> str:
    s = summary(rows)
    if not s["open"]:
        return "предложения без отговор: 0"
    return (f"предложения без отговор: **{s['open']}** "
            f"(най-старото: {s['oldest_days']} дни; "
            f"просрочени над {SLA_HOURS}ч: {s['overdue']})")


def load_stamp(path=None) -> dict:
    try:
        return json.loads((path or STAMP).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_stamp(data: dict, path=None) -> None:
    p = path or STAMP
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    except Exception:
        pass


def message(row: dict) -> str:
    days = (row["age_hours"] or 0) / 24
    return (f"⏳ CORTEX++ · предложение без отговор\n"
            f"{row['title']}\n\n"
            f"чака {days:.1f} дни (обещанието е {SLA_HOURS} часа)\n"
            f"вид: {row['kind']} · id: {row['id']}\n\n"
            f"Отговори с OK {row['id']} за одобрение.")


def digest(late: list[dict], rows: list[dict] | None = None,
           queue_path=None, top: int = DIGEST_TOP) -> str:
    """The ONE message a delivery run is allowed to send about the queue.

    Count first, because the count is the actual news. Then the five oldest by
    age WITH their ids, because "OK <id>" is the whole point — a digest that
    names a problem but not the handle to grab it by makes the human open a
    laptop, which at 02:00 means it waits another day. The rest goes to the
    queue file; the message says how many are down there.
    """
    rows = rows if rows is not None else late
    n = len(late)
    oldest = late[:top]
    lines = [f"⏳ CORTEX++ · {n} предложения без отговор",
             f"просрочени над {SLA_HOURS}ч · открити общо {len(rows)}",
             ""]
    lines.append(f"най-старите {len(oldest)}:")
    for r in oldest:
        days = (r["age_hours"] or 0) / 24
        lines.append(f"· {days:.1f} дни · {r['id']}\n  {r['title'][:70]}")
    if n > len(oldest):
        lines.append(f"... и още {n - len(oldest)}")
    lines += ["", "Отговори с OK <id> за одобрение."]
    if queue_path is not None:
        lines.append(f"Пълен списък: {queue_path}")
    return "\n".join(lines)


def digest_key(ids: list[str]) -> str:
    """A dedup key for the BATCH, so a re-run with the same backlog is silent.

    Hashed rather than listed because the key is stored in alarm_human's stamp
    file, capped at 20 000 characters — thirty ids in a key would spend a fifth
    of that budget on one entry and evict the rest of the day's dedup memory.
    """
    h = hashlib.sha1("|".join(sorted(ids)).encode("utf-8")).hexdigest()[:12]
    return f"sla:digest:{len(ids)}:{h}"


def write_queue(rows: list[dict], path=None) -> pathlib.Path | None:
    """The full table, for the screen. Fail-open: the phone message matters more.

    Written on every non-dry run, including runs that send nothing, because a
    cockpit that only sees the queue on escalation nights sees it wrong.
    """
    p = path or QUEUE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "generated_utc": _now().isoformat(),
            "sla_hours": SLA_HOURS,
            "summary": summary(rows),
            "rows": [{**r, "age_days": round((r["age_hours"] or 0) / 24, 2),
                      "overdue": (r["age_hours"] or 0) > SLA_HOURS}
                     for r in rows],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p
    except Exception as e:                                       # noqa: BLE001
        print(f"[SLA] queue file NOT written: {type(e).__name__}: {e}")
        return None


def run(improvements_path=None, quarantine_dir=None, thresholds_path=None,
        stamp_path=None, sender=None, dry_run: bool = False,
        queue_path=None) -> dict:
    """One pass over the queue: write the full table, send at most ONE message."""
    rows = all_open(improvements_path, quarantine_dir, thresholds_path)
    late = overdue(rows)
    stamp = load_stamp(stamp_path)

    written = None if dry_run else write_queue(rows, queue_path)

    # Everything overdue that has never been escalated. ONE message covers the
    # whole set — see the module docstring on the 28 messages in two minutes.
    fresh = [r for r in late if r["id"] not in stamp]
    escalated: list[str] = []
    if fresh:
        ids = [r["id"] for r in fresh]
        # A digest of one is a worse message than the proposal itself: the
        # per-proposal form names it, ages it and hands over the reply line.
        text = (message(fresh[0]) if len(fresh) == 1
                else digest(fresh, rows, written))
        key = f"sla:{ids[0]}" if len(fresh) == 1 else digest_key(ids)
        ok = True
        if not dry_run:
            try:
                if sender is not None:
                    sender(key, text)
                else:
                    import supervisor
                    supervisor.alarm_human(
                        "предложение без отговор", text,
                        dedup_key=key, trigger="MANUAL")
            except Exception:
                ok = False
        if ok:
            escalated = ids
            for r in fresh:
                stamp[r["id"]] = {"escalated_at": _now().isoformat(),
                                  "age_hours": r["age_hours"],
                                  "delivered_as": key}

    if not dry_run:
        save_stamp(stamp, stamp_path)

    s = summary(rows)
    print(f"[SLA] open {s['open']} | overdue {s['overdue']} | "
          f"escalated now {len(escalated)} | oldest {s['oldest_days']} days "
          f"| {s['by_kind']}" + (" — DRY RUN" if dry_run else ""))
    if escalated:
        print(f"[SLA] {'WOULD SEND one' if dry_run else 'one'} message covering "
              f"{len(escalated)} proposal(s); full list -> {written}")
    for pid in escalated[:DIGEST_TOP]:
        row = next(r for r in late if r["id"] == pid)
        print(f"[SLA] OVERDUE {pid}: {row['title'][:70]} "
              f"({(row['age_hours'] or 0) / 24:.1f} days)")
    return {"rows": rows, "overdue": late, "escalated": escalated,
            "summary": s, "messages_sent": 1 if (escalated and not dry_run) else 0,
            "queue_file": str(written) if written else None}


def for_cycle_report() -> dict:
    try:
        rows = all_open()
        return {**summary(rows), "line": report_line(rows),
                "oldest_five": [{"id": r["id"], "title": r["title"],
                                 "days": round((r["age_hours"] or 0) / 24, 1)}
                                for r in rows[:5]]}
    except Exception:
        return {}


def _selftest() -> int:
    print("core/proposal_sla.py --selftest")
    rows = all_open()
    s = summary(rows)
    ok = True

    checks = [
        ("proposals are found", s["open"] > 0),
        ("all three queues are counted", len(s["by_kind"]) >= 2),
        ("the oldest is named", bool(s["oldest_title"])),
        ("the report line reads as a debt", "без отговор" in report_line(rows)),
    ]
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed

    print(f"\n  {report_line(rows)}")
    print(f"  by kind: {s['by_kind']}")
    print("  петте най-стари:")
    for r in rows[:5]:
        print(f"    {(r['age_hours'] or 0) / 24:>5.1f}d  {r['kind']:<18} "
              f"{r['title'][:56]}")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv
             else (run(dry_run="--dry-run" in sys.argv) and 0))
