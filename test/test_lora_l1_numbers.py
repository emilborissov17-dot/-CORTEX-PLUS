# -*- coding: utf-8 -*-
"""test/test_lora_l1_numbers.py — the L1 teaching material is correct by arithmetic and keeps the real exam unseen."""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from training import lora_l1_numbers as L1  # noqa: E402


def _parse(ex):
    u = ex["messages"][0]["content"]
    v = float(re.search(r"\nvalue: (-?[\d.]+)", u).group(1))
    line = float(re.search(r"\): (-?[\d.]+) ", u).group(1))
    worse_high = "higher is worse" in u
    return v, line, worse_high, json.loads(ex["messages"][1]["content"])["verdict"]


def test_every_answer_is_right_by_independent_arithmetic():
    for ex in L1.build(600, 5):
        v, line, worse_high, verdict = _parse(ex)
        assert v != line
        assert verdict == ("OVER" if (v > line if worse_high else v < line) else "UNDER")


def test_balanced_twins_and_no_real_case_names():
    rows = L1.build(800, 7)
    assert 0.4 < sum(r["meta"]["truth"] == "OVER" for r in rows) / len(rows) < 0.6
    assert not any(r["meta"]["case"].split(":", 1)[1] in L1.REAL_CASE_NAMES for r in rows)
    keys = {}
    for r in rows:
        keys.setdefault((r["meta"]["case"], r["meta"]["line"], r["meta"]["direction"]), set()).add(r["meta"]["truth"])
    assert sum(1 for s in keys.values() if s == {"OVER", "UNDER"}) > 100     # the counterfactual twins are there


def test_holdout_differs_from_train():
    tr = {r["messages"][0]["content"] for r in L1.build(400, 11)}
    ho = {r["messages"][0]["content"] for r in L1.build(200, 911)}
    assert len(tr & ho) < 5
