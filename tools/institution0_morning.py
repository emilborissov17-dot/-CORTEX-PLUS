#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/institution0_morning.py — INSTITUTION #0 (WITNESS STAGE).

One line per commitment per morning: what the parties promised, what UCDP has
recorded since, whether this month is outside the place's own range, and a
forecast that is declared to be persistence and nothing cleverer.

WHAT THIS IS NOT, said here because it is the part that will be misread:
  * NO CAUSAL CLAIM. A rise after a commitment is not the commitment failing,
    and a fall is not the commitment working. This file counts events and says
    so; it never says "because".
  * THE ATTRIBUTION IS UCDP'S. `side_a` is Uppsala's judgement about who did
    something, arrived at from news reports. This file does not verify it,
    cannot, and does not claim to.
  * THE FORECAST IS PERSISTENCE, v0. It predicts SAME every time, with p read
    off the actor's own history. It is here to be beaten, not believed.

WINDOWS ARE ANCHORED ON THE DATA, NEVER ON TODAY (C1). UCDP publishes August in
September. A window measured back from today sits in a month that does not exist
yet, every count comes out zero, and zero reads as peace. So the anchor is
`last_complete_month(rows)` and every count carries `as_of`, the release id.

THE NULL COMES BEFORE THE WORD "RISE" (C3). For each actor, the last-month /
mean-of-prior-3 ratio is computed at every month of the previous 36, giving that
actor's own distribution of the statistic. A rise is published only above the
90th percentile of that distribution. Below it the line says "within its own
range" — which is a finding, not a silence. No fixed threshold, no Poisson test.

ACTORS ARE EXACT STRINGS (C4 iv), and where UCDP re-coded an actor mid-series the
register lists every string with its window and the counts are kept SEPARATE
unless UCDP itself joins them. `actor_unknown` (UCDP's XXXnnn) is counted on its
own line and never charged to a party.

Usage:
  venv\\Scripts\\python.exe tools/institution0_morning.py            # print, write nothing
  venv\\Scripts\\python.exe tools/institution0_morning.py --write    # append to the ledger
  venv\\Scripts\\python.exe tools/institution0_morning.py --selftest
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import ucdp_client as uc          # noqa: E402

REGISTER = REPO / "config" / "commitments.json"
REPORTERS = REPO / "config" / "reporter_independence.json"
LEDGER = REPO / "experiments" / "institution" / "ledger.jsonl"

NAME = "institution #0 (witness stage)"
SOURCE_ID = "ucdp"
REPORTER_KEY = "org:UCDP/PRIO"

NULL_MONTHS = 36          # the place's own history the null is drawn from
PRIOR_K = 3               # months in the comparison window
RISE_PERCENTILE = 0.90    # a rise is published only above this
FORECAST_VERSION = "v0-persistence"
SHUFFLE_SEED = 20260918   # the control's seed, fixed so the control is reproducible


class Unmapped(RuntimeError):
    """The reporter class is not confirmed for this source. Refuse, never default.

    `unknown` is a real class in reporter_independence.json and it means "a human
    has not ruled". Writing it here because we did not look would put a class on
    the board that nobody chose.
    """


def reporter_class(path: Path = REPORTERS, key: str = REPORTER_KEY) -> tuple[str, str]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    hit = (cfg.get("confirmed") or {}).get(key)
    if hit is None:
        raise Unmapped("%s has no confirmed entry for %r — institution #0 refuses to "
                       "publish a number whose reporter class nobody ruled on" % (path, key))
    return hit["class"], hit.get("why", "")


def load_register(path: Path = REGISTER) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _direction(a: int, b: int) -> str:
    """Direction of b relative to a."""
    if b > a:
        return "UP"
    if b < a:
        return "DOWN"
    return "SAME"


def _empirical_same_rate(counts: dict, months: list[str]) -> tuple[Optional[float], int]:
    """(p, n) — how often this actor's month-to-month direction was SAME.

    This is the probability attached to the v0 forecast. It is the actor's own
    history and nothing else: no pooling across actors, no prior, no smoothing.
    """
    seen = 0
    same = 0
    for i in range(1, len(months)):
        a, b = counts.get(months[i - 1], 0), counts.get(months[i], 0)
        seen += 1
        if _direction(a, b) == "SAME":
            same += 1
    if seen == 0:
        return None, 0
    return round(same / seen, 4), seen


def _months_back(anchor: str, n: int) -> list[str]:
    """The n complete months ending at `anchor`, oldest first."""
    return uc.prior_months(anchor, n - 1) + [anchor] if n > 1 else [anchor]


def actor_line(rows, country: str, side_a: str, anchor: str,
               commitment_date: Optional[str]) -> dict:
    """Every number this experiment publishes about one actor, in one place."""
    events = uc.osv_events(rows, country, side_a)
    counts = uc.monthly_counts(events)
    deaths = uc.monthly_deaths_civilians(events)

    prior = uc.prior_months(anchor, PRIOR_K)
    n_last = counts.get(anchor, 0)
    prior_counts = [counts.get(m, 0) for m in prior]
    mean_prior = sum(prior_counts) / float(PRIOR_K)
    ratio = round(n_last / mean_prior, 4) if mean_prior > 0 else None

    window = _months_back(anchor, NULL_MONTHS)
    null_series = uc.ratio_series(counts, window, PRIOR_K)
    p90 = uc.percentile(null_series, RISE_PERCENTILE)
    if ratio is None or p90 is None:
        verdict = "NO_NULL"          # not "no rise": we could not form the comparison
    elif ratio > p90:
        verdict = "ABOVE_OWN_P90"
    else:
        verdict = "WITHIN_OWN_RANGE"

    p_same, n_trans = _empirical_same_rate(counts, window)

    pre = None
    if commitment_date:
        pre_months = [m for m in sorted(counts) if m < commitment_date[:7]]
        if pre_months:
            pre = round(sum(counts[m] for m in pre_months) / float(len(pre_months)), 3)

    return {
        "side_a": side_a,
        "ucdp_events_osv_last_month": n_last,
        "ucdp_deaths_civilians_last_month": deaths.get(anchor, 0),
        "ucdp_events_osv_prior_3": prior_counts,
        "prior_3_months": prior,
        "mean_prior_3": round(mean_prior, 4),
        "ratio": ratio,
        "null_n_months": len(null_series),
        "null_p90": round(p90, 4) if p90 is not None else None,
        "verdict": verdict,
        "pre_commitment_monthly_rate": pre,
        "forecast": "SAME",
        "forecast_version": FORECAST_VERSION,
        "p": p_same,
        "p_basis": "empirical frequency of a SAME month-to-month direction over "
                   "this actor's own last %d months (n=%d transitions)" % (NULL_MONTHS, n_trans),
        "baseline_persistence": "SAME",
        "realized": None,
        "realized_month": None,
    }


def unknown_actor_line(rows, country: str, anchor: str) -> dict:
    """UCDP's XXXnnn perpetrators, counted separately and charged to nobody."""
    events = [r for r in uc.osv_events(rows, country) if uc.is_unknown_actor(r["side_a"])]
    counts = uc.monthly_counts(events)
    prior = uc.prior_months(anchor, PRIOR_K)
    return {
        "side_a": "actor_unknown (UCDP XXXnnn)",
        "ucdp_events_osv_last_month": counts.get(anchor, 0),
        "ucdp_events_osv_prior_3": [counts.get(m, 0) for m in prior],
        "note": "never charged to a party to any commitment",
    }


def context_line(rows, anchor: str, register: dict) -> dict:
    """The place with the largest rise, whether or not anybody promised anything.

    commitment_id is null EXPLICITLY when the riser has no commitment, and the
    line is published anyway. A register that only ever reports places it already
    watches would confirm itself forever.
    """
    watched = {c["ucdp_country"] for c in register["commitments"]}
    best = None
    for country in {r["country"] for r in rows if r["type_of_violence"] == uc.OSV}:
        counts = uc.monthly_counts(uc.osv_events(rows, country))
        prior = [counts.get(m, 0) for m in uc.prior_months(anchor, PRIOR_K)]
        mean_prior = sum(prior) / float(PRIOR_K)
        if mean_prior < 1:            # a rise from near-nothing is not a rise
            continue
        n_last = counts.get(anchor, 0)
        ratio = n_last / mean_prior
        window = _months_back(anchor, NULL_MONTHS)
        p90 = uc.percentile(uc.ratio_series(counts, window, PRIOR_K), RISE_PERCENTILE)
        if p90 is None or ratio <= p90:
            continue
        if best is None or ratio > best["ratio"]:
            top = sorted(uc.monthly_counts(uc.osv_events(rows, country)).items())
            actors = {}
            for r in uc.osv_events(rows, country):
                if uc.month_of(r) == anchor:
                    actors[r["side_a"]] = actors.get(r["side_a"], 0) + 1
            top_actor = max(actors.items(), key=lambda kv: kv[1])[0] if actors else None
            best = {"place": country, "ratio": round(ratio, 4),
                    "ucdp_events_osv_last_month": n_last,
                    "mean_prior_3": round(mean_prior, 4),
                    "null_p90": round(p90, 4),
                    "top_actor": top_actor,
                    "top_actor_is_party_to_a_commitment": None,
                    "commitment_id": None,
                    "watched_place": country in watched,
                    "_series_len": len(top)}
    return best or {"place": None, "note": "no place rose above its own p90 this month"}


def build(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    register = load_register()
    cls, why = reporter_class()
    rows, as_of = uc.load_events()
    anchor = uc.last_complete_month(rows)

    lines = []
    for c in register["commitments"]:
        actors = []
        for a in c["actor_strings"][SOURCE_ID]:
            line = actor_line(rows, c["ucdp_country"], a["side_a"], anchor, c["date"])
            line["link"] = a["link"]
            line["party"] = a["party"]
            line["window_from"] = a["from"]
            line["window_to"] = a["to"]
            actors.append(line)
        lines.append({
            "ts": now.isoformat(),
            "kind": "commitment",
            "experiment": NAME,
            "commitment_id": c["id"],
            "place": c["place"],
            "ucdp_country": c["ucdp_country"],
            "commitment_title": c["title"],
            "commitment_date": c["date"],
            "register_status": c["status"],
            "anchor_month": anchor,
            "as_of": as_of,
            "source": SOURCE_ID,
            "reporter_class": cls,
            "actors": actors,
            "actor_unknown": unknown_actor_line(rows, c["ucdp_country"], anchor),
            "witness": None,
            "witness_reason": None,
        })

    ctx = context_line(rows, anchor, register)
    ctx.update({"ts": now.isoformat(), "kind": "context", "experiment": NAME,
                "anchor_month": anchor, "as_of": as_of, "source": SOURCE_ID,
                "reporter_class": cls, "witness": None, "witness_reason": None})
    lines.append(ctx)
    return {"anchor": anchor, "as_of": as_of, "reporter_class": cls,
            "reporter_why": why, "lines": lines}


def score(ledger: Path = LEDGER) -> dict:
    """Fill `realized` on past lines whose next month the release now carries.

    Hit-rate is reported against persistence AND against a shuffled control. The
    control matters more than it looks: v0 IS persistence, so v0 vs persistence
    is a tie by construction and the only informative comparison is whether
    either beats a forecast with the labels shuffled.
    """
    if not ledger.exists():
        return {"scored": 0, "note": "no ledger yet"}
    rows, _as_of = uc.load_events()
    register = load_register()
    country_of = {c["id"]: c["ucdp_country"] for c in register["commitments"]}

    out = []
    changed = 0
    for raw in ledger.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        if rec.get("kind") != "commitment":
            out.append(rec)
            continue
        nxt = uc.prior_months(rec["anchor_month"], -1) if False else None
        y, m = int(rec["anchor_month"][:4]), int(rec["anchor_month"][5:7])
        m += 1
        if m == 13:
            y, m = y + 1, 1
        next_month = "%04d-%02d" % (y, m)
        have = {uc.month_of(r) for r in rows}
        for a in rec.get("actors", []):
            if a.get("realized") is not None or next_month not in have:
                continue
            counts = uc.monthly_counts(
                uc.osv_events(rows, country_of[rec["commitment_id"]], a["side_a"]))
            a["realized"] = _direction(counts.get(rec["anchor_month"], 0),
                                       counts.get(next_month, 0))
            a["realized_month"] = next_month
            changed += 1
        out.append(rec)

    if changed:
        ledger.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
                          encoding="utf-8")

    judged = [(a["forecast"], a["realized"])
              for r in out if r.get("kind") == "commitment"
              for a in r.get("actors", []) if a.get("realized")]
    if not judged:
        return {"scored": changed, "n_judged": 0,
                "note": "nothing matured yet — UCDP releases a month about six weeks late"}
    hits = sum(1 for f, z in judged if f == z)
    rng = random.Random(SHUFFLE_SEED)
    labels = [z for _f, z in judged]
    shuffled = labels[:]
    rng.shuffle(shuffled)
    ctrl = sum(1 for (f, _z), s in zip(judged, shuffled) if f == s)
    return {
        "scored": changed,
        "n_judged": len(judged),
        "hit_rate_v0": round(hits / len(judged), 4),
        "hit_rate_persistence": round(hits / len(judged), 4),
        "hit_rate_shuffled_control": round(ctrl / len(judged), 4),
        "note": "v0 IS persistence, so those two are equal by construction; the "
                "shuffled control is the only informative comparison",
    }


def selftest() -> dict:
    out = {"register": str(REGISTER), "ledger": str(LEDGER)}
    out["register_exists"] = "LIVE" if REGISTER.exists() else "INERT"
    try:
        cls, _why = reporter_class()
        out["reporter_class"] = "LIVE (%s -> %s)" % (REPORTER_KEY, cls)
    except (Unmapped, OSError) as e:
        out["reporter_class"] = "INERT (%s)" % e
    out["ucdp_client"] = uc.selftest()
    bat = REPO / "tools" / "prophecy_morning.bat"
    out["caller"] = ("LIVE" if bat.exists() and "institution0_morning" in
                     bat.read_text(encoding="utf-8", errors="replace") else "INERT (no caller)")
    out["ledger_lines"] = len(LEDGER.read_text(encoding="utf-8").splitlines()) \
        if LEDGER.exists() else 0
    return out


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
        return 0
    if "--score" in argv:
        print(json.dumps(score(), ensure_ascii=False, indent=2))
        return 0
    board = build()
    if "--write" in argv:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            for line in board["lines"]:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        print("appended %d line(s) to %s" % (len(board["lines"]), LEDGER))
        print(json.dumps(score(), ensure_ascii=False, indent=2))
    else:
        for line in board["lines"]:
            print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
