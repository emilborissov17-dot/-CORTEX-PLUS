#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_official_readers.py — the three payload families that carry official statistics.

Every payload below is a REAL response, trimmed: probed live 2026-08-03 and pasted, not
imagined. No network runs in this file.

WHAT IS ACTUALLY BEING GUARDED. Grounding, Merkle and the smoke fetch all verify that we
read CORRECTLY. Not one of them can notice that we read the WRONG CELL — a value pulled
from the wrong country, the wrong dimension or the wrong series is real, well-formed,
correctly hashed, and about something nobody asked about. That failure survives every
layer we have closed. So each reader resolves a DECLARED address and, when the address
matches nothing, raises with the address named and the codes that were actually present.
The tests below spend most of their effort on that refusal, not on the happy path.

  venv\\Scripts\\python.exe test\\test_official_readers.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "composers"))

import readers as R    # noqa: E402
import composer as C   # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ── UN SDG: row-shaped JSON ──────────────────────────────────────────────────
# GET unstats.un.org/sdgapi/v1/sdg/Series/Data?seriesCode=SH_H2O_SAFE&areaCode=1
UNSDG = {"totalElements": 75, "data": [
    {"series": "SH_H2O_SAFE", "geoAreaCode": "1", "geoAreaName": "World",
     "timePeriodStart": 2000.0, "value": "61.26163483",
     "attributes": {"Units": "PERCENT"}, "dimensions": {"Location": "ALLAREA"}},
    {"series": "SH_H2O_SAFE", "geoAreaCode": "1", "geoAreaName": "World",
     "timePeriodStart": 2024.0, "value": "73.73517609",
     "attributes": {"Units": "PERCENT"}, "dimensions": {"Location": "ALLAREA"}},
    {"series": "SH_H2O_SAFE", "geoAreaCode": "1", "geoAreaName": "World",
     "timePeriodStart": 2024.0, "value": "92.11",
     "attributes": {"Units": "PERCENT"}, "dimensions": {"Location": "URBAN"}},
    {"series": "SH_H2O_SAFE", "geoAreaCode": "4", "geoAreaName": "Afghanistan",
     "timePeriodStart": 2024.0, "value": "30.1",
     "attributes": {"Units": "PERCENT"}, "dimensions": {"Location": "ALLAREA"}},
]}
SDG_SRC = {"extract": "data", "row_key_column": "geoAreaCode", "row_key": "1",
           "where": {"dimensions.Location": "ALLAREA"},
           "column_name": "value", "data_date_column": "timePeriodStart"}

v, dd = R.read_json_rows(UNSDG, SDG_SRC)
check("UN SDG: the World row is selected, not row 0", v == 73.73517609)
check("...the LATEST period among matches wins", dd == "2024.0")
check("...and a STRING value is read as a number — UN SDG publishes strings",
      isinstance(v, float))
check("a second dimension filter discriminates within the same entity and year",
      R.read_json_rows(UNSDG, dict(SDG_SRC,
                                   where={"dimensions.Location": "URBAN"}))[0] == 92.11)
check("a different entity gives a different number, proving the key does the work",
      R.read_json_rows(UNSDG, dict(SDG_SRC, row_key="4"))[0] == 30.1)

err = raises(R.read_json_rows, UNSDG, dict(SDG_SRC, row_key="999"))
check("an entity that is not there RAISES", err is not None)
check("...naming the key asked for", "'999'" in err)
check("...listing what WAS present", "'1'" in err and "'4'" in err)
check("...and refusing to substitute", "answer a question nobody asked" in err)
check("a where-filter that matches nothing raises too",
      raises(R.read_json_rows, UNSDG,
             dict(SDG_SRC, where={"dimensions.Location": "LUNAR"})) is not None)
check("a column that carries no number raises rather than returning None",
      raises(R.read_json_rows, UNSDG, dict(SDG_SRC, column_name="geoAreaName")) is not None)
check("an extract that is not an array is a named failure",
      "not an array" in (raises(R.read_json_rows, UNSDG,
                                dict(SDG_SRC, extract="totalElements")) or ""))


# ── EUROSTAT: JSON-stat 2.0 ──────────────────────────────────────────────────
# GET ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m?format=JSON
JSONSTAT = {
    "class": "dataset", "label": "Unemployment by sex and age - monthly data",
    "source": "ESTAT", "updated": "2026-07-31T11:00:00+0200",
    "id": ["s_adj", "geo", "time"], "size": [2, 2, 2],
    "dimension": {
        "s_adj": {"label": "Seasonal adjustment",
                  "category": {"index": {"SA": 0, "NSA": 1}}},
        "geo": {"label": "Geopolitical entity",
                "category": {"index": {"EU27_2020": 0, "DE": 1}}},
        "time": {"label": "Time", "category": {"index": {"2026-05": 0, "2026-06": 1}}},
    },
    # row-major over size [2,2,2]: idx = s_adj*4 + geo*2 + time
    "value": {"0": 6.2, "1": 6.0, "2": 3.4, "3": 3.3,
              "4": 6.9, "5": 6.7, "6": 3.8, "7": 3.7},
}

v, dd = R.read_jsonstat(JSONSTAT, {"cell": {"s_adj": "SA", "geo": "EU27_2020"}})
check("JSON-stat: the flat index is computed row-major and resolves the right cell",
      v == 6.0)
check("...an unpinned time dimension resolves to the LATEST period", dd == "2026-06")
check("pinning a different geo moves to a different cell",
      R.read_jsonstat(JSONSTAT, {"cell": {"s_adj": "SA", "geo": "DE"}})[0] == 3.3)
check("pinning a different adjustment moves again",
      R.read_jsonstat(JSONSTAT, {"cell": {"s_adj": "NSA", "geo": "DE"}})[0] == 3.7)
check("pinning time explicitly reads that period, not the latest",
      R.read_jsonstat(JSONSTAT, {"cell": {"s_adj": "SA", "geo": "EU27_2020",
                                          "time": "2026-05"}}) == (6.2, "2026-05"))

err = raises(R.read_jsonstat, JSONSTAT, {"cell": {"s_adj": "SA", "geo": "ATLANTIS"}})
check("a category that does not exist RAISES", err is not None)
check("...naming the dimension and the code", "'geo'" in err and "'ATLANTIS'" in err)
check("...listing the categories that ARE there", "EU27_2020" in err)
check("...and refusing to read a neighbouring category",
      "answer a question nobody asked" in err)

err = raises(R.read_jsonstat, JSONSTAT, {"cell": {"s_adj": "SA"}})
check("an UNPINNED multi-category dimension is an ambiguous address, and raises",
      err is not None and "ambiguous" in err)
check("...rather than silently taking index 0, which is how you publish Germany as the EU",
      "geo" in err)
check("naming a dimension the dataset does not have is a named failure",
      "not in this dataset" in (raises(R.read_jsonstat, JSONSTAT,
                                       {"cell": {"nope": "x"}}) or ""))
check("a single-category dimension needs no pin",
      R.read_jsonstat({"id": ["geo", "time"], "size": [1, 2],
                       "dimension": {"geo": {"category": {"index": {"EU": 0}}},
                                     "time": {"category": {"index": {"2025": 0,
                                                                     "2026": 1}}}},
                       "value": {"0": 1.0, "1": 2.0}}, {}) == (2.0, "2026"))
check("a cell the provider left empty raises instead of returning None",
      "published no value" in (raises(R.read_jsonstat,
                                      dict(JSONSTAT, value={"0": 6.2}),
                                      {"cell": {"s_adj": "SA", "geo": "EU27_2020",
                                                "time": "2026-06"}}) or ""))


# ── SDMX-JSON, both shapes one reader ────────────────────────────────────────
# shape A, series-major — data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A
ECB = {"header": {"id": "x"}, "dataSets": [{"action": "Replace", "series": {
    "0:0:0:0:0": {"observations": {"0": [1.1485, 0, 0, None, None]}}}}],
    "structure": {"dimensions": {
        "series": [{"id": "FREQ", "values": [{"id": "D"}]},
                   {"id": "CURRENCY", "values": [{"id": "USD"}]},
                   {"id": "CURRENCY_DENOM", "values": [{"id": "EUR"}]},
                   {"id": "EXR_TYPE", "values": [{"id": "SP00"}]},
                   {"id": "EXR_SUFFIX", "values": [{"id": "A"}]}],
        "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-07-31"}]}]}}}

v, dd = R.read_sdmx(ECB, {"series_key": {"FREQ": "D", "CURRENCY": "USD"}})
check("SDMX series-major (ECB) resolves", v == 1.1485 and dd == "2026-07-31")

# shape B, fully flat — sdmx.oecd.org ... &dimensionAtObservation=AllDimensions
OECD = {"data": {"dataSets": [{"action": "Information", "observations": {
    "0:0:0:0": [4.2, None, 0], "1:0:0:0": [6.7, None, 0], "0:0:1:0": [4.4, None, 0]}}],
    "structures": [{"dimensions": {"observation": [
        {"id": "REF_AREA", "values": [{"id": "USA"}, {"id": "DEU"}]},
        {"id": "SEX", "values": [{"id": "_T"}]},
        {"id": "TIME_PERIOD", "values": [{"id": "2026-06"}, {"id": "2026-05"}]},
        {"id": "FREQ", "values": [{"id": "M"}]}]}}]}}

v, dd = R.read_sdmx(OECD, {"series_key": {"REF_AREA": "USA", "FREQ": "M"}})
check("SDMX fully-flat (OECD) resolves through the SAME reader", v == 4.2)
check("...taking the latest TIME_PERIOD among matches", dd == "2026-06")
check("a different REF_AREA gives a different country's number, as it must",
      R.read_sdmx(OECD, {"series_key": {"REF_AREA": "DEU"}})[0] == 6.7)

err = raises(R.read_sdmx, OECD, {"series_key": {"REF_AREA": "ATLANTIS"}})
check("an SDMX code that is not there RAISES", err is not None)
check("...naming WHICH dimension failed to carry the code", "REF_AREA" in err)
check("...and showing the codes that were present", "USA" in err and "DEU" in err)
check("...refusing to read a different series", "answer a question nobody asked" in err)
check("an empty payload is a named failure, not a crash",
      "no dataSets" in (raises(R.read_sdmx, {}, {"series_key": {}}) or ""))


# ── the walls know about the three new kinds ─────────────────────────────────

for kind, addr in (("http_json_rows", {"extract": "data"}),
                   ("http_jsonstat", {"cell": {"geo": "EU"}}),
                   ("http_sdmx", {"series_key": {"FREQ": "M"}})):
    check(f"{kind} declares its location", C.KIND_LOCATION[kind] == "url")
    check(f"{kind} without its address is refused by the parsing-rule wall",
          raises(C.validate_rule, {"kind": kind, "url": "u"}) is not None)
    check(f"{kind} WITH its address passes",
          C.validate_rule({"kind": kind, "url": "u", **addr}) is True)
    check(f"{kind} with an EMPTY address is still refused — {{}} is not an address",
          raises(C.validate_rule, {"kind": kind, "url": "u",
                                   **{k: type(v)() for k, v in addr.items()}}) is not None)
    check(f"{kind} may claim the deterministic carve-out — no model in its read path",
          kind in C.DETERMINISTIC_KINDS)
    check(f"{kind} is registrable: source_registration knows its required fields or "
          f"the composer wall does",
          C.validate_entry({"kind": kind, "url": "u"}) is True)

check("a wrong-address failure classifies as an unparseable PAYLOAD, not a dead url — "
      "the source answered, the answer lacked what we asked for",
      C.classify_failure(R.RowNotFound("x")) == (C.FAILURE_FETCH, "unparseable_payload"))
check("the CSV failure shares a base with the other three — same fact, four dialects",
      issubclass(C.CsvRowNotFound, R.RowNotFound))

check("readers import nothing from composer, so they stay pure parsers",
      "import composer" not in (REPO / "experiments" / "composers" / "readers.py")
      .read_text(encoding="utf-8"))
check("what could NOT be read is recorded in the module, not quietly dropped",
      "Eurostat SDMX 2.1 answers 406" in R.__doc__ and "IMF" in R.__doc__)
check("...and IMF is named as SKIPPED rather than blacklisted",
      "SKIPPED, not blacklisted" in R.__doc__)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
