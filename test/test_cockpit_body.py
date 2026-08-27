"""The whole body in one look, and the ones it cannot read say why.

Two complaints. Forty-odd rows in a single column ran off a 1080p screen, so
reading the body meant scrolling it — and a body you have to scroll is a body
you compare against your memory of the top of it. And the header count that
raises the obvious question ("33/43 available") was not connected to the list
that answers it, which was folded into a <details> at the bottom.

AND THE MIC CONTRADICTION (COMMAND 30, 0.2). The panel printed the same three
words — NOT AVAILABLE — for a sensor this machine does not have and for a sample
somatic.py deliberately refused a moment ago. So MIC ON was green, the
microphone was working (measured live: rms 1.4e-05), and mic_rms said NOT
AVAILABLE, because acoustic() had sampled seconds earlier and
CAPTURE_COOLDOWN_SEC is 10. Both statements were true and together they read as
a lie. A refusal is now DECLINED, and it carries its reason.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from test_cockpit_doors import (FIXTURES, REPO, TEMPLATE, needs_node,  # noqa: F401
                                run_probe)

sys.path.insert(0, str(REPO))
PAGE = TEMPLATE.read_text(encoding="utf-8")

BODY = """
FIXTURES['/api/panels'] = {panels:[{panel:'somatic',live:true}]};
FIXTURES['/api/somatic'] = {
  toggles:{mic_enabled:true, camera_enabled:false},
  available_count:33, total_count:43,
  state_vector:{version:'v1', measured:25, dims:25},
  groups:{
    ENERGY:[{key:'battery_percent', value:97, unit:'%', available:true, band:'green',
             declined:false, source:'hardware', reflexivity:0},
            {key:'battery_secsleft', value:null, unit:'s', available:false,
             declined:false, reason:'unlimited while plugged in',
             source:'hardware', reflexivity:0}],
    ACOUSTIC:[{key:'mic_rms', value:null, unit:'rms', available:false, declined:true,
               reason:'REFUSED: 9.6s left of the 10s capture cooldown',
               source:'hardware', reflexivity:0}],
    THERMAL:[{key:'cpu_temp_c', value:null, unit:'C', available:false, declined:false,
              reason:'psutil.sensors_temperatures() is not implemented on Windows',
              source:'hardware', reflexivity:0}]},
  not_available:[
    {group:'ENERGY', key:'battery_secsleft', reason:'unlimited while plugged in'},
    {group:'THERMAL', key:'cpu_temp_c', reason:'psutil.sensors_temperatures() is not implemented on Windows'},
    {group:'STORAGE', key:'smart_health', reason:'SMART needs elevated rights and smartctl, neither present'}]};
"""


@needs_node
def test_the_available_count_opens_the_list_of_what_is_missing(tmp_path):
    """THE HEADLINE. The count that raises the question now answers it."""
    r = run_probe(tmp_path, FIXTURES + BODY + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('body');
  const closed = document.querySelector('#view').innerHTML;
  const b = document.querySelector('#bodymissing');
  if(!b) return {found:false};
  await b.onclick();
  return {found:true, closed, open: document.querySelector('#view').innerHTML};
};
""")
    res = r["result"]
    assert res["found"] is True, "the available count is not a control"
    assert "33/43" in res["closed"], "the header no longer states the count"
    assert 'id="anchor-missing"' not in res["closed"], (
        "the why-list is BUILT before it is asked for — the same rule the tabs "
        "follow: not hidden with CSS, not built")
    assert 'id="anchor-missing"' in res["open"]


@needs_node
def test_every_missing_sensor_states_its_reason(tmp_path):
    """no sensor / not implemented / needs admin — never a bare absence."""
    r = run_probe(tmp_path, FIXTURES + BODY + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('body');
  await document.querySelector('#bodymissing').onclick();
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    for reason in ("unlimited while plugged in",
                   "not implemented on Windows",
                   "needs elevated rights"):
        assert reason in html, f"the missing list does not say {reason!r}"


@needs_node
def test_a_declined_sample_is_not_reported_as_a_missing_sensor(tmp_path):
    """THE MIC CONTRADICTION. A refusal is a decision, not an absence."""
    r = run_probe(tmp_path, FIXTURES + BODY + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('body');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert "DECLINED" in html, (
        "a refused sample still reads as NOT AVAILABLE, which is what made the "
        "green MIC ON toggle look like a contradiction")
    assert "capture cooldown" in html, "the refusal does not carry its reason"


@needs_node
def test_the_body_renders_in_two_columns_with_groups_kept_whole(tmp_path):
    r = run_probe(tmp_path, FIXTURES + BODY + """
/*---RUN---*/
FINALIZE = async () => {
  await switchTo('body');
  return {html: document.querySelector('#view').innerHTML};
};
""")
    html = r["result"]["html"]
    assert 'class="bodycols"' in html, "the body is still one column"
    assert html.count('class="bodygroup"') >= 3, (
        "groups are no longer their own blocks, so a column break can split one")


def test_the_two_column_css_keeps_a_group_intact():
    assert "column-count:2" in PAGE.replace(" ", ""), "no two-column rule"
    assert "break-inside:avoid" in PAGE.replace(" ", ""), (
        "a group can be split across the column break, which is worse than one "
        "long column")


# ── the honest half: the distinction is in the DATA, not sniffed in the page ──

def test_a_refusal_is_a_field_not_a_string_the_page_has_to_sniff():
    from cockpit import somatic as som
    r = som.Reading("ACOUSTIC", "mic_rms", None, "rms", available=False,
                    reason="REFUSED: 9.6s left of the 10s capture cooldown")
    assert r.declined is True
    assert r.as_dict()["declined"] is True

    absent = som.Reading("THERMAL", "cpu_temp_c", None, "C", available=False,
                         reason="psutil.sensors_temperatures() is not implemented")
    assert absent.declined is False
    assert absent.as_dict()["declined"] is False


def test_the_live_microphone_is_declined_not_missing_when_it_is_on_cooldown():
    """Against the real module, because the contradiction was a real one."""
    from cockpit import somatic as som
    first = [r for r in som.acoustic(enabled=True) if r.key == "mic_rms"][0]
    second = [r for r in som.acoustic(enabled=True) if r.key == "mic_rms"][0]

    # The first read may itself be refused (a cycle running, or a cooldown left
    # over from another caller). What must hold is that a REFUSAL never looks
    # like a missing sensor.
    for row in (first, second):
        if not row.available and "REFUSED" in (row.reason or ""):
            assert row.declined is True
            break
    else:
        pytest.skip("the microphone was never refused during this run")


def test_the_refusal_names_the_cooldown_that_caused_it():
    """A DECLINED row is only useful if it says why, and for how long.

    The page shows the reason verbatim, so the sentence has to come from the
    module that made the decision rather than from the template guessing.
    """
    from cockpit import somatic as som
    assert som.CAPTURE_COOLDOWN_SEC > 0

    som._stamp("mic")                       # as a real sample would have done
    refused = [r for r in som.acoustic(enabled=True) if r.key == "mic_rms"][0]
    assert refused.declined is True
    assert "cooldown" in refused.reason
    assert str(int(som.CAPTURE_COOLDOWN_SEC)) in refused.reason, (
        "the refusal does not name the cooldown it is enforcing, so the reader "
        "cannot tell how long to wait")
