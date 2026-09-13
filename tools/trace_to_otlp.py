#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/trace_to_otlp.py — the trace, in the shape a tracing backend expects.

JSONL in, OTLP/JSON out: resourceSpans -> scopeSpans -> spans, with "ev" rows
folded into span.events.

NOT CALLED BY THE CYCLE, and no SDK is installed to do it. That is the whole
point of the split. On 12 Sep 2026 cortex_reasoner died with

    ModuleNotFoundError: opentelemetry.exporter.otlp.proto.common._exporter_metrics

because one package of a transitive family was a minor version out of step. The
recorder therefore writes plain JSON that cannot break, and this converter — which
runs later, by hand, and can fail without costing a night — produces the
interchange format. A dependency that can stop the cycle has no business inside
the cycle.

AN UNCLOSED SPAN IS EXPORTED, NOT DROPPED. status.code = 2 (ERROR),
attributes.unclosed = true, and endTimeUnixNano set to the last timestamp the
trace ever saw. Dropping it would hide the one span that says where the process
died, which is the most valuable row in the file.

    venv\\Scripts\\python.exe tools\\trace_to_otlp.py --out claude\\reports\\trace.otlp.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE_DIR = REPO / "memory" / "cycle_trace"

UNSET, OK, ERROR = 0, 1, 2
CODE = {"UNSET": UNSET, "OK": OK, "ERROR": ERROR}


def newest_trace():
    if not TRACE_DIR.is_dir():
        return None
    files = sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _attrs(d: dict) -> list:
    """OTLP KeyValue list. None becomes a real null, not the string 'None'."""
    out = []
    for k, v in (d or {}).items():
        if v is None:
            val = {"stringValue": ""}
        elif isinstance(v, bool):
            val = {"boolValue": v}
        elif isinstance(v, int):
            val = {"intValue": str(v)}
        elif isinstance(v, float):
            val = {"doubleValue": v}
        elif isinstance(v, (list, tuple)):
            val = {"arrayValue": {"values": [{"stringValue": str(x)} for x in v]}}
        else:
            val = {"stringValue": str(v)}
        out.append({"key": str(k), "value": val})
    return out


def _ns(t0_epoch: float, t: float) -> str:
    return str(int((t0_epoch + float(t or 0.0)) * 1e9))


def convert(rows: list) -> dict:
    head = next((r for r in rows if r.get("k") == "head"), {})
    trace_id = str(head.get("trace_id") or "0" * 32)
    t0_iso = head.get("t0")
    try:
        t0_epoch = time.mktime(time.strptime(t0_iso, "%Y-%m-%dT%H:%M:%SZ"))
        t0_epoch -= time.timezone if not time.daylight else time.altzone
    except Exception:
        t0_epoch = 0.0

    opens = {r["sp"]: r for r in rows if r.get("k") == "open"}
    spans = [r for r in rows if r.get("k") == "span"]
    evs = [r for r in rows if r.get("k") == "ev"]

    last_t = 0.0
    for r in rows:
        for key in ("t_end", "t"):
            v = r.get(key)
            if isinstance(v, (int, float)):
                last_t = max(last_t, v)

    ev_by_span = {}
    for e in evs:
        ev_by_span.setdefault(e.get("sp"), []).append({
            "timeUnixNano": _ns(t0_epoch, e.get("t")),
            "name": str(e.get("name")),
            "attributes": _attrs(e.get("attr") or {}),
        })

    out_spans = []
    closed = set()
    for s in spans:
        sp = s.get("sp")
        closed.add(sp)
        o = opens.get(sp, {})
        out_spans.append({
            "traceId": trace_id,
            "spanId": str(sp),
            "parentSpanId": str(s.get("pa") or o.get("pa") or ""),
            "name": str(s.get("name")),
            "kind": 1,
            "startTimeUnixNano": _ns(t0_epoch, s.get("t")),
            "endTimeUnixNano": _ns(t0_epoch, s.get("t_end")),
            "attributes": _attrs({**(o.get("attr") or {}), **(s.get("attr") or {})}),
            "events": ev_by_span.get(sp, []),
            "status": {"code": CODE.get(str(s.get("st")), UNSET)},
        })

    for sp, o in opens.items():
        if sp in closed:
            continue
        out_spans.append({
            "traceId": trace_id,
            "spanId": str(sp),
            "parentSpanId": str(o.get("pa") or ""),
            "name": str(o.get("name")),
            "kind": 1,
            "startTimeUnixNano": _ns(t0_epoch, o.get("t")),
            "endTimeUnixNano": _ns(t0_epoch, last_t),
            "attributes": _attrs({**(o.get("attr") or {}), "unclosed": True}),
            "events": ev_by_span.get(sp, []),
            "status": {"code": ERROR,
                       "message": "no span record: the process stopped inside it"},
        })

    orphan = ev_by_span.get(None, [])
    return {
        "resourceSpans": [{
            "resource": {"attributes": _attrs({
                "service.name": "cortex-cycle",
                "cycle.id": head.get("cycle_id"),
                "process.pid": head.get("pid"),
                "process.runtime.version": head.get("py"),
                "cortex.unattributed_events": len(orphan),
            })},
            "scopeSpans": [{
                "scope": {"name": "core.flight_recorder", "version": "1"},
                "spans": out_spans,
            }],
        }]
    }


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    trace = Path(a.trace) if a.trace else newest_trace()
    if trace is None or not trace.is_file():
        print("no trace found in memory/cycle_trace/")
        return 1
    rows = []
    for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    doc = convert(rows)
    out = Path(a.out) if a.out else (REPO / "claude" / "reports" /
                                     (trace.stem + ".otlp.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(doc["resourceSpans"][0]["scopeSpans"][0]["spans"])
    unclosed = sum(1 for s in doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
                   if any(k["key"] == "unclosed" for k in s["attributes"]))
    print(f"{n} spans ({unclosed} unclosed, exported as ERROR) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
