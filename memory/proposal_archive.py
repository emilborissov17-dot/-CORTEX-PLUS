#!/usr/bin/env python3
"""
memory/proposal_archive.py — every proposal the system ever made, kept.

WHAT WAS BEING LOST (measured 17 Aug 2026)
-------------------------------------------
`agents/core/self_observer.py::save_proposals` is a read-modify-write with three
lossy paths, and until this file existed none of them left a copy anywhere:

  1. AGE CUTOFF   MAX_AGE_DAYS = 7  — proposals older than a week are deleted.
                  37 were already gone in the 8 cycle-runs whose logs survive.
  2. THE 50-CAP   MAX_PROPOSALS = 50 — oldest trimmed. Not binding today (30/50),
                  binding the moment the system gets more productive.
  3. THE GUARD    a proposal `evaluate_proposal_alignment` blocks is `print`ed and
                  dropped. It never touched disk at all.

  ( 4. and a fourth nobody had named: the fuzzy dedup `continue` at the top of the
    loop silently discards any proposal whose problem matches an existing one in
    the first 80 characters. )

`memory/improvement_proposals_archive.json` looked like the answer. It is not:
the string appears in ZERO files and in ZERO commits of the whole git history,
and the file is untracked. Nothing ever wrote it from this codebase. It stopped
on 23 July because whatever hand-run script produced it was never run again.

So this is written upstream of all four, at the moment of decision.

THE BLOCKED ONES ARE THE POINT
-------------------------------
A blocked proposal is archived WITH the reason it was blocked. Those are the
records we lost most completely, and they are the most interesting ones we have:
they are what the system wanted to do and what we refused. A system that keeps
only its approved thoughts has no record of its own judgement being overruled.

APPEND-ONLY, AND THAT INCLUDES THE BAD ONES
--------------------------------------------
Nothing here is ever rewritten or deleted — not duplicates, not nonsense, not
proposals that were wrong. This is a record of what the system thought, not a
curated list of good ideas. `record()` only ever opens a file in "a" mode.

WHY MARKDOWN, ONE FILE PER MONTH
---------------------------------
The criterion this format was chosen against: a human must be able to answer
"what did the system propose about water in July" WITHOUT WRITING CODE.

    memory/proposal_archive/2026-07.md   →  open it, Ctrl-F "water"   →  done.

JSONL was the obvious alternative and it fails that test in practice. The corpus
is mostly Bulgarian; a JSONL line is a single dense escaped string, and a reader
who wants July's water proposals gets a wall of `\\u0432\\u043e\\u0434` unless they
reach for `jq` — which is writing code. Monthly files bound the search without an
index, and an index would have to be REWRITTEN, which append-only forbids.

The cost is stated honestly: this is not a machine-parseable store. Nothing in
the repo reads it today, and CLAUDE.md is explicit that a file nothing loads is
dead weight — so it is written for the human who greps it, and the format is kept
regular (one `- **key:** value` per field) so a parser is possible later if
something ever genuinely needs one. It is deliberately not built now.

WHAT IS NOT CAPTURED, STATED RATHER THAN INVENTED
--------------------------------------------------
There is no separate reasoning trace. `call_groq_meta` returns the model's final
text and nothing else; no provider in the chain is asked for a reasoning channel,
and none is stored. What IS recoverable is the model's FULL RAW OUTPUT for the
batch that produced a proposal — the JSON array plus whatever preamble the model
emitted around it — and that is archived under `raw model output (batch)`, named
for what it actually is. It is not labelled "reasoning", because it is not
reliably reasoning. If a reasoning channel is captured one day, it gets its own
field; it does not get retrofitted into this one.

    venv\\Scripts\\python.exe -m memory.proposal_archive --selftest
    venv\\Scripts\\python.exe -m memory.proposal_archive --backfill
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# Module constants, not `BASE / ...` inside a function — a path built in a
# function body cannot be redirected by a test fixture and cannot be seen by the
# write-surface guard. That is the 16 Aug 2026 lesson, and it applies here even
# harder: this file is the only copy of what it holds.
ARCHIVE_DIR = BASE / "memory" / "proposal_archive"
LIVE_PROPOSALS = BASE / "memory" / "improvement_proposals.json"

ACCEPTED = "ACCEPTED"
BLOCKED = "BLOCKED"
DUPLICATE = "DUPLICATE"

README = """# Proposal archive

Every proposal CORTEX++ generated, including the ones that were blocked,
duplicated, or wrong. Append-only: nothing here is ever edited or deleted.

## How to answer "what did the system propose about water in July"

Open `2026-07.md` and search for `water` (or `вода`). That is the whole method.
No tooling, no query language.

## What an outcome means

- `ACCEPTED`  — passed the alignment guard and entered memory/improvement_proposals.json.
              It may still have been deleted from there later by the 7-day cutoff
              or the 50-cap. This archive is the only place it survives.
- `BLOCKED`   — alignment guard refused it. The reason is on the `outcome` line.
              These never reached improvement_proposals.json at all.
- `DUPLICATE` — the system proposed it again; the fuzzy dedup dropped it. Kept,
              because "the system keeps raising this" is itself a finding.

## What is NOT here

No separate reasoning trace exists — no provider in the chain is asked for one.
`raw model output (batch)` is the model's full final text for the batch of
proposals that included this one, which is what is actually recoverable.

Entries backfilled on the day the archive was built carry `backfilled: true` and
have no model/provider/cycle_id, because none was recorded when they were made.
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cycle_id() -> str | None:
    """Which cycle produced this. Env first (the supervisor sets it at spawn),
    heartbeat second (a manual run stamps its own)."""
    env = os.environ.get("CORTEX_CYCLE_ID")
    if env:
        return env
    try:
        from memory import heartbeat as hb
        return (hb.read() or {}).get("cycle_id")
    except Exception:
        return None


def record_id(proposal: dict, ts: str) -> str:
    """Stable id for one archived record: timestamp + the problem text.

    Used ONLY so `--backfill` can be re-run without duplicating what it already
    rescued. The live `record()` path never dedupes — if the system proposed the
    same thing twice, the archive says so twice.
    """
    key = f"{ts}|{str(proposal.get('problem', ''))[:160]}"
    return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:12]


def _month_file(ts: str, archive_dir: Path) -> Path:
    return archive_dir / f"{ts[:7]}.md"


def _fence(text: str, limit: int = 6000) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    clipped = text[:limit]
    tail = "" if len(text) <= limit else f"\n… [clipped, {len(text)} chars total]"
    # A model can emit ``` inside its own output; nesting one level deeper keeps
    # the block intact instead of ending it halfway through the evidence.
    return f"````\n{clipped}{tail}\n````"


def _entry(proposal: dict, outcome: str, reason: str, provenance: dict | None,
           ts: str, rid: str, backfilled: bool) -> str:
    prov = provenance or {}
    component = str(proposal.get("component", "") or "?")
    head = f"## {ts} — {outcome} — {component}"

    lines = [head, ""]
    lines.append(f"- **id:** {rid}")
    lines.append(f"- **outcome:** {outcome}"
                 + (f" — {reason}" if reason else ""))
    lines.append(f"- **component:** {component}")
    # Three spellings exist in the wild and all of them are real: the LLM path
    # sets `source`, the dependency path sets `generated_by`, and the archive
    # hook passes its own. Preferring the most specific first means a record
    # says "unknown" only when it genuinely is.
    lines.append("- **generated_by:** " + str(
        prov.get("generated_by") or proposal.get("generated_by")
        or proposal.get("source") or "unknown"))
    lines.append(f"- **timestamp:** {ts}")
    lines.append(f"- **provider:** {prov.get('provider') or '(not recorded)'}")
    lines.append(f"- **model:** {prov.get('model') or '(not recorded)'}")
    lines.append(f"- **cycle_id:** {prov.get('cycle_id') or '(not recorded)'}")
    if prov.get("finish_reason"):
        lines.append(f"- **finish_reason:** {prov['finish_reason']}")
    if prov.get("prompt_sha1"):
        lines.append(f"- **prompt_sha1:** {prov['prompt_sha1']}")
    if proposal.get("agi_characteristic"):
        lines.append(f"- **agi_characteristic:** {proposal['agi_characteristic']}")
    if proposal.get("priority"):
        lines.append(f"- **priority:** {proposal['priority']}")
    if backfilled:
        lines.append("- **backfilled:** true — rescued from "
                     "memory/improvement_proposals.json when the archive was "
                     "built; provenance was not recorded at generation time")
    lines.append("")

    for label, key in (("Problem", "problem"), ("Root cause", "root_cause"),
                       ("Solution", "solution"),
                       ("Measurable goal", "measurable_goal")):
        val = str(proposal.get(key, "") or "").strip()
        lines.append(f"**{label}:** {val or '(none recorded)'}")
        lines.append("")

    raw = prov.get("raw_response")
    if raw:
        lines.append("<details><summary>raw model output (batch)</summary>")
        lines.append("")
        lines.append(_fence(raw))
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def record(proposal: dict, outcome: str, reason: str = "",
           provenance: dict | None = None, archive_dir: Path | None = None,
           backfilled: bool = False) -> str | None:
    """Append one proposal to the archive. Returns its id, or None on failure.

    NEVER RAISES, and never silently succeeds either: a failure prints, because
    this is the only copy and a quiet loss here is exactly the class of bug the
    file exists to end.
    """
    try:
        archive_dir = Path(archive_dir) if archive_dir else ARCHIVE_DIR
        ts = str(proposal.get("timestamp") or "").strip() or _utc_now()
        prov = dict(provenance or {})
        prov.setdefault("cycle_id", _cycle_id())
        rid = record_id(proposal, ts)

        archive_dir.mkdir(parents=True, exist_ok=True)
        readme = archive_dir / "README.md"
        if not readme.exists():
            readme.write_text(README, encoding="utf-8")

        path = _month_file(ts, archive_dir)
        new_file = not path.exists()
        with open(path, "a", encoding="utf-8") as fh:
            if new_file:
                fh.write(f"# Proposals — {ts[:7]}\n\n"
                         f"Append-only. See README.md in this directory.\n\n")
            fh.write(_entry(proposal, outcome, reason, prov, ts, rid, backfilled))
        return rid
    except Exception as e:
        print(f"  [PROPOSAL_ARCHIVE] FAILED to archive "
              f"{str(proposal.get('problem', ''))[:60]!r}: {type(e).__name__}: {e}")
        return None


def existing_ids(archive_dir: Path | None = None) -> set:
    """Ids already in the archive. Read-only; used by --backfill only."""
    archive_dir = Path(archive_dir) if archive_dir else ARCHIVE_DIR
    ids = set()
    if not archive_dir.exists():
        return ids
    for f in sorted(archive_dir.glob("*.md")):
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("- **id:** "):
                    ids.add(line.split("- **id:** ", 1)[1].strip())
        except Exception:
            continue
    return ids


def backfill(live_path: Path | None = None,
             archive_dir: Path | None = None) -> dict:
    """Rescue the proposals sitting in improvement_proposals.json right now.

    THE URGENT PART. The 29 on disk span exactly the 7-day window and the oldest
    are deleted around 23 August with no copy anywhere. They are archived as
    ACCEPTED (they are in the live file, so they passed the guard) and marked
    `backfilled: true`, because their model, provider and cycle_id were never
    recorded and inventing them would be worse than admitting the gap.

    Re-runnable: skips ids already present. That is a read, not a rewrite.
    """
    live_path = Path(live_path) if live_path else LIVE_PROPOSALS
    archive_dir = Path(archive_dir) if archive_dir else ARCHIVE_DIR
    out = {"found": 0, "archived": 0, "already_present": 0, "failed": 0}
    try:
        data = json.loads(live_path.read_text(encoding="utf-8"))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    proposals = data.get("proposals", data) if isinstance(data, dict) else data
    have = existing_ids(archive_dir)
    for p in proposals or []:
        out["found"] += 1
        ts = str(p.get("timestamp") or "").strip() or _utc_now()
        if record_id(p, ts) in have:
            out["already_present"] += 1
            continue
        rid = record(p, ACCEPTED,
                     reason="in improvement_proposals.json when the archive was built",
                     provenance={"generated_by": p.get("source")},
                     archive_dir=archive_dir, backfilled=True)
        if rid:
            out["archived"] += 1
            have.add(rid)
        else:
            out["failed"] += 1
    return out


def selftest() -> dict:
    """LIVE / INERT for every integration, against THIS repo."""
    import shutil
    import tempfile

    rep: dict = {"ts": _utc_now()}
    tmp = Path(tempfile.mkdtemp(prefix="proposal_archive_selftest_"))
    try:
        rid = record({"component": "WATER", "problem": "probe",
                      "solution": "s", "timestamp": "2026-07-15T00:00:00+00:00"},
                     BLOCKED, reason="probe reason", archive_dir=tmp)
        july = tmp / "2026-07.md"
        body = july.read_text(encoding="utf-8") if july.exists() else ""
        rep["write_and_month_routing"] = {
            "LIVE": bool(rid) and "probe reason" in body and july.exists(),
            "file": july.name, "id": rid,
        }
        before = len(body)
        record({"component": "WATER", "problem": "probe2",
                "timestamp": "2026-07-16T00:00:00+00:00"}, ACCEPTED,
               archive_dir=tmp)
        after = len(july.read_text(encoding="utf-8"))
        rep["append_only"] = {"LIVE": after > before and "probe reason" in
                              july.read_text(encoding="utf-8"),
                              "grew_by": after - before}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Is anything actually calling us? An archive nobody writes to is a lie.
    try:
        src = (BASE / "agents" / "core" / "self_observer.py").read_text(
            encoding="utf-8", errors="replace")
        wired = "proposal_archive" in src
        rep["self_observer_wiring"] = {
            "LIVE": wired,
            "note": ("save_proposals archives every outcome" if wired else
                     "NOTHING WRITES THIS ARCHIVE — proposals are still being lost"),
            "blocked_path": "BLOCKED" in src,
        }
    except Exception as e:
        rep["self_observer_wiring"] = {"LIVE": False, "error": f"{type(e).__name__}: {e}"}

    rep["live_archive"] = {
        "dir": str(ARCHIVE_DIR),
        "exists": ARCHIVE_DIR.exists(),
        "months": sorted(p.name for p in ARCHIVE_DIR.glob("*.md")) if ARCHIVE_DIR.exists() else [],
        "entries": len(existing_ids()),
    }
    return rep


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        r = selftest()
        print(f"proposal_archive selftest — {r['ts']}")
        for k in ("write_and_month_routing", "append_only", "self_observer_wiring"):
            d = r.get(k, {})
            print(f"  {'LIVE ' if d.get('LIVE') else 'INERT'}  {k}: "
                  f"{ {a: b for a, b in d.items() if a != 'LIVE'} }")
        print(f"  live archive: {r['live_archive']}")
        return 0 if all(r.get(k, {}).get("LIVE") for k in
                        ("write_and_month_routing", "append_only",
                         "self_observer_wiring")) else 1
    if "--backfill" in argv:
        res = backfill()
        print(f"[PROPOSAL_ARCHIVE] backfill: {res}")
        return 0
    print(__doc__.strip().splitlines()[1])
    print("usage: --selftest | --backfill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
