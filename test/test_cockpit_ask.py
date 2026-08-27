"""Ask confirms what it did and where the question went.

Typing a question and pressing Enter looked exactly like typing a question and
pressing nothing. The write itself was fine — memory/human_input_queue.db, an
append-only sqlite queue — but the page acknowledged nothing: no confirmation,
no route, no position. A write with no receipt teaches the operator that the
control is broken, and the next symptom is the same question asked three times.

route_of() is deterministic and consults no model, so where a question goes is
knowable at the moment it is written:

    DEEP:            -> 8b-deferred     the batch window, returns later
    battery/cpu/...  -> sys-direct      answered by code, straight from sensors
    anything else    -> 3b-next-cycle   the warm small model, inside the grammar
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))

ASK_FIXTURE = """
FIXTURES['/api/ask'] = {ok:true, id:41, route:'3b-next-cycle', tag:null,
  text:'why is ENERGY_REVIEW low', position:2, waiting:3,
  where:'the next cycle — answered by the warm 3b model, inside the grammar',
  queue_path:'memory/human_input_queue.db',
  queue:[{id:40, ts:'2026-08-27T01:00:00+00:00', text:'earlier question',
          route:'3b-next-cycle', answered:0},
         {id:41, ts:'2026-08-27T01:05:00+00:00', text:'why is ENERGY_REVIEW low',
          route:'3b-next-cycle', answered:0}]};
FIXTURES['/api/timeline'] = {rows:[], counts_by_source:{}, sources:[],
                             cycles_available:[], cycle_id:'c-1'};
"""


@needs_node
def test_pressing_enter_clears_the_box_and_writes_a_receipt(tmp_path):
    """THE HEADLINE. Before this the box cleared and nothing else happened."""
    r = run_probe(tmp_path, FIXTURES + ASK_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  const box = document.querySelector('#askbox');
  box.value = 'why is ENERGY_REVIEW low';
  await document.querySelector('#asksend').onclick();
  return {box: box.value, note: document.querySelector('#asknote').innerHTML,
          posts: LOG.fetches.filter(f => f.method === 'POST')};
};
""")
    res = r["result"]
    assert res["box"] == "", "the box did not clear"
    note = res["note"]
    assert "queued" in note, f"no confirmation was written: {note!r}"
    assert "position 2" in note, "the receipt does not say where in the queue"
    assert "memory/human_input_queue.db" in note, (
        "the receipt does not name the queue it landed in")


@needs_node
def test_the_receipt_reports_the_route_the_server_chose(tmp_path):
    """What the SERVER decided, never what the page guessed."""
    r = run_probe(tmp_path, FIXTURES + ASK_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  document.querySelector('#askbox').value = 'a question';
  await document.querySelector('#asksend').onclick();
  return {note: document.querySelector('#asknote').innerHTML};
};
""")
    assert "the next cycle" in r["result"]["note"]


@needs_node
def test_a_deep_question_says_it_went_to_the_batch_window(tmp_path):
    """DEEP: is stripped from the text and carried as the tag."""
    r = run_probe(tmp_path, FIXTURES + """
FIXTURES['/api/ask'] = {ok:true, id:42, route:'8b-deferred', tag:'DEEP',
  text:'what is the point', position:1, waiting:1,
  where:'the 8b batch window — it returns later, tagged 8b-deferred',
  queue_path:'memory/human_input_queue.db', queue:[]};
FIXTURES['/api/timeline'] = {rows:[], counts_by_source:{}, sources:[],
                             cycles_available:[], cycle_id:'c-1'};
/*---RUN---*/
FINALIZE = async () => {
  document.querySelector('#askbox').value = 'DEEP: what is the point';
  await document.querySelector('#asksend').onclick();
  const post = LOG.fetches.filter(f => f.url === '/api/ask' && f.method === 'POST')[0];
  return {note: document.querySelector('#asknote').innerHTML, body: post.body};
};
""")
    res = r["result"]
    assert "8b batch window" in res["note"], (
        "a DEEP question does not say it was deferred")
    body = json.loads(res["body"])
    assert body["tag"] == "DEEP"
    assert not body["text"].upper().startswith("DEEP:"), (
        "the DEEP: prefix was sent as part of the question text")


@needs_node
def test_a_refusal_is_shown_and_the_box_is_not_cleared(tmp_path):
    """Losing the text on a failed send is the worst possible outcome."""
    r = run_probe(tmp_path, FIXTURES + ASK_FIXTURE + """
FIXTURES['/api/ask'] = {ok:false, error:'empty question'};
/*---RUN---*/
FINALIZE = async () => {
  const box = document.querySelector('#askbox');
  box.value = 'something worth keeping';
  await document.querySelector('#asksend').onclick();
  return {box: box.value, note: document.querySelector('#asknote').innerHTML};
};
""")
    res = r["result"]
    assert "not queued" in res["note"]
    assert res["box"] == "something worth keeping", (
        "a refused question was thrown away with the box")


@needs_node
def test_the_question_becomes_visible_in_expression(tmp_path):
    """The operator could see every answer and none of the asking."""
    r = run_probe(tmp_path, FIXTURES + ASK_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('expression');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert "why is ENERGY_REVIEW low" in html, (
        "the queued question has no visible trace in EXPRESSION")
    assert "memory/human_input_queue.db" in html
    assert 'id="anchor-asked"' in html


@needs_node
def test_an_empty_box_sends_nothing(tmp_path):
    r = run_probe(tmp_path, FIXTURES + ASK_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  document.querySelector('#askbox').value = '   ';
  await document.querySelector('#asksend').onclick();
  return {posts: LOG.fetches.filter(f => f.method === 'POST').length};
};
""")
    assert r["result"]["posts"] == 0


def test_the_route_semantics_are_the_ones_the_receipt_claims():
    """The wording is the system's actual behaviour, not a nice sentence."""
    from cockpit import expression as ex
    assert ex.route_of("what is the point", tag="DEEP") == ex.ROUTE_8B_DEFERRED
    assert ex.route_of("what is the battery") == ex.ROUTE_SYS_DIRECT
    assert ex.route_of("why is ENERGY_REVIEW low") == ex.ROUTE_3B


def test_submitting_writes_exactly_one_row_and_positions_it(tmp_path, monkeypatch):
    """The other half: one row in the queue, and the position is real.

    Against a throwaway database — the live memory/human_input_queue.db is the
    operator's own queue and a test has no business appending to it.
    """
    from cockpit import server as srv
    db = tmp_path / "human_input_queue.db"
    monkeypatch.setattr(srv, "QUEUE_DB", db)
    client = srv.app.test_client()

    first = client.post("/api/ask", json={"text": "why is ENERGY_REVIEW low"})
    assert first.status_code == 200
    d1 = first.get_json()
    assert d1["ok"] is True
    assert d1["position"] == 1 and d1["waiting"] == 1
    assert d1["route"] == "3b-next-cycle"
    assert "next cycle" in d1["where"]

    second = client.post("/api/ask", json={"text": "and the point of it",
                                           "tag": "DEEP"})
    d2 = second.get_json()
    assert d2["position"] == 2 and d2["waiting"] == 2
    assert d2["route"] == "8b-deferred"
    assert "8b" in d2["where"]

    from cockpit import expression as ex
    rows = ex.queue_read(db_path=db)
    assert len(rows) == 2, "the queue holds something other than the two writes"
    assert [r["text"] for r in rows] == ["why is ENERGY_REVIEW low",
                                         "and the point of it"]

    empty = client.post("/api/ask", json={"text": "   "})
    assert empty.status_code == 400
    assert len(ex.queue_read(db_path=db)) == 2, "an empty question was queued"


def test_the_endpoint_returns_a_position_and_a_destination():
    """ast: the receipt cannot report fields the server never builds."""
    import ast
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    keys = {k.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
            for k in n.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    for field in ("position", "waiting", "where", "queue_path"):
        assert field in keys, f"/api/ask never returns {field!r}"
