# -*- coding: utf-8 -*-
"""
K1b primary metric, second attempt: PAIRED RANKING.

WHY THE FIRST METRIC WAS REPLACED (5 September 2026, 02:40)
-----------------------------------------------------------
Mean per-token NLL of the target answers "how probable is this text?". A model
lowers that on any corpus by learning the TARGET DISTRIBUTION - format,
vocabulary, the house style of a CORTEX proposal. Measured the same night: a
negative control trained on DERANGED pairs, which cannot contain any
problem->solution mapping, improved held-out NLL on novel targets by +1.2204
nats, CI [+1.1117, +1.3285]. The metric could not tell "learned the mapping"
from "learned what a solution looks like around here".

THE REPLACEMENT
    For each holdout example (prompt p, true target t), draw K=9 distractor
    targets from the holdout target pool. Score 1 if t receives the lowest mean
    per-token NLL of the ten. Report accuracy per stratum against
    chance = 1/(K+1) = 0.10.

WHY IT IS INVARIANT TO DISTRIBUTIONAL GAIN
    Every candidate is drawn from the SAME pool of real targets, so a model that
    learned only house style lowers NLL on all ten equally and the ranking does
    not move. Only knowledge of which target belongs to THIS prompt can raise
    accuracy above chance.

NO TORCH HERE, ON PURPOSE
    training/eval_adapter.py imports torch at module level, so its tests are
    INERT under the main suite (venv/ has numpy only). This module is pure and
    takes an `nll_fn(prompt, target) -> float` callback, so every failure mode
    below is testable in the suite that actually runs every night.

PRE-REGISTERED DECISION RULE (fixed 5 Sep 2026, before any run)
    - The CONTROL adapter must score AT CHANCE. If it does not, this metric is
      contaminated too and runs A and B stay unrun. The control is the null
      model, not merely a gate.
    - A or B may claim learning only if its accuracy CI is entirely above 0.10
      AND entirely above the control's accuracy on the SAME examples.
    - NLL stays in the report as a SECONDARY number, explicitly labelled
      "distributional gain, not mapping".
"""
from __future__ import annotations

import hashlib

import numpy as np

K_DISTRACTORS = 9
CHANCE = 1.0 / (K_DISTRACTORS + 1)      # 0.10
MIN_BUCKET = 30
BOOTSTRAP_N = 10000
SEED = 20260905

# Length band for distractor selection, as a fraction of the true target's token
# length. Failure mode 1: per-token NLL still varies systematically with length,
# so an unbanded draw lets the model win by preferring short strings.
LENGTH_BAND = 0.25

# Trailing punctuation stripped by norm(). Failure of the old norm(), proven by
# test on 5 Sep: a single appended full stop made a memorised target read as
# novel and put it in the bucket that IS the verdict.
_TRAILING = ".,;:!?…-–—\"')]}»*"


def norm(text) -> str:
    """Whitespace-collapsed, trailing-punctuation-stripped, casefolded.

    Used for TWO things and they must stay the same function: SEEN/UNSEEN
    classification, and distractor-collision exclusion. If they diverged, a
    distractor could be the true target under one definition and not the other.
    """
    s = " ".join(str(text).split())
    s = s.rstrip(_TRAILING + " ")
    return s.casefold()


def example_id(prompt, target) -> str:
    """A stable id for one holdout example.

    sha256, NOT Python's hash(): hash() is salted per process, so a seed derived
    from it would differ between the base run and the adapter run and failure
    mode 4 (unpaired comparison) would be built straight in.
    """
    h = hashlib.sha256()
    h.update(str(prompt).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(target).encode("utf-8"))
    return h.hexdigest()


def _rng_for(eid: str, seed: int = SEED) -> np.random.Generator:
    return np.random.default_rng((int(eid[:16], 16) ^ seed) & ((1 << 63) - 1))


def build_pool(rows: list, token_len) -> list:
    """The distractor pool: DISTINCT targets under norm(), in a stable order.

    Failure mode 5: the corpus has 744 distinct targets in 1323 rows. Drawing
    from the raw rows would make common boilerplate dominate the distractors,
    which makes the task easy for the wrong reason - the model would only have
    to prefer a rare string over a common one.
    """
    seen: dict = {}
    for r in rows:
        t = r.get("target")
        if not t or not str(t).strip():
            continue
        key = norm(t)
        if key in seen:
            continue
        seen[key] = {"target": str(t), "norm": key, "len": int(token_len(str(t)))}
    return [seen[k] for k in sorted(seen)]


def draw_distractors(eid: str, target, tlen: int, pool: list,
                     k: int = K_DISTRACTORS, band: float | None = LENGTH_BAND,
                     seed: int = SEED) -> tuple:
    """(distractor targets, widened) - deterministic in `eid` alone.

    Determinism in eid and nothing else is what makes the comparison PAIRED: the
    base run and the adapter run see identical distractor sets because neither
    the model nor the call order enters the seed.

    `band=None` is the deliberately UNMATCHED variant. It is not a fallback - it
    is reported alongside the banded number so the length-bias gap is visible
    instead of being an assumption.

    Returns (None, widened) when the pool cannot supply k distractors. The caller
    must report that count; an unscorable item is not a zero.
    """
    tnorm = norm(target)
    cands = [p for p in pool if p["norm"] != tnorm]
    widened = False
    if band is not None:
        lo, hi = tlen * (1.0 - band), tlen * (1.0 + band)
        banded = [p for p in cands if lo <= p["len"] <= hi]
        if len(banded) >= k:
            cands = banded
        else:
            widened = True          # recorded, never silent
    if len(cands) < k:
        return None, widened
    rng = _rng_for(eid, seed)
    idx = rng.choice(len(cands), size=k, replace=False)
    return [cands[int(i)]["target"] for i in sorted(idx)], widened


def hit(true_nll: float, distractor_nlls) -> int:
    """1 only if the true target is STRICTLY lowest.

    A tie scores 0. Ties are not evidence of knowing the answer, and scoring
    them as hits would inflate accuracy exactly where the model is indifferent.
    """
    return 1 if all(true_nll < d for d in distractor_nlls) else 0


def score_example(nll_fn, prompt, target, distractors) -> int:
    """One item, through the caller's NLL function. The true target is scored
    FIRST so a stateful nll_fn cannot be primed by the distractors."""
    t = nll_fn(prompt, target)
    ds = [nll_fn(prompt, d) for d in distractors]
    return hit(t, ds)


def accuracy_ci(hits, n_boot: int = BOOTSTRAP_N, seed: int = SEED) -> tuple:
    """(accuracy, (lo, hi)) - or (accuracy, None) when the bucket is too small."""
    arr = np.asarray(list(hits), dtype=float)
    if len(arr) < MIN_BUCKET:
        return (float(arr.mean()) if len(arr) else float("nan")), None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(arr.mean()), (float(np.percentile(means, 2.5)),
                               float(np.percentile(means, 97.5)))


def rank_verdict(hits) -> tuple:
    """(verdict, accuracy, ci). AT CHANCE is a real answer, not a failure."""
    acc, ci = accuracy_ci(hits)
    if ci is None:
        return f"UNRESOLVABLE (n<{MIN_BUCKET})", acc, None
    if ci[0] > CHANCE:
        return "ABOVE CHANCE", acc, ci
    if ci[1] < CHANCE:
        return "BELOW CHANCE", acc, ci
    return "AT CHANCE", acc, ci


def beats_control(hits, control_hits) -> tuple:
    """The pre-registered second condition: entirely above 0.10 AND entirely
    above the control on the same examples. Returns (bool, why)."""
    v, acc, ci = rank_verdict(hits)
    cv, cacc, cci = rank_verdict(control_hits)
    if ci is None or cci is None:
        return False, f"UNRESOLVABLE: n={len(list(hits))} control n={len(list(control_hits))}"
    if ci[0] <= CHANCE:
        return False, f"CI lo {ci[0]:.4f} does not clear chance {CHANCE:.2f}"
    if ci[0] <= cci[1]:
        return False, (f"CI lo {ci[0]:.4f} overlaps the control's CI hi {cci[1]:.4f} — "
                       f"not distinguishable from the null model")
    return True, f"acc {acc:.4f} CI [{ci[0]:.4f}, {ci[1]:.4f}] vs control {cacc:.4f}"
