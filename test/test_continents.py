#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_continents.py — SEVEN ROWS SAT UNREAD ON DISK SINCE 2 JULY.

WHAT WAS MISSING
-----------------
wellbeing_globe has computed a continent tier since 2 July 2026 — seven World
Bank regions, each with a country count, a population, three measures and a
modal zone — and no report has ever mentioned it. The whole planet was reported
as one number while a seven-row breakdown of the same data sat in
output/wellbeing_continent.json.

    Субсахарска Африка   48 държави   лишения 0.523   процъфтяване 0.508
    Северна Америка       3 държави   лишения 0.189   процъфтяване 0.825

Those are the same planet. One number cannot say that.

THE TERM IS КОНТИНЕНТ, EVERYWHERE USER-FACING. The data uses World Bank region
codes and calls them regions; a person reading a morning report should not have
to learn that vocabulary. The code keeps region_id as the join key; every
string a human reads says continent, in Bulgarian.

    venv\\Scripts\\python.exe -m pytest test/test_continents.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import continents as c

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "output" / "wellbeing_continent.json"

EXPECTED_IDS = {"EAS", "ECS", "LCN", "MEA", "NAC", "SAS", "SSF"}


# ---------------------------------------------------------------------------
# (a) THE PROOF — seven nodes with their values
# ---------------------------------------------------------------------------

def test_the_seven_continents_load_with_their_values():
    rows = c.load()

    assert len(rows) == 7, f"{len(rows)} continents, expected 7"
    assert {r["region_id"] for r in rows} == EXPECTED_IDS

    for r in rows:
        for key in ("dep", "str", "flo"):
            assert isinstance(r[key], (int, float)), f"{r['region_id']} has no {key}"
            assert 0.0 <= r[key] <= 1.0, f"{r['region_id']}.{key}={r[key]}"
        assert isinstance(r["countries"], int) and r["countries"] > 0
        assert isinstance(r["population"], int) and r["population"] > 0


def _render() -> str:
    """The report's own renderer, on a minimal record.

    NOT build(): that walks the cycle and WRITES into memory/ and output/, and
    test/conftest.py's write-surface guard rejects it — correctly. The 16 Aug
    2026 incident it exists for is exactly this shape. to_markdown only reads,
    which is what the section under test needs.
    """
    from core.cycle_report import to_markdown
    return to_markdown({"ts": "2026-08-21T00:00:00+00:00", "rows": [],
                        "broken": [], "failed": [], "plan": {}, "brain": {},
                        "log": "", "cycle_start": None})


def test_the_report_renders_all_seven_with_dep_str_flo():
    """THE REQUIRED PROOF, through the report's own renderer."""
    md = _render()

    assert "## Континенти" in md, "the section is not in the report"
    for name in c.NAMES_BG.values():
        assert name in md, f"{name} is missing from the report"

    rows = c.load()
    for r in rows:
        for key in ("dep", "str", "flo"):
            assert f"{r[key]:.3f}" in md, (
                f"{r['continent']}.{key} = {r[key]:.3f} is not rendered"
            )


def test_the_section_names_the_worst_continent():
    md = "\n".join(c.render_markdown())
    assert "най-много лишения" in md
    assert "Субсахарска Африка" in md


# ---------------------------------------------------------------------------
# (b) The term is КОНТИНЕНТ, not "region"
# ---------------------------------------------------------------------------

def test_no_user_facing_string_says_region():
    """The join key may be a World Bank code; the reader must never meet it."""
    md = "\n".join(c.render_markdown())
    lowered = md.lower()

    assert "континент" in lowered
    for banned in ("region", "регион", "wb "):
        assert banned not in lowered, (
            f"the word {banned!r} reached a human-facing string"
        )
    for code in EXPECTED_IDS:
        assert code not in md, f"the raw code {code} is shown to a person"


def test_every_continent_is_named_in_bulgarian():
    for r in c.load():
        assert r["continent"] != r["region_id"]
        assert r["continent"] in c.NAMES_BG.values()


def test_the_zone_is_translated_too():
    for r in c.load():
        assert r["zone_bg"] != r["zone"] or r["zone"] is None, (
            f"{r['continent']} shows the untranslated zone {r['zone']!r}"
        )


# ---------------------------------------------------------------------------
# (c) Worst-of
# ---------------------------------------------------------------------------

def test_worst_deprivation_is_the_highest_value():
    rows = c.load()
    assert c.worst("dep", rows)["region_id"] == "SSF"
    assert c.worst("dep", rows)["dep"] == max(r["dep"] for r in rows)


def test_worst_flourishing_is_the_LOWEST_value():
    """Flourishing runs the other way. Taking the max would name the best
    continent as the worst — the same polarity trap as the risk axes."""
    rows = c.load()
    lead = c.worst("flo", rows)
    assert lead["flo"] == min(r["flo"] for r in rows)
    assert lead["region_id"] == "SSF"


# ---------------------------------------------------------------------------
# (d) THE NEGATIVE CONTROL — attribution must not be invented
# ---------------------------------------------------------------------------

def test_attribution_names_a_continent_when_the_tier_exists():
    text = c.attribution("CLIMATE_GLOBAL_RISK_REVIEW")
    assert text is not None
    assert "воден от" in text
    assert "Субсахарска Африка" in text


def test_attribution_returns_none_when_there_is_no_tier(tmp_path, monkeypatch):
    """Inventing an attribution is worse than leaving the row global: it sends
    someone to the wrong continent."""
    empty = tmp_path / "absent.json"
    monkeypatch.setattr(c, "CONTINENTS", empty)

    assert c.load() == []
    assert c.attribution("ANY") is None, (
        "\n  AN ATTRIBUTION WAS PRODUCED WITH NO CONTINENT DATA.\n"
        "  A row that says 'воден от X' when nothing was measured per country\n"
        "  sends a reader to the wrong place with full confidence.\n"
    )
    assert c.render_markdown() == [], "an empty section was rendered anyway"


def test_a_corrupt_source_does_not_raise(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(c, "CONTINENTS", bad)
    assert c.load() == []
    assert c.computed_at() is None


# ---------------------------------------------------------------------------
# (e) R4 rows carry the attribution
# ---------------------------------------------------------------------------

def test_r4_rows_in_the_report_carry_an_attribution():
    md = _render()

    if "## Оси отвъд собствената си цел" not in md:
        pytest.skip("no R4 disagreements in the current assessment")

    section = md.split("## Оси отвъд собствената си цел", 1)[1].split("##", 1)[0]
    assert "воден от" in section, "R4 rows render without attribution"
    assert "CLIMATE_GLOBAL_RISK_REVIEW" in section


def test_the_source_file_is_the_one_wellbeing_globe_writes():
    """A second copy of this data would drift from the first."""
    assert SOURCE.exists()
    blob = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert "regions" in blob and "computed_at" in blob
    assert len(blob["regions"]) == 7
