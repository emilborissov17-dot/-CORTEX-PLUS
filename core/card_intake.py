#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/card_intake.py — THE BRIDGE FROM THE SENSOR TO THE SYSTEM. (10 Sep 2026)

An agent (OpenClaw planetary-agent, any model) answers task cards with JSON.
Nothing it says enters the system by being said. It enters by passing
core/quote_gate.py against the live page, here, at ingest, on this machine.

  inbox    openclaw_queue/cards/*.jsonl     one JSON object per line, as the agent returned it
  accepted memory/verified_observations.jsonl  ONLY gate-ACCEPTED (and NULL_WITH_REASON) records,
                                               each with the gate verdict, the fetch time and
                                               a sha256 of the page text it was checked against
  refused  memory/card_refusals.jsonl       every other verdict, by name — the agent's
                                               invention rate is a number, not an impression
  open     (nothing written)                  FETCH_FAILED: retried next run, never accepted
                                               on faith, never counted against the agent

Idempotent: a record is keyed by sha256 of its canonical JSON; a line already
judged is skipped. The corpus for the local student (training/verified_corpus.py)
reads verified_observations.jsonl and nothing else — so what the student learns
is, by construction, only what the world confirmed.

Usage:
  venv\\Scripts\\python.exe core/card_intake.py            # judge every unjudged line in the inbox
  venv\\Scripts\\python.exe core/card_intake.py --dry      # print verdicts, write nothing
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from core import quote_gate as qg  # noqa: E402
from core import task_runs as tr  # noqa: E402

TASK_NAME = "card_intake"

INBOX = REPO / "openclaw_queue" / "cards"
ACCEPTED = REPO / "memory" / "verified_observations.jsonl"
REFUSED = REPO / "memory" / "card_refusals.jsonl"
OK_VERDICTS = ("ACCEPTED", "NULL_WITH_REASON")


def _key(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def judge_inbox(inbox: Path = INBOX, fetch: Callable[[str], Optional[str]] = qg._fetch,
                dry: bool = False, accepted_path: Path = ACCEPTED, refused_path: Path = REFUSED) -> dict:
    seen = {r.get("card_key") for r in _read_jsonl(accepted_path)} | {r.get("card_key") for r in _read_jsonl(refused_path)}
    counts = {"accepted": 0, "null_with_reason": 0, "refused": 0, "self_report": 0, "open": 0, "skipped": 0}
    for f in sorted(inbox.glob("*.jsonl")) if inbox.exists() else []:
        for rec in _read_jsonl(f):
            k = _key(rec)
            if k in seen:
                counts["skipped"] += 1
                continue
            # a card the agent itself refused is a record of the boundary holding, not a measurement
            if rec.get("refused") is True:
                verdict = {"verdict": "AGENT_REFUSED", "reason": rec.get("reason")}
                page_hash = None
            elif "url" not in rec and "value" not in rec:
                # a self-report (CAN/CANNOT, least-certain) — kept, not a measurement, not a refusal
                verdict = {"verdict": "NOT_AN_OBSERVATION"}
                page_hash = None
            else:
                page = fetch(str(rec.get("url", ""))) if rec.get("url") else None
                verdict = qg.judge(rec, page)
                page_hash = hashlib.sha256(page.encode("utf-8")).hexdigest() if page else None
            out = {"card_key": k, "judged_utc": datetime.now(timezone.utc).isoformat(),
                   "source_file": f.name, "verdict": verdict["verdict"], "gate": verdict,
                   "page_sha256": page_hash, "record": rec}
            v = verdict["verdict"]
            if v == "FETCH_FAILED":
                counts["open"] += 1              # left open, retried next run
                continue
            if not dry:
                _append(accepted_path if v in OK_VERDICTS else refused_path, out)
            seen.add(k)
            if v == "ACCEPTED":
                counts["accepted"] += 1
            elif v == "NULL_WITH_REASON":
                counts["null_with_reason"] += 1
            elif v == "NOT_AN_OBSERVATION":
                counts["self_report"] += 1
            else:
                counts["refused"] += 1
            print(json.dumps({"card": rec.get("card"), "key": rec.get("key"), "verdict": v}, ensure_ascii=False))
    return counts


def main(argv=None) -> dict:
    """The judge, with its two run rows. A FUNCTION, not a __main__ block.

    TWO ROWS, THE SAME TWO THE WORKER WRITES (20 Sep 2026). This step runs as
    the second half of tools/openclaw_chain.bat, which exports CORTEX_RUN_ID so
    both halves carry one id and the pair reads as one event. A chain whose
    fetch finished and whose judge died leaves ("card_intake", <id>) with a
    start and no finish, which is exactly the shape core.task_runs.unfinished
    keys on.

    LIFTED OUT OF __main__ ON 21 SEP 2026, and the reason is the handler below.
    It caught BaseException, which test_no_bare_except flagged, and it was
    resolved by DECLARING it — which recorded the choice without checking it. A
    guard sitting in a __main__ block cannot be reached by any test, so nobody
    could have checked it. It is a function now, and
    test_the_interrupt_handlers_record_and_reraise exercises it.
    """
    argv = sys.argv if argv is None else argv
    dry = "--dry" in argv
    tr.announce(TASK_NAME)
    rid = tr.run_id(TASK_NAME)
    tr.row(TASK_NAME, "start", rid, dry=dry)
    try:
        c = judge_inbox(dry=dry)
    except BaseException as exc:                                  # noqa: BLE001
        # A CRASH IS A FINISH, and it is recorded with its reason before being
        # RE-RAISED — nothing is swallowed on this path, which is what makes
        # the BaseException catch safe.
        #
        # WHY BaseException AND NOT Exception. Measured 21 Sep 2026: judge_inbox
        # is not a generator, so GeneratorExit cannot arrive here, and the only
        # sys.exit in this module is in the __main__ block below, after this
        # returns — so SystemExit cannot arise from the call path either. What
        # remains is KeyboardInterrupt. Narrowed to `except Exception`, a Ctrl-C
        # would leave a start with no finish, which is the row shape that means
        # "killed by a reboot" — and, because nothing ever clears it,
        # tr.announce() would report that phantom at the top of every future run
        # for ever. Recording the interrupt is what keeps the signal a signal.
        tr.row(TASK_NAME, "finish", rid, ok=False,
               error=f"{type(exc).__name__}: {str(exc)[:300]}")
        raise
    tr.row(TASK_NAME, "finish", rid, ok=True, **c)
    return c


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
