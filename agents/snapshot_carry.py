"""Last-known-good for the per-axis snapshots, on the rule the master file already uses.

WHAT HAPPENED (measured 2026-08-04). The axis snapshot agents do:

    raw = provider.fetch()
    _write(folder, axis, {"source_type": "REAL_DATA", "metrics": raw, "raw": raw})

An EMPTY fetch is not an exception, so `{}` fell through the success path and was written
as REAL_DATA. GOVERNANCE_INSTITUTIONS_REVIEW went from 18 metrics to zero in a single
cycle and its scorer went from degraded to DEAD — while the file on disk still declared
REAL_DATA. Running the provider by hand minutes later returned all 18. Nothing was wrong
with the source; one transient failure erased the axis and labelled the erasure real data.

core/global_indicators.py fixed exactly this a day earlier (2026-08-03) for the master
file, after a slow minute at the World Bank turned eleven metrics into None. Its rule —
last-known-good, carried forward with loud ageing, dated to the ORIGINAL observation — is
reused here rather than reimplemented, so the two layers cannot drift apart in what
"carried" means.

Carried is never laundered into fresh: `_carried` names every metric served from a
previous cycle and dates it to when it was actually observed, so a value copied forward
for a month cannot pass as today's reading.
"""
from __future__ import annotations

import json
from pathlib import Path


def carry_forward_metrics(snapshot_path, new_metrics: dict) -> tuple:
    """Merge `new_metrics` over the previous snapshot's, keeping last-known-good.

    Returns (merged_metrics, carried) where `carried` maps each carried key to its value,
    original observation date and age. A partial fetch keeps everything it did get and
    carries only what it missed."""
    from core.global_indicators import _carry_forward

    path = Path(snapshot_path)
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(new_metrics or {}), {}

    # The civilization agent stores values under "metrics"; the human and cosmos agents
    # store the same thing under "raw" only. Read either, so one helper covers all three.
    old = prev.get("metrics") or prev.get("raw") or {}
    if not isinstance(old, dict) or not old:
        return dict(new_metrics or {}), {}

    old_ts = prev.get("observed_utc") or prev.get("snapshot_timestamp")
    carried: dict = {}
    merged = _carry_forward(dict(new_metrics or {}), old, old_ts, carried)
    merged.pop("_carried", None)          # kept beside the metrics, not inside them
    return merged, carried
