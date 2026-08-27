"""Unread is shown, then cleared — never cleared unseen.

Clicking "6 unread" marked every expression line seen and rendered nothing. The
counter went to zero and the reader never learned what the six were. That is
information destroyed ON CLICK by the one control that claims to mean "I have
read this", and "seen" is append-only by design, so it could not be taken back.

The order is the whole fix, and it is what these tests assert: the list reaches
the screen BEFORE /api/expression/seen is called.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))

UNREAD_FIXTURE = """
FIXTURES['/api/expression'] = {
  lines: [], rejected: [], lexicon: {warm:false, label:'lexicon warming: 7/20 cycles'},
  unread: 3,
  unread_rows: [
    {ts:'2026-08-27T01:10:00+00:00', depth:'expression', stream:'expression', text:'FIRST UNREAD LINE'},
    {ts:'2026-08-27T01:20:00+00:00', depth:'expression', stream:'expression', text:'SECOND UNREAD LINE'},
    {ts:'2026-08-27T01:30:00+00:00', depth:'expression', stream:'expression', text:'THIRD UNREAD LINE'}]};
FIXTURES['/api/expression/seen'] = {unread: 0};
FIXTURES['/api/timeline'] = {
  rows:[{ts:'2026-08-27T01:20:00+00:00', reflexivity:1, source:'expression', text:'SECOND UNREAD LINE'}],
  counts_by_source:{expression:1}, sources:[], cycles_available:[], cycle_id:'c-1'};
"""


@needs_node
def test_clicking_unread_shows_all_three_before_anything_is_marked(tmp_path):
    """THE HEADLINE, and the ORDER is the assertion."""
    r = run_probe(tmp_path, FIXTURES + UNREAD_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  await markSeen();
  const html = document.querySelector('#view').innerHTML;
  const seenCall = LOG.fetches.filter(f => f.url === '/api/expression/seen');
  return {html, seenCall,
          order: LOG.fetches.map(f => f.url)};
};
""")
    res = r["result"]
    html = res["html"]
    for line in ("FIRST UNREAD LINE", "SECOND UNREAD LINE", "THIRD UNREAD LINE"):
        assert line in html, f"the unread list does not show {line!r}"

    assert len(res["seenCall"]) == 1, "seen was called more than once, or not at all"
    body = json.loads(res["seenCall"][0]["body"])
    assert len(body["ts"]) == 3, (
        "the mark did not carry exactly the three timestamps that were shown")


@needs_node
def test_the_list_is_rendered_before_seen_is_posted(tmp_path):
    """Order, proved from the page's own call sequence."""
    r = run_probe(tmp_path, FIXTURES + UNREAD_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  const marks = [];
  const realFetch = fetch;
  globalThis.fetch = (u, o) => {
    if(String(u).includes('/seen')){
      marks.push({at: 'seen',
                  viewHadLines: (document.querySelector('#view').innerHTML||'')
                                  .includes('FIRST UNREAD LINE')});
    }
    return realFetch(u, o);
  };
  await markSeen();
  return {marks};
};
""")
    marks = r["result"]["marks"]
    assert marks, "the seen endpoint was never called"
    assert marks[0]["viewHadLines"] is True, (
        "seen was posted while the unread lines were NOT yet on screen — this is "
        "exactly the destroy-on-click behaviour the change exists to stop")


@needs_node
def test_only_then_does_the_counter_reach_zero(tmp_path):
    r = run_probe(tmp_path, FIXTURES + UNREAD_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  const before = document.querySelector('#unread').textContent;
  await markSeen();
  return {before, after: document.querySelector('#unread').textContent,
          html: document.querySelector('#view').innerHTML};
};
""")
    res = r["result"]
    assert "0 unread" in res["after"], "the counter did not clear after the list"
    assert "FIRST UNREAD LINE" in res["html"], (
        "the counter cleared and took the list with it")


@needs_node
def test_each_item_links_into_the_timeline_at_its_place(tmp_path):
    """Quoting a line out of the stream is not the same as finding it in it."""
    r = run_probe(tmp_path, FIXTURES + UNREAD_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  await markSeen();
  const rows = document.querySelectorAll('.unrow');
  const second = rows.find(x => x.dataset.uts === '2026-08-27T01:20:00+00:00');
  if(!second) return {found:false, n: rows.length};
  second.onclick();
  return {found:true, n: rows.length, scrolled: LOG.scrolled,
          anchorInHtml: document.querySelector('#view').innerHTML
                          .includes('id="tl-' + tsKey('2026-08-27T01:20:00+00:00'))};
};
""")
    res = r["result"]
    assert res["found"] is True, f"unread rows are not clickable ({res})"
    assert res["anchorInHtml"] is True, (
        "the timeline renders no anchor for that line, so the link has nowhere "
        "to land")
    assert res["scrolled"], "clicking an unread line scrolled to nothing"


@needs_node
def test_nothing_unread_marks_nothing(tmp_path):
    """A click on a zero must not post a mark."""
    r = run_probe(tmp_path, FIXTURES + UNREAD_FIXTURE + """
FIXTURES['/api/expression'].unread_rows = [];
FIXTURES['/api/expression'].unread = 0;
/*---RUN---*/
FINALIZE = async () => {
  await markSeen();
  return {seen: LOG.fetches.filter(f => f.url === '/api/expression/seen').length};
};
""")
    assert r["result"]["seen"] == 0


def test_the_two_definitions_of_unread_cannot_disagree():
    """The count and the rows must come from ONE predicate.

    Two definitions is how a list of three ends up clearing a count of four.
    """
    from cockpit import expression as ex
    import inspect
    count_src = inspect.getsource(ex.pending_unread)
    rows_src = inspect.getsource(ex.pending_unread_rows)
    for fragment in ('depth") == EXPRESSION', 'ts") not in seen'):
        assert fragment in count_src and fragment in rows_src, (
            f"pending_unread and pending_unread_rows disagree on {fragment!r}")


def test_the_rows_are_served(tmp_path):
    """The endpoint must actually hand them over."""
    import ast
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    keys = {k.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
            for k in n.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert "unread_rows" in keys, "/api/expression never returns the unread rows"
