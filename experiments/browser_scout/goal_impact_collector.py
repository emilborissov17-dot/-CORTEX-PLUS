#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/goal_impact_collector.py — the collector that turns a human-like
web read into a GOAL-IMPACT VECTOR and commits it to the sensorium.

This is the keystone that makes the whole sensing loop coherent (Emil, 30 Jul 2026):

    decide need -> human-browse (real typing/clicking, visible) -> read the opened pages
    -> per page extract a CALIBRATED goal-impact component (grounded + sign-consistent)
    -> compose ONE axis vector (signed, weighted, disagreements kept) -> DROP into the
       Merkle-committed sensorium as kind "goal_impact".

From there the fast_cycle only runs sensorium.ingest() (light, no browser): the full
vector goes to the brain (goal_impact_inbox), the moving scalar goes to the composer
(browse_sources) for scoring. Sensing and thinking stay decoupled; nothing is fabricated
(every component's fact is verbatim-grounded, every sign is vote-consistent), and a human
still approves promotion of any new sensory source.

  # real, on Emil's machine (needs Ollama + a browser; headful so he can watch):
  venv/Scripts/python.exe experiments/browser_scout/goal_impact_collector.py \
      --axis SOCIAL_RELATIONS_REVIEW \
      --need "a current signal of social cohesion / unrest and its direction vs the goal"

  # deterministic path from known-good pages (no search):
  ... goal_impact_collector.py --axis SOCIAL_RELATIONS_REVIEW --need "..." \
      --urls https://en.wikipedia.org/wiki/List_of_ongoing_armed_conflicts
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "experiments" / "sensorium"))

import autonomous_scout as scout        # human_browse_read, _page_text, decide, _now_iso
import goal_impact as gi                 # extract_calibrated, compose_vector
import sensorium                         # drop / ingest / verify (Merkle-committed)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def gather_pages(axis: str, need: str, urls=None, n_open: int = 4, plan=None):
    """Return [(url, page_text)] the human way — search + open + read in a visible browser —
    or straight from a given URL list. Overridable in tests (pass pages= to collect())."""
    if urls:
        return [(u, scout._page_text(u)) for u in urls], "(given urls)"
    query = (plan or {}).get("search_query") or need
    pages = scout.human_browse_read(query, n_open=n_open)
    return pages, scout._loosen(query)


def collect(axis: str, need: str, urls=None, votes: int = 2, collector: str = "goal_impact_collector",
            pages=None, drop: bool = True) -> dict:
    """Read pages -> calibrated goal-impact components -> composed vector -> sensorium drop.

    pages: optional pre-read [(url, text)] to bypass the browser (used by the fixture test).
    drop:  set False to compute the vector WITHOUT committing (dry run / inspection).
    Returns a trail: what it decided, what it read, each component's verdict, the vector,
    and the sensorium drop id (or None). Nothing is invented — an empty read yields n=0.
    """
    plan = {}
    try:
        if not urls:                       # let the model choose good search keywords
            plan = scout.decide(axis, need)
    except Exception as e:
        plan = {"_decide_error": f"{type(e).__name__}: {e}"}

    if pages is None:
        pages, query_used = gather_pages(axis, need, urls=urls, plan=plan)
    else:
        query_used = "(pages supplied)"

    trail = {"axis": axis, "need": need, "plan": plan, "query_used": query_used,
             "pages_read": [u for u, _ in pages], "components": [], "rejected": []}
    observations = []
    for url, text in pages:
        try:
            obs, why = gi.extract_calibrated(text, axis, need, url, votes=votes)
        except Exception as e:
            trail["rejected"].append({"url": url, "why": f"error: {type(e).__name__}: {e}"})
            continue
        if obs:
            observations.append(obs)
            trail["components"].append({"url": url, "sign": obs.get("sign"),
                                        "signed_scalar": obs.get("signed_scalar"),
                                        "dimension": obs.get("dimension"),
                                        "impact_confidence": obs.get("impact_confidence"),
                                        "observation": obs.get("observation")})
        else:
            trail["rejected"].append({"url": url, "why": why})

    vector = gi.compose_vector(observations)
    vector["axis"] = axis
    vector["need"] = need
    vector["data_date"] = _now_iso()[:10]
    vector["composed_at"] = _now_iso()
    vector["collector"] = collector
    trail["vector"] = vector

    trail["dropped"] = None
    if drop and vector.get("n", 0) > 0:
        trail["dropped"] = sensorium.drop(axis, "goal_impact", vector, collector=collector)
    elif drop:
        trail["drop_skipped"] = "no groundable components — nothing committed (empty is empty)"
    return trail


if __name__ == "__main__":
    a = {"votes": 2}
    urls = []
    for i, tok in enumerate(sys.argv):
        if tok == "--axis":  a["axis"] = sys.argv[i + 1]
        if tok == "--need":  a["need"] = sys.argv[i + 1]
        if tok == "--votes": a["votes"] = int(sys.argv[i + 1])
        if tok == "--urls":  urls = [u for u in sys.argv[i + 1:] if not u.startswith("--")]
    a.setdefault("axis", "SOCIAL_RELATIONS_REVIEW")
    a.setdefault("need", "a current signal of social cohesion / unrest and its direction vs the goal")
    dry = "--dry" in sys.argv
    trail = collect(a["axis"], a["need"], urls=urls or None, votes=a["votes"], drop=not dry)
    print(json.dumps(trail, ensure_ascii=False, indent=2))
