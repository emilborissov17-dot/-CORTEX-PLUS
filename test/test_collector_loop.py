#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_collector_loop.py — the loop must be able to be somewhere it has not been.

THE FIXED POINT (memory/collector_runs.jsonl, 31 Jul - 3 Aug 2026): 12 scheduled runs,
3 days, ONE axis every time, TWO distinct queries (one used 10 runs running), 34 page
reads over 11 distinct URLs, the same four blogs read and rejected eight times each.
Nothing raised. Each part behaved correctly. The loop simply had no memory, so it had no
way to be anywhere but where it started — the axis was index 0 of a dict, the query was a
pure function of a constant prompt, and the pages were whatever that query returned.

Four memories, asserted here:
  SEEN      a URL rejected for this axis+need class is not re-read for N days, unless
            its content changed; past the window it is read again regardless
  QUERY     a zero-yield query may not be reused; after 3 attempts the run REFUSES
            by name instead of repeating
  ROTATION  an axis that has gone dry K times yields to another hungry axis, and when
            every axis is over the limit the longest-waiting one still goes
  BREADTH   distinct_urls_tried / distinct_queries / axes_touched are computed and
            published beside the decline rate, which alone cannot tell an honest guard
            from a stuck loop

  venv\\Scripts\\python.exe test\\test_collector_loop.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "browser_scout"))

import collector_memory as M   # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


TMP = Path(tempfile.mkdtemp())
SEEN = TMP / "seen.json"
QUERIES = TMP / "queries.json"
ROT = TMP / "rotation.json"
RUNS = TMP / "runs.jsonl"
M.SEEN_FILE, M.QUERIES_FILE, M.ROTATION_FILE = SEEN, QUERIES, ROT

CONF = dict(M.DEFAULTS)
CONF["seen_ttl_days"] = 14
CONF["dry_runs_before_rotation"] = 3
CONF["max_query_attempts"] = 3


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── SEEN ─────────────────────────────────────────────────────────────────────

URL = "https://buffer.invalid/resources/state-of-social-media-engagement-2026/"
PAGE = "Social media engagement in 2026 rose. Marketing copy, no measurement."

skip, why = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily",
                          seen_path=SEEN, config=CONF)
check("a URL never read is never skipped", skip is False and why == "never read")

M.remember(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily", "rejected", PAGE,
           seen_path=SEEN)
skip, why = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily",
                          seen_path=SEEN, config=CONF,
                          probe=lambda u: M.content_hash(PAGE))
check("a URL rejected for this axis+need class IS skipped", skip is True)
check("...and says when and why", "rejected 0.0d ago" in why and "unchanged" in why)

skip, why = M.should_skip(URL, "WATER_REVIEW", "measurement_daily", seen_path=SEEN,
                          config=CONF, probe=lambda u: M.content_hash(PAGE))
check("the SAME url is NOT skipped for a different axis", skip is False)
skip, _w = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "anchor_annual", seen_path=SEEN,
                         config=CONF, probe=lambda u: M.content_hash(PAGE))
check("...nor for a different need class", skip is False)

skip, why = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily",
                          seen_path=SEEN, config=CONF,
                          probe=lambda u: M.content_hash("now shows a real index: 41.2"))
check("a CHANGED page is re-read, not skipped", skip is False and "content changed" in why)

skip, why = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily",
                          seen_path=SEEN, config=CONF, probe=lambda u: None)
check("an unreadable probe keeps the skip (conservative, and it was already rejected)",
      skip is True and "probe could not read it" in why)

M.remember(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily", "accepted", PAGE,
           seen_path=SEEN)
skip, why = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily",
                          seen_path=SEEN, config=CONF,
                          probe=lambda u: M.content_hash(PAGE))
check("a page that was ACCEPTED is never skipped", skip is False and "accepted" in why)

doc = json.loads(SEEN.read_text(encoding="utf-8"))
doc[URL] = {"axis": "SOCIAL_RELATIONS_REVIEW", "need_class": "measurement_daily",
            "last_read": _ago(20), "verdict": "rejected",
            "content_hash": M.content_hash(PAGE)}
SEEN.write_text(json.dumps(doc), encoding="utf-8")
skip, why = M.should_skip(URL, "SOCIAL_RELATIONS_REVIEW", "measurement_daily",
                          seen_path=SEEN, config=CONF,
                          probe=lambda u: M.content_hash(PAGE))
check("past the TTL the page is read again whatever its hash says — the world moves",
      skip is False and "past the 14d window" in why)

check("the hash ignores whitespace and case, not words",
      M.content_hash("A  B\nc") == M.content_hash("a b C")
      and M.content_hash("A B") != M.content_hash("A B C"))


# ── QUERY ────────────────────────────────────────────────────────────────────

AX, CLS = "SOCIAL_RELATIONS_REVIEW", "measurement_daily"
STUCK = "2026 social media engagement daily"

M.record_query(AX, CLS, STUCK, 0, queries_path=QUERIES)
check("a zero-yield query is remembered as dry",
      M.dry_queries(AX, CLS, queries_path=QUERIES) == [STUCK])

calls = []


def _always_the_same(prior):
    calls.append(prior)
    return STUCK


q, tried, refusal = M.choose_query(AX, CLS, _always_the_same, config=CONF,
                                   queries_path=QUERIES)
check("a query known to yield nothing is REFUSED, not reused", q is None)
check("...after exactly max_query_attempts tries", len(calls) == CONF["max_query_attempts"])
check("...with the named refusal", M.QUERY_EXHAUSTED in refusal)
check("...and the planner was TOLD what had already failed", STUCK in calls[0])

M.record_query(AX, CLS, "unrest index live tracker", 2, queries_path=QUERIES)
check("a query that YIELDED is not banned",
      "unrest index live tracker" not in M.dry_queries(AX, CLS, queries_path=QUERIES))

seq = iter([STUCK, "acled conflict event count this week"])
q, tried, refusal = M.choose_query(AX, CLS, lambda prior: next(seq), config=CONF,
                                   queries_path=QUERIES)
check("a FRESH query is accepted on the second attempt",
      q == "acled conflict event count this week" and refusal is None)
check("...and the repeat it rejected is recorded for the run row", tried == [STUCK])


# ── ROTATION ─────────────────────────────────────────────────────────────────

def needs_doc(axes):
    return {a: {"items": [{"kind": "slot_unfilled", "slot": "measurement_daily",
                           "detail": f"needs >= 1 live source(s) of class "
                                     f"'measurement_daily' for {a}, has 0"}]}
            for a in axes}


AXES = ["SOCIAL_RELATIONS_REVIEW", "WATER_REVIEW", "FOOD_REVIEW", "ENERGY_REVIEW"]
ROT.write_text(json.dumps({"cursor": None, "axes": {}}), encoding="utf-8")

a1, item, note = M.pick_axis(needs_doc(AXES), config=CONF, rotation_path=ROT)
check("the first pick is the first hungry axis", a1 == "SOCIAL_RELATIONS_REVIEW")
check("...and it carries that axis's own need text", "SOCIAL_RELATIONS_REVIEW" in item["detail"])

M.record_run(a1, 0, rotation_path=ROT)
a2, _i, _n = M.pick_axis(needs_doc(AXES), config=CONF, rotation_path=ROT)
check("the very next run moves on — no axis takes two turns in a row",
      a2 == "WATER_REVIEW")

ROT.write_text(json.dumps({"cursor": "ENERGY_REVIEW", "axes": {
    "SOCIAL_RELATIONS_REVIEW": {"dry_runs": 3, "last_run": _ago(0.1)}}}), encoding="utf-8")
a3, _i, note = M.pick_axis(needs_doc(AXES), config=CONF, rotation_path=ROT)
check("an axis with K consecutive dry runs YIELDS its slot", a3 == "WATER_REVIEW")
check("...and the skip is stated, not silent", "skipped" in note and "3 dry runs" in note)

ROT.write_text(json.dumps({"cursor": None, "axes": {
    a: {"dry_runs": 9, "last_run": _ago(1 if a != "FOOD_REVIEW" else 30)} for a in AXES
}}), encoding="utf-8")
a4, _i, note = M.pick_axis(needs_doc(AXES), config=CONF, rotation_path=ROT)
check("when EVERY axis is over the limit the eye does not switch off",
      a4 == "FOOD_REVIEW")
check("...the one that waited longest goes, and says so", "waited longest" in note)
check("...and its counter is cleared so it gets a real chance",
      json.loads(ROT.read_text(encoding="utf-8"))["axes"]["FOOD_REVIEW"]["dry_runs"] == 0)

ROT.write_text(json.dumps({"cursor": None, "axes": {}}), encoding="utf-8")
st = M.record_run("WATER_REVIEW", 0, rotation_path=ROT)
check("a run that produced nothing counts as dry", st["dry_runs"] == 1)
M.record_run("WATER_REVIEW", 0, rotation_path=ROT)
st = M.record_run("WATER_REVIEW", 2, rotation_path=ROT)
check("a run that produced a component clears the count", st["dry_runs"] == 0)

a, i, note = M.pick_axis({}, config=CONF, rotation_path=ROT)
check("no hunger is reported as no hunger, not as an axis", a is None and "no axis" in note)


# ── the collector actually consults them ─────────────────────────────────────

import goal_impact_collector as GIC   # noqa: E402
import autonomous_scout as scout      # noqa: E402

GIC.COMPOSER_NEEDS = TMP / "needs.json"
GIC.COMPOSER_NEEDS.write_text(json.dumps(needs_doc(AXES)), encoding="utf-8")
ROT.write_text(json.dumps({"cursor": "SOCIAL_RELATIONS_REVIEW", "axes": {}}),
               encoding="utf-8")
ax, need, item, note = GIC.need_from_composer()
check("need_from_composer no longer returns index 0 of a dict", ax == "WATER_REVIEW")
check("...and reports how it chose", "round-robin" in note)

_real_decide = scout.decide
scout.decide = lambda axis, need, slot=None, prior_queries=None: {
    "search_query": STUCK, "target_metric": "engagement", "need_class": CLS}
try:
    trail = GIC.collect(AX, f"needs >= 1 live source(s) of class '{CLS}', has 0",
                        drop=False)
finally:
    scout.decide = _real_decide
check("a run whose only query is a known dead end REFUSES instead of browsing",
      M.QUERY_EXHAUSTED in str(trail.get("refusal")))
check("...reads nothing", trail["pages_read"] == [])
check("...composes an explicit n=0 rather than a silent one", trail["vector"]["n"] == 0)
check("...and the refusal survives into the run row",
      json.loads(json.dumps(trail)).get("refusal") is not None)

src = (REPO / "experiments" / "browser_scout" / "goal_impact_collector.py").read_text(
    encoding="utf-8")
check("the run row carries the breadth fields",
      '"seen_skipped"' in src and '"prior_queries"' in src and '"refusal"' in src)
check("--urls is never seen-skipped: a human naming a page is not a repeat",
      "skip=None if urls else _skip" in src)

sc = (REPO / "experiments" / "browser_scout" / "autonomous_scout.py").read_text(
    encoding="utf-8")
check("autonomous_scout no longer pins the first axis either",
      "_mem.pick_axis(needs)" in sc)
check("...and shares the collector's cursor rather than fighting it",
      "collector_memory" in sc)
check("decide() is told what already failed", "prior_queries" in sc)


# ── BREADTH ──────────────────────────────────────────────────────────────────

def row(ts, axis, query, comps, rej, skipped=()):
    return json.dumps({
        "ts": ts, "axis": axis, "search_query": query, "pages_read": len(comps) + len(rej),
        "components": [{"url": u} for u in comps],
        "rejected": [{"url": u} for u in rej],
        "seen_skipped": [{"url": u} for u in skipped]})


# an honest guard: many fresh pages, most declined
honest = "\n".join(row(_ago(1), f"AX{i}", f"query {i}", [f"https://ok{i}.invalid"],
                       [f"https://no{i}{j}.invalid" for j in range(9)])
                   for i in range(3))
RUNS.write_text(honest + "\n", encoding="utf-8")
h = M.weekly(7, runs_log=RUNS)

# a stuck loop: the same page, the same query, the same axis, over and over
stuck = "\n".join(row(_ago(1), "AX0", "the one query", [], ["https://same.invalid"] * 9)
                  for _ in range(3))
RUNS.write_text(stuck + "\n", encoding="utf-8")
s = M.weekly(7, runs_log=RUNS)

check("an honest guard declines most of what it reads", abs(h["decline_rate"] - 0.9) < 1e-9)
check("a stuck loop declines everything — and BOTH look like discipline in that number",
      s["decline_rate"] == 1.0)
check("...but the breadth counters separate them cleanly",
      h["distinct_urls_tried"] == 30 and s["distinct_urls_tried"] == 1)
check("...on queries too", h["distinct_queries"] == 3 and s["distinct_queries"] == 1)
check("...and on axes", h["n_axes_touched"] == 3 and s["n_axes_touched"] == 1)
check("the report says out loud that the rate alone is not readable",
      "cannot distinguish" in s["reading_note"])

RUNS.write_text(row(_ago(30), "OLD", "old query", ["https://old.invalid"], []) + "\n",
                encoding="utf-8")
old = M.weekly(7, runs_log=RUNS)
check("the window is real — a month-old run is not this week's evidence",
      old["runs"] == 0 and old["decline_rate"] is None)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
