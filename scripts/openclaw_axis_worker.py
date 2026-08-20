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
import pathlib
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

DEFAULT_TIMEOUT = 30


class Refused(ValueError):
    """This source did not produce a number. The reason is the message."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if getter is not None:
        status, payload, err = getter(url, timeout)
    else:
        import requests
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "CORTEX-DMZ-worker/1.0"})
            status = r.status_code
            err = None
            try:
                payload = r.json()
            except Exception:
                payload, err = None, f"body is not JSON ({r.text[:60]!r})"
        except Exception as exc:  # noqa: BLE001
            status, payload, err = None, None, f"{type(exc).__name__}: {exc}"
    latency = round(time.time() - t0, 3)

    if err:
        raise Refused(f"{sid}: {err}")
    if status != 200:
        raise Refused(f"{sid}: HTTP {status}")

    value = as_number(walk(payload, source.get("path", "")),
                      f"{sid} at path {source.get('path')!r}")

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
    }


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

    feeds, shadows, refusals = [], [], []
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
        if own_state:
            life.save(lstate)

    counts = life.summary(lstate)
    print(f"[DMZ] {len(feeds)} trusted / {len(shadows)} shadow / "
          f"{len(refusals)} refused of {len(sources)} sources "
          f"({counts[life.TRUSTED]} TRUSTED, {counts[life.CANDIDATE]} CANDIDATE, "
          f"{counts[life.DEMOTED]} DEMOTED)"
          f"{' — DRY RUN, nothing written' if dry_run else ''}")
    return {"ts": _now(), "sources": len(sources), "feeds": feeds,
            "shadows": shadows, "refusals": refusals, "lifecycle": counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sources", default=None)
    a = ap.parse_args()
    result = run(pathlib.Path(a.sources) if a.sources else None,
                 dry_run=a.dry_run)
    return 0 if result["feeds"] else 1


if __name__ == "__main__":
    sys.exit(main())
