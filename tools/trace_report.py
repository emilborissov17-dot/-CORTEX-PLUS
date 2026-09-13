#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/trace_report.py — turn a cycle trace into a page a human can read.

Writes claude/reports/TRACE_<date>.md and TRACE_<date>.html.

THE ARITHMETIC IS THE POINT, and it is printed with words rather than left for
the reader to attempt. Sum of the "step:*" spans, plus the unattributed seconds,
against the wall clock. Nested "call:" spans are excluded from that sum on
purpose: they run INSIDE their step and adding them would count the same seconds
twice, which is how a report ends up claiming more time than the night had.

When the sum does not close, the gap is stated in seconds and named. It is not
distributed over the steps to make it disappear.

EVERY STEP OF core/cycle_map.STEPS GETS A ROW, including the ones that never ran.
A step that produced nothing must read as 0, not as absent: absent is what 32
steps looked like before this file existed, and it is indistinguishable from a
step that does not exist.

    venv\\Scripts\\python.exe tools\\trace_report.py
    venv\\Scripts\\python.exe tools\\trace_report.py --trace memory\\cycle_trace\\X.jsonl
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
TRACE_DIR = REPO / "memory" / "cycle_trace"
OUT_DIR = REPO / "claude" / "reports"


def _show(p: Path) -> str:
    """A path for a human. A trace under tmp_path is not relative to the repo, and
    Path.relative_to RAISES rather than shrugging — which turned three tests red
    with a ValueError from inside the report, not from the thing being reported."""
    try:
        return str(p.relative_to(REPO)).replace(chr(92), "/")
    except ValueError:
        return str(p)


def newest_trace() -> Path | None:
    if not TRACE_DIR.is_dir():
        return None
    files = sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load(path: Path) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue        # a half-written last line from a killed process
    return rows


def all_steps() -> list:
    try:
        from core.cycle_map import STEPS
        return [(s[0], s[1]) for s in STEPS]
    except Exception:
        return []


def _canonical(label: str) -> str:
    """The step name a _run() LABEL belongs to.

    The trace writes step:<_run label> — "internet_agent". cycle_map knows the
    STEP — "internet_intelligence". Matching the two by string made the report say
    "1 of 75 steps left a span" on a cycle where two had: daily_tier matched
    because its label happens to equal its name, cortex_strategist_agent did not.
    core.cycle_map already owns this table; step_audit already goes through it.
    """
    try:
        from core.cycle_map import _canon
        return _canon(label) or label
    except Exception:
        return label


def fold(rows: list) -> dict:
    head = next((r for r in rows if r.get("k") == "head"), {})
    opens, spans, evs = {}, [], []
    for r in rows:
        k = r.get("k")
        if k == "open":
            opens[r["sp"]] = r
        elif k == "span":
            spans.append(r)
        elif k == "ev":
            evs.append(r)

    closed = {s["sp"] for s in spans}
    unclosed = [o for sp, o in opens.items() if sp not in closed]

    last_t = 0.0
    for r in rows:
        for key in ("t_end", "t"):
            v = r.get(key)
            if isinstance(v, (int, float)):
                last_t = max(last_t, v)
    for e in evs:
        v = (e.get("attr") or {}).get("t_end")
        if isinstance(v, (int, float)):
            last_t = max(last_t, v)

    # span id -> the step it belongs to, following parents up
    parent = {}
    name_of = {}
    for sp, o in opens.items():
        parent[sp] = o.get("pa")
        name_of[sp] = o.get("name", "")

    def step_of(sp):
        seen = set()
        while sp and sp not in seen:
            seen.add(sp)
            n = name_of.get(sp, "")
            if n.startswith("step:"):
                return _canonical(n[5:])
            sp = parent.get(sp)
        return None

    ms_by_step = defaultdict(int)
    status_by_step = {}
    for s in spans:
        n = s.get("name", "")
        if n.startswith("step:"):
            canon = _canonical(n[5:])
            ms_by_step[canon] += int(s.get("ms") or 0)
            if s.get("st") in ("ERROR", "HALTED") or canon not in status_by_step:
                status_by_step[canon] = s.get("st", "UNSET")

    files_by_step = defaultdict(lambda: defaultdict(int))
    spawns_by_step = defaultdict(list)
    hosts_by_step = defaultdict(lambda: defaultdict(int))
    unattributed_sec = 0.0
    pulse_where = defaultdict(float)
    for e in evs:
        a = e.get("attr") or {}
        st = step_of(e.get("sp")) or a.get("step_from_stack")
        nm = e.get("name")
        if nm == "touch" and a.get("path"):
            files_by_step[st or "(unattributed)"][a["path"]] += a.get("n", 1)
        elif nm == "spawn":
            spawns_by_step[st or "(unattributed)"].append(
                " ".join(a.get("argv") or [])[:100])
        elif nm == "connect" and a.get("host"):
            hosts_by_step[st or "(unattributed)"][a["host"]] += a.get("n", 1)
        elif nm == "pulse":
            span = max(1.0, float(a.get("t_end", e.get("t", 0.0))) - float(e.get("t", 0.0)))
            if st is None:
                unattributed_sec += span
                pulse_where[a.get("where") or "(unknown)"] += span

    step_ms_total = sum(ms_by_step.values())
    accounted = step_ms_total / 1000.0 + unattributed_sec
    gap = last_t - accounted

    return {"head": head, "opens": opens, "spans": spans, "evs": evs,
            "unclosed": unclosed, "last_t": last_t, "ms_by_step": ms_by_step,
            "status_by_step": status_by_step, "files_by_step": files_by_step,
            "spawns_by_step": spawns_by_step, "hosts_by_step": hosts_by_step,
            "unattributed_sec": unattributed_sec, "pulse_where": pulse_where,
            "step_ms_total": step_ms_total, "accounted": accounted, "gap": gap,
            "step_of": step_of, "name_of": name_of, "parent": parent}


def md(f: dict, trace: Path) -> str:
    steps = all_steps()
    L = ["# TRACE — " + str(f["head"].get("cycle_id", "(unnamed)")),
         "",
         f"From `{_show(trace)}`, {len(f['spans'])} spans, "
         f"{len(f['evs'])} events, wall clock {f['last_t']:.0f}s "
         f"({f['last_t'] / 60:.1f} min).",
         "",
         f"Recorded channels: {', '.join(f['head'].get('channels') or []) or '—'}. "
         f"pid {f['head'].get('pid')}, python {f['head'].get('py')}.",
         "",
         "## Minutes per step", "",
         "Every step in `core/cycle_map.STEPS` has a row. **A step that did not run "
         "reads 0, not blank** — blank is what 32 of the 75 looked like before this "
         "record existed, and blank is indistinguishable from a step that does not "
         "exist.", "",
         "| # | step | seconds | minutes | status |", "|---|---|--:|--:|---|"]
    ran = 0
    for name, idx in steps:
        ms = f["ms_by_step"].get(name, 0)
        if ms:
            ran += 1
        st = f["status_by_step"].get(name, "—" if not ms else "OK")
        L.append(f"| {idx} | {name} | {ms / 1000.0:.1f} | {ms / 60000.0:.2f} | {st} |")
    L.append(f"| — | **(unattributed)** | **{f['unattributed_sec']:.1f}** "
             f"| **{f['unattributed_sec'] / 60.0:.2f}** | — |")
    L += ["", f"{ran} of {len(steps)} steps left a span.", ""]

    if f["unclosed"]:
        L += ["## Died inside", "",
              "An `open` with no `span` after it. The process stopped while this was "
              "running — which is exactly what the synchronous write of `open` is "
              "for.", "",
              "| span | opened at | attributes |", "|---|--:|---|"]
        for o in f["unclosed"]:
            L.append(f"| `{o.get('name')}` | {o.get('t', 0):.1f}s | "
                     f"`{json.dumps(o.get('attr') or {}, ensure_ascii=False)[:120]}` |")
        L.append("")
    else:
        L += ["## Died inside", "", "Nothing: every `open` has its `span`.", ""]

    L += ["## Where the unattributed seconds went", ""]
    if f["pulse_where"]:
        L += ["| location | seconds |", "|---|--:|"]
        for w, s in sorted(f["pulse_where"].items(), key=lambda kv: -kv[1])[:25]:
            L.append(f"| `{w}` | {s:.0f} |")
    else:
        L.append("None — every pulse landed inside a step.")
    L.append("")

    L += ["## Files written, per step", ""]
    if f["files_by_step"]:
        L += ["| step | file | writes |", "|---|---|--:|"]
        for st in sorted(f["files_by_step"], key=lambda s: str(s)):
            for p, n in sorted(f["files_by_step"][st].items(), key=lambda kv: -kv[1])[:12]:
                L.append(f"| {st} | `{p}` | {n} |")
    else:
        L.append("No write was seen. If the cycle ran, that is a finding about the "
                 "audit hook, not about the cycle.")
    L.append("")

    L += ["## Children spawned", ""]
    tot = sum(len(v) for v in f["spawns_by_step"].values())
    if tot:
        L += ["| step | argv | times |", "|---|---|--:|"]
        for st, lst in sorted(f["spawns_by_step"].items(), key=lambda kv: str(kv[0])):
            seen = defaultdict(int)
            for a in lst:
                seen[a] += 1
            for a, n in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
                L.append(f"| {st} | `{a}` | {n} |")
    else:
        L.append("None seen.")
    L.append("")

    L += ["## Hosts connected", ""]
    if f["hosts_by_step"]:
        L += ["| step | host | times |", "|---|---|--:|"]
        for st in sorted(f["hosts_by_step"], key=lambda s: str(s)):
            for h, n in sorted(f["hosts_by_step"][st].items(), key=lambda kv: -kv[1])[:12]:
                L.append(f"| {st} | `{h}` | {n} |")
    else:
        L.append("None seen.")
    L.append("")

    pct = (abs(f["gap"]) / f["last_t"] * 100.0) if f["last_t"] else 0.0
    L += ["## The arithmetic", "",
          f"- sum of `step:*` spans (nested `call:` excluded, so no second is counted "
          f"twice): **{f['step_ms_total'] / 1000.0:.0f}s**",
          f"- unattributed seconds (`ev` with `sp` null): **{f['unattributed_sec']:.0f}s**",
          f"- the two together: **{f['accounted']:.0f}s**",
          f"- wall clock, t0 to the last timestamp seen: **{f['last_t']:.0f}s**",
          ""]
    if abs(f["gap"]) < 1.0:
        L.append("**It closes.** The difference is under a second.")
    elif f["gap"] > 0:
        L.append(f"**It does not close: {f['gap']:.0f}s ({pct:.1f}%) are missing** — "
                 f"wall-clock time that neither a step nor an unattributed pulse "
                 f"accounts for. The likely readings, in order of how ordinary they "
                 f"are: seconds before the first step opened and after the last one "
                 f"closed; a step that was killed, whose span was never written (see "
                 f"*Died inside*); and pulses lost in the last two seconds before a "
                 f"kill. The number is left as it is rather than spread over the "
                 f"steps, because spread over the steps it would stop being visible.")
    else:
        L.append(f"**It over-counts by {-f['gap']:.0f}s ({pct:.1f}%)** — the parts add "
                 f"up to more than the whole, which means the same seconds are being "
                 f"counted twice. The first place to look is two `step:*` spans open "
                 f"at once.")
    L += ["", "---", "",
          f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by `tools/trace_report.py`."]
    return "\n".join(L) + "\n"


HTML_CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--line:#d8d8d4;--ok:#4a7c59;--err:#a4383a;
--unset:#8a8a86;--halt:#3d6b8c;--ev:#c8a24a;--band:#eeeeea}
*{box-sizing:border-box}
body{margin:0;padding:0 16px 48px;background:var(--bg);color:var(--fg);
font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:17px;margin:20px 0 4px}
.meta{color:#6a6a66;margin-bottom:18px}
.row{position:relative;height:20px;margin:1px 0}
.bar{position:absolute;height:16px;border-radius:2px;color:#fff;font-size:11px;
line-height:16px;padding:0 5px;overflow:hidden;white-space:nowrap}
.OK{background:var(--ok)} .ERROR{background:var(--err)} .UNSET{background:var(--unset)} .HALTED{background:var(--halt)}
.open{background:repeating-linear-gradient(45deg,var(--err),var(--err) 5px,#c05a5c 5px,#c05a5c 10px)}
.tick{position:absolute;width:2px;height:16px;background:var(--ev);opacity:.75;top:2px}
.axis{position:relative;height:22px;border-bottom:1px solid var(--line);margin-bottom:6px}
.axis span{position:absolute;font-size:11px;color:#6a6a66}
.legend{margin:14px 0 22px}
.legend i{display:inline-block;width:11px;height:11px;margin:0 5px 0 14px;
vertical-align:-1px;border-radius:2px}
table{border-collapse:collapse;margin:10px 0 26px;font-size:12px}
th,td{border:1px solid var(--line);padding:3px 8px;text-align:left}
th{background:var(--band)} td.n{text-align:right}
.sum{background:#fff;border:1px solid var(--line);padding:12px 14px;margin:18px 0}
"""


def html_page(f: dict, trace: Path) -> str:
    total = max(1.0, f["last_t"])
    spans = sorted([s for s in f["spans"]], key=lambda s: s.get("t", 0))
    depth = {}

    def d_of(sp):
        n, seen = 0, set()
        while sp and sp not in seen:
            seen.add(sp)
            sp = f["parent"].get(sp)
            if sp:
                n += 1
        return n

    ticks_by_span = defaultdict(list)
    for e in f["evs"]:
        if e.get("sp"):
            ticks_by_span[e["sp"]].append(e.get("t", 0.0))

    out = ["<title>TRACE " + html.escape(str(f["head"].get("cycle_id", ""))) + "</title>",
           "<style>" + HTML_CSS + "</style>",
           "<h1>TRACE " + html.escape(str(f["head"].get("cycle_id", "(unnamed)"))) + "</h1>",
           f"<div class=meta>{html.escape(str(trace.name))} &middot; "
           f"{len(f['spans'])} spans &middot; {len(f['evs'])} events &middot; "
           f"wall clock {f['last_t']:.0f}s</div>",
           "<div class=legend>"
           "<i class=OK></i>OK<i class=ERROR></i>ERROR<i class=HALTED></i>HALTED (stopped on purpose)<i class=UNSET></i>UNSET"
           "<i class=open></i>open with no span (died inside)"
           "<i style='background:var(--ev)'></i>event</div>",
           "<div class=axis>"]
    for i in range(0, 11):
        out.append(f"<span style='left:{i * 10}%'>{total * i / 10:.0f}s</span>")
    out.append("</div>")

    for s in spans:
        left = 100.0 * s.get("t", 0) / total
        width = max(0.15, 100.0 * (s.get("ms", 0) / 1000.0) / total)
        dep = d_of(s.get("sp"))
        st = s.get("st", "UNSET")
        label = html.escape(f"{s.get('name', '')}  {s.get('ms', 0) / 1000.0:.1f}s")
        out.append(f"<div class=row><div class='bar {st}' style='left:{left:.3f}%;"
                   f"width:{width:.3f}%;margin-left:{dep * 6}px'>{label}</div>")
        for t in ticks_by_span.get(s.get("sp"), [])[:400]:
            out.append(f"<div class=tick style='left:{100.0 * t / total:.3f}%'></div>")
        out.append("</div>")

    for o in f["unclosed"]:
        left = 100.0 * o.get("t", 0) / total
        width = max(0.4, 100.0 - left)
        out.append(f"<div class=row><div class='bar open' style='left:{left:.3f}%;"
                   f"width:{width:.3f}%'>"
                   f"{html.escape(str(o.get('name')))} — never closed</div></div>")

    out.append("<h1>Minutes per step</h1><table><tr><th>#</th><th>step</th>"
               "<th>seconds</th><th>status</th></tr>")
    for name, idx in all_steps():
        ms = f["ms_by_step"].get(name, 0)
        st = f["status_by_step"].get(name, "&mdash;" if not ms else "OK")
        out.append(f"<tr><td>{html.escape(idx)}</td><td>{html.escape(name)}</td>"
                   f"<td class=n>{ms / 1000.0:.1f}</td><td>{st}</td></tr>")
    out.append(f"<tr><td>&mdash;</td><td><b>(unattributed)</b></td>"
               f"<td class=n><b>{f['unattributed_sec']:.1f}</b></td><td>&mdash;</td></tr>")
    out.append("</table>")

    gap = f["gap"]
    verdict = ("it closes (under a second)" if abs(gap) < 1
               else f"<b>{gap:.0f}s missing</b>" if gap > 0
               else f"<b>{-gap:.0f}s counted twice</b>")
    out.append(f"<div class=sum><b>The arithmetic.</b><br>"
               f"step spans {f['step_ms_total'] / 1000.0:.0f}s "
               f"+ unattributed {f['unattributed_sec']:.0f}s "
               f"= {f['accounted']:.0f}s against a wall clock of "
               f"{f['last_t']:.0f}s &rarr; {verdict}.</div>")
    return "\n".join(out) + "\n"


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", default=None)
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args(argv)

    trace = Path(a.trace) if a.trace else newest_trace()
    if trace is None or not trace.is_file():
        print("no trace found in memory/cycle_trace/")
        return 1
    rows = load(trace)
    if not rows:
        print(f"{trace} is empty")
        return 1
    f = fold(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUT_DIR / f"TRACE_{a.date}.md"
    html_path = OUT_DIR / f"TRACE_{a.date}.html"
    md_path.write_text(md(f, trace), encoding="utf-8")
    html_path.write_text(html_page(f, trace), encoding="utf-8")

    steps = all_steps()
    ran = sum(1 for n, _ in steps if f["ms_by_step"].get(n))
    print(f"trace            : {trace}")
    print(f"steps with a span: {ran} of {len(steps)}")
    print(f"unattributed     : {f['unattributed_sec']:.0f}s")
    print(f"died inside      : {[o.get('name') for o in f['unclosed']] or 'nothing'}")
    print(f"arithmetic       : {f['step_ms_total'] / 1000.0:.0f}s steps + "
          f"{f['unattributed_sec']:.0f}s unattributed = {f['accounted']:.0f}s "
          f"vs {f['last_t']:.0f}s wall  -> gap {f['gap']:.0f}s")
    print(f"-> {_show(md_path)}")
    print(f"-> {_show(html_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
