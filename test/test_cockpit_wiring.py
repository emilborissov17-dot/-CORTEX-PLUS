"""Controls born from injected markup are wired like the rest — and CLOSE closes.

THE REPORTED BUG. The read-only overlay rendered correctly and its CLOSE button
did nothing. The suspicion was that the overlay is injected with innerHTML after
the panel was wired, so the handler was bound to a node that no longer exists.

THAT WAS NOT IT, and the harness is what proved it: the overlay is static markup
in the page body (cockpit.html:272), CLOSE is bound to the live node, the click
reaches the handler, and the handler sets `hidden = true` exactly as written.

The cause was CSS.

    [hidden] { display: none }     user-agent stylesheet   specificity (0,1,0)
    #runwrap { display: flex }     cockpit.html            specificity (1,0,0)

An ID selector setting `display` unconditionally OVERRIDES the only rule that
gives the `hidden` attribute any meaning. The property flipped and the cascade
kept display:flex, so the overlay stayed on screen.

The Part 5 test asserted `wrap.hidden === true` and passed. It verified the
PROPERTY and never the VISIBILITY — which is precisely how this shipped, and
why this file checks the cascade rather than the flag.

AND THE PREMISE WAS RIGHT ONE LEVEL UP. Nothing was dead, but there were TWO
wiring mechanisms — bind-once-at-load for static nodes, rebind-per-render for
injected ones — and nothing said which a new control should use. A control added
at the bottom of the file but rendered into #view would be dead on the second
tick, silently. There is now one function, it wires everything, and a test here
refuses any binding outside it.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, TEMPLATE, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))
PAGE = TEMPLATE.read_text(encoding="utf-8")
CSS = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
SCRIPT = PAGE[PAGE.index("<script>"):]

RUN = """
FIXTURES['/api/run/supervisor_status'] = {ok:true, key:'supervisor_status',
  label:'supervisor status', argv:['python','supervisor.py','--status'],
  exit_code:0, seconds:0.4, stdout:'THE OVERLAY BODY', stderr:'',
  stdout_truncated:false};
FIXTURES['/api/expression'] = {lines:[],rejected:[],lexicon:{},unread:0,unread_rows:[]};
FIXTURES['/api/toggle'] = {toggles:{mic_enabled:false,camera_enabled:false}};
"""


# ── the reproduction from 0.3, now passing ──────────────────────────────────

def test_the_cascade_lets_hidden_hide():
    """THE ACTUAL BUG, checked where it lived: in the stylesheet.

    A DOM harness cannot catch this — there is no CSS engine in it — so the
    assertion is on specificity, which is the thing that decided the outcome.
    """
    def spec(sel):
        return (len(re.findall(r"#[\w-]+", sel)),
                len(re.findall(r"\.[\w-]+|\[[^\]]+\]", sel)), 0)

    rules = {}
    for m in re.finditer(r"(#runwrap(?:\[[^\]]+\])?)\s*\{([^}]*)\}", CSS):
        d = re.search(r"display\s*:\s*([\w-]+)", m.group(2))
        if d:
            rules[m.group(1)] = (d.group(1), spec(m.group(1)))

    assert "#runwrap" in rules, "the overlay no longer sets display"
    assert "#runwrap[hidden]" in rules, (
        "nothing re-hides #runwrap when the hidden attribute is set; an ID rule "
        "setting display beats the UA [hidden] rule and the overlay will not "
        "close")
    hide_display, hide_spec = rules["#runwrap[hidden]"]
    show_display, show_spec = rules["#runwrap"]
    assert hide_display == "none"
    assert hide_spec > show_spec, (
        f"#runwrap[hidden] {hide_spec} does not outrank #runwrap {show_spec}, "
        f"so hidden is still inert")


def test_no_element_the_page_hides_by_property_is_pinned_visible_by_an_id_rule():
    """The general form of the same defect, for the next overlay somebody adds."""
    def spec(sel):
        return (len(re.findall(r"#[\w-]+", sel)),
                len(re.findall(r"\.[\w-]+|\[[^\]]+\]", sel)), 0)

    hidden_ids = set(re.findall(r"\$\('#([\w-]+)'\)\.hidden", SCRIPT))
    hidden_ids |= set(re.findall(r"(\w+)\.hidden\s*=", SCRIPT)) & {"wrap"}
    hidden_ids.add("runwrap")           # assigned through a local `wrap`

    for hid in sorted(hidden_ids):
        shows = [(s, spec(s)) for s in re.findall(
            r"(#" + hid + r"(?:\[[^\]]+\])?)\s*\{[^}]*display\s*:\s*(?!none)", CSS)]
        if not shows:
            continue
        hides = [spec(s) for s in re.findall(
            r"(#" + hid + r"\[hidden\])\s*\{[^}]*display\s*:\s*none", CSS)]
        assert hides, (
            f"#{hid} is hidden via the hidden property but an author rule sets "
            f"display on it; add #{hid}[hidden]{{display:none}}")
        assert max(hides) > max(s for _, s in shows)


@needs_node
def test_close_closes(tmp_path):
    """The 0.3 reproduction. The handler was always fine; assert it still is."""
    r = run_probe(tmp_path, FIXTURES + RUN + """
/*---RUN---*/
FINALIZE = async () => {
  const btn = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'supervisor_status');
  await btn.onclick();
  const opened = document.querySelector('#runwrap').hidden;
  const close = document.querySelector('#runclose');
  const wired = typeof close.onclick === 'function';
  if(wired) close.onclick();
  return {opened, wired, closed: document.querySelector('#runwrap').hidden};
};
""")
    res = r["result"]
    assert res["opened"] is False, "the overlay did not open"
    assert res["wired"] is True, "CLOSE is not wired"
    assert res["closed"] is True, "CLOSE did not set the overlay hidden"


@needs_node
def test_close_returns_focus_to_the_control_that_opened_it(tmp_path):
    r = run_probe(tmp_path, FIXTURES + RUN + """
/*---RUN---*/
FINALIZE = async () => {
  const btn = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'supervisor_status');
  await btn.onclick();
  const before = LOG.focused.length;
  document.querySelector('#runclose').onclick();
  return {focusedAfter: LOG.focused.slice(before)};
};
""")
    assert r["result"]["focusedAfter"], (
        "closing the overlay left focus nowhere; a keyboard reader loses their "
        "place in the control bar")


@needs_node
def test_escape_closes_it_too(tmp_path):
    r = run_probe(tmp_path, FIXTURES + RUN + """
/*---RUN---*/
FINALIZE = async () => {
  const btn = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'supervisor_status');
  await btn.onclick();
  const open = document.querySelector('#runwrap').hidden;
  KEYDOWN({key:'Escape'});
  return {open, closed: document.querySelector('#runwrap').hidden};
};
""")
    res = r["result"]
    assert res["open"] is False
    assert res["closed"] is True, "Escape does not close the overlay"


# ── 1.3 the refresh neither resurrects nor rewrites ─────────────────────────

@needs_node
def test_a_tick_does_not_resurrect_a_closed_overlay(tmp_path):
    r = run_probe(tmp_path, FIXTURES + RUN + """
/*---RUN---*/
FINALIZE = async () => {
  const btn = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'supervisor_status');
  await btn.onclick();
  document.querySelector('#runclose').onclick();
  await tick();
  await render();
  return {hidden: document.querySelector('#runwrap').hidden};
};
""")
    assert r["result"]["hidden"] is True, (
        "the 15-second refresh reopened an overlay the reader had closed")


@needs_node
def test_an_open_overlay_is_aged_not_swapped(tmp_path):
    """Its contents must not change under the reader; it says how old they are."""
    r = run_probe(tmp_path, FIXTURES + RUN + """
/*---RUN---*/
FINALIZE = async () => {
  const btn = document.querySelectorAll('.ask-run').find(x => x.dataset.run === 'supervisor_status');
  await btn.onclick();
  const body0 = document.querySelector('#runout').textContent;
  const stale0 = document.querySelector('#runstale').textContent;
  FIXTURES['/api/run/supervisor_status'].stdout = 'COMPLETELY DIFFERENT OUTPUT';
  await tick();
  await render();
  return {body0, stale0,
          body1: document.querySelector('#runout').textContent,
          stale1: document.querySelector('#runstale').textContent,
          hidden: document.querySelector('#runwrap').hidden};
};
""")
    res = r["result"]
    assert res["hidden"] is False, "the tick closed an overlay the reader had open"
    assert res["body1"] == res["body0"] == "THE OVERLAY BODY", (
        "the refresh swapped the overlay's contents underneath the reader")
    assert res["stale0"] == ""
    assert "refreshed" in res["stale1"], (
        "the overlay does not say that its snapshot has aged")


# ── 1.1 one mechanism, and it survives a re-render ──────────────────────────

# class -> the tab that renders it. Checked on ITS OWN tab, because #view holds
# one tab at a time and a class from a tab you have navigated away from is not
# absent-because-unwired, it is absent because the markup is gone.
CONTROL_CLASSES = [
    ("tab", "overview"),        # the tab bar itself, rebuilt by drawTabs()
    ("jump", "overview"),       # the pending-human counts
    ("degchip", "cycle"),       # DEGRADED n
    ("prow", "pending"),        # an expandable proposal row
    ("unrow", "expression"),    # an unread line
    ("axis", "world"),          # an axis pill
    ("pf", "pending"),          # prefill
    ("ask-run", "overview"),    # static: supervisor status / git status
    ("cmd", "overview"),        # static: run full cycle / claude code
]


@needs_node
@pytest.mark.parametrize("cls,tab", CONTROL_CLASSES)
def test_a_control_still_has_its_handler_after_a_re_render(tmp_path, cls, tab):
    """ONE TEST PER CONTROL CLASS. A handler bound to a node cannot outlive it,
    and #view is replaced wholesale every fifteen seconds."""
    extra = ""
    if cls == "unrow":
        extra = "await markSeen();"        # the unread list is what renders .unrow
    r = run_probe(tmp_path, FIXTURES + RUN + DOORS_FIXTURE + f"""
/*---RUN---*/
FINALIZE = async () => {{
  await switchTo('{tab}');
  {extra}
  const first = document.querySelectorAll('.{cls}').length;
  await render();                       // the fifteen-second tick
  await render();                       // and the next one
  const els = document.querySelectorAll('.{cls}');
  return {{first, n: els.length,
           wired: els.filter(e => typeof e.onclick === 'function').length}};
}};
""")
    res = r["result"]
    assert res["first"] > 0, (
        f"no .{cls} was rendered on the {tab} tab — the fixture is void and this "
        f"test would pass without checking anything")
    assert res["n"] > 0, f".{cls} disappeared entirely after a re-render"
    assert res["wired"] == res["n"], (
        f"{res['n'] - res['wired']} of {res['n']} .{cls} controls lost their "
        f"handler after a re-render")


@needs_node
def test_the_negative_control_is_detected(tmp_path):
    """THE TEST MUST BE ABLE TO FAIL.

    A control injected AFTER wiring has run is exactly the defect that was
    suspected. Injecting one and asserting it is unbound proves these assertions
    have teeth; wiring then has to pick it up.
    """
    r = run_probe(tmp_path, FIXTURES + RUN + DOORS_FIXTURE + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('overview');
  const view = document.querySelector('#view');
  view.innerHTML = view.innerHTML +
    '<button class="jump" data-tab="pending" data-anchor="anchor-proposals">late</button>';
  const late = () => document.querySelectorAll('.jump').find(e => e.dataset.anchor === 'anchor-proposals' && !e._seen);
  const before = document.querySelectorAll('.jump').map(e => typeof e.onclick === 'function');
  wireControls();
  const after = document.querySelectorAll('.jump').map(e => typeof e.onclick === 'function');
  return {before, after};
};
""")
    res = r["result"]
    assert False in res["before"], (
        "a control injected after wiring appeared already bound — the harness is "
        "flattering the page and none of these assertions mean anything")
    assert all(res["after"]), (
        "wireControls() did not pick up a control injected after it last ran")


# ── the rule that keeps it one mechanism ────────────────────────────────────

def test_no_control_is_bound_outside_the_wiring_functions():
    """ast-shaped guard, in the one language this file is written in.

    The whole point of 30.1: a new control added at the bottom of the script but
    rendered into #view would be dead on the second tick and nothing would say
    so. Every binding must live inside a function the renderer calls.
    """
    wiring = []
    for name in ("wireStatic", "wirePanel", "wireTerminal", "drawTabs",
                 "mountSession", "connectTab", "ensureSession"):
        i = SCRIPT.find(f"function {name}(")
        assert i != -1, f"{name} is gone"
        wiring.append(SCRIPT[i:SCRIPT.index("\n}", i)])
    inside = "\n".join(wiring)

    offenders = []
    for m in re.finditer(r"^\s*(?:\$\('#[\w-]+'\)|document\.querySelectorAll\([^)]*\)\.forEach)"
                         r"[^\n]*\.on(?:click|change|input|toggle)\s*=", SCRIPT, re.M):
        if m.group(0) not in inside:
            offenders.append(m.group(0).strip()[:70])
    assert not offenders, (
        "these bind a handler outside the wiring functions, so they run once at "
        f"load and die on the first re-render of their node: {offenders}")


def test_re_wiring_is_idempotent():
    """wireControls() now runs after every render — forty times an hour.

    addEventListener would stack forty listeners on the same static node.
    """
    for name in ("wireStatic", "wirePanel"):
        i = SCRIPT.find(f"function {name}(")
        body = SCRIPT[i:SCRIPT.index("\n}", i)]
        # comments EXPLAIN the rule and must not trip it
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        body = re.sub(r"//[^\n]*", "", body)
        assert "addEventListener" not in body, (
            f"{name}() uses addEventListener; it runs after every render and "
            f"would stack a listener per render")


def test_both_render_paths_wire_the_controls():
    """The terminal path returns early and used to skip wiring entirely."""
    i = SCRIPT.find("async function render(){")
    body = SCRIPT[i:SCRIPT.index("\nfunction ", i)]
    terminal_branch = body[body.index("if(active === 'terminal')"):body.index("return;")]
    assert "wireControls()" in terminal_branch, (
        "the terminal path returns without wiring the control bar, so ask, "
        "unread and the bottom buttons die the moment TERMINAL is opened")
    assert body.count("wireControls()") >= 2, (
        "only one render path wires its controls")


DOORS_FIXTURE = """
FIXTURES['/api/cycles'] = {label:'t', current_cycle:'c', current_step:'s',
  covered:1, total_steps:1, counts:{done:1},
  checklist:[{index:'1',step:'a',state:'done',what:'w'}],
  badges:{degraded_steps:1, degraded_source:'x',
          degraded_rows:[{step:'a',fallback:'f',why:null,calls:1,seconds:1,
                          artifact_count:1,artifacts:['p']}]}};
FIXTURES['/api/pending'] = {improvement_proposals:{open:1},
  threshold_proposals:{unsigned:1}, quarantined_patches:{count:1},
  prefill_note:'n',
  queues:{proposals:{count:1,rows:[{id:'imp:1',title:'t',author:'a',age_days:1,
            prefill:'p',index:1,source:'s',detail:{problem:'p'}}]},
          thresholds:{count:0,rows:[]}, quarantine:{count:0,rows:[]},
          telegram:{count:0,rows:[]}}};
FIXTURES['/api/proposals'] = {groups:{}, field_used:'a', total:1};
FIXTURES['/api/forks'] = {no_data:true, missing:[], why:'w'};
FIXTURES['/api/goal'] = {subgoal_count:1, axis_count:1, composite_history:[1],
  tree:{SG:[{axis:'ENERGY_REVIEW',target:null,weight:1}]},
  continents:[{region_id:'R',zone:'Z'}]};
FIXTURES['/api/columns'] = {column_order:[], column_spec:{},
  independence_violations:[], lifecycle_ladder:'l', ladder_note:'n',
  record_count:0, empty_because:'x'};
FIXTURES['/api/somatic'] = {toggles:{}, available_count:1, total_count:2,
  state_vector:{version:'v1',measured:1,dims:1},
  groups:{G:[{key:'k',value:1,unit:'',available:true,band:'green',declined:false,
              source:'hardware',reflexivity:0}]},
  not_available:[{group:'G',key:'m',reason:'r'}]};
FIXTURES['/api/expression'] = {lines:[],rejected:[],lexicon:{},unread:1,
  unread_rows:[{ts:'2026-08-27T01:00:00+00:00',depth:'expression',
                stream:'expression',text:'u'}]};
FIXTURES['/api/expression/seen'] = {unread:0};
FIXTURES['/api/timeline'] = {rows:[], counts_by_source:{}, sources:[],
  cycles_available:['c'], cycle_id:'c', legend:[]};
FIXTURES['/api/ask'] = {queue:[]};
FIXTURES['/api/axis/ENERGY_REVIEW'] = {axis:'ENERGY_REVIEW', known:true,
  subgoal:'SG', latest:{score:0.2,level:'LOW',verification:'V',metrics_used:{},
  signals:[]}, target:1, target_unit:'u', direction:'d', rationale:'r',
  weight:1, score_source:'s', latest_scale:'0..1', history_scale:'0..100',
  history_len:2, history:[{date:'a',score:1,source:'s'},
                          {date:'b',score:2,source:'s'}], sources:{}};
"""
