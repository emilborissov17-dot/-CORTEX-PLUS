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

class SourceSchemaDrift(Exception):
    """The extraction contract no longer holds — the source has changed.

    Kimi, 15 August 2026: "Fragility is source_schema_drift, not a step failure."
    A separate type, so the cycle can tell "my code broke" from "the world I was
    reading now looks different". The second is news; the first is a defect.

    REQUIREMENT RECOVERED, IMPLEMENTATION NEW, 2026-08-28. A `git reset --hard`
    destroyed the version carrying this class; the docstring above survives in
    experiments/browser_scout/__pycache__/scout.cpython-314.pyc compiled
    2026-08-17 14:16:18. Nothing here was reassembled from bytecode.
    """


def _drift_record(key: str, exc: "SourceSchemaDrift") -> dict:
    """A source event, filed under its own key so it never reads as a code fault."""
    return {"ok": False, "event": "source_schema_drift", "source": key,
            "reason": str(exc), "kind": "upstream"}


def _fault_record(key: str, exc: BaseException) -> dict:
    """A defect in our own code. Not an event about the world."""
    return {"ok": False, "source": key,
            "error": f"{type(exc).__name__}: {exc}"}


def _extract_ongoing_conflicts(text: str):
    # Wikipedia states each tier as "The N conflicts in the following list ..."
    hits = re.findall(r"The\s+(\d+)\s+conflicts\s+in\s+the\s+following\s+list", text)
    if not hits:
        raise SourceSchemaDrift(
            "the extraction contract is invalid: the phrase 'The N conflicts in "
            "the following list' is gone. The page has changed — this is an "
            "event for the source, not an error in the code.")
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
        except SourceSchemaDrift as e:
            # NOT a failure of this step. The world we were reading changed, and
            # that is a finding about the source — printed differently so a human
            # scanning the log does not read it as a bug in our code.
            out[key] = _drift_record(key, e)
            print(f"[browser_scout] {key} -> THE SOURCE HAS CHANGED "
                  f"(not a code failure): {e}")
        except Exception as e:
            out[key] = _fault_record(key, e)
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
