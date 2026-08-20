#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_orchestrator_grounded.py — ATTENTION IS ALLOCATED BY ARITHMETIC.

WHY
----
cognitive_orchestrator (12.7) decides which axes matter this cycle. When that
came from a model reading prose, the priority order was an opinion that could
not be checked, reproduced or disagreed with. A system whose composite is 0 of
173 measured cannot also have its attention allocated by assertion.

    penalty = 1 - score          how far the axis is from its own target
    need    = weight x penalty   how much of the goal is being lost there

THE THREE INVARIANTS UNDER TEST
--------------------------------
  1. Empty feeds REFUSE. An orchestration built on nothing is indistinguishable
     from one built on everything being fine, so it must not be produced.
  2. THREAT and OPPORTUNITY are disjoint BY CONSTRUCTION — set difference, not
     two thresholds that could both fire.
  3. The action vocabulary is closed, and exactly one action reaches outside
     this repo: REPORT_TO_HUMAN.

    venv\\Scripts\\python.exe -m pytest test/test_orchestrator_grounded.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core.orchestrator_grounded import (ACTIONS, INTERNAL_ACTIONS, OPPORTUNITY,
                                        THREAT, WATCH, WORLD_ACTIONS,
                                        RefusedToOrchestrate, action_for,
                                        classify, load_scores, orchestrate, rank,
                                        write)

REPO = pathlib.Path(__file__).resolve().parents[1]


def _feed(axis, weight, value=1.0, present=True):
    return {"axis": axis, "weight": weight, "key": "k", "unit": "u",
            "value": value if present else None,
            "status": "PRESENT" if present else "ABSENT"}


def _write_feeds(tmp_path, feeds):
    p = tmp_path / "axis_feeds_latest.json"
    p.write_text(json.dumps({"feeds": feeds}), encoding="utf-8")
    return p


def _write_goal(tmp_path, scores):
    p = tmp_path / "goal.json"
    p.write_text(json.dumps({"metric_details": {
        f"k{i}": {"axis": a, "score": s} for i, (a, s) in enumerate(scores.items())
    }}), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# (a) THE NEGATIVE CONTROL — empty feeds must refuse
# ---------------------------------------------------------------------------

def test_no_feeds_at_all_refuses(tmp_path):
    with pytest.raises(RefusedToOrchestrate) as caught:
        orchestrate(feeds_path=tmp_path / "nothing.json")
    assert "12.68" in str(caught.value), (
        "the refusal must say which step produces what is missing"
    )


def test_an_empty_feed_list_refuses(tmp_path):
    with pytest.raises(RefusedToOrchestrate):
        orchestrate(feeds_path=_write_feeds(tmp_path, []))


def test_feeds_without_usable_weights_refuse(tmp_path):
    """Feeds exist but nothing can be ranked. Returning an empty ranking here
    would read as 'nothing needs attention'."""
    feeds = [{"axis": "A", "weight": None, "status": "PRESENT"},
             {"axis": "B", "weight": "heavy", "status": "PRESENT"}]
    with pytest.raises(RefusedToOrchestrate) as caught:
        orchestrate(feeds_path=_write_feeds(tmp_path, feeds))
    assert "none carries a usable weight" in str(caught.value)


def test_real_feeds_do_not_refuse(tmp_path):
    """POSITIVE CONTROL — a gate that refuses everything is not a gate."""
    feeds = [_feed("A", 10.0), _feed("B", 5.0)]
    result = orchestrate(feeds_path=_write_feeds(tmp_path, feeds),
                         goal_score_path=_write_goal(tmp_path, {"A": 0.2}))
    assert result["axes_ranked"] == 2


# ---------------------------------------------------------------------------
# (b) need = weight x penalty
# ---------------------------------------------------------------------------

def test_need_is_weight_times_penalty():
    rows = rank([_feed("A", 10.0), _feed("B", 10.0)], {"A": 0.8185, "B": 0.2})
    by = {r["axis"]: r for r in rows}

    assert by["A"]["penalty"] == pytest.approx(1 - 0.8185)
    assert by["A"]["need"] == pytest.approx(10.0 * (1 - 0.8185))
    assert by["B"]["need"] == pytest.approx(10.0 * 0.8)
    assert by["B"]["rank"] < by["A"]["rank"], "the axis losing more must rank higher"


def test_an_unmeasured_axis_takes_maximum_penalty_not_zero():
    """Not knowing is not the same as being fine. Defaulting an unknown to a
    neutral score is how 8 axes came to sit at exactly 60.0."""
    rows = rank([_feed("UNKNOWN", 10.0, present=False)], {})
    assert rows[0]["penalty"] == 1.0
    assert rows[0]["need"] == 10.0
    assert rows[0]["score"] is None


def test_the_ranking_is_sorted_by_need_descending():
    rows = rank([_feed(a, w) for a, w in
                 [("A", 1.0), ("B", 9.0), ("C", 5.0)]], {})
    assert [r["axis"] for r in rows] == ["B", "C", "A"]
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_a_weightless_feed_is_not_ranked():
    rows = rank([_feed("A", 10.0), {"axis": "B", "status": "PRESENT"}], {})
    assert [r["axis"] for r in rows] == ["A"]


# ---------------------------------------------------------------------------
# (c) THREAT and OPPORTUNITY are disjoint by construction
# ---------------------------------------------------------------------------

def test_threat_and_opportunity_never_overlap():
    rows = rank([_feed("MEASURED_BAD", 10.0), _feed("MEASURED_GOOD", 10.0),
                 _feed("UNMEASURED", 10.0, present=False)],
                {"MEASURED_BAD": 0.1, "MEASURED_GOOD": 0.95})
    sets = classify(rows)

    assert set(sets[THREAT]) & set(sets[OPPORTUNITY]) == set()
    assert set(sets[THREAT]) & set(sets[WATCH]) == set()
    assert set(sets[OPPORTUNITY]) & set(sets[WATCH]) == set()
    assert "MEASURED_BAD" in sets[THREAT]
    assert "UNMEASURED" in sets[OPPORTUNITY], (
        "an axis with weight and no measurement is an opportunity: the loss is "
        "unknown and knowing it is cheap"
    )
    assert "MEASURED_GOOD" in sets[WATCH]


def test_an_unmeasured_axis_is_an_opportunity_not_a_threat():
    """It has maximum penalty, so a naive threshold would call it a THREAT and
    it would sit in both sets. The set difference is what prevents that."""
    rows = rank([_feed("U", 10.0, present=False)], {})
    sets = classify(rows)
    assert sets[THREAT] == []
    assert sets[OPPORTUNITY] == ["U"]


def test_every_axis_lands_in_exactly_one_bucket(tmp_path):
    feeds = [_feed(f"AX{i}", float(i + 1), present=(i % 2 == 0)) for i in range(8)]
    result = orchestrate(feeds_path=_write_feeds(tmp_path, feeds),
                         goal_score_path=_write_goal(tmp_path, {"AX0": 0.1, "AX2": 0.9}))
    total = sum(len(v) for v in result["sets"].values())
    assert total == result["axes_ranked"]


# ---------------------------------------------------------------------------
# (d) The action vocabulary is closed
# ---------------------------------------------------------------------------

def test_only_report_to_human_reaches_the_world():
    assert WORLD_ACTIONS == ("REPORT_TO_HUMAN",), (
        "a second world-facing action appeared. Every path outside this repo "
        "must collapse to one action a human wrote down."
    )
    assert set(INTERNAL_ACTIONS) & set(WORLD_ACTIONS) == set()


@pytest.mark.parametrize("bucket,expected", [
    (THREAT, "REPORT_TO_HUMAN"),
    (OPPORTUNITY, "WIRE_A_SOURCE"),
    (WATCH, "WATCH"),
])
def test_each_bucket_maps_to_one_fixed_action(bucket, expected):
    assert action_for({"need": 1.0}, bucket) == expected


def test_no_row_can_carry_an_action_outside_the_vocabulary(tmp_path):
    feeds = [_feed(f"AX{i}", float(i + 1), present=(i % 3 == 0)) for i in range(9)]
    result = orchestrate(feeds_path=_write_feeds(tmp_path, feeds),
                         goal_score_path=_write_goal(tmp_path, {"AX0": 0.05}))
    for r in result["ranking"]:
        assert r["action"] in ACTIONS, r
        if r["bucket"] != THREAT:
            assert r["action"] in INTERNAL_ACTIONS, (
                f"{r['axis']} is {r['bucket']} but its action reaches the world"
            )


# ---------------------------------------------------------------------------
# (e) The contract with step 12.7, and the live shape
# ---------------------------------------------------------------------------

def test_the_output_states_that_prose_may_not_reorder(tmp_path):
    """The rule has to travel with the file. Step 12.7 reads this, and a rule
    that lives only in a docstring is a rule the next reader will not see."""
    result = orchestrate(feeds_path=_write_feeds(tmp_path, [_feed("A", 1.0)]),
                         goal_score_path=_write_goal(tmp_path, {"A": 0.5}))
    note = result["_ranking_is_arithmetic"]
    assert "ANNOTATE" in note and "may NOT" in note
    assert result["_action_vocabulary"]["world"] == ["REPORT_TO_HUMAN"]


def test_it_writes_where_step_12_7_will_look(tmp_path):
    result = orchestrate(feeds_path=_write_feeds(tmp_path, [_feed("A", 1.0)]),
                         goal_score_path=_write_goal(tmp_path, {"A": 0.5}))
    path = pathlib.Path(write(result, tmp_path / "orchestration_grounded_latest.json"))
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["axes_ranked"] == 1


def test_the_live_repo_orchestrates_without_refusing():
    """Against the real feeds produced by step 12.68."""
    result = orchestrate()
    assert result["axes_ranked"] > 0
    assert result["buckets"][THREAT] + result["buckets"][OPPORTUNITY] \
        + result["buckets"][WATCH] == result["axes_ranked"]
    for r in result["ranking"]:
        assert r["action"] in ACTIONS
