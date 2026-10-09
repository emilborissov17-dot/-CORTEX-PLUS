# -*- coding: utf-8 -*-
"""core/shown.py — what has already been shown to the brain, per need (C-SHOWN-1, 9 Oct 2026).

WHY THIS EXISTS. Until now review() showed each need the FIRST five statements ever ingested for
it, in store order, with no record of what had been shown. Read on the machine 9 Oct: 38 needs
shown 190 items per brain turn, the same items since 1 Oct 15:22, while the store grew to 679 438
statements and one turn of the agents brought 5 688. The 3B therefore repeated one verdict (269
STILL_OPEN, 0 closed) and proposed the same 13 expressions every turn.

Perplexity rounds 82 and 82B under Emil R73 decided the selection: only statements NOT YET SHOWN
for that need, newest by ingestion time first, k per need; the store-wide relevance read stays
only as a conditional fallback for a need with no linked statements of its own, labelled
CONTEXT_RETRIEVED and also deduplicated; and when there is nothing new, the 3B is not called at
all. This module is the record that makes "not yet shown" a fact instead of a hope.

THE RECORD. memory/shown_to_brain.jsonl, one row per item actually shown:
    {"ts": "...", "need_id": "BN-...", "statement_id": "...", "kind": "LINKED"|"CONTEXT"}
Append-only: a row says the brain was shown this, and that never stops being true. Nothing is
deleted here and nothing in the store is deleted — a need keeps every statement it ever gained
(Emil R24: no retirement).

FAILURE PATHS FIRST, and the distinction that matters (R65 verifier, 9 Oct). A file that is NOT
THERE is an empty record: nothing has been shown yet, so nothing is suppressed and the brain is
shown the newest material. A file that IS there and cannot be read is NOT the same thing and
must never be treated as one - it raises ShownUnreadable. Read as "nothing shown", an unreadable
record would make every need be shown everything it has already seen and re-recorded, which is
the exact defect this module exists to remove, wearing a plausible record as a disguise.
A row that is not a JSON object, or that has no need_id or statement_id, is skipped, not guessed.
An item whose kind is not LINKED or CONTEXT is REFUSED, not written as LINKED: LINKED means "the
need's own evidence" and is never the value a missing label falls back to (DEFECT-B).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
SHOWN = REPO / "memory" / "shown_to_brain.jsonl"
LINKED = "LINKED"
CONTEXT = "CONTEXT"
KINDS = (LINKED, CONTEXT)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ShownUnreadable(RuntimeError):
    """The record is there and cannot be read. NOT the same as "nothing has been shown yet"."""


def shown_ids(path=None) -> dict:
    """need_id -> set of statement ids already shown for that need. A file that does not exist
    yet is an empty dict - nothing has been shown, so nothing is suppressed. A file that exists
    and cannot be read or decoded RAISES ShownUnreadable instead of pretending to be empty."""
    out: dict = {}
    p = Path(path or SHOWN)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    except (OSError, ValueError) as exc:                       # unreadable, undecodable, a directory
        raise ShownUnreadable(f"{p}: {type(exc).__name__}: {exc}") from exc
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue                                           # a torn last line: skipped, never guessed
        if not isinstance(row, dict):
            continue                                           # a list or a bare number is not a row
        nid, sid = row.get("need_id"), row.get("statement_id")
        if isinstance(nid, str) and isinstance(sid, str):
            out.setdefault(nid, set()).add(sid)
    return out


def record(need_id: str, items: list, path=None, kind_of=None) -> int:
    """Append one row per shown item. `items` are the dicts review() showed; each carries "id"
    and, from the selection, "shown_as" (LINKED or CONTEXT). Returns the number of rows written.
    An item without an id is not recorded and not invented."""
    rows = []
    for it in items or []:
        sid = (it or {}).get("id")
        if not isinstance(sid, str):
            continue
        kind = (kind_of or (lambda i: (i or {}).get("shown_as")))(it)
        if kind not in KINDS:
            raise ValueError(f"shown.record: {need_id} item {sid!r} carries kind {kind!r}, which is "
                             f"not one of {KINDS}; LINKED is never assumed for a missing label")
        rows.append({"ts": _now(), "need_id": need_id, "statement_id": sid, "kind": kind})
    if not rows:
        return 0
    p = Path(path or SHOWN)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


DROP_REGIONS = ("furniture",)          # 82C В1.1: page furniture is not shown and not proposed
REGION_RANK = {"main": 0, "unknown": 1}


def unseen(items: list, seen: set, k: int, newest_first: bool = True, drop_regions=DROP_REGIONS) -> list:
    """The first k items of `items` that are not in `seen`, newest by ingestion time first
    (Perplexity 82 В2.2), with page FURNITURE dropped and the region as the TIE-BREAKER only
    (82C В1): main before unknown when the ingestion time is equal — which is the real case,
    because a page's furniture and its main text are ingested in the same second. The measured
    reason for dropping furniture: of 752 refused proposals, 521 were "an argument is the whole
    sentence" and the refused arguments include 'toggle navigation' and 'Skip to content'.
    Nothing is deleted from the store; furniture simply is not an input to the brain.
    An item whose ingested_at is MISSING OR NOT A STRING sorts LAST among the unseen — it is not
    treated as new, and it is not dropped either; an epoch number or a datetime is not silently
    read as a date (R65 verifier, 9 Oct: it used to sort as the oldest dated item instead of
    last). The order is stable, so the same input gives the same output."""
    drop = set(drop_regions or ())
    out = [it for it in (items or []) if (it or {}).get("id") not in (seen or set())
           and (it or {}).get("region") not in drop]
    if newest_first:
        out = sorted(out, key=lambda it: (_ts(it) is None, _neg(_ts(it)),
                                          REGION_RANK.get((it or {}).get("region"), len(REGION_RANK))))
    return out[:k] if k is not None else out


def _ts(it):
    """The item's ingestion time if it is a string, else None. A non-string is NOT a date."""
    v = (it or {}).get("ingested_at")
    return v if isinstance(v, str) else None


class _Rev:
    """Sorts strings descending inside a tuple key, without reversing the whole sort."""

    __slots__ = ("s",)

    def __init__(self, s):
        self.s = s

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == getattr(other, "s", None)


def _neg(ts):
    return _Rev(ts if isinstance(ts, str) else "")


def selftest() -> dict:
    ids = shown_ids()
    return {"integrations": {"memory/shown_to_brain.jsonl":
                             f"LIVE ({len(ids)} need(s) with a record)" if Path(SHOWN).exists()
                             else "INERT (nothing shown yet)"},
            "needs_with_a_record": len(ids), "rows": sum(len(v) for v in ids.values()), "ok": True}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2, ensure_ascii=False))
        sys.exit(0)
    print(__doc__)
