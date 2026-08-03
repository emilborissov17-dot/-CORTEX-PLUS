#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_deterministic_intake.py — feeds that need no model, and a door the system
does not control.

DETERMINISTIC FEEDS (D1). The carve-out is not a privilege, it is a trade. A structured
feed gets to be read with no model in the path; what it pays is a schema contract with no
forgiveness — drift kills it at the FIRST violation, not the third. DEATH_AT=3 exists to
forgive a flaky network. A feed that changed shape is not flaky; it is a different feed,
and two more cycles of reading it would be two more cycles of reading something else under
the old name. An ADDED field is as fatal as a dropped one, for the same reason.

ROW SELECTION. OWID grapher CSVs are panel data: 195 rows, one per country. "The last row"
of that is whichever country sorts last — Zimbabwe's water stress published as the world's.
Correctly fetched, correctly parsed, correctly hashed, and about the wrong thing. So a
source may name its row, and a key that matches nothing FAILS LOUDLY. A fallback there
would convert "the entity I asked for is gone" into "here is a number".

HUMAN SOVEREIGNTY (D2/D3). Every source in the portfolio arrived through one pipeline: an
LLM suggested it, the system probed it, the system offered it. If all a human can approve
is what that pipeline surfaced, the human is ratifying the system's search bubble and
calling it oversight. cortex_ingest is the door the other way, and what comes through it
meets exactly the same walls.

  venv\\Scripts\\python.exe test\\test_deterministic_intake.py
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "composers"))
sys.path.insert(0, str(REPO / "scripts"))

import composer as C        # noqa: E402
import cortex_ingest as CI  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


TMP = Path(tempfile.mkdtemp())

# a panel exactly like an OWID grapher csvType=filtered response
PANEL = ("entity,code,year,water_stress\n"
         "Afghanistan,AFG,2022,54.76\n"
         "India,IND,2022,66.49\n"
         "World,OWID_WRL,2022,18.62\n"
         "Kuwait,KWT,2022,3850.5\n"
         "Zimbabwe,ZWE,2022,21.3\n")


def csv_src(**kw):
    src = {"kind": "http_csv", "url": "https://panel.invalid/x.csv"}
    src.update(kw)
    return src


# ── ROW SELECTION ────────────────────────────────────────────────────────────

cells, dd = C._csv_select(csv_src(row_key="World"), PANEL)
check("a named row is selected by its key", cells[0] == "World")
check("...and the named column is read off THAT row",
      float(cells[C._csv_col(csv_src(column_name="water_stress"), PANEL)]) == 18.62)
check("row_key_column defaults to 'entity'", C._csv_select(csv_src(row_key="India"),
                                                           PANEL)[0][0] == "India")
check("the last row is NOT what a keyed read returns — that was the whole bug",
      cells[0] != "Zimbabwe")

# without a key the old behaviour is untouched
check("a source with no row_key still reads the last row (single-series feeds unchanged)",
      C._csv_select(csv_src(), PANEL)[0][0] == "Zimbabwe")


def fails_with(src, text=PANEL):
    try:
        C._csv_select(src, text)
        C._csv_col(src, text)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


err = fails_with(csv_src(row_key="Atlantis"))
check("a key matching NO row is a loud failure", err is not None)
check("...naming the key that was asked for", "Atlantis" in err)
check("...showing what WAS there, so the human can see what changed",
      "Afghanistan" in err or "World" in err)
check("...and saying in words that it refuses to substitute another row",
      "answer a question nobody asked" in err)
check("...it is a named exception type, not a bare ValueError",
      err.startswith("CsvRowNotFound"))

check("a column_name the provider dropped is a loud failure too",
      "column_name 'gone'" in (fails_with(csv_src(row_key="World",
                                                  column_name="gone")) or ""))
check("a row_key_column that is not in the header fails by name",
      "row_key_column 'country'" in (fails_with(csv_src(row_key="World",
                                                        row_key_column="country")) or ""))
check("asking for a keyed row in a headerless payload fails rather than guessing",
      "no header row" in (fails_with(csv_src(row_key="World"), "1,2\n3,4\n") or ""))

check("column_name resolves by header, so an inserted column does not shift the read",
      C._csv_col(csv_src(column_name="year"), PANEL) == 2
      and C._csv_col(csv_src(column_name="year"),
                     PANEL.replace("entity,code,", "entity,NEW,code,")
                          .replace(",AFG,", ",x,AFG,")) == 3)
check("a date column can be named too",
      C._csv_select(csv_src(row_key="World", data_date_column="year"), PANEL)[1] == "2022")

def rule_refused(entry):
    try:
        C.validate_rule(entry)
        return None
    except C.PromotionRejected as e:
        return str(e)


check("the parsing-rule wall accepts column_name in place of col",
      C.validate_rule(csv_src(column_name="water_stress")) is True)
check("an http_csv with neither col nor column_name is refused, naming both",
      "'col' or 'column_name'" in (rule_refused({"kind": "http_csv", "url": "u"}) or ""))


# ── SCHEMA CONTRACT: drift kills at 1 ────────────────────────────────────────

fp = C.schema_fingerprint("http_json_path", {"a": 1, "b": {"c": 2}})
check("a dict payload fingerprints to its top-level keys", fp == {"type": "dict",
                                                                 "keys": ["a", "b"]})
check("a csv fingerprints to its header and width",
      C.schema_fingerprint("http_csv", PANEL)
      == {"type": "csv", "n_cols": 4, "header": ["entity", "code", "year", "water_stress"]})
check("a headerless csv says so rather than inventing a header",
      C.schema_fingerprint("http_csv", "1,2,3\n4,5,6\n")["header"] is None)

base = {"type": "dict", "keys": ["a", "b"]}
check("an unchanged shape is no violation", C.schema_diff(base, dict(base)) == "")
check("a DROPPED field kills",
      "dropped ['b']" in C.schema_diff(base, {"type": "dict", "keys": ["a"]}))
check("an UNEXPECTED field kills just as hard — same reason, both mean a different feed",
      "unexpected ['c']" in C.schema_diff(base, {"type": "dict", "keys": ["a", "b", "c"]}))
check("a changed payload TYPE kills",
      "type changed" in C.schema_diff(base, {"type": "list", "element_keys": None}))
check("a csv that gained a column kills",
      C.schema_diff(C.schema_fingerprint("http_csv", PANEL),
                    C.schema_fingerprint("http_csv", PANEL.replace("year,", "year,extra,")))
      != "")
check("no declared schema means nothing to violate (non-deterministic sources unaffected)",
      C.check_schema({"kind": "http_json_path"}, {"anything": 1}) == "")

# ...and it actually kills, in compose(), at the first violation
AXIS = "DETAX"
C.SPEC_FILE = TMP / "specs.json"
C.STATE_DIR = TMP / "state"
C.NEEDS_FILE = TMP / "needs.json"
C.OUT_FILE = TMP / "out.json"
C.DISCOVERED = TMP / "disc.json"
FEED = REPO / "test" / "_deterministic_feed.json"


def write_spec(deterministic=True):
    C.SPEC_FILE.write_text(json.dumps({AXIS: {
        "anchor_slot": "anchor_annual", "measure_slot": "measurement_daily",
        "portfolio": {"anchor_annual": {"min": 1, "freshness_days": 400, "sources": [
            {"id": "det", "kind": "file", "path": "test/_deterministic_feed.json",
             "extract": "value", "org": "T", "unit": "u",
             "deterministic": deterministic,
             "schema": {"type": "dict", "keys": ["as_of", "value"]}}]}}}}),
        encoding="utf-8")


FEED.write_text(json.dumps({"value": 12.0, "as_of": "2026-08-03"}), encoding="utf-8")
write_spec()
C.STATE_DIR.mkdir(parents=True, exist_ok=True)
(C.STATE_DIR / f"{AXIS}.json").unlink(missing_ok=True)
r = C.compose(AXIS, force=True)
check("a deterministic feed matching its contract composes normally",
      r["slots"]["anchor_annual"]["filled"] is True)

FEED.write_text(json.dumps({"value": 12.0, "as_of": "2026-08-03", "note": "hello"}),
                encoding="utf-8")
r = C.compose(AXIS, force=True)
st = json.loads((C.STATE_DIR / f"{AXIS}.json").read_text(encoding="utf-8"))["sources"]["det"]
check("ONE unexpected field and the source is DEAD — not on the third strike, the first",
      st["status"] == "dead")
check("...and the composer says which field", "unexpected ['note']" in st["last_error"])
check("...raising a schema_violation need, not a generic death",
      any(n["kind"] == "schema_violation" for n in r["needs"]))
check("...the slot is now empty rather than quietly holding a stale reading",
      r["slots"]["anchor_annual"]["filled"] is False)

# the same drift on a NON-deterministic source is not fatal — no contract, no breach
FEED.write_text(json.dumps({"value": 12.0, "as_of": "2026-08-03", "note": "hello"}),
                encoding="utf-8")
write_spec(deterministic=False)
(C.STATE_DIR / f"{AXIS}.json").unlink(missing_ok=True)
r = C.compose(AXIS, force=True)
check("an ordinary source is NOT killed by the same drift — it never contracted to a shape",
      r["slots"]["anchor_annual"]["filled"] is True)


# ── the carve-out's conditions, at promotion ─────────────────────────────────

C.SPEC_FILE.write_text(json.dumps({AXIS: {"portfolio": {
    "anchor_annual": {"min": 1, "sources": []}}}}), encoding="utf-8")


def n_sources():
    return len(json.loads(C.SPEC_FILE.read_text(encoding="utf-8"))
               [AXIS]["portfolio"]["anchor_annual"]["sources"])


res = C.promote(AXIS, "https://gdelt.invalid/x", "anchor_annual", "http_gdelt_tone", "G",
                deterministic=True)
check("a kind needing interpretation cannot be deterministic", res.get("rejected") is True)
check("...named as the model-in-the-read-path problem it is",
      "model in the read path" in res.get("error", ""))
check("...and refused as a SCHEMA fault, before any request — so a dead host cannot "
      "preempt it and let it through when the host recovers",
      res.get("failure_class") == C.FAILURE_SCHEMA)
check("...and the spec is untouched", n_sources() == 0)

FEED.write_text(json.dumps({"value": 12.0, "as_of": "2026-08-03"}), encoding="utf-8")
res = C.promote(AXIS, "local://det", "anchor_annual", "file", "T", extract="value",
                path="test/_deterministic_feed.json", deterministic=True)
check("a structured deterministic source promotes", res.get("promoted") is not None)
check("...and the smoke fetch IS the schema validation — the contract is captured there",
      res["schema"] == {"type": "dict", "keys": ["as_of", "value"]})
check("...so there is no window where it is trusted without one",
      res.get("deterministic") is True)

C.SPEC_FILE.write_text(json.dumps({AXIS: {"portfolio": {
    "anchor_annual": {"min": 1, "sources": []}}}}), encoding="utf-8")
res = C.promote(AXIS, "local://det", "anchor_annual", "file", "T", extract="value",
                path="test/_deterministic_feed.json", deterministic=True,
                schema={"type": "dict", "keys": ["value", "nonexistent"]})
check("a DECLARED schema that does not match what was fetched is refused",
      res.get("rejected") is True and "declared schema does not match" in res["error"])
check("...spec untouched", n_sources() == 0)


# ── D3: the door the system does not control ─────────────────────────────────

PROBE = REPO / "test" / "_ingest_probe.json"
PROBE.write_text(json.dumps({"readings": {"level_m": 3.42}, "as_of": "2026-08-03"}),
                 encoding="utf-8")
CI.DISCOVERED = TMP / "ingested.json"

# A URL the system never proposed, handed over by a human. Both the probe AND the transport
# under composer.fetch are stubbed to the same bytes — stubbing only the probe would let the
# smoke fetch reach for the real network and "prove" nothing but that .invalid does not
# resolve. The point is that the smoke fetch runs the REAL loader over the real payload.
_real_probe, _real_http = CI.SR.probe, C._http
PAYLOAD = PROBE.read_text(encoding="utf-8")
CI.SR.probe = lambda url, fmt="json", timeout=15: (
    (json.loads(PAYLOAD), None) if "never-seen" in url
    else (None, "ConnectionError: no such host"))
C._http = lambda url, timeout=15: PAYLOAD
try:
    t = CI.ingest("https://never-seen-by-the-system.invalid/gauge.json",
                  axis="WATER_REVIEW", slot="measurement_daily",
                  metric="water level in metres", org="A Human's Gauge",
                  overrides={"path": None, "extract": "readings.level_m"})
finally:
    CI.SR.probe, C._http = _real_probe, _real_http

steps = {s["step"]: s for s in t["steps"]}
check("a URL the system never discovered is accepted for ingest", steps["probe"]["ok"])
check("...the human's declared rule wins over the walker's guess",
      steps["derive"]["source"] == "declared by the human")
check("...it meets the SAME schema wall as anything self-discovered",
      steps["schema_wall"]["ok"] and
      steps["schema_wall"]["checked"] == ["location", "parsing rule"])
check("...and the SAME smoke fetch, through composer.fetch", steps["smoke_fetch"]["ok"])
check("...reporting the value it actually read", steps["smoke_fetch"]["value"] == 3.42)
check("...registered as a candidate under the axis", steps["register"]["ok"])
check("...and NOT promoted — that stays Emil's separate act",
      "promote" not in steps and "NOT promoted" in t["result"])
check("...it is recorded as human-proposed, not as a discovery",
      json.loads(CI.DISCOVERED.read_text(encoding="utf-8"))
      ["WATER_REVIEW"]["sources"][0]["proposed_by"] == "human")
check("...and it carries its origin and reporter class like any other source",
      t["origin"] == "never-seen-by-the-system.invalid"
      and t["reporter_class"]["class"] == "unknown")

CI.SR.probe = lambda url, fmt="json", timeout=15: (None, "ConnectionError: no such host")
try:
    t = CI.ingest("https://dead.invalid/x.json", axis="WATER_REVIEW")
finally:
    CI.SR.probe = _real_probe
check("a URL that cannot be read is refused, verbatim",
      "ConnectionError" in t["steps"][0]["error"] and "REFUSED" in t["result"])
check("...and nothing was registered on the way",
      "register" not in {s["step"] for s in t["steps"]})

CI.SR.probe = lambda url, fmt="json", timeout=15: ({"a": 1.0, "b": 2.0, "c": 3.0}, None)
try:
    t = CI.ingest("https://ambiguous.invalid/x.json", axis="WATER_REVIEW",
                  metric="nothing that matches")
finally:
    CI.SR.probe = _real_probe
check("an ambiguous payload is refused rather than guessed at", "REFUSED" in t["result"])
check("...and tells the human exactly how to resolve it themselves",
      "--extract" in t["result"] and "--column-name" in t["result"])

check("the ingest path is a SEPARATE file, so cortex_query keeps its guarantee",
      (REPO / "scripts" / "cortex_ingest.py").exists()
      and "subprocess" not in (REPO / "scripts" / "cortex_query.py")
      .read_text(encoding="utf-8"))
check("...and says why in its docstring, so it is not merged back in later",
      "different files" in CI.__doc__ and "search bubble" in CI.__doc__)

for f in (FEED, PROBE):
    f.unlink(missing_ok=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
