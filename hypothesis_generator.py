"""
CORTEX Hypothesis Generator
Reads trend data from trends.json and produces forward-looking predictions.

Model selection:
  - Bounded metrics (defined in AXIS_BOUNDS): logistic/sigmoid fit via
    logit-space linear regression. By construction, predictions stay inside
    [lower, upper]. The suppressed linear value is recorded transparently.
  - Unbounded metrics: standard linear regression.
"""

import json
import math
import os
import sys
import argparse
from datetime import datetime, timedelta, timezone, date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from citation_verifier import verify_hypothesis

try:
    from core.groq_backend import call_groq as _call_groq_causal
except Exception:
    _call_groq_causal = None

TRENDS_PATH        = os.path.join("cortex_memory", "abstractions", "trends.json")
PENDING_PATH       = os.path.join("cortex_memory", "hypotheses", "pending.json")
REJECTED_PATH      = os.path.join("cortex_memory", "hypotheses", "rejected.json")
CAUSAL_PENDING_PATH = os.path.join("cortex_memory", "hypotheses", "causal_pending.json")

AXIS_UNITS = {
    "co2_ppm": "ppm",
    "kp_index": "",
    "earthquake_max": "Mw",
    "refugees": "души",
    "gbif_30d": "записа",
    "goal_score": "",
}

# Metrics with hard physical/logical bounds → use logistic model.
# Format: axis_name -> (lower, upper)
AXIS_BOUNDS = {
    "goal_score": (0.0, 1.0),   # normalized composite score
    "kp_index":   (0.0, 9.0),   # geomagnetic K-index
}


# ---------------------------------------------------------------------------
# Regression helpers
# ---------------------------------------------------------------------------

def _linear_regression(xs, ys):
    """Pure-Python OLS. Returns (slope, intercept, r_squared)."""
    n = len(xs)
    if n < 2:
        return 0.0, float(ys[0]) if ys else 0.0, 0.0

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)

    denom = n * sum_xx - sum_x ** 2
    if denom == 0:
        return 0.0, sum_y / n, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot < 1e-30:
        r_squared = 1.0
    else:
        y_pred = [slope * x + intercept for x in xs]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred))
        r_squared = max(0.0, 1.0 - ss_res / ss_tot)

    return slope, intercept, r_squared


def _logistic_regression(xs, ys, lower, upper):
    """
    Fits a logistic curve bounded in [lower, upper] using logit-space OLS.

    Strategy:
      1. Normalize ys to (0,1): z = (y - lower) / (upper - lower)
      2. Clip to [eps, 1-eps] to avoid logit singularity
      3. Apply logit: L = log(z / (1-z))  → linear in x
      4. Fit L ~ k*x + b  via linear regression
      5. Predict: y_pred = lower + span / (1 + exp(-(k*x + b)))

    Returns (k, b, r_squared_logit, r_squared_orig, clipped_any).
    clipped_any is True when at least one normalized value was at the boundary
    (indicates the data is near saturation — reduces reliability).
    """
    _LOGIT_EPS = 1e-4
    span = upper - lower
    if span <= 0:
        raise ValueError(f"Invalid bounds: lower={lower} >= upper={upper}")

    zs_raw = [(y - lower) / span for y in ys]
    clipped_any = any(z <= 0 or z >= 1 for z in zs_raw)
    zs = [max(_LOGIT_EPS, min(1.0 - _LOGIT_EPS, z)) for z in zs_raw]

    ls = [math.log(z / (1.0 - z)) for z in zs]

    k, b, r_sq_logit = _linear_regression(xs, ls)

    # R² in original (y) space
    n = len(xs)
    y_pred_fit = [lower + span / (1.0 + math.exp(-(k * x + b))) for x in xs]
    y_mean = sum(ys) / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot < 1e-30:
        r_sq_orig = 1.0
    else:
        ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred_fit))
        r_sq_orig = max(0.0, 1.0 - ss_res / ss_tot)

    return k, b, r_sq_logit, r_sq_orig, clipped_any


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_hypothesis(axis_name, horizon_days=30, past_offset_days=None):
    """
    Generate a prediction for `axis_name` by extrapolating its trend.

    For bounded axes (AXIS_BOUNDS), uses logistic/sigmoid model so the
    prediction is always inside the valid range.  The raw linear projection
    is recorded in the output for transparency.

    Args:
        axis_name:        Key in trends.json (e.g. "co2_ppm", "goal_score")
        horizon_days:     Days ahead to project (default 30)
        past_offset_days: If set, forces prediction_date that many days in the
                          past — used to trigger the evaluator immediately in tests

    Returns the hypothesis record (also appended to pending.json).
    """
    with open(TRENDS_PATH, "r", encoding="utf-8") as f:
        trends = json.load(f)

    available = [k for k in trends if k != "cycle_count"]
    if axis_name not in trends:
        raise ValueError(
            f"Axis '{axis_name}' not found in trends. Available: {available}"
        )

    values = trends[axis_name]
    if not isinstance(values, list) or len(values) == 0:
        raise ValueError(f"No list data for axis '{axis_name}'")

    n = len(values)
    xs = list(range(n))
    future_step = (n - 1) + horizon_days

    # Data-volume confidence penalty (same for all models)
    data_penalty = min(1.0, max(0.0, (n - 1) / 5.0))

    bounds = AXIS_BOUNDS.get(axis_name)

    # --- Linear projection (always computed for reference) ---
    slope_lin, intercept_lin, r_sq_lin = _linear_regression(xs, values)
    linear_pred = slope_lin * future_step + intercept_lin

    if bounds is not None:
        lower, upper = bounds

        # --- Logistic model for bounded axes ---
        try:
            k, b, r_sq_logit, r_sq_orig, clipped_any = _logistic_regression(
                xs, values, lower, upper
            )
            predicted_value = lower + (upper - lower) / (
                1.0 + math.exp(-(k * future_step + b))
            )
            model_type = "logistic"
            r_squared = r_sq_orig

            # Extra confidence penalty when data is near the boundary
            # (logit is poorly constrained at extremes with few points)
            saturation_penalty = 0.8 if clipped_any else 1.0

            # Also penalise if the logit-space fit is weak
            logit_quality = max(0.0, r_sq_logit)
            confidence = round(
                logit_quality * data_penalty * saturation_penalty, 3
            )

        except Exception as exc:
            # Fallback to linear + clip if logistic fitting fails
            predicted_value = max(lower, min(upper, linear_pred))
            model_type = "linear+clip(fallback)"
            r_squared = r_sq_lin
            confidence = round(r_sq_lin * data_penalty * 0.5, 3)  # heavy penalty

        # Build the transparency note about the suppressed linear value
        linear_out_of_bounds = linear_pred < lower or linear_pred > upper
        if linear_out_of_bounds:
            bounds_note = (
                f" [BOUNDED {lower}–{upper} | ЛОГИСТИЧЕН МОДЕЛ"
                f" | линейна проекция={linear_pred:.4g} → извън допустимите граници]"
            )
        else:
            bounds_note = (
                f" [BOUNDED {lower}–{upper} | ЛОГИСТИЧЕН МОДЕЛ"
                f" | линейна проекция={linear_pred:.4g}]"
            )

    else:
        # --- Standard linear model ---
        predicted_value = linear_pred
        model_type = "linear"
        r_squared = r_sq_lin
        confidence = round(r_sq_lin * data_penalty, 3)
        bounds_note = ""
        lower, upper = None, None

    # --- Build human-readable hypothesis text ---
    now = datetime.now(timezone.utc)
    if past_offset_days is not None:
        prediction_date = (now - timedelta(days=past_offset_days)).date()
    else:
        prediction_date = (now + timedelta(days=horizon_days)).date()

    unit = AXIS_UNITS.get(axis_name, "")
    unit_str = f" {unit}" if unit else ""

    slope_ref = slope_lin  # use linear slope for direction label
    direction = (
        "остане стабилен на" if abs(slope_ref) < 1e-9
        else ("нарасне до" if slope_ref > 0 else "спадне до")
    )
    hypothesis_text = (
        f"Ако текущият темп продължи, {axis_name} ще {direction} "
        f"{predicted_value:.4g}{unit_str} до {prediction_date.isoformat()}"
        f"{bounds_note}"
    )

    record = {
        "id": f"{axis_name}_{now.strftime('%Y%m%d_%H%M%S')}",
        "axis": axis_name,
        "hypothesis_text": hypothesis_text,
        "predicted_value": round(predicted_value, 6),
        "prediction_date": prediction_date.isoformat(),
        "horizon_days": horizon_days,
        "model_type": model_type,
        "bounds": [lower, upper] if bounds is not None else None,
        "linear_projection": round(linear_pred, 6),
        "slope_per_cycle": round(slope_lin, 8),
        "n_points": n,
        "r_squared": round(r_squared, 4),
        "confidence": confidence,
        "created_at": now.isoformat(),
        "status": "pending",
    }

    os.makedirs(os.path.dirname(PENDING_PATH), exist_ok=True)

    # ── citation verification gate ────────────────────────────────────────────
    vr = verify_hypothesis(record)
    record["verification_status"]  = vr.status
    record["verification_reasons"] = vr.reasons
    record["verification_at"]      = vr.timestamp

    if vr.status == "REJECTED":
        record["status"] = "rejected"
        rejected: list = []
        if os.path.exists(REJECTED_PATH):
            with open(REJECTED_PATH, "r", encoding="utf-8") as f:
                rejected = json.load(f)
        rejected.append(record)
        with open(REJECTED_PATH, "w", encoding="utf-8") as f:
            json.dump(rejected, f, indent=2, ensure_ascii=False)
        print(
            f"  [HYP] ⛔ REJECTED {record['id']}: {'; '.join(vr.reasons)}",
            file=sys.stderr,
        )
        return record

    if vr.status == "FLAGGED":
        print(
            f"  [HYP] ⚠️  FLAGGED  {record['id']}: {'; '.join(vr.reasons)}",
            file=sys.stderr,
        )
    else:
        print(f"  [HYP] ✅ ACCEPTED {record['id']}", file=sys.stderr)
    # ─────────────────────────────────────────────────────────────────────────

    pending = []
    if os.path.exists(PENDING_PATH):
        with open(PENDING_PATH, "r", encoding="utf-8") as f:
            pending = json.load(f)

    pending.append(record)

    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

    return record


def generate_causal_hypothesis(
    metric_label: str,
    indicator_path: str,
    baseline_value: float,
    current_value: float,
    direction: str,
    problem_context: str,
    target_pct: float | None = None,
) -> dict:
    """
    Generate an LLM-based causal hypothesis explaining WHY a global indicator
    moves the way it does, and WHAT concrete action would improve it.

    Unlike generate_hypothesis() (which extrapolates trends via regression),
    this function produces cause-effect reasoning and an action recommendation.
    The result is saved to causal_pending.json and returned.

    Args:
        metric_label:    Human-readable name, e.g. "Government Effectiveness"
        indicator_path:  Dot-path in global_indicators, e.g. "governance.ge_est"
        baseline_value:  Value captured when initiative was created
        current_value:   Latest value from global_indicators
        direction:       "higher" or "lower" (desired direction of improvement)
        problem_context: The initiative's problem description
        target_pct:      The % change targeted in the milestone (or None)
    """
    now = datetime.now(timezone.utc)
    record_id = f"causal_{indicator_path.replace('.', '_')}_{now.strftime('%Y%m%d_%H%M%S')}"

    if _call_groq_causal is None:
        return {
            "id":                  record_id,
            "type":                "causal_hypothesis",
            "metric_label":        metric_label,
            "indicator_path":      indicator_path,
            "baseline_value":      baseline_value,
            "current_value":       current_value,
            "delta":               round(current_value - baseline_value, 4),
            "direction":           direction,
            "hypothesis_text":     "",
            "root_cause":          "",
            "suggested_action":    "",
            "expected_improvement": "",
            "evidence_strength":   "none",
            "created_at":          now.isoformat(),
            "verification_status": "SKIPPED",
            "verification_reason": "call_groq unavailable",
        }

    delta      = round(current_value - baseline_value, 4)
    delta_desc = (
        f"намалява с {abs(delta):.4f}" if delta < 0
        else (f"расте с {delta:.4f}" if delta > 0 else "остава непроменен")
    )
    target_str = f"Целевото подобрение е {target_pct}%." if target_pct is not None else ""

    prompt = (
        "Ти си аналитик на глобални данни за AGI система с мисия да решава реални проблеми.\n\n"
        f"ИНИЦИАТИВА (ПРОБЛЕМ): {problem_context}\n\n"
        f"МЕТРИКА: {metric_label} (path: {indicator_path})\n"
        f"ПОСОКА НА ПОДОБРЕНИЕ: {'по-висока' if direction == 'higher' else 'по-ниска'} стойност\n"
        f"BASELINE (при старт): {baseline_value}\n"
        f"ТЕКУЩА СТОЙНОСТ: {current_value}\n"
        f"ПРОМЯНА: {delta_desc} ({delta:+.4f})\n"
        f"{target_str}\n\n"
        "ЗАДАЧА: Генерирай причинно-следствена хипотеза.\n"
        "1. ЗАЩО се движи метриката по този начин? (конкретни механизми, не обща теория)\n"
        "2. КОЯ е ROOT CAUSE?\n"
        "3. КАКВО конкретно действие би подобрило метриката?\n"
        "4. КАКВО подобрение очакваме ако действието се приложи?\n"
        "5. КОЛКО е силна доказателствената база: strong / moderate / weak?\n\n"
        "Отговори САМО с валиден JSON — без markdown:\n"
        '{"hypothesis_text":"...","root_cause":"...","suggested_action":"...",'
        '"expected_improvement":"...","evidence_strength":"moderate"}'
    )

    raw = ""
    try:
        raw = _call_groq_causal(prompt, max_tokens=500)
        import re as _re
        raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break
        if "{" in raw:
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
        parsed = json.loads(raw)
    except Exception as e:
        print(f"  [CAUSAL_HYP] parse error: {e} | raw[:100]: {raw[:100]!r}")
        parsed = {}

    hypothesis_text  = parsed.get("hypothesis_text", "")
    root_cause       = parsed.get("root_cause", "")
    suggested_action = parsed.get("suggested_action", "")
    expected_improvement = parsed.get("expected_improvement", "")
    evidence_strength    = parsed.get("evidence_strength", "unknown")

    # Simple quality gate
    if len(hypothesis_text) > 50 and len(suggested_action) > 30:
        verification_status = "ACCEPTED"
        verification_reason = ""
    elif hypothesis_text or suggested_action:
        verification_status = "FLAGGED"
        verification_reason = "hypothesis_text or suggested_action too short"
    else:
        verification_status = "REJECTED"
        verification_reason = "empty response from LLM"

    record = {
        "id":                  record_id,
        "type":                "causal_hypothesis",
        "metric_label":        metric_label,
        "indicator_path":      indicator_path,
        "baseline_value":      baseline_value,
        "current_value":       current_value,
        "delta":               delta,
        "direction":           direction,
        "hypothesis_text":     hypothesis_text,
        "root_cause":          root_cause,
        "suggested_action":    suggested_action,
        "expected_improvement": expected_improvement,
        "evidence_strength":   evidence_strength,
        "created_at":          now.isoformat(),
        "verification_status": verification_status,
        "verification_reason": verification_reason,
    }

    if verification_status != "REJECTED":
        os.makedirs(os.path.dirname(CAUSAL_PENDING_PATH), exist_ok=True)
        existing: list = []
        if os.path.exists(CAUSAL_PENDING_PATH):
            try:
                with open(CAUSAL_PENDING_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
        existing.append(record)
        with open(CAUSAL_PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"  [CAUSAL_HYP] {verification_status}: {metric_label} -> {suggested_action[:60]}")
    else:
        print(f"  [CAUSAL_HYP] REJECTED: {metric_label} (empty LLM response)")

    return record


def _list_axes():
    with open(TRENDS_PATH, "r", encoding="utf-8") as f:
        trends = json.load(f)
    return [k for k in trends if k != "cycle_count"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CORTEX Hypothesis Generator — generates trend-based predictions"
    )
    parser.add_argument("--generate", metavar="AXIS",
                        help="Generate hypothesis for the given axis name")
    parser.add_argument("--horizon", type=int, default=30,
                        help="Prediction horizon in days (default: 30)")
    parser.add_argument("--past-test", type=int, default=None, metavar="DAYS",
                        help="Force prediction_date DAYS ago (triggers evaluator immediately)")
    parser.add_argument("--list-axes", action="store_true",
                        help="List all available axes in trends.json")
    parser.add_argument("--check", action="store_true",
                        help="Run evaluator on due hypotheses (delegates to evaluator.py)")
    args = parser.parse_args()

    if args.list_axes:
        print("Available axes:", _list_axes())
        sys.exit(0)

    if args.generate:
        try:
            rec = generate_hypothesis(
                args.generate,
                horizon_days=args.horizon,
                past_offset_days=args.past_test,
            )
            print(json.dumps(rec, indent=2, ensure_ascii=False))
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

    if args.check:
        from evaluator import check_due_hypotheses
        results = check_due_hypotheses()
        if results:
            print(json.dumps(results, indent=2, ensure_ascii=False))
