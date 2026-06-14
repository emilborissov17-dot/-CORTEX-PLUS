#!/usr/bin/env python3
"""
memory/auto_threshold.py
Изчислява прагове за auto_level динамично от историческите данни.
LOW/MEDIUM/HIGH се определят от перцентилите на реалните стойности.
"""
import json, pathlib
from statistics import quantiles

BASE_DIR     = pathlib.Path(__file__).resolve().parents[1]
HISTORY_PATH = BASE_DIR / "memory" / "axis_history.json"
THRESH_PATH  = BASE_DIR / "memory" / "dynamic_thresholds.json"

def compute_thresholds() -> dict:
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        print("[THRESHOLD] Няма история — нужни са поне 2 snapshot-а")
        return {}

    thresholds = {}

    for axis, snapshots in history.items():
        axis_thresh = {}
        # Събери всички метрики от историята
        all_metrics = {}
        for snap in snapshots:
            metrics = snap.get("metrics", {})
            for k, v in metrics.items():
                if v is not None:
                    try:
                        all_metrics.setdefault(k, []).append(float(v))
                    except Exception:
                        pass

        for metric, values in all_metrics.items():
            if len(values) < 2:
                continue
            try:
                q = quantiles(values, n=4)  # Q1, Q2, Q3
                axis_thresh[metric] = {
                    "p25": round(q[0], 4),
                    "p50": round(q[1], 4),
                    "p75": round(q[2], 4),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "n":   len(values),
                }
            except Exception:
                pass

        if axis_thresh:
            thresholds[axis] = axis_thresh

    THRESH_PATH.write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[THRESHOLD] {len(thresholds)} оси с динамични прагове")
    return thresholds

def get_dynamic_level(axis: str, metric: str, value: float, direction: str) -> str:
    """Върни LOW/MEDIUM/HIGH базирано на перцентили от историята."""
    try:
        thresholds = json.loads(THRESH_PATH.read_text(encoding="utf-8"))
        t = thresholds.get(axis, {}).get(metric)
        if not t:
            return None
        if direction == "higher_is_better":
            if value >= t["p75"]: return "HIGH"
            if value >= t["p25"]: return "MEDIUM"
            return "LOW"
        else:
            if value <= t["p25"]: return "HIGH"
            if value <= t["p75"]: return "MEDIUM"
            return "LOW"
    except Exception:
        return None

if __name__ == "__main__":
    thresholds = compute_thresholds()
    if not thresholds:
        print("[THRESHOLD] Изчакай повече история — пуска се автоматично всеки ден")
    else:
        for axis, metrics in list(thresholds.items())[:3]:
            print(f"  {axis}:")
            for metric, t in list(metrics.items())[:2]:
                print(f"    {metric}: p25={t['p25']}, p75={t['p75']}, n={t['n']}")
