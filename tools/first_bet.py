#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIRST BET — the first really-graded forecast. See claude/SPEC_7SEP_FIRST_BET.md.

The system bets on tomorrow's value of ONE daily indicator, reality grades it in 24 h,
and the bet is compared against persistence (tomorrow = today). Archive-imitation is
dead — A3 scored 0.2611 against a base of 0.2667, AT CHANCE, with LEARNED=False and
BEYOND_TRIVIAL=False — so this replaces "imitate the past" with "bet on the future",
where reality rather than a corpus says whether the answer was right.

WHICH GATE. Not a new one. `fast_cycle_runner.py:1600` calls
`core.proposal_intake.admit(...)`; `admit` applies `core.proposal_intake.judge` to every
proposal. This module calls `judge` — the same decision, one candidate at a time so each
verdict maps back to the completion that produced it, and so nothing is appended to the
live `memory/proposal_intake_refusals.jsonl`. `test_the_gate_is_the_live_one` pins that
chain; if the live door ever stops using this decision, the claim fails loudly.

WHAT IS SEALED, AND WHERE. A new isolated ledger, `memory/first_bet/BET_<date>.json`.
NOT prophecy, NOT axis_next: an experiment that has never been graded once does not get
to write into the ledgers the cycle depends on.

RUNNING IT. Not tonight. The 03:04 cycle needs the GPU and the ladder, and this script
does not run until that cycle has finished and released both. `--dry-run` reads
completions from a file and touches neither.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SERIES_DEFAULT = "GDELT_DAILY"          # the spec's default; see the note in main()
N_COMPLETIONS = 8
TEMPERATURE = 0.7                       # spec: never above 1.0 for a numeric delta
LEDGER_DIR = REPO / "memory" / "first_bet"
REQUIRED = ("INDICATOR", "EXPECTED_DELTA", "DEADLINE")

PROMPT = """You are forecasting ONE daily indicator.

INDICATOR: {series}
Today's value ({v0_date}): {v0}
Recent daily changes: {recent}

Answer with EXACTLY these three lines, and nothing else:
INDICATOR: {series}
EXPECTED_DELTA: <a signed number — the change from today's value to the deadline>
DEADLINE: {deadline}

You may add one optional fourth line:
CONFIDENCE: <a number between 0 and 1>
"""


# ── parsing ─────────────────────────────────────────────────────────────────
def parse_completion(raw: str) -> dict:
    """KEY: value, one per line. Missing fields are NAMED, not inferred."""
    out = {"raw": raw, "indicator": None, "expected_delta": None,
           "deadline": None, "confidence": None, "missing_fields": []}
    for line in str(raw).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().upper(), v.strip()
        if k == "INDICATOR":
            out["indicator"] = v
        elif k == "EXPECTED_DELTA":
            out["expected_delta"] = v
        elif k == "DEADLINE":
            out["deadline"] = v
        elif k == "CONFIDENCE":
            try:
                out["confidence"] = float(v)
            except ValueError:
                out["confidence"] = None
    out["missing_fields"] = [f for f in REQUIRED
                             if out[f.lower() if f != "EXPECTED_DELTA"
                                    else "expected_delta"] in (None, "")]
    return out


# ── the series preconditions ────────────────────────────────────────────────
def series_moved(values, n: int = 3) -> bool:
    """Did the series MOVE across the last n available days?

    The spec requires this before betting, and it is the precondition most likely to
    fire: CLIMATE_GLOBAL_RISK_REVIEW is the only gate-resolvable daily indicator and
    core/global_indicators.py:78 feeds it from co2_weekly_mlo.csv, a WEEKLY file — so
    six days in seven it returns the number it returned yesterday. Betting on a frozen
    series is betting on nothing; persistence wins by construction.
    """
    vals = [v for v in (values or []) if isinstance(v, (int, float))]
    if len(vals) < n:
        return False
    tail = vals[-n:]
    return len(set(tail)) > 1


def median_abs_daily_change(values):
    """The series' own recent day-to-day variation — the scale a sane delta lives on."""
    vals = [v for v in (values or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return None
    return statistics.median(abs(vals[i] - vals[i - 1]) for i in range(1, len(vals)))


# ── the gate ────────────────────────────────────────────────────────────────
def gate_all(parsed_list, series_id: str, today: date | None = None, **inject) -> list:
    """One record per candidate: raw text, parsed fields, verdict, refusal string.

    The NAME LOCK runs first and is this module's own check, not the shared gate's.
    The gate asks whether an indicator resolves; it cannot know which series was
    actually fetched. A completion that names a different indicator would otherwise
    pass — and the bet would be sealed under a name nothing checked, which is the
    defect this repo keeps finding.
    """
    from core.proposal_intake import judge
    today = today or date.today()
    records = []
    for p in parsed_list:
        rec = {"raw": p["raw"], "parsed": {k: v for k, v in p.items() if k != "raw"}}
        if p["indicator"] is not None and p["indicator"] != series_id:
            rec.update(verdict="REFUSED", missing=["indicator"],
                       refusal=(f"name: completion names {p['indicator']!r} but the bet "
                                f"is on {series_id!r}; the sealed indicator is locked to "
                                f"the fetched series id"))
            records.append(rec)
            continue
        delta = p["expected_delta"]
        try:
            delta_val = float(delta)
        except (TypeError, ValueError):
            delta_val = delta               # let the gate name it, do not pre-judge
        v = judge({"indicator": p["indicator"], "expected_delta": delta_val,
                   "deadline": p["deadline"],
                   "component": "first_bet", "solution": "first bet candidate"},
                  today=today, **inject)
        rec.update(verdict=v["verdict"], missing=v["missing"], refusal=v["why"])
        records.append(rec)
    return records


# ── the choice ──────────────────────────────────────────────────────────────
def choose(records, ref_delta):
    """Seal ONE. Confidence first if the model gave any, else the candidate whose delta
    is closest to the series' own recent daily variation.

    "Smallest confidence width" for a scalar confidence is read as width = 1 - c, so
    the narrowest is the highest confidence. Stated because the spec's phrase does not
    define itself for a scalar.
    """
    ok = [(i, r) for i, r in enumerate(records) if r["verdict"] == "ADMITTED"]
    if not ok:
        return None, "no candidate passed the gate"
    with_c = [(i, r) for i, r in ok if r["parsed"].get("confidence") is not None]
    if with_c:
        i, r = min(with_c, key=lambda t: 1.0 - float(t[1]["parsed"]["confidence"]))
        return i, (f"smallest confidence width (1-c = "
                   f"{1.0 - float(r['parsed']['confidence']):.3f})")
    if ref_delta is None:
        i, _ = ok[0]
        return i, "first passing candidate (no confidence, no reference delta)"
    i, r = min(ok, key=lambda t: abs(float(t[1]["parsed"]["expected_delta"]) - ref_delta))
    return i, (f"delta closest to the series' median absolute daily change "
               f"({ref_delta:.6g})")


# ── the seal ────────────────────────────────────────────────────────────────
def seal_bet(records, series_id: str, v0: float, v0_date: str, ref_delta,
             today: date | None = None, ledger_dir: Path | None = None,
             deadline: str | None = None) -> str:
    today = today or date.today()
    ledger_dir = Path(ledger_dir or LEDGER_DIR)
    ledger_dir.mkdir(parents=True, exist_ok=True)

    idx, reason = choose(records, ref_delta)
    cands = [dict(r, sealed=(i == idx)) for i, r in enumerate(records)]

    payload = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "indicator": series_id, "V0": v0, "V0_date": v0_date,
        "n_candidates": len(records),
        "n_passed_gate": sum(r["verdict"] == "ADMITTED" for r in records),
        "gate_entry_point": "core.proposal_intake.judge (the decision "
                            "core.proposal_intake.admit applies; admit is what "
                            "fast_cycle_runner.py:1600 calls)",
        "all_8_candidates": cands,
    }

    if idx is None:
        payload.update(predicted_delta=None, predicted_value=None, deadline=deadline,
                       confidence=None, chosen_reason=reason,
                       sha256_of_sealed_fields=None,
                       persistence_predicted_value=v0, persistence_deadline=deadline,
                       outcome="NO_BET: no candidate passed the gate")
    else:
        c = records[idx]["parsed"]
        delta = float(c["expected_delta"])
        dl = c["deadline"]
        sealed = {"indicator": series_id, "expected_delta": delta, "deadline": dl}
        payload.update(
            predicted_delta=delta, predicted_value=v0 + delta, deadline=dl,
            confidence=c.get("confidence"), chosen_reason=reason,
            sha256_of_sealed_fields=hashlib.sha256(
                json.dumps(sealed, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")).hexdigest(),
            # THE NULL, sealed at the same instant and in the same file. A baseline
            # computed after the outcome is not a baseline.
            persistence_predicted_value=v0, persistence_deadline=dl,
            outcome="SEALED — not graded. Grading is a separate step at +24 h.")

    out = ledger_dir / f"BET_{today.isoformat()}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out)


# ── generation (NEVER called by the tests) ──────────────────────────────────
def generate_completions(prompt: str, n: int = N_COMPLETIONS,
                         temperature: float = TEMPERATURE) -> list:
    """N completions from the local 3B via core.brain.think.

    Imported lazily and only from main(): the guard tests must never touch a model,
    and this must not run while the 03:04 cycle holds the GPU.
    """
    from core.brain import think
    out = []
    for _ in range(n):
        r = think(role="forecaster", question=prompt, kind="first_bet",
                  remember_it=False, temperature=temperature)
        out.append("" if r is None else str(r.get("text") or r))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indicator", default=SERIES_DEFAULT)
    ap.add_argument("--dry-run", metavar="JSON",
                    help="read completions from a JSON list instead of a model; "
                         "touches no GPU and no network")
    ap.add_argument("--ledger-dir", default=None)
    a = ap.parse_args()

    # PRECONDITION 1 — the indicator must resolve through the SHARED gate. Checked
    # before anything is generated: eight completions on a name the gate cannot
    # resolve is eight refusals and a wasted GPU trip.
    #
    # MEASURED 2026-09-07, before this ran: the spec's default GDELT_DAILY does NOT
    # resolve -- "trends.json has no series 'GDELT_DAILY'; axis_observations has no
    # axis 'GDELT_DAILY'; metric_details has no metric 'GDELT_DAILY'". The only
    # gate-resolvable daily indicator is CLIMATE_GLOBAL_RISK_REVIEW, and precondition
    # 2 is likely to refuse that one for being frozen. Both are reported rather than
    # worked around.
    from core.proposal_intake import _default_resolver, split_indicator
    parts = split_indicator(a.indicator)
    value, why_not = (None, "indicator is not AXIS or AXIS__metric")
    if parts:
        value, why_not = _default_resolver(*parts)
    if value is None:
        print(f"REFUSED before betting: {a.indicator} does not resolve today: {why_not}")
        print("  Nothing was generated. Pick a series the gate can resolve, or make "
              "this one resolve first.")
        return 2

    if not a.dry_run:
        print("REFUSED: this script does not generate tonight. The 03:04 cycle needs "
              "the GPU and the ladder. Re-run with --dry-run, or after the cycle has "
              "released both.")
        return 3

    completions = json.loads(Path(a.dry_run).read_text(encoding="utf-8"))
    parsed = [parse_completion(c) for c in completions]
    records = gate_all(parsed, a.indicator)
    out = seal_bet(records, series_id=a.indicator, v0=float(value),
                   v0_date=date.today().isoformat(), ref_delta=None,
                   ledger_dir=a.ledger_dir)
    print(f"-> {out}")
    for i, r in enumerate(records):
        print(f"  cand {i}: {r['verdict']}"
              + (f" — {r['refusal']}" if r["verdict"] == "REFUSED" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
