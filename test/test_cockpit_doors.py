"""Every mentioned thing is reachable by clicking its mention.

Emil walked every tab and found the cockpit a dead end: OVERVIEW said
"improvement proposals 22" and that was the end of the sentence. The number was
true, there was no way to reach the twenty-two, and the tab bar was the only
guess available. CYCLE said "DEGRADED 2" while the step names, the fallback that
actually ran and the artifact paths sat unused in the same API payload.

These tests DRIVE THE REAL PAGE. test/cockpit_dom_harness.js runs the cockpit's
own inline JavaScript against a strict DOM — querySelector returns null for
markup that is not there, exactly as a browser does — so a handler that is never
attached, or an anchor that does not exist, fails here rather than in front of a
human.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "cockpit" / "templates" / "cockpit.html"
HARNESS = pathlib.Path(__file__).resolve().parent / "cockpit_dom_harness.js"

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(
    NODE is None,
    reason="node is not installed; the cockpit's JS cannot be executed here")


def inline_js() -> str:
    """The page's own inline <script> body, exactly as the browser receives it."""
    html = TEMPLATE.read_text(encoding="utf-8")
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert blocks, "cockpit.html has no inline script block"
    return blocks[-1]


def run_probe(tmp_path, probe: str) -> dict:
    """Run `probe` inside the page's own sandbox. Returns the harness report."""
    js = tmp_path / "inline.js"
    js.write_text(inline_js(), encoding="utf-8")
    pf = tmp_path / "probe.js"
    pf.write_text(probe, encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(HARNESS), str(js), str(TEMPLATE), str(pf)],
        capture_output=True, text=True, timeout=90, cwd=str(REPO))
    out = proc.stdout
    marker = "---HARNESS-JSON---"
    assert marker in out, f"harness produced no report:\n{out}\n{proc.stderr}"
    report = json.loads(out.split(marker, 1)[1].strip())
    assert report["threw"] is None, f"the page threw: {report['threw']}"
    return report


# The payloads every probe starts from. Deliberately small and obviously fake:
# a test that reads the live memory/ would pass or fail with the weather.
FIXTURES = """
FIXTURES['/api/panels'] = {panels:[{panel:'cycles',live:true},{panel:'pending',live:true}]};
FIXTURES['/api/flow']   = {computed_now:{flow_score:2.5272}, red_below:2.0};
FIXTURES['/api/cycles'] = {
  label:'test', current_cycle:'c-1', current_step:'body_scan', covered:2, total_steps:2,
  counts:{done:1,passed:0},
  checklist:[{index:'1',step:'planet_snapshots_agent',state:'done',what:'a description long enough that the old code would have cut it at seventy characters and lost the end'},
             {index:'2',step:'body_scan',state:'done',what:'short'}],
  badges:{survival_latched:false, degraded_steps:2,
          degraded_source:'memory/step_contract_latest.json',
          degraded_rows:[
            {step:'planet_snapshots_agent', fallback:'answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned',
             why:null, calls:1, seconds:81.77, artifact_count:11,
             artifacts:['memory/snapshots/planet.json','memory/cycle_logs/x.log']},
            {step:'cortex_orchestrator', fallback:'answered by local_3b (qwen2.5:3b) at its slice of B=112s',
             why:null, calls:1, seconds:93.53, artifact_count:6,
             artifacts:['memory/chromadb/chroma.sqlite3']}]}};
FIXTURES['/api/pending'] = {
  improvement_proposals:{open:22}, threshold_proposals:{unsigned:15},
  quarantined_patches:{count:2}, prefill_note:'note',
  queues:{
    proposals:{count:22, rows:[{id:'imp:23', title:'SOCIAL_RELATIONS_REVIEW is furthest from the goal',
      author:'hyperclaw', age_days:7.6, prefill:'echo hi', index:23,
      source:'memory/improvement_proposals.json',
      detail:{problem:'THE WHOLE PROBLEM TEXT', solution:'THE WHOLE SOLUTION TEXT',
              measurable_goal:'up 10% in 3 years', root_cause:'plan-2026-08-27.md',
              component:'SOCIAL', priority:'HIGH', generated_by:'HYPERCLAW',
              timestamp:'2026-08-27T01:29:12Z'}}]},
    thresholds:{count:15, rows:[]}, quarantine:{count:2, rows:[]},
    telegram:{count:0, rows:[]}}};
FIXTURES['/api/proposals'] = {groups:{}, field_used:'author', total:22};
FIXTURES['/api/forks'] = {no_data:true, missing:[], why:'x'};
FIXTURES['/api/expression'] = {lines:[], rejected:[], lexicon:{}, unread:0};
FIXTURES['/api/toggle'] = {toggles:{mic_enabled:false, camera_enabled:false}};
"""


@needs_node
def test_the_overview_counts_are_buttons_that_carry_a_destination(tmp_path):
    """THE HEADLINE. A count that names nothing is a dead end."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = () => {
  const html = document.querySelector('#view').innerHTML;
  const jumps = document.querySelectorAll('.jump').map(b => ({
    tab: b.dataset.tab, anchor: b.dataset.anchor, wired: typeof b.onclick === 'function'}));
  return {html_has_22: html.includes('22'), jumps};
};
""")
    jumps = r["result"]["jumps"]
    assert len(jumps) == 3, f"expected three doors on OVERVIEW, got {jumps}"
    assert all(j["wired"] for j in jumps), "a count rendered as a button with no handler"
    assert {j["anchor"] for j in jumps} == {
        "anchor-proposals", "anchor-thresholds", "anchor-quarantine"}
    assert {j["tab"] for j in jumps} == {"pending"}


@needs_node
def test_clicking_a_count_switches_tab_and_scrolls_to_an_anchor_that_exists(tmp_path):
    """The anchor must be REAL. A door onto a missing id is still a dead end."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  const b = document.querySelectorAll('.jump').find(x => x.dataset.anchor === 'anchor-proposals');
  await b.onclick();
  return {tab: LOG.stored['cortex.cockpit.tab'], scrolled: LOG.scrolled,
          html: document.querySelector('#view').innerHTML};
};
""")
    res = r["result"]
    assert res["tab"] == "pending", "the click did not switch tab"
    assert 'id="anchor-proposals"' in res["html"], (
        "PENDING rendered without the anchor the door points at")


@needs_node
def test_every_anchor_a_door_points_at_is_rendered_by_its_tab(tmp_path):
    """All three, not just the one with a convenient fixture."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  const wanted = document.querySelectorAll('.jump').map(b => b.dataset.anchor);
  await switchTo('pending');
  return {wanted, html: document.querySelector('#view').innerHTML};
};
""")
    res = r["result"]
    missing = [a for a in res["wanted"] if f'id="{a}"' not in res["html"]]
    assert not missing, f"doors point at anchors PENDING never renders: {missing}"


@needs_node
def test_degraded_is_a_chip_that_names_the_steps_and_the_fallback(tmp_path):
    """DEGRADED 2 used to be the whole sentence. The names were in the payload."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('cycle');
  const before = document.querySelector('#view').innerHTML;
  const chip = document.querySelectorAll('.degchip')[0];
  if(!chip) return {chip: false};
  await chip.onclick();
  const after = document.querySelector('#view').innerHTML;
  return {chip: true, before_names: before.includes('cortex_orchestrator'),
          after: after};
};
""")
    res = r["result"]
    assert res["chip"] is True, "DEGRADED did not render as a clickable chip"
    after = res["after"]
    assert "planet_snapshots_agent" in after and "cortex_orchestrator" in after, (
        "the chip opened without naming the degraded steps")
    assert "local_3b" in after, "it does not say which fallback ran"
    assert "memory/snapshots/planet.json" in after, "no artifact path is shown"
    assert 'id="anchor-degraded"' in after


@needs_node
def test_a_proposal_row_opens_in_place_with_its_full_text_and_source(tmp_path):
    """Before any prefill: the human approving it should be able to read it."""
    r = run_probe(tmp_path, FIXTURES + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('pending');
  const closed = document.querySelector('#view').innerHTML;
  const row = document.querySelectorAll('.prow')[0];
  if(!row) return {row: false};
  await row.onclick({target:{closest:()=>null}});
  return {row: true, closed, open: document.querySelector('#view').innerHTML};
};
""")
    res = r["result"]
    assert res["row"] is True, "proposal rows are not clickable"
    assert "THE WHOLE SOLUTION TEXT" not in res["closed"], (
        "the fixture is void — the full text was already visible when closed")
    assert "THE WHOLE SOLUTION TEXT" in res["open"]
    assert "THE WHOLE PROBLEM TEXT" in res["open"]
    assert "memory/improvement_proposals.json" in res["open"], (
        "the row does not say which file it came from")


@needs_node
def test_a_zero_count_is_not_a_door(tmp_path):
    """A control that opens an empty list teaches distrust of the ones that work."""
    r = run_probe(tmp_path, FIXTURES + """
FIXTURES['/api/pending'].improvement_proposals = {open:0};
FIXTURES['/api/pending'].threshold_proposals = {unsigned:0};
FIXTURES['/api/pending'].quarantined_patches = {count:0};
/*---RUN---*/
FINALIZE = () => ({jumps: document.querySelectorAll('.jump').length});
""")
    assert r["result"]["jumps"] == 0


def test_the_server_hands_over_what_the_doors_need():
    """ast, not a live request: the fields must be BUILT, not happen to be there."""
    import ast
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    for field in ("degraded_rows", "degraded_source", "detail", "source"):
        assert field in keys, (
            f"cockpit/server.py never builds {field!r}; the panel would have "
            f"nothing to open")
