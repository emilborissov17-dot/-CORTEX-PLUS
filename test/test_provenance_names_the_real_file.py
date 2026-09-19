# -*- coding: utf-8 -*-
"""test/test_provenance_names_the_real_file.py — a provenance string must be followable.

THE DEFECT, measured 19 September 2026. goal_score_calculator reported
`observation_where: "last_observations"` for all sixteen axis_observations. That
is the name of a VARIABLE, not of a file:

    last_obs = {**load_last_obs(), **load_governance_globals(),
                **load_global_indicators(), **load_probed_signals()}

Four files merged, later wins, and every key that came out was labelled with the
same literal. A reader following it landed on data/last_observations.json, which
was written 2026-06-17, held eight bare scalars with no date in it anywhere, and
did not contain four of the sixteen keys at all.

That is a lie rather than a gap: the claim was checkable and failed its own
check. The repair is not "add a field" but "make the field name something a
reader can open", which is what these tests pin.

THE FIRST ATTEMPT AT THE REPAIR WAS ALSO UNFOLLOWABLE and this test is what
caught it. The loaders recorded the ADAPTED key (wb_SE.ADT.1524.LT.ZS) as the
field, and that key appears nowhere in the file — the payload holds
world_bank.literacy_rate_youth_pct. Sixteen of sixteen still failed. The field is
now the path INTO the file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import goal_score_calculator as g   # noqa: E402


def _dig(payload, dotted: str):
    """(found, value) for a dotted path into nested dicts."""
    cur = payload
    if not dotted:
        return False, None
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def test_no_loader_reports_the_variable_name_as_a_file():
    """"last_observations" is a dict, not a path. It must never be a `where`."""
    trends = {"co2_ppm": [1.0]}
    last_obs = {"wb_SH.DYN.MORT": 37.4}
    g._OBS_ORIGIN.clear()
    g._claim("wb_SH.DYN.MORT", "data/last_observations.json", "wb_SH.DYN.MORT")
    _v, origin = g._resolve_metric_origin("child_mortality_per_1000", trends, last_obs)
    assert origin["where"] != "last_observations"
    assert origin["where"] == "data/last_observations.json"


def test_a_key_no_loader_claimed_is_UNCLAIMED_not_a_plausible_filename():
    """The failure mode this replaces is inheriting a filename that looks right.

    An unclaimed key must say so loudly rather than borrow the last loader's
    path — a wrong-but-plausible file is harder to catch than an obvious gap.
    """
    g._OBS_ORIGIN.clear()
    _v, origin = g._resolve_metric_origin(
        "child_mortality_per_1000", {}, {"wb_SH.DYN.MORT": 37.4})
    assert origin["where"] == g.UNCLAIMED
    assert "UNCLAIMED" in origin["where"]


def test_the_last_writer_wins_exactly_as_the_value_does():
    """last_obs is a merge; provenance must follow the same precedence.

    If the snapshot overrides the stale file's value, it must also override its
    provenance, or the number comes from one file and the label from another.
    """
    g._OBS_ORIGIN.clear()
    g._claim("k", "data/last_observations.json", "k")
    g._claim("k", "snapshots/master/global_indicators_latest.json", "world_bank.k")
    files, fields = g.observation_origins()
    assert files["k"] == "snapshots/master/global_indicators_latest.json"
    assert fields["k"] == "world_bank.k"


def test_the_trends_branch_names_its_file_too():
    g._OBS_ORIGIN.clear()
    _v, origin = g._resolve_metric_origin("co2_ppm_mauna_loa", {"co2_ppm": [426.0]}, {})
    assert origin["where"].endswith("trends.json")
    assert origin["where_field"] == "co2_ppm[-1]"


@pytest.mark.live_state
def test_every_live_provenance_string_opens_and_contains_its_field():
    """THE ONE THAT MATTERS, against the real files.

    Marked live_state: it reads snapshots/ and output/, which the nightly cycle
    rewrites, so its outcome moves with the world rather than with the code and
    it belongs to tools/live_monitor.py rather than to the gate. The four
    deterministic tests above are the gating ones.

    A provenance string that names a file which does not contain the field is a
    FAILURE, not a warning. That is the whole content of this repair.
    """
    res = g.compute_goal_score()
    unfollowable = []
    for axis, o in sorted((res.get("axis_observations") or {}).items()):
        where = o.get("observation_where")
        field = o.get("observation_where_field")
        assert where, "%s reports no observation_where at all" % axis
        assert where != "last_observations", (
            "%s still reports the variable name as a file" % axis)
        path = REPO / where
        if not path.exists():
            unfollowable.append((axis, where, field, "file missing"))
            continue
        found, _value = _dig(json.loads(path.read_text(encoding="utf-8")), field or "")
        if not found:
            unfollowable.append((axis, where, field, "field not in file"))
    assert not unfollowable, (
        "%d provenance string(s) name a file that does not contain the field: %s"
        % (len(unfollowable), unfollowable))


@pytest.mark.live_state
def test_an_axis_with_no_date_says_why_rather_than_going_quiet():
    """A null date is a fact when it carries a reason; a bare null is the gap
    that hid five-year-old numbers behind a nightly timestamp."""
    res = g.compute_goal_score()
    for axis, o in (res.get("axis_observations") or {}).items():
        if o.get("observed_at") is None:
            assert o.get("observed_at_why"), (
                "%s has no observation date and no reason for it" % axis)
