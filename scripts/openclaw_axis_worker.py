#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/openclaw_axis_worker.py — THE DMZ FETCH WORKER.

WHAT CROSSES, AND WHAT DOES NOT
--------------------------------
The only thing in CORTEX that reaches the outside world for an axis number.

    IN   a URL, from the seed config or from what data_scout found
    OUT  one finite NUMBER bound to (axis, key), or a named refusal

Same contract as agents/axis/axis_feed.py, one step further out. There the risk
was a model writing prose where a measurement belonged; here it is a remote
service answering with a string, a null, an error object or an HTML maintenance
page, and that landing in the queue as if somebody had measured it.

HOW IT RUNS (recorded 20 September 2026, the day it first ran at all)
---------------------------------------------------------------------
For a month nothing ran this. It was registered that day as the Windows task
CORTEX_OpenClaw:

    venv/Scripts/python.exe scripts/openclaw_axis_worker.py
    daily 05:50 local, repeating every 6h for 1 day -> 05:50 / 11:50 / 17:50 / 23:50

05:50 IS NOT AN ARBITRARY HOUR. The nightly cycle starts at 03:04 and took 103,
108 and 100 minutes on 18, 19 and 20 Sep, so 05:50 clears its worst observed end
by about an hour. 11:50 is ten minutes before CORTEX_Prophecy at 12:00, whose
step 148 is core/card_intake.py — the gate that judges what this writes — so the
morning run reads cards fetched minutes earlier rather than six hours earlier.

THE TASK LIVES IN WINDOWS TASK SCHEDULER AND NOWHERE IN THIS REPO, like every
other CORTEX_* task. config/scheduler.json is the supervisor's ceilings and
budgets, not a task registry, so this paragraph is the only place in the source
tree that says what runs this file. To check it rather than believe it:

    schtasks /Query /TN CORTEX_OpenClaw /V /FO LIST

and memory/task_runs.jsonl carries two rows per run, so a run that started and
never came back is visible without asking Windows anything.

THE ALLOWLIST IS GONE, ON PURPOSE
----------------------------------
It used to be that a human wrote four URLs into a config and only those were
fetched. Safe, and a dead end: data_scout has been finding sources since June
and 44 active JSON candidates sit unused in memory/discovered_data_sources.json,
some since 31 July, because nothing decided whether to believe them.

A hand-written list cannot grow. What grows is a PROCESS for earning trust —
core/source_lifecycle.py. Sources now come from BOTH places:

    config/openclaw_sources.json          the seed, hand-written
    memory/discovered_data_sources.json   data_scout's own finds

and every one of them starts as a CANDIDATE. Candidates are fetched every cycle
and their readings are STORED BUT NOT BELIEVED — shadow rows, written beside
the trusted ones and marked. Only a source that has earned TRUSTED enters the
composite as MEASURED.

GET ONLY. The worker issues no other verb; that is asserted by a test rather
than left to discipline.

    venv/Scripts/python.exe scripts/openclaw_axis_worker.py
    venv/Scripts/python.exe scripts/openclaw_axis_worker.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
SOURCES = BASE / "config" / "openclaw_sources.json"
QUEUE = BASE / "openclaw_queue"
FEEDS = QUEUE / "external_feeds.jsonl"
REFUSALS = QUEUE / "external_refusals.jsonl"
SHADOWS = QUEUE / "external_shadow.jsonl"

# THE WIRE, CLOSED 20 September 2026. This worker has written the three files
# above since it was built and NOTHING has ever read them into the cycle:
# external_feeds.jsonl is read back only by this module's own _peer_for(), the
# other two only by this module's tests. Meanwhile core.card_intake.judge_inbox
# reads openclaw_queue/cards/*.jsonl and writes what the quote gate ACCEPTS into
# memory/verified_observations.jsonl, which four modules do read. Two halves,
# green separately for a month, delivering nothing between them.
#
# CARDS is that missing segment. The three files keep their contents and their
# readers; this is an addition, not a redirection.
CARDS = QUEUE / "cards"

# ── A RUN THAT STARTS AND NEVER FINISHES MUST BE VISIBLE ───────────────────
# Two rows per run, start and finish. A worker killed by a reboot, an OOM or a
# closed laptop writes the first and never the second, and the gap is the whole
# signal: a silent worker that simply stops is the defect this repo keeps
# finding, and it is invisible in a log that only records successes.
#
# NOT A DUPLICATE OF THE FEED FILES. Those record what was FETCHED; this records
# that the PROCESS ran, which is a different question and is unanswerable from
# them — a run that died before its first fetch leaves no feed row at all.
TASK_RUNS = BASE / "memory" / "task_runs.jsonl"
TASK_NAME = "openclaw_axis_worker"

DEFAULT_TIMEOUT = 30


class Refused(ValueError):
    """This source did not produce a number. The reason is the message."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ONE IMPLEMENTATION, TWO CALLERS (20 Sep 2026). core/card_intake.py needed the
# same two rows ten minutes after this one grew them, and a second copy of a
# run-log is how two logs drift into disagreeing about the same night. The
# behaviour moved to core/task_runs.py; these two keep their names so the tests
# that ask the questions go on asking them in the same words.
def _task_row(row: dict, path: pathlib.Path | None = None) -> None:
    """Append one run row. Fail-open: a log that cannot be written must not
    cost the run it is describing."""
    from core import task_runs as _tr
    rec = dict(row)
    task = rec.pop("task", TASK_NAME)
    event = rec.pop("event", "start")
    rid = rec.pop("run_id", "")
    rec.pop("pid", None)
    rec.pop("ts", None)
    _tr.row(task, event, rid, path=path, **rec)


def unfinished_runs(path: pathlib.Path | None = None, task: str = TASK_NAME) -> list:
    """Runs that wrote a start and never a finish.

    THE READER OF TASK_RUNS, in the same commit that started writing it, because
    a file nobody reads is the thing this repo spent yesterday removing. It is
    read at the top of every run, so the FIRST thing a run says is whether the
    last one came back.
    """
    from core import task_runs as _tr
    return _tr.unfinished(task, path)


DISCOVERED = BASE / "memory" / "discovered_data_sources.json"


def load_sources(path: pathlib.Path | None = None) -> tuple[list[dict], int]:
    """The seed list only. Kept separate so its shape stays readable."""
    cfg = json.loads((path or SOURCES).read_text(encoding="utf-8"))
    return cfg.get("sources", []), int(cfg.get("timeout_sec", DEFAULT_TIMEOUT))


def load_discovered(path: pathlib.Path | None = None) -> list[dict]:
    """data_scout's finds, translated into the worker's shape.

    Only status=active and format=json: a CSV needs a different parser and a
    rejected source was already judged by something else. kind=http_json_count
    means the number is the LENGTH of the list at `extract` — that is how EONET
    reports events — so the path becomes '<extract>.#len'.
    """
    try:
        blob = json.loads((path or DISCOVERED).read_text(encoding="utf-8"))
    except Exception:
        return []

    out: list[dict] = []
    for axis, node in blob.items():
        if axis.startswith("_"):
            continue
        entries = node.get("sources") if isinstance(node, dict) else node
        for src in entries or []:
            if not isinstance(src, dict):
                continue
            if src.get("status") != "active" or src.get("format") != "json":
                continue
            url, extract = src.get("url"), src.get("extract")
            if not url or not extract:
                continue
            path_expr = (f"{extract}.#len" if src.get("kind") == "http_json_count"
                         else extract)
            out.append({
                # STABLE across processes. The first version used hash(url),
                # which Python randomises per interpreter (PYTHONHASHSEED), so
                # every run minted fresh ids and no source could accumulate a
                # streak — visible as the candidate count climbing 32, 60, 88,
                # 116 over four runs of the same 33 sources.
                "id": f"scout:{src.get('org', '?')}:"
                      f"{hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]}",
                "axis": axis,
                "key": (src.get("metric") or extract)[:60],
                "url": url,
                "path": path_expr,
                "unit": src.get("slot_hint") or "unknown",
                "org": src.get("org"),
                "why": src.get("provenance") or src.get("metric"),
                "origin": "data_scout",
                "discovered_at": src.get("discovered_at"),
            })
    return out


def all_sources(seed_path=None, discovered_path=None) -> tuple[list[dict], int]:
    """Seed plus discovered, de-duplicated on (axis, url)."""
    seed, timeout = load_sources(seed_path)
    for s in seed:
        s.setdefault("origin", "seed")
    # Keyed on the PATH too, not just (axis, url). The seed deliberately holds
    # two entries against the same USGS url — one real, one with a path that
    # walks into a number — so that the refusal branch runs on every fetch.
    # De-duplicating on (axis, url) alone silently ate the broken one.
    merged, seen = [], set()
    for src in list(seed) + load_discovered(discovered_path):
        key = (src.get("axis"), src.get("url"), src.get("path"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(src)
    return merged, timeout


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def walk(payload, path: str):
    """Resolve a dotted path. Raises Refused with WHERE it failed.

    The error names the segment that broke and what was there instead, because
    "path did not resolve" sends the reader back to the API docs while "at
    'total', count was an int" sends them to the right line of the config.
    """
    node = payload
    if not path:
        raise Refused("empty path")
    for i, seg in enumerate(path.split(".")):
        trail = ".".join(path.split(".")[:i]) or "<root>"
        if seg == "#len":
            if not isinstance(node, (list, tuple)):
                raise Refused(f"#len at {trail}: expected a list, found "
                              f"{type(node).__name__}")
            return len(node)
        if isinstance(node, dict):
            if seg not in node:
                keys = ", ".join(list(node)[:6]) or "(no keys)"
                raise Refused(f"at {trail!r}: no key {seg!r}; has: {keys}")
            node = node[seg]
        elif isinstance(node, (list, tuple)):
            if not seg.lstrip("-").isdigit():
                raise Refused(f"at {trail!r}: {seg!r} is not a list index")
            idx = int(seg)
            if not -len(node) <= idx < len(node):
                raise Refused(f"at {trail!r}: index {idx} out of range "
                              f"(len {len(node)})")
            node = node[idx]
        else:
            raise Refused(f"at {seg!r}: cannot descend into "
                          f"{type(node).__name__} ({str(node)[:40]})")
    return node


# The card's six gate fields, in core.quote_gate.REQUIRED's own order, plus the
# observation date. NOTHING ELSE MAY JOIN THIS LIST without a reason, and the
# reason can never be "it would be useful to have": card_intake._key() hashes the
# WHOLE record, so a field that changes between runs while the reading does not
# gives the same measurement a new identity every night. The gate would re-fetch
# it, re-judge it and re-append it, and the four readers of
# memory/verified_observations.jsonl would count one observation many times.
#
# ts, latency_s, source_id, org, path, trust, origin, measured and status all
# change per run or carry no meaning for the gate. They stay in the feed, the
# shadow and the refusal files, which is where a reader looking for them goes.
CARD_FIELDS = ("axis", "key", "value", "unit", "url", "quote", "data_date")

_QUOTE_WIDTH = 90


def quote_from_body(raw: str, value: float, width: int = _QUOTE_WIDTH) -> str | None:
    r"""A VERBATIM slice of the raw response text containing `value`, or None.

    NEVER REBUILT FROM THE PARSED OBJECT, and that is the whole point rather
    than a nicety. core.quote_gate.judge() accepts a card by finding its quote
    ON THE PAGE it fetched; a quote assembled from the number we already parsed
    would match every time, and the gate would be answering "is this string a
    string" instead of "did the page say this". The slice is cut out of the
    bytes the server sent, so the check stays a check.

    WHERE THE SLICE STARTS, AND WHY IT IS NOT ARBITRARY. quote_gate._NUM only
    matches a standalone number: `(?<![\w:./\-])`. A compact JSON body serves
    `"count":38`, where the character before the digit is a colon, so a slice
    that swallowed the colon would carry a number the gate cannot see and every
    card would come back VALUE_MISMATCH. When the preceding character would
    block the match, the slice begins AT the value; otherwise it keeps the left
    context, which is what makes the quote readable to a human.

    Returns None when the value cannot be found in the body verbatim — a float
    the server wrote in another notation (1e3, 38.00) is not quotable, and a
    card with no quote is not written at all.
    """
    if not raw or not isinstance(raw, str):
        return None
    for cand in _spellings(value):
        i = raw.find(cand)
        while i != -1:
            end = i + len(cand)
            # INSIDE A LONGER NUMBER, and a digit either side is not enough to
            # rule it out. The first live run quoted "46.0016162" — a LATITUDE —
            # as evidence for a flood count of 46, because the character after
            # "46" is a dot and the guard only looked for digits.
            if not (_IN_NUMBER.match(raw[i - 1:i])
                    or _IN_NUMBER.match(raw[end:end + 1])):
                left = i if _BLOCKS_NUM.match(raw[i - 1:i]) else max(0, i - width // 2)
                cut = raw[left:min(len(raw), end + width // 2)]
                if _gate_sees(cut, value):
                    return cut
            i = raw.find(cand, i + 1)
    return None


def _gate_sees(quote: str, value: float) -> bool:
    """Would core.quote_gate find `value` among the numbers of this quote?

    THE GATE'S OWN REGEX, imported rather than copied. A quote this worker emits
    and the gate then rejects is worse than no quote: it lands in
    memory/card_refusals.jsonl as if the SOURCE were at fault, when the fault is
    in the cutting. Asking the gate's own rule here means the worker never
    produces a quote it already knows will be refused.
    """
    try:
        from core import quote_gate as _qg
        nums = [float(n.replace(",", ".")) for n in _qg._NUM.findall(quote)]
    except Exception:                                             # noqa: BLE001
        return True              # fail open: the gate will judge it either way
    return any(abs(n - value) < 1e-9 for n in nums)


_BLOCKS_NUM = re.compile(r"[\w:./\-]")
# A digit or a decimal point beside the match means it is part of a longer
# number: "46" inside "46.0016162", "2" inside "1.2".
_IN_NUMBER = re.compile(r"[\d.]")


def _spellings(value: float) -> list:
    """How a server may have written this number, longest first.

    Only spellings that could appear literally. The parsed float is used to
    FIND the slice; it is never what the slice is made of.
    """
    out = []
    if float(value).is_integer():
        out.append(str(int(value)))
    out.append(repr(float(value)))
    out.append(str(value))
    seen, uniq = set(), []
    for c in sorted(out, key=len, reverse=True):
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def observation_date(payload, source: dict) -> tuple:
    """(data_date, reason_it_is_missing). Never today's date.

    THE SPELLING IS data_date, which config/field_names.json already registers
    for this exact concept — the date the value refers to — and which
    experiments/browser_scout/scout.py and core/provenance_pairs.py already
    write. The repo has thirteen spellings for one concept because each new
    writer picked its own; this one does not add a fourteenth.

    A source declares where its payload carries the date, with data_date_path.
    None of the four seed sources does today, and that is reported rather than
    filled in: a card whose observation date is the moment we happened to fetch
    it says the reading is fresh when what is fresh is the request.
    """
    path = source.get("data_date_path")
    if not path:
        return None, ("the source declares no data_date_path, so the payload's "
                      "own observation date is unknown; today's date would be "
                      "the date of the FETCH, not of the reading")
    try:
        got = walk(payload, path)
    except Refused as exc:
        return None, f"data_date_path {path!r} did not resolve: {exc}"
    if not isinstance(got, str) or not got.strip():
        return None, (f"data_date_path {path!r} resolved to "
                      f"{type(got).__name__} {str(got)[:40]!r}, not a date string")
    return got.strip(), None


def as_number(value, where: str) -> float:
    """The DMZ rule. Same shape as agents.axis.axis_feed.check_number."""
    if isinstance(value, bool):
        raise Refused(f"{where}: bool is not a measurement ({value!r})")
    if not isinstance(value, (int, float)):
        raise Refused(f"{where}: expected a number, got "
                      f"{type(value).__name__} {str(value)[:60]!r}")
    if not math.isfinite(float(value)):
        raise Refused(f"{where}: {value!r} is not finite")
    return float(value)


# ---------------------------------------------------------------------------
# One source
# ---------------------------------------------------------------------------

def fetch_one(source: dict, timeout: int, getter=None) -> dict:
    """Returns a feed row, or raises Refused with the reason."""
    sid = source.get("id") or "<unnamed>"
    url = source.get("url")
    if not url:
        raise Refused(f"{sid}: no url in the allowlist entry")

    t0 = time.time()
    raw = None
    if getter is not None:
        # THREE OR FOUR, and the fourth is the raw body text. A getter that
        # hands back only a parsed object cannot be quoted from — there is no
        # page left to quote — so such a row gets no card and says why. The
        # live path below always has the text.
        got = getter(url, timeout)
        if len(got) == 4:
            status, payload, err, raw = got
        else:
            status, payload, err = got
    else:
        import requests
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "CORTEX-DMZ-worker/1.0"})
            status = r.status_code
            err = None
            raw = r.text
            try:
                payload = json.loads(raw)
            except Exception:
                payload, err = None, f"body is not JSON ({raw[:60]!r})"
        except Exception as exc:  # noqa: BLE001
            status, payload, err = None, None, f"{type(exc).__name__}: {exc}"
    latency = round(time.time() - t0, 3)

    if err:
        raise Refused(f"{sid}: {err}")
    if status != 200:
        raise Refused(f"{sid}: HTTP {status}")

    path = source.get("path", "")
    value = as_number(walk(payload, path), f"{sid} at path {path!r}")

    # A COMPUTED VALUE CANNOT BE QUOTED, and pretending otherwise is how the
    # first live run produced three cards whose quotes were coincidences.
    # '#len' does not READ a number off the body; it counts the body's own
    # structure, so the number appears nowhere in the bytes and every match is
    # an accident of decimal digits. celestrak (250 objects) escaped only
    # because no "250" happened to be in its body; the three EONET counts did
    # not, and quoted a latitude and a magnitude array instead.
    computed = "#len" in path.split(".")
    quote = None if computed else quote_from_body(raw, value)
    data_date, date_missing = observation_date(payload, source)

    return {
        "ts": _now(),
        "source_id": sid,
        "axis": source.get("axis"),
        "key": source.get("key"),
        "value": value,
        "unit": source.get("unit"),
        "org": source.get("org"),
        "url": url,
        "path": source.get("path"),
        "latency_s": latency,
        "status": "PRESENT",
        # for the card, and for a human reading the feed row beside it
        "quote": quote,
        "quote_missing": None if quote else (
            f"the value is COUNTED from the body's structure (path {path!r}), so "
            f"it appears nowhere in it verbatim and cannot be quoted" if computed
            else "no raw response text" if not raw else
            f"the value {value!r} is not in the body verbatim"),
        "data_date": data_date,
        "data_date_missing": date_missing,
    }


def card_from_row(row: dict) -> dict | None:
    """The six gate fields plus the observation date, and nothing else.

    None when the row carries no quote: core.quote_gate.judge() would answer
    MALFORMED, and a card written to be refused is noise in
    memory/card_refusals.jsonl rather than a record of anything. The reason
    stays on the feed row, which is written either way.
    """
    if not row.get("quote"):
        return None
    card = {k: row.get(k) for k in CARD_FIELDS}
    if card["data_date"] is None:
        # A NAMED ABSENCE, not a blank and not today. The gate does not read
        # this key; a human comparing two readings of the same series does.
        card["data_date_missing"] = row.get("data_date_missing")
    return card


def _peer_for(axis: str, key: str, queue_dir: pathlib.Path) -> float | None:
    """The TRUSTED reading of the SAME QUANTITY, if one exists.

    THE BUG THIS FIXES, found by running it. The first version compared a
    candidate against the axis's primary metric from goal_score. Those measure
    different things: NASA-EONET reports 113 wildfire events for
    CLIMATE_GLOBAL_RISK, whose primary metric is 427.59 ppm of CO2. Every
    discovered source therefore "contradicted" the axis on its very first
    reading — 16 of them on the first live run — and since a contradiction
    resets the clean streak, NO discovered source could ever have been promoted.
    A lifecycle that can only ever refuse is not a lifecycle.

    A contradiction has to be between two claims about the SAME quantity. Until
    a trusted source exists for this (axis, key), there is no incumbent to
    disagree with, and the candidate is judged only on whether it answers and
    whether it is stable.
    """
    path = queue_dir / FEEDS.name
    if not path.exists():
        return None
    latest = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("axis") == axis and row.get("key") == key
                    and row.get("measured") and isinstance(row.get("value"), (int, float))):
                latest = float(row["value"])
    except Exception:
        return None
    return latest


def run(sources_path=None, queue_dir=None, getter=None, dry_run=False,
        discovered_path=None, lifecycle_state=None, ledger=None) -> dict:
    from core import source_lifecycle as life

    sources, timeout = all_sources(sources_path, discovered_path)
    q = pathlib.Path(queue_dir) if queue_dir else QUEUE
    own_state = lifecycle_state is None
    lstate = life.load() if own_state else lifecycle_state

    feeds, shadows, refusals, cards = [], [], [], []
    for source in sources:
        sid = source.get("id") or "<unnamed>"
        axis = source.get("axis")
        try:
            row = fetch_one(source, timeout, getter)
            rec = life.observe(sid, axis=axis, ok=True, value=row["value"],
                               peer=_peer_for(axis, source.get('key'), q),
                               state=lstate, ledger=ledger)
            row["trust"] = rec["state"]
            row["origin"] = source.get("origin")
            # ── ONLY A TRUSTED SOURCE IS A MEASUREMENT ─────────────────────
            # A candidate's number is stored beside the trusted ones and marked,
            # so it can be compared later — but it is not measured, and nothing
            # downstream may read it as one.
            row["measured"] = rec["state"] == life.TRUSTED
            row["status"] = "PRESENT" if row["measured"] else "SHADOW"
            (feeds if row["measured"] else shadows).append(row)
            # A CARD ONLY FOR A TRUSTED READING. The module's own rule two lines
            # up is that a candidate's number is stored beside the trusted ones
            # and is NOT a measurement; a card is a claim to be judged and
            # filed into memory/verified_observations.jsonl, so a shadow row
            # must not become one. Shadows and refusals keep their files.
            if row["measured"]:
                card = card_from_row(row)
                if card is not None:
                    cards.append(card)
                else:
                    print(f"[DMZ] no card  {sid:<34} {row.get('quote_missing')}")
            mark = "OK     " if row["measured"] else "shadow "
            print(f"[DMZ] {mark}{sid:<34} {str(axis):<28} "
                  f"{row['value']} {row['unit'] or ''} [{rec['state']}]")
        except Refused as exc:
            life.observe(sid, axis=axis, ok=False, reason=str(exc),
                         state=lstate, ledger=ledger)
            refusals.append({"ts": _now(), "source_id": sid, "axis": axis,
                             "key": source.get("key"), "url": source.get("url"),
                             "path": source.get("path"), "origin": source.get("origin"),
                             "status": "REFUSED", "reason": str(exc)})
            print(f"[DMZ] REFUSED {sid:<34} {exc}")

    if not dry_run:
        q.mkdir(parents=True, exist_ok=True)
        for rows, name in ((feeds, FEEDS.name), (shadows, SHADOWS.name),
                           (refusals, REFUSALS.name)):
            if rows:
                with open(q / name, "a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if cards:
            # INTO THE GATE'S OWN INBOX. core.card_intake.judge_inbox globs
            # <inbox>/*.jsonl, so the name only has to end in .jsonl and say
            # which day it came from; the date here is the FETCH day, which is
            # what a filename is for, and it is deliberately not the card's
            # observation date.
            cards_dir = q / CARDS.name
            cards_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).date().isoformat()
            with open(cards_dir / f"{day}_cards.jsonl", "a", encoding="utf-8") as fh:
                for card in cards:
                    fh.write(json.dumps(card, ensure_ascii=False) + "\n")
        if own_state:
            life.save(lstate)

    counts = life.summary(lstate)
    print(f"[DMZ] {len(feeds)} trusted / {len(shadows)} shadow / "
          f"{len(refusals)} refused / {len(cards)} card(s) of {len(sources)} sources "
          f"({counts[life.TRUSTED]} TRUSTED, {counts[life.CANDIDATE]} CANDIDATE, "
          f"{counts[life.DEMOTED]} DEMOTED)"
          f"{' — DRY RUN, nothing written' if dry_run else ''}")
    return {"ts": _now(), "sources": len(sources), "feeds": feeds,
            "shadows": shadows, "refusals": refusals, "cards": cards,
            "lifecycle": counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sources", default=None)
    ap.add_argument("--unfinished", action="store_true",
                    help="report runs that started and never finished, then exit")
    a = ap.parse_args()

    if a.unfinished:
        open_runs = unfinished_runs()
        print(json.dumps({"unfinished": open_runs}, ensure_ascii=False, indent=1))
        return 1 if open_runs else 0

    for stale in unfinished_runs():
        print(f"[DMZ] PREVIOUS RUN NEVER FINISHED: started {stale.get('ts')} "
              f"(run_id {stale.get('run_id')}) — killed, rebooted or crashed "
              f"before it could write a finish row")

    # THE CHAIN'S ID IF WE ARE IN ONE. tools/openclaw_chain.bat exports
    # CORTEX_RUN_ID so the fetch and the judge that follows it read as one
    # event; run alone, this mints its own, which is correct — it IS its own
    # event then.
    from core import task_runs as _tr
    run_id = _tr.run_id(TASK_NAME)
    started = time.time()
    _task_row({"task": TASK_NAME, "event": "start", "run_id": run_id,
               "ts": _now(), "pid": os.getpid(), "dry_run": bool(a.dry_run)})
    try:
        result = run(pathlib.Path(a.sources) if a.sources else None,
                     dry_run=a.dry_run)
    except BaseException as exc:                                  # noqa: BLE001
        # A CRASH IS A FINISH, and it is recorded as one with its reason. What
        # must stay unrecorded is a process that never got here at all — killed
        # or rebooted — and that is exactly the row this except clause does not
        # write for it.
        _task_row({"task": TASK_NAME, "event": "finish", "run_id": run_id,
                   "ts": _now(), "ok": False,
                   "seconds": round(time.time() - started, 1),
                   "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        raise
    _task_row({"task": TASK_NAME, "event": "finish", "run_id": run_id,
               "ts": _now(), "ok": True,
               "seconds": round(time.time() - started, 1),
               "sources": result["sources"],
               "trusted": len(result["feeds"]),
               "shadow": len(result["shadows"]),
               "refused": len(result["refusals"]),
               "cards": len(result["cards"])})
    return 0 if result["feeds"] else 1


if __name__ == "__main__":
    sys.exit(main())
