#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_origin_honesty.py — what the portfolio stands on, and who measured it.

TWO LIES BY OMISSION, both live and both measurable:

ORIGIN. Diversity was counted as distinct `org` strings — free text an LLM wrote at
discovery. 41 of the 43 file-kind sources in the live spec read ONE file,
snapshots/master/global_indicators_latest.json, under 15 different org labels. So the
number said "diversified" about a portfolio standing on a single file, and a slot holding
two sources from that one file reported `filled` — quietly promising a redundancy that
does not exist.

REPORTER INDEPENDENCE. The guard stack proves we did not invent a number and did read it
correctly. It cannot ask whether the number is TRUE, and world_bank.safe_water_access_pct
originates from national statistical offices: the measured entity reporting on itself.
This is made visible, never scored — the load-bearing test in this file is
`the class changes NO number anywhere`, because discounting a government statistic would
be asserting a truth we have no evidence for.

  venv\\Scripts\\python.exe test\\test_origin_honesty.py
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "composers"))
sys.path.insert(0, str(REPO / "scripts"))

import provenance as P      # noqa: E402
import composer as C        # noqa: E402
import cortex_query as CQ   # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


TMP = Path(tempfile.mkdtemp())
SNAP = "snapshots/master/global_indicators_latest.json"


# ── C1: origin is what a source RESOLVES to ─────────────────────────────────

check("a file source's origin is its path",
      P.origin({"kind": "file", "path": SNAP, "url": "local://x", "org": "UNHCR"}) == SNAP)
check("...NOT its url, which on a file entry is only an identity reference",
      P.origin({"kind": "file", "path": SNAP, "url": "https://unhcr.org/a"}) == SNAP)
check("an http source's origin is its host",
      P.origin({"kind": "http_csv", "url": "https://gml.noaa.gov/webdata/x.csv",
                "org": "NOAA-GML"}) == "gml.noaa.gov")
check("...port, scheme and userinfo are not part of it",
      P.origin({"kind": "http_json_path",
                "url": "https://u:p@API.Example.COM:8443/a/b"}) == "api.example.com")
check("an explicit human-set origin wins — that is the case derivation cannot know",
      P.origin({"kind": "file", "path": SNAP, "origin": "World Bank (via snapshot)"})
      == "World Bank (via snapshot)")

# the live shape: two orgs, one origin
two_labels_one_file = [
    {"id": "gi_refugees_millions", "kind": "file", "path": SNAP, "org": "UNHCR"},
    {"id": "promoted_96302", "kind": "file", "path": SNAP, "org": "UCDP/PRIO"},
]
conc = P.concentration(two_labels_one_file)
check("two different org LABELS on one file is one origin", conc["n_origins"] == 1)
check("...100% concentration, flagged", conc["top_share"] == 1.0 and conc["concentrated"])

mixed = two_labels_one_file + [
    {"id": "noaa", "kind": "http_csv", "url": "https://gml.noaa.gov/a.csv", "org": "NOAA"}]
check("a genuinely mixed axis is not flagged at the 50% line",
      P.concentration(mixed)["top_share"] == round(2 / 3, 3)
      and P.concentration(mixed)["concentrated"] is True)
check("...and a 50/50 split is NOT over the line (strictly greater)",
      P.concentration(two_labels_one_file[:1] + mixed[2:])["concentrated"] is False)


# ── C3: nominally_filled ─────────────────────────────────────────────────────

st, note = P.slot_status(two_labels_one_file, 1)
check("a slot whose min is met only by one origin is NOMINALLY filled",
      st == "nominally_filled")
check("...and says why in words a human can act on",
      "one origin" in note and "labels, not in the provenance" in note)
st1, note1 = P.slot_status(two_labels_one_file[:1], 1)
check("a SINGLE-source slot is nominal too — one origin is one origin",
      st1 == "nominally_filled")
check("...but is not accused of a false redundancy it never claimed",
      "as reliable as" in note1 and "labels" not in note1)
check("a slot met across two origins is genuinely filled",
      P.slot_status(mixed, 1)[0] == "filled")
check("a slot below its min is unfilled, not nominal",
      P.slot_status(two_labels_one_file, 5)[0] == "unfilled")
check("an empty slot is unfilled", P.slot_status([], 1)[0] == "unfilled")


# ── C5: reporter independence, human-owned ───────────────────────────────────

CFG = {"confirmed": {
    "org:World Bank": {"class": "self_reported", "why": "national statistical offices",
                       "confirmed_by": "Emil"},
    "host:gml.noaa.gov": {"class": "independent", "why": "instrument record",
                          "confirmed_by": "Emil"},
}, "proposed": {
    "org:Ministry of Truth": {"class": "independent", "why": "the system thought so"},
}}

cls, why = P.reporter_class({"kind": "file", "path": SNAP, "org": "World Bank"}, CFG)
check("a CONFIRMED org mapping is applied", cls == "self_reported")
check("...carrying the human's reason and name", "national statistical offices" in why
      and "confirmed by Emil" in why)

cls, _w = P.reporter_class({"kind": "http_csv", "url": "https://gml.noaa.gov/a.csv",
                            "org": "World Bank"}, CFG)
check("host beats org — the most specific thing we know wins", cls == "independent")

cls, why = P.reporter_class({"kind": "file", "path": SNAP, "org": "Somebody New"}, CFG)
check("an UNMAPPED org is unknown", cls == "unknown")
check("...and unknown is never read as independent", "never read as independent" in why)

cls, _w = P.reporter_class({"org": "Ministry of Truth"}, CFG)
check("a PROPOSED class is inadmissible until a human confirms it", cls == "unknown")

cls, _w = P.reporter_class({"org": "X", "reporter_class": "independent"}, CFG)
check("a class the system wrote onto its own record is ignored", cls == "unknown")
cls, why = P.reporter_class({"org": "X", "reporter_class": "independent",
                             "reporter_class_confirmed_by": "Emil"}, CFG)
check("...and honoured once a human signs it", cls == "independent" and "by Emil" in why)

cls, _w = P.reporter_class({"org": "X", "reporter_class": "obviously_true",
                            "reporter_class_confirmed_by": "Emil"}, CFG)
check("a class outside the taxonomy is not admitted even from a human", cls == "unknown")

sh = P.class_shares([{"org": "World Bank"}, {"org": "World Bank"}], CFG)
check("an axis measured entirely by its own subject is flagged self_reported_only",
      sh["self_reported_only"] is True)
check("...and one independent source clears the flag",
      P.class_shares([{"org": "World Bank"},
                      {"url": "https://gml.noaa.gov/a.csv"}], CFG)["self_reported_only"]
      is False)
check("all-unknown is NOT self_reported_only (unknown is not a verdict either way)",
      P.class_shares([{"org": "Nobody"}], CFG)["self_reported_only"] is False)
check("the unmapped queue names both the org and the host to rule on",
      P.unmapped_keys([{"org": "Nobody", "url": "https://who.invalid/a"}], CFG)
      == ["host:who.invalid", "org:Nobody"])


# ── C6: THE LOAD-BEARING ONE — the class changes no number anywhere ──────────

AXIS = "TESTAX"
C.SPEC_FILE = TMP / "specs.json"
C.STATE_DIR = TMP / "state"
C.NEEDS_FILE = TMP / "needs.json"
C.OUT_FILE = TMP / "out.json"
C.DISCOVERED = TMP / "disc.json"
PROBE = REPO / "test" / "_origin_honesty_probe.json"
PROBE.write_text(json.dumps({"a": 1.0, "b": 2.0}), encoding="utf-8")

C.SPEC_FILE.write_text(json.dumps({AXIS: {
    "anchor_slot": "anchor_annual", "measure_slot": "measurement_daily",
    "portfolio": {
        "anchor_annual": {"min": 1, "freshness_days": 400, "sources": [
            {"id": "s1", "kind": "file", "path": "test/_origin_honesty_probe.json",
             "extract": "a", "org": "World Bank", "unit": "u"},
            {"id": "s2", "kind": "file", "path": "test/_origin_honesty_probe.json",
             "extract": "b", "org": "UNHCR", "unit": "u"}]},
        "measurement_daily": {"min": 1, "freshness_days": 400, "sources": [
            {"id": "s3", "kind": "file", "path": "test/_origin_honesty_probe.json",
             "extract": "a", "org": "FAO/WB", "unit": "u"}]},
    }}}), encoding="utf-8")


def compose_with(cfg):
    _real = P.reporter_config
    P.reporter_config = lambda path=None: cfg
    try:
        C.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (C.STATE_DIR / f"{AXIS}.json").unlink(missing_ok=True)
        return C.compose(AXIS, force=True)
    finally:
        P.reporter_config = _real


with_cfg = compose_with(CFG)
without_cfg = compose_with({"confirmed": {}})

check("with the mapping, the confirmed org is actually classed",
      with_cfg["reporter_independence"]["counts"]["self_reported"] == 1)
check("...and the two orgs it does not cover stay unknown",
      with_cfg["reporter_independence"]["counts"]["unknown"] == 2)
check("without any mapping, everything is unknown",
      without_cfg["reporter_independence"]["counts"]["unknown"] == 3)

check("THE CLASS CHANGES NO NUMBER: confidence is byte-identical",
      json.dumps(with_cfg["confidence"]) == json.dumps(without_cfg["confidence"]))
check("...nor its parts", json.dumps(with_cfg["confidence_parts"], sort_keys=True)
      == json.dumps(without_cfg["confidence_parts"], sort_keys=True))
check("...nor the composed VALUES",
      [with_cfg["composed"][k]["value"] for k in ("anchor", "daily")]
      == [without_cfg["composed"][k]["value"] for k in ("anchor", "daily")]
      and with_cfg["composed"]["divergence"] == without_cfg["composed"]["divergence"])
check("...nor the slot verdicts",
      [s["status"] for s in with_cfg["slots"].values()]
      == [s["status"] for s in without_cfg["slots"].values()])


# The class DOES appear on a source record and in the axis tally — that is the visibility
# it exists for. The claim being tested is narrower and stronger: it appears THERE and
# NOWHERE ELSE. Strip the three places it is allowed to show up and the two reports must
# be identical down to the byte, which is what proves the class annotates and never
# propagates into anything that is computed with.
ANNOTATION = {"reporter_class", "reporter_why"}
DECLARED = {"reporter_independence", "unmapped_reporters", "ts"}


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in ANNOTATION | DECLARED}
    if isinstance(x, list):
        return [strip(v) for v in x if not (isinstance(v, dict)
                                            and v.get("kind") == "self_reported_only")]
    return x


check("STRIPPED OF THE ANNOTATION, THE TWO REPORTS ARE IDENTICAL — the class propagates "
      "into nothing",
      json.dumps(strip(with_cfg), sort_keys=True)
      == json.dumps(strip(without_cfg), sort_keys=True))
check("the module says so in writing, so nobody 'improves' it later",
      "NEVER SCORED" in P.__doc__ and "never_scored" in
      json.dumps(with_cfg["reporter_independence"]))


# ── C2/C4: what compose() now reports ────────────────────────────────────────

check("both slots meet their min", all(s["filled"] for s in with_cfg["slots"].values()))
check("...and BOTH are reported nominally filled, because it is one file",
      all(s["nominally_filled"] for s in with_cfg["slots"].values()))
check("a nominally-filled slot raises a NEED, it does not pass quietly",
      sum(1 for n in with_cfg["needs"] if n["kind"] == "slot_nominally_filled") == 2)
check("the axis is flagged origin_concentrated",
      with_cfg["origin_concentration"]["concentrated"] is True
      and any(n["kind"] == "origin_concentrated" for n in with_cfg["needs"]))
check("...naming the one origin everything resolves to",
      with_cfg["origin_concentration"]["top_origin"]
      == "test/_origin_honesty_probe.json")
check("an all-self-reported axis raises self_reported_only",
      any(n["kind"] == "self_reported_only" for n in
          compose_with({"confirmed": {"org:World Bank": {"class": "self_reported",
                                                         "confirmed_by": "Emil"},
                                      "org:UNHCR": {"class": "self_reported",
                                                    "confirmed_by": "Emil"},
                                      "org:FAO/WB": {"class": "self_reported",
                                                     "confirmed_by": "Emil"}}})["needs"]))

check("DIVERSITY IS NOW ORIGINS: 3 labels on 1 file scores 1 origin over 2 slots",
      with_cfg["confidence_parts"]["diversity"] == 0.5)
check("...and says what it is counting",
      with_cfg["confidence_parts"]["diversity_basis"] == "distinct ORIGINS across filled slots")
check("the label count is still published, and higher — that is the point",
      with_cfg["label_diversity"]["value"] == 1.0
      and with_cfg["label_diversity"]["value"] > with_cfg["confidence_parts"]["diversity"])
check("...explicitly named as labels, not origins",
      "not origins" in with_cfg["label_diversity"]["basis"])


# ── the duplication in cortex_query must never drift ─────────────────────────

live = json.loads((REPO / "config" / "composer_specs.json").read_text(encoding="utf-8"))
live_srcs = [s for ax, body in live.items() if not ax.startswith("_")
             for sl in (body.get("portfolio") or {}).values()
             for s in sl.get("sources", [])]
confirmed = (json.loads((REPO / "config" / "reporter_independence.json")
                        .read_text(encoding="utf-8")).get("confirmed") or {})
cfg_live = {"confirmed": confirmed}

check(f"the live spec has sources to compare ({len(live_srcs)})", len(live_srcs) > 40)
check("cortex_query's origin() agrees with provenance on EVERY live source",
      all(CQ._origin(s) == P.origin(s) for s in live_srcs))
check("...and its reporter lookup agrees too",
      all(CQ._reporter(s, confirmed) == P.reporter_class(s, cfg_live)[0] for s in live_srcs))
check("the duplication is declared, not accidental",
      "DELIBERATE DUPLICATION" in (REPO / "scripts" / "cortex_query.py")
      .read_text(encoding="utf-8"))

import ast   # noqa: E402
tree = ast.parse((REPO / "scripts" / "cortex_query.py").read_text(encoding="utf-8"))
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported |= {a.name.split(".")[0] for a in node.names}
    elif isinstance(node, ast.ImportFrom):
        imported.add((node.module or "").split(".")[0])
check("--clock added no project import — the read path stays unmediated",
      imported <= {"argparse", "json", "random", "sys", "datetime", "pathlib", "__future__"})
check("...and specifically no subprocess, which would reopen the gate for every command",
      "subprocess" not in imported)


# ── C7: the live distribution, which is the actual deliverable ───────────────

live_shares = P.class_shares(live_srcs, cfg_live)
n = live_shares["n_sources"]
print(f"\nLIVE PORTFOLIO ({n} sources):")
for c in P.CLASSES:
    print(f"  {c:<16} {live_shares['counts'][c]:>4}  {live_shares['shares'][c]:>6.0%}")
check("most of the portfolio is self-reported, and the number is visible",
      live_shares["counts"]["self_reported"] > live_shares["counts"]["independent"])
check("nothing landed in unknown by accident of seeding — the queue is short and named",
      len(P.unmapped_keys(live_srcs, cfg_live)) <= 4)

PROBE.unlink(missing_ok=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
