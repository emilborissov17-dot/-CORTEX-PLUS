#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MARKET BET — next-session direction for SPY / GLD / UUP, against a momentum baseline.

PREDICTION ONLY (§VI). Nothing here places, sizes, or recommends a trade. It records a
direction and a stated reason, and reality grades the direction.

WHY MARKETS. Earthquakes were an honest but useless null: the count is close to noise
around its own mean, so a rationale about it cannot be checked against anything. A
market direction can be wrong for a NAMED reason - "CPI surprise +0.3, BLS 12 Sep" is a
fact somebody can look up, and a bet that cites it can be diagnosed rather than only
counted.

THE RATIONALE IS SEALED AND NEVER REWARDED. Only the graded direction decides whether a
bet was right. A rationale that earned credit is one the model learns to write well
rather than to mean.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.market_daily import ASSETS, INDICATORS  # noqa: E402
from tools.first_bet import MODEL_PIN, generate_completions  # noqa: E402

N_COMPLETIONS = 8
TEMPERATURE = 0.7
LEDGER = REPO / "memory" / "first_bet"

DIRECTIONS = ("UP", "DOWN")
BUCKETS = ("MACRO", "GEOPOL", "FLOW", "SECTOR")

PROMPT = """You are forecasting the next-session direction of one exchange-traded fund.
This is a PREDICTION ONLY. No trade will be placed on it.

ASSET: {sym}
Last close ({close_date}): {close}
Recent closes (oldest to newest): {recent}

Answer with EXACTLY these three lines and nothing else:

DIRECTION: UP or DOWN
DEADLINE: {deadline}
RATIONALE: DRIVER [one of MACRO|GEOPOL|FLOW|SECTOR] | SIGNAL [a NAMED EXTERNAL FACT with a date and a source] | LOGIC [one sentence]

The SIGNAL must be a fact somebody else could look up - an event, a release, a printed
number - with a date and where it came from. For example:
  RATIONALE: DRIVER MACRO | SIGNAL CPI surprise +0.3, BLS 12 Sep | LOGIC a hotter print lifts real yields and weighs on equities
It must NOT be interpretation. "Sentiment feels weak" and "momentum is negative" are not
signals; they are opinions about the price you were just shown.
"""

_DATE_RE = re.compile(
    r"\b(\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})\b", re.I)
_SOURCE_RE = re.compile(
    r"\b(BLS|BEA|Fed|FOMC|ECB|BOJ|OPEC|EIA|Treasury|Reuters|Bloomberg|WSJ|FT|"
    r"CPI|PPI|NFP|ISM|PMI|GDP|Census|IMF|OECD|SEC)\b")


# US EQUITY MARKET HOLIDAYS 2026 (NYSE/NYSE Arca calendar). A weekday rule alone is
# NOT enough, and the dry run proved it: Friday 2026-09-04 + one weekday gave
# 2026-09-07, which is LABOR DAY and has no session at all. A bet whose deadline falls
# on a closed market cannot be graded, and nothing in the price data says "closed" -
# a missing bar looks exactly like a bar that has not arrived yet.
#
# This list is a MAINTENANCE BURDEN and is written down as one: it is correct for 2026
# and will be wrong for 2027 unless somebody updates it. next_session() refuses rather
# than guesses once it runs past the end of the declared year.
US_MARKET_HOLIDAYS_2026 = frozenset({
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Washington's Birthday
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
})


def next_session(after: date) -> date:
    """The next US equity session strictly after `after`.

    Refuses outside 2026 rather than guessing: an out-of-date holiday table that
    silently returns a closed day is worse than an error.
    """
    d = after + timedelta(days=1)
    for _ in range(10):
        if d.year != 2026:
            raise ValueError(
                f"next_session({after}) reached {d}: the holiday table only covers "
                f"2026. Update US_MARKET_HOLIDAYS_2026 before betting past it.")
        if d.weekday() < 5 and d.isoformat() not in US_MARKET_HOLIDAYS_2026:
            return d
        d += timedelta(days=1)
    raise ValueError(f"no session found within 10 days of {after}")


def parse_completion(raw: str) -> dict:
    out = {"raw": raw, "direction": None, "deadline": None, "rationale": None,
           "driver": None, "signal": None, "logic": None}
    for line in str(raw).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().upper(), v.strip()
        if k == "DIRECTION":
            out["direction"] = v.upper().strip(" .*")
        elif k == "DEADLINE":
            out["deadline"] = v
        elif k == "RATIONALE":
            out["rationale"] = v
            parts = [p.strip() for p in v.split("|")]
            for p in parts:
                up = p.upper()
                if up.startswith("DRIVER"):
                    out["driver"] = p[6:].strip(" :")
                elif up.startswith("SIGNAL"):
                    out["signal"] = p[6:].strip(" :")
                elif up.startswith("LOGIC"):
                    out["logic"] = p[5:].strip(" :")
    return out


def signal_is_external_fact(signal) -> bool:
    """Best-effort: a SIGNAL must carry a DATE or a NAMED SOURCE.

    This cannot verify that the fact is true - only that it is the KIND of thing that
    could be checked. "Sentiment feels weak" names nothing and fails; "CPI surprise
    +0.3, BLS 12 Sep" names a release, a number, a source and a date and passes. The
    check is deliberately weak and deliberately stated as weak: it filters interpretation
    dressed as evidence, not lies.
    """
    s = str(signal or "").strip()
    if len(s) < 8:
        return False
    return bool(_DATE_RE.search(s) or _SOURCE_RE.search(s))


def gate_all(parsed_list, sym: str, deadline: str) -> list:
    """One record per candidate, each with a verdict and an exact refusal string."""
    out = []
    for p in parsed_list:
        rec = {"raw": p["raw"], "parsed": {k: v for k, v in p.items() if k != "raw"}}
        d = (p.get("direction") or "").upper()
        if d not in DIRECTIONS:
            rec.update(verdict="REFUSED", missing=["direction"],
                       refusal=(f"direction: {p.get('direction')!r} is not a direction. "
                                f"UP or DOWN, and nothing else, can be graded."))
        elif not str(p.get("rationale") or "").strip():
            rec.update(verdict="REFUSED", missing=["rationale"],
                       refusal=("rationale: the bet states a direction with no reason. "
                                "DRIVER | SIGNAL | LOGIC is required, and it is recorded "
                                "but never rewarded."))
        elif (p.get("driver") or "").upper().split()[0:1] and \
                (p.get("driver") or "").upper().split()[0] not in BUCKETS:
            rec.update(verdict="REFUSED", missing=["driver"],
                       refusal=(f"driver: {p.get('driver')!r} is not one of "
                                f"{'|'.join(BUCKETS)}."))
        elif not signal_is_external_fact(p.get("signal")):
            rec.update(verdict="REFUSED", missing=["signal"],
                       refusal=(f"signal: {p.get('signal')!r} is interpretation, not a "
                                f"dated external fact. A SIGNAL must carry a date or a "
                                f"named source so somebody else could look it up."))
        elif str(p.get("deadline") or "").strip() != deadline:
            rec.update(verdict="REFUSED", missing=["deadline"],
                       refusal=(f"deadline: {p.get('deadline')!r} is not the graded "
                                f"session {deadline!r}."))
        else:
            rec.update(verdict="ADMITTED", missing=[], refusal=None)
        out.append(rec)
    return out


def choose(records) -> tuple:
    """The MAJORITY direction among passing candidates; ties break to the first.

    Majority, not "most confident": there is no confidence field here, and picking the
    single most fluent rationale would let the prose choose the bet - exactly what the
    reward rule forbids.
    """
    ok = [(i, r) for i, r in enumerate(records) if r["verdict"] == "ADMITTED"]
    if not ok:
        return None, "no candidate passed the gate", None
    votes = {d: [i for i, r in ok if r["parsed"]["direction"] == d] for d in DIRECTIONS}
    win = max(DIRECTIONS, key=lambda d: len(votes[d]))
    if not votes[win]:
        return None, "no candidate passed the gate", None
    idx = votes[win][0]
    return idx, (f"majority direction {win} "
                 f"({len(votes['UP'])} UP / {len(votes['DOWN'])} DOWN of {len(ok)} "
                 f"passing); first such candidate sealed"), win


def seal(per_asset: dict, baseline: dict, out_path: Path,
         allow_overwrite: bool = False) -> str:
    if out_path.exists() and not allow_overwrite:
        raise FileExistsError(f"{out_path} already holds a sealed bet.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": "market direction, PREDICTION ONLY — no trade (§VI)",
        "model": MODEL_PIN, "n_completions": N_COMPLETIONS,
        "temperature": TEMPERATURE,
        "gate_entry_point": "tools/market_bet.gate_all (direction + DRIVER|SIGNAL|LOGIC); "
                            "the cycle's proposal gate judges proposals, not directions",
        "baseline_method": "20-trading-day momentum sign, sealed in "
                           "BASELINE_2026-09-07_markets.json before any bet",
        "assets": per_asset, "baseline": baseline,
        "reference_close_date": "2026-09-04",
        "grading_rule": "the FIRST bar strictly after reference_close_date, "
                        "whatever date it carries - so a wrong deadline guess "
                        "cannot corrupt the grade",
        "outcome": "SEALED — not graded. Grading is +24 h against the next session close.",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return str(out_path)


def sha_of(sym: str, direction: str, deadline: str) -> str:
    return hashlib.sha256(json.dumps(
        {"asset": sym, "direction": direction, "deadline": deadline},
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", metavar="JSON",
                    help="{sym: [8 completions]} instead of a model")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--deadline", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if not a.dry_run and not a.live:
        print("REFUSED: pass --dry-run <json> or --live. Nothing ran.")
        return 3

    import core.market_daily as md
    baseline = json.loads(
        (LEDGER / "BASELINE_2026-09-07_markets.json").read_text(encoding="utf-8"))
    ref = baseline["last_close"]["SPY"]["date"]
    deadline = a.deadline or next_session(date.fromisoformat(ref)).isoformat()
    print(f"reference close {ref} -> graded session {deadline}"
          + ("  (today is a market holiday)"
             if date.today().isoformat() in US_MARKET_HOLIDAYS_2026 else ""))

    dry = json.loads(Path(a.dry_run).read_text(encoding="utf-8")) if a.dry_run else None
    per_asset = {}
    for sym in ASSETS:
        lc = baseline["last_close"][sym]
        if dry is not None:
            comps = dry[sym]
        else:
            import evaluator
            live = json.loads(Path(evaluator.TRENDS_PATH).read_text(encoding="utf-8"))
            recent = ", ".join(f"{v:.2f}" for v in live[INDICATORS[sym]][-10:])
            comps = generate_completions(
                PROMPT.format(sym=sym, close=lc["adjclose"], close_date=lc["date"],
                              recent=recent, deadline=deadline),
                n=N_COMPLETIONS, temperature=TEMPERATURE)
        recs = gate_all([parse_completion(c) for c in comps], sym, deadline)
        idx, reason, win = choose(recs)
        per_asset[sym] = {
            "indicator": INDICATORS[sym], "last_close": lc,
            "deadline": deadline,
            "sealed_direction": win,
            "sealed_rationale": recs[idx]["parsed"]["rationale"] if idx is not None else None,
            "chosen_reason": reason,
            "sha256": sha_of(sym, win, deadline) if win else None,
            "baseline_momentum_sign": baseline["baseline"][sym]["sign"],
            "n_passed_gate": sum(r["verdict"] == "ADMITTED" for r in recs),
            "candidates": [dict(r, sealed=(i == idx)) for i, r in enumerate(recs)],
        }
        print(f"\n{sym}  last {lc['date']} {lc['adjclose']}  deadline {deadline}")
        for i, r in enumerate(recs):
            mark = "SEALED " if i == idx else "       "
            print(f"  {mark}{i} {r['verdict']:9} "
                  + (r["parsed"]["direction"] or "-")
                  + ("" if r["verdict"] == "ADMITTED" else f"  — {r['refusal'][:88]}"))
        print(f"  -> {reason}")

    out = Path(a.out or (LEDGER / "BET_2026-09-07_markets.json"))
    print("\n" + seal(per_asset, baseline["baseline"], out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
