"""
The contract between the goal and the tree that measures it.

Three files have to agree, and until now nothing made them:

  civilization_goal.txt      the goal and its 5 subgoals   (human territory)
  config/target_config.json  the axes, grouped by subgoal   (the operationalization)
  agi_axes_spec.txt          LOW/MEDIUM/HIGH per axis       (what a score MEANS)

Before this test three axes (COGNITION_LEARNING_REVIEW, SOCIAL_RELATIONS_REVIEW,
GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL) carried weight and were scored in the live
system with no definition anywhere. A weight without a definition behind it is a
number nobody can falsify.

A desync now fails the build instead of surviving until somebody happens to look.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
CFG_FILE = BASE / "config" / "target_config.json"
GOAL_FILE = BASE / "civilization_goal.txt"
SPEC_FILE = BASE / "agi_axes_spec.txt"

# A deliberate act, not a moving target: adding or retiring an axis must be a
# visible edit to this number, reviewed like any other change to the goal.
#
# 25 -> 24 on 21 Aug 2026: GENERAL_SELF_REVIEW retired. Self-observation is a
# SENSE, not a state of the world, and an axis that scores the observer lets
# degraded sensors raise the composite by rating themselves higher. It now lives
# in core/self_mirror.py and feeds no number. Total weight 173 -> 167.
EXPECTED_AXIS_COUNT = 24

# Retiring an axis breaks the composite series by construction: the denominator
# changes. The break is DECLARED, never silent -- config/series_breaks.json holds
# the record and test_retired_axes_are_declared below refuses a retirement that
# was not written down.
RETIRED_AXES = {"GENERAL_SELF_REVIEW"}


def _cfg() -> dict:
    return json.loads(CFG_FILE.read_text(encoding="utf-8"))


def _branches(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if not str(k).startswith("_")}


def _axes(cfg: dict) -> dict:
    out = {}
    for axes in _branches(cfg).values():
        out.update(axes)
    return out


def _spec_axis_names() -> set:
    text = SPEC_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^AXIS_NAME:\s*(\S+)\s*$", text, flags=re.MULTILINE))


def _goal_subgoals() -> dict:
    """index -> verbatim heading, parsed from the numbered list in the goal file."""
    text = GOAL_FILE.read_text(encoding="utf-8")
    return {int(n): title.strip()
            for n, title in re.findall(r"^\s*(\d+)\.\s+(.+?)\s*$", text, flags=re.MULTILINE)}


# --------------------------------------------------------------------------- #
# (a) every axis that carries weight has a definition
# --------------------------------------------------------------------------- #

def test_every_axis_has_a_definition_in_the_spec():
    undefined = sorted(set(_axes(_cfg())) - _spec_axis_names())
    assert not undefined, (
        "these axes are weighted and scored in the live system but have no "
        f"LOW/MEDIUM/HIGH definition in {SPEC_FILE.name}: {undefined}. "
        "Either define them or remove them from the config -- but note that "
        "REMOVING an axis raises the composite, because the composite divides "
        "by measured weight only (goal_score_calculator: weighted_sum / measured_weight)."
    )


def test_spec_defines_no_axis_the_config_does_not_carry():
    orphans = sorted(_spec_axis_names() - set(_axes(_cfg())))
    assert not orphans, (
        f"{SPEC_FILE.name} defines axes absent from the config: {orphans}. "
        "A definition nothing measures is a promise nothing keeps."
    )


# --------------------------------------------------------------------------- #
# (b) the top level of the tree IS the goal's subgoal list
# --------------------------------------------------------------------------- #

def test_branch_count_matches_the_goal():
    cfg = _cfg()
    declared = cfg.get("_meta", {}).get("branches", {})
    subgoals = _goal_subgoals()
    assert len(_branches(cfg)) == len(subgoals) == len(declared), (
        f"tree has {len(_branches(cfg))} branches, _meta.branches declares "
        f"{len(declared)}, {GOAL_FILE.name} has {len(subgoals)} subgoals"
    )


def test_each_branch_maps_to_a_subgoal_by_verbatim_name():
    cfg = _cfg()
    declared = cfg["_meta"]["branches"]
    subgoals = _goal_subgoals()

    assert set(declared) == set(_branches(cfg)), (
        "_meta.branches and the actual top-level keys disagree: "
        f"{sorted(set(declared) ^ set(_branches(cfg)))}"
    )

    for branch, meta in declared.items():
        idx, name = meta["subgoal_index"], meta["subgoal_bg"]
        assert idx in subgoals, f"{branch} claims subgoal {idx}, which the goal file does not have"
        assert subgoals[idx] == name, (
            f"{branch} claims subgoal {idx} is '{name}', but {GOAL_FILE.name} says "
            f"'{subgoals[idx]}'. Rename one or the other -- do not let them drift."
        )

    indices = sorted(m["subgoal_index"] for m in declared.values())
    assert indices == sorted(subgoals), f"subgoals covered {indices}, goal file has {sorted(subgoals)}"


# --------------------------------------------------------------------------- #
# (c) no axis is silently lost or double-counted by regrouping
# --------------------------------------------------------------------------- #

def test_no_axis_is_lost_or_duplicated():
    cfg = _cfg()
    placed = [a for axes in _branches(cfg).values() for a in axes]
    assert len(placed) == len(set(placed)), (
        "an axis appears in more than one branch and would be counted twice: "
        f"{sorted({a for a in placed if placed.count(a) > 1})}"
    )
    assert len(placed) == EXPECTED_AXIS_COUNT, (
        f"expected {EXPECTED_AXIS_COUNT} axes, found {len(placed)}. If this change "
        "is intended, edit EXPECTED_AXIS_COUNT in this file in the same commit -- "
        "an axis must never disappear as a side effect of restructuring. "
        "(The first draft of the 5-branch table listed 24 of 25 and would have "
        "dropped TECHNOLOGY_INFRA_REVIEW, weight 5, in silence.)"
    )


def test_every_axis_carries_a_positive_weight():
    bad = {a: c.get("weight") for a, c in _axes(_cfg()).items()
           if not isinstance(c.get("weight"), (int, float)) or float(c["weight"]) <= 0}
    assert not bad, f"axes with missing or non-positive weight: {bad}"


def test_branches_contain_only_axes():
    """
    goal_score_calculator iterates `for axis_name, cfg in axes.items()` WITHOUT
    skipping underscore keys. Any metadata parked inside a branch would be read
    as an axis with primary_metric=None and default weight 1 -- silently
    inflating the denominator. Branch metadata belongs in _meta.branches.
    """
    for branch, axes in _branches(_cfg()).items():
        for key, cfg in axes.items():
            assert not key.startswith("_"), f"{branch}.{key} is metadata inside a branch"
            assert isinstance(cfg, dict) and "primary_metric" in cfg, (
                f"{branch}.{key} does not look like an axis block"
            )


# --------------------------------------------------------------------------- #
# (c2) the spec's own TOP_LEVEL_AXES block is not a fourth copy of the tree
# --------------------------------------------------------------------------- #

def _spec_top_level() -> dict:
    """branch -> [axes] as declared in the spec's TOP_LEVEL_AXES block."""
    text = SPEC_FILE.read_text(encoding="utf-8")
    out, branch, in_children = {}, None, False
    for raw in text.splitlines():
        m = re.match(r"^\s{2}-\s+([A-Z_]+):\s*$", raw)
        if m:
            branch, in_children = m.group(1), False
            out[branch] = []
            continue
        if re.match(r"^\s+CHILD_AXES:\s*$", raw):
            in_children = True
            continue
        if raw.startswith("#") or not raw.strip():
            if raw.startswith("#"):
                in_children = False
            continue
        c = re.match(r"^\s{8}-\s+(\S+)\s*$", raw)
        if c and in_children and branch:
            out[branch].append(c.group(1))
    return {b: a for b, a in out.items() if a}


def test_spec_top_level_matches_the_config_exactly():
    cfg = _cfg()
    from_cfg = {b: list(axes) for b, axes in _branches(cfg).items()}
    from_spec = _spec_top_level()
    assert from_spec == from_cfg, (
        "agi_axes_spec.txt's TOP_LEVEL_AXES and target_config.json disagree. "
        "This block is generated -- run scripts/regroup_axis_spec_to_subgoals.py. "
        f"config={from_cfg}\nspec={from_spec}"
    )


# --------------------------------------------------------------------------- #
# (d) regrouping must not move the composite
# --------------------------------------------------------------------------- #

def _composite(tree: dict, scores: dict) -> float:
    """The shape goal_score_calculator uses: sum(score*w) / sum(w of MEASURED)."""
    num = den = 0.0
    for key, axes in tree.items():
        if str(key).startswith("_"):
            continue
        for axis, cfg in axes.items():
            if axis not in scores:
                continue
            w = float(cfg.get("weight", 1))
            num += scores[axis] * w
            den += w
    return num / den if den else 0.0


FIXTURE = BASE / "test" / "fixtures" / "target_config_pre_subgoals.json"

LEGACY_DOMAINS = {"PLANET", "HUMAN", "CIVILIZATION", "COSMOS"}


def test_every_axis_kept_its_legacy_domain():
    """Without this, pre-migration axis_history / goal_score_history series
    stop being traceable to the tree that produced them."""
    lost = sorted(a for a, c in _axes(_cfg()).items()
                  if c.get("legacy_domain") not in LEGACY_DOMAINS)
    assert not lost, f"axes with missing or invalid legacy_domain: {lost}"


def test_regrouping_did_not_move_the_composite():
    """
    Compared against a COMMITTED pre-migration snapshot, not a transient .bak.

    An earlier version of this test used skipif(.bak missing) and therefore
    skipped on the live machine -- a guard that cannot fire is a ritual. A
    missing fixture now fails loudly instead of passing quietly.
    """
    if not FIXTURE.exists():
        pytest.fail(
            f"missing {FIXTURE.relative_to(BASE)} -- this guard cannot run without it.\n"
            "Recreate it from the authoritative pre-migration source:\n"
            "  git show <commit-before-migration>:config/target_config.json "
            "> test/fixtures/target_config_pre_subgoals.json"
        )

    old = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert {k for k in old if not k.startswith("_")} == LEGACY_DOMAINS, (
        "the fixture is not a pre-migration config -- it looks like a copy of the "
        "migrated tree, which would make this test compare a file to itself."
    )
    new = _cfg()

    # deterministic synthetic scores, one per axis, no randomness
    axes = sorted(_axes(new))
    scores = {a: (i % 10) / 10.0 for i, a in enumerate(axes)}

    assert _composite(old, scores) == pytest.approx(_composite(new, scores), abs=1e-12), (
        "the composite moved. Regrouping alone cannot do that -- a weight changed."
    )

    # and with a partially blind sensor set, which is the real-world case
    half = {a: s for a, s in scores.items() if hash(a) % 2 == 0}
    assert _composite(old, half) == pytest.approx(_composite(new, half), abs=1e-12)


# --------------------------------------------------------------------------- #
# (e) a retirement is declared, never silent -- rule 1.3
# --------------------------------------------------------------------------- #

BREAKS_FILE = BASE / "config" / "series_breaks.json"


def _breaks() -> list:
    return json.loads(BREAKS_FILE.read_text(encoding="utf-8"))["breaks"]


def test_retired_axes_are_declared_as_a_series_break():
    """Rule 1.3: if the weights move, the series are marked BROKEN, not silently
    continued. Removing an axis moves the denominator of the goal, so it MUST
    leave a record naming both fingerprints."""
    declared = " ".join(json.dumps(b, ensure_ascii=False) for b in _breaks())
    missing = sorted(a for a in RETIRED_AXES if a not in declared)
    assert not missing, (
        f"{missing} left the goal tree with no entry in "
        f"{BREAKS_FILE.relative_to(BASE)} -- rule 1.3 forbids a silent break.")


def test_every_break_names_the_fingerprint_on_both_sides():
    """A break whose record does not say what the fingerprint was before and
    after cannot be used to decide whether two points are comparable."""
    for b in _breaks():
        before = b.get("config_fingerprint_before")
        after = b.get("config_fingerprint_after")
        assert before and after, f"{b.get('id')}: missing a fingerprint"
        assert before != after, (
            f"{b.get('id')}: identical fingerprints -- nothing actually broke, or "
            "the record was copied without being updated.")


def test_the_declared_after_fingerprint_is_the_one_the_live_config_produces():
    """NEGATIVE CONTROL for the record itself. A break entry that names an
    'after' fingerprint no live config produces is a story, not evidence."""
    import goal_score_calculator as gsc

    live = gsc.config_fingerprint(_cfg())
    latest = _breaks()[-1]
    assert latest["config_fingerprint_after"] == live, (
        f"the newest break claims the tree now fingerprints as "
        f"{latest['config_fingerprint_after']}, but config/target_config.json "
        f"fingerprints as {live}. Either the tree changed again without a new "
        "break entry, or the entry was written by hand and never checked.")


def test_a_retired_axis_does_not_linger_in_the_spec():
    """The spec is what a score MEANS. A definition for an axis that no longer
    carries weight is the dead-weight failure CLAUDE.md exists to stop."""
    still_there = sorted(RETIRED_AXES & _spec_axis_names())
    assert not still_there, (
        f"{still_there} is retired from the tree but still defined in "
        "agi_axes_spec.txt")
