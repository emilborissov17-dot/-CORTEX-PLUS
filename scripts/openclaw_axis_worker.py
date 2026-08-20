#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/openclaw_axis_worker.py — THE DMZ FETCH WORKER.

WHAT CROSSES, AND WHAT DOES NOT
--------------------------------
This is the only thing in CORTEX that reaches the outside world for an axis
number, and it is deliberately small enough to read in one sitting.

    IN   a URL from config/openclaw_sources.json, and nothing else
    OUT  one finite NUMBER bound to (axis, key), or a named refusal

Same contract as agents/axis/axis_feed.py, applied one step further out. There
the risk was a model writing prose where a measurement belonged; here it is a
remote service answering with a string, a null, an error object or an HTML
error page, and that landing in the queue as if someone had measured it.

config/openclaw_sources.json IS THE ALLOWLIST. The worker fetches nothing that
is not named there, so widening what CORTEX touches is a human edit to a config
file rather than something a model can decide at runtime.
docs/OPENCLAW_INTEGRATION_DESIGN.md: "Неизвестното = изисква одобрение."

REFUSALS ARE WRITTEN DOWN, NOT DROPPED
---------------------------------------
openclaw_queue/external_refusals.jsonl gets a row with the reason: HTTP status,
unreadable body, path that does not resolve, or a value that is not a number.
A source that has quietly rotted must look different from a source nobody
asked. One entry in the allowlist is broken ON PURPOSE so that the refusal path
is exercised on every real run, not only under test.

    venv\\Scripts\\python.exe scripts/openclaw_axis_worker.py          # fetch
    venv\\Scripts\\python.exe scripts/openclaw_axis_worker.py --dry-run
"""
from __future__ import annotations

import argparse
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

DEFAULT_TIMEOUT = 30


class Refused(ValueError):
    """This source did not produce a number. The reason is the message."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sources(path: pathlib.Path | None = None) -> tuple[list[dict], int]:
    cfg = json.loads((path or SOURCES).read_text(encoding="utf-8"))
    return cfg.get("sources", []), int(cfg.get("timeout_sec", DEFAULT_TIMEOUT))


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


def run(sources_path=None, queue_dir=None, getter=None, dry_run=False) -> dict:
    sources, timeout = load_sources(sources_path)
    q = pathlib.Path(queue_dir) if queue_dir else QUEUE

    feeds, refusals = [], []
    for source in sources:
        try:
            row = fetch_one(source, timeout, getter)
            feeds.append(row)
            print(f"[DMZ] OK      {row['source_id']:<26} {row['axis']:<28} "
                  f"{row['value']} {row['unit'] or ''}")
        except Refused as exc:
            refusal = {"ts": _now(), "source_id": source.get("id"),
                       "axis": source.get("axis"), "key": source.get("key"),
                       "url": source.get("url"), "path": source.get("path"),
                       "status": "REFUSED", "reason": str(exc)}
            refusals.append(refusal)
            print(f"[DMZ] REFUSED {source.get('id'):<26} {exc}")

    if not dry_run:
        q.mkdir(parents=True, exist_ok=True)
        if feeds:
            with open(q / FEEDS.name, "a", encoding="utf-8") as fh:
                for row in feeds:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if refusals:
            with open(q / REFUSALS.name, "a", encoding="utf-8") as fh:
                for row in refusals:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[DMZ] {len(feeds)} feed(s), {len(refusals)} refusal(s) "
          f"of {len(sources)} allowlisted source(s)"
          f"{' — DRY RUN, nothing written' if dry_run else ''}")
    return {"ts": _now(), "sources": len(sources), "feeds": feeds,
            "refusals": refusals}


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
