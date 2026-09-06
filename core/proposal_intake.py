#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/proposal_intake.py — BORN GRADEABLE OR NOT BORN (Kimi Round 31, 5 Sep 2026).

Every proposal in memory/improvement_proposals.json was written by an LLM asked for
"a concrete action" and never asked what would show whether the action worked.
Measured on 5 Sep: 89 proposals, 0 measurable; 786 of 1323 training prompts are
"Action required for <AXIS>"; "measurable_goal" is literally solution[:80] in all
three injectors — a field whose NAME asserts a property the code never checks.
That is the defect this repo hunts, sitting in the one file the system learns from.

THE RULE, copied from the one that fixed hypothesis_intake: a proposal is admitted
only if it names
  * indicator      — an axis, or AXIS__metric, that evaluator.ground_truth resolves
                     TODAY (so it can be graded by the same code that grades
                     hypotheses; creation and grading cannot disagree);
  * expected_delta — a non-zero number, the movement it expects in that indicator;
  * deadline       — an ISO date after today and within MAX_HORIZON_DAYS.
Anything else is REFUSED at the door with the missing pieces named, and the refusal
is appended to memory/proposal_intake_refusals.jsonl. The refusal log is not a
graveyard: it is the curriculum the generator is retrained against.

REFUSED IS NOT DROPPED SILENTLY. Unlike proposal_gate (moral: flags, never drops),
this gate does keep ungradeable proposals OUT of the queue — a proposal nobody can
ever score must not reach self_modifier or the training corpus. But every refusal
leaves a line with a named reason, so "0 proposals injected" can always be
distinguished from "the injector broke".

What this does NOT do: change the generator. Tonight's cycle will most likely admit
0 and refuse everything — that is the honest state, and the first night the count
of refusals is a number instead of a feeling.

  venv\\Scripts\\python.exe -m core.proposal_intake --selftest
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
REFUSALS = REPO / "memory" / "proposal_intake_refusals.jsonl"

MAX_HORIZON_DAYS = 365
REQUIRED = ("indicator", "expected_delta", "deadline")

_INDICATOR_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?:__[a-z0-9_]+)?$")


def _default_resolver(axis: str, metric: str | None):
    """(value, why_not) through the grader's own resolver — the same function
    hypothesis_intake uses, so a proposal is gradeable iff a hypothesis about the
    same key would be."""
    try:
        from core.hypothesis_intake import _resolves
        return _resolves(axis, metric)
    except Exception as exc:  # the resolver itself is missing or broken
        return None, f"resolver unavailable: {type(exc).__name__}: {exc}"


def split_indicator(ind) -> tuple[str, str | None] | None:
    if not isinstance(ind, str) or not _INDICATOR_RE.match(ind.strip()):
        return None
    ind = ind.strip()
    if "__" in ind:
        axis, metric = ind.split("__", 1)
        return axis, metric
    return ind, None


# ── SCALE: is this a POSSIBLE number for this indicator? (3b, 6 Sep 2026) ────
# A delta that parses is not yet a delta that could happen. WATER_REVIEW +1.2 is
# 1.2 PERCENT OF THE WORLD'S POPULATION gaining safe water; on its own series
# that is either routine or absurd, and until 6 Sep nothing in the system could
# say which, because no history of the indicator existed.
#
# THE SCALE IS A NAMED UNKNOWN, NEVER A DEFAULT. With too few observations the
# proposal is ADMITTED and carries the mark "unverified: N observations, need 7"
# into its own record and the summary line. Inventing a plausible range to judge
# against would be the gate telling itself what it wants to hear - and the
# history only started tonight, so for the first week every proposal is
# unverified and must say so rather than look checked.
MIN_SCALE_OBS = 7
SCALE_MULTIPLE = 2.0


def _default_scale_check(indicator: str, delta) -> tuple:
    """(refusal_or_None, mark_or_None) for one proposal's delta."""
    try:
        from core.axis_history import daily_range
        r = daily_range(indicator)
    except Exception as e:                                       # noqa: BLE001
        return (f"scale: check unavailable ({type(e).__name__}: {e})", None)
    n = r.get("n") or 0
    if n < MIN_SCALE_OBS:
        return (None, f"unverified: {n} observations, need {MIN_SCALE_OBS}")
    rng = r.get("range")
    if rng == 0:
        return (f"no_scale: {indicator} flat over {n} days "
                f"(every observation {r.get('min')})", None)
    if abs(float(delta)) > SCALE_MULTIPLE * rng:
        return (f"scale: delta {delta} exceeds {SCALE_MULTIPLE:g}x the {n}-day "
                f"range {rng:.6g} ({r.get('min'):.6g}..{r.get('max'):.6g})", None)
    return (None, f"verified against {n} observations, range {rng:.6g}")


def _default_cadence_check(indicator: str, deadline: date):
    """The real cadence gate. Injectable for the same reason `resolver` is: a
    test that exercises field validation on a synthetic axis is not making a
    claim about that axis's publication schedule."""
    from core.cadence import deadline_refusal
    return deadline_refusal(indicator, deadline)


def judge(p: dict, today: date | None = None,
          resolver: Callable = _default_resolver,
          cadence_check: Callable = _default_cadence_check,
          scale_check: Callable = _default_scale_check) -> dict:
    """{"verdict": "ADMITTED"} or {"verdict": "REFUSED", "missing": [...], "why": ...}.
    Never raises. Every missing piece is named, not just the first."""
    today = today or date.today()
    missing: list[str] = []
    why: list[str] = []

    if not isinstance(p, dict):
        return {"verdict": "REFUSED", "missing": list(REQUIRED),
                "why": "not a proposal object"}

    # indicator
    parts = split_indicator(p.get("indicator"))
    if parts is None:
        missing.append("indicator")
        why.append("indicator must be AXIS or AXIS__metric (got %r)" % (p.get("indicator"),))
    else:
        value, why_not = resolver(*parts)
        if value is None:
            missing.append("indicator")
            why.append(f"indicator {p['indicator']!r} does not resolve today: {why_not}")

    # expected_delta
    d = p.get("expected_delta")
    if isinstance(d, bool) or not isinstance(d, (int, float)):
        missing.append("expected_delta")
        why.append("expected_delta must be a number (got %r)" % (d,))
    elif d == 0:
        missing.append("expected_delta")
        why.append("expected_delta of 0 predicts nothing")

    # deadline
    dl = p.get("deadline")
    try:
        dl_date = date.fromisoformat(str(dl)[:10])
        days = (dl_date - today).days
        if days <= 0:
            missing.append("deadline")
            why.append(f"deadline {dl_date} is not after today {today}")
        elif days > MAX_HORIZON_DAYS:
            missing.append("deadline")
            why.append(f"deadline {dl_date} is {days} days out; max {MAX_HORIZON_DAYS}")
        else:
            # ── CADENCE (6 Sep 2026, Kimi R35) ───────────────────────────────
            # A deadline only means something if an observation can land inside
            # it. WATER_REVIEW is annual and last observed in 2024; nothing could
            # arrive by 2026-09-10 to settle "+1.2", so the prediction is not
            # wrong, it is unsettleable - and a ledger that scores it scores
            # noise. Refused BY NAME, never silently lengthened or downgraded.
            try:
                # Only when the indicator RESOLVED. An unresolvable indicator is
                # already refused by name above; adding "and its cadence is
                # unknown" names one cause twice and buries the real one.
                _reason = (cadence_check(str(p.get("indicator") or "").split("__")[0],
                                         dl_date)
                           if "indicator" not in missing else None)
            except Exception as _e:                              # noqa: BLE001
                # A cadence layer that cannot answer must say so, not wave the
                # proposal through on silence.
                _reason = f"cadence: check unavailable ({type(_e).__name__}: {_e})"
            if _reason:
                missing.append("deadline")
                why.append(_reason)
    except Exception:
        missing.append("deadline")
        why.append("deadline must be an ISO date (got %r)" % (dl,))

    # SCALE, last: it needs a resolved indicator AND a numeric delta, and it
    # must not add noise to a proposal already refused for either.
    scale_mark = None
    if "indicator" not in missing and "expected_delta" not in missing:
        try:
            _sref, scale_mark = scale_check(
                str(p.get("indicator") or "").split("__")[0], d)
        except Exception as _e:                                  # noqa: BLE001
            _sref, scale_mark = (f"scale: check unavailable "
                                 f"({type(_e).__name__}: {_e})", None)
        if _sref:
            missing.append("expected_delta")
            why.append(_sref)

    if missing:
        return {"verdict": "REFUSED", "missing": missing, "why": "; ".join(why)}
    return {"verdict": "ADMITTED", "missing": [], "why": None,
            "scale_check": scale_mark}


def admit(proposals: list, source: str, today: date | None = None,
          resolver: Callable = _default_resolver,
          cadence_check: Callable = _default_cadence_check,
          scale_check: Callable = _default_scale_check,
          refusals_path: Path | None = None, write: bool = True) -> tuple[list, list]:
    """Split proposals into (admitted, refused). Refused ones are appended to the
    refusal log, one JSON line each, with the source injector named."""
    admitted, refused = [], []
    ts = _now()
    for p in proposals or []:
        v = judge(p, today=today, resolver=resolver,
                  cadence_check=cadence_check, scale_check=scale_check)
        if v["verdict"] == "ADMITTED":
            # The mark travels WITH the proposal: a reader of
            # improvement_proposals.json must be able to see that a delta was
            # admitted without its scale ever being checked.
            if isinstance(p, dict) and v.get("scale_check"):
                p["scale_check"] = v["scale_check"]
            admitted.append(p)
        else:
            refused.append({
                "ts": ts, "source": source,
                "component": p.get("component") if isinstance(p, dict) else None,
                "solution": (str(p.get("solution") or "")[:200]
                             if isinstance(p, dict) else None),
                "missing": v["missing"], "why": v["why"],
            })
    if write and refused:
        path = refusals_path or REFUSALS
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for r in refused:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return admitted, refused


def summary_line(source: str, admitted: list, refused: list) -> str:
    unver = sum(1 for a in admitted
                if isinstance(a, dict)
                and str(a.get("scale_check", "")).startswith("unverified"))
    tail = f"; {unver} with scale UNVERIFIED" if unver else ""
    if not refused:
        return (f"[FAST_CYCLE] {source} -> {len(admitted)} proposals admitted, "
                f"0 refused{tail}")
    from collections import Counter
    c = Counter(m for r in refused for m in r["missing"])
    top = ", ".join(f"{k}:{n}" for k, n in c.most_common())
    return (f"[FAST_CYCLE] {source} -> {len(admitted)} admitted, {len(refused)} REFUSED "
            f"ungradeable (missing {top}){tail}; "
            f"see memory/proposal_intake_refusals.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _selftest() -> int:
    print("core/proposal_intake --selftest")
    print(f"  refusal log           : {'LIVE ' if REFUSALS.is_file() else 'not yet written '}{REFUSALS}")
    for rel, needle in (("fast_cycle_runner.py", "proposal_intake"),):
        q = REPO / rel
        wired = q.is_file() and needle in q.read_text(encoding="utf-8", errors="ignore")
        print(f"  consumer {rel:26s}: {'LIVE' if wired else 'INERT'}")
    old = {"component": "PLANET", "problem": "Action required for PLANET",
           "solution": "Build membrane filters for microplastics",
           "measurable_goal": "Build membrane filters for microplastics"}
    v = judge(old, resolver=lambda a, m: (None, "no such axis"))
    print(f"  legacy fixture        : {v['verdict']} missing={v['missing']} (must be REFUSED)")
    good = {**old, "indicator": "PLANET", "expected_delta": 1.5,
            "deadline": (date.today().replace(year=date.today().year + 1)).isoformat()}
    v = judge(good, resolver=lambda a, m: (0.42, None))
    print(f"  gradeable fixture     : {v['verdict']} (must be ADMITTED)")
    # live: what would the current queue look like through this door?
    q = REPO / "memory" / "improvement_proposals.json"
    if q.is_file():
        try:
            raw = json.loads(q.read_text(encoding="utf-8"))
            items = raw.get("proposals", raw) if isinstance(raw, dict) else raw
            adm, ref = admit(items, "selftest", write=False)
            print(f"  live queue            : {len(items)} in file -> {len(adm)} would be admitted, "
                  f"{len(ref)} refused")
        except Exception as e:
            print(f"  live queue            : unreadable ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else 0)
