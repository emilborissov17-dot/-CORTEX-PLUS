# -*- coding: utf-8 -*-
"""test/test_csv_row_key.py — half an address is not an address.

MEASURED 19 September 2026. config/axis_source_map.json declares 14 http_csv
candidates with `row_key_column: "entity"` and ZERO with `row_key`. With the key
absent, composer._csv_select fell through to `rows[-1]` — the alphabetically last
entity in an OWID entity x year panel. The map's own _coverage_summary records
what that produced:

    "returned_the_wrong_row": {
        "...": "Zimbabwe",
        "owid_mean_years_schooling": "Zimbabwe (2020)",
        "owid_plastic_waste_per_capita": "Yemen (2010)",
        ...
    }

Zimbabwe's water stress, reported as the world's. The number was real, correctly
parsed and correctly hashed, and about the wrong thing entirely.

These tests pin the refusal, and the control that keeps the refusal honest: a
genuine single-series feed with NO row_key_column must still read its last row,
because that is what a single-series feed is.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "composers"))
sys.path.insert(0, str(REPO))

import composer as C          # noqa: E402

PANEL = ("entity,code,year,value,value__original_year\n"
         "Albania,ALB,2025,1.5,2020\n"
         "World,OWID_WRL,2024,9.9,2024\n"
         "Zimbabwe,ZWE,2023,7.7,2023\n")

SINGLE = ("date,mean\n"
          "2026-09-01,425.1\n"
          "2026-09-06,426.08\n")


def test_row_key_column_without_row_key_refuses():
    """THE DEFECT. Declaring the key column says 'this is a panel'. Reading the
    last row of a panel anyway is the silent fallback, one field over."""
    with pytest.raises(C.CsvRowKeyMissing) as e:
        C._csv_select({"row_key_column": "entity", "column_name": "value"}, PANEL)
    msg = str(e.value)
    assert "row_key_column" in msg and "row_key" in msg
    assert "World" in msg, "the refusal does not show how to fix itself"


def test_the_refusal_is_distinguishable_from_a_missing_row():
    """Two different facts, two different classes.

    CsvRowNotFound: the address was given and the payload does not hold it.
    CsvRowKeyMissing: our record never finished the address.
    A reader of a refusal must be able to tell 'the provider dropped the row'
    from 'we never said which row', because the fixes are not the same.
    """
    assert C.CsvRowKeyMissing is not C.CsvRowNotFound
    assert issubclass(C.CsvRowKeyMissing, C.readers.RowNotFound)
    with pytest.raises(C.CsvRowNotFound):
        C._csv_select({"row_key": "Atlantis", "row_key_column": "entity"}, PANEL)


def test_the_resolved_row_is_the_entity_that_was_asked_for():
    cells, _dd = C._csv_select({"row_key": "World", "row_key_column": "entity"}, PANEL)
    assert cells[0] == "World"
    cells, _dd = C._csv_select({"row_key": "Albania", "row_key_column": "entity"}, PANEL)
    assert cells[0] == "Albania"


def test_a_missing_entity_never_falls_back_to_another_row():
    """The failure this whole pack exists to remove: answering a question nobody
    asked, with a real number, about the wrong country."""
    with pytest.raises(C.CsvRowNotFound) as e:
        C._csv_select({"row_key": "World", "row_key_column": "entity"},
                      "entity,year,value\nAlbania,2025,1\nZimbabwe,2023,7\n")
    msg = str(e.value)
    assert "World" in msg
    assert "Albania" in msg or "Zimbabwe" in msg, "the refusal does not sample what WAS there"


def test_a_genuine_single_series_feed_is_unchanged():
    """THE CONTROL. NOAA's CO2 trend is one series, not a panel; it declares no
    row_key_column and must still read its last row. If this broke, the refusal
    above would be indistinguishable from breaking every working source."""
    cells, _dd = C._csv_select({}, SINGLE)
    assert cells[0] == "2026-09-06"


def test_data_date_column_is_honoured_when_declared():
    """__original_year is the column that stops five-year-old inequality being
    reported as current. The composer honours a generic data_date_column; nothing
    in the map declares one, which is a config gap and not a code gap."""
    cells, dd = C._csv_select(
        {"row_key": "Albania", "row_key_column": "entity",
         "data_date_column": "value__original_year"}, PANEL)
    assert cells[0] == "Albania"
    assert dd == "2020", (
        "the 2025 row for Albania is a 2020 survey; data_date must say 2020")


def test_without_data_date_column_the_date_is_none_not_the_year_column():
    """An absent date is None, never quietly the row's `year`. Reporting the
    publication year as the observation year is the same error one column over."""
    _cells, dd = C._csv_select({"row_key": "Albania", "row_key_column": "entity"}, PANEL)
    assert dd is None


def test_the_live_map_has_no_half_addressed_candidate_left():
    """The map and the code must agree. Any http_csv candidate that declares a
    key column must now declare a key, or the composer refuses it at fetch time
    and the axis silently has no source.

    This is the test that will go red the moment somebody adds a candidate the
    old way, which is how the 14 got there in the first place.
    """
    import json
    m = json.loads((REPO / "config" / "axis_source_map.json").read_text(encoding="utf-8"))
    half = []
    for branch, axes in m.items():
        if str(branch).startswith("_"):
            continue
        for axis, body in axes.items():
            for c in (body.get("numeric_candidates") or []):
                if c.get("kind") != "http_csv":
                    continue
                if c.get("row_key_column") and not c.get("row_key"):
                    half.append((axis, c["id"]))
    assert not half, (
        "%d candidate(s) declare row_key_column and no row_key, so composer.fetch "
        "refuses them: %s" % (len(half), half))
