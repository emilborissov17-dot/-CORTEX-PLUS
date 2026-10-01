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
    """This source did not produce a number. The reason is the message.

    `network` is True when the fetch never reached the source (DNS, refused
    connection, timeout). A run in which EVERY network source fails that way is
    a dead network, not 25 bad sources — see run() / run_with_retry()."""

    def __init__(self, msg: str, network: bool = False):
        super().__init__(msg)
        self.network = network


def is_network_error(exc: BaseException) -> bool:
    """The fetch never reached the source: connection, DNS or timeout."""
    try:
        import requests
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True
    except Exception:                                             # noqa: BLE001
        pass
    return isinstance(exc, (ConnectionError, TimeoutError))


# ── C-OC-1 PART 1 (1 Oct 2026): A SOURCE DECLARES WHAT, WHERE AND WHEN ─────────
# Two rows in memory/verified_observations.jsonl show why. "Forest area (% of
# total land area)" = 17490 was the World Bank HEADER's row count, and an ISS card
# carried a unix timestamp under a key that says latitude/longitude/altitude.
# Both passed the quote gate because the digits were on the page. A number is
# only evidence for a claim the SOURCE declared before the fetch:
#   subcategory  resolves through core.taxonomy.subcategory()  (else REFUSED by name)
#   place        ISO3 (WLD for the world) or a named point "point:<name>"
#   unit         anything but empty / "unknown"
#   period_path  (or data_date_path) in the SAME JSON record as `path`
# A source missing any of these still fetches, but its row is SHADOW with the
# missing field named, and a shadow never becomes a card.
PLACE_RE = re.compile(r"^(?:[A-Z]{3}|point:\S.*)$")
NETWORK_RETRY_SEC = 120
EXIT_NETWORK_DOWN = 3


def _parent(path: str) -> str:
    return ".".join(str(path or "").split(".")[:-1])


def period_path_of(source: dict) -> str | None:
    return source.get("period_path") or source.get("data_date_path")


def declaration_problems(source: dict) -> list:
    """Every missing or malformed declaration, named. [] means fully declared.
    Does NOT check that the subcategory resolves — an unresolvable one is a
    refusal (subcategory_problem), not a shadow."""
    out = []
    if not source.get("subcategory"):
        out.append("subcategory: not declared")
    place = source.get("place")
    if not place:
        out.append("place: not declared")
    elif not PLACE_RE.match(str(place)):
        out.append(f"place: {place!r} is not ISO3, WLD or point:<name>")
    unit = str(source.get("unit") or "").strip()
    if not unit or unit.lower() == "unknown":
        out.append(f"unit: {source.get('unit')!r} is not a unit")
    path = str(source.get("path") or "")
    pp = period_path_of(source)
    if source.get("parallel"):
        # value and period come from PARALLEL ARRAYS by a declared entity index
        # (C-OC-3): the spec itself declares both, so no path/period_path applies.
        return out
    if "#len" in path.split("."):
        out.append("path: counts a list (#len) — there is no record to quote or to date")
    if not pp:
        out.append("period_path: not declared")
    elif _parent(pp) != _parent(path):
        out.append(f"period_path: {pp!r} is not in the same record as path {path!r}")
    return out


def card_eligible(row: dict, state: str) -> bool:
    """C-OC-3 (Emil, R27): one criterion, and it is on us. A reading becomes a
    card when we can QUOTE it from the page; the gate then checks the quote is
    really there. No declaration, period, place, unit or ladder history is
    required — those are labels."""
    return bool(row.get("quote"))


def subcategory_problem(source: dict) -> str | None:
    """A DECLARED subcategory that does not resolve is a refusal, by name."""
    sub = source.get("subcategory")
    if not sub:
        return None
    try:
        from core import taxonomy as _tx
        _tx.subcategory(sub)
    except Exception as exc:                                      # noqa: BLE001
        return f"subcategory {sub!r} does not resolve in config/taxonomy.json ({exc})"
    return None


def worldbank_header_problem(payload, path: str) -> str | None:
    """World Bank v2 bodies are [header, [rows]]. Element 0 is paging metadata
    (page, pages, per_page, total, lastupdated) — never an observation."""
    if (isinstance(payload, list) and len(payload) == 2 and isinstance(payload[0], dict)
            and {"page", "pages", "total"} <= set(payload[0])
            and str(path or "").split(".")[0] == "0"):
        return "World Bank header, not an observation"
    return None


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


def is_web_source(src: dict) -> bool:
    """A discovered source the worker may fetch: a URL-located kind with an http(s)
    URL. memory/discovered_data_sources.json is shared with the composers, whose
    kind "file" (url local://snapshots/...) reads a file on this machine; found on
    1 Oct 2026 failing as InvalidSchema on every worker run."""
    from core import source_registration as sr
    rule = sr.KIND_RULES.get(src.get("kind"))
    if rule is not None and rule.get("location") != "url":
        return False
    return str(src.get("url") or "").lower().startswith(("http://", "https://"))


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
            if not is_web_source(src):
                continue                 # a composer's local file is not a web source (C-TURN-1 7c)
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
CARD_FIELDS = ("axis", "key", "value", "unit", "url", "quote", "data_date",
               "subcategory", "place", "period", "period_how",
               "place_how", "unit_how", "subcategory_how")
# Card fields that are LABELS about how a value is known, not observation dates.
# test_the_spelling_is_the_one_the_registry_already_carries skips exactly these.
CARD_LABEL_FIELDS = ("period_how", "place_how", "unit_how", "subcategory_how", "subcategory", "place")

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


def quote_from_record(raw: str, payload, path: str, value: float,
                      width: int = _QUOTE_WIDTH) -> str | None:
    """A verbatim slice that starts AT the value and stays inside THE record the
    path walked — never the first textual match of the digits in the body.

    The record is the JSON object holding the value (the parent of `path`). Each
    textual occurrence of the value is checked: the smallest {...} around it is
    cut from the raw bytes, parsed, and must EQUAL the walked record. Only then is
    the quote taken, from the value to the record's end (capped at `width`).
    It starts at the value because compact JSON writes `"value":31.09`, and the
    gate's standalone-number rule cannot see a number behind a colon.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        record = walk(payload, _parent(path)) if _parent(path) else payload
    except Refused:
        return None
    if not isinstance(record, dict):
        return None
    from core.observation_record import _balanced_object
    for cand in _spellings(value):
        i = raw.find(cand)
        while i != -1:
            end = i + len(cand)
            if not (_IN_NUMBER.match(raw[i - 1:i]) or _IN_NUMBER.match(raw[end:end + 1])):
                a, b = _balanced_object(raw, i)
                if a != -1:
                    try:
                        same = json.loads(raw[a:b]) == record
                    except ValueError:
                        same = False
                    if same:
                        cut = raw[i:min(b, i + width)]
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

class NoMeasurement(Exception):
    """The page was fetched (and enters the store as statements), but no number
    could be read at the declared path. NOT a refusal of the page (C-OC-3)."""


def get_page(source: dict, timeout: int, getter=None) -> dict:
    """One GET. -> {status, payload (parsed JSON or None), raw, err, network,
    latency, content_type}. A non-JSON body is NOT an error: it is a page."""
    url = source.get("url")
    t0 = time.time()
    raw, payload, err, status, network, ctype = None, None, None, None, False, ""
    if getter is not None:
        try:
            got = getter(url, timeout)
        except Exception as exc:  # noqa: BLE001
            got = (None, None, f"{type(exc).__name__}: {exc}")
            network = is_network_error(exc)
        if len(got) == 4:
            status, payload, err, raw = got
        else:
            status, payload, err = got
    else:
        # the fetch standard (C-OC-3 Part 2): GET only, no credentials or cookies,
        # no private/loopback/LAN address on any hop, <= 5 MB, <= 30 s, 2 s per host
        from core import fetch_standard as _fs
        try:
            got = _fs.get(url, timeout=min(timeout, _fs.TIMEOUT_S))
            status, raw, ctype = got["status"], got["raw"], got["content_type"]
            try:
                payload = json.loads(raw)
            except Exception:  # noqa: BLE001
                payload = None
        except _fs.FetchRefused as exc:
            status, err = None, f"REFUSED_BY_FETCH_STANDARD: {exc}"
        except Exception as exc:  # noqa: BLE001
            status, err = None, f"{type(exc).__name__}: {exc}"
            network = is_network_error(exc)
    return {"status": status, "payload": payload, "raw": raw, "err": err, "network": network,
            "latency": round(time.time() - t0, 3), "content_type": ctype}


def _parallel_reading(source: dict, payload) -> tuple:
    """Value and period from PARALLEL ARRAYS (values[i], periods[i], entities[i]),
    as Our World in Data serves them: the entity is declared, the newest period
    for that entity is taken. -> (value, period)."""
    spec = source["parallel"]
    vals, pers, ents = (walk(payload, spec["values"]), walk(payload, spec["periods"]),
                        walk(payload, spec["entities"]))
    if not (isinstance(vals, list) and isinstance(pers, list) and isinstance(ents, list)
            and len(vals) == len(pers) == len(ents)):
        raise NoMeasurement("parallel arrays missing or of unequal length")
    idx = [i for i, e in enumerate(ents) if e == spec["entity"]]
    if not idx:
        raise NoMeasurement(f"entity {spec['entity']!r} not in the arrays")
    i = max(idx, key=lambda n: pers[n])
    return vals[i], pers[i]


def fetch_one(source: dict, timeout: int, getter=None, page: dict | None = None) -> dict:
    """The MEASUREMENT read from one page. Raises Refused for an unreachable page
    or for a LABEL that contradicts the page's own structure (the World Bank
    header count named as an indicator); raises NoMeasurement when no number is
    at the declared path. Neither stops the page from entering as statements."""
    sid = source.get("id") or "<unnamed>"
    url = source.get("url")
    if not url:
        raise Refused(f"{sid}: no url")
    page = page or get_page(source, timeout, getter)
    if page["err"]:
        raise Refused(f"{sid}: {page['err']}", network=page["network"])
    if page["status"] != 200:
        raise Refused(f"{sid}: HTTP {page['status']}")
    payload, raw = page["payload"], page["raw"]
    path = source.get("path", "")
    undeclared = declaration_problems(source)        # LABELS missing, never a gate
    period, period_how = None, "unknown"
    if source.get("parallel"):
        if payload is None:
            raise NoMeasurement("body is not JSON")
        v, per = _parallel_reading(source, payload)
        try:
            value = as_number(v, f"{sid} parallel value")
        except Refused as exc:
            raise NoMeasurement(str(exc))
        period, period_how = str(per), "parallel_index"
        quote = quote_from_body(raw, value)
        computed = False
    else:
        if payload is None:
            raise NoMeasurement("body is not JSON: no path to walk (the page still enters as statements)")
        header = worldbank_header_problem(payload, path)
        if header:
            raise Refused(f"{sid}: {header} (path {path!r})")
        try:
            value = as_number(walk(payload, path), f"{sid} at path {path!r}")
        except Refused as exc:
            raise NoMeasurement(str(exc))
        pp = period_path_of(source)
        if pp and not any(u.startswith("period_path") for u in undeclared):
            try:
                got_p = walk(payload, pp)
            except Refused as exc:
                undeclared.append(f"period_path: {pp!r} did not resolve ({exc})")
            else:
                if isinstance(got_p, bool) or not isinstance(got_p, (str, int)) or not str(got_p).strip():
                    undeclared.append(f"period_path: {pp!r} resolved to {type(got_p).__name__}, not a period")
                else:
                    # C-OC-3 Part 0: a period from the feed's own clock is a
                    # processing time (or a rolling window's end day).
                    from core.atoms import classify_period
                    period, period_how = classify_period(pp, str(got_p).strip(),
                                                         rolling=bool(source.get("rolling_window")))
        # A COMPUTED VALUE ('#len') CANNOT BE QUOTED: it appears nowhere in the bytes.
        computed = "#len" in path.split(".")
        quote = None if computed else quote_from_record(raw, payload, path, value)
        if quote is None and not computed:
            # the walked record did not contain it verbatim; fall back to the page
            q2 = quote_from_body(raw, value)
            if q2 is not None:
                quote, period_how = q2, period_how
    data_date, date_missing = observation_date(payload, source) if payload is not None else (None, "no JSON")
    unit = source.get("unit")
    return {
        "ts": _now(), "source_id": sid, "axis": source.get("axis") or "UNPLACED",
        "key": source.get("key") or sid, "value": value,
        "unit": unit if unit not in (None, "") else "unknown",
        "org": source.get("org"), "url": url, "path": path, "latency_s": page["latency"],
        "status": "PRESENT",
        "quote": quote,
        "quote_missing": None if quote else (
            f"the value is COUNTED from the body's structure (path {path!r}) and cannot be quoted" if computed
            else "no raw response text" if not raw else f"the value {value!r} is not on the page verbatim"),
        "data_date": data_date, "data_date_missing": date_missing,
        "subcategory": source.get("subcategory"),
        "place": source.get("place"),
        "period": period,
        "period_how": period_how,
        "place_how": "declared" if source.get("place") else "unknown",
        "unit_how": "declared" if unit not in (None, "", "unknown") else "unknown",
        "subcategory_how": "declared" if source.get("subcategory") else "unknown",
        "undeclared": undeclared,
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
        discovered_path=None, lifecycle_state=None, ledger=None, ingest=None,
        parking=None, wanted=None) -> dict:
    """One pass. C-OC-3: EVERY fetched page enters the store as statements (via
    `ingest`, which main() passes as core.knowledge.ingest; a library or test
    call passes nothing and nothing is written). In addition, a number read at
    the declared path becomes a card for the gate. Only two refusals remain, both
    of OUR claim: a quote not on the page (the gate) and a label that
    contradicts the page's own structure (the World Bank header)."""
    from core import source_lifecycle as life

    sources, timeout = all_sources(sources_path, discovered_path)
    q = pathlib.Path(queue_dir) if queue_dir else QUEUE
    own_state = lifecycle_state is None
    lstate = life.load() if own_state else lifecycle_state

    from core import fetch_standard as _fs
    wanted = set(wanted or ())
    feeds, carded, stored, refusals, unreachable, cards, parked = [], [], [], [], [], [], []
    pages = {"ingested": 0, "skipped_same_content": 0, "statements_added": 0,
             "page_only": 0, "needs": []}
    for source in sources:
        sid = source.get("id") or "<unnamed>"
        axis = source.get("axis")
        sub_bad = subcategory_problem(source)
        if sub_bad:
            # a wrong LABEL is dropped, the source is not
            source = {**source, "subcategory": None}
        # PARKED after 3 consecutive failures; a need that names it unparks it
        if parking is not None and _fs.is_parked(sid, parking):
            if sid in wanted:
                _fs.unpark(sid, "named by a need", parking)
            else:
                parked.append({"ts": _now(), "source_id": sid, "status": "PARKED"})
                continue
        page = get_page(source, timeout, getter)
        if parking is not None:
            _fs.record(sid, ok=not page["err"] and page["status"] == 200,
                       err=page["err"] or f"HTTP {page['status']}", path=parking)
        if page["err"] or page["status"] != 200:
            reason = page["err"] or f"HTTP {page['status']}"
            life.observe(sid, axis=axis, ok=False, reason=reason, state=lstate, ledger=ledger)
            unreachable.append({"ts": _now(), "source_id": sid, "axis": axis, "key": source.get("key"),
                                "url": source.get("url"), "status": "UNREACHABLE", "reason": f"{sid}: {reason}",
                                "network": bool(page["network"])})
            print(f"[DMZ] UNREACHABLE {sid:<30} {reason[:120]}")
            continue
        # ── the page, WHOLE, into the store the brain reads ────────────────
        if ingest is not None and not dry_run:
            from core import knowledge as _kn
            try:
                text, form = _kn.body_to_text(page["raw"], page["payload"], page["content_type"])
            except _kn.FlattenLostValue as exc:
                text, form = page["raw"] or "", f"raw_text ({exc})"
            if form == "pdf_unreadable":
                pages["needs"].append({"source_id": sid, "need": "a PDF reader (none installed)"})
            else:
                rep = ingest(sid, text, url=source.get("url", ""), origin="web",
                             **({"extra": {"granularity": "record"}} if form == "json" else {}))
                if rep.get("outcome") == "SKIPPED_SAME_CONTENT":
                    pages["skipped_same_content"] += 1
                else:
                    pages["ingested"] += 1
                    pages["statements_added"] += rep.get("added", 0)
        # ── and, in addition, the measurement ─────────────────────────────
        try:
            row = fetch_one(source, timeout, page=page)
        except NoMeasurement as exc:
            pages["page_only"] += 1
            stored.append({"ts": _now(), "source_id": sid, "url": source.get("url"),
                           "status": "STORED", "reason": str(exc)})
            continue
        except Refused as exc:
            refusals.append({"ts": _now(), "source_id": sid, "axis": axis, "key": source.get("key"),
                             "url": source.get("url"), "path": source.get("path"),
                             "status": "LABEL_REFUSED", "reason": str(exc), "network": False})
            print(f"[DMZ] LABEL REFUSED {sid:<28} {exc} — the page itself entered as statements")
            continue
        rec = life.observe(sid, axis=axis, ok=True, value=row["value"],
                           peer=_peer_for(axis, source.get('key'), q), state=lstate, ledger=ledger)
        row["trust"] = rec["state"]
        row["origin"] = source.get("origin")
        # The COMPOSITE still reads only TRUSTED and declared readings.
        row["measured"] = rec["state"] == life.TRUSTED and not row["undeclared"]
        eligible = card_eligible(row, rec["state"])
        row["status"] = "PRESENT" if row["measured"] else ("CARDED" if eligible else "STORED")
        (feeds if row["measured"] else carded if eligible else stored).append(row)
        if eligible:
            card = card_from_row(row)
            if card is not None:
                cards.append(card)
        print(f"[DMZ] {row['status']:<8}{sid:<34} {row['value']} {row['unit'] or ''} [{rec['state']}]")

    if not dry_run:
        q.mkdir(parents=True, exist_ok=True)
        for rows, name in ((feeds, FEEDS.name), (carded + stored, SHADOWS.name),
                           (refusals + unreachable, REFUSALS.name)):
            if rows:
                with open(q / name, "a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if cards:
            cards_dir = q / CARDS.name
            cards_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).date().isoformat()
            with open(cards_dir / f"{day}_cards.jsonl", "a", encoding="utf-8") as fh:
                for card in cards:
                    fh.write(json.dumps(card, ensure_ascii=False) + "\n")
        if own_state:
            life.save(lstate)

    counts = life.summary(lstate)
    print(f"[DMZ] {len(feeds)} trusted / {len(carded)} carded / {len(stored)} stored / "
          f"{len(refusals)} label-refused / {len(unreachable)} unreachable / {len(cards)} card(s) of "
          f"{len(sources)} sources; pages ingested {pages['ingested']} (+{pages['statements_added']} statements), "
          f"same content {pages['skipped_same_content']}"
          f"{' — DRY RUN, nothing written' if dry_run else ''}")
    net_sources = [s for s in sources if str(s.get("url", "")).lower().startswith(("http://", "https://"))]
    net_fail = [r for r in unreachable if r.get("network")
                and str(r.get("url", "")).lower().startswith(("http://", "https://"))]
    network_down = (bool(net_sources) and not feeds and not carded and not stored
                    and len(net_fail) == len(net_sources))
    return {"ts": _now(), "sources": len(sources), "feeds": feeds,
            "carded": carded, "declared": carded, "stored": stored, "shadows": stored,
            "refusals": refusals, "unreachable": unreachable, "parked": parked, "cards": cards, "pages": pages,
            "lifecycle": counts, "network_down": network_down}


def run_with_retry(runner, sleep=None) -> dict:
    """One pass; if the network was down for the whole pass, wait
    NETWORK_RETRY_SEC and run the whole pass ONCE more. The returned result is
    the second pass, marked retried, with the first pass's counts beside it."""
    sleep = sleep or time.sleep
    first = runner()
    if not first.get("network_down"):
        first["retried"] = False
        return first
    print(f"[DMZ] NETWORK DOWN: every network source failed on the connection; "
          f"retrying the whole pass once in {NETWORK_RETRY_SEC} s")
    sleep(NETWORK_RETRY_SEC)
    second = runner()
    second["retried"] = True
    second["first_pass"] = {"sources": first["sources"], "refused": len(first["refusals"])}
    return second


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
        from core import knowledge as _kn
        from core import fetch_standard as _fs_main
        result = run_with_retry(lambda: run(pathlib.Path(a.sources) if a.sources else None,
                                            dry_run=a.dry_run, ingest=_kn.ingest,
                                            parking=_fs_main.PARKING))
    except BaseException as exc:                                  # noqa: BLE001
        # A CRASH IS A FINISH, recorded with its reason and then RE-RAISED.
        # Nothing is swallowed here; what must stay unrecorded is a process that
        # never got here at all — killed or rebooted — and that is exactly the
        # row this clause does not write for it.
        #
        # WHY BaseException AND NOT Exception. Measured 21 Sep 2026: run() is
        # not a generator, so GeneratorExit cannot arrive, and the only sys.exit
        # in this module is at the bottom, outside main() — so SystemExit cannot
        # arise from the call path. What remains is KeyboardInterrupt. Under
        # `except Exception` a Ctrl-C would leave a start with no finish, the
        # row shape that means "killed by a reboot", and nothing ever clears it:
        # unfinished_runs() would announce that phantom at the top of every
        # future run for ever.
        #
        # NOTHING IS LOST BY IT EITHER. The feed, shadow, refusal and card
        # writes all happen inside run() before it returns; an interrupt mid-run
        # leaves them exactly as they were, and the cards it did not reach are
        # re-judged next run because judge_inbox rebuilds `seen` from its own
        # output files.
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
               "carded": len(result.get("carded", [])),
               "stored": len(result.get("stored", [])),
               "label_refused": len(result["refusals"]),
               "unreachable": len(result.get("unreachable", [])),
               "parked": len(result.get("parked", [])),
               "pages_ingested": (result.get("pages") or {}).get("ingested", 0),
               "statements_added": (result.get("pages") or {}).get("statements_added", 0),
               "pages_same_content": (result.get("pages") or {}).get("skipped_same_content", 0),
               "needs": (result.get("pages") or {}).get("needs", []),
               "cards": len(result["cards"]),
               "network_down": bool(result.get("network_down")),
               "retried": bool(result.get("retried"))})
    if result.get("network_down"):
        return EXIT_NETWORK_DOWN
    return 0 if result["feeds"] else 1


if __name__ == "__main__":
    sys.exit(main())
