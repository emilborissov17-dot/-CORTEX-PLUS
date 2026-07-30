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
