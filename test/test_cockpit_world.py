"""WORLD separates what flows from what is only designed.

The five-columns panel already said, honestly, "no data yet — three_columns.py
is not wired". It said it three panels along in a uniform grid, in the same
visual register as the goal tree, which DOES flow. Honest text carried at the
same weight as live data still reads as a feature: the reader has to notice a
sentence to learn that a whole panel is a drawing.

And an axis was a pill with a name behind which there was nothing — 24 labels
for measurements the system takes every night and would not show.

NOT WIRED HERE, deliberately: three_columns.py stays unwired. Writing a producer
for memory/columns/ is cycle-side work. The cockpit's job in this part is to
stop mixing the real and the planned on one visual level.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, TEMPLATE, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))
PAGE = TEMPLATE.read_text(encoding="utf-8")

WORLD = """
FIXTURES['/api/panels'] = {panels:[{panel:'goal',live:true},{panel:'columns',live:false}]};
FIXTURES['/api/goal'] = {
  subgoal_count:2, axis_count:3, composite_history:[0.1,0.2,0.3],
  tree:{SUSTAINABLE_RESOURCES:[{axis:'ENERGY_REVIEW',target:null,weight:8},
                               {axis:'WATER_REVIEW',target:null,weight:5}],
        SAFETY:[{axis:'SOCIAL_RELATIONS_REVIEW',target:null,weight:5}]},
  continents:[{region_id:'SSF', zone:'Precarious'}]};
FIXTURES['/api/columns'] = {
  column_order:['a','b'], column_spec:{a:{title:'A',refines:'x',pipeline_kind:'k'},
                                       b:{title:'B',refines:'y',pipeline_kind:'k'}},
  independence_violations:[], lifecycle_ladder:'ladder', ladder_note:'note',
  record_count:0, empty_because:'three_columns.py is not wired'};
FIXTURES['/api/axis/ENERGY_REVIEW'] = {
  axis:'ENERGY_REVIEW', known:true, subgoal:'SUSTAINABLE_RESOURCES',
  latest:{score:0.2, level:'LOW', verification:'VERIFIED',
          metrics_used:{renewable_pct:19.7, fossil_pct:null},
          signals:['renewables 19.7% — critically low']},
  target:80.0, target_unit:'percent of total energy', direction:'higher_better',
  rationale:'IEA Net Zero 2050 requires 80%+ renewables', weight:8,
  score_source:'cortex_scoring_engine',
  latest_scale:'0..1', history_scale:'0..100', history_len:3,
  history:[{date:'2026-06-03',score:55.67,source:null},
           {date:'2026-07-01',score:33.0,source:'cortex_scoring_engine'},
           {date:'2026-08-27',score:20.0,source:'cortex_scoring_engine'}],
  sources:{scores:'output/cortex_scores_latest.json',
           history:'memory/axis_history.json', target:'config/target_config.json'}};
"""


@needs_node
def test_the_tab_is_split_into_two_labelled_halves(tmp_path):
    """THE HEADLINE."""
    r = run_probe(tmp_path, FIXTURES + WORLD + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('world');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert "LIVE" in html and "what flows tonight" in html
    assert "DESIGNED, NOT WIRED" in html
    assert html.index("LIVE") < html.index("DESIGNED"), (
        "the designed half is rendered above the live one")


@needs_node
def test_the_unwired_panel_says_what_would_have_to_exist(tmp_path):
    r = run_probe(tmp_path, FIXTURES + WORLD + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('world');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert "memory/columns/" in html, (
        "the panel does not name the thing that would light it up")
    assert "wouldneed" in html
    assert "cols dim" in html, "the designed panel is not visually demoted"


@needs_node
def test_an_axis_opens_its_value_target_source_and_history(tmp_path):
    """A pill with a name and nothing behind it was the whole complaint."""
    r = run_probe(tmp_path, FIXTURES + WORLD + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('world');
  const b = document.querySelectorAll('.axis').find(x => x.dataset.axis === 'ENERGY_REVIEW');
  if(!b) return {found:false};
  await b.onclick();
  return {found:true, html: document.querySelector('#view').innerHTML};
};
""")
    res = r["result"]
    assert res["found"] is True, "axes are not clickable"
    html = res["html"]
    assert "0.2" in html, "the axis does not show what it reads now"
    assert "80" in html, "the axis does not show what it is aiming at"
    assert "percent of total energy" in html
    assert "cortex_scoring_engine" in html, "the axis does not name its source"
    assert "config/target_config.json" in html, "the panel does not cite its files"
    assert "<svg" in html, "no sparkline was drawn"
    assert 'id="anchor-axis"' in html


@needs_node
def test_the_two_score_scales_are_named_rather_than_silently_mixed(tmp_path):
    """cortex_scores_latest.json holds 0..1 and axis_history.json holds 0..100
    for the same axis on the same day. Printing both unlabelled would draw a
    cliff that is not there."""
    r = run_probe(tmp_path, FIXTURES + WORLD + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('world');
  await document.querySelectorAll('.axis').find(x => x.dataset.axis === 'ENERGY_REVIEW').onclick();
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert "0..1" in html and "0..100" in html, (
        "the two scales are printed side by side without saying they differ")


@needs_node
def test_an_unmeasured_metric_says_so_rather_than_showing_nothing(tmp_path):
    r = run_probe(tmp_path, FIXTURES + WORLD + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('world');
  await document.querySelectorAll('.axis').find(x => x.dataset.axis === 'ENERGY_REVIEW').onclick();
  return {html: document.querySelector('#view').innerHTML};
};
""")
    assert "not measured" in r["result"]["html"], (
        "a null metric renders as a blank cell, which reads as zero")


def test_three_columns_is_still_not_wired():
    """THE GUARD. This part must not quietly turn the planned into the real."""
    producers = [p for p in (REPO / "memory").glob("columns*")]
    assert not producers, (
        "memory/columns/ now exists — if three_columns.py was wired, the WORLD "
        "tab's DESIGNED half is lying and must be moved")


# ── the endpoint that feeds it ──────────────────────────────────────────────

def test_the_axis_endpoint_reads_the_files_it_names():
    from cockpit import server as srv
    d = srv.app.test_client().get("/api/axis/ENERGY_REVIEW").get_json()
    assert d["known"] is True
    assert d["subgoal"] == "SUSTAINABLE_RESOURCES"
    assert d["target"] == 80.0
    assert d["weight"] == 8
    assert d["direction"] == "higher_better"
    assert d["history_len"] > 0
    assert d["history_len"] <= 55, "the sparkline series is unbounded"
    for path in d["sources"].values():
        assert (REPO / path).exists(), f"the panel cites {path}, which is not there"


def test_an_unknown_axis_says_so_instead_of_inventing_a_zero():
    from cockpit import server as srv
    d = srv.app.test_client().get("/api/axis/NOT_AN_AXIS").get_json()
    assert d["known"] is False
    assert d["latest"] is None
    assert d["history"] == []
    assert d["empty_because"]
