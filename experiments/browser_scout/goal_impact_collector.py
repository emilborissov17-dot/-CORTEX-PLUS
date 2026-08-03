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
import collector_memory as mem           # seen urls, query history, axis rotation
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


def gather_pages(axis: str, need: str, urls=None, n_open: int = 4, plan=None, skip=None):
    """Return [(url, page_text)] the human way — search + open + read in a visible browser —
    or straight from a given URL list. Overridable in tests (pass pages= to collect()).

    `skip` is consulted before a result is opened, so a page already rejected for this
    axis and need class costs nothing at all rather than a page-load plus two model votes.
    An explicit --urls list is NEVER skipped: that is a human naming what to read."""
    if urls:
        return [(u, scout._page_text(u)) for u in urls], "(given urls)"
    query = (plan or {}).get("search_query") or need
    pages = scout.human_browse_read(query, n_open=n_open, skip=skip)
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
    _skipped_pdfs = []
    _cls = scout.need_class(need)
    plan, plan_err, prior_tried, refusal = {}, None, [], None

    if not urls and pages is None:
        # QUERY DIVERSIFICATION. decide() is a temperature-0.1 call over a constant prompt,
        # so an unchanged (axis, need) yields an unchanged query forever — measured: the
        # same keywords for ten consecutive runs, zero components each. A query already
        # known to yield nothing may not be reused; the planner is asked again, told what
        # failed. After max_query_attempts the run REFUSES by name rather than repeating,
        # because a repeat logs identically to an honest empty read.
        def _propose(prior):
            nonlocal plan, plan_err
            try:
                got = scout.decide(axis, need, prior_queries=prior)
                plan = got if isinstance(got, dict) else {}
                return (plan or {}).get("search_query")
            except Exception as e:
                plan_err = f"{type(e).__name__}: {e}"
                return None

        chosen_q, prior_tried, refusal = mem.choose_query(axis, _cls, _propose)
        if refusal and plan_err and not prior_tried:
            # the planner never answered at all. That is a broken tongue, not an exhausted
            # query space, and it must not be reported as one.
            plan = {"_decide_error": plan_err}
            fallback = str(need)
            if fallback in mem.dry_queries(axis, _cls):
                refusal = (f"planner unavailable ({plan_err}) and the raw need has already "
                           f"been tried and yielded nothing — nothing left to ask")
            else:
                refusal, chosen_q = None, fallback
                _beat("plan", f"FAILED {plan_err} — falling back to the raw need")
        if chosen_q:
            plan["search_query"] = chosen_q
            _beat("plan", f"query={chosen_q!r} metric={plan.get('target_metric')!r}"
                          + (f" | rejected {len(prior_tried)} repeat(s)" if prior_tried else ""))

    if refusal:
        # A NAMED refusal. Not an empty read, not a browse failure, not silence.
        _beat("refuse", refusal)
        trail = {"axis": axis, "need": need, "plan": plan, "query_used": None,
                 "need_class": _cls, "pages_read": [], "components": [], "rejected": [],
                 "seen_skipped": [], "prior_queries": prior_tried,
                 "refusal": refusal, "dropped": None,
                 "vector": {"n": 0, "axis": axis, "need": need,
                            "composed_at": _now_iso(), "collector": collector}}
        return trail

    _seen_skipped = []
    if pages is None:
        _beat("search", "opening the browser" if not urls else f"{len(urls)} given url(s)")

        def _skip(url):
            return mem.should_skip(url, axis, _cls)

        pages, query_used = gather_pages(axis, need, urls=urls, plan=plan,
                                         skip=None if urls else _skip)
        _seen_skipped = list(getattr(scout.human_browse_read, "last_seen_skipped", None) or [])
        for _s in _seen_skipped:
            _beat("search", f"seen_skipped {str(_s.get('url'))[:70]} — {_s.get('why')}")
        _beat("search", f"{len(pages)} page(s) read, {len(_seen_skipped)} skipped as already "
                        f"rejected | query={query_used!r}")
        for _pdf in (getattr(scout.human_browse_read, "last_skipped", None) or []):
            _skipped_pdfs.append(_pdf)
            _beat("search", f"PDF skipped: {_pdf[:90]}")
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
             "need_class": _cls, "prior_queries": prior_tried,
             "seen_skipped": _seen_skipped,
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
                                        "cadence_match": obs.get("cadence_match"),
                                        "observation": obs.get("observation")})
        else:
            trail["rejected"].append({"url": url, "why": why})
        # SEEN MEMORY: what this page turned out to be worth, for THIS axis and need class,
        # with the hash of what we read. That is what lets the next run skip it — and what
        # lets it un-skip the moment the page changes.
        mem.remember(url, axis, _cls, "accepted" if obs else "rejected", text)

    # a PDF that was skipped must appear as a NAMED rejection, not vanish
    for _pdf in _skipped_pdfs:
        trail["rejected"].append({"url": _pdf, "why": scout.PDF_SKIP_REASON})

    # Does anything found actually FILL the slot the need asked for? A daily slot is only
    # filled by a component whose cadence matches; an annual figure is kept in the vector
    # but the hunger stays declared, so data_scout and the approval loop keep hunting.
    if _cls in ("measurement_daily", "event_daily"):
        trail["slot_filled"] = any(o.get("cadence_match") is True for o in observations)
        if observations and not trail["slot_filled"]:
            trail["slot_note"] = (f"components found, but none match the '{_cls}' cadence — "
                                  f"kept in the vector, slot stays hungry")
        _beat("cadence", f"class={_cls} slot_filled={trail['slot_filled']} "
                         f"(cadence_match: {[o.get('cadence_match') for o in observations]})")

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

    # what this query was actually worth, so it can never be asked blindly again
    if query_used and query_used not in ("(given urls)", "(pages supplied)"):
        mem.record_query(axis, _cls, (plan or {}).get("search_query") or query_used,
                         int(vector.get("n") or 0))
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
            "need_class": trail.get("need_class"),
            "slot_filled": trail.get("slot_filled"),
            "slot_note": trail.get("slot_note"),
            # the three fields that make a stuck loop visible in the log itself: what
            # queries were refused as repeats, what pages were skipped as already-judged,
            # and — when it happens — the named refusal instead of a silent zero.
            "prior_queries": trail.get("prior_queries") or [],
            "seen_skipped": trail.get("seen_skipped") or [],
            "refusal": trail.get("refusal"),
            "rotation_note": trail.get("rotation_note"),
            "search_query": (trail.get("plan") or {}).get("search_query"),
            "components": [{"url": c.get("url"), "sign": c.get("sign"),
                            "signed_scalar": c.get("signed_scalar"),
                            "dimension": c.get("dimension"),
                            "impact_confidence": c.get("impact_confidence"),
                            "cadence_match": c.get("cadence_match"),
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
    """The SYSTEM's own declared hunger, not a human-written sentence. The need is the
    declared item's OWN detail text. Returns (axis, need, item, note).

    AXIS ROTATION LIVES HERE. This used to return the FIRST slot_unfilled item in JSON key
    order and stop. 21 axes were hungry; SOCIAL_RELATIONS_REVIEW happens to be first in the
    file, so it took all 14 runs over three days while twenty other axes starved — not
    because it was the most promising, but because dictionaries have an order and nobody
    looked past index 0. Now the hungry axes take turns, an axis that has gone dry K times
    running yields its slot, and if every axis is over the limit the one that has waited
    longest goes anyway (collector_memory.pick_axis)."""
    needs = json.loads(COMPOSER_NEEDS.read_text(encoding="utf-8"))
    axis, item, note = mem.pick_axis(needs)
    if not axis:
        return None, None, None, note
    return axis, item.get("detail", "a live numeric indicator"), item, note


if __name__ == "__main__":
    a = {"votes": 2}
    urls = []
    for i, tok in enumerate(sys.argv):
        if tok == "--axis":  a["axis"] = sys.argv[i + 1]
        if tok == "--need":  a["need"] = sys.argv[i + 1]
        if tok == "--votes": a["votes"] = int(sys.argv[i + 1])
        if tok == "--urls":  urls = [u for u in sys.argv[i + 1:] if not u.startswith("--")]
    if "--stats" in sys.argv:            # the breadth counters, on demand
        print(json.dumps(mem.publish_weekly(), ensure_ascii=False, indent=2))
        sys.exit(0)
    chosen, rotation_note = None, None
    if "--from-needs" in sys.argv:
        _ax, _nd, chosen, rotation_note = need_from_composer()
        if not _ax:
            print(json.dumps({"error": rotation_note or
                              "no slot_unfilled need declared in composer_needs.json"},
                             ensure_ascii=False, indent=2))
            sys.exit(0)
        a["axis"], a["need"] = _ax, _nd     # the system chose both — nothing hardcoded
        _beat("rotate", f"{_ax} ({rotation_note})")
    a.setdefault("axis", "SOCIAL_RELATIONS_REVIEW")
    a.setdefault("need", "a current signal of social cohesion / unrest and its direction vs the goal")
    dry = "--dry" in sys.argv
    trail = collect(a["axis"], a["need"], urls=urls or None, votes=a["votes"], drop=not dry)
    if chosen:
        trail["need_source"] = {"from": "memory/composer_needs.json",
                                "axis": a["axis"], "slot": chosen.get("slot"),
                                "kind": chosen.get("kind"), "detail": chosen.get("detail")}
        trail["rotation_note"] = rotation_note
        # a run that produced nothing counts as DRY, and K of those move the eye elsewhere
        mem.record_run(a["axis"], int((trail.get("vector") or {}).get("n") or 0))
    _log = log_run(trail, mode="dry" if dry else "run")
    _beat("log", _log or "not written")
    # Breadth counters, republished every run and printed beside the decline rate — never
    # the decline rate on its own, which cannot tell discipline from a stuck loop.
    _inst = mem.publish_weekly()
    _beat("instrument", f"7d: {_inst['runs']} run(s), {_inst['distinct_urls_tried']} distinct "
                        f"url(s), {_inst['distinct_queries']} distinct quer(ies), "
                        f"{_inst['n_axes_touched']} axis/axes, decline_rate="
                        f"{_inst['decline_rate']}")
    print(json.dumps(trail, ensure_ascii=False, indent=2))
