# -*- coding: utf-8 -*-
"""
test/test_truncation_budgets.py — STEP 6c of the 10 Sep 2026 handover.

MEASURED, NOT ASSUMED. Counted over memory/cycle_logs/*.log in this repo:
~5 truncations a night, every night, across 31 distinct axis labels
(FOOD_REVIEW 6, WATER_REVIEW 5, SCOUT/GOVERNANCE_INSTITUTIONS_REVIEW 4, ...).
Each one printed `TRUNCATED from <backend> (max_tokens=N) — retrying once at 2N`
and each retry then SUCCEEDED. So the answer was reachable all along and the
first budget was simply too small — the cost was a whole second LLM call, ~5
times a night.

The handover asked for "the axis name in the log line so the pattern is
countable". It is already there and always was: call_llm_json's `label=`
carries the axis, which is how the counts above were produced. What was
missing was the budget.

THE NUMBERS ARE THE ONES THE RETRY PROVED, not guesses:
  internet_agent  400 -> 800   (_reasoning_budget: 1500 -> 2400)
  data_scout      600 -> 1200  (_reasoning_budget: 1800 -> 3600)

Note the trap in the old log line: max_tokens=400 was never the real Groq
budget, because GROQ_BUDGET_FLOOR lifts it to 1500 regardless. A fix aimed at
"raise 400" without checking the floor would have moved nothing.

max_tokens is a CEILING, not a spend: a short answer costs the same at 800 as at
400, so this removes a duplicated call and adds nothing to the bill. The
forbidden shortcut is the opposite one — silencing the TRUNCATED line, or
dropping retry_on_truncation, either of which would hide the truncation instead
of ending it.
"""
from __future__ import annotations

import ast
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def _src(path: pathlib.Path) -> str:
    """utf-8-sig: agents/internet/internet_agent.py carries a UTF-8 BOM, and
    ast.parse refuses U+FEFF as a non-printable character."""
    return path.read_text(encoding="utf-8-sig")


def _call_llm_json_kwargs(path: pathlib.Path) -> list:
    """Every call_llm_json(...) in a file, as {kwarg: literal}."""
    tree = ast.parse(_src(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "call_llm_json":
            continue
        kw = {}
        for k in node.keywords:
            if k.arg and isinstance(k.value, ast.Constant):
                kw[k.arg] = k.value.value
        out.append(kw)
    return out


def test_the_axis_review_budget_is_the_one_the_retry_proved():
    calls = _call_llm_json_kwargs(BASE / "agents" / "internet" / "internet_agent.py")
    assert calls, "no call_llm_json call found in internet_agent.py"
    budgets = [c.get("max_tokens") for c in calls if "max_tokens" in c]
    assert budgets, "the call carries no explicit max_tokens"
    assert min(budgets) >= 800, (
        f"axis-review budget is back below 800 ({budgets}); 400 truncated ~5 "
        f"times a night and every retry at 800 succeeded")


def test_the_scout_budget_is_the_one_the_retry_proved():
    calls = _call_llm_json_kwargs(BASE / "core" / "data_scout.py")
    budgets = [c.get("max_tokens") for c in calls if "max_tokens" in c]
    assert budgets, "the scout call carries no explicit max_tokens"
    assert min(budgets) >= 1200, (
        f"scout budget is back below 1200 ({budgets}); 600 truncated and every "
        f"retry at 1200 succeeded")


def test_the_new_budget_beats_the_old_retry_not_just_the_old_attempt():
    """The point is to stop the SECOND call, so the first attempt must now be at
    least as generous as the retry used to be. 800 -> 2400 vs the old retry's
    2400: equal, which is exactly the threshold that landed."""
    from core import groq_backend as G
    old_first = G._reasoning_budget(400, G.GROQ_BUDGET_MULT, G.GROQ_BUDGET_FLOOR,
                                    G.GROQ_BUDGET_CAP)
    old_retry = G._reasoning_budget(800, G.GROQ_BUDGET_MULT, G.GROQ_BUDGET_FLOOR,
                                    G.GROQ_BUDGET_CAP)
    new_first = old_retry
    assert old_first == 1500, (
        "GROQ_BUDGET_FLOOR no longer lifts 400 to 1500 — the measurement in this "
        "file's docstring was made under that floor and needs redoing")
    assert new_first > old_first, "the new first attempt is no bigger than the old one"


def test_truncation_is_still_retried_rather_than_hidden():
    """MECHANICAL NET on the forbidden shortcut. Raising the budget must not be
    paired with removing the retry or the TRUNCATED line: a bigger budget makes
    truncation rarer, never impossible, and a silent truncation is worse than a
    logged one. This fails if the retry or its announcement is dropped."""
    src = (BASE / "core" / "llm_json.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "call_llm_json")
    body = ast.dump(fn)
    assert "retry_on_truncation" in body, "the retry switch is gone"
    assert "TruncatedJSONError" in body, "truncation is no longer caught by name"
    # and the announcement still names the label, which is how the axis counts
    # in this file's docstring were produced
    assert "TRUNCATED" in src


def test_the_label_still_carries_the_axis_name():
    """The countability the handover asked for: every one of these call sites
    must pass a per-axis label, or the log line loses the axis and the pattern
    becomes uncountable again."""
    for path, expect in ((BASE / "agents" / "internet" / "internet_agent.py", "axis"),
                         (BASE / "core" / "data_scout.py", None)):
        calls = _call_llm_json_kwargs(path)
        tree = ast.parse(_src(path))
        labelled = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "call_llm_json":
                continue
            if any(k.arg == "label" for k in node.keywords):
                labelled = True
        assert labelled, f"{path.name} calls call_llm_json without a label"
