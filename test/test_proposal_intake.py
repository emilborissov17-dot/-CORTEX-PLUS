"""core/proposal_intake — born gradeable or not born.

Each test names the defect it would catch if removed:
  * legacy proposals (measurable_goal = solution[:80]) must be REFUSED, with every
    missing field named — otherwise the 786 "Action required for PLANET" rows come back;
  * an indicator that does not resolve through the grader is not an indicator;
  * expected_delta 0 / non-numeric / deadline in the past or a year+ out are refused;
  * a complete proposal is ADMITTED;
  * every refusal lands in the log with its source, one line each;
  * fast_cycle_runner writes the queue through _inject_proposals ONLY — no injector
    may write memory/improvement_proposals.json directly again.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from core import proposal_intake as pi


# A permissive cadence check for the tests that use SYNTHETIC axes.
# Added 6 Sep 2026 with the cadence gate. These tests exercise FIELD VALIDATION
# on made-up indicators; they make no claim about when the World Bank publishes,
# so they inject a cadence check exactly as they already inject a resolver. The
# cadence gate itself is tested against the real declaration in
# test/test_cadence_gate.py.
def _any_cadence(indicator, deadline):
    return None



REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 5)


def _resolves(axis, metric):
    table = {("PLANET", None): 0.61, ("CLIMATE_GLOBAL_RISK_REVIEW", "co2_annual_increase"): 2.4}
    v = table.get((axis, metric))
    return (v, None) if v is not None else (None, f"no reading for {axis}/{metric}")


LEGACY = {"component": "PLANET", "problem": "Action required for PLANET",
          "solution": "Build membrane filters for microplastics",
          "measurable_goal": "Build membrane filters for microplastics",
          "generated_by": "HYPERCLAW"}

GOOD = {**LEGACY, "indicator": "PLANET", "expected_delta": 0.02,
        "deadline": (TODAY + timedelta(days=90)).isoformat()}


def test_legacy_shape_is_refused_with_every_missing_field_named():
    v = pi.judge(LEGACY, today=TODAY, resolver=_resolves, cadence_check=_any_cadence)
    assert v["verdict"] == "REFUSED"
    assert set(v["missing"]) == {"indicator", "expected_delta", "deadline"}
    assert "measurable_goal" not in v["why"]  # the old field buys nothing


def test_complete_proposal_is_admitted():
    v = pi.judge(GOOD, today=TODAY, resolver=_resolves, cadence_check=_any_cadence)
    # scale_check joined the verdict on 6 Sep (3b): an admitted proposal now says
    # whether its delta was checked against the indicator's own range, or was
    # admitted with the scale still unknown. The three original fields are
    # asserted individually rather than by exact dict equality, so a later
    # honest addition does not read as a regression.
    assert v["verdict"] == "ADMITTED"
    assert v["missing"] == []
    assert v["why"] is None
    assert "scale_check" in v


def test_metric_indicator_admitted_and_unresolvable_refused():
    ok = {**GOOD, "indicator": "CLIMATE_GLOBAL_RISK_REVIEW__co2_annual_increase"}
    assert pi.judge(ok, today=TODAY, resolver=_resolves, cadence_check=_any_cadence)["verdict"] == "ADMITTED"
    bad = {**GOOD, "indicator": "CLIMATE_GLOBAL_RISK_REVIEW__no_such_metric"}
    v = pi.judge(bad, today=TODAY, resolver=_resolves, cadence_check=_any_cadence)
    assert v["verdict"] == "REFUSED" and v["missing"] == ["indicator"]
    assert "does not resolve" in v["why"]


@pytest.mark.parametrize("field,value", [
    ("indicator", "planet"),          # lower-case is not an axis name
    ("indicator", "PLANET metric"),   # spaces
    ("expected_delta", 0),
    ("expected_delta", "big"),
    ("expected_delta", True),
    ("deadline", TODAY.isoformat()),                              # today is not after today
    ("deadline", (TODAY - timedelta(days=1)).isoformat()),
    ("deadline", (TODAY + timedelta(days=366)).isoformat()),
    ("deadline", "4052-10"),                                      # the real one from the corpus
    ("deadline", "by Q3"),
])
def test_each_bad_field_is_refused_by_name(field, value):
    v = pi.judge({**GOOD, field: value}, today=TODAY, resolver=_resolves, cadence_check=_any_cadence)
    assert v["verdict"] == "REFUSED"
    assert v["missing"] == [field]


def test_admit_splits_and_logs_every_refusal(tmp_path):
    log = tmp_path / "refusals.jsonl"
    adm, ref = pi.admit([GOOD, LEGACY, {**GOOD, "expected_delta": 0}], "hyperclaw_to_proposals",
                        today=TODAY, resolver=_resolves, cadence_check=_any_cadence, refusals_path=log)
    assert adm == [GOOD]
    assert len(ref) == 2
    lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert all(l["source"] == "hyperclaw_to_proposals" for l in lines)
    assert lines[0]["missing"] == ["indicator", "expected_delta", "deadline"]
    assert lines[1]["missing"] == ["expected_delta"]


def test_admit_never_raises_on_garbage(tmp_path):
    adm, ref = pi.admit([None, "text", 42, {}], "x", today=TODAY, resolver=_resolves, cadence_check=_any_cadence,
                        refusals_path=tmp_path / "r.jsonl")
    assert adm == [] and len(ref) == 4


def test_summary_line_counts_missing_fields():
    _, ref = pi.admit([LEGACY, LEGACY], "hyperclaw_to_proposals", today=TODAY,
                      resolver=_resolves, cadence_check=_any_cadence, write=False)
    line = pi.summary_line("hyperclaw_to_proposals", [], ref)
    assert "0 admitted, 2 REFUSED" in line
    assert "indicator:2" in line and "deadline:2" in line


def test_runner_writes_the_queue_only_through_inject_proposals():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8", errors="ignore")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    # exactly one writer of the queue file, inside _inject_proposals
    writers = [m.start() for m in re.finditer(r"proposals_path\.write_text\(", code)]
    assert len(writers) == 1, f"{len(writers)} direct writers of improvement_proposals.json"
    helper = code.find("def _inject_proposals(")
    nxt = code.find("\ndef ", helper + 1)
    assert helper != -1 and helper < writers[0] < nxt, "the one writer is not inside _inject_proposals"
    for injector in ("strategist_to_proposals", "growth_to_proposals", "hyperclaw_to_proposals"):
        assert f'_inject_proposals(new_proposals, ' in code
        assert f'"{injector}")' in code, f"{injector} does not go through the door"