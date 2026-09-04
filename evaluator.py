"""
CORTEX Hypothesis Evaluator
Checks due hypotheses against current trend data and moves them to resolved.json.
"""

import json
import os
import sys
import argparse
from datetime import date, datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TRENDS_PATH = os.path.join("cortex_memory", "abstractions", "trends.json")
PENDING_PATH = os.path.join("cortex_memory", "hypotheses", "pending.json")
RESOLVED_PATH = os.path.join("cortex_memory", "hypotheses", "resolved.json")


GOAL_SNAP_PATH = os.path.join("snapshots", "master", "goal_score_latest.json")


def _observed_from_scorer(axis_name):
    """The axis's own external reading from the scorer's snapshot, or None.

    ADDED 3 Sep 2026. trends.json carries seven series — co2_ppm, kp_index,
    earthquake_max, refugees, gbif_30d, goal_score, cycle_count — and five of them
    are EMPTY LISTS. It has never carried an axis under its REVIEW name. So a
    hypothesis about ENERGY_REVIEW could be pre-registered, come due, and be
    skipped forever for want of anything to grade it against: that is the state the
    two live hypotheses have been in since 17 and 20 July.

    snapshots/master/goal_score_latest.json DOES name a current external reading
    per axis (axis_observations), and it is the same block core/measurement_honesty
    already treats as the authority for whether an axis counts as measured. Reading
    it here means the generator and the grader agree on what the number IS.

    trends.json is still tried FIRST so nothing that resolves today changes.
    """
    try:
        with open(GOAL_SNAP_PATH, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:
        return None
    obs = (snap.get("axis_observations") or {}).get(axis_name)
    if isinstance(obs, dict):
        v = obs.get("observed_value")
        if isinstance(v, (int, float)):
            return float(v)
    return None


# THE THIRD LOOKUP (4 Sep 2026, Q0). trends.json names a series "co2_ppm"; the
# scorer names the same NOAA reading "co2_ppm_mauna_loa" — goal_score_calculator's
# own trend_map already maps one onto the other, in the opposite direction. Without
# the alias a hypothesis registered under the trends name can never be graded
# against the scorer, which is half of why the 20 July co2_ppm prediction sat
# unresolved for seven weeks with a live reading on disk the whole time.
_METRIC_ALIAS = {
    "co2_ppm": "co2_ppm_mauna_loa",
    "refugees": "refugee_population",
}


def _observed_from_metric_details(axis_name):
    """The reading under the scorer's METRIC name, or None.

    axis_observations is keyed by REVIEW axis; a hypothesis whose axis is a raw
    series name ("co2_ppm") never matches it. metric_details is keyed by metric,
    which is what such a hypothesis is actually about.
    """
    try:
        with open(GOAL_SNAP_PATH, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:
        return None
    details = snap.get("metric_details") or {}
    for key in (_METRIC_ALIAS.get(axis_name), axis_name):
        if not key:
            continue
        row = details.get(key)
        if isinstance(row, dict) and isinstance(row.get("current"), (int, float)):
            return float(row["current"])
    return None


def ground_truth(axis_name):
    """(value, trail) for axis_name. trail names every lookup tried and its outcome.

    Returning the trail is the point. Until now the failure to find a reading was
    reported as one word — SKIP — and a hypothesis could sit past due forever with
    nobody able to say WHICH lookup came up empty. A named reason is the difference
    between an unresolvable prediction and a forgotten one.
    """
    trail = []

    try:
        with open(TRENDS_PATH, "r", encoding="utf-8") as f:
            trends = json.load(f)
        values = trends.get(axis_name)
        if isinstance(values, list) and values:
            return values[-1], trail + [f"trends.json['{axis_name}'] -> {values[-1]}"]
        if isinstance(values, list):
            trail.append(f"trends.json['{axis_name}'] is an EMPTY series")
        else:
            trail.append(f"trends.json has no series '{axis_name}'")
    except Exception as exc:
        trail.append(f"trends.json unreadable ({exc.__class__.__name__})")

    v = _observed_from_scorer(axis_name)
    if v is not None:
        return v, trail + [f"axis_observations['{axis_name}'] -> {v}"]
    trail.append(f"axis_observations has no axis '{axis_name}'")

    v = _observed_from_metric_details(axis_name)
    if v is not None:
        alias = _METRIC_ALIAS.get(axis_name)
        via = f"'{alias}' (alias of '{axis_name}')" if alias else f"'{axis_name}'"
        return v, trail + [f"metric_details[{via}] -> {v}"]
    trail.append(f"metric_details has no metric '{axis_name}'"
                 + (f" nor its alias '{_METRIC_ALIAS[axis_name]}'"
                    if axis_name in _METRIC_ALIAS else ""))

    return None, trail


def _get_current_value(axis_name):
    """Most recent value for axis_name. Kept for callers that want a bare float."""
    return ground_truth(axis_name)[0]


def _accuracy(predicted, actual):
    """
    accuracy = 1 - |predicted - actual| / |actual|, clipped to [0, 1].
    Returns (accuracy, error_pct).
    """
    if actual == 0:
        if abs(predicted) < 1e-9:
            return 1.0, 0.0
        return 0.0, None
    error_ratio = abs(predicted - actual) / abs(actual)
    acc = round(max(0.0, 1.0 - error_ratio), 4)
    err_pct = round(error_ratio * 100, 2)
    return acc, err_pct


def check_due_hypotheses():
    """
    Evaluate all hypotheses whose prediction_date <= today.
    Compares predicted_value against current value in trends.json.
    Moves resolved records to resolved.json and removes them from pending.json.

    Returns list of newly resolved records.
    """
    if not os.path.exists(PENDING_PATH):
        print("Няма pending.json — все още няма хипотези.")
        return []

    with open(PENDING_PATH, "r", encoding="utf-8") as f:
        pending = json.load(f)

    if not pending:
        print("pending.json е празен.")
        return []

    today = date.today()
    still_pending = []
    resolved_new = []

    for h in pending:
        pred_date = date.fromisoformat(h["prediction_date"])

        if pred_date > today:
            still_pending.append(h)
            continue

        axis = h["axis"]
        actual, trail = ground_truth(axis)

        if actual is None:
            # PAST DUE AND UNGRADEABLE IS A VERDICT, NOT A SKIP (4 Sep 2026, Q0).
            # This branch used to append to still_pending unconditionally. A
            # hypothesis whose axis has no reading anywhere therefore returned to
            # pending every night forever, while the step above it printed a clean
            # report: the 17 July kp_index and 20 July co2_ppm predictions sat here
            # for seven weeks and the cycle called that success. A prediction that
            # cannot be graded is a failure of the registration, and it has to leave
            # pending carrying the reason it could not be graded.
            reason = "; ".join(trail)
            record = {
                **h,
                "status": "unresolvable",
                "actual_value": None,
                "accuracy": None,
                "error_pct": None,
                "unresolvable_reason": reason,
                "days_overdue": (today - pred_date).days,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
            resolved_new.append(record)
            print(f"[UNRESOLVABLE] {h['id']} ({(today - pred_date).days}d overdue): "
                  f"no ground truth for '{axis}' — {reason}")
            continue

        predicted = h["predicted_value"]
        acc, err_pct = _accuracy(predicted, actual)

        verdict = (
            "ТОЧНА      " if acc >= 0.90
            else ("ПРИЕМЛИВА  " if acc >= 0.70
                  else "НЕТОЧНА    ")
        )

        resolved_record = {
            **h,
            "status": "resolved",
            "actual_value": actual,
            "accuracy": acc,
            "error_pct": err_pct,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        resolved_new.append(resolved_record)

        print(
            f"[{verdict}] {h['id']}\n"
            f"           прогноза={predicted:.4g}  реална={actual:.4g}  "
            f"точност={acc:.1%}  грешка={err_pct}%"
        )

    # Write surviving pending hypotheses
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(still_pending, f, indent=2, ensure_ascii=False)

    # Append newly resolved to resolved.json
    if resolved_new:
        resolved_all = []
        if os.path.exists(RESOLVED_PATH):
            with open(RESOLVED_PATH, "r", encoding="utf-8") as f:
                resolved_all = json.load(f)
        resolved_all.extend(resolved_new)
        with open(RESOLVED_PATH, "w", encoding="utf-8") as f:
            json.dump(resolved_all, f, indent=2, ensure_ascii=False)

        n_graded = sum(1 for r in resolved_new if r.get("status") == "resolved")
        n_unres  = sum(1 for r in resolved_new if r.get("status") == "unresolvable")
        # THE TWO NUMBERS ARE REPORTED SEPARATELY, ALWAYS. Folding an ungradeable
        # prediction into the resolved count is how "0 due" stayed true while two
        # predictions rotted for seven weeks.
        print("")
        print(f"{len(resolved_new)} хипотеза(и) → resolved.json "
              f"({n_graded} graded, {n_unres} UNRESOLVABLE)")
    else:
        print("Няма дължими хипотези за оценка днес.")

    overdue_left = [h for h in still_pending
                    if date.fromisoformat(h["prediction_date"]) < today]
    if overdue_left:
        # Nothing may reach this line: a past-due hypothesis either graded or was
        # marked unresolvable above. If one is here the contract broke, and it says
        # so loudly instead of waiting another seven weeks to be noticed.
        print(f"[CONTRACT VIOLATION] {len(overdue_left)} past-due hypothesis(es) "
              f"remain pending: {[h['id'] for h in overdue_left]}")

    still_count = len(still_pending)
    if still_count:
        next_due = min(h["prediction_date"] for h in still_pending)
        print(f"{still_count} хипотеза(и) остават pending (следваща: {next_due})")

    return resolved_new


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CORTEX Hypothesis Evaluator — checks due predictions"
    )
    parser.add_argument("--check", action="store_true",
                        help="Evaluate all due hypotheses")
    parser.add_argument("--show-pending", action="store_true",
                        help="Print current pending hypotheses")
    parser.add_argument("--show-resolved", action="store_true",
                        help="Print resolved hypotheses")
    args = parser.parse_args()

    if args.show_pending:
        if os.path.exists(PENDING_PATH):
            with open(PENDING_PATH, "r", encoding="utf-8") as f:
                print(json.dumps(json.load(f), indent=2, ensure_ascii=False))
        else:
            print("Няма pending.json")

    if args.show_resolved:
        if os.path.exists(RESOLVED_PATH):
            with open(RESOLVED_PATH, "r", encoding="utf-8") as f:
                print(json.dumps(json.load(f), indent=2, ensure_ascii=False))
        else:
            print("Няма resolved.json")

    if args.check:
        results = check_due_hypotheses()
        if results:
            print(json.dumps(results, indent=2, ensure_ascii=False))

    if not any(vars(args).values()):
        parser.print_help()
