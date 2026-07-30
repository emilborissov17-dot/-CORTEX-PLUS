#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_diag_goal_impact.py — WHY did the goal_impact collector return n=0 on a page that
scout.py grounds cleanly? Read-only diagnostic. Shows: the text the collector actually
sees, whether the key figure is in it, the RAW local-model output, and EXACTLY which
guard rejected the read (or that the model itself declined). No writes, no drops.

  venv/Scripts/python.exe experiments/browser_scout/_diag_goal_impact.py \
      https://en.wikipedia.org/wiki/List_of_ongoing_armed_conflicts
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autonomous_scout as s
import goal_impact as gi

URL = sys.argv[1] if len(sys.argv) > 1 else \
    "https://en.wikipedia.org/wiki/List_of_ongoing_armed_conflicts"
AXIS = "SOCIAL_RELATIONS_REVIEW"
NEED = "current signal of social cohesion / unrest and its direction vs the goal"

print(f"URL: {URL}")
txt = s._page_text(URL)
print(f"page_text length: {len(txt)}")
print(f"contains '48'?  {'48' in txt}    contains 'conflict'?  {'conflict' in txt.lower()}")
print(f"text head (first 300): {txt[:300]!r}")
print(f"text[:6500] tail (what the model sees LAST): {txt[6300:6500]!r}")
print("-" * 70)

# Tee the raw model output so we see what qwen actually returned (both votes).
_orig = gi._local
_calls = {"n": 0}
def _tee(prompt, num_predict=350, **kw):
    _calls["n"] += 1
    out = _orig(prompt, num_predict=num_predict, **kw)
    print(f"\n=== RAW MODEL OUTPUT (call {_calls['n']}, {len(out)} chars) ===")
    print(out[:1200])
    print("=== end raw ===")
    return out
gi._local = _tee

print("\n>>> single extract_goal_impact (shows the guard verdict):")
obs, why = gi.extract_goal_impact(txt, AXIS, NEED, URL)
print(f"\nVERDICT why = {why!r}")
print(f"OBS = {obs}")

# If it was grounding, show the near-miss: what did the model claim as evidence vs the text?
try:
    import json, re
    got = gi._json_from(_orig(  # one clean read, un-teed, to inspect fields
        f"{gi._frame()}\n\nYou are measuring the axis '{AXIS}' (need: {NEED}) by reading a web "
        f"page.\nFind the SINGLE most relevant observation (a number or a stated fact) and assess "
        f"its impact.\nReply ONLY JSON with keys observation, evidence, value, unit, sign, "
        f"magnitude, dimension, rationale, contested, counterview.\n\nPAGE TEXT (truncated):\n{txt[:6500]}"))
    ev = str(got.get("evidence", "")).strip()
    def _norm(x): return re.sub(r"\s+", " ", x).strip().lower()
    print("\n--- grounding inspection ---")
    print(f"model evidence: {ev!r}")
    print(f"evidence[:40] normalised: {_norm(ev)[:40]!r}")
    print(f"is evidence[:40] a verbatim span of the page? {_norm(ev)[:40] in _norm(txt)}")
    print(f"model value: {got.get('value')!r}  contested: {got.get('contested')!r}  "
          f"counterview len: {len(str(got.get('counterview','')))}")
except Exception as e:
    print(f"(inspection read failed: {type(e).__name__}: {e})")

# ---------------------------------------------------------------------------
# FORCED GUARD 3 — DIAGNOSTIC ONLY. Nothing here touches the pipeline; the
# shipped guards are unchanged and still reject these pages upstream.
# GUARD 1 keeps firing on Wikipedia citation-bracket noise ('[3]' vs '[ 3 ]')
# BEFORE decomposition can run, so GUARD 3 has never executed on real data and
# the raised budgets (_decompose_claims 1200 / _refute_claim 400) are unproven.
# Feed structural_faithful an evidence span sliced VERBATIM from this very page
# so grounding cannot fail for formatting reasons, then watch the real path:
# decompose -> per-claim grounding -> adversarial entailment.
print("\n" + "=" * 70)
print(">>> FORCED GUARD 3 (bypasses GUARD 1 — diagnostic only, pipeline untouched)")

_i = txt.find("254,000")
span = txt[_i:_i + 60].strip() if _i >= 0 else txt[2000:2060].strip()
print(f"verbatim span: {span!r}")
print(f"span verbatim in page? {gi._norm(span)[:40] in gi._norm(txt)}")

# One faithful case and one fabricated control, so a 'passed' result is only
# meaningful if the fabricated twin is actually rejected on the same real page.
for label, observation in [
        ("FAITHFUL   ", "Cumulative fatalities are reported as 254,000 to 263,000+."),
        ("FABRICATED ", "Cumulative fatalities are reported as 999,000.")]:
    print(f"\n--- {label} obs: {observation}")
    _t0 = time.time()
    try:
        passed, survivors, broken = gi.structural_faithful(observation, span, txt)
    except Exception as e:
        print(f"   structural_faithful raised: {type(e).__name__}: {e}")
        continue
    print(f"   passed={passed}  survivors={len(survivors)}  broken={len(broken)}  "
          f"({time.time() - _t0:.0f}s)")
    for s_ in survivors:
        print(f"   SURVIVOR: {str(s_.get('text'))!r}")
        print(f"             span={str(s_.get('evidence_span'))[:70]!r}")
    for b in broken:
        print(f"   BROKEN[{b.get('stage')}]: {b.get('why')} — claim: {str(b.get('claim'))!r}")
