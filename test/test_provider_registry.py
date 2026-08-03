#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_provider_registry.py — providers, not series; and a hint that never becomes a filter.

MODE 2: CATALOG TRAVERSAL. A provider publishes a machine-readable list of what it holds.
No search engine, no browser, no model — the opposite failure mode to the collector, which
had too much freedom and spent three days on four marketing blogs. This can only ever
return something the provider actually publishes, by its own code.

THE THING MOST WORTH GUARDING HERE is the axis map. config/sdg_axis_map.json associates
SDG goals with our axes, and the moment it is used to DECIDE what an axis may see it
becomes exactly the axis-fit filter core/source_registration.py refuses in writing — the
one that would mechanically destroy the cross-domain feeds this system exists to combine,
silently, while looking tidy. So it may only ORDER, it must always report what it set
aside, and anything it does not associate must still be ingestable without an override.
Those three properties are asserted below.

Catalog parsing is tested against captured payloads; nothing here uses the network.

  venv\\Scripts\\python.exe test\\test_provider_registry.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import provider_catalog as PC   # noqa: E402

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


# ── the registry ─────────────────────────────────────────────────────────────

reg = PC.registry()
check("the registry loads", bool(reg))
check("live providers cover all three reader families",
      {reg[p]["kind"] for p in PC.live_providers()}
      == {"http_json_rows", "http_jsonstat", "http_sdmx"})
check("every live provider declares a catalog and a series url",
      all(reg[p].get("catalog", {}).get("url") and reg[p].get("series_url")
          for p in PC.live_providers()))
check("every live provider declares a default independence class",
      all(reg[p].get("reporter_independence") for p in PC.live_providers()))

skipped = PC.skipped_providers()
check("a provider we cannot READ is recorded as skipped, not silently absent",
      any(s["id"] == "imf" for s in skipped))
check("...with the reason, so it can be closed deliberately",
      all(s["why"] for s in skipped))
check("...and what would unblock it", all(s["unblocks_if"] for s in skipped))
check("skipped is stated to be about US, not a verdict on them",
      "Nothing is wrong with IMF" in reg["imf"]["skip_is_not_a_blacklist"])
check("a skipped provider cannot be built into a source by accident",
      "skipped" in (raises(PC.build_source, "imf", "X") or ""))
check("an unknown provider names the ones that exist",
      "have:" in (raises(PC.provider, "nope") or ""))

check("Eurostat is routed through JSON-stat, and WHY its SDMX is not used is recorded",
      reg["eurostat"]["kind"] == "http_jsonstat"
      and "406" in reg["eurostat"]["sdmx_note"])
check("no national institute is claimed before the reader is proven on one",
      "None are registered yet" in
      " ".join(json.loads((REPO / "config" / "providers.json")
                          .read_text(encoding="utf-8"))["_national_institutes_note"]))


# ── catalog parsing, against captured payloads ───────────────────────────────

UNSDG_CAT = json.dumps([
    {"code": "SH_H2O_SAFE", "description": "Safely managed drinking water (%)",
     "goal": ["6"], "uri": "/v1/sdg/Series/SH_H2O_SAFE"},
    {"code": "SI_POV_DAY1", "description": "Population below poverty line (%)",
     "goal": ["1"], "uri": "/x"},
    {"code": "", "description": "junk with no code", "goal": ["9"]},
])
entries = PC._parse_json_list(UNSDG_CAT, reg["un_sdg"]["catalog"])
check("UN SDG catalog parses to code/title/topic", len(entries) == 2)
check("...a record with no code is dropped, not carried as an empty one",
      all(e["code"] for e in entries))
check("...goals survive as a list, because a series can serve several",
      entries[0]["topic"] == ["6"])

EUROSTAT_TOC = ('"title"\t"code"\t"type"\t"last update"\n'
                '"Labour market"\t"lm"\t"folder"\t"2026"\n'
                '"Unemployment rate - monthly"\t"ei_lmhr_m"\t"table"\t"2026"\n'
                '"HICP monthly"\t"prc_hicp_manr"\t"dataset"\t"2026"\n')
entries = PC._parse_tsv(EUROSTAT_TOC, reg["eurostat"]["catalog"])
check("Eurostat TOC parses by HEADER NAME, not by column position",
      {e["code"] for e in entries} == {"ei_lmhr_m", "prc_hicp_manr"})
check("...folders are not series and are dropped",
      all(e["code"] != "lm" for e in entries))

OECD_DF = json.dumps({"data": {"dataflows": [
    {"id": "DF_IALFS_UNE_M", "agencyID": "OECD.SDD.TPS", "version": "1.0",
     "name": "Unemployment rate, monthly"},
    {"id": "DF_OTHER", "agencyID": "OECD.X", "version": "2.1", "name": {"en": "Other"}}]}})
entries = PC._parse_sdmx_dataflows(OECD_DF, reg["oecd"]["catalog"])
check("SDMX dataflows parse into the agency,id,version code the data url needs",
      entries[0]["code"] == "OECD.SDD.TPS,DF_IALFS_UNE_M,1.0")
check("...a localised name object resolves to its English string",
      entries[1]["title"] == "Other")

check("search is a TEXT match, and says so — it is not a ranking",
      [e["code"] for e in PC.search(entries, "unemployment")] == ["OECD.SDD.TPS,DF_IALFS_UNE_M,1.0"])


# ── THE AXIS MAP IS A HINT, NOT A FILTER ─────────────────────────────────────

CAT = [{"code": "A", "title": "water", "topic": ["6"]},
       {"code": "B", "title": "poverty", "topic": ["1"]},
       {"code": "C", "title": "health", "topic": ["3"]},
       {"code": "D", "title": "no goal at all", "topic": []}]

hit, aside = PC.for_axis(CAT, "WATER_REVIEW")
check("the map associates goal 6 with WATER_REVIEW", [e["code"] for e in hit] == ["A"])
check("...and REPORTS what it set aside, so no caller can pass this off as the catalog",
      aside == 3)
check("a goal mapping to several axes is honoured on each of them",
      [e["code"] for e in PC.for_axis(CAT, "INEQUALITY_POVERTY_REVIEW")[0]] == ["B"]
      and [e["code"] for e in PC.for_axis(CAT, "HUMAN_WELL_BEING_REVIEW")[0]] == ["B", "C"])
check("an axis the SDGs say nothing about returns nothing and sets aside EVERYTHING — "
      "silence, not a fabricated association",
      PC.for_axis(CAT, "DEEP_TIME_RISKS_REVIEW") == ([], 4))

# the load-bearing one
src = PC.build_source("un_sdg", "SI_POV_DAY1", params={"area": "1"})
check("A SERIES THE MAP DOES NOT ASSOCIATE WITH AN AXIS IS STILL INGESTABLE FOR IT — "
      "build_source takes no axis and applies no map",
      src["url"].endswith("seriesCode=SI_POV_DAY1&areaCode=1&pageSize=500"))
check("...and nothing in the traversal module filters by axis at all",
      "for_axis" not in PC.build_source.__code__.co_names
      and "for_axis" not in PC.ingest.__code__.co_names)

doc = " ".join(json.loads((REPO / "config" / "sdg_axis_map.json")
                          .read_text(encoding="utf-8"))["_doc"])
check("the map says in writing that it may not be used as a filter, and why",
      "ROUTING HINT ONLY" in doc and "cross-domain" in doc)
check("...naming the module whose refusal it inherits",
      "source_registration" in doc)
check("axes with no SDG goal are recorded as deliberate silence, not as gaps",
      any("not gaps in the map" in s for s in
          json.loads((REPO / "config" / "sdg_axis_map.json")
                     .read_text(encoding="utf-8"))["_axes_with_no_sdg_goal"]))


# ── build_source: templating, and the address travelling with it ─────────────

src = PC.build_source("un_sdg", "SH_H2O_SAFE")
check("the series url is templated from the provider record",
      "seriesCode=SH_H2O_SAFE" in src["url"] and "areaCode=1" in src["url"])
check("...the reader address travels with it, templated too",
      src["row_key"] == "1" and src["extract"] == "data"
      and src["column_name"] == "value")
check("...and it is marked deterministic — a catalog series has no model in its read path",
      src["deterministic"] is True)
check("a different area produces a different url AND a matching row key — the two cannot "
      "drift apart, which is how you read the world's row and label it Chad",
      PC.build_source("un_sdg", "X", params={"area": "148"})["row_key"] == "148")

src = PC.build_source("oecd", "AGENCY,DF,1.0",
                      address={"series_key": {"REF_AREA": "USA"}})
check("an explicit address overrides the provider default",
      src["series_key"] == {"REF_AREA": "USA"})
check("...and the OECD url carries the flag its dialect needs",
      "dimensionAtObservation=AllDimensions" in src["url"])

sys.path.insert(0, str(REPO / "experiments" / "composers"))
import composer as C   # noqa: E402

for pid in PC.live_providers():
    s = PC.build_source(pid, "CODE")
    check(f"{pid}: the built source declares its location",
          C.validate_entry(s) is True)
    check(f"{pid}: ...and, once its address is filled, its parsing rule",
          C.validate_rule(dict(s, **({"cell": {"geo": "EU"}} if s["kind"] == "http_jsonstat"
                                     else {"series_key": {"FREQ": "M"}}
                                     if s["kind"] == "http_sdmx" else {})))
          is True)
    check(f"{pid}: ...and may claim the deterministic carve-out",
          C.validate_deterministic(s) is True)

check("catalog traversal reuses the SHARED intake pipeline rather than a private one",
      "cortex_ingest" in PC.ingest.__doc__ or "cortex_ingest" in
      (REPO / "core" / "provider_catalog.py").read_text(encoding="utf-8"))
check("...and promotes nothing by default",
      PC.ingest.__defaults__[-1] is False)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
