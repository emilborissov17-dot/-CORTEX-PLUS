#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/snapshot.py — ONE SELF-CONTAINED HTML FILE OF WHAT THE COCKPIT SEES.

Renders every read-only endpoint once, inlines the results into a single HTML
file, and writes it to output/cockpit_snapshot.html.

PUBLISHING IS NOT WIRED, ON PURPOSE
-------------------------------------
This writes a file. It does not upload it, does not call scripts/publish_reports.py,
and does not put it anywhere a browser outside this machine can reach. The
snapshot contains the active window title, the Wi-Fi SSID, the machine's
uptime and its process list summary — a picture of somebody's desk. Wiring a
publish step to that by default would be a decision nobody made out loud.

The terminal is deliberately ABSENT from a snapshot: a static file cannot hold a
shell, and rendering a dead terminal panel would suggest otherwise.

A snapshot is a MOMENT, and says so in its header. Nothing in it refreshes; the
timestamps are the timestamps of the read.

    venv/Scripts/python.exe -m cockpit.snapshot
    venv/Scripts/python.exe -m cockpit.snapshot --out somewhere/else.html
"""
from __future__ import annotations

import html
import json
import pathlib
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

DEFAULT_OUT = BASE / "output" / "cockpit_snapshot.html"

# Read-only endpoints only. The two writeful ones and the WS bridge are absent
# by construction rather than by filtering.
ENDPOINTS = ("/api/panels", "/api/cycles", "/api/flow", "/api/pending",
             "/api/proposals", "/api/goal", "/api/columns", "/api/expression",
             "/api/thoughts", "/api/somatic", "/api/forks")

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>CORTEX++ cockpit snapshot {ts}</title>
<style>
 body{{margin:0;background:#0b0e12;color:#c7d0da;
      font:13px/1.45 Consolas,ui-monospace,monospace}}
 header{{padding:12px 16px;border-bottom:1px solid #1e242c}}
 h1{{font-size:14px;letter-spacing:.14em;margin:0}}
 .muted{{color:#6b7683}}
 section{{margin:12px 16px;border:1px solid #1e242c;border-radius:5px;padding:10px 12px;
         background:#12161c}}
 h2{{font-size:11px;letter-spacing:.16em;color:#6b7683;margin:0 0 8px;
     text-transform:uppercase}}
 pre{{white-space:pre-wrap;word-break:break-word;margin:0;font-size:11px;
     max-height:460px;overflow:auto;color:#9aa5b1}}
 .warn{{color:#d8b13a}}
</style></head><body>
<header>
 <h1>CORTEX++ COCKPIT — SNAPSHOT</h1>
 <div class="muted">read at {ts} · this is a MOMENT, nothing here refreshes</div>
 <div class="warn">the terminal is absent from a snapshot: a static file cannot
  hold a shell, and drawing a dead panel would suggest otherwise</div>
</header>
{body}
<section><h2>provenance</h2><pre>{prov}</pre></section>
</body></html>
"""


def render(endpoints=ENDPOINTS) -> str:
    from cockpit.server import app
    app.config["TESTING"] = True
    client = app.test_client()

    parts, prov = [], []
    for ep in endpoints:
        try:
            r = client.get(ep)
            blob = r.get_json()
            status = r.status_code
        except Exception as e:                       # noqa: BLE001
            blob = {"error": "{}: {}".format(type(e).__name__, e)}
            status = 500
        prov.append("{:<26} {}".format(ep, status))
        parts.append("<section><h2>{}</h2><pre>{}</pre></section>".format(
            html.escape(ep),
            html.escape(json.dumps(blob, ensure_ascii=False, indent=2)[:200000])))

    ts = datetime.now(timezone.utc).isoformat()
    return _TEMPLATE.format(ts=html.escape(ts), body="\n".join(parts),
                            prov=html.escape("\n".join(prov)))


def write(out_path: pathlib.Path) -> pathlib.Path:
    """Write the snapshot. `out_path` is REQUIRED — no default."""
    p = pathlib.Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(), encoding="utf-8")
    return p


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Write a static cockpit snapshot.")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    p = write(pathlib.Path(args.out))
    print("snapshot written: {} ({:,} bytes)".format(p, p.stat().st_size))
    print("PUBLISHING IS NOT WIRED. This file contains the active window title, "
          "the Wi-Fi SSID and machine uptime; it is a picture of somebody's desk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
