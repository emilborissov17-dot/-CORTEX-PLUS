#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/scout.py — autonomous HTML -> neutral JSON for dynamic axes.

The system (not a human in a chat) fetches a public HTML page, extracts an OBJECTIVE
number DETERMINISTICALLY (regex/parse — no LLM, so no hallucination and no cloud
budget), and writes a neutral record the composer reads via its existing "file" kind.
Runs headless and unattended; wired into the cycle it refreshes each run. This is the
data-autonomous core; a visible Playwright-headful layer (so Emil can watch) sits on
top once that toolchain is installed — the JSON contract here is identical either way.

Guardrails: extraction is READ-ONLY sensing. Each extractor must return
(value, breakdown, evidence) where `evidence` is the exact substring(s) it counted, so
the number is always traceable to the page text — a value with no evidence is rejected.

  python experiments/browser_scout/scout.py --all
  python experiments/browser_scout/scout.py --source social_conflicts
  python experiments/browser_scout/scout.py --source social_conflicts --html-file page.txt  # offline test
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT_DIR = REPO / "memory" / "browse_sources"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _fetch(url: str, timeout: int = 20) -> str:
    """Autonomous fetch — requests (the lib the cycle already uses successfully)."""
    import requests
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": "CORTEX-browser-scout/1.0"})
    r.raise_for_status()
    return r.text


# ── deterministic extractors: (text) -> (value, breakdown, evidence) ─────────
# Each COUNTS from the page and returns the exact strings it counted, so the number
# can never be a hallucination — it is arithmetic over matched substrings.

def _extract_ongoing_conflicts(text: str):
    # Wikipedia states each tier as "The N conflicts in the following list ..."
    hits = re.findall(r"The\s+(\d+)\s+conflicts\s+in\s+the\s+following\s+list", text)
    if not hits:
        raise ValueError("tier statements not found — page layout changed")
    nums = [int(h) for h in hits]
    tiers = ["major_wars_10k+", "minor_wars_1k-9999", "conflicts_100-999", "skirmishes_1-99"]
    breakdown = {tiers[i] if i < len(tiers) else f"tier_{i}": n for i, n in enumerate(nums)}
    evidence = re.findall(r"The\s+\d+\s+conflicts\s+in\s+the\s+following\s+list", text)
    return sum(nums), breakdown, evidence


SOURCES = {
    "social_conflicts": {
        "axis": "SOCIAL_RELATIONS_REVIEW",
        "url": "https://en.wikipedia.org/wiki/List_of_ongoing_armed_conflicts",
        "metric": "ongoing_armed_conflicts",
        "unit": "count of ongoing armed conflicts worldwide",
        "orientation": "higher = worse for social stability",
        "org": "Wikipedia/UCDP-ACLED",
        "extractor": _extract_ongoing_conflicts,
    },
}


def scout(key: str, html: str | None = None) -> dict:
    spec = SOURCES[key]
    if html is None:
        html = _fetch(spec["url"])
    value, breakdown, evidence = spec["extractor"](html)
    if not evidence:
        raise ValueError("no evidence substrings — refusing to write an untraceable value")
    rec = {
        "metric": spec["metric"], "value": value, "breakdown": breakdown,
        "unit": spec["unit"], "orientation": spec["orientation"],
        "source": spec["org"], "source_url": spec["url"],
        "extraction": "deterministic count from matched page substrings; no interpretation",
        "evidence": evidence[:6],
        "data_date": _now_iso()[:10], "extracted_at": _now_iso(),
        "extracted_by": "browser_scout (HTML -> objective JSON, autonomous)",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return rec


def run_all() -> dict:
    out = {}
    for key in SOURCES:
        try:
            rec = scout(key)
            out[key] = {"ok": True, "value": rec["value"]}
            print(f"[browser_scout] {key} -> {rec['metric']}={rec['value']} "
                  f"{rec['breakdown']} -> memory/browse_sources/{key}.json")
        except Exception as e:
            out[key] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            print(f"[browser_scout] {key} -> FAILED: {type(e).__name__}: {e}")
    return out


if __name__ == "__main__":
    if "--html-file" in sys.argv:
        i = sys.argv.index("--html-file")
        html = Path(sys.argv[i + 1]).read_text(encoding="utf-8")
        key = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else "social_conflicts"
        rec = scout(key, html=html)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    elif "--source" in sys.argv:
        key = sys.argv[sys.argv.index("--source") + 1]
        rec = scout(key)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    else:
        run_all()
