#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/merit.py — WHAT WAS CLAIMED, WHAT HAPPENED, AND WHAT COULD EARN A WEIGHT.

24 Aug 2026. This is not the training run. It is the thing without which a
training run is guaranteed to be harmful.

If a LoRA were available tomorrow it would be trained on this system's own
outputs — the same loop that taught it Russian one cycle at a time, except
written into weights and no longer reversible by deleting a file. AMENDMENT_001
set the two conditions: THE EXAM IS NOT WRITTEN BY THE STUDENT, and THE PREVIOUS
WEIGHTS SURVIVE. This module builds the record that makes the first one
checkable.

IT WRAPS WHAT EXISTS. IT DOES NOT REPLACE IT.
-----------------------------------------------
Part 0.7 found two records that already pair a claim with a later outcome, and
building a third beside them is the drift this repo keeps paying for. Both are
adapted here rather than duplicated:

  experiments/prophecy/prophecy_ledger.jsonl   541 sealed, 471 scored,
      hash-chained, every ref_hash resolving inside the same file. A model
      claim? NO — the learner is `trend`, `persistence`, `damped`, a
      statistical extrapolation. Excellent evidence, wrong claimant.

  memory/divergence_log.jsonl                  861 rows carrying prev_promise,
      which IS a model's claim about what a step would do, paired against
      `observed`, which is a file-touch audit measured from disk by
      core/metta_check.py. Model claims the exam did not write.

THE FOUR STATES
-----------------
  OPEN            a claim was made and its check is not in yet
  CLOSED          an observation arrived and a verdict was reached
  SELF_EXAMINED   the claim and its check came from ONE generation. Permanently
                  ineligible whatever the outcome — a student marking their own
                  paper produces a number, not evidence.
  ELIGIBLE        all four of: the claimant was a MODEL; the observation was
                  not produced by that model; the verdict was correct; and the
                  pairing is reconstructable from the record alone.

ONLY A MODEL CLAIM CAN EARN A WEIGHT. A statistical learner beating a naive
baseline 30 times is a fact about arithmetic, and no gradient descends from it.
That is why the prophecy rows import as CLOSED and never as ELIGIBLE, and it is
the honest answer to "how many would be eligible today".

NOTHING IS EVER DELETED. Wrong predictions stay, and they are the more valuable
half: a record that keeps only the hits is a record that teaches overconfidence.

    venv/Scripts/python.exe core/merit.py --report
    venv/Scripts/python.exe core/merit.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LEDGER = BASE / "memory" / "merit_ledger.jsonl"
PROPHECY = BASE / "experiments" / "prophecy" / "prophecy_ledger.jsonl"
DIVERGENCE = BASE / "memory" / "divergence_log.jsonl"

OPEN, CLOSED = "OPEN", "CLOSED"
SELF_EXAMINED, ELIGIBLE = "SELF_EXAMINED", "ELIGIBLE"

CLAIMANT_MODEL, CLAIMANT_CODE = "model", "code"
OBSERVER_MODEL, OBSERVER_CODE, OBSERVER_HUMAN = "model", "code", "human"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _cid(*parts) -> str:
    return hashlib.sha256("::".join(str(p) for p in parts).encode("utf-8")
                          ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def open_claim(claim, how_checked: str, claimant: str = CLAIMANT_MODEL,
               model=None, step=None, generation_id=None, claim_id=None,
               path=None, **extra) -> dict:
    """Record an expectation about something that will later be observable.

    `how_checked` is not optional and not decoration: a claim whose test is
    decided after the outcome is known is a claim that cannot fail.
    `generation_id` identifies the model call that produced it — the whole
    SELF_EXAMINED check hangs on comparing it to the closing one.
    """
    if not str(how_checked or "").strip():
        raise ValueError("how_checked is required: a claim with no stated test "
                         "cannot be wrong, and a claim that cannot be wrong "
                         "cannot earn anything")
    rec = {
        "entry": OPEN,
        "claim_id": claim_id or _cid(claim, step, _now()),
        "ts": _now(),
        "claim": claim,
        "how_checked": how_checked,
        "claimant": claimant,
        "model": model,
        "step": step,
        "generation_id": generation_id,
        **extra,
    }
    _append(rec, path)
    return rec


def close_claim(claim_id: str, actual, correct: Optional[bool],
                observer: str = OBSERVER_CODE, generation_id=None,
                path=None, **extra) -> dict:
    """Pair an observation to a claim. Verdicts are mechanical where possible."""
    rec = {
        "entry": CLOSED,
        "claim_id": claim_id,
        "ts": _now(),
        "actual": actual,
        "correct": None if correct is None else bool(correct),
        "observer": observer,
        "generation_id": generation_id,
        **extra,
    }
    _append(rec, path)
    return rec


def _append(rec: dict, path=None) -> bool:
    from core.durable import append_json
    return append_json(pathlib.Path(path or LEDGER), rec)


# ---------------------------------------------------------------------------
# Reading and judging
# ---------------------------------------------------------------------------

def read(path=None) -> list:
    try:
        return [json.loads(l) for l in
                pathlib.Path(path or LEDGER).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def verdict(opened: dict, closed: Optional[dict]) -> tuple:
    """(state, why). The whole judgement, from the two records alone."""
    if closed is None:
        return OPEN, "no observation has arrived yet"

    same_gen = (opened.get("generation_id") is not None
                and opened.get("generation_id") == closed.get("generation_id"))
    if same_gen or closed.get("observer") == OBSERVER_MODEL and same_gen:
        return SELF_EXAMINED, (
            "the claim and its check came from one generation ({}) — a student "
            "marking their own paper".format(opened.get("generation_id")))

    if closed.get("observer") == OBSERVER_MODEL:
        return SELF_EXAMINED, (
            "the observation was produced by a model, not measured")

    if opened.get("claimant") != CLAIMANT_MODEL:
        return CLOSED, (
            "the claimant was {!r}, not a model — no gradient descends from a "
            "statistical learner beating a baseline".format(
                opened.get("claimant")))

    if closed.get("correct") is None:
        return CLOSED, "closed, but no mechanical verdict was reached"
    if not closed.get("correct"):
        return CLOSED, "closed and wrong — kept, and the more valuable half"

    return ELIGIBLE, (
        "a model claim, closed by an observation it did not produce, correct, "
        "and reconstructable from this record alone")


def pair(rows: list) -> list:
    """Every claim with its closing record, judged. Reconstructable from the
    ledger alone — that is one of the ELIGIBLE conditions, so it is how the
    pairing is done rather than by any outside index."""
    opens = {r["claim_id"]: r for r in rows if r.get("entry") == OPEN}
    closes = {}
    for r in rows:
        if r.get("entry") == CLOSED and r.get("claim_id") in opens:
            closes[r["claim_id"]] = r          # last close wins
    out = []
    for cid, o in opens.items():
        c = closes.get(cid)
        state, why = verdict(o, c)
        out.append({"claim_id": cid, "state": state, "why": why,
                    "opened": o, "closed": c})
    return out


def summary(rows=None, path=None, days: Optional[int] = None) -> dict:
    rows = rows if rows is not None else read(path)
    pairs = pair(rows)
    if days is not None and pairs:
        stamps = [_parse(p["opened"].get("ts")) for p in pairs]
        newest = max([s for s in stamps if s] or [None])
        if newest:
            cut = newest - timedelta(days=days)
            pairs = [p for p in pairs
                     if (_parse(p["opened"].get("ts")) or newest) >= cut]
    counts = {}
    for p in pairs:
        counts[p["state"]] = counts.get(p["state"], 0) + 1
    return {"entries": len(rows), "claims": len(pairs), "states": counts,
            "eligible": counts.get(ELIGIBLE, 0)}


# ---------------------------------------------------------------------------
# Adapters — the two records that already exist
# ---------------------------------------------------------------------------

def from_prophecy(path=None, days: Optional[int] = 30) -> list:
    """prophecy_ledger.jsonl as merit pairs. CLAIMANT IS CODE, always.

    The learner is `trend`, `persistence` or `damped` — a statistical
    extrapolation. The evidence is excellent and the pairing is airtight; the
    claimant is simply not a model, so none of it can earn a weight.
    """
    try:
        rows = [json.loads(l) for l in
                pathlib.Path(path or PROPHECY).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []
    sealed = {r.get("hash"): r for r in rows
              if r.get("event") == "PREDICTION_SEALED"}
    out = []
    scored = [r for r in rows if r.get("event") == "OUTCOME_SCORED"]
    newest = max([_parse(r.get("ts")) for r in rows
                  if _parse(r.get("ts"))] or [None])
    for r in scored:
        if days is not None and newest:
            t = _parse(r.get("ts"))
            if t and t < newest - timedelta(days=days):
                continue
        s = sealed.get(r.get("ref_hash"))
        cid = _cid("prophecy", r.get("ref_hash"))
        o = {"entry": OPEN, "claim_id": cid, "ts": (s or r).get("ts"),
             "claim": (s or {}).get("learner"),
             "how_checked": (s or {}).get("basis", "learner vs baseline error"),
             "claimant": CLAIMANT_CODE,
             "model": (s or {}).get("model"),
             "step": (s or {}).get("target_kind") or r.get("target_kind"),
             "generation_id": None, "source": "prophecy_ledger"}
        c = {"entry": CLOSED, "claim_id": cid, "ts": r.get("ts"),
             "actual": r.get("actual"),
             "correct": r.get("learner_wins"),
             "observer": OBSERVER_CODE, "generation_id": None,
             "source": "prophecy_ledger"}
        out.append(o)
        out.append(c)
    return out


def from_divergence(path=None, days: Optional[int] = 30) -> list:
    """divergence_log.jsonl as merit pairs. CLAIMANT IS THE MODEL.

    `prev_promise` is what the brain said a step would do. `observed` is what
    core/metta_check.py measured on disk afterwards. `brain_prev_ok` is the
    mechanical verdict. The exam was not written by the student: the file-touch
    audit is code and does not consult the promise.
    """
    try:
        rows = [json.loads(l) for l in
                pathlib.Path(path or DIVERGENCE).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []
    newest = max([_parse(r.get("ts")) for r in rows
                  if _parse(r.get("ts"))] or [None])
    out = []
    for i, r in enumerate(rows):
        if not r.get("prev_promise"):
            continue
        if days is not None and newest:
            t = _parse(r.get("ts"))
            if t and t < newest - timedelta(days=days):
                continue
        if r.get("observed") is None or r.get("brain_prev_ok") is None:
            continue
        cid = _cid("divergence", r.get("ts"), r.get("prev_step"), i)
        out.append({"entry": OPEN, "claim_id": cid, "ts": r.get("ts"),
                    "claim": r.get("prev_promise"),
                    "how_checked": ("core/metta_check.py measures which files "
                                    "the step actually touched on disk"),
                    "claimant": CLAIMANT_MODEL,
                    "model": r.get("model"),
                    "step": r.get("prev_step"),
                    # The promise and the audit are different generations by
                    # construction: the audit is not a generation at all.
                    "generation_id": "brain::{}".format(r.get("prev_step")),
                    "source": "divergence_log"})
        out.append({"entry": CLOSED, "claim_id": cid, "ts": r.get("ts"),
                    "actual": r.get("observed"),
                    "correct": bool(r.get("brain_prev_ok")),
                    "observer": OBSERVER_CODE,
                    "generation_id": None,
                    "divergence": r.get("divergence"),
                    "source": "divergence_log"})
    return out


def would_be_eligible(days: int = 30) -> dict:
    """The report's headline: how many entries would be ELIGIBLE today."""
    proph = from_prophecy(days=days)
    diver = from_divergence(days=days)
    out = {"days": days,
           "prophecy": summary(proph),
           "divergence": summary(diver),
           "combined": summary(proph + diver)}
    out["eligible_total"] = out["combined"]["eligible"]
    return out


# ---------------------------------------------------------------------------

def _report() -> int:
    print("core/merit.py — READ ONLY. Nothing is written.\n")
    w = would_be_eligible(30)
    for name in ("prophecy", "divergence"):
        s = w[name]
        print("  {:<12} {:>4} claims   {}".format(
            name, s["claims"], dict(sorted(s["states"].items()))))
    print("\n  ELIGIBLE over the last {} days: {}".format(
        w["days"], w["eligible_total"]))
    print("\n  own ledger: {}".format(summary()))
    return 0


def _selftest() -> int:
    import tempfile
    print("core/merit.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    p = pathlib.Path(tempfile.mkdtemp()) / "merit.jsonl"

    # a claim closed by its OWN generation
    a = open_claim("ram will fall", how_checked="read ram_percent after",
                   model="qwen2.5:3b", step="s1", generation_id="gen-1", path=p)
    close_claim(a["claim_id"], actual=1, correct=True, observer=OBSERVER_CODE,
                generation_id="gen-1", path=p)

    # a claim closed by an EXTERNAL observation, correct
    b = open_claim("disk will not fall below 60", how_checked="shutil.disk_usage",
                   model="qwen2.5:3b", step="s2", generation_id="gen-2", path=p)
    close_claim(b["claim_id"], actual=65.5, correct=True,
                observer=OBSERVER_CODE, generation_id=None, path=p)

    # external, wrong
    c = open_claim("cpu will spike", how_checked="cpu_percent", model="m",
                   step="s3", generation_id="gen-3", path=p)
    close_claim(c["claim_id"], actual=6.0, correct=False,
                observer=OBSERVER_CODE, path=p)

    # still open
    d = open_claim("tomorrow will finish", how_checked="the ledger",
                   model="m", step="s4", generation_id="gen-4", path=p)

    st = {x["claim_id"]: x["state"] for x in pair(read(p))}
    check("a claim closed by its own generation is SELF_EXAMINED",
          st[a["claim_id"]] == SELF_EXAMINED)
    check("and is never ELIGIBLE", st[a["claim_id"]] != ELIGIBLE)
    check("a model claim closed externally and correct is ELIGIBLE",
          st[b["claim_id"]] == ELIGIBLE)
    check("a wrong one is CLOSED, and kept", st[c["claim_id"]] == CLOSED)
    check("an unclosed one is OPEN", st[d["claim_id"]] == OPEN)

    before = p.read_bytes()
    read(p); pair(read(p)); summary(path=p)
    check("the ledger is byte-identical after a read", p.read_bytes() == before)

    try:
        open_claim("x", how_checked="", path=p)
        check("a claim with no stated test is refused", False)
    except ValueError:
        check("a claim with no stated test is refused", True)

    e = open_claim("y", how_checked="z", claimant=CLAIMANT_CODE, path=p)
    close_claim(e["claim_id"], actual=1, correct=True, path=p)
    st = {x["claim_id"]: x["state"] for x in pair(read(p))}
    check("a CODE claim is never ELIGIBLE however right it was",
          st[e["claim_id"]] == CLOSED)

    f = open_claim("w", how_checked="z", model="m", generation_id="g", path=p)
    close_claim(f["claim_id"], actual=1, correct=True,
                observer=OBSERVER_MODEL, path=p)
    st = {x["claim_id"]: x["state"] for x in pair(read(p))}
    check("an observation a model produced is SELF_EXAMINED",
          st[f["claim_id"]] == SELF_EXAMINED)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    raise SystemExit(_report())
