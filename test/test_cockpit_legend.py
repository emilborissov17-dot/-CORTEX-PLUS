"""EXPRESSION carries its own legend, GENERATED rather than asserted.

Emil could not tell who writes what, or why. Seven streams interleaved by
timestamp — some of them the machine measuring itself, some of them a language
model with an opinion — rendered in one list with a source tag and nothing else.

The legend is derived from cockpit/timeline.SOURCES, which is the same table
sources_status() already reads. That matters more than the wording: a stream
added to that table gains its legend line automatically, and one deleted loses
it. A hand-written paragraph would be correct on the day it was written and
quietly wrong afterwards — which is the failure this repo keeps finding.

`gated` is COMPUTED, not declared: core/language_gate.py scores exactly one
file, so a stream is filtered out of the exemplar pool if and only if it IS that
file. Asking the gate where it reads keeps the answer true the day somebody
points it somewhere else.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, TEMPLATE, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))
PAGE = TEMPLATE.read_text(encoding="utf-8")


def test_the_legend_has_a_line_for_every_declared_stream():
    from cockpit import timeline as tl
    legend = tl.legend()
    assert len(legend) == len(tl.SOURCES), (
        "the legend and the registry disagree about how many streams there are")
    assert [r["source"] for r in legend] == [s[0] for s in tl.SOURCES]


def test_every_line_answers_all_four_questions():
    """who writes it, when, mediation, and whether the gate filters it."""
    from cockpit import timeline as tl
    for row in tl.legend():
        for field in ("writer", "when", "mediation", "rung", "path"):
            assert row.get(field), f"{row['source']}: {field} is empty"
        assert isinstance(row["gated"], bool)
        assert row["mediation"] in ("code", "model", "model 3b", "model 8b"), (
            f"{row['source']}: unrecognised mediation {row['mediation']!r}")


def test_gate_filtering_is_derived_from_where_the_gate_actually_reads():
    """Not a flag somebody remembered to set."""
    from cockpit import timeline as tl
    from core import language_gate as lg

    journal = pathlib.Path(lg.JOURNAL).resolve()
    gated = [r for r in tl.legend() if r["gated"]]
    assert gated, "nothing is gate-filtered, which cannot be right"
    for row in gated:
        assert pathlib.Path(REPO / row["path"]).resolve() == journal, (
            f"{row['source']} claims to be gate-filtered but is not the file "
            f"the gate reads")

    not_gated = [r for r in tl.legend() if not r["gated"]]
    for row in not_gated:
        assert pathlib.Path(REPO / row["path"]).resolve() != journal


def test_a_new_stream_gains_its_line_without_anyone_writing_one(monkeypatch):
    """THE POINT OF GENERATING IT. Add to the table, get a legend row."""
    from cockpit import timeline as tl
    extra = ("invented_stream", tl.MEM / "invented.jsonl", tl.MEASUREMENT,
             ("invented",), "nobody yet", "never", "code")
    monkeypatch.setattr(tl, "SOURCES", tuple(tl.SOURCES) + (extra,))
    names = [r["source"] for r in tl.legend()]
    assert "invented_stream" in names, (
        "a stream added to the registry did not appear in the legend, so the "
        "legend is a copy rather than a derivation")


def test_the_page_does_not_hard_code_a_single_stream_name():
    """A legend typed into the template is the thing this replaces."""
    block = PAGE.split('<details class="legend"')[1].split("</details>")[0]
    from cockpit import timeline as tl
    for name, *_ in tl.SOURCES:
        assert name not in block, (
            f"{name!r} is written into the template; the legend must be built "
            f"from t.legend() so it cannot go stale")
    assert "t.legend" in block, "the template does not read the generated legend"


@needs_node
def test_the_legend_renders_in_the_expression_tab(tmp_path):
    r = run_probe(tmp_path, FIXTURES + """
FIXTURES['/api/expression'] = {lines:[], rejected:[], lexicon:{}, unread:0,
                               unread_rows:[]};
FIXTURES['/api/ask'] = {queue:[]};
FIXTURES['/api/timeline'] = {rows:[], counts_by_source:{}, sources:[],
  cycles_available:[], cycle_id:'c-1',
  legend:[{source:'brain_stance', path:'memory/brain_step_log.jsonl',
           writer:'core/brain.py', when:'once per step', mediation:'model 3b',
           reflexivity:1, rung:'r1 reading the world', feeds:['brain_stance'],
           gated:false, gate_note:'not read by the language gate'},
          {source:'rationale', path:'memory/brain_journal.jsonl',
           writer:'core/brain.py remember()', when:'on every decision',
           mediation:'model', reflexivity:2, rung:'r2 reading itself',
           feeds:['rationale'], gated:true,
           gate_note:'the language gate scores these'}]};
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('expression');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert "brain_stance" in html and "core/brain.py" in html
    assert "once per step" in html, "the legend does not say WHEN"
    assert "model 3b" in html, "the legend does not say what mediates it"
    assert "gate-filtered" in html, "the legend does not say what the gate takes"
    assert "generated from the registry" in html


def test_the_legend_survives_a_re_render_if_it_was_open():
    """<details> lives inside #view, which is rebuilt every 15 seconds."""
    script = PAGE.split("<script>")[-1]
    assert "legendOpen" in script, (
        "nothing remembers whether the legend was unfolded, so it refolds itself "
        "twice a minute")
    # ontoggle, not addEventListener('toggle'): wirePanel() now runs after every
    # render, and a stacking listener would fire once per render it survived.
    assert "ontoggle" in script, "the open state is never recorded"
