#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/target_grounding.py — THE STANDARD, APPLIED TO US. (10 Sep 2026.)

Emil, on the worry that a monitor which measures the world against its authors'
targets cannot see its own blind spots: "СТАНДАРТИ, СТАНДАРТИ ... ПРАВИЛА,
ПРАВИЛА, ДОРИ И ЗА НАС." The vision cannot be proven in advance; the numbers
we wrote into it can be held to the same rule as everything else.

THE RULE, WHICH ALREADY EXISTS FOR EVERYONE ELSE
------------------------------------------------
A number from a sensor enters the system only if its quote is on the live
page it names (core/quote_gate.py, R43). config/target_config.json holds 24
target_values — 350 ppm, 80% renewables, 100% safe water, 35% forest — each
with a `rationale` naming a source in prose ("Rockström et al. 2009",
"IEA Net Zero 2050", "SDG6"). Prose is not a quote. Not one of the 24 carries
a `source_url` and a `quote` the gate could check. So, by the system's own
standard, every target the system scores the world against is today
UNGROUNDED: an author's assertion, exactly like a sensor card without a page.

This script says so, per axis, and the test behind it is a RATCHET: the
number of ungrounded targets may fall and may never rise. A new target
without a page is refused by the same test that refuses a sensor's invented
row.

  GROUNDED     source_url + quote present, gate says ACCEPTED against the page
  CONTESTED    source_url + quote present, gate says QUOTE_NOT_ON_PAGE / VALUE_MISMATCH
  UNFETCHED    source_url + quote present, page could not be fetched (open, retry)
  UNGROUNDED   no source_url or no quote — the target is an author's assertion
  SEMANTIC     no primary metric at all (qualitative axis) — nothing to ground yet

Usage:
  venv\\Scripts\\python.exe scripts/target_grounding.py            # audit, no network
  venv\\Scripts\\python.exe scripts/target_grounding.py --fetch    # verify the grounded ones against the live page
  venv\\Scripts\\python.exe scripts/target_grounding.py --write    # + claude/reports/TARGET_GROUNDING.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CONFIG = REPO / "config" / "target_config.json"
REPORT = REPO / "claude" / "reports" / "TARGET_GROUNDING.md"

GROUNDED, CONTESTED, UNFETCHED, UNGROUNDED, SEMANTIC = (
    "GROUNDED", "CONTESTED", "UNFETCHED", "UNGROUNDED", "SEMANTIC")


def axes(config_path: Path = CONFIG) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    return {a: s for b, g in cfg.items() if not b.startswith("_") and isinstance(g, dict)
            for a, s in g.items() if isinstance(s, dict)}


def judge_axis(axis: str, spec: dict, fetch=None) -> dict:
    """Pure unless `fetch` is given. Verdict per the rule above."""
    row = {"axis": axis, "primary_metric": spec.get("primary_metric"), "target_value": spec.get("target_value"),
           "source_url": spec.get("source_url"), "quote": spec.get("quote"),
           "rationale": (spec.get("rationale") or "")[:120]}
    if spec.get("primary_metric") is None:
        return dict(row, verdict=SEMANTIC)
    if not spec.get("source_url") or not spec.get("quote"):
        return dict(row, verdict=UNGROUNDED,
                    why="target_value has a rationale in prose but no source_url + quote the gate could check")
    if fetch is None:
        return dict(row, verdict=UNFETCHED, why="not fetched in this run")
    from core import quote_gate as qg
    rec = {"axis": axis, "key": spec.get("primary_metric"), "value": spec.get("target_value"),
           "unit": spec.get("unit"), "url": spec["source_url"], "quote": spec["quote"]}
    v = qg.judge(rec, fetch(spec["source_url"]))
    if v["verdict"] == "ACCEPTED":
        return dict(row, verdict=GROUNDED, gate=v)
    if v["verdict"] == "FETCH_FAILED":
        return dict(row, verdict=UNFETCHED, gate=v)
    return dict(row, verdict=CONTESTED, gate=v)


def audit(config_path: Path = CONFIG, fetch=None) -> dict:
    rows = [judge_axis(a, s, fetch) for a, s in sorted(axes(config_path).items())]
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in (GROUNDED, CONTESTED, UNFETCHED, UNGROUNDED, SEMANTIC)}
    measurable = sum(1 for r in rows if r["verdict"] != SEMANTIC)
    return {"ts": datetime.now(timezone.utc).isoformat(), "axes": len(rows), "measurable": measurable,
            "counts": counts, "rows": rows,
            "rule": "a target_value without a source_url + quote that core/quote_gate.py accepts against the live page "
                    "is an author's assertion, held to the same standard as a sensor card"}


def markdown(r: dict) -> str:
    c = r["counts"]
    lines = ["# TARGET GROUNDING — the sensor standard applied to our own targets", "",
             f"_{r['ts'][:19]}Z · {r['axes']} axes, {r['measurable']} with a primary metric_", "",
             f"**GROUNDED {c[GROUNDED]} · CONTESTED {c[CONTESTED]} · UNFETCHED {c[UNFETCHED]} · "
             f"UNGROUNDED {c[UNGROUNDED]} · SEMANTIC {c[SEMANTIC]}**", "",
             "| axis | metric | target | verdict | why |", "|---|---|---:|---|---|"]
    for row in r["rows"]:
        why = row.get("why") or (json.dumps(row.get("gate"), ensure_ascii=False) if row.get("gate") else "")
        lines.append(f"| {row['axis']} | {row['primary_metric'] or '—'} | {row['target_value'] if row['target_value'] is not None else '—'} "
                     f"| {row['verdict']} | {why[:100]} |")
    lines += ["", "## Reading", "",
              "Every target the world is scored against was written by the authors with a rationale in prose. "
              "By the rule the system applies to every sensor (R43: the quote must be on the live page), "
              "a rationale is not evidence. This is not a claim that the targets are wrong — 350 ppm is Rockström's "
              "number — it is the claim that the system cannot yet tell a target that is someone's finding from one "
              "that is someone's wish. Grounding one is small work: add `source_url` and a verbatim `quote` to the axis, "
              "and this audit checks it against the page. test/test_target_grounding.py is a ratchet: UNGROUNDED may "
              "fall, never rise.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    fetch = None
    if "--fetch" in sys.argv:
        from core import quote_gate as qg
        fetch = qg._fetch
    r = audit(fetch=fetch)
    if "--write" in sys.argv:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(markdown(r), encoding="utf-8")
        print(f"wrote {REPORT}")
    print(json.dumps({k: r[k] for k in ("axes", "measurable", "counts")}, ensure_ascii=False))
    for row in r["rows"]:
        print(f"  {row['verdict']:<11} {row['axis']}")
