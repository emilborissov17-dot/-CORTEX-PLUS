#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/daily_board.py — ONE NUMBER PER EXPERIMENT, EVERY MORNING.

Emil, 17 September 2026: "an experiment that does not show a number every day is
built wrong. Long horizons are for the verdict, not for visibility."

WHAT THIS IS
------------
Six running experiments, six rows, rewritten every morning by
tools/prophecy_morning.bat as a :step after agi_scoreboard. Columns:

    name | what ran last night | today's number | yesterday's number | needs correction?

WHAT A REFUSAL LOOKS LIKE HERE, AND THE FORBIDDEN FALLBACK
----------------------------------------------------------
A row whose source file is absent, unparseable, or holds no usable record
prints **MISSING** and the path it looked at. That is the row's success state
for that morning — it is not an error and it does not stop the other five.

THE FORBIDDEN FALLBACKS, NAMED SO THEY CANNOT BE WRITTEN BACK IN BY ACCIDENT:

  1. a default (0, 0.0, "n/a", "--") standing where a measurement should be;
  2. **yesterday's number carried into today's column** — the failure that makes
     a dead experiment look alive for as long as nobody checks the mtime.

The net behind that instruction is STRUCTURAL, not a promise: `build_rows()`
takes no previous board and cannot read one — it is a pure function of a repo
root and a clock. Only `render()` sees the previous board, and only to fill the
*yesterday* column. `test/test_daily_board_missing.py` deletes each source in a
copy of this repo and asserts the row says MISSING while the yesterday column
still shows the old number beside it; a second test asserts the signature, so
re-introducing the fallback breaks a test rather than a morning.

EVERY NUMBER CARRIES THE NAME OF THE STATISTIC THAT PRODUCED IT.
claude/reports/SCOREBOARD_LABEL_AUDIT_2026-09-17.md found five values printed
with no statistic named and one (row 7) printed under the wrong one. A number
under a false name survives review precisely because everything about it looks
right. So: "MAE", "Brier", "success-rate difference", "selectivity" — the word
over the number names the arithmetic under it, or the number does not print.

YESTERDAY'S NUMBER COMES OFF DISK, NEVER OFF A RECOMPUTE.
Each board carries a machine block (a fenced JSON object at the bottom) holding
today's headline per row id. Tomorrow reads the newest dated board strictly
before today from claude/reports/daily_board/ and copies those strings. If no
such file exists the column says so in words. A recomputed "yesterday" would
silently rewrite history every time an input changed underneath it.

Usage:
  venv\\Scripts\\python.exe tools/daily_board.py              # print, write nothing
  venv\\Scripts\\python.exe tools/daily_board.py --write      # write board + dated copy
  venv\\Scripts\\python.exe tools/daily_board.py --selftest   # LIVE/INERT per integration
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]

BOARD = "claude/reports/DAILY_BOARD.md"
ARCHIVE = "claude/reports/daily_board"

# ---------------------------------------------------------------------------
# SOURCES. One entry per row id: every path this file will ever read.
# --selftest prints LIVE/INERT off exactly this table, so a source that moves
# and is not corrected here is reported, not silently defaulted.
# ---------------------------------------------------------------------------
SOURCES: dict[str, list[str]] = {
    "t1": ["memory/t1_result_full.json"],
    "probe": ["claude/reports/BRAIN_PROBE_*.json"],
    "selfmodel": ["experiments/prophecy/prophecy_ledger.jsonl",
                  "memory/existence_ledger.jsonl"],
    "world": ["experiments/prophecy/prophecy_ledger.jsonl"],
    "fresh": ["memory/measurement_honesty_latest.json",
              "memory/daily_tier.jsonl"],
    "local": ["memory/llm_provenance.jsonl"],
}

# ---------------------------------------------------------------------------
# THE CORRECTION THRESHOLDS, declared rather than buried inside an `if`. A row
# says "yes" when its own condition below is true, and the condition is printed
# beside the answer, so "needs correction" is never an opinion held by this file.
# ---------------------------------------------------------------------------
FRESH_K1_FLOOR = 0.10          # k1_fresh below this: the goal is measured, but stale
MOVED_SHARE_FLOOR = 0.10       # share of dated daily indicators that changed value
LOCAL_SHARE_FLOOR = 0.25       # local:* share of the day's logged answers
SELECTIVITY_FLOOR = 0.10       # probe real minus control; below this the probe reads noise
EQ_DECIMALS = 3                # "equals the baseline to N decimals"

MACHINE_OPEN = "```json machine"
MACHINE_CLOSE = "```"

TERMINAL_EVENTS = ("CYCLE_FINISHED", "CYCLE_DIED", "CYCLE_KILLED")


class SourceMissing(Exception):
    """Raised, never returned — a caller that forgets to catch it gets a traceback,
    not a zero. Carries the path so the row can print where it looked."""

    def __init__(self, path: Any, why: str = "not on disk"):
        self.path = str(path)
        self.why = why
        super().__init__("{}: {}".format(self.path, why))


# --------------------------------------------------------------------------- readers
def _require(p: Path) -> Path:
    if not p.exists():
        raise SourceMissing(p, "not on disk")
    if not p.is_file():
        raise SourceMissing(p, "is not a file")
    return p


def _json(p: Path) -> Any:
    _require(p)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SourceMissing(p, "unreadable: {}".format(type(e).__name__)) from e


def _jsonl(p: Path) -> list[dict]:
    _require(p)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise SourceMissing(p, "unreadable: {}".format(type(e).__name__)) from e
    out, torn = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            torn += 1
    if not out:
        raise SourceMissing(p, "no readable record ({} torn line(s))".format(torn))
    return out


def _newest(repo: Path, pattern: str) -> Path:
    hits = sorted(repo.glob(pattern))
    if not hits:
        raise SourceMissing(repo / pattern, "no file matches this pattern")
    return hits[-1]


def _age_days(ts: Any, now: datetime) -> Optional[float]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return round((now - d).total_seconds() / 86400.0, 2)


def _ran(ts: Any, now: datetime, what: str) -> str:
    age = _age_days(ts, now)
    if age is None:
        return "{} — run timestamp unparseable ({!r})".format(what, ts)
    if age <= 1.0:
        return "{}, {:.2f} d ago ({})".format(what, age, ts)
    return ("nothing — {} last ran {:.2f} d ago ({}) and has not been re-run"
            .format(what, age, ts))


# --------------------------------------------------------------------------- rows
def row_t1(repo: Path, now: datetime) -> dict:
    """Row 1 — T1 transfer test: the verdict and the three pre-registered differences."""
    src = repo / SOURCES["t1"][0]
    d = _json(src)
    dec = d.get("decomposition") or {}
    if not dec or "verdict" not in d:
        raise SourceMissing(src, "no verdict/decomposition in the file")

    def diff(key: str) -> str:
        x = dec.get(key) or {}
        return "{} (95% CI [{}, {}], n={})".format(x.get("diff"), x.get("lo"), x.get("hi"), x.get("n"))

    cond = d.get("conditions") or {}
    head = "verdict {} · success-rate difference on-off = {}".format(d["verdict"], diff("total_on_minus_off"))
    detail = [
        "- success rate (share of trials whose stated direction was correct): on {} · off {} · shuffled {}"
        .format(d["success_rate"]["on"], d["success_rate"]["off"], d["success_rate"]["shuffled"]),
        "- Brier score (mean squared error of the stated probability): on {} · off {} · shuffled {}"
        .format(d["brier"]["on"], d["brier"]["off"], d["brier"]["shuffled"]),
        "- success-rate difference, total (on - off): {}".format(diff("total_on_minus_off")),
        "- success-rate difference, retrieval-specific (on - shuffled): {}"
        .format(diff("retrieval_on_minus_shuffled")),
        "- success-rate difference, format (shuffled - off): {}".format(diff("format_shuffled_minus_off")),
        "- every interval is a paired bootstrap, 10,000 resamples over tasks",
        "- pre-registered acceptance conditions met: {}/{}"
        .format(sum(1 for v in cond.values() if v), len(cond)),
        "- parse failures (on/off/shuffled) {}/{}/{} · transport errors {}/{}/{} — the Brier "
        "comparison is {}void".format(
            (d.get("parse_failures") or {}).get("on"), (d.get("parse_failures") or {}).get("off"),
            (d.get("parse_failures") or {}).get("shuffled"),
            (d.get("transport_errors") or {}).get("on"), (d.get("transport_errors") or {}).get("off"),
            (d.get("transport_errors") or {}).get("shuffled"),
            "" if d.get("brier_comparison_void") else "not "),
    ]
    fails = d["verdict"] != "PASS"
    return {
        "id": "t1", "name": "T1 transfer test",
        "ran": _ran(d.get("ts"), now, "tools/transfer_test.py ({})".format(d.get("model"))),
        "headline": head, "detail": detail,
        "correction": "yes" if fails else "no",
        "why": ("verdict is {} with {}/{} pre-registered conditions met — the design, not the run, "
                "is what has to change (condition: verdict != PASS)"
                .format(d["verdict"], sum(1 for v in cond.values() if v), len(cond))
                if fails else "verdict is PASS (condition: verdict != PASS)"),
        "sources": [src.relative_to(repo).as_posix()],
    }


def row_probe(repo: Path, now: datetime) -> dict:
    """Row 2 — brain probe: best layer, its control, spoken vs probe, four memory conditions."""
    src = _newest(repo, SOURCES["probe"][0])
    d = _json(src)
    a = d.get("A_best_layer") or {}
    b = d.get("B_best_layer") or {}
    sp = d.get("B_spoken") or {}
    cond = d.get("C_conditions") or {}
    if not b or not cond:
        raise SourceMissing(src, "no B_best_layer / C_conditions in the file")

    head = ("best layer {} · probe accuracy real {} / control {} / selectivity (real - control) {}"
            .format(b.get("layer"), b.get("real"), b.get("control"), b.get("selectivity")))
    detail = [
        "- A, primitive identity, best layer {}: probe accuracy real {} · control {} · "
        "selectivity {} · chance {}".format(a.get("layer"), a.get("real"), a.get("control"),
                                            a.get("selectivity"), a.get("chance")),
        "- B, direction, best layer {}: probe accuracy real {} · control {} · selectivity {} · chance {}"
        .format(b.get("layer"), b.get("real"), b.get("control"), b.get("selectivity"), b.get("chance")),
        "- spoken accuracy (share of {} answers whose stated direction was correct): {} "
        "· refusals {} — against probe accuracy {} at layer {}"
        .format(sp.get("n"), sp.get("accuracy"), sp.get("refusals"), b.get("real"), b.get("layer")),
    ]
    for name in ("filler", "true", "all_up", "all_down"):
        c = cond.get(name) or {}
        detail.append(
            "- condition {}: spoken accuracy {} · spoken up-rate {} · probe accuracy {} · n {} · refusals {}"
            .format(name, c.get("spoken_accuracy"), c.get("spoken_up_rate"),
                    c.get("probe_accuracy", "not measured"), c.get("n"), c.get("refusals")))

    chance = float(b.get("chance") or 0.5)
    under = sorted(k for k, c in cond.items()
                   if isinstance(c.get("probe_accuracy"), (int, float))
                   and float(c["probe_accuracy"]) < chance)
    thin = float(b.get("selectivity") or 0.0) < SELECTIVITY_FLOOR
    why = []
    if under:
        why.append("probe accuracy is below chance ({}) in condition(s) {} — the layer-{} probe does "
                   "not transfer to the memory conditions it was read out on"
                   .format(chance, ", ".join(under), d.get("C_probe_layer")))
    if thin:
        why.append("selectivity {} < {}".format(b.get("selectivity"), SELECTIVITY_FLOOR))
    return {
        "id": "probe", "name": "Brain probe (scanner)",
        "ran": _ran(d.get("ts"), now, "tools/brain_probe.py ({})".format(d.get("model"))),
        "headline": head, "detail": detail,
        "correction": "yes" if why else "no",
        "why": ("; ".join(why) if why else
                "selectivity >= {} and no condition's probe accuracy is below chance"
                .format(SELECTIVITY_FLOOR)),
        "sources": [src.relative_to(repo).as_posix()],
    }


def row_selfmodel(repo: Path, now: datetime) -> dict:
    """Row 3 — what the self-model predicted about last night, against what happened."""
    led = repo / SOURCES["selfmodel"][0]
    exi = repo / SOURCES["selfmodel"][1]
    recs = _jsonl(led)
    events = _jsonl(exi)

    term = [e for e in events if e.get("event") in TERMINAL_EVENTS]
    if not term:
        raise SourceMissing(exi, "no terminal cycle event on the existence ledger")
    if len(term) < 2:
        raise SourceMissing(exi, "only one terminal cycle event — no anchor to have predicted from")
    last, prev = term[-1], term[-2]

    anchor = "next_cycle_after::{}".format(prev.get("ts"))
    sealed = [r for r in recs if r.get("event") == "PREDICTION_SEALED" and r.get("target_id") == anchor]
    scored = {r.get("ref_hash"): r for r in recs if r.get("event") == "OUTCOME_SCORED"}
    if not sealed:
        raise SourceMissing(led, "no prediction sealed against the anchor {}".format(anchor))

    actual = ("cycle {} {} after {} s, {} steps completed, {} degraded"
              .format(last.get("cycle_id"), last.get("event"), last.get("duration_sec"),
                      last.get("steps_completed"), last.get("degraded_steps")))
    detail = ["- what happened: {}".format(actual),
              "- anchor the predictions were sealed against: {}".format(anchor)]
    open_kinds, closed = [], []
    for s in sealed:
        kind = s.get("target_kind")
        o = scored.get(s.get("hash"))
        if o is None:
            open_kinds.append(str(kind))
            detail.append(
                "- {}: SEALED, NOT YET SCORED — learner {} vs baseline {}; no error is computed "
                "here, experiments/prophecy/self_forecast.py --score owns that arithmetic"
                .format(kind, s.get("learner"), s.get("baseline")))
            continue
        rule = str(o.get("rule") or "")
        rule = ("Brier (mean squared error)" if rule == "brier"
                else (rule or "MAE (mean absolute error)"))
        closed.append((str(kind), bool(o.get("learner_wins"))))
        detail.append(
            "- {}: sealed learner {} vs baseline {}; actual {}; {} learner {} vs baseline {} "
            "-> learner_wins {}".format(kind, s.get("learner"), s.get("baseline"), o.get("actual"),
                                        rule, o.get("learner_err"), o.get("baseline_err"),
                                        o.get("learner_wins")))

    if closed:
        wins = sum(1 for _, w in closed if w)
        head = ("{}/{} scored self-predictions beat their baseline on last night's cycle ({})"
                .format(wins, len(closed), ", ".join(k for k, _ in closed)))
    else:
        head = ("{} self-prediction(s) sealed for last night, none scored yet ({}); "
                "actual duration {} s".format(len(open_kinds), ", ".join(open_kinds),
                                              last.get("duration_sec")))
    lost = [k for k, w in closed if not w]
    why = []
    if open_kinds:
        why.append("{} prediction(s) still open at board time — self_forecast --score runs earlier "
                   "in the same 09:00 batch, so an open row here means the board was built before "
                   "it or the scorer refused".format(len(open_kinds)))
    if lost:
        why.append("baseline beat the learner on {}".format(", ".join(lost)))
    return {
        "id": "selfmodel", "name": "Self-model",
        "ran": actual, "headline": head, "detail": detail,
        "correction": "yes" if why else "no",
        "why": ("; ".join(why) if why else
                "every self-prediction sealed for last night is scored and beat its baseline"),
        "sources": [led.relative_to(repo).as_posix(), exi.relative_to(repo).as_posix()],
    }


def row_world(repo: Path, now: datetime) -> dict:
    """Row 4 — world forecasts, learner against the naive persistence baseline.

    MAE and Brier are BOTH named here, and one of them is named as absent: the
    world loop seals point values, so a Brier score has nothing to be computed
    over. Printing a 0/1 direction hit-rate under the word Brier would be exactly
    the defect the label audit found in scoreboard row 7 (fixed in a6cd0f2), and
    it is not repeated here.
    """
    led = repo / SOURCES["world"][0]
    recs = _jsonl(led)
    sealed = {r["hash"]: r for r in recs if r.get("event") == "PREDICTION_SEALED" and "hash" in r}
    pairs = [(sealed[o["ref_hash"]], o) for o in recs
             if o.get("event") == "OUTCOME_SCORED" and o.get("ref_hash") in sealed
             and sealed[o["ref_hash"]].get("target_kind") == "world_next"]
    w_sealed = [r for r in sealed.values() if r.get("target_kind") == "world_next"]
    if not w_sealed:
        raise SourceMissing(led, "no world_next prediction on the ledger")

    def eq_to_dp(r: dict) -> bool:
        try:
            return round(float(r["learner"]), EQ_DECIMALS) == round(float(r["baseline"]), EQ_DECIMALS)
        except (TypeError, ValueError, KeyError):
            return False

    def eq_exactly(r: dict) -> bool:
        try:
            return float(r["learner"]) == float(r["baseline"])
        except (TypeError, ValueError, KeyError):
            return False

    def mae(sel: list) -> tuple:
        """MAE of learner and baseline over the selected pairs, and the head-to-head count.

        The same arithmetic as experiments/prophecy/scoreboard.py's mae(): the mean of
        the `learner_err`/`baseline_err` the ledger sealed, which are absolute errors.
        """
        ls = [float(o["learner_err"]) for _, o in sel if o.get("learner_err") is not None]
        bs = [float(o["baseline_err"]) for _, o in sel if o.get("baseline_err") is not None]
        return (round(sum(ls) / len(ls), 4) if ls else None,
                round(sum(bs) / len(bs), 4) if bs else None,
                sum(1 for l, b in zip(ls, bs) if l < b), len(ls))

    # Two exclusion rules, both named, because they give different numbers and only
    # one of them agrees with PROPHECY_SCOREBOARD.md. Reporting the strict one alone
    # under the bare word "MAE" would put two different statistics under one name
    # across two files — the failure the label audit exists to stop.
    exact_live = [(s, o) for s, o in pairs if not eq_exactly(s)]
    dp_live = [(s, o) for s, o in pairs if not eq_to_dp(s)]
    mae_l, mae_b, wins, n_exact = mae(exact_live)
    smae_l, smae_b, swins, n_dp = mae(dp_live)

    today = now.date().isoformat()
    sealed_today = [r for r in w_sealed if str(r.get("ts", ""))[:10] == today]
    scored_today = [o for _, o in pairs if str(o.get("ts", ""))[:10] == today]
    eq_today = [r for r in sealed_today if eq_to_dp(r)]
    eq_all = [r for r in w_sealed if eq_to_dp(r)]
    eq_exact = [r for r in w_sealed if eq_exactly(r)]

    head = ("MAE (mean absolute error) learner {} vs naive-persistence baseline {} over n={} "
            "scored, exact ties excluded; {} vs {} over n={} with ties to {} decimals also "
            "excluded · Brier NOT DEFINED for this row"
            .format(mae_l, mae_b, n_exact, smae_l, smae_b, n_dp, EQ_DECIMALS))
    detail = [
        "- MAE (mean absolute error of the point forecast), excluding pairs where learner and "
        "baseline were sealed EXACTLY equal — the rule experiments/prophecy/scoreboard.py uses, "
        "so this number is the one in PROPHECY_SCOREBOARD.md: learner {} vs baseline {}, learner "
        "closer in {}/{}".format(mae_l, mae_b, wins, n_exact),
        "- MAE, excluding pairs equal to {} decimals as well: learner {} vs baseline {}, learner "
        "closer in {}/{}. This is the honest head-to-head — the {} near-ties the first rule keeps "
        "are pairs where the learner IS the baseline to display precision, and they pull both "
        "means toward each other.".format(EQ_DECIMALS, smae_l, smae_b, swins, n_dp,
                                          n_exact - n_dp),
        "- Brier (mean squared error of a stated probability): NOT DEFINED for world_next. "
        "experiments/prophecy/world_forecast.py seals a point value, not a probability, and "
        "experiments/prophecy/scoreboard.py:62 PROB_KINDS does not contain world_next. A 0/1 "
        "direction hit-rate printed under the word Brier would be the row-7 mislabel again, so "
        "this row prints the absence instead of a number.",
        "- sealed this morning ({}): {}, of which {} equal the baseline to {} decimals"
        .format(today, len(sealed_today), len(eq_today), EQ_DECIMALS),
        "- scored this morning: {}".format(len(scored_today)),
        "- sealed all time: {}, of which {} equal the baseline to {} decimals and only {} are "
        "equal exactly — the {} in between are counted as live comparisons by scoreboard.py's "
        "exact-equality _is_degenerate()".format(len(w_sealed), len(eq_all), EQ_DECIMALS,
                                                 len(eq_exact), len(eq_all) - len(eq_exact)),
    ]
    for r in eq_today[:8]:
        detail.append("    equal to {} dp: {} learner {} vs baseline {}"
                      .format(EQ_DECIMALS, r.get("indicator"), r.get("learner"), r.get("baseline")))
    needs = bool(eq_today)
    return {
        "id": "world", "name": "World forecasts",
        "ran": "{} world_next sealed and {} scored on {}".format(len(sealed_today), len(scored_today), today),
        "headline": head, "detail": detail,
        "correction": "yes" if needs else "no",
        "why": ("{}/{} forecasts sealed this morning are the baseline to {} decimals — EWMA on a "
                "near-flat series is persistence with a rounding tail, and exact-equality "
                "degeneracy does not catch it".format(len(eq_today), len(sealed_today), EQ_DECIMALS)
                if needs else
                "no forecast sealed today equals its baseline to {} decimals".format(EQ_DECIMALS)),
        "sources": [led.relative_to(repo).as_posix()],
    }


def row_fresh(repo: Path, now: datetime) -> dict:
    """Row 5 — how much of the goal rests on a recent observation, and what actually moved."""
    hon = repo / SOURCES["fresh"][0]
    tier = repo / SOURCES["fresh"][1]
    h = _json(hon)
    if "k1_fresh" not in h:
        raise SourceMissing(hon, "no k1_fresh field in the file")
    rows = _jsonl(tier)

    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        ind, date = r.get("indicator"), r.get("date")
        if ind is None or date is None:
            continue
        by.setdefault(str(ind), {})[str(date)] = r.get("value")
    latest = max((d for dates in by.values() for d in dates), default=None)
    if latest is None:
        raise SourceMissing(tier, "no dated observation in the daily tier")

    moved = unchanged = no_earlier = 0
    for dates in by.values():
        if latest not in dates:
            continue
        earlier = [d for d in sorted(dates) if d < latest]
        if not earlier:
            no_earlier += 1
        elif float(dates[latest]) != float(dates[earlier[-1]]):
            moved += 1
        else:
            unchanged += 1
    dated = moved + unchanged + no_earlier
    share = round(moved / dated, 4) if dated else None

    head = ("k1_fresh {} (share of goal weight resting on an observation no older than {} days) "
            "· {}/{} daily indicators moved".format(h["k1_fresh"], h.get("fresh_window_days"),
                                                    moved, dated))
    detail = [
        "- k1 {} — share of goal weight whose axis is MEASURED and names the external observation "
        "that measured it".format(h.get("k1")),
        "- k1_fresh {} — of that, the share dated within {} days: {} of {} total weight "
        "({} measured)".format(h.get("k1_fresh"), h.get("fresh_window_days"), h.get("fresh_weight"),
                               (h.get("honest_composite") or {}).get("total_weight"),
                               h.get("measured_weight")),
        "- undated weight {} — counts toward k1, is neither fresh nor stale, only unaudited"
        .format(h.get("undated_weight")),
        "- oldest dated observation: {} at {} days".format(h.get("oldest_axis"),
                                                           h.get("max_observation_age_days")),
        "- daily tier, latest observation date {}: {} indicators carry a row dated that day; {} "
        "changed value against that indicator's most recent earlier dated row (share {}), {} are "
        "identical, {} have no earlier row to compare".format(latest, dated, moved, share,
                                                              unchanged, no_earlier),
    ]
    thin_k1 = float(h["k1_fresh"]) < FRESH_K1_FLOOR
    thin_move = share is not None and share < MOVED_SHARE_FLOOR
    why = []
    if thin_k1:
        why.append("k1_fresh {} < {}".format(h["k1_fresh"], FRESH_K1_FLOOR))
    if thin_move:
        why.append("moved share {} < {} — the daily tier is recording the same numbers again, so "
                   "the world loop has almost nothing to learn from".format(share, MOVED_SHARE_FLOOR))
    return {
        "id": "fresh", "name": "Data freshness",
        "ran": ("core/daily_tier.py recorded {} rows dated {}; measurement honesty written {}"
                .format(sum(1 for r in rows if str(r.get("date")) == latest), latest, h.get("ts"))),
        "headline": head, "detail": detail,
        "correction": "yes" if why else "no",
        "why": ("; ".join(why) if why else
                "k1_fresh >= {} and moved share >= {}".format(FRESH_K1_FLOOR, MOVED_SHARE_FLOOR)),
        "sources": [hon.relative_to(repo).as_posix(), tier.relative_to(repo).as_posix()],
    }


def row_local(repo: Path, now: datetime) -> dict:
    """Row 6 — is the local brain answering at all today."""
    src = repo / SOURCES["local"][0]
    recs = _jsonl(src)
    today = now.date().isoformat()
    day = [r for r in recs if str(r.get("ts", ""))[:10] == today]
    local = [r for r in day if str(r.get("backend", "")).startswith("local:")]
    cloud = len(day) - len(local)
    tally: dict[str, int] = {}
    for r in day:
        key = str(r.get("backend"))
        tally[key] = tally.get(key, 0) + 1
    share = round(len(local) / len(day), 4) if day else None

    if not local:
        head = "LOCAL BRAIN SILENT — 0 local:* answers of {} logged since 00:00 UTC".format(len(day))
    else:
        head = ("{} local:* answers of {} logged since 00:00 UTC (count of rows whose backend "
                "starts with 'local:'), {} cloud".format(len(local), len(day), cloud))
    detail = ["- counted over rows of memory/llm_provenance.jsonl whose ts falls on the UTC day {}"
              .format(today),
              "- local {} · cloud {} · local share {}".format(len(local), cloud, share)]
    detail += ["    {}: {}".format(k, v) for k, v in sorted(tally.items(), key=lambda kv: -kv[1])]
    silent = not local
    thin = share is not None and share < LOCAL_SHARE_FLOOR
    return {
        "id": "local", "name": "Local brain alive",
        "ran": "{} logged model answers on {}, {} of them local".format(len(day), today, len(local)),
        "headline": head, "detail": detail,
        "correction": "yes" if (silent or thin) else "no",
        "why": ("no local answer today — ollama is down, or every caller routed to cloud"
                if silent else
                ("local share {} < {}".format(share, LOCAL_SHARE_FLOOR) if thin else
                 "local share {} >= {}".format(share, LOCAL_SHARE_FLOOR))),
        "sources": [src.relative_to(repo).as_posix()],
    }


BUILDERS = [
    ("t1", "T1 transfer test", row_t1),
    ("probe", "Brain probe (scanner)", row_probe),
    ("selfmodel", "Self-model", row_selfmodel),
    ("world", "World forecasts", row_world),
    ("fresh", "Data freshness", row_fresh),
    ("local", "Local brain alive", row_local),
]


def build_rows(repo: Path, now: datetime) -> list[dict]:
    """The whole board, computed from `repo` and the clock AND NOTHING ELSE.

    There is deliberately no previous-board parameter: a fallback to yesterday's
    number cannot be written here without changing this signature, and
    test/test_daily_board_missing.py asserts the signature.
    """
    out = []
    for rid, name, fn in BUILDERS:
        try:
            out.append(fn(repo, now))
        except SourceMissing as miss:
            out.append({
                "id": rid, "name": name, "status": "MISSING",
                "ran": "MISSING — {} ({})".format(miss.path, miss.why),
                "headline": "MISSING — {}".format(miss.path),
                "detail": ["- source unusable: {} ({}). No number is printed for this row today, "
                           "and yesterday's is NOT carried forward.".format(miss.path, miss.why)],
                "correction": "yes",
                "why": "source unusable: {} ({})".format(miss.path, miss.why),
                "sources": SOURCES.get(rid, []),
            })
    return out


# --------------------------------------------------------------------------- previous board
def read_machine_block(text: str) -> dict:
    """The {row id: headline} map a previous board wrote about ITSELF."""
    m = re.search(re.escape(MACHINE_OPEN) + r"\n(.*?)\n" + re.escape(MACHINE_CLOSE), text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def previous_board(repo: Path, today: str) -> tuple[Optional[str], dict]:
    """The newest dated board STRICTLY BEFORE today. Never today's own file."""
    d = repo / ARCHIVE
    if not d.exists():
        return None, {}
    dated = sorted(p for p in d.glob("????-??-??.md") if p.stem < today)
    if not dated:
        return None, {}
    p = dated[-1]
    return p.stem, read_machine_block(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- render
def _cell(s: Any) -> str:
    """A markdown table cell: no newlines, no bare pipes."""
    return str(s).replace("|", "\\|").replace("\n", " ")


def render(rows: list[dict], now: datetime, prev_date: Optional[str], prev: dict) -> str:
    today = now.date().isoformat()
    yest = (prev.get("rows") or {})
    if prev_date is None:
        note = ("no earlier board on disk in `claude/reports/daily_board/` — this is the first "
                "one, so the yesterday column says so rather than showing a recompute")
    else:
        note = "copied verbatim from the machine block of `{}/{}.md`".format(ARCHIVE, prev_date)

    L = ["# DAILY BOARD — {}".format(today),
         "",
         "Written {} by `tools/daily_board.py`, run from `tools/prophecy_morning.bat` after the "
         "`agi_scoreboard` step.".format(now.isoformat()),
         "",
         "One row per running experiment. Every number is printed under the name of the statistic "
         "that produced it. A row whose source is unusable prints **MISSING** and the path — never "
         "a default, and never yesterday's number moved into today's column.",
         "",
         "Yesterday's column: {}.".format(note),
         "",
         "| experiment | what ran last night | today's number | yesterday's number | needs correction? |",
         "|---|---|---|---|---|"]
    for r in rows:
        y = yest.get(r["id"])
        if y is None:
            y = "no earlier board" if prev_date is None else "absent from the {} board".format(prev_date)
        L.append("| {} | {} | {} | {} | {} |".format(
            r["name"], _cell(r["ran"]), _cell(r["headline"]), _cell(y),
            _cell("**{}** — {}".format(r["correction"], r["why"]))))

    L += ["", "---", "", "## Detail, row by row", ""]
    for r in rows:
        L += ["### {}{}".format(r["name"], "  — MISSING" if r.get("status") == "MISSING" else ""),
              "",
              "Source(s): " + ", ".join("`{}`".format(s) for s in r.get("sources", [])),
              ""]
        L += list(r["detail"])
        L += ["", "Needs correction: **{}** — {}".format(r["correction"], r["why"]), ""]

    L += ["---", "",
          "Thresholds this board uses to answer *needs correction*, declared in "
          "`tools/daily_board.py` rather than buried in a condition:",
          "",
          "- `FRESH_K1_FLOOR = {}` · `MOVED_SHARE_FLOOR = {}` · `LOCAL_SHARE_FLOOR = {}` · "
          "`SELECTIVITY_FLOOR = {}` · `EQ_DECIMALS = {}`"
          .format(FRESH_K1_FLOOR, MOVED_SHARE_FLOOR, LOCAL_SHARE_FLOOR, SELECTIVITY_FLOOR, EQ_DECIMALS),
          "",
          "Regenerate by hand: `venv\\Scripts\\python.exe tools/daily_board.py --write`.",
          "",
          "The block below is what tomorrow's board reads for its *yesterday* column. It is written "
          "by this board about itself and is never recomputed by the reader.",
          "", MACHINE_OPEN,
          json.dumps({"date": today, "generated_utc": now.isoformat(),
                      "rows": {r["id"]: r["headline"] for r in rows},
                      "status": {r["id"]: r.get("status", "OK") for r in rows}},
                     ensure_ascii=False, indent=1),
          MACHINE_CLOSE, ""]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- selftest
def selftest(repo: Path = REPO) -> dict:
    """Which of this board's integrations are LIVE in the repo it finds itself in."""
    out: dict[str, Any] = {"repo": str(repo), "sources": {}}
    for rid, pats in SOURCES.items():
        for pat in pats:
            key = "{}:{}".format(rid, pat)
            if "*" in pat:
                hits = sorted(repo.glob(pat))
                out["sources"][key] = ("LIVE ({})".format(hits[-1].relative_to(repo).as_posix()) if hits
                                       else "INERT (no file matches)")
            else:
                p = repo / pat
                out["sources"][key] = ("LIVE ({} bytes)".format(p.stat().st_size) if p.exists()
                                       else "INERT (not on disk)")
    bat = repo / "tools" / "prophecy_morning.bat"
    srv = repo / "cockpit" / "server.py"
    tpl = repo / "cockpit" / "templates" / "cockpit.html"
    out["caller"] = ("LIVE (tools/prophecy_morning.bat runs daily_board)"
                     if bat.exists() and "daily_board" in bat.read_text(encoding="utf-8", errors="replace")
                     else "INERT (no caller in tools/prophecy_morning.bat)")
    out["cockpit_route"] = ("LIVE (/daily_board.md served by cockpit/server.py)"
                            if srv.exists() and "daily_board.md" in srv.read_text(encoding="utf-8", errors="replace")
                            else "INERT (no route in cockpit/server.py)")
    out["cockpit_link"] = ("LIVE (cockpit.html links /daily_board.md)"
                           if tpl.exists() and "daily_board.md" in tpl.read_text(encoding="utf-8", errors="replace")
                           else "INERT (no link in cockpit/templates/cockpit.html)")
    out["previous_board"] = (lambda d: "LIVE ({} dated boards)".format(len(list(d.glob("????-??-??.md"))))
                             if d.exists() else "INERT (no archive directory yet)")(repo / ARCHIVE)
    return out


def main(argv: list[str]) -> int:
    repo = REPO
    now = datetime.now(timezone.utc)
    if "--selftest" in argv:
        print(json.dumps(selftest(repo), ensure_ascii=False, indent=2))
        return 0
    rows = build_rows(repo, now)
    today = now.date().isoformat()
    prev_date, prev = previous_board(repo, today)
    text = render(rows, now, prev_date, prev)
    if "--write" in argv:
        board = repo / BOARD
        board.parent.mkdir(parents=True, exist_ok=True)
        board.write_text(text, encoding="utf-8")
        arch = repo / ARCHIVE / "{}.md".format(today)
        arch.parent.mkdir(parents=True, exist_ok=True)
        arch.write_text(text, encoding="utf-8")
        print("wrote {}".format(board))
        print("wrote {}".format(arch))
        missing = [r["id"] for r in rows if r.get("status") == "MISSING"]
        if missing:
            print("MISSING rows: " + ", ".join(missing))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
