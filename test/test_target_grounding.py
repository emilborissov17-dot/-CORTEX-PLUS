# -*- coding: utf-8 -*-
"""test/test_target_grounding.py — the ratchet: our own targets are held to the sensor standard (10 Sep 2026)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("target_grounding", REPO / "scripts" / "target_grounding.py")
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

# Measured 10 Sep 2026 on config/target_config.json: 24 axes, 17 with a primary metric,
# 17 UNGROUNDED, 0 GROUNDED. This number may go DOWN. A commit that raises it — a new
# target written as prose only — fails here, by the same rule that refuses a sensor's
# invented row. Lower it in the same commit that grounds a target.
UNGROUNDED_CEILING = 17


def test_a_target_with_prose_only_is_ungrounded():
    r = tg.judge_axis("X", {"primary_metric": "m", "target_value": 1.0, "rationale": "Someone et al. 2009 says 1.0"})
    assert r["verdict"] == tg.UNGROUNDED


def test_a_qualitative_axis_is_semantic_not_ungrounded():
    assert tg.judge_axis("X", {"primary_metric": None, "target_value": None})["verdict"] == tg.SEMANTIC


def test_a_target_with_a_page_is_judged_by_the_gate_not_by_its_shape():
    spec_ = {"primary_metric": "co2", "target_value": 350.0, "unit": "ppm",
             "source_url": "https://x", "quote": "safe boundary of 350 ppm"}
    page_yes = "<p>... a safe boundary of 350 ppm for CO2 ...</p>"
    page_no = "<p>nothing of the sort</p>"
    assert tg.judge_axis("X", spec_, fetch=lambda u: page_yes)["verdict"] == tg.GROUNDED
    assert tg.judge_axis("X", spec_, fetch=lambda u: page_no)["verdict"] == tg.CONTESTED
    assert tg.judge_axis("X", spec_, fetch=lambda u: None)["verdict"] == tg.UNFETCHED
    # the value must be the number in the quote — a page that says 350 does not ground a target of 450
    assert tg.judge_axis("X", dict(spec_, target_value=450.0), fetch=lambda u: page_yes)["verdict"] == tg.CONTESTED


def test_without_fetch_a_grounded_looking_target_is_unfetched_never_grounded():
    spec_ = {"primary_metric": "co2", "target_value": 350.0, "source_url": "https://x", "quote": "350 ppm"}
    assert tg.judge_axis("X", spec_)["verdict"] == tg.UNFETCHED


def test_the_ratchet_on_the_live_config():
    r = tg.audit()
    assert r["axes"] == 24
    assert r["counts"][tg.UNGROUNDED] <= UNGROUNDED_CEILING, (
        f"{r['counts'][tg.UNGROUNDED]} ungrounded targets, ceiling {UNGROUNDED_CEILING}: a target was added as prose only")
    assert r["counts"][tg.GROUNDED] + r["counts"][tg.CONTESTED] + r["counts"][tg.UNFETCHED] + r["counts"][tg.UNGROUNDED] == r["measurable"]


def test_markdown_carries_every_axis_and_the_rule(tmp_path):
    md = tg.markdown(tg.audit())
    for a in tg.axes():
        assert a in md
    assert "UNGROUNDED" in md and "ratchet" in md
