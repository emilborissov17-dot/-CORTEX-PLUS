"""
Migrate config/target_config.json from the 4 ontological domains
(PLANET / HUMAN / CIVILIZATION / COSMOS) to the 5 functional subgoals
declared in civilization_goal.txt.

WHY
---
The 4 domains are a SENSOR-SIDE taxonomy: they say where a measurement comes
from (planet, people, civilization, cosmos). That taxonomy still lives in
config/domains_tree.json and config/review_domains_map.json and is NOT touched
by this migration.

The top level of target_config.json is something else: it is the
operationalization of the GOAL. Per TRUE_GOAL_CANON the 25 axes ARE the
operationalization, so the top level should map 1:1 onto the goal's own
subgoals. After this migration the composite is readable per subgoal.

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It does NOT change a single per-axis weight. Regrouping is composite-neutral
(goal_score_calculator iterates axes generically; the domain key is only a
container). Reweighting is NOT neutral -- it moves the composite for reasons
that have nothing to do with the world, and it breaks comparability of
axis_history.json / goal_score_history.json. That decision is human and is
reported here as numbers, not applied.

INVARIANTS (asserted, not assumed)
----------------------------------
  * every axis of the old tree appears exactly once in the new tree
  * no axis is invented
  * axis count and total weight are identical before/after
  * every per-axis config block is byte-identical apart from added legacy_domain
  * branch dicts contain ONLY axes (consumers iterate axes.items() without
    skipping underscore keys -- branch metadata lives in _meta.branches)

Usage:
    python scripts/migrate_axis_tree_to_subgoals.py            # dry run, report only
    python scripts/migrate_axis_tree_to_subgoals.py --write    # rewrite the config
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from collections import OrderedDict

BASE = pathlib.Path(__file__).resolve().parents[1]
CFG = BASE / "config" / "target_config.json"
GOAL = BASE / "civilization_goal.txt"

# Branch key -> (subgoal number in civilization_goal.txt, verbatim heading, axes)
# The verbatim heading is what the CI guard matches against the goal file, so a
# rename of a subgoal in the goal file fails the build instead of drifting.
BRANCHES: "OrderedDict[str, dict]" = OrderedDict([
    ("SUSTAINABLE_RESOURCES", {
        "subgoal_index": 1,
        "subgoal_bg": "Устойчиви ресурси",
        "axes": [
            "ENERGY_REVIEW",
            "WATER_REVIEW",
            "FOOD_REVIEW",
            "MATERIALS_WASTE_REVIEW",
            "COSMIC_RESOURCES_REVIEW",
        ],
    }),
    ("HEALTHY_ENVIRONMENTS", {
        "subgoal_index": 2,
        "subgoal_bg": "Здрави среди на съществуване",
        "axes": [
            "CLIMATE_GLOBAL_RISK_REVIEW",
            "ECOSYSTEMS_BIODIVERSITY_REVIEW",
            "PLANETARY_POTENTIAL_REVIEW",
        ],
    }),
    ("CIVILIZATIONAL_STABILITY", {
        "subgoal_index": 3,
        "subgoal_bg": "Устойчива цивилизация",
        "axes": [
            "ECONOMY_WORK_REVIEW",
            "INEQUALITY_POVERTY_REVIEW",
            "INFRASTRUCTURE_CITIES_REVIEW",
            "GOVERNANCE_INSTITUTIONS_REVIEW",
            "HUMAN_WELL_BEING_REVIEW",
            "SOCIAL_RELATIONS_REVIEW",
            "CULTURE_MEDIA_REVIEW",
            "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL",
            # NOT in the original proposal -- it listed 24 of 25 axes and
            # TECHNOLOGY_INFRA_REVIEW (weight 5) would have been silently
            # dropped. Placed here next to INFRASTRUCTURE_CITIES_REVIEW.
            # PENDING HUMAN RATIFICATION.
            "TECHNOLOGY_INFRA_REVIEW",
        ],
    }),
    ("KNOWLEDGE_UNDERSTANDING", {
        "subgoal_index": 4,
        "subgoal_bg": "Знание и разбиране",
        "axes": [
            "EDUCATION_CULTURE_REVIEW",
            "COGNITION_LEARNING_REVIEW",
            "GENERAL_SELF_REVIEW",
        ],
    }),
    ("SAFETY", {
        "subgoal_index": 5,
        "subgoal_bg": "Безопасност",
        "axes": [
            "TECHNOLOGY_AI_REVIEW",
            "DEEP_TIME_RISKS_REVIEW",
            "GOAL_PROGRESS_REVIEW",
            "LONG_TERM_FUTURE_REVIEW",
            # Space expansion is framed in the vision as insurance against
            # extinction, i.e. risk management -- not a separate sphere.
            "SPACE_INFRASTRUCTURE_REVIEW",
        ],
    }),
])


def load_old(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def flatten(old: dict) -> "OrderedDict[str, tuple]":
    """axis_name -> (legacy_domain, cfg). Fails loudly on duplicate axis names."""
    flat: "OrderedDict[str, tuple]" = OrderedDict()
    for domain, axes in old.items():
        if str(domain).startswith("_"):
            continue
        for axis, cfg in axes.items():
            if axis in flat:
                raise SystemExit(f"FATAL: axis {axis} declared twice in the old tree")
            flat[axis] = (domain, cfg)
    return flat


def build_new(old: dict, flat: "OrderedDict[str, tuple]") -> dict:
    planned = [a for b in BRANCHES.values() for a in b["axes"]]

    missing = [a for a in flat if a not in planned]
    invented = [a for a in planned if a not in flat]
    dupes = [a for a in set(planned) if planned.count(a) > 1]
    if missing:
        raise SystemExit(f"FATAL: axes present in the config but not placed: {missing}")
    if invented:
        raise SystemExit(f"FATAL: axes placed but not present in the config: {invented}")
    if dupes:
        raise SystemExit(f"FATAL: axes placed in more than one branch: {dupes}")

    new: "OrderedDict[str, object]" = OrderedDict()

    meta = dict(old.get("_meta", {}))
    meta["description"] = (
        "Scientific targets and weights for all 25 CORTEX++ review axes, "
        "grouped by the 5 subgoals of civilization_goal.txt"
    )
    meta["structure_ref"] = "civilization_goal.txt"
    meta["structure_rule"] = (
        "The top level of this file IS the goal's subgoal list. Renaming, adding "
        "or removing a branch here without the same change in civilization_goal.txt "
        "fails test/test_axis_tree_contract.py."
    )
    meta["migrated_from"] = "4 domains (PLANET/HUMAN/CIVILIZATION/COSMOS)"
    meta["migration_note"] = (
        "Regrouping only. No per-axis weight was changed, so the composite is "
        "unchanged by construction (goal_score_calculator sums over axes, not "
        "domains). The sensor-side domain taxonomy stays in config/domains_tree.json; "
        "each axis keeps legacy_domain so pre-migration series remain traceable."
    )
    meta["branches"] = OrderedDict(
        (key, {"subgoal_index": b["subgoal_index"], "subgoal_bg": b["subgoal_bg"]})
        for key, b in BRANCHES.items()
    )
    new["_meta"] = meta

    for key, b in BRANCHES.items():
        branch: "OrderedDict[str, dict]" = OrderedDict()
        for axis in b["axes"]:
            legacy_domain, cfg = flat[axis]
            merged = OrderedDict(cfg)
            # Idempotent: on a re-run the source tree is already the new one, so
            # legacy_domain must keep the ORIGINAL 4-domain value, not be
            # overwritten with the branch it now lives in.
            merged["legacy_domain"] = cfg.get("legacy_domain", legacy_domain)
            branch[axis] = merged
        new[key] = branch

    return new


def report(old: dict, new: dict) -> None:
    def totals(tree):
        out = OrderedDict()
        for k, axes in tree.items():
            if str(k).startswith("_"):
                continue
            out[k] = sum(float(c.get("weight", 1)) for c in axes.values())
        return out

    o, n = totals(old), totals(new)
    o_axes = sum(len(a) for k, a in old.items() if not str(k).startswith("_"))
    n_axes = sum(len(a) for k, a in new.items() if not str(k).startswith("_"))

    print("BEFORE (4 domains)")
    for k, v in o.items():
        print(f"  {k:<26} {v:>6.1f}")
    print(f"  {'TOTAL':<26} {sum(o.values()):>6.1f}   axes={o_axes}")

    print("\nAFTER (5 subgoals)")
    grand = sum(n.values())
    for k, v in n.items():
        print(f"  {k:<26} {v:>6.1f}   {v / grand:>5.1%} of the goal")
    print(f"  {'TOTAL':<26} {grand:>6.1f}   axes={n_axes}")

    assert o_axes == n_axes == 25, f"axis count changed: {o_axes} -> {n_axes}"
    assert abs(sum(o.values()) - grand) < 1e-9, "total weight changed"
    print("\nINVARIANTS OK: 25 axes, total weight unchanged, no axis lost or invented.")

    print("\nWEIGHT PRINCIPLES CHECK (informational -- this script changes nothing):")
    print("  _meta.weight_principles says 'Climate/CO2 and basic needs highest'.")
    print(f"  HEALTHY_ENVIRONMENTS (holds CLIMATE) = {n['HEALTHY_ENVIRONMENTS']:.0f}"
          f" ({n['HEALTHY_ENVIRONMENTS'] / grand:.1%})")
    print(f"  CIVILIZATIONAL_STABILITY            = {n['CIVILIZATIONAL_STABILITY']:.0f}"
          f" ({n['CIVILIZATIONAL_STABILITY'] / grand:.1%})")
    print("  -> Under the goal's own structure the current per-axis weights make")
    print("     stability the dominant branch and environments a small one.")
    print("     Whether that still reflects the principle is a HUMAN decision.")
    print("     Not applied here: reweighting moves the composite and breaks")
    print("     comparability of axis_history / goal_score_history.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="rewrite config/target_config.json (a .bak copy is kept)")
    args = ap.parse_args()

    old = load_old(CFG)
    flat = flatten(old)
    new = build_new(old, flat)
    report(old, new)

    # per-axis blocks must be identical apart from the added legacy_domain
    for branch, axes in new.items():
        if str(branch).startswith("_"):
            continue
        for axis, cfg in axes.items():
            before = {k: v for k, v in flat[axis][1].items() if k != "legacy_domain"}
            after = {k: v for k, v in cfg.items() if k != "legacy_domain"}
            assert before == after, f"axis block mutated: {axis}"

    if args.write:
        shutil.copy2(CFG, CFG.with_suffix(".json.bak"))
        CFG.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"\nWRITTEN: {CFG}   (backup: {CFG.with_suffix('.json.bak')})")
    else:
        print("\nDRY RUN. Nothing written. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
