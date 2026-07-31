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


RUNS_LOG = REPO / "memory" / "collector_runs.jsonl"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _beat(phase: str, msg: str = ""):
    """One line per phase on STDERR, so an unattended run is readable in the task log
    while STDOUT stays a clean JSON trail for anything that pipes it."""
    print(f"[COLLECT {_now_iso()[11:19]}] {phase}"
          + (f" -> {msg}" if msg else ""), file=sys.stderr, flush=True)


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
    _beat("need", f"{axis} :: {str(need)[:70]}")
    plan = {}
    try:
        if not urls:                       # let the model choose good search keywords
            plan = scout.decide(axis, need)
            _beat("plan", f"query={plan.get('search_query')!r} metric={plan.get('target_metric')!r}")
    except Exception as e:
        plan = {"_decide_error": f"{type(e).__name__}: {e}"}
        _beat("plan", f"FAILED {plan['_decide_error']} — falling back to the raw need")

    if pages is None:
        _beat("search", "opening the browser" if not urls else f"{len(urls)} given url(s)")
        pages, query_used = gather_pages(axis, need, urls=urls, plan=plan)
        _beat("search", f"{len(pages)} page(s) read | query={query_used!r}")
        if not pages:
            # A browse that returned NOTHING is a broken eye, not an empty world. Left
            # unmarked it composes to n=0 and logs identically to "read pages, rejected
            # them all" — so an unattended run would look like honest silence forever.
            _beat("search", "SEARCH RETURNED NOTHING — the browse failed, this is not "
                            "'no signal'. Headless is blocked by the engines; headful works.")
            _browse_failed = True
        else:
            _browse_failed = False
    else:
        query_used = "(pages supplied)"
        _browse_failed = False

    trail = {"axis": axis, "need": need, "plan": plan, "query_used": query_used,
             "pages_read": [u for u, _ in pages], "components": [], "rejected": []}
    if _browse_failed:
        trail["browse_failed"] = ("search returned 0 pages — the eye failed, not the world. "
                                  "Headless Chromium is blocked by the search engines "
                                  "(measured: headful 3 pages, headless 0, same query).")
    observations = []
    for _i, (url, text) in enumerate(pages, 1):
        _beat(f"page {_i}/{len(pages)}", f"{url[:78]} ({len(text)} chars)")
        try:
            obs, why = gi.extract_calibrated(text, axis, need, url, votes=votes)
        except Exception as e:
            trail["rejected"].append({"url": url, "why": f"error: {type(e).__name__}: {e}"})
            _beat(f"page {_i}/{len(pages)}", f"ERROR {type(e).__name__}: {e}")
            continue
        _beat(f"page {_i}/{len(pages)}",
              (f"ACCEPTED sign={obs.get('sign')} scalar={obs.get('signed_scalar')} "
               f"dim={obs.get('dimension')} conf={obs.get('impact_confidence')}")
              if obs else f"REJECTED {str(why)[:90]}")
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
        _beat("verdict", f"n={vector['n']} overall={vector.get('overall_signed_weighted')} "
                         f"-> DROPPED {trail['dropped']}")
    elif drop:
        trail["drop_skipped"] = "no groundable components — nothing committed (empty is empty)"
        _beat("verdict", f"n=0, {len(trail['rejected'])} rejected — nothing committed "
                         f"(empty is empty)")
    else:
        _beat("verdict", f"n={vector.get('n')} (dry run — no commit)")
    return trail


def log_run(trail: dict, mode: str = "scheduled"):
    """Append the trail TAIL — never the whole thing — so an unattended run leaves an
    auditable record without the log growing by a page of text per fetch. Fail-open."""
    try:
        vec = trail.get("vector") or {}
        entry = {
            "ts": _now_iso(), "mode": mode,
            "axis": trail.get("axis"), "need": str(trail.get("need"))[:160],
            "query_used": trail.get("query_used"),
            "pages_read": len(trail.get("pages_read") or []),
            "n_components": vec.get("n"),
            "overall_signed_weighted": vec.get("overall_signed_weighted"),
            "by_dimension": vec.get("by_dimension"),
            "dropped": trail.get("dropped"),
            "drop_skipped": trail.get("drop_skipped"),
            "browse_failed": trail.get("browse_failed"),
            "components": [{"url": c.get("url"), "sign": c.get("sign"),
                            "signed_scalar": c.get("signed_scalar"),
                            "dimension": c.get("dimension"),
                            "impact_confidence": c.get("impact_confidence"),
                            "observation": str(c.get("observation"))[:180]}
                           for c in (trail.get("components") or [])],
            "rejected": [{"url": r.get("url"), "why": str(r.get("why"))[:180]}
                         for r in (trail.get("rejected") or [])],
        }
        RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNS_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return str(RUNS_LOG)
    except Exception as e:
        _beat("log", f"FAILED {type(e).__name__}: {e}")
        return None


COMPOSER_NEEDS = REPO / "memory" / "composer_needs.json"


def need_from_composer():
    """The SYSTEM's own declared hunger, not a human-written sentence. Mirrors
    autonomous_scout --from-needs: first axis carrying a slot_unfilled item wins, and the
    need is that item's OWN detail text. Returns (axis, need, item) or (None, None, None)."""
    needs = json.loads(COMPOSER_NEEDS.read_text(encoding="utf-8"))
    for axis, entry in (needs or {}).items():
        for it in (entry or {}).get("items", []):
            if it.get("kind") == "slot_unfilled":
                return axis, it.get("detail", "a live numeric indicator"), it
    return None, None, None


if __name__ == "__main__":
    a = {"votes": 2}
    urls = []
    for i, tok in enumerate(sys.argv):
        if tok == "--axis":  a["axis"] = sys.argv[i + 1]
        if tok == "--need":  a["need"] = sys.argv[i + 1]
        if tok == "--votes": a["votes"] = int(sys.argv[i + 1])
        if tok == "--urls":  urls = [u for u in sys.argv[i + 1:] if not u.startswith("--")]
    chosen = None
    if "--from-needs" in sys.argv:
        _ax, _nd, chosen = need_from_composer()
        if not _ax:
            print(json.dumps({"error": "no slot_unfilled need declared in composer_needs.json"},
                             ensure_ascii=False, indent=2))
            sys.exit(0)
        a["axis"], a["need"] = _ax, _nd     # the system chose both — nothing hardcoded
    a.setdefault("axis", "SOCIAL_RELATIONS_REVIEW")
    a.setdefault("need", "a current signal of social cohesion / unrest and its direction vs the goal")
    dry = "--dry" in sys.argv
    trail = collect(a["axis"], a["need"], urls=urls or None, votes=a["votes"], drop=not dry)
    if chosen:
        trail["need_source"] = {"from": "memory/composer_needs.json",
                                "axis": a["axis"], "slot": chosen.get("slot"),
                                "kind": chosen.get("kind"), "detail": chosen.get("detail")}
    _log = log_run(trail, mode="dry" if dry else "run")
    _beat("log", _log or "not written")
    print(json.dumps(trail, ensure_ascii=False, indent=2))
