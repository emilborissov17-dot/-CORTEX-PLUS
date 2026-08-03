#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_registration_wall.py — a candidate that cannot be fetched is never registered,
and a source that was never contacted is never blamed.

THE LIVE FAILURE THIS PINS DOWN (approvals_ledger.jsonl, 31 Jul - 3 Aug 2026):
data_scout parsed a payload to prove it held numbers, discarded the parsed structure, and
registered {url, format, metric, org, slot_hint}. That record cannot be fetched by any
composer kind. It still became an approval item and reached Emil's phone; id 96b9 was
tapped OK three times and a027 once, each hitting the same deterministic refusal, and the
approval path then BLACKLISTED the provider for it. OWID and the World Bank were barred
for a field WE had failed to compute, from a payload we had held in memory seconds before.

Four things are asserted here:
  DERIVE     the parsing rule comes out of the payload data_scout already fetched
  WALL       no rule -> not registered, named reason, never offered
  CLASS      a schema refusal is OUR fault and never blacklists; only a real fetch
             failure does, and it records which kind
  RESTORE    the un-blacklist migration is exact and idempotent

  venv\\Scripts\\python.exe test\\test_registration_wall.py
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "composers"))
sys.path.insert(0, str(REPO / "experiments" / "needs"))

from core import source_registration as SR   # noqa: E402
import composer as C                          # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


TMP = Path(tempfile.mkdtemp())
SR.DISCARDED = TMP / "discarded.jsonl"


# ── DERIVE: the rule comes out of a real payload ─────────────────────────────

# a USGS-shaped payload: the count lives in a named scalar
usgs = {"type": "FeatureCollection",
        "metadata": {"generated": 1754200000000, "title": "USGS All Earthquakes",
                     "status": 200, "api": "1.10.3", "count": 137},
        "features": [{"type": "Feature", "properties": {"mag": 1.2}},
                     {"type": "Feature", "properties": {"mag": 3.4}}]}
kind, rule, why = SR.derive_rule("json", usgs, "count of earthquakes today")
check("scalar rule derived from a named field",
      kind == "http_json_path" and rule == {"extract": "metadata.count"})
check("...and it is walkable by the composer's own addresser",
      C._dotted(usgs, rule["extract"]) == 137)
check("...with a stated reason", "matches the metric" in why)

# an EONET-shaped payload: the measurement IS the number of dated events
eonet = {"title": "EONET Events", "description": "natural events",
         "events": [{"id": "EONET_1"}, {"id": "EONET_2"}, {"id": "EONET_3"}]}
kind, rule, why = SR.derive_rule("json", eonet, "count of open wildfire events")
check("event-array rule derived", kind == "http_json_count" and rule == {"extract": "events"})
check("...and the composer can count it",
      isinstance(C._dotted(eonet, rule["extract"]), list))

# an open-meteo-shaped payload: parallel arrays, and the date array beside the values
meteo = {"latitude": 51.2, "longitude": 10.4,
         "daily": {"time": ["2026-08-01", "2026-08-02", "2026-08-03"],
                   "shortwave_radiation_sum": [18.4, 21.0, 19.7]}}
kind, rule, why = SR.derive_rule("json", meteo, "daily shortwave radiation sum")
check("series rule derived",
      kind == "http_json_series" and rule.get("extract") == "daily.shortwave_radiation_sum")
check("...and the sibling DATE array is picked up, so staleness stays checkable",
      rule.get("data_date_extract") == "daily.time")

# a NOAA-shaped CSV: the value is the last numeric column, the date is the first
csv = "# comment line\nyear,month,day,cycle,trend\n2026,8,1,424.51,423.90\n"
kind, rule, why = SR.derive_rule("csv", csv, "global mean CO2 trend")
check("csv col rule derived from the last numeric column",
      kind == "http_csv" and rule.get("col") == 4)
check("...and matches what composer.fetch would read",
      float(csv.strip().splitlines()[-1].split(",")[rule["col"]]) == 423.90)

csvd = "date,value\n2026-08-01,17.5\n2026-08-02,18.25\n"
kind, rule, why = SR.derive_rule("csv", csvd, "river discharge")
check("csv date column recognised when present",
      rule.get("col") == 1 and rule.get("data_date_col") == 0)


# ── WALL: no unambiguous rule -> no registration ─────────────────────────────

ambiguous = {"alpha": 1.0, "beta": 2.0, "gamma": 3.0,
             "nested": {"delta": 4.0, "epsilon": 5.0}}
kind, rule, why = SR.derive_rule("json", ambiguous, "some unrelated quantity")
check("an ambiguous payload yields NO rule", kind is None and rule is None)
check("...with a named, countable reason", "no unambiguous parsing rule" in why and "5 numeric" in why)

rec, why = SR.build_candidate("https://example.invalid/a.json", "json", ambiguous,
                              metric="some unrelated quantity", org="X",
                              slot_hint="measurement_daily", axis="AX")
check("build_candidate REFUSES to produce a record without a rule", rec is None)

rec, why = SR.build_candidate("https://example.invalid/u.json", "json", usgs,
                              metric="count of earthquakes today", org="USGS",
                              slot_hint="measurement_daily", axis="AX")
check("a derivable candidate IS registered", rec is not None)
check("...carrying its kind and its rule",
      rec["kind"] == "http_json_path" and rec["extract"] == "metadata.count")
check("...and nothing it needs is missing", SR.missing_fields(rec) == [])
check("...status active, rule provenance recorded",
      rec["status"] == "active" and rec.get("rule_derivation"))

# a tie is refused rather than broken by iteration order
tie = {"events_a": [{"i": 1}, {"i": 2}], "events_b": [{"i": 3}, {"i": 4}]}
kind, _r, why = SR.derive_rule("json", tie, "events")
check("two equally long event arrays are a refusal, not a coin flip", kind is None)

SR.discard("AX", "https://example.invalid/a.json", "no unambiguous parsing rule")
rows = [json.loads(l) for l in SR.DISCARDED.read_text(encoding="utf-8").splitlines() if l.strip()]
check("a dropped candidate is LOGGED", len(rows) == 1 and rows[0]["axis"] == "AX")
check("...and explicitly NOT blacklisted", rows[0]["blacklisted"] is False)


# ── CLASS: whose fault was it? ───────────────────────────────────────────────

check("a bare PromotionRejected is a SCHEMA failure",
      C.classify_failure(C.PromotionRejected("x")) == (C.FAILURE_SCHEMA,
                                                       "incomplete_registration"))
check("an empty smoke read is a FETCH failure",
      C.classify_failure(C.SmokeFetchEmpty("x")) == (C.FAILURE_FETCH, "no_usable_value"))
check("stale data is a FETCH failure, named",
      C.classify_failure(C.StaleData("x")) == (C.FAILURE_FETCH, "stale_data_date"))
check("a parse error is a FETCH failure, named",
      C.classify_failure(KeyError("k")) == (C.FAILURE_FETCH, "unparseable_payload"))
check("an unreachable endpoint is a FETCH failure",
      C.classify_failure(OSError("no route")) == (C.FAILURE_FETCH, "dead_url"))

# the rule wall itself
def rule_refused(entry):
    try:
        C.validate_rule(entry)
        return None
    except C.PromotionRejected as e:
        return str(e)

check("http_json_path without extract is refused by the rule wall",
      "requires 'extract'" in (rule_refused({"kind": "http_json_path", "url": "u"}) or ""))
check("http_csv without col is refused",
      "requires 'col'" in (rule_refused({"kind": "http_csv", "url": "u"}) or ""))
check("http_csv WITH col 0 is accepted (column zero is a real column)",
      rule_refused({"kind": "http_csv", "url": "u", "col": 0}) is None)
check("http_gdelt_tone needs no rule (fixed payload shape)",
      rule_refused({"kind": "http_gdelt_tone", "url": "u"}) is None)
check("the location wall is UNCHANGED — it still only asks about the location",
      rule_refused({"kind": "file", "path": "p", "extract": "a"}) is None
      and C.validate_entry({"kind": "file", "path": "p"}) is True)


# ── promote(): a refused promotion leaves no trace, and says whose fault ─────

SPEC = TMP / "specs.json"
C.SPEC_FILE = SPEC
PROBE = REPO / "test" / "_registration_wall_probe.json"
PROBE.write_text(json.dumps({"block": {"value": 42.0}}), encoding="utf-8")


def fresh_spec():
    SPEC.write_text(json.dumps({"AX": {"portfolio": {"anchor_annual": {
        "min": 1, "sources": []}}}}), encoding="utf-8")


def n_sources():
    return len(json.loads(SPEC.read_text(encoding="utf-8"))
               ["AX"]["portfolio"]["anchor_annual"]["sources"])


fresh_spec()
res = C.promote("AX", "https://example.invalid/x.json", "anchor_annual",
                "http_json_path", "ORG")           # no extract
check("promote without a parsing rule is refused", res.get("rejected") is True)
check("...classed SCHEMA — our record, not their server",
      res.get("failure_class") == C.FAILURE_SCHEMA)
check("...and the spec is untouched", n_sources() == 0)

fresh_spec()
res = C.promote("AX", "https://nothing.invalid/x.json", "anchor_annual",
                "http_json_path", "ORG", extract="a.b")
check("promote whose smoke fetch cannot reach the host is refused",
      res.get("rejected") is True)
check("...classed FETCH — the source was actually asked",
      res.get("failure_class") == C.FAILURE_FETCH)
check("...surfacing the raw exception", bool(res.get("exception")))
check("...spec untouched", n_sources() == 0)

fresh_spec()
res = C.promote("AX", "local://probe", "anchor_annual", "file", "ORG",
                extract="block.value", path="test/_registration_wall_probe.json")
check("a complete, fetchable source promotes", res.get("promoted") and n_sources() == 1)
check("...reporting what it actually read", res.get("smoke_value") == 42.0)

fresh_spec()
res = C.promote("AX", "local://probe", "anchor_annual", "file", "ORG",
                extract="block.value", path="test/_registration_wall_probe.json",
                data_max_age_days=1)
check("a source with no data_date is not falsely called stale", res.get("promoted"))

STALE = REPO / "test" / "_registration_wall_stale.json"
STALE.write_text(json.dumps({"v": 1.0, "when": "2019-01-01"}), encoding="utf-8")
fresh_spec()
res = C.promote("AX", "local://stale", "anchor_annual", "file", "ORG",
                extract="v", path="test/_registration_wall_stale.json",
                data_date_extract="when", data_max_age_days=30)
check("a source whose own data date is years old is refused at promote",
      res.get("rejected") is True and res.get("reason_code") == "stale_data_date")
check("...classed FETCH (it answered; the answer was old)",
      res.get("failure_class") == C.FAILURE_FETCH)
check("...spec untouched", n_sources() == 0)


# ── the approval fork: incomplete is discarded, broken is blacklisted ────────

import approve_reader as A   # noqa: E402

STORE = TMP / "discovered.json"
A.DISCOVERED = STORE


def store_with(status="active", **extra):
    STORE.write_text(json.dumps({"AX": {"sources": [
        {"url": "https://prov.invalid/f.json", "org": "PROV", "format": "json",
         "status": status, **extra}]}}, ensure_ascii=False), encoding="utf-8")


def src():
    return json.loads(STORE.read_text(encoding="utf-8"))["AX"]["sources"][0]


store_with()
check("a schema refusal DISCARDS",
      A._discard_candidate("AX", "https://prov.invalid/f.json", "no parsing rule") is True)
check("...marking it incomplete, NOT rejected", src()["status"] == "incomplete")
check("...and it is not blacklisted by any other name",
      "rejected_why" not in src() and "rejected_at" not in src())

store_with()
check("a real fetch failure BLACKLISTS",
      A._mark_candidate("AX", "https://prov.invalid/f.json", "dead", "dead_url") is True)
check("...as rejected, with the failure named",
      src()["status"] == "rejected" and src()["rejected_class"] == "dead_url")
check("...and says it was actually contacted", "real fetch" in src()["rejected_after"])

r = A._apply_promote({"axis": "AX", "url": "https://x.invalid/a.json", "slot": "s",
                      "kind": "http_json_path", "org": "P", "parse": {}})
check("_apply_promote refuses a rule-less candidate", r.get("ok") is False)
check("...classed SCHEMA, so the caller cannot blacklist it",
      r.get("failure_class") == C.FAILURE_SCHEMA)
check("...and says so in the text Emil reads", "NOT blacklisted" in r.get("error", ""))


# ── RESTORE: the un-blacklist migration ─────────────────────────────────────

MIG = TMP / "migrate.json"
BARRED = ("no parsing rule: kind 'http_json_path' needs an 'extract' path. "
          "Candidate was registered without one — not promoted.")
MIG.write_text(json.dumps({
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": {"sources": [
        {"url": "https://owid.invalid/a.json", "org": "Our World in Data (OWID)",
         "format": "json", "status": "rejected", "rejected_why": BARRED,
         "rejected_at": "2026-08-03T08:37:02+00:00"}]},
    "WATER_REVIEW": {"sources": [
        {"url": "https://wb.invalid/b.json", "org": "World Bank", "format": "json",
         "status": "rejected", "rejected_why": BARRED,
         "rejected_at": "2026-07-31T17:29:02+00:00"},
        {"url": "https://dead.invalid/c.json", "org": "Dead", "format": "json",
         "status": "rejected", "rejected_class": "dead_url",
         "rejected_why": "HTTPError: 404 — the endpoint is gone",
         "rejected_at": "2026-07-31T17:29:02+00:00"}]},
    "_updated": "2026-08-03T00:00:00+00:00",
}, ensure_ascii=False), encoding="utf-8")

res = SR.unblacklist_incomplete(MIG, complete=False)
check("both no-parsing-rule victims are restored", len(res["restored"]) == 2)
check("...named exactly", {r["org"] for r in res["restored"]} ==
      {"Our World in Data (OWID)", "World Bank"})
doc = json.loads(MIG.read_text(encoding="utf-8"))
owid = doc["GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL"]["sources"][0]
check("...status back to active", owid["status"] == "active")
check("...blacklist markers gone",
      not any(k in owid for k in ("rejected_why", "rejected_at", "rejected_class")))
check("...and why it was restored is on the record", "never fetched" in owid["unblacklist_reason"])
dead = doc["WATER_REVIEW"]["sources"][1]
check("a source barred for a REAL fetch failure stays barred",
      dead["status"] == "rejected" and dead["rejected_class"] == "dead_url")

again = SR.unblacklist_incomplete(MIG, complete=False)
check("the migration is idempotent — a second run restores nothing",
      again["restored"] == [])
check("...and does not disturb the store",
      json.loads(MIG.read_text(encoding="utf-8")) == doc)


# ── A6: the axis-fit filter must stay absent, and stay refused in writing ────

src_text = (REPO / "core" / "source_registration.py").read_text(encoding="utf-8")
check("the module states WHY no axis-fit filter may be added",
      "NO AXIS-FIT FILTER" in src_text and "cross-domain" in src_text.lower())

for f in (PROBE, STALE):
    f.unlink(missing_ok=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
