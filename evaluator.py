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


def _get_current_value(axis_name):
    """Return the most recent value for axis_name from trends.json, or None."""
    with open(TRENDS_PATH, "r", encoding="utf-8") as f:
        trends = json.load(f)
    values = trends.get(axis_name)
    if not isinstance(values, list) or len(values) == 0:
        return None
    return values[-1]


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
        actual = _get_current_value(axis)

        if actual is None:
            print(f"[SKIP] {h['id']}: липсват текущи данни за '{axis}'")
            still_pending.append(h)
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

        print(f"\n{len(resolved_new)} хипотеза(и) → resolved.json")
    else:
        print("Няма дължими хипотези за оценка днес.")

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
