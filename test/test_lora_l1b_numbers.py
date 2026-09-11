# -*- coding: utf-8 -*-
"""test/test_lora_l1b_numbers.py — L1b lessons teach the skill, not the form (12 Sep 2026).

Pins the four rules: every verdict is arithmetic; number twins flip and paraphrase/date
twins hold; no exam-only layout ever appears in a lesson; the answer writes the
comparison before the verdict; no real probe case is taught.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "training"))
import lora_l1b_numbers as B  # noqa: E402
from lora_l1_numbers import truth  # noqa: E402


def test_verdicts_are_arithmetic_and_no_real_case_is_taught():
    for r in B.build(300, 1, False, None) + B.build(80, 2, True, None):
        m, a = r["meta"], json.loads(r["messages"][1]["content"])
        assert a["verdict"] == m["truth"] == truth(m["value"], m["line"], m["direction"])
        assert m["case"].split(":", 1)[1] not in B.REAL_CASE_NAMES


def test_number_twins_flip_and_paraphrase_twins_hold():
    by = collections.defaultdict(dict)
    for r in B.build(600, 3, False, None):
        by[r["meta"]["pair"]][r["meta"]["group"]] = r["meta"]["truth"]
    pairs = [d for d in by.values() if "base" in d]
    assert any("number_twin" in d for d in pairs) and any("paraphrase_twin" in d for d in pairs)
    for d in pairs:
        if "number_twin" in d:
            assert d["number_twin"] != d["base"]
        for hold in ("paraphrase_twin", "date_twin"):
            if hold in d:
                assert d[hold] == d["base"]


def test_exam_only_layouts_never_appear_in_lessons():
    taught = {r["meta"]["layout"] for r in B.build(800, 4, False, None)}
    assert not taught & {f.__name__ for f in B.LAYOUT_EXAM}
    groups = {r["meta"]["group"] for r in B.build(200, 5, True, None)}
    assert groups == {"seen_long", "unseen_short", "unseen_long", "probe_long"}


def test_exam_rows_come_in_flipping_pairs():
    ex = B.build(120, 6, True, None)
    by = collections.defaultdict(list)
    for r in ex:
        by[r["meta"]["pair"]].append(r["meta"]["truth"])
    assert all(len(v) == 2 and v[0] != v[1] for v in by.values())


def test_the_step_comes_before_the_verdict():
    r = B.build(10, 7, False, None)[0]
    txt = r["messages"][1]["content"]
    assert txt.index('"reason"') < txt.index('"verdict"') and " vs line " in txt


def test_twins_stay_inside_the_unit_domain():
    for r in B.build(800, 8, False, None):
        if r["meta"]["group"] == "number_twin" and "percent" in r["messages"][0]["content"]:
            assert 0 <= r["meta"]["value"] <= 100
