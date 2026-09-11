# -*- coding: utf-8 -*-
"""test/test_quote_gate.py — R43 at ingest (ITEM 80). Failure paths first."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import quote_gate as qg  # noqa: E402

PAGE = """<html><body><h2>Recent Daily Average Mauna Loa CO2</h2>
<table><tr><td>September 08:</td><td>426.57 ppm</td></tr>
<tr><td>September 07:</td><td>Unavailable</td></tr></table>
<p>Last Updated: September 9, 2026</p></body></html>"""
TEXT = qg.re.sub(r"<[^>]+>", " ", PAGE)

GOOD = {"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa", "value": 426.57, "unit": "ppm",
        "url": "https://gml.noaa.gov/ccgg/trends/monthly.html", "quote": "September 08:   426.57 ppm"}


def test_a_quote_absent_from_THIS_page_is_refused_by_name():
    """The refusal path, on a fixture where the row genuinely is absent.

    RENAMED 11 Sep. This was called "the real case from 10 Sep" and described the
    sensor's answer as "a plausible next-day row that was not on the page". On the
    REAL page the row WAS there — Emil opened it, and the live fetch below proves
    it: monthly.html serves `September 09:&nbsp;&nbsp; 426.62 ppm`. The test is
    good (PAGE above deliberately stops at September 08, so refusing is correct);
    only its story was wrong, and a wrong story in a test name outlives the run
    that produced it."""
    rec = dict(GOOD, value=426.62, quote="September 09:   426.62 ppm", observed_date="2026-09-09")
    v = qg.judge(rec, TEXT)
    assert v["verdict"] == "QUOTE_NOT_ON_PAGE"


def test_fetch_failure_is_open_not_accepted_and_not_a_refusal():
    assert qg.judge(GOOD, None)["verdict"] == "FETCH_FAILED"
    assert qg.check(GOOD, fetch=lambda u: None)["verdict"] == "FETCH_FAILED"


def test_value_must_be_the_number_in_the_quote():
    rec = dict(GOOD, value=427.15)          # the system's other CO2 product, pasted onto this quote
    assert qg.judge(rec, TEXT)["verdict"] == "VALUE_MISMATCH"


def test_malformed_is_named():
    v = qg.judge({"axis": "A", "key": "k", "value": "many", "unit": "x", "url": "u", "quote": "q"}, TEXT)
    assert v["verdict"] == "MALFORMED"
    v = qg.judge({"axis": "A", "key": "k", "url": "u"}, TEXT)
    assert v["verdict"] == "MALFORMED" and "quote" in v["missing"]


def test_a_named_absence_is_a_correct_answer():
    v = qg.judge({"axis": "A", "key": "k", "value": None, "url": "u", "reason": "page shows Unavailable"}, TEXT)
    assert v["verdict"] == "NULL_WITH_REASON"


def test_mutation_the_substring_check_is_load_bearing(monkeypatch):
    """If the gate stopped comparing against the page, the invented row would pass."""
    rec = dict(GOOD, value=426.62, quote="September 09:   426.62 ppm")
    monkeypatch.setattr(qg, "_norm", lambda s: "")     # neuter: everything normalises to nothing
    assert qg.judge(rec, TEXT)["verdict"] != "QUOTE_NOT_ON_PAGE"


def test_happy_path_whitespace_insensitive():
    assert qg.judge(GOOD, TEXT)["verdict"] == "ACCEPTED"
    assert qg.check(GOOD, fetch=lambda u: TEXT)["verdict"] == "ACCEPTED"


# ── 11 Sep 2026: cards A/B/C exposed two holes ────────────────────────────

GDACS_PAGE = ('{"features":[{"properties":{"country":"Belgium","fromdate":"2026-08-14T00:00:00","todate":"2026-08-17T00:00:00"}},'
              '{"properties":{"country":"X","fromdate":"2026-09-05T00:00:00","todate":"2026-09-06T00:00:00"}}]}')
CARD_B = {"axis": "ECOSYSTEMS_BIODIVERSITY_REVIEW", "key": "gdacs_wildfire_orange_red_7d_count", "value": 0, "unit": "events per 7 days",
          "url": "u", "quote": '"Belgium","fromdate":"2026-08-14T00:00:00","todate":"2026-08-17T00:00:00"',
          "window_utc": "2026-09-04T06:56:00Z/2026-09-11T06:56:00Z"}


def test_a_zero_inside_a_timestamp_is_not_the_number_zero():
    """The hole: value 0 was ACCEPTED because "T00:00:00" contains "00"."""
    rec = dict(CARD_B); rec.pop("window_utc")
    v = qg.judge(rec, GDACS_PAGE)
    assert v["verdict"] == "VALUE_MISMATCH" and v["numbers_in_quote"] == []


def test_standalone_numbers_still_parse_from_tables_and_json():
    assert qg._NUM.findall("2025 2.23 0.11") == ["2025", "2.23", "0.11"]
    assert qg._NUM.findall('"count": 2026') == ["2026"]
    assert qg._NUM.findall("2026-08-14T00:00:00") == []


def test_an_aggregate_card_is_recounted_by_the_gate_not_trusted():
    assert qg.judge(CARD_B, GDACS_PAGE)["verdict"] == "RECOUNT_MISMATCH"          # page has 1 in window, agent said 0
    assert qg.judge(dict(CARD_B, value=1), GDACS_PAGE)["verdict"] == "ACCEPTED"
    only_old = GDACS_PAGE.replace(',{"properties":{"country":"X","fromdate":"2026-09-05T00:00:00","todate":"2026-09-06T00:00:00"}}', "")
    assert qg.judge(CARD_B, only_old)["verdict"] == "ACCEPTED"


def test_an_aggregate_card_on_a_non_json_page_is_malformed_not_accepted():
    html = "<pre>" + CARD_B["quote"] + "</pre> not json"        # quote present, page not parseable -> nothing to recount
    assert qg.judge(CARD_B, html)["verdict"] == "MALFORMED"


def test_mutation_the_recount_is_load_bearing(monkeypatch):
    monkeypatch.setattr(qg, "recount", lambda page, window, date_key="fromdate": int(CARD_B["value"]))
    assert qg.judge(CARD_B, GDACS_PAGE)["verdict"] == "ACCEPTED"     # neutered recount lets the wrong count through


# ── the gate's own first live run, and the false refusal it produced ──────────

# VERBATIM from https://gml.noaa.gov/ccgg/trends/monthly.html, fetched on this
# machine 2026-09-10 at ingest time. The &nbsp; entities are the whole point:
# this is what _fetch's tag-stripping leaves behind, and what the agent — which
# read the RENDERED page — could not have quoted.
NOAA_RAW = ('<td>September 09:&nbsp;&nbsp; 426.62 ppm</td>'
            '<td>September 08:&nbsp;&nbsp; 426.57 ppm</td>')
NOAA_QUOTE = "September 09:   426.62 ppm"


def test_the_gate_does_not_invent_a_refusal_over_html_entities():
    """THE FALSE REFUSAL, 10 Sep 2026, found on the gate's first live run.

    Card 1 — the NOAA CO2 reading this module's docstring was written about, the
    one Emil confirmed WAS on the page — came back QUOTE_NOT_ON_PAGE. It was on
    the page. The page serves `September 09:&nbsp;&nbsp; 426.62 ppm`; tag
    stripping leaves the literal text "&nbsp;", so no amount of whitespace
    normalisation could match a quote taken from the rendered page.

    A TRUE reading would have been written to card_refusals.jsonl and counted
    against the sensor's invention rate — corrupting the one number this module
    exists to produce. The docstring already named this failure ("otherwise the
    gate itself invents refusals"); the code did not implement it."""
    import re as _re
    stripped = _re.sub(r"<[^>]+>", " ", NOAA_RAW)          # what _fetch did before
    assert qg.judge({"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa",
                     "value": 426.62, "unit": "ppm", "url": "u", "quote": NOAA_QUOTE},
                    stripped)["verdict"] == "QUOTE_NOT_ON_PAGE", (
        "the un-decoded page must still fail — otherwise this test is not "
        "reproducing the defect it was written for")

    import html as _html
    decoded = _html.unescape(stripped)                     # what _fetch does now
    assert qg.judge({"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa",
                     "value": 426.62, "unit": "ppm", "url": "u", "quote": NOAA_QUOTE},
                    decoded)["verdict"] == "ACCEPTED"


def test_fetch_decodes_entities_before_judging(monkeypatch):
    """MECHANICAL NET on the fix itself, through the real _fetch path. Remove
    html.unescape from _fetch and this fails, which is the state the module
    shipped in."""
    class _Resp:
        status_code = 200
        text = NOAA_RAW
    monkeypatch.setattr(qg, "requests", None, raising=False)
    import types
    fake = types.SimpleNamespace(get=lambda url, timeout=None, headers=None: _Resp())
    monkeypatch.setitem(sys.modules, "requests", fake)
    page = qg._fetch("https://example.invalid/noaa")
    assert page is not None
    assert "&nbsp;" not in page, "_fetch is not decoding HTML entities"
    rec = {"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa",
           "value": 426.62, "unit": "ppm", "url": "https://example.invalid/noaa",
           "quote": NOAA_QUOTE}
    assert qg.judge(rec, page)["verdict"] == "ACCEPTED"


def test_decoding_entities_does_not_make_an_invention_pass():
    """NEGATIVE CONTROL, so the fix cannot be 'match everything'. A number the
    page does not carry must still be refused after decoding."""
    import html as _html, re as _re
    page = _html.unescape(_re.sub(r"<[^>]+>", " ", NOAA_RAW))
    invented = {"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "key": "co2_ppm_mauna_loa",
                "value": 999.99, "unit": "ppm", "url": "u",
                "quote": "September 09:   999.99 ppm"}
    assert qg.judge(invented, page)["verdict"] == "QUOTE_NOT_ON_PAGE"
    # and a quote that IS on the page but whose number was altered
    mismatch = {"axis": "A", "key": "k", "value": 500.0, "unit": "ppm", "url": "u",
                "quote": NOAA_QUOTE}
    assert qg.judge(mismatch, page)["verdict"] == "VALUE_MISMATCH"
