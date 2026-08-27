"""The CYCLE tab reads like a document, not like a spreadsheet cell.

Three complaints from Emil's walk, all in the step list:

  * descriptions were cut at 70 characters — in JavaScript, so the end of the
    sentence was destroyed before CSS ever had a chance to wrap it;
  * the hover lit only the cell under the pointer, so on a 31-row table the eye
    could pair a step with its neighbour's description;
  * tick() re-renders every 15 seconds and render() replaces #view wholesale, so
    the page jumped to the top twice a minute — the row being read walked off
    the screen while it was being read.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from test_cockpit_doors import (FIXTURES, REPO, TEMPLATE,  # noqa: F401
                                needs_node, run_probe)

CSS = TEMPLATE.read_text(encoding="utf-8")


@needs_node
def test_a_long_step_description_is_rendered_whole(tmp_path):
    """THE HEADLINE. The fixture's description is 106 characters long."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('cycle');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    tail = "cut it at seventy characters and lost the end"
    assert tail in html, (
        "the step description is still being truncated before it reaches the DOM")


@needs_node
def test_no_renderer_truncates_a_description_with_slice(tmp_path):
    """The defect was a .slice(0,70) in the renderer, not a CSS clamp."""
    inline = re.findall(r"<script>(.*?)</script>", CSS, re.S)[-1]
    body = re.search(r"async function tabCycle\(\)\{.*?\n\}", inline, re.S)
    assert body, "tabCycle() is gone"
    assert ".slice(0," not in body.group(0), (
        "tabCycle() truncates again — a description cut in JavaScript cannot be "
        "recovered by any stylesheet")


def test_the_whole_row_lights_on_hover_and_it_is_pure_css():
    """Both columns, no handler — so it survives every re-render for free."""
    assert re.search(r"tr:hover\s*>\s*td", CSS), (
        "no whole-row hover rule; a cell-only highlight lets the eye pair a step "
        "with the wrong description")
    inline = re.findall(r"<script>(.*?)</script>", CSS, re.S)[-1]
    assert "mouseover" not in inline and "mouseenter" not in inline, (
        "the highlight must be CSS: a JS handler would have to be re-attached on "
        "every render")


def test_the_wrapping_rule_exists_and_does_not_clamp():
    assert "td.full" in CSS, "no rule to wrap a full-width description cell"
    assert "-webkit-line-clamp" not in CSS, (
        "a line clamp hides the end of the sentence just as a slice did")
    assert "text-overflow:ellipsis" not in CSS.replace(" ", "")


@needs_node
def test_the_step_list_keeps_its_position_across_a_refresh(tmp_path):
    """A 15-second tick must not move the reader."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('cycle');
  window.scrollY = 640;                 // the reader has scrolled down
  const calls = [];
  window.scrollTo = (x, y) => calls.push(y);
  await render();                       // what tick() does every 15 seconds
  return {restored: calls};
};
""")
    assert 640 in r["result"]["restored"], (
        "the re-render dropped the reader back to the top of the page")


@needs_node
def test_switching_tab_still_lands_at_the_top(tmp_path):
    """Keeping position is for the SAME document. A new tab is a new document."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('cycle');
  window.scrollY = 640;
  const calls = [];
  window.scrollTo = (x, y) => calls.push(y);
  await switchTo('pending');
  return {restored: calls};
};
""")
    assert 640 not in r["result"]["restored"], (
        "switching tab restored the previous tab's scroll offset — the reader "
        "asked for a different document and should see the start of it")


@needs_node
def test_an_anchor_from_a_door_beats_the_kept_position(tmp_path):
    """goTo() was asked for a specific place. That wins over 'where you were'."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('pending');
  window.scrollY = 640;
  const calls = [];
  window.scrollTo = (x, y) => calls.push(y);
  pendingAnchor = 'anchor-quarantine';
  await render();
  return {restored: calls, scrolled: LOG.scrolled};
};
""")
    res = r["result"]
    assert 640 not in res["restored"], (
        "the kept position overrode an anchor the reader explicitly asked for")
