#!/usr/bin/env python3
"""
core/prediction_resolutions.py — the record K4 has nothing to score without.

WHY THIS EXISTS (ITEM 7.3b, 28 August 2026)
-------------------------------------------
K4 is meant to say how well the system's interval predictions about THE WORLD
hold up. Today it cannot say anything, and not because the model is bad: there
is no file anywhere that pairs a prediction with the value that later arrived.
memory/prediction_resolutions.jsonl did not exist and nothing in the repo read
or wrote it — checked by grep over every .py and .json before this was written.

Two events, one line each, appended in the order they happen:

  PREDICTION   ts, axis, domain, predicted_centre, predicted_low,
               predicted_high, alpha
  RESOLUTION   ts, axis, domain, observed_value, resolved_ts, and the same
               band, copied, so a single line can be judged without seeking
               backwards through the file

WHAT IS ADJACENT AND WHY THIS IS NOT A SECOND COPY OF IT
--------------------------------------------------------
experiments/prophecy/prophecy_ledger.py already seals axis self-predictions
(target_kind "axis_next") and scores them when they mature. It is a hash chain,
it lives at experiments/prophecy/prophecy_ledger.jsonl, and it predicts a LEVEL
WORD — "axis X will be LEVEL L next cycle". K4 needs a NUMERIC INTERVAL: a
centre, a band, and the alpha that band was drawn at, so coverage and Winkler
score are computable. Those are different quantities and neither file can
answer the other's question.

THE RISK IS REAL AND IS NAMED HERE RATHER THAN DISCOVERED LATER: two records of
what the system predicted about an axis can drift apart. If one of them is ever
made authoritative for both, it should be the sealed chain, because a record
that cannot be edited after the outcome is worth more than one that can — and
this file is deliberately NOT a chain, because K4 needs to append a resolution
to a prediction made days earlier and a chain makes that a rewrite.

prediction_id IS AN ADDITION, and here is why. The item lists the fields without
one, which leaves a resolution to be matched to its prediction by (axis, domain)
and time order. That works right up until two predictions for one axis are open
at once, and then it silently pairs the wrong ones. The id is a hash of the
sealed prediction's own content, so the join is checkable and a resolution that
matches nothing says so instead of guessing.

DRY-RUN BY DEFAULT. Per CLAUDE.md, a module that writes a ledger needs an
explicit --write. record_prediction() and record_resolution() return the row
they WOULD append unless write=True.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
LEDGER = BASE / "memory" / "prediction_resolutions.jsonl"

PREDICTION = "PREDICTION"
RESOLUTION = "RESOLUTION"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prediction_id(axis: str, domain: str, ts: str, centre) -> str:
    """Deterministic, from the prediction's own content. Same inputs, same id —
    so a caller that retries does not open a second prediction."""
    raw = json.dumps([str(axis), str(domain), str(ts), float(centre)],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _append(row: dict, path: pathlib.Path | None = None) -> dict:
    p = path or LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def record_prediction(axis: str, domain: str, predicted_centre: float,
                      predicted_low: float, predicted_high: float,
                      alpha: float, ts: str | None = None,
                      write: bool = False,
                      path: pathlib.Path | None = None) -> dict:
    """One prediction, before the answer is known. DRY-RUN unless write=True."""
    if predicted_low > predicted_high:
        raise ValueError(
            f"low {predicted_low} is above high {predicted_high} — a band that "
            f"is inside out would score as if it had failed, which is a lie "
            f"about the model rather than about the world")
    stamp = ts or _now()
    row = {
        "event": PREDICTION,
        "ts": stamp,
        "prediction_id": prediction_id(axis, domain, stamp, predicted_centre),
        "axis": str(axis),
        "domain": str(domain),
        "predicted_centre": float(predicted_centre),
        "predicted_low": float(predicted_low),
        "predicted_high": float(predicted_high),
        "alpha": float(alpha),
    }
    return _append(row, path) if write else row


def record_resolution(prediction: dict, observed_value: float,
                      resolved_ts: str | None = None, write: bool = False,
                      path: pathlib.Path | None = None) -> dict:
    """The value that actually arrived, against the band that was sealed.

    Takes the PREDICTION ROW rather than an id, so the band travels onto the
    resolution line and one line can be judged on its own. `inside` is computed
    here, once, instead of by every future reader with its own idea of whether
    the bounds are inclusive.
    """
    if prediction.get("event") != PREDICTION:
        raise ValueError(f"not a prediction row: event={prediction.get('event')!r}")
    lo = float(prediction["predicted_low"])
    hi = float(prediction["predicted_high"])
    obs = float(observed_value)
    row = {
        "event": RESOLUTION,
        "ts": prediction["ts"],
        "prediction_id": prediction["prediction_id"],
        "axis": prediction["axis"],
        "domain": prediction["domain"],
        "predicted_centre": float(prediction["predicted_centre"]),
        "predicted_low": lo,
        "predicted_high": hi,
        "alpha": float(prediction["alpha"]),
        "observed_value": obs,
        "resolved_ts": resolved_ts or _now(),
        "inside": bool(lo <= obs <= hi),
    }
    return _append(row, path) if write else row


def load(path: pathlib.Path | None = None) -> list:
    p = path or LEDGER
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    except FileNotFoundError:
        return []


def pairs(path: pathlib.Path | None = None) -> dict:
    """Join by prediction_id. Reports the three populations separately, because
    "predicted and never resolved" is a finding and averaging it away is how a
    coverage number flatters itself."""
    rows = load(path)
    preds = {r["prediction_id"]: r for r in rows if r.get("event") == PREDICTION}
    res = {r["prediction_id"]: r for r in rows if r.get("event") == RESOLUTION}
    resolved = [res[k] for k in preds if k in res]
    return {
        "resolved": resolved,
        "open": [preds[k] for k in preds if k not in res],
        "orphan_resolutions": [res[k] for k in res if k not in preds],
        "coverage": (sum(1 for r in resolved if r["inside"]) / len(resolved)
                     if resolved else None),
    }


def _selftest() -> int:
    """Which integrations are LIVE and which are INERT in the repo it finds
    itself in — per CLAUDE.md, so a module cannot degrade silently."""
    import tempfile
    print("core/prediction_resolutions.py --selftest")
    ok = True

    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "pr.jsonl"
        pred = record_prediction("CLIMATE_GLOBAL_RISK_REVIEW", "planet",
                                 0.5, 0.4, 0.6, 0.2, write=True, path=p)
        record_resolution(pred, 0.55, write=True, path=p)
        j = pairs(p)
        for label, cond in (
                ("a prediction and its resolution join by id", len(j["resolved"]) == 1),
                ("an observation inside the band is marked inside", j["resolved"][0]["inside"]),
                ("coverage is computed", j["coverage"] == 1.0),
                ("nothing is left open", not j["open"]),
                ("dry run appends nothing",
                 record_prediction("A", "b", 1, 0, 2, 0.2, path=p)
                 and len(load(p)) == 2)):
            print(f"  {'PASS' if cond else 'FAIL'} {label}")
            ok &= bool(cond)

    live = LEDGER.exists()
    print(f"  memory/prediction_resolutions.jsonl  "
          f"{'LIVE (' + str(len(load())) + ' rows)' if live else 'INERT (not created yet)'}")
    print("  producer wired into the cycle          INERT — nothing calls "
          "record_prediction() yet; ITEM 7.3b creates the record, not the caller")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
